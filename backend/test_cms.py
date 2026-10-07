import shutil
import tempfile
import unittest
import json
from pathlib import Path

from fastapi.testclient import TestClient

import server


class CMSWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path_names = ("DATA_DIR", "STUDENTS_FILE", "COURSES_FILE", "HOMEWORK_FILE", "SUBMISSIONS_FILE", "CLASSES_FILE", "COMMUNITY_POSTS_FILE", "COMMUNITY_REPLIES_FILE", "CONVERSATIONS_FILE", "MESSAGES_FILE", "REPORTS_FILE", "NOTIFICATIONS_FILE", "AI_SESSIONS_FILE", "AI_MESSAGES_FILE", "AI_USAGE_FILE")
        cls.original_paths = {name: getattr(server, name) for name in cls.path_names}
        cls.temp = tempfile.TemporaryDirectory()
        cls.data_dir = Path(cls.temp.name)
        cls.source_dir = Path(__file__).resolve().parent / "data"
        for name in cls.path_names[1:]:
            setattr(server, name, cls.data_dir / Path(getattr(server, name)).name)
        server.DATA_DIR = cls.data_dir
        for filename in ("courses.json", "classes.json"):
            shutil.copyfile(cls.source_dir / filename, cls.data_dir / filename)
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
        shutil.copyfile(self.source_dir / "courses.json", self.data_dir / "courses.json")
        courses_path = self.data_dir / "courses.json"
        courses = json.loads(courses_path.read_text(encoding="utf-8"))
        first_content = courses[0]["lessons"][0].get("content", "")
        if isinstance(first_content, dict):
            courses[0]["lessons"][0]["content"] = first_content.get("explanation", "")
            courses_path.write_text(json.dumps(courses, ensure_ascii=False, indent=2), encoding="utf-8")
        self.student = self.make_user("cms-student", "student", "A2 - B1")
        self.teacher = self.make_user("cms-teacher", "teacher")
        self.admin = self.make_user("cms-admin", "administrator")
        server.save_students([self.student, self.teacher, self.admin])
        for name in ("homework.json", "submissions.json", "community_posts.json", "community_replies.json", "conversations.json", "messages.json", "reports.json", "notifications.json"):
            (self.data_dir / name).write_text("[]\n", encoding="utf-8")
        server.REVOKED_TOKENS.clear()
        self.headers = {role: {"Authorization": f"Bearer {server.create_access_token(user)}"} for role, user in (("student", self.student), ("teacher", self.teacher), ("admin", self.admin))}

    def test_anonymous_course_preview_does_not_return_lessons_or_student_progress(self):
        response = self.client.get("/api/courses/cefr-a0-a1")
        self.assertEqual(response.status_code, 200, response.text)
        preview = response.json()
        self.assertEqual(preview["id"], "cefr-a0-a1")
        self.assertNotIn("lessons", preview)
        self.assertNotIn("progress", preview)

    @staticmethod
    def make_user(user_id, role, level=None):
        password = f"{user_id}-password"
        return {"id": user_id, "fullName": user_id, "email": f"{user_id}@test.local", "passwordHash": server.hash_password(password), "role": role, "level": level, "courseProgress": {}}

    def test_admin_course_list_create_edit_and_activate_deactivate(self):
        original_courses = server.load_courses()
        self.student["courseProgress"] = {"cefr-a0-a1": {"completedLessons": ["a0-lesson-1"], "updatedAt": "2026-01-01T00:00:00+00:00"}}
        server.save_students([self.student, self.teacher, self.admin])
        listed = self.client.get("/api/admin/courses", headers=self.headers["admin"])
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["courses"]), 16)
        migrated_courses = server.load_courses()
        self.assertEqual([item["id"] for item in migrated_courses[:len(original_courses)]], [item["id"] for item in original_courses])
        migrated_lesson = migrated_courses[0]["lessons"][0]
        self.assertEqual(migrated_lesson["content"]["explanation"], original_courses[0]["lessons"][0]["content"])
        self.assertEqual(migrated_lesson["course_id"], "cefr-a0-a1")
        self.assertEqual(server.find_student(self.student["id"])["courseProgress"], self.student["courseProgress"])
        payload = {"title": "Omani English", "titleAr": "الإنجليزية العمانية", "description": "A focused CEFR path", "descriptionAr": "مسار تعليمي", "level": "A0 → A1", "order": 22}
        created = self.client.post("/api/admin/courses", headers=self.headers["admin"], json=payload)
        self.assertEqual(created.status_code, 200, created.text)
        course = created.json()["course"]
        self.assertFalse(course["active"])
        self.assertEqual(course["requiredRank"], server.CEFR_RANKS["A1"])
        payload["title"] = "Revised course"
        edited = self.client.put(f"/api/admin/courses/{course['id']}", headers=self.headers["admin"], json=payload)
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()["course"]["title"], "Revised course")
        self.assertEqual(self.client.patch(f"/api/admin/courses/{course['id']}/status", headers=self.headers["admin"], json={"active": True}).json()["active"], True)
        student_courses = self.client.get("/api/courses", headers=self.headers["student"]).json()["courses"]
        self.assertIn(course["id"], [item["id"] for item in student_courses])
        self.assertEqual(self.client.patch(f"/api/admin/courses/{course['id']}/status", headers=self.headers["admin"], json={"active": False}).status_code, 200)
        self.assertNotIn(course["id"], [item["id"] for item in self.client.get("/api/courses", headers=self.headers["student"]).json()["courses"]])
        self.assertEqual(len(server.load_courses()), 17)

    def test_admin_lesson_create_edit_reorder_publish_and_archive(self):
        course_id = "cefr-a0-a1"
        content = {"introduction": "Welcome", "explanation": "Explain a greeting", "examples": "Hello", "vocabulary": "hello", "grammar_notes": "Names", "practice_instructions": "Say hello"}
        created = self.client.post(f"/api/admin/courses/{course_id}/lessons", headers=self.headers["admin"], json={"title": "Greetings", "titleAr": "التحية", "description": "Start here", "content": content, "estimated_minutes": 12})
        self.assertEqual(created.status_code, 200, created.text)
        lesson = created.json()["lesson"]
        self.assertFalse(lesson["published"])
        self.assertEqual(lesson["course_id"], course_id)
        self.assertEqual(lesson["content"]["introduction"], "Welcome")
        edited_payload = {"title": "Introductions", "titleAr": "التعارف", "description": "Introduce yourself", "content": content, "estimated_minutes": 18}
        self.assertEqual(self.client.put(f"/api/admin/courses/{course_id}/lessons/{lesson['id']}", headers=self.headers["admin"], json=edited_payload).status_code, 200)
        ids = [lesson["id"], "a0-lesson-1", "a0-lesson-2", "a0-lesson-3"]
        reordered = self.client.post(f"/api/admin/courses/{course_id}/lessons/reorder", headers=self.headers["admin"], json={"lesson_ids": ids})
        self.assertEqual(reordered.status_code, 200, reordered.text)
        self.assertEqual(reordered.json()["lessons"][0]["id"], lesson["id"])
        self.assertEqual(self.client.patch(f"/api/admin/courses/{course_id}/lessons/{lesson['id']}/status", headers=self.headers["admin"], json={"published": True}).status_code, 200)
        course = self.client.get(f"/api/courses/{course_id}", headers=self.headers["student"]).json()
        self.assertEqual(course["lessons"][0]["id"], lesson["id"])
        self.assertEqual(course["lessons"][0]["content"]["explanation"], "Explain a greeting")
        archived = self.client.patch(f"/api/admin/courses/{course_id}/lessons/{lesson['id']}/status", headers=self.headers["admin"], json={"archived": True})
        self.assertEqual(archived.status_code, 200)
        self.assertFalse(archived.json()["lesson"]["published"])
        self.assertNotIn(lesson["id"], [item["id"] for item in self.client.get(f"/api/courses/{course_id}", headers=self.headers["student"]).json()["lessons"]])
        self.assertIn(lesson["id"], [item["id"] for item in self.client.get(f"/api/admin/courses/{course_id}/lessons", headers=self.headers["admin"]).json()["lessons"]])

    def test_student_and_teacher_cannot_modify_courses_or_lessons(self):
        course_id = "cefr-a0-a1"
        payload = {"title": "Hijack", "level": "A0 → A1"}
        for role in ("student", "teacher"):
            self.assertEqual(self.client.post("/api/admin/courses", headers=self.headers[role], json=payload).status_code, 403)
            self.assertEqual(self.client.put(f"/api/admin/courses/{course_id}", headers=self.headers[role], json=payload).status_code, 403)
            self.assertEqual(self.client.patch(f"/api/admin/courses/{course_id}/status", headers=self.headers[role], json={"active": False}).status_code, 403)
            self.assertEqual(self.client.post(f"/api/admin/courses/{course_id}/lessons", headers=self.headers[role], json={"title": "No"}).status_code, 403)
            self.assertEqual(self.client.put(f"/api/admin/courses/{course_id}/lessons/a0-lesson-1", headers=self.headers[role], json={"title": "No"}).status_code, 403)
            self.assertEqual(self.client.patch(f"/api/admin/courses/{course_id}/lessons/a0-lesson-1/status", headers=self.headers[role], json={"published": False}).status_code, 403)
        self.assertEqual(self.client.get("/api/admin/courses").status_code, 401)

    def test_student_sees_published_authorized_lessons_only(self):
        course_id = "cefr-a0-a1"
        created = self.client.post(f"/api/admin/courses/{course_id}/lessons", headers=self.headers["admin"], json={"title": "Private draft"}).json()["lesson"]
        response = self.client.get(f"/api/courses/{course_id}", headers=self.headers["student"])
        self.assertEqual(response.status_code, 200, response.text)
        lesson_ids = [item["id"] for item in response.json()["lessons"]]
        self.assertNotIn(created["id"], lesson_ids)
        completion = self.client.post(f"/api/me/courses/{course_id}/lessons/{created['id']}/complete", headers=self.headers["student"])
        self.assertEqual(completion.status_code, 404)
        locked = self.client.get("/api/courses/cefr-b1-b2", headers=self.headers["student"])
        self.assertEqual(locked.status_code, 403)

    def test_existing_lesson_completion_progress_xp_and_notification_still_work(self):
        path = "/api/me/courses/cefr-a0-a1/lessons/a0-lesson-1/complete"
        completed = self.client.post(path, headers=self.headers["student"])
        self.assertEqual(completed.status_code, 200, completed.text)
        self.assertIn("a0-lesson-1", completed.json()["progress"]["completedLessons"])
        self.assertEqual(server.gamification_summary(server.find_student(self.student["id"]))["xp"], server.XP_REWARDS["lesson_completed"])
        notification = self.client.get("/api/me/notifications", headers=self.headers["student"])
        self.assertEqual(notification.status_code, 200)


if __name__ == "__main__":
    unittest.main()
