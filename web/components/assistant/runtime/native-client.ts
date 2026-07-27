import {
  Client,
  MessageAssembler,
  type AssembledMessage,
  type ThreadState,
  type ThreadStream,
} from "@langchain/langgraph-sdk"
import type {
  Event,
  InputEvent,
  LifecycleEvent,
} from "@langchain/protocol"
import type {
  LangChainMessage,
  LangChainToolCall,
  LangChainToolCallChunk,
  LangGraphInterruptState,
  LangGraphMessagesEvent,
  LangGraphStreamCallback,
} from "@assistant-ui/react-langgraph"

import {
  AgentLifecycleError,
  sanitizeAgentError,
} from "./error-state"
import {
  AgentTokenBroker,
  type AgentCancellationSnapshot,
} from "./token-broker"
import {
  InspectionProjector,
  sourcesFromContent,
  type AgentActivity,
} from "./inspection"
import { projectInterruptForUi } from "./interrupt-projection"

const TERMINAL_RUN_STATUSES = new Set([
  "success",
  "error",
  "timeout",
  "interrupted",
])
const TERMINAL_WAIT_MS = 2_000
const TERMINAL_POLL_MS = 100
const DISPOSE_WAIT_MS = TERMINAL_WAIT_MS + 500
const MAX_STATE_MESSAGES = 500
const MAX_STATE_CONTENT_BLOCKS = 256
const MAX_STATE_TEXT_CODE_UNITS = 100_000
const MAX_STATE_MESSAGE_ID_CODE_UNITS = 256
const SAFE_STATE_MESSAGE_ID = /^[A-Za-z0-9][A-Za-z0-9._:@/-]*$/

export type { AgentActivity } from "./inspection"

export interface PendingInterrupt {
  interruptId: string
  namespace: string[]
  value: unknown
  resumable: boolean
  when: string
}

interface NativeAgentClientOptions {
  apiUrl: string
  assistantId: string
  identity: string
  tokenBroker?: AgentTokenBroker
  client?: Client
  onActivity?: (activity: AgentActivity) => void
  onError?: (error: Error) => void
}

interface ActiveNativeStream {
  cancellationSnapshot?: AgentCancellationSnapshot
  completion: Promise<void>
  controller: AbortController
  settle: () => void
  stream?: ThreadStream
}

const nativeClientInspectionReaders = new WeakMap<
  NativeAgentClient,
  () => {
    activeStreams: number
    disposed: boolean
    pendingInterrupts: number
  }
>()

type ProtocolStreamEvent = Extract<
  Event,
  {
    method:
      | "messages"
      | "lifecycle"
      | "input.requested"
      | "tools"
      | "custom"
  }
>
type ProtocolMessagesEvent = Extract<Event, { method: "messages" }>
type MessageAssemblyUpdate = NonNullable<
  ReturnType<MessageAssembler["consume"]>
>

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value)

function parseJsonObject(value: unknown): LangChainToolCall["args"] {
  if (isRecord(value)) return value as LangChainToolCall["args"]
  if (typeof value !== "string" || value.trim() === "") return {}
  try {
    const parsed = JSON.parse(value) as unknown
    return isRecord(parsed) ? (parsed as LangChainToolCall["args"]) : {}
  } catch {
    return {}
  }
}

function unknownBlockLabel(block: Record<string, unknown>): string {
  const type =
    typeof block.type === "string" && block.type.trim()
      ? block.type.trim()
      : "unknown"
  return `[지원하지 않는 콘텐츠: ${type}]`
}

function boundedStateText(value: unknown): string | undefined {
  return typeof value === "string" &&
    value.length <= MAX_STATE_TEXT_CODE_UNITS &&
    !value.includes("\0")
    ? value
    : undefined
}

function visibleStateContent(
  content: unknown
): Array<{ type: "text"; text: string }> | undefined {
  const direct = boundedStateText(content)
  if (direct !== undefined) return [{ type: "text", text: direct }]
  if (
    !Array.isArray(content) ||
    content.length > MAX_STATE_CONTENT_BLOCKS
  ) {
    return undefined
  }

  const result: Array<{ type: "text"; text: string }> = []
  for (const part of content) {
    if (typeof part === "string") {
      const text = boundedStateText(part)
      if (text === undefined) return undefined
      result.push({ type: "text", text })
      continue
    }
    if (!isRecord(part)) continue
    if (
      (part.type === "text" || part.type === "text_delta") &&
      boundedStateText(part.text) !== undefined
    ) {
      result.push({ type: "text", text: part.text as string })
      continue
    }
    // Durable reconciliation returns only user-visible text. Reasoning,
    // thinking, tool, data, and future blocks are excluded from UI state;
    // this local projection does not claim they never reached the browser.
  }
  return result
}

export function normalizeStateMessages(value: unknown): LangChainMessage[] {
  if (!Array.isArray(value) || value.length > MAX_STATE_MESSAGES) return []

  return value.flatMap((candidate, index): LangChainMessage[] => {
    if (!isRecord(candidate)) return []
    const rawType = candidate.type ?? candidate.role
    const type =
      rawType === "user"
        ? "human"
        : rawType === "assistant"
          ? "ai"
          : rawType
    const id =
      typeof candidate.id === "string" &&
      candidate.id.length <= MAX_STATE_MESSAGE_ID_CODE_UNITS &&
      SAFE_STATE_MESSAGE_ID.test(candidate.id)
        ? candidate.id
        : `checkpoint-message-${index}`
    const content = visibleStateContent(candidate.content)
    if (!content || content.length === 0) return []
    if (type === "human") {
      return [
        {
          id,
          type: "human",
          content,
        },
      ]
    }
    if (type !== "ai") return []

    const sources = sourcesFromContent(candidate.content)
    return [
      {
        id,
        type: "ai",
        content,
        ...(sources.length > 0
          ? {
              additional_kwargs: {
                metadata: { sources },
              },
            }
          : {}),
      },
    ]
  })
}

export function projectRootValuesEvent(
  event: Extract<Event, { method: "values" }>
): LangGraphMessagesEvent<LangChainMessage> | undefined {
  if (
    event.params.namespace.length !== 0 ||
    !isRecord(event.params.data) ||
    !Array.isArray(event.params.data.messages)
  ) {
    return undefined
  }
  return {
    event: "values",
    data: {
      messages: normalizeStateMessages(event.params.data.messages),
    },
  }
}

function assembledMessageToLangChain(
  message: AssembledMessage,
  role: "ai" | "human" | "system"
): LangChainMessage {
  const content: Array<
    | { type: "text"; text: string }
    | { type: "reasoning"; reasoning: string }
  > = []
  const toolCalls: LangChainToolCall[] = []
  const toolCallChunks: LangChainToolCallChunk[] = []
  const sources = sourcesFromContent(message.blocks)

  message.blocks.forEach((rawBlock, index) => {
    const block = rawBlock as Record<string, unknown>
    if (block.type === "text" && typeof block.text === "string") {
      content.push({ type: "text", text: block.text })
      return
    }
    if (block.type === "reasoning" && typeof block.reasoning === "string") {
      // Preserve the semantic part/status without retaining model reasoning.
      content.push({ type: "reasoning", reasoning: "" })
      return
    }
    if (block.type === "tool_call" || block.type === "tool_call_chunk") {
      const id =
        typeof block.id === "string" && block.id
          ? block.id
          : `${message.id}-tool-${index}`
      const name =
        typeof block.name === "string" && block.name
          ? block.name
          : "unknown_tool"
      const partialJson =
        typeof block.args === "string"
          ? block.args
          : JSON.stringify(parseJsonObject(block.args))
      toolCalls.push({
        index,
        id,
        name,
        args: parseJsonObject(block.args),
        partial_json: partialJson,
      })
      toolCallChunks.push({
        index,
        id,
        name,
        args: partialJson,
      })
      return
    }
    content.push({ type: "text", text: unknownBlockLabel(block) })
  })

  if (role === "system") {
    return {
      id: message.id,
      type: "system",
      content: content.map((part) =>
        "text" in part ? part.text : part.reasoning
      ).join("\n"),
    }
  }
  if (role === "human") {
    return {
      id: message.id,
      type: "human",
      content: content.map((part) =>
        "reasoning" in part
          ? { type: "text" as const, text: part.reasoning }
          : part
      ),
    }
  }
  return {
    id: message.id,
    type: "ai",
    content,
    ...(toolCalls.length > 0 ? { tool_calls: toolCalls } : {}),
    ...(toolCallChunks.length > 0 ? { tool_call_chunks: toolCallChunks } : {}),
    ...(sources.length > 0
      ? {
          additional_kwargs: {
            metadata: { sources },
          },
        }
      : {}),
    ...(message.error
      ? {
          status: {
            type: "incomplete" as const,
            reason: "error" as const,
            error: message.error.message,
          },
        }
      : {}),
  }
}

/**
 * Uses the SDK's MessageAssembler as the sole APv2 content-block reducer.
 * The only local work is converting its assembled projection into the
 * message shape consumed by @assistant-ui/react-langgraph.
 */
export class NativeMessageProjection {
  readonly #assembler = new MessageAssembler()
  readonly #roles = new Map<string, "ai" | "human" | "drop">()

  consume(
    event: ProtocolMessagesEvent
  ): LangGraphMessagesEvent<LangChainMessage> | undefined {
    const update = this.#assembler.consume(event)
    if (!update) return undefined
    const role = this.#resolveRole(update)
    if (role === "drop") {
      if (update.kind === "message-finish" || update.kind === "message-error") {
        this.#roles.delete(update.key)
      }
      return undefined
    }
    const message = assembledMessageToLangChain(update.message, role)
    if (update.kind === "message-finish" || update.kind === "message-error") {
      this.#roles.delete(update.key)
    }
    return {
      event:
        update.kind === "message-finish" || update.kind === "message-error"
          ? "messages/complete"
          : "messages/partial",
      data: [message],
    }
  }

  #resolveRole(
    update: MessageAssemblyUpdate
  ): "ai" | "human" | "drop" {
    if (update.kind === "message-start") {
      const role = update.event.params.data.role
      const normalized =
        role === "human" ? role : role === "ai" ? role : ("drop" as const)
      this.#roles.set(update.key, normalized)
      return normalized
    }
    return this.#roles.get(update.key) ?? "ai"
  }
}

function pendingFromInputEvent(event: InputEvent): PendingInterrupt {
  const data = event.params.data as typeof event.params.data & {
    value?: unknown
  }
  return {
    interruptId: data.interrupt_id,
    namespace: [...event.params.namespace],
    value: data.payload ?? data.value,
    resumable: true,
    when: "during",
  }
}

export function projectPendingInterruptForRuntime(
  pending: PendingInterrupt
): LangGraphInterruptState {
  return {
    value: projectInterruptForUi(pending.value),
    resumable: pending.resumable,
    when: pending.when,
    ns: pending.namespace,
  }
}

export function projectInputEventForRuntime(
  event: InputEvent
): LangGraphInterruptState {
  return projectPendingInterruptForRuntime(pendingFromInputEvent(event))
}

function normalizeInterruptCandidates(value: unknown): unknown[] {
  if (Array.isArray(value)) return value
  if (!isRecord(value)) return []
  return Object.values(value).flatMap((entry) =>
    Array.isArray(entry) ? entry : []
  )
}

export function extractPendingInterrupt(
  state: ThreadState<Record<string, unknown>> & {
    interrupts?: unknown
  }
): PendingInterrupt | undefined {
  const topLevel = normalizeInterruptCandidates(state.interrupts)
  const candidates =
    topLevel.length > 0
      ? topLevel
      : (state.tasks ?? []).flatMap((task) => task.interrupts ?? [])
  if (candidates.length === 0) return undefined
  if (candidates.length > 1) {
    throw new Error(
      "동시에 여러 승인 요청이 도착했습니다. 안전하게 재개할 수 없어 중단했습니다."
    )
  }

  const candidate = candidates[0]
  if (!isRecord(candidate)) {
    throw new Error("승인 요청 형식을 읽을 수 없습니다.")
  }
  const interruptId =
    typeof candidate.interrupt_id === "string"
      ? candidate.interrupt_id
      : typeof candidate.id === "string"
        ? candidate.id
        : undefined
  if (!interruptId) {
    throw new Error("승인 요청 식별자가 없습니다.")
  }
  return {
    interruptId,
    namespace: Array.isArray(candidate.ns)
      ? candidate.ns.filter((part): part is string => typeof part === "string")
      : [],
    value: candidate.value ?? candidate.payload,
    resumable: candidate.resumable !== false,
    when: typeof candidate.when === "string" ? candidate.when : "during",
  }
}

function safeLifecycleError(event: LifecycleEvent): string {
  void event
  return "에이전트 실행을 완료하지 못했습니다."
}

function toRunMessages(messages: LangChainMessage[]) {
  return messages.map((message) => ({
    role:
      message.type === "human"
        ? "user"
        : message.type === "ai"
          ? "assistant"
          : message.type,
    content: message.content,
    id: message.id,
    ...(message.type === "tool"
      ? {
          name: message.name,
          tool_call_id: message.tool_call_id,
        }
      : {}),
  }))
}

function timeoutController(milliseconds: number): {
  controller: AbortController
  clear: () => void
} {
  const controller = new AbortController()
  const timer = setTimeout(
    () =>
      controller.abort(
        new DOMException("Terminal run wait timed out", "TimeoutError")
      ),
    milliseconds
  )
  return { controller, clear: () => clearTimeout(timer) }
}

function createActiveStream(): ActiveNativeStream {
  let settled = false
  let resolveCompletion: (() => void) | undefined
  const completion = new Promise<void>((resolve) => {
    resolveCompletion = resolve
  })
  return {
    completion,
    controller: new AbortController(),
    settle: () => {
      if (settled) return
      settled = true
      resolveCompletion?.()
    },
  }
}

function closeThreadBestEffort(stream: ThreadStream | undefined): void {
  if (!stream) return
  void stream.close().catch(() => undefined)
}

async function waitForActiveStreams(
  activeStreams: readonly ActiveNativeStream[]
): Promise<void> {
  if (activeStreams.length === 0) return
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    await Promise.race([
      Promise.all(activeStreams.map((active) => active.completion)),
      new Promise<void>((resolve) => {
        timer = setTimeout(resolve, DISPOSE_WAIT_MS)
      }),
    ])
  } finally {
    if (timer !== undefined) clearTimeout(timer)
  }
}

export async function cancelRunAndWait(
  client: Pick<Client, "runs">,
  threadId: string,
  runId: string
): Promise<void> {
  const bounded = timeoutController(TERMINAL_WAIT_MS)
  try {
    // Exactly one cancellation request. Polling below is read-only.
    await client.runs.cancel(threadId, runId, false, "interrupt", {
      signal: bounded.controller.signal,
    })
    while (!bounded.controller.signal.aborted) {
      const run = await client.runs.get(threadId, runId, {
        signal: bounded.controller.signal,
      })
      if (TERMINAL_RUN_STATUSES.has(run.status)) return
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(resolve, TERMINAL_POLL_MS)
        bounded.controller.signal.addEventListener(
          "abort",
          () => {
            clearTimeout(timer)
            reject(bounded.controller.signal.reason)
          },
          { once: true }
        )
      })
    }
  } catch (error) {
    if (
      !(error instanceof DOMException) ||
      (error.name !== "AbortError" && error.name !== "TimeoutError")
    ) {
      throw error
    }
  } finally {
    bounded.clear()
  }
}

async function resolveActiveRunId(
  client: Pick<Client, "runs">,
  threadId: string,
  signal: AbortSignal
): Promise<string | undefined> {
  const runs = await client.runs.list(threadId, {
    limit: 10,
    signal,
  })
  return runs.find(
    (run) => run.status === "pending" || run.status === "running"
  )?.run_id
}

function isRootTerminal(event: LifecycleEvent): boolean {
  return (
    event.params.namespace.length === 0 &&
    (event.params.data.event === "completed" ||
      event.params.data.event === "failed" ||
      event.params.data.event === "interrupted")
  )
}

export class NativeAgentClient {
  readonly client: Client
  readonly tokenBroker: AgentTokenBroker
  readonly assistantId: string
  readonly #apiUrl: string
  readonly #onActivity?: (activity: AgentActivity) => void
  readonly #onError?: (error: Error) => void
  readonly #pendingInterrupts = new Map<string, PendingInterrupt>()
  readonly #activeStreams = new Set<ActiveNativeStream>()
  #disposed = false
  #disposePromise?: Promise<void>

  constructor(options: NativeAgentClientOptions) {
    this.#apiUrl = options.apiUrl
    this.assistantId = options.assistantId
    this.#onActivity = options.onActivity
    this.#onError = options.onError
    this.tokenBroker =
      options.tokenBroker ??
      new AgentTokenBroker(options.identity)
    this.client =
      options.client ??
      new Client({
        apiUrl: options.apiUrl,
        apiKey: null,
        streamProtocol: "v2",
        onRequest: (url, init) => this.tokenBroker.onRequest(url, init),
        callerOptions: {
          fetch: this.tokenBroker.fetchWithAuthRetry as typeof fetch,
          maxRetries: 0,
        },
      })
    nativeClientInspectionReaders.set(this, () => ({
      activeStreams: this.#activeStreams.size,
      disposed: this.#disposed,
      pendingInterrupts: this.#pendingInterrupts.size,
    }))
  }

  dispose(): Promise<void> {
    if (this.#disposePromise) return this.#disposePromise
    this.#disposed = true
    // Seal immediately so no old runtime request can mint, refresh, or attach
    // a credential. A stream-start snapshot remains usable only for its
    // already-bound cancellation target.
    this.tokenBroker.seal()
    this.#pendingInterrupts.clear()
    const activeStreams = [...this.#activeStreams]
    let resolveDispose: (() => void) | undefined
    let rejectDispose: ((error: unknown) => void) | undefined
    this.#disposePromise = new Promise<void>((resolve, reject) => {
      resolveDispose = resolve
      rejectDispose = reject
    })
    for (const active of activeStreams) {
      active.controller.abort(
        new DOMException("Agent identity changed", "AbortError")
      )
      closeThreadBestEffort(active.stream)
    }
    void (async () => {
      await waitForActiveStreams(activeStreams)
      // A hung stream cannot retain bearer material beyond the bounded wait.
      // On the normal path, stream.finally has already disposed each snapshot.
      for (const active of activeStreams) {
        active.cancellationSnapshot?.dispose()
      }
      this.tokenBroker.clear()
      for (const active of activeStreams) {
        this.#activeStreams.delete(active)
      }
    })().then(resolveDispose, rejectDispose)
    return this.#disposePromise
  }

  setPendingInterrupt(
    threadId: string,
    pending: PendingInterrupt | undefined
  ): void {
    if (pending) this.#pendingInterrupts.set(threadId, pending)
    else this.#pendingInterrupts.delete(threadId)
  }

  readonly stream: LangGraphStreamCallback<LangChainMessage> = async function* (
    this: NativeAgentClient,
    messages: LangChainMessage[],
    config: Parameters<LangGraphStreamCallback<LangChainMessage>>[1]
  ) {
    if (this.#disposed) {
      throw new Error("폐기된 에이전트 런타임은 다시 사용할 수 없습니다.")
    }
    const active = createActiveStream()
    this.#activeStreams.add(active)
    const signal = AbortSignal.any([
      config.abortSignal,
      active.controller.signal,
    ])
    let threadId: string | undefined
    let thread: ThreadStream | undefined
    let subscription:
      | Awaited<ReturnType<ThreadStream["subscribe"]>>
      | undefined
    let runId: string | undefined
    let terminal = false
    let cancelIssued = false
    const closeOnAbort = () => {
      closeThreadBestEffort(thread)
    }

    try {
      signal.throwIfAborted()
      active.cancellationSnapshot =
        await this.tokenBroker.captureCancellationSnapshot(signal)
      const initialized = await config.initialize()
      if (!initialized.externalId) {
        throw new Error("원격 대화 ID를 만들지 못했습니다.")
      }
      if (initialized.remoteId !== initialized.externalId) {
        throw new Error("대화 ID 매핑이 일치하지 않습니다.")
      }
      threadId = initialized.externalId
      signal.throwIfAborted()
      thread = this.client.threads.stream(threadId, {
        assistantId: this.assistantId,
        transport: "sse",
        fetch: this.tokenBroker.fetchWithAuthRetry as typeof fetch,
        maxReconnectAttempts: 5,
        onReconnect: ({ attempt }) => {
          this.#onActivity?.({
            id: "connection:reconnect",
            kind: "connection",
            namespace: [],
            status: "reconnecting",
            label: `연결을 복구하는 중입니다 (${attempt}/5).`,
          })
        },
      })
      active.stream = thread
      signal.addEventListener("abort", closeOnAbort, { once: true })
      if (signal.aborted) closeOnAbort()
      subscription = await thread.subscribe(
        [
          "messages",
          "lifecycle",
          "input",
          "tools",
          "custom",
        ],
        {
          namespaces: [[]],
          depth: 0,
        }
      )

      if (config.command) {
        const pending = this.#pendingInterrupts.get(threadId)
        if (!pending) {
          throw new Error("재개할 승인 요청이 없습니다.")
        }
        await thread.respondInput({
          namespace: pending.namespace,
          interrupt_id: pending.interruptId,
          response: config.command.resume,
        })
        // APv2 input.respond creates/resumes a run but the SDK's native
        // respondInput method intentionally returns void. Resolve the active
        // ID once so Stop can still cancel a resumed run exactly once.
        runId = await resolveActiveRunId(this.client, threadId, signal).catch(
          () => undefined
        )
        this.#pendingInterrupts.delete(threadId)
        yield { event: "updates", data: { __interrupt__: [] } }
      } else {
        const result = await thread.submitRun({
          input: { messages: toRunMessages(messages) },
          ...(isRecord(config.runConfig)
            ? { config: config.runConfig }
            : {}),
        })
        runId = result.run_id
      }

      const projection = new NativeMessageProjection()
      const inspection = new InspectionProjector()
      const resuming = config.command !== undefined
      let sawRootRunning = false

      // ThreadStream pauses, rather than closes, a subscription at a root
      // terminal. A newly attached resume stream can first replay the prior
      // `interrupted` event and then resume when the new `running` event
      // arrives. Re-entering the iterator is therefore required by the SDK's
      // SubscriptionHandle contract; otherwise a successful resumed run can
      // look like an empty stream.
      while (!terminal) {
        for await (const event of subscription as AsyncIterable<ProtocolStreamEvent>) {
          signal.throwIfAborted()
          if (event.method === "messages") {
            const activity = inspection.consumeMessage(event)
            if (activity) this.#onActivity?.(activity)
            // Nested-agent transcript text is not a user-facing answer.
            // Lifecycle/custom summaries remain visible; root-message reasoning
            // is locally removed but may already have crossed the SSE boundary.
            if (event.params.namespace.length > 0) continue
            const projected = projection.consume(event)
            if (projected) yield projected
            continue
          }
          if (event.method === "input.requested") {
            const pending = pendingFromInputEvent(event)
            const existing = this.#pendingInterrupts.get(threadId)
            if (existing && existing.interruptId !== pending.interruptId) {
              throw new Error(
                "동시에 여러 승인 요청이 도착했습니다. 안전하게 재개할 수 없어 중단했습니다."
              )
            }
            this.#pendingInterrupts.set(threadId, pending)
            yield {
              event: "updates",
              data: {
                __interrupt__: [projectInputEventForRuntime(event)],
              },
            }
            continue
          }
          if (event.method === "tools") {
            this.#onActivity?.(inspection.consumeTool(event))
            continue
          }
          if (event.method === "custom") {
            const activity = inspection.consumeCustom(event)
            if (activity) this.#onActivity?.(activity)
            continue
          }
          if (event.method === "lifecycle") {
            this.#onActivity?.(inspection.consumeLifecycle(event))
            const root = event.params.namespace.length === 0
            if (root && event.params.data.event === "running") {
              sawRootRunning = true
            }
            if (event.params.data.event === "failed") {
              this.#onError?.(new AgentLifecycleError())
              yield {
                event: "error",
                data: { message: safeLifecycleError(event) },
              }
            }
            const staleResumeInterrupt =
              root &&
              event.params.data.event === "interrupted" &&
              resuming &&
              !sawRootRunning
            if (isRootTerminal(event) && !staleResumeInterrupt) {
              terminal = true
              break
            }
          }
        }
        if (terminal || !subscription.isPaused) break
        await subscription.waitForResume()
      }
    } catch (error) {
      if (
        !signal.aborted &&
        !(error instanceof Error && error.name === "AbortError")
      ) {
        const normalized = sanitizeAgentError(error)
        this.#onError?.(normalized)
        throw normalized
      }
    } finally {
      if (
        signal.aborted &&
        !terminal &&
        threadId &&
        runId &&
        active.cancellationSnapshot &&
        !cancelIssued
      ) {
        cancelIssued = true
        try {
          const cancellationClient = new Client({
            apiUrl: this.#apiUrl,
            apiKey: null,
            callerOptions: {
              fetch: active.cancellationSnapshot.createFetch({
                apiUrl: this.#apiUrl,
                threadId,
                runId,
              }) as typeof fetch,
              maxRetries: 0,
            },
          })
          await cancelRunAndWait(cancellationClient, threadId, runId)
        } catch {
          // Cancellation is bounded best effort. Cleanup below is mandatory
          // even when the old credential is rejected or the API is offline.
        }
      }
      signal.removeEventListener("abort", closeOnAbort)
      await subscription?.unsubscribe().catch(() => undefined)
      await thread?.close().catch(() => undefined)
      active.cancellationSnapshot?.dispose()
      this.#activeStreams.delete(active)
      active.settle()
    }
  }.bind(this)
}

export const nativeClientTesting = {
  assembledMessageToLangChain,
  inspect(client: NativeAgentClient) {
    const read = nativeClientInspectionReaders.get(client)
    if (!read) throw new Error("Unknown NativeAgentClient")
    return read()
  },
  pendingFromInputEvent,
  resolveActiveRunId,
  safeLifecycleError,
}
