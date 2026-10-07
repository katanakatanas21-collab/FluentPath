from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from db.base import Base
from db import models  # noqa: F401 - register model metadata
from db.session import (
    build_verified_ssl_context,
    normalize_database_url,
    requires_verified_tls,
    strip_tls_query_parameters,
)
from db_config import DatabaseConfigurationError, DatabaseSettings, _validate_postgres_url

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def database_url():
    url = _validate_postgres_url(os.environ.get("DATABASE_URL"), "DATABASE_URL")
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url.removeprefix("postgres://")
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    # Transport security is decided by the pinned CA below, never by ssl*
    # query parameters, so a URL cannot quietly ask for an unverified
    # connection while migrations run.
    return strip_tls_query_parameters(normalize_database_url(url))


def engine_connect_arguments():
    """Return the connect arguments migrations must use, or None.

    Staging and production migrations get the same pinned-root,
    hostname-checked SSL context the application runtime uses.

    This module previously built its engine straight from the URL and never
    supplied an ``ssl`` argument at all. Nothing in the URL could turn
    verification on, and no ssl parameter was required, so a migration was free
    to reach the database unverified. Note that an explicit ``sslmode=disable``
    was not the exposure: asyncpg rejects that keyword outright, so it failed
    loudly by accident. The defect was the missing enforcement, not an honoured
    downgrade. Stripping ``ssl*`` keeps the URL from having any say in the
    matter either way.
    """
    environment = (os.environ.get("FLUENT_PATH_ENVIRONMENT") or "development").strip().lower()
    # Reuse the runtime's own predicate so migrations and the application can
    # never disagree about which environments demand certificate verification.
    if not requires_verified_tls(DatabaseSettings(database_url=None, environment=environment)):
        return None
    # Refuse to run if a caller tries to inject its own ssl argument.
    if os.environ.get("ALEMBIC_SSL_OVERRIDE"):
        raise DatabaseConfigurationError(
            "A custom ssl override is not accepted; verified TLS is mandatory for migrations"
        )
    return {"ssl": build_verified_ssl_context()}


def run_migrations_offline():
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"}, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = database_url()
    engine_kwargs = {"prefix": "sqlalchemy.", "poolclass": pool.NullPool}
    connect_arguments = engine_connect_arguments()
    if connect_arguments:
        engine_kwargs["connect_args"] = connect_arguments
    connectable = async_engine_from_config(section, **engine_kwargs)
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    import asyncio
    asyncio.run(run_migrations_online())
