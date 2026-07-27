import { createHmac, timingSafeEqual } from "node:crypto"

export const ANONYMOUS_COOKIE_NAME = "agent-anonymous-session"
export const ANONYMOUS_SESSION_TTL_SECONDS = 14 * 24 * 60 * 60
export const ANONYMOUS_TOKEN_TTL_SECONDS = 300
export const SITEVERIFY_TIMEOUT_MS = 5_000
export const SITEVERIFY_URL =
  "https://challenges.cloudflare.com/turnstile/v0/siteverify"

const MAX_REQUEST_BODY_BYTES = 4_096
const MAX_SITEVERIFY_RESPONSE_BYTES = 16_384
const MAX_COOKIE_BYTES = 1_024
const MAX_COOKIE_PAYLOAD_BYTES = 512
const MAX_SECRET_BYTES = 4_096
const MIN_SECRET_BYTES = 32
const MAX_TURNSTILE_SECRET_BYTES = 256
const MAX_TURNSTILE_TOKEN_BYTES = 2_048
const MAX_CHALLENGE_AGE_SECONDS = 330
const MAX_CHALLENGE_CLOCK_SKEW_SECONDS = 30
const COOKIE_CONTEXT = "syshin0116.dev/anonymous-session/v1\u0000"
const VISIBLE_ASCII_PATTERN = /^[\x21-\x7e]+$/
const ACTION_PATTERN = /^[A-Za-z0-9_-]{1,32}$/
const ERROR_CODE_PATTERN = /^[a-z0-9-]{1,64}$/
const CDATA_PATTERN = /^[A-Za-z0-9_-]{0,255}$/
const UUID_V4_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const ANONYMOUS_SUBJECT_PATTERN =
  /^anon:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const RFC3339_UTC_PATTERN =
  /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,3}))?Z$/
const SITEVERIFY_FIELDS = new Set([
  "success",
  "challenge_ts",
  "hostname",
  "error-codes",
  "action",
  "cdata",
  "metadata",
])

export type FetchLike = (
  input: string | URL | Request,
  init?: RequestInit
) => Promise<Response>

export interface AnonymousAgentTokenConfig {
  agentAuthSecret: string
  anonymousSessionSecret: string
  turnstileSecret: string
  expectedHostname: string
  expectedAction: string
}

export type AnonymousAgentTokenFeature =
  | { state: "disabled" }
  | { state: "misconfigured" }
  | { state: "enabled"; config: AnonymousAgentTokenConfig }

export type TurnstileVerification =
  | "verified"
  | "rejected"
  | "unavailable"

export class InvalidAnonymousTokenRequest extends Error {
  constructor() {
    super("Invalid anonymous token request")
    this.name = "InvalidAnonymousTokenRequest"
  }
}

function byteLength(value: string): number {
  return Buffer.byteLength(value, "utf8")
}

function isBoundedString(
  value: unknown,
  minimumBytes: number,
  maximumBytes: number
): value is string {
  if (typeof value !== "string") return false
  const length = byteLength(value)
  return length >= minimumBytes && length <= maximumBytes
}

function isSigningSecret(value: unknown): value is string {
  return isBoundedString(value, MIN_SECRET_BYTES, MAX_SECRET_BYTES)
}

function isAgentAuthSecret(value: unknown): value is string {
  return (
    isSigningSecret(value) &&
    value.length >= 32
  )
}

function isTurnstileSecret(value: unknown): value is string {
  return (
    isBoundedString(value, 1, MAX_TURNSTILE_SECRET_BYTES) &&
    VISIBLE_ASCII_PATTERN.test(value)
  )
}

function isHostname(value: unknown): value is string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > 253 ||
    value !== value.toLowerCase()
  ) {
    return false
  }
  const labels = value.split(".")
  return labels.every(
    (label) =>
      label.length >= 1 &&
      label.length <= 63 &&
      /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(label)
  )
}

function isAction(value: unknown): value is string {
  return typeof value === "string" && ACTION_PATTERN.test(value)
}

function isTurnstileToken(value: unknown): value is string {
  return (
    isBoundedString(value, 1, MAX_TURNSTILE_TOKEN_BYTES) &&
    VISIBLE_ASCII_PATTERN.test(value)
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.getPrototypeOf(value) === Object.prototype
  )
}

function hasExactKeys(
  value: Record<string, unknown>,
  expected: readonly string[]
): boolean {
  const keys = Object.keys(value)
  return (
    keys.length === expected.length &&
    keys.every((key, index) => key === expected[index])
  )
}

export function readAnonymousAgentTokenFeature(
  environment: Readonly<Record<string, unknown>>
): AnonymousAgentTokenFeature {
  if (environment.AGENT_ANONYMOUS_TOKEN_ENABLED !== "true") {
    return { state: "disabled" }
  }

  const agentAuthSecret = environment.AGENT_AUTH_SECRET
  const anonymousSessionSecret = environment.ANONYMOUS_SESSION_SECRET
  const turnstileSecret = environment.TURNSTILE_SECRET_KEY
  const expectedHostname = environment.TURNSTILE_EXPECTED_HOSTNAME
  const expectedAction = environment.TURNSTILE_EXPECTED_ACTION

  if (
    !isAgentAuthSecret(agentAuthSecret) ||
    !isSigningSecret(anonymousSessionSecret) ||
    anonymousSessionSecret === agentAuthSecret ||
    !isTurnstileSecret(turnstileSecret) ||
    !isHostname(expectedHostname) ||
    !isAction(expectedAction)
  ) {
    return { state: "misconfigured" }
  }

  return {
    state: "enabled",
    config: {
      agentAuthSecret,
      anonymousSessionSecret,
      turnstileSecret,
      expectedHostname,
      expectedAction,
    },
  }
}

function isJsonContentType(value: string | null): boolean {
  if (value === null) return false
  const normalized = value.toLowerCase()
  return (
    normalized === "application/json" ||
    normalized === "application/json; charset=utf-8"
  )
}

function hasValidDeclaredLength(
  headers: Headers,
  maximumBytes: number
): boolean {
  const declared = headers.get("content-length")
  if (declared === null) return true
  if (!/^(?:0|[1-9]\d*)$/.test(declared)) return false
  const value = Number(declared)
  return Number.isSafeInteger(value) && value <= maximumBytes
}

async function readBoundedBytes(
  body: ReadableStream<Uint8Array> | null,
  maximumBytes: number
): Promise<Uint8Array> {
  if (body === null) throw new Error("Missing response body")
  const reader = body.getReader()
  const chunks: Uint8Array[] = []
  let total = 0

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      total += value.byteLength
      if (total > maximumBytes) {
        await reader.cancel()
        throw new Error("Body exceeds byte limit")
      }
      chunks.push(value)
    }
  } finally {
    reader.releaseLock()
  }

  const result = new Uint8Array(total)
  let offset = 0
  for (const chunk of chunks) {
    result.set(chunk, offset)
    offset += chunk.byteLength
  }
  return result
}

async function readBoundedText(
  body: ReadableStream<Uint8Array> | null,
  maximumBytes: number
): Promise<string> {
  const bytes = await readBoundedBytes(body, maximumBytes)
  return new TextDecoder("utf-8", { fatal: true }).decode(bytes)
}

export async function readTurnstileRequest(
  request: Request
): Promise<{ turnstileToken: string }> {
  if (
    !isJsonContentType(request.headers.get("content-type")) ||
    !hasValidDeclaredLength(request.headers, MAX_REQUEST_BODY_BYTES)
  ) {
    throw new InvalidAnonymousTokenRequest()
  }

  let text: string
  let parsed: unknown
  try {
    text = await readBoundedText(request.body, MAX_REQUEST_BODY_BYTES)
    parsed = JSON.parse(text)
  } catch {
    throw new InvalidAnonymousTokenRequest()
  }

  if (
    !isRecord(parsed) ||
    !hasExactKeys(parsed, ["turnstileToken"]) ||
    !isTurnstileToken(parsed.turnstileToken) ||
    JSON.stringify({ turnstileToken: parsed.turnstileToken }) !== text
  ) {
    throw new InvalidAnonymousTokenRequest()
  }

  return { turnstileToken: parsed.turnstileToken }
}

function isErrorCodes(value: unknown): value is string[] {
  return (
    Array.isArray(value) &&
    value.length <= 16 &&
    value.every(
      (entry) =>
        typeof entry === "string" && ERROR_CODE_PATTERN.test(entry)
    )
  )
}

function isChallengeTimestamp(value: unknown): value is string {
  if (typeof value !== "string" || value.length > 32) return false
  const match = RFC3339_UTC_PATTERN.exec(value)
  if (match === null) return false
  const parsed = Date.parse(value)
  if (!Number.isFinite(parsed)) return false
  const canonical = `${match[1]}.${(match[2] ?? "").padEnd(3, "0")}Z`
  return new Date(parsed).toISOString() === canonical
}

function isMetadata(value: unknown): boolean {
  if (!isRecord(value)) return false
  const keys = Object.keys(value)
  if (keys.length === 0) return true
  return (
    keys.length === 1 &&
    keys[0] === "ephemeral_id" &&
    isBoundedString(value.ephemeral_id, 1, 256) &&
    VISIBLE_ASCII_PATTERN.test(value.ephemeral_id)
  )
}

function parseSiteverifyResponse(
  value: unknown,
  expectedHostname: string,
  expectedAction: string,
  nowSeconds: number
): TurnstileVerification {
  if (
    !isRecord(value) ||
    Object.keys(value).some((key) => !SITEVERIFY_FIELDS.has(key)) ||
    typeof value.success !== "boolean"
  ) {
    return "unavailable"
  }

  if (
    ("challenge_ts" in value &&
      !isChallengeTimestamp(value.challenge_ts)) ||
    ("hostname" in value &&
      (typeof value.hostname !== "string" ||
        !isHostname(value.hostname))) ||
    ("action" in value &&
      (typeof value.action !== "string" || !isAction(value.action))) ||
    ("error-codes" in value && !isErrorCodes(value["error-codes"])) ||
    ("cdata" in value &&
      (typeof value.cdata !== "string" ||
        !CDATA_PATTERN.test(value.cdata))) ||
    ("metadata" in value && !isMetadata(value.metadata))
  ) {
    return "unavailable"
  }

  const errorCodes = value["error-codes"]
  if (!value.success) {
    return isErrorCodes(errorCodes) && errorCodes.length > 0
      ? "rejected"
      : "unavailable"
  }

  if (
    !isChallengeTimestamp(value.challenge_ts) ||
    typeof value.hostname !== "string" ||
    typeof value.action !== "string" ||
    (isErrorCodes(errorCodes) && errorCodes.length > 0)
  ) {
    return "unavailable"
  }

  const challengeSeconds = Date.parse(value.challenge_ts) / 1_000
  if (
    challengeSeconds < nowSeconds - MAX_CHALLENGE_AGE_SECONDS ||
    challengeSeconds > nowSeconds + MAX_CHALLENGE_CLOCK_SKEW_SECONDS ||
    value.hostname !== expectedHostname ||
    value.action !== expectedAction
  ) {
    return "rejected"
  }

  return "verified"
}

export async function verifyTurnstileToken(options: {
  token: string
  secret: string
  expectedHostname: string
  expectedAction: string
  fetchImpl: FetchLike
  timeoutMs?: number
  nowSeconds?: number
}): Promise<TurnstileVerification> {
  const timeoutMs = options.timeoutMs ?? SITEVERIFY_TIMEOUT_MS
  const nowSeconds =
    options.nowSeconds ?? Math.floor(Date.now() / 1_000)
  if (
    !isTurnstileToken(options.token) ||
    !isTurnstileSecret(options.secret) ||
    !isHostname(options.expectedHostname) ||
    !isAction(options.expectedAction) ||
    !Number.isSafeInteger(timeoutMs) ||
    timeoutMs < 1 ||
    timeoutMs > 30_000 ||
    !Number.isSafeInteger(nowSeconds) ||
    nowSeconds < 0
  ) {
    return "unavailable"
  }

  const controller = new AbortController()
  let timeoutId: ReturnType<typeof setTimeout> | undefined
  const timeout = new Promise<never>((_resolve, reject) => {
    timeoutId = setTimeout(() => {
      controller.abort()
      reject(new Error("Siteverify timeout"))
    }, timeoutMs)
  })

  const verify = async (): Promise<TurnstileVerification> => {
    const form = new URLSearchParams({
      secret: options.secret,
      response: options.token,
    })
    const response = await options.fetchImpl(SITEVERIFY_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: form.toString(),
      signal: controller.signal,
      redirect: "error",
      cache: "no-store",
      credentials: "omit",
    })
    if (
      !response.ok ||
      !isJsonContentType(response.headers.get("content-type")) ||
      !hasValidDeclaredLength(
        response.headers,
        MAX_SITEVERIFY_RESPONSE_BYTES
      )
    ) {
      return "unavailable"
    }

    const text = await readBoundedText(
      response.body,
      MAX_SITEVERIFY_RESPONSE_BYTES
    )
    const parsed: unknown = JSON.parse(text)
    return parseSiteverifyResponse(
      parsed,
      options.expectedHostname,
      options.expectedAction,
      nowSeconds
    )
  }

  try {
    return await Promise.race([verify(), timeout])
  } catch {
    return "unavailable"
  } finally {
    if (timeoutId !== undefined) clearTimeout(timeoutId)
  }
}

function isAnonymousSubject(value: unknown): value is string {
  return (
    typeof value === "string" &&
    ANONYMOUS_SUBJECT_PATTERN.test(value)
  )
}

function isSafeTimestamp(value: unknown): value is number {
  return (
    typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= 0
  )
}

function signCookiePayload(payload: string, secret: string): Buffer {
  return createHmac("sha256", secret)
    .update(COOKIE_CONTEXT, "utf8")
    .update(payload, "ascii")
    .digest()
}

function decodeCanonicalBase64Url(
  value: string,
  maximumBytes: number
): Buffer | null {
  if (
    value.length === 0 ||
    !/^[A-Za-z0-9_-]+$/.test(value)
  ) {
    return null
  }
  const decoded = Buffer.from(value, "base64url")
  if (
    decoded.byteLength > maximumBytes ||
    decoded.toString("base64url") !== value
  ) {
    return null
  }
  return decoded
}

export function createAnonymousSessionCookie(
  subject: string,
  secret: string,
  nowSeconds = Math.floor(Date.now() / 1_000)
): { value: string; expiresAt: number } {
  if (!isAnonymousSubject(subject)) {
    throw new Error("Anonymous session subject must contain a UUIDv4")
  }
  if (!isSigningSecret(secret)) {
    throw new Error("ANONYMOUS_SESSION_SECRET must be at least 32 bytes")
  }
  if (!isSafeTimestamp(nowSeconds)) {
    throw new Error("Anonymous session timestamp is invalid")
  }

  const expiresAt = nowSeconds + ANONYMOUS_SESSION_TTL_SECONDS
  const payload = Buffer.from(
    JSON.stringify({
      v: 1,
      sub: subject,
      iat: nowSeconds,
      exp: expiresAt,
    }),
    "utf8"
  ).toString("base64url")
  const signature = signCookiePayload(payload, secret).toString("base64url")
  return { value: `${payload}.${signature}`, expiresAt }
}

export function readAnonymousSessionCookie(
  cookie: string,
  secret: string,
  nowSeconds = Math.floor(Date.now() / 1_000)
): string | null {
  if (
    !isSigningSecret(secret) ||
    !isSafeTimestamp(nowSeconds) ||
    byteLength(cookie) > MAX_COOKIE_BYTES
  ) {
    return null
  }

  const segments = cookie.split(".")
  if (segments.length !== 2) return null
  const [payload, suppliedSignature] = segments
  const payloadBytes = decodeCanonicalBase64Url(
    payload,
    MAX_COOKIE_PAYLOAD_BYTES
  )
  const signatureBytes = decodeCanonicalBase64Url(
    suppliedSignature,
    32
  )
  if (
    payloadBytes === null ||
    signatureBytes === null ||
    signatureBytes.byteLength !== 32
  ) {
    return null
  }

  const expectedSignature = signCookiePayload(payload, secret)
  if (!timingSafeEqual(signatureBytes, expectedSignature)) return null

  let text: string
  let parsed: unknown
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(payloadBytes)
    parsed = JSON.parse(text)
  } catch {
    return null
  }

  if (
    !isRecord(parsed) ||
    !hasExactKeys(parsed, ["v", "sub", "iat", "exp"]) ||
    JSON.stringify(parsed) !== text ||
    parsed.v !== 1 ||
    !isAnonymousSubject(parsed.sub) ||
    !isSafeTimestamp(parsed.iat) ||
    !isSafeTimestamp(parsed.exp) ||
    parsed.exp - parsed.iat !== ANONYMOUS_SESSION_TTL_SECONDS ||
    parsed.iat > nowSeconds ||
    parsed.exp <= nowSeconds
  ) {
    return null
  }

  return parsed.sub
}

export function createAnonymousSubject(
  randomUUID: () => string
): string {
  const uuid = randomUUID()
  if (!UUID_V4_PATTERN.test(uuid)) {
    throw new Error("Anonymous subject source must return a canonical UUIDv4")
  }
  return `anon:${uuid}`
}
