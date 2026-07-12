import { describe, expect, test } from "bun:test"
import {
  BoundedTtlCache,
  ConcurrencyGate,
  FixedWindowRateLimiter,
} from "./preview-abuse"

describe("FixedWindowRateLimiter", () => {
  test("rejects requests beyond the window limit and resets later", () => {
    const limiter = new FixedWindowRateLimiter(2, 10_000, 10)

    expect(limiter.check("client", 1_000).allowed).toBe(true)
    expect(limiter.check("client", 2_000).allowed).toBe(true)
    expect(limiter.check("client", 3_000)).toEqual({
      allowed: false,
      retryAfterSeconds: 8,
    })
    expect(limiter.check("client", 11_000).allowed).toBe(true)
  })

  test("keeps the client map bounded", () => {
    const limiter = new FixedWindowRateLimiter(1, 10_000, 2)

    limiter.check("one", 0)
    limiter.check("two", 0)
    limiter.check("three", 0)

    expect(limiter.size).toBe(2)
    expect(limiter.check("one", 1).allowed).toBe(true)
  })
})

describe("BoundedTtlCache", () => {
  test("expires entries and evicts the least recently used entry", () => {
    const cache = new BoundedTtlCache<string>(2, 1_000)

    cache.set("one", "1", 0)
    cache.set("two", "2", 0)
    expect(cache.get("one", 100)).toBe("1")
    cache.set("three", "3", 100)

    expect(cache.get("two", 100)).toBeUndefined()
    expect(cache.get("one", 999)).toBe("1")
    expect(cache.get("one", 1_000)).toBeUndefined()
    expect(cache.size).toBe(1)
  })
})

describe("ConcurrencyGate", () => {
  test("rejects excess work without creating an unbounded queue", () => {
    const gate = new ConcurrencyGate(1)
    const release = gate.tryAcquire()

    expect(release).not.toBeNull()
    expect(gate.tryAcquire()).toBeNull()
    expect(gate.active).toBe(1)

    release?.()
    release?.()
    expect(gate.active).toBe(0)
    expect(gate.tryAcquire()).not.toBeNull()
  })
})
