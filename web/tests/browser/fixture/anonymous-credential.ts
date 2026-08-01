export const FIXTURE_ANONYMOUS_IDENTITY =
  "anon:123e4567-e89b-42d3-a456-426614174000"
export const FIXTURE_OWNER_IDENTITY = "browser-fixture-user"
export const FIXTURE_TOKEN_EXPIRES_AT = 4_102_444_800

const encode = (value: object) =>
  Buffer.from(JSON.stringify(value)).toString("base64url")

function fixtureToken(
  identity: string,
  extraClaims: Record<string, unknown> = {},
  expiresAt = FIXTURE_TOKEN_EXPIRES_AT
): string {
  return `${encode({ alg: "HS256", typ: "JWT" })}.${encode({
    exp: expiresAt,
    sub: identity,
    iss: "syshin0116.dev",
    aud: "agent-api",
    iat: expiresAt - 300,
    ...extraClaims,
  })}.fixture-signature`
}

export function fixtureOwnerToken(): string {
  return fixtureToken(FIXTURE_OWNER_IDENTITY)
}

export function fixtureAnonymousToken(
  identity = FIXTURE_ANONYMOUS_IDENTITY,
  expiresAt = FIXTURE_TOKEN_EXPIRES_AT
): string {
  return fixtureToken(identity, { scope: "anon" }, expiresAt)
}
