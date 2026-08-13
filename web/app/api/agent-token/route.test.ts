import { describe, expect, test } from "bun:test"
import { NextRequest } from "next/server"
import { createAgentToken } from "@/lib/agent-auth"
import {
  ANONYMOUS_COOKIE_NAME,
  ANONYMOUS_SESSION_TTL_SECONDS,
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
const ANONYMOUS_INTENT_HEADER = "X-Agent-Token-Intent"

const VALID_ENV = {
  AGENT_ANONYMOUS_TOKEN_ENABLED: "true",
  AGENT_AUTH_SECRET: AGENT_SECRET,
  ANONYMOUS_SESSION_SECRET: SESSION_SECRET,
}

type Session = Awaited<ReturnType<AgentTokenPostDependencies["authenticate"]>>

function dependencies(
  overrides: Partial<AgentTokenPostDependencies> = {}
): AgentTokenPostDependencies {
  return {
    authenticate: async () => null,
    checkBot: async () => ({ isBot: false }),
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
    nowSeconds: () => NOW,
    randomUUID: () => UUID,
    nodeEnv: "production",
    ...overrides,
  }
}

function request(options: {
  body?: string
  contentLength?: string
  contentType?: string
  cookie?: string
  intent?: string
  transferEncoding?: string
} = {}): NextRequest {
  const headers = new Headers()
  if (options.contentLength) {
    headers.set("content-length", options.contentLength)
  }
  if (options.contentType) headers.set("content-type", options.contentType)
  if (options.transferEncoding) {
    headers.set("transfer-encoding", options.transferEncoding)
  }
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

function explicitAnonymousRequest(cookie?: string): NextRequest {
  return request({ cookie, intent: "anonymous" })
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
  test("keeps anonymous issuance off the owner route", async () => {
    let authenticateCalls = 0
    let botChecks = 0
    const handler = createAgentTokenPostHandler(
      dependencies({
        authenticate: async () => {
          authenticateCalls += 1
          return null
        },
        checkBot: async () => {
          botChecks += 1
          return { isBot: false }
        },
      }),
      "owner"
    )

    const response = await handler(explicitAnonymousRequest())

    expect(response.status).toBe(403)
    expect(authenticateCalls).toBe(0)
    expect(botChecks).toBe(0)
  })

  test("preserves the owner path without reading anonymous config, body, or bot verdict", async () => {
    let botChecks = 0
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
        checkBot: async () => {
          botChecks += 1
          throw new Error("owner traffic must not check BotID")
        },
        env: { AGENT_ANONYMOUS_TOKEN_ENABLED: "true" },
      })
    )

    const response = await handler(
      request({ body: "not-json", contentType: "text/plain" })
    )
    const body = await responseBody(response)
    const payload = jwtPayload(body.token as string)

    expect(response.status).toBe(200)
    expect(response.headers.get("cache-control")).toBe("no-store")
    expect(payload).toMatchObject({
      sub: "owner-id",
      scope: "admin model:select",
    })
    expect((payload.exp as number) - (payload.iat as number)).toBe(900)
    expect(setCookie(response)).toBeNull()
    expect(botChecks).toBe(0)
  })

  test("grants signed-in users model selection without admin access", async () => {
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
    expect(payload).toMatchObject({ scope: "model:select" })
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
    let botChecks = 0
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
        checkBot: async () => {
          botChecks += 1
          return { isBot: false }
        },
      })
    )

    const response = await handler(request())

    expect(response.status).toBe(403)
    expect(await responseBody(response)).toEqual({ error: "Forbidden" })
    expect(botChecks).toBe(0)
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
  })

  test.each(["", "Anonymous", "anonymous-v2", "owner"])(
    "keeps an unrecognized token intent on the owner path: %s",
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

  test("requires explicit anonymous intent when no owner session exists", async () => {
    let botChecks = 0
    const handler = createAgentTokenPostHandler(
      dependencies({
        checkBot: async () => {
          botChecks += 1
          return { isBot: false }
        },
      })
    )

    const response = await handler(request())

    expect(response.status).toBe(401)
    expect(await responseBody(response)).toEqual({ error: "Unauthorized" })
    expect(botChecks).toBe(0)
  })

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
  })
})

describe("POST /api/agent-token anonymous preflight", () => {
  test("keeps owner authentication off the BotID route", async () => {
    let authenticateCalls = 0
    let botChecks = 0
    const handler = createAgentTokenPostHandler(
      dependencies({
        authenticate: async () => {
          authenticateCalls += 1
          return null
        },
        checkBot: async () => {
          botChecks += 1
          return { isBot: false }
        },
      }),
      "anonymous"
    )

    const response = await handler(request())

    expect(response.status).toBe(403)
    expect(authenticateCalls).toBe(0)
    expect(botChecks).toBe(0)
  })

  test("keeps explicit anonymous requests closed while the flag is disabled", async () => {
    let authenticateCalls = 0
    let botChecks = 0
    const handler = createAgentTokenPostHandler(
      dependencies({
        authenticate: async () => {
          authenticateCalls += 1
          throw new Error("owner auth must not select the public branch")
        },
        checkBot: async () => {
          botChecks += 1
          return { isBot: false }
        },
        env: { ...VALID_ENV, AGENT_ANONYMOUS_TOKEN_ENABLED: "false" },
      })
    )

    const response = await handler(explicitAnonymousRequest())

    expect(response.status).toBe(403)
    expect(await responseBody(response)).toEqual({ error: "Forbidden" })
    expect(authenticateCalls).toBe(0)
    expect(botChecks).toBe(0)
  })

  test.each([undefined, "false", "TRUE", "1", true, 1])(
    "keeps anonymous access closed when the flag is %#",
    async (flag) => {
      const handler = createAgentTokenPostHandler(
        dependencies({
          env: { ...VALID_ENV, AGENT_ANONYMOUS_TOKEN_ENABLED: flag },
        })
      )

      const response = await handler(explicitAnonymousRequest())

      expect(response.status).toBe(403)
      expect(await responseBody(response)).toEqual({ error: "Forbidden" })
    }
  )

  test("does not let a valid anonymous cookie bypass the disabled flag", async () => {
    const existing = createAnonymousSessionCookie(
      `anon:${SECOND_UUID}`,
      SESSION_SECRET,
      NOW - 60
    )
    let minted = false
    const handler = createAgentTokenPostHandler(
      dependencies({
        env: { ...VALID_ENV, AGENT_ANONYMOUS_TOKEN_ENABLED: "false" },
        createToken: (...args) => {
          minted = true
          return createAgentToken(...args)
        },
      })
    )

    const response = await handler(
      explicitAnonymousRequest(`${ANONYMOUS_COOKIE_NAME}=${existing.value}`)
    )

    expect(response.status).toBe(403)
    expect(minted).toBe(false)
  })

  test.each([
    ["missing cookie secret", { ...VALID_ENV, ANONYMOUS_SESSION_SECRET: undefined }],
    ["reused JWT secret", { ...VALID_ENV, ANONYMOUS_SESSION_SECRET: AGENT_SECRET }],
    ["missing JWT secret", { ...VALID_ENV, AGENT_AUTH_SECRET: undefined }],
  ])("fails preflight before bot inspection for %s", async (_name, env) => {
    let botChecks = 0
    const handler = createAgentTokenPostHandler(
      dependencies({
        env,
        checkBot: async () => {
          botChecks += 1
          return { isBot: false }
        },
      })
    )

    const response = await handler(explicitAnonymousRequest())

    expect(response.status).toBe(503)
    expect(await responseBody(response)).toEqual({
      error: "Anonymous authentication is unavailable",
    })
    expect(botChecks).toBe(0)
  })

  test.each([
    [
      "declared body",
      request({ contentLength: "1", intent: "anonymous" }),
    ],
    [
      "body media type",
      request({ contentType: "application/json", intent: "anonymous" }),
    ],
    [
      "streamed body",
      request({ transferEncoding: "chunked", intent: "anonymous" }),
    ],
  ])("rejects an anonymous request with a %s", async (_name, invalidRequest) => {
    let botChecks = 0
    const handler = createAgentTokenPostHandler(
      dependencies({
        checkBot: async () => {
          botChecks += 1
          return { isBot: false }
        },
      })
    )

    const response = await handler(invalidRequest)

    expect(response.status).toBe(400)
    expect(await responseBody(response)).toEqual({ error: "Invalid request" })
    expect(botChecks).toBe(0)
  })

  test("rejects a bot verdict without minting", async () => {
    let minted = false
    const handler = createAgentTokenPostHandler(
      dependencies({
        checkBot: async () => ({ isBot: true }),
        createToken: (...args) => {
          minted = true
          return createAgentToken(...args)
        },
      })
    )

    const response = await handler(explicitAnonymousRequest())

    expect(response.status).toBe(403)
    expect(await responseBody(response)).toEqual({ error: "Forbidden" })
    expect(minted).toBe(false)
    expect(setCookie(response)).toBeNull()
  })

  test.each([
    ["throw", async () => { throw new Error("private bot error") }],
    ["null", async () => null],
    ["missing isBot", async () => ({})],
    ["non-boolean isBot", async () => ({ isBot: "false" })],
  ])("fails closed when the bot verdict is %s", async (_name, checkBot) => {
    const handler = createAgentTokenPostHandler(dependencies({ checkBot }))

    const response = await handler(explicitAnonymousRequest())
    const body = await responseBody(response)

    expect(response.status).toBe(503)
    expect(body).toEqual({
      error: "Anonymous authentication is unavailable",
    })
    expect(JSON.stringify(body)).not.toContain("private bot error")
    expect(setCookie(response)).toBeNull()
  })
})

describe("POST /api/agent-token anonymous issuance", () => {
  test("mints from a bodyless Basic pass without consulting unavailable owner auth", async () => {
    let authenticateCalls = 0
    let botChecks = 0
    const handler = createAgentTokenPostHandler(
      dependencies({
        authenticate: async () => {
          authenticateCalls += 1
          throw new Error("database connection details")
        },
        checkBot: async () => {
          botChecks += 1
          return { isBot: false, extra: "allowed" }
        },
      })
    )

    const response = await handler(explicitAnonymousRequest())
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
    expect(cookie).toContain(`${ANONYMOUS_COOKIE_NAME}=`)
    expect(cookie).toContain("HttpOnly")
    expect(cookie).toContain("SameSite=lax")
    expect(cookie).toContain("Secure")
    expect(cookie).toContain("Path=/")
    expect(cookie).toContain(`Max-Age=${ANONYMOUS_SESSION_TTL_SECONDS}`)
    expect(cookie).not.toContain(AGENT_SECRET)
    expect(cookie).not.toContain(SESSION_SECRET)
    expect(authenticateCalls).toBe(0)
    expect(botChecks).toBe(1)
  })

  test("checks a valid cookie before reminting the same identity", async () => {
    const existingSubject = `anon:${SECOND_UUID}`
    const existing = createAnonymousSessionCookie(
      existingSubject,
      SESSION_SECRET,
      NOW - 60
    )
    let botChecks = 0
    const handler = createAgentTokenPostHandler(
      dependencies({
        checkBot: async () => {
          botChecks += 1
          return { isBot: false }
        },
        randomUUID: () => {
          throw new Error("valid cookie must not rotate")
        },
      })
    )

    const response = await handler(
      explicitAnonymousRequest(`${ANONYMOUS_COOKIE_NAME}=${existing.value}`)
    )
    const payload = jwtPayload((await responseBody(response)).token as string)

    expect(response.status).toBe(200)
    expect(payload).toMatchObject({ sub: existingSubject, scope: "anon" })
    expect(setCookie(response)).toBeNull()
    expect(botChecks).toBe(1)
  })

  test("blocks a valid cookie when the current request is a bot", async () => {
    const existing = createAnonymousSessionCookie(
      `anon:${SECOND_UUID}`,
      SESSION_SECRET,
      NOW - 60
    )
    let minted = false
    const handler = createAgentTokenPostHandler(
      dependencies({
        checkBot: async () => ({ isBot: true }),
        createToken: (...args) => {
          minted = true
          return createAgentToken(...args)
        },
      })
    )

    const response = await handler(
      explicitAnonymousRequest(`${ANONYMOUS_COOKIE_NAME}=${existing.value}`)
    )

    expect(response.status).toBe(403)
    expect(minted).toBe(false)
  })

  test("omits Secure only outside production", async () => {
    const handler = createAgentTokenPostHandler(
      dependencies({ nodeEnv: "development" })
    )

    const response = await handler(explicitAnonymousRequest())

    expect(setCookie(response)).not.toContain("Secure")
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
  ])("rotates the %s cookie after a Basic pass", async (_name, value) => {
    const handler = createAgentTokenPostHandler(dependencies())

    const response = await handler(
      explicitAnonymousRequest(`${ANONYMOUS_COOKIE_NAME}=${value}`)
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
      explicitAnonymousRequest(
        `${ANONYMOUS_COOKIE_NAME}=${existing.value}; ${ANONYMOUS_COOKIE_NAME}=${existing.value}`
      )
    )
    const payload = jwtPayload((await responseBody(response)).token as string)

    expect(payload.sub).toBe(`anon:${UUID}`)
    expect(setCookie(response)).toContain(`${ANONYMOUS_COOKIE_NAME}=`)
  })

  test("returns a generic 503 and no cookie when minting fails", async () => {
    const handler = createAgentTokenPostHandler(
      dependencies({
        createToken: () => {
          throw new Error("private signing error")
        },
      })
    )

    const response = await handler(explicitAnonymousRequest())

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

    const response = await handler(explicitAnonymousRequest())

    expect(response.status).toBe(503)
    expect(await responseBody(response)).toEqual({
      error: "Anonymous authentication is unavailable",
    })
    expect(setCookie(response)).toBeNull()
  })
})
