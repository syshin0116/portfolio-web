import { createHmac, timingSafeEqual } from "node:crypto"

export const ANONYMOUS_COOKIE_NAME = "agent-anonymous-session"
export const ANONYMOUS_SESSION_TTL_SECONDS = 14 * 24 * 60 * 60
export const ANONYMOUS_TOKEN_TTL_SECONDS = 300

const MAX_COOKIE_BYTES = 1_024
const MAX_COOKIE_PAYLOAD_BYTES = 512
const MAX_SECRET_BYTES = 4_096
const MIN_SECRET_BYTES = 32
const COOKIE_CONTEXT = "syshin0116.dev/anonymous-session/v1\u0000"
const UUID_V4_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const ANONYMOUS_SUBJECT_PATTERN =
  /^anon:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

export interface AnonymousAgentTokenConfig {
  agentAuthSecret: string
  anonymousSessionSecret: string
}

export type AnonymousAgentTokenFeature =
  | { state: "disabled" }
  | { state: "misconfigured" }
  | { state: "enabled"; config: AnonymousAgentTokenConfig }

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

  if (
    !isAgentAuthSecret(agentAuthSecret) ||
    !isSigningSecret(anonymousSessionSecret) ||
    anonymousSessionSecret === agentAuthSecret
  ) {
    return { state: "misconfigured" }
  }

  return {
    state: "enabled",
    config: {
      agentAuthSecret,
      anonymousSessionSecret,
    },
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
