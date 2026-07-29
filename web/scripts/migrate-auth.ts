import { readFile } from "node:fs/promises"
import { resolve } from "node:path"
import { Pool, type PoolClient } from "pg"
import { readAuthMigrationCliConfig } from "../lib/auth-config"
import {
  lockAuthSchemaForMigration,
  verifyAuthSchema,
} from "../lib/auth-schema"

const MIGRATION_FILE = resolve(
  import.meta.dir,
  "../db/auth/0001_authjs.sql"
)
const HELP = `Usage: bun run auth:migrate [--allow-insecure-loopback-test]

Production must use the no-argument command and sslmode=require.
The loopback option is CI-test-only and also requires
AUTH_POSTGRES_TEST_URL to equal AUTH_DATABASE_MIGRATION_URL exactly.`

export async function applyAuthMigration(
  client: PoolClient,
  migrationFile = MIGRATION_FILE
): Promise<void> {
  const sql = await readFile(migrationFile, "utf8")
  await client.query(
    "BEGIN ISOLATION LEVEL READ COMMITTED READ WRITE NOT DEFERRABLE"
  )
  try {
    await client.query(
      "SET LOCAL search_path = pg_catalog, public"
    )
    await client.query("SET LOCAL lock_timeout = '5s'")
    await client.query("SET LOCAL statement_timeout = '60s'")
    await client.query(
      "SET LOCAL idle_in_transaction_session_timeout = '60s'"
    )
    await lockAuthSchemaForMigration(client)
    await client.query(sql)
    await verifyAuthSchema(client)
    await client.query("COMMIT")
  } catch (error) {
    try {
      await client.query("ROLLBACK")
    } catch (rollbackError) {
      throw new AggregateError(
        [error, rollbackError],
        "Auth.js schema migration rollback failed"
      )
    }
    throw error
  }
}

async function main(): Promise<void> {
  if (
    process.argv.length === 3 &&
    process.argv[2] === "--help"
  ) {
    console.log(HELP)
    return
  }
  const pool = new Pool({
    ...readAuthMigrationCliConfig(),
  })
  try {
    const client = await pool.connect()
    try {
      await applyAuthMigration(client)
    } finally {
      client.release()
    }
    console.log("Auth.js schema migration and verification passed")
  } finally {
    await pool.end()
  }
}

if (import.meta.main) {
  try {
    await main()
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "unknown migration failure"
    console.error(`Auth.js schema migration failed: ${message}`)
    process.exitCode = 1
  }
}
