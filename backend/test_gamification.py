import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

import server


class GamificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path_names = ("DATA_DIR", "STUDENTS_FILE", "COURSES_FILE", "HOMEWORK_FILE", "SUBMISSIONS_FILE", "CLASSES_FILE", "COMMUNITY_POSTS_FILE", "COMMUNITY_REPLIES_FILE", "CONVERSATIONS_FILE", "MESSAGES_FILE", "REPORTS_FILE", "NOTIFICATIONS_FILE", "AI_SESSIONS_FILE", "AI_MESSAGES_FILE", "AI_USAGE_FILE")
        cls.original_paths = {name: getattr(server, name) for name in cls.path_names}
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.data_directory = Path(cls.temporary_directory.name)
        for filename in ("courses.json", "classes.json"):
            shutil.copyfile(Path(__file__).resolve().parent / "data" / filename, cls.data_directory / filename)
        server.DATA_DIR = cls.data_directory
        for name in cls.path_names[1:]:
            setattr(server, name, cls.data_directory / Path(getattr(server, name)).name)
        cls.client = TestClient(server.app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.temporary_directory.cleanup()
        for name, path in cls.original_paths.items():
            setattr(server, name, path)
        server.REVOKED_TOKENS.clear()

    def setUp(self):
        self.student = {
            "id": "gamification-student",
            "fullName": "Learning Student",
            "email": "learning.student@test.local",
            "passwordHash": server.hash_password("student-gamification-password"),
            "role": "student",
            "level": "A2 - B1",
            "courseProgress": {},
        }
        self.other_student = {
            "id": "gamification-other-student",
            "fullName": "Second Learner",
            "email": "second.learner@test.local",
            "passwordHash": server.hash_password("second-gamification-password"),
            "role": "student",
            "level": "A2 - B1",
            "courseProgress": {},
        }
        self.teacher = {
            "id": "gamification-teacher",
            "fullName": "Class Teacher",
            "email": "class.teacher@test.local",
            "passwordHash": server.hash_password("teacher-gamification-password"),
            "role": "teacher",
            "courseProgress": {},
        }
        server.save_students([self.student, self.other_student, self.teacher])
        server.save_json_list(server.CLASSES_FILE, [{
            "id": "gamification-teacher-class",
            "teacherId": self.teacher["id"],
            "courseId": "cefr-a0-a1",
            "assignedStudentIds": [self.student["id"]],
            "status": "scheduled",
        }])
        server.save_json_list(server.HOMEWORK_FILE, [])
        server.save_json_list(server.SUBMISSIONS_FILE, [])
        server.REVOKED_TOKENS.clear()
        self.student_headers = self.login(self.student, "student-gamification-password")
        self.other_headers = self.login(self.other_student, "second-gamification-password")
        self.teacher_headers = self.login(self.teacher, "teacher-gamification-password")

    def login(self, account, password):
        response = self.client.post("/api/login", json={"email": account["email"], "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def gamification(self, headers=None):
        response = self.client.get("/api/me/gamification", headers=headers or self.student_headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_lesson_xp_is_awarded_once_on_duplicate_completion(self):
        course_id = "cefr-a0-a1"
        lesson_id = "a0-lesson-1"
        path = f"/api/me/courses/{course_id}/lessons/{lesson_id}/complete"
        first = self.client.post(path, headers=self.student_headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(self.gamification()["xp"], server.XP_REWARDS["lesson_completed"])
        duplicate = self.client.post(path, headers=self.student_headers)
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertEqual(self.gamification()["xp"], server.XP_REWARDS["lesson_completed"])

    def test_homework_submission_and_first_grade_rewards_are_idempotent(self):
        created = self.client.post("/api/teacher/homework", headers=self.teacher_headers, json={
            "title": "Write a short introduction", "description": "A short practice task.",
            "studentIds": [self.student["id"]],
        })
        self.assertEqual(created.status_code, 200, created.text)
        homework_id = created.json()["homework"]["id"]
        submitted = self.client.post(
            f"/api/student/homework/{homework_id}/submissions", headers=self.student_headers,
            json={"answer": "Hello, I am learning English.", "xp": 9999, "level": 99, "badge": "admin"},
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(self.gamification()["xp"], server.XP_REWARDS["homework_submitted"])
        self.client.post(
            f"/api/student/homework/{homework_id}/submissions", headers=self.student_headers,
            json={"answer": "Updated answer"},
        )
        self.assertEqual(self.gamification()["xp"], server.XP_REWARDS["homework_submitted"])

        submission_id = submitted.json()["submission"]["id"]
        grade_path = f"/api/teacher/homework/{homework_id}/submissions/{submission_id}/grade"
        graded = self.client.patch(grade_path, headers=self.teacher_headers, json={"grade": 90})
        self.assertEqual(graded.status_code, 200, graded.text)
        expected = server.XP_REWARDS["homework_submitted"] + server.XP_REWARDS["homework_graded"]
        self.assertEqual(self.gamification()["xp"], expected)
        repeated_grade = self.client.patch(grade_path, headers=self.teacher_headers, json={"grade": 95})
        self.assertEqual(repeated_grade.status_code, 200, repeated_grade.text)
        self.assertEqual(self.gamification()["xp"], expected)

    def test_placement_test_awards_once_and_uses_authenticated_student(self):
        payload = {"answers": [1, 1, 2, 3, 0], "studentId": self.other_student["id"]}
        denied = self.client.post("/api/test-results", headers=self.student_headers, json=payload)
        self.assertEqual(denied.status_code, 403)
        payload["studentId"] = self.student["id"]
        for _ in range(2):
            response = self.client.post("/api/test-results", headers=self.student_headers, json=payload)
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.gamification()["xp"], server.XP_REWARDS["placement_test_completed"])
        self.assertEqual(self.gamification()["level"], 1)

    def test_streak_same_day_consecutive_days_and_gap_preserve_longest(self):
        state = {"currentStreak": 0, "longestStreak": 0, "lastActivityDate": None}
        server.record_learning_day(state, date(2026, 1, 1))
        server.record_learning_day(state, date(2026, 1, 1))
        self.assertEqual(state["currentStreak"], 1)
        server.record_learning_day(state, date(2026, 1, 2))
        server.record_learning_day(state, date(2026, 1, 3))
        self.assertEqual(state["currentStreak"], 3)
        self.assertEqual(state["longestStreak"], 3)
        server.record_learning_day(state, date(2026, 1, 5))
        self.assertEqual(state["currentStreak"], 1)
        self.assertEqual(state["longestStreak"], 3)
        self.assertEqual(state["lastActivityDate"], "2026-01-05")

    def test_level_thresholds_and_seven_day_badge(self):
        for xp, level in ((0, 1), (99, 1), (100, 2), (250, 3), (500, 4), (1000, 5)):
            with self.subTest(xp=xp):
                self.assertEqual(server.xp_level_progress(xp)["level"], level)
        for day in range(1, 8):
            server.award_learning_action(
                self.student,
                f"lesson_completed:streak-test-{day}",
                "lesson_completed",
                activity_date=date(2026, 2, day),
            )
        server.save_students([self.student, self.other_student, self.teacher])
        achievements = self.client.get("/api/me/achievements", headers=self.student_headers)
        self.assertEqual(achievements.status_code, 200, achievements.text)
        streak_badge = next(badge for badge in achievements.json()["badges"] if badge["id"] == "streak_7")
        self.assertTrue(streak_badge["earned"])
        self.assertEqual(achievements.json()["currentStreak"], 7)

    def test_badges_unlock_and_locked_badges_are_listed(self):
        course = next(item for item in server.load_courses() if item["id"] == "cefr-a0-a1")
        lesson_ids = [lesson["id"] for lesson in course["lessons"]]
        for index in range(5):
            server.award_learning_action(self.student, f"lesson_completed:cefr-a0-a1:test-{index}", "lesson_completed")
        stored_students = [self.student, self.other_student, self.teacher]
        student_progress = self.student.setdefault("courseProgress", {})
        student_progress["cefr-a0-a1"] = {"completedLessons": lesson_ids, "updatedAt": None}
        server.refresh_student_badges(self.student)
        server.save_students(stored_students)
        response = self.client.get("/api/me/achievements", headers=self.student_headers)
        self.assertEqual(response.status_code, 200, response.text)
        badges = {badge["id"]: badge for badge in response.json()["badges"]}
        self.assertTrue(badges["first_lesson"]["earned"])
        self.assertTrue(badges["course_starter"]["earned"])
        self.assertTrue(badges["course_finisher"]["earned"])
        self.assertTrue(badges["xp_100"]["earned"])
        self.assertFalse(badges["first_class"]["earned"])
        self.assertTrue(badges["xp_500"]["earned"] is False)

    def test_leaderboard_is_ranked_and_does_not_expose_private_fields(self):
        server.award_learning_action(self.other_student, "placement_test_completed", "placement_test_completed")
        server.save_students([self.student, self.other_student, self.teacher])
        response = self.client.get("/api/leaderboard", headers=self.student_headers)
        self.assertEqual(response.status_code, 200, response.text)
        rows = response.json()["leaderboard"]
        self.assertEqual(rows[0]["displayName"], self.other_student["fullName"])
        self.assertEqual(rows[0]["rank"], 1)
        self.assertEqual(set(rows[0]), {"rank", "displayName", "xp", "level"})
        self.assertNotIn("email", json.dumps(rows))
        self.assertNotIn(self.teacher["fullName"], [row["displayName"] for row in rows])

    def test_gamification_endpoints_require_student_jwt(self):
        for path in ("/api/me/gamification", "/api/me/achievements", "/api/leaderboard"):
            self.assertEqual(self.client.get(path).status_code, 401)
            self.assertEqual(self.client.get(path, headers=self.teacher_headers).status_code, 403)
        forged_student_path = self.client.post(
            f"/api/students/{self.other_student['id']}/courses/cefr-a0-a1/lessons/a0-lesson-1/complete",
            headers=self.student_headers,
        )
        self.assertEqual(forged_student_path.status_code, 403)


if __name__ == "__main__":
    unittest.main()
