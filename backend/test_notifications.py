import json
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import server


class NotificationWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path_names = ("DATA_DIR", "STUDENTS_FILE", "COURSES_FILE", "HOMEWORK_FILE", "SUBMISSIONS_FILE", "CLASSES_FILE", "COMMUNITY_POSTS_FILE", "COMMUNITY_REPLIES_FILE", "CONVERSATIONS_FILE", "MESSAGES_FILE", "REPORTS_FILE", "NOTIFICATIONS_FILE", "AI_SESSIONS_FILE", "AI_MESSAGES_FILE", "AI_USAGE_FILE")
        cls.original_paths = {name: getattr(server, name) for name in cls.path_names}
        cls.temp = tempfile.TemporaryDirectory()
        cls.data = Path(cls.temp.name)
        for filename in ("courses.json", "classes.json"):
            shutil.copyfile(Path(__file__).resolve().parent / "data" / filename, cls.data / filename)
        server.DATA_DIR = cls.data
        for name in cls.path_names[1:]:
            setattr(server, name, cls.data / Path(getattr(server, name)).name)
        cls.client = TestClient(server.app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.temp.cleanup()
        for name, path in cls.original_paths.items():
            setattr(server, name, path)
        server.REVOKED_TOKENS.clear()

    def setUp(self):
        shutil.copyfile(Path(__file__).resolve().parent / "data" / "classes.json", self.data / "classes.json")
        self.student = self.user("notify-student", "Student", "student")
        self.student2 = self.user("notify-student2", "Other Student", "student")
        self.teacher = self.user("notify-teacher", "Teacher", "teacher")
        self.admin = self.user("notify-admin", "Admin", "administrator")
        server.save_students([self.student, self.student2, self.teacher, self.admin])
        classes = server.load_classes()
        classes[0].update({"teacherId": self.teacher["id"], "assignedStudentIds": [self.student["id"]]})
        server.save_json_list(server.CLASSES_FILE, classes)
        for filename in ("homework.json", "submissions.json", "community_posts.json", "community_replies.json", "conversations.json", "messages.json", "reports.json", "notifications.json"):
            (self.data / filename).write_text("[]\n", encoding="utf-8")
        server.REVOKED_TOKENS.clear()
        self.headers = {name: self.login(user, f"{name}-password") for name, user in (("student", self.student), ("student2", self.student2), ("teacher", self.teacher), ("admin", self.admin))}

    @staticmethod
    def user(uid, name, role):
        return {"id": uid, "fullName": name, "email": f"{uid}@test.local", "passwordHash": server.hash_password(f"{uid.removeprefix('notify-')}-password"), "role": role, "level": "A2 - B1", "courseProgress": {}}

    def login(self, user, password):
        response = self.client.post("/api/login", json={"email": user["email"], "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def items(self, user="student"):
        response = self.client.get("/api/me/notifications", headers=self.headers[user])
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["notifications"]

    def test_homework_assignment_submission_and_grading_notifications(self):
        created = self.client.post("/api/teacher/homework", headers=self.headers["teacher"], json={"title": "Writing", "description": "Practice", "studentIds": [self.student["id"]]})
        self.assertEqual(created.status_code, 200, created.text)
        hw = created.json()["homework"]
        self.assertEqual([item["type"] for item in self.items()], ["homework_assigned"])
        submitted = self.client.post(f"/api/student/homework/{hw['id']}/submissions", headers=self.headers["student"], json={"answer": "Hello"})
        self.assertEqual(submitted.status_code, 200, submitted.text)
        submission = submitted.json()["submission"]
        self.assertEqual(len([item for item in self.items("teacher") if item["type"] == "homework_submitted"]), 1)
        self.client.post(f"/api/student/homework/{hw['id']}/submissions", headers=self.headers["student"], json={"answer": "Updated"})
        self.assertEqual(len([item for item in self.items("teacher") if item["type"] == "homework_submitted"]), 1)
        grade = self.client.patch(f"/api/teacher/homework/{hw['id']}/submissions/{submission['id']}/grade", headers=self.headers["teacher"], json={"grade": 90, "teacherFeedback": "Good"})
        self.assertEqual(grade.status_code, 200, grade.text)
        self.assertEqual(len([item for item in self.items() if item["type"] == "homework_graded"]), 1)

    def test_message_and_community_reply_notifications(self):
        started = self.client.post("/api/conversations", headers=self.headers["student"], json={"classId": "class-foundations-01"})
        self.assertEqual(started.status_code, 200, started.text)
        conversation_id = started.json()["conversation"]["id"]
        sent = self.client.post(f"/api/conversations/{conversation_id}/messages", headers=self.headers["student"], json={"content": "Question"})
        self.assertEqual(sent.status_code, 200, sent.text)
        self.assertEqual(self.items("teacher")[0]["type"], "new_message")
        post = self.client.post("/api/community/posts", headers=self.headers["student"], json={"title": "Question", "content": "Help?"})
        self.assertEqual(post.status_code, 200, post.text)
        post_id = post.json()["post"]["id"]
        reply = self.client.post(f"/api/community/posts/{post_id}/replies", headers=self.headers["student2"], json={"content": "Sure"})
        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertTrue(any(item["type"] == "community_reply" for item in self.items()))
        class_id = server.load_classes()[0]["id"]
        scoped_post = self.client.post("/api/community/posts", headers=self.headers["student"], json={"title": "Class discussion", "content": "Practice?", "scope": "class", "classId": class_id})
        self.assertEqual(scoped_post.status_code, 200, scoped_post.text)
        self.assertTrue(any(item["type"] == "community_activity" for item in self.items("teacher")))

    def test_class_cancellation_report_and_registration_events(self):
        class_id = server.load_classes()[0]["id"]
        cancelled = self.client.post(f"/api/teacher/classes/{class_id}/cancel", headers=self.headers["teacher"])
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertTrue(any(item["type"] == "class_cancelled" for item in self.items()))
        post = self.client.post("/api/community/posts", headers=self.headers["student"], json={"title": "Reportable", "content": "Review this"})
        post_id = post.json()["post"]["id"]
        reported = self.client.post(f"/api/community/posts/{post_id}/reports", headers=self.headers["student2"], json={"reason": "Review requested"})
        self.assertEqual(reported.status_code, 200, reported.text)
        self.assertTrue(any(item["type"] == "community_report" for item in self.items("admin")))
        registered = self.client.post("/api/register", json={"fullName": "New Learner", "email": "new-learner@test.local", "password": "new-learner-password", "dateOfBirth": "2000-01-01"})
        self.assertEqual(registered.status_code, 200, registered.text)
        self.assertTrue(any(item["type"] == "new_user_registration" for item in self.items("admin")))

    def test_achievement_creates_once_and_notification_api_is_private(self):
        path = "/api/me/courses/cefr-a0-a1/lessons/a0-lesson-1/complete"
        self.assertEqual(self.client.post(path, headers=self.headers["student"]).status_code, 200)
        self.assertEqual(self.client.post(path, headers=self.headers["student"]).status_code, 200)
        entries = self.items()
        achievement = next(item for item in entries if item["type"] == "achievement_unlocked")
        self.assertEqual(sum(item["type"] == "achievement_unlocked" for item in entries), 2)  # First Lesson + Course Starter
        self.assertTrue(any(item["type"] == "student_achievement" for item in self.items("teacher")))
        self.assertFalse(any("email" in item or "recipient_user_id" in item or "event_key" in item for item in entries))
        self.assertEqual(self.client.patch(f"/api/me/notifications/{achievement['id']}/read", headers=self.headers["student2"]).status_code, 404)
        self.assertEqual(self.client.get("/api/me/notifications", headers=self.headers["student2"]).json()["notifications"], [])
        self.assertEqual(self.client.get("/api/me/notifications/unread-count", headers=self.headers["student"]).json()["unreadCount"], len(entries))
        self.assertEqual(self.client.patch(f"/api/me/notifications/{achievement['id']}/read", headers=self.headers["student"]).status_code, 200)
        self.assertEqual(self.client.post("/api/me/notifications/read-all", headers=self.headers["student"]).status_code, 200)
        self.assertEqual(self.client.get("/api/me/notifications/unread-count", headers=self.headers["student"]).json()["unreadCount"], 0)
        self.assertEqual(self.client.get("/api/me/notifications").status_code, 401)


if __name__ == "__main__":
    unittest.main()
