-- Fluent Path: verification of `privilege_hardening.sql`.
--
-- Read-only. Safe to run at any time, before or after hardening. It raises an exception on
-- the first violation, so it can be used as a gate after any change to privileges.
-- Run as the role that owns the application tables.
--
-- One expected exception: default privileges recorded with a grantor other than the backend
-- role. Supabase provisioning also created `ALTER DEFAULT PRIVILEGES ... GRANT ALL` as
-- `supabase_admin`, and the backend role is not a member of that role, so it cannot revoke
-- them. Those are reported as a notice and listed by the final query, not treated as a
-- failure, because they only apply to objects created by that other role.

DO $verify$
DECLARE
    leaking record;
    foreign_count bigint;
BEGIN
    -- 1. No role other than the connected owner may hold any privilege on a public table.
    --    aclexplode reports the PUBLIC pseudo-role with grantee OID 0, which has no pg_roles
    --    row, so the join must be a LEFT JOIN or grants to PUBLIC would pass unnoticed.
    SELECT c.relname AS object_name, pg_get_userbyid(c.relowner) AS owner,
           COALESCE(r.rolname, 'PUBLIC') AS grantee, a.privilege_type AS privilege
    INTO leaking
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl, acldefault('r', c.relowner))) AS a
    LEFT JOIN pg_roles r ON r.oid = a.grantee
    WHERE n.nspname = 'public' AND c.relkind = 'r'
      AND COALESCE(r.rolname, 'PUBLIC') <> pg_get_userbyid(c.relowner)
    LIMIT 1;

    IF leaking IS NOT NULL THEN
        RAISE EXCEPTION 'public.% still grants % to %', leaking.object_name,
            leaking.privilege, leaking.grantee;
    END IF;

    -- 2. The same must hold for sequences in public.
    SELECT c.relname AS object_name, COALESCE(r.rolname, 'PUBLIC') AS grantee,
           a.privilege_type AS privilege
    INTO leaking
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl, acldefault('S', c.relowner))) AS a
    LEFT JOIN pg_roles r ON r.oid = a.grantee
    WHERE n.nspname = 'public' AND c.relkind = 'S'
      AND COALESCE(r.rolname, 'PUBLIC') <> pg_get_userbyid(c.relowner)
    LIMIT 1;

    IF leaking IS NOT NULL THEN
        RAISE EXCEPTION 'public.% still grants % to %', leaking.object_name,
            leaking.privilege, leaking.grantee;
    END IF;

    -- 3. The backend role's own default privileges must not re-grant to anon, authenticated
    --    or service_role, or the next table created by any future migration is exposed again.
    SELECT pg_get_userbyid(d.defaclrole) AS grantor, d.defaclobjtype::text AS object_type,
           COALESCE(r.rolname, 'PUBLIC') AS grantee, a.privilege_type AS privilege
    INTO leaking
    FROM pg_default_acl d
    JOIN pg_namespace n ON n.oid = d.defaclnamespace
    CROSS JOIN LATERAL aclexplode(d.defaclacl) AS a
    LEFT JOIN pg_roles r ON r.oid = a.grantee
    WHERE n.nspname = 'public'
      AND d.defaclrole = (SELECT oid FROM pg_roles WHERE rolname = current_user)
      AND COALESCE(r.rolname, 'PUBLIC') IN ('anon', 'authenticated', 'service_role')
    LIMIT 1;

    IF leaking IS NOT NULL THEN
        RAISE EXCEPTION
            'default privileges for % still grant % on % to %', leaking.grantor,
            leaking.privilege, leaking.object_type, leaking.grantee;
    END IF;

    -- 3a. Default privileges belonging to another grantor cannot be changed by this role.
    --     Report, do not fail.
    SELECT count(*)
    INTO foreign_count
    FROM pg_default_acl d
    JOIN pg_namespace n ON n.oid = d.defaclnamespace
    CROSS JOIN LATERAL aclexplode(d.defaclacl) AS a
    LEFT JOIN pg_roles r ON r.oid = a.grantee
    WHERE n.nspname = 'public'
      AND d.defaclrole <> (SELECT oid FROM pg_roles WHERE rolname = current_user)
      AND COALESCE(r.rolname, 'PUBLIC') IN ('anon', 'authenticated', 'service_role');

    IF foreign_count > 0 THEN
        RAISE NOTICE
            '% default-privilege entries belong to another grantor and were not changed; '
            'they only affect objects that other role creates', foreign_count;
    END IF;

    -- 4. Every public table must have row level security enabled as defense in depth.
    --    Not FORCEd: the owner keeps full access, which Alembic and the importer need.
    SELECT c.relname INTO leaking
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity
    LIMIT 1;

    IF leaking IS NOT NULL THEN
        RAISE EXCEPTION 'public.% does not have row level security enabled', leaking.relname;
    END IF;

    SELECT c.relname INTO leaking
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relforcerowsecurity
    LIMIT 1;

    IF leaking IS NOT NULL THEN
        RAISE EXCEPTION 'public.% has row level security FORCEd, which would block the owner',
            leaking.relname;
    END IF;

    -- 5. The backend role must still own every public table, or Alembic cannot run.
    SELECT c.relname, pg_get_userbyid(c.relowner) INTO leaking
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'r'
      AND pg_get_userbyid(c.relowner) <> current_user
    LIMIT 1;

    IF leaking IS NOT NULL THEN
        RAISE EXCEPTION 'public.% is owned by %, not by the backend role %',
            leaking.relname, leaking.relowner, current_user;
    END IF;

    -- 6. The backend role must still have BYPASSRLS or table ownership, otherwise the
    --    owner-exemption that keeps the importer working would be gone.
    IF NOT EXISTS (SELECT 1 FROM pg_roles
                   WHERE rolname = current_user AND (rolbypassrls OR rolsuper)) THEN
        RAISE EXCEPTION 'backend role % has neither BYPASSRLS nor superuser; '
            'verify Alembic and importer access before relying on RLS', current_user;
    END IF;
END
$verify$;

SELECT 'privilege_hardening verified' AS result,
       count(*) FILTER (WHERE c.relrowsecurity) AS tables_with_rls,
       count(*) FILTER (WHERE c.relforcerowsecurity) AS tables_with_rls_forced,
       count(*) AS public_tables
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r';

-- Residual default privileges owned by another grantor, listed for the record.
SELECT pg_get_userbyid(d.defaclrole) AS grantor,
       d.defaclobjtype::text AS object_type,
       COALESCE(r.rolname, 'PUBLIC') AS grantee,
       a.privilege_type AS privilege
FROM pg_default_acl d
JOIN pg_namespace n ON n.oid = d.defaclnamespace
CROSS JOIN LATERAL aclexplode(d.defaclacl) AS a
LEFT JOIN pg_roles r ON r.oid = a.grantee
WHERE n.nspname = 'public'
  AND d.defaclrole <> (SELECT oid FROM pg_roles WHERE rolname = current_user)
  AND COALESCE(r.rolname, 'PUBLIC') IN ('anon', 'authenticated', 'service_role')
ORDER BY grantor, object_type, grantee, privilege;