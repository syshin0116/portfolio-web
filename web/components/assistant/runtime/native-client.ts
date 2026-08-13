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
import type { AgentTokenIntent } from "@/lib/agent-token-intent"
import type { AgentModel } from "@/lib/agent-model"

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
import {
  projectInterruptForUi,
  readRuntimeInterruptProjection,
  type InterruptUiProjection,
} from "./interrupt-projection"
import type { RuntimeThreadSource } from "./thread-source"

const TERMINAL_RUN_STATUSES = new Set([
  "success",
  "error",
  "timeout",
  "interrupted",
])
const TERMINAL_WAIT_MS = 2_000
const TERMINAL_POLL_MS = 100
const DISPOSE_WAIT_MS = TERMINAL_WAIT_MS + 500
const RESUMED_RUN_ID_WAIT_MS = 2_000
const RESUMED_RUN_ID_POLL_MS = 50
const INTERRUPT_WATCHER_WAIT_MS = 1_000
const INTERRUPT_STATE_FALLBACK_WAIT_MS = 1_000
const INTERRUPT_WATCHER_POLL_MS = 10
const INTERRUPT_WATCHER_STABLE_POLLS = 5
const MAX_STATE_MESSAGES = 500
const MAX_STATE_CONTENT_BLOCKS = 256
const MAX_STATE_TEXT_BYTES = 100_000
const MAX_STATE_MESSAGE_ID_BYTES = 512
const SAFE_STATE_MESSAGE_ID = /^[A-Za-z0-9][A-Za-z0-9._:@/-]*$/
const MAX_INTERRUPT_ID_BYTES = 512
const MAX_INTERRUPT_NAMESPACE_PARTS = 32
const MAX_INTERRUPT_NAMESPACE_PART_BYTES = 512
const SAFE_INTERRUPT_ID = /^[A-Za-z0-9][A-Za-z0-9._:@/-]*$/
const SAFE_INTERRUPT_NAMESPACE_PART = /^[A-Za-z0-9][A-Za-z0-9._:@/-]*$/
const SAFE_PUBLIC_ROOT_INTERRUPT_ID = /^[0-9a-f]{32}$/
const SUBMIT_NONCE_METADATA_KEY = "syshin_ui_submit_nonce"
const SAFE_SUBMIT_NONCE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const MAX_EVENT_BYTES = 256 * 1_024
const MAX_RUN_BYTES = 8 * 1_024 * 1_024
const MAX_LIVE_MESSAGES = 256
const MAX_MESSAGE_BYTES = 1 * 1_024 * 1_024
const MAX_CONTENT_BLOCKS_PER_MESSAGE = 256
const MAX_BLOCK_BYTES = 256 * 1_024
const MAX_LIVE_ID_BYTES = 512
const MAX_TEXT_BYTES_PER_MESSAGE = 512 * 1_024
const MAX_TOOL_ARGUMENT_BYTES_PER_MESSAGE = 256 * 1_024
const MAX_PRE_BARRIER_BYTES = 2 * 1_024 * 1_024
const textEncoder = new TextEncoder()

export type { AgentActivity } from "./inspection"

export interface PendingInterrupt {
  interruptId: string
  namespace: string[]
  value: InterruptUiProjection
  resumable: boolean
  when: string
}

export interface NativeAgentClientOptions {
  apiUrl: string
  assistantId: string
  identity: string
  initialToken?: string
  onAuthenticationExpired?: () => void
  tokenIntent?: AgentTokenIntent
  getSelectedModel?: () => AgentModel | undefined
  tokenBroker?: AgentTokenBroker
  client?: Client
  getSourceGeneration?: () => number
  onActivity?: (
    activity: AgentActivity,
    source: RuntimeThreadSource
  ) => void
  onError?: (error: Error, source: RuntimeThreadSource) => void
}

interface ActiveNativeStream {
  cancellationSnapshot?: AgentCancellationSnapshot
  completion: Promise<void>
  controller: AbortController
  settle: () => void
  stream?: ThreadStream
}

type NativeThreadSubscription = Awaited<
  ReturnType<ThreadStream["subscribe"]>
>

interface NativeThreadSession {
  closePromise?: Promise<void>
  subscription: NativeThreadSubscription
  thread: ThreadStream
  threadId: string
}

type QueuedNestedInput =
  | { type: "pending"; pending: PendingInterrupt }
  | { type: "error"; error: Error }
  | { type: "done" }

class NestedInputQueue {
  readonly #items: QueuedNestedInput[] = []
  readonly #waiters: Array<(item: QueuedNestedInput) => void> = []
  #closed = false

  push(pending: PendingInterrupt): void {
    if (this.#closed) return
    this.#deliver({ type: "pending", pending })
  }

  fail(): void {
    if (this.#closed) return
    this.#closed = true
    this.#items.length = 0
    this.#deliver({
      type: "error",
      error: new Error(
        "동시에 여러 승인 요청이 도착했습니다. 안전하게 재개할 수 없어 중단했습니다."
      ),
    })
  }

  close(): void {
    if (this.#closed) return
    this.#closed = true
    this.#items.length = 0
    this.#deliver({ type: "done" })
  }

  async next(signal: AbortSignal): Promise<QueuedNestedInput> {
    signal.throwIfAborted()
    const current = this.#items.shift()
    if (current) return current
    if (this.#closed) return { type: "done" }
    return await new Promise<QueuedNestedInput>((resolve, reject) => {
      const deliver = (item: QueuedNestedInput) => {
        signal.removeEventListener("abort", onAbort)
        resolve(item)
      }
      const onAbort = () => {
        const index = this.#waiters.indexOf(deliver)
        if (index >= 0) this.#waiters.splice(index, 1)
        reject(signal.reason)
      }
      signal.addEventListener("abort", onAbort, { once: true })
      this.#waiters.push(deliver)
    })
  }

  #deliver(item: QueuedNestedInput): void {
    const waiter = this.#waiters.shift()
    if (waiter) waiter(item)
    else this.#items.push(item)
  }
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

class AgentProtocolBoundaryError extends Error {
  constructor() {
    super("Agent protocol boundary rejected an unsafe event")
    this.name = "AgentProtocolBoundaryError"
    this.stack = undefined
  }
}

function isUnicodeScalarString(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index)
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1)
      if (next < 0xdc00 || next > 0xdfff) return false
      index += 1
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      return false
    }
  }
  return !value.includes("\0")
}

function utf8Bytes(value: string): number {
  return textEncoder.encode(value).byteLength
}

function boundedUtf8String(
  value: unknown,
  maxBytes: number
): value is string {
  return (
    typeof value === "string" &&
    isUnicodeScalarString(value) &&
    utf8Bytes(value) <= maxBytes
  )
}

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
  return boundedUtf8String(value, MAX_STATE_TEXT_BYTES)
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
      boundedUtf8String(candidate.id, MAX_STATE_MESSAGE_ID_BYTES) &&
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
            error: "에이전트 메시지를 완료하지 못했습니다.",
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

function projectToolResult(
  activity: Extract<AgentActivity, { kind: "tool" }>
): LangGraphMessagesEvent<LangChainMessage> | undefined {
  if (
    !activity.toolName ||
    (activity.status !== "completed" && activity.status !== "failed")
  ) {
    return undefined
  }
  return {
    event: "messages/complete",
    data: [
      {
        type: "tool",
        content: activity.label,
        tool_call_id: activity.toolCallId,
        name: activity.toolName,
        status: activity.status === "completed" ? "success" : "error",
      },
    ],
  }
}

function safeInterruptIdentifier(value: unknown): string | undefined {
  return boundedUtf8String(value, MAX_INTERRUPT_ID_BYTES) &&
    SAFE_INTERRUPT_ID.test(value)
    ? value
    : undefined
}

function safeInterruptNamespace(value: unknown): string[] | undefined {
  if (
    !Array.isArray(value) ||
    value.length > MAX_INTERRUPT_NAMESPACE_PARTS
  ) {
    return undefined
  }
  const result: string[] = []
  for (const part of value) {
    if (
      typeof part !== "string" ||
      part.length === 0 ||
      !boundedUtf8String(part, MAX_INTERRUPT_NAMESPACE_PART_BYTES) ||
      !SAFE_INTERRUPT_NAMESPACE_PART.test(part)
    ) {
      return undefined
    }
    result.push(part)
  }
  return result
}

function pendingFromInputEvent(event: InputEvent): PendingInterrupt {
  const data = event.params.data as typeof event.params.data & {
    value?: unknown
  }
  const interruptId = safeInterruptIdentifier(data.interrupt_id)
  const namespace = safeInterruptNamespace(event.params.namespace)
  if (!interruptId || !namespace) {
    throw new Error("승인 요청 식별 정보가 올바르지 않습니다.")
  }
  return {
    interruptId,
    namespace,
    value: projectInterruptForUi(data.payload ?? data.value),
    resumable: true,
    when: "during",
  }
}

function pendingFromSdkInterrupt(value: unknown): PendingInterrupt {
  if (!isRecord(value)) {
    throw new Error("승인 요청 형식을 읽을 수 없습니다.")
  }
  const interruptId = safeInterruptIdentifier(value.interruptId)
  const namespace = safeInterruptNamespace(value.namespace)
  if (!interruptId || !namespace) {
    throw new Error("승인 요청 식별 정보가 올바르지 않습니다.")
  }
  return {
    interruptId,
    namespace,
    value: projectInterruptForUi(value.payload),
    resumable: true,
    when: "during",
  }
}

export function projectPendingInterruptForRuntime(
  pending: PendingInterrupt
): LangGraphInterruptState {
  return {
    value: pending.value,
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
  const interruptId = safeInterruptIdentifier(
    typeof candidate.interrupt_id === "string"
      ? candidate.interrupt_id
      : typeof candidate.id === "string"
        ? candidate.id
        : undefined
  )
  if (!interruptId) {
    throw new Error("승인 요청 식별 정보가 올바르지 않습니다.")
  }
  const namespace = safeInterruptNamespace(candidate.ns ?? [])
  if (!namespace) {
    throw new Error("승인 요청 식별 정보가 올바르지 않습니다.")
  }
  return {
    interruptId,
    namespace,
    value: projectInterruptForUi(candidate.value ?? candidate.payload),
    resumable: candidate.resumable !== false,
    when: candidate.when === "before" ? "before" : "during",
  }
}

function pendingFromPublicRootState(state: unknown): PendingInterrupt {
  if (!isRecord(state) || !Array.isArray(state.interrupts)) {
    throw new Error("승인 요청 상태를 안전하게 확인할 수 없습니다.")
  }
  if (state.interrupts.length !== 1) {
    throw new Error(
      "동시에 여러 승인 요청이 도착했거나 요청이 없습니다. 안전하게 재개할 수 없어 중단했습니다."
    )
  }

  const candidate = state.interrupts[0]
  if (
    !isRecord(candidate) ||
    typeof candidate.id !== "string" ||
    !SAFE_PUBLIC_ROOT_INTERRUPT_ID.test(candidate.id) ||
    !Array.isArray(candidate.ns) ||
    candidate.ns.length !== 0 ||
    candidate.resumable !== true ||
    (candidate.when !== "before" && candidate.when !== "during")
  ) {
    throw new Error("승인 요청 상태를 안전하게 확인할 수 없습니다.")
  }
  const projection = projectInterruptForUi(candidate.value)
  if (!projection.recognized) {
    throw new Error("승인 요청 상태를 안전하게 확인할 수 없습니다.")
  }

  return {
    interruptId: candidate.id,
    namespace: [],
    value: projection,
    resumable: true,
    when: candidate.when,
  }
}

async function loadPublicRootInterrupt(
  client: Client,
  threadId: string,
  signal: AbortSignal
): Promise<PendingInterrupt> {
  const bounded = timeoutController(
    INTERRUPT_STATE_FALLBACK_WAIT_MS,
    "Public interrupt state fallback timed out"
  )
  const stateSignal = AbortSignal.any([
    signal,
    bounded.controller.signal,
  ])
  try {
    const request = client.threads.getState<Record<string, unknown>>(
      threadId,
      undefined,
      { signal: stateSignal }
    )
    const state = await settleBeforeAbort(request, stateSignal)
    stateSignal.throwIfAborted()
    return pendingFromPublicRootState(state)
  } catch (error) {
    if (signal.aborted) throw signal.reason
    if (bounded.controller.signal.aborted) {
      throw new Error("승인 요청 상태를 안전하게 확인할 수 없습니다.")
    }
    throw error
  } finally {
    bounded.clear()
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

interface LiveMessageBudget {
  blockBytes: Map<number, number>
  blockCount: number
  blockIndexes: Set<number>
  blockTextBytes: Map<number, number>
  blockToolArgumentBytes: Map<number, number>
  bytes: number
  textBytes: number
  toolArgumentBytes: number
}

function serializedUtf8Bytes(value: unknown): number {
  try {
    const serialized = JSON.stringify(value)
    if (serialized === undefined) throw new AgentProtocolBoundaryError()
    return utf8Bytes(serialized)
  } catch {
    throw new AgentProtocolBoundaryError()
  }
}

function safeLiveIdentifier(value: unknown): asserts value is string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    !boundedUtf8String(value, MAX_LIVE_ID_BYTES)
  ) {
    throw new AgentProtocolBoundaryError()
  }
}

function namespaceKey(namespace: readonly string[]): string {
  return namespace.join("\u001f")
}

function messageScopeKey(
  namespace: readonly string[],
  node: unknown
): string {
  if (node !== undefined) safeLiveIdentifier(node)
  return `${namespaceKey(namespace)}\u001e${node ?? ""}`
}

function stringBytes(value: unknown): number {
  return typeof value === "string" && isUnicodeScalarString(value)
    ? utf8Bytes(value)
    : value === undefined
      ? 0
      : serializedUtf8Bytes(value)
}

function contentPayloadBytes(value: unknown): {
  text: number
  toolArguments: number
} {
  if (!isRecord(value)) return { text: 0, toolArguments: 0 }
  return {
    text: stringBytes(value.text) + stringBytes(value.reasoning),
    toolArguments:
      value.args === undefined ? 0 : stringBytes(value.args),
  }
}

class LiveRunBudget {
  readonly #messages = new Map<string, LiveMessageBudget>()
  #messageCount = 0
  #runBytes = 0

  observe(event: ProtocolStreamEvent): void {
    const eventBytes = serializedUtf8Bytes(event)
    if (eventBytes > MAX_EVENT_BYTES) {
      throw new AgentProtocolBoundaryError()
    }
    this.#runBytes += eventBytes
    if (this.#runBytes > MAX_RUN_BYTES) {
      throw new AgentProtocolBoundaryError()
    }

    if ("event_id" in event && event.event_id !== undefined) {
      safeLiveIdentifier(event.event_id)
    }
    if (
      !Array.isArray(event.params.namespace) ||
      event.params.namespace.length > MAX_INTERRUPT_NAMESPACE_PARTS
    ) {
      throw new AgentProtocolBoundaryError()
    }
    for (const part of event.params.namespace) {
      safeLiveIdentifier(part)
    }
    if (event.method !== "messages") return

    const data = event.params.data as Record<string, unknown>
    const eventName = data.event
    const key = messageScopeKey(
      event.params.namespace,
      event.params.node
    )
    if (eventName === "message-start") {
      safeLiveIdentifier(data.id)
      this.#messageCount += 1
      if (
        this.#messageCount > MAX_LIVE_MESSAGES ||
        this.#messages.has(key)
      ) {
        throw new AgentProtocolBoundaryError()
      }
      this.#messages.set(key, {
        blockBytes: new Map(),
        blockCount: 0,
        blockIndexes: new Set(),
        blockTextBytes: new Map(),
        blockToolArgumentBytes: new Map(),
        bytes: 0,
        textBytes: 0,
        toolArgumentBytes: 0,
      })
    }
    const message = this.#messages.get(key)
    if (!message) throw new AgentProtocolBoundaryError()
    message.bytes += eventBytes
    if (message.bytes > MAX_MESSAGE_BYTES) {
      throw new AgentProtocolBoundaryError()
    }

    if (eventName === "content-block-start") {
      const index = data.index
      if (
        !Number.isSafeInteger(index) ||
        (index as number) < 0 ||
        (index as number) >= MAX_CONTENT_BLOCKS_PER_MESSAGE ||
        message.blockIndexes.has(index as number)
      ) {
        throw new AgentProtocolBoundaryError()
      }
      message.blockCount += 1
      if (message.blockCount > MAX_CONTENT_BLOCKS_PER_MESSAGE) {
        throw new AgentProtocolBoundaryError()
      }
      const content = data.content
      const contentBytes = serializedUtf8Bytes(content)
      if (contentBytes > MAX_BLOCK_BYTES) {
        throw new AgentProtocolBoundaryError()
      }
      message.blockIndexes.add(index as number)
      message.blockBytes.set(index as number, contentBytes)
      const payloadBytes = contentPayloadBytes(content)
      message.blockTextBytes.set(index as number, payloadBytes.text)
      message.blockToolArgumentBytes.set(
        index as number,
        payloadBytes.toolArguments
      )
      message.textBytes += payloadBytes.text
      message.toolArgumentBytes += payloadBytes.toolArguments
      if (isRecord(content)) {
        if (content.id !== undefined) safeLiveIdentifier(content.id)
        if (content.tool_call_id !== undefined) {
          safeLiveIdentifier(content.tool_call_id)
        }
      }
    } else if (eventName === "content-block-delta") {
      const index = data.index
      if (
        !Number.isSafeInteger(index) ||
        !message.blockIndexes.has(index as number)
      ) {
        throw new AgentProtocolBoundaryError()
      }
      const delta = isRecord(data.delta) ? data.delta : {}
      const blockBytes =
        (message.blockBytes.get(index as number) ?? 0) +
        serializedUtf8Bytes(delta)
      if (blockBytes > MAX_BLOCK_BYTES) {
        throw new AgentProtocolBoundaryError()
      }
      message.blockBytes.set(index as number, blockBytes)
      const fields = isRecord(delta.fields) ? delta.fields : delta
      const payloadBytes = contentPayloadBytes(fields)
      message.blockTextBytes.set(
        index as number,
        (message.blockTextBytes.get(index as number) ?? 0) +
          payloadBytes.text
      )
      message.blockToolArgumentBytes.set(
        index as number,
        (message.blockToolArgumentBytes.get(index as number) ?? 0) +
          payloadBytes.toolArguments
      )
      message.textBytes += payloadBytes.text
      message.toolArgumentBytes += payloadBytes.toolArguments
    } else if (eventName === "content-block-finish") {
      const index = data.index
      if (
        !Number.isSafeInteger(index) ||
        !message.blockIndexes.has(index as number) ||
        serializedUtf8Bytes(data.content) > MAX_BLOCK_BYTES
      ) {
        throw new AgentProtocolBoundaryError()
      }
      const content = data.content
      const payloadBytes = contentPayloadBytes(content)
      message.textBytes +=
        payloadBytes.text -
        (message.blockTextBytes.get(index as number) ?? 0)
      message.toolArgumentBytes +=
        payloadBytes.toolArguments -
        (message.blockToolArgumentBytes.get(index as number) ?? 0)
      if (isRecord(content)) {
        if (content.id !== undefined) safeLiveIdentifier(content.id)
        if (content.tool_call_id !== undefined) {
          safeLiveIdentifier(content.tool_call_id)
        }
      }
      message.blockIndexes.delete(index as number)
      message.blockBytes.delete(index as number)
      message.blockTextBytes.delete(index as number)
      message.blockToolArgumentBytes.delete(index as number)
    }
    if (
      message.textBytes > MAX_TEXT_BYTES_PER_MESSAGE ||
      message.toolArgumentBytes > MAX_TOOL_ARGUMENT_BYTES_PER_MESSAGE
    ) {
      throw new AgentProtocolBoundaryError()
    }
    if (
      eventName === "message-finish" &&
      message.blockIndexes.size > 0
    ) {
      throw new AgentProtocolBoundaryError()
    }
    if (eventName === "message-finish" || eventName === "message-error") {
      this.#messages.delete(key)
    }
  }
}

function isBoundedDecimal(value: string): boolean {
  if (!/^(0|[1-9][0-9]*)$/.test(value)) return false
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) && parsed >= 0
}

function eventIdBelongsToRun(eventId: string, runId: string): boolean {
  const brokerPrefix = `${runId}_event_`
  if (eventId.startsWith(brokerPrefix)) {
    const parts = eventId.slice(brokerPrefix.length).split(":")
    return (
      parts.length === 2 &&
      isBoundedDecimal(parts[0]!) &&
      isBoundedDecimal(parts[1]!)
    )
  }
  for (const lifecycle of ["running", "status-end"] as const) {
    const prefix = `${runId}:${lifecycle}:`
    if (
      eventId.startsWith(prefix) &&
      isBoundedDecimal(eventId.slice(prefix.length))
    ) {
      return true
    }
  }
  return false
}

function isRootLifecycle(
  event: ProtocolStreamEvent
): event is Extract<ProtocolStreamEvent, { method: "lifecycle" }> {
  return (
    event.method === "lifecycle" &&
    event.params.namespace.length === 0
  )
}

class RunCorrelationGate {
  readonly #queuedLifecycle: LifecycleEvent[] = []
  #configured = false
  #correlated = false
  #runId?: string
  #queuedBytes = 0

  observeLifecycle(event: LifecycleEvent): void {
    if (event.params.namespace.length !== 0) return
    if (!this.#configured) {
      const eventBytes = serializedUtf8Bytes(event)
      this.#queuedBytes += eventBytes
      this.#queuedLifecycle.push(event)
      if (
        this.#queuedLifecycle.length > MAX_LIVE_MESSAGES ||
        this.#queuedBytes > MAX_PRE_BARRIER_BYTES
      ) {
        throw new AgentProtocolBoundaryError()
      }
      return
    }
    this.#observeMarker(event)
  }

  configure(runId: string): void {
    if (this.#configured) throw new AgentProtocolBoundaryError()
    safeLiveIdentifier(runId)
    this.#configured = true
    this.#runId = runId
    const queued = this.#queuedLifecycle.splice(0)
    this.#queuedBytes = 0
    for (const event of queued) this.#observeMarker(event)
  }

  accepts(event: ProtocolStreamEvent, eventId: string): boolean {
    const runId = this.#runId
    if (!this.#configured || runId === undefined) {
      throw new AgentProtocolBoundaryError()
    }
    if (!eventIdBelongsToRun(eventId, runId)) return false
    if (isRootLifecycle(event)) this.#correlated = true
    if (!this.#correlated) throw new AgentProtocolBoundaryError()
    return true
  }

  #observeMarker(event: LifecycleEvent): void {
    const eventId =
      "event_id" in event && typeof event.event_id === "string"
        ? event.event_id
        : undefined
    if (eventId === undefined) throw new AgentProtocolBoundaryError()
    safeLiveIdentifier(eventId)
    if (eventIdBelongsToRun(eventId, this.#runId!)) {
      this.#correlated = true
    }
  }
}

class RunEventBoundary {
  readonly #budget: LiveRunBudget
  readonly #correlation: RunCorrelationGate
  readonly #accepted = new WeakMap<object, boolean>()
  readonly #seenEventIds: Set<string>
  readonly #queued: ProtocolStreamEvent[] = []
  #configured = false
  #lastSequence?: number
  #queuedBytes = 0

  constructor(
    correlation: RunCorrelationGate,
    budget = new LiveRunBudget(),
    seenEventIds = new Set<string>()
  ) {
    this.#correlation = correlation
    this.#budget = budget
    this.#seenEventIds = seenEventIds
  }

  queueOrObserve(event: ProtocolStreamEvent): boolean | undefined {
    const cached = this.#accepted.get(event)
    if (cached !== undefined) return cached
    if (!this.#configured) {
      const eventBytes = serializedUtf8Bytes(event)
      if (eventBytes > MAX_EVENT_BYTES) {
        throw new AgentProtocolBoundaryError()
      }
      this.#queuedBytes += eventBytes
      this.#queued.push(event)
      if (
        this.#queued.length > MAX_LIVE_MESSAGES * 8 ||
        this.#queuedBytes > MAX_PRE_BARRIER_BYTES
      ) {
        throw new AgentProtocolBoundaryError()
      }
      return undefined
    }
    return this.#observe(event)
  }

  configure(): void {
    if (this.#configured) throw new AgentProtocolBoundaryError()
    this.#configured = true
    const queued = this.#queued.splice(0)
    this.#queuedBytes = 0
    for (const event of queued) this.#observe(event)
  }

  wasAccepted(event: ProtocolStreamEvent): boolean {
    const accepted = this.queueOrObserve(event)
    if (accepted === undefined) throw new AgentProtocolBoundaryError()
    return accepted
  }

  #observe(event: ProtocolStreamEvent): boolean {
    const cached = this.#accepted.get(event)
    if (cached !== undefined) return cached
    const eventId =
      "event_id" in event && typeof event.event_id === "string"
        ? event.event_id
        : undefined
    if (eventId === undefined) throw new AgentProtocolBoundaryError()
    safeLiveIdentifier(eventId)
    if (this.#seenEventIds.has(eventId)) {
      this.#accepted.set(event, false)
      return false
    }
    this.#seenEventIds.add(eventId)
    const sequence = "seq" in event ? event.seq : undefined
    if (
      typeof sequence !== "number" ||
      !Number.isSafeInteger(sequence) ||
      sequence < 0 ||
      (this.#lastSequence !== undefined && sequence <= this.#lastSequence)
    ) {
      throw new AgentProtocolBoundaryError()
    }
    this.#lastSequence = sequence
    const accepted = this.#correlation.accepts(event, eventId)
    this.#accepted.set(event, accepted)
    if (accepted) this.#budget.observe(event)
    return accepted
  }
}

function createSubmitNonce(): string {
  const nonce = crypto.randomUUID()
  if (!SAFE_SUBMIT_NONCE.test(nonce)) {
    throw new AgentProtocolBoundaryError()
  }
  return nonce
}

function runMetadataWithNonce(
  runConfig: unknown,
  nonce: string
): Record<string, unknown> {
  const callerMetadata =
    isRecord(runConfig) && isRecord(runConfig.metadata)
      ? runConfig.metadata
      : {}
  return {
    ...callerMetadata,
    [SUBMIT_NONCE_METADATA_KEY]: nonce,
  }
}

function runConfigWithNonce(
  runConfig: unknown,
  nonce: string
): Record<string, unknown> {
  const callerConfig = isRecord(runConfig) ? runConfig : {}
  const callerMetadata = isRecord(callerConfig.metadata)
    ? callerConfig.metadata
    : {}
  return {
    ...callerConfig,
    metadata: {
      ...callerMetadata,
      [SUBMIT_NONCE_METADATA_KEY]: nonce,
    },
  }
}

function runConfigWithModel(
  runConfig: unknown,
  model: AgentModel | undefined
): Record<string, unknown> {
  const callerConfig = isRecord(runConfig) ? runConfig : {}
  const { configurable, ...rest } = callerConfig
  delete rest.model
  const callerConfigurable = isRecord(configurable) ? configurable : {}
  const restConfigurable = { ...callerConfigurable }
  delete restConfigurable.model
  if (!isRecord(configurable) && model === undefined) return rest
  return {
    ...rest,
    configurable: {
      ...restConfigurable,
      ...(model ? { model } : {}),
    },
  }
}

function runMatchesSubmitNonce(
  run: unknown,
  threadId: string,
  submitNonce: string
): run is { run_id: string } {
  if (
    !isRecord(run) ||
    run.thread_id !== threadId ||
    typeof run.run_id !== "string"
  ) {
    return false
  }
  const observed: unknown[] = []
  if (
    isRecord(run.metadata) &&
    SUBMIT_NONCE_METADATA_KEY in run.metadata
  ) {
    observed.push(run.metadata[SUBMIT_NONCE_METADATA_KEY])
  }
  if (
    isRecord(run.config) &&
    isRecord(run.config.metadata) &&
    SUBMIT_NONCE_METADATA_KEY in run.config.metadata
  ) {
    observed.push(
      run.config.metadata[SUBMIT_NONCE_METADATA_KEY]
    )
  }
  return (
    observed.length > 0 &&
    observed.every((candidate) => candidate === submitNonce)
  )
}

function timeoutController(
  milliseconds: number,
  message = "Terminal run wait timed out"
): {
  controller: AbortController
  clear: () => void
} {
  const controller = new AbortController()
  const timer = setTimeout(
    () =>
      controller.abort(
        new DOMException(message, "TimeoutError")
      ),
    milliseconds
  )
  return { controller, clear: () => clearTimeout(timer) }
}

async function settleBeforeAbort<T>(
  operation: Promise<T>,
  signal: AbortSignal
): Promise<T> {
  return await new Promise<T>((resolve, reject) => {
    let settled = false
    const finish = (callback: () => void) => {
      if (settled) return
      settled = true
      signal.removeEventListener("abort", onAbort)
      callback()
    }
    const onAbort = () => finish(() => reject(signal.reason))
    signal.addEventListener("abort", onAbort, { once: true })
    operation.then(
      (value) => finish(() => resolve(value)),
      (error) => finish(() => reject(error))
    )
    if (signal.aborted) onAbort()
  })
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
    if (!bounded.controller.signal.aborted) throw error
  } finally {
    bounded.clear()
  }
}

async function waitForResumedRunId(
  client: Pick<Client, "runs">,
  threadId: string,
  knownRunIds: ReadonlySet<string>,
  submitNonce: string,
  signal: AbortSignal
): Promise<string> {
  while (!signal.aborted) {
    const runs = await client.runs.list(threadId, {
      limit: 10,
      offset: 0,
      signal,
    })
    const created = runs.filter(
      (run) =>
        !knownRunIds.has(run.run_id) &&
        runMatchesSubmitNonce(run, threadId, submitNonce)
    )
    if (created.length > 1) throw new AgentProtocolBoundaryError()
    if (created.length === 1) return created[0]!.run_id
    await waitForDelay(RESUMED_RUN_ID_POLL_MS, signal)
  }
  throw signal.reason
}

async function resolveResumedRunIdOrThrow(
  client: Pick<Client, "runs">,
  threadId: string,
  knownRunIds: ReadonlySet<string>,
  submitNonce: string,
  signal: AbortSignal
): Promise<string> {
  try {
    return await waitForResumedRunId(
      client,
      threadId,
      knownRunIds,
      submitNonce,
      signal
    )
  } catch {
    // This resolver uses only its own bounded signal. Convert its
    // TimeoutError/AbortError into an ordinary failure so the outer stream
    // cannot mistake resolver exhaustion for user Stop.
    throw new Error("재개된 실행 식별자를 확인하지 못했습니다.")
  }
}

type CommandSettlement =
  | { status: "fulfilled"; value: unknown }
  | { status: "rejected"; reason: unknown }

function settleCommand(command: Promise<unknown>): Promise<CommandSettlement> {
  return command.then(
    (value) => ({ status: "fulfilled" as const, value }),
    (reason) => ({ status: "rejected" as const, reason })
  )
}

async function awaitCommandSettlement(
  settlement: Promise<CommandSettlement>,
  signal: AbortSignal
): Promise<CommandSettlement> {
  signal.throwIfAborted()
  return await new Promise<CommandSettlement>((resolve, reject) => {
    const onAbort = () => reject(signal.reason)
    signal.addEventListener("abort", onAbort, { once: true })
    settlement.then(resolve, reject).finally(() => {
      signal.removeEventListener("abort", onAbort)
    })
  })
}

async function waitForDelay(
  milliseconds: number,
  signal: AbortSignal
): Promise<void> {
  signal.throwIfAborted()
  await new Promise<void>((resolve, reject) => {
    const onTimer = () => {
      signal.removeEventListener("abort", onAbort)
      resolve()
    }
    const timer = setTimeout(onTimer, milliseconds)
    const onAbort = () => {
      clearTimeout(timer)
      reject(signal.reason)
    }
    signal.addEventListener("abort", onAbort, { once: true })
    if (signal.aborted) onAbort()
  })
}

function pendingInterruptKey(pending: PendingInterrupt): string {
  return `${pending.namespace.join("\u001f")}\u001e${pending.interruptId}`
}

async function waitForInterruptedInput(
  thread: ThreadStream,
  pendingInterrupts: Map<string, PendingInterrupt>,
  threadId: string,
  signal: AbortSignal,
  loadFallback: () => Promise<PendingInterrupt>
): Promise<PendingInterrupt> {
  const bounded = timeoutController(INTERRUPT_WATCHER_WAIT_MS)
  const waitSignal = AbortSignal.any([
    signal,
    bounded.controller.signal,
  ])
  let stableKey: string | undefined
  let stablePolls = 0
  try {
    while (!waitSignal.aborted) {
      const unique = new Map<string, PendingInterrupt>()
      for (const raw of [...thread.interrupts]) {
        const pending = pendingFromSdkInterrupt(raw)
        unique.set(pendingInterruptKey(pending), pending)
      }
      if (unique.size > 1) {
        pendingInterrupts.delete(threadId)
        throw new Error(
          "동시에 여러 승인 요청이 도착했습니다. 안전하게 재개할 수 없어 중단했습니다."
        )
      }
      const sdkPending = unique.values().next().value as
        | PendingInterrupt
        | undefined
      const observed = pendingInterrupts.get(threadId)
      if (
        observed &&
        sdkPending &&
        pendingInterruptKey(observed) !== pendingInterruptKey(sdkPending)
      ) {
        pendingInterrupts.delete(threadId)
        throw new Error(
          "동시에 여러 승인 요청이 도착했습니다. 안전하게 재개할 수 없어 중단했습니다."
        )
      }
      const pending = observed ?? sdkPending
      // ThreadStream applies input.requested to `interrupts` before onEvent.
      // Requiring the SDK projection (not only our callback queue) creates a
      // bounded barrier against the root content SSE reaching interrupted
      // before the wildcard lifecycle/input watcher catches up.
      if (sdkPending && pending) {
        const key = pendingInterruptKey(pending)
        if (key === stableKey) {
          stablePolls += 1
        } else {
          stableKey = key
          stablePolls = 1
        }
        pendingInterrupts.set(threadId, pending)
        if (stablePolls >= INTERRUPT_WATCHER_STABLE_POLLS) {
          return pending
        }
      } else {
        stableKey = undefined
        stablePolls = 0
      }
      await waitForDelay(INTERRUPT_WATCHER_POLL_MS, waitSignal)
    }
    throw waitSignal.reason
  } catch (error) {
    if (bounded.controller.signal.aborted && !signal.aborted) {
      try {
        const fallback = await loadFallback()
        const observed = pendingInterrupts.get(threadId)
        if (
          observed &&
          pendingInterruptKey(observed) !== pendingInterruptKey(fallback)
        ) {
          throw new Error(
            "동시에 여러 승인 요청이 도착했습니다. 안전하게 재개할 수 없어 중단했습니다."
          )
        }
        pendingInterrupts.set(threadId, fallback)
        return fallback
      } catch (fallbackError) {
        pendingInterrupts.delete(threadId)
        throw fallbackError
      }
    }
    throw error
  } finally {
    bounded.clear()
  }
}

async function* mergeContentAndNestedInputs(
  subscription: Awaited<ReturnType<ThreadStream["subscribe"]>>,
  nestedInputs: NestedInputQueue,
  signal: AbortSignal
): AsyncGenerator<
  | { type: "content"; event: ProtocolStreamEvent }
  | Exclude<QueuedNestedInput, { type: "done" }>
> {
  signal.throwIfAborted()
  let contentIterator = subscription[Symbol.asyncIterator]()
  let contentNext = contentIterator.next()
  let nestedNext = nestedInputs.next(signal)

  while (!signal.aborted) {
    const winner = await Promise.race([
      nestedNext.then(
        (result) => ({ source: "nested" as const, result }),
        (error) => ({ source: "failure" as const, error })
      ),
      contentNext.then(
        (result) => ({ source: "content" as const, result }),
        (error) => ({ source: "failure" as const, error })
      ),
    ])
    if (winner.source === "failure") throw winner.error
    if (winner.source === "nested") {
      if (winner.result.type === "done") {
        nestedNext = new Promise<QueuedNestedInput>(() => undefined)
        continue
      }
      nestedNext = nestedInputs.next(signal)
      yield winner.result
      continue
    }
    if (!winner.result.done) {
      const event = winner.result.value as ProtocolStreamEvent
      const rootTerminal =
        event.method === "lifecycle" && isRootTerminal(event)
      // Do not leave a pending read that can consume the next run's first
      // event when ThreadStream resumes this paused root subscription.
      if (!rootTerminal) contentNext = contentIterator.next()
      yield {
        type: "content",
        event,
      }
      if (rootTerminal) contentNext = contentIterator.next()
      continue
    }
    if (!subscription.isPaused) {
      throw new AgentProtocolBoundaryError()
    }

    let resumed = false
    const resume = subscription.waitForResume().then(() => {
      resumed = true
    })
    while (!resumed) {
      const waiting = await Promise.race([
        nestedNext.then(
          (result) => ({ source: "nested" as const, result }),
          (error) => ({ source: "failure" as const, error })
        ),
        resume.then(() => ({ source: "resume" as const })),
      ])
      if (waiting.source === "failure") throw waiting.error
      if (waiting.source === "nested") {
        if (waiting.result.type === "done") {
          nestedNext = new Promise<QueuedNestedInput>(() => undefined)
          continue
        }
        nestedNext = nestedInputs.next(signal)
        yield waiting.result
      }
    }
    contentIterator = subscription[Symbol.asyncIterator]()
    contentNext = contentIterator.next()
  }
  signal.throwIfAborted()
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
  readonly #getSelectedModel?: () => AgentModel | undefined
  readonly #getSourceGeneration: () => number
  readonly #onActivity?: (
    activity: AgentActivity,
    source: RuntimeThreadSource
  ) => void
  readonly #onError?: (error: Error, source: RuntimeThreadSource) => void
  readonly #pendingInterrupts = new Map<string, PendingInterrupt>()
  readonly #activeStreams = new Set<ActiveNativeStream>()
  #disposed = false
  #disposePromise?: Promise<void>
  #streamLease?: symbol
  #threadSession?: NativeThreadSession

  constructor(options: NativeAgentClientOptions) {
    this.#apiUrl = options.apiUrl
    this.#getSelectedModel = options.getSelectedModel
    this.assistantId = options.assistantId
    this.#getSourceGeneration = options.getSourceGeneration ?? (() => 0)
    this.#onActivity = options.onActivity
    this.#onError = options.onError
    this.tokenBroker =
      options.tokenBroker ??
      new AgentTokenBroker(options.identity, {
        agentOrigin: options.apiUrl,
        initialToken: options.initialToken,
        onAuthenticationExpired: options.onAuthenticationExpired,
        tokenIntent: options.tokenIntent,
      })
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

  #closeThreadSession(session: NativeThreadSession): Promise<void> {
    if (this.#threadSession === session) this.#threadSession = undefined
    session.closePromise ??= session.subscription
      .unsubscribe()
      .catch(() => undefined)
      .then(() => session.thread.close().catch(() => undefined))
    return session.closePromise
  }

  dispose(): Promise<void> {
    if (this.#disposePromise) return this.#disposePromise
    this.#disposed = true
    // Seal general runtime requests immediately. A stream-start snapshot may
    // refresh only inside its already-bound run-resolution/cancel capability.
    this.tokenBroker.seal()
    this.#pendingInterrupts.clear()
    const activeStreams = [...this.#activeStreams]
    const retainedSession = this.#threadSession
    const retainedSessionClose = retainedSession
      ? this.#closeThreadSession(retainedSession)
      : Promise.resolve()
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
      if (active.stream !== retainedSession?.thread) {
        closeThreadBestEffort(active.stream)
      }
    }
    void (async () => {
      void retainedSessionClose
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
    if (!pending) {
      this.#pendingInterrupts.delete(threadId)
      return
    }
    const interruptId = safeInterruptIdentifier(pending.interruptId)
    const namespace = safeInterruptNamespace(pending.namespace)
    if (!interruptId || !namespace) {
      throw new Error("승인 요청 식별 정보가 올바르지 않습니다.")
    }
    this.#pendingInterrupts.set(threadId, {
      interruptId,
      namespace,
      value: readRuntimeInterruptProjection(pending.value),
      resumable: pending.resumable !== false,
      when: pending.when === "before" ? "before" : "during",
    })
  }

  readonly stream: LangGraphStreamCallback<LangChainMessage> = async function* (
    this: NativeAgentClient,
    messages: LangChainMessage[],
    config: Parameters<LangGraphStreamCallback<LangChainMessage>>[1]
  ) {
    if (this.#disposed) {
      throw new Error("폐기된 에이전트 런타임은 다시 사용할 수 없습니다.")
    }
    const sourceGeneration = this.#getSourceGeneration()
    if (
      !Number.isSafeInteger(sourceGeneration) ||
      sourceGeneration < 0
    ) {
      throw new AgentProtocolBoundaryError()
    }
    const selectedModel = this.#getSelectedModel?.()
    const active = createActiveStream()
    const signal = AbortSignal.any([
      config.abortSignal,
      active.controller.signal,
    ])
    const streamLease = Symbol("native-stream")
    let threadId: string | undefined
    const runtimeSource = (
      currentThreadId: string | undefined = threadId
    ): RuntimeThreadSource => ({
      generation: sourceGeneration,
      threadId: currentThreadId,
    })
    let thread: ThreadStream | undefined
    let subscription: NativeThreadSubscription | undefined
    let session: NativeThreadSession | undefined
    let looseThreadClosePromise: Promise<void> | undefined
    let runId: string | undefined
    let terminal = false
    let cancelIssued = false
    const presentedInterruptKeys = new Set<string>()
    const nestedInputs = new NestedInputQueue()
    let nestedInputFailed = false
    const liveRunBudget = new LiveRunBudget()
    const seenEventIds = new Set<string>()
    const correlation = new RunCorrelationGate()
    const contentBoundary = new RunEventBoundary(
      correlation,
      liveRunBudget,
      seenEventIds
    )
    const watcherBoundary = new RunEventBoundary(
      correlation,
      liveRunBudget,
      seenEventIds
    )
    const preBarrierWatcherEvents: ProtocolStreamEvent[] = []
    let watcherFailure: Error | undefined
    let unsubscribeThreadEvents: (() => void) | undefined
    const closeLooseThread = () => {
      if (!thread || session) return
      looseThreadClosePromise ??= thread.close().catch(() => undefined)
    }
    const closeOnAbort = () => {
      if (session) {
        void this.#closeThreadSession(session)
      } else {
        closeLooseThread()
      }
    }

    if (this.#streamLease) {
      throw new Error("이미 진행 중인 에이전트 실행이 있습니다.")
    }
    this.#streamLease = streamLease
    this.#activeStreams.add(active)
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
      const boundThreadId = threadId
      const inspection = new InspectionProjector()
      signal.throwIfAborted()
      const previousSession = this.#threadSession
      if (previousSession?.threadId !== boundThreadId) {
        if (previousSession) {
          await this.#closeThreadSession(previousSession)
          signal.throwIfAborted()
        }
        thread = this.client.threads.stream(boundThreadId, {
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
            }, runtimeSource(boundThreadId))
          },
        })
      } else {
        // The pinned SDK pauses root subscriptions at terminal lifecycle and
        // resumes them from submitRun/respondInput for the next turn.
        session = previousSession
        thread = session.thread
        subscription = session.subscription
      }
      active.stream = thread
      signal.addEventListener("abort", closeOnAbort, { once: true })
      if (signal.aborted) closeOnAbort()
      const projectWatcherEvent = (event: ProtocolStreamEvent) => {
        if (event.params.namespace.length === 0) return
        if (event.method === "lifecycle") {
          this.#onActivity?.(
            inspection.consumeLifecycle(event),
            runtimeSource(boundThreadId)
          )
          return
        }
        if (event.method !== "input.requested" || nestedInputFailed) return
        if (!Array.isArray(event.params.namespace)) {
          throw new AgentProtocolBoundaryError()
        }
        try {
          const pending = pendingFromInputEvent(event)
          const existing = this.#pendingInterrupts.get(boundThreadId)
          if (existing) {
            if (pendingInterruptKey(existing) === pendingInterruptKey(pending)) {
              return
            }
            this.#pendingInterrupts.delete(boundThreadId)
            nestedInputFailed = true
            nestedInputs.fail()
            return
          }
          this.#pendingInterrupts.set(boundThreadId, pending)
          nestedInputs.push(pending)
        } catch {
          this.#pendingInterrupts.delete(boundThreadId)
          nestedInputFailed = true
          nestedInputs.fail()
        }
      }
      unsubscribeThreadEvents = thread.onEvent((rawEvent) => {
        if (
          rawEvent.method !== "messages" &&
          rawEvent.method !== "lifecycle" &&
          rawEvent.method !== "input.requested" &&
          rawEvent.method !== "tools" &&
          rawEvent.method !== "custom"
        ) {
          return
        }
        const event = rawEvent as ProtocolStreamEvent
        try {
          if (
            !isRecord(event.params) ||
            !Array.isArray(event.params.namespace)
          ) {
            throw new AgentProtocolBoundaryError()
          }
          if (event.params.namespace.length === 0) {
            if (event.method === "lifecycle") {
              correlation.observeLifecycle(event)
            }
            return
          }
          const accepted = watcherBoundary.queueOrObserve(event)
          if (accepted === undefined) {
            preBarrierWatcherEvents.push(event)
          } else if (accepted) {
            projectWatcherEvent(event)
          }
        } catch {
          watcherFailure = new AgentProtocolBoundaryError()
          nestedInputs.fail()
        }
      })
      if (!subscription) {
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
        signal.throwIfAborted()
        session = {
          subscription,
          thread,
          threadId: boundThreadId,
        }
        this.#threadSession = session
      }

      const pending = config.command
        ? this.#pendingInterrupts.get(boundThreadId)
        : undefined
      if (config.command && !pending) {
        throw new Error("재개할 승인 요청이 없습니다.")
      }
      const runResolution = timeoutController(RESUMED_RUN_ID_WAIT_MS)
      try {
        const runResolutionClient = new Client({
          apiUrl: this.#apiUrl,
          apiKey: null,
          callerOptions: {
            fetch: active.cancellationSnapshot.createRunResolverFetch({
              apiUrl: this.#apiUrl,
              threadId: boundThreadId,
            }) as typeof fetch,
            maxRetries: 0,
          },
        })
        const knownRunIds = new Set(
          (
            await runResolutionClient.runs.list(boundThreadId, {
              limit: 10,
              offset: 0,
              signal: runResolution.controller.signal,
            })
          ).map((run) => run.run_id)
        )
        const submitNonce = createSubmitNonce()
        const runConfigWithSelectedModel = runConfigWithModel(
          config.runConfig,
          selectedModel
        )
        const metadata = runMetadataWithNonce(
          runConfigWithSelectedModel,
          submitNonce
        )
        // Aegra 0.9.24 persists request metadata for tracing but omits it
        // from Run responses. Mirror the internal nonce into standard
        // RunnableConfig metadata, which Aegra persists and returns, so lost
        // command responses can still bind only the exact created run.
        const runConfig = runConfigWithNonce(
          runConfigWithSelectedModel,
          submitNonce
        )
        const commandSettlement = settleCommand(
          config.command
            ? thread.respondInput({
                namespace: pending!.namespace,
                interrupt_id: pending!.interruptId,
                response: config.command.resume,
                config: runConfig,
                metadata,
              })
            : thread.submitRun({
                input: { messages: toRunMessages(messages) },
                config: runConfig,
                metadata,
              })
        )
        const resolverSettlement = settleCommand(
          resolveResumedRunIdOrThrow(
            runResolutionClient,
            boundThreadId,
            knownRunIds,
            submitNonce,
            runResolution.controller.signal
          )
        )

        const first = await Promise.race([
          commandSettlement.then((result) => ({
            source: "command" as const,
            result,
          })),
          resolverSettlement.then((result) => ({
            source: "resolver" as const,
            result,
          })),
        ])
        let command: CommandSettlement
        if (first.source === "resolver") {
          if (first.result.status === "rejected") throw first.result.reason
          runId = first.result.value as string
          command = await awaitCommandSettlement(
            commandSettlement,
            runResolution.controller.signal
          )
        } else {
          command = first.result
          const resolved = await awaitCommandSettlement(
            resolverSettlement,
            runResolution.controller.signal
          )
          if (resolved.status === "rejected") throw resolved.reason
          runId = resolved.value as string
        }
        if (command.status === "rejected") throw command.reason
        if (
          !config.command &&
          isRecord(command.value) &&
          typeof command.value.run_id === "string" &&
          command.value.run_id !== runId
        ) {
          throw new AgentProtocolBoundaryError()
        }
        correlation.configure(runId)
        contentBoundary.configure()
        watcherBoundary.configure()
        for (const event of preBarrierWatcherEvents.splice(0)) {
          if (watcherBoundary.wasAccepted(event)) projectWatcherEvent(event)
        }
        if (watcherFailure) throw watcherFailure
      } finally {
        runResolution.clear()
      }
      signal.throwIfAborted()
      if (config.command) {
        this.#pendingInterrupts.delete(boundThreadId)
        yield { event: "updates", data: { __interrupt__: [] } }
      }

      const projection = new NativeMessageProjection()

      // The root-only content pump is merged locally with only bounded nested
      // input projections received from ThreadStream.onEvent. The watcher
      // never widens message, state, tool, or custom content delivery.
      for await (const item of mergeContentAndNestedInputs(
        subscription,
        nestedInputs,
        signal
      )) {
        if (watcherFailure) throw watcherFailure
        if (item.type === "error") throw item.error
        if (item.type === "pending") {
          presentedInterruptKeys.add(pendingInterruptKey(item.pending))
          yield {
            event: "updates",
            data: {
              __interrupt__: [
                projectPendingInterruptForRuntime(item.pending),
              ],
            },
          }
          continue
        }
        const event = item.event
        signal.throwIfAborted()
        if (!contentBoundary.wasAccepted(event)) continue
        if (event.method === "messages") {
          const activity = inspection.consumeMessage(event)
          if (activity) {
            this.#onActivity?.(activity, runtimeSource(boundThreadId))
          }
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
          const existing = this.#pendingInterrupts.get(boundThreadId)
          if (
            existing &&
            pendingInterruptKey(existing) !== pendingInterruptKey(pending)
          ) {
            this.#pendingInterrupts.delete(boundThreadId)
            throw new Error(
              "동시에 여러 승인 요청이 도착했습니다. 안전하게 재개할 수 없어 중단했습니다."
            )
          }
          if (existing) continue
          this.#pendingInterrupts.set(boundThreadId, pending)
          presentedInterruptKeys.add(pendingInterruptKey(pending))
          yield {
            event: "updates",
            data: {
              __interrupt__: [
                projectPendingInterruptForRuntime(pending),
              ],
            },
          }
          continue
        }
        if (event.method === "tools") {
          const activity = inspection.consumeTool(event)
          this.#onActivity?.(activity, runtimeSource(boundThreadId))
          const result = projectToolResult(activity)
          if (result) yield result
          continue
        }
        if (event.method === "custom") {
          const activity = inspection.consumeCustom(event)
          if (activity) {
            this.#onActivity?.(activity, runtimeSource(boundThreadId))
          }
          continue
        }
        if (event.method === "lifecycle") {
          this.#onActivity?.(
            inspection.consumeLifecycle(event),
            runtimeSource(boundThreadId)
          )
          const root = event.params.namespace.length === 0
          if (root && event.params.data.event === "failed") {
            this.#onError?.(
              new AgentLifecycleError(),
              runtimeSource(boundThreadId)
            )
            yield {
              event: "error",
              data: { message: safeLifecycleError(event) },
            }
          }
          if (
            root &&
            event.params.data.event === "interrupted"
          ) {
            const pending = await waitForInterruptedInput(
              thread,
              this.#pendingInterrupts,
              boundThreadId,
              signal,
              // The pinned Aegra/SDK pair can deliver a nested input first
              // and globally dedupe the later root input. The authoritative
              // guest state response is already server-projected; use the
              // authenticated public SDK state API only after the bounded
              // ThreadStream input barrier is exhausted.
              () =>
                loadPublicRootInterrupt(
                  this.client,
                  boundThreadId,
                  signal
                )
            )
            const key = pendingInterruptKey(pending)
            if (!presentedInterruptKeys.has(key)) {
              presentedInterruptKeys.add(key)
              yield {
                event: "updates",
                data: {
                  __interrupt__: [
                    projectPendingInterruptForRuntime(pending),
                  ],
                },
              }
            }
          }
          if (isRootTerminal(event)) {
            terminal = true
            break
          }
        }
      }
    } catch (error) {
      if (!signal.aborted) {
        const normalized = sanitizeAgentError(error)
        this.#onError?.(normalized, runtimeSource())
        throw normalized
      }
    } finally {
      if (
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
        } catch (error) {
          this.#onError?.(
            sanitizeAgentError(error),
            runtimeSource()
          )
        }
      }
      signal.removeEventListener("abort", closeOnAbort)
      nestedInputs.close()
      unsubscribeThreadEvents?.()
      const keepThreadSession =
        terminal &&
        session !== undefined &&
        this.#threadSession === session &&
        !signal.aborted &&
        !this.#disposed
      if (!keepThreadSession) {
        if (session) {
          await this.#closeThreadSession(session)
        } else {
          await subscription?.unsubscribe().catch(() => undefined)
          closeLooseThread()
          await looseThreadClosePromise
        }
      }
      active.cancellationSnapshot?.dispose()
      this.#activeStreams.delete(active)
      if (this.#streamLease === streamLease) this.#streamLease = undefined
      active.settle()
    }
  }.bind(this)
}

export const nativeClientTesting = {
  assembledMessageToLangChain,
  eventIdBelongsToRun,
  runConfigWithModel,
  inspect(client: NativeAgentClient) {
    const read = nativeClientInspectionReaders.get(client)
    if (!read) throw new Error("Unknown NativeAgentClient")
    return read()
  },
  pendingFromInputEvent,
  pendingFromPublicRootState,
  resolveResumedRunIdOrThrow,
  safeLifecycleError,
}
