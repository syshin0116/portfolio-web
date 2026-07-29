import { Pool } from "pg"
import { readAuthMigrationCliConfig } from "../lib/auth-config"
import { verifyAuthSchemaSnapshot } from "../lib/auth-schema"

const HELP = `Usage: bun run auth:verify [--allow-insecure-loopback-test]

Production must use the no-argument command and sslmode=require.
The loopback option is CI-test-only and also requires
AUTH_POSTGRES_TEST_URL to equal AUTH_DATABASE_MIGRATION_URL exactly.`

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
      await verifyAuthSchemaSnapshot(client)
    } finally {
      client.release()
    }
    console.log("Auth.js schema verification passed")
  } finally {
    await pool.end()
  }
}

if (import.meta.main) {
  try {
    await main()
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "unknown verification failure"
    console.error(`Auth.js schema verification failed: ${message}`)
    process.exitCode = 1
  }
}
