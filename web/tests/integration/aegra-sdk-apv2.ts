import { Client, MessageAssembler } from "@langchain/langgraph-sdk"
import { isDeepStrictEqual } from "node:util"
import type {
  CustomEvent,
  Event,
  InputEvent,
  LifecycleEvent,
  MessagesEvent,
} from "@langchain/protocol"

import inspectionFixture from "../../../protocol/fixtures/inspection-events-v1.json"
import {
  NativeMessageProjection,
  projectInputEventForRuntime,
} from "../../components/assistant/runtime/native-client"
import { projectInterruptForUi } from "../../components/assistant/runtime/interrupt-projection"

const INSPECTION_EVENT_NAME = "syshin.rag.inspection.v1"
const PRIVATE_STATE_SENTINEL = "PRIVATE_DEEP_AGENT_STATE_MUST_NOT_REACH_UI"

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim()
  if (!value) {
    throw new Error(`${name} is required`)
  }
  return value
}

function invariant(
  condition: unknown,
  message: string
): asserts condition {
  if (!condition) throw new Error(message)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}

function assembledText(
  event: MessagesEvent,
  assembler: MessageAssembler
): string | undefined {
  const update = assembler.consume(event)
  if (update.kind !== "message-finish") return undefined
  return update.message.blocks
    .flatMap((block) =>
      block.type === "text" && typeof block.text === "string"
        ? [block.text]
        : []
    )
    .join("")
}

const apiUrl = requiredEnvironment("AEGRA_JS_E2E_BASE_URL")
const token = requiredEnvironment("AEGRA_JS_E2E_TOKEN")
const threadId = requiredEnvironment("AEGRA_JS_E2E_THREAD_ID")
const observedStreamFilters: Record<string, unknown>[] = []
const recordingFetch = Object.assign(
  async (
    input: Parameters<typeof fetch>[0],
    init?: Parameters<typeof fetch>[1]
  ) => {
    const rawUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url
    const url = new URL(rawUrl)
    if (
      url.pathname.endsWith(`/threads/${threadId}/stream/events`) &&
      typeof init?.body === "string"
    ) {
      const body = JSON.parse(init.body) as unknown
      if (isRecord(body)) observedStreamFilters.push(body)
    }
    return fetch(input, init)
  },
  { preconnect: fetch.preconnect.bind(fetch) }
)
const client = new Client({
  apiUrl,
  apiKey: null,
  streamProtocol: "v2",
  defaultHeaders: {
    Authorization: `Bearer ${token}`,
  },
  callerOptions: {
    fetch: recordingFetch,
    maxRetries: 0,
  },
})
const CHANNELS = [
  "messages",
  "tools",
  "lifecycle",
  "input",
  "custom",
] as const

async function openPhase() {
  const thread = client.threads.stream(threadId, {
    assistantId: "fixture",
    transport: "sse",
    fetch: recordingFetch,
    maxReconnectAttempts: 0,
  })
  const unsubscribeEvent = thread.onEvent((event) => {
    rawPrivateStateObserved ||= JSON.stringify(event).includes(
      PRIVATE_STATE_SENTINEL
    )
    if (
      event.method === "lifecycle" &&
      event.params.namespace.length > 0
    ) {
      sawNestedLifecycle = true
    }
    if (
      event.method === "input.requested" &&
      event.params.namespace.length > 0
    ) {
      acceptNestedInputEvent(event)
    }
  })
  const subscription = await thread.subscribe(CHANNELS, {
    namespaces: [[]],
    depth: 0,
  })
  return {
    subscription,
    thread,
    unsubscribeEvent,
  }
}

const assembler = new MessageAssembler()
const nativeMessages = new NativeMessageProjection()
const observedEvents: Event[] = []
const observedEventKeys = new Set<string>()
const runtimeOutput: unknown[] = []
const inspectionPayloads: unknown[] = []
let interruptTarget:
  | {
      interruptId: string
      namespace: string[]
    }
  | undefined
let assistantText: string | undefined
let interruptProjectionRecognized = false
let interruptProjection: unknown
let sawNestedLifecycle = false
let sawNestedInputOnContent = false
let sawToolStart = false
let sawToolFinish = false
let sawRootCompletion = false
let rawPrivateStateObserved = false
let watcherFailure: Error | undefined
const phases: Awaited<ReturnType<typeof openPhase>>[] = []

function interruptKey(target: {
  interruptId: string
  namespace: string[]
}): string {
  return `${target.namespace.join("\u001f")}\u001e${target.interruptId}`
}

function acceptProjectedInterrupt(
  target: { interruptId: string; namespace: string[] },
  projected: ReturnType<typeof projectInputEventForRuntime>
): void {
  try {
    invariant(target.namespace.length > 0, "nested interrupt namespace was empty")
    const current = interruptTarget
    if (current) {
      invariant(
        interruptKey(current) === interruptKey(target),
        "multiple concurrent interrupts were observed"
      )
      return
    }
    interruptTarget = {
      interruptId: target.interruptId,
      namespace: [...target.namespace],
    }
    interruptProjectionRecognized =
      isRecord(projected.value) && projected.value.recognized === true
    interruptProjection = projected.value
    runtimeOutput.push({
      event: "updates",
      data: {
        __interrupt__: [projected],
      },
    })
  } catch (error) {
    watcherFailure =
      error instanceof Error ? error : new Error("nested input watcher failed")
  }
}

function acceptNestedInputEvent(event: InputEvent): void {
  try {
    acceptProjectedInterrupt(
      {
        interruptId: event.params.data.interrupt_id,
        namespace: [...event.params.namespace],
      },
      projectInputEventForRuntime(event)
    )
  } catch (error) {
    watcherFailure =
      error instanceof Error ? error : new Error("nested input watcher failed")
  }
}

async function waitForNestedInterrupt(
  thread: Awaited<ReturnType<typeof openPhase>>["thread"]
): Promise<void> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (watcherFailure) throw watcherFailure
    const unique = new Map<
      string,
      {
        interruptId: string
        namespace: string[]
        payload: unknown
      }
    >()
    for (const candidate of [...thread.interrupts]) {
      const target = {
        interruptId: candidate.interruptId,
        namespace: [...candidate.namespace],
      }
      unique.set(interruptKey(target), {
        ...target,
        payload: candidate.payload,
      })
    }
    invariant(
      unique.size <= 1,
      "SDK watcher retained multiple concurrent interrupts"
    )
    const candidate = unique.values().next().value
    if (candidate) {
      acceptProjectedInterrupt(
        {
          interruptId: candidate.interruptId,
          namespace: candidate.namespace,
        },
        {
          value: projectInterruptForUi(candidate.payload),
          resumable: true,
          when: "during",
          ns: candidate.namespace,
        }
      )
      // Hold a short stable window so a second pre-terminal input cannot
      // arrive just after the first one is accepted.
      await new Promise((resolve) => setTimeout(resolve, 50))
      invariant(
        new Set(
          thread.interrupts.map((entry) =>
            interruptKey({
              interruptId: entry.interruptId,
              namespace: entry.namespace,
            })
          )
        ).size === 1,
        "SDK watcher retained multiple concurrent interrupts"
      )
      return
    }
    await new Promise((resolve) => setTimeout(resolve, 10))
  }
  throw new Error("SDK watcher did not capture the nested interrupt")
}

function recordEvent(event: Event): "interrupted" | "completed" | undefined {
  const replayKey =
    event.event_id ??
    (typeof event.seq === "number"
      ? `${event.seq}:${event.method}`
      : undefined)
  if (replayKey && observedEventKeys.has(replayKey)) return undefined
  if (replayKey) observedEventKeys.add(replayKey)
  observedEvents.push(event)
  rawPrivateStateObserved ||= JSON.stringify(event).includes(
    PRIVATE_STATE_SENTINEL
  )
  if (event.method === "messages") {
    assistantText = assembledText(event, assembler) ?? assistantText
    const projected = nativeMessages.consume(event)
    if (projected) runtimeOutput.push(projected)
    return undefined
  }
  if (event.method === "custom") {
    const custom = event as CustomEvent
    if (custom.params.data.name === INSPECTION_EVENT_NAME) {
      inspectionPayloads.push(custom.params.data.payload)
    }
    return undefined
  }
  if (event.method === "tools") {
    sawToolStart ||= event.params.data.event === "tool-started"
    sawToolFinish ||= event.params.data.event === "tool-finished"
    return undefined
  }
  if (event.method === "input.requested") {
    sawNestedInputOnContent ||= event.params.namespace.length > 0
    return undefined
  }
  if (event.method !== "lifecycle") return undefined
  const lifecycle = event as LifecycleEvent
  sawNestedLifecycle ||= lifecycle.params.namespace.length > 0
  if (lifecycle.params.namespace.length !== 0) return undefined
  if (lifecycle.params.data.event === "interrupted") return "interrupted"
  if (lifecycle.params.data.event === "completed") {
    sawRootCompletion = true
    return "completed"
  }
  return undefined
}

async function closePhase(
  phase: Awaited<ReturnType<typeof openPhase>>
): Promise<void> {
  // The isolated Aegra fixture shortens its post-terminal SSE grace to 50 ms.
  // Let both the root content stream and lifecycle-only watcher exhaust
  // naturally so the integration also proves their DB sessions are returned.
  await new Promise((resolve) => setTimeout(resolve, 100))
  phase.unsubscribeEvent()
  await phase.subscription.unsubscribe().catch(() => undefined)
  await phase.thread.close().catch(() => undefined)
}

try {
  const initial = await openPhase()
  phases.push(initial)
  const started = await initial.thread.submitRun({
    input: {
      messages: [
        {
          type: "human",
          content: "Official JavaScript SDK APv2 persistence proof",
        },
      ],
    },
  })
  invariant(
    typeof started.run_id === "string" && started.run_id.length > 0,
    "submitRun did not return a run id"
  )

  let initialTerminal: ReturnType<typeof recordEvent>
  for await (const event of initial.subscription) {
    initialTerminal = recordEvent(event)
    if (initialTerminal) break
  }
  invariant(initialTerminal === "interrupted", "initial run did not interrupt")
  await waitForNestedInterrupt(initial.thread)
  invariant(watcherFailure === undefined, "nested input watcher failed")
  invariant(interruptTarget !== undefined, "input.requested was not observed")
  await closePhase(initial)

  const resumed = await openPhase()
  phases.push(resumed)
  await resumed.thread.respondInput({
    namespace: interruptTarget.namespace,
    interrupt_id: interruptTarget.interruptId,
    response: "approved-via-js-sdk",
  })
  let resumedTerminal: ReturnType<typeof recordEvent>
  let sawResumedRunning = false
  while (!resumedTerminal) {
    for await (const event of resumed.subscription) {
      if (
        event.method === "lifecycle" &&
        event.params.namespace.length === 0 &&
        event.params.data.event === "running"
      ) {
        sawResumedRunning = true
      }
      const terminal = recordEvent(event)
      if (terminal === "completed") {
        resumedTerminal = terminal
        break
      }
      if (terminal === "interrupted" && !sawResumedRunning) {
        continue
      }
    }
    if (resumedTerminal || !resumed.subscription.isPaused) break
    await resumed.subscription.waitForResume()
  }
  invariant(
    resumedTerminal === "completed",
    `resumed run did not complete; observed ${observedEvents
      .filter((event) => event.method === "lifecycle")
      .map((event) => {
        const lifecycle = event as LifecycleEvent
        return `${lifecycle.params.namespace.join("/") || "root"}:${lifecycle.params.data.event}`
      })
      .join(", ")}`
  )

  const canonicalInspection =
    inspectionFixture.records[0].payload.params.data.payload
  invariant(
    inspectionPayloads.length === 1,
    `expected one inspection event; observed ${observedEvents
      .map((event) =>
        event.method === "custom"
          ? `custom:${String((event as CustomEvent).params.data.name)}`
          : event.method
      )
      .join(", ")}`
  )
  invariant(
    isDeepStrictEqual(inspectionPayloads[0], canonicalInspection),
    "inspection event did not match the canonical fixture"
  )
  invariant(interruptProjectionRecognized, "unexpected interrupt projection")
  invariant(
    isDeepStrictEqual(interruptProjection, {
      recognized: true,
      kind: "approval",
      title: "Deterministic fixture approval",
      prompt: "Continue the deterministic Aegra fixture?",
      inputHint: "수정할 내용을 입력해 재개",
    }),
    "interrupt projection exceeded the reviewed UI contract"
  )
  invariant(
    interruptTarget.namespace.length > 0 &&
      interruptTarget.namespace[0]?.startsWith("nested_subgraph:"),
    "nested interrupt namespace was not preserved"
  )
  invariant(
    !sawNestedInputOnContent,
    "root-only content subscription received a nested input event"
  )
  invariant(sawToolStart && sawToolFinish, "tool lifecycle was incomplete")
  invariant(sawNestedLifecycle, "nested lifecycle was not observed")
  invariant(sawRootCompletion, "root lifecycle did not complete")
  invariant(assistantText === "fixture-complete", "message assembly failed")
  invariant(
    !rawPrivateStateObserved,
    "root-only APv2 streams exposed private graph state"
  )

  const serializedRuntimeOutput = JSON.stringify(runtimeOutput)
  for (const forbidden of [
    PRIVATE_STATE_SENTINEL,
    "private_state",
    "nested_result",
    "todos",
    "files",
    "scratch",
  ]) {
    invariant(
      !serializedRuntimeOutput.includes(forbidden),
      `native runtime leaked forbidden APv2 state: ${forbidden}`
    )
  }

  const sequenced = observedEvents.flatMap((event) =>
    typeof event.seq === "number" ? [event.seq] : []
  )
  invariant(
    sequenced.every(
      (sequence, index) => index === 0 || sequence > sequenced[index - 1]
    ),
    "APv2 sequence numbers were not strictly increasing"
  )

  const contentFilters = observedStreamFilters.filter(
    (filter) =>
      isDeepStrictEqual(filter.channels, [...CHANNELS]) &&
      isDeepStrictEqual(filter.namespaces, [[]]) &&
      filter.depth === 0
  )
  const watcherFilters = observedStreamFilters.filter(
    (filter) =>
      isDeepStrictEqual(filter.channels, ["lifecycle", "input"]) &&
      filter.namespaces === undefined &&
      filter.depth === undefined
  )
  invariant(
    observedStreamFilters.length === 4 &&
      contentFilters.length === 2 &&
      watcherFilters.length === 2,
    `unexpected APv2 SSE connection filters: ${JSON.stringify(observedStreamFilters)}`
  )

  console.log(
    JSON.stringify({
      assistantText,
      inspectionEvents: inspectionPayloads.length,
      protocol: "v2",
      interruptProjectionRecognized,
      nestedInputOnContent: sawNestedInputOnContent,
      nestedInterruptNamespace: interruptTarget.namespace.length > 0,
      rawPrivateStateObserved,
      runtimeBoundarySafe: true,
      sawNestedLifecycle,
      sawToolFinish,
      sawToolStart,
      streamConnections: observedStreamFilters.length,
      threadId,
    })
  )
} finally {
  for (const phase of phases.reverse()) {
    await closePhase(phase)
  }
}
