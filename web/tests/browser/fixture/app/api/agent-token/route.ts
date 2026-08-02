import { randomUUID } from "node:crypto"
import {
  AGENT_TOKEN_INTENT_HEADER,
  ANONYMOUS_AGENT_TOKEN_INTENT,
} from "@/lib/agent-token-intent"

import {
  FIXTURE_OWNER_IDENTITY,
  FIXTURE_TOKEN_EXPIRES_AT,
  fixtureAnonymousToken,
  fixtureOwnerToken,
} from "../../../anonymous-credential"

const COOKIE_NAME = "fixture-anonymous-subject"
const OWNER_COOKIE_NAME = "fixture-owner-session"
const SUBJECT_PATTERN =
  /^anon:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

function cookieSubject(request: Request): string | undefined {
  const header = request.headers.get("cookie")
  if (header === null) return undefined
  const prefix = `${COOKIE_NAME}=`
  const values = header
    .split(";")
    .map((part) => part.trim())
    .filter((part) => part.startsWith(prefix))
    .map((part) => decodeURIComponent(part.slice(prefix.length)))
  return values.length === 1 && SUBJECT_PATTERN.test(values[0]!)
    ? values[0]
    : undefined
}

function hasOwnerSession(request: Request): boolean {
  const header = request.headers.get("cookie")
  if (header === null) return false
  return header
    .split(";")
    .map((part) => part.trim())
    .some((part) => part === `${OWNER_COOKIE_NAME}=1`)
}

function json(
  body: Record<string, unknown>,
  status = 200,
  subject?: string
): Response {
  const headers = new Headers({
    "Cache-Control": "no-store",
    "Content-Type": "application/json",
  })
  if (subject !== undefined) {
    headers.set(
      "Set-Cookie",
      `${COOKIE_NAME}=${encodeURIComponent(subject)}; HttpOnly; SameSite=Lax; Path=/`
    )
  }
  return new Response(JSON.stringify(body), { status, headers })
}

export async function POST(request: Request) {
  if (hasOwnerSession(request)) {
    if (request.headers.has(AGENT_TOKEN_INTENT_HEADER)) {
      return json({ error: "Invalid owner token intent" }, 400)
    }
    return json({
      token: fixtureOwnerToken(),
      expiresAt: FIXTURE_TOKEN_EXPIRES_AT,
      identity: FIXTURE_OWNER_IDENTITY,
    })
  }

  if (
    request.headers.get(AGENT_TOKEN_INTENT_HEADER) !==
    ANONYMOUS_AGENT_TOKEN_INTENT
  ) {
    return json({ error: "Invalid anonymous token intent" }, 400)
  }

  let subject = cookieSubject(request)
  let createdSubject = false
  if (subject === undefined) {
    let body: unknown
    try {
      body = await request.json()
    } catch {
      return json({ challengeRequired: true })
    }
    if (
      body === null ||
      typeof body !== "object" ||
      Array.isArray(body) ||
      Object.keys(body).length !== 1 ||
      !("turnstileToken" in body) ||
      body.turnstileToken !== "fixture-turnstile-token"
    ) {
      return json({ error: "Verification failed" }, 403)
    }
    subject = `anon:${randomUUID()}`
    createdSubject = true
  }
  const expiresAt =
    Math.floor(Date.now() / 1_000) + (createdSubject ? 30 : 300)
  return json(
    {
      token: fixtureAnonymousToken(subject, expiresAt),
      expiresAt,
    },
    200,
    subject
  )
}
