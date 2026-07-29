import { describe, expect, test } from "bun:test"
import {
  Client as NeonClient,
  neonConfig,
  Pool as NeonPool,
} from "@neondatabase/serverless"
import { Client as PgClient } from "pg"
import { parse as parsePgConnectionString } from "pg-connection-string"
import {
  AUTH_INSECURE_LOOPBACK_TEST_ARGUMENT,
  AUTH_POSTGRES_SEARCH_PATH_OPTIONS,
  AuthRuntimeConfigurationError,
  parseAuthPostgresPoolConfig,
  parseAuthEmailList,
  readAuthMigrationCliConfig,
  readAuthMigrationConfig,
  readAuthRuntimeConfig,
} from "./auth-config"

const VALID_ENV = {
  NODE_ENV: "production",
  DATABASE_URL:
    "postgresql://auth:secret@db.example.test/auth?sslmode=require",
  AUTH_SECRET: "auth-secret-with-at-least-thirty-two-bytes",
  AUTH_ALLOWED_EMAILS: "Owner@Example.com",
  AUTH_GITHUB_ID: "github-client-id",
  AUTH_GITHUB_SECRET: "github-client-secret",
  AUTH_GOOGLE_ID: "google-client-id",
  AUTH_GOOGLE_SECRET: "google-client-secret",
}

interface NeonConnectionParametersForTest {
  readonly user: string
  readonly password: string
  readonly database: string
  readonly host: string
  readonly port: number
  readonly ssl: unknown
  readonly options?: string
  readonly statement_timeout?: number
  readonly query_timeout?: number
  readonly lock_timeout?: number
  readonly idle_in_transaction_session_timeout?: number
  readonly application_name?: string
}

function neonConnectionParameters(
  client: unknown
): NeonConnectionParametersForTest {
  return (
    client as {
      readonly connectionParameters: NeonConnectionParametersForTest
    }
  ).connectionParameters
}

describe("readAuthRuntimeConfig", () => {
  test("returns a normalized fail-closed production contract", () => {
    const config = readAuthRuntimeConfig(VALID_ENV)
    expect(config).toEqual({
      database: expect.objectContaining({
        user: "auth",
        password: "secret",
        host: "db.example.test",
        port: 5432,
        database: "auth",
        ssl: { rejectUnauthorized: true },
        options: AUTH_POSTGRES_SEARCH_PATH_OPTIONS,
      }),
      authSecret: VALID_ENV.AUTH_SECRET,
      githubId: VALID_ENV.AUTH_GITHUB_ID,
      githubSecret: VALID_ENV.AUTH_GITHUB_SECRET,
      googleId: VALID_ENV.AUTH_GOOGLE_ID,
      googleSecret: VALID_ENV.AUTH_GOOGLE_SECRET,
      allowedEmails: ["owner@example.com"],
    })
    expect(config.database).not.toHaveProperty("connectionString")
  })

  test.each([
    "DATABASE_URL",
    "AUTH_SECRET",
    "AUTH_GITHUB_ID",
    "AUTH_GITHUB_SECRET",
    "AUTH_GOOGLE_ID",
    "AUTH_GOOGLE_SECRET",
  ])("rejects a missing %s", (name) => {
    const environment = { ...VALID_ENV, [name]: "" }
    expect(() => readAuthRuntimeConfig(environment)).toThrow(
      new AuthRuntimeConfigurationError(`${name} is required`)
    )
  })

  test("rejects a weak secret", () => {
    expect(() =>
      readAuthRuntimeConfig({ ...VALID_ENV, AUTH_SECRET: "too-short" })
    ).toThrow("AUTH_SECRET must be at least 32 bytes")
  })

  test("rejects an empty production allowlist", () => {
    expect(() =>
      readAuthRuntimeConfig({ ...VALID_ENV, AUTH_ALLOWED_EMAILS: " , " })
    ).toThrow(
      "AUTH_ALLOWED_EMAILS must contain at least one email in production"
    )
  })

  test("allows an empty local-development allowlist", () => {
    expect(
      readAuthRuntimeConfig({
        ...VALID_ENV,
        NODE_ENV: "development",
        AUTH_ALLOWED_EMAILS: "",
      }).allowedEmails
    ).toEqual([])
  })
})

describe("direct PostgreSQL URL validation", () => {
  test("accepts only one exact secure Neon-compatible query contract", () => {
    const value =
      "postgresql://auth:secret@db.example.test:5432/auth?sslmode=require"
    expect(
      parseAuthPostgresPoolConfig(value, "DATABASE_URL")
    ).toEqual(
      expect.objectContaining({
        user: "auth",
        password: "secret",
        host: "db.example.test",
        port: 5432,
        database: "auth",
        ssl: { rejectUnauthorized: true },
        options: AUTH_POSTGRES_SEARCH_PATH_OPTIONS,
      })
    )
  })

  test.each([
    "https://db.example.test/auth",
    "postgresql://db.example.test",
    "postgresql://auth:secret@ep-example-pooler.us-east-1.aws.neon.tech/auth?sslmode=require",
    "postgresql://auth@db.example.test/auth?sslmode=require",
    "postgresql://auth:@db.example.test/auth?sslmode=require",
    "postgresql://:secret@db.example.test/auth?sslmode=require",
    "postgresql://auth:secret@db.example.test/auth",
    "postgresql://auth:secret@db.example.test/auth?",
    "postgresql://auth:secret@db.example.test/auth?channel_binding=require",
    "postgresql://auth:secret@db.example.test/auth?sslmode=require&channel_binding=require",
    "postgresql://auth:secret@db.example.test/auth?channel_binding=require&sslmode=require",
    "postgresql://auth:secret@db.example.test/auth?sslmode=disable",
    "postgresql://auth:secret@db.example.test/auth?sslmode=prefer",
    "postgresql://auth:secret@127.0.0.1:5432/auth?sslmode=disable",
    "postgresql://auth:secret@db.example.test/auth?sslmode=require&channel_binding=disable",
    "postgresql://auth:secret@db.example.test/auth?sslmode=require&sslmode=require",
    "postgresql://auth:secret@db.example.test/auth?sslmode=require&channel_binding=require&channel_binding=require",
    "postgresql://auth:secret@db.example.test/auth?sslmode=require&host=other.example.test",
    "postgresql://auth:secret@db.example.test/auth?sslmode=require&port=6543",
    "postgresql://auth:secret@db.example.test/auth?sslmode=require&database=other",
    "postgresql://auth:secret@db.example.test/auth?sslmode=require&user=other",
    "postgresql://auth:secret@db.example.test/auth?sslmode=require&password=other",
    "postgresql://auth:secret@db.example.test/auth?sslmode=require&options=-c%20search_path%3Dother",
    "postgresql://auth:secret@db.example.test/auth?sslmode=require&application_name=delivery",
    "postgresql://auth:secret@db.example.test:0/auth?sslmode=require",
    "postgresql://auth:secret@db.example.test:6543/auth?sslmode=require",
    "postgresql://auth:secret@db.example.test:/auth?sslmode=require",
    "postgresql://auth:secret@db.example.test:05432/auth?sslmode=require",
    "postgresql://auth:secret@db.example.test:0005432/auth?sslmode=require",
    "postgresql://auth:secret@db..example.test/auth?sslmode=require",
    "postgresql://auth:secret@-db.example.test/auth?sslmode=require",
    "postgresql://auth:secret@db-.example.test/auth?sslmode=require",
    "postgresql://auth:secret@db.example.test/auth?%68ost=other.example.test&sslmode=require",
    "postgresql://auth:secret@db。example。test/auth?sslmode=require",
    "postgresql://auth:secret@%64b.example.test/auth?sslmode=require",
    "postgresql://auth:secret@db.example.test/auth%3Aother?sslmode=require",
    "postgresql://auth:secret@db.example.test/auth?sslmode=require#",
    "postgresql://auth:secret@db.example.test/auth?sslmode=require#ignored",
    "not a URL",
  ])("rejects an invalid or pooled endpoint %s", (value) => {
    expect(() =>
      parseAuthPostgresPoolConfig(value, "DATABASE_URL")
    ).toThrow(AuthRuntimeConfigurationError)
  })

  test.each(["PGPORT", "PGUSER", "PGPASSWORD", "PGOPTIONS", "PGSSLMODE"])(
    "rejects non-empty %s fallback input without disclosing its value",
    (name) => {
      const secretValue = "must-not-appear-in-the-error"
      let thrown: unknown
      try {
        readAuthRuntimeConfig({
          ...VALID_ENV,
          [name]: secretValue,
        })
      } catch (error) {
        thrown = error
      }
      expect(thrown).toBeInstanceOf(AuthRuntimeConfigurationError)
      expect(String(thrown)).toContain(name)
      expect(String(thrown)).not.toContain(secretValue)
    }
  )

  test("rejects query input that node-postgres would otherwise reinterpret", () => {
    const authorityHost = "db.example.test"
    for (const [query, parsedKey, parsedValue] of [
      ["host=other.example.test", "host", "other.example.test"],
      ["port=6543", "port", "6543"],
      ["user=other", "user", "other"],
      ["password=other", "password", "other"],
      ["options=-c%20role%3Dother", "options", "-c role=other"],
    ] as const) {
      const value =
        `postgresql://auth:secret@${authorityHost}/auth` +
        `?sslmode=require&${query}`
      expect(new URL(value).hostname).toBe(authorityHost)
      expect(
        parsePgConnectionString(value, {
          useLibpqCompat: true,
        })[parsedKey]
      ).toBe(parsedValue)
      expect(() =>
        parseAuthPostgresPoolConfig(value, "DATABASE_URL")
      ).toThrow(AuthRuntimeConfigurationError)
    }

    const duplicate =
      `postgresql://auth:secret@${authorityHost}/auth` +
      "?sslmode=require&sslmode=disable"
    expect(
      parsePgConnectionString(duplicate, {
        useLibpqCompat: true,
      }).sslmode
    ).toBe("disable")
    expect(() =>
      parseAuthPostgresPoolConfig(duplicate, "DATABASE_URL")
    ).toThrow(AuthRuntimeConfigurationError)

    const encodedReservedDatabase =
      `postgresql://auth:secret@${authorityHost}/` +
      "auth%3Aother?sslmode=require"
    expect(
      decodeURIComponent(new URL(encodedReservedDatabase).pathname.slice(1))
    ).toBe("auth:other")
    expect(
      parsePgConnectionString(encodedReservedDatabase, {
        useLibpqCompat: true,
      }).database
    ).toBe("auth%3Aother")
    expect(() =>
      parseAuthPostgresPoolConfig(
        encodedReservedDatabase,
        "DATABASE_URL"
      )
    ).toThrow(AuthRuntimeConfigurationError)
  })

  test("allows insecure loopback only through the explicit test option", () => {
    const value =
      "postgresql://auth:secret@127.0.0.1:5432/auth?sslmode=disable"
    expect(() =>
      parseAuthPostgresPoolConfig(value, "DATABASE_URL")
    ).toThrow(AuthRuntimeConfigurationError)
    expect(
      parseAuthPostgresPoolConfig(value, "AUTH_POSTGRES_TEST_URL", {
        allowInsecureLoopback: true,
      }).ssl
    ).toBe(false)
    expect(() =>
      parseAuthPostgresPoolConfig(
        value.replace("127.0.0.1", "LOCALHOST"),
        "AUTH_POSTGRES_TEST_URL",
        { allowInsecureLoopback: true }
      )
    ).toThrow(AuthRuntimeConfigurationError)
    expect(() =>
      readAuthRuntimeConfig({
        ...VALID_ENV,
        DATABASE_URL: value,
      })
    ).toThrow(AuthRuntimeConfigurationError)
  })

  test("keeps actual Neon Client and Pool parameters on the one decoded target", async () => {
    for (const [
        value,
        expectedUser,
        expectedDatabase,
        rawUser,
        rawDatabase,
      ] of [
        [
          "postgresql://u:p@db.example.test/a%2541b?sslmode=require",
          "u",
          "a%41b",
          "u",
          "aAb",
        ],
        [
          "postgresql://u:p@db.example.test/%252F?sslmode=require",
          "u",
          "%2F",
          "u",
          "%2F",
        ],
        [
          "postgresql://%3A:p@db.example.test/auth?sslmode=require",
          ":",
          "auth",
          null,
          "auth",
        ],
      ] as const) {
        const rawClient = new NeonClient(value)
        const rawParameters = neonConnectionParameters(rawClient)
        if (rawUser === null) {
          expect(rawParameters.user).not.toBe(expectedUser)
          expect(rawParameters.user.length).toBeGreaterThan(0)
        } else {
          expect(rawParameters.user).toBe(rawUser)
        }
        expect(rawParameters.database).toBe(rawDatabase)

        const config = parseAuthPostgresPoolConfig(
          value,
          "DATABASE_URL"
        )
        expect(config).not.toHaveProperty("connectionString")
        const client = new NeonClient(config)
        const clientParameters = neonConnectionParameters(client)
        expect(clientParameters.user).toBe(expectedUser)
        expect(clientParameters.password).toBe("p")
        expect(clientParameters.database).toBe(
          expectedDatabase
        )
        expect(clientParameters.options).toBe(
          AUTH_POSTGRES_SEARCH_PATH_OPTIONS
        )
        expect(clientParameters.host).toBe("db.example.test")
        expect(clientParameters.port).toBe(5432)
        expect(clientParameters.ssl).toEqual({
          rejectUnauthorized: true,
        })
        expect(clientParameters.statement_timeout).toBe(10_000)
        expect(clientParameters.query_timeout).toBe(12_000)
        expect(clientParameters.lock_timeout).toBe(3_000)
        expect(
          clientParameters.idle_in_transaction_session_timeout
        ).toBe(10_000)
        expect(clientParameters.application_name).toBe(
          "syshin0116-auth-runtime"
        )

        const pool = new NeonPool(config)
        const pooledClient = new pool.Client(pool.options)
        const pooledParameters =
          neonConnectionParameters(pooledClient)
        expect(pooledParameters.user).toBe(
          expectedUser
        )
        expect(pooledParameters.database).toBe(
          expectedDatabase
        )
        expect(pooledParameters.options).toBe(
          AUTH_POSTGRES_SEARCH_PATH_OPTIONS
        )

        const pgClient = new PgClient(config)
        const pgParameters = neonConnectionParameters(pgClient)
        expect(pgParameters.user).toBe(expectedUser)
        expect(pgParameters.password).toBe("p")
        expect(pgParameters.database).toBe(expectedDatabase)
        expect(pgParameters.host).toBe("db.example.test")
        expect(pgParameters.port).toBe(5432)
        expect(pgParameters.options).toBe(
          AUTH_POSTGRES_SEARCH_PATH_OPTIONS
        )
        await pool.end()
      }
  })

  test("rejects a nondefault hosted port that the pinned Neon proxy ignores", () => {
    const wsProxy = neonConfig.wsProxy
    expect(typeof wsProxy).toBe("function")
    if (typeof wsProxy !== "function") return
    const host = "ep-project-a.us-east-2.aws.neon.tech"
    expect(wsProxy(host, 5432)).toBe(wsProxy(host, 6543))
    expect(() =>
      parseAuthPostgresPoolConfig(
        `postgresql://auth:secret@${host}:6543/auth?sslmode=require`,
        "DATABASE_URL"
      )
    ).toThrow(AuthRuntimeConfigurationError)
  })
})

test("parseAuthEmailList normalizes and deduplicates", () => {
  expect(
    parseAuthEmailList("Owner@Example.com, member@example.com,owner@example.com")
  ).toEqual(["owner@example.com", "member@example.com"])
})

test("migration configuration never falls back to runtime DATABASE_URL", () => {
  expect(() =>
    readAuthMigrationConfig({
      DATABASE_URL: VALID_ENV.DATABASE_URL,
    })
  ).toThrow(
    "AUTH_DATABASE_MIGRATION_URL is required; DATABASE_URL is intentionally not a fallback"
  )
  expect(
    readAuthMigrationConfig({
      AUTH_DATABASE_MIGRATION_URL: VALID_ENV.DATABASE_URL,
    }).database
  ).toBe("auth")
})

test("migration configuration returns the exact maintenance pool contract", () => {
  const config = readAuthMigrationConfig({
    AUTH_DATABASE_MIGRATION_URL: VALID_ENV.DATABASE_URL,
  })
  expect(config).toEqual(
    expect.objectContaining({
      user: "auth",
      password: "secret",
      host: "db.example.test",
      port: 5432,
      database: "auth",
      ssl: { rejectUnauthorized: true },
      options: AUTH_POSTGRES_SEARCH_PATH_OPTIONS,
      statement_timeout: 60_000,
      query_timeout: 65_000,
      lock_timeout: 5_000,
      idle_in_transaction_session_timeout: 60_000,
      application_name: "syshin0116-auth-maintenance",
      max: 1,
      connectionTimeoutMillis: 5_000,
      idleTimeoutMillis: 5_000,
    })
  )
  expect(config).not.toHaveProperty("connectionString")
})

test("migration configuration rejects PostgreSQL environment fallback", () => {
  expect(() =>
    readAuthMigrationConfig({
      AUTH_DATABASE_MIGRATION_URL: VALID_ENV.DATABASE_URL,
      PGOPTIONS: "-c search_path=attacker",
    })
  ).toThrow("PGOPTIONS")
})

describe("migration CLI loopback test boundary", () => {
  const loopbackUrl =
    "postgresql://postgres:test@127.0.0.1:5432/postgres?sslmode=disable"

  test("keeps the no-argument production path secure", () => {
    expect(
      readAuthMigrationCliConfig(
        { AUTH_DATABASE_MIGRATION_URL: VALID_ENV.DATABASE_URL },
        []
      ).database
    ).toBe("auth")
    expect(() =>
      readAuthMigrationCliConfig(
        { AUTH_DATABASE_MIGRATION_URL: loopbackUrl },
        []
      )
    ).toThrow(AuthRuntimeConfigurationError)
  })

  test("allows only an exact integration URL with the explicit test argument", () => {
    expect(
      readAuthMigrationCliConfig(
        {
          AUTH_DATABASE_MIGRATION_URL: loopbackUrl,
          AUTH_POSTGRES_TEST_URL: loopbackUrl,
        },
        [AUTH_INSECURE_LOOPBACK_TEST_ARGUMENT]
      ).ssl
    ).toBe(false)

    for (const [environment, arguments_] of [
      [
        {
          AUTH_DATABASE_MIGRATION_URL: loopbackUrl,
          AUTH_POSTGRES_TEST_URL: loopbackUrl.replace(
            "postgres:test",
            "other:test"
          ),
        },
        [AUTH_INSECURE_LOOPBACK_TEST_ARGUMENT],
      ],
      [
        {
          AUTH_DATABASE_MIGRATION_URL: loopbackUrl.replace(
            "127.0.0.1",
            "LOCALHOST"
          ),
          AUTH_POSTGRES_TEST_URL: loopbackUrl.replace(
            "127.0.0.1",
            "LOCALHOST"
          ),
        },
        [AUTH_INSECURE_LOOPBACK_TEST_ARGUMENT],
      ],
      [
        {
          AUTH_DATABASE_MIGRATION_URL: loopbackUrl,
          AUTH_POSTGRES_TEST_URL: loopbackUrl,
        },
        ["--unknown"],
      ],
    ] as const) {
      expect(() =>
        readAuthMigrationCliConfig(environment, arguments_)
      ).toThrow(AuthRuntimeConfigurationError)
    }
  })
})
