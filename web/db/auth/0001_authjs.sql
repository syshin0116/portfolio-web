DO $migration$
BEGIN
  IF to_regclass('public.verification_tokens') IS NOT NULL
     AND to_regclass('public.verification_token') IS NOT NULL THEN
    RAISE EXCEPTION
      'both public.verification_tokens and public.verification_token exist; reconcile them manually before migration';
  END IF;

  IF to_regclass('public.verification_tokens') IS NOT NULL THEN
    ALTER TABLE public.verification_tokens
      RENAME TO verification_token;
  END IF;
END
$migration$;

CREATE TABLE IF NOT EXISTS public.users (
  id text PRIMARY KEY DEFAULT gen_random_uuid()::text,
  name text,
  email text,
  "emailVerified" timestamp with time zone,
  image text
);

CREATE TABLE IF NOT EXISTS public.accounts (
  id text PRIMARY KEY DEFAULT gen_random_uuid()::text,
  "userId" text NOT NULL,
  type text NOT NULL,
  provider text NOT NULL,
  "providerAccountId" text NOT NULL,
  refresh_token text,
  access_token text,
  expires_at bigint,
  token_type text,
  scope text,
  id_token text,
  session_state text
);

CREATE TABLE IF NOT EXISTS public.sessions (
  id text PRIMARY KEY DEFAULT gen_random_uuid()::text,
  "userId" text NOT NULL,
  expires timestamp with time zone NOT NULL,
  "sessionToken" text NOT NULL
);

CREATE TABLE IF NOT EXISTS public.verification_token (
  identifier text NOT NULL,
  expires timestamp with time zone NOT NULL,
  token text NOT NULL
);

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS id text DEFAULT gen_random_uuid()::text,
  ADD COLUMN IF NOT EXISTS name text,
  ADD COLUMN IF NOT EXISTS email text,
  ADD COLUMN IF NOT EXISTS "emailVerified" timestamp with time zone,
  ADD COLUMN IF NOT EXISTS image text;

ALTER TABLE public.accounts
  ADD COLUMN IF NOT EXISTS id text DEFAULT gen_random_uuid()::text,
  ADD COLUMN IF NOT EXISTS "userId" text,
  ADD COLUMN IF NOT EXISTS type text,
  ADD COLUMN IF NOT EXISTS provider text,
  ADD COLUMN IF NOT EXISTS "providerAccountId" text,
  ADD COLUMN IF NOT EXISTS refresh_token text,
  ADD COLUMN IF NOT EXISTS access_token text,
  ADD COLUMN IF NOT EXISTS expires_at bigint,
  ADD COLUMN IF NOT EXISTS token_type text,
  ADD COLUMN IF NOT EXISTS scope text,
  ADD COLUMN IF NOT EXISTS id_token text,
  ADD COLUMN IF NOT EXISTS session_state text;

ALTER TABLE public.sessions
  ADD COLUMN IF NOT EXISTS id text DEFAULT gen_random_uuid()::text,
  ADD COLUMN IF NOT EXISTS "userId" text,
  ADD COLUMN IF NOT EXISTS expires timestamp with time zone,
  ADD COLUMN IF NOT EXISTS "sessionToken" text;

ALTER TABLE public.verification_token
  ADD COLUMN IF NOT EXISTS identifier text,
  ADD COLUMN IF NOT EXISTS expires timestamp with time zone,
  ADD COLUMN IF NOT EXISTS token text;

DO $safe_widening$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'accounts'
      AND column_name = 'expires_at'
      AND data_type = 'integer'
      AND udt_name = 'int4'
  ) THEN
    ALTER TABLE public.accounts
      ALTER COLUMN expires_at TYPE bigint
      USING expires_at::bigint;
  END IF;
END
$safe_widening$;

DO $contract$
DECLARE
  mismatch record;
BEGIN
  FOR mismatch IN
    WITH expected(table_name, column_name, data_type, udt_name) AS (
      VALUES
        ('users', 'id', 'text', 'text'),
        ('users', 'name', 'text', 'text'),
        ('users', 'email', 'text', 'text'),
        ('users', 'emailVerified', 'timestamp with time zone', 'timestamptz'),
        ('users', 'image', 'text', 'text'),
        ('accounts', 'id', 'text', 'text'),
        ('accounts', 'userId', 'text', 'text'),
        ('accounts', 'type', 'text', 'text'),
        ('accounts', 'provider', 'text', 'text'),
        ('accounts', 'providerAccountId', 'text', 'text'),
        ('accounts', 'refresh_token', 'text', 'text'),
        ('accounts', 'access_token', 'text', 'text'),
        ('accounts', 'expires_at', 'bigint', 'int8'),
        ('accounts', 'token_type', 'text', 'text'),
        ('accounts', 'scope', 'text', 'text'),
        ('accounts', 'id_token', 'text', 'text'),
        ('accounts', 'session_state', 'text', 'text'),
        ('sessions', 'id', 'text', 'text'),
        ('sessions', 'userId', 'text', 'text'),
        ('sessions', 'expires', 'timestamp with time zone', 'timestamptz'),
        ('sessions', 'sessionToken', 'text', 'text'),
        ('verification_token', 'identifier', 'text', 'text'),
        ('verification_token', 'expires', 'timestamp with time zone', 'timestamptz'),
        ('verification_token', 'token', 'text', 'text')
    )
    SELECT
      expected.table_name,
      expected.column_name,
      columns.data_type AS actual_data_type,
      columns.udt_name AS actual_udt_name,
      expected.data_type AS expected_data_type,
      expected.udt_name AS expected_udt_name
    FROM expected
    JOIN information_schema.columns AS columns
      ON columns.table_schema = 'public'
      AND columns.table_name = expected.table_name
      AND columns.column_name = expected.column_name
    WHERE columns.data_type <> expected.data_type
       OR columns.udt_name <> expected.udt_name
  LOOP
    RAISE EXCEPTION
      'incompatible type for %.%: found %/%, expected %/%',
      mismatch.table_name,
      mismatch.column_name,
      mismatch.actual_data_type,
      mismatch.actual_udt_name,
      mismatch.expected_data_type,
      mismatch.expected_udt_name;
  END LOOP;
END
$contract$;

ALTER TABLE public.users
  ALTER COLUMN id SET DEFAULT gen_random_uuid()::text,
  ALTER COLUMN id SET NOT NULL,
  ALTER COLUMN name DROP DEFAULT,
  ALTER COLUMN name DROP NOT NULL,
  ALTER COLUMN email DROP DEFAULT,
  ALTER COLUMN email DROP NOT NULL,
  ALTER COLUMN "emailVerified" DROP DEFAULT,
  ALTER COLUMN "emailVerified" DROP NOT NULL,
  ALTER COLUMN image DROP DEFAULT,
  ALTER COLUMN image DROP NOT NULL;

ALTER TABLE public.accounts
  ALTER COLUMN id SET DEFAULT gen_random_uuid()::text,
  ALTER COLUMN id SET NOT NULL,
  ALTER COLUMN "userId" DROP DEFAULT,
  ALTER COLUMN "userId" SET NOT NULL,
  ALTER COLUMN type DROP DEFAULT,
  ALTER COLUMN type SET NOT NULL,
  ALTER COLUMN provider DROP DEFAULT,
  ALTER COLUMN provider SET NOT NULL,
  ALTER COLUMN "providerAccountId" DROP DEFAULT,
  ALTER COLUMN "providerAccountId" SET NOT NULL,
  ALTER COLUMN refresh_token DROP DEFAULT,
  ALTER COLUMN refresh_token DROP NOT NULL,
  ALTER COLUMN access_token DROP DEFAULT,
  ALTER COLUMN access_token DROP NOT NULL,
  ALTER COLUMN expires_at DROP DEFAULT,
  ALTER COLUMN expires_at DROP NOT NULL,
  ALTER COLUMN token_type DROP DEFAULT,
  ALTER COLUMN token_type DROP NOT NULL,
  ALTER COLUMN scope DROP DEFAULT,
  ALTER COLUMN scope DROP NOT NULL,
  ALTER COLUMN id_token DROP DEFAULT,
  ALTER COLUMN id_token DROP NOT NULL,
  ALTER COLUMN session_state DROP DEFAULT,
  ALTER COLUMN session_state DROP NOT NULL;

ALTER TABLE public.sessions
  ALTER COLUMN id SET DEFAULT gen_random_uuid()::text,
  ALTER COLUMN id SET NOT NULL,
  ALTER COLUMN "userId" DROP DEFAULT,
  ALTER COLUMN "userId" SET NOT NULL,
  ALTER COLUMN expires DROP DEFAULT,
  ALTER COLUMN expires SET NOT NULL,
  ALTER COLUMN "sessionToken" DROP DEFAULT,
  ALTER COLUMN "sessionToken" SET NOT NULL;

ALTER TABLE public.verification_token
  ALTER COLUMN identifier DROP DEFAULT,
  ALTER COLUMN identifier SET NOT NULL,
  ALTER COLUMN expires DROP DEFAULT,
  ALTER COLUMN expires SET NOT NULL,
  ALTER COLUMN token DROP DEFAULT,
  ALTER COLUMN token SET NOT NULL;

DO $primary_keys$
DECLARE
  target text;
  expected_columns text[];
  actual_columns text[];
  actual_constraint_name text;
BEGIN
  FOR target, expected_columns IN
    VALUES
      ('users', ARRAY['id']::text[]),
      ('accounts', ARRAY['id']::text[]),
      ('sessions', ARRAY['id']::text[]),
      ('verification_token', ARRAY['identifier', 'token']::text[])
  LOOP
    SELECT
      constraint_row.conname,
      ARRAY(
        SELECT attribute.attname::text
        FROM unnest(constraint_row.conkey)
          WITH ORDINALITY AS key(attnum, ordinality)
        JOIN pg_attribute AS attribute
          ON attribute.attrelid = constraint_row.conrelid
          AND attribute.attnum = key.attnum
        ORDER BY key.ordinality
      )
      INTO actual_constraint_name, actual_columns
    FROM pg_constraint AS constraint_row
    WHERE constraint_row.conrelid =
      format('public.%I', target)::regclass
      AND constraint_row.contype = 'p'
    ORDER BY constraint_row.oid
    LIMIT 1;

    IF actual_columns IS NULL THEN
      EXECUTE format(
        'ALTER TABLE public.%I ADD CONSTRAINT %I PRIMARY KEY (%s)',
        target,
        target || '_pkey',
        (
          SELECT string_agg(format('%I', column_name), ', ')
          FROM unnest(expected_columns) AS column_name
        )
      );
    ELSIF actual_columns <> expected_columns THEN
      RAISE EXCEPTION
        'incompatible primary key on public.%: found %, expected %',
        target,
        actual_columns,
        expected_columns;
    ELSIF actual_constraint_name <> target || '_pkey' THEN
      EXECUTE format(
        'ALTER TABLE public.%I RENAME CONSTRAINT %I TO %I',
        target,
        actual_constraint_name,
        target || '_pkey'
      );
    END IF;
  END LOOP;
END
$primary_keys$;

DO $unique_constraints$
DECLARE
  target text;
  constraint_name text;
  expected_columns text[];
  existing_constraint text;
  existing_index text;
BEGIN
  FOR target, constraint_name, expected_columns IN
    VALUES
      ('users', 'users_email_key', ARRAY['email']::text[]),
      (
        'accounts',
        'accounts_provider_provider_account_id_key',
        ARRAY['provider', 'providerAccountId']::text[]
      ),
      (
        'sessions',
        'sessions_session_token_key',
        ARRAY['sessionToken']::text[]
      )
  LOOP
    SELECT constraint_row.conname
      INTO existing_constraint
    FROM pg_constraint AS constraint_row
    WHERE constraint_row.conrelid =
      format('public.%I', target)::regclass
      AND constraint_row.contype = 'u'
      AND (
        SELECT array_agg(
          attribute.attname::text ORDER BY key.ordinality
        )
        FROM unnest(constraint_row.conkey)
          WITH ORDINALITY AS key(attnum, ordinality)
        JOIN pg_attribute AS attribute
          ON attribute.attrelid = constraint_row.conrelid
          AND attribute.attnum = key.attnum
      ) = expected_columns
    ORDER BY constraint_row.oid
    LIMIT 1;

    IF existing_constraint IS NULL THEN
      SELECT index_class.relname
        INTO existing_index
      FROM pg_index AS index_row
      JOIN pg_class AS index_class
        ON index_class.oid = index_row.indexrelid
      WHERE index_row.indrelid =
        format('public.%I', target)::regclass
        AND index_row.indisunique
        AND NOT index_row.indisprimary
        AND index_row.indisvalid
        AND index_row.indisready
        AND index_row.indislive
        AND index_row.indpred IS NULL
        AND index_row.indexprs IS NULL
        AND (
          SELECT array_agg(
            attribute.attname::text ORDER BY key.ordinality
          )
          FROM unnest(index_row.indkey)
            WITH ORDINALITY AS key(attnum, ordinality)
          JOIN pg_attribute AS attribute
            ON attribute.attrelid = index_row.indrelid
            AND attribute.attnum = key.attnum
        ) = expected_columns
        AND NOT EXISTS (
          SELECT 1
          FROM pg_constraint AS constraint_row
          WHERE constraint_row.conindid = index_row.indexrelid
            AND constraint_row.contype IN ('p', 'u')
        )
      ORDER BY index_row.indexrelid
      LIMIT 1;

      IF existing_index IS NOT NULL THEN
        EXECUTE format(
          'ALTER TABLE public.%I ADD CONSTRAINT %I UNIQUE USING INDEX %I',
          target,
          constraint_name,
          existing_index
        );
      ELSE
        EXECUTE format(
          'ALTER TABLE public.%I ADD CONSTRAINT %I UNIQUE (%s)',
          target,
          constraint_name,
          (
            SELECT string_agg(format('%I', column_name), ', ')
            FROM unnest(expected_columns) AS column_name
          )
        );
      END IF;
    END IF;

    IF existing_constraint IS NOT NULL
       AND existing_constraint <> constraint_name
       AND NOT EXISTS (
         SELECT 1
         FROM pg_constraint AS constraint_row
         WHERE constraint_row.conrelid =
           format('public.%I', target)::regclass
           AND constraint_row.conname = constraint_name
       ) THEN
      EXECUTE format(
        'ALTER TABLE public.%I RENAME CONSTRAINT %I TO %I',
        target,
        existing_constraint,
        constraint_name
      );
    END IF;
  END LOOP;
END
$unique_constraints$;

DO $foreign_keys$
DECLARE
  target text;
  constraint_name text;
  local_column text;
  matching_count integer;
  conflicting_count integer;
  matching_name text;
BEGIN
  FOR target, constraint_name, local_column IN
    VALUES
      ('accounts', 'accounts_user_id_fkey', 'userId'),
      ('sessions', 'sessions_user_id_fkey', 'userId')
  LOOP
    SELECT
      count(*) FILTER (
        WHERE constraint_row.confrelid = 'public.users'::regclass
          AND referenced_attribute.attname = 'id'
          AND constraint_row.confdeltype = 'c'
          AND constraint_row.convalidated
      ),
      count(*),
      min(constraint_row.conname) FILTER (
        WHERE constraint_row.confrelid = 'public.users'::regclass
          AND referenced_attribute.attname = 'id'
          AND constraint_row.confdeltype = 'c'
          AND constraint_row.convalidated
      )
    INTO matching_count, conflicting_count, matching_name
    FROM pg_constraint AS constraint_row
    JOIN pg_attribute AS local_attribute
      ON local_attribute.attrelid = constraint_row.conrelid
      AND local_attribute.attnum = constraint_row.conkey[1]
    JOIN pg_attribute AS referenced_attribute
      ON referenced_attribute.attrelid = constraint_row.confrelid
      AND referenced_attribute.attnum = constraint_row.confkey[1]
    WHERE constraint_row.conrelid =
      format('public.%I', target)::regclass
      AND constraint_row.contype = 'f'
      AND array_length(constraint_row.conkey, 1) = 1
      AND local_attribute.attname = local_column;

    IF matching_count = 0 AND conflicting_count > 0 THEN
      RAISE EXCEPTION
        'incompatible foreign key on public.%.%; expected public.users(id) ON DELETE CASCADE',
        target,
        local_column;
    END IF;

    IF matching_count = 0 THEN
      EXECUTE format(
        'ALTER TABLE public.%I ADD CONSTRAINT %I FOREIGN KEY (%I) REFERENCES public.users(id) ON DELETE CASCADE',
        target,
        constraint_name,
        local_column
      );
    ELSIF matching_count = 1
       AND matching_name <> constraint_name THEN
      EXECUTE format(
        'ALTER TABLE public.%I RENAME CONSTRAINT %I TO %I',
        target,
        matching_name,
        constraint_name
      );
    END IF;
  END LOOP;
END
$foreign_keys$;
