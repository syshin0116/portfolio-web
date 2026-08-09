import {
  AGENT_TOKEN_INTENT_HEADER,
  ANONYMOUS_AGENT_TOKEN_INTENT,
} from "@/lib/agent-token-intent"

const TOKEN_ENDPOINT = "/api/anonymous-agent-token"
const TOKEN_ISSUER = "syshin0116.dev"
const TOKEN_AUDIENCE = "agent-api"
const TOKEN_SCOPE = "anon"
const TOKEN_TTL_SECONDS = 300
const MAX_RESPONSE_BYTES = 8 * 1_024
const MAX_TOKEN_BYTES = 4 * 1_024
const ANONYMOUS_SUBJECT_PATTERN =
  /^anon:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const BASE64URL_PATTERN = /^[A-Za-z0-9_-]+$/

export type AnonymousChatConfig =
  | { state: "disabled" }
  | { state: "enabled" }

export interface AnonymousCredential {
  readonly expiresAt: number
  readonly identity: string
  readonly token: string
}

export type AnonymousBootstrapFailure =
  | "network"
  | "rate-limited"
  | "unavailable"

export class AnonymousBootstrapError extends Error {
  readonly kind: AnonymousBootstrapFailure
  readonly status?: number

  constructor(kind: AnonymousBootstrapFailure, status?: number) {
    super("Anonymous chat bootstrap failed")
    this.name = "AnonymousBootstrapError"
    this.kind = kind
    this.status = status
    this.stack = undefined
  }
}

type FetchLike = (
  input: RequestInfo | URL,
  init?: RequestInit
) => Promise<Response>

interface AnonymousBootstrapOptions {
  fetch?: FetchLike
  nowSeconds?: () => number
  signal: AbortSignal
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value)
  )
}

function exactKeys(
  value: Record<string, unknown>,
  expected: readonly string[]
): boolean {
  const actual = Object.keys(value).sort()
  const sortedExpected = [...expected].sort()
  return (
    actual.length === sortedExpected.length &&
    actual.every((key, index) => key === sortedExpected[index])
  )
}

function decodeJwtObject(segment: string): Record<string, unknown> {
  if (
    segment.length === 0 ||
    segment.length > MAX_TOKEN_BYTES ||
    !BASE64URL_PATTERN.test(segment)
  ) {
    throw new AnonymousBootstrapError("unavailable")
  }
  const base64 = segment.replace(/-/g, "+").replace(/_/g, "/")
  const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, "=")
  try {
    const bytes = Uint8Array.from(atob(padded), (character) =>
      character.charCodeAt(0)
    )
    const decoded = new TextDecoder("utf-8", { fatal: true }).decode(bytes)
    const parsed = JSON.parse(decoded) as unknown
    if (!isRecord(parsed)) {
      throw new Error("JWT segment is not an object")
    }
    return parsed
  } catch {
    throw new AnonymousBootstrapError("unavailable")
  }
}

function validateAnonymousToken(
  token: string,
  responseExpiresAt: unknown,
  nowSeconds: number
): AnonymousCredential {
  if (
    token.length === 0 ||
    new TextEncoder().encode(token).length > MAX_TOKEN_BYTES ||
    token.trim() !== token
  ) {
    throw new AnonymousBootstrapError("unavailable")
  }
  const parts = token.split(".")
  if (
    parts.length !== 3 ||
    !BASE64URL_PATTERN.test(parts[2] ?? "")
  ) {
    throw new AnonymousBootstrapError("unavailable")
  }
  const header = decodeJwtObject(parts[0]!)
  const claims = decodeJwtObject(parts[1]!)
  if (
    !exactKeys(header, ["alg", "typ"]) ||
    header.alg !== "HS256" ||
    header.typ !== "JWT" ||
    !exactKeys(claims, ["aud", "exp", "iat", "iss", "scope", "sub"])
  ) {
    throw new AnonymousBootstrapError("unavailable")
  }
  const issuedAt = claims.iat
  const expiresAt = claims.exp
  const identity = claims.sub
  if (
    claims.iss !== TOKEN_ISSUER ||
    claims.aud !== TOKEN_AUDIENCE ||
    claims.scope !== TOKEN_SCOPE ||
    typeof identity !== "string" ||
    !ANONYMOUS_SUBJECT_PATTERN.test(identity) ||
    typeof issuedAt !== "number" ||
    !Number.isSafeInteger(issuedAt) ||
    typeof expiresAt !== "number" ||
    !Number.isSafeInteger(expiresAt) ||
    expiresAt - issuedAt !== TOKEN_TTL_SECONDS ||
    expiresAt <= nowSeconds ||
    responseExpiresAt !== expiresAt
  ) {
    throw new AnonymousBootstrapError("unavailable")
  }
  return { token, identity, expiresAt }
}

async function readBoundedJson(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type")
  if (
    contentType === null ||
    contentType.split(";", 1)[0]?.trim().toLowerCase() !==
      "application/json"
  ) {
    throw new AnonymousBootstrapError("unavailable")
  }
  const cacheControl = response.headers.get("cache-control")
  if (
    cacheControl === null ||
    !cacheControl
      .split(",")
      .some((directive) => directive.trim().toLowerCase() === "no-store")
  ) {
    throw new AnonymousBootstrapError("unavailable")
  }
  const declaredLength = response.headers.get("content-length")
  if (
    declaredLength !== null &&
    (!declaredLength.match(/^[0-9]+$/) ||
      Number(declaredLength) > MAX_RESPONSE_BYTES)
  ) {
    throw new AnonymousBootstrapError("unavailable")
  }

  const reader = response.body?.getReader()
  if (!reader) throw new AnonymousBootstrapError("unavailable")
  const decoder = new TextDecoder("utf-8", { fatal: true })
  let total = 0
  let text = ""
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      total += value.byteLength
      if (total > MAX_RESPONSE_BYTES) {
        await reader.cancel()
        throw new AnonymousBootstrapError("unavailable")
      }
      text += decoder.decode(value, { stream: true })
    }
    text += decoder.decode()
    return JSON.parse(text) as unknown
  } catch (error) {
    if (error instanceof AnonymousBootstrapError) throw error
    throw new AnonymousBootstrapError("unavailable")
  }
}

function bootstrapFailure(status: number): AnonymousBootstrapError {
  if (status === 429) {
    return new AnonymousBootstrapError("rate-limited", status)
  }
  return new AnonymousBootstrapError("unavailable", status)
}

export function resolveAnonymousChatConfig(
  enabled: string | undefined
): AnonymousChatConfig {
  if (enabled !== "true") return { state: "disabled" }
  return { state: "enabled" }
}

export async function bootstrapAnonymousSession(
  options: AnonymousBootstrapOptions
): Promise<AnonymousCredential> {
  options.signal.throwIfAborted()
  const fetchImpl =
    options.fetch ?? ((input, init) => fetch(input, init))
  const init: RequestInit = {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: {
      [AGENT_TOKEN_INTENT_HEADER]: ANONYMOUS_AGENT_TOKEN_INTENT,
    },
    redirect: "error",
    referrerPolicy: "no-referrer",
    signal: options.signal,
  }

  let response: Response
  try {
    response = await fetchImpl(TOKEN_ENDPOINT, init)
  } catch (error) {
    if (options.signal.aborted) throw error
    throw new AnonymousBootstrapError("network")
  }
  if (!response.ok) {
    await response.body?.cancel()
    throw bootstrapFailure(response.status)
  }

  const body = await readBoundedJson(response)
  if (!isRecord(body) || !exactKeys(body, ["expiresAt", "token"])) {
    throw new AnonymousBootstrapError("unavailable")
  }
  if (typeof body.token !== "string") {
    throw new AnonymousBootstrapError("unavailable")
  }
  return validateAnonymousToken(
    body.token,
    body.expiresAt,
    Math.floor((options.nowSeconds ?? (() => Date.now() / 1_000))())
  )
}

export const anonymousBootstrapTesting = {
  validateAnonymousToken,
}
