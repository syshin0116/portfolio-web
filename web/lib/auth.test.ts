import { describe, expect, test } from "bun:test"
import { neonConfig } from "@neondatabase/serverless"
import { readFile } from "node:fs/promises"
import type { Pool as PgPool } from "pg"
import {
  type AuthPostgresPoolConfig,
  readAuthRuntimeConfig,
} from "./auth-config"
import {
  authTesting,
  createAuthOptions,
  withAuthPoolLifecycle,
} from "./auth"

const VALID_ENV = {
  NODE_ENV: "production",
  DATABASE_URL:
    "postgresql://auth:secret@db.example.test/auth?sslmode=require",
  AUTH_SECRET: "auth-secret-with-at-least-thirty-two-bytes",
  AUTH_ALLOWED_EMAILS: "owner@example.com",
  AUTH_GITHUB_ID: "github-client-id",
  AUTH_GITHUB_SECRET: "github-client-secret",
  AUTH_GOOGLE_ID: "google-client-id",
  AUTH_GOOGLE_SECRET: "google-client-secret",
}

function poolWithEnd(end: () => Promise<void>): PgPool {
  return { end } as unknown as PgPool
}

describe("Auth.js request-scoped Neon pool contract", () => {
  test("creates a fresh adapter pool for every lazy configuration call", () => {
    const poolConfigs: AuthPostgresPoolConfig[] = []
    const createPool = (config: AuthPostgresPoolConfig): PgPool => {
      poolConfigs.push(config)
      return {} as PgPool
    }

    const first = createAuthOptions(VALID_ENV, createPool)
    const second = createAuthOptions(VALID_ENV, createPool)

    expect(poolConfigs).toHaveLength(2)
    for (const config of poolConfigs) {
      expect(config).toEqual(
        expect.objectContaining({
          user: "auth",
          password: "secret",
          host: "db.example.test",
          database: "auth",
          port: 5432,
          ssl: { rejectUnauthorized: true },
        })
      )
      expect(config).not.toHaveProperty("connectionString")
    }
    expect(first.adapter).toBeDefined()
    expect(second.adapter).toBeDefined()
    expect(first.adapter).not.toBe(second.adapter)
  })

  test("wires allowlist and verified-provider checks into sign-in", async () => {
    const verifiedInputs: unknown[] = []
    const options = createAuthOptions(
      VALID_ENV,
      () => ({}) as PgPool,
      async (input) => {
        verifiedInputs.push(input)
        return true
      }
    )
    const signIn = options.callbacks?.signIn
    expect(signIn).toBeDefined()

    const allowed = await signIn!({
      user: {
        id: "owner-id",
        email: "owner@example.com",
        emailVerified: null,
      },
      account: {
        provider: "github",
        providerAccountId: "provider-owner",
        type: "oauth",
        access_token: "provider-token",
      },
      profile: { login: "owner" },
    })
    const denied = await signIn!({
      user: {
        id: "denied-id",
        email: "denied@example.com",
        emailVerified: null,
      },
      account: {
        provider: "google",
        providerAccountId: "provider-denied",
        type: "oidc",
      },
      profile: {
        email: "denied@example.com",
        email_verified: true,
      },
    })

    expect(allowed).toBe(true)
    expect(denied).toBe(false)
    expect(verifiedInputs).toEqual([
      {
        provider: "github",
        email: "owner@example.com",
        accessToken: "provider-token",
        profile: { login: "owner" },
      },
    ])
  })

  test("projects only a canonical adapter id into the session", async () => {
    const options = createAuthOptions(VALID_ENV, () => ({}) as PgPool)
    const session = options.callbacks?.session
    expect(session).toBeDefined()

    type SessionInput = Parameters<NonNullable<typeof session>>[0]
    const projected = await session!(
      {
        session: {
          user: {
            id: "",
            email: "owner@example.com",
            name: null,
            image: null,
          },
          expires: "2099-01-01T00:00:00.000Z",
        },
        user: {
          id: 42,
          email: "owner@example.com",
          emailVerified: null,
        },
        newSession: undefined,
        trigger: "update",
      } as unknown as SessionInput
    )
    expect(projected.user?.id).toBe("42")
  })

  test("closes every request pool after a successful operation", async () => {
    const ended: number[] = []
    let created = 0
    const result = await withAuthPoolLifecycle(
      async (lazyConfig) => {
        lazyConfig()
        lazyConfig()
        return "complete"
      },
      VALID_ENV,
      () => {
        const id = ++created
        return poolWithEnd(async () => {
          ended.push(id)
        })
      }
    )

    expect(result).toBe("complete")
    expect(ended).toEqual([1, 2])
  })

  test("closes a request pool when the auth operation fails", async () => {
    let endCalls = 0
    await expect(
      withAuthPoolLifecycle(
        async (lazyConfig) => {
          lazyConfig()
          throw new Error("operation failed")
        },
        VALID_ENV,
        () =>
          poolWithEnd(async () => {
            endCalls += 1
          })
      )
    ).rejects.toThrow("operation failed")
    expect(endCalls).toBe(1)
  })

  test("fails closed and sanitizes a request pool cleanup failure", async () => {
    await expect(
      withAuthPoolLifecycle(
        async (lazyConfig) => {
          lazyConfig()
          return "must not escape"
        },
        VALID_ENV,
        () =>
          poolWithEnd(async () => {
            throw new Error("connection details")
          })
      )
    ).rejects.toThrow("Auth database connection cleanup failed")
  })

  test("does not create a pool when lazy configuration fails closed", async () => {
    let createCalls = 0
    await expect(
      withAuthPoolLifecycle(
        async (lazyConfig) => {
          lazyConfig()
        },
        { ...VALID_ENV, AUTH_SECRET: "" },
        () => {
          createCalls += 1
          return {} as PgPool
        }
      )
    ).rejects.toThrow("AUTH_SECRET is required")
    expect(createCalls).toBe(0)
  })

  test("constructs a bounded Neon adapter-compatible pool", async () => {
    const previousPoolQueryViaFetch = neonConfig.poolQueryViaFetch
    neonConfig.poolQueryViaFetch = true
    try {
      const pool = authTesting.createNeonRequestPool(
        readAuthRuntimeConfig(VALID_ENV).database
      )
      expect(typeof pool.query).toBe("function")
      expect(typeof pool.connect).toBe("function")
      expect(typeof pool.end).toBe("function")
      expect(pool.options.max).toBe(1)
      expect(pool.options.connectionTimeoutMillis).toBe(5_000)
      expect(pool.options.idleTimeoutMillis).toBe(5_000)
      expect(pool.options.statement_timeout).toBe(10_000)
      expect(pool.options.query_timeout).toBe(12_000)
      expect(pool.options.lock_timeout).toBe(3_000)
      expect(pool.options.options).toBe(
        "-c search_path=pg_catalog,public"
      )
      expect(pool.options).not.toHaveProperty("connectionString")
      expect(
        (
          pool as unknown as {
            hasFetchUnsupportedListeners: boolean
          }
        ).hasFetchUnsupportedListeners
      ).toBe(true)
      await pool.end()
    } finally {
      neonConfig.poolQueryViaFetch = previousPoolQueryViaFetch
    }
  })

  test("keeps Pool and NextAuth creation inside the request lifecycle", async () => {
    const source = await readFile(
      new URL("./auth.ts", import.meta.url),
      "utf8"
    )

    expect(source).toContain("operation(NextAuth(lazyConfig))")
    expect(source).not.toMatch(
      /^(?:const|let|var)\s+\w*[Pp]ool\b/gmu
    )
    expect(source).not.toMatch(
      /^(?:const|let|var)\s+\w*[Aa]uth\b.*NextAuth\(/gmu
    )
  })
})
