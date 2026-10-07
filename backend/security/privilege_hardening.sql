-- Fluent Path: minimum-privilege hardening for the Supabase staging `public` schema.
--
-- Purpose: remove direct Data API / database-role access to Fluent Path application tables
-- for anon, authenticated and service_role, and stop future tables from inheriting it, while
-- leaving the FastAPI backend's access completely untouched.
--
-- Verified context (read-only analysis, 2026-10-02):
--   * `public` holds 27 tables: the 26 application tables plus alembic_version.
--   * Every one of them is owned by the connected role (`postgres`) and carries the ACL
--     `arwdDxtm` (SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN)
--     for anon, authenticated and service_role, recorded with grantor `postgres`.
--   * No grant exists for the PUBLIC pseudo-role, and no column-level grant exists.
--   * Row level security is disabled on all 27 tables.
--   * The single sequence, ai_usage_events_id_seq, carries the same three broad grants.
--   * There are no functions, views or materialized views in `public`, and no publication
--     references `public`, so nothing that Supabase Realtime or Storage relies on is affected.
--   * Those table grants were never written by Fluent Path code. Supabase provisions
--     `ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated,
--     service_role` for the project owner, and the `0001_initial_schema` migration created
--     every table as that owner, so each table inherited the grants at creation time.
--
-- Why the FastAPI backend is unaffected: the backend connects as the pooler login role that
-- resolves to `postgres`, which owns all 27 tables and has BYPASSRLS. Table ownership and
-- BYPASSRLS are both unaffected by these statements, and the running API performs no database
-- access at all today. Only Alembic (needs ownership to ALTER/DROP) and the guarded importer
-- (needs SELECT, INSERT and sequence USAGE) touch the database, and both keep full access.
--
-- Scope guard: this script touches schema `public` only. It never references `auth`,
-- `storage`, `realtime`, `vault`, `graphql`, `extensions`, `pgrst` or `pgbouncer`, never
-- modifies a role, never modifies Supabase-managed objects, and never changes data.
--
-- Run as the role that owns the application tables, inside a single transaction.

BEGIN;

-- Step 1. Remove the broad table privileges. These are recorded with this role as grantor,
-- because they were inherited from this role's default privileges at table creation.
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM anon, authenticated, service_role;

-- Step 2. Remove the same broad privileges on the identity sequence. Without this,
-- anon could still read and advance ai_usage_events_id_seq.
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated, service_role;

-- Step 3. No public functions exist today; this keeps a future one from being callable.
REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM anon, authenticated, service_role;

-- Step 4. Stop future objects created by this role from inheriting the grants. Without this,
-- the next table created by any future migration would be exposed again.
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon, authenticated, service_role;

-- Step 5. Defense in depth. Row level security is enabled with no policies, so anon and
-- authenticated are denied even if a privilege is ever granted again by mistake. It is
-- deliberately not FORCEd, and it changes nothing for this role, which owns every table and
-- bypasses RLS. It does not protect against service_role, which also has BYPASSRLS; that role
-- is protected by steps 1 to 4 only.
DO $hardening$
DECLARE
    target record;
BEGIN
    FOR target IN
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r'
        ORDER BY c.relname
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', target.relname);
    END LOOP;
END
$hardening$;

COMMIT;