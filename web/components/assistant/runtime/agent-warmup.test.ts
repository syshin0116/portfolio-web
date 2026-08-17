import { describe, expect, test } from "bun:test"

import { warmAgent } from "./agent-warmup"

const API_URL = "https://agent.example.test"

function immediateSleep() {
  return Promise.resolve()
}

describe("agent warm-up probe", () => {
  test("probes the readiness path on the agent origin and stops on success", async () => {
    const seen: string[] = []
    const ready = await warmAgent({
      apiUrl: API_URL,
      signal: new AbortController().signal,
      sleep: immediateSleep,
      fetch: async (input) => {
        seen.push(String(input))
        return new Response(null, { status: 200 })
      },
    })

    expect(ready).toBe(true)
    expect(seen).toEqual([`${API_URL}/ready`])
  })

  test("retries a booting revision until it answers", async () => {
    let attempts = 0
    const ready = await warmAgent({
      apiUrl: API_URL,
      signal: new AbortController().signal,
      sleep: immediateSleep,
      fetch: async () => {
        attempts += 1
        if (attempts < 3) throw new TypeError("network error")
        return new Response(null, { status: 200 })
      },
    })

    expect(ready).toBe(true)
    expect(attempts).toBe(3)
  })

  test("reports a revision that never becomes ready instead of looping", async () => {
    let attempts = 0
    const ready = await warmAgent({
      apiUrl: API_URL,
      signal: new AbortController().signal,
      sleep: immediateSleep,
      fetch: async () => {
        attempts += 1
        return new Response(null, { status: 503 })
      },
    })

    expect(ready).toBe(false)
    expect(attempts).toBe(4)
  })

  test("gives up immediately when the origin has no readiness route", async () => {
    let attempts = 0
    const ready = await warmAgent({
      apiUrl: API_URL,
      signal: new AbortController().signal,
      sleep: immediateSleep,
      fetch: async () => {
        attempts += 1
        return new Response(null, { status: 404 })
      },
    })

    expect(ready).toBe(false)
    expect(attempts).toBe(1)
  })

  test("stops probing once the caller aborts", async () => {
    const controller = new AbortController()
    let attempts = 0

    await expect(
      warmAgent({
        apiUrl: API_URL,
        signal: controller.signal,
        sleep: immediateSleep,
        fetch: async () => {
          attempts += 1
          controller.abort(new DOMException("unmounted", "AbortError"))
          throw new DOMException("aborted", "AbortError")
        },
      })
    ).rejects.toThrow("unmounted")
    expect(attempts).toBe(1)
  })
})
