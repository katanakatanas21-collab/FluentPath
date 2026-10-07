import unittest
from unittest.mock import patch

import zoom_service


class ZoomServiceTests(unittest.TestCase):
    def setUp(self):
        zoom_service._token = None
        zoom_service._token_expires_at = 0

    def tearDown(self):
        zoom_service._token = None
        zoom_service._token_expires_at = 0

    @patch.dict("os.environ", {
        "ZOOM_ACCOUNT_ID": "account-test",
        "ZOOM_CLIENT_ID": "client-test",
        "ZOOM_CLIENT_SECRET": "secret-test",
        "ZOOM_HOST_USER_ID": "teacher@example.test",
    })
    def test_oauth_token_is_reused_for_create_update_and_cancel(self):
        meeting = {"id": 123, "start_url": "https://zoom.us/s/private", "join_url": "https://zoom.us/j/student"}
        responses = [(200, {"access_token": "sensitive-token", "expires_in": 3600}), (201, meeting), (204, {}), (200, meeting), (204, {})]
        with patch.object(zoom_service, "_request", side_effect=responses) as request:
            record = {
                "title": "Practice", "description": "Speaking", "date": "2030-02-01",
                "startTime": "12:00", "startsAt": "2030-02-01T12:00:00+00:00", "durationMinutes": 45,
            }
            created = zoom_service.create_meeting(record)
            zoom_service.update_meeting(created["zoomMeetingId"], record)
            fresh_links = zoom_service.get_meeting(created["zoomMeetingId"])
            zoom_service.delete_meeting(created["zoomMeetingId"])

        self.assertEqual(created, {
            "zoomMeetingId": "123", "teacherJoinUrl": "https://zoom.us/s/private",
            "studentJoinUrl": "https://zoom.us/j/student", "meetingUrl": "https://zoom.us/j/student",
        })
        self.assertEqual(request.call_count, 5)
        token_call = request.call_args_list[0]
        self.assertEqual(token_call.args[0], "https://zoom.us/oauth/token")
        self.assertIn(b"grant_type=account_credentials", token_call.kwargs["data"])
        self.assertEqual(request.call_args_list[1].args[0], "https://api.zoom.us/v2/users/teacher@example.test/meetings")
        self.assertEqual(request.call_args_list[2].kwargs["method"], "PATCH")
        self.assertEqual(request.call_args_list[3].kwargs["method"], "GET")
        self.assertEqual(fresh_links["teacherJoinUrl"], "https://zoom.us/s/private")
        self.assertEqual(request.call_args_list[4].kwargs["method"], "DELETE")

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_credentials_fail_without_network_access(self):
        with patch.object(zoom_service, "_request") as request:
            with self.assertRaises(zoom_service.ZoomError) as caught:
                zoom_service.create_meeting({})
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(caught.exception.code, "ZOOM_NOT_CONFIGURED")
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
