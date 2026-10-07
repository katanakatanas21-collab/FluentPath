import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

import server
from persistence.runtime import read_store


class HomeworkWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path_names = (
            "DATA_DIR", "STUDENTS_FILE", "COURSES_FILE", "HOMEWORK_FILE", "CLASSES_FILE",
            "SUBMISSIONS_FILE", "COMMUNITY_POSTS_FILE", "COMMUNITY_REPLIES_FILE",
            "CONVERSATIONS_FILE", "MESSAGES_FILE", "REPORTS_FILE", "NOTIFICATIONS_FILE",
            "AI_SESSIONS_FILE", "AI_MESSAGES_FILE", "AI_USAGE_FILE",
        )
        cls.original_paths = {name: getattr(server, name) for name in cls.path_names}
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.data_directory = Path(cls.temporary_directory.name)
        source_directory = Path(__file__).resolve().parent / "data"
        for filename in ("students.json", "courses.json", "homework.json", "classes.json"):
            shutil.copyfile(source_directory / filename, cls.data_directory / filename)

        server.DATA_DIR = cls.data_directory
        for name in cls.path_names[1:]:
            setattr(server, name, cls.data_directory / Path(getattr(server, name)).name)

        users = server.load_students()
        cls.owner = next(user for user in users if user.get("role") == "teacher" and user.get("devOnly"))
        cls.owner_password = "homework-owner-test-password"
        cls.owner["passwordHash"] = server.hash_password(cls.owner_password)
        cls.other_teacher = {
            "id": "other-teacher-homework-test",
            "fullName": "Other Teacher",
            "email": "other.teacher.homework@test.local",
            "passwordHash": server.hash_password("other-teacher-test-password"),
            "role": "teacher",
            "dateOfBirth": "",
            "phone": "",
            "courseProgress": {},
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        users.append(cls.other_teacher)

        students = [user for user in users if user.get("role", "student") == "student"]
        for student in students[:2]:
            student["level"] = "A2 - B1"
        if len(students) < 2:
            second_student = {
                "id": "second-student-homework-test",
                "fullName": "Second Student",
                "email": "second.student.homework@test.local",
                "passwordHash": server.hash_password("second-student-test-password"),
                "role": "student",
                "level": "A2 - B1",
                "courseProgress": {},
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
            users.append(second_student)
            students.append(second_student)
        cls.students = students[:2]
        cls.student_passwords = {}
        for index, student in enumerate(cls.students):
            password = f"homework-student-{index}-test-password"
            student["passwordHash"] = server.hash_password(password)
            cls.student_passwords[student["id"]] = password

        cls.administrator = next(user for user in users if user.get("role") == "administrator" and user.get("devOnly"))
        cls.admin_password = "homework-admin-test-password"
        cls.administrator["passwordHash"] = server.hash_password(cls.admin_password)
        server.save_students(users)
        server.REVOKED_TOKENS.clear()
        cls.client = TestClient(server.app)
        cls.client.__enter__()
        cls.tokens = {
            "teacher": cls.login(cls.owner, cls.owner_password),
            "otherTeacher": cls.login(cls.other_teacher, "other-teacher-test-password"),
            "admin": cls.login(cls.administrator, cls.admin_password),
        }
        for student in cls.students:
            cls.tokens[student["id"]] = cls.login(student, cls.student_passwords[student["id"]])

    @classmethod
    def login(cls, account, password):
        response = cls.client.post("/api/login", json={"email": account["email"], "password": password})
        if response.status_code != 200:
            raise AssertionError(f"Unable to log in {account['email']}: {response.text}")
        return response.json()["access_token"]

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.temporary_directory.cleanup()
        for name, original_path in cls.original_paths.items():
            setattr(server, name, original_path)
        server.REVOKED_TOKENS.clear()

    def headers(self, account):
        return {"Authorization": f"Bearer {self.tokens[account]}"}

    def test_assign_submit_review_grade_and_privacy(self):
        teacher_headers = self.headers("teacher")
        first_student, second_student = self.students
        due_date = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        create_response = self.client.post("/api/teacher/homework", headers=teacher_headers, json={
            "title": "Write about your hometown",
            "description": "Write a short paragraph about a place you know.",
            "courseId": "cefr-a0-a1",
            "studentIds": [first_student["id"]],
            "dueDate": due_date,
        })
        self.assertEqual(create_response.status_code, 200, create_response.text)
        homework = create_response.json()["homework"]
        homework_id = homework["id"]
        self.assertEqual(homework["teacherId"], self.owner["id"])
        self.assertEqual(homework["assignedStudentIds"], [first_student["id"]])
        self.assertIsNotNone(homework["dueDate"])

        restricted_response = self.client.post("/api/teacher/homework", headers=teacher_headers, json={
            "title": "Advanced course restriction",
            "description": "This course is above the current student level.",
            "courseId": "cefr-b1-b2",
            "level": "A0",
        })
        self.assertEqual(restricted_response.status_code, 200, restricted_response.text)

        student_headers = self.headers(first_student["id"])
        other_student_headers = self.headers(second_student["id"])
        assigned_list = self.client.get("/api/student/homework", headers=student_headers)
        self.assertEqual(assigned_list.status_code, 200)
        self.assertIn(homework_id, [item["id"] for item in assigned_list.json()["homework"]])
        self.assertNotIn(
            restricted_response.json()["homework"]["id"],
            [item["id"] for item in assigned_list.json()["homework"]],
        )
        other_list = self.client.get("/api/student/homework", headers=other_student_headers)
        self.assertNotIn(homework_id, [item["id"] for item in other_list.json()["homework"]])
        self.assertEqual(self.client.get(f"/api/student/homework/{homework_id}", headers=other_student_headers).status_code, 404)
        self.assertEqual(self.client.post(
            f"/api/student/homework/{homework_id}/submissions",
            headers=other_student_headers,
            json={"answer": "Not assigned to me"},
        ).status_code, 404)
        self.assertEqual(self.client.post("/api/teacher/homework", headers=student_headers, json={
            "title": "Unauthorized", "description": "Student should not create", "courseId": "cefr-a0-a1",
        }).status_code, 403)

        detail = self.client.get(f"/api/student/homework/{homework_id}", headers=student_headers)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["homework"]["description"], "Write a short paragraph about a place you know.")
        self.assertNotIn("assignedStudentIds", detail.json()["homework"])
        self.assertNotIn("teacherId", detail.json()["homework"])
        submit_response = self.client.post(
            f"/api/student/homework/{homework_id}/submissions",
            headers=student_headers,
            json={"answer": "My hometown is a quiet place near the coast."},
        )
        self.assertEqual(submit_response.status_code, 200, submit_response.text)
        submission = submit_response.json()["submission"]
        self.assertEqual(submission["status"], "submitted")
        # Asserted through the runtime bridge rather than by opening the JSON
        # file, so the same assertion holds whichever backend is installed.
        stored = next(r for r in read_store("submissions")
                      if r["id"] == submission["id"])
        self.assertEqual(stored["answer"], submission["answer"])
        self.assertEqual(self.client.patch(
            f"/api/teacher/homework/{homework_id}/submissions/{submission['id']}/grade",
            headers=student_headers,
            json={"grade": 90, "teacherFeedback": "Well done"},
        ).status_code, 403)

        submissions_path = f"/api/teacher/homework/{homework_id}/submissions"
        review = self.client.get(submissions_path, headers=teacher_headers)
        self.assertEqual(review.status_code, 200)
        self.assertEqual(len(review.json()["submissions"]), 1)
        self.assertEqual(review.json()["submissions"][0]["student"]["id"], first_student["id"])

        other_teacher_headers = self.headers("otherTeacher")
        self.assertEqual(self.client.get(submissions_path, headers=other_teacher_headers).status_code, 403)
        grade_path = f"/api/teacher/homework/{homework_id}/submissions/{submission['id']}/grade"
        self.assertEqual(self.client.patch(grade_path, headers=other_teacher_headers, json={
            "grade": 10, "teacherFeedback": "Unauthorized teacher",
        }).status_code, 403)

        grade_response = self.client.patch(grade_path, headers=teacher_headers, json={
            "grade": 92, "teacherFeedback": "Clear writing and useful details.",
        })
        self.assertEqual(grade_response.status_code, 200, grade_response.text)
        self.assertEqual(grade_response.json()["submission"]["status"], "graded")
        student_result = self.client.get(f"/api/student/homework/{homework_id}", headers=student_headers)
        self.assertEqual(student_result.status_code, 200)
        self.assertEqual(student_result.json()["homework"]["submission"]["grade"], 92)
        self.assertEqual(student_result.json()["homework"]["submission"]["teacherFeedback"], "Clear writing and useful details.")
        self.assertEqual(self.client.post(
            f"/api/student/homework/{homework_id}/submissions",
            headers=student_headers,
            json={"answer": "Changed after grading"},
        ).status_code, 409)

        administrator_headers = self.headers("admin")
        self.assertEqual(self.client.get("/api/student/homework", headers=administrator_headers).status_code, 403)
        self.assertEqual(self.client.get("/api/teacher/homework", headers=administrator_headers).status_code, 403)


if __name__ == "__main__":
    unittest.main()