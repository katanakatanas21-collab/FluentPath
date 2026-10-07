import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

import server
from unittest.mock import patch


class ClassWorkflowTests(unittest.TestCase):
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
        source = Path(__file__).resolve().parent / "data"
        for filename in ("students.json", "courses.json", "homework.json", "classes.json"):
            shutil.copyfile(source / filename, cls.data_directory / filename)
        server.DATA_DIR = cls.data_directory
        for name in cls.path_names[1:]:
            setattr(server, name, cls.data_directory / Path(getattr(server, name)).name)

        users = server.load_students()
        cls.teacher = next(user for user in users if user.get("role") == "teacher" and user.get("devOnly"))
        cls.teacher_password = "class-workflow-teacher-password"
        cls.teacher["passwordHash"] = server.hash_password(cls.teacher_password)
        cls.other_teacher = {
            "id": "class-workflow-other-teacher",
            "fullName": "Other Teacher",
            "email": "other.class.teacher@test.local",
            "passwordHash": server.hash_password("class-workflow-other-password"),
            "role": "teacher",
            "courseProgress": {},
        }
        users.append(cls.other_teacher)
        cls.unassigned_student = {
            "id": "class-workflow-unassigned-student",
            "fullName": "Unassigned Student",
            "email": "unassigned.class.student@test.local",
            "passwordHash": server.hash_password("unassigned-class-student-password"),
            "role": "student",
            "courseProgress": {},
        }
        users.append(cls.unassigned_student)
        cls.students = [user for user in users if user.get("role", "student") == "student"]
        while len(cls.students) < 2:
            student = {
                "id": f"class-workflow-student-{len(cls.students)}",
                "fullName": f"Class Student {len(cls.students) + 1}",
                "email": f"class.student.{len(cls.students)}@test.local",
                "passwordHash": "",
                "role": "student",
                "courseProgress": {},
                "level": "A2 - B1",
            }
            users.append(student)
            cls.students.append(student)
        cls.students = cls.students[:2]
        cls.student_passwords = []
        for index, student in enumerate(cls.students):
            student["level"] = "A2 - B1"
            password = f"class-workflow-student-{index}-password"
            student["passwordHash"] = server.hash_password(password)
            cls.student_passwords.append(password)
        cls.admin = next(user for user in users if user.get("role") == "administrator" and user.get("devOnly"))
        cls.admin_password = "class-workflow-admin-password"
        cls.admin["passwordHash"] = server.hash_password(cls.admin_password)
        server.save_students(users)

        server.REVOKED_TOKENS.clear()
        cls.client = TestClient(server.app)
        cls.client.__enter__()
        cls.tokens = {
            "teacher": cls.login(cls.teacher, cls.teacher_password),
            "otherTeacher": cls.login(cls.other_teacher, "class-workflow-other-password"),
            "admin": cls.login(cls.admin, cls.admin_password),
        }
        for student, password in zip(cls.students, cls.student_passwords):
            cls.tokens[student["id"]] = cls.login(student, password)

    @classmethod
    def login(cls, account, password):
        response = cls.client.post("/api/login", json={"email": account["email"], "password": password})
        if response.status_code != 200:
            raise AssertionError(f"Login failed for {account['email']}: {response.text}")
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

    def class_body(self, *, day_offset=5, student_ids=None, title="Speaking practice"):
        class_date = date.today() + timedelta(days=day_offset)
        return {
            "title": title,
            "description": "Practice a short introduction.",
            "courseId": "cefr-a0-a1",
            "level": "A0",
            "studentIds": student_ids or [self.students[0]["id"]],
            "date": class_date.isoformat(),
            "startTime": "14:00",
            "endTime": "14:45",
            "meetingProvider": "zoom",
            "meetingUrl": "https://zoom.us/j/123456789",
            "teacherJoinUrl": "https://zoom.us/s/teacher-link",
            "studentJoinUrl": "https://zoom.us/j/123456789",
        }

    def test_teacher_create_student_assignment_admin_view_and_cancel(self):
        request_body = self.class_body()
        request_body["teacherId"] = self.other_teacher["id"]
        request_body["assignedStudentIds"] = [self.students[1]["id"]]
        create_response = self.client.post(
            "/api/teacher/classes",
            headers=self.headers("teacher"),
            json=request_body,
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        created = create_response.json()["class"]
        class_id = created["id"]
        self.assertEqual(created["teacherId"], self.teacher["id"])
        self.assertEqual(created["assignedStudentIds"], [self.students[0]["id"]])
        self.assertEqual(created["durationMinutes"], 45)
        dashboard_classes = self.client.get("/api/teacher/dashboard", headers=self.headers("teacher")).json()["upcomingClasses"]
        self.assertIn(class_id, [item["id"] for item in dashboard_classes])

        owner_list = self.client.get("/api/teacher/classes", headers=self.headers("teacher"))
        self.assertIn(class_id, [item["id"] for item in owner_list.json()["classes"]])
        outsider_list = self.client.get("/api/teacher/classes", headers=self.headers("otherTeacher"))
        self.assertNotIn(class_id, [item["id"] for item in outsider_list.json()["classes"]])

        student_key = self.students[0]["id"]
        student_classes = self.client.get("/api/student/classes", headers=self.headers(student_key))
        self.assertIn(class_id, [item["id"] for item in student_classes.json()["upcoming"]])
        listed_class = next(item for item in student_classes.json()["upcoming"] if item["id"] == class_id)
        self.assertNotIn("teacherJoinUrl", listed_class)
        self.assertNotIn("assignedStudentIds", listed_class)
        self.assertNotIn(class_id, [item["id"] for item in student_classes.json()["past"]])
        other_student = self.students[1]["id"]
        other_classes = self.client.get("/api/student/classes", headers=self.headers(other_student))
        self.assertNotIn(class_id, [item["id"] for item in other_classes.json()["upcoming"]])
        self.assertEqual(self.client.get(f"/api/student/classes/{class_id}", headers=self.headers(other_student)).status_code, 404)

        detail = self.client.get(f"/api/student/classes/{class_id}", headers=self.headers(student_key))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["class"]["teacher"]["id"], self.teacher["id"])
        self.assertEqual(detail.json()["class"]["studentJoinUrl"], "https://zoom.us/j/123456789")
        self.assertNotIn("teacherJoinUrl", detail.json()["class"])
        self.assertNotIn("dateOfBirth", detail.json()["class"]["teacher"])

        admin_response = self.client.get("/api/admin/classes", headers=self.headers("admin"))
        self.assertEqual(admin_response.status_code, 200)
        admin_payload = admin_response.json()
        admin_class = next(item for item in admin_payload["classes"] if item["id"] == class_id)
        self.assertEqual(admin_class["teacher"]["id"], self.teacher["id"])
        self.assertEqual(admin_class["students"][0]["id"], self.students[0]["id"])
        # The legacy seeded class moves from "upcoming" to "past" once its start time
        # passes, so the aggregate is derived from the returned records rather than a
        # fixed total. The created class must still be counted as upcoming.
        self.assertIn(class_id, [item["id"] for item in admin_payload["classes"] if item["timeState"] == "upcoming"])
        self.assertEqual(
            admin_payload["upcoming"],
            sum(1 for item in admin_payload["classes"] if item["timeState"] == "upcoming" and item["status"] != "cancelled"),
        )

        unrelated_assignment = self.client.post(
            "/api/teacher/classes",
            headers=self.headers("teacher"),
            json=self.class_body(student_ids=[self.unassigned_student["id"]], title="Unauthorized assignment"),
        )
        self.assertEqual(unrelated_assignment.status_code, 403)

        self.assertEqual(self.client.put(
            f"/api/teacher/classes/{class_id}",
            headers=self.headers("otherTeacher"),
            json=self.class_body(title="Unauthorized edit"),
        ).status_code, 403)
        self.assertEqual(self.client.post(
            f"/api/teacher/classes/{class_id}/cancel",
            headers=self.headers("otherTeacher"),
        ).status_code, 403)

        update_body = self.class_body(title="Updated speaking class")
        update_response = self.client.put(
            f"/api/teacher/classes/{class_id}",
            headers=self.headers("teacher"),
            json=update_body,
        )
        self.assertEqual(update_response.status_code, 200, update_response.text)
        self.assertEqual(update_response.json()["class"]["title"], "Updated speaking class")
        cancel_response = self.client.post(
            f"/api/teacher/classes/{class_id}/cancel",
            headers=self.headers("teacher"),
        )
        self.assertEqual(cancel_response.status_code, 200)
        self.assertEqual(cancel_response.json()["class"]["status"], "cancelled")
        self.assertIn(class_id, [item["id"] for item in self.client.get("/api/student/classes", headers=self.headers(student_key)).json()["cancelled"]])

    def test_past_state_and_legacy_class_compatibility(self):
        teacher_classes = self.client.get("/api/teacher/classes", headers=self.headers("teacher"))
        legacy = next(item for item in teacher_classes.json()["classes"] if item["id"] == "class-foundations-01")
        self.assertEqual(legacy["startTime"], "16:00")
        self.assertEqual(legacy["durationMinutes"], 45)
        past_class = self.class_body(day_offset=-2, title="Past review")
        create_response = self.client.post("/api/teacher/classes", headers=self.headers("teacher"), json=past_class)
        self.assertEqual(create_response.status_code, 200, create_response.text)
        dashboard_classes = self.client.get("/api/teacher/dashboard", headers=self.headers("teacher")).json()["upcomingClasses"]
        self.assertNotIn(create_response.json()["class"]["id"], [item["id"] for item in dashboard_classes])
        student_classes = self.client.get("/api/student/classes", headers=self.headers(self.students[0]["id"]))
        self.assertIn(create_response.json()["class"]["id"], [item["id"] for item in student_classes.json()["past"]])

    def test_role_denials_and_meeting_url_validation(self):
        class_request = self.class_body()
        class_request["meetingUrl"] = "javascript:alert(1)"
        self.assertEqual(self.client.post("/api/teacher/classes", headers=self.headers("teacher"), json=class_request).status_code, 400)
        self.assertEqual(self.client.get("/api/student/classes", headers=self.headers("admin")).status_code, 403)
        self.assertEqual(self.client.get("/api/admin/classes", headers=self.headers("teacher")).status_code, 403)
        self.assertEqual(self.client.get("/api/teacher/meeting-options", headers=self.headers(self.students[0]["id"])).status_code, 403)
        self.assertEqual(self.client.get("/api/teacher/meeting-options", headers=self.headers("teacher")).status_code, 200)

    @patch("server.zoom_service.create_meeting", return_value={
        "zoomMeetingId": "zoom-987", "teacherJoinUrl": "https://zoom.us/s/host-private",
        "studentJoinUrl": "https://zoom.us/j/student-safe", "meetingUrl": "https://zoom.us/j/student-safe",
    })
    def test_zoom_create_update_cancel_and_private_join_links(self, create_meeting):
        body = self.class_body()
        body.pop("meetingUrl")
        body.pop("teacherJoinUrl")
        body.pop("studentJoinUrl")
        created = self.client.post("/api/teacher/classes", headers=self.headers("teacher"), json=body)
        self.assertEqual(created.status_code, 200, created.text)
        item = created.json()["class"]
        self.assertEqual(item["zoomMeetingId"], "zoom-987")
        self.assertEqual(create_meeting.call_count, 1)
        student = self.client.get(f"/api/student/classes/{item['id']}", headers=self.headers(self.students[0]["id"]))
        self.assertEqual(student.status_code, 200)
        self.assertEqual(student.json()["class"]["studentJoinUrl"], "https://zoom.us/j/student-safe")
        self.assertNotIn("teacherJoinUrl", student.json()["class"])
        admin = self.client.get("/api/admin/classes", headers=self.headers("admin"))
        admin_class = next(entry for entry in admin.json()["classes"] if entry["id"] == item["id"])
        self.assertNotIn("teacherJoinUrl", admin_class)
        self.assertNotIn("studentJoinUrl", admin_class)
        self.assertNotIn("meetingUrl", admin_class)

        body["title"] = "Updated Zoom session"
        with patch("server.zoom_service.update_meeting") as update_meeting:
            updated = self.client.put(f"/api/teacher/classes/{item['id']}", headers=self.headers("teacher"), json=body)
        self.assertEqual(updated.status_code, 200, updated.text)
        update_meeting.assert_called_once()
        self.assertEqual(update_meeting.call_args.args[0], "zoom-987")
        with patch("server.zoom_service.get_meeting", return_value={
            "teacherJoinUrl": "https://zoom.us/s/fresh-private",
            "studentJoinUrl": "https://zoom.us/j/student-safe",
            "meetingUrl": "https://zoom.us/j/student-safe",
        }) as get_meeting:
            start_response = self.client.post(f"/api/teacher/classes/{item['id']}/zoom-start", headers=self.headers("teacher"))
        self.assertEqual(start_response.status_code, 200, start_response.text)
        self.assertEqual(start_response.json()["startUrl"], "https://zoom.us/s/fresh-private")
        get_meeting.assert_called_once_with("zoom-987")
        self.assertEqual(self.client.post(f"/api/teacher/classes/{item['id']}/zoom-start", headers=self.headers("otherTeacher")).status_code, 403)
        with patch("server.zoom_service.delete_meeting") as delete_meeting:
            cancelled = self.client.post(f"/api/teacher/classes/{item['id']}/cancel", headers=self.headers("teacher"))
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        delete_meeting.assert_called_once_with("zoom-987")

    @patch("server.zoom_service.create_meeting", side_effect=server.zoom_service.ZoomError("Zoom is not configured. Ask an administrator to configure the server.", status_code=503, code="ZOOM_NOT_CONFIGURED"))
    def test_zoom_configuration_failure_does_not_save_class(self, _create_meeting):
        body = self.class_body(title="Unprovisioned Zoom class")
        body.pop("meetingUrl")
        body.pop("teacherJoinUrl")
        body.pop("studentJoinUrl")
        response = self.client.post("/api/teacher/classes", headers=self.headers("teacher"), json=body)
        self.assertEqual(response.status_code, 503)
        self.assertFalse(any(item.get("title") == "Unprovisioned Zoom class" for item in server.load_classes()))


if __name__ == "__main__":
    unittest.main()
