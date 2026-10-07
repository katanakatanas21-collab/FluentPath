"""Regression tests for notification persistence routing.

Defect under test
-----------------
``server.load_json_list`` / ``server.save_json_list`` resolve a *path* to a
store name through ``persistence.store_name_for_path``, which used to ask the
active backend ``path_for(name)``. ``PostgresStoreBackend`` has no file, so it
answers ``None`` for every store, the resolver returned ``None``, and the
helpers silently took their direct-file branch. On staging this sent the
registration notification to ``backend/data/notifications.json`` instead of
PostgreSQL, and it would have done the same for every other path-based store.

These tests pin the whole class, not just the one line that was observed:

* notification reads and writes go through the configured backend by store name;
* a PostgreSQL runtime cannot silently fall back to a JSON file;
* a backend failure fails closed instead of writing a file;
* the JSON backend still serves and writes its files, so development is
  unaffected;
* ``backend/data`` stays byte-identical across PostgreSQL-mode notification work.

The ``FakePostgresStore`` below reproduces the one behaviour that caused the
defect -- ``path_for`` answering ``None`` -- so the failure mode is reachable
without a database. ``test_postgres_runtime.py`` covers the same routing against
the real driver.
"""

import hashlib
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

import persistence
import server
from persistence.runtime import STORE_NAMES, store_name_for_path


BACKEND_DATA = Path(server.__file__).resolve().parent / "data"

PATH_NAMES = (
    "DATA_DIR", "STUDENTS_FILE", "COURSES_FILE", "HOMEWORK_FILE", "SUBMISSIONS_FILE",
    "CLASSES_FILE", "COMMUNITY_POSTS_FILE", "COMMUNITY_REPLIES_FILE", "CONVERSATIONS_FILE",
    "MESSAGES_FILE", "REPORTS_FILE", "NOTIFICATIONS_FILE", "AI_SESSIONS_FILE",
    "AI_MESSAGES_FILE", "AI_USAGE_FILE",
)


class FakePostgresStore:
    """A store with no file of its own, exactly like ``PostgresStoreBackend``.

    ``path_for`` returning ``None`` is not a simplification: it is the behaviour
    that made every product store path unresolvable and caused the defect.
    """

    name = "postgres"

    def __init__(self, fail_on_write=False):
        self.records = {store_name: [] for store_name in STORE_NAMES}
        self.reads = []
        self.writes = []
        self.fail_on_write = fail_on_write

    def path_for(self, store_name):
        return None

    async def read(self, store_name, *, path=None):
        self.reads.append(store_name)
        return [dict(record) for record in self.records[store_name]]

    async def write(self, store_name, records, *, path=None):
        self.writes.append(store_name)
        if self.fail_on_write:
            raise persistence.DataStoreError("Persistent storage is unavailable.")
        self.records[store_name] = [dict(record) for record in records]

    async def revoke_token(self, token, user_id, expires_at):
        return None

    async def token_is_revoked(self, token):
        return False


class PostgresRoutingTestCase(unittest.TestCase):
    """Installs a PostgreSQL-shaped backend and restores the process afterwards."""

    def setUp(self):
        self.original_paths = {name: getattr(server, name) for name in PATH_NAMES}
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.store = FakePostgresStore()
        persistence.configure(self.store)
        self.addCleanup(self.restore_json_backend)
        self.client = TestClient(server.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        server.REVOKED_TOKENS.clear()
        self.addCleanup(server.REVOKED_TOKENS.clear)

    def restore_json_backend(self):
        for name, path in self.original_paths.items():
            setattr(server, name, path)
        persistence.configure_from_environment(
            {"FLUENT_PATH_ENVIRONMENT": "development"},
            path_resolver=server.resolve_store_path,
        )

    def repoint_stores(self):
        """Point every store constant at the temp directory, as the suite does."""
        server.DATA_DIR = self.data
        for name in PATH_NAMES[1:]:
            setattr(server, name, self.data / Path(getattr(server, name)).name)

    @staticmethod
    def user(uid, role, level="A2 - B1"):
        return {
            "id": uid,
            "fullName": f"User {uid}",
            "email": f"{uid}@test.local",
            "passwordHash": server.hash_password("route-password"),
            "role": role,
            "level": level if role == "student" else None,
            "courseProgress": {},
        }


class PathResolutionTests(PostgresRoutingTestCase):
    def test_postgres_store_reports_no_path_which_is_the_root_cause(self):
        # Precondition of the defect, pinned so it cannot regress unnoticed.
        self.assertIsNone(self.store.path_for("notifications"))

    def test_store_name_resolves_for_every_product_store_path(self):
        self.repoint_stores()
        by_attribute = {attribute: store_name
                        for store_name, attribute in server._STORE_PATH_ATTRIBUTES.items()}
        for name in PATH_NAMES[1:]:
            self.assertEqual(store_name_for_path(getattr(server, name)), by_attribute[name], name)

    def test_unrelated_path_does_not_resolve_to_a_store(self):
        self.assertIsNone(store_name_for_path(self.data / "scratch.json"))


class NotificationWriteRoutingTests(PostgresRoutingTestCase):
    def test_registration_notification_routes_to_postgres_and_not_to_the_file(self):
        self.repoint_stores()
        sentinel = b'[{"id":"sentinel","recipient_user_id":"someone-else"}]\n'
        notifications_file = self.data / "notifications.json"
        notifications_file.write_bytes(sentinel)

        administrator = self.user("route-admin", "administrator")
        self.store.records["students"] = [administrator]

        response = self.client.post("/api/register", json={
            "fullName": "Route Test",
            "email": "route-test@test.local",
            "password": "Route-Test-12345",
            "dateOfBirth": "2000-01-01",
            "phone": "+10000000000",
        })
        self.assertEqual(response.status_code, 200, response.text)

        self.assertIn("notifications", self.store.writes)
        recipients = [record["recipient_user_id"] for record in self.store.records["notifications"]]
        self.assertIn("route-admin", recipients)
        events = [record["event_key"] for record in self.store.records["notifications"]]
        self.assertTrue(any(event.startswith("registration:") for event in events), events)
        self.assertEqual(notifications_file.read_bytes(), sentinel)

    def test_create_notification_uses_the_store_by_name(self):
        self.repoint_stores()
        self.assertTrue(server.create_notification(
            "recipient-1", "event-1", "info", "Title", "Message"))
        self.assertEqual(self.store.writes, ["notifications"])
        self.assertEqual(self.store.records["notifications"][0]["event_key"], "event-1")
        self.assertFalse((self.data / "notifications.json").exists())

    def test_duplicate_event_key_is_still_suppressed(self):
        self.repoint_stores()
        self.assertTrue(server.create_notification("r", "e", "info", "t", "m"))
        self.assertFalse(server.create_notification("r", "e", "info", "t", "m"))
        self.assertEqual(len(self.store.records["notifications"]), 1)

    def test_class_reminder_notification_uses_the_store(self):
        self.repoint_stores()
        starts = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        server.maybe_create_class_reminder(
            {"id": "class-1", "title": "Live", "startsAt": starts, "status": "scheduled"},
            "teacher-1")
        self.assertIn("notifications", self.store.writes)
        self.assertEqual(self.store.records["notifications"][0]["type"], "upcoming_class_reminder")

    def test_learning_notifications_use_the_store(self):
        self.repoint_stores()
        student = self.user("gamify-student", "student")
        student["gamification"] = {
            "xp": 500, "currentStreak": 3, "longestStreak": 3,
            "lastActivityDate": datetime.now(timezone.utc).date().isoformat(),
            "earnedBadges": [], "awardedActions": [],
        }
        server.create_learning_notifications(student, previous_xp=0, previous_level=1)
        self.assertIn("notifications", self.store.writes)
        types = {record["type"] for record in self.store.records["notifications"]}
        self.assertTrue({"level_up", "streak_milestone"} & types, types)


class NotificationReadRoutingTests(PostgresRoutingTestCase):
    def setUp(self):
        super().setUp()
        self.repoint_stores()
        self.student = self.user("read-student", "student")
        self.teacher = self.user("read-teacher", "teacher")
        self.store.records["students"] = [self.student, self.teacher]
        self.store.records["notifications"] = [{
            "id": "note-1",
            "recipient_user_id": "read-student",
            "event_key": "event-1",
            "type": "info",
            "title": "Title",
            "message": "Message",
            "read": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "related_entity_type": None,
            "related_entity_id": None,
            "severity": "info",
        }]
        server.REVOKED_TOKENS.clear()
        self.headers = {"Authorization": f"Bearer {server.create_access_token(self.student)}"}

    def test_list_endpoint_reads_through_the_backend(self):
        response = self.client.get("/api/me/notifications", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("notifications", self.store.reads)
        self.assertEqual([n["id"] for n in response.json()["notifications"]], ["note-1"])
        self.assertNotIn("event_key", response.json()["notifications"][0])
        self.assertFalse((self.data / "notifications.json").exists())

    def test_unread_count_reads_through_the_backend(self):
        response = self.client.get("/api/me/notifications/unread-count", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["unreadCount"], 1)

    def test_mark_read_writes_through_the_backend(self):
        response = self.client.patch("/api/me/notifications/note-1/read", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("notifications", self.store.writes)
        self.assertTrue(self.store.records["notifications"][0]["read"])
        self.assertFalse((self.data / "notifications.json").exists())

    def test_mark_all_read_writes_through_the_backend(self):
        response = self.client.post("/api/me/notifications/read-all", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("notifications", self.store.writes)
        self.assertTrue(self.store.records["notifications"][0]["read"])

    def test_another_users_notification_is_not_readable(self):
        response = self.client.patch("/api/me/notifications/note-1/read", headers={
            "Authorization": f"Bearer {server.create_access_token(self.teacher)}"})
        self.assertEqual(response.status_code, 404, response.text)


class NoSilentFallbackTests(PostgresRoutingTestCase):
    def test_postgres_mode_refuses_to_write_an_unresolved_json_file(self):
        scratch = self.data / "scratch.json"
        with self.assertRaises(persistence.DataStoreError):
            server.save_json_list(scratch, [{"id": "nope"}])
        self.assertFalse(scratch.exists())

    def test_postgres_mode_refuses_to_read_an_unresolved_json_file(self):
        scratch = self.data / "scratch.json"
        scratch.write_text('[{"id":"nope"}]\n', encoding="utf-8")
        with self.assertRaises(persistence.DataStoreError):
            server.load_json_list(scratch)

    def test_backend_failure_fails_closed_without_writing_a_file(self):
        self.repoint_stores()
        notifications_file = self.data / "notifications.json"
        self.store.fail_on_write = True
        with self.assertRaises(persistence.DataStoreError):
            server.create_notification("r", "e", "info", "t", "m")
        self.assertFalse(notifications_file.exists())

    def test_failed_write_surfaces_as_503(self):
        self.repoint_stores()
        self.store.records["students"] = [self.user("fail-admin", "administrator")]
        self.store.fail_on_write = True
        response = self.client.post("/api/register", json={
            "fullName": "Fail Test",
            "email": "fail-test@test.local",
            "password": "Fail-Test-12345",
            "dateOfBirth": "2000-01-01",
            "phone": "+10000000000",
        })
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json()["detail"], "DATA_STORE_UNAVAILABLE")
        self.assertFalse((self.data / "notifications.json").exists())


class JsonBackendTests(PostgresRoutingTestCase):
    """The JSON backend must keep working exactly as before, for development."""

    def setUp(self):
        super().setUp()
        persistence.configure_from_environment(
            {"FLUENT_PATH_ENVIRONMENT": "development"},
            path_resolver=server.resolve_store_path)
        self.repoint_stores()

    def test_store_paths_still_resolve_on_the_json_backend(self):
        self.assertEqual(store_name_for_path(server.NOTIFICATIONS_FILE), "notifications")

    def test_json_backend_still_reads_and_writes_its_file(self):
        notifications_file = self.data / "notifications.json"
        server.save_json_list(server.NOTIFICATIONS_FILE, [{"id": "json-1"}])
        self.assertTrue(notifications_file.exists())
        self.assertEqual(server.load_json_list(server.NOTIFICATIONS_FILE), [{"id": "json-1"}])

    def test_json_backend_still_creates_notifications_in_the_file(self):
        self.assertTrue(server.create_notification("r", "e", "info", "t", "m"))
        records = server.load_notifications()
        self.assertEqual(records[0]["event_key"], "e")
        self.assertTrue((self.data / "notifications.json").exists())

    def test_scratch_paths_still_work_on_the_json_backend(self):
        scratch = self.data / "scratch.json"
        server.save_json_list(scratch, [{"id": "scratch"}])
        self.assertEqual(server.load_json_list(scratch), [{"id": "scratch"}])


class BackendDataIntegrityTests(unittest.TestCase):
    """Real ``backend/data`` must not change while PostgreSQL mode is active."""

    def setUp(self):
        self.before = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(BACKEND_DATA.glob("*.json"))
        }
        self.assertIn("notifications.json", self.before)

    def tearDown(self):
        # Safety net: a regression must fail the test, never destroy real data.
        for name, digest in self.before.items():
            path = BACKEND_DATA / name
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                shutil.copyfile(Path(__file__).resolve().parent / "data" / name, path)

    def test_postgres_notification_operations_leave_backend_data_untouched(self):
        self.assertGreaterEqual(len(self.before), 14)
        store = FakePostgresStore()
        original_paths = {name: getattr(server, name) for name in PATH_NAMES}
        persistence.configure(store)
        try:
            server.create_notification("recipient", "event", "info", "Title", "Message")
            self.assertEqual(store.records["notifications"][0]["event_key"], "event")
            self.assertEqual(store.writes, ["notifications"])
        finally:
            for name, path in original_paths.items():
                setattr(server, name, path)
            persistence.configure_from_environment(
                {"FLUENT_PATH_ENVIRONMENT": "development"},
                path_resolver=server.resolve_store_path)

        after = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(BACKEND_DATA.glob("*.json"))
        }
        self.assertEqual(after, self.before)


if __name__ == "__main__":
    unittest.main()