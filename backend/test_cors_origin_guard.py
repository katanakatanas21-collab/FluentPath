"""Startup gate for the CORS allowlist.

The allowlist is resolved at import time, before the middleware is installed, so
an unsafe value has to stop the process rather than degrade quietly. Each case
therefore launches a throwaway interpreter and asserts on how it exits.

The Postgres backend binds its engine lazily, so a placeholder loopback
DATABASE_URL satisfies the staging/production persistence precondition without
opening a socket to anything.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

BACKEND_DIRECTORY = Path(__file__).resolve().parent
PLACEHOLDER_LOOPBACK_URL = (
    "postgresql+asyncpg://offline:offline@127.0.0.1:5432/offline_cors_probe"
)
TEST_ONLY_STRONG_SECRET = "a3-test-only-strong-secret-0123456789abcdef"
TEST_ONLY_FRONTEND_ORIGIN = "https://app.synthetic-a3-test.invalid"
TEST_ONLY_SECOND_ORIGIN = "https://admin.synthetic-a3-test.invalid"
CORS_REFUSAL_SIGNATURE = "FLUENT_PATH_CORS_ORIGINS"
PROBE = (
    "import server, sys; "
    "sys.stderr.write('ORIGINS=' + '|'.join(server.allowed_frontend_origins))"
)

#: Everything this suite controls, cleared from the inherited environment so an
#: operator's own settings cannot decide an outcome.
CONTROLLED_VARIABLES = (
    "FLUENT_PATH_ENVIRONMENT",
    "FLUENT_PATH_JWT_SECRET",
    "FLUENT_PATH_CORS_ORIGINS",
    "FLUENT_PATH_PERSISTENCE",
    "DATABASE_URL",
)

#: Values that must never become a non-development allowlist.
UNSAFE_ALLOWLISTS = (
    ("unset", None),
    ("empty string", ""),
    ("whitespace only", "   "),
    ("commas and spaces only", " , , "),
    ("a bare wildcard", "*"),
    ("a wildcard mixed with a real origin", f"*,{TEST_ONLY_FRONTEND_ORIGIN}"),
    ("localhost", "http://localhost:3000"),
    ("127.0.0.1", "http://127.0.0.1:3000"),
    ("::1", "http://[::1]:3000"),
    ("0.0.0.0", "http://0.0.0.0:3000"),
    (
        "loopback mixed with a real origin",
        f"http://localhost:3000,{TEST_ONLY_FRONTEND_ORIGIN}",
    ),
    ("a bare hostname with no scheme", "app.example.invalid"),
    ("a protocol-relative origin", "//app.example.invalid"),
    ("free text", "not an origin"),
    ("a javascript scheme", "javascript:alert(1)"),
)


def run_backend(**environment):
    child = dict(os.environ)
    for name in CONTROLLED_VARIABLES:
        child.pop(name, None)
    for name, value in environment.items():
        if value is not None:
            child[name] = value
    return subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=str(BACKEND_DIRECTORY),
        env=child,
        capture_output=True,
        text=True,
        timeout=120,
    )


def staging_and_production(**extra):
    return run_backend(
        FLUENT_PATH_JWT_SECRET=TEST_ONLY_STRONG_SECRET,
        DATABASE_URL=PLACEHOLDER_LOOPBACK_URL,
        **extra,
    )


class DevelopmentCorsDefaultsTests(unittest.TestCase):
    """Development must keep working with no configuration at all."""

    def test_unset_environment_keeps_the_two_localhost_defaults(self):
        result = run_backend(FLUENT_PATH_ENVIRONMENT="development")
        self.assertEqual(result.returncode, 0, f"{result.stdout}{result.stderr}")
        self.assertIn("ORIGINS=http://localhost:3000|http://127.0.0.1:3000", result.stderr)

    def test_no_environment_variable_at_all_keeps_the_defaults(self):
        result = run_backend()
        self.assertEqual(result.returncode, 0, f"{result.stdout}{result.stderr}")
        self.assertIn("ORIGINS=http://localhost:3000|http://127.0.0.1:3000", result.stderr)

    def test_development_accepts_an_explicit_localhost_allowlist(self):
        result = run_backend(
            FLUENT_PATH_ENVIRONMENT="development",
            FLUENT_PATH_CORS_ORIGINS="http://localhost:3000,http://127.0.0.1:3000",
        )
        self.assertEqual(result.returncode, 0, f"{result.stdout}{result.stderr}")

    def test_development_still_accepts_a_loopback_allowlist(self):
        result = run_backend(
            FLUENT_PATH_ENVIRONMENT="development",
            FLUENT_PATH_CORS_ORIGINS="http://localhost:3000",
        )
        self.assertEqual(result.returncode, 0, f"{result.stdout}{result.stderr}")

    def test_development_tolerates_an_empty_value_by_falling_back(self):
        result = run_backend(FLUENT_PATH_ENVIRONMENT="development", FLUENT_PATH_CORS_ORIGINS="")
        self.assertEqual(result.returncode, 0, f"{result.stdout}{result.stderr}")
        self.assertIn("ORIGINS=http://localhost:3000|http://127.0.0.1:3000", result.stderr)


class StagingCorsAllowlistTests(unittest.TestCase):
    def test_staging_refuses_every_unsafe_allowlist(self):
        for label, value in UNSAFE_ALLOWLISTS:
            with self.subTest(allowlist=label):
                result = staging_and_production(
                    FLUENT_PATH_ENVIRONMENT="staging",
                    FLUENT_PATH_CORS_ORIGINS=value,
                )
                self.assertNotEqual(result.returncode, 0, f"{label} should refuse")
                self.assertIn(CORS_REFUSAL_SIGNATURE, f"{result.stdout}{result.stderr}")

    def test_staging_accepts_a_synthetic_https_origin(self):
        result = staging_and_production(
            FLUENT_PATH_ENVIRONMENT="staging",
            FLUENT_PATH_CORS_ORIGINS=TEST_ONLY_FRONTEND_ORIGIN,
        )
        self.assertEqual(result.returncode, 0, f"{result.stdout}{result.stderr}")
        self.assertIn(f"ORIGINS={TEST_ONLY_FRONTEND_ORIGIN}", result.stderr)

    def test_staging_accepts_several_synthetic_origins(self):
        result = staging_and_production(
            FLUENT_PATH_ENVIRONMENT="staging",
            FLUENT_PATH_CORS_ORIGINS=f"{TEST_ONLY_FRONTEND_ORIGIN},{TEST_ONLY_SECOND_ORIGIN}",
        )
        self.assertEqual(result.returncode, 0, f"{result.stdout}{result.stderr}")
        self.assertIn(
            f"ORIGINS={TEST_ONLY_FRONTEND_ORIGIN}|{TEST_ONLY_SECOND_ORIGIN}", result.stderr
        )

    def test_staging_trims_surrounding_whitespace_per_origin(self):
        result = staging_and_production(
            FLUENT_PATH_ENVIRONMENT="staging",
            FLUENT_PATH_CORS_ORIGINS=f"  {TEST_ONLY_FRONTEND_ORIGIN} , {TEST_ONLY_SECOND_ORIGIN}  ",
        )
        self.assertEqual(result.returncode, 0, f"{result.stdout}{result.stderr}")
        self.assertIn(
            f"ORIGINS={TEST_ONLY_FRONTEND_ORIGIN}|{TEST_ONLY_SECOND_ORIGIN}", result.stderr
        )


class ProductionCorsAllowlistTests(unittest.TestCase):
    def test_production_refuses_every_unsafe_allowlist(self):
        for label, value in UNSAFE_ALLOWLISTS:
            with self.subTest(allowlist=label):
                result = staging_and_production(
                    FLUENT_PATH_ENVIRONMENT="production",
                    FLUENT_PATH_CORS_ORIGINS=value,
                )
                self.assertNotEqual(result.returncode, 0, f"{label} should refuse")
                self.assertIn(CORS_REFUSAL_SIGNATURE, f"{result.stdout}{result.stderr}")

    def test_production_accepts_a_synthetic_https_origin(self):
        result = staging_and_production(
            FLUENT_PATH_ENVIRONMENT="production",
            FLUENT_PATH_CORS_ORIGINS=TEST_ONLY_FRONTEND_ORIGIN,
        )
        self.assertEqual(result.returncode, 0, f"{result.stdout}{result.stderr}")
        self.assertIn(f"ORIGINS={TEST_ONLY_FRONTEND_ORIGIN}", result.stderr)


class CorsRefusalHygieneTests(unittest.TestCase):
    def test_refusal_never_echoes_the_jwt_secret(self):
        secret = "a3-test-only-strong-secret-0123456789abcdef"
        result = staging_and_production(
            FLUENT_PATH_ENVIRONMENT="staging",
            FLUENT_PATH_CORS_ORIGINS="*",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(secret, f"{result.stdout}{result.stderr}")

    def test_refusal_never_echoes_the_database_url(self):
        result = staging_and_production(
            FLUENT_PATH_ENVIRONMENT="staging",
            FLUENT_PATH_CORS_ORIGINS="*",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(PLACEHOLDER_LOOPBACK_URL, f"{result.stdout}{result.stderr}")

    def test_refusal_names_no_hard_coded_domain(self):
        result = staging_and_production(FLUENT_PATH_ENVIRONMENT="staging")
        self.assertNotEqual(result.returncode, 0)
        message = f"{result.stdout}{result.stderr}"
        self.assertIn(CORS_REFUSAL_SIGNATURE, message)
        self.assertIn("hard-coded", message)

    def test_refusal_names_only_the_offending_allowlist_value(self):
        result = staging_and_production(
            FLUENT_PATH_ENVIRONMENT="staging",
            FLUENT_PATH_CORS_ORIGINS="http://localhost:3000",
        )
        message = f"{result.stdout}{result.stderr}"
        self.assertIn("http://localhost:3000", message)
        self.assertNotIn("Origin", message.split("FLUENT_PATH_CORS_ORIGINS", 1)[0])


if __name__ == "__main__":
    unittest.main()