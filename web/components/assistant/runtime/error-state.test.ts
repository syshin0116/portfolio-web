import { describe, expect, test } from "bun:test"

import {
  AgentLifecycleError,
  classifyAgentError,
  humanizeAgentError,
  reduceAgentError,
  sanitizeAgentError,
  type AgentErrorRoutingState,
} from "./error-state"
import { AgentAuthenticationError } from "./token-broker"

describe("classifyAgentError", () => {
  test.each([
    [
      new AgentAuthenticationError("raw auth detail", 401),
      "connection",
      "authentication",
      "다시 로그인",
    ],
    [
      Object.assign(new Error("conflict"), { status: 409 }),
      "turn",
      "conflict",
      "같은 대화에서 다시 시도",
    ],
    [
      { response: { status: 429 }, secret: "do-not-render" },
      "turn",
      "rate-limit",
      "같은 대화에서 다시 시도",
    ],
    [
      new Error("Protocol request failed: 503 — db password"),
      "turn",
      "server",
      "같은 대화에서 다시 시도",
    ],
    [
      new AgentLifecycleError(),
      "turn",
      "lifecycle",
      "같은 대화에서 다시 시도",
    ],
  ] as const)(
    "maps failures to a safe Korean channel and action",
    (error, channel, kind, actionLabel) => {
      const presentation = classifyAgentError(error)
      expect(presentation).toMatchObject({ channel, kind, actionLabel })
      expect(JSON.stringify(presentation)).not.toContain("db password")
      expect(JSON.stringify(presentation)).not.toContain("do-not-render")
    }
  )

  test("separates connection-time and turn-time network failures", () => {
    expect(
      classifyAgentError(new TypeError("Failed to fetch"), "connection")
    ).toMatchObject({
      channel: "connection",
      kind: "network",
      action: "retry-connection",
      actionLabel: "다시 연결",
    })
    expect(
      classifyAgentError(new TypeError("Failed to fetch"), "turn")
    ).toMatchObject({
      channel: "turn",
      kind: "network",
      action: "retry-turn",
      actionLabel: "같은 대화에서 다시 시도",
    })
  })

  test("routes connection-time server responses to reconnect, not turn retry", () => {
    expect(
      classifyAgentError(
        Object.assign(new Error("upstream secret"), { status: 503 }),
        "connection"
      )
    ).toEqual({
      channel: "connection",
      kind: "server",
      message:
        "에이전트 서버가 일시적으로 응답하지 않습니다. 잠시 후 다시 연결해 주세요.",
      action: "retry-connection",
      actionLabel: "다시 연결",
    })
  })

  test("keeps a ready connection usable when a recoverable turn fails", () => {
    const ready: AgentErrorRoutingState = {
      connectionStatus: "ready",
    }
    const next = reduceAgentError(
      ready,
      Object.assign(new Error("busy"), { status: 409 }),
      "turn"
    )
    expect(next.connectionStatus).toBe("ready")
    expect(next.connectionError).toBeUndefined()
    expect(next.turnError).toMatchObject({
      kind: "conflict",
      channel: "turn",
    })
  })

  test("moves fatal authentication failures to the connection channel", () => {
    const next = reduceAgentError(
      { connectionStatus: "ready" },
      new AgentAuthenticationError("secret", 401),
      "turn"
    )
    expect(next).toMatchObject({
      connectionStatus: "error",
      connectionError: {
        kind: "authentication",
        channel: "connection",
      },
    })
  })

  test("retains the compatibility humanizer without exposing internals", () => {
    expect(humanizeAgentError(new Error("postgres://secret"))).toBe(
      "에이전트 실행을 완료하지 못했습니다. 같은 대화에서 다시 시도해 주세요."
    )
  })

  test("sanitizes raw SDK, auth, URL, and backend response details before rethrow", () => {
    const raw = Object.assign(
      new Error(
        "503 postgres://owner:secret@db.internal Authorization: Bearer token"
      ),
      { status: 503, response: { body: "private backend body" } }
    )
    const safe = sanitizeAgentError(raw)

    expect(safe.status).toBe(503)
    expect(safe.message).toBe(
      "에이전트 서버가 일시적으로 응답하지 않습니다. 잠시 후 다시 시도해 주세요."
    )
    expect(JSON.stringify(safe)).not.toContain("secret")
    expect(JSON.stringify(safe)).not.toContain("Bearer")
    expect(JSON.stringify(safe)).not.toContain("private backend body")
  })

  test("drops stacks and rejects unallowlisted status fields at the UI boundary", () => {
    const sentinel = "ultra-secret-sentinel"
    const raw = Object.assign(new Error(sentinel), {
      status: 418,
      response: { status: 418, body: sentinel },
      stack: `Error: ${sentinel}\n at postgres://${sentinel}`,
    })
    const safe = sanitizeAgentError(raw)

    expect(safe.status).toBeUndefined()
    expect(safe.stack).toBeUndefined()
    expect(JSON.stringify(safe)).not.toContain(sentinel)
    expect(Object.values(safe)).not.toContain(sentinel)
  })
})
