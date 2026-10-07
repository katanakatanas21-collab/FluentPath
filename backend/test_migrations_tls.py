"""Regression tests for Alembic transport security.

`migrations/env.py` used to build its engine straight from the URL and never
supplied an ``ssl`` argument, so a migration could reach the database with no
certificate verification at all while the application runtime refused to. The
URL also had no say in the matter: nothing in it could turn verification on.

To be precise about the old exposure: an explicit ``sslmode=disable`` was not
silently honoured, because asyncpg rejects that keyword and it failed loudly.
The defect was the total absence of enforced verification.

These tests pin the migration path to the same pinned-root, hostname-checked
SSL context the runtime uses, and pin the absence of any downgrade in the file.

The module executes migrations at import, so it is loaded once with a stubbed
Alembic context in offline mode. Only the pure helpers are then exercised.
"""

import ast
import importlib.util
import io
import os
import ssl
import sys
import tokenize
import unittest
from pathlib import Path
from unittest import mock

import alembic

BACKEND = Path(__file__).resolve().parent
ENV_PATH = BACKEND / "migrations" / "env.py"

#: Tokens that would mean a migration could run without verifying the server.
FORBIDDEN_IN_CODE = (
    "CERT_NONE",
    "verify=False",
    "sslmode=disable",
    "sslmode=require",
    "sslmode=allow",
    "sslmode=prefer",
    "ssl_vermode",
    "create_default_context()",
)

#: Environments where a migration must never run without certificate verification.
VERIFIED_TLS_ENVIRONMENTS = ("staging", "production")


def load_env_module():
    """Import migrations/env.py with a stubbed Alembic offline context.

    Offline mode still renders SQL from the configured URL, so a placeholder is
    supplied. It points at a reserved non-routable name and is never dialled,
    because `context.configure` and `context.run_migrations` are stubs.
    """
    fake = mock.MagicMock()
    fake.config.config_file_name = None
    fake.is_offline_mode.return_value = True
    spec = importlib.util.spec_from_file_location("_fp_migrations_env", ENV_PATH)
    module = importlib.util.module_from_spec(spec)
    placeholder = {
        "DATABASE_URL": "postgresql://placeholder:placeholder@placeholder.invalid:5432/placeholder",
        "FLUENT_PATH_ENVIRONMENT": "development",
    }
    with mock.patch.object(alembic, "context", fake), \
            mock.patch.dict(os.environ, placeholder, clear=False):
        spec.loader.exec_module(module)
    return module


def code_without_comments_or_strings(path: Path) -> str:
    """Return the executable source, with comments and string literals removed.

    A naive substring search over the raw file would trip over the very words it
    is looking for when they appear in a docstring explaining the hazard, so the
    check is applied to code only.
    """
    source = path.read_text(encoding="utf-8")
    kept = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        kept.append(token.string)
    return " ".join(kept)


class MigrationTlsStaticTests(unittest.TestCase):
    def test_env_module_exists_and_parses(self):
        ast.parse(ENV_PATH.read_text(encoding="utf-8"))

    def test_no_tls_downgrade_appears_in_executable_code(self):
        code = code_without_comments_or_strings(ENV_PATH)
        for token in FORBIDDEN_IN_CODE:
            with self.subTest(token=token):
                self.assertNotIn(token, code)

    def test_env_module_uses_the_projects_verified_tls_helper(self):
        code = code_without_comments_or_strings(ENV_PATH)
        self.assertIn("build_verified_ssl_context", code)
        self.assertIn("strip_tls_query_parameters", code)

    def test_env_module_does_not_pass_ssl_query_parameters_through(self):
        # The URL handed to Alembic must already have ssl* removed, so a query
        # string cannot reintroduce a downgrade after validation.
        code = code_without_comments_or_strings(ENV_PATH)
        self.assertNotIn("?sslmode", code)
        self.assertNotIn("&sslmode", code)


class MigrationTlsBehaviourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = load_env_module()

    def _url(self, value, environment="development"):
        return mock.patch.dict(os.environ, {
            "DATABASE_URL": value,
            "FLUENT_PATH_ENVIRONMENT": environment,
        }, clear=False)

    def test_ssl_query_parameters_are_stripped_from_the_migration_url(self):
        for suffix in ("?sslmode=disable", "?sslmode=require",
                       "?sslmode=verify-full&application_name=x"):
            with self.subTest(suffix=suffix):
                with self._url("postgresql://u:p@db.example.test:5432/app" + suffix):
                    result = self.env.database_url()
                self.assertNotIn("sslmode", result)
                self.assertNotIn("ssl", result.lower().split("@")[-1].split("?")[-1])

    def test_database_url_is_still_normalized_to_the_asyncpg_driver(self):
        for supplied, expected_scheme in (
            ("postgres://u:p@db.example.test:5432/app", "postgresql+asyncpg://"),
            ("postgresql://u:p@db.example.test:5432/app", "postgresql+asyncpg://"),
            ("postgresql+asyncpg://u:p@db.example.test:5432/app", "postgresql+asyncpg://"),
        ):
            with self.subTest(supplied=supplied):
                with self._url(supplied):
                    result = self.env.database_url()
                self.assertTrue(result.startswith(expected_scheme), result)

    def test_staging_and_production_migrations_require_verified_tls(self):
        for environment in VERIFIED_TLS_ENVIRONMENTS:
            with self.subTest(environment=environment):
                with mock.patch.dict(os.environ, {
                    "DATABASE_URL": "postgresql://u:p@db.example.test:5432/app",
                    "FLUENT_PATH_ENVIRONMENT": environment,
                }, clear=False):
                    arguments = self.env.engine_connect_arguments()
                self.assertIn("ssl", arguments)
                context = arguments["ssl"]
                self.assertIsInstance(context, ssl.SSLContext)
                self.assertIs(context.verify_mode, ssl.CERT_REQUIRED)
                self.assertIs(context.check_hostname, True)

    def test_development_and_test_migrations_do_not_force_tls(self):
        # A disposable local database has no pinned root to present, so these
        # environments must stay usable. They also never carry production data.
        for environment in ("development", "test"):
            with self.subTest(environment=environment):
                with mock.patch.dict(os.environ, {
                    "DATABASE_URL": "postgresql://u:p@127.0.0.1:5432/test",
                    "FLUENT_PATH_ENVIRONMENT": environment,
                }, clear=False):
                    self.assertIsNone(self.env.engine_connect_arguments())

    def test_a_custom_ssl_override_is_refused(self):
        for environment in VERIFIED_TLS_ENVIRONMENTS:
            with self.subTest(environment=environment):
                with mock.patch.dict(os.environ, {
                    "DATABASE_URL": "postgresql://u:p@db.example.test:5432/app",
                    "FLUENT_PATH_ENVIRONMENT": environment,
                    "ALEMBIC_SSL_OVERRIDE": "CERT_NONE",
                }, clear=False):
                    with self.assertRaises(Exception) as caught:
                        self.env.engine_connect_arguments()
                self.assertNotIn("CERT_NONE", str(caught.exception))

    def test_missing_database_url_is_still_refused(self):
        with mock.patch.dict(os.environ, {"FLUENT_PATH_ENVIRONMENT": "development"},
                             clear=False):
            os.environ.pop("DATABASE_URL", None)
            with self.assertRaises(Exception):
                self.env.database_url()


class MigrationTlsEnvironmentTests(unittest.TestCase):
    """The pinned root must exist and keep its recorded fingerprint."""

    def test_pinned_root_certificate_is_present_and_matches(self):
        from db.session import SUPABASE_ROOT_CA, SUPABASE_ROOT_CA_SHA256, pinned_root_ca_fingerprint
        self.assertTrue(SUPABASE_ROOT_CA.is_file(), SUPABASE_ROOT_CA)
        self.assertEqual(pinned_root_ca_fingerprint(SUPABASE_ROOT_CA),
                         SUPABASE_ROOT_CA_SHA256)

    def test_verified_context_requires_certificates_and_hostname(self):
        from db.session import build_verified_ssl_context
        context = build_verified_ssl_context()
        self.assertIs(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertIs(context.check_hostname, True)
        self.assertEqual(len(context.get_ca_certs()), 1)


if __name__ == "__main__":
    sys.exit(unittest.main() or 0)