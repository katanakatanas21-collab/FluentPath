import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

import server


class SocialWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path_names = (
            "DATA_DIR", "STUDENTS_FILE", "COURSES_FILE", "HOMEWORK_FILE", "SUBMISSIONS_FILE", "CLASSES_FILE",
            "COMMUNITY_POSTS_FILE", "COMMUNITY_REPLIES_FILE", "CONVERSATIONS_FILE", "MESSAGES_FILE", "REPORTS_FILE",
            "NOTIFICATIONS_FILE", "AI_SESSIONS_FILE", "AI_MESSAGES_FILE", "AI_USAGE_FILE",
        )
        cls.original_paths = {name: getattr(server, name) for name in cls.path_names}
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.data_directory = Path(cls.temporary_directory.name)
        source = Path(__file__).resolve().parent / "data"
        for filename in ("students.json", "courses.json", "homework.json", "classes.json"):
            shutil.copyfile(source / filename, cls.data_directory / filename)
        server.DATA_DIR = cls.data_directory
        for name in cls.path_names[1:]:
            server_value = cls.data_directory / Path(getattr(server, name)).name
            setattr(server, name, server_value)
        for name in cls.path_names[6:]:
            getattr(server, name).write_text("[]\n", encoding="utf-8")

        users = server.load_students()
        cls.teacher = next(user for user in users if user.get("role") == "teacher" and user.get("devOnly"))
        cls.teacher_password = "social-teacher-test-password"
        cls.teacher["passwordHash"] = server.hash_password(cls.teacher_password)
        cls.other_teacher = {
            "id": "social-other-teacher",
            "fullName": "Other Teacher",
            "email": "social.other.teacher@test.local",
            "passwordHash": server.hash_password("social-other-teacher-password"),
            "role": "teacher",
            "courseProgress": {},
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        users.append(cls.other_teacher)
        students = [user for user in users if user.get("role", "student") == "student"]
        while len(students) < 2:
            student = {
                "id": f"social-student-{len(students)}",
                "fullName": f"Social Student {len(students) + 1}",
                "email": f"social.student.{len(students)}@test.local",
                "passwordHash": "",
                "role": "student",
                "level": "A2 - B1",
                "courseProgress": {},
            }
            users.append(student)
            students.append(student)
        cls.students = students[:2]
        cls.student_passwords = []
        for index, student in enumerate(cls.students):
            student["level"] = "A2 - B1"
            password = f"social-student-{index}-test-password"
            student["passwordHash"] = server.hash_password(password)
            cls.student_passwords.append(password)
        cls.admin = next(user for user in users if user.get("role") == "administrator" and user.get("devOnly"))
        cls.admin_password = "social-admin-test-password"
        cls.admin["passwordHash"] = server.hash_password(cls.admin_password)
        server.save_students(users)

        server.REVOKED_TOKENS.clear()
        cls.client = TestClient(server.app)
        cls.client.__enter__()
        cls.tokens = {
            "teacher": cls.login(cls.teacher, cls.teacher_password),
            "otherTeacher": cls.login(cls.other_teacher, "social-other-teacher-password"),
            "admin": cls.login(cls.admin, cls.admin_password),
        }
        for student, password in zip(cls.students, cls.student_passwords):
            cls.tokens[student["id"]] = cls.login(student, password)

    @classmethod
    def login(cls, user, password):
        response = cls.client.post("/api/login", json={"email": user["email"], "password": password})
        if response.status_code != 200:
            raise AssertionError(f"Login failed: {response.text}")
        return response.json()["access_token"]

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.temporary_directory.cleanup()
        for name, path in cls.original_paths.items():
            setattr(server, name, path)
        server.REVOKED_TOKENS.clear()

    def headers(self, account):
        return {"Authorization": f"Bearer {self.tokens[account]}"}

    def test_community_ownership_replies_reporting_and_moderation(self):
        student_headers = self.headers(self.students[0]["id"])
        other_headers = self.headers(self.students[1]["id"])
        create = self.client.post("/api/community/posts", headers=student_headers, json={
            "title": "How do I practice speaking?",
            "content": "I would like to build a daily speaking habit.",
            "scope": "general",
            "authorId": self.students[1]["id"],
            "role": "administrator",
        })
        self.assertEqual(create.status_code, 200, create.text)
        post = create.json()["post"]
        self.assertEqual(post["author"]["id"], self.students[0]["id"])
        self.assertFalse({"email", "phone", "dateOfBirth", "passwordHash"}.intersection(post["author"]))
        post_id = post["id"]

        edit = self.client.patch("/api/community/posts/" + post_id, headers=student_headers, json={
            "title": "Updated speaking question", "content": "What short exercise works well?",
        })
        self.assertEqual(edit.status_code, 200, edit.text)
        self.assertEqual(self.client.patch("/api/community/posts/" + post_id, headers=other_headers, json={
            "title": "Hijack", "content": "Another person's post",
        }).status_code, 403)

        reply = self.client.post(f"/api/community/posts/{post_id}/replies", headers=other_headers, json={"content": "Try recording a one-minute voice note."})
        self.assertEqual(reply.status_code, 200, reply.text)
        reply_id = reply.json()["reply"]["id"]
        self.assertEqual(self.client.patch(f"/api/community/replies/{reply_id}", headers=student_headers, json={"content": "Unauthorized edit"}).status_code, 403)
        self.assertEqual(self.client.patch(f"/api/community/replies/{reply_id}", headers=other_headers, json={"content": "Edited my suggestion."}).status_code, 200)

        self.assertEqual(self.client.post(f"/api/community/posts/{post_id}/like", headers=other_headers).status_code, 200)
        self.assertTrue(self.client.get("/api/community/posts", headers=student_headers).json()["posts"][0]["likedByMe"] is False)

        course_post = self.client.post("/api/community/posts", headers=student_headers, json={
            "title": "Course practice question", "content": "I need help with introductions.",
            "scope": "course", "courseId": "cefr-a0-a1",
        })
        self.assertEqual(course_post.status_code, 200, course_post.text)
        course_post_id = course_post.json()["post"]["id"]
        teacher_reply = self.client.post(f"/api/community/posts/{course_post_id}/replies", headers=self.headers("teacher"), json={"content": "Try the first lesson dialogue."})
        self.assertEqual(teacher_reply.status_code, 200, teacher_reply.text)
        self.assertEqual(self.client.get(f"/api/community/posts/{course_post_id}", headers=self.headers("otherTeacher")).status_code, 404)

        report = self.client.post(f"/api/community/posts/{post_id}/reports", headers=other_headers, json={"reason": "Needs moderator review"})
        self.assertEqual(report.status_code, 200, report.text)
        self.assertEqual(self.client.get("/api/admin/community/reports", headers=self.headers("teacher")).status_code, 403)
        reports = self.client.get("/api/admin/community/reports", headers=self.headers("admin"))
        self.assertEqual(reports.status_code, 200)
        report_id = reports.json()["reports"][0]["id"]
        resolved = self.client.post(f"/api/admin/community/reports/{report_id}/resolve", headers=self.headers("admin"), json={"action": "hide"})
        self.assertEqual(resolved.status_code, 200, resolved.text)
        self.assertEqual(self.client.get(f"/api/community/posts/{post_id}", headers=student_headers).status_code, 404)
        self.assertIn(post_id, [item["id"] for item in self.client.get("/api/community/posts", headers=self.headers("admin")).json()["posts"]])
        self.assertEqual(self.client.get("/api/admin/community/reports", headers=other_headers).status_code, 403)

    def test_relationship_scoped_private_messaging_and_read_state(self):
        student_id = self.students[0]["id"]
        student_headers = self.headers(student_id)
        second_student_headers = self.headers(self.students[1]["id"])
        teacher_headers = self.headers("teacher")

        contacts = self.client.get("/api/messaging/contacts", headers=student_headers)
        self.assertEqual(contacts.status_code, 200)
        self.assertIn(self.teacher["id"], [item["user"]["id"] for item in contacts.json()["contacts"]])
        self.assertNotIn(self.other_teacher["id"], [item["user"]["id"] for item in contacts.json()["contacts"]])

        created = self.client.post("/api/conversations", headers=student_headers, json={
            "classId": "class-foundations-01",
            "senderId": self.students[1]["id"],
            "role": "administrator",
        })
        self.assertEqual(created.status_code, 200, created.text)
        conversation_id = created.json()["conversation"]["id"]
        bad_start = self.client.post("/api/conversations", headers=student_headers, json={"classId": "unknown-class"})
        self.assertEqual(bad_start.status_code, 403)

        sent = self.client.post(f"/api/conversations/{conversation_id}/messages", headers=student_headers, json={
            "content": "Could you suggest a speaking exercise?",
            "senderId": self.students[1]["id"],
            "role": "administrator",
        })
        self.assertEqual(sent.status_code, 200, sent.text)
        self.assertEqual(sent.json()["message"]["sender"]["id"], student_id)
        self.assertEqual(self.client.get(f"/api/conversations/{conversation_id}", headers=second_student_headers).status_code, 404)

        teacher_list = self.client.get("/api/conversations", headers=teacher_headers)
        self.assertEqual(teacher_list.status_code, 200)
        teacher_summary = next(item for item in teacher_list.json()["conversations"] if item["id"] == conversation_id)
        self.assertEqual(teacher_summary["unreadCount"], 1)
        teacher_thread = self.client.get(f"/api/conversations/{conversation_id}", headers=teacher_headers)
        self.assertEqual(teacher_thread.status_code, 200)
        self.assertEqual(self.client.get("/api/conversations", headers=teacher_headers).json()["conversations"][0]["unreadCount"], 0)
        teacher_message = self.client.post(f"/api/conversations/{conversation_id}/messages", headers=teacher_headers, json={"content": "Practice with a one-minute introduction."})
        self.assertEqual(teacher_message.status_code, 200)
        self.assertEqual(self.client.get(f"/api/conversations/{conversation_id}", headers=student_headers).json()["messages"][-1]["content"], "Practice with a one-minute introduction.")

        other_class = dict(server.load_classes()[0])
        other_class.update({"id": "other-teacher-private-class", "teacherId": self.other_teacher["id"], "assignedStudentIds": [self.students[1]["id"]]})
        classes = server.load_classes()
        classes.append(other_class)
        server.save_json_list(server.CLASSES_FILE, classes)
        other_thread = self.client.post("/api/conversations", headers=second_student_headers, json={"classId": other_class["id"]})
        self.assertEqual(other_thread.status_code, 200)
        other_conversation_id = other_thread.json()["conversation"]["id"]
        self.assertEqual(self.client.get(f"/api/conversations/{other_conversation_id}", headers=teacher_headers).status_code, 404)

        admin_headers = self.headers("admin")
        staff_thread = self.client.post("/api/conversations", headers=admin_headers, json={"staffUserId": self.teacher["id"]})
        self.assertEqual(staff_thread.status_code, 200, staff_thread.text)
        staff_conversation_id = staff_thread.json()["conversation"]["id"]
        self.assertEqual(self.client.get(f"/api/conversations/{staff_conversation_id}", headers=teacher_headers).status_code, 200)
        self.assertEqual(self.client.get(f"/api/conversations/{staff_conversation_id}", headers=self.headers("otherTeacher")).status_code, 404)


if __name__ == "__main__":
    unittest.main()
