import type { PoolConfig as NeonPoolConfig } from "@neondatabase/serverless"
import type { PoolConfig as PgPoolConfig } from "pg"

const MINIMUM_AUTH_SECRET_BYTES = 32
const CONTROL_CHARACTER_PATTERN = /[\u0000-\u001f\u007f]/u
const WHITESPACE_PATTERN = /\s/u
const INVALID_PERCENT_ESCAPE_PATTERN = /%(?![0-9a-f]{2})/iu
const RESERVED_DATABASE_CHARACTER_PATTERN = /[:/?#@!$&'()*+,;=]/u
const POSTGRES_ENVIRONMENT_NAME_PATTERN = /^PG[A-Z0-9_]*$/u
const RUNTIME_STATEMENT_TIMEOUT_MS = 10_000
const RUNTIME_QUERY_TIMEOUT_MS = 12_000
const RUNTIME_LOCK_TIMEOUT_MS = 3_000
const MAINTENANCE_STATEMENT_TIMEOUT_MS = 60_000
const MAINTENANCE_QUERY_TIMEOUT_MS = 65_000
const MAINTENANCE_LOCK_TIMEOUT_MS = 5_000

export const AUTH_POSTGRES_SEARCH_PATH_OPTIONS =
  "-c search_path=pg_catalog,public" as const
export const AUTH_INSECURE_LOOPBACK_TEST_ARGUMENT =
  "--allow-insecure-loopback-test"

export class AuthRuntimeConfigurationError extends Error {
  readonly code = "AUTH_RUNTIME_CONFIGURATION_ERROR"

  constructor(message: string) {
    super(message)
    this.name = "AuthRuntimeConfigurationError"
  }
}

export interface AuthPostgresPoolConfig {
  readonly user: string
  readonly password: string
  readonly host: string
  readonly port: number
  readonly database: string
  readonly ssl: false | Readonly<{ rejectUnauthorized: true }>
  readonly options: typeof AUTH_POSTGRES_SEARCH_PATH_OPTIONS
  readonly statement_timeout: number
  readonly query_timeout: number
  readonly lock_timeout: number
  readonly idle_in_transaction_session_timeout: number
  readonly application_name:
    | "syshin0116-auth-runtime"
    | "syshin0116-auth-maintenance"
  readonly max: 1
  readonly connectionTimeoutMillis: 5_000
  readonly idleTimeoutMillis: 5_000
  readonly connectionString?: never
}

export interface AuthRuntimeConfig {
  database: AuthPostgresPoolConfig
  authSecret: string
  githubId: string
  githubSecret: string
  googleId: string
  googleSecret: string
  allowedEmails: readonly string[]
}

type Environment = Readonly<Record<string, unknown>>
interface DirectPostgresUrlOptions {
  readonly allowInsecureLoopback?: boolean
  readonly maintenance?: boolean
}

function configuredString(
  environment: Environment,
  name: string
): string {
  const value = environment[name]
  if (typeof value !== "string" || value.trim() === "") {
    throw new AuthRuntimeConfigurationError(`${name} is required`)
  }
  if (value !== value.trim()) {
    throw new AuthRuntimeConfigurationError(
      `${name} must not contain surrounding whitespace`
    )
  }
  return value
}

export function parseAuthEmailList(value: unknown): readonly string[] {
  if (typeof value !== "string") return []
  return [
    ...new Set(
      value
        .split(",")
        .map((email) => email.trim().toLowerCase())
        .filter(Boolean)
    ),
  ]
}

function postgresUrlError(
  variableName: string,
  detail: string
): never {
  throw new AuthRuntimeConfigurationError(
    `${variableName} ${detail}`
  )
}

function decodedUrlComponent(
  value: string,
  variableName: string
): string {
  if (INVALID_PERCENT_ESCAPE_PATTERN.test(value)) {
    return postgresUrlError(
      variableName,
      "must use unambiguous percent encoding"
    )
  }
  try {
    return decodeURIComponent(value)
  } catch {
    return postgresUrlError(
      variableName,
      "must use unambiguous percent encoding"
    )
  }
}

export function assertNoPostgresEnvironmentFallback(
  environment: Environment = process.env
): void {
  const overrideName = Object.keys(environment)
    .sort()
    .find((name) => {
      if (!POSTGRES_ENVIRONMENT_NAME_PATTERN.test(name)) {
        return false
      }
      const value = environment[name]
      return (
        value !== undefined &&
        value !== null &&
        value !== ""
      )
    })
  if (overrideName !== undefined) {
    throw new AuthRuntimeConfigurationError(
      `${overrideName} must be unset; PostgreSQL PG* environment fallback is forbidden`
    )
  }
}

function canonicalHost(parsed: URL): string {
  const hostname = parsed.hostname
  if (hostname.startsWith("[") && hostname.endsWith("]")) {
    return hostname.slice(1, -1).toLowerCase()
  }
  return hostname.toLowerCase().replace(/\.$/u, "")
}

export function parseAuthPostgresPoolConfig(
  value: string,
  variableName: string,
  options: DirectPostgresUrlOptions = {}
): AuthPostgresPoolConfig {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    CONTROL_CHARACTER_PATTERN.test(value) ||
    WHITESPACE_PATTERN.test(value)
  ) {
    return postgresUrlError(
      variableName,
      "must be a valid PostgreSQL URL"
    )
  }
  if (value.includes("#")) {
    return postgresUrlError(
      variableName,
      "must not contain a fragment"
    )
  }

  const schemeSeparator = value.indexOf("://")
  const authorityStart = schemeSeparator + 3
  const pathStart = value.indexOf("/", authorityStart)
  const queryStart = value.indexOf("?", authorityStart)
  if (
    schemeSeparator <= 0 ||
    pathStart < authorityStart ||
    queryStart <= pathStart
  ) {
    return postgresUrlError(
      variableName,
      "must include one database and the secure query contract"
    )
  }

  const rawDatabase = value.slice(pathStart + 1, queryStart)
  const rawQuery = value.slice(queryStart + 1)
  const rawAuthority = value.slice(authorityStart, pathStart)
  const userInfoEnd = rawAuthority.lastIndexOf("@")
  const rawHostAndPort = rawAuthority.slice(userInfoEnd + 1)
  let rawHost = rawHostAndPort
  let rawPort: string | null = null
  if (rawHostAndPort.startsWith("[")) {
    const bracketEnd = rawHostAndPort.indexOf("]")
    if (bracketEnd < 0) {
      return postgresUrlError(
        variableName,
        "must include a canonical host"
      )
    }
    rawHost = rawHostAndPort.slice(0, bracketEnd + 1)
    const suffix = rawHostAndPort.slice(bracketEnd + 1)
    if (suffix !== "") {
      if (!suffix.startsWith(":")) {
        return postgresUrlError(
          variableName,
          "must include a canonical host and port"
        )
      }
      rawPort = suffix.slice(1)
    }
  } else {
    const portSeparator = rawHostAndPort.lastIndexOf(":")
    if (portSeparator >= 0) {
      rawHost = rawHostAndPort.slice(0, portSeparator)
      rawPort = rawHostAndPort.slice(portSeparator + 1)
    }
  }
  if (
    userInfoEnd <= 0 ||
    rawHost.length === 0 ||
    rawHost.includes("%") ||
    /[^\u0000-\u007f]/u.test(rawHost) ||
    rawDatabase.length === 0 ||
    rawDatabase.includes("/") ||
    rawDatabase.includes("\\") ||
    INVALID_PERCENT_ESCAPE_PATTERN.test(rawDatabase) ||
    (
      rawPort !== null &&
      (
        !/^[1-9][0-9]{0,4}$/u.test(rawPort) ||
        Number(rawPort) > 65_535 ||
        String(Number(rawPort)) !== rawPort
      )
    )
  ) {
    return postgresUrlError(
      variableName,
      "must use fixed credentials, one canonical host, and one database"
    )
  }

  let parsed: URL
  try {
    parsed = new URL(value)
  } catch {
    return postgresUrlError(
      variableName,
      "must be a valid PostgreSQL URL"
    )
  }
  if (!["postgres:", "postgresql:"].includes(parsed.protocol)) {
    return postgresUrlError(
      variableName,
      "must use postgres:// or postgresql://"
    )
  }

  const loopback =
    parsed.hostname === "localhost" ||
    parsed.hostname === "127.0.0.1" ||
    parsed.hostname === "[::1]"
  const canonicalLoopback =
    loopback &&
    (
      rawHost === "localhost" ||
      rawHost === "127.0.0.1" ||
      rawHost === "[::1]"
    )
  const productionTls = rawQuery === "sslmode=require"
  const loopbackTest =
    options.allowInsecureLoopback === true &&
    canonicalLoopback &&
    rawQuery === "sslmode=disable"
  if (!productionTls && !loopbackTest) {
    return postgresUrlError(
      variableName,
      "must use exactly sslmode=require; sslmode=disable is available only to the explicit loopback test path"
    )
  }

  const username = decodedUrlComponent(parsed.username, variableName)
  const password = decodedUrlComponent(parsed.password, variableName)
  const database = decodedUrlComponent(rawDatabase, variableName)
  const host = canonicalHost(parsed)
  const port = rawPort === null ? 5432 : Number(rawPort)
  const hostLabels = host.replace(/\.$/u, "").split(".")
  const canonicalDnsHost =
    host.includes(":") ||
    hostLabels.every((label) =>
      /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/u.test(label)
    )
  if (
    host.length === 0 ||
    !canonicalDnsHost ||
    username.length === 0 ||
    password.length === 0 ||
    database.length === 0 ||
    CONTROL_CHARACTER_PATTERN.test(username) ||
    CONTROL_CHARACTER_PATTERN.test(password) ||
    CONTROL_CHARACTER_PATTERN.test(database) ||
    WHITESPACE_PATTERN.test(username) ||
    WHITESPACE_PATTERN.test(password) ||
    WHITESPACE_PATTERN.test(database) ||
    !Number.isInteger(port) ||
    port < 1 ||
    port > 65_535 ||
    (!loopback && port !== 5432) ||
    Buffer.byteLength(database, "utf8") > 63 ||
    [".", ".."].includes(database) ||
    database.includes("/") ||
    database.includes("\\") ||
    RESERVED_DATABASE_CHARACTER_PATTERN.test(database)
  ) {
    return postgresUrlError(
      variableName,
      "must include fixed credentials, host, valid port, and one database"
    )
  }
  if (host.includes("-pooler.")) {
    return postgresUrlError(
      variableName,
      "must use a direct Neon endpoint, not -pooler"
    )
  }

  const maintenance = options.maintenance === true
  const applicationName = maintenance
    ? ("syshin0116-auth-maintenance" as const)
    : ("syshin0116-auth-runtime" as const)
  const config = {
    user: username,
    password,
    host,
    port,
    database,
    ssl: productionTls
      ? Object.freeze({ rejectUnauthorized: true as const })
      : false,
    options: AUTH_POSTGRES_SEARCH_PATH_OPTIONS,
    statement_timeout: maintenance
      ? MAINTENANCE_STATEMENT_TIMEOUT_MS
      : RUNTIME_STATEMENT_TIMEOUT_MS,
    query_timeout: maintenance
      ? MAINTENANCE_QUERY_TIMEOUT_MS
      : RUNTIME_QUERY_TIMEOUT_MS,
    lock_timeout: maintenance
      ? MAINTENANCE_LOCK_TIMEOUT_MS
      : RUNTIME_LOCK_TIMEOUT_MS,
    idle_in_transaction_session_timeout: maintenance
      ? MAINTENANCE_STATEMENT_TIMEOUT_MS
      : RUNTIME_STATEMENT_TIMEOUT_MS,
    application_name: applicationName,
    max: 1,
    connectionTimeoutMillis: 5_000,
    idleTimeoutMillis: 5_000,
  } as const satisfies NeonPoolConfig & PgPoolConfig
  return config
}

export function readAuthRuntimeConfig(
  environment: Environment = process.env,
  nodeEnv =
    typeof environment.NODE_ENV === "string"
      ? environment.NODE_ENV
      : process.env.NODE_ENV
): AuthRuntimeConfig {
  assertNoPostgresEnvironmentFallback(environment)
  const database = parseAuthPostgresPoolConfig(
    configuredString(environment, "DATABASE_URL"),
    "DATABASE_URL"
  )
  const authSecret = configuredString(environment, "AUTH_SECRET")
  if (Buffer.byteLength(authSecret, "utf8") < MINIMUM_AUTH_SECRET_BYTES) {
    throw new AuthRuntimeConfigurationError(
      `AUTH_SECRET must be at least ${MINIMUM_AUTH_SECRET_BYTES} bytes`
    )
  }

  const allowedEmails = parseAuthEmailList(
    environment.AUTH_ALLOWED_EMAILS
  )
  if (nodeEnv === "production" && allowedEmails.length === 0) {
    throw new AuthRuntimeConfigurationError(
      "AUTH_ALLOWED_EMAILS must contain at least one email in production"
    )
  }

  return {
    database,
    authSecret,
    githubId: configuredString(environment, "AUTH_GITHUB_ID"),
    githubSecret: configuredString(environment, "AUTH_GITHUB_SECRET"),
    googleId: configuredString(environment, "AUTH_GOOGLE_ID"),
    googleSecret: configuredString(environment, "AUTH_GOOGLE_SECRET"),
    allowedEmails,
  }
}

function configuredAuthMigration(
  environment: Environment = process.env,
  allowInsecureLoopback = false
): AuthPostgresPoolConfig {
  assertNoPostgresEnvironmentFallback(environment)
  const value = environment.AUTH_DATABASE_MIGRATION_URL
  if (typeof value !== "string" || value.trim() === "") {
    throw new AuthRuntimeConfigurationError(
      "AUTH_DATABASE_MIGRATION_URL is required; DATABASE_URL is intentionally not a fallback"
    )
  }
  if (value !== value.trim()) {
    throw new AuthRuntimeConfigurationError(
      "AUTH_DATABASE_MIGRATION_URL must not contain surrounding whitespace"
    )
  }
  return parseAuthPostgresPoolConfig(
    value,
    "AUTH_DATABASE_MIGRATION_URL",
    {
      allowInsecureLoopback,
      maintenance: true,
    }
  )
}

export function readAuthMigrationConfig(
  environment: Environment = process.env
): AuthPostgresPoolConfig {
  return configuredAuthMigration(environment)
}

export function readAuthMigrationCliConfig(
  environment: Environment = process.env,
  arguments_: readonly string[] = process.argv.slice(2)
): AuthPostgresPoolConfig {
  if (arguments_.length === 0) {
    return readAuthMigrationConfig(environment)
  }
  if (
    arguments_.length !== 1 ||
    arguments_[0] !== AUTH_INSECURE_LOOPBACK_TEST_ARGUMENT
  ) {
    throw new AuthRuntimeConfigurationError(
      "Auth migration command arguments are invalid"
    )
  }
  const migrationUrl = environment.AUTH_DATABASE_MIGRATION_URL
  const testUrl = environment.AUTH_POSTGRES_TEST_URL
  if (
    typeof migrationUrl !== "string" ||
    typeof testUrl !== "string" ||
    migrationUrl !== testUrl
  ) {
    throw new AuthRuntimeConfigurationError(
      "Auth insecure loopback mode requires the exact PostgreSQL integration-test URL"
    )
  }
  return configuredAuthMigration(environment, true)
}

export function isAuthRuntimeConfigurationError(
  error: unknown
): error is AuthRuntimeConfigurationError {
  return error instanceof AuthRuntimeConfigurationError
}
