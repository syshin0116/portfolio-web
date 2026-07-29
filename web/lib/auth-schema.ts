import type { Pool, PoolClient, QueryResultRow } from "pg"

const AUTH_TABLES = [
  "accounts",
  "sessions",
  "users",
  "verification_token",
] as const

interface AuthSchemaColumn {
  readonly table: (typeof AUTH_TABLES)[number]
  readonly name: string
  readonly dataType: string
  readonly udtName: string
  readonly nullable: boolean
  readonly defaultKind: "none" | "uuid-text"
  readonly datetimePrecision?: 6
}

export const AUTH_SCHEMA_COLUMNS: readonly AuthSchemaColumn[] = [
  {
    table: "accounts",
    name: "id",
    dataType: "text",
    udtName: "text",
    nullable: false,
    defaultKind: "uuid-text",
  },
  {
    table: "accounts",
    name: "userId",
    dataType: "text",
    udtName: "text",
    nullable: false,
    defaultKind: "none",
  },
  {
    table: "accounts",
    name: "type",
    dataType: "text",
    udtName: "text",
    nullable: false,
    defaultKind: "none",
  },
  {
    table: "accounts",
    name: "provider",
    dataType: "text",
    udtName: "text",
    nullable: false,
    defaultKind: "none",
  },
  {
    table: "accounts",
    name: "providerAccountId",
    dataType: "text",
    udtName: "text",
    nullable: false,
    defaultKind: "none",
  },
  ...[
    "refresh_token",
    "access_token",
    "token_type",
    "scope",
    "id_token",
    "session_state",
  ].map(
    (name): AuthSchemaColumn => ({
      table: "accounts",
      name,
      dataType: "text",
      udtName: "text",
      nullable: true,
      defaultKind: "none",
    })
  ),
  {
    table: "accounts",
    name: "expires_at",
    dataType: "bigint",
    udtName: "int8",
    nullable: true,
    defaultKind: "none",
  },
  {
    table: "sessions",
    name: "id",
    dataType: "text",
    udtName: "text",
    nullable: false,
    defaultKind: "uuid-text",
  },
  {
    table: "sessions",
    name: "userId",
    dataType: "text",
    udtName: "text",
    nullable: false,
    defaultKind: "none",
  },
  {
    table: "sessions",
    name: "expires",
    dataType: "timestamp with time zone",
    udtName: "timestamptz",
    nullable: false,
    defaultKind: "none",
    datetimePrecision: 6,
  },
  {
    table: "sessions",
    name: "sessionToken",
    dataType: "text",
    udtName: "text",
    nullable: false,
    defaultKind: "none",
  },
  {
    table: "users",
    name: "id",
    dataType: "text",
    udtName: "text",
    nullable: false,
    defaultKind: "uuid-text",
  },
  ...["name", "email", "image"].map(
    (name): AuthSchemaColumn => ({
      table: "users",
      name,
      dataType: "text",
      udtName: "text",
      nullable: true,
      defaultKind: "none",
    })
  ),
  {
    table: "users",
    name: "emailVerified",
    dataType: "timestamp with time zone",
    udtName: "timestamptz",
    nullable: true,
    defaultKind: "none",
    datetimePrecision: 6,
  },
  {
    table: "verification_token",
    name: "identifier",
    dataType: "text",
    udtName: "text",
    nullable: false,
    defaultKind: "none",
  },
  {
    table: "verification_token",
    name: "expires",
    dataType: "timestamp with time zone",
    udtName: "timestamptz",
    nullable: false,
    defaultKind: "none",
    datetimePrecision: 6,
  },
  {
    table: "verification_token",
    name: "token",
    dataType: "text",
    udtName: "text",
    nullable: false,
    defaultKind: "none",
  },
]

interface AuthSchemaReferentialIntegrityTrigger {
  readonly relationName: "accounts" | "sessions" | "users"
  readonly constraintName:
    | "accounts_user_id_fkey"
    | "sessions_user_id_fkey"
  readonly constraintTable: "accounts" | "sessions"
  readonly oppositeRelation: "accounts" | "sessions" | "users"
  readonly constraintIndex: "users_pkey"
  readonly functionName:
    | "RI_FKey_cascade_del"
    | "RI_FKey_check_ins"
    | "RI_FKey_check_upd"
    | "RI_FKey_noaction_upd"
  readonly triggerType: 5 | 9 | 17
}

export const AUTH_SCHEMA_REFERENTIAL_INTEGRITY_TRIGGERS:
  readonly AuthSchemaReferentialIntegrityTrigger[] = [
    {
      relationName: "accounts",
      constraintName: "accounts_user_id_fkey",
      constraintTable: "accounts",
      oppositeRelation: "users",
      constraintIndex: "users_pkey",
      functionName: "RI_FKey_check_ins",
      triggerType: 5,
    },
    {
      relationName: "accounts",
      constraintName: "accounts_user_id_fkey",
      constraintTable: "accounts",
      oppositeRelation: "users",
      constraintIndex: "users_pkey",
      functionName: "RI_FKey_check_upd",
      triggerType: 17,
    },
    {
      relationName: "users",
      constraintName: "accounts_user_id_fkey",
      constraintTable: "accounts",
      oppositeRelation: "accounts",
      constraintIndex: "users_pkey",
      functionName: "RI_FKey_cascade_del",
      triggerType: 9,
    },
    {
      relationName: "users",
      constraintName: "accounts_user_id_fkey",
      constraintTable: "accounts",
      oppositeRelation: "accounts",
      constraintIndex: "users_pkey",
      functionName: "RI_FKey_noaction_upd",
      triggerType: 17,
    },
    {
      relationName: "sessions",
      constraintName: "sessions_user_id_fkey",
      constraintTable: "sessions",
      oppositeRelation: "users",
      constraintIndex: "users_pkey",
      functionName: "RI_FKey_check_ins",
      triggerType: 5,
    },
    {
      relationName: "sessions",
      constraintName: "sessions_user_id_fkey",
      constraintTable: "sessions",
      oppositeRelation: "users",
      constraintIndex: "users_pkey",
      functionName: "RI_FKey_check_upd",
      triggerType: 17,
    },
    {
      relationName: "users",
      constraintName: "sessions_user_id_fkey",
      constraintTable: "sessions",
      oppositeRelation: "sessions",
      constraintIndex: "users_pkey",
      functionName: "RI_FKey_cascade_del",
      triggerType: 9,
    },
    {
      relationName: "users",
      constraintName: "sessions_user_id_fkey",
      constraintTable: "sessions",
      oppositeRelation: "sessions",
      constraintIndex: "users_pkey",
      functionName: "RI_FKey_noaction_upd",
      triggerType: 17,
    },
  ]

const AUTH_SCHEMA_REFERENTIAL_INTEGRITY_TRIGGER_JSON =
  JSON.stringify(
    AUTH_SCHEMA_REFERENTIAL_INTEGRITY_TRIGGERS.map((trigger) => ({
      relation_name: trigger.relationName,
      constraint_name: trigger.constraintName,
      constraint_table: trigger.constraintTable,
      opposite_relation: trigger.oppositeRelation,
      constraint_index: trigger.constraintIndex,
      function_name: trigger.functionName,
      trigger_type: trigger.triggerType,
    }))
  )

type Queryable = Pick<Pool | PoolClient, "query">
const AUTH_SCHEMA_ADVISORY_LOCK_NAME =
  "syshin0116.dev:authjs-schema:v1"

interface ColumnRow extends QueryResultRow {
  table_name: string
  column_name: string
  data_type: string
  udt_name: string
  is_nullable: "YES" | "NO"
  datetime_precision: number | null
  is_generated: "ALWAYS" | "NEVER"
  is_identity: "NO" | "YES"
  collation_name: string | null
  column_default: string | null
}

interface IndexRow extends QueryResultRow {
  table_name: string
  index_name: string
  columns: (string | null)[]
  opclasses: string[]
  opclass_access_methods: string[]
  collations_match: boolean
  collations_default: boolean
  option_bits: number[]
  access_method: string
  index_relation_kind: string
  index_persistence: string
  index_options: string[] | null
  backing_constraint_types: string[]
  backing_constraint_names: string[]
  unique: boolean
  primary: boolean
  exclusion: boolean
  immediate: boolean
  clustered: boolean
  valid: boolean
  check_xmin: boolean
  ready: boolean
  live: boolean
  replica_identity: boolean
  has_predicate: boolean
  has_expressions: boolean
  nulls_not_distinct: boolean
  key_attribute_count: number
  total_attribute_count: number
}

interface ConstraintRow extends QueryResultRow {
  constraint_name: string
  constraint_type: string
  constraint_schema: string
  local_schema: string
  local_table: string
  local_columns: string[]
  referenced_schema: string | null
  referenced_table: string | null
  referenced_columns: string[]
  delete_action: string
  update_action: string
  match_type: string
  validated: boolean
  enforced: boolean
  deferrable: boolean
  deferred: boolean
  local_only: boolean
  inheritance_count: number
  no_inherit: boolean
  parent_constraint_oid: number
  backing_index_name: string | null
  period: boolean
  equality_operators_exact: boolean
}

export class AuthSchemaVerificationError extends Error {
  readonly violations: readonly string[]

  constructor(violations: readonly string[]) {
    super(
      "Auth.js schema verification failed:\n" +
        violations.map((violation) => `- ${violation}`).join("\n")
    )
    this.name = "AuthSchemaVerificationError"
    this.violations = violations
  }
}

function sameColumns(actual: readonly string[], expected: readonly string[]) {
  return JSON.stringify(actual) === JSON.stringify(expected)
}

function isUuidTextDefault(value: string | null): boolean {
  if (value === null) return false
  const normalized = value.replace(/\s/gu, "")
  return [
    "gen_random_uuid()::text",
    "(gen_random_uuid())::text",
    "(gen_random_uuid()::text)",
  ].includes(normalized)
}

async function tableViolations(client: Queryable): Promise<string[]> {
  const relationResult = await client.query<{
    table_name: string
    relkind: string
    relpersistence: string
    relispartition: boolean
    table_access_method: string | null
    relrowsecurity: boolean
    relforcerowsecurity: boolean
  }>(
    `
      SELECT
        class.relname AS table_name,
        class.relkind,
        class.relpersistence,
        class.relispartition,
        access_method.amname AS table_access_method,
        class.relrowsecurity,
        class.relforcerowsecurity
      FROM pg_class AS class
      JOIN pg_namespace AS namespace
        ON namespace.oid = class.relnamespace
      LEFT JOIN pg_am AS access_method
        ON access_method.oid = class.relam
      WHERE namespace.nspname = 'public'
        AND class.relname = ANY($1::text[])
    `,
    [[...AUTH_TABLES, "verification_tokens"]]
  )
  const relations = new Map(
    relationResult.rows.map((row) => [row.table_name, row])
  )
  const violations: string[] = []
  for (const table of AUTH_TABLES) {
    const relation = relations.get(table)
    if (!relation) {
      violations.push(`public.${table} is missing or is not a table`)
      continue
    }
    if (
      relation.relkind !== "r" ||
      relation.relpersistence !== "p" ||
      relation.relispartition ||
      relation.table_access_method !== "heap"
    ) {
      violations.push(
        `public.${table} must be an ordinary permanent table`
      )
    }
    if (
      relation.relrowsecurity ||
      relation.relforcerowsecurity
    ) {
      violations.push(
        `public.${table} must not enable or force row-level security`
      )
    }
  }
  if (relations.has("verification_tokens")) {
    violations.push(
      "legacy public.verification_tokens still exists; only verification_token is allowed"
    )
  }
  const inheritanceResult = await client.query<{
    child_schema: string
    child_table: string
    parent_schema: string
    parent_table: string
  }>(
    `
      WITH auth_relations AS (
        SELECT class.oid
        FROM pg_class AS class
        JOIN pg_namespace AS namespace
          ON namespace.oid = class.relnamespace
        WHERE namespace.nspname = 'public'
          AND class.relname = ANY($1::text[])
      )
      SELECT
        child_namespace.nspname AS child_schema,
        child.relname AS child_table,
        parent_namespace.nspname AS parent_schema,
        parent.relname AS parent_table
      FROM pg_inherits AS inheritance
      JOIN pg_class AS child
        ON child.oid = inheritance.inhrelid
      JOIN pg_namespace AS child_namespace
        ON child_namespace.oid = child.relnamespace
      JOIN pg_class AS parent
        ON parent.oid = inheritance.inhparent
      JOIN pg_namespace AS parent_namespace
        ON parent_namespace.oid = parent.relnamespace
      WHERE inheritance.inhrelid IN (
        SELECT oid FROM auth_relations
      ) OR inheritance.inhparent IN (
        SELECT oid FROM auth_relations
      )
      ORDER BY
        child_namespace.nspname,
        child.relname,
        parent_namespace.nspname,
        parent.relname
    `,
    [[...AUTH_TABLES]]
  )
  for (const inheritance of inheritanceResult.rows) {
    violations.push(
      `${inheritance.child_schema}.${inheritance.child_table} inherits from ` +
        `${inheritance.parent_schema}.${inheritance.parent_table}; Auth.js tables must have no inheritance edges`
    )
  }
  return violations
}

async function columnViolations(client: Queryable): Promise<string[]> {
  const result = await client.query<ColumnRow>(
    `
      SELECT
        table_name,
        column_name,
        data_type,
        udt_name,
        is_nullable,
        datetime_precision,
        is_generated,
        is_identity,
        collation_name,
        column_default
      FROM information_schema.columns
      WHERE table_schema = 'public'
        AND table_name = ANY($1::text[])
      ORDER BY table_name, ordinal_position
    `,
    [[...AUTH_TABLES]]
  )
  const actualByKey = new Map(
    result.rows.map((column) => [
      `${column.table_name}.${column.column_name}`,
      column,
    ])
  )
  const expectedKeys = new Set(
    AUTH_SCHEMA_COLUMNS.map((column) => `${column.table}.${column.name}`)
  )
  const violations: string[] = []

  for (const expected of AUTH_SCHEMA_COLUMNS) {
    const key = `${expected.table}.${expected.name}`
    const actual = actualByKey.get(key)
    if (!actual) {
      violations.push(`public.${key} is missing`)
      continue
    }
    if (
      actual.data_type !== expected.dataType ||
      actual.udt_name !== expected.udtName
    ) {
      violations.push(
        `public.${key} has type ${actual.data_type}/${actual.udt_name}; ` +
          `expected ${expected.dataType}/${expected.udtName}`
      )
    }
    const nullable = actual.is_nullable === "YES"
    if (nullable !== expected.nullable) {
      violations.push(
        `public.${key} nullable=${nullable}; expected ${expected.nullable}`
      )
    }
    const expectedDatetimePrecision =
      expected.datetimePrecision ?? null
    if (
      actual.datetime_precision !== expectedDatetimePrecision
    ) {
      violations.push(
        `public.${key} has datetime precision ${String(
          actual.datetime_precision
        )}; expected ${String(expectedDatetimePrecision)}`
      )
    }
    if (
      expected.defaultKind === "none" &&
      actual.column_default !== null
    ) {
      violations.push(
        `public.${key} has an unexpected default expression`
      )
    }
    if (
      expected.defaultKind === "uuid-text" &&
      !isUuidTextDefault(actual.column_default)
    ) {
      violations.push(
        `public.${key} must default to gen_random_uuid()::text`
      )
    }
    if (
      actual.is_generated !== "NEVER" ||
      actual.is_identity !== "NO" ||
      actual.collation_name !== null
    ) {
      violations.push(
        `public.${key} must not be generated or an identity column and must use the default collation`
      )
    }
  }

  for (const actual of result.rows) {
    const key = `${actual.table_name}.${actual.column_name}`
    if (!expectedKeys.has(key)) {
      violations.push(`public.${key} is not part of the Auth.js contract`)
    }
  }
  return violations
}

async function indexRows(
  client: Queryable
): Promise<IndexRow[]> {
  const result = await client.query<IndexRow>(
    `
      SELECT
        class.relname AS table_name,
        index_class.relname AS index_name,
        ARRAY(
          SELECT attribute.attname::text
          FROM unnest(index_row.indkey)
            WITH ORDINALITY AS key(attnum, ordinality)
          LEFT JOIN pg_attribute AS attribute
            ON attribute.attrelid = index_row.indrelid
            AND attribute.attnum = key.attnum
          ORDER BY key.ordinality
        ) AS columns,
        ARRAY(
          SELECT
            opclass_namespace.nspname || '.' || opclass.opcname
          FROM unnest(index_row.indclass)
            WITH ORDINALITY AS key(opclass_oid, ordinality)
          JOIN pg_opclass AS opclass
            ON opclass.oid = key.opclass_oid
          JOIN pg_namespace AS opclass_namespace
            ON opclass_namespace.oid = opclass.opcnamespace
          ORDER BY key.ordinality
        ) AS opclasses,
        ARRAY(
          SELECT opclass_access_method.amname::text
          FROM unnest(index_row.indclass)
            WITH ORDINALITY AS key(opclass_oid, ordinality)
          JOIN pg_opclass AS opclass
            ON opclass.oid = key.opclass_oid
          JOIN pg_am AS opclass_access_method
            ON opclass_access_method.oid = opclass.opcmethod
          ORDER BY key.ordinality
        ) AS opclass_access_methods,
        NOT EXISTS (
          SELECT 1
          FROM unnest(index_row.indkey, index_row.indcollation)
            AS key(attnum, collation_oid)
          LEFT JOIN pg_attribute AS attribute
            ON attribute.attrelid = index_row.indrelid
            AND attribute.attnum = key.attnum
          WHERE key.attnum <= 0
            OR attribute.attcollation IS DISTINCT FROM key.collation_oid
        ) AS collations_match,
        NOT EXISTS (
          SELECT 1
          FROM unnest(index_row.indcollation)
            AS collation_key(collation_oid)
          WHERE collation_key.collation_oid IS DISTINCT FROM
            to_regcollation('pg_catalog.default')::oid
        ) AS collations_default,
        ARRAY(
          SELECT option_bit::integer
          FROM unnest(index_row.indoption)
            WITH ORDINALITY AS option_row(option_bit, ordinality)
          ORDER BY option_row.ordinality
        ) AS option_bits,
        access_method.amname AS access_method,
        index_class.relkind AS index_relation_kind,
        index_class.relpersistence AS index_persistence,
        index_class.reloptions AS index_options,
        ARRAY(
          SELECT constraint_row.contype::text
          FROM pg_constraint AS constraint_row
          WHERE constraint_row.conindid = index_row.indexrelid
            AND constraint_row.conrelid = index_row.indrelid
            AND constraint_row.contype IN ('p', 'u')
          ORDER BY constraint_row.oid
        ) AS backing_constraint_types,
        ARRAY(
          SELECT constraint_row.conname::text
          FROM pg_constraint AS constraint_row
          WHERE constraint_row.conindid = index_row.indexrelid
            AND constraint_row.conrelid = index_row.indrelid
            AND constraint_row.contype IN ('p', 'u')
          ORDER BY constraint_row.oid
        ) AS backing_constraint_names,
        index_row.indisunique AS unique,
        index_row.indisprimary AS primary,
        index_row.indisexclusion AS exclusion,
        index_row.indimmediate AS immediate,
        index_row.indisclustered AS clustered,
        index_row.indisvalid AS valid,
        index_row.indcheckxmin AS check_xmin,
        index_row.indisready AS ready,
        index_row.indislive AS live,
        index_row.indisreplident AS replica_identity,
        index_row.indpred IS NOT NULL AS has_predicate,
        index_row.indexprs IS NOT NULL AS has_expressions,
        index_row.indnullsnotdistinct AS nulls_not_distinct,
        index_row.indnkeyatts AS key_attribute_count,
        index_row.indnatts AS total_attribute_count
      FROM pg_index AS index_row
      JOIN pg_class AS class
        ON class.oid = index_row.indrelid
      JOIN pg_namespace AS namespace
        ON namespace.oid = class.relnamespace
      JOIN pg_class AS index_class
        ON index_class.oid = index_row.indexrelid
      JOIN pg_am AS access_method
        ON access_method.oid = index_class.relam
      WHERE namespace.nspname = 'public'
        AND class.relname = ANY($1::text[])
      ORDER BY class.relname, index_class.relname
    `,
    [[...AUTH_TABLES]]
  )
  return result.rows
}

async function constraintRows(
  client: Queryable
): Promise<ConstraintRow[]> {
  const result = await client.query<ConstraintRow>(
    `
      SELECT
        constraint_row.conname AS constraint_name,
        constraint_row.contype AS constraint_type,
        constraint_namespace.nspname AS constraint_schema,
        local_namespace.nspname AS local_schema,
        local_class.relname AS local_table,
        ARRAY(
          SELECT local_attribute.attname::text
          FROM unnest(constraint_row.conkey)
            WITH ORDINALITY AS local_key(attnum, ordinality)
          JOIN pg_attribute AS local_attribute
            ON local_attribute.attrelid = constraint_row.conrelid
            AND local_attribute.attnum = local_key.attnum
          ORDER BY local_key.ordinality
        ) AS local_columns,
        referenced_namespace.nspname AS referenced_schema,
        referenced_class.relname AS referenced_table,
        ARRAY(
          SELECT referenced_attribute.attname::text
          FROM unnest(constraint_row.confkey)
            WITH ORDINALITY AS referenced_key(attnum, ordinality)
          JOIN pg_attribute AS referenced_attribute
            ON referenced_attribute.attrelid = constraint_row.confrelid
            AND referenced_attribute.attnum = referenced_key.attnum
          ORDER BY referenced_key.ordinality
        ) AS referenced_columns,
        constraint_row.confdeltype AS delete_action,
        constraint_row.confupdtype AS update_action,
        constraint_row.confmatchtype AS match_type,
        constraint_row.convalidated AS validated,
        COALESCE(
          (
            to_jsonb(constraint_row) ->> 'conenforced'
          )::boolean,
          true
        ) AS enforced,
        constraint_row.condeferrable AS deferrable,
        constraint_row.condeferred AS deferred,
        constraint_row.conislocal AS local_only,
        constraint_row.coninhcount AS inheritance_count,
        constraint_row.connoinherit AS no_inherit,
        constraint_row.conparentid AS parent_constraint_oid,
        backing_index.relname AS backing_index_name,
        COALESCE(
          (
            to_jsonb(constraint_row) ->> 'conperiod'
          )::boolean,
          false
        ) AS period,
        CASE
          WHEN constraint_row.contype = 'f' THEN
            constraint_row.conpfeqop =
              ARRAY['pg_catalog.=(text,text)'::regoperator]::oid[]
            AND constraint_row.conppeqop =
              ARRAY['pg_catalog.=(text,text)'::regoperator]::oid[]
            AND constraint_row.conffeqop =
              ARRAY['pg_catalog.=(text,text)'::regoperator]::oid[]
          ELSE true
        END AS equality_operators_exact
      FROM pg_constraint AS constraint_row
      JOIN pg_class AS local_class
        ON local_class.oid = constraint_row.conrelid
      JOIN pg_namespace AS local_namespace
        ON local_namespace.oid = local_class.relnamespace
      JOIN pg_namespace AS constraint_namespace
        ON constraint_namespace.oid = constraint_row.connamespace
      LEFT JOIN pg_class AS referenced_class
        ON referenced_class.oid = constraint_row.confrelid
      LEFT JOIN pg_namespace AS referenced_namespace
        ON referenced_namespace.oid = referenced_class.relnamespace
      LEFT JOIN pg_class AS backing_index
        ON backing_index.oid = constraint_row.conindid
      WHERE (
        local_namespace.nspname = 'public'
        AND local_class.relname = ANY($1::text[])
      ) OR (
        referenced_namespace.nspname = 'public'
        AND referenced_class.relname = ANY($1::text[])
      )
      ORDER BY constraint_row.oid
    `,
    [[...AUTH_TABLES]]
  )
  return result.rows
}

async function constraintViolations(
  client: Queryable
): Promise<string[]> {
  const indexes = await indexRows(client)
  const constraintCatalog = await constraintRows(client)
  const constraints = constraintCatalog.filter(
    (constraint) => constraint.constraint_type !== "n"
  )
  const notNullConstraints = constraintCatalog.filter(
    (constraint) => constraint.constraint_type === "n"
  )
  const violations: string[] = []
  const expectedNotNullColumns = AUTH_SCHEMA_COLUMNS.filter(
    (column) => !column.nullable
  )
  const exactPostgres18NotNullConstraint = (
    constraint: ConstraintRow,
    expected: AuthSchemaColumn
  ) =>
    constraint.constraint_type === "n" &&
    constraint.constraint_schema === "public" &&
    constraint.local_schema === "public" &&
    constraint.local_table === expected.table &&
    sameColumns(constraint.local_columns, [expected.name]) &&
    constraint.referenced_schema === null &&
    constraint.referenced_table === null &&
    constraint.referenced_columns.length === 0 &&
    constraint.validated &&
    constraint.enforced &&
    !constraint.deferrable &&
    !constraint.deferred &&
    constraint.local_only &&
    constraint.inheritance_count === 0 &&
    !constraint.no_inherit &&
    constraint.parent_constraint_oid === 0 &&
    constraint.backing_index_name === null &&
    !constraint.period &&
    constraint.equality_operators_exact

  // PostgreSQL 17 keeps relation NOT NULL state outside pg_constraint.
  // PostgreSQL 18 exposes it as contype = 'n'. Once that surface is
  // present, require its complete exact inventory instead of treating
  // every 'n' row as harmless catalog noise.
  if (notNullConstraints.length > 0) {
    for (const expected of expectedNotNullColumns) {
      const matches = notNullConstraints.filter((constraint) =>
        exactPostgres18NotNullConstraint(constraint, expected)
      )
      if (matches.length !== 1) {
        violations.push(
          `public.${expected.table}.${expected.name} must have one exact PostgreSQL 18 NOT NULL constraint`
        )
      }
    }
    for (const constraint of notNullConstraints) {
      const allowed = expectedNotNullColumns.some((expected) =>
        exactPostgres18NotNullConstraint(constraint, expected)
      )
      if (!allowed) {
        violations.push(
          `${constraint.local_schema}.${constraint.local_table} has unexpected PostgreSQL 18 NOT NULL constraint ${constraint.constraint_name}`
        )
      }
    }
  }
  const requiredPrimaryKeys = new Map<string, readonly string[]>([
    ["users", ["id"]],
    ["accounts", ["id"]],
    ["sessions", ["id"]],
    ["verification_token", ["identifier", "token"]],
  ])
  for (const [table, columns] of requiredPrimaryKeys) {
    const matches = constraints.filter(
      (constraint) =>
        constraint.constraint_type === "p" &&
        constraint.constraint_schema === "public" &&
        constraint.local_schema === "public" &&
        constraint.local_table === table &&
        sameColumns(constraint.local_columns, columns) &&
        constraint.validated &&
        constraint.enforced &&
        !constraint.period &&
        !constraint.deferrable &&
        !constraint.deferred &&
        constraint.local_only &&
        constraint.inheritance_count === 0 &&
        constraint.no_inherit &&
        constraint.parent_constraint_oid === 0 &&
        constraint.constraint_name === `${table}_pkey` &&
        constraint.backing_index_name === `${table}_pkey`
    )
    if (matches.length !== 1) {
      violations.push(
        `public.${table} must have primary key (${columns.join(", ")})`
      )
    }
  }

  const requiredUniqueKeys = new Map<string, readonly string[][]>([
    ["users", [["email"]]],
    ["accounts", [["provider", "providerAccountId"]]],
    ["sessions", [["sessionToken"]]],
  ])
  const expectedIndexes = new Map<
    string,
    readonly {
      columns: readonly string[]
      constraintType: "p" | "u"
      name: string
    }[]
  >()
  for (const table of AUTH_TABLES) {
    expectedIndexes.set(table, [
      ...(requiredPrimaryKeys.has(table)
        ? [{
            columns: requiredPrimaryKeys.get(table) ?? [],
            constraintType: "p" as const,
            name: `${table}_pkey`,
          }]
        : []),
      ...(requiredUniqueKeys.get(table) ?? []).map((columns) => ({
        columns,
        constraintType: "u" as const,
        name:
          table === "users"
            ? "users_email_key"
            : table === "accounts"
              ? "accounts_provider_provider_account_id_key"
              : "sessions_session_token_key",
      })),
    ])
  }

  const isStructurallyExactIndex = (index: IndexRow) =>
    index.access_method === "btree" &&
    index.index_relation_kind === "i" &&
    index.index_persistence === "p" &&
    index.index_options === null &&
    index.unique &&
    !index.exclusion &&
    index.immediate &&
    !index.clustered &&
    index.valid &&
    !index.check_xmin &&
    index.ready &&
    index.live &&
    !index.replica_identity &&
    !index.has_predicate &&
    !index.has_expressions &&
    !index.nulls_not_distinct &&
    index.key_attribute_count === index.total_attribute_count &&
    index.columns.every((column) => column !== null) &&
    index.opclasses.every(
      (opclass) => opclass === "pg_catalog.text_ops"
    ) &&
    index.opclass_access_methods.every(
      (method) => method === "btree"
    ) &&
    index.collations_match &&
    index.collations_default &&
    index.option_bits.every((option) => option === 0) &&
    index.backing_constraint_types.length === 1

  for (const index of indexes) {
    const expected = expectedIndexes.get(index.table_name) ?? []
    const matchingExpected = expected.filter(
      ({ columns, constraintType, name }) =>
        sameColumns(index.columns as string[], columns) &&
        index.index_name === name &&
        index.primary === (constraintType === "p") &&
        index.backing_constraint_types[0] === constraintType &&
        index.backing_constraint_names[0] === name
    )
    if (
      !isStructurallyExactIndex(index) ||
      matchingExpected.length !== 1
    ) {
      violations.push(
        `public.${index.table_name} has unexpected index ${index.index_name}`
      )
    }
  }

  for (const [table, expected] of expectedIndexes) {
    for (const { columns, constraintType, name } of expected) {
      const matches = indexes.filter(
        (index) =>
          index.table_name === table &&
          isStructurallyExactIndex(index) &&
          index.index_name === name &&
          sameColumns(index.columns as string[], columns) &&
          index.primary === (constraintType === "p") &&
          index.backing_constraint_types[0] === constraintType &&
          index.backing_constraint_names[0] === name
      )
      if (matches.length !== 1) {
        violations.push(
          `public.${table} must have exactly one constraint-backed btree index (${columns.join(", ")})`
        )
      }
    }
  }

  const exactForeignKey = (
    constraint: ConstraintRow,
    table: string
  ) =>
    constraint.constraint_type === "f" &&
    constraint.constraint_schema === "public" &&
    constraint.local_schema === "public" &&
    constraint.local_table === table &&
    sameColumns(constraint.local_columns, ["userId"]) &&
    constraint.referenced_schema === "public" &&
    constraint.referenced_table === "users" &&
    sameColumns(constraint.referenced_columns, ["id"]) &&
    constraint.delete_action === "c" &&
    constraint.update_action === "a" &&
    constraint.match_type === "s" &&
    constraint.validated &&
    constraint.enforced &&
    !constraint.period &&
    !constraint.deferrable &&
    !constraint.deferred &&
    constraint.local_only &&
    constraint.inheritance_count === 0 &&
    constraint.no_inherit &&
    constraint.parent_constraint_oid === 0 &&
    constraint.constraint_name === `${table}_user_id_fkey` &&
    constraint.backing_index_name === "users_pkey" &&
    constraint.equality_operators_exact

  for (const table of ["accounts", "sessions"]) {
    if (
      constraints.filter((constraint) =>
        exactForeignKey(constraint, table)
      ).length !== 1
    ) {
      violations.push(
        `public.${table}(userId) must reference public.users(id) ` +
          "ON DELETE CASCADE with one validated foreign key"
      )
    }
  }

  for (const [table, keySets] of requiredUniqueKeys) {
    for (const columns of keySets) {
      const matches = constraints.filter(
        (constraint) =>
          constraint.constraint_type === "u" &&
          constraint.constraint_schema === "public" &&
          constraint.local_schema === "public" &&
          constraint.local_table === table &&
          sameColumns(constraint.local_columns, columns) &&
          constraint.validated &&
          constraint.enforced &&
          !constraint.period &&
          !constraint.deferrable &&
          !constraint.deferred &&
          constraint.local_only &&
          constraint.inheritance_count === 0 &&
          constraint.no_inherit &&
          constraint.parent_constraint_oid === 0 &&
          constraint.constraint_name ===
            (
              table === "users"
                ? "users_email_key"
                : table === "accounts"
                  ? "accounts_provider_provider_account_id_key"
                  : "sessions_session_token_key"
            ) &&
          constraint.backing_index_name === constraint.constraint_name
      )
      if (matches.length !== 1) {
        violations.push(
          `public.${table} must have one nondeferrable unique constraint (${columns.join(", ")})`
        )
      }
    }
  }

  const allowedUniqueConstraints = new Map<
    string,
    readonly (readonly string[])[]
  >([...requiredUniqueKeys])
  for (const constraint of constraints) {
    const allowedPrimary =
      constraint.constraint_type === "p" &&
      constraint.constraint_schema === "public" &&
      constraint.local_schema === "public" &&
      requiredPrimaryKeys.has(constraint.local_table) &&
      sameColumns(
        constraint.local_columns,
        requiredPrimaryKeys.get(constraint.local_table) ?? []
      ) &&
      constraint.validated &&
      constraint.enforced &&
      !constraint.period &&
      !constraint.deferrable &&
      !constraint.deferred &&
      constraint.local_only &&
      constraint.inheritance_count === 0 &&
      constraint.no_inherit &&
      constraint.parent_constraint_oid === 0 &&
      constraint.constraint_name ===
        `${constraint.local_table}_pkey` &&
      constraint.backing_index_name === constraint.constraint_name
    const allowedUnique =
      constraint.constraint_type === "u" &&
      constraint.constraint_schema === "public" &&
      constraint.local_schema === "public" &&
      (
        allowedUniqueConstraints.get(constraint.local_table) ?? []
      ).some((columns) =>
        sameColumns(constraint.local_columns, columns)
      ) &&
      constraint.validated &&
      constraint.enforced &&
      !constraint.period &&
      !constraint.deferrable &&
      !constraint.deferred &&
      constraint.local_only &&
      constraint.inheritance_count === 0 &&
      constraint.no_inherit &&
      constraint.parent_constraint_oid === 0 &&
      constraint.backing_index_name === constraint.constraint_name &&
      constraint.constraint_name ===
        (
          constraint.local_table === "users"
            ? "users_email_key"
            : constraint.local_table === "accounts"
              ? "accounts_provider_provider_account_id_key"
              : "sessions_session_token_key"
        )
    const allowedForeignKey = ["accounts", "sessions"].some(
      (table) => exactForeignKey(constraint, table)
    )
    if (!allowedPrimary && !allowedUnique && !allowedForeignKey) {
      const kind =
        constraint.constraint_type === "f"
          ? "foreign key"
          : "constraint"
      violations.push(
        `${constraint.local_schema}.${constraint.local_table} has unexpected ${kind} ${constraint.constraint_name}`
      )
    }
  }
  return violations
}

async function referentialIntegrityTriggerViolations(
  client: Queryable
): Promise<string[]> {
  const result = await client.query<{ exact: boolean }>(
    `
      WITH required_triggers AS (
        SELECT *
        FROM jsonb_to_recordset($1::jsonb) AS required_trigger(
          relation_name text,
          constraint_name text,
          constraint_table text,
          opposite_relation text,
          constraint_index text,
          function_name text,
          trigger_type integer
        )
      ),
      actual_triggers AS (
        SELECT
          relation.relname AS relation_name,
          constraint_row.conname AS constraint_name,
          constraint_relation.relname AS constraint_table,
          opposite_relation.relname AS opposite_relation,
          trigger_index.relname AS constraint_index,
          trigger_function.proname AS function_name,
          trigger_row.tgtype::integer AS trigger_type,
          COALESCE(
            (
              relation_namespace.nspname = 'public'
              AND constraint_namespace.nspname = 'public'
              AND constraint_relation_namespace.nspname = 'public'
              AND constraint_referenced_namespace.nspname = 'public'
              AND constraint_referenced_relation.relname = 'users'
              AND constraint_row.contype = 'f'
              AND constraint_index_namespace.nspname = 'public'
              AND constraint_index.relname = 'users_pkey'
              AND trigger_index_namespace.nspname = 'public'
              AND trigger_index.oid = constraint_index.oid
              AND opposite_namespace.nspname = 'public'
              AND function_namespace.nspname = 'pg_catalog'
              AND trigger_function.prorettype =
                'pg_catalog.trigger'::regtype
              AND trigger_function.prokind = 'f'
              AND trigger_function.pronargs = 0
              AND function_language.lanname = 'internal'
              AND trigger_row.tgenabled = 'O'
              AND trigger_row.tgisinternal
              AND NOT trigger_row.tgdeferrable
              AND NOT trigger_row.tginitdeferred
              AND trigger_row.tgnargs = 0
              AND octet_length(trigger_row.tgargs) = 0
              AND trigger_row.tgattr::text = ''
              AND trigger_row.tgqual IS NULL
              AND trigger_row.tgoldtable IS NULL
              AND trigger_row.tgnewtable IS NULL
              AND trigger_row.tgparentid = 0
            ),
            false
          ) AS structurally_safe
        FROM pg_trigger AS trigger_row
        JOIN pg_class AS relation
          ON relation.oid = trigger_row.tgrelid
        JOIN pg_namespace AS relation_namespace
          ON relation_namespace.oid = relation.relnamespace
        LEFT JOIN pg_constraint AS constraint_row
          ON constraint_row.oid = trigger_row.tgconstraint
        LEFT JOIN pg_namespace AS constraint_namespace
          ON constraint_namespace.oid = constraint_row.connamespace
        LEFT JOIN pg_class AS constraint_relation
          ON constraint_relation.oid = constraint_row.conrelid
        LEFT JOIN pg_namespace AS constraint_relation_namespace
          ON constraint_relation_namespace.oid =
            constraint_relation.relnamespace
        LEFT JOIN pg_class AS constraint_referenced_relation
          ON constraint_referenced_relation.oid =
            constraint_row.confrelid
        LEFT JOIN pg_namespace AS constraint_referenced_namespace
          ON constraint_referenced_namespace.oid =
            constraint_referenced_relation.relnamespace
        LEFT JOIN pg_class AS constraint_index
          ON constraint_index.oid = constraint_row.conindid
        LEFT JOIN pg_namespace AS constraint_index_namespace
          ON constraint_index_namespace.oid =
            constraint_index.relnamespace
        LEFT JOIN pg_class AS opposite_relation
          ON opposite_relation.oid = trigger_row.tgconstrrelid
        LEFT JOIN pg_namespace AS opposite_namespace
          ON opposite_namespace.oid = opposite_relation.relnamespace
        LEFT JOIN pg_class AS trigger_index
          ON trigger_index.oid = trigger_row.tgconstrindid
        LEFT JOIN pg_namespace AS trigger_index_namespace
          ON trigger_index_namespace.oid =
            trigger_index.relnamespace
        LEFT JOIN pg_proc AS trigger_function
          ON trigger_function.oid = trigger_row.tgfoid
        LEFT JOIN pg_namespace AS function_namespace
          ON function_namespace.oid = trigger_function.pronamespace
        LEFT JOIN pg_language AS function_language
          ON function_language.oid = trigger_function.prolang
        WHERE relation_namespace.nspname = 'public'
          AND relation.relname = ANY($2::text[])
          AND trigger_row.tgisinternal
      )
      SELECT
        (SELECT count(*) FROM required_triggers) = 8
        AND (SELECT count(*) FROM actual_triggers) = 8
        AND NOT EXISTS (
          SELECT 1
          FROM actual_triggers AS actual
          WHERE actual.structurally_safe IS DISTINCT FROM true
            OR NOT EXISTS (
              SELECT 1
              FROM required_triggers AS required
              WHERE required.relation_name = actual.relation_name
                AND required.constraint_name =
                  actual.constraint_name
                AND required.constraint_table =
                  actual.constraint_table
                AND required.opposite_relation =
                  actual.opposite_relation
                AND required.constraint_index =
                  actual.constraint_index
                AND required.function_name =
                  actual.function_name
                AND required.trigger_type = actual.trigger_type
            )
        )
        AND NOT EXISTS (
          SELECT 1
          FROM required_triggers AS required
          WHERE (
            SELECT count(*)
            FROM actual_triggers AS actual
            WHERE actual.structurally_safe
              AND required.relation_name =
                actual.relation_name
              AND required.constraint_name =
                actual.constraint_name
              AND required.constraint_table =
                actual.constraint_table
              AND required.opposite_relation =
                actual.opposite_relation
              AND required.constraint_index =
                actual.constraint_index
              AND required.function_name =
                actual.function_name
              AND required.trigger_type =
                actual.trigger_type
          ) <> 1
        ) AS exact
    `,
    [
      AUTH_SCHEMA_REFERENTIAL_INTEGRITY_TRIGGER_JSON,
      [...AUTH_TABLES],
    ]
  )
  return result.rows[0]?.exact === true
    ? []
    : [
        "Auth.js internal referential-integrity trigger inventory is not exact",
      ]
}

async function orphanViolations(client: Queryable): Promise<string[]> {
  const prerequisites = await client.query<{ available: boolean }>(
    `
      SELECT
        (
          SELECT count(*)
          FROM pg_class AS relation
          JOIN pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
          WHERE namespace.nspname = 'public'
            AND relation.relname IN (
              'accounts',
              'sessions',
              'users'
            )
            AND relation.relkind = 'r'
        ) = 3
        AND (
          SELECT count(*)
          FROM information_schema.columns AS column_row
          WHERE column_row.table_schema = 'public'
            AND (
              (
                column_row.table_name = 'accounts'
                AND column_row.column_name = 'userId'
              ) OR (
                column_row.table_name = 'sessions'
                AND column_row.column_name = 'userId'
              ) OR (
                column_row.table_name = 'users'
                AND column_row.column_name = 'id'
              )
            )
        ) = 3 AS available
    `
  )
  if (prerequisites.rows[0]?.available !== true) return []

  const result = await client.query<{ table_name: string }>(`
    SELECT 'accounts'::text AS table_name
    WHERE EXISTS (
      SELECT 1
      FROM public.accounts AS account_row
      LEFT JOIN public.users AS user_row
        ON user_row.id = account_row."userId"
      WHERE user_row.id IS NULL
    )

    UNION ALL

    SELECT 'sessions'::text AS table_name
    WHERE EXISTS (
      SELECT 1
      FROM public.sessions AS session_row
      LEFT JOIN public.users AS user_row
        ON user_row.id = session_row."userId"
      WHERE user_row.id IS NULL
    )

    ORDER BY table_name
  `)
  return result.rows.map(
    (row) =>
      `public.${row.table_name} has rows whose userId does not reference public.users.id`
  )
}

async function writeSurfaceViolations(
  client: Queryable
): Promise<string[]> {
  const result = await client.query<{
    table_name: string
    object_kind: "policy" | "rule" | "trigger"
    object_name: string
  }>(
    `
      WITH auth_relations AS (
        SELECT class.oid, class.relname AS table_name
        FROM pg_class AS class
        JOIN pg_namespace AS namespace
          ON namespace.oid = class.relnamespace
        WHERE namespace.nspname = 'public'
          AND class.relname = ANY($1::text[])
      )
      SELECT
        auth_relations.table_name,
        'trigger'::text AS object_kind,
        trigger_row.tgname AS object_name
      FROM auth_relations
      JOIN pg_trigger AS trigger_row
        ON trigger_row.tgrelid = auth_relations.oid
      WHERE NOT trigger_row.tgisinternal

      UNION ALL

      SELECT
        auth_relations.table_name,
        'rule'::text AS object_kind,
        rewrite_row.rulename AS object_name
      FROM auth_relations
      JOIN pg_rewrite AS rewrite_row
        ON rewrite_row.ev_class = auth_relations.oid

      UNION ALL

      SELECT
        auth_relations.table_name,
        'policy'::text AS object_kind,
        policy_row.polname AS object_name
      FROM auth_relations
      JOIN pg_policy AS policy_row
        ON policy_row.polrelid = auth_relations.oid

      ORDER BY table_name, object_kind, object_name
    `,
    [[...AUTH_TABLES]]
  )
  return result.rows.map((row) => {
    if (row.object_kind === "trigger") {
      return (
        `public.${row.table_name} has non-internal trigger ` +
        row.object_name
      )
    }
    if (row.object_kind === "rule") {
      return (
        `public.${row.table_name} has unexpected rewrite rule ` +
        row.object_name
      )
    }
    return (
      `public.${row.table_name} has unexpected RLS policy ` +
      row.object_name
    )
  })
}

export async function inspectAuthSchema(
  client: Queryable
): Promise<readonly string[]> {
  const violations = [
    ...(await tableViolations(client)),
    ...(await columnViolations(client)),
    ...(await constraintViolations(client)),
    ...(await referentialIntegrityTriggerViolations(client)),
    ...(await orphanViolations(client)),
    ...(await writeSurfaceViolations(client)),
  ]
  return violations.sort()
}

export async function verifyAuthSchema(
  client: Queryable
): Promise<void> {
  const violations = await inspectAuthSchema(client)
  if (violations.length > 0) {
    throw new AuthSchemaVerificationError(violations)
  }
}

export async function verifyAuthSchemaSnapshot(
  client: PoolClient
): Promise<void> {
  let sessionLockHeld = false
  let transactionOpen = false
  let primaryError: unknown
  try {
    await client.query(
      `
        SELECT pg_catalog.pg_advisory_lock(
          pg_catalog.hashtextextended($1, 0)
        )
      `,
      [AUTH_SCHEMA_ADVISORY_LOCK_NAME]
    )
    sessionLockHeld = true
    await client.query(
      "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY NOT DEFERRABLE"
    )
    transactionOpen = true
    await client.query(
      "SET LOCAL search_path = pg_catalog, public"
    )
    await client.query("SET LOCAL lock_timeout = '5s'")
    await client.query("SET LOCAL statement_timeout = '15s'")
    await client.query(
      "SET LOCAL idle_in_transaction_session_timeout = '15s'"
    )
    await client.query(
      `
        LOCK TABLE
          public.users,
          public.accounts,
          public.sessions,
          public.verification_token
        IN ACCESS SHARE MODE
      `
    )
    await verifyAuthSchema(client)
    await client.query("COMMIT")
    transactionOpen = false
  } catch (error) {
    primaryError = error
    if (transactionOpen) {
      try {
        await client.query("ROLLBACK")
        transactionOpen = false
      } catch (rollbackError) {
        primaryError = new AggregateError(
          [error, rollbackError],
          "Auth.js schema verification rollback failed"
        )
      }
    }
  } finally {
    if (sessionLockHeld) {
      try {
        await client.query(
          `
            SELECT pg_catalog.pg_advisory_unlock(
              pg_catalog.hashtextextended($1, 0)
            )
          `,
          [AUTH_SCHEMA_ADVISORY_LOCK_NAME]
        )
      } catch (unlockError) {
        if (primaryError !== undefined) {
          primaryError = new AggregateError(
            [primaryError, unlockError],
            "Auth.js schema verification cleanup failed"
          )
        } else {
          primaryError = unlockError
        }
      }
    }
  }
  if (primaryError !== undefined) throw primaryError
}

export async function lockAuthSchemaForMigration(
  client: PoolClient
): Promise<void> {
  await client.query(
    `
      SELECT pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended($1, 0)
      )
    `,
    [AUTH_SCHEMA_ADVISORY_LOCK_NAME]
  )
}
