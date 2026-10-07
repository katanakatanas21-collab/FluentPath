-- Fluent Path: rollback of `privilege_hardening.sql`.
--
-- This restores exactly the privilege state observed before hardening, and nothing else.
-- It is only for reverting the hardening itself; it re-exposes `users` (including
-- password_hash) and `revoked_tokens` to anon and authenticated, so it must not be used to
-- "fix" a failing application. The running FastAPI backend never needed those privileges, so
-- rolling back is not a remedy for any application problem.
--
-- Run as the role that owns the application tables, inside a single transaction.

BEGIN;

-- Undo step 5: disable row level security on the same set of tables hardening enabled.
DO $rollback$
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
        EXECUTE format('ALTER TABLE public.%I DISABLE ROW LEVEL SECURITY', target.relname);
    END LOOP;
END
$rollback$;

-- Undo step 4.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO anon, authenticated, service_role;

-- Undo steps 1 to 3.
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO anon, authenticated, service_role;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, service_role;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO anon, authenticated, service_role;

COMMIT;