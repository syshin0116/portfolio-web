export const INTERRUPT_UI_SCHEMA = "syshin.rag.interrupt.v1"

const MAX_ENVELOPE_DEPTH = 4
const MAX_ENVELOPE_NODES = 64
const MAX_ENVELOPE_OBJECT_KEYS = 16
const MAX_ENVELOPE_LIST_ITEMS = 8
const MAX_ENVELOPE_STRINGS = 32
const MAX_ENVELOPE_STRING_CODE_UNITS = 2_048
const MAX_ENVELOPE_UTF8_BYTES = 4_096

const MAX_TITLE_BYTES = 160
const MAX_PROMPT_BYTES = 480
const MAX_INPUT_HINT_BYTES = 160

const APPROVAL_KEYS = new Set([
  "schema",
  "kind",
  "title",
  "prompt",
  "input_hint",
])
const INPUT_KEYS = APPROVAL_KEYS
const RUNTIME_PROJECTION_KEYS = new Set([
  "recognized",
  "kind",
  "title",
  "prompt",
  "inputHint",
])
const textEncoder = new TextEncoder()

export interface InterruptUiProjection {
  recognized: boolean
  kind: "approval" | "input" | "unknown"
  title: string
  prompt: string
  inputHint: string
}

export const GENERIC_INTERRUPT_PROJECTION =
  Object.freeze<InterruptUiProjection>({
    recognized: false,
    kind: "unknown",
    title: "사용자 확인이 필요합니다.",
    prompt:
      "에이전트가 안전하게 계속하기 위해 응답을 기다리고 있습니다.",
    inputHint: "응답을 입력해 재개",
  })

interface EnvelopeBudget {
  bytes: number
  listItems: number
  nodes: number
  strings: number
  seen: WeakSet<object>
}

function addStringToBudget(value: string, budget: EnvelopeBudget): boolean {
  if (value.length > MAX_ENVELOPE_STRING_CODE_UNITS) return false
  budget.strings += 1
  if (budget.strings > MAX_ENVELOPE_STRINGS) return false
  budget.bytes += textEncoder.encode(value).byteLength
  return budget.bytes <= MAX_ENVELOPE_UTF8_BYTES
}

function inspectEnvelope(
  value: unknown,
  budget: EnvelopeBudget,
  depth = 0
): boolean {
  budget.nodes += 1
  if (
    depth > MAX_ENVELOPE_DEPTH ||
    budget.nodes > MAX_ENVELOPE_NODES
  ) {
    return false
  }
  if (typeof value === "string") return addStringToBudget(value, budget)
  if (
    value === null ||
    typeof value === "boolean" ||
    (typeof value === "number" && Number.isFinite(value))
  ) {
    return true
  }
  if (typeof value !== "object" || budget.seen.has(value)) return false
  budget.seen.add(value)

  const prototype = Object.getPrototypeOf(value)
  if (
    prototype !== Object.prototype &&
    prototype !== Array.prototype &&
    prototype !== null
  ) {
    return false
  }
  const descriptors = Object.getOwnPropertyDescriptors(value)
  const ownKeys = Reflect.ownKeys(descriptors)
  if (ownKeys.some((key) => typeof key !== "string")) return false
  if (
    ownKeys.some((key) => {
      const descriptor = descriptors[String(key)]
      return !descriptor || descriptor.get !== undefined || descriptor.set !== undefined
    })
  ) {
    return false
  }

  if (Array.isArray(value)) {
    if (value.length > MAX_ENVELOPE_LIST_ITEMS) return false
    const itemKeys = ownKeys.filter((key) => key !== "length") as string[]
    if (
      itemKeys.length !== value.length ||
      itemKeys.some((key, index) => key !== String(index))
    ) {
      return false
    }
    budget.listItems += value.length
    if (budget.listItems > MAX_ENVELOPE_LIST_ITEMS) return false
    return itemKeys.every((key) =>
      inspectEnvelope(descriptors[key]!.value, budget, depth + 1)
    )
  }

  const stringKeys = ownKeys as string[]
  if (stringKeys.length > MAX_ENVELOPE_OBJECT_KEYS) return false
  return stringKeys.every(
    (key) =>
      addStringToBudget(key, budget) &&
      inspectEnvelope(descriptors[key]!.value, budget, depth + 1)
  )
}

function isBoundedEnvelope(value: unknown): boolean {
  try {
    return inspectEnvelope(value, {
      bytes: 0,
      listItems: 0,
      nodes: 0,
      strings: 0,
      seen: new WeakSet(),
    })
  } catch {
    return false
  }
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return false
  }
  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}

function hasExactKeys(
  value: Record<string, unknown>,
  allowed: ReadonlySet<string>
): boolean {
  const keys = Object.getOwnPropertyNames(value)
  return keys.every((key) => allowed.has(key))
}

function boundedText(
  value: unknown,
  maxUtf8Bytes: number
): string | undefined {
  if (typeof value !== "string") return undefined
  const normalized = value.trim()
  if (
    normalized.length === 0 ||
    normalized.length > maxUtf8Bytes ||
    textEncoder.encode(normalized).byteLength > maxUtf8Bytes
  ) {
    return undefined
  }
  return normalized
}

/**
 * Projects an opaque APv2 interrupt payload into a deliberately tiny UI
 * contract. Unknown, malformed, accessor-backed, cyclic, or oversized values
 * are never partially rendered; callers receive generic fixed copy instead.
 */
export function projectInterruptForUi(value: unknown): InterruptUiProjection {
  try {
    if (!isBoundedEnvelope(value) || !isPlainRecord(value)) {
      return GENERIC_INTERRUPT_PROJECTION
    }
    if (
      value.schema !== INTERRUPT_UI_SCHEMA ||
      (value.kind !== "approval" && value.kind !== "input") ||
      !Object.hasOwn(value, "schema") ||
      !Object.hasOwn(value, "kind") ||
      !Object.hasOwn(value, "prompt") ||
      !hasExactKeys(value, value.kind === "approval" ? APPROVAL_KEYS : INPUT_KEYS)
    ) {
      return GENERIC_INTERRUPT_PROJECTION
    }

    const prompt = boundedText(value.prompt, MAX_PROMPT_BYTES)
    if (!prompt) {
      return GENERIC_INTERRUPT_PROJECTION
    }
    const title =
      !Object.hasOwn(value, "title")
        ? value.kind === "approval"
          ? "사용자 확인이 필요합니다."
          : "추가 입력이 필요합니다."
        : boundedText(value.title, MAX_TITLE_BYTES)
    const inputHint =
      !Object.hasOwn(value, "input_hint")
        ? value.kind === "approval"
          ? "수정할 내용을 입력해 재개"
          : "응답을 입력해 재개"
        : boundedText(value.input_hint, MAX_INPUT_HINT_BYTES)
    if (!title || !inputHint) return GENERIC_INTERRUPT_PROJECTION

    return Object.freeze({
      recognized: true,
      kind: value.kind,
      title,
      prompt,
      inputHint,
    })
  } catch {
    return GENERIC_INTERRUPT_PROJECTION
  }
}

/**
 * Reads only the tiny object produced locally by projectInterruptForUi.
 * Protocol payloads never call this directly; native-client projects them
 * first, so opaque interrupt state cannot enter assistant-ui unchanged.
 */
export function readRuntimeInterruptProjection(
  value: unknown
): InterruptUiProjection {
  try {
    if (
      !isBoundedEnvelope(value) ||
      !isPlainRecord(value) ||
      !hasExactKeys(value, RUNTIME_PROJECTION_KEYS) ||
      typeof value.recognized !== "boolean" ||
      (value.kind !== "approval" &&
        value.kind !== "input" &&
        value.kind !== "unknown")
    ) {
      return GENERIC_INTERRUPT_PROJECTION
    }
    const title = boundedText(value.title, MAX_TITLE_BYTES)
    const prompt = boundedText(value.prompt, MAX_PROMPT_BYTES)
    const inputHint = boundedText(value.inputHint, MAX_INPUT_HINT_BYTES)
    if (
      !title ||
      !prompt ||
      !inputHint ||
      (value.recognized && value.kind === "unknown") ||
      (!value.recognized && value.kind !== "unknown")
    ) {
      return GENERIC_INTERRUPT_PROJECTION
    }
    return Object.freeze({
      recognized: value.recognized,
      kind: value.kind,
      title,
      prompt,
      inputHint,
    })
  } catch {
    return GENERIC_INTERRUPT_PROJECTION
  }
}
