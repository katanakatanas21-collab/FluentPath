"""Regression tests for the runtime Alembic revision guard.

The guard exists so that a database at the wrong revision produces a clear,
actionable refusal instead of an opaque undefined-column SQL error. These tests
need no PostgreSQL: ``sqlite3`` is in the standard library, so the guard's real
``inspect(...).has_table`` call and its real ``SELECT version_num`` run for real,
and only the ``AsyncSession`` wrapper around them is simulated. The asyncpg path
itself is covered live by ``test_postgres_runtime``.
"""

import asyncio
import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from db.revision import EXPECTED_SCHEMA_REVISION, VERSION_TABLE
from db_config import DatabaseSettings
from persistence.errors import DataStoreError, SchemaVersionMismatch
from persistence.postgres_backend import (
    ObservedSchemaRevision,
    PostgresStoreBackend,
    validate_schema_revision,
)
from persistence.runtime import resolve_backend_name

DISPOSABLE_URL = "postgresql+asyncpg://user:password@127.0.0.1:5432/fluent_path_test"

WRONG_REVISION = "0002_nullable_user_created_at"

#: Every in-memory engine these tests open, closed from the thread that ran the
#: tests so SQLite never finalizes a connection from another one.
_ENGINES = []


def tearDownModule():
    for engine in _ENGINES:
        engine.dispose()
    _ENGINES.clear()


class FakeAsyncSession:
    """Runs the guard's statements against a real synchronous Session.

    Only the async wrapper is simulated, so ``get_bind``, ``inspect`` and the
    ``SELECT version_num`` are all exercised for real against SQLite.
    """

    def __init__(self, sync_session, executed):
        self._sync_session = sync_session
        self._executed = executed

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        self._sync_session.close()
        return False

    async def run_sync(self, function):
        return function(self._sync_session)

    async def execute(self, statement):
        self._executed.append(str(statement))
        return self._sync_session.execute(statement)


def build_backend(revisions=(), *, create_table=True):
    """Return a backend whose guard sees a database at the given revision state."""
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        future=True,
    )
    _ENGINES.append(engine)
    connection = engine.connect()
    if create_table:
        connection.execute(text(f"CREATE TABLE {VERSION_TABLE} (version_num VARCHAR(32) NOT NULL)"))
        for revision in revisions:
            connection.execute(
                text(f"INSERT INTO {VERSION_TABLE} (version_num) VALUES (:value)"),
                {"value": revision},
            )
        connection.commit()
    connection.close()

    executed: list[str] = []

    def session_factory():
        return FakeAsyncSession(Session(engine), executed)

    backend = PostgresStoreBackend(
        DatabaseSettings(DISPOSABLE_URL, "test"), session_factory=session_factory
    )

    def set_revision(*values):
        """Move the simulated database to another revision state."""
        connection = engine.connect()
        connection.execute(text(f"DELETE FROM {VERSION_TABLE}"))
        for value in values:
            connection.execute(
                text(f"INSERT INTO {VERSION_TABLE} (version_num) VALUES (:value)"),
                {"value": value},
            )
        connection.commit()
        connection.close()

    return backend, executed, set_revision


def run(coroutine):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coroutine)
    finally:
        loop.close()


class SchemaRevisionValidationTests(unittest.TestCase):
    """The pure decision, including the cases a real database rarely produces."""

    def test_the_expected_revision_is_accepted(self):
        observed = ObservedSchemaRevision(True, (EXPECTED_SCHEMA_REVISION,))
        self.assertIsNone(validate_schema_revision(observed, EXPECTED_SCHEMA_REVISION))

    def test_a_different_revision_is_refused(self):
        observed = ObservedSchemaRevision(True, (WRONG_REVISION,))
        with self.assertRaises(SchemaVersionMismatch) as caught:
            validate_schema_revision(observed, EXPECTED_SCHEMA_REVISION)
        self.assertIn(WRONG_REVISION, str(caught.exception))
        self.assertIn(EXPECTED_SCHEMA_REVISION, str(caught.exception))

    def test_an_unmigrated_database_is_refused(self):
        with self.assertRaises(SchemaVersionMismatch) as caught:
            validate_schema_revision(ObservedSchemaRevision(False, ()), EXPECTED_SCHEMA_REVISION)
        self.assertIn(VERSION_TABLE, str(caught.exception))

    def test_an_empty_version_table_is_refused(self):
        with self.assertRaises(SchemaVersionMismatch) as caught:
            validate_schema_revision(ObservedSchemaRevision(True, ()), EXPECTED_SCHEMA_REVISION)
        self.assertIn("exactly one", str(caught.exception))

    def test_several_version_rows_are_refused(self):
        observed = ObservedSchemaRevision(True, (EXPECTED_SCHEMA_REVISION, WRONG_REVISION))
        with self.assertRaises(SchemaVersionMismatch):
            validate_schema_revision(observed, EXPECTED_SCHEMA_REVISION)

    def test_the_refusal_is_a_data_store_error_so_the_api_contract_is_unchanged(self):
        self.assertTrue(issubclass(SchemaVersionMismatch, DataStoreError))
        with self.assertRaises(DataStoreError):
            validate_schema_revision(ObservedSchemaRevision(True, (WRONG_REVISION,)),
                                     EXPECTED_SCHEMA_REVISION)

    def test_the_refusal_never_names_a_host_database_or_credential(self):
        with self.assertRaises(SchemaVersionMismatch) as caught:
            validate_schema_revision(ObservedSchemaRevision(True, (WRONG_REVISION,)),
                                     EXPECTED_SCHEMA_REVISION)
        message = str(caught.exception)
        for secret in ("127.0.0.1", "fluent_path_test", "password", "postgresql", "://"):
            self.assertNotIn(secret, message)


class SchemaRevisionGuardTests(unittest.TestCase):
    """The guard as the backend actually calls it."""

    def test_a_database_at_the_expected_revision_is_accepted(self):
        backend, executed, _ = build_backend([EXPECTED_SCHEMA_REVISION])
        self.assertIsNone(run(backend._require_current_schema()))
        self.assertTrue(any(VERSION_TABLE in statement for statement in executed))

    def test_a_database_at_another_revision_is_refused(self):
        backend, _, _ = build_backend([WRONG_REVISION])
        with self.assertRaises(SchemaVersionMismatch):
            run(backend._require_current_schema())

    def test_an_unmigrated_database_is_refused(self):
        backend, _, _ = build_backend(create_table=False)
        with self.assertRaises(SchemaVersionMismatch):
            run(backend._require_current_schema())

    def test_a_read_is_refused_before_any_table_is_touched(self):
        backend, _, _ = build_backend([WRONG_REVISION])
        with self.assertRaises(SchemaVersionMismatch):
            run(backend.read("students"))

    def test_a_write_is_refused_before_any_table_is_touched(self):
        backend, _, _ = build_backend([WRONG_REVISION])
        with self.assertRaises(SchemaVersionMismatch):
            run(backend.write("students", []))

    def test_token_revocation_is_refused_too(self):
        from datetime import datetime, timedelta, timezone

        backend, _, _ = build_backend([WRONG_REVISION])
        with self.assertRaises(SchemaVersionMismatch):
            run(backend.token_is_revoked("token"))
        with self.assertRaises(SchemaVersionMismatch):
            run(backend.revoke_token("token", "user-1",
                                     datetime.now(timezone.utc) + timedelta(days=1)))

    def test_success_is_remembered_so_the_check_is_not_repeated_per_call(self):
        backend, executed, _ = build_backend([EXPECTED_SCHEMA_REVISION])
        run(backend._require_current_schema())
        after_first = len(executed)
        run(backend._require_current_schema())
        self.assertEqual(len(executed), after_first)

    def test_a_refusal_is_not_remembered_so_a_migration_is_picked_up(self):
        backend, _, set_revision = build_backend([WRONG_REVISION])
        with self.assertRaises(SchemaVersionMismatch):
            run(backend._require_current_schema())
        self.assertFalse(backend._schema_verified)

        # The operator applies the migration underneath the running process. The
        # next call must re-check and accept, rather than failing forever from a
        # remembered verdict.
        set_revision(EXPECTED_SCHEMA_REVISION)
        self.assertIsNone(run(backend._require_current_schema()))
        self.assertTrue(backend._schema_verified)


class NoJsonFallbackTests(unittest.TestCase):
    """A schema problem must never resolve to file storage."""

    def test_staging_still_selects_postgresql(self):
        self.assertEqual(resolve_backend_name({"FLUENT_PATH_ENVIRONMENT": "staging"}), "postgres")

    def test_production_still_selects_postgresql(self):
        self.assertEqual(resolve_backend_name({"FLUENT_PATH_ENVIRONMENT": "production"}), "postgres")

    def test_staging_still_refuses_an_explicit_json_request(self):
        from persistence.errors import PersistenceConfigurationError

        with self.assertRaises(PersistenceConfigurationError):
            resolve_backend_name({"FLUENT_PATH_ENVIRONMENT": "staging",
                                  "FLUENT_PATH_PERSISTENCE": "json"})


class SharedRevisionConstantTests(unittest.TestCase):
    """The importer and the runtime must never drift apart."""

    def test_the_importer_uses_the_shared_constant(self):
        import import_json_to_postgres

        self.assertIs(import_json_to_postgres.EXPECTED_REVISION, EXPECTED_SCHEMA_REVISION)

    def test_the_constant_matches_the_local_alembic_head(self):
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from pathlib import Path

        scripts = Path(__file__).resolve().parent / "migrations"
        config = Config()
        config.set_main_option("script_location", str(scripts))
        self.assertEqual(ScriptDirectory.from_config(config).get_heads(),
                         [EXPECTED_SCHEMA_REVISION])


if __name__ == "__main__":
    unittest.main()