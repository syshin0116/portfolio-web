---
title: "Web Auth.js operations runbook"
description: >
  Apply and verify the Auth.js PostgreSQL contract, configure OAuth providers,
  validate the owner journey, and roll back without exposing migration credentials.
when_to_read: >
  Before changing web authentication, Auth.js tables, OAuth callbacks, Vercel auth
  variables, or the Auth.js Neon branch.
tags: [operations, authjs, oauth, postgres, neon, vercel]
status: stable
updated: "2026-07-30"
owners: ["@syshin0116"]
refs:
  - ../adr/0007-postgres-on-neon-split-projects.md
  - gcp-neon-foundation.md
template: spec
---

# Web Auth.js operations runbook

## Contract

The web keeps Auth.js v5 with the official PostgreSQL adapter. Neon supplies PostgreSQL;
Neon Auth is not part of the authentication boundary. Each database URL is parsed once
into a narrow typed pool configuration; drivers receive explicit credentials, host,
port, database, TLS, fixed search path, and timeouts rather than the raw URL. Vercel
request handling creates a fresh bounded `@neondatabase/serverless` Pool inside
NextAuth's lazy configuration, forces its node-postgres-compatible WebSocket path, and
awaits `pool.end()` when that auth operation succeeds or fails. The migration CLI, exact
verifier, and PostgreSQL 17 integration suite use the same typed target contract with
the adapter's official `pg` peer independently.

The checked-in schema contract is `web/db/auth/0001_authjs.sql`. It:

- keeps `users`, `accounts`, and `sessions` string UUID IDs and existing rows;
- safely widens the production legacy `accounts.expires_at` from `integer` to `bigint`;
- atomically renames legacy `verification_tokens` to the adapter's required singular
  `verification_token`;
- creates the provider-account and session-token uniqueness boundaries;
- creates validated `accounts`/`sessions` user foreign keys with `ON DELETE CASCADE`;
- runs under the CLI's transaction-scoped advisory lock and is safe to run repeatedly;
- rolls the entire migration back on duplicate, orphaned, incompatible, or ambiguous
  data. It never deletes or deduplicates rows.

The SQL file deliberately has no standalone `BEGIN` or `COMMIT`. Only
`bun run auth:migrate` may execute it: the CLI starts an explicit
read-committed/read-write/non-deferrable transaction, fixes transaction-local search
path and timeouts, takes the lock, runs the exact verifier on the same connection before
`COMMIT`, and rolls back both DDL and data-preserving type changes on failure. The
standalone verifier uses a locked repeatable-read/read-only/non-deferrable snapshot.
Do not paste the SQL directly into a console.

If both verification-token table names exist, stop and reconcile them manually under a
separately reviewed data plan. Do not merge or drop one opportunistically.

## Credentials and variables

Vercel runtime configuration contains only:

- `DATABASE_URL`: the branch-scoped, least-privileged direct endpoint;
- `AUTH_SECRET`: at least 32 bytes;
- `AUTH_ALLOWED_EMAILS`: a non-empty production allowlist;
- optional `AUTH_ADMIN_EMAILS`, which must remain a deliberate subset of allowed users;
- `AUTH_GITHUB_ID` / `AUTH_GITHUB_SECRET`;
- `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET`.

The request path fails closed if any required runtime value is absent or invalid. Both
URLs require one database, fixed non-empty credentials, a direct endpoint, and exactly
`sslmode=require`; strip Neon-generated `channel_binding` and reject every other query
key, fragment, pooler endpoint, non-default hosted port, and non-empty `PG*` fallback
variable. Only the explicit loopback CI command may use `sslmode=disable`, and only
when `AUTH_POSTGRES_TEST_URL` exactly equals `AUTH_DATABASE_MIGRATION_URL`.
`AUTH_DATABASE_MIGRATION_URL` is an elevated, direct-endpoint credential used only by an
operator or migration job and must never be stored in Vercel runtime variables.

The verifier requires exactly 24 columns (including precision-6 timestamps), seven
built-in indexes, nine non-`NOT NULL` constraints, eight enabled PostgreSQL RI triggers,
no orphaned accounts or sessions, no legacy plural verification table, no inheritance,
no extra indexes or non-`NOT NULL` constraints, and no non-internal triggers, rewrite
rules, RLS policies, or RLS state. PostgreSQL 18 stores relation `NOT NULL`
specifications as `pg_constraint` rows with `contype = 'n'`, while PostgreSQL 17 does
not. The verifier accepts that surface only when every expected non-null column has
exactly one validated, enforced, local, non-inherited, non-period constraint with no
backing index, duplicate, or extra row. Constraint names are intentionally not part of
this cross-version contract because a PostgreSQL 18 legacy-table rename can preserve
the old generated name. Effective nullability remains independently audited through the
exact column inventory, and every other unexpected constraint type remains a violation.
This is an application-schema contract, not a claim that any hosted Neon database has
been migrated.

The nine required primary-key, unique, and foreign-key constraints must also remain
enforced and non-period on PostgreSQL 18. A `NOT ENFORCED` foreign key, a
`WITHOUT OVERLAPS` primary/unique key, or a `PERIOD` foreign key is schema drift even
when its table, columns, and generated name otherwise match.

The runtime database role needs `CONNECT`, schema `USAGE`, and only the required
`SELECT`, `INSERT`, `UPDATE`, and `DELETE` rights on the four Auth.js tables. UUID text
defaults require no sequence permission. It receives no table-creation, table-alteration,
role-management, cross-schema, or database-administration privilege.

## Preview migration and verification

Take a branch backup or restorable Neon branch before the first migration. Use an
isolated preview branch and its migration credential:

```sh
cd web
read -rs AUTH_DATABASE_MIGRATION_URL
export AUTH_DATABASE_MIGRATION_URL
bun run auth:migrate
bun run auth:verify
unset AUTH_DATABASE_MIGRATION_URL
```

`auth:migrate` applies the transaction and immediately runs the exact verifier.
`auth:verify` is the independent, read-only gate. Neither command falls back to runtime
`DATABASE_URL`, reparses the connection string, or prints it. Production uses the
no-argument commands; `--allow-insecure-loopback-test` exists only for local CI.

After preview passes, repeat the same commands with the separately held production
migration credential. Promote only the already-reviewed application revision, then bind
its production runtime credential.

This repository change is the first-stage application and schema contract. It does not
claim that preview or production Neon has been migrated. Before merging the change that
restores or enables Vercel Git automatic deployment, verify the current `main` revision's
Production Neon schema plus its runtime and OAuth environment prerequisites. Apply the
same pre-merge gate to every later application revision that depends on a schema change:
use the isolated credential to migrate and verify the target Neon branch, then merge only
the exact reviewed revision. Never add that elevated URL to Vercel. If a required runtime
variable or schema prerequisite is absent, the Auth surface must fail closed; automatic
delivery must not turn missing prerequisites into implicit DDL authority.

## OAuth provider setup

Use distinct preview and production OAuth credentials so a preview callback cannot
authenticate into production.

The callbacks currently usable on the deployed Vercel domain are:

- GitHub: `https://syshin0116.vercel.app/api/auth/callback/github`
- Google: `https://syshin0116.vercel.app/api/auth/callback/google`

`syshin0116.vercel.app` is the canonical verified Vercel Production project domain.
Keep automatic Production-domain assignment enabled; a successful build that remains
staged does not update this OAuth origin and can leave an older Auth.js implementation
serving traffic. The tokenless `vercel/production` observer compares the public
runtime's Git SHA and unique deployment URL with the exact GitHub/Vercel deployment
event after each `main` merge. Treat a mismatch as a deployment-routing failure before
changing OAuth credentials or the Neon schema.

Add the exact Vercel Preview origin with the same callback paths to the preview provider
configuration. GitHub OAuth apps support one callback root, so use separate apps for
preview and production. The custom-domain targets are
`https://syshin0116.dev/api/auth/callback/github` and
`https://syshin0116.dev/api/auth/callback/google`, but they must not replace the live
Vercel callbacks until the canonical custom-domain DNS resolves and both HTTPS callback
paths pass the preview-to-production acceptance gate.

Sign-in accepts only an allowlisted email that the provider proves is verified. Google
must return a matching `email_verified=true` claim. GitHub must return a matching primary,
verified address from `/user/emails`. Provider API failures deny sign-in. Cross-provider
account linking keeps Auth.js's safe default; `allowDangerousEmailAccountLinking` remains
disabled. An existing user who adds another provider may therefore see
`OAuthAccountNotLinked` and should sign in with the originally linked provider.

## Browser acceptance gate

Run all of these on preview with a fresh browser profile before production:

1. GitHub login reaches its callback and creates one user, account, and session.
2. Google login reaches its callback and applies the default account-linking rule.
3. A non-allowlisted or unverified address is rejected and creates no persisted user or
   account.
4. `/api/auth/session` returns a non-empty string user ID.
5. `/api/agent-token` returns a JWT whose string `sub` equals that user ID.
6. Logout invalidates the session; a new browser cannot reuse it.
7. Session refresh and a second fresh login succeed.

CI proves schema idempotency, legacy-row preservation, verifier-triggered rollback,
constraint failures, adapter user/account/session lifecycle, request-pool cleanup, and
string token subjects against PostgreSQL 17. It also injects PostgreSQL 18-style
relation `NOT NULL` catalog rows into the verifier's real PostgreSQL 17 catalog path and
proves that duplicate, unvalidated, inherited, and extra relation constraints fail while
an unexpected `CHECK` constraint still fails. The pinned adapter/Neon driver cast
remains a reviewed compatibility boundary; preview must run the same adapter lifecycle
against an actual Neon branch before promotion. Real provider callbacks remain an
operational acceptance gate because CI does not own provider accounts or secrets.

## Rollback

Restore the previous Vercel deployment and its previous runtime database binding. Do not
copy rows between preview and production, and do not roll new sessions back into the old
database. The schema migration is additive except for the lossless verification-table
rename and remains compatible with the pinned OAuth adapter. Preserve the pre-migration
branch until login, session refresh, logout, and rollback rehearsal all pass.
