import { describe, expect, test } from "bun:test"
import {
  ANONYMOUS_SESSION_TTL_SECONDS,
  ANONYMOUS_TOKEN_TTL_SECONDS,
  InvalidAnonymousTokenRequest,
  SITEVERIFY_URL,
  type TurnstileVerification,
  createAnonymousSessionCookie,
  createAnonymousSubject,
  readAnonymousAgentTokenFeature,
  readAnonymousSessionCookie,
  readTurnstileRequest,
  verifyTurnstileToken,
} from "./anonymous-agent-token"

const NOW = 1_800_000_000
const UUID = "123e4567-e89b-42d3-a456-426614174000"
const SUBJECT = `anon:${UUID}`
const AGENT_SECRET = "test-agent-secret-with-more-than-32-characters"
const SESSION_SECRET = "test-anonymous-session-secret-more-than-32-bytes"
const TURNSTILE_SECRET = "test-turnstile-secret"
const HOSTNAME = "syshin0116.dev"
const ACTION = "agent-token"
const CHALLENGE_TS = new Date(NOW * 1_000).toISOString()

const VALID_ENV = {
  AGENT_ANONYMOUS_TOKEN_ENABLED: "true",
  AGENT_AUTH_SECRET: AGENT_SECRET,
  ANONYMOUS_SESSION_SECRET: SESSION_SECRET,
  TURNSTILE_SECRET_KEY: TURNSTILE_SECRET,
  TURNSTILE_EXPECTED_HOSTNAME: HOSTNAME,
  TURNSTILE_EXPECTED_ACTION: ACTION,
}

function jsonResponse(
  body: unknown,
  init: ResponseInit = {}
): Response {
  const headers = new Headers(init.headers)
  if (!headers.has("content-type")) {
    headers.set("content-type", "application/json")
  }
  return new Response(JSON.stringify(body), { ...init, headers })
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
    "TURNSTILE_SECRET_KEY",
    "TURNSTILE_EXPECTED_HOSTNAME",
    "TURNSTILE_EXPECTED_ACTION",
  ] as const)("fails preflight when %s is missing", (key) => {
    expect(
      readAnonymousAgentTokenFeature({ ...VALID_ENV, [key]: undefined })
    ).toEqual({ state: "misconfigured" })
  })

  test.each([
    ["AGENT_AUTH_SECRET", "short"],
    ["AGENT_AUTH_SECRET", "가".repeat(11)],
    ["ANONYMOUS_SESSION_SECRET", "short"],
    ["TURNSTILE_SECRET_KEY", " secret"],
    ["TURNSTILE_SECRET_KEY", "secret "],
    ["TURNSTILE_EXPECTED_HOSTNAME", "https://syshin0116.dev"],
    ["TURNSTILE_EXPECTED_HOSTNAME", "*.syshin0116.dev"],
    ["TURNSTILE_EXPECTED_HOSTNAME", "SYSHIN0116.dev"],
    ["TURNSTILE_EXPECTED_ACTION", "agent token"],
    ["TURNSTILE_EXPECTED_ACTION", "a".repeat(33)],
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
        turnstileSecret: TURNSTILE_SECRET,
        expectedHostname: HOSTNAME,
        expectedAction: ACTION,
      },
    })
  })
})

describe("readTurnstileRequest", () => {
  test.each(["application/json", "application/json; charset=utf-8"])(
    "accepts a canonical bounded JSON body with %s",
    async (contentType) => {
      const token = "turnstile-token._~-123"
      const request = new Request("https://example.test/api/agent-token", {
        method: "POST",
        headers: { "content-type": contentType },
        body: JSON.stringify({ turnstileToken: token }),
      })

      await expect(readTurnstileRequest(request)).resolves.toEqual({
        turnstileToken: token,
      })
    }
  )

  test.each([
    ["missing content type", JSON.stringify({ turnstileToken: "token" }), undefined],
    ["wrong content type", JSON.stringify({ turnstileToken: "token" }), "text/plain"],
    ["malformed JSON", "{", "application/json"],
    ["null", "null", "application/json"],
    ["array", "[]", "application/json"],
    ["missing field", "{}", "application/json"],
    [
      "extra field",
      JSON.stringify({ turnstileToken: "token", extra: true }),
      "application/json",
    ],
    [
      "duplicate field",
      '{"turnstileToken":"first","turnstileToken":"second"}',
      "application/json",
    ],
    ["boolean token", '{"turnstileToken":true}', "application/json"],
    ["numeric token", '{"turnstileToken":1}', "application/json"],
    ["null token", '{"turnstileToken":null}', "application/json"],
    ["object token", '{"turnstileToken":{}}', "application/json"],
    ["array token", '{"turnstileToken":[]}', "application/json"],
    ["empty token", '{"turnstileToken":""}', "application/json"],
    ["space token", '{"turnstileToken":" "}', "application/json"],
    ["leading space", '{"turnstileToken":" token"}', "application/json"],
    ["trailing space", '{"turnstileToken":"token "}', "application/json"],
    ["control character", '{"turnstileToken":"token\\n"}', "application/json"],
    ["non-ASCII token", '{"turnstileToken":"토큰"}', "application/json"],
    [
      "oversized token",
      JSON.stringify({ turnstileToken: "a".repeat(2_049) }),
      "application/json",
    ],
    [
      "non-canonical whitespace",
      '{ "turnstileToken": "token" }',
      "application/json",
    ],
  ])("rejects %s", async (_name, body, contentType) => {
    const headers = contentType ? { "content-type": contentType } : undefined
    const request = new Request("https://example.test/api/agent-token", {
      method: "POST",
      headers,
      body,
    })

    await expect(readTurnstileRequest(request)).rejects.toBeInstanceOf(
      InvalidAnonymousTokenRequest
    )
  })

  test("rejects a body beyond the route byte budget", async () => {
    const request = new Request("https://example.test/api/agent-token", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        turnstileToken: "token",
        padding: "x".repeat(5_000),
      }),
    })

    await expect(readTurnstileRequest(request)).rejects.toBeInstanceOf(
      InvalidAnonymousTokenRequest
    )
  })

  test("rejects a non-canonical Content-Length before reading", async () => {
    const request = new Request("https://example.test/api/agent-token", {
      method: "POST",
      headers: {
        "content-length": "0030",
        "content-type": "application/json",
      },
      body: JSON.stringify({ turnstileToken: "token" }),
    })

    await expect(readTurnstileRequest(request)).rejects.toBeInstanceOf(
      InvalidAnonymousTokenRequest
    )
  })
})

describe("verifyTurnstileToken", () => {
  test("uses only the fixed HTTPS endpoint and validates the documented response", async () => {
    let calledUrl: string | URL | Request | undefined
    let calledInit: RequestInit | undefined
    const fetchImpl = async (
      input: string | URL | Request,
      init?: RequestInit
    ) => {
      calledUrl = input
      calledInit = init
      return jsonResponse({
        success: true,
        challenge_ts: CHALLENGE_TS,
        hostname: HOSTNAME,
        "error-codes": [],
        action: ACTION,
        cdata: "session_123",
        metadata: { ephemeral_id: "x:test" },
      })
    }

    await expect(
      verifyTurnstileToken({
        token: "client-token",
        secret: TURNSTILE_SECRET,
        expectedHostname: HOSTNAME,
        expectedAction: ACTION,
        fetchImpl,
        timeoutMs: 100,
        nowSeconds: NOW,
      })
    ).resolves.toBe("verified")

    expect(calledUrl).toBe(SITEVERIFY_URL)
    expect(calledInit?.method).toBe("POST")
    expect(new Headers(calledInit?.headers).get("content-type")).toBe(
      "application/x-www-form-urlencoded"
    )
    expect(calledInit?.signal).toBeInstanceOf(AbortSignal)
    expect(calledInit?.redirect).toBe("error")
    expect(calledInit?.cache).toBe("no-store")
    expect(calledInit?.credentials).toBe("omit")
    const form = new URLSearchParams(calledInit?.body as string)
    expect([...form.keys()].sort()).toEqual(["response", "secret"])
    expect(form.get("response")).toBe("client-token")
    expect(form.get("secret")).toBe(TURNSTILE_SECRET)
  })

  test.each([
    [
      "failure",
      { success: false, "error-codes": ["invalid-input-response"] },
      "rejected",
    ],
    [
      "hostname mismatch",
      {
        success: true,
        challenge_ts: CHALLENGE_TS,
        hostname: "evil.example",
        action: ACTION,
      },
      "rejected",
    ],
    [
      "action mismatch",
      {
        success: true,
        challenge_ts: CHALLENGE_TS,
        hostname: HOSTNAME,
        action: "different-action",
      },
      "rejected",
    ],
    [
      "stale challenge",
      {
        success: true,
        challenge_ts: new Date((NOW - 331) * 1_000).toISOString(),
        hostname: HOSTNAME,
        action: ACTION,
      },
      "rejected",
    ],
    [
      "string success confusion",
      {
        success: "true",
        challenge_ts: CHALLENGE_TS,
        hostname: HOSTNAME,
        action: ACTION,
      },
      "unavailable",
    ],
    [
      "missing hostname",
      { success: true, challenge_ts: CHALLENGE_TS, action: ACTION },
      "unavailable",
    ],
    [
      "missing action",
      { success: true, challenge_ts: CHALLENGE_TS, hostname: HOSTNAME },
      "unavailable",
    ],
    [
      "non-string hostname",
      {
        success: true,
        challenge_ts: CHALLENGE_TS,
        hostname: 1,
        action: ACTION,
      },
      "unavailable",
    ],
    [
      "non-string action",
      {
        success: true,
        challenge_ts: CHALLENGE_TS,
        hostname: HOSTNAME,
        action: true,
      },
      "unavailable",
    ],
    [
      "unknown field",
      {
        success: true,
        challenge_ts: CHALLENGE_TS,
        hostname: HOSTNAME,
        action: ACTION,
        score: 1,
      },
      "unavailable",
    ],
    [
      "malformed error codes",
      {
        success: true,
        challenge_ts: CHALLENGE_TS,
        hostname: HOSTNAME,
        action: ACTION,
        "error-codes": "none",
      },
      "unavailable",
    ],
    [
      "malformed challenge timestamp",
      {
        success: true,
        hostname: HOSTNAME,
        action: ACTION,
        challenge_ts: "not-a-date",
      },
      "unavailable",
    ],
    [
      "impossible challenge timestamp",
      {
        success: true,
        hostname: HOSTNAME,
        action: ACTION,
        challenge_ts: "2027-02-31T00:00:00Z",
      },
      "unavailable",
    ],
    [
      "malformed metadata",
      {
        success: true,
        challenge_ts: CHALLENGE_TS,
        hostname: HOSTNAME,
        action: ACTION,
        metadata: { unexpected: "value" },
      },
      "unavailable",
    ],
  ])("fails closed for %s", async (_name, body, expected) => {
    await expect(
      verifyTurnstileToken({
        token: "client-token",
        secret: TURNSTILE_SECRET,
        expectedHostname: HOSTNAME,
        expectedAction: ACTION,
        fetchImpl: async () => jsonResponse(body),
        timeoutMs: 100,
        nowSeconds: NOW,
      })
    ).resolves.toBe(expected as TurnstileVerification)
  })

  test.each([
    [
      "non-2xx response",
      async () =>
        jsonResponse(
          {
            success: true,
            challenge_ts: CHALLENGE_TS,
            hostname: HOSTNAME,
            action: ACTION,
          },
          { status: 500 }
        ),
    ],
    [
      "redirect response",
      async () =>
        jsonResponse(
          {
            success: true,
            challenge_ts: CHALLENGE_TS,
            hostname: HOSTNAME,
            action: ACTION,
          },
          {
            status: 302,
            headers: {
              location: "https://attacker.example/siteverify",
            },
          }
        ),
    ],
    [
      "wrong media type",
      async () =>
        new Response(
          JSON.stringify({ success: true, hostname: HOSTNAME, action: ACTION }),
          { headers: { "content-type": "text/plain" } }
        ),
    ],
    [
      "malformed JSON",
      async () =>
        new Response("{", {
          headers: { "content-type": "application/json" },
        }),
    ],
    [
      "oversized response",
      async () =>
        jsonResponse({
          success: true,
          challenge_ts: CHALLENGE_TS,
          hostname: HOSTNAME,
          action: ACTION,
          cdata: "x".repeat(20_000),
        }),
    ],
    [
      "network failure",
      async () => {
        throw new Error("network details must stay internal")
      },
    ],
  ])("fails closed for %s", async (_name, fetchImpl) => {
    await expect(
      verifyTurnstileToken({
        token: "client-token",
        secret: TURNSTILE_SECRET,
        expectedHostname: HOSTNAME,
        expectedAction: ACTION,
        fetchImpl,
        timeoutMs: 100,
        nowSeconds: NOW,
      })
    ).resolves.toBe("unavailable")
  })

  test("aborts a hung Siteverify request at the fixed timeout", async () => {
    const fetchImpl = async (
      _input: string | URL | Request,
      init?: RequestInit
    ): Promise<Response> =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => reject(new DOMException("aborted", "AbortError")),
          { once: true }
        )
      })

    await expect(
      verifyTurnstileToken({
        token: "client-token",
        secret: TURNSTILE_SECRET,
        expectedHostname: HOSTNAME,
        expectedAction: ACTION,
        fetchImpl,
        timeoutMs: 5,
        nowSeconds: NOW,
      })
    ).resolves.toBe("unavailable")
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
