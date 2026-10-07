import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import server


INVALID_CREDENTIALS_DETAIL = "البريد الإلكتروني أو كلمة المرور غير صحيحة"


class DevAccountAuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path_names = (
            "DATA_DIR", "STUDENTS_FILE", "COURSES_FILE", "HOMEWORK_FILE", "SUBMISSIONS_FILE",
            "CLASSES_FILE", "COMMUNITY_POSTS_FILE", "COMMUNITY_REPLIES_FILE",
            "CONVERSATIONS_FILE", "MESSAGES_FILE", "REPORTS_FILE", "NOTIFICATIONS_FILE",
            "AI_SESSIONS_FILE", "AI_MESSAGES_FILE", "AI_USAGE_FILE",
        )
        cls.original_paths = {name: getattr(server, name) for name in cls.path_names}
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.data_directory = Path(cls.temporary_directory.name)
        for filename in ("students.json", "courses.json", "homework.json", "classes.json"):
            shutil.copyfile(Path(__file__).resolve().parent / "data" / filename, cls.data_directory / filename)
        server.DATA_DIR = cls.data_directory
        for name in cls.path_names[1:]:
            setattr(server, name, cls.data_directory / Path(getattr(server, name)).name)

        cls.dev_teacher_password = "dev-account-teacher-password"
        cls.dev_admin_password = "dev-account-admin-password"
        cls.student_password = "dev-account-student-password"
        cls.teacher_password = "dev-account-regular-teacher-password"

        users = [
            {
                "id": "dev-only-teacher",
                "fullName": "Development Teacher",
                "email": "dev.only.teacher@test.local",
                "passwordHash": server.hash_password(cls.dev_teacher_password),
                "role": "teacher",
                "devOnly": True,
                "courseProgress": {},
            },
            {
                "id": "dev-only-administrator",
                "fullName": "Development Administrator",
                "email": "dev.only.admin@test.local",
                "passwordHash": server.hash_password(cls.dev_admin_password),
                "role": "administrator",
                "devOnly": True,
                "courseProgress": {},
            },
            {
                "id": "regular-student",
                "fullName": "Regular Student",
                "email": "regular.student@test.local",
                "passwordHash": server.hash_password(cls.student_password),
                "role": "student",
                "devOnly": False,
                "courseProgress": {},
            },
            {
                "id": "regular-teacher",
                "fullName": "Regular Teacher",
                "email": "regular.teacher@test.local",
                "passwordHash": server.hash_password(cls.teacher_password),
                "role": "teacher",
                "courseProgress": {},
            },
        ]
        server.save_students(users)

        server.REVOKED_TOKENS.clear()
        cls.client = TestClient(server.app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.temporary_directory.cleanup()
        for name, path in cls.original_paths.items():
            setattr(server, name, path)
        server.REVOKED_TOKENS.clear()

    def tearDown(self):
        server.REVOKED_TOKENS.clear()

    def attempt_login(self, email, password):
        return self.client.post("/api/login", json={"email": email, "password": password})

    def assertRejected(self, response):
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], INVALID_CREDENTIALS_DETAIL)
        self.assertEqual(response.headers.get("WWW-Authenticate"), "Bearer")
        self.assertNotIn("access_token", response.json())

    def assertAccepted(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertIn("access_token", payload)
        self.assertTrue(payload["access_token"])

    def test_development_teacher_is_rejected_in_staging(self):
        with patch.object(server, "APP_ENVIRONMENT", "staging"):
            self.assertRejected(
                self.attempt_login("dev.only.teacher@test.local", self.dev_teacher_password)
            )

    def test_development_administrator_is_rejected_in_staging(self):
        with patch.object(server, "APP_ENVIRONMENT", "staging"):
            self.assertRejected(
                self.attempt_login("dev.only.admin@test.local", self.dev_admin_password)
            )

    def test_development_account_is_rejected_in_production(self):
        with patch.object(server, "APP_ENVIRONMENT", "production"):
            self.assertRejected(
                self.attempt_login("dev.only.teacher@test.local", self.dev_teacher_password)
            )
            self.assertRejected(
                self.attempt_login("dev.only.admin@test.local", self.dev_admin_password)
            )

    def test_development_account_is_rejected_in_test_environment(self):
        with patch.object(server, "APP_ENVIRONMENT", "test"):
            self.assertRejected(
                self.attempt_login("dev.only.teacher@test.local", self.dev_teacher_password)
            )

    def test_development_account_still_authenticates_in_development(self):
        with patch.object(server, "APP_ENVIRONMENT", "development"):
            self.assertAccepted(
                self.attempt_login("dev.only.teacher@test.local", self.dev_teacher_password)
            )
            self.assertAccepted(
                self.attempt_login("dev.only.admin@test.local", self.dev_admin_password)
            )

    def test_regular_accounts_authenticate_in_development(self):
        with patch.object(server, "APP_ENVIRONMENT", "development"):
            self.assertAccepted(
                self.attempt_login("regular.student@test.local", self.student_password)
            )
            self.assertAccepted(
                self.attempt_login("regular.teacher@test.local", self.teacher_password)
            )

    def test_regular_accounts_authenticate_in_staging(self):
        with patch.object(server, "APP_ENVIRONMENT", "staging"):
            self.assertAccepted(
                self.attempt_login("regular.student@test.local", self.student_password)
            )
            self.assertAccepted(
                self.attempt_login("regular.teacher@test.local", self.teacher_password)
            )

    def test_regular_accounts_authenticate_in_production(self):
        with patch.object(server, "APP_ENVIRONMENT", "production"):
            self.assertAccepted(
                self.attempt_login("regular.student@test.local", self.student_password)
            )

    def test_rejection_response_is_indistinguishable_from_wrong_password(self):
        with patch.object(server, "APP_ENVIRONMENT", "staging"):
            blocked = self.attempt_login("dev.only.teacher@test.local", self.dev_teacher_password)
            wrong_password = self.attempt_login("dev.only.teacher@test.local", "not-the-password")
        self.assertEqual(blocked.status_code, wrong_password.status_code)
        self.assertEqual(blocked.json(), wrong_password.json())
        self.assertEqual(
            blocked.headers.get("WWW-Authenticate"),
            wrong_password.headers.get("WWW-Authenticate"),
        )

    def test_dev_account_rejection_requires_correct_password_first(self):
        with patch.object(server, "APP_ENVIRONMENT", "staging"):
            self.assertRejected(
                self.attempt_login("dev.only.teacher@test.local", "wrong-password-entirely")
            )

    def test_registration_never_produces_a_development_account(self):
        self.assertFalse(
            any(key in server.StudentRegister.model_fields for key in ("devOnly", "role", "dev_only"))
        )
        with patch.object(server, "APP_ENVIRONMENT", "staging"):
            response = self.client.post("/api/register", json={
                "fullName": "Newly Registered",
                "email": "newly.registered@test.local",
                "password": "newly-registered-password",
                "dateOfBirth": "2000-01-01",
                "phone": "",
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["student"].get("devOnly"))
        created = next(
            user for user in server.load_students()
            if user["email"] == "newly.registered@test.local"
        )
        self.assertFalse(created.get("devOnly", False))

    def test_me_endpoint_still_serves_regular_accounts_after_login(self):
        with patch.object(server, "APP_ENVIRONMENT", "staging"):
            login = self.attempt_login("regular.student@test.local", self.student_password)
            self.assertAccepted(login)
            token = login.json()["access_token"]
            me = self.client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me.status_code, 200, me.text)
        self.assertEqual(me.json()["id"], "regular-student")


if __name__ == "__main__":
    unittest.main()