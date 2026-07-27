import type {
  CustomEvent,
  LifecycleEvent,
  MessagesEvent,
  ToolsEvent,
} from "@langchain/protocol"

export const INSPECTION_EVENT_NAME = "syshin.rag.inspection.v1"
export const INSPECTION_DELIVERY = "live-run-only"

const MAX_EVENT_BYTES = 65_536
const MAX_QUERY_CHARACTERS = 1_000
const MAX_SOURCE_COUNT = 50
const MAX_HIT_COUNT = 10_000
const MAX_CORPUS_DOCUMENT_COUNT = 1_000_000
const MAX_ELAPSED_MS = 86_400_000
const METHOD_ID = /^[A-Za-z0-9][A-Za-z0-9._-]*$/
const IMPLEMENTATION_ID =
  /^[A-Za-z0-9][A-Za-z0-9._:/+-]*@[A-Za-z0-9][A-Za-z0-9._+-]*$/
const OPAQUE_ID = /^[A-Za-z0-9][A-Za-z0-9._:/#@+-]*$/
const SHA256_FINGERPRINT = /^sha256:[0-9a-f]{64}$/
const textEncoder = new TextEncoder()
const PAYLOAD_KEYS = [
  "corpus_document_count",
  "corpus_revision",
  "delivery",
  "hit_count",
  "kind",
  "method_id",
  "method_identity",
  "query",
  "query_truncated",
  "schema_version",
  "sources",
  "sources_truncated",
  "stages",
  "tool_call_id",
] as const
const METHOD_IDENTITY_KEYS = [
  "fingerprint",
  "implementation_id",
  "method_id",
] as const
const PROVENANCE_KEYS = [
  "corpus_revision",
  "kind",
  "retriever_fingerprint",
] as const
const STAGE_KEYS = [
  "application",
  "elapsed_ms",
  "fingerprint",
  "implementation_id",
  "stage_id",
] as const
const APPLICATION_KEYS = ["input_count", "output_count", "status"] as const

export interface InspectionMethodIdentity {
  methodId: string
  implementationId: string
  fingerprint: string
}

export interface InspectionProvenance {
  kind: "published-corpus"
  corpusRevision: string
  retrieverFingerprint: string
}

export interface InspectionSource {
  key: string
  docId?: string
  title?: string
  url?: string
  path?: string
  citedText?: string
  chunkId?: string
  rank?: number
  score?: number
  provenance?: InspectionProvenance
}

export interface InspectionStage {
  stageId: string
  implementationId: string
  fingerprint: string
  elapsedMs: number
  application: {
    status: "applied"
    inputCount: number
    outputCount: number
  }
}

interface ActivityBase {
  id: string
  namespace: string[]
  status: string
  label: string
}

export type AgentActivity =
  | (ActivityBase & {
      kind: "lifecycle"
      error?: string
    })
  | (ActivityBase & {
      kind: "tool"
      toolCallId: string
      toolName?: string
    })
  | (ActivityBase & {
      kind: "nested"
      name: string
      elapsedMs?: number
    })
  | (ActivityBase & {
      kind: "retrieval"
      delivery: "live-run-only"
      toolCallId: string
      query: string
      queryTruncated: boolean
      methodId: string
      methodIdentity: InspectionMethodIdentity
      hitCount: number
      corpusDocumentCount: number
      corpusRevision: string
      sourcesTruncated: boolean
      sources: InspectionSource[]
      stages: [InspectionStage]
    })
  | (ActivityBase & {
      kind: "sources"
      messageId: string
      sources: InspectionSource[]
    })
  | (ActivityBase & {
      kind: "connection"
      status: "reconnecting"
    })

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value)

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

function boundedString(
  value: unknown,
  maxCharacters: number,
  options: {
    trim?: boolean
    requireTrimmed?: boolean
    pattern?: RegExp
  } = {}
): string | undefined {
  if (typeof value !== "string" || !isUnicodeScalarString(value)) {
    return undefined
  }
  if (options.requireTrimmed && value !== value.trim()) return undefined
  const normalized = options.trim ? value.trim() : value
  if (
    normalized.length === 0 ||
    normalized.length > maxCharacters ||
    (options.pattern && !options.pattern.test(normalized))
  ) {
    return undefined
  }
  return normalized
}

function boundedNumber(
  value: unknown,
  options: {
    integer?: boolean
    minimum?: number
    maximum?: number
  } = {}
): number | undefined {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    (options.integer && !Number.isInteger(value)) ||
    (options.minimum !== undefined && value < options.minimum) ||
    (options.maximum !== undefined && value > options.maximum)
  ) {
    return undefined
  }
  return value
}

function hasExactKeys(
  value: Record<string, unknown>,
  required: readonly string[],
  optional: readonly string[] = []
): boolean {
  const expected = new Set([...required, ...optional])
  return (
    required.every((key) => Object.hasOwn(value, key)) &&
    Object.keys(value).every((key) => expected.has(key))
  )
}

function isCanonicalDocId(value: string): boolean {
  return (
    value.endsWith(".md") &&
    !value.startsWith("/") &&
    !/^[A-Za-z]:/.test(value) &&
    !value.includes("\\") &&
    !value.includes("\0") &&
    !value.split("/").some((part) => part === "" || part === "." || part === "..")
  )
}

function fingerprint(value: unknown): string | undefined {
  return typeof value === "string" && SHA256_FINGERPRINT.test(value)
    ? value
    : undefined
}

function serializedSizeIsSafe(value: unknown): boolean {
  try {
    return textEncoder.encode(JSON.stringify(value)).byteLength <= MAX_EVENT_BYTES
  } catch {
    return false
  }
}

function methodIdentityFromUnknown(
  value: unknown,
  methodId: string
): InspectionMethodIdentity | undefined {
  if (!isRecord(value) || !hasExactKeys(value, METHOD_IDENTITY_KEYS)) {
    return undefined
  }
  const identityMethodId = boundedString(value.method_id, 128, {
    requireTrimmed: true,
    pattern: METHOD_ID,
  })
  const implementationId = boundedString(value.implementation_id, 256, {
    requireTrimmed: true,
    pattern: IMPLEMENTATION_ID,
  })
  const methodFingerprint = fingerprint(value.fingerprint)
  if (
    identityMethodId !== methodId ||
    !implementationId ||
    !methodFingerprint
  ) {
    return undefined
  }
  return {
    methodId: identityMethodId,
    implementationId,
    fingerprint: methodFingerprint,
  }
}

function provenanceFromUnknown(
  value: unknown,
  corpusRevision: string,
  retrieverFingerprint: string
): InspectionProvenance | undefined {
  if (!isRecord(value) || !hasExactKeys(value, PROVENANCE_KEYS)) {
    return undefined
  }
  if (
    value.kind !== "published-corpus" ||
    value.corpus_revision !== corpusRevision ||
    value.retriever_fingerprint !== retrieverFingerprint
  ) {
    return undefined
  }
  return {
    kind: "published-corpus",
    corpusRevision,
    retrieverFingerprint,
  }
}

function inspectionSources(
  value: unknown,
  corpusRevision: string,
  retrieverFingerprint: string
): InspectionSource[] | undefined {
  if (!Array.isArray(value) || value.length > MAX_SOURCE_COUNT) {
    return undefined
  }
  const sources: InspectionSource[] = []
  for (const [index, candidate] of value.entries()) {
    if (
      !isRecord(candidate) ||
      !hasExactKeys(
        candidate,
        ["doc_id", "provenance", "rank", "title"],
        ["chunk_id", "score"]
      )
    ) {
      return undefined
    }
    const docId = boundedString(candidate.doc_id, 1_000, {
      requireTrimmed: true,
    })
    const title = boundedString(candidate.title, 300, {
      requireTrimmed: true,
    })
    const rank = boundedNumber(candidate.rank, {
      integer: true,
      minimum: 1,
      maximum: MAX_HIT_COUNT,
    })
    const score =
      candidate.score === undefined
        ? undefined
        : boundedNumber(candidate.score)
    const chunkId =
      candidate.chunk_id === undefined
        ? undefined
        : boundedString(candidate.chunk_id, 256, {
            requireTrimmed: true,
            pattern: OPAQUE_ID,
          })
    const provenance = provenanceFromUnknown(
      candidate.provenance,
      corpusRevision,
      retrieverFingerprint
    )
    if (
      !docId ||
      !isCanonicalDocId(docId) ||
      !title ||
      rank !== index + 1 ||
      (candidate.score !== undefined && score === undefined) ||
      (candidate.chunk_id !== undefined && !chunkId) ||
      !provenance
    ) {
      return undefined
    }
    sources.push({
      key: docId,
      docId,
      title,
      rank,
      ...(score !== undefined ? { score } : {}),
      ...(chunkId ? { chunkId } : {}),
      provenance,
    })
  }
  return sources
}

function stageFromUnknown(
  value: unknown,
  identity: InspectionMethodIdentity
): InspectionStage | undefined {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, STAGE_KEYS) ||
    !isRecord(value.application) ||
    !hasExactKeys(value.application, APPLICATION_KEYS)
  ) {
    return undefined
  }
  const stageId = boundedString(value.stage_id, 128, {
    requireTrimmed: true,
    pattern: METHOD_ID,
  })
  const implementationId = boundedString(value.implementation_id, 256, {
    requireTrimmed: true,
    pattern: IMPLEMENTATION_ID,
  })
  const stageFingerprint = fingerprint(value.fingerprint)
  const elapsedMs = boundedNumber(value.elapsed_ms, {
    minimum: 0,
    maximum: MAX_ELAPSED_MS,
  })
  const inputCount = boundedNumber(value.application.input_count, {
    integer: true,
    minimum: 0,
    maximum: MAX_HIT_COUNT,
  })
  const outputCount = boundedNumber(value.application.output_count, {
    integer: true,
    minimum: 0,
    maximum: MAX_HIT_COUNT,
  })
  if (
    stageId !== identity.methodId ||
    implementationId !== identity.implementationId ||
    stageFingerprint !== identity.fingerprint ||
    elapsedMs === undefined ||
    value.application.status !== "applied" ||
    inputCount !== 1 ||
    outputCount === undefined
  ) {
    return undefined
  }
  return {
    stageId,
    implementationId,
    fingerprint: stageFingerprint,
    elapsedMs,
    application: {
      status: "applied",
      inputCount,
      outputCount,
    },
  }
}

function retrievalFromUnknown(
  payload: Record<string, unknown>,
  namespace: string[]
): Extract<AgentActivity, { kind: "retrieval" }> | undefined {
  if (
    !hasExactKeys(payload, PAYLOAD_KEYS) ||
    payload.schema_version !== 1 ||
    payload.kind !== "retrieval" ||
    payload.delivery !== INSPECTION_DELIVERY ||
    typeof payload.query_truncated !== "boolean" ||
    typeof payload.sources_truncated !== "boolean" ||
    !serializedSizeIsSafe(payload)
  ) {
    return undefined
  }

  const toolCallId = boundedString(payload.tool_call_id, 256, {
    requireTrimmed: true,
    pattern: OPAQUE_ID,
  })
  const query = boundedString(payload.query, MAX_QUERY_CHARACTERS)
  const methodId = boundedString(payload.method_id, 128, {
    requireTrimmed: true,
    pattern: METHOD_ID,
  })
  const corpusRevision = fingerprint(payload.corpus_revision)
  const corpusDocumentCount = boundedNumber(payload.corpus_document_count, {
    integer: true,
    minimum: 0,
    maximum: MAX_CORPUS_DOCUMENT_COUNT,
  })
  const hitCount = boundedNumber(payload.hit_count, {
    integer: true,
    minimum: 0,
    maximum: MAX_HIT_COUNT,
  })
  if (
    !toolCallId ||
    !query ||
    !methodId ||
    !corpusRevision ||
    corpusDocumentCount === undefined ||
    hitCount === undefined
  ) {
    return undefined
  }

  const methodIdentity = methodIdentityFromUnknown(
    payload.method_identity,
    methodId
  )
  if (!methodIdentity) return undefined
  const sources = inspectionSources(
    payload.sources,
    corpusRevision,
    methodIdentity.fingerprint
  )
  if (
    !sources ||
    sources.length > hitCount ||
    payload.sources_truncated !== (sources.length < hitCount) ||
    !Array.isArray(payload.stages) ||
    payload.stages.length !== 1
  ) {
    return undefined
  }
  const stage = stageFromUnknown(payload.stages[0], methodIdentity)
  if (
    !stage ||
    stage.application.outputCount !== hitCount ||
    stage.application.inputCount !== 1
  ) {
    return undefined
  }

  return {
    id: `retrieval:${toolCallId}`,
    kind: "retrieval",
    namespace,
    status: "completed",
    label: "검색 검사 정보가 도착했습니다.",
    delivery: INSPECTION_DELIVERY,
    toolCallId,
    query,
    queryTruncated: payload.query_truncated,
    methodId,
    methodIdentity,
    hitCount,
    corpusDocumentCount,
    corpusRevision,
    sourcesTruncated: payload.sources_truncated,
    sources,
    stages: [stage],
  }
}

export function projectInspectionCustomEvent(
  event: CustomEvent
): AgentActivity | undefined {
  const data = event.params.data
  if (data.name !== INSPECTION_EVENT_NAME || !isRecord(data.payload)) {
    return undefined
  }
  return retrievalFromUnknown(data.payload, [...event.params.namespace])
}

function safeOptionalString(
  record: Record<string, unknown>,
  key: string,
  limit: number
): string | undefined {
  return record[key] === undefined
    ? undefined
    : boundedString(record[key], limit, { trim: true })
}

function sourceFromCitation(value: unknown): InspectionSource | undefined {
  if (!isRecord(value) || value.type !== "citation") return undefined
  const key =
    safeOptionalString(value, "id", 1_000) ??
    safeOptionalString(value, "url", 2_000) ??
    safeOptionalString(value, "title", 300)
  if (!key) return undefined
  const title = safeOptionalString(value, "title", 300)
  const url = safeSourceUrl(safeOptionalString(value, "url", 2_000))
  const citedText = safeOptionalString(value, "cited_text", 2_000)
  return {
    key,
    ...(title ? { title } : {}),
    ...(url ? { url } : {}),
    ...(citedText ? { citedText } : {}),
  }
}

function dedupeSources(sources: InspectionSource[]): InspectionSource[] {
  const seen = new Set<string>()
  return sources.filter((source) => {
    const key = [
      source.key,
      source.url ?? "",
      source.docId ?? "",
      source.title ?? "",
    ].join("\u0000")
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function sourcesFromContentBlock(value: unknown): InspectionSource[] {
  if (!isRecord(value) || !Array.isArray(value.annotations)) return []
  return dedupeSources(
    value.annotations.flatMap((annotation): InspectionSource[] => {
      const source = sourceFromCitation(annotation)
      return source ? [source] : []
    })
  )
}

export function sourcesFromContent(content: unknown): InspectionSource[] {
  if (!Array.isArray(content)) return []
  return dedupeSources(content.flatMap(sourcesFromContentBlock))
}

export function safeSourceUrl(url: string | undefined): string | undefined {
  if (!url) return undefined
  try {
    const parsed = new URL(url)
    return parsed.protocol === "https:" || parsed.protocol === "http:"
      ? parsed.toString()
      : undefined
  } catch {
    return undefined
  }
}

export function inspectionSourcesFromUnknown(
  value: unknown
): InspectionSource[] {
  if (!Array.isArray(value) || value.length > MAX_SOURCE_COUNT) return []
  const sources: InspectionSource[] = []
  for (const candidate of value) {
    if (!isRecord(candidate)) return []
    const key = boundedString(candidate.key, 1_000, { trim: true })
    const docId = safeOptionalString(candidate, "docId", 1_000)
    const title = safeOptionalString(candidate, "title", 300)
    const url =
      candidate.url === undefined
        ? undefined
        : safeSourceUrl(safeOptionalString(candidate, "url", 2_000))
    const path = safeOptionalString(candidate, "path", 1_000)
    const citedText = safeOptionalString(candidate, "citedText", 2_000)
    const rank =
      candidate.rank === undefined
        ? undefined
        : boundedNumber(candidate.rank, { integer: true, minimum: 0 })
    const score =
      candidate.score === undefined
        ? undefined
        : boundedNumber(candidate.score)
    if (
      !key ||
      (candidate.docId !== undefined && !docId) ||
      (candidate.title !== undefined && !title) ||
      (candidate.url !== undefined && !url) ||
      (candidate.path !== undefined && !path) ||
      (candidate.citedText !== undefined && !citedText) ||
      (candidate.rank !== undefined && (rank === undefined || rank < 1)) ||
      (candidate.score !== undefined && score === undefined)
    ) {
      return []
    }
    sources.push({
      key,
      ...(docId ? { docId } : {}),
      ...(title ? { title } : {}),
      ...(url ? { url } : {}),
      ...(path ? { path } : {}),
      ...(citedText ? { citedText } : {}),
      ...(rank !== undefined ? { rank } : {}),
      ...(score !== undefined ? { score } : {}),
    })
  }
  return dedupeSources(sources)
}

function namespaceKey(namespace: readonly string[], node?: string): string {
  return `${namespace.join("/")}\u0000${node ?? ""}`
}

function toolStatus(event: ToolsEvent): string {
  const kind = event.params.data.event
  return kind === "tool-started"
    ? "running"
    : kind === "tool-error"
      ? "failed"
      : kind === "tool-finished"
        ? "completed"
        : "streaming"
}

export class InspectionProjector {
  readonly #tools = new Map<
    string,
    Extract<AgentActivity, { kind: "tool" }>
  >()
  readonly #nestedStartedAt = new Map<string, number>()
  readonly #messageIds = new Map<string, string>()
  readonly #messageSources = new Map<string, InspectionSource[]>()

  consumeCustom(event: CustomEvent): AgentActivity | undefined {
    return projectInspectionCustomEvent(event)
  }

  consumeTool(event: ToolsEvent): AgentActivity {
    const data = event.params.data
    const previous = this.#tools.get(data.tool_call_id)
    const toolName =
      data.event === "tool-started"
        ? boundedString(data.tool_name, 200, { trim: true })
        : previous?.toolName
    const status = toolStatus(event)
    const activity: Extract<AgentActivity, { kind: "tool" }> = {
      id: `tool:${data.tool_call_id}`,
      kind: "tool",
      namespace: [...event.params.namespace],
      status,
      label:
        status === "completed"
          ? "도구 실행이 끝났습니다."
          : status === "failed"
            ? "도구 실행을 완료하지 못했습니다."
            : "도구를 실행 중입니다.",
      toolCallId: data.tool_call_id,
      ...(toolName ? { toolName } : {}),
    }
    this.#tools.set(data.tool_call_id, activity)
    return activity
  }

  consumeLifecycle(event: LifecycleEvent): AgentActivity {
    const { data, namespace, timestamp } = event.params
    if (namespace.length === 0) {
      return {
        id: `lifecycle:root:${timestamp}:${data.event}`,
        kind: "lifecycle",
        namespace: [],
        status: data.event,
        label:
          data.event === "completed"
            ? "에이전트 작업이 끝났습니다."
            : data.event === "failed"
              ? "에이전트 작업을 완료하지 못했습니다."
              : data.event === "interrupted"
                ? "에이전트가 입력을 기다립니다."
                : "에이전트가 작업 중입니다.",
      }
    }

    const key = namespace.join("/")
    if (
      (data.event === "started" || data.event === "running") &&
      !this.#nestedStartedAt.has(key)
    ) {
      this.#nestedStartedAt.set(key, timestamp)
    }
    const startedAt = this.#nestedStartedAt.get(key)
    const elapsedMs =
      startedAt !== undefined &&
      (data.event === "completed" || data.event === "failed")
        ? Math.max(0, timestamp - startedAt)
        : undefined
    const name =
      boundedString(data.graph_name, 200, { trim: true }) ??
      boundedString(namespace.at(-1), 200, { trim: true }) ??
      "중첩 작업"
    return {
      id: `nested:${key}`,
      kind: "nested",
      namespace: [...namespace],
      status: data.event,
      label:
        data.event === "completed"
          ? "중첩 작업이 끝났습니다."
          : data.event === "failed"
            ? "중첩 작업을 완료하지 못했습니다."
            : data.event === "interrupted"
              ? "중첩 작업이 입력을 기다립니다."
              : "중첩 작업을 실행 중입니다.",
      name,
      ...(elapsedMs !== undefined ? { elapsedMs } : {}),
    }
  }

  consumeMessage(event: MessagesEvent): AgentActivity | undefined {
    const { data, namespace, node } = event.params
    const key = namespaceKey(namespace, node)
    if (data.event === "message-start") {
      this.#messageIds.set(key, data.id)
      return undefined
    }
    if (
      data.event !== "content-block-start" &&
      data.event !== "content-block-finish"
    ) {
      if (data.event === "message-finish" || data.event === "error") {
        this.#messageIds.delete(key)
      }
      return undefined
    }
    const sources = sourcesFromContentBlock(data.content)
    if (sources.length === 0) return undefined
    const messageId = this.#messageIds.get(key)
    if (!messageId) return undefined
    const merged = dedupeSources([
      ...(this.#messageSources.get(messageId) ?? []),
      ...sources,
    ])
    this.#messageSources.set(messageId, merged)
    return {
      id: `sources:${messageId}`,
      kind: "sources",
      namespace: [...namespace],
      status: "completed",
      label: `${merged.length}개의 인용 출처가 제공되었습니다.`,
      messageId,
      sources: merged,
    }
  }
}

export const inspectionTesting = {
  sourcesFromContentBlock,
}
