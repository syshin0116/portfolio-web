import { describe, expect, test } from "bun:test"
import {
  ANONYMOUS_SESSION_TTL_SECONDS,
  ANONYMOUS_TOKEN_TTL_SECONDS,
  createAnonymousSessionCookie,
  createAnonymousSubject,
  readAnonymousAgentTokenFeature,
  readAnonymousSessionCookie,
} from "./anonymous-agent-token"

const NOW = 1_800_000_000
const UUID = "123e4567-e89b-42d3-a456-426614174000"
const SUBJECT = `anon:${UUID}`
const AGENT_SECRET = "test-agent-secret-with-more-than-32-characters"
const SESSION_SECRET = "test-anonymous-session-secret-more-than-32-bytes"

const VALID_ENV = {
  AGENT_ANONYMOUS_TOKEN_ENABLED: "true",
  AGENT_AUTH_SECRET: AGENT_SECRET,
  ANONYMOUS_SESSION_SECRET: SESSION_SECRET,
}

describe("readAnonymousAgentTokenFeature", () => {
  test.each([
    [undefined, "missing"],
    ["false", "explicit false"],
    ["TRUE", "case confusion"],
    ["False", "case confusion"],
    ["1", "numeric string"],
    ["0", "numeric string"],
    [" true", "leading whitespace"],
    ["true ", "trailing whitespace"],
    ["", "empty string"],
    [true, "boolean true"],
    [false, "boolean false"],
    [1, "number one"],
    [0, "number zero"],
    [null, "null"],
    [{}, "object"],
    [[], "array"],
  ])("keeps the anonymous branch disabled for %# (%s)", (value) => {
    expect(
      readAnonymousAgentTokenFeature({
        ...VALID_ENV,
        AGENT_ANONYMOUS_TOKEN_ENABLED: value,
      })
    ).toEqual({ state: "disabled" })
  })

  test.each([
    "AGENT_AUTH_SECRET",
    "ANONYMOUS_SESSION_SECRET",
  ] as const)("fails preflight when %s is missing", (key) => {
    expect(
      readAnonymousAgentTokenFeature({ ...VALID_ENV, [key]: undefined })
    ).toEqual({ state: "misconfigured" })
  })

  test.each([
    ["AGENT_AUTH_SECRET", "short"],
    ["AGENT_AUTH_SECRET", "가".repeat(11)],
    ["ANONYMOUS_SESSION_SECRET", "short"],
  ])("rejects invalid %s value", (key, value) => {
    expect(
      readAnonymousAgentTokenFeature({ ...VALID_ENV, [key]: value })
    ).toEqual({ state: "misconfigured" })
  })

  test("rejects reuse of the shared agent JWT key as the cookie key", () => {
    expect(
      readAnonymousAgentTokenFeature({
        ...VALID_ENV,
        ANONYMOUS_SESSION_SECRET: AGENT_SECRET,
      })
    ).toEqual({ state: "misconfigured" })
  })

  test("returns only validated server-side configuration", () => {
    expect(readAnonymousAgentTokenFeature(VALID_ENV)).toEqual({
      state: "enabled",
      config: {
        agentAuthSecret: AGENT_SECRET,
        anonymousSessionSecret: SESSION_SECRET,
      },
    })
  })
})

describe("anonymous session cookie", () => {
  test("round-trips a signed UUIDv4 subject for exactly fourteen days", () => {
    const created = createAnonymousSessionCookie(
      SUBJECT,
      SESSION_SECRET,
      NOW
    )

    expect(created.expiresAt).toBe(NOW + ANONYMOUS_SESSION_TTL_SECONDS)
    expect(readAnonymousSessionCookie(created.value, SESSION_SECRET, NOW)).toBe(
      SUBJECT
    )
    expect(
      readAnonymousSessionCookie(
        created.value,
        SESSION_SECRET,
        created.expiresAt - 1
      )
    ).toBe(SUBJECT)
    expect(
      readAnonymousSessionCookie(
        created.value,
        SESSION_SECRET,
        created.expiresAt
      )
    ).toBeNull()
  })

  test.each([
    ["wrong secret", "another-test-session-secret-more-than-32-bytes"],
    ["weak secret", "short"],
  ])("rejects a cookie with %s", (_name, secret) => {
    const created = createAnonymousSessionCookie(
      SUBJECT,
      SESSION_SECRET,
      NOW
    )
    expect(readAnonymousSessionCookie(created.value, secret, NOW)).toBeNull()
  })

  test("rejects payload and signature forgery", () => {
    const created = createAnonymousSessionCookie(
      SUBJECT,
      SESSION_SECRET,
      NOW
    )
    const [payload, signature] = created.value.split(".")
    const changedPayload = `${payload.slice(0, -1)}${
      payload.endsWith("A") ? "B" : "A"
    }`
    const changedSignature = `${signature.slice(0, -1)}${
      signature.endsWith("A") ? "B" : "A"
    }`

    expect(
      readAnonymousSessionCookie(
        `${changedPayload}.${signature}`,
        SESSION_SECRET,
        NOW
      )
    ).toBeNull()
    expect(
      readAnonymousSessionCookie(
        `${payload}.${changedSignature}`,
        SESSION_SECRET,
        NOW
      )
    ).toBeNull()
  })

  test("rejects a cookie issued in the future", () => {
    const created = createAnonymousSessionCookie(
      SUBJECT,
      SESSION_SECRET,
      NOW + 1
    )

    expect(
      readAnonymousSessionCookie(created.value, SESSION_SECRET, NOW)
    ).toBeNull()
  })

  test.each([
    "",
    "not-a-cookie",
    "a.b.c",
    `${"a".repeat(1_025)}.signature`,
  ])("rejects malformed cookie %#", (value) => {
    expect(readAnonymousSessionCookie(value, SESSION_SECRET, NOW)).toBeNull()
  })
})

describe("createAnonymousSubject", () => {
  test("accepts only a canonical random UUIDv4", () => {
    expect(createAnonymousSubject(() => UUID)).toBe(SUBJECT)
  })

  test.each([
    "123e4567-e89b-12d3-a456-426614174000",
    "123e4567-e89b-42d3-7456-426614174000",
    "123E4567-E89B-42D3-A456-426614174000",
    "not-a-uuid",
    "",
  ])("rejects a non-v4 or non-canonical random source result %#", (value) => {
    expect(() => createAnonymousSubject(() => value)).toThrow("UUIDv4")
  })

  test("exports the ADR token lifetime contract", () => {
    expect(ANONYMOUS_TOKEN_TTL_SECONDS).toBe(300)
  })
})
