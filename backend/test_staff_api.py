import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import server


class StaffApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path_names = (
            "DATA_DIR", "STUDENTS_FILE", "COURSES_FILE", "HOMEWORK_FILE", "CLASSES_FILE",
            "SUBMISSIONS_FILE", "COMMUNITY_POSTS_FILE", "COMMUNITY_REPLIES_FILE",
            "CONVERSATIONS_FILE", "MESSAGES_FILE", "REPORTS_FILE", "NOTIFICATIONS_FILE",
            "AI_SESSIONS_FILE", "AI_MESSAGES_FILE", "AI_USAGE_FILE",
        )
        cls.original_paths = {name: getattr(server, name) for name in cls.path_names}
        cls.original_data_dir = server.DATA_DIR
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.data_directory = Path(cls.temporary_directory.name)
        source_directory = Path(__file__).resolve().parent / "data"
        server.DATA_DIR = cls.data_directory
        for name in cls.path_names[1:]:
            setattr(server, name, cls.data_directory / Path(getattr(server, name)).name)
        for filename in ("students.json", "courses.json", "homework.json", "classes.json"):
            shutil.copyfile(source_directory / filename, cls.data_directory / filename)

        users = server.load_students()
        cls.accounts = {
            role: next(
                user for user in users
                if user.get("role", "student") == role
                and (role == "student" or user.get("devOnly"))
            )
            for role in ("student", "teacher", "administrator")
        }
        cls.passwords = {
            "student": "student-check-passphrase-2026",
            "teacher": "teacher-check-passphrase-2026",
            "administrator": "admin-check-passphrase-2026",
        }
        for role, account in cls.accounts.items():
            account["passwordHash"] = server.hash_password(cls.passwords[role])
        cls.accounts["student"].update({
            "level": "A2 - B1",
            "testScore": 2,
            "totalQuestions": 5,
        })
        cls.unassigned_student = {
            "id": "staff-api-unassigned-student",
            "fullName": "Unassigned Student",
            "email": "unassigned.staff.student@test.local",
            "passwordHash": server.hash_password("unassigned-staff-student-password"),
            "role": "student",
            "courseProgress": {},
        }
        users.append(cls.unassigned_student)
        server.save_students(users)
        server.REVOKED_TOKENS.clear()
        cls.client = TestClient(server.app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.temporary_directory.cleanup()
        server.DATA_DIR = cls.original_data_dir
        for name, path in cls.original_paths.items():
            setattr(server, name, path)

    def test_role_access_and_student_learning_flows(self):
        for origin in ("http://localhost:3000", "http://127.0.0.1:3000"):
            with self.subTest(origin=origin):
                preflight = self.client.options("/api/login", headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                })
                self.assertEqual(preflight.status_code, 200)
                self.assertEqual(preflight.headers.get("access-control-allow-origin"), origin)

        tokens = {}
        for role, account in self.accounts.items():
            response = self.client.post("/api/login", json={
                "email": account["email"],
                "password": self.passwords[role],
            })
            self.assertEqual(response.status_code, 200, role)
            tokens[role] = response.json()["access_token"]

        invalid_login = self.client.post("/api/login", json={
            "email": self.accounts["student"]["email"],
            "password": "invalid-passphrase",
        })
        self.assertEqual(invalid_login.status_code, 401)

        student_headers = {"Authorization": f"Bearer {tokens['student']}"}
        student_profile = self.client.get("/api/me", headers=student_headers)
        self.assertEqual(student_profile.status_code, 200)
        self.assertEqual(student_profile.json()["email"], self.accounts["student"]["email"])
        self.assertNotIn("passwordHash", student_profile.json())
        self.assertEqual(self.client.get("/api/teacher/dashboard", headers=student_headers).status_code, 403)
        self.assertEqual(self.client.get("/api/admin/dashboard", headers=student_headers).status_code, 403)

        courses_response = self.client.get("/api/courses", headers=student_headers)
        self.assertEqual(courses_response.status_code, 200)
        locked_course = next(
            (course for course in courses_response.json()["courses"] if course["locked"]),
            None,
        )
        if locked_course:
            self.assertEqual(
                self.client.get(
                    f"/api/courses/{locked_course['id']}",
                    headers=student_headers,
                ).status_code,
                403,
            )
        available_course = next(
            course for course in courses_response.json()["courses"]
            if course["available"]
        )
        course_response = self.client.get(
            f"/api/courses/{available_course['id']}",
            headers=student_headers,
        )
        self.assertEqual(course_response.status_code, 200)
        lesson = course_response.json()["lessons"][0]
        completion = self.client.post(
            f"/api/me/courses/{available_course['id']}/lessons/{lesson['id']}/complete",
            headers=student_headers,
        )
        self.assertEqual(completion.status_code, 200)
        self.assertGreaterEqual(completion.json()["progress"]["completedCount"], 1)
        test_result = self.client.post(
            "/api/test-results",
            headers=student_headers,
            json={"answers": [1, 1, 2, 3, 0]},
        )
        self.assertEqual(test_result.status_code, 200)
        self.assertEqual(
            self.client.get("/api/me", headers=student_headers).json()["level"],
            "B2 - C1",
        )

        teacher_headers = {"Authorization": f"Bearer {tokens['teacher']}"}
        for path in (
            "/api/teacher/dashboard",
            "/api/teacher/students",
            "/api/teacher/courses",
            "/api/teacher/homework",
            "/api/teacher/classes",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path, headers=teacher_headers).status_code, 200)
        teacher_roster = self.client.get("/api/teacher/students", headers=teacher_headers).json()["students"]
        self.assertNotIn(self.unassigned_student["id"], [student["id"] for student in teacher_roster])
        self.assertTrue(all(not {"email", "phone", "dateOfBirth"}.intersection(student) for student in teacher_roster))
        unauthorized_assignment = self.client.post(
            "/api/teacher/homework",
            headers=teacher_headers,
            json={"title": "Private assignment", "description": "Should be blocked", "studentIds": [self.unassigned_student["id"]]},
        )
        self.assertEqual(unauthorized_assignment.status_code, 403)
        self.assertEqual(self.client.post(
            "/api/teacher/homework",
            headers=teacher_headers,
            json={
                "title": "Temporary test item",
                "description": "Isolated backend integration test",
                "courseId": available_course["id"],
            },
        ).status_code, 200)
        self.assertEqual(self.client.get("/api/admin/dashboard", headers=teacher_headers).status_code, 403)

        administrator_headers = {"Authorization": f"Bearer {tokens['administrator']}"}
        for path in ("/api/admin/dashboard", "/api/admin/users", "/api/admin/courses"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path, headers=administrator_headers).status_code, 200)
        admin_users = self.client.get("/api/admin/users", headers=administrator_headers).json()["users"]
        self.assertTrue(all(not {"phone", "dateOfBirth"}.intersection(user) for user in admin_users))
        self.assertEqual(self.client.get("/api/teacher/dashboard", headers=administrator_headers).status_code, 403)

        forged_token = server.jwt.encode({
            "sub": self.accounts["student"]["id"],
            "role": "administrator",
            "exp": server.datetime.now(server.timezone.utc) + server.timedelta(minutes=5),
        }, server.JWT_SECRET, algorithm=server.JWT_ALGORITHM)
        forged_headers = {"Authorization": f"Bearer {forged_token}"}
        self.assertEqual(self.client.get("/api/admin/dashboard", headers=forged_headers).status_code, 403)

        self.assertEqual(self.client.post("/api/logout", headers=student_headers).status_code, 200)
        self.assertEqual(self.client.get("/api/me", headers=student_headers).status_code, 401)


if __name__ == "__main__":
    unittest.main()
