import { describe, expect, test } from "bun:test"
import { NextRequest } from "next/server"
import { createAgentToken } from "@/lib/agent-auth"
import {
  ANONYMOUS_COOKIE_NAME,
  ANONYMOUS_SESSION_TTL_SECONDS,
  SITEVERIFY_TIMEOUT_MS,
  createAnonymousSessionCookie,
} from "@/lib/anonymous-agent-token"
import {
  type AgentTokenPostDependencies,
  createAgentTokenPostHandler,
} from "@/lib/agent-token-route"

const NOW = 1_800_000_000
const UUID = "123e4567-e89b-42d3-a456-426614174000"
const SECOND_UUID = "123e4567-e89b-42d3-b456-426614174001"
const AGENT_SECRET = "test-agent-secret-with-more-than-32-characters"
const SESSION_SECRET = "test-anonymous-session-secret-more-than-32-bytes"
const TURNSTILE_SECRET = "test-turnstile-secret"
const HOSTNAME = "syshin0116.dev"
const ACTION = "agent-token"
const ANONYMOUS_INTENT_HEADER = "X-Agent-Token-Intent"
const CHALLENGE_TS = new Date(NOW * 1_000).toISOString()

const VALID_ENV = {
  AGENT_ANONYMOUS_TOKEN_ENABLED: "true",
  AGENT_AUTH_SECRET: AGENT_SECRET,
  ANONYMOUS_SESSION_SECRET: SESSION_SECRET,
  TURNSTILE_SECRET_KEY: TURNSTILE_SECRET,
  TURNSTILE_EXPECTED_HOSTNAME: HOSTNAME,
  TURNSTILE_EXPECTED_ACTION: ACTION,
}

type Session = Awaited<ReturnType<AgentTokenPostDependencies["authenticate"]>>

function successResponse(
  overrides: Record<string, unknown> = {}
): Response {
  return new Response(
    JSON.stringify({
      success: true,
      challenge_ts: CHALLENGE_TS,
      hostname: HOSTNAME,
      action: ACTION,
      ...overrides,
    }),
    { headers: { "content-type": "application/json" } }
  )
}

function dependencies(
  overrides: Partial<AgentTokenPostDependencies> = {}
): AgentTokenPostDependencies {
  return {
    authenticate: async () => null,
    createToken: (subject, secret, now, ttl, scopes) =>
      createAgentToken(
        subject,
        secret ?? AGENT_SECRET,
        now ?? NOW,
        ttl,
        scopes
      ),
    isAllowed: (email) => email === "owner@example.com",
    isAdmin: (email) => email === "owner@example.com",
    env: VALID_ENV,
    fetchImpl: async () => successResponse(),
    nowSeconds: () => NOW,
    randomUUID: () => UUID,
    nodeEnv: "production",
    turnstileTimeoutMs: SITEVERIFY_TIMEOUT_MS,
    ...overrides,
  }
}

function request(options: {
  body?: string
  contentType?: string
  cookie?: string
  intent?: string
} = {}): NextRequest {
  const headers = new Headers()
  if (options.contentType) headers.set("content-type", options.contentType)
  if (options.cookie) headers.set("cookie", options.cookie)
  if (options.intent !== undefined) {
    headers.set(ANONYMOUS_INTENT_HEADER, options.intent)
  }
  return new NextRequest("https://syshin0116.dev/api/agent-token", {
    method: "POST",
    headers,
    body: options.body,
  })
}

function anonymousRequest(cookie?: string): NextRequest {
  return request({
    body: JSON.stringify({ turnstileToken: "client-turnstile-token" }),
    contentType: "application/json",
    cookie,
  })
}

function explicitAnonymousRequest(cookie?: string): NextRequest {
  return request({
    body: JSON.stringify({ turnstileToken: "client-turnstile-token" }),
    contentType: "application/json",
    cookie,
    intent: "anonymous",
  })
}

function jwtPayload(token: string): Record<string, unknown> {
  return JSON.parse(Buffer.from(token.split(".")[1], "base64url").toString())
}

function setCookie(response: Response): string | null {
  return response.headers.get("set-cookie")
}

async function responseBody(
  response: Response
): Promise<Record<string, unknown>> {
  return response.json() as Promise<Record<string, unknown>>
}

describe("POST /api/agent-token signed-in precedence", () => {
  test("preserves the owner path without reading anonymous config or body", async () => {
    let fetched = false
    const session: Session = {
      user: {
        id: "owner-id",
        email: "owner@example.com",
        name: "Owner",
        image: null,
      },
      expires: "2099-01-01T00:00:00.000Z",
    }
    const handler = createAgentTokenPostHandler(
      dependencies({
        authenticate: async () => session,
        env: {
          AGENT_ANONYMOUS_TOKEN_ENABLED: "true",
        },
        fetchImpl: async () => {
          fetched = true
          throw new Error("signed-in traffic must not call Siteverify")
        },
      })
    )

    const response = await handler(
      request({ cookie: `${ANONYMOUS_COOKIE_NAME}=forged.cookie` })
    )
    const body = await responseBody(response)
    const payload = jwtPayload(body.token as string)

    expect(response.status).toBe(200)
    expect(response.headers.get("cache-control")).toBe("no-store")
    expect(payload).toMatchObject({
      sub: "owner-id",
      scope: "admin",
    })
    expect((payload.exp as number) - (payload.iat as number)).toBe(900)
    expect(setCookie(response)).toBeNull()
    expect(fetched).toBe(false)
  })

  test("preserves the signed-in non-admin scope", async () => {
    const session: Session = {
      user: {
        id: "member-id",
        email: "member@example.com",
        name: null,
        image: null,
      },
      expires: "2099-01-01T00:00:00.000Z",
    }
    const handler = createAgentTokenPostHandler(
      dependencies({
        authenticate: async () => session,
        isAllowed: (email) => email === "member@example.com",
      })
    )

    const response = await handler(request())
    const payload = jwtPayload((await responseBody(response)).token as string)

    expect(response.status).toBe(200)
    expect(payload.sub).toBe("member-id")
    expect(payload).not.toHaveProperty("scope")
  })

  test("canonicalizes a numeric adapter user id before signing", async () => {
    const session: Session = {
      user: {
        id: 42,
        email: "member@example.com",
        name: null,
        image: null,
      },
      expires: "2099-01-01T00:00:00.000Z",
    }
    const handler = createAgentTokenPostHandler(
      dependencies({
        authenticate: async () => session,
        isAllowed: (email) => email === "member@example.com",
      })
    )

    const response = await handler(request())
    const payload = jwtPayload((await responseBody(response)).token as string)

    expect(response.status).toBe(200)
    expect(payload.sub).toBe("42")
  })

  test("never downgrades a disallowed signed-in session to anonymous", async () => {
    let fetched = false
    const session: Session = {
      user: {
        id: "outsider-id",
        email: "outsider@example.com",
        name: null,
        image: null,
      },
      expires: "2099-01-01T00:00:00.000Z",
    }
    const handler = createAgentTokenPostHandler(
      dependencies({
        authenticate: async () => session,
        fetchImpl: async () => {
          fetched = true
          return successResponse()
        },
      })
    )

    const response = await handler(anonymousRequest())

    expect(response.status).toBe(403)
    expect(await responseBody(response)).toEqual({ error: "Forbidden" })
    expect(response.headers.get("cache-control")).toBe("no-store")
    expect(fetched).toBe(false)
  })

  test("preserves Unauthorized when an allowed session has no subject", async () => {
    const session: Session = {
      user: {
        id: "",
        email: "owner@example.com",
        name: null,
        image: null,
      },
      expires: "2099-01-01T00:00:00.000Z",
    }
    const handler = createAgentTokenPostHandler(
      dependencies({
        authenticate: async () => session,
        isAllowed: () => true,
      })
    )

    const response = await handler(request())

    expect(response.status).toBe(401)
    expect(await responseBody(response)).toEqual({ error: "Unauthorized" })
    expect(response.headers.get("cache-control")).toBe("no-store")
  })

  test("keeps an unmarked owner request fail-closed when session lookup is unavailable", async () => {
    const handler = createAgentTokenPostHandler(
      dependencies({
        authenticate: async () => {
          throw new Error("database connection details")
        },
      })
    )

    const response = await handler(request())

    expect(response.status).toBe(503)
    expect(await responseBody(response)).toEqual({
      error: "Authentication is unavailable",
    })
    expect(response.headers.get("cache-control")).toBe("no-store")
  })

  test.each(["", "Anonymous", "anonymous-v2", "owner"])(
    "keeps an unrecognized token intent fail-closed when session lookup is unavailable: %s",
    async (intent) => {
      const handler = createAgentTokenPostHandler(
        dependencies({
          authenticate: async () => {
            throw new Error("database connection details")
          },
        })
      )

      const response = await handler(request({ intent }))

      expect(response.status).toBe(503)
      expect(await responseBody(response)).toEqual({
        error: "Authentication is unavailable",
      })
    }
  )

  test("preserves the configured-authentication failure response", async () => {
    const session: Session = {
      user: {
        id: "owner-id",
        email: "owner@example.com",
        name: null,
        image: null,
      },
      expires: "2099-01-01T00:00:00.000Z",
    }
    const handler = createAgentTokenPostHandler(
      dependencies({
        authenticate: async () => session,
        createToken: () => {
          throw new Error("secret details")
        },
      })
    )

    const response = await handler(request())

    expect(response.status).toBe(503)
    expect(await responseBody(response)).toEqual({
      error: "Agent authentication is not configured",
    })
    expect(response.headers.get("cache-control")).toBe("no-store")
  })
})

describe("POST /api/agent-token disabled and preflight behavior", () => {
  test("keeps an explicitly marked anonymous request closed while the flag is disabled", async () => {
    let authenticateCalls = 0
    let siteverifyCalls = 0
    const handler = createAgentTokenPostHandler(
      dependencies({
        authenticate: async () => {
          authenticateCalls += 1
          throw new Error("owner auth must not select the public branch")
        },
        env: {
          ...VALID_ENV,
          AGENT_ANONYMOUS_TOKEN_ENABLED: "false",
        },
        fetchImpl: async () => {
          siteverifyCalls += 1
          return successResponse()
        },
      })
    )

    const response = await handler(explicitAnonymousRequest())

    expect(response.status).toBe(403)
    expect(await responseBody(response)).toEqual({ error: "Forbidden" })
    expect(authenticateCalls).toBe(0)
    expect(siteverifyCalls).toBe(0)
  })

  test.each([
    [undefined, "missing"],
    ["false", "false"],
    ["TRUE", "case confusion"],
    ["1", "numeric string"],
    [true, "boolean confusion"],
    [1, "number confusion"],
  ])("keeps anonymous access closed when the flag is %# (%s)", async (flag) => {
    let fetched = false
    const handler = createAgentTokenPostHandler(
      dependencies({
        env: { ...VALID_ENV, AGENT_ANONYMOUS_TOKEN_ENABLED: flag },
        fetchImpl: async () => {
          fetched = true
          return successResponse()
        },
      })
    )

    const response = await handler(
      request({
        body: "{malformed",
        contentType: "application/json",
      })
    )

    expect(response.status).toBe(403)
    expect(await responseBody(response)).toEqual({ error: "Forbidden" })
    expect(response.headers.get("cache-control")).toBe("no-store")
    expect(fetched).toBe(false)
  })

  test("does not let a valid anonymous cookie bypass the disabled flag", async () => {
    const existing = createAnonymousSessionCookie(
      `anon:${SECOND_UUID}`,
      SESSION_SECRET,
      NOW - 60
    )
    let minted = false
    const handler = createAgentTokenPostHandler(
      dependencies({
        env: {
          ...VALID_ENV,
          AGENT_ANONYMOUS_TOKEN_ENABLED: "false",
        },
        createToken: (...args) => {
          minted = true
          return createAgentToken(...args)
        },
      })
    )

    const response = await handler(
      request({ cookie: `${ANONYMOUS_COOKIE_NAME}=${existing.value}` })
    )

    expect(response.status).toBe(403)
    expect(await responseBody(response)).toEqual({ error: "Forbidden" })
    expect(minted).toBe(false)
  })

  test.each([
    [
      "missing Turnstile secret",
      { ...VALID_ENV, TURNSTILE_SECRET_KEY: undefined },
    ],
    [
      "missing cookie secret",
      { ...VALID_ENV, ANONYMOUS_SESSION_SECRET: undefined },
    ],
    [
      "reused JWT secret",
      { ...VALID_ENV, ANONYMOUS_SESSION_SECRET: AGENT_SECRET },
    ],
    ["missing JWT secret", { ...VALID_ENV, AGENT_AUTH_SECRET: undefined }],
  ])("fails preflight without network access for %s", async (_name, env) => {
    let fetched = false
    const handler = createAgentTokenPostHandler(
      dependencies({
        env,
        fetchImpl: async () => {
          fetched = true
          return successResponse()
        },
      })
    )

    const response = await handler(anonymousRequest())

    expect(response.status).toBe(503)
    expect(await responseBody(response)).toEqual({
      error: "Anonymous authentication is unavailable",
    })
    expect(response.headers.get("cache-control")).toBe("no-store")
    expect(fetched).toBe(false)
  })
})

describe("POST /api/agent-token anonymous bootstrap", () => {
  test("mints after a valid challenge without consulting unavailable owner auth", async () => {
    let authenticateCalls = 0
    const handler = createAgentTokenPostHandler(
      dependencies({
        authenticate: async () => {
          authenticateCalls += 1
          throw new Error("database connection details")
        },
      })
    )

    const response = await handler(explicitAnonymousRequest())
    const body = await responseBody(response)
    const payload = jwtPayload(body.token as string)

    expect(response.status).toBe(200)
    expect(payload).toMatchObject({
      sub: `anon:${UUID}`,
      scope: "anon",
    })
    expect(authenticateCalls).toBe(0)
  })

  test("remints a valid cookie without consulting unavailable owner auth", async () => {
    const existingSubject = `anon:${SECOND_UUID}`
    const existing = createAnonymousSessionCookie(
      existingSubject,
      SESSION_SECRET,
      NOW - 60
    )
    let authenticateCalls = 0
    let siteverifyCalls = 0
    const handler = createAgentTokenPostHandler(
      dependencies({
        authenticate: async () => {
          authenticateCalls += 1
          throw new Error("database connection details")
        },
        fetchImpl: async () => {
          siteverifyCalls += 1
          return successResponse()
        },
      })
    )

    const response = await handler(
      request({
        cookie: `${ANONYMOUS_COOKIE_NAME}=${existing.value}`,
        intent: "anonymous",
      })
    )
    const payload = jwtPayload((await responseBody(response)).token as string)

    expect(response.status).toBe(200)
    expect(payload).toMatchObject({ sub: existingSubject, scope: "anon" })
    expect(authenticateCalls).toBe(0)
    expect(siteverifyCalls).toBe(0)
  })

  test("requests a challenge without treating an empty cookie resume as an error", async () => {
    let fetched = false
    const handler = createAgentTokenPostHandler(
      dependencies({
        fetchImpl: async () => {
          fetched = true
          return successResponse()
        },
      })
    )

    const response = await handler(request())

    expect(response.status).toBe(200)
    expect(await responseBody(response)).toEqual({
      challengeRequired: true,
    })
    expect(response.headers.get("cache-control")).toBe("no-store")
    expect(fetched).toBe(false)
    expect(setCookie(response)).toBeNull()
  })

  test("mints a five-minute anon JWT and a fourteen-day protected cookie", async () => {
    let calledUrl: string | URL | Request | undefined
    let calledInit: RequestInit | undefined
    const handler = createAgentTokenPostHandler(
      dependencies({
        fetchImpl: async (input, init) => {
          calledUrl = input
          calledInit = init
          return successResponse()
        },
      })
    )

    const response = await handler(anonymousRequest())
    const body = await responseBody(response)
    const payload = jwtPayload(body.token as string)
    const cookie = setCookie(response)

    expect(response.status).toBe(200)
    expect(response.headers.get("cache-control")).toBe("no-store")
    expect(payload).toEqual({
      sub: `anon:${UUID}`,
      iss: "syshin0116.dev",
      aud: "agent-api",
      iat: NOW,
      exp: NOW + 300,
      scope: "anon",
    })
    expect(body.expiresAt).toBe(NOW + 300)
    expect(calledUrl).toBe(
      "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    )
    const form = new URLSearchParams(calledInit?.body as string)
    expect(form.get("secret")).toBe(TURNSTILE_SECRET)
    expect(form.get("response")).toBe("client-turnstile-token")
    expect(cookie).toContain(`${ANONYMOUS_COOKIE_NAME}=`)
    expect(cookie).toContain("HttpOnly")
    expect(cookie).toContain("SameSite=lax")
    expect(cookie).toContain("Secure")
    expect(cookie).toContain("Path=/")
    expect(cookie).toContain(`Max-Age=${ANONYMOUS_SESSION_TTL_SECONDS}`)
    expect(cookie).not.toContain(TURNSTILE_SECRET)
    expect(cookie).not.toContain(SESSION_SECRET)
    expect(cookie).not.toContain("client-turnstile-token")
  })

  test("omits Secure only outside production", async () => {
    const handler = createAgentTokenPostHandler(
      dependencies({ nodeEnv: "development" })
    )

    const response = await handler(anonymousRequest())

    expect(setCookie(response)).not.toContain("Secure")
  })

  test("remints a valid signed identity without replaying a challenge", async () => {
    const existingSubject = `anon:${SECOND_UUID}`
    const existing = createAnonymousSessionCookie(
      existingSubject,
      SESSION_SECRET,
      NOW - 60
    )
    let fetchCount = 0
    const handler = createAgentTokenPostHandler(
      dependencies({
        fetchImpl: async () => {
          fetchCount += 1
          return successResponse()
        },
      })
    )

    const response = await handler(
      request({ cookie: `${ANONYMOUS_COOKIE_NAME}=${existing.value}` })
    )
    const payload = jwtPayload((await responseBody(response)).token as string)

    expect(response.status).toBe(200)
    expect(payload.sub).toBe(existingSubject)
    expect(fetchCount).toBe(0)
    expect(setCookie(response)).toBeNull()
  })

  test.each([
    ["forged", "forged.cookie"],
    [
      "expired",
      createAnonymousSessionCookie(
        `anon:${SECOND_UUID}`,
        SESSION_SECRET,
        NOW - ANONYMOUS_SESSION_TTL_SECONDS
      ).value,
    ],
    [
      "signed with another key",
      createAnonymousSessionCookie(
        `anon:${SECOND_UUID}`,
        "other-test-anonymous-session-secret-more-than-32",
        NOW - 60
      ).value,
    ],
  ])("rotates a %s cookie after successful verification", async (_name, value) => {
    const handler = createAgentTokenPostHandler(dependencies())

    const response = await handler(
      anonymousRequest(`${ANONYMOUS_COOKIE_NAME}=${value}`)
    )
    const payload = jwtPayload((await responseBody(response)).token as string)

    expect(response.status).toBe(200)
    expect(payload.sub).toBe(`anon:${UUID}`)
    expect(setCookie(response)).toContain(`${ANONYMOUS_COOKIE_NAME}=`)
  })

  test("rotates ambiguous duplicate cookies", async () => {
    const existing = createAnonymousSessionCookie(
      `anon:${SECOND_UUID}`,
      SESSION_SECRET,
      NOW - 60
    )
    const handler = createAgentTokenPostHandler(dependencies())

    const response = await handler(
      anonymousRequest(
        `${ANONYMOUS_COOKIE_NAME}=${existing.value}; ${ANONYMOUS_COOKIE_NAME}=${existing.value}`
      )
    )
    const payload = jwtPayload((await responseBody(response)).token as string)

    expect(payload.sub).toBe(`anon:${UUID}`)
    expect(setCookie(response)).toContain(`${ANONYMOUS_COOKIE_NAME}=`)
  })

  test.each([
    ["invalid request", request({ body: "{}", contentType: "application/json" })],
    [
      "type-confused token",
      request({
        body: '{"turnstileToken":true}',
        contentType: "application/json",
      }),
    ],
    [
      "oversized request",
      request({
        body: JSON.stringify({
          turnstileToken: "token",
          padding: "x".repeat(5_000),
        }),
        contentType: "application/json",
      }),
    ],
  ])("rejects %s before Siteverify", async (_name, invalidRequest) => {
    let fetched = false
    const handler = createAgentTokenPostHandler(
      dependencies({
        fetchImpl: async () => {
          fetched = true
          return successResponse()
        },
      })
    )

    const response = await handler(invalidRequest)

    expect(response.status).toBe(400)
    expect(await responseBody(response)).toEqual({ error: "Invalid request" })
    expect(response.headers.get("cache-control")).toBe("no-store")
    expect(fetched).toBe(false)
    expect(setCookie(response)).toBeNull()
  })

  test.each([
    ["success false", { success: false, "error-codes": ["bad-request"] }],
    [
      "hostname mismatch",
      {
        success: true,
        challenge_ts: CHALLENGE_TS,
        hostname: "evil.example",
        action: ACTION,
      },
    ],
    [
      "action mismatch",
      {
        success: true,
        challenge_ts: CHALLENGE_TS,
        hostname: HOSTNAME,
        action: "other-action",
      },
    ],
  ])("fails closed without a cookie for Turnstile %s", async (_name, result) => {
    let minted = false
    const handler = createAgentTokenPostHandler(
      dependencies({
        fetchImpl: async () =>
          new Response(JSON.stringify(result), {
            headers: { "content-type": "application/json" },
          }),
        createToken: (...args) => {
          minted = true
          return createAgentToken(...args)
        },
      })
    )

    const response = await handler(anonymousRequest())

    expect(response.status).toBe(403)
    expect(await responseBody(response)).toEqual({
      error: "Verification failed",
    })
    expect(response.headers.get("cache-control")).toBe("no-store")
    expect(setCookie(response)).toBeNull()
    expect(minted).toBe(false)
  })

  test.each([
    [
      "type-confused response",
      async () =>
        new Response(
          JSON.stringify({
            success: "true",
            challenge_ts: CHALLENGE_TS,
            hostname: HOSTNAME,
            action: ACTION,
          }),
          { headers: { "content-type": "application/json" } }
        ),
    ],
    [
      "network error",
      async () => {
        throw new Error("private upstream error")
      },
    ],
  ])("fails unavailable and hides Siteverify %s details", async (_name, fetchImpl) => {
    const handler = createAgentTokenPostHandler(
      dependencies({
        fetchImpl,
      })
    )

    const response = await handler(anonymousRequest())
    const body = await responseBody(response)

    expect(response.status).toBe(503)
    expect(body).toEqual({
      error: "Anonymous authentication is unavailable",
    })
    expect(JSON.stringify(body)).not.toContain(
      "private upstream error"
    )
    expect(setCookie(response)).toBeNull()
  })

  test("returns a generic 503 and no cookie when minting fails", async () => {
    const handler = createAgentTokenPostHandler(
      dependencies({
        createToken: () => {
          throw new Error("private signing error")
        },
      })
    )

    const response = await handler(anonymousRequest())

    expect(response.status).toBe(503)
    expect(await responseBody(response)).toEqual({
      error: "Anonymous authentication is unavailable",
    })
    expect(setCookie(response)).toBeNull()
  })

  test("returns a generic 503 when the random source violates UUIDv4", async () => {
    const handler = createAgentTokenPostHandler(
      dependencies({ randomUUID: () => "attacker-chosen-subject" })
    )

    const response = await handler(anonymousRequest())

    expect(response.status).toBe(503)
    expect(await responseBody(response)).toEqual({
      error: "Anonymous authentication is unavailable",
    })
    expect(setCookie(response)).toBeNull()
  })
})
