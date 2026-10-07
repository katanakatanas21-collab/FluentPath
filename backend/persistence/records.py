"""Translation between JSON store records and normalized PostgreSQL rows.

Two directions are provided:

``records_from_rows``
    Reconstructs the exact JSON record shape the API layer already expects, so
    ``server.py`` domain rules and API responses need no changes.

``rows_from_records``
    Turns records a caller wants to store into the rows of ``db.models``.

The forward direction intentionally mirrors
``import_json_to_postgres._rows_for_tables``, which is the mapping that was
already validated against staging. ``test_persistence_mapping`` asserts the two
produce identical rows for every store, so runtime writes cannot drift away from
the verified import.

Legacy fields that the normalized schema does not model are carried in the
``legacy_fields`` / ``legacy_*`` JSONB columns rather than being dropped.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from persistence.errors import DataStoreError

# ---------------------------------------------------------------------------
# Tables each logical store owns, parents before children.
# ---------------------------------------------------------------------------

STORE_READ_TABLES: Mapping[str, tuple[str, ...]] = {
    "students": ("users", "student_profiles", "gamification_state", "user_badges", "gamification_actions", "lessons", "lesson_completions"),
    "courses": ("courses", "lessons"),
    "homework": ("homework", "homework_assignments"),
    "submissions": ("homework_submissions",),
    "classes": ("classes", "class_students"),
    "community_posts": ("community_posts", "community_post_likes"),
    "community_replies": ("community_replies",),
    "conversations": ("conversations", "conversation_participants"),
    "messages": ("messages", "message_reads"),
    "reports": ("community_reports",),
    "notifications": ("notifications",),
    "ai_sessions": ("ai_sessions",),
    "ai_messages": ("ai_messages",),
    "ai_usage": ("ai_usage_events",),
}

# Tables written for each store. `students` additionally owns lesson completions,
# because a student's course progress is part of their record.
STORE_WRITE_TABLES: Mapping[str, tuple[str, ...]] = {
    "students": ("users", "student_profiles", "gamification_state", "user_badges", "gamification_actions", "lesson_completions"),
    "courses": ("courses", "lessons"),
    "homework": ("homework", "homework_assignments"),
    "submissions": ("homework_submissions",),
    "classes": ("classes", "class_students"),
    "community_posts": ("community_posts", "community_post_likes"),
    "community_replies": ("community_replies",),
    "conversations": ("conversations", "conversation_participants"),
    "messages": ("messages", "message_reads"),
    "reports": ("community_reports",),
    "notifications": ("notifications",),
    "ai_sessions": ("ai_sessions",),
    "ai_messages": ("ai_messages",),
    "ai_usage": ("ai_usage_events",),
}

# Stores whose table key is not carried in the JSON record. These are replaced
# wholesale because the record cannot address individual rows.
UNKEYED_WRITE_TABLES = frozenset({"ai_usage_events"})


class MappingError(DataStoreError):
    """A record could not be translated; treated as an unavailable store."""


# ---------------------------------------------------------------------------
# Scalar helpers
# ---------------------------------------------------------------------------


def _dt(value: Any) -> datetime | None:
    """Parse an aware ISO-8601 timestamp, matching the importer's strictness."""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise MappingError("A record timestamp could not be parsed.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MappingError("A record timestamp is missing a UTC offset.")
    return parsed


def _optional_dt(value: Any) -> datetime | None:
    """Parse a timestamp, treating a malformed value as unknown history."""
    if value in (None, ""):
        return None
    try:
        return _dt(value)
    except MappingError:
        return None


def _date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise MappingError("A record date could not be parsed.") from exc


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise MappingError("A stored value is not a timestamp.")


def _iso_date(value: Any) -> str | None:
    return None if value is None else str(value)


def _text(value: Any, default: str = "") -> str:
    return default if value is None else str(value)


def _number(value: Any) -> Any:
    """Keep JSON numbers as numbers; PostgreSQL coerces to its own numeric type."""
    return value


def _int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise MappingError("A record integer could not be parsed.") from exc


def _required_id(record: Mapping[str, Any], label: str) -> str:
    value = record.get("id")
    if not isinstance(value, str) or not value.strip():
        raise MappingError(f"{label} is missing an identifier.")
    return value


def _id_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, str) and item]


# ---------------------------------------------------------------------------
# Read contexts
# ---------------------------------------------------------------------------


class ReadContext:
    """Rows already fetched from the database, grouped by table name."""

    __slots__ = ("rows",)

    def __init__(self, rows: Mapping[str, Sequence[Mapping[str, Any]]] | None = None):
        self.rows: dict[str, list[Mapping[str, Any]]] = {
            name: list(values) for name, values in (rows or {}).items()
        }

    def table(self, name: str) -> list[Mapping[str, Any]]:
        return self.rows.get(name, [])


class WriteContext:
    """Cross-store facts needed to plan rows for one store write."""

    __slots__ = ("lesson_courses",)

    def __init__(self, lesson_courses: Mapping[str, str] | None = None):
        #: lesson id -> course id, used to keep course progress referentially honest.
        self.lesson_courses: dict[str, str] = dict(lesson_courses or {})


EMPTY_READ_CONTEXT = ReadContext()
EMPTY_WRITE_CONTEXT = WriteContext()


# ---------------------------------------------------------------------------
# Rows -> records
# ---------------------------------------------------------------------------


def _students_from_rows(context: ReadContext) -> list[dict]:
    profiles = {row["user_id"]: row for row in context.table("student_profiles")}
    states = {row["student_id"]: row for row in context.table("gamification_state")}
    badges: dict[str, list[Mapping[str, Any]]] = {}
    for row in context.table("user_badges"):
        badges.setdefault(row["student_id"], []).append(row)
    actions: dict[str, list[Mapping[str, Any]]] = {}
    for row in context.table("gamification_actions"):
        actions.setdefault(row["student_id"], []).append(row)
    lesson_courses = {row["id"]: row["course_id"] for row in context.table("lessons")}

    completions: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in context.table("lesson_completions"):
        completions[(row["student_id"], row["lesson_id"])] = row

    records = []
    for user in context.table("users"):
        user_id = user["id"]
        profile = profiles.get(user_id)
        state = states.get(user_id)
        legacy_gamification = dict(profile.get("legacy_gamification") or {}) if profile else {}

        progress: dict[str, dict] = {}
        if profile:
            for course_id, item in (profile.get("legacy_course_progress") or {}).items():
                completed = item.get("completedLessons", []) if isinstance(item, dict) else []
                progress[course_id] = {
                    **item,
                    "completedLessons": [lesson for lesson in _id_list(completed)],
                }
        # The normalized completion table is authoritative; add anything the
        # retained legacy view does not already list so the two cannot diverge.
        # The table is also the only place a completion time survives, so it has
        # to be written back into the retained view or the next write would
        # erase it.
        for (student_id, lesson_id), row in sorted(
            completions.items(), key=lambda item: (item[0][0], item[1].get("completed_at") or datetime.min.replace(tzinfo=timezone.utc))
        ):
            if student_id != user_id:
                continue
            course_id = lesson_courses.get(lesson_id)
            if course_id is None:
                continue
            item = progress.setdefault(course_id, {"completedLessons": []})
            completed = item.setdefault("completedLessons", [])
            if lesson_id not in completed:
                completed.append(lesson_id)
            completed_at = _iso(row.get("completed_at"))
            if completed_at:
                previous = _iso(item.get("updatedAt"))
                if previous is None or completed_at > previous:
                    item["updatedAt"] = completed_at

        earned = {
            row["badge_id"]: {"id": row["badge_id"], "earnedAt": _iso(row["earned_at"])}
            for row in badges.get(user_id, [])
        }
        retained_badges = [
            badge for badge in legacy_gamification.get("earnedBadges") or []
            if isinstance(badge, dict) and badge.get("id") not in earned
        ]
        badge_records = sorted(
            [*retained_badges, *earned.values()],
            key=lambda item: (item.get("earnedAt") or "", item.get("id") or ""),
        )
        legacy_actions = legacy_gamification.get("awardedActions") or []
        retained = [
            action for action in legacy_actions
            if isinstance(action, str) or not isinstance(action, dict) or not action.get("key")
            or action["key"] not in {row["action_key"] for row in actions.get(user_id, [])}
        ]
        timestamped = sorted(
            (
                {"key": row["action_key"], "xp": row["xp_awarded"], "createdAt": _iso(row["created_at"])}
                for row in actions.get(user_id, [])
            ),
            key=lambda item: (item["createdAt"] or "", item["key"]),
        )
        gamification = {
            **legacy_gamification,
            "xp": int(state["xp"]) if state else _int(legacy_gamification.get("xp")),
            "currentStreak": int(state["current_streak"]) if state else _int(legacy_gamification.get("currentStreak")),
            "longestStreak": int(state["longest_streak"]) if state else _int(legacy_gamification.get("longestStreak")),
            "lastActivityDate": _iso_date(state["last_activity_date"]) if state else legacy_gamification.get("lastActivityDate"),
            "earnedBadges": badge_records,
            "awardedActions": retained + timestamped,
        }

        record = {
            "id": user_id,
            "fullName": user["full_name"],
            "email": user["email"],
            "passwordHash": user["password_hash"],
            "role": user["role"],
            "devOnly": bool(user.get("dev_only", False)),
            "createdAt": _iso(user.get("created_at")),
            # The JSON records use "" for an unknown date of birth or phone number, and
            # users without a student profile (teachers, administrators) carry exactly
            # that. A NULL column must therefore read back as "", never as null, or the
            # profile form's <input type="date"> would receive a null value.
            "dateOfBirth": (_iso_date(profile.get("date_of_birth")) or "") if profile else "",
            "phone": (profile or {}).get("phone") or "",
            "level": (profile or {}).get("level"),
            "testScore": (profile or {}).get("test_score"),
            "totalQuestions": (profile or {}).get("total_questions"),
            "testCompletedAt": _iso((profile or {}).get("test_completed_at")),
            "courseProgress": progress,
        }
        # Students without any gamification history must not grow a gamification
        # key on read, otherwise the next write would invent a state row for them.
        if state is not None or legacy_gamification:
            record["gamification"] = gamification
        records.append(record)
    return records


def _lessons_from_rows(context: ReadContext) -> list[dict]:
    return [
        {
            "id": row["id"],
            "course_id": row["course_id"],
            "number": row.get("number"),
            "title": row["title"],
            "titleAr": row.get("title_ar"),
            "description": row.get("description"),
            "descriptionAr": row.get("description_ar"),
            "content": row.get("content") or {},
            "order": row["display_order"],
            "estimated_minutes": row.get("estimated_minutes"),
            "published": bool(row.get("published", True)),
            "archived": bool(row.get("archived", False)),
            "created_at": _iso(row.get("created_at")),
            "updated_at": _iso(row.get("updated_at")),
        }
        for row in sorted(context.table("lessons"), key=lambda item: (item["course_id"], item["display_order"], item["id"]))
    ]


def _courses_from_rows(context: ReadContext) -> list[dict]:
    lessons = _lessons_from_rows(context)
    by_course: dict[str, list[dict]] = {}
    for lesson in lessons:
        by_course.setdefault(lesson["course_id"], []).append(lesson)
    records = []
    for row in sorted(context.table("courses"), key=lambda item: (item["display_order"], item["id"])):
        legacy = dict(row.get("legacy_fields") or {})
        record = {
            "id": row["id"],
            "type": row["type"],
            "level": row.get("level"),
            "requiredRank": row.get("required_rank"),
            "title": row["title"],
            "titleAr": row.get("title_ar"),
            "description": row.get("description"),
            "descriptionAr": row.get("description_ar"),
            "active": bool(row.get("active", True)),
            "order": row["display_order"],
            **legacy,
            "lessons": by_course.get(row["id"], []),
        }
        if record.get("requiredRank") is None:
            record.pop("requiredRank", None)
        records.append(record)
    return records


def _homework_from_rows(context: ReadContext) -> list[dict]:
    assignments: dict[str, list[str]] = {}
    for row in context.table("homework_assignments"):
        assignments.setdefault(row["homework_id"], []).append(row["student_id"])
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "description": row.get("description") or "",
            "courseId": row.get("course_id"),
            "level": row.get("level"),
            "createdBy": row["created_by"],
            "teacherId": row["teacher_id"],
            "status": row["status"],
            "dueDate": _iso(row.get("due_date")),
            "createdAt": _iso(row.get("created_at")),
            "assignedStudentIds": assignments.get(row["id"], []),
        }
        for row in sorted(context.table("homework"), key=lambda item: (item["created_at"] or datetime.min.replace(tzinfo=timezone.utc), item["id"]))
    ]


def _submissions_from_rows(context: ReadContext) -> list[dict]:
    return [
        {
            "id": row["id"],
            "homeworkId": row["homework_id"],
            "studentId": row["student_id"],
            "answer": row["answer"],
            "status": row["status"],
            "grade": _number(row.get("grade")),
            "teacherFeedback": row.get("teacher_feedback"),
            "submittedAt": _iso(row.get("submitted_at")),
            "gradedAt": _iso(row.get("graded_at")),
        }
        for row in sorted(context.table("homework_submissions"), key=lambda item: (item["submitted_at"] or datetime.min.replace(tzinfo=timezone.utc), item["id"]))
    ]


def _classes_from_rows(context: ReadContext) -> list[dict]:
    members: dict[str, list[str]] = {}
    for row in context.table("class_students"):
        members.setdefault(row["class_id"], []).append(row["student_id"])
    records = []
    for row in sorted(context.table("classes"), key=lambda item: (item["starts_at"] or datetime.min.replace(tzinfo=timezone.utc), item["id"])):
        record = {
            **(row.get("legacy_fields") or {}),
            "id": row["id"],
            "teacherId": row["teacher_id"],
            "courseId": row.get("course_id"),
            "title": row["title"],
            "startsAt": _iso(row.get("starts_at")),
            "durationMinutes": row.get("duration_minutes"),
            "status": row["status"],
            "meetingProvider": row.get("meeting_provider") or "none",
            "meetingUrl": row.get("meeting_url"),
            "teacherJoinUrl": row.get("teacher_join_url"),
            "studentJoinUrl": row.get("student_join_url"),
            "zoomMeetingId": row.get("zoom_meeting_id"),
            "assignedStudentIds": members.get(row["id"], []),
            "createdAt": _iso(row.get("created_at")),
        }
        records.append(record)
    return records


def _community_posts_from_rows(context: ReadContext) -> list[dict]:
    likes: dict[str, list[str]] = {}
    for row in sorted(context.table("community_post_likes"), key=lambda item: (item["post_id"], item["user_id"])):
        likes.setdefault(row["post_id"], []).append(row["user_id"])
    return [
        {
            "id": row["id"],
            "authorId": row["author_id"],
            "scope": row["scope"],
            "courseId": row.get("course_id"),
            "classId": row.get("class_id"),
            "title": row.get("title"),
            "content": row["content"],
            "status": row["status"],
            "createdAt": _iso(row.get("created_at")),
            "updatedAt": _iso(row.get("updated_at")),
            "likesBy": likes.get(row["id"], []),
        }
        for row in sorted(context.table("community_posts"), key=lambda item: (item["created_at"] or datetime.min.replace(tzinfo=timezone.utc), item["id"]))
    ]


def _community_replies_from_rows(context: ReadContext) -> list[dict]:
    return [
        {
            "id": row["id"],
            "postId": row["post_id"],
            "authorId": row["author_id"],
            "content": row["content"],
            "status": row["status"],
            "createdAt": _iso(row.get("created_at")),
            "updatedAt": _iso(row.get("updated_at")),
        }
        for row in sorted(context.table("community_replies"), key=lambda item: (item["created_at"] or datetime.min.replace(tzinfo=timezone.utc), item["id"]))
    ]


def _reports_from_rows(context: ReadContext) -> list[dict]:
    return [
        {
            "id": row["id"],
            "postId": row["post_id"],
            "reporterId": row["reporter_id"],
            "reason": row["reason"],
            "resolution": row.get("resolution"),
            "status": row["status"],
            "createdAt": _iso(row.get("created_at")),
            "resolvedAt": _iso(row.get("resolved_at")),
            "resolvedBy": row.get("resolved_by"),
        }
        for row in sorted(context.table("community_reports"), key=lambda item: (item["created_at"] or datetime.min.replace(tzinfo=timezone.utc), item["id"]))
    ]


def _conversations_from_rows(context: ReadContext) -> list[dict]:
    participants: dict[str, list[str]] = {}
    for row in sorted(context.table("conversation_participants"), key=lambda item: (item["conversation_id"], item["user_id"])):
        participants.setdefault(row["conversation_id"], []).append(row["user_id"])
    records = []
    for row in sorted(context.table("conversations"), key=lambda item: (item["created_at"] or datetime.min.replace(tzinfo=timezone.utc), item["id"])):
        records.append({
            "id": row["id"],
            "type": row["type"],
            "classId": row.get("class_id"),
            "createdBy": row["created_by"],
            "participantIds": participants.get(row["id"], []),
            "createdAt": _iso(row.get("created_at")),
        })
    return records


def _messages_from_rows(context: ReadContext) -> list[dict]:
    readers: dict[str, list[str]] = {}
    for row in sorted(context.table("message_reads"), key=lambda item: (item["message_id"], item["user_id"])):
        readers.setdefault(row["message_id"], []).append(row["user_id"])
    return [
        {
            "id": row["id"],
            "conversationId": row["conversation_id"],
            "senderId": row["sender_id"],
            "content": row["content"],
            "readBy": readers.get(row["id"], []),
            "createdAt": _iso(row.get("created_at")),
        }
        for row in sorted(context.table("messages"), key=lambda item: (item["created_at"] or datetime.min.replace(tzinfo=timezone.utc), item["id"]))
    ]


def _notifications_from_rows(context: ReadContext) -> list[dict]:
    return [
        {
            "id": row["id"],
            "recipient_user_id": row["recipient_user_id"],
            "event_key": row["event_key"],
            "type": row["type"],
            "title": row["title"],
            "message": row["message"],
            "read": bool(row.get("is_read", False)),
            "created_at": _iso(row.get("created_at")),
            "related_entity_type": row.get("related_entity_type"),
            "related_entity_id": row.get("related_entity_id"),
            "severity": row["severity"],
        }
        for row in sorted(context.table("notifications"), key=lambda item: (item["created_at"] or datetime.min.replace(tzinfo=timezone.utc), item["id"]))
    ]


def _ai_sessions_from_rows(context: ReadContext) -> list[dict]:
    return [
        {
            "id": row["id"],
            "student_id": row["student_id"],
            "mode": row["mode"],
            "cefr_level": row.get("cefr_level"),
            "status": row["status"],
            "created_at": _iso(row.get("created_at")),
            "updated_at": _iso(row.get("updated_at")),
            "completed_at": _iso(row.get("completed_at")),
        }
        for row in sorted(context.table("ai_sessions"), key=lambda item: (item["created_at"] or datetime.min.replace(tzinfo=timezone.utc), item["id"]))
    ]


def _ai_messages_from_rows(context: ReadContext) -> list[dict]:
    records = []
    for row in sorted(context.table("ai_messages"), key=lambda item: (item["created_at"] or datetime.min.replace(tzinfo=timezone.utc), item["id"])):
        record = {
            "id": row["id"],
            "session_id": row["session_id"],
            "student_id": row["student_id"],
            "role": row["role"],
            "content": row["content"],
            "feedback": row.get("feedback"),
            "score": _number(row.get("score")),
            "corrections": row.get("corrections"),
            "next_step": row.get("next_step"),
            "xp_awarded": _int(row.get("xp_awarded")),
            "created_at": _iso(row.get("created_at")),
        }
        record.update(row.get("structured_feedback") or {})
        records.append(record)
    return records


def _ai_usage_from_rows(context: ReadContext) -> list[dict]:
    return [
        {"student_id": row["student_id"], "created_at": _iso(row.get("created_at"))}
        for row in sorted(
            context.table("ai_usage_events"),
            key=lambda item: item["created_at"] or datetime.min.replace(tzinfo=timezone.utc),
        )
    ]


RECORDS_FROM_ROWS = {
    "students": _students_from_rows,
    "courses": _courses_from_rows,
    "homework": _homework_from_rows,
    "submissions": _submissions_from_rows,
    "classes": _classes_from_rows,
    "community_posts": _community_posts_from_rows,
    "community_replies": _community_replies_from_rows,
    "conversations": _conversations_from_rows,
    "messages": _messages_from_rows,
    "reports": _reports_from_rows,
    "notifications": _notifications_from_rows,
    "ai_sessions": _ai_sessions_from_rows,
    "ai_messages": _ai_messages_from_rows,
    "ai_usage": _ai_usage_from_rows,
}


def records_from_rows(store_name: str, context: ReadContext) -> list[dict]:
    builder = RECORDS_FROM_ROWS.get(store_name)
    if builder is None:
        raise KeyError(store_name)
    return builder(context)


# ---------------------------------------------------------------------------
# Records -> rows
# ---------------------------------------------------------------------------


def _student_rows(records: Sequence[Mapping[str, Any]], context: WriteContext) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {
        "users": [],
        "student_profiles": [],
        "gamification_state": [],
        "user_badges": [],
        "gamification_actions": [],
        "lesson_completions": [],
    }
    seen: set[str] = set()
    for record in records:
        user_id = _required_id(record, "A user record")
        if user_id in seen:
            raise MappingError("A user record is duplicated.")
        seen.add(user_id)
        role = record.get("role") or "student"
        email = str(record.get("email") or "").strip().lower()
        if not email:
            raise MappingError("A user record is missing an email address.")
        rows["users"].append({
            "id": user_id,
            "email": email,
            "password_hash": _text(record.get("passwordHash"), ""),
            "role": role,
            "full_name": _text(record.get("fullName"), ""),
            "dev_only": bool(record.get("devOnly", False)),
            "created_at": _optional_dt(record.get("createdAt")),
        })
        if role != "student":
            continue
        rows["student_profiles"].append({
            "user_id": user_id,
            "date_of_birth": _date(record.get("dateOfBirth")),
            "phone": record.get("phone"),
            "level": record.get("level"),
            "test_score": record.get("testScore"),
            "total_questions": record.get("totalQuestions"),
            "test_completed_at": _optional_dt(record.get("testCompletedAt")),
            "legacy_course_progress": record.get("courseProgress") or {},
            "legacy_gamification": record.get("gamification") or {},
        })
        game = record.get("gamification") or {}
        if game:
            rows["gamification_state"].append({
                "student_id": user_id,
                "xp": _int(game.get("xp")),
                "current_streak": _int(game.get("currentStreak")),
                "longest_streak": _int(game.get("longestStreak")),
                "last_activity_date": _date(game.get("lastActivityDate")),
            })
        for badge in game.get("earnedBadges") or []:
            if not isinstance(badge, dict) or not badge.get("id"):
                continue
            earned_at = _optional_dt(badge.get("earnedAt"))
            if earned_at is None:
                # No usable timestamp: keep the evidence in the retained legacy
                # document rather than inventing a moment the badge was earned.
                continue
            rows["user_badges"].append({
                "student_id": user_id,
                "badge_id": badge["id"],
                "earned_at": earned_at,
            })
        for action in game.get("awardedActions") or []:
            # String keys are deduplication state, not events; they stay in the
            # retained legacy document. Fabricating event rows for them is wrong.
            if not isinstance(action, dict) or not action.get("key"):
                continue
            created_at = _optional_dt(action.get("createdAt"))
            if created_at is None or "xp" not in action:
                continue
            rows["gamification_actions"].append({
                "student_id": user_id,
                "action_key": action["key"],
                "xp_awarded": _int(action.get("xp")),
                "created_at": created_at,
            })
        progress = record.get("courseProgress") or {}
        if isinstance(progress, dict):
            for course_id, item in progress.items():
                completed = item.get("completedLessons", []) if isinstance(item, dict) else item if isinstance(item, list) else []
                for lesson_id in _id_list(completed):
                    if context.lesson_courses.get(lesson_id) == course_id:
                        rows["lesson_completions"].append({
                            "student_id": user_id,
                            "lesson_id": lesson_id,
                            "completed_at": _optional_dt(item.get("updatedAt")) if isinstance(item, dict) else None,
                        })
    return rows


def _course_rows(records: Sequence[Mapping[str, Any]]) -> dict[str, list[dict]]:
    known_course = {"id", "title", "titleAr", "description", "descriptionAr", "level", "type", "active", "order", "requiredRank", "lessons"}
    known_lesson = {"id", "course_id", "number", "title", "titleAr", "description", "descriptionAr", "content", "order", "estimated_minutes", "estimatedMinutes", "published", "archived", "created_at", "updated_at"}
    rows: dict[str, list[dict]] = {"courses": [], "lessons": []}
    for record in records:
        course_id = _required_id(record, "A course record")
        rank = record.get("requiredRank")
        rows["courses"].append({
            "id": course_id,
            "title": _text(record.get("title"), ""),
            "title_ar": record.get("titleAr"),
            "description": record.get("description"),
            "description_ar": record.get("descriptionAr"),
            "level": record.get("level"),
            "type": record.get("type") or "cefr",
            "active": bool(record.get("active", True)),
            "display_order": _int(record.get("order")),
            "required_rank": rank if isinstance(rank, int) and not isinstance(rank, bool) else None,
            "legacy_fields": {
                key: value for key, value in record.items()
                if key not in known_course or (key == "requiredRank" and not isinstance(value, int))
            },
            "created_at": _optional_dt(record.get("created_at") or record.get("createdAt")),
            "updated_at": _optional_dt(record.get("updated_at") or record.get("updatedAt")),
        })
        for lesson in record.get("lessons") or []:
            content = lesson.get("content") or {}
            if isinstance(content, str):
                content = {"explanation": content}
            created_at = _optional_dt(lesson.get("created_at"))
            updated_at = _optional_dt(lesson.get("updated_at"))
            if created_at is None or updated_at is None:
                raise MappingError("A lesson record is missing its creation or update timestamp.")
            rows["lessons"].append({
                "id": _required_id(lesson, "A lesson record"),
                "course_id": lesson.get("course_id") or course_id,
                "number": lesson.get("number"),
                "title": _text(lesson.get("title"), ""),
                "title_ar": lesson.get("titleAr"),
                "description": lesson.get("description"),
                "description_ar": lesson.get("descriptionAr"),
                "content": content,
                "display_order": _int(lesson.get("order", lesson.get("number")), 0),
                "estimated_minutes": lesson.get("estimated_minutes", lesson.get("estimatedMinutes")),
                "published": bool(lesson.get("published", True)),
                "archived": bool(lesson.get("archived", False)),
                "created_at": created_at,
                "updated_at": updated_at,
            })
    return rows


def _homework_rows(records: Sequence[Mapping[str, Any]]) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {"homework": [], "homework_assignments": []}
    for record in records:
        homework_id = _required_id(record, "A homework record")
        teacher = record.get("teacherId", record.get("createdBy"))
        rows["homework"].append({
            "id": homework_id,
            "created_by": record.get("createdBy", teacher),
            "teacher_id": teacher,
            "course_id": record.get("courseId"),
            "title": _text(record.get("title"), ""),
            "description": _text(record.get("description"), ""),
            "level": record.get("level"),
            "due_date": _optional_dt(record.get("dueDate")),
            "status": record.get("status", "active"),
            "created_at": _optional_dt(record.get("createdAt")),
        })
        for student_id in dict.fromkeys(_id_list(record.get("assignedStudentIds"))):
            rows["homework_assignments"].append({"homework_id": homework_id, "student_id": student_id})
    return rows


def _submission_rows(records: Sequence[Mapping[str, Any]]) -> dict[str, list[dict]]:
    return {
        "homework_submissions": [
            {
                "id": _required_id(record, "A submission record"),
                "homework_id": record.get("homeworkId"),
                "student_id": record.get("studentId"),
                "answer": _text(record.get("answer"), ""),
                "status": record.get("status") or "submitted",
                "grade": record.get("grade"),
                "teacher_feedback": record.get("teacherFeedback"),
                "submitted_at": _optional_dt(record.get("submittedAt")),
                "graded_at": _optional_dt(record.get("gradedAt")),
            }
            for record in records
        ]
    }


def _class_rows(records: Sequence[Mapping[str, Any]]) -> dict[str, list[dict]]:
    known = {"id", "teacherId", "courseId", "title", "startsAt", "durationMinutes", "status", "meetingProvider", "meetingUrl", "teacherJoinUrl", "studentJoinUrl", "zoomMeetingId", "studentIds", "assignedStudentIds", "createdAt"}
    rows: dict[str, list[dict]] = {"classes": [], "class_students": []}
    for record in records:
        class_id = _required_id(record, "A class record")
        rows["classes"].append({
            "id": class_id,
            "teacher_id": record.get("teacherId"),
            "course_id": record.get("courseId"),
            "title": _text(record.get("title"), ""),
            "starts_at": _optional_dt(record.get("startsAt") or record.get("dateTime")),
            "duration_minutes": record.get("durationMinutes"),
            "status": record.get("status") or "scheduled",
            "meeting_provider": record.get("meetingProvider") or "none",
            "meeting_url": record.get("meetingUrl"),
            "teacher_join_url": record.get("teacherJoinUrl"),
            "student_join_url": record.get("studentJoinUrl"),
            "zoom_meeting_id": record.get("zoomMeetingId"),
            "legacy_fields": {key: value for key, value in record.items() if key not in known},
            "created_at": _optional_dt(record.get("createdAt")),
        })
        for student_id in dict.fromkeys(_id_list(record.get("studentIds", record.get("assignedStudentIds", [])))):
            rows["class_students"].append({"class_id": class_id, "student_id": student_id})
    return rows


def _community_post_rows(records: Sequence[Mapping[str, Any]]) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {"community_posts": [], "community_post_likes": []}
    for record in records:
        post_id = _required_id(record, "A community post record")
        rows["community_posts"].append({
            "id": post_id,
            "author_id": record.get("authorId"),
            "scope": record.get("scope") or "general",
            "course_id": record.get("courseId"),
            "class_id": record.get("classId"),
            "title": record.get("title"),
            "content": _text(record.get("content"), ""),
            "status": record.get("status") or "active",
            "created_at": _optional_dt(record.get("createdAt")),
            "updated_at": _optional_dt(record.get("updatedAt")),
        })
        for user_id in dict.fromkeys(_id_list(record.get("likesBy"))):
            rows["community_post_likes"].append({"post_id": post_id, "user_id": user_id, "created_at": None})
    return rows


def _community_reply_rows(records: Sequence[Mapping[str, Any]]) -> dict[str, list[dict]]:
    return {
        "community_replies": [
            {
                "id": _required_id(record, "A community reply record"),
                "post_id": record.get("postId"),
                "author_id": record.get("authorId"),
                "content": _text(record.get("content"), ""),
                "status": record.get("status") or "active",
                "created_at": _optional_dt(record.get("createdAt")),
                "updated_at": _optional_dt(record.get("updatedAt")),
            }
            for record in records
        ]
    }


def _report_rows(records: Sequence[Mapping[str, Any]]) -> dict[str, list[dict]]:
    return {
        "community_reports": [
            {
                "id": _required_id(record, "A community report record"),
                "post_id": record.get("postId"),
                "reporter_id": record.get("reporterId"),
                "reason": _text(record.get("reason"), ""),
                "resolution": record.get("resolution"),
                "status": record.get("status") or "open",
                "created_at": _optional_dt(record.get("createdAt")),
                "resolved_at": _optional_dt(record.get("resolvedAt")),
                "resolved_by": record.get("resolvedBy"),
            }
            for record in records
        ]
    }


def _conversation_rows(records: Sequence[Mapping[str, Any]]) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {"conversations": [], "conversation_participants": []}
    for record in records:
        conversation_id = _required_id(record, "A conversation record")
        participants = sorted(dict.fromkeys(_id_list(record.get("participantIds"))))
        rows["conversations"].append({
            "id": conversation_id,
            "type": record.get("type", "student_teacher"),
            "class_id": record.get("classId"),
            "scope_key": record.get("classId") or "",
            "created_by": record.get("createdBy") or (participants[0] if participants else ""),
            "pair_key": "|".join(participants),
            "created_at": _optional_dt(record.get("createdAt")),
        })
        for user_id in participants:
            rows["conversation_participants"].append({"conversation_id": conversation_id, "user_id": user_id})
    return rows


def _message_rows(records: Sequence[Mapping[str, Any]]) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {"messages": [], "message_reads": []}
    for record in records:
        message_id = _required_id(record, "A message record")
        rows["messages"].append({
            "id": message_id,
            "conversation_id": record.get("conversationId"),
            "sender_id": record.get("senderId"),
            "content": _text(record.get("content"), ""),
            "created_at": _optional_dt(record.get("createdAt")),
        })
        for user_id in dict.fromkeys(_id_list(record.get("readBy"))):
            rows["message_reads"].append({"message_id": message_id, "user_id": user_id, "read_at": None})
    return rows


def _notification_rows(records: Sequence[Mapping[str, Any]]) -> dict[str, list[dict]]:
    return {
        "notifications": [
            {
                "id": _required_id(record, "A notification record"),
                "recipient_user_id": record.get("recipient_user_id"),
                "event_key": record.get("event_key") or _required_id(record, "A notification record"),
                "type": record.get("type") or "info",
                "title": _text(record.get("title"), ""),
                "message": _text(record.get("message"), ""),
                "related_entity_type": record.get("related_entity_type"),
                "related_entity_id": record.get("related_entity_id"),
                "severity": record.get("severity") or "info",
                "is_read": bool(record.get("read", False)),
                "created_at": _optional_dt(record.get("created_at")),
            }
            for record in records
        ]
    }


def _ai_session_rows(records: Sequence[Mapping[str, Any]]) -> dict[str, list[dict]]:
    return {
        "ai_sessions": [
            {
                "id": _required_id(record, "An AI session record"),
                "student_id": record.get("student_id"),
                "mode": record.get("mode") or "conversation",
                "cefr_level": record.get("cefr_level"),
                "status": record.get("status") or "active",
                "created_at": _optional_dt(record.get("created_at")),
                "updated_at": _optional_dt(record.get("updated_at")),
                "completed_at": _optional_dt(record.get("completed_at")),
            }
            for record in records
        ]
    }


def _ai_message_rows(records: Sequence[Mapping[str, Any]]) -> dict[str, list[dict]]:
    return {
        "ai_messages": [
            {
                "id": _required_id(record, "An AI message record"),
                "session_id": record.get("session_id"),
                "student_id": record.get("student_id"),
                "role": record.get("role") or "user",
                "content": _text(record.get("content"), ""),
                "feedback": record.get("feedback"),
                "score": record.get("score"),
                "corrections": record.get("corrections"),
                "next_step": record.get("next_step"),
                "structured_feedback": {
                    key: record[key]
                    for key in ("grammar_feedback", "vocabulary_feedback", "clarity_feedback", "relevance_feedback")
                    if key in record
                },
                "xp_awarded": _int(record.get("xp_awarded")),
                "created_at": _optional_dt(record.get("created_at")),
            }
            for record in records
        ]
    }


def _ai_usage_rows(records: Sequence[Mapping[str, Any]]) -> dict[str, list[dict]]:
    return {
        "ai_usage_events": [
            {"student_id": record.get("student_id"), "created_at": _optional_dt(record.get("created_at"))}
            for record in records
        ]
    }


ROWS_FROM_RECORDS = {
    "students": _student_rows,
    "courses": _course_rows,
    "homework": _homework_rows,
    "submissions": _submission_rows,
    "classes": _class_rows,
    "community_posts": _community_post_rows,
    "community_replies": _community_reply_rows,
    "conversations": _conversation_rows,
    "messages": _message_rows,
    "reports": _report_rows,
    "notifications": _notification_rows,
    "ai_sessions": _ai_session_rows,
    "ai_messages": _ai_message_rows,
    "ai_usage": _ai_usage_rows,
}


def rows_from_records(
    store_name: str,
    records: Iterable[Mapping[str, Any]],
    context: WriteContext | None = None,
) -> dict[str, list[dict]]:
    """Plan the database rows required to make one store hold ``records``."""
    builder = ROWS_FROM_RECORDS.get(store_name)
    if builder is None:
        raise KeyError(store_name)
    materialized = list(records)
    if builder is _student_rows:
        return builder(materialized, context or EMPTY_WRITE_CONTEXT)
    return builder(materialized)


def table_key_columns(table) -> tuple[str, ...]:
    return tuple(column.name for column in table.primary_key.columns)