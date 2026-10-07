"""Server-to-Server OAuth client for Zoom meetings.

Credentials are read only by this backend module and are never returned to callers.
"""

import base64
import json
import os
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.parse import quote
from urllib.request import Request, urlopen


class ZoomError(Exception):
    def __init__(self, message="Zoom is temporarily unavailable", *, status_code=502, code="ZOOM_UNAVAILABLE"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


_token = None
_token_expires_at = 0
_token_lock = threading.Lock()


def is_configured():
    return all(os.getenv(key, "").strip() for key in (
        "ZOOM_ACCOUNT_ID", "ZOOM_CLIENT_ID", "ZOOM_CLIENT_SECRET", "ZOOM_HOST_USER_ID",
    ))


def _request(url, *, method="GET", headers=None, data=None):
    request = Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urlopen(request, timeout=12) as response:
            body = response.read()
            return response.status, json.loads(body.decode("utf-8")) if body else {}
    except HTTPError as error:
        # Consume the provider response without propagating its body or credentials.
        try:
            error.read()
        finally:
            raise ZoomError(status_code=404 if error.code == 404 else 502) from None
    except (URLError, TimeoutError, OSError, ValueError) as error:
        raise ZoomError() from None


def _access_token():
    global _token, _token_expires_at
    if not is_configured():
        raise ZoomError("Zoom is not configured. Ask an administrator to configure the server.", status_code=503, code="ZOOM_NOT_CONFIGURED")
    with _token_lock:
        if _token and time.time() < _token_expires_at - 60:
            return _token
        client_pair = f"{os.environ['ZOOM_CLIENT_ID']}:{os.environ['ZOOM_CLIENT_SECRET']}".encode()
        basic_auth = base64.b64encode(client_pair).decode("ascii")
        status, payload = _request(
            "https://zoom.us/oauth/token",
            method="POST",
            headers={
                "Authorization": f"Basic {basic_auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=urlencode({
                "grant_type": "account_credentials",
                "account_id": os.environ["ZOOM_ACCOUNT_ID"],
            }).encode("ascii"),
        )
        access_token = payload.get("access_token") if status == 200 else None
        if not access_token:
            raise ZoomError()
        _token = access_token
        _token_expires_at = time.time() + int(payload.get("expires_in", 3600))
        return _token


def _api(method, path, payload=None):
    token = _access_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    status, response = _request(
        f"https://api.zoom.us/v2{path}",
        method=method,
        headers=headers,
        data=body,
    )
    if status < 200 or status >= 300:
        raise ZoomError()
    return response


def meeting_payload(class_item):
    starts_at = class_item.get("startsAt") or f"{class_item['date']}T{class_item['startTime']}:00+00:00"
    return {
        "topic": class_item["title"],
        "agenda": class_item.get("description", ""),
        "type": 2,
        "start_time": starts_at,
        "timezone": "UTC",
        "duration": int(class_item.get("durationMinutes", 45)),
        "settings": {"waiting_room": True},
    }


def create_meeting(class_item):
    if not is_configured():
        raise ZoomError("Zoom is not configured. Ask an administrator to configure the server.", status_code=503, code="ZOOM_NOT_CONFIGURED")
    host_id = quote(os.environ["ZOOM_HOST_USER_ID"].strip(), safe="@.+_-")
    payload = _api("POST", f"/users/{host_id}/meetings", meeting_payload(class_item))
    if not payload.get("id") or not payload.get("start_url") or not payload.get("join_url"):
        raise ZoomError()
    return {
        "zoomMeetingId": str(payload["id"]),
        "teacherJoinUrl": payload["start_url"],
        "studentJoinUrl": payload["join_url"],
        "meetingUrl": payload["join_url"],
    }


def update_meeting(meeting_id, class_item):
    _api("PATCH", f"/meetings/{quote(str(meeting_id), safe='')}", meeting_payload(class_item))


def get_meeting(meeting_id):
    payload = _api("GET", f"/meetings/{quote(str(meeting_id), safe='')}")
    if not payload.get("start_url") or not payload.get("join_url"):
        raise ZoomError()
    return {"teacherJoinUrl": payload["start_url"], "studentJoinUrl": payload["join_url"], "meetingUrl": payload["join_url"]}


def delete_meeting(meeting_id):
    # Zoom returns 204 on success. Treat an already-removed meeting as completed.
    try:
        _api("DELETE", f"/meetings/{quote(str(meeting_id), safe='')}")
    except ZoomError as error:
        if error.status_code != 404:
            raise
