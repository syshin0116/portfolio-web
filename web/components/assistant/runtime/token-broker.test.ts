import { describe, expect, test } from "bun:test"

import {
  AgentAuthenticationError,
  AgentTokenBroker,
  TOKEN_REFRESH_MARGIN_SECONDS,
  tokenBrokerTesting,
} from "./token-broker"

function token(exp: number, subject = "user-1"): string {
  const encode = (value: object) =>
    Buffer.from(JSON.stringify(value)).toString("base64url")
  return `${encode({ alg: "HS256", typ: "JWT" })}.${encode({
    sub: subject,
    exp,
  })}.signature`
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })
}

describe("AgentTokenBroker", () => {
  test("coalesces refreshes and refreshes 60 seconds before JWT exp", async () => {
    let now = 1_000
    let mintCalls = 0
    const broker = new AgentTokenBroker("user-1", {
      nowSeconds: () => now,
      fetch: async () => {
        mintCalls += 1
        return jsonResponse({
          token: token(mintCalls === 1 ? 1_120 : 1_400),
          expiresAt: 9_999,
        })
      },
    })
    const signal = new AbortController().signal

    const [first, second] = await Promise.all([
      broker.get(signal),
      broker.get(signal),
    ])
    expect(first).toBe(second)
    expect(mintCalls).toBe(1)
    expect(TOKEN_REFRESH_MARGIN_SECONDS).toBe(60)

    now = 1_059
    expect(await broker.get(signal)).toBe(first)
    expect(mintCalls).toBe(1)

    now = 1_060
    expect(await broker.get(signal)).not.toBe(first)
    expect(mintCalls).toBe(2)
  })

  test("partitions tokens by identity and aborts the previous refresh", async () => {
    let observedSignal: AbortSignal | undefined
    let resolveFetch: ((response: Response) => void) | undefined
    const broker = new AgentTokenBroker("user-1", {
      nowSeconds: () => 1_000,
      fetch: async (_input, init) => {
        observedSignal = init?.signal as AbortSignal
        return await new Promise<Response>((resolve) => {
          resolveFetch = resolve
        })
      },
    })
    const pending = broker.get(new AbortController().signal)
    await Promise.resolve()

    broker.setIdentity("user-2")
    expect(observedSignal?.aborted).toBe(true)
    resolveFetch?.(jsonResponse({ token: token(2_000) }))
    await expect(pending).rejects.toMatchObject({ name: "AbortError" })
  })

  test("propagates caller abort without caching a token", async () => {
    let networkSignal: AbortSignal | undefined
    const broker = new AgentTokenBroker("user-1", {
      fetch: async (_input, init) => {
        networkSignal = init?.signal as AbortSignal
        return await new Promise<Response>((_resolve, reject) => {
          networkSignal?.addEventListener(
            "abort",
            () => reject(networkSignal?.reason),
            { once: true }
          )
        })
      },
    })
    const controller = new AbortController()
    const pending = broker.get(controller.signal)
    controller.abort(new DOMException("stop", "AbortError"))

    await expect(pending).rejects.toMatchObject({ name: "AbortError" })
    expect(networkSignal?.aborted).toBe(true)
  })

  test("retries a 401 exactly once with a forced fresh token", async () => {
    const calls: Array<{ url: string; authorization: string | null }> = []
    let minted = 0
    const broker = new AgentTokenBroker("user-1", {
      nowSeconds: () => 1_000,
      fetch: async (input, init) => {
        const url = String(input)
        if (url === "/api/agent-token") {
          minted += 1
          return jsonResponse({ token: token(2_000 + minted, `user-${minted}`) })
        }
        calls.push({
          url,
          authorization: new Headers(init?.headers).get("Authorization"),
        })
        return new Response(null, { status: calls.length <= 2 ? 401 : 200 })
      },
    })
    const signal = new AbortController().signal
    const initial = await broker.onRequest(new URL("https://agent.example/state"), {
      signal,
    })
    const response = await broker.fetchWithAuthRetry(
      "https://agent.example/state",
      initial
    )

    expect(response.status).toBe(401)
    expect(calls).toHaveLength(2)
    expect(minted).toBe(2)
    expect(calls[0]!.authorization).not.toBe(calls[1]!.authorization)
  })

  test("rejects malformed and expired JWTs even if route metadata says fresh", async () => {
    const malformed = new AgentTokenBroker("user-1", {
      nowSeconds: () => 1_000,
      fetch: async () =>
        jsonResponse({ token: "not-a-jwt", expiresAt: 9_999 }),
    })
    await expect(
      malformed.get(new AbortController().signal)
    ).rejects.toBeInstanceOf(AgentAuthenticationError)

    const expired = new AgentTokenBroker("user-1", {
      nowSeconds: () => 1_000,
      fetch: async () =>
        jsonResponse({ token: token(999), expiresAt: 9_999 }),
    })
    await expect(
      expired.get(new AbortController().signal)
    ).rejects.toThrow("already expired")
  })

  test("decodes unicode-safe JWT payloads and preserves existing headers", () => {
    expect(tokenBrokerTesting.decodeJwtExpiration(token(2_000, "한글"))).toBe(
      2_000
    )
    const next = tokenBrokerTesting.withAuthorization(
      { headers: { "x-request-id": "req-1" } },
      "fresh"
    )
    const headers = new Headers(next.headers)
    expect(headers.get("x-request-id")).toBe("req-1")
    expect(headers.get("Authorization")).toBe("Bearer fresh")
  })

  test("pins one old-identity token to one bounded cancellation target", async () => {
    const apiCalls: Array<{
      authorization: string | null
      method: string
      untrustedHeader: string | null
      url: string
    }> = []
    let mintCalls = 0
    const oldToken = token(2_000, "old-user")
    const newToken = token(2_100, "new-user")
    const broker = new AgentTokenBroker("old-user", {
      nowSeconds: () => 1_000,
      fetch: async (input, init) => {
        const url = String(input)
        if (url === "/api/agent-token") {
          mintCalls += 1
          return jsonResponse({
            token: mintCalls === 1 ? oldToken : newToken,
          })
        }
        apiCalls.push({
          authorization: new Headers(init?.headers).get("Authorization"),
          method: init?.method ?? "GET",
          untrustedHeader: new Headers(init?.headers).get("x-untrusted"),
          url,
        })
        return url.endsWith("/cancel?wait=0&action=interrupt")
          ? new Response(null, { status: 204 })
          : jsonResponse({ status: "interrupted" })
      },
    })
    const signal = new AbortController().signal
    const snapshot = await broker.captureCancellationSnapshot(signal)
    const cancellationFetch = snapshot.createFetch({
      apiUrl: "https://agent.example",
      threadId: "thread-1",
      runId: "run-1",
    })
    expect(() =>
      snapshot.createFetch({
        apiUrl: "https://agent.example",
        threadId: "thread-2",
        runId: "run-2",
      })
    ).toThrow("already bound")

    broker.setIdentity("new-user")
    expect(await broker.get(signal)).toBe(newToken)
    await cancellationFetch(
      "https://agent.example/threads/thread-1/runs/run-1/cancel?wait=0&action=interrupt",
      { method: "POST", headers: { "x-untrusted": "must-drop" } }
    )
    await cancellationFetch(
      "https://agent.example/threads/thread-1/runs/run-1"
    )

    expect(apiCalls).toEqual([
      {
        authorization: `Bearer ${oldToken}`,
        method: "POST",
        untrustedHeader: null,
        url: "https://agent.example/threads/thread-1/runs/run-1/cancel?wait=0&action=interrupt",
      },
      {
        authorization: `Bearer ${oldToken}`,
        method: "GET",
        untrustedHeader: null,
        url: "https://agent.example/threads/thread-1/runs/run-1",
      },
    ])
    expect(apiCalls.every((call) => call.authorization !== `Bearer ${newToken}`))
      .toBe(true)
    expect(mintCalls).toBe(2)

    await expect(
      cancellationFetch(
        "https://agent.example/threads/thread-1/runs/run-1/cancel?wait=0&action=interrupt",
        { method: "POST" }
      )
    ).rejects.toThrow("already attempted")
    await expect(
      cancellationFetch("https://agent.example/threads/thread-2/runs/run-1")
    ).rejects.toThrow("out-of-scope")

    snapshot.dispose()
    await expect(
      cancellationFetch(
        "https://agent.example/threads/thread-1/runs/run-1"
      )
    ).rejects.toThrow("disposed")
  })

  test("seal blocks general refresh while the captured cancellation remains usable", async () => {
    let mintCalls = 0
    const broker = new AgentTokenBroker("old-user", {
      nowSeconds: () => 1_000,
      fetch: async (input) => {
        if (String(input) === "/api/agent-token") {
          mintCalls += 1
          return jsonResponse({ token: token(2_000, "old-user") })
        }
        return new Response(null, { status: 204 })
      },
    })
    const signal = new AbortController().signal
    const snapshot = await broker.captureCancellationSnapshot(signal)
    const cancellationFetch = snapshot.createFetch({
      apiUrl: "https://agent.example",
      threadId: "thread-1",
      runId: "run-1",
    })

    broker.seal()
    expect(tokenBrokerTesting.inspect(broker)).toEqual({
      cached: false,
      refreshing: false,
      sealed: true,
    })
    await expect(broker.get(signal, true)).rejects.toThrow("disposed")
    await cancellationFetch(
      "https://agent.example/threads/thread-1/runs/run-1/cancel?wait=0&action=interrupt",
      { method: "POST" }
    )
    expect(mintCalls).toBe(1)

    snapshot.dispose()
    broker.clear()
    expect(tokenBrokerTesting.inspect(broker)).toEqual({
      cached: false,
      refreshing: false,
      sealed: true,
    })
  })

  test("pins resumed-run discovery to one exact read-only thread endpoint and old identity", async () => {
    const oldToken = token(2_000, "old-user")
    const newToken = token(2_100, "new-user")
    const calls: Array<{
      authorization: string | null
      credentials: RequestCredentials | undefined
      method: string
      untrustedHeader: string | null
      url: string
    }> = []
    let mintCalls = 0
    const broker = new AgentTokenBroker("old-user", {
      nowSeconds: () => 1_000,
      fetch: async (input, init) => {
        const url = String(input)
        if (url === "/api/agent-token") {
          mintCalls += 1
          return jsonResponse({
            token: mintCalls === 1 ? oldToken : newToken,
          })
        }
        calls.push({
          authorization: new Headers(init?.headers).get("Authorization"),
          credentials: init?.credentials,
          method: init?.method ?? "GET",
          untrustedHeader: new Headers(init?.headers).get("x-untrusted"),
          url,
        })
        return jsonResponse([])
      },
    })
    const signal = new AbortController().signal
    const snapshot = await broker.captureCancellationSnapshot(signal)
    const resolverFetch = snapshot.createRunResolverFetch({
      apiUrl: "https://agent.example",
      threadId: "thread-1",
    })

    broker.setIdentity("new-user")
    expect(await broker.get(signal)).toBe(newToken)
    await resolverFetch(
      "https://agent.example/threads/thread-1/runs?offset=0&limit=10",
      {
        headers: { "x-untrusted": "drop-me" },
        credentials: "include",
      }
    )

    expect(calls).toEqual([
      {
        authorization: `Bearer ${oldToken}`,
        credentials: "omit",
        method: "GET",
        untrustedHeader: null,
        url: "https://agent.example/threads/thread-1/runs?offset=0&limit=10",
      },
    ])
    expect(calls[0]!.authorization).not.toBe(`Bearer ${newToken}`)
    await expect(
      resolverFetch(
        "https://agent.example/threads/thread-1/runs?limit=11&offset=0"
      )
    ).rejects.toThrow("out-of-scope")
    await expect(
      resolverFetch(
        "https://agent.example/threads/thread-1/runs?limit=10&offset=0",
        { method: "POST" }
      )
    ).rejects.toThrow("out-of-scope")
    await expect(
      resolverFetch(
        "https://agent.example/threads/thread-1/runs?limit=10&offset=0",
        { body: "opaque" }
      )
    ).rejects.toThrow("out-of-scope")
    await expect(
      resolverFetch(
        "https://user:password@agent.example/threads/thread-1/runs?limit=10&offset=0"
      )
    ).rejects.toThrow("out-of-scope")
  })

  test("bounds resumed-run polling and seals discovery after exact run binding", async () => {
    const broker = new AgentTokenBroker("user-1", {
      nowSeconds: () => 1_000,
      fetch: async (input) =>
        String(input) === "/api/agent-token"
          ? jsonResponse({ token: token(2_000) })
          : jsonResponse([]),
    })
    const signal = new AbortController().signal
    const snapshot = await broker.captureCancellationSnapshot(signal)
    const resolverFetch = snapshot.createRunResolverFetch({
      apiUrl: "https://agent.example",
      threadId: "thread-1",
    })
    const exactList =
      "https://agent.example/threads/thread-1/runs?limit=10&offset=0"
    for (let index = 0; index < 32; index += 1) {
      expect((await resolverFetch(exactList)).status).toBe(200)
    }
    await expect(resolverFetch(exactList)).rejects.toThrow("out-of-scope")

    expect(() =>
      snapshot.createFetch({
        apiUrl: "https://agent.example",
        threadId: "thread-2",
        runId: "run-1",
      })
    ).toThrow("does not match")
    const cancellationFetch = snapshot.createFetch({
      apiUrl: "https://agent.example",
      threadId: "thread-1",
      runId: "run-1",
    })
    await expect(resolverFetch(exactList)).rejects.toThrow(
      "closed after run binding"
    )
    await cancellationFetch(
      "https://agent.example/threads/thread-1/runs/run-1/cancel?wait=0&action=interrupt",
      { method: "POST" }
    )
  })

  test("rejects credential-bearing restricted-fetch base URLs", async () => {
    const broker = new AgentTokenBroker("user-1", {
      nowSeconds: () => 1_000,
      fetch: async () => jsonResponse({ token: token(2_000) }),
    })
    const snapshot = await broker.captureCancellationSnapshot(
      new AbortController().signal
    )
    expect(() =>
      snapshot.createRunResolverFetch({
        apiUrl: "https://user:password@agent.example",
        threadId: "thread-1",
      })
    ).toThrow("must not contain")
    expect(() =>
      snapshot.createFetch({
        apiUrl: "https://user:password@agent.example",
        threadId: "thread-1",
        runId: "run-1",
      })
    ).toThrow("must not contain")
  })
})
