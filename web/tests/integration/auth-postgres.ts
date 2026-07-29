import assert from "node:assert/strict"
import { randomUUID } from "node:crypto"
import PostgresAdapter from "@auth/pg-adapter"
import { Pool, type PoolClient } from "pg"
import {
  type AuthPostgresPoolConfig,
  parseAuthPostgresPoolConfig,
} from "../../lib/auth-config"
import {
  AuthSchemaVerificationError,
  inspectAuthSchema,
  verifyAuthSchema,
  verifyAuthSchemaSnapshot,
} from "../../lib/auth-schema"
import { applyAuthMigration } from "../../scripts/migrate-auth"

const TEST_DATABASE_PREFIX = "auth_contract_"

function testBasePoolConfig(
  value = process.env.AUTH_POSTGRES_TEST_URL
): AuthPostgresPoolConfig {
  assert.ok(
    value,
    "AUTH_POSTGRES_TEST_URL is required for the PostgreSQL integration suite"
  )
  const config = parseAuthPostgresPoolConfig(
    value,
    "AUTH_POSTGRES_TEST_URL",
    { allowInsecureLoopback: true, maintenance: true }
  )
  assert.ok(
    ["localhost", "127.0.0.1", "::1"].includes(config.host),
    "AUTH_POSTGRES_TEST_URL must target a loopback PostgreSQL server"
  )
  assert.equal(config.ssl, false)
  return config
}

function databaseName(label: string): string {
  const suffix = randomUUID().replaceAll("-", "").slice(0, 12)
  const name = `${TEST_DATABASE_PREFIX}${label}_${suffix}`.toLowerCase()
  assert.match(name, /^[a-z0-9_]+$/u)
  assert.ok(name.length <= 63)
  return name
}

async function withTestDatabase(
  label: string,
  run: (client: PoolClient, pool: Pool) => Promise<void>
): Promise<void> {
  const baseConfig = testBasePoolConfig()
  const name = databaseName(label)
  const adminPool = new Pool({
    ...baseConfig,
  })
  assert.equal(Object.hasOwn(adminPool.options, "connectionString"), false)
  assert.ok(name.startsWith(TEST_DATABASE_PREFIX))
  await adminPool.query(`CREATE DATABASE "${name}"`)

  const pool = new Pool({
    ...baseConfig,
    database: name,
    options: "-c search_path=public,pg_catalog",
    max: 3,
  })
  assert.equal(pool.options.host, baseConfig.host)
  assert.equal(pool.options.port, baseConfig.port)
  assert.equal(pool.options.database, name)
  assert.equal(Object.hasOwn(pool.options, "connectionString"), false)
  try {
    const client = await pool.connect()
    try {
      await run(client, pool)
    } finally {
      client.release()
    }
  } finally {
    await pool.end()
    assert.ok(name.startsWith(TEST_DATABASE_PREFIX))
    await adminPool.query(`DROP DATABASE "${name}" WITH (FORCE)`)
    await adminPool.end()
  }
}

const LEGACY_SCHEMA = `
  CREATE TABLE users (
    id text PRIMARY KEY DEFAULT gen_random_uuid(),
    name text,
    email text UNIQUE,
    "emailVerified" timestamp with time zone,
    image text
  );
  CREATE TABLE accounts (
    id text PRIMARY KEY DEFAULT gen_random_uuid(),
    "userId" text NOT NULL,
    type text NOT NULL,
    provider text NOT NULL,
    "providerAccountId" text NOT NULL,
    refresh_token text,
    access_token text,
    expires_at integer,
    token_type text,
    scope text,
    id_token text,
    session_state text
  );
  CREATE TABLE sessions (
    id text PRIMARY KEY DEFAULT gen_random_uuid(),
    "userId" text NOT NULL,
    expires timestamp with time zone NOT NULL,
    "sessionToken" text NOT NULL UNIQUE
  );
  CREATE TABLE verification_tokens (
    identifier text NOT NULL,
    expires timestamp with time zone NOT NULL,
    token text NOT NULL,
    PRIMARY KEY (identifier, token)
  );
`

async function seedLegacyRows(client: PoolClient) {
  const userId = "11111111-1111-4111-8111-111111111111"
  const accountId = "22222222-2222-4222-8222-222222222222"
  const sessionId = "33333333-3333-4333-8333-333333333333"
  await client.query(
    `
      INSERT INTO users (id, name, email)
      VALUES ($1, 'Legacy Owner', 'legacy@example.com')
    `,
    [userId]
  )
  await client.query(
    `
      INSERT INTO accounts (
        id, "userId", type, provider, "providerAccountId", expires_at
      ) VALUES (
        $1,
        $2,
        'oauth',
        'github',
        'legacy-provider-id',
        1900000000
      )
    `,
    [accountId, userId]
  )
  await client.query(
    `
      INSERT INTO sessions (
        id, "userId", expires, "sessionToken"
      ) VALUES ($1, $2, now() + interval '1 day', 'legacy-session')
    `,
    [sessionId, userId]
  )
  await client.query(
    `
      INSERT INTO verification_tokens (identifier, expires, token)
      VALUES ('legacy@example.com', now() + interval '1 day', 'legacy-token')
    `
  )
  return { userId, accountId, sessionId }
}

async function migrationAndAdapterLifecycle(): Promise<void> {
  await withTestDatabase("lifecycle", async (client, pool) => {
    await client.query(LEGACY_SCHEMA)
    const legacy = await seedLegacyRows(client)

    await applyAuthMigration(client)
    await applyAuthMigration(client)
    await verifyAuthSchema(client)

    const preserved = await client.query<{
      user_id: string
      account_id: string
      session_id: string
      verification_token: string
      expires_at: string
      expires_type: string
    }>(
      `
        SELECT
          users.id AS user_id,
          accounts.id AS account_id,
          sessions.id AS session_id,
          verification_token.token AS verification_token,
          accounts.expires_at,
          pg_typeof(accounts.expires_at)::text AS expires_type
        FROM users
        JOIN accounts ON accounts."userId" = users.id
        JOIN sessions ON sessions."userId" = users.id
        CROSS JOIN verification_token
        WHERE users.id = $1
      `,
      [legacy.userId]
    )
    assert.deepEqual(preserved.rows, [
      {
        user_id: legacy.userId,
        account_id: legacy.accountId,
        session_id: legacy.sessionId,
        verification_token: "legacy-token",
        expires_at: "1900000000",
        expires_type: "bigint",
      },
    ])
    assert.equal(
      (
        await client.query(
          "SELECT to_regclass('public.verification_tokens') AS relation"
        )
      ).rows[0].relation,
      null
    )

    const adapter = PostgresAdapter(pool)
    assert.ok(adapter.createUser)
    assert.ok(adapter.linkAccount)
    assert.ok(adapter.getUserByAccount)
    assert.ok(adapter.createSession)
    assert.ok(adapter.getSessionAndUser)
    assert.ok(adapter.createVerificationToken)
    assert.ok(adapter.useVerificationToken)

    const createdUser = await adapter.createUser({
      id: "adapter-supplied-id-is-not-persisted",
      name: "Adapter User",
      email: "adapter@example.com",
      emailVerified: null,
      image: null,
    })
    assert.equal(typeof createdUser.id, "string")
    assert.match(
      createdUser.id,
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u
    )

    const linkedAccount = await adapter.linkAccount({
      userId: createdUser.id,
      type: "oauth",
      provider: "github",
      providerAccountId: "adapter-provider-id",
      access_token: "access-token",
      expires_at: 1_900_000_000,
      refresh_token: "refresh-token",
      id_token: "id-token",
      scope: "read:user user:email",
      session_state: null,
      token_type: "bearer",
    })
    assert.ok(linkedAccount)
    assert.equal(linkedAccount.userId, createdUser.id)
    assert.equal(linkedAccount.expires_at, 1_900_000_000)

    const accountUser = await adapter.getUserByAccount({
      provider: "github",
      providerAccountId: "adapter-provider-id",
    })
    assert.equal(accountUser?.id, createdUser.id)

    const expires = new Date("2099-01-01T00:00:00.000Z")
    const createdSession = await adapter.createSession({
      sessionToken: "adapter-session-token",
      userId: createdUser.id,
      expires,
    })
    assert.equal(createdSession.userId, createdUser.id)
    assert.equal(
      typeof (createdSession as { id?: unknown }).id,
      "string"
    )

    const sessionAndUser = await adapter.getSessionAndUser(
      "adapter-session-token"
    )
    assert.equal(sessionAndUser?.user.id, createdUser.id)
    assert.equal(
      sessionAndUser?.session.sessionToken,
      "adapter-session-token"
    )

    await assert.rejects(
      async () => {
        await adapter.linkAccount!({
          userId: legacy.userId,
          type: "oauth",
          provider: "github",
          providerAccountId: "adapter-provider-id",
        })
      },
      (error: unknown) =>
        typeof error === "object" &&
        error !== null &&
        "code" in error &&
        error.code === "23505"
    )

    const verification = {
      identifier: "adapter@example.com",
      expires,
      token: "adapter-verification-token",
    }
    await adapter.createVerificationToken(verification)
    assert.deepEqual(
      await adapter.useVerificationToken({
        identifier: verification.identifier,
        token: verification.token,
      }),
      verification
    )
    assert.equal(
      await adapter.useVerificationToken({
        identifier: verification.identifier,
        token: verification.token,
      }),
      null
    )

    await client.query("DELETE FROM users WHERE id = $1", [createdUser.id])
    const cascaded = await client.query<{
      accounts: string
      sessions: string
    }>(
      `
        SELECT
          (SELECT count(*) FROM accounts WHERE "userId" = $1) AS accounts,
          (SELECT count(*) FROM sessions WHERE "userId" = $1) AS sessions
      `,
      [createdUser.id]
    )
    assert.deepEqual(cascaded.rows[0], {
      accounts: "0",
      sessions: "0",
    })

    await client.query("ALTER TABLE users ADD COLUMN unexpected text")
    const drift = await inspectAuthSchema(client)
    assert.ok(
      drift.includes(
        "public.users.unexpected is not part of the Auth.js contract"
      )
    )
    await assert.rejects(
      () => verifyAuthSchema(client),
      AuthSchemaVerificationError
    )
  })
}

async function conflictRollsBackWithoutCleanup(): Promise<void> {
  await withTestDatabase("conflict", async (client) => {
    await client.query(LEGACY_SCHEMA)
    const legacy = await seedLegacyRows(client)
    await client.query(
      `
        INSERT INTO accounts (
          id, "userId", type, provider, "providerAccountId"
        ) VALUES (
          '44444444-4444-4444-8444-444444444444',
          $1,
          'oauth',
          'github',
          'legacy-provider-id'
        )
      `,
      [legacy.userId]
    )

    await assert.rejects(
      () => applyAuthMigration(client),
      (error: unknown) =>
        typeof error === "object" &&
        error !== null &&
        "code" in error &&
        error.code === "23505"
    )

    const relations = await client.query<{
      plural: string | null
      singular: string | null
      account_count: string
      expires_type: string
    }>(
      `
        SELECT
          to_regclass('public.verification_tokens')::text AS plural,
          to_regclass('public.verification_token')::text AS singular,
          (SELECT count(*) FROM accounts) AS account_count,
          (
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'accounts'
              AND column_name = 'expires_at'
          ) AS expires_type
      `
    )
    assert.deepEqual(relations.rows[0], {
      plural: "verification_tokens",
      singular: null,
      account_count: "2",
      expires_type: "integer",
    })
  })
}

async function verifierDriftRollsBackMigration(): Promise<void> {
  await withTestDatabase("verifier_drift", async (client) => {
    await client.query(LEGACY_SCHEMA)
    await seedLegacyRows(client)
    await client.query("ALTER TABLE users ADD COLUMN unexpected text")

    await assert.rejects(
      () => applyAuthMigration(client),
      AuthSchemaVerificationError
    )

    const state = await client.query<{
      expires_type: string
      plural: string | null
      singular: string | null
      unexpected: string
    }>(
      `
        SELECT
          to_regclass('public.verification_tokens')::text AS plural,
          to_regclass('public.verification_token')::text AS singular,
          (
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'accounts'
              AND column_name = 'expires_at'
          ) AS expires_type,
          (
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'users'
              AND column_name = 'unexpected'
          ) AS unexpected
      `
    )
    assert.deepEqual(state.rows[0], {
      plural: "verification_tokens",
      singular: null,
      expires_type: "integer",
      unexpected: "text",
    })
  })
}

async function multipleForeignKeysRollBackMigration(): Promise<void> {
  await withTestDatabase("foreign_key_drift", async (client) => {
    await client.query(LEGACY_SCHEMA)
    const legacy = await seedLegacyRows(client)
    await client.query("CREATE TABLE alternate_users (id text PRIMARY KEY)")
    await client.query(
      "INSERT INTO alternate_users (id) VALUES ($1)",
      [legacy.userId]
    )
    await client.query(
      `
        ALTER TABLE accounts
          ADD CONSTRAINT accounts_user_id_exact
          FOREIGN KEY ("userId") REFERENCES users(id) ON DELETE CASCADE;
        ALTER TABLE accounts
          ADD CONSTRAINT accounts_user_id_conflicting
          FOREIGN KEY ("userId") REFERENCES alternate_users(id);
      `
    )

    await assert.rejects(
      () => applyAuthMigration(client),
      AuthSchemaVerificationError
    )

    const state = await client.query<{
      account_foreign_keys: string
      expires_type: string
      plural: string | null
      session_foreign_keys: string
      singular: string | null
    }>(
      `
        SELECT
          to_regclass('public.verification_tokens')::text AS plural,
          to_regclass('public.verification_token')::text AS singular,
          (
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'accounts'
              AND column_name = 'expires_at'
          ) AS expires_type,
          (
            SELECT count(*)
            FROM pg_constraint
            WHERE conrelid = 'public.accounts'::regclass
              AND contype = 'f'
          ) AS account_foreign_keys,
          (
            SELECT count(*)
            FROM pg_constraint
            WHERE conrelid = 'public.sessions'::regclass
              AND contype = 'f'
          ) AS session_foreign_keys
      `
    )
    assert.deepEqual(state.rows[0], {
      plural: "verification_tokens",
      singular: null,
      expires_type: "integer",
      account_foreign_keys: "2",
      session_foreign_keys: "0",
    })
  })
}

async function exactSchemaContractRegressions(): Promise<void> {
  await withTestDatabase("exact_contract", async (client) => {
    await applyAuthMigration(client)
    await verifyAuthSchemaSnapshot(client)

    const inventory = await client.query<{
      columns: string
      constraints: string
      indexes: string
      ri_triggers: string
    }>(`
      SELECT
        (SELECT count(*) FROM information_schema.columns
          WHERE table_schema = 'public'
            AND table_name IN ('accounts', 'sessions', 'users', 'verification_token'))::text AS columns,
        (SELECT count(*) FROM pg_constraint
          WHERE conrelid IN ('public.accounts'::regclass, 'public.sessions'::regclass,
                             'public.users'::regclass, 'public.verification_token'::regclass))::text AS constraints,
        (SELECT count(*) FROM pg_index
          WHERE indrelid IN ('public.accounts'::regclass, 'public.sessions'::regclass,
                             'public.users'::regclass, 'public.verification_token'::regclass))::text AS indexes,
        (SELECT count(*) FROM pg_trigger
          WHERE tgrelid IN ('public.accounts'::regclass, 'public.sessions'::regclass,
                            'public.users'::regclass)
            AND tgisinternal AND tgconstraint <> 0 AND tgenabled = 'O')::text AS ri_triggers
    `)
    assert.deepEqual(inventory.rows[0], {
      columns: "24",
      constraints: "9",
      indexes: "7",
      ri_triggers: "8",
    })

    await client.query(`
      ALTER TABLE public.sessions ALTER COLUMN expires
      TYPE timestamp(0) with time zone USING expires
    `)
    await assert.rejects(
      () => verifyAuthSchema(client),
      /datetime precision 0; expected 6/u
    )
    await client.query(`
      ALTER TABLE public.sessions ALTER COLUMN expires
      TYPE timestamp(6) with time zone USING expires
    `)

    await client.query(
      "CREATE INDEX auth_contract_extra_index ON public.users (name)"
    )
    await assert.rejects(() => verifyAuthSchema(client), /unexpected index/u)
    await client.query("DROP INDEX public.auth_contract_extra_index")

    await client.query("ALTER TABLE public.accounts DISABLE TRIGGER ALL")
    await assert.rejects(
      () => verifyAuthSchema(client),
      /internal referential-integrity trigger inventory is not exact/u
    )
    await client.query("ALTER TABLE public.accounts ENABLE TRIGGER ALL")

    await client.query("ALTER TABLE public.accounts DISABLE TRIGGER ALL")
    await client.query(`
      INSERT INTO public.accounts (
        id, "userId", type, provider, "providerAccountId"
      ) VALUES ('orphan-account', 'missing-user', 'oauth', 'github', 'orphan')
    `)
    await client.query("ALTER TABLE public.accounts ENABLE TRIGGER ALL")
    await assert.rejects(
      () => verifyAuthSchema(client),
      /does not reference public\.users\.id/u
    )
    await client.query("DELETE FROM public.accounts WHERE id = 'orphan-account'")

    await client.query(
      "CREATE TABLE public.auth_contract_child () INHERITS (public.users)"
    )
    await assert.rejects(() => verifyAuthSchema(client), /inheritance/u)
    await client.query("DROP TABLE public.auth_contract_child")

    await client.query(
      "CREATE TABLE public.verification_tokens (identifier text NOT NULL)"
    )
    await assert.rejects(
      () => verifyAuthSchema(client),
      /verification_tokens/u
    )
    await client.query("DROP TABLE public.verification_tokens")
    await verifyAuthSchema(client)
  })
}

async function maintenanceTransactionContract(): Promise<void> {
  await withTestDatabase("transaction_contract", async (client) => {
    await client.query(`
      SET SESSION CHARACTERISTICS AS TRANSACTION
        ISOLATION LEVEL SERIALIZABLE, READ ONLY, DEFERRABLE
    `)
    await applyAuthMigration(client)
    await client.query("RESET default_transaction_isolation")
    await client.query("RESET default_transaction_read_only")
    await client.query("RESET default_transaction_deferrable")
    await verifyAuthSchemaSnapshot(client)
  })
}

async function integrationConnectionHarnessSafety(): Promise<void> {
  const value = process.env.AUTH_POSTGRES_TEST_URL
  assert.ok(value)
  for (const hostileQuery of [
    "host=attacker.invalid",
    "port=1",
    "options=-c%20search_path%3Dattacker",
  ]) {
    assert.throws(
      () => testBasePoolConfig(`${value}&${hostileQuery}`),
      /AUTH_POSTGRES_TEST_URL/u
    )
  }
  const config = testBasePoolConfig()
  const pool = new Pool({ ...config })
  try {
    assert.equal(pool.options.host, config.host)
    assert.equal(pool.options.port, config.port)
    assert.equal(Object.hasOwn(pool.options, "connectionString"), false)
  } finally {
    await pool.end()
  }
}

await integrationConnectionHarnessSafety()
console.log("auth PostgreSQL: loopback-only typed harness passed")
await migrationAndAdapterLifecycle()
console.log("auth PostgreSQL: migration idempotency and adapter lifecycle passed")
await conflictRollsBackWithoutCleanup()
console.log("auth PostgreSQL: conflicting legacy data rolled back intact")
await verifierDriftRollsBackMigration()
console.log("auth PostgreSQL: verifier drift rolled the migration back intact")
await multipleForeignKeysRollBackMigration()
console.log("auth PostgreSQL: conflicting foreign keys rolled back intact")
await exactSchemaContractRegressions()
console.log("auth PostgreSQL: exact schema contract regressions passed")
await maintenanceTransactionContract()
console.log("auth PostgreSQL: explicit maintenance transaction contract passed")
