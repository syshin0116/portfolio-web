import { NextRequest, NextResponse } from "next/server"
import type { createAgentToken } from "@/lib/agent-auth"
import { canonicalAuthSubject } from "@/lib/auth-subject"
import { hasAnonymousAgentTokenIntent } from "@/lib/agent-token-intent"
import {
  ANONYMOUS_COOKIE_NAME,
  ANONYMOUS_SESSION_TTL_SECONDS,
  ANONYMOUS_TOKEN_TTL_SECONDS,
  createAnonymousSessionCookie,
  createAnonymousSubject,
  readAnonymousAgentTokenFeature,
  readAnonymousSessionCookie,
} from "@/lib/anonymous-agent-token"

interface AgentTokenSession {
  user?: {
    id?: unknown
    email?: string | null
    name?: string | null
    image?: string | null
  } | null
  expires?: string
}

export interface AgentTokenPostDependencies {
  authenticate: () => Promise<AgentTokenSession | null>
  checkBot: () => Promise<unknown>
  createToken: typeof createAgentToken
  isAllowed: (email: string | null | undefined) => boolean
  isAdmin: (email: string | null | undefined) => boolean
  env: Readonly<Record<string, unknown>>
  nowSeconds: () => number
  randomUUID: () => string
  nodeEnv: string | undefined
}

export type AgentTokenRouteMode = "anonymous" | "combined" | "owner"

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
  const subject = canonicalAuthSubject(session.user?.id)
  if (subject === null) {
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

function isBodylessAnonymousRequest(request: NextRequest): boolean {
  const contentLength = request.headers.get("content-length")
  return (
    request.headers.get("content-type") === null &&
    request.headers.get("transfer-encoding") === null &&
    (contentLength === null || contentLength === "0")
  )
}

export function createAgentTokenPostHandler(
  dependencies: AgentTokenPostDependencies,
  mode: AgentTokenRouteMode = "combined"
): (request: NextRequest) => Promise<NextResponse> {
  const handleAnonymousRequest = async (
    request: NextRequest
  ): Promise<NextResponse> => {
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
    if (!isBodylessAnonymousRequest(request)) {
      return jsonResponse({ error: "Invalid request" }, 400)
    }

    let verdict: unknown
    try {
      verdict = await dependencies.checkBot()
    } catch {
      return jsonResponse(
        { error: "Anonymous authentication is unavailable" },
        503
      )
    }
    if (
      verdict === null ||
      typeof verdict !== "object" ||
      !("isBot" in verdict) ||
      typeof verdict.isBot !== "boolean"
    ) {
      return jsonResponse(
        { error: "Anonymous authentication is unavailable" },
        503
      )
    }
    if (verdict.isBot) {
      return jsonResponse({ error: "Forbidden" }, 403)
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

  return async (request: NextRequest): Promise<NextResponse> => {
    const anonymousIntent = hasAnonymousAgentTokenIntent(request)
    if (mode === "anonymous") {
      return anonymousIntent
        ? handleAnonymousRequest(request)
        : jsonResponse({ error: "Forbidden" }, 403)
    }
    if (anonymousIntent) {
      if (mode === "owner") {
        return jsonResponse({ error: "Forbidden" }, 403)
      }
      return handleAnonymousRequest(request)
    }

    let session: AgentTokenSession | null
    try {
      session = await dependencies.authenticate()
    } catch {
      return jsonResponse(
        { error: "Authentication is unavailable" },
        503
      )
    }
    if (dependencies.isAllowed(session?.user?.email)) {
      return mintSignedInToken(session as AgentTokenSession, dependencies)
    }
    if (session !== null) {
      return jsonResponse({ error: "Forbidden" }, 403)
    }

    return jsonResponse({ error: "Unauthorized" }, 401)
  }
}
