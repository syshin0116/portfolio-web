import { createHmac } from "node:crypto"

const TOKEN_ISSUER = "syshin0116.dev"
const TOKEN_AUDIENCE = "agent-api"
const MIN_SECRET_LENGTH = 32
const SCOPE_PATTERN = /^[A-Za-z0-9:_-]+$/
const MAX_SCOPE_LENGTH = 512

function encode(value: Record<string, unknown>): string {
  return Buffer.from(JSON.stringify(value)).toString("base64url")
}

export function createAgentToken(
  subject: string,
  secret = process.env.AGENT_AUTH_SECRET ?? "",
  now = Math.floor(Date.now() / 1000),
  ttlSeconds = 15 * 60,
  scopes: readonly string[] = []
): { token: string; expiresAt: number } {
  if (!subject) throw new Error("Agent token subject is required")
  if (secret.length < MIN_SECRET_LENGTH) {
    throw new Error("AGENT_AUTH_SECRET must be at least 32 characters")
  }

  const expiresAt = now + ttlSeconds
  const header = encode({ alg: "HS256", typ: "JWT" })
  const payload: Record<string, unknown> = {
    sub: subject,
    iss: TOKEN_ISSUER,
    aud: TOKEN_AUDIENCE,
    iat: now,
    exp: expiresAt,
  }
  const normalizedScopes = [...new Set(scopes.map((scope) => scope.trim()))]
    .filter(Boolean)
    .sort()
  if (normalizedScopes.some((scope) => !SCOPE_PATTERN.test(scope))) {
    throw new Error("Invalid agent token scope")
  }
  if (normalizedScopes.length > 0) {
    const scope = normalizedScopes.join(" ")
    if (scope.length > MAX_SCOPE_LENGTH) {
      throw new Error("Invalid agent token scope")
    }
    payload.scope = scope
  }
  const encodedPayload = encode(payload)
  const signingInput = `${header}.${encodedPayload}`
  const signature = createHmac("sha256", secret)
    .update(signingInput)
    .digest("base64url")

  return { token: `${signingInput}.${signature}`, expiresAt }
}
