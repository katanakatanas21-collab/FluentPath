"""Async SQLAlchemy engine factory used by the PostgreSQL persistence backend."""

import hashlib
import ssl
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db_config import DatabaseConfigurationError, DatabaseSettings

CERT_DIRECTORY = Path(__file__).resolve().parent / "certs"
SUPABASE_ROOT_CA = CERT_DIRECTORY / "supabase_root_2021_ca.pem"
SUPABASE_ROOT_CA_SHA256 = "807025AD50D4ED219D2C9C7D299C004F824EB00CF7F65AFEF607D07B72E6CAFA"
VERIFIED_TLS_ENVIRONMENTS = frozenset({"staging", "production"})


def normalize_database_url(url: str) -> str:
    """Accept the provider spellings of a PostgreSQL URL and return an asyncpg one."""
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    return url


def requires_verified_tls(settings: DatabaseSettings) -> bool:
    """Staging and production must never connect without certificate verification."""
    return (settings.environment or "").strip().lower() in VERIFIED_TLS_ENVIRONMENTS


def strip_tls_query_parameters(url: str) -> str:
    """Drop ssl* query parameters.

    Transport security is decided here, not by configuration text, so a URL
    cannot quietly ask for an unverified connection.
    """
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    kept = [pair for pair in pairs if not pair[0].lower().startswith("ssl")]
    if len(kept) == len(pairs):
        return url
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def pinned_root_ca_fingerprint(path: Path = SUPABASE_ROOT_CA) -> str:
    try:
        der = ssl.PEM_cert_to_DER_cert(Path(path).read_text(encoding="ascii"))
    except FileNotFoundError as exc:
        raise DatabaseConfigurationError(
            f"The pinned database root certificate is missing: {Path(path).name}"
        ) from exc
    except (OSError, ValueError) as exc:
        raise DatabaseConfigurationError(
            f"The pinned database root certificate cannot be read: {Path(path).name}"
        ) from exc
    return hashlib.sha256(der).hexdigest().upper()


def build_verified_ssl_context(path: Path = SUPABASE_ROOT_CA) -> ssl.SSLContext:
    """Build an SSL context that anchors on the pinned root and verifies the hostname.

    The pooler presents a private three-certificate chain rooted at
    "Supabase Root 2021 CA", a self-signed authority that is not in the Windows
    or certifi trust stores. Encryption without verification is not acceptable,
    so the root is pinned by fingerprint and the hostname is checked against it.

    Python 3.13 and newer turn on ``VERIFY_X509_STRICT`` inside
    ``create_default_context``. That flag demands the RFC 5280 conformance
    extensions (keyUsage, basicConstraints) that this legacy private root does
    not carry, and it rejects the chain before the signature or hostname is ever
    examined. Strict conformance checking is therefore relaxed for this pinned
    anchor only. Chain construction, signature validation and hostname
    verification all stay enabled, which is what actually protects the
    connection; ``build_verified_ssl_context`` and the TLS regression tests
    assert exactly that.
    """
    actual = pinned_root_ca_fingerprint(path)
    if actual != SUPABASE_ROOT_CA_SHA256:
        raise DatabaseConfigurationError(
            "The pinned database root certificate does not match the expected SHA-256 fingerprint"
        )
    context = ssl.create_default_context(cafile=str(path))
    strict = getattr(ssl, "VERIFY_X509_STRICT", 0)
    if strict:
        context.verify_flags &= ~strict
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    if context.check_hostname is not True or context.verify_mode != ssl.CERT_REQUIRED:
        raise DatabaseConfigurationError("Refusing to build an SSL context without full verification")
    return context


def create_engine_and_session_factory(
    settings: DatabaseSettings,
    *,
    pool_size: int = 5,
    max_overflow: int = 5,
    connect_args: dict | None = None,
):
    """Return an async engine together with its session factory.

    The engine is returned as well so the owner can dispose of it on shutdown;
    an engine created inside one event loop must be used and closed from that
    same loop.
    """
    if not settings.database_url:
        raise ValueError("DATABASE_URL is required to create a database engine")
    url = strip_tls_query_parameters(normalize_database_url(settings.database_url))
    arguments = dict(connect_args or {})
    if requires_verified_tls(settings):
        if "ssl" in arguments:
            raise DatabaseConfigurationError(
                "Verified TLS is mandatory in this environment; a custom ssl argument is not accepted"
            )
        arguments["ssl"] = build_verified_ssl_context()
    engine_kwargs = {
        "pool_size": pool_size,
        "max_overflow": max_overflow,
        "pool_pre_ping": True,
    }
    if arguments:
        engine_kwargs["connect_args"] = arguments
    engine = create_async_engine(url, **engine_kwargs)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def create_session_factory(settings: DatabaseSettings, *, pool_size: int = 5, max_overflow: int = 5):
    return create_engine_and_session_factory(settings, pool_size=pool_size, max_overflow=max_overflow)[1]