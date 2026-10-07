"""Database URL validation helpers; importing this module never connects."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit


class DatabaseConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class DatabaseSettings:
    database_url: str | None
    environment: str


def _validate_postgres_url(value: str | None, variable: str) -> str:
    if not value or not value.strip():
        raise DatabaseConfigurationError(f"{variable} is required for this operation")
    value = value.strip()
    try:
        parsed = urlsplit(value)
        valid = parsed.scheme in {"postgres", "postgresql", "postgresql+asyncpg"} and bool(parsed.hostname) and bool(parsed.path.strip("/"))
    except ValueError:
        valid = False
    if not valid:
        raise DatabaseConfigurationError(f"{variable} must be a valid PostgreSQL URL")
    return value


def load_database_settings(environ: Mapping[str, str] | None = None) -> DatabaseSettings:
    """Read optional runtime configuration without affecting JSON-only startup."""
    env = os.environ if environ is None else environ
    environment = env.get("FLUENT_PATH_ENVIRONMENT", "development").strip().lower()
    if environment not in {"development", "test", "staging", "production"}:
        raise DatabaseConfigurationError("FLUENT_PATH_ENVIRONMENT must be development, test, staging, or production")
    if environment == "test":
        database_url = require_test_database_url(env)
    else:
        database_url = _validate_postgres_url(env["DATABASE_URL"], "DATABASE_URL") if env.get("DATABASE_URL") else None
    if environment in {"staging", "production"} and not database_url:
        raise DatabaseConfigurationError(f"DATABASE_URL is required in {environment}")
    return DatabaseSettings(database_url=database_url, environment=environment)


def require_test_database_url(environ: Mapping[str, str] | None = None) -> str:
    """Tests must opt in to a dedicated test URL; production URL is never a fallback."""
    env = os.environ if environ is None else environ
    value = _validate_postgres_url(env.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL")
    name = urlsplit(value).path.strip("/").lower()
    if "test" not in name:
        raise DatabaseConfigurationError("TEST_DATABASE_URL database name must contain 'test'")
    return value


def importer_target_url(environ: Mapping[str, str] | None = None) -> str:
    """Require explicit importer-only target configuration; never infer from DATABASE_URL."""
    env = os.environ if environ is None else environ
    if env.get("FLUENT_PATH_IMPORT_CONFIRM") != "I_CONFIRM_STAGING_IMPORT":
        raise DatabaseConfigurationError("Importer requires FLUENT_PATH_IMPORT_CONFIRM=I_CONFIRM_STAGING_IMPORT")
    if env.get("FLUENT_PATH_ENVIRONMENT", "").lower() not in {"development", "staging"}:
        raise DatabaseConfigurationError("Importer target must be explicitly marked development or staging")
    value = _validate_postgres_url(env.get("IMPORT_DATABASE_URL"), "IMPORT_DATABASE_URL")
    parsed = urlsplit(value)
    name = parsed.path.strip("/").lower()
    host = (parsed.hostname or "").lower()
    if "prod" in name or "production" in name or any("prod" in label for label in host.split(".")):
        raise DatabaseConfigurationError("Production database targets are prohibited by the JSON importer")
    return value


def importer_target_identity(value: str) -> str:
    """Non-secret target identity required on the importer command line."""
    parsed = urlsplit(_validate_postgres_url(value, "IMPORT_DATABASE_URL"))
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return f"{host}/{parsed.path.strip('/')}"
