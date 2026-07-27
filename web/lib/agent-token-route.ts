import { NextRequest, NextResponse } from "next/server"
import type { createAgentToken } from "@/lib/agent-auth"
import {
  ANONYMOUS_COOKIE_NAME,
  ANONYMOUS_SESSION_TTL_SECONDS,
  ANONYMOUS_TOKEN_TTL_SECONDS,
  type FetchLike,
  InvalidAnonymousTokenRequest,
  createAnonymousSessionCookie,
  createAnonymousSubject,
  readAnonymousAgentTokenFeature,
  readAnonymousSessionCookie,
  readTurnstileRequest,
  verifyTurnstileToken,
} from "@/lib/anonymous-agent-token"

interface AgentTokenSession {
  user?: {
    id?: string | null
    email?: string | null
    name?: string | null
    image?: string | null
  } | null
  expires?: string
}

export interface AgentTokenPostDependencies {
  authenticate: () => Promise<AgentTokenSession | null>
  createToken: typeof createAgentToken
  isAllowed: (email: string | null | undefined) => boolean
  isAdmin: (email: string | null | undefined) => boolean
  env: Readonly<Record<string, unknown>>
  fetchImpl: FetchLike
  nowSeconds: () => number
  randomUUID: () => string
  nodeEnv: string | undefined
  turnstileTimeoutMs: number
}

function jsonResponse(
  body: Record<string, unknown>,
  status = 200
): NextResponse {
  return NextResponse.json(body, {
    status,
    headers: { "Cache-Control": "no-store" },
  })
}

function mintSignedInToken(
  session: AgentTokenSession,
  dependencies: AgentTokenPostDependencies
): NextResponse {
  const subject = session.user?.id ?? session.user?.email
  if (!subject) {
    return jsonResponse({ error: "Unauthorized" }, 401)
  }

  try {
    const scopes = dependencies.isAdmin(session.user?.email)
      ? ["admin"]
      : []
    const result = dependencies.createToken(
      subject,
      undefined,
      undefined,
      undefined,
      scopes
    )
    return jsonResponse(result)
  } catch {
    return jsonResponse(
      { error: "Agent authentication is not configured" },
      503
    )
  }
}

function mintAnonymousToken(options: {
  subject: string
  agentAuthSecret: string
  nowSeconds: number
  dependencies: AgentTokenPostDependencies
}): NextResponse | null {
  try {
    const result = options.dependencies.createToken(
      options.subject,
      options.agentAuthSecret,
      options.nowSeconds,
      ANONYMOUS_TOKEN_TTL_SECONDS,
      ["anon"]
    )
    return jsonResponse(result)
  } catch {
    return null
  }
}

function requestCookieValues(
  request: NextRequest,
  name: string
): string[] {
  const header = request.headers.get("cookie")
  if (header === null) return []
  const prefix = `${name}=`
  return header
    .split(";")
    .map((part) => part.trim())
    .filter((part) => part.startsWith(prefix))
    .map((part) => part.slice(prefix.length))
}

export function createAgentTokenPostHandler(
  dependencies: AgentTokenPostDependencies
): (request: NextRequest) => Promise<NextResponse> {
  return async (request: NextRequest): Promise<NextResponse> => {
    const session = await dependencies.authenticate()
    if (dependencies.isAllowed(session?.user?.email)) {
      return mintSignedInToken(session as AgentTokenSession, dependencies)
    }
    if (session !== null) {
      return jsonResponse({ error: "Forbidden" }, 403)
    }

    const feature = readAnonymousAgentTokenFeature(dependencies.env)
    if (feature.state === "disabled") {
      return jsonResponse({ error: "Forbidden" }, 403)
    }
    if (feature.state === "misconfigured") {
      return jsonResponse(
        { error: "Anonymous authentication is unavailable" },
        503
      )
    }

    const nowSeconds = dependencies.nowSeconds()
    const cookies = requestCookieValues(request, ANONYMOUS_COOKIE_NAME)
    const existingSubject =
      cookies.length === 1
        ? readAnonymousSessionCookie(
            cookies[0],
            feature.config.anonymousSessionSecret,
            nowSeconds
          )
        : null

    if (existingSubject !== null) {
      const response = mintAnonymousToken({
        subject: existingSubject,
        agentAuthSecret: feature.config.agentAuthSecret,
        nowSeconds,
        dependencies,
      })
      return (
        response ??
        jsonResponse(
          { error: "Anonymous authentication is unavailable" },
          503
        )
      )
    }

    let turnstileToken: string
    try {
      ;({ turnstileToken } = await readTurnstileRequest(request))
    } catch (error) {
      if (error instanceof InvalidAnonymousTokenRequest) {
        return jsonResponse({ error: "Invalid request" }, 400)
      }
      return jsonResponse(
        { error: "Anonymous authentication is unavailable" },
        503
      )
    }

    const verification = await verifyTurnstileToken({
      token: turnstileToken,
      secret: feature.config.turnstileSecret,
      expectedHostname: feature.config.expectedHostname,
      expectedAction: feature.config.expectedAction,
      fetchImpl: dependencies.fetchImpl,
      timeoutMs: dependencies.turnstileTimeoutMs,
      nowSeconds,
    })
    if (verification === "rejected") {
      return jsonResponse({ error: "Verification failed" }, 403)
    }
    if (verification === "unavailable") {
      return jsonResponse(
        { error: "Anonymous authentication is unavailable" },
        503
      )
    }

    try {
      const subject = createAnonymousSubject(dependencies.randomUUID)
      const cookie = createAnonymousSessionCookie(
        subject,
        feature.config.anonymousSessionSecret,
        nowSeconds
      )
      const response = mintAnonymousToken({
        subject,
        agentAuthSecret: feature.config.agentAuthSecret,
        nowSeconds,
        dependencies,
      })
      if (response === null) {
        return jsonResponse(
          { error: "Anonymous authentication is unavailable" },
          503
        )
      }

      response.cookies.set({
        name: ANONYMOUS_COOKIE_NAME,
        value: cookie.value,
        httpOnly: true,
        sameSite: "lax",
        secure: dependencies.nodeEnv === "production",
        path: "/",
        maxAge: ANONYMOUS_SESSION_TTL_SECONDS,
        expires: new Date(cookie.expiresAt * 1_000),
      })
      return response
    } catch {
      return jsonResponse(
        { error: "Anonymous authentication is unavailable" },
        503
      )
    }
  }
}
