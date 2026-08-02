import { describe, expect, test } from "bun:test"

import {
  AnonymousBootstrapError,
  bootstrapAnonymousSession,
  resolveAnonymousChatConfig,
} from "./anonymous-bootstrap"

const IDENTITY = "anon:123e4567-e89b-42d3-a456-426614174000"

function encode(value: object): string {
  return Buffer.from(JSON.stringify(value)).toString("base64url")
}

function token(
  overrides: Record<string, unknown> = {},
  header: Record<string, unknown> = { alg: "HS256", typ: "JWT" }
): string {
  return `${encode(header)}.${encode({
    sub: IDENTITY,
    iss: "syshin0116.dev",
    aud: "agent-api",
    iat: 1_000,
    exp: 1_300,
    scope: "anon",
    ...overrides,
  })}.signature`
}

function response(
  body: unknown,
  status = 200,
  headers: Record<string, string> = {}
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "cache-control": "no-store",
      "content-type": "application/json",
      ...headers,
    },
  })
}

describe("resolveAnonymousChatConfig", () => {
  test.each([undefined, "", "false", "TRUE", "1"])(
    "stays disabled unless the flag is exactly true: %s",
    (flag) => {
      expect(resolveAnonymousChatConfig(flag, "site-key-123")).toEqual({
        state: "disabled",
      })
    }
  )

  test.each([
    undefined,
    "",
    " short",
    "short",
    "site key with spaces",
    "site-key-123 ",
  ])("fails closed on an invalid public site key: %s", (siteKey) => {
    expect(resolveAnonymousChatConfig("true", siteKey)).toHaveProperty(
      "state",
      "misconfigured"
    )
  })

  test("accepts one bounded public site key", () => {
    expect(
      resolveAnonymousChatConfig(
        "true",
        "1x00000000000000000000AA"
      )
    ).toEqual({
      state: "enabled",
      siteKey: "1x00000000000000000000AA",
    })
  })
})

describe("bootstrapAnonymousSession", () => {
  test("resumes a cookie session without sending a body", async () => {
    let captured: RequestInit | undefined
    const credential = await bootstrapAnonymousSession({
      signal: new AbortController().signal,
      nowSeconds: () => 1_001,
      fetch: async (input, init) => {
        expect(input).toBe("/api/agent-token")
        captured = init
        return response({ token: token(), expiresAt: 1_300 })
      },
    })

    expect(credential).toEqual({
      token: token(),
      identity: IDENTITY,
      expiresAt: 1_300,
    })
    expect(captured).toMatchObject({
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      redirect: "error",
      referrerPolicy: "no-referrer",
    })
    expect(new Headers(captured?.headers).get("x-agent-token-intent")).toBe(
      "anonymous"
    )
    expect(captured?.body).toBeUndefined()
  })

  test("sends one exact Turnstile request and never persists the token", async () => {
    let captured: RequestInit | undefined
    await bootstrapAnonymousSession({
      signal: new AbortController().signal,
      turnstileToken: "one-time-challenge",
      nowSeconds: () => 1_001,
      fetch: async (_input, init) => {
        captured = init
        return response({ token: token(), expiresAt: 1_300 })
      },
    })

    expect(new Headers(captured?.headers).get("content-type")).toBe(
      "application/json"
    )
    expect(new Headers(captured?.headers).get("x-agent-token-intent")).toBe(
      "anonymous"
    )
    expect(captured?.body).toBe(
      JSON.stringify({ turnstileToken: "one-time-challenge" })
    )
  })

  test("maps an empty-cookie resume to a new challenge", async () => {
    await expect(
      bootstrapAnonymousSession({
        signal: new AbortController().signal,
        fetch: async () => response({ challengeRequired: true }),
      })
    ).rejects.toMatchObject({
      name: "AnonymousBootstrapError",
      kind: "challenge-required",
      status: 200,
    })
  })

  test.each([
    [400, "rejected"],
    [403, "rejected"],
    [429, "rate-limited"],
    [503, "unavailable"],
  ] as const)(
    "maps challenged status %s to %s",
    async (status, kind) => {
      await expect(
        bootstrapAnonymousSession({
          signal: new AbortController().signal,
          turnstileToken: "one-time-challenge",
          fetch: async () => response({}, status),
        })
      ).rejects.toMatchObject({ kind, status })
    }
  )

  test.each([
    [{ token: token(), expiresAt: 1_301 }, "response expiry mismatch"],
    [{ token: token({ scope: "admin" }), expiresAt: 1_300 }, "wrong scope"],
    [
      {
        token: token({ sub: "user-1" }),
        expiresAt: 1_300,
      },
      "signed-in subject",
    ],
    [
      {
        token: token({ exp: 1_299 }),
        expiresAt: 1_299,
      },
      "wrong TTL",
    ],
    [
      {
        token: token({ extra: true }),
        expiresAt: 1_300,
      },
      "unknown claim",
    ],
    [
      {
        token: token({}, { alg: "none", typ: "JWT" }),
        expiresAt: 1_300,
      },
      "wrong algorithm",
    ],
  ])("rejects a malformed credential: %s", async (body) => {
    await expect(
      bootstrapAnonymousSession({
        signal: new AbortController().signal,
        nowSeconds: () => 1_001,
        fetch: async () => response(body),
      })
    ).rejects.toBeInstanceOf(AnonymousBootstrapError)
  })

  test("rejects missing no-store and oversized responses", async () => {
    await expect(
      bootstrapAnonymousSession({
        signal: new AbortController().signal,
        fetch: async () =>
          response(
            { token: token(), expiresAt: 1_300 },
            200,
            { "cache-control": "private" }
          ),
      })
    ).rejects.toMatchObject({ kind: "unavailable" })

    await expect(
      bootstrapAnonymousSession({
        signal: new AbortController().signal,
        fetch: async () =>
          response(
            { token: token(), expiresAt: 1_300 },
            200,
            { "content-length": "8193" }
          ),
      })
    ).rejects.toMatchObject({ kind: "unavailable" })
  })

  test("preserves caller cancellation and sanitizes network failures", async () => {
    const controller = new AbortController()
    controller.abort(new DOMException("stop", "AbortError"))
    await expect(
      bootstrapAnonymousSession({
        signal: controller.signal,
        fetch: async () => {
          throw new Error("must not run")
        },
      })
    ).rejects.toMatchObject({ name: "AbortError" })

    await expect(
      bootstrapAnonymousSession({
        signal: new AbortController().signal,
        fetch: async () => {
          throw new Error("private network detail")
        },
      })
    ).rejects.toMatchObject({
      name: "AnonymousBootstrapError",
      kind: "network",
      message: "Anonymous chat bootstrap failed",
    })
  })
})
