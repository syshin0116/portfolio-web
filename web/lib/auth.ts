import PostgresAdapter from "@auth/pg-adapter"
import { Pool as NeonPool } from "@neondatabase/serverless"
import NextAuth, {
  type NextAuthConfig,
  type Session,
} from "next-auth"
import GitHub from "next-auth/providers/github"
import Google from "next-auth/providers/google"
import type { Pool as PgPool } from "pg"
import { isAllowedEmail } from "@/lib/allowed-user"
import {
  assertNoPostgresEnvironmentFallback,
  type AuthPostgresPoolConfig,
  AuthRuntimeConfigurationError,
  isAuthRuntimeConfigurationError,
  readAuthRuntimeConfig,
} from "@/lib/auth-config"
import { canonicalAuthSubject } from "@/lib/auth-subject"
import { hasVerifiedProviderEmail } from "@/lib/oauth-email"

export type AuthPoolFactory = (config: AuthPostgresPoolConfig) => PgPool
export type ProviderEmailVerifier = typeof hasVerifiedProviderEmail
type NextAuthInstance = ReturnType<typeof NextAuth>
type LazyAuthConfig = () => NextAuthConfig

function createNeonRequestPool(
  config: AuthPostgresPoolConfig
): PgPool {
  assertNoPostgresEnvironmentFallback(process.env)
  // @auth/pg-adapter consumes the node-postgres-compatible pool surface
  // implemented by the pinned Neon driver.
  const pool = new NeonPool({
    ...config,
  })
  // Pinned Neon can otherwise route Pool.query through its mutable global
  // fetch optimization, which reconstructs a URL and drops startup options.
  // A per-pool connect listener forces the node-postgres-compatible path.
  pool.on("connect", () => undefined)
  return pool
}

export function createAuthOptions(
  environment: Readonly<Record<string, unknown>> = process.env,
  createPool: AuthPoolFactory = createNeonRequestPool,
  verifyProviderEmail: ProviderEmailVerifier = hasVerifiedProviderEmail
): NextAuthConfig {
  const config = readAuthRuntimeConfig(environment)
  const nodeEnv =
    environment.NODE_ENV === "development" ||
    environment.NODE_ENV === "production" ||
    environment.NODE_ENV === "test"
      ? environment.NODE_ENV
      : undefined

  return {
    secret: config.authSecret,
    adapter: PostgresAdapter(createPool(config.database)),
    providers: [
      GitHub({
        clientId: config.githubId,
        clientSecret: config.githubSecret,
      }),
      Google({
        clientId: config.googleId,
        clientSecret: config.googleSecret,
      }),
    ],
    pages: {
      signIn: "/login",
      error: "/auth/error",
    },
    callbacks: {
      async signIn({ user, account, profile }) {
        if (
          !isAllowedEmail(
            user.email,
            config.allowedEmails.join(","),
            nodeEnv
          )
        ) {
          return false
        }
        return verifyProviderEmail({
          provider: account?.provider,
          email: user.email,
          accessToken: account?.access_token ?? undefined,
          profile,
        })
      },
      session({ session, user }) {
        const subject = canonicalAuthSubject(
          (user as { id?: unknown }).id
        )
        if (subject === null) {
          throw new AuthRuntimeConfigurationError(
            "The Auth.js adapter returned an invalid user id"
          )
        }
        if (session.user) session.user.id = subject
        return session
      },
    },
  }
}

async function closeAuthPools(pools: readonly PgPool[]): Promise<void> {
  const outcomes = await Promise.allSettled(
    pools.map(async (pool) => pool.end())
  )
  if (outcomes.some((outcome) => outcome.status === "rejected")) {
    throw new AuthRuntimeConfigurationError(
      "Auth database connection cleanup failed"
    )
  }
}

export async function withAuthPoolLifecycle<T>(
  operation: (lazyConfig: LazyAuthConfig) => Promise<T>,
  environment: Readonly<Record<string, unknown>> = process.env,
  createPool: AuthPoolFactory = createNeonRequestPool
): Promise<T> {
  const pools: PgPool[] = []
  const lazyConfig = () =>
    createAuthOptions(environment, (databaseConfig) => {
      const pool = createPool(databaseConfig)
      pools.push(pool)
      return pool
    })

  let result: T | undefined
  let operationFailed = false
  let operationError: unknown
  try {
    result = await operation(lazyConfig)
  } catch (error) {
    operationFailed = true
    operationError = error
  }

  await closeAuthPools(pools)
  if (operationFailed) throw operationError
  return result as T
}

async function runNextAuth<T>(
  operation: (instance: NextAuthInstance) => Promise<T>
): Promise<T> {
  return withAuthPoolLifecycle((lazyConfig) =>
    operation(NextAuth(lazyConfig))
  )
}

async function authUnavailableResponse(
  error: unknown
): Promise<Response> {
  if (!isAuthRuntimeConfigurationError(error)) throw error
  console.error(`[auth] ${error.message}`)
  return Response.json(
    { error: "Authentication is unavailable" },
    {
      status: 503,
      headers: { "Cache-Control": "no-store" },
    }
  )
}

type AuthGetRequest = Parameters<NextAuthInstance["handlers"]["GET"]>[0]
type AuthPostRequest = Parameters<NextAuthInstance["handlers"]["POST"]>[0]

async function GET(request: AuthGetRequest) {
  try {
    return await runNextAuth((instance) => instance.handlers.GET(request))
  } catch (error) {
    return authUnavailableResponse(error)
  }
}

async function POST(request: AuthPostRequest) {
  try {
    return await runNextAuth((instance) => instance.handlers.POST(request))
  } catch (error) {
    return authUnavailableResponse(error)
  }
}

export const handlers = { GET, POST }

export async function auth(): Promise<Session | null> {
  return runNextAuth(async (instance) => instance.auth())
}

export const authTesting = {
  createNeonRequestPool,
}
