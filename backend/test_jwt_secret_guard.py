"""Startup guard for FLUENT_PATH_JWT_SECRET.

The guard runs at import time, so it cannot be exercised by patching a module
attribute the way the request-level suites do. Each case therefore launches a
throwaway interpreter and asserts on how it exits.

The Postgres backend binds its engine lazily, so supplying a placeholder
loopback DATABASE_URL satisfies the staging/production persistence
precondition without opening a socket to anything.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

BACKEND_DIRECTORY = Path(__file__).resolve().parent
DEVELOPMENT_FALLBACK = "fluent-path-development-secret-change-me"
MINIMUM_LENGTH = 32
PLACEHOLDER_LOOPBACK_URL = "postgresql+asyncpg://offline:offline@127.0.0.1:5432/offline_guard_probe"
TEST_ONLY_STRONG_SECRET = "a4-test-only-strong-secret-0123456789abcdef"
#: A valid allowlist is supplied for every non-development case so this suite
#: keeps isolating the JWT guard. Staging and production also refuse to start
#: without FLUENT_PATH_CORS_ORIGINS, which would otherwise mask the secret check.
TEST_ONLY_CORS_ORIGIN = "https://app.synthetic-a4-test.invalid"
JWT_GUARD_SIGNATURE = "requires a strong FLUENT_PATH_JWT_SECRET"


class JwtSecretStartupGuardTests(unittest.TestCase):
    #: Names this suite controls. They are cleared from the inherited
    #: environment so an operator's own settings cannot decide a test outcome,
    #: while everything Windows needs to boot the interpreter is preserved.
    CONTROLLED_VARIABLES = (
        "FLUENT_PATH_ENVIRONMENT",
        "FLUENT_PATH_JWT_SECRET",
        "FLUENT_PATH_CORS_ORIGINS",
        "FLUENT_PATH_PERSISTENCE",
        "DATABASE_URL",
    )

    def start_server(self, **environment):
        child_environment = dict(os.environ)
        for name in self.CONTROLLED_VARIABLES:
            child_environment.pop(name, None)
        if environment.get("FLUENT_PATH_ENVIRONMENT", "development") != "development":
            child_environment["FLUENT_PATH_CORS_ORIGINS"] = TEST_ONLY_CORS_ORIGIN
        for name, value in environment.items():
            if value is not None:
                child_environment[name] = value
        return subprocess.run(
            [sys.executable, "-c", "import server"],
            cwd=str(BACKEND_DIRECTORY),
            env=child_environment,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def assertRefused(self, result):
        combined = f"{result.stdout}{result.stderr}"
        self.assertNotEqual(result.returncode, 0, combined)
        self.assertIn(JWT_GUARD_SIGNATURE, combined)

    def assertStarts(self, result):
        combined = f"{result.stdout}{result.stderr}"
        self.assertEqual(result.returncode, 0, combined)

    # --- development keeps the existing fallback -------------------------------

    def test_development_starts_without_a_configured_secret(self):
        self.assertStarts(self.start_server(FLUENT_PATH_ENVIRONMENT="development"))

    def test_development_starts_with_the_development_fallback_secret(self):
        self.assertStarts(self.start_server(
            FLUENT_PATH_ENVIRONMENT="development",
            FLUENT_PATH_JWT_SECRET=DEVELOPMENT_FALLBACK,
        ))

    def test_unset_environment_defaults_to_development_and_starts(self):
        self.assertStarts(self.start_server())

    def test_development_starts_with_a_short_secret(self):
        self.assertStarts(self.start_server(
            FLUENT_PATH_ENVIRONMENT="development",
            FLUENT_PATH_JWT_SECRET="short",
        ))

    # --- staging fails closed --------------------------------------------------

    def test_staging_is_refused_without_a_configured_secret(self):
        self.assertRefused(self.start_server(
            FLUENT_PATH_ENVIRONMENT="staging",
            DATABASE_URL=PLACEHOLDER_LOOPBACK_URL,
        ))

    def test_staging_is_refused_with_the_development_fallback_secret(self):
        self.assertRefused(self.start_server(
            FLUENT_PATH_ENVIRONMENT="staging",
            DATABASE_URL=PLACEHOLDER_LOOPBACK_URL,
            FLUENT_PATH_JWT_SECRET=DEVELOPMENT_FALLBACK,
        ))

    def test_staging_is_refused_with_a_secret_below_the_minimum_length(self):
        self.assertRefused(self.start_server(
            FLUENT_PATH_ENVIRONMENT="staging",
            DATABASE_URL=PLACEHOLDER_LOOPBACK_URL,
            FLUENT_PATH_JWT_SECRET="a" * (MINIMUM_LENGTH - 1),
        ))

    # --- production fails closed ----------------------------------------------

    def test_production_is_refused_without_a_configured_secret(self):
        self.assertRefused(self.start_server(
            FLUENT_PATH_ENVIRONMENT="production",
            DATABASE_URL=PLACEHOLDER_LOOPBACK_URL,
        ))

    def test_production_is_refused_with_the_development_fallback_secret(self):
        self.assertRefused(self.start_server(
            FLUENT_PATH_ENVIRONMENT="production",
            DATABASE_URL=PLACEHOLDER_LOOPBACK_URL,
            FLUENT_PATH_JWT_SECRET=DEVELOPMENT_FALLBACK,
        ))

    def test_production_is_refused_with_a_secret_below_the_minimum_length(self):
        self.assertRefused(self.start_server(
            FLUENT_PATH_ENVIRONMENT="production",
            DATABASE_URL=PLACEHOLDER_LOOPBACK_URL,
            FLUENT_PATH_JWT_SECRET="a" * (MINIMUM_LENGTH - 1),
        ))

    # --- any other non-development environment is also covered ----------------

    def test_test_environment_is_refused_without_a_configured_secret(self):
        self.assertRefused(self.start_server(
            FLUENT_PATH_ENVIRONMENT="test",
            FLUENT_PATH_PERSISTENCE="json",
            DATABASE_URL=PLACEHOLDER_LOOPBACK_URL,
        ))

    def test_unknown_environment_name_is_refused_without_a_configured_secret(self):
        self.assertRefused(self.start_server(
            FLUENT_PATH_ENVIRONMENT="preview",
            FLUENT_PATH_PERSISTENCE="json",
            DATABASE_URL=PLACEHOLDER_LOOPBACK_URL,
        ))

    # --- the boundary and the happy path --------------------------------------

    def test_secret_exactly_at_the_minimum_length_is_accepted(self):
        self.assertStarts(self.start_server(
            FLUENT_PATH_ENVIRONMENT="staging",
            DATABASE_URL=PLACEHOLDER_LOOPBACK_URL,
            FLUENT_PATH_JWT_SECRET="b" * MINIMUM_LENGTH,
        ))

    def test_staging_starts_with_a_strong_configured_secret(self):
        self.assertStarts(self.start_server(
            FLUENT_PATH_ENVIRONMENT="staging",
            DATABASE_URL=PLACEHOLDER_LOOPBACK_URL,
            FLUENT_PATH_JWT_SECRET=TEST_ONLY_STRONG_SECRET,
        ))

    def test_production_starts_with_a_strong_configured_secret(self):
        self.assertStarts(self.start_server(
            FLUENT_PATH_ENVIRONMENT="production",
            DATABASE_URL=PLACEHOLDER_LOOPBACK_URL,
            FLUENT_PATH_JWT_SECRET=TEST_ONLY_STRONG_SECRET,
        ))

    def test_refusal_message_never_contains_the_secret_value(self):
        secret = "a4-test-only-strong-secret-0123456789abcdef"
        refused = self.start_server(
            FLUENT_PATH_ENVIRONMENT="staging",
            DATABASE_URL=PLACEHOLDER_LOOPBACK_URL,
            FLUENT_PATH_JWT_SECRET="z" * 8,
        )
        self.assertRefused(refused)
        self.assertNotIn("z" * 8, f"{refused.stdout}{refused.stderr}")
        accepted = self.start_server(
            FLUENT_PATH_ENVIRONMENT="staging",
            DATABASE_URL=PLACEHOLDER_LOOPBACK_URL,
            FLUENT_PATH_JWT_SECRET=secret,
        )
        self.assertStarts(accepted)
        self.assertNotIn(secret, f"{accepted.stdout}{accepted.stderr}")

    def test_fallback_constant_is_never_accepted_outside_development(self):
        for environment in ("staging", "production"):
            with self.subTest(environment=environment):
                self.assertRefused(self.start_server(
                    FLUENT_PATH_ENVIRONMENT=environment,
                    DATABASE_URL=PLACEHOLDER_LOOPBACK_URL,
                    FLUENT_PATH_JWT_SECRET=DEVELOPMENT_FALLBACK,
                ))


if __name__ == "__main__":
    unittest.main()