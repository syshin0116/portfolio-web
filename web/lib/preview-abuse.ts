export interface RateLimitDecision {
  allowed: boolean
  retryAfterSeconds: number
}

interface RateLimitEntry {
  count: number
  windowStartedAt: number
}

export class FixedWindowRateLimiter {
  private readonly entries = new Map<string, RateLimitEntry>()

  constructor(
    private readonly limit: number,
    private readonly windowMs: number,
    private readonly maxClients: number
  ) {
    if (limit < 1 || windowMs < 1 || maxClients < 1) {
      throw new Error("Rate limiter values must be positive")
    }
  }

  check(key: string, now = Date.now()): RateLimitDecision {
    let entry = this.entries.get(key)
    if (entry && now - entry.windowStartedAt >= this.windowMs) {
      this.entries.delete(key)
      entry = undefined
    }

    if (!entry) {
      this.makeRoom(now)
      entry = { count: 0, windowStartedAt: now }
    } else {
      this.entries.delete(key)
    }

    this.entries.set(key, entry)
    if (entry.count >= this.limit) {
      return {
        allowed: false,
        retryAfterSeconds: Math.max(
          1,
          Math.ceil((entry.windowStartedAt + this.windowMs - now) / 1000)
        ),
      }
    }

    entry.count += 1
    return { allowed: true, retryAfterSeconds: 0 }
  }

  get size() {
    return this.entries.size
  }

  private makeRoom(now: number) {
    if (this.entries.size < this.maxClients) return

    for (const [key, entry] of this.entries) {
      if (now - entry.windowStartedAt >= this.windowMs) {
        this.entries.delete(key)
      }
    }

    while (this.entries.size >= this.maxClients) {
      const oldestKey = this.entries.keys().next().value
      if (oldestKey === undefined) break
      this.entries.delete(oldestKey)
    }
  }
}

interface CacheEntry<T> {
  expiresAt: number
  value: T
}

export class BoundedTtlCache<T> {
  private readonly entries = new Map<string, CacheEntry<T>>()

  constructor(
    private readonly maxEntries: number,
    private readonly ttlMs: number
  ) {
    if (maxEntries < 1 || ttlMs < 1) {
      throw new Error("Cache values must be positive")
    }
  }

  get(key: string, now = Date.now()): T | undefined {
    const entry = this.entries.get(key)
    if (!entry) return undefined
    if (entry.expiresAt <= now) {
      this.entries.delete(key)
      return undefined
    }

    this.entries.delete(key)
    this.entries.set(key, entry)
    return entry.value
  }

  set(key: string, value: T, now = Date.now()) {
    this.entries.delete(key)
    while (this.entries.size >= this.maxEntries) {
      const oldestKey = this.entries.keys().next().value
      if (oldestKey === undefined) break
      this.entries.delete(oldestKey)
    }
    this.entries.set(key, { value, expiresAt: now + this.ttlMs })
  }

  delete(key: string) {
    this.entries.delete(key)
  }

  get size() {
    return this.entries.size
  }
}

export class ConcurrencyGate {
  private activeCount = 0

  constructor(private readonly maxConcurrent: number) {
    if (maxConcurrent < 1) {
      throw new Error("Concurrency limit must be positive")
    }
  }

  tryAcquire(): (() => void) | null {
    if (this.activeCount >= this.maxConcurrent) return null

    this.activeCount += 1
    let released = false
    return () => {
      if (released) return
      released = true
      this.activeCount -= 1
    }
  }

  get active() {
    return this.activeCount
  }
}
