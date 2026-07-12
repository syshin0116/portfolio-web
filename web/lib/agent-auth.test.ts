import { describe, expect, test } from "bun:test"
import { createAgentToken } from "./agent-auth"

const CONTRACT_TOKEN =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyLTEyMyIsImlzcyI6InN5c2hpbjAxMTYuZGV2IiwiYXVkIjoiYWdlbnQtYXBpIiwiaWF0IjoxMDAwLCJleHAiOjE5MDB9.EUErDCiSa0A4AbbqPOFlkobzB9k4j7Z9uHHZ4lH-KLY"

describe("createAgentToken", () => {
  test("creates a scoped, expiring HS256 token", () => {
    const { token, expiresAt } = createAgentToken(
      "user-123",
      "test-secret-that-is-at-least-thirty-two-bytes",
      1_000,
      900
    )
    const [header, payload, signature] = token.split(".")
    expect(JSON.parse(Buffer.from(header, "base64url").toString())).toEqual({
      alg: "HS256",
      typ: "JWT",
    })
    expect(JSON.parse(Buffer.from(payload, "base64url").toString())).toMatchObject({
      sub: "user-123",
      iss: "syshin0116.dev",
      aud: "agent-api",
      iat: 1_000,
      exp: 1_900,
    })
    expect(signature.length).toBeGreaterThan(20)
    expect(expiresAt).toBe(1_900)
    expect(token).toBe(CONTRACT_TOKEN)
  })

  test("rejects weak configuration", () => {
    expect(() => createAgentToken("user-123", "short")).toThrow(
      "AGENT_AUTH_SECRET"
    )
  })

  test("adds normalized scopes only when granted", () => {
    const { token } = createAgentToken(
      "admin-user",
      "test-secret-that-is-at-least-thirty-two-bytes",
      1_000,
      900,
      ["admin", "admin"]
    )
    const payload = JSON.parse(
      Buffer.from(token.split(".")[1], "base64url").toString()
    )

    expect(payload.scope).toBe("admin")
  })

  test("rejects malformed scopes", () => {
    expect(() =>
      createAgentToken(
        "admin-user",
        "test-secret-that-is-at-least-thirty-two-bytes",
        1_000,
        900,
        ["admin other"]
      )
    ).toThrow("scope")
  })
})
