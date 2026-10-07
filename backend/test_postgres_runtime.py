"""Live PostgreSQL runtime checks.

These are the only tests that execute the PostgreSQL write path, so they need a
disposable database. They are skipped unless TEST_DATABASE_URL is set, and
``db_config.require_test_database_url`` is still applied, so the ordinary test
run stays entirely on the JSON backend and can never point at staging or
production.

Run them against a throwaway database that has been migrated to head:

    $env:FLUENT_PATH_ENVIRONMENT = "test"
    $env:FLUENT_PATH_PERSISTENCE = "postgres"
    $env:TEST_DATABASE_URL = "postgresql+asyncpg://user:pass@127.0.0.1:5432/fluent_path_test"
    .\\venv\\Scripts\\python.exe -m unittest test_postgres_runtime -v
"""

import os
import unittest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import text

from db import models  # noqa: F401 - import registers ORM metadata
from db.base import Base
import server as server_module
from db_config import require_test_database_url
from persistence import STORE_NAMES
from persistence.errors import DataStoreError
from persistence.runtime import (
    _run,
    active_store,
    build_store,
    configure,
    read_store,
    revoke_token,
    shutdown,
    token_is_revoked,
    write_store,
)
from test_persistence import STAMP, STUDENT_ID, TEACHER_ID, minimal_universe


def _configured_test_url():
    """Return the disposable URL, or None so these tests skip.

    ``require_test_database_url`` refuses a URL whose database name does not
    contain ``test``, which keeps staging and production out of reach here even
    if TEST_DATABASE_URL is set carelessly.
    """
    raw = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not raw:
        return None
    try:
        return require_test_database_url({"TEST_DATABASE_URL": raw})
    except Exception:  # noqa: BLE001 - a non-test URL must skip rather than run.
        return None


TEST_URL = _configured_test_url()

# Every application table, children first, so a single TRUNCATE covers the graph.
APPLICATION_TABLES = ", ".join(
    f'"{table.name}"' for table in reversed(Base.metadata.sorted_tables)
)


def truncate_all_stores():
    """Empty every application table through the store's own event loop.

    The coroutine has to run on the same loop the engine is bound to, so it goes
    through the store bridge rather than a separate ad-hoc loop.
    """
    store = active_store()

    async def run():
        factory = await store._factory()
        async with factory() as session:
            async with session.begin():
                await session.execute(text(f"TRUNCATE {APPLICATION_TABLES} RESTART IDENTITY CASCADE"))

    _run(run())


def set_schema_revision(value):
    """Move alembic_version so the runtime guard can be exercised for real.

    ``None`` leaves the table empty, which is what an interrupted or hand-edited
    migration looks like to the guard.
    """
    store = active_store()

    async def run():
        factory = await store._factory()
        async with factory() as session:
            async with session.begin():
                await session.execute(text("DELETE FROM alembic_version"))
                if value is not None:
                    await session.execute(
                        text("INSERT INTO alembic_version (version_num) VALUES (:value)"),
                        {"value": value},
                    )

    _run(run())


#: Columns whose PostgreSQL value cannot reproduce an absent JSON key. Both are
#: read back through a default, and every consumer treats them the same way, so
#: the comparison normalizes both sides instead of hiding the difference.
COLUMN_DEFAULTS = {"devOnly": False, "zoomMeetingId": None}

#: server.py already lowercases an address on registration and on login
#: (lines 1120 and 1162), so PostgreSQL storing it folded matches the
#: application's own convention rather than changing it.
LOWERCASED_KEYS = {"email"}


def _as_utc_instant(value):
    """Reduce an ISO timestamp to its instant, so an offset change is not a difference."""
    if not isinstance(value, str):
        return value
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        return value
    return parsed.astimezone(timezone.utc).isoformat()


def comparable(value):
    """Normalize one stored value for comparison against its JSON original."""
    if isinstance(value, dict):
        return {key: comparable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [comparable(item) for item in value]
    return _as_utc_instant(value)


def comparable_records(records):
    normalized = []
    for record in records:
        item = {}
        for key, value in record.items():
            if key in LOWERCASED_KEYS and isinstance(value, str):
                value = value.strip().lower()
            item[key] = comparable(value)
        for key, default in COLUMN_DEFAULTS.items():
            if item.get(key) is None:
                item[key] = default
        normalized.append(item)
    return normalized


def _current_store_or_none():
    """The store installed right now, or None when nothing is configured yet."""
    from persistence.errors import PersistenceConfigurationError

    try:
        return active_store()
    except PersistenceConfigurationError:
        return None


class _PostgresRuntimeFixture:
    """Process-wide PostgreSQL setup shared by the live runtime test classes.

    Deliberately not a ``TestCase`` subclass: the notification class needs this
    same fixture, and inheriting the general class to get it would silently run
    every round-trip test a second time.
    """

    @classmethod
    def setUpClass(cls):
        # These tests swap the process-wide store for PostgreSQL, so the store the
        # rest of the suite already relies on has to be put back afterwards. It is
        # captured before the swap because server configures JSON at import time.
        cls.previous_store = _current_store_or_none()
        configure(build_store({
            "FLUENT_PATH_ENVIRONMENT": "test",
            "FLUENT_PATH_PERSISTENCE": "postgres",
            "TEST_DATABASE_URL": TEST_URL,
        }))
        cls.universe = minimal_universe()
        cls._reset()

    @classmethod
    def tearDownClass(cls):
        cls._reset()
        shutdown()
        if cls.previous_store is not None:
            # Hand the JSON store back, resolver and all, so later modules keep
            # writing to the temporary directory they redirected server to.
            configure(cls.previous_store)

    @classmethod
    def _reset(cls):
        truncate_all_stores()
        for name in STORE_NAMES:
            write_store(name, cls.universe[name])

    def setUp(self):
        self._reset()


@unittest.skipUnless(TEST_URL, "set TEST_DATABASE_URL to a migrated disposable database")
class PostgresRuntimeTests(_PostgresRuntimeFixture, unittest.TestCase):

    def test_every_store_round_trips(self):
        for name in STORE_NAMES:
            with self.subTest(store=name):
                self.assertEqual(
                    comparable_records(read_store(name)),
                    comparable_records(self.universe[name]),
                )

    def test_the_documented_column_normalizations_hold(self):
        # These are the only places a PostgreSQL read may differ from the JSON
        # original. Each one is either the column default or the application's
        # own convention, so it is asserted here rather than silently normalized.
        students = {record["id"]: record for record in read_store("students")}
        teacher = students[TEACHER_ID]

        # A user with no student profile still reports "" for the profile form.
        self.assertEqual(teacher["dateOfBirth"], "")
        self.assertEqual(teacher["phone"], "")

        # An absent flag reads back as the column's false default.
        self.assertIs(students[STUDENT_ID]["devOnly"], False)

        # An absent Zoom id reads back as null, and every consumer tests truthiness.
        self.assertIsNone(read_store("classes")[0]["zoomMeetingId"])

    def test_a_timestamp_keeps_its_instant_while_gaining_utc(self):
        written = {record["id"]: record for record in self.universe["students"]}[TEACHER_ID]["createdAt"]
        stored = {record["id"]: record for record in read_store("students")}[TEACHER_ID]["createdAt"]
        self.assertEqual(datetime.fromisoformat(stored), datetime.fromisoformat(written))
        self.assertTrue(stored.endswith("+00:00"))

    def test_an_update_changes_the_row_without_duplicating_it(self):
        students = read_store("students")
        updated = [
            {**record, "fullName": "محدث"} if record["id"] == STUDENT_ID else record
            for record in students
        ]
        write_store("students", updated)

        stored = read_store("students")
        self.assertEqual(len(stored), len(students))
        changed = [record for record in stored if record["id"] == STUDENT_ID]
        self.assertEqual(changed[0]["fullName"], "محدث")

    def test_a_removed_record_disappears(self):
        courses = read_store("courses")
        dropped = courses[0]["id"]
        write_store("courses", [record for record in courses if record["id"] != dropped])
        self.assertNotIn(dropped, [record["id"] for record in read_store("courses")])
        self.assertEqual(len(read_store("courses")), len(courses) - 1)

    def test_a_dangling_reference_is_rejected_and_leaves_no_partial_write(self):
        before = read_store("submissions")
        broken = [{
            "id": "sub-x",
            "homeworkId": "missing-homework",
            "studentId": STUDENT_ID,
            "answer": "x",
            "status": "submitted",
            "submittedAt": STAMP,
        }]
        with self.assertRaises(DataStoreError):
            write_store("submissions", broken)
        self.assertEqual(read_store("submissions"), before)

    def test_a_revoked_token_is_reported_as_revoked_and_stored_only_as_a_digest(self):
        token = "token-for-runtime-check"
        self.assertFalse(token_is_revoked(token))

        revoke_token(token, STUDENT_ID, datetime.now(timezone.utc) + timedelta(days=7))
        self.assertTrue(token_is_revoked(token))

        # A leaked database must not hand out live tokens.
        async def read_digest():
            store = active_store()
            factory = await store._factory()
            async with factory() as session:
                result = await session.execute(
                    text("SELECT token_id FROM revoked_tokens")
                )
                return [row[0] for row in result]

        stored = _run(read_digest())
        self.assertEqual(len(stored), 1)
        self.assertNotIn(token, stored[0])
        self.assertEqual(len(stored[0]), 64)
        self.assertTrue(all(character in "0123456789abcdef" for character in stored[0]))

    def test_repeated_writes_of_the_same_records_are_idempotent(self):
        write_store("students", self.universe["students"])
        write_store("students", self.universe["students"])
        self.assertEqual(
            comparable_records(read_store("students")),
            comparable_records(self.universe["students"]),
        )

    def test_unknown_store_names_fail_before_touching_the_database(self):
        with self.assertRaises(KeyError):
            read_store("not_a_store")
        with self.assertRaises(KeyError):
            write_store("not_a_store", [])

    def test_the_schema_guard_refuses_another_revision_on_the_real_driver(self):
        """Exercise the guard over asyncpg, not only the offline SQLite fake."""
        from db.revision import EXPECTED_SCHEMA_REVISION
        from db_config import DatabaseSettings
        from persistence.errors import SchemaVersionMismatch
        from persistence.postgres_backend import PostgresStoreBackend

        def backend():
            # A fresh backend each time: the shared one already verified the
            # revision and deliberately remembers that for its lifetime.
            return PostgresStoreBackend(DatabaseSettings(TEST_URL, "test"))

        stale = backend()
        restored = backend()
        try:
            set_schema_revision("0002_nullable_user_created_at")
            with self.assertRaises(SchemaVersionMismatch):
                _run(stale.read("students"))
            with self.assertRaises(SchemaVersionMismatch):
                _run(stale.write("students", self.universe["students"]))
            with self.assertRaises(SchemaVersionMismatch):
                _run(stale.token_is_revoked("some-token"))
        finally:
            set_schema_revision(EXPECTED_SCHEMA_REVISION)

        # The same operations succeed once the expected revision is back, which
        # shows the refusal was about the revision and nothing else.
        try:
            self.assertEqual(len(_run(restored.read("students"))),
                             len(self.universe["students"]))
        finally:
            _run(stale.close())
            _run(restored.close())

    def test_an_empty_version_table_is_refused_on_the_real_driver(self):
        from db.revision import EXPECTED_SCHEMA_REVISION
        from db_config import DatabaseSettings
        from persistence.errors import SchemaVersionMismatch
        from persistence.postgres_backend import PostgresStoreBackend

        backend = PostgresStoreBackend(DatabaseSettings(TEST_URL, "test"))
        try:
            set_schema_revision(None)
            with self.assertRaises(SchemaVersionMismatch):
                _run(backend.read("students"))
        finally:
            set_schema_revision(EXPECTED_SCHEMA_REVISION)
            _run(backend.close())


@unittest.skipUnless(TEST_URL, "set TEST_DATABASE_URL to a migrated disposable database")
class PostgresNotificationRoutingTests(_PostgresRuntimeFixture, unittest.TestCase):
    """Notification routing proven against the real driver.

    The defect these cover was invisible offline in one direction and invisible
    live in the other: a PostgreSQL store has no file, so a path-based helper
    used to fall through to the local JSON file. These run the real
    ``create_notification`` against a real database and require that the row
    lands in PostgreSQL and that no JSON file is created or touched.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Point the server's store constants at a scratch directory so any
        # stray file write is visible and cannot reach real backend/data.
        import shutil
        import tempfile
        from pathlib import Path

        cls._scratch = tempfile.TemporaryDirectory()
        cls._scratch_dir = Path(cls._scratch.name)
        cls._data_dir = Path(server_module.__file__).resolve().parent / "data"
        cls._path_names = (
            "DATA_DIR", "STUDENTS_FILE", "COURSES_FILE", "HOMEWORK_FILE", "SUBMISSIONS_FILE",
            "CLASSES_FILE", "COMMUNITY_POSTS_FILE", "COMMUNITY_REPLIES_FILE",
            "CONVERSATIONS_FILE", "MESSAGES_FILE", "REPORTS_FILE", "NOTIFICATIONS_FILE",
            "AI_SESSIONS_FILE", "AI_MESSAGES_FILE", "AI_USAGE_FILE",
        )
        cls._original_paths = {n: getattr(server_module, n) for n in cls._path_names}
        for filename in ("students.json", "courses.json", "homework.json", "classes.json"):
            shutil.copyfile(cls._data_dir / filename, cls._scratch_dir / filename)
        server_module.DATA_DIR = cls._scratch_dir
        for name in cls._path_names[1:]:
            setattr(server_module, name,
                    cls._scratch_dir / Path(getattr(server_module, name)).name)

    @classmethod
    def tearDownClass(cls):
        for name, path in cls._original_paths.items():
            setattr(server_module, name, path)
        cls._scratch.cleanup()
        super().tearDownClass()

    def _real_data_digests(self):
        import hashlib
        return {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(self._data_dir.glob("*.json"))
        }

    def test_postgres_store_reports_no_path_for_any_store(self):
        store = active_store()
        for name in STORE_NAMES:
            self.assertIsNone(store.path_for(name), name)

    def test_store_name_for_path_resolves_on_a_real_postgres_runtime(self):
        from persistence.runtime import store_name_for_path
        self.assertEqual(store_name_for_path(server_module.NOTIFICATIONS_FILE),
                         "notifications")

    def test_create_notification_writes_a_real_row_and_no_file(self):
        before = self._real_data_digests()
        scratch_file = self._scratch_dir / "notifications.json"
        self.assertFalse(scratch_file.exists())

        self.assertTrue(server_module.create_notification(
            STUDENT_ID, "live-event", "info", "Live", "Live notification"))

        stored = read_store("notifications")
        self.assertIn("live-event", [r["event_key"] for r in stored])
        row = next(r for r in stored if r["event_key"] == "live-event")
        self.assertEqual(row["recipient_user_id"], STUDENT_ID)
        self.assertFalse(scratch_file.exists())
        self.assertEqual(self._real_data_digests(), before)

    def test_duplicate_event_key_is_suppressed_in_postgres(self):
        self.assertTrue(server_module.create_notification(STUDENT_ID, "e", "info", "t", "m"))
        self.assertFalse(server_module.create_notification(STUDENT_ID, "e", "info", "t", "m"))
        self.assertEqual(
            len([r for r in read_store("notifications") if r["event_key"] == "e"]), 1)

    def test_notification_survives_a_fresh_read_from_the_database(self):
        server_module.create_notification(STUDENT_ID, "event-1", "info", "t", "m")
        # A brand new read goes back to PostgreSQL, so this proves the row is
        # really there rather than cached in the process.
        self.assertIn(
            "event-1", [r["event_key"] for r in read_store("notifications")])

    def test_backend_data_is_untouched_by_postgres_notification_work(self):
        before = self._real_data_digests()
        server_module.create_notification(STUDENT_ID, "e1", "info", "t", "m")
        server_module.create_notification(TEACHER_ID, "e2", "info", "t", "m")
        events = [r["event_key"] for r in read_store("notifications")]
        self.assertIn("e1", events)
        self.assertIn("e2", events)
        self.assertEqual(self._real_data_digests(), before)

    def test_postgres_mode_refuses_a_silent_json_fallback(self):
        scratch = self._scratch_dir / "not-a-store.json"
        with self.assertRaises(DataStoreError):
            server_module.save_json_list(scratch, [{"id": "nope"}])
        self.assertFalse(scratch.exists())


@unittest.skipUnless(TEST_URL, "set TEST_DATABASE_URL to a migrated disposable database")
class PostgresNotificationApiTests(_PostgresRuntimeFixture, unittest.TestCase):
    """The endpoint-driven form of the notification proof, on the real driver.

    ``test_notifications.py`` already proves that assigning homework notifies the
    student, but it proves it against the fake postgres-shaped store. The defect
    these tests exist for lived one layer below the endpoint: a path-based helper
    that quietly resolved a local JSON file whenever the store reported no path.
    A fake store always reports a path, so only the real driver can catch that.
    These tests therefore send the identical real HTTP request against real
    PostgreSQL with an empty scratch directory, which turns any file fallback
    into a file that visibly appears.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import tempfile
        from pathlib import Path

        cls._scratch = tempfile.TemporaryDirectory()
        cls._scratch_dir = Path(cls._scratch.name)
        cls._data_dir = Path(server_module.__file__).resolve().parent / "data"
        cls._path_names = (
            "DATA_DIR", "STUDENTS_FILE", "COURSES_FILE", "HOMEWORK_FILE", "SUBMISSIONS_FILE",
            "CLASSES_FILE", "COMMUNITY_POSTS_FILE", "COMMUNITY_REPLIES_FILE",
            "CONVERSATIONS_FILE", "MESSAGES_FILE", "REPORTS_FILE", "NOTIFICATIONS_FILE",
            "AI_SESSIONS_FILE", "AI_MESSAGES_FILE", "AI_USAGE_FILE",
        )
        cls._original_paths = {n: getattr(server_module, n) for n in cls._path_names}
        # Nothing is copied into the scratch directory on purpose. Under
        # PostgreSQL no file should be read at all, so an empty directory makes a
        # fallback visible instead of quietly succeeding against a stale copy.
        server_module.DATA_DIR = cls._scratch_dir
        for name in cls._path_names[1:]:
            setattr(server_module, name,
                    cls._scratch_dir / Path(getattr(server_module, name)).name)

    @classmethod
    def tearDownClass(cls):
        for name, path in cls._original_paths.items():
            setattr(server_module, name, path)
        cls._scratch.cleanup()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self._digests_before = self._real_data_digests()
        # Same ids as minimal_universe, so the seeded class membership and
        # homework assignment keep resolving; only the profile changes, because
        # the student has to be placed to be allowed to read notifications, and
        # the credentials, which must be real hashes because this logs in over HTTP.
        write_store("students", [
            self._user(TEACHER_ID, "teacher", "A2 - B1"),
            self._user(STUDENT_ID, "student", "A2 - B1"),
        ])
        server_module.REVOKED_TOKENS.clear()
        self.client = TestClient(server_module.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(server_module.REVOKED_TOKENS.clear)
        self.teacher_headers = self._login(TEACHER_ID)
        self.student_headers = self._login(STUDENT_ID)

    @staticmethod
    def _user(uid, role, level):
        return {
            "id": uid,
            "fullName": f"{role} {uid}",
            "email": f"{uid}@postgres-http.local",
            "passwordHash": server_module.hash_password(f"{uid}-password"),
            "role": role,
            "devOnly": False,
            "dateOfBirth": "",
            "phone": "",
            "level": level,
            "testScore": 3,
            "totalQuestions": 4,
            "testCompletedAt": STAMP,
            "courseProgress": {},
            "createdAt": STAMP,
        }

    def _login(self, uid):
        response = self.client.post("/api/login", json={
            "email": f"{uid}@postgres-http.local", "password": f"{uid}-password"})
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def _real_data_digests(self):
        import hashlib
        return {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(self._data_dir.glob("*.json"))
        }

    def _rows(self, sql, parameters=None):
        """Query through the store's own event loop, bypassing the record mapping."""
        store = active_store()

        async def run():
            factory = await store._factory()
            async with factory() as session:
                result = await session.execute(text(sql), parameters or {})
                return [dict(row._mapping) for row in result.fetchall()]

        return _run(run())

    def _assign_homework(self):
        response = self.client.post("/api/teacher/homework", headers=self.teacher_headers,
                                    json={"title": "Writing", "description": "Practice",
                                          "studentIds": [STUDENT_ID]})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["homework"]

    def test_assigning_homework_over_http_writes_a_real_notification_row(self):
        homework = self._assign_homework()

        # minimal_universe seeds one unrelated registration notification, so the
        # request is scoped to the homework event rather than the whole table.
        self.assertEqual(
            [row["event_key"] for row in self._rows(
                "SELECT event_key FROM public.notifications "
                "WHERE event_key LIKE :prefix ORDER BY event_key",
                {"prefix": "homework_assigned:%"})],
            [f"homework_assigned:{homework['id']}"],
        )
        row = self._rows(
            "SELECT recipient_user_id, type, related_entity_type, related_entity_id, "
            "is_read, severity FROM public.notifications WHERE event_key = :key",
            {"key": f"homework_assigned:{homework['id']}"},
        )[0]
        self.assertEqual(row["recipient_user_id"], STUDENT_ID)
        self.assertEqual(row["type"], "homework_assigned")
        self.assertEqual(row["related_entity_type"], "homework")
        self.assertEqual(row["related_entity_id"], homework["id"])
        self.assertEqual(row["severity"], "info")
        self.assertFalse(row["is_read"])

    def test_the_student_reads_that_same_notification_back_over_http(self):
        homework = self._assign_homework()

        listed = self.client.get("/api/me/notifications", headers=self.student_headers)
        self.assertEqual(listed.status_code, 200, listed.text)
        items = [item for item in listed.json()["notifications"]
                 if item["type"] == "homework_assigned"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["related_entity_id"], homework["id"])
        self.assertFalse(items[0]["read"])
        # The client payload deliberately drops the internal routing keys.
        self.assertNotIn("event_key", items[0])
        self.assertNotIn("recipient_user_id", items[0])

        # A read that goes back to PostgreSQL rather than to process state.
        self.assertEqual(
            [record["event_key"] for record in read_store("notifications")
             if record["event_key"].startswith("homework_assigned:")],
            [f"homework_assigned:{homework['id']}"],
        )

    def test_the_request_persists_the_homework_row_too(self):
        homework = self._assign_homework()

        rows = self._rows(
            "SELECT id, teacher_id FROM public.homework WHERE id = :id",
            {"id": homework["id"]},
        )
        self.assertEqual(rows, [{"id": homework["id"], "teacher_id": TEACHER_ID}])
        self.assertEqual(
            self._rows("SELECT student_id FROM public.homework_assignments "
                       "WHERE homework_id = :id", {"id": homework["id"]}),
            [{"student_id": STUDENT_ID}],
        )

    def test_the_whole_request_creates_no_json_file_and_touches_no_real_data(self):
        self.assertEqual(sorted(self._scratch_dir.glob("*")), [])

        self._assign_homework()

        # The regression this guards was a silent read-modify-write of a local
        # file, so the scratch directory has to still be empty afterwards and
        # real backend/data has to be byte-identical.
        self.assertEqual(sorted(self._scratch_dir.glob("*")), [])
        self.assertEqual(self._real_data_digests(), self._digests_before)