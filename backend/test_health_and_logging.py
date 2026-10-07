"""Readiness probing and failure logging.

``/api/health`` answers ok only after the configured backend has answered a
read-only check, so a process that cannot reach its storage reports 503 instead
of looking healthy. The logging tests pin the two properties that make the logs
usable without making them a disclosure risk: a failure is recorded, and nothing
from the request or the driver is recorded with it.
"""

import asyncio
import logging
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import server
from persistence.errors import DataStoreError
from persistence.json_backend import JsonStoreBackend
from persistence.store import STORE_FILENAMES, STORE_NAMES, Store

#: Substrings that must never appear in a log record or an error response.
SECRET_MARKERS = (
    "hunter2",
    "Bearer ",
    "postgresql+asyncpg://",
    "SUPABASE_SERVICE_KEY",
    "select version_num",
)


def records_text(records) -> str:
    """Flatten records into the text a log destination would receive.

    ``exc_info`` is included deliberately: a traceback is part of what gets
    written, so a leak hiding in an attached exception has to be visible here.
    """
    chunks = []
    for record in records:
        chunks.append(record.getMessage())
        if record.exc_info:
            chunks.append("".join(logging.Formatter().formatException(record.exc_info)))
        chunks.append(" ".join(f"{key}={value}" for key, value in record.__dict__.items()))
    return "\n".join(chunks)


class HealthRouteTests(unittest.TestCase):
    """The route reports the backend, not just the process."""

    def setUp(self):
        self.client = TestClient(server.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_ok_when_the_backend_answers(self):
        with mock.patch("persistence.check_store_health") as check:
            response = self.client.get("/api/health")

        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "ok", "message": "FluentPath API is running"}, response.json())
        check.assert_called_once_with()

    def test_unavailable_when_the_backend_is_down(self):
        with mock.patch("persistence.check_store_health", side_effect=DataStoreError("boom")):
            response = self.client.get("/api/health")

        self.assertEqual(503, response.status_code)
        self.assertEqual(
            {"status": "unavailable", "message": "FluentPath API cannot reach its storage backend"},
            response.json(),
        )

    def test_unavailable_on_an_unexpected_failure(self):
        with mock.patch("persistence.check_store_health", side_effect=RuntimeError("odd")):
            response = self.client.get("/api/health")

        self.assertEqual(503, response.status_code)
        self.assertEqual("unavailable", response.json()["status"])

    def test_failure_body_leaks_no_cause(self):
        cause = "postgresql+asyncpg://user:hunter2@db.internal:5432/prod"
        with mock.patch("persistence.check_store_health", side_effect=DataStoreError(cause)):
            response = self.client.get("/api/health")

        body = response.text
        for marker in SECRET_MARKERS:
            self.assertNotIn(marker, body)

    def test_probe_is_read_only(self):
        """Readiness must not call the write path."""
        with mock.patch.object(server.persistence, "write_store") as write:
            with mock.patch("persistence.check_store_health"):
                self.client.get("/api/health")

        write.assert_not_called()

    def test_backend_name_failure_still_returns_503(self):
        """A diagnostic lookup must not escalate a clean 503 into a 500."""
        with mock.patch("persistence.check_store_health", side_effect=DataStoreError("boom")):
            with mock.patch("persistence.active_backend_name", side_effect=RuntimeError("odd")):
                response = self.client.get("/api/health")

        self.assertEqual(503, response.status_code)


class JsonBackendHealthTests(unittest.TestCase):
    """The JSON backend proves its configured paths without touching them."""

    def test_ok_when_every_store_path_is_resolvable(self):
        with TemporaryDirectory() as directory:
            backend = JsonStoreBackend(lambda name: Path(directory) / f"{name}.json")
            asyncio.run(backend.check_health())

    def test_unavailable_when_a_store_path_is_unset(self):
        backend = JsonStoreBackend(lambda name: None)
        with self.assertRaises(DataStoreError):
            asyncio.run(backend.check_health())

    def test_unavailable_when_the_directory_is_missing(self):
        with TemporaryDirectory() as directory:
            missing = Path(directory) / "absent"
            backend = JsonStoreBackend(lambda name: missing / f"{name}.json")
            with self.assertRaises(DataStoreError):
                asyncio.run(backend.check_health())

    def test_creates_no_files(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            backend = JsonStoreBackend(lambda name: root / f"{name}.json")
            asyncio.run(backend.check_health())
            self.assertEqual([], sorted(path.name for path in root.iterdir()))


class StoreContractTests(unittest.TestCase):
    """A backend that has not opted in fails closed rather than reading fine."""

    def test_base_contract_refuses_to_report_ready(self):
        class MinimalStore(Store):
            async def read(self, store_name, *, path=None):
                return []

            async def write(self, store_name, records, *, path=None):
                return None

        with self.assertRaises(DataStoreError):
            asyncio.run(MinimalStore().check_health())

    def test_json_backend_covers_every_store(self):
        with TemporaryDirectory() as directory:
            backend = JsonStoreBackend(lambda name: Path(directory) / f"{name}.json")
            missing = [name for name in STORE_NAMES if backend.path_for(name) is None]
            self.assertEqual([], missing)
            self.assertEqual(set(STORE_NAMES), set(STORE_FILENAMES))

    def test_check_health_is_abstract_on_the_contract(self):
        self.assertTrue(hasattr(Store, "check_health"))


class PostgresBackendHealthTests(unittest.TestCase):
    """The PostgreSQL probe asks for ``SELECT 1`` and nothing else."""

    class RecordingSession:
        def __init__(self, statements):
            self._statements = statements

        async def execute(self, statement):
            self._statements.append(str(statement))
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

    def _backend(self, statements, *, session_factory=None):
        from persistence.postgres_backend import PostgresStoreBackend

        session_factory = session_factory or (lambda: self.RecordingSession(statements))
        return PostgresStoreBackend(mock.Mock(), session_factory=session_factory)

    def test_uses_a_single_select_one(self):
        statements = []
        asyncio.run(self._backend(statements).check_health())
        self.assertEqual(["SELECT 1"], statements)

    def test_sanitizes_a_driver_failure(self):
        class Exploding:
            async def __aenter__(self):
                raise ConnectionError("could not connect: postgresql+asyncpg://u:hunter2@host/db")

            async def __aexit__(self, *exc_info):
                return False

        backend = self._backend([], session_factory=lambda: Exploding())
        with self.assertRaises(DataStoreError) as caught:
            asyncio.run(backend.check_health())

        message = str(caught.exception)
        self.assertEqual("The database did not answer a readiness check.", message)
        self.assertIsNone(caught.exception.__cause__)
        for marker in SECRET_MARKERS:
            self.assertNotIn(marker, message)

    def test_sanitizes_a_slow_driver_failure(self):
        """A timeout message must not carry the connection string either."""
        import sqlalchemy

        class TimingOut:
            async def __aenter__(self):
                raise sqlalchemy.exc.TimeoutError(
                    "timeout connecting to postgresql+asyncpg://u:hunter2@host/db"
                )

            async def __aexit__(self, *exc_info):
                return False

        backend = self._backend([], session_factory=lambda: TimingOut())
        with self.assertRaises(DataStoreError) as caught:
            asyncio.run(backend.check_health())

        self.assertNotIn("hunter2", str(caught.exception))

    def test_reports_an_unconfigured_backend(self):
        from db_config import DatabaseSettings
        from persistence.postgres_backend import PostgresStoreBackend

        backend = PostgresStoreBackend(DatabaseSettings(database_url="", environment="staging"))
        with self.assertRaises(DataStoreError):
            asyncio.run(backend.check_health())

    def test_reports_a_tls_rejection_sanitized(self):
        """Staging refuses an unverified socket; the probe must not echo it."""
        from db_config import DatabaseSettings
        from persistence.postgres_backend import PostgresStoreBackend

        settings = DatabaseSettings(
            database_url="postgresql+asyncpg://u:hunter2@127.0.0.1:1/none",
            environment="staging",
        )
        with self.assertRaises(DataStoreError) as caught:
            asyncio.run(PostgresStoreBackend(settings).check_health())

        self.assertNotIn("hunter2", str(caught.exception))

    def test_probe_writes_nothing(self):
        statements = []
        backend = self._backend(statements)
        with mock.patch.object(backend, "write") as write:
            asyncio.run(backend.check_health())
        write.assert_not_called()


class RuntimeHealthTests(unittest.TestCase):
    """The runtime refuses to report readiness with no backend installed."""

    def test_requires_a_configured_backend(self):
        from persistence.errors import PersistenceConfigurationError
        from persistence import runtime

        with mock.patch.object(runtime, "_store", None):
            with self.assertRaises(PersistenceConfigurationError):
                runtime.check_store_health()

    def test_delegates_to_the_active_backend(self):
        from persistence import runtime

        calls = []

        class ReadyStore(Store):
            name = "ready"

            async def read(self, store_name, *, path=None):
                return []

            async def write(self, store_name, records, *, path=None):
                return None

            async def check_health(self):
                calls.append(True)

        with mock.patch.object(runtime, "_store", ReadyStore()):
            runtime.check_store_health()

        self.assertEqual([True], calls)

    def test_surfaces_a_backend_failure(self):
        from persistence import runtime

        class BrokenStore(Store):
            name = "broken"

            async def read(self, store_name, *, path=None):
                return []

            async def write(self, store_name, records, *, path=None):
                return None

            async def check_health(self):
                raise DataStoreError("down")

        with mock.patch.object(runtime, "_store", BrokenStore()):
            with self.assertRaises(DataStoreError):
                runtime.check_store_health()


class FailureLoggingTests(unittest.TestCase):
    """Failures are recorded; requests and causes are not."""

    def _app(self):
        app = FastAPI()

        @app.get("/boom")
        async def boom():
            raise RuntimeError("secret-ish internal detail")

        @app.get("/api/answer")
        async def answer():
            return {"ok": True}

        @app.get("/api/refuse")
        async def refuse():
            # A 5xx produced without an exception, the way the DataStoreError
            # handler answers a store outage.
            return JSONResponse(status_code=503, content={"detail": "DATA_STORE_UNAVAILABLE"})

        app.middleware("http")(server.log_request_failures)
        return TestClient(app, raise_server_exceptions=False)

    def test_unhandled_exception_is_logged_with_a_traceback(self):
        with self.assertLogs(server.logger, level="ERROR") as captured:
            self._app().get("/boom")

        text = records_text(captured.records)
        self.assertIn("Unhandled server error.", text)
        self.assertIn("RuntimeError", text)

    def test_successful_request_is_not_logged(self):
        with mock.patch.object(server.logger, "error") as error:
            with mock.patch.object(server.logger, "exception") as exception:
                response = self._app().get("/api/answer")

        self.assertEqual(200, response.status_code)
        error.assert_not_called()
        exception.assert_not_called()

    def test_5xx_response_is_logged_with_status(self):
        client = self._app()
        with self.assertLogs(server.logger, level="ERROR") as captured:
            response = client.get("/api/refuse")

        text = records_text(captured.records)
        self.assertIn("Server error response.", text)
        self.assertIn(str(response.status_code), text)

    def test_logged_context_omits_the_query_string(self):
        """Tokens and personal data arrive in the query string, not the path."""
        with self.assertLogs(server.logger, level="ERROR") as captured:
            self._app().get("/boom", params={"token": "a6-secret-token", "email": "p@example.com"})

        text = records_text(captured.records)
        self.assertIn("path=/boom", text)
        self.assertIn("method=GET", text)
        for marker in ("a6-secret-token", "p@example.com", "token=", "email="):
            self.assertNotIn(marker, text)

    def test_logged_context_is_an_allowlist(self):
        for attribute in ("headers", "cookies", "query_params", "client", "body"):
            self.assertNotIn(attribute, server.LOGGABLE_REQUEST_FIELDS)

    def test_logging_never_records_the_authorization_header(self):
        with self.assertLogs(server.logger, level="ERROR") as captured:
            self._app().get(
                "/boom",
                headers={"Authorization": "Bearer a6-bearer-token"},
            )

        self.assertNotIn("a6-bearer-token", records_text(captured.records))

    def test_backend_failure_log_omits_the_cause(self):
        with mock.patch("persistence.check_store_health", side_effect=DataStoreError("boom")):
            with self.assertLogs(server.logger, level="ERROR") as captured:
                TestClient(server.app).__enter__().get("/api/health")

        text = records_text(captured.records)
        self.assertIn("persistence backend is unavailable", text)
        self.assertNotIn("boom", text)

    def test_unexpected_readiness_failure_does_not_log_the_cause(self):
        cause = "postgresql+asyncpg://u:hunter2@host/db"
        with mock.patch("persistence.check_store_health", side_effect=RuntimeError(cause)):
            with self.assertLogs(server.logger, level="ERROR") as captured:
                TestClient(server.app).__enter__().get("/api/health")

        self.assertNotIn("hunter2", records_text(captured.records))

    def test_module_logger_name_is_stable(self):
        self.assertEqual("fluentpath.api", server.logger.name)

    def test_logger_uses_the_standard_library_only(self):
        module = type(server.logger).__module__
        self.assertEqual("logging", module)


if __name__ == "__main__":
    unittest.main()