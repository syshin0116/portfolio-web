import { describe, expect, test } from "bun:test"

import {
  AgentTokenError,
  DEFAULT_TOKEN_REFRESH_MARGIN_SECONDS,
  RefreshingAgentToken,
  type AgentOnRequest,
} from "./auth"

describe("RefreshingAgentToken", () => {
  test("refreshes an async onRequest token at the 60 second margin", async () => {
    let nowSeconds = 1_000
    let calls = 0
    const onRequest: AgentOnRequest = async ({ purpose, threadId }) => {
      calls += 1
      expect(purpose).toBe("command")
      expect(threadId).toBe("thread-1")
      return {
        token: `token-${calls}`,
        expiresAt: calls === 1 ? 1_120 : 1_300,
      }
    }
    const cache = new RefreshingAgentToken(onRequest, {
      nowSeconds: () => nowSeconds,
    })
    const signal = new AbortController().signal
    const context = {
      purpose: "command" as const,
      threadId: "thread-1",
      url: "https://agent.example/threads/thread-1/commands",
      signal,
    }

    expect(DEFAULT_TOKEN_REFRESH_MARGIN_SECONDS).toBe(60)
    expect(await cache.get(context)).toBe("token-1")

    nowSeconds = 1_059
    expect(await cache.get(context)).toBe("token-1")
    expect(calls).toBe(1)

    nowSeconds = 1_060
    expect(await cache.get(context)).toBe("token-2")
    expect(calls).toBe(2)
  })

  test("does not cache an expired or malformed token", async () => {
    const expired = new RefreshingAgentToken(
      async () => ({ token: "expired", expiresAt: 999 }),
      { nowSeconds: () => 1_000 }
    )
    await expect(
      expired.get({
        purpose: "event-stream",
        threadId: "thread-1",
        url: "https://agent.example/events",
        signal: new AbortController().signal,
      })
    ).rejects.toBeInstanceOf(AgentTokenError)

    const empty = new RefreshingAgentToken(
      async () => ({ token: "", expiresAt: 2_000 }),
      { nowSeconds: () => 1_000 }
    )
    await expect(
      empty.get({
        purpose: "command",
        threadId: "thread-1",
        url: "https://agent.example/commands",
        signal: new AbortController().signal,
      })
    ).rejects.toThrow("non-empty")
  })

  test("checks expiration after the asynchronous hook resolves", async () => {
    let nowSeconds = 1_000
    const cache = new RefreshingAgentToken(
      async () => {
        nowSeconds = 1_100
        return { token: "too-late", expiresAt: 1_050 }
      },
      { nowSeconds: () => nowSeconds }
    )

    await expect(
      cache.get({
        purpose: "command",
        threadId: "thread-1",
        url: "https://agent.example/commands",
        signal: new AbortController().signal,
      })
    ).rejects.toThrow("expired")
  })

  test("passes AbortSignal through to the asynchronous hook", async () => {
    const reason = new DOMException("cancelled", "AbortError")
    const controller = new AbortController()
    controller.abort(reason)
    const cache = new RefreshingAgentToken(async ({ signal }) => {
      signal.throwIfAborted()
      return { token: "unreachable", expiresAt: 2_000 }
    })

    await expect(
      cache.get({
        purpose: "event-stream",
        threadId: "thread-1",
        url: "https://agent.example/events",
        signal: controller.signal,
      })
    ).rejects.toBe(reason)
  })
})
