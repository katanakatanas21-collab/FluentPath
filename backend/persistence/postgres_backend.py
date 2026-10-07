"""PostgreSQL backend for the normalized Fluent Path schema.

Read and write both work in API-compatible plain dictionaries, so the domain
rules in ``server.py`` are unchanged. Writes are planned as a per-table diff
inside one transaction and applied under a table lock, which keeps a store write
atomic and prevents a partial update from reaching the database.

Known MVP boundaries, tracked deliberately:

* Every store call is issued from one background event loop, so database work is
  serialized rather than running concurrently per request. This is a throughput
  limit, not a correctness one, and is what allows the synchronous domain
  helpers to keep working unchanged. Moving the endpoints to ``async def`` with a
  per-request session is the follow-on.
* Removing a user, conversation or homework record that another store still
  references is refused by the database foreign keys and surfaces as a
  ``DataStoreError``. The JSON backend had no such constraint, so this fails
  closed rather than silently dropping dependent rows.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, NamedTuple, Sequence

from sqlalchemy import and_, delete, insert, inspect, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.base import Base
from db import models as _models  # noqa: F401  (registers the table metadata)
from db.revision import EXPECTED_SCHEMA_REVISION, VERSION_TABLE
from db_config import DatabaseSettings
from db.session import create_engine_and_session_factory
from persistence.errors import DataStoreError, SchemaVersionMismatch
from persistence.records import (
    STORE_READ_TABLES,
    STORE_WRITE_TABLES,
    UNKEYED_WRITE_TABLES,
    MappingError,
    ReadContext,
    WriteContext,
    records_from_rows,
    rows_from_records,
    table_key_columns,
)
from persistence.store import STORE_NAMES, Store, normalize_records

#: Canonical lock order. Locking every application table in one statement, in a
#: fixed order, removes any possibility of a lock-ordering deadlock.
LOCKED_TABLES: tuple[str, ...] = tuple(sorted(Base.metadata.tables))


def _table(name: str):
    table = Base.metadata.tables.get(name)
    if table is None:  # pragma: no cover - guarded by STORE_*_TABLES
        raise DataStoreError(f"Unknown application table {name}")
    return table


def _token_digest(token: str) -> str:
    """Store a one-way digest of a bearer token; the token itself is never persisted."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _key_clause(table, key_columns: Sequence[str], key: Sequence[Any]):
    return and_(*(table.c[column] == value for column, value in zip(key_columns, key)))


def _values_match(current: Any, target: Any) -> bool:
    if current is None or target is None:
        return current is None and target is None
    # bool is a subclass of int, so a boolean column would otherwise reach the
    # Decimal conversion and raise InvalidOperation on Decimal("False"). That
    # made every repeat write of the students store fail.
    if isinstance(current, bool) or isinstance(target, bool):
        return bool(current) == bool(target)
    numeric = (int, float, Decimal)
    if isinstance(current, numeric) and isinstance(target, numeric):
        try:
            return Decimal(str(current)) == Decimal(str(target))
        except ArithmeticError:
            return current == target
    return current == target


class ObservedSchemaRevision(NamedTuple):
    """What the target database reports about its own migration state.

    ``table_present`` separates "never migrated" from "migrated but the history
    row is gone", because the remedy differs: the first needs an upgrade, the
    second needs an investigation.
    """

    table_present: bool
    revisions: tuple[str, ...]


def validate_schema_revision(observed: ObservedSchemaRevision, expected: str) -> None:
    """Refuse to use a database that is not exactly at ``expected``.

    Raises ``SchemaVersionMismatch`` with a message that names only revisions, so
    a log line can be acted on without disclosing where the database is.
    """
    if not observed.table_present:
        raise SchemaVersionMismatch(
            f"The database has no {VERSION_TABLE} table, so it has never been migrated. "
            f"Apply the reviewed migrations up to {expected} before starting the application."
        )
    if len(observed.revisions) != 1:
        raise SchemaVersionMismatch(
            f"The database reports {len(observed.revisions)} rows in {VERSION_TABLE}; exactly one is "
            f"required. Found: {sorted(observed.revisions) or 'none'}."
        )
    found = observed.revisions[0]
    if found != expected:
        raise SchemaVersionMismatch(
            f"The database is at schema revision {found!r} but this code requires {expected!r}. "
            f"Apply the reviewed migrations, or run the code that matches the deployed schema."
        )


class PostgresStoreBackend(Store):
    """Serves the logical stores from the normalized PostgreSQL schema."""

    name = "postgres"

    def __init__(self, settings: DatabaseSettings, *, session_factory=None, engine=None):
        self._settings = settings
        # Created lazily on first use so the engine binds to the event loop that
        # will actually use it.
        self._session_factory = session_factory
        self._engine = engine
        self._schema_verified = False

    @property
    def settings(self) -> DatabaseSettings:
        return self._settings

    async def _factory(self):
        if self._session_factory is None:
            if not self._settings.database_url:
                raise DataStoreError("PostgreSQL persistence requires a database URL.")
            try:
                self._engine, self._session_factory = create_engine_and_session_factory(self._settings)
            except Exception:
                raise DataStoreError("PostgreSQL persistence could not be configured.") from None
        return self._session_factory

    async def _observe_schema_revision(self, session) -> ObservedSchemaRevision:
        # ``run_sync`` hands the function the underlying synchronous Session, so
        # the bind is what the inspector needs; a Session is not inspectable.
        present = await session.run_sync(
            lambda sync_session: inspect(sync_session.get_bind()).has_table(VERSION_TABLE)
        )
        if not present:
            return ObservedSchemaRevision(table_present=False, revisions=())
        result = await session.execute(text(f"SELECT version_num FROM {VERSION_TABLE}"))
        return ObservedSchemaRevision(
            table_present=True,
            revisions=tuple(row[0] for row in result),
        )

    async def _require_current_schema(self) -> None:
        """Refuse to read or write a database that is not at the expected revision.

        Without this, an older schema surfaces as an opaque undefined-column or
        missing-relation SQL error, or worse, a read that quietly omits data the
        code expects. It runs once per process and only on success: a failure must
        be re-evaluated, so a migration applied underneath a running process is
        picked up rather than remembered as verified.

        The check gets its own short-lived session so a write never holds a table
        lock while the schema is being judged.

        The cached success lasts for the life of this backend instance. That covers
        the case the guard exists for, where new code meets a database that has not
        been migrated yet, and keeps the check off the hot path. It deliberately
        does not watch for a revision change made after the first successful check;
        reverting a migration under a running process is not an expected operation.
        Restarting the process re-runs the check.
        """
        if self._schema_verified:
            return
        factory = await self._factory()
        try:
            async with factory() as session:
                observed = await self._observe_schema_revision(session)
        except SchemaVersionMismatch:
            raise
        except Exception:
            raise DataStoreError("The database schema version could not be checked.") from None
        validate_schema_revision(observed, EXPECTED_SCHEMA_REVISION)
        self._schema_verified = True

    async def _fetch(self, session, table_names: Sequence[str]) -> dict[str, list[dict]]:
        collected: dict[str, list[dict]] = {}
        for name in table_names:
            table = _table(name)
            result = await session.execute(select(*table.columns))
            collected[name] = [dict(row) for row in result.mappings()]
        return collected

    async def read(self, store_name: str, *, path=None) -> list[dict]:
        self.validate_store_name(store_name)
        await self._require_current_schema()
        factory = await self._factory()
        try:
            async with factory() as session:
                rows = await self._fetch(session, STORE_READ_TABLES[store_name])
                return records_from_rows(store_name, ReadContext(rows))
        except MappingError:
            raise
        except DataStoreError:
            raise
        except Exception:
            raise DataStoreError("Persistent data could not be read.") from None

    async def _lock(self, session) -> None:
        await session.execute(
            text("LOCK TABLE " + ", ".join(f'"{name}"' for name in LOCKED_TABLES) + " IN EXCLUSIVE MODE")
        )

    async def _stored_user_times(self, session) -> dict[str, Any]:
        rows = await self._fetch(session, ("users",))
        return {row["id"]: row.get("created_at") for row in rows["users"]}

    async def _lesson_courses(self, session) -> dict[str, str]:
        rows = await self._fetch(session, ("lessons",))
        return {row["id"]: row["course_id"] for row in rows["lessons"]}

    async def write(self, store_name: str, records, *, path=None) -> None:
        self.validate_store_name(store_name)
        await self._require_current_schema()
        payload = normalize_records(store_name, records)
        factory = await self._factory()
        try:
            async with factory() as session:
                async with session.begin():
                    await self._lock(session)
                    context = WriteContext()
                    if store_name == "students":
                        context = WriteContext(await self._lesson_courses(session))
                    planned = rows_from_records(store_name, payload, context)
                    if store_name == "students":
                        planned["users"] = self._with_preserved_user_times(
                            planned["users"], await self._stored_user_times(session)
                        )
                    for table_name in STORE_WRITE_TABLES[store_name]:
                        await self._reconcile(session, table_name, planned.get(table_name, []))
        except MappingError:
            raise
        except DataStoreError:
            raise
        except Exception:
            raise DataStoreError("Persistent data could not be saved.") from None

    @staticmethod
    def _with_preserved_user_times(
        user_rows: Sequence[Mapping[str, Any]], stored: Mapping[str, Any]
    ) -> list[dict]:
        """Never lose an unknown historical creation time; never invent one either."""
        now = datetime.now(timezone.utc)
        return [
            {**row, "created_at": row.get("created_at") or stored.get(row["id"]) or now}
            for row in user_rows
        ]

    async def _reconcile(self, session, table_name: str, target_rows: Sequence[Mapping[str, Any]]) -> None:
        table = _table(table_name)
        payload = [dict(row) for row in target_rows]

        if table_name in UNKEYED_WRITE_TABLES:
            await session.execute(delete(table))
            if payload:
                await session.execute(insert(table), payload)
            return

        key_columns = table_key_columns(table)
        result = await session.execute(select(*table.columns))
        current = {tuple(row[column] for column in key_columns): dict(row) for row in result.mappings()}

        target: dict[tuple, dict] = {}
        for row in payload:
            key = tuple(row[column] for column in key_columns)
            if key in target:
                raise MappingError(f"Duplicate {table_name} key {key!r} in one write.")
            target[key] = row

        for key in current.keys() - target.keys():
            await session.execute(delete(table).where(_key_clause(table, key_columns, key)))

        inserts = [row for key, row in target.items() if key not in current]
        if inserts:
            await session.execute(insert(table), inserts)

        for key, row in target.items():
            existing = current.get(key)
            if existing is None:
                continue
            changed = {
                column: value
                for column, value in row.items()
                if column not in key_columns and not _values_match(existing.get(column), value)
            }
            if changed:
                await session.execute(update(table).where(_key_clause(table, key_columns, key)).values(**changed))

    async def revoke_token(self, token: str, user_id: str, expires_at) -> None:
        if not token or not user_id or expires_at is None:
            return
        await self._require_current_schema()
        factory = await self._factory()
        now = datetime.now(timezone.utc)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        try:
            async with factory() as session:
                async with session.begin():
                    await session.execute(delete(_table("revoked_tokens")).where(_table("revoked_tokens").c.expires_at <= now))
                    await session.execute(
                        pg_insert(_table("revoked_tokens"))
                        .values(
                            token_id=_token_digest(token),
                            user_id=user_id,
                            expires_at=expires_at,
                            revoked_at=now,
                        )
                        .on_conflict_do_nothing(index_elements=["token_id"])
                    )
        except Exception:
            # Revocation durability must never turn a successful logout into an error.
            raise DataStoreError("Persistent data could not be saved.") from None

    async def token_is_revoked(self, token: str) -> bool:
        if not token:
            return False
        await self._require_current_schema()
        factory = await self._factory()
        try:
            async with factory() as session:
                result = await session.execute(
                    select(_table("revoked_tokens").c.token_id).where(
                        _table("revoked_tokens").c.token_id == _token_digest(token),
                        _table("revoked_tokens").c.expires_at > datetime.now(timezone.utc),
                    )
                )
                return result.first() is not None
        except Exception:
            raise DataStoreError("Persistent data could not be read.") from None

    async def check_health(self) -> None:
        """Confirm the database answers a trivial query.

        Uses ``SELECT 1`` and deliberately does not verify the schema revision:
        readiness should report reachability, and the revision guard already runs
        on the first real read. Nothing is written.
        """
        try:
            factory = await self._factory()
        except DataStoreError:
            raise
        try:
            async with factory() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            # Driver errors carry connection strings and row values, so nothing
            # from the exception is allowed to reach the caller or the log.
            raise DataStoreError("The database did not answer a readiness check.") from None

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None


def describe_settings(settings: DatabaseSettings) -> str:
    """Non-secret summary of the configured target, safe to log."""
    from urllib.parse import urlsplit

    if not settings.database_url:
        return "postgres: no database URL configured"
    parsed = urlsplit(settings.database_url)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return f"postgres: {host}/{parsed.path.strip('/')} ({settings.environment})"


__all__ = ["PostgresStoreBackend", "describe_settings", "STORE_NAMES"]