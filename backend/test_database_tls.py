"""Transport security tests for the PostgreSQL connection layer.

These run offline. They assert that a staging or production connection cannot be
made without a verified certificate chain and a hostname check, and that the
pinned root certificate is exactly the expected one.

The Supabase pooler terminates TLS with a private three-certificate chain rooted
at "Supabase Root 2021 CA". That authority is self-signed and absent from the
Windows and certifi trust stores, so it has to be pinned. Pinning it by
fingerprint keeps verification enabled; the earlier connection code used
``sslmode=require``, which asyncpg documents as "no server certificate or host
verification", and that is what these tests exist to prevent from returning.
"""

import hashlib
import ssl
import unittest
from pathlib import Path
from unittest import mock

from db import session as session_module
from db.session import (
    SUPABASE_ROOT_CA,
    SUPABASE_ROOT_CA_SHA256,
    build_verified_ssl_context,
    create_engine_and_session_factory,
    normalize_database_url,
    pinned_root_ca_fingerprint,
    requires_verified_tls,
    strip_tls_query_parameters,
)
from db_config import DatabaseConfigurationError, DatabaseSettings

HOST = "aws-0-ap-northeast-1.pooler.supabase.com"
URL = f"postgresql://postgres.example:{HOST}:5432/postgres"
STRICT = getattr(ssl, "VERIFY_X509_STRICT", 0)


def capture_engine(**kwargs):
    """Build settings that would reach create_async_engine, capturing its arguments."""
    settings = DatabaseSettings(
        database_url=kwargs.pop("database_url", URL),
        environment=kwargs.pop("environment", "staging"),
    )
    with mock.patch.object(session_module, "create_async_engine") as factory:
        factory.return_value = mock.Mock()
        create_engine_and_session_factory(settings, **kwargs)
    if not factory.call_args:
        raise AssertionError("create_async_engine was never called")
    args, engine_kwargs = factory.call_args
    return args[0], engine_kwargs


class PinnedRootCertificateTests(unittest.TestCase):
    def test_the_pinned_root_certificate_is_present(self):
        self.assertTrue(SUPABASE_ROOT_CA.is_file(), f"missing {SUPABASE_ROOT_CA}")

    def test_the_pinned_root_certificate_matches_the_expected_fingerprint(self):
        self.assertEqual(pinned_root_ca_fingerprint(), SUPABASE_ROOT_CA_SHA256)

    def test_the_fingerprint_is_the_sha256_of_the_certificate_der(self):
        der = ssl.PEM_cert_to_DER_cert(SUPABASE_ROOT_CA.read_text(encoding="ascii"))
        self.assertEqual(hashlib.sha256(der).hexdigest().upper(), SUPABASE_ROOT_CA_SHA256)

    def test_the_pinned_certificate_is_the_supabase_root_authority(self):
        info = ssl._ssl._test_decode_cert(str(SUPABASE_ROOT_CA))
        subject = dict(item for group in info["subject"] for item in group)
        issuer = dict(item for group in info["issuer"] for item in group)
        self.assertEqual(subject["commonName"], "Supabase Root 2021 CA")
        self.assertEqual(subject["organizationName"], "Supabase Inc")
        self.assertEqual(subject, issuer, "the pinned anchor must be self-issued")

    def test_a_different_certificate_is_rejected(self):
        with self.subTest("wrong fingerprint"):
            with mock.patch.object(session_module, "SUPABASE_ROOT_CA_SHA256", "00" * 32):
                with self.assertRaises(DatabaseConfigurationError):
                    build_verified_ssl_context()

    def test_a_missing_certificate_is_rejected(self):
        with self.assertRaises(DatabaseConfigurationError):
            pinned_root_ca_fingerprint(SUPABASE_ROOT_CA.parent / "does-not-exist.pem")


class VerifiedSslContextTests(unittest.TestCase):
    def setUp(self):
        self.context = build_verified_ssl_context()

    def test_certificate_verification_is_required(self):
        self.assertEqual(self.context.verify_mode, ssl.CERT_REQUIRED)

    def test_hostname_verification_is_required(self):
        self.assertTrue(self.context.check_hostname)

    def test_verification_cannot_be_switched_off_on_the_returned_context(self):
        with self.assertRaises(ValueError):
            self.context.verify_mode = ssl.CERT_NONE

    def test_legacy_strict_conformance_checking_is_relaxed_but_verification_is_not(self):
        # Python 3.13+ enables VERIFY_X509_STRICT by default and this private root
        # carries no keyUsage/basicConstraints extensions. Only that extra
        # conformance check is relaxed; chain and hostname checks stay on.
        if STRICT:
            self.assertFalse(self.context.verify_flags & STRICT)
        self.assertEqual(self.context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(self.context.check_hostname)

    def test_the_pinned_certificate_is_the_only_configured_anchor(self):
        anchors = self.context.get_ca_certs()
        self.assertEqual(len(anchors), 1, "exactly the pinned root must be trusted")
        subject = dict(item for group in anchors[0]["subject"] for item in group)
        self.assertEqual(subject["commonName"], "Supabase Root 2021 CA")


class TlsQueryParameterTests(unittest.TestCase):
    def test_ssl_parameters_are_removed_from_the_url(self):
        for parameter in ("sslmode", "sslrootcert", "sslcert", "sslkey", "sslcrl", "sslpassword"):
            with self.subTest(parameter=parameter):
                stripped = strip_tls_query_parameters(f"{URL}?{parameter}=whatever")
                self.assertNotIn(parameter, stripped)

    def test_other_query_parameters_survive(self):
        stripped = strip_tls_query_parameters(f"{URL}?application_name=app&sslmode=require&pool_size=3")
        self.assertIn("application_name=app", stripped)
        self.assertIn("pool_size=3", stripped)
        self.assertNotIn("sslmode", stripped)

    def test_stripping_is_idempotent(self):
        once = strip_tls_query_parameters(f"{URL}?sslmode=require&application_name=app")
        self.assertEqual(strip_tls_query_parameters(once), once)

    def test_a_url_without_ssl_parameters_is_unchanged(self):
        self.assertEqual(strip_tls_query_parameters(URL), URL)

    def test_credentials_are_not_mangled_by_stripping(self):
        stripped = strip_tls_query_parameters(f"{URL}?sslmode=require")
        self.assertIn("postgres.example", stripped)
        self.assertIn(f"{HOST}:5432", stripped)


class VerifiedTlsRequirementTests(unittest.TestCase):
    def test_staging_and_production_require_verified_tls(self):
        for environment in ("staging", "production", "STAGING", " Production "):
            with self.subTest(environment=environment):
                self.assertTrue(requires_verified_tls(DatabaseSettings(URL, environment)))

    def test_development_and_test_do_not_force_verified_tls(self):
        for environment in ("development", "test", ""):
            with self.subTest(environment=environment):
                self.assertFalse(requires_verified_tls(DatabaseSettings(URL, environment)))

    def test_staging_engine_is_built_with_a_verified_ssl_context(self):
        _, engine_kwargs = capture_engine(environment="staging")
        context = engine_kwargs["connect_args"]["ssl"]
        self.assertIsInstance(context, ssl.SSLContext)
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_development_engine_is_not_forced_into_verified_tls(self):
        _, engine_kwargs = capture_engine(environment="development")
        self.assertNotIn("connect_args", engine_kwargs)

    def test_a_caller_cannot_supply_an_unverified_context_in_staging(self):
        for environment in ("staging", "production"):
            with self.subTest(environment=environment):
                with self.assertRaises(DatabaseConfigurationError):
                    capture_engine(
                        environment=environment,
                        connect_args={"ssl": ssl.create_default_context()},
                    )

    def test_a_caller_cannot_supply_a_disabled_verification_context_in_staging(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with self.assertRaises(DatabaseConfigurationError):
            capture_engine(environment="staging", connect_args={"ssl": context})


class DowngradeResistanceTests(unittest.TestCase):
    """A URL must not be able to weaken transport security."""

    def test_sslmode_require_in_the_url_cannot_reach_the_driver(self):
        url, _ = capture_engine(environment="staging", database_url=f"{URL}?sslmode=require")
        self.assertNotIn("sslmode", url)

    def test_sslmode_disable_in_the_url_cannot_reach_the_driver(self):
        url, engine_kwargs = capture_engine(environment="staging", database_url=f"{URL}?sslmode=disable")
        self.assertNotIn("sslmode", url)
        self.assertTrue(engine_kwargs["connect_args"]["ssl"].check_hostname)

    def test_a_sslrootcert_override_in_the_url_cannot_reach_the_driver(self):
        url, _ = capture_engine(environment="staging", database_url=f"{URL}?sslrootcert=/tmp/other.pem")
        self.assertNotIn("sslrootcert", url)

    def test_verification_still_holds_after_a_downgrade_attempt(self):
        _, engine_kwargs = capture_engine(environment="staging", database_url=f"{URL}?sslmode=disable&sslmode=require")
        context = engine_kwargs["connect_args"]["ssl"]
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)


class NoDowngradeEscapeHatchTests(unittest.TestCase):
    """Guard against a future edit reintroducing an unverified connection."""

    def test_the_connection_module_contains_no_unverified_tls_settings(self):
        source = Path(session_module.__file__).read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines()
            if not line.strip().startswith("#")
        )
        for forbidden in ("CERT_NONE", "verify=False", "sslmode=disable", "check_hostname = False"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, code)

    def test_the_pinned_ca_lives_in_the_repository_not_in_a_temporary_path(self):
        self.assertTrue(SUPABASE_ROOT_CA.is_file())
        self.assertNotIn("temp", str(SUPABASE_ROOT_CA).lower())


class UrlNormalisationTests(unittest.TestCase):
    def test_provider_spellings_become_asyncpg_urls(self):
        for spelling in ("postgres://", "postgresql://"):
            with self.subTest(spelling=spelling):
                self.assertEqual(
                    normalize_database_url(f"{spelling}u:p@h:5432/d"),
                    "postgresql+asyncpg://u:p@h:5432/d",
                )

    def test_an_already_normalised_url_is_unchanged(self):
        already = "postgresql+asyncpg://u:p@h:5432/d"
        self.assertEqual(normalize_database_url(already), already)


if __name__ == "__main__":
    unittest.main()