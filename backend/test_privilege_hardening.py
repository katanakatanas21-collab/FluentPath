"""Static regression checks for the privilege-hardening SQL scripts.

These are text-level checks, not database tests. The behavioural proof lives in
.staging-preflight-20261002/privilege_hardening_disposable.py, which runs the real scripts
against a disposable PostgreSQL 17 container. These tests exist so that an accidental edit to
the SQL, or a review change to its scope, fails loudly in the offline test run rather than
being discovered during a staging change window.

No database connection, staging connection or provider is used.
"""
import re
import unittest
from pathlib import Path

SECURITY = Path(__file__).resolve().parent / 'security'
FORWARD = SECURITY / 'privilege_hardening.sql'
ROLLBACK = SECURITY / 'privilege_hardening_rollback.sql'
VERIFY = SECURITY / 'verify_privilege_hardening.sql'

DATA_ROLES = ('anon', 'authenticated', 'service_role')
SUPABASE_MANAGED = ('auth', 'storage', 'realtime', 'vault', 'graphql', 'extensions',
                    'pgrst', 'pgbouncer', 'supabase_migrations')


def sql_text(path):
    return path.read_text(encoding='utf-8')


def executable_lines(text):
    """Strip comments so scope checks cannot be satisfied by a comment alone."""
    without_block = re.sub(r'--[^\n]*', '', text)
    return [line.strip() for line in without_block.splitlines() if line.strip()]


def names_schema(schema, text):
    """True if the identifier appears as a whole word, so 'auth' does not match
    'authenticated' and 'auth' the schema is still detected."""
    return re.search(r'(?<![a-z0-9_])' + re.escape(schema) + r'(?![a-z0-9_])', text) is not None


MUTATING_VERBS = ('INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER', 'GRANT', 'REVOKE',
                  'TRUNCATE', 'COMMENT', 'COPY', 'VACUUM', 'REINDEX', 'SET', 'RESET')


def mutating_keywords(text):
    """Whole-word mutating keywords in comment-free SQL.

    Whole words matter: 'GRANTS % TO %' in an error message is not a GRANT statement, and
    'grantee' is not a GRANT. String literals are removed too, so wording inside a message
    cannot be mistaken for a statement.
    """
    without_comments = re.sub(r'--[^\n]*', '', text)
    without_literals = re.sub(r"'(?:[^']|'')*'", "''", without_comments)
    found = set()
    for keyword in MUTATING_VERBS:
        if re.search(r'\b' + keyword + r'\b', without_literals, re.IGNORECASE):
            found.add(keyword)
    return found


class NoByteOrderMarkTests(unittest.TestCase):
    def test_scripts_have_no_byte_order_mark(self):
        # A UTF-8 BOM makes asyncpg reject the script with a syntax error, which would look
        # like a broken remediation rather than an encoding problem.
        for path in (FORWARD, ROLLBACK, VERIFY):
            with self.subTest(script=path.name):
                self.assertFalse(path.read_bytes().startswith(b'\xef\xbb\xbf'), path.name)


class ForwardScriptTests(unittest.TestCase):
    def setUp(self):
        self.text = sql_text(FORWARD)
        self.statements = executable_lines(self.text)

    def test_revokes_every_object_class_from_every_data_api_role(self):
        for objtype in ('TABLES', 'SEQUENCES', 'FUNCTIONS'):
            with self.subTest(object_type=objtype):
                self.assertTrue(any(
                    statement.startswith('REVOKE ALL PRIVILEGES ON ALL ' + objtype)
                    and statement.endswith('FROM anon, authenticated, service_role;')
                    for statement in self.statements), objtype)

    def test_revokes_default_privileges_for_tables_sequences_and_functions(self):
        for objtype in ('TABLES', 'SEQUENCES', 'FUNCTIONS'):
            with self.subTest(object_type=objtype):
                self.assertTrue(any(
                    statement == 'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON '
                                 + objtype + ' FROM anon, authenticated, service_role;'
                    for statement in self.statements), objtype)

    def test_default_privilege_change_is_scoped_to_the_connected_role(self):
        # ALTER DEFAULT PRIVILEGES ... FOR ROLE would change another grantor's rules, which the
        # backend role cannot do and which would reach beyond this remediation.
        for statement in self.statements:
            self.assertNotIn('FOR ROLE', statement.upper(), statement)

    def test_enables_rls_on_every_public_table_without_forcing_it(self):
        self.assertTrue(any("relkind = 'r'" in statement for statement in self.statements))
        self.assertTrue(any('ENABLE ROW LEVEL SECURITY' in statement
                            for statement in self.statements))
        self.assertFalse(any('FORCE ROW LEVEL SECURITY' in statement
                             for statement in self.statements))
        self.assertFalse(any('FORCE' in statement.upper().replace('INFORMATION_SCHEMA', '')
                             for statement in self.statements))

    def test_runs_in_a_single_transaction(self):
        self.assertEqual(sum(1 for s in self.statements if s == 'BEGIN;'), 1)
        self.assertEqual(sum(1 for s in self.statements if s == 'COMMIT;'), 1)

    def test_never_modifies_data_or_roles(self):
        forbidden = ('INSERT ', 'UPDATE ', 'DELETE ', 'TRUNCATE ', 'DROP ', 'ALTER ROLE',
                     'CREATE ROLE', 'GRANT ')
        for statement in self.statements:
            for keyword in forbidden:
                with self.subTest(statement=statement, keyword=keyword):
                    self.assertNotIn(keyword, statement.upper(), statement)


class ScopeTests(unittest.TestCase):
    """The remediation must touch schema public only."""

    def setUp(self):
        self.scripts = {path.name: sql_text(path)
                        for path in (FORWARD, ROLLBACK, VERIFY)}

    def test_no_supabase_managed_schema_is_referenced(self):
        for name, text in self.scripts.items():
            statements = ' '.join(executable_lines(text)).lower()
            for schema in SUPABASE_MANAGED:
                with self.subTest(script=name, schema=schema):
                    self.assertFalse(names_schema(schema, statements), schema)

    def test_every_schema_reference_is_public(self):
        for name, text in self.scripts.items():
            for schema in set(re.findall(r'\bIN SCHEMA ([a-z_]+)', text)):
                with self.subTest(script=name, schema=schema):
                    self.assertEqual(schema, 'public')


class RollbackScriptTests(unittest.TestCase):
    def setUp(self):
        self.text = sql_text(ROLLBACK)
        self.statements = executable_lines(self.text)

    def test_restores_the_same_grants_and_default_privileges_it_removed(self):
        for objtype in ('TABLES', 'SEQUENCES', 'FUNCTIONS'):
            with self.subTest(object_type=objtype):
                self.assertTrue(any(
                    statement == 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON '
                                 + objtype + ' TO anon, authenticated, service_role;'
                    for statement in self.statements), objtype)
                self.assertTrue(any(
                    statement.startswith('GRANT ALL PRIVILEGES ON ALL ' + objtype)
                    for statement in self.statements), objtype)

    def test_warns_that_it_reintroduces_the_exposure(self):
        self.assertIn('RE-EXPOSE', self.text.upper())
        for role in DATA_ROLES:
            with self.subTest(role=role):
                self.assertIn(role, self.text)


class VerifierScriptTests(unittest.TestCase):
    def setUp(self):
        self.text = sql_text(VERIFY)
        self.statements = executable_lines(self.text)

    def test_checks_tables_sequences_and_default_privileges(self):
        joined = ' '.join(self.statements)
        self.assertIn("acldefault('r'", joined)
        self.assertIn("acldefault('S'", joined)
        self.assertIn('pg_default_acl', joined)

    def test_detects_grants_to_the_public_pseudo_role(self):
        # aclexplode reports PUBLIC with grantee OID 0, which has no pg_roles row, so an inner
        # join would silently hide a grant to PUBLIC.
        self.assertIn("COALESCE(r.rolname, 'PUBLIC')", self.text)
        self.assertIsNone(
            re.search(r'(?<!LEFT )\bJOIN pg_roles r ON r\.oid = a\.grantee', self.text),
            'an inner join to pg_roles hides grants to PUBLIC')
        self.assertIn('LEFT JOIN pg_roles r ON r.oid = a.grantee', self.text)

    def test_only_fails_on_default_privileges_the_backend_role_owns(self):
        self.assertIn('d.defaclrole = (SELECT oid FROM pg_roles WHERE rolname = current_user)',
                      self.text)

    def test_requires_rls_enabled_but_not_forced(self):
        self.assertIn('NOT c.relrowsecurity', self.text)
        self.assertIn('c.relforcerowsecurity', self.text)

    def test_requires_the_backend_role_to_own_every_table(self):
        self.assertIn('pg_get_userbyid(c.relowner) <> current_user', self.text)

    def test_is_read_only(self):
        self.assertEqual(mutating_keywords(self.text), set())


class DisposableProofScriptTests(unittest.TestCase):
    """The proof must stay disposable and must not be able to reach staging."""

    def setUp(self):
        self.text = sql_text(Path(__file__).resolve().parents[1]
                             / '.staging-preflight-20261002'
                             / 'privilege_hardening_disposable.py')

    def test_reads_no_configured_database_url(self):
        # It must never load the project's .env, or it could silently connect to staging.
        self.assertNotIn('load_dotenv', self.text)
        self.assertNotIn('dotenv', self.text)

    def test_generates_its_own_credentials(self):
        self.assertIn('secrets.token_urlsafe', self.text)
        self.assertIn('secrets.token_hex', self.text)

    def test_asserts_it_did_not_touch_staging_or_product_data(self):
        self.assertIn("'staging_touched': False", self.text)
        self.assertIn("'product_data_touched': False", self.text)

    def test_does_not_run_the_real_migration_or_importer_against_staging(self):
        self.assertIn('alembic_run', self.text)
        self.assertNotIn('imp.apply(', self.text)


if __name__ == '__main__':
    unittest.main()