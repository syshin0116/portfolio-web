import {
  RefreshingAgentToken,
  type AgentOnRequest,
  type AgentRequestPurpose,
} from "./auth"
import { parseServerSentEvents, type ServerSentEvent } from "./sse"
import type {
  AgentStatus,
  Channel,
  Checkpoint,
  CheckpointRef,
  Command,
  CommandResponse,
  ContentBlockDelta,
  ErrorCode,
  ErrorResponse,
  Event,
  EventStreamRequest,
  LifecycleCause,
  MessageMetadata,
  MessageRole,
  Namespace,
  UsageInfo,
} from "./protocol-types"

export const AGENT_PROTOCOL_UPSTREAM_THREAD_STREAM_SUFFIX = "/stream"
export const AEGRA_THREAD_EVENT_STREAM_SUFFIX = "/stream/events"
export const AEGRA_THREAD_COMMANDS_SUFFIX = "/commands"
export const AEGRA_EVENT_STREAM_FEATURE_FLAG = "FF_V2_EVENT_STREAMING"

const MAX_DIAGNOSTICS = 100
const AGENT_STATUSES = new Set<AgentStatus>([
  "started",
  "running",
  "completed",
  "failed",
  "interrupted",
])

type JsonObject = Record<string, unknown>

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isSequence(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0
}

function isNamespace(value: unknown): value is Namespace {
  return (
    Array.isArray(value) &&
    value.every((segment) => typeof segment === "string")
  )
}

function isAgentStatus(value: unknown): value is AgentStatus {
  return typeof value === "string" && AGENT_STATUSES.has(value as AgentStatus)
}

function copyNamespace(namespace: Namespace): Namespace {
  return [...namespace]
}

function eventCoordinates(event: Event): {
  method: string
  seq: number
  eventId?: string
} {
  return {
    method: String(event.method),
    seq: Number(event.seq),
    ...(event.event_id === undefined ? {} : { eventId: event.event_id }),
  }
}

export class AgentProtocolDecodeError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options)
    this.name = "AgentProtocolDecodeError"
  }
}

function normalizeAegraHitlEvent(payload: JsonObject): JsonObject {
  if (payload.method !== "input.requested") return payload
  if (!isObject(payload.params) || !isObject(payload.params.data)) return payload

  const data = payload.params.data
  if ("value" in data && "payload" in data) {
    throw new AgentProtocolDecodeError(
      "Aegra input.requested contains both value and payload; translation is ambiguous"
    )
  }
  if (!("value" in data)) return payload

  const value = data["value"]
  const translatedData: JsonObject = { ...data, payload: value }
  delete translatedData.value
  return {
    ...payload,
    params: {
      ...payload.params,
      data: translatedData,
    },
  }
}

function validateEventEnvelope(payload: JsonObject): asserts payload is Event {
  if (payload.type !== "event") {
    throw new AgentProtocolDecodeError(
      "Agent event envelope must have type 'event'"
    )
  }
  if (typeof payload.method !== "string" || payload.method.length === 0) {
    throw new AgentProtocolDecodeError(
      "Agent event envelope requires a method"
    )
  }
  if (!isSequence(payload.seq)) {
    throw new AgentProtocolDecodeError(
      "Agent event envelope requires a non-negative safe integer seq"
    )
  }
  if (
    payload.event_id !== undefined &&
    (typeof payload.event_id !== "string" || payload.event_id.length === 0)
  ) {
    throw new AgentProtocolDecodeError(
      "Agent event_id must be a non-empty string when present"
    )
  }
  if (!isObject(payload.params)) {
    throw new AgentProtocolDecodeError("Agent event requires params")
  }
  if (!isNamespace(payload.params.namespace)) {
    throw new AgentProtocolDecodeError(
      "Agent event params.namespace must be a string array"
    )
  }
  if (
    typeof payload.params.timestamp !== "number" ||
    !Number.isFinite(payload.params.timestamp)
  ) {
    throw new AgentProtocolDecodeError(
      "Agent event params.timestamp must be a finite number"
    )
  }
  if (!("data" in payload.params)) {
    throw new AgentProtocolDecodeError("Agent event params requires data")
  }

  if (payload.method === "input.requested") {
    if (!isObject(payload.params.data)) {
      throw new AgentProtocolDecodeError(
        "input.requested data must be an object"
      )
    }
    if (
      typeof payload.params.data.interrupt_id !== "string" ||
      payload.params.data.interrupt_id.length === 0
    ) {
      throw new AgentProtocolDecodeError(
        "input.requested requires interrupt_id"
      )
    }
    if (!("payload" in payload.params.data)) {
      throw new AgentProtocolDecodeError(
        "input.requested requires the normalized payload field"
      )
    }
    if ("value" in payload.params.data) {
      throw new AgentProtocolDecodeError(
        "Aegra HITL value must not cross the transport boundary"
      )
    }
  }
}

/**
 * Parses the Aegra 0.9.24 dialect into the locked official generated shape.
 *
 * The only dialect rewrite is HITL `data.value` -> `data.payload`. Aegra uses
 * numeric `seq` as the SSE id while the upstream contract describes
 * `event_id`; both are accepted, and any third value is rejected to protect
 * replay cursor integrity.
 */
export function decodeAegraEvent(
  raw: unknown,
  sse?: Pick<ServerSentEvent, "id" | "event">
): Event {
  if (!isObject(raw)) {
    throw new AgentProtocolDecodeError("SSE data must decode to an object")
  }
  const payload = normalizeAegraHitlEvent(raw)
  validateEventEnvelope(payload)

  if (sse?.event !== undefined && sse.event !== payload.method) {
    throw new AgentProtocolDecodeError(
      `SSE event ${JSON.stringify(sse.event)} does not match envelope method ${JSON.stringify(payload.method)}`
    )
  }
  if (sse?.id !== undefined) {
    const validIds = new Set([String(payload.seq)])
    if (payload.event_id !== undefined) validIds.add(payload.event_id)
    if (!validIds.has(sse.id)) {
      throw new AgentProtocolDecodeError(
        `SSE id ${JSON.stringify(sse.id)} matches neither seq nor event_id`
      )
    }
  }
  return payload
}

const ERROR_CODES = new Set<ErrorCode>([
  "invalid_argument",
  "unknown_command",
  "unknown_error",
  "no_such_run",
  "no_such_subscription",
  "no_such_namespace",
  "no_such_interrupt",
  "no_such_checkpoint",
  "permission_denied",
  "not_supported",
])

export function decodeCommandResponse(
  raw: unknown,
  expectedCommandId?: number
): CommandResponse | ErrorResponse {
  if (!isObject(raw)) {
    throw new AgentProtocolDecodeError(
      "Command response must decode to an object"
    )
  }
  if (raw.type !== "success" && raw.type !== "error") {
    throw new AgentProtocolDecodeError(
      "Command response type must be success or error"
    )
  }
  if (
    raw.id !== null &&
    (!isSequence(raw.id) || (expectedCommandId !== undefined && raw.id !== expectedCommandId))
  ) {
    throw new AgentProtocolDecodeError(
      "Command response id does not correlate with the request"
    )
  }
  if (
    expectedCommandId !== undefined &&
    raw.type === "success" &&
    raw.id !== expectedCommandId
  ) {
    throw new AgentProtocolDecodeError(
      "Successful command response must correlate with the request"
    )
  }
  if (raw.meta !== undefined && !isObject(raw.meta)) {
    throw new AgentProtocolDecodeError("Command response meta must be an object")
  }
  if (
    isObject(raw.meta) &&
    raw.meta.applied_through_seq !== undefined &&
    !isSequence(raw.meta.applied_through_seq)
  ) {
    throw new AgentProtocolDecodeError(
      "Command response applied_through_seq must be a non-negative safe integer"
    )
  }

  if (raw.type === "success") {
    if (!isObject(raw.result)) {
      throw new AgentProtocolDecodeError(
        "Successful command response requires an object result"
      )
    }
    return raw as CommandResponse
  }

  if (
    typeof raw.error !== "string" ||
    !ERROR_CODES.has(raw.error as ErrorCode) ||
    typeof raw.message !== "string"
  ) {
    throw new AgentProtocolDecodeError(
      "Error command response requires a known error code and message"
    )
  }
  return raw as ErrorResponse
}

export interface AgentReplayCursor {
  seq: number
  eventId?: string
}

export interface AgentEventStreamRequest {
  channels: Channel[]
  namespaces?: Namespace[]
  depth?: number
}

export function eventStreamRequestFor(
  request: AgentEventStreamRequest,
  cursor?: AgentReplayCursor | null
): EventStreamRequest {
  if ("since" in request) {
    throw new AgentProtocolDecodeError(
      "Replay sequence must come from the reducer cursor"
    )
  }
  if (
    !Array.isArray(request.channels) ||
    request.channels.length === 0 ||
    request.channels.some(
      (channel) => typeof channel !== "string" || channel.length === 0
    )
  ) {
    throw new AgentProtocolDecodeError(
      "Event stream requires at least one channel"
    )
  }
  if (
    request.namespaces !== undefined &&
    (!Array.isArray(request.namespaces) ||
      request.namespaces.some((namespace) => !isNamespace(namespace)))
  ) {
    throw new AgentProtocolDecodeError(
      "Event stream namespaces must be string-array paths"
    )
  }
  if (
    request.depth !== undefined &&
    (!Number.isSafeInteger(request.depth) || request.depth < 0)
  ) {
    throw new AgentProtocolDecodeError(
      "Event stream depth must be a non-negative safe integer"
    )
  }
  if (cursor !== undefined && cursor !== null && !isSequence(cursor.seq)) {
    throw new AgentProtocolDecodeError(
      "Replay cursor requires a non-negative safe integer seq"
    )
  }
  if (
    cursor?.eventId !== undefined &&
    (typeof cursor.eventId !== "string" || cursor.eventId.length === 0)
  ) {
    throw new AgentProtocolDecodeError(
      "Replay cursor eventId must be a non-empty string when present"
    )
  }

  const result: EventStreamRequest = {
    channels: [...request.channels],
    ...(request.namespaces === undefined
      ? {}
      : {
          namespaces: request.namespaces.map((namespace) => [
            ...namespace,
          ]),
        }),
    ...(request.depth === undefined ? {} : { depth: request.depth }),
    ...(cursor === undefined || cursor === null ? {} : { since: cursor.seq }),
  }
  return result
}

export type RuntimeMessageRole = "assistant" | "user" | "system"
export type RuntimeMessageStatus = "running" | "complete" | "incomplete"

export interface AgentRuntimeContentBlock {
  index: number
  status: "streaming" | "complete"
  content: JsonObject & { type: string }
}

export interface AgentRuntimeMessage {
  /** Namespace-qualified stable key for UI stores. */
  key: string
  /** Protocol message id, which is only guaranteed unique in its namespace. */
  id: string
  role: RuntimeMessageRole
  protocolRole: MessageRole
  namespace: Namespace
  node?: string
  timestamp: number
  metadata?: MessageMetadata
  content: AgentRuntimeContentBlock[]
  status: RuntimeMessageStatus
  usage?: UsageInfo
  error?: { message: string; code?: string }
}

export interface AgentRuntimeTool {
  key: string
  toolCallId: string
  name: string
  namespace: Namespace
  node?: string
  timestamp: number
  status: "running" | "completed" | "failed"
  input?: unknown
  outputText: string
  output?: unknown
  error?: { message: string; code?: string }
}

export interface AgentRuntimeAgent {
  key: string
  parentKey?: string
  namespace: Namespace
  depth: number
  status: AgentStatus
  graphName?: string
  cause?: LifecycleCause
  checkpoint?: CheckpointRef
  error?: string
  timestamp: number
}

export interface AgentRuntimeCheckpoint extends Checkpoint {
  namespace: Namespace
  timestamp: number
}

export interface AgentRuntimeTimelineItem {
  key: string
  namespace: Namespace
  timestamp: number
  data: unknown
}

export interface AgentRuntimeInterrupt {
  key: string
  interruptId: string
  namespace: Namespace
  timestamp: number
  payload: unknown
  status: "pending" | "responded"
}

export interface AgentRuntimeSnapshot {
  namespace: Namespace
  timestamp: number
  data: unknown
}

export type AgentRuntimeDiagnosticKind =
  | "unknown-event"
  | "malformed"
  | "stale-or-duplicate"

export interface AgentRuntimeDiagnostic {
  kind: AgentRuntimeDiagnosticKind
  message: string
  method?: string
  seq?: number
  eventId?: string
}

export interface AgentRuntimeError {
  source: "command" | "lifecycle" | "message"
  commandId?: number
  code: string
  message: string
}

export interface AgentRuntimeRun {
  status: "idle" | AgentStatus
  runId?: string
  graphName?: string
  checkpoint?: CheckpointRef
}

export interface AgentRuntimeCommandState {
  id: number
  method: string
  type: "success" | "error"
  appliedThroughSeq?: number
}

export interface AgentRuntimeState {
  run: AgentRuntimeRun
  cursor: AgentReplayCursor | null
  messages: AgentRuntimeMessage[]
  tools: AgentRuntimeTool[]
  agents: AgentRuntimeAgent[]
  checkpoints: AgentRuntimeCheckpoint[]
  tasks: AgentRuntimeTimelineItem[]
  interrupts: AgentRuntimeInterrupt[]
  values: AgentRuntimeSnapshot[]
  updates: AgentRuntimeTimelineItem[]
  custom: AgentRuntimeTimelineItem[]
  diagnostics: AgentRuntimeDiagnostic[]
  error?: AgentRuntimeError
  lastCommand?: AgentRuntimeCommandState
  /**
   * Protocol lifecycle bookkeeping. UI adapters should treat this as opaque.
   */
  activeMessageKeys: Record<string, string>
}

export function createAgentRuntimeState(): AgentRuntimeState {
  return {
    run: { status: "idle" },
    cursor: null,
    messages: [],
    tools: [],
    agents: [],
    checkpoints: [],
    tasks: [],
    interrupts: [],
    values: [],
    updates: [],
    custom: [],
    diagnostics: [],
    activeMessageKeys: {},
  }
}

function namespaceStorageKey(namespace: Namespace): string {
  return JSON.stringify(namespace)
}

function agentKey(namespace: Namespace): string {
  if (namespace.length === 0) return "root"
  return `root/${namespace.map(encodeURIComponent).join("/")}`
}

function messageSourceKey(namespace: Namespace, node?: string): string {
  return `${namespaceStorageKey(namespace)}:${node ?? ""}`
}

function messageKey(namespace: Namespace, id: string): string {
  return `${namespaceStorageKey(namespace)}:${id}`
}

function toolKey(namespace: Namespace, toolCallId: string): string {
  return `${namespaceStorageKey(namespace)}:${toolCallId}`
}

function interruptKey(namespace: Namespace, interruptId: string): string {
  return `${namespaceStorageKey(namespace)}:${interruptId}`
}

function diagnostic(
  state: AgentRuntimeState,
  item: AgentRuntimeDiagnostic
): AgentRuntimeState {
  return {
    ...state,
    diagnostics: [...state.diagnostics, item].slice(-MAX_DIAGNOSTICS),
  }
}

function malformed(
  state: AgentRuntimeState,
  event: Event,
  message: string
): AgentRuntimeState {
  return diagnostic(state, {
    kind: "malformed",
    message,
    ...eventCoordinates(event),
  })
}

function runtimeRole(role: MessageRole): RuntimeMessageRole {
  if (role === "ai") return "assistant"
  if (role === "human") return "user"
  return "system"
}

function eventParams(event: Event): {
  namespace: Namespace
  timestamp: number
  node?: string
  data: unknown
} {
  const params = event.params as JsonObject
  return {
    namespace: copyNamespace(params.namespace as Namespace),
    timestamp: params.timestamp as number,
    ...(typeof params.node === "string" ? { node: params.node } : {}),
    data: params.data,
  }
}

function updateMessage(
  state: AgentRuntimeState,
  event: Event,
  key: string,
  update: (message: AgentRuntimeMessage) => AgentRuntimeMessage
): AgentRuntimeState {
  const index = state.messages.findIndex((message) => message.key === key)
  if (index === -1) {
    return malformed(state, event, `No active runtime message for ${key}`)
  }
  const messages = [...state.messages]
  messages[index] = update(messages[index])
  return { ...state, messages }
}

function reduceMessageEvent(
  state: AgentRuntimeState,
  event: Event
): AgentRuntimeState {
  const { namespace, timestamp, node, data } = eventParams(event)
  if (!isObject(data) || typeof data.event !== "string") {
    return malformed(state, event, "messages event requires a data.event")
  }
  const sourceKey = messageSourceKey(namespace, node)

  if (data.event === "message-start") {
    if (
      typeof data.id !== "string" ||
      data.id.length === 0 ||
      !["ai", "human", "system"].includes(String(data.role))
    ) {
      return malformed(
        state,
        event,
        "message-start requires id and a known role"
      )
    }
    const id = data.id
    const key = messageKey(namespace, id)
    const activeMessageKeys = {
      ...state.activeMessageKeys,
      [sourceKey]: key,
    }
    if (state.messages.some((message) => message.key === key)) {
      return diagnostic(
        { ...state, activeMessageKeys },
        {
          kind: "stale-or-duplicate",
          message: `Message ${key} was already started`,
          ...eventCoordinates(event),
        }
      )
    }
    const protocolRole = data.role as MessageRole
    return {
      ...state,
      activeMessageKeys,
      messages: [
        ...state.messages,
        {
          key,
          id,
          role: runtimeRole(protocolRole),
          protocolRole,
          namespace,
          ...(node === undefined ? {} : { node }),
          timestamp,
          ...(isObject(data.metadata)
            ? { metadata: data.metadata as MessageMetadata }
            : {}),
          content: [],
          status: "running",
        },
      ],
    }
  }

  const activeKey = state.activeMessageKeys[sourceKey]
  if (!activeKey) {
    return malformed(
      state,
      event,
      `Message lifecycle ${data.event} arrived without message-start`
    )
  }

  if (data.event === "content-block-start") {
    if (
      !Number.isSafeInteger(data.index) ||
      Number(data.index) < 0 ||
      !isObject(data.content) ||
      typeof data.content.type !== "string"
    ) {
      return malformed(
        state,
        event,
        "content-block-start requires index and typed content"
      )
    }
    const index = Number(data.index)
    return updateMessage(state, event, activeKey, (message) => {
      if (message.content.some((block) => block.index === index)) {
        return message
      }
      return {
        ...message,
        content: [
          ...message.content,
          {
            index,
            status: "streaming" as const,
            content: data.content as JsonObject & { type: string },
          },
        ].sort((left, right) => left.index - right.index),
      }
    })
  }

  if (data.event === "content-block-delta") {
    if (
      !Number.isSafeInteger(data.index) ||
      Number(data.index) < 0 ||
      !isObject(data.delta) ||
      typeof data.delta.type !== "string"
    ) {
      return malformed(
        state,
        event,
        "content-block-delta requires index and typed delta"
      )
    }
    const index = Number(data.index)
    const message = state.messages.find((item) => item.key === activeKey)
    const block = message?.content.find((item) => item.index === index)
    if (!block) {
      return malformed(
        state,
        event,
        `content-block-delta has no block at index ${index}`
      )
    }

    const delta = data.delta as ContentBlockDelta
    let content: JsonObject & { type: string }
    if (delta.type === "text-delta" && typeof delta.text === "string") {
      content = {
        ...block.content,
        text: `${typeof block.content.text === "string" ? block.content.text : ""}${delta.text}`,
      }
    } else if (
      delta.type === "reasoning-delta" &&
      typeof delta.reasoning === "string"
    ) {
      content = {
        ...block.content,
        reasoning: `${typeof block.content.reasoning === "string" ? block.content.reasoning : ""}${delta.reasoning}`,
      }
    } else if (delta.type === "data-delta" && typeof delta.data === "string") {
      content = {
        ...block.content,
        base64: `${typeof block.content.base64 === "string" ? block.content.base64 : ""}${delta.data}`,
      }
    } else if (delta.type === "block-delta" && isObject(delta.fields)) {
      content = {
        ...block.content,
        ...delta.fields,
        type:
          typeof delta.fields.type === "string"
            ? delta.fields.type
            : block.content.type,
      }
    } else {
      return malformed(
        state,
        event,
        `Unsupported or malformed content delta ${String(delta.type)}`
      )
    }

    return updateMessage(state, event, activeKey, (current) => ({
      ...current,
      content: current.content.map((item) =>
        item.index === index ? { ...item, content } : item
      ),
    }))
  }

  if (data.event === "content-block-finish") {
    if (
      !Number.isSafeInteger(data.index) ||
      Number(data.index) < 0 ||
      !isObject(data.content) ||
      typeof data.content.type !== "string"
    ) {
      return malformed(
        state,
        event,
        "content-block-finish requires index and typed content"
      )
    }
    const index = Number(data.index)
    const message = state.messages.find((item) => item.key === activeKey)
    if (!message?.content.some((item) => item.index === index)) {
      return malformed(
        state,
        event,
        `content-block-finish has no block at index ${index}`
      )
    }
    return updateMessage(state, event, activeKey, (current) => ({
      ...current,
      content: current.content.map((item) =>
        item.index === index
          ? {
              index,
              status: "complete",
              content: data.content as JsonObject & { type: string },
            }
          : item
      ),
    }))
  }

  if (data.event === "message-finish") {
    const activeMessageKeys = { ...state.activeMessageKeys }
    delete activeMessageKeys[sourceKey]
    const next = updateMessage(state, event, activeKey, (message) => ({
      ...message,
      status: "complete",
      ...(isObject(data.usage) ? { usage: data.usage as UsageInfo } : {}),
    }))
    return { ...next, activeMessageKeys }
  }

  if (data.event === "error") {
    if (typeof data.message !== "string") {
      return malformed(state, event, "message error requires a message")
    }
    const activeMessageKeys = { ...state.activeMessageKeys }
    delete activeMessageKeys[sourceKey]
    const next = updateMessage(state, event, activeKey, (message) => ({
      ...message,
      status: "incomplete",
      error: {
        message: data.message as string,
        ...(typeof data.code === "string" ? { code: data.code } : {}),
      },
    }))
    return {
      ...next,
      activeMessageKeys,
      error: {
        source: "message",
        code: typeof data.code === "string" ? data.code : "message_error",
        message: data.message,
      },
    }
  }

  return malformed(
    state,
    event,
    `Unknown messages lifecycle ${data.event}`
  )
}

function reduceToolEvent(
  state: AgentRuntimeState,
  event: Event
): AgentRuntimeState {
  const { namespace, timestamp, node, data } = eventParams(event)
  if (
    !isObject(data) ||
    typeof data.event !== "string" ||
    typeof data.tool_call_id !== "string"
  ) {
    return malformed(
      state,
      event,
      "tools event requires event and tool_call_id"
    )
  }
  const key = toolKey(namespace, data.tool_call_id)
  const index = state.tools.findIndex((tool) => tool.key === key)

  if (data.event === "tool-started") {
    if (typeof data.tool_name !== "string") {
      return malformed(state, event, "tool-started requires tool_name")
    }
    const started: AgentRuntimeTool = {
      key,
      toolCallId: data.tool_call_id,
      name: data.tool_name,
      namespace,
      ...(node === undefined ? {} : { node }),
      timestamp,
      status: "running",
      ...("input" in data ? { input: data.input } : {}),
      outputText: "",
    }
    const tools = [...state.tools]
    if (index === -1) tools.push(started)
    else tools[index] = started
    return { ...state, tools }
  }

  if (index === -1) {
    return malformed(
      state,
      event,
      `${data.event} arrived before tool-started`
    )
  }
  const tools = [...state.tools]
  const current = tools[index]
  if (data.event === "tool-output-delta" && typeof data.delta === "string") {
    tools[index] = {
      ...current,
      outputText: current.outputText + data.delta,
      timestamp,
    }
  } else if (data.event === "tool-finished") {
    tools[index] = {
      ...current,
      status: "completed",
      timestamp,
      output: data.output,
    }
  } else if (data.event === "tool-error" && typeof data.message === "string") {
    tools[index] = {
      ...current,
      status: "failed",
      timestamp,
      error: {
        message: data.message,
        ...(typeof data.code === "string" ? { code: data.code } : {}),
      },
    }
  } else {
    return malformed(state, event, `Malformed tools lifecycle ${data.event}`)
  }
  return { ...state, tools }
}

function reduceLifecycleEvent(
  state: AgentRuntimeState,
  event: Event
): AgentRuntimeState {
  const { namespace, timestamp, data } = eventParams(event)
  if (!isObject(data) || !isAgentStatus(data.event)) {
    return malformed(
      state,
      event,
      "lifecycle event requires a known status"
    )
  }
  const key = agentKey(namespace)
  const existingIndex = state.agents.findIndex((agent) => agent.key === key)
  const agent: AgentRuntimeAgent = {
    key,
    ...(namespace.length === 0
      ? {}
      : { parentKey: agentKey(namespace.slice(0, -1)) }),
    namespace,
    depth: namespace.length,
    status: data.event,
    ...(typeof data.graph_name === "string"
      ? { graphName: data.graph_name }
      : {}),
    ...(isObject(data.cause)
      ? { cause: data.cause as unknown as LifecycleCause }
      : {}),
    ...(isObject(data.checkpoint) &&
    typeof data.checkpoint.id === "string"
      ? {
          checkpoint: {
            id: data.checkpoint.id,
            ...(typeof data.checkpoint.ns === "string"
              ? { ns: data.checkpoint.ns }
              : {}),
          },
        }
      : {}),
    ...(typeof data.error === "string" ? { error: data.error } : {}),
    timestamp,
  }
  const agents = [...state.agents]
  if (existingIndex === -1) agents.push(agent)
  else agents[existingIndex] = { ...agents[existingIndex], ...agent }

  if (namespace.length !== 0) return { ...state, agents }

  const run: AgentRuntimeRun = {
    ...state.run,
    status: data.event,
    ...(typeof data.graph_name === "string"
      ? { graphName: data.graph_name }
      : {}),
    ...(agent.checkpoint === undefined
      ? {}
      : { checkpoint: agent.checkpoint }),
  }
  return {
    ...state,
    agents,
    run,
    ...(data.event === "failed"
      ? {
          error: {
            source: "lifecycle" as const,
            code: "run_failed",
            message:
              typeof data.error === "string"
                ? data.error
                : "The agent run failed.",
          },
        }
      : {}),
  }
}

function reduceInputEvent(
  state: AgentRuntimeState,
  event: Event
): AgentRuntimeState {
  const { namespace, timestamp, data } = eventParams(event)
  if (
    !isObject(data) ||
    typeof data.interrupt_id !== "string" ||
    !("payload" in data)
  ) {
    return malformed(
      state,
      event,
      "input.requested requires interrupt_id and payload"
    )
  }
  const key = interruptKey(namespace, data.interrupt_id)
  const interrupt: AgentRuntimeInterrupt = {
    key,
    interruptId: data.interrupt_id,
    namespace,
    timestamp,
    payload: data.payload,
    status: "pending",
  }
  const index = state.interrupts.findIndex((item) => item.key === key)
  const interrupts = [...state.interrupts]
  if (index === -1) interrupts.push(interrupt)
  else interrupts[index] = interrupt
  return {
    ...state,
    interrupts,
    run:
      namespace.length === 0
        ? { ...state.run, status: "interrupted" }
        : state.run,
  }
}

function reduceCheckpointEvent(
  state: AgentRuntimeState,
  event: Event
): AgentRuntimeState {
  const { namespace, timestamp, data } = eventParams(event)
  if (
    !isObject(data) ||
    typeof data.id !== "string" ||
    !Number.isSafeInteger(data.step) ||
    !["input", "loop", "update", "fork"].includes(String(data.source))
  ) {
    return malformed(state, event, "checkpoints event is malformed")
  }
  const checkpoint: AgentRuntimeCheckpoint = {
    ...(data as unknown as Checkpoint),
    namespace,
    timestamp,
  }
  const index = state.checkpoints.findIndex(
    (item) =>
      item.id === checkpoint.id &&
      namespaceStorageKey(item.namespace) === namespaceStorageKey(namespace)
  )
  const checkpoints = [...state.checkpoints]
  if (index === -1) checkpoints.push(checkpoint)
  else checkpoints[index] = checkpoint
  return { ...state, checkpoints }
}

function timelineItem(event: Event): AgentRuntimeTimelineItem {
  const { namespace, timestamp, data } = eventParams(event)
  return {
    key: event.event_id ?? `seq:${String(event.seq)}`,
    namespace,
    timestamp,
    data,
  }
}

function reduceSnapshotEvent(
  state: AgentRuntimeState,
  event: Event
): AgentRuntimeState {
  const { namespace, timestamp, data } = eventParams(event)
  const key = namespaceStorageKey(namespace)
  const values = [...state.values]
  const index = values.findIndex(
    (snapshot) => namespaceStorageKey(snapshot.namespace) === key
  )
  const snapshot = { namespace, timestamp, data }
  if (index === -1) values.push(snapshot)
  else values[index] = snapshot
  return { ...state, values }
}

/**
 * Pure Agent Protocol event reducer used by the future assistant-ui external
 * store adapter. Sequence gating happens before any visible state mutation.
 */
export function reduceAgentProtocolEvent(
  state: AgentRuntimeState,
  event: Event
): AgentRuntimeState {
  if (!isSequence(event.seq)) {
    return diagnostic(state, {
      kind: "malformed",
      message: "Reducer received an event without a valid seq",
      method: String(event.method),
    })
  }
  if (state.cursor !== null && event.seq <= state.cursor.seq) {
    return diagnostic(state, {
      kind: "stale-or-duplicate",
      message: `Ignored event seq ${event.seq}; cursor is ${state.cursor.seq}`,
      ...eventCoordinates(event),
    })
  }

  const advanced: AgentRuntimeState = {
    ...state,
    cursor: {
      seq: event.seq,
      ...(event.event_id === undefined ? {} : { eventId: event.event_id }),
    },
  }

  switch (String(event.method)) {
    case "messages":
      return reduceMessageEvent(advanced, event)
    case "tools":
      return reduceToolEvent(advanced, event)
    case "lifecycle":
      return reduceLifecycleEvent(advanced, event)
    case "input.requested":
      return reduceInputEvent(advanced, event)
    case "checkpoints":
      return reduceCheckpointEvent(advanced, event)
    case "tasks":
      return { ...advanced, tasks: [...advanced.tasks, timelineItem(event)] }
    case "values":
      return reduceSnapshotEvent(advanced, event)
    case "updates":
      return {
        ...advanced,
        updates: [...advanced.updates, timelineItem(event)],
      }
    case "custom":
      return {
        ...advanced,
        custom: [...advanced.custom, timelineItem(event)],
      }
    default:
      return diagnostic(advanced, {
        kind: "unknown-event",
        message: `Ignored unknown Agent Protocol event ${String(event.method)}`,
        ...eventCoordinates(event),
      })
  }
}

function commandAppliedThrough(
  response: CommandResponse | ErrorResponse
): number | undefined {
  const value = response.meta?.applied_through_seq
  return isSequence(value) ? value : undefined
}

function respondedInterruptKeys(command: Command): Set<string> {
  if (command.method !== "input.respond") return new Set()
  const params = command.params as unknown as JsonObject
  if (Array.isArray(params.responses)) {
    return new Set(
      params.responses.flatMap((item) => {
        if (
          !isObject(item) ||
          !isNamespace(item.namespace) ||
          typeof item.interrupt_id !== "string"
        ) {
          return []
        }
        return [interruptKey(item.namespace, item.interrupt_id)]
      })
    )
  }
  if (
    isNamespace(params.namespace) &&
    typeof params.interrupt_id === "string"
  ) {
    return new Set([interruptKey(params.namespace, params.interrupt_id)])
  }
  return new Set()
}

/**
 * Reduces the command sidecar response separately from event replay. In
 * particular, `applied_through_seq` is recorded but never advances the event
 * cursor—the cursor only represents events the client actually reduced.
 */
export function reduceAgentCommandResult(
  state: AgentRuntimeState,
  command: Command,
  response: CommandResponse | ErrorResponse
): AgentRuntimeState {
  if (response.id !== command.id) {
    return diagnostic(state, {
      kind: "malformed",
      message: `Command response ${String(response.id)} does not match ${command.id}`,
    })
  }
  const appliedThroughSeq = commandAppliedThrough(response)
  const lastCommand: AgentRuntimeCommandState = {
    id: command.id,
    method: command.method,
    type: response.type,
    ...(appliedThroughSeq === undefined ? {} : { appliedThroughSeq }),
  }
  if (response.type === "error") {
    return {
      ...state,
      lastCommand,
      error: {
        source: "command",
        commandId: command.id,
        code: response.error,
        message: response.message,
      },
    }
  }

  const result = response.result as JsonObject
  const runId = typeof result.run_id === "string" ? result.run_id : undefined
  const responseKeys = respondedInterruptKeys(command)
  return {
    ...state,
    lastCommand,
    error: undefined,
    run: {
      ...state.run,
      ...(runId === undefined ? {} : { runId }),
      ...(command.method === "run.start" || command.method === "input.respond"
        ? { status: "started" as const }
        : {}),
    },
    interrupts:
      responseKeys.size === 0
        ? state.interrupts
        : state.interrupts.map((interrupt) =>
            responseKeys.has(interrupt.key)
              ? { ...interrupt, status: "responded" as const }
              : interrupt
          ),
  }
}

export function selectVisibleText(state: AgentRuntimeState): string {
  return state.messages
    .flatMap((message) => message.content)
    .map((block) =>
      block.content.type === "text" &&
      typeof block.content.text === "string"
        ? block.content.text
        : ""
    )
    .join("")
}

export type AgentTransportHttpErrorKind =
  | "unauthorized"
  | "forbidden"
  | "busy-thread"
  | "rate-limited"
  | "server-error"
  | "bad-request"
  | "not-found"
  | "http-error"

export class AgentTransportHttpError extends Error {
  readonly kind: AgentTransportHttpErrorKind
  readonly status: number
  readonly retryAfterMs?: number
  readonly responseBody?: unknown

  constructor(options: {
    kind: AgentTransportHttpErrorKind
    status: number
    message: string
    retryAfterMs?: number
    responseBody?: unknown
  }) {
    super(options.message)
    this.name = "AgentTransportHttpError"
    this.kind = options.kind
    this.status = options.status
    this.retryAfterMs = options.retryAfterMs
    this.responseBody = options.responseBody
  }
}

export class AgentTransportNetworkError extends Error {
  readonly kind = "network"

  constructor(message: string, options?: ErrorOptions) {
    super(message, options)
    this.name = "AgentTransportNetworkError"
  }
}

function httpErrorKind(status: number): AgentTransportHttpErrorKind {
  if (status === 401) return "unauthorized"
  if (status === 403) return "forbidden"
  if (status === 404) return "not-found"
  if (status === 409) return "busy-thread"
  if (status === 429) return "rate-limited"
  if (status >= 500) return "server-error"
  if (status >= 400 && status < 500) return "bad-request"
  return "http-error"
}

function retryAfterMilliseconds(value: string | null): number | undefined {
  if (value === null || value.trim() === "") return undefined
  if (/^\d+(?:\.\d+)?$/.test(value.trim())) {
    return Math.max(0, Number(value) * 1_000)
  }
  const retryAt = Date.parse(value)
  if (Number.isNaN(retryAt)) return undefined
  return Math.max(0, retryAt - Date.now())
}

async function responsePayload(response: Response): Promise<unknown> {
  const text = await response.text()
  if (text.length === 0) return undefined
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

function errorDetail(payload: unknown): string | undefined {
  if (typeof payload === "string") return payload
  if (!isObject(payload)) return undefined
  if (typeof payload.detail === "string") return payload.detail
  if (typeof payload.message === "string") return payload.message
  return undefined
}

type AegraEventStreamOptions = AgentEventStreamRequest & {
  threadId: string
  cursor?: AgentReplayCursor | null
  signal?: AbortSignal
}

export interface AgentEventStream extends AsyncIterable<Event> {
  readonly signal: AbortSignal
  cancel(reason?: unknown): void
}

class ManagedAgentEventStream implements AgentEventStream {
  readonly #controller = new AbortController()
  readonly #factory: (signal: AbortSignal) => AsyncGenerator<Event>
  readonly #externalSignal?: AbortSignal
  readonly #onExternalAbort: () => void
  #consumed = false

  constructor(
    factory: (signal: AbortSignal) => AsyncGenerator<Event>,
    externalSignal?: AbortSignal
  ) {
    this.#factory = factory
    this.#externalSignal = externalSignal
    this.#onExternalAbort = () =>
      this.#controller.abort(this.#externalSignal?.reason)

    if (externalSignal?.aborted) {
      this.#onExternalAbort()
    } else {
      externalSignal?.addEventListener("abort", this.#onExternalAbort, {
        once: true,
      })
    }
  }

  get signal(): AbortSignal {
    return this.#controller.signal
  }

  cancel(
    reason: unknown = new DOMException(
      "Agent event stream cancelled",
      "AbortError"
    )
  ): void {
    if (!this.#controller.signal.aborted) this.#controller.abort(reason)
    this.#externalSignal?.removeEventListener(
      "abort",
      this.#onExternalAbort
    )
  }

  [Symbol.asyncIterator](): AsyncIterator<Event> {
    if (this.#consumed) {
      throw new AgentProtocolDecodeError(
        "An Agent event stream can only be consumed once"
      )
    }
    this.#consumed = true
    return this.#iterate()
  }

  async *#iterate(): AsyncGenerator<Event> {
    try {
      this.signal.throwIfAborted()
      yield* this.#factory(this.signal)
    } finally {
      this.#externalSignal?.removeEventListener(
        "abort",
        this.#onExternalAbort
      )
      this.cancel()
    }
  }
}

export interface AgentProtocolV2TransportOptions {
  baseUrl: string
  fetch?: typeof fetch
  /**
   * Async token hook. Its result is cached until the default 60-second
   * refresh margin rather than captured for the component lifetime.
   */
  onRequest?: AgentOnRequest
  tokenRefreshMarginSeconds?: number
  nowSeconds?: () => number
  headers?: HeadersInit
}

export class AgentProtocolV2Transport {
  readonly #baseUrl: string
  readonly #fetch: typeof fetch
  readonly #token?: RefreshingAgentToken
  readonly #headers: Headers

  constructor(options: AgentProtocolV2TransportOptions) {
    const baseUrl = options.baseUrl.replace(/\/+$/, "")
    if (baseUrl.length === 0) {
      throw new AgentProtocolDecodeError("Agent baseUrl must not be empty")
    }
    this.#baseUrl = baseUrl
    this.#fetch = options.fetch ?? globalThis.fetch.bind(globalThis)
    this.#headers = new Headers(options.headers)
    this.#token =
      options.onRequest === undefined
        ? undefined
        : new RefreshingAgentToken(options.onRequest, {
            ...(options.tokenRefreshMarginSeconds === undefined
              ? {}
              : {
                  refreshMarginSeconds:
                    options.tokenRefreshMarginSeconds,
                }),
            ...(options.nowSeconds === undefined
              ? {}
              : { nowSeconds: options.nowSeconds }),
          })
  }

  streamEvents(options: AegraEventStreamOptions): AgentEventStream {
    const { threadId, cursor, signal, ...request } = options
    const body = eventStreamRequestFor(request, cursor)
    return new ManagedAgentEventStream(
      (streamSignal) =>
        this.#streamEvents(threadId, body, streamSignal),
      signal
    )
  }

  async sendCommand(
    threadId: string,
    command: Command,
    signal?: AbortSignal
  ): Promise<CommandResponse | ErrorResponse> {
    validateAegraCommand(command)
    const controller = linkedAbortController(signal)
    try {
      const url = this.#threadUrl(
        threadId,
        AEGRA_THREAD_COMMANDS_SUFFIX
      )
      const response = await this.#post(
        url,
        "command",
        threadId,
        command,
        "application/json",
        controller.signal
      )
      return decodeCommandResponse(
        await parseJsonResponse(response),
        command.id
      )
    } finally {
      controller.cleanup()
    }
  }

  async *#streamEvents(
    threadId: string,
    body: EventStreamRequest,
    signal: AbortSignal
  ): AsyncGenerator<Event> {
    const url = this.#threadUrl(
      threadId,
      AEGRA_THREAD_EVENT_STREAM_SUFFIX
    )
    const response = await this.#post(
      url,
      "event-stream",
      threadId,
      body,
      "text/event-stream",
      signal
    )
    const contentType = response.headers.get("content-type")?.toLowerCase()
    if (!contentType?.startsWith("text/event-stream")) {
      throw new AgentProtocolDecodeError(
        `Expected text/event-stream but received ${contentType ?? "no content type"}`
      )
    }
    if (response.body === null) {
      throw new AgentProtocolDecodeError(
        "Agent event stream response has no body"
      )
    }

    for await (const frame of parseServerSentEvents(response.body, signal)) {
      let raw: unknown
      try {
        raw = JSON.parse(frame.data)
      } catch (error) {
        throw new AgentProtocolDecodeError(
          "Agent SSE data is not valid JSON",
          { cause: error }
        )
      }
      yield decodeAegraEvent(raw, frame)
    }
  }

  async #post(
    url: string,
    purpose: AgentRequestPurpose,
    threadId: string,
    body: unknown,
    accept: string,
    signal: AbortSignal
  ): Promise<Response> {
    signal.throwIfAborted()
    const headers = new Headers(this.#headers)
    headers.set("accept", accept)
    headers.set("content-type", "application/json")
    if (this.#token !== undefined) {
      const token = await this.#token.get({
        purpose,
        threadId,
        url,
        signal,
      })
      headers.set("authorization", `Bearer ${token}`)
    }

    let response: Response
    try {
      response = await this.#fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        signal,
      })
    } catch (error) {
      if (signal.aborted) throw signal.reason
      throw new AgentTransportNetworkError(
        "Could not reach the agent service",
        { cause: error }
      )
    }
    if (response.ok) return response

    const payload = await responsePayload(response)
    const detail = errorDetail(payload)
    const featureFlagHint =
      response.status === 503
        ? ` Verify ${AEGRA_EVENT_STREAM_FEATURE_FLAG}=true and the native event runtime capability.`
        : ""
    const retryAfterMs = retryAfterMilliseconds(
      response.headers.get("retry-after")
    )
    throw new AgentTransportHttpError({
      kind: httpErrorKind(response.status),
      status: response.status,
      message: `${detail ?? `Agent request failed with HTTP ${response.status}`}${featureFlagHint}`,
      ...(retryAfterMs === undefined ? {} : { retryAfterMs }),
      ...(payload === undefined ? {} : { responseBody: payload }),
    })
  }

  #threadUrl(threadId: string, suffix: string): string {
    if (threadId.length === 0) {
      throw new AgentProtocolDecodeError("threadId must not be empty")
    }
    return `${this.#baseUrl}/threads/${encodeURIComponent(threadId)}${suffix}`
  }
}

function validateAegraCommand(command: Command): void {
  const raw = command as unknown as JsonObject
  if (!isSequence(raw.id) || !isObject(raw.params)) {
    throw new AgentProtocolDecodeError(
      "Aegra command requires a non-negative id and object params"
    )
  }
  if (raw.method !== "run.start" && raw.method !== "input.respond") {
    throw new AgentProtocolDecodeError(
      `Aegra 0.9.24 does not support command ${String(raw.method)}`
    )
  }
  if (raw.method === "run.start") {
    if (
      typeof raw.params.assistant_id !== "string" ||
      raw.params.assistant_id.length === 0
    ) {
      throw new AgentProtocolDecodeError(
        "run.start requires assistant_id"
      )
    }
    return
  }
  if ("update" in raw.params || "goto" in raw.params) {
    throw new AgentProtocolDecodeError(
      "Aegra 0.9.24 does not forward input.respond update or goto"
    )
  }
  if (Array.isArray(raw.params.responses)) {
    if (raw.params.responses.length === 0) {
      throw new AgentProtocolDecodeError(
        "input.respond responses must not be empty"
      )
    }
    return
  }
  if (!("response" in raw.params)) {
    throw new AgentProtocolDecodeError(
      "input.respond requires response or responses"
    )
  }
}

function linkedAbortController(external?: AbortSignal): {
  signal: AbortSignal
  cleanup(): void
} {
  const controller = new AbortController()
  const onAbort = () => controller.abort(external?.reason)
  if (external?.aborted) onAbort()
  else external?.addEventListener("abort", onAbort, { once: true })
  return {
    signal: controller.signal,
    cleanup() {
      external?.removeEventListener("abort", onAbort)
    },
  }
}

async function parseJsonResponse(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch (error) {
    throw new AgentProtocolDecodeError(
      "Agent command response is not valid JSON",
      { cause: error }
    )
  }
}
