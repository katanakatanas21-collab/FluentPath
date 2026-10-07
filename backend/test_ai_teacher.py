import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import ai_teacher
import server


VALID_TURN = {
    "reply": "Choose the correct past-tense sentence: I went or I go yesterday?",
    "feedback": "",
    "score": None,
    "corrections": [],
    "next_step": "Pick one answer.",
    "is_complete": False,
    "grammar_feedback": "",
    "vocabulary_feedback": "",
    "clarity_feedback": "",
    "relevance_feedback": "",
}
VALID_FEEDBACK = {
    "reply": "Good work. The past tense is went.",
    "feedback": "You used the correct past tense.",
    "score": 90,
    "corrections": [],
    "next_step": "Try another past-tense sentence.",
    "is_complete": True,
    "grammar_feedback": "The past tense is correct.",
    "vocabulary_feedback": "Good use of familiar words.",
    "clarity_feedback": "Your response is easy to understand.",
    "relevance_feedback": "Your answer stays on topic.",
}


class AITeacherWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path_names = (
            "DATA_DIR", "STUDENTS_FILE", "COURSES_FILE", "HOMEWORK_FILE", "SUBMISSIONS_FILE",
            "CLASSES_FILE", "COMMUNITY_POSTS_FILE", "COMMUNITY_REPLIES_FILE", "CONVERSATIONS_FILE",
            "MESSAGES_FILE", "REPORTS_FILE", "NOTIFICATIONS_FILE", "AI_SESSIONS_FILE",
            "AI_MESSAGES_FILE", "AI_USAGE_FILE",
        )
        cls.original_paths = {name: getattr(server, name) for name in cls.path_names}
        cls.temp = tempfile.TemporaryDirectory()
        cls.data_dir = Path(cls.temp.name)
        cls.source_dir = Path(__file__).resolve().parent / "data"
        server.DATA_DIR = cls.data_dir
        for name in cls.path_names[1:]:
            setattr(server, name, cls.data_dir / Path(getattr(server, name)).name)
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
        self.student = self.make_user("ai-student", "student", "A1 - A2")
        self.other_student = self.make_user("ai-other", "student", "B2 - C1")
        self.teacher = self.make_user("ai-teacher", "teacher", "C1+")
        server.save_students([self.student, self.other_student, self.teacher])
        for filename in ("notifications.json", "ai_sessions.json", "ai_messages.json", "ai_usage.json"):
            server.save_json_list(self.data_dir / filename, [])
        server.REVOKED_TOKENS.clear()
        self.headers = {
            role: {"Authorization": f"Bearer {server.create_access_token(account)}"}
            for role, account in (("student", self.student), ("other", self.other_student), ("teacher", self.teacher))
        }

    @staticmethod
    def make_user(user_id, role, level):
        return {
            "id": user_id,
            "fullName": user_id,
            "email": f"{user_id}@test.local",
            "passwordHash": server.hash_password(f"{user_id}-test-password"),
            "role": role,
            "level": level,
            "courseProgress": {},
        }

    def create_session(self, headers=None, mode="grammar", result=VALID_TURN):
        with patch("server.ai_teacher.generate_ai_response", new_callable=AsyncMock, return_value=result):
            response = self.client.post("/api/me/ai/sessions", headers=headers or self.headers["student"], json={"mode": mode})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["session"]

    def test_authenticated_student_creates_session_with_server_cefr_and_mocked_backend_provider(self):
        with patch("server.ai_teacher.generate_ai_response", new_callable=AsyncMock, return_value=VALID_TURN) as provider:
            response = self.client.post(
                "/api/me/ai/sessions",
                headers=self.headers["student"],
                json={"mode": "grammar", "student_id": self.other_student["id"], "cefr_level": "C1+", "xp": 90000},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["session"]["cefr_level"], self.student["level"])
        self.assertNotIn("student_id", response.json()["session"])
        self.assertNotIn("email", response.json()["session"])
        provider.assert_awaited_once_with("grammar", self.student["level"], [])

    def test_unauthenticated_non_student_and_unconfigured_requests_are_safe(self):
        unauthorized = self.client.post("/api/me/ai/sessions", json={"mode": "writing"})
        self.assertEqual(unauthorized.status_code, 401)
        denied = self.client.post("/api/me/ai/sessions", headers=self.headers["teacher"], json={"mode": "writing"})
        self.assertEqual(denied.status_code, 403)
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}), patch("server.ai_teacher.generate_ai_response", wraps=ai_teacher.generate_ai_response):
            missing_key = self.client.post("/api/me/ai/sessions", headers=self.headers["student"], json={"mode": "writing"})
        self.assertEqual(missing_key.status_code, 503)
        self.assertEqual(missing_key.json()["detail"], "AI_TEACHER_NOT_CONFIGURED")
        self.assertEqual(server.load_json_list(server.AI_SESSIONS_FILE), [])

    def test_session_history_persists_and_is_only_visible_to_owner(self):
        session = self.create_session()
        with patch("server.ai_teacher.generate_ai_response", new_callable=AsyncMock, return_value=VALID_FEEDBACK):
            answer = self.client.post(
                f"/api/me/ai/sessions/{session['id']}/messages",
                headers=self.headers["student"],
                json={"content": "I go to school yesterday.", "xp": 100000},
            )
        self.assertEqual(answer.status_code, 200, answer.text)
        detail = self.client.get(f"/api/me/ai/sessions/{session['id']}", headers=self.headers["student"])
        self.assertEqual(detail.status_code, 200)
        self.assertEqual([item["role"] for item in detail.json()["messages"]], ["assistant", "user", "assistant"])
        self.assertEqual(detail.json()["messages"][1]["content"], "I go to school yesterday.")
        self.assertEqual(self.client.get(f"/api/me/ai/sessions/{session['id']}", headers=self.headers["other"]).status_code, 404)
        self.assertEqual(self.client.get("/api/me/ai/sessions", headers=self.headers["other"]).json()["sessions"], [])
        self.assertNotIn("student_id", detail.json()["session"])

    def test_xp_is_server_awarded_once_per_mode_per_utc_day_and_not_from_client_fields(self):
        first = self.create_session(mode="grammar")
        message_url = f"/api/me/ai/sessions/{first['id']}/messages"
        with patch("server.ai_teacher.generate_ai_response", new_callable=AsyncMock, return_value=VALID_FEEDBACK):
            response = self.client.post(message_url, headers=self.headers["student"], json={"content": "I went yesterday.", "xp": 999999, "level": 99, "badge": "admin"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["xp_awarded"], server.XP_REWARDS["ai_practice_completed"])
        self.assertEqual(server.gamification_summary(server.find_student(self.student["id"]))["xp"], 10)

        second = self.create_session(mode="grammar")
        with patch("server.ai_teacher.generate_ai_response", new_callable=AsyncMock, return_value=VALID_FEEDBACK):
            duplicate = self.client.post(f"/api/me/ai/sessions/{second['id']}/messages", headers=self.headers["student"], json={"content": "I went yesterday."})
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertEqual(duplicate.json()["xp_awarded"], 0)
        with patch("server.ai_teacher.generate_ai_response", new_callable=AsyncMock, return_value=VALID_FEEDBACK):
            third_duplicate = self.client.post(message_url, headers=self.headers["student"], json={"content": "I went another day."})
        self.assertEqual(third_duplicate.status_code, 200)
        self.assertEqual(third_duplicate.json()["xp_awarded"], 0)
        self.assertEqual(server.gamification_summary(server.find_student(self.student["id"]))["xp"], 10)

    def test_conversation_streak_xp_requires_three_student_turns(self):
        session = self.create_session(mode="conversation")
        for turn in range(1, 4):
            with patch("server.ai_teacher.generate_ai_response", new_callable=AsyncMock, return_value=VALID_FEEDBACK):
                response = self.client.post(
                    f"/api/me/ai/sessions/{session['id']}/messages",
                    headers=self.headers["student"],
                    json={"content": f"My answer number {turn} is about my learning."},
                )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["xp_awarded"], 10 if turn == 3 else 0)
        self.assertEqual(server.gamification_summary(server.find_student(self.student["id"]))["currentStreak"], 1)

    def test_invalid_model_response_is_not_returned_to_client(self):
        with patch("server.ai_teacher.generate_ai_response", new_callable=AsyncMock, return_value={"reply": "This response is incomplete."}):
            response = self.client.post("/api/me/ai/sessions", headers=self.headers["student"], json={"mode": "vocabulary"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "AI_TEACHER_UNAVAILABLE")
        self.assertEqual(server.load_json_list(server.AI_SESSIONS_FILE), [])

    def test_provider_output_validator_and_message_length(self):
        with self.assertRaises(ai_teacher.AIProviderError):
            ai_teacher.validate_ai_response("not JSON")
        with self.assertRaises(ai_teacher.AIProviderError):
            ai_teacher.validate_ai_response({**VALID_TURN, "score": 101})
        session = self.create_session()
        too_long = self.client.post(
            f"/api/me/ai/sessions/{session['id']}/messages",
            headers=self.headers["student"],
            json={"content": "x" * 1501},
        )
        self.assertEqual(too_long.status_code, 422)

    def test_provider_failures_do_not_leak_internal_details(self):
        with patch("server.ai_teacher.generate_ai_response", new_callable=AsyncMock, side_effect=ai_teacher.AIProviderError("private provider detail")):
            response = self.client.post("/api/me/ai/sessions", headers=self.headers["student"], json={"mode": "speaking"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "AI_TEACHER_UNAVAILABLE")
        self.assertNotIn("private provider detail", response.text)

    def test_opt_in_provider_diagnostics_log_only_sanitized_metadata(self):
        error = SimpleNamespace(
            status_code=401,
            code="invalid_api_key",
            request_id="req-safe-id",
            message="Rejected key sk-test-secret and Bearer hidden-token",
        )
        with patch.dict(os.environ, {"AI_TEACHER_DIAGNOSTICS": "1", "OPENAI_API_KEY": "sk-test-secret"}):
            with self.assertLogs(ai_teacher.logger, level="WARNING") as captured:
                ai_teacher._log_provider_diagnostic(error)
        diagnostic = " ".join(captured.output)
        self.assertIn("exception=SimpleNamespace", diagnostic)
        self.assertIn("status=401", diagnostic)
        self.assertIn("code=invalid_api_key", diagnostic)
        self.assertIn("request_id=req-safe-id", diagnostic)
        self.assertIn("[REDACTED]", diagnostic)
        self.assertNotIn("sk-test-secret", diagnostic)
        self.assertNotIn("hidden-token", diagnostic)

    def test_provider_diagnostics_are_disabled_by_default(self):
        error = SimpleNamespace(message="safe message")
        with patch.dict(os.environ, {}, clear=True):
            with self.assertNoLogs(ai_teacher.logger, level="WARNING"):
                ai_teacher._log_provider_diagnostic(error)

    def test_provider_request_limit_is_enforced_per_authenticated_student(self):
        timestamp = datetime.now(timezone.utc).isoformat()
        server.save_json_list(server.AI_USAGE_FILE, [{"student_id": self.student["id"], "created_at": timestamp} for _ in range(20)])
        with patch("server.ai_teacher.generate_ai_response", new_callable=AsyncMock, return_value=VALID_TURN) as provider:
            response = self.client.post("/api/me/ai/sessions", headers=self.headers["student"], json={"mode": "vocabulary"})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["detail"], "AI_TEACHER_RATE_LIMITED")
        provider.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
