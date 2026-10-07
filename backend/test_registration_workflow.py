import unittest
from datetime import datetime
import os
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient

import server


class RegistrationWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path_names = (
            "DATA_DIR", "STUDENTS_FILE", "COURSES_FILE", "HOMEWORK_FILE", "SUBMISSIONS_FILE",
            "CLASSES_FILE", "COMMUNITY_POSTS_FILE", "COMMUNITY_REPLIES_FILE", "CONVERSATIONS_FILE",
            "MESSAGES_FILE", "REPORTS_FILE", "NOTIFICATIONS_FILE", "AI_SESSIONS_FILE",
            "AI_MESSAGES_FILE", "AI_USAGE_FILE",
        )
        cls.original_paths = {name: getattr(server, name) for name in cls.path_names}
        cls.data_directory = Path(__file__).resolve().parent / ".qa-tests" / f"registration-{uuid4().hex}"
        cls.data_directory.mkdir(parents=True)
        server.DATA_DIR = cls.data_directory
        for name in cls.path_names[1:]:
            setattr(server, name, cls.data_directory / Path(getattr(server, name)).name)
        cls.client = TestClient(server.app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        for name, path in cls.original_paths.items():
            setattr(server, name, path)
        for name in cls.path_names[1:]:
            (cls.data_directory / Path(cls.original_paths[name]).name).unlink(missing_ok=True)
        for scratch_name in ("notifications.json", "atomic-test.json"):
            (cls.data_directory / scratch_name).unlink(missing_ok=True)
        cls.data_directory.rmdir()
        server.REVOKED_TOKENS.clear()

    def setUp(self):
        self.existing_student = self.make_user("existing-student", "student", "A2 - B1")
        self.teacher = self.make_user("existing-teacher", "teacher", None)
        self.administrator = self.make_user("existing-admin", "administrator", None)
        server.save_students([self.existing_student, self.teacher, self.administrator])
        for path_name in self.path_names[2:]:
            server.save_json_list(getattr(server, path_name), [])
        server.REVOKED_TOKENS.clear()
        self.headers = {
            role: {"Authorization": f"Bearer {server.create_access_token(user)}"}
            for role, user in (
                ("existing", self.existing_student),
                ("teacher", self.teacher),
                ("admin", self.administrator),
            )
        }

    @staticmethod
    def make_user(user_id, role, level):
        return {
            "id": user_id,
            "fullName": user_id,
            "email": f"{user_id}@test.local",
            "passwordHash": server.hash_password(f"{user_id}-secure-password"),
            "role": role,
            "level": level,
            "testScore": 2 if level else None,
            "totalQuestions": 5 if level else None,
            "courseProgress": {},
        }

    def register(self, email="new.student@test.local", password="new-student-secure-password"):
        return self.client.post("/api/register", json={
            "fullName": "New Student",
            "email": email,
            "password": password,
            "dateOfBirth": "2000-01-01",
            "phone": "",
        })

    def test_registration_persists_hashed_account_and_returns_authenticated_student(self):
        password = "new-student-secure-password"
        response = self.register(password=password)
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["token_type"], "bearer")
        self.assertNotIn("passwordHash", payload["student"])
        self.assertEqual(payload["student"]["role"], "student")
        self.assertIsNone(payload["student"]["level"])
        self.assertIsNone(payload["student"]["testCompletedAt"])

        stored = next(user for user in server.load_students() if user["email"] == "new.student@test.local")
        self.assertNotEqual(stored["passwordHash"], password)
        created_at = datetime.fromisoformat(stored["createdAt"].replace("Z", "+00:00"))
        self.assertIsNotNone(created_at.tzinfo)
        self.assertEqual(created_at.utcoffset().total_seconds(), 0)
        self.assertTrue(server.verify_password(password, stored["passwordHash"]))
        self.assertEqual(len(stored["passwordHash"].split(":", 1)[1]), 64)

        headers = {"Authorization": f"Bearer {payload['access_token']}"}
        profile = self.client.get("/api/me", headers=headers)
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.json()["id"], payload["student"]["id"])
        self.assertEqual(profile.json()["role"], "student")
        self.assertNotIn("passwordHash", profile.json())

    def test_cors_allows_only_the_configured_local_frontend_origins(self):
        for origin in ("http://localhost:3000", "http://127.0.0.1:3000"):
            response = self.client.options(
                "/api/register",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers.get("access-control-allow-origin"), origin)

        rejected = self.client.options(
            "/api/register",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertNotEqual(rejected.headers.get("access-control-allow-origin"), "https://untrusted.example")

    def test_corrupt_store_returns_generic_503_without_overwriting_existing_bytes(self):
        path = server.DATA_DIR / "notifications.json"
        original = b'{"unexpected":"object"}'
        path.write_bytes(original)

        response = self.client.get("/api/me/notifications", headers=self.headers["existing"])

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "DATA_STORE_UNAVAILABLE"})
        self.assertEqual(path.read_bytes(), original)

    def test_atomic_json_write_failure_preserves_previous_store(self):
        path = server.DATA_DIR / "atomic-test.json"
        original = '[{"id":"preserved"}]'
        path.write_text(original, encoding="utf-8")

        with patch.object(server.os, "replace", side_effect=OSError("replace failed")):
            with self.assertRaises(server.DataStoreError):
                server.save_json_list(path, [{"id": "replacement"}])

        self.assertEqual(path.read_text(encoding="utf-8"), original)
        self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_transient_sharing_failure_on_replace_is_retried(self):
        path = server.DATA_DIR / "atomic-test.json"
        path.write_text('[{"id":"preserved"}]', encoding="utf-8")
        sharing_violation = PermissionError(13, "Access is denied")
        sharing_violation.winerror = 5
        real_replace = os.replace
        attempts = []

        def flaky_replace(source, target):
            attempts.append((source, target))
            if len(attempts) < 3:
                raise sharing_violation
            return real_replace(source, target)

        with patch.object(server, "time"), patch.object(server.os, "replace", side_effect=flaky_replace):
            server.save_json_list(path, [{"id": "after-retry"}])

        self.assertEqual(len(attempts), 3)
        self.assertEqual([record["id"] for record in server.load_json_list(path)], ["after-retry"])
        self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_persistent_sharing_failure_fails_closed_after_bounded_retries(self):
        path = server.DATA_DIR / "atomic-test.json"
        original = '[{"id":"preserved"}]'
        path.write_text(original, encoding="utf-8")
        sharing_violation = PermissionError(13, "Access is denied")
        sharing_violation.winerror = 5
        attempts = []

        def always_locked(source, target):
            attempts.append((source, target))
            raise sharing_violation

        with patch.object(server, "time"), patch.object(server.os, "replace", side_effect=always_locked):
            with self.assertRaises(server.DataStoreError):
                server.save_json_list(path, [{"id": "replacement"}])

        self.assertEqual(len(attempts), server.STORE_REPLACE_ATTEMPTS)
        self.assertEqual(path.read_text(encoding="utf-8"), original)
        self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_non_transient_replace_failure_is_not_retried(self):
        path = server.DATA_DIR / "atomic-test.json"
        original = '[{"id":"preserved"}]'
        path.write_text(original, encoding="utf-8")
        attempts = []

        def out_of_space(source, target):
            attempts.append((source, target))
            raise OSError(28, "No space left on device")

        with patch.object(server, "time"), patch.object(server.os, "replace", side_effect=out_of_space):
            with self.assertRaises(server.DataStoreError):
                server.save_json_list(path, [{"id": "replacement"}])

        self.assertEqual(len(attempts), 1)
        self.assertEqual(path.read_text(encoding="utf-8"), original)
        self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_duplicate_email_is_rejected_case_insensitively_without_second_record(self):
        first = self.register("Duplicate.Student@test.local")
        self.assertEqual(first.status_code, 200)
        before = len(server.load_students())
        duplicate = self.register(" duplicate.student@TEST.local ")
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(len(server.load_students()), before)

    def test_unplaced_student_cannot_use_student_features_before_test(self):
        registration = self.register()
        headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}
        response = self.client.get("/api/me/gamification", headers=headers)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "PLACEMENT_REQUIRED")
        self.assertEqual(self.client.get("/api/me", headers=headers).status_code, 200)
        forged_result = self.client.post("/api/test-results", headers=headers, json={
            "score": 5,
            "totalQuestions": 5,
            "level": "C1+",
        })
        self.assertEqual(forged_result.status_code, 422)
        self.assertIsNone(self.client.get("/api/me", headers=headers).json()["level"])

    def test_placement_result_saves_for_authenticated_student_then_logout_login_persists_it(self):
        registration = self.register()
        headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}
        result = self.client.post("/api/test-results", headers=headers, json={
            "answers": [1, 1, 2, 3, 0],
        })
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["result"]["score"], 4)
        profile = self.client.get("/api/me", headers=headers).json()
        self.assertEqual(profile["level"], "B2 - C1")
        self.assertEqual(profile["testScore"], 4)
        self.assertEqual(profile["totalQuestions"], 5)
        self.assertTrue(profile["testCompletedAt"])
        self.assertEqual(self.client.get("/api/me/gamification", headers=headers).status_code, 200)

        logout = self.client.post("/api/logout", headers=headers)
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(self.client.get("/api/me", headers=headers).status_code, 401)

        login = self.client.post("/api/login", json={
            "email": "new.student@test.local",
            "password": "new-student-secure-password",
        })
        self.assertEqual(login.status_code, 200)
        self.assertNotEqual(login.json()["access_token"], registration.json()["access_token"])
        new_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        relogged_profile = self.client.get("/api/me", headers=new_headers)
        self.assertEqual(relogged_profile.status_code, 200)
        self.assertEqual(relogged_profile.json()["level"], "B2 - C1")
        self.assertEqual(relogged_profile.json()["testScore"], 4)
        self.assertTrue(relogged_profile.json()["testCompletedAt"])

    def test_existing_students_and_staff_authorization_remain_unchanged(self):
        self.assertEqual(self.client.get("/api/me/gamification", headers=self.headers["existing"]).status_code, 200)
        self.assertEqual(self.client.get("/api/teacher/dashboard", headers=self.headers["teacher"]).status_code, 200)
        self.assertEqual(self.client.get("/api/admin/dashboard", headers=self.headers["admin"]).status_code, 200)
        self.assertEqual(self.client.get("/api/teacher/dashboard", headers=self.headers["existing"]).status_code, 403)
        self.assertEqual(self.client.get("/api/admin/dashboard", headers=self.headers["teacher"]).status_code, 403)

    def test_default_json_store_is_stable_across_working_directories(self):
        source_backend = Path(server.__file__).resolve().parent
        configured_store = self.original_paths["DATA_DIR"]
        self.assertTrue(configured_store.is_absolute())
        self.assertEqual(configured_store, source_backend / "data")


if __name__ == "__main__":
    unittest.main()
