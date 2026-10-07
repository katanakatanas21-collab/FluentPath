"""Guarded JSON inventory/import command. Dry-run is the default.

Nothing in this module imports backend/server.py or writes to source JSON files.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
from pathlib import PureWindowsPath
from typing import Any
from datetime import date, datetime

from db.revision import EXPECTED_SCHEMA_REVISION
from db_config import DatabaseConfigurationError, importer_target_identity, importer_target_url

STORE_NAMES = (
    "students", "courses", "homework", "submissions", "classes",
    "community_posts", "community_replies", "conversations", "messages",
    "reports", "notifications", "ai_sessions", "ai_messages", "ai_usage",
)
APP_TABLES = (
    "users", "student_profiles", "courses", "lessons", "lesson_completions",
    "homework", "homework_assignments", "homework_submissions", "classes",
    "class_students", "community_posts", "community_post_likes", "community_replies",
    "community_reports", "conversations", "conversation_participants", "messages",
    "message_reads", "notifications", "ai_sessions", "ai_messages", "ai_usage_events",
    "revoked_tokens", "gamification_state", "user_badges", "gamification_actions",
)
#: Shared with the persistence runtime so a new revision cannot be adopted by the
#: importer and silently missed by the running application.
EXPECTED_REVISION = EXPECTED_SCHEMA_REVISION
# This exception is deliberately pinned to one identified source record and the
# digest of its observed malformed value. It cannot authorize another bad value.
LEGACY_UNKNOWN_CREATED_AT = {
    "user_id": "ac541972745fe045",
    "value_sha256": "9564efa6c8f1665560ff1a5bdf318c7969a11c9b5bdec0821af769917aac53e4",
    "format": "windows_absolute_path_string",
}


class ImportValidationError(ValueError):
    pass


def load_source(source: Path) -> dict[str, list[dict[str, Any]]]:
    resolved = source.resolve(strict=True)
    if ".qa-disposable" in {part.lower() for part in resolved.parts}:
        raise ImportValidationError("QA disposable directories are not valid import sources")
    if resolved.name.lower() != "data":
        raise ImportValidationError("Source must be an explicitly selected data directory")
    result = {}
    for name in STORE_NAMES:
        path = resolved / f"{name}.json"
        if not path.is_file():
            raise ImportValidationError(f"Required source store is missing: {name}.json")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ImportValidationError(f"Source store cannot be read: {name}.json") from exc
        if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
            raise ImportValidationError(f"Source store must contain a list of objects: {name}.json")
        result[name] = value
    return result


def _unique_ids(rows: list[dict[str, Any]], label: str, *, key: str = "id", optional: bool = False) -> set[str]:
    seen: set[str] = set()
    for row in rows:
        value = row.get(key)
        if optional and value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise ImportValidationError(f"{label} contains a missing or invalid {key}")
        if value in seen:
            raise ImportValidationError(f"{label} contains duplicate {key} values")
        seen.add(value)
    return seen


def validate_source(stores: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    """Validate unique identifiers and known references without exposing row values."""
    users = _unique_ids(stores["students"], "students")
    user_roles = {row["id"]: row.get("role", "student") for row in stores["students"]}
    emails = [str(row.get("email", "")).strip().lower() for row in stores["students"]]
    if any(not email for email in emails) or len(set(emails)) != len(emails):
        raise ImportValidationError("students contains missing or duplicate normalized emails")
    if any(row.get("role", "student") not in {"student", "teacher", "administrator"} for row in stores["students"]):
        raise ImportValidationError("students contains an unsupported role")
    if any(not isinstance(row.get("passwordHash"), str) or not row["passwordHash"] for row in stores["students"]):
        raise ImportValidationError("students contains a missing password hash")
    courses = _unique_ids(stores["courses"], "courses")
    lessons: set[str] = set()
    lesson_course: dict[str, str] = {}
    for course in stores["courses"]:
        for lesson in course.get("lessons", []):
            if not isinstance(lesson, dict):
                raise ImportValidationError("courses contains an invalid lesson record")
            lesson_id = _unique_ids([lesson], "lessons").pop()
            if lesson_id in lessons:
                raise ImportValidationError("lessons contains duplicate identifiers")
            lessons.add(lesson_id)
            lesson_course[lesson_id] = course["id"]
            if lesson.get("course_id") not in (None, course["id"]):
                raise ImportValidationError("lesson course reference does not match its parent")
    homework = _unique_ids(stores["homework"], "homework")
    classes = _unique_ids(stores["classes"], "classes")
    posts = _unique_ids(stores["community_posts"], "community_posts")
    replies = _unique_ids(stores["community_replies"], "community_replies")
    conversations = _unique_ids(stores["conversations"], "conversations")
    messages = _unique_ids(stores["messages"], "messages")
    reports = _unique_ids(stores["reports"], "reports")
    notifications = _unique_ids(stores["notifications"], "notifications")
    ai_sessions = _unique_ids(stores["ai_sessions"], "ai_sessions")
    ai_messages = _unique_ids(stores["ai_messages"], "ai_messages")

    def ref(value: Any, available: set[str], label: str, *, optional: bool = False) -> None:
        if optional and value is None:
            return
        if value not in available:
            raise ImportValidationError(f"{label} contains an unresolved reference")

    for row in stores["homework"]:
        ref(row.get("teacherId", row.get("createdBy")), users, "homework teacher")
        ref(row.get("createdBy", row.get("teacherId")), users, "homework creator")
        if user_roles.get(row.get("teacherId", row.get("createdBy"))) != "teacher":
            raise ImportValidationError("homework teacher relationship has an invalid role")
        ref(row.get("courseId"), courses, "homework course", optional=True)
        assigned = row.get("assignedStudentIds", [])
        if len(assigned) != len(set(assigned)):
            raise ImportValidationError("homework contains duplicate student assignments")
        for uid in assigned:
            ref(uid, users, "homework assignee")
            if user_roles.get(uid) != "student": raise ImportValidationError("homework assignee relationship has an invalid role")
    for row in stores["submissions"]:
        ref(row.get("homeworkId"), homework, "submission homework")
        ref(row.get("studentId"), users, "submission student")
    for row in stores["classes"]:
        ref(row.get("teacherId"), users, "class teacher")
        if user_roles.get(row.get("teacherId")) != "teacher":
            raise ImportValidationError("class teacher relationship has an invalid role")
        ref(row.get("courseId"), courses, "class course", optional=True)
        assigned = row.get("studentIds", row.get("assignedStudentIds", []))
        if len(assigned) != len(set(assigned)):
            raise ImportValidationError("class contains duplicate student assignments")
        for uid in assigned:
            ref(uid, users, "class student")
            if user_roles.get(uid) != "student": raise ImportValidationError("class student relationship has an invalid role")
    for row in stores["community_posts"]:
        ref(row.get("authorId"), users, "post author")
        ref(row.get("courseId"), courses, "post course", optional=True)
        ref(row.get("classId"), classes, "post class", optional=True)
        for uid in row.get("likesBy", []): ref(uid, users, "post like")
        if len(row.get("likesBy", [])) != len(set(row.get("likesBy", []))):
            raise ImportValidationError("community post contains duplicate likes")
    for user in stores["students"]:
        progress = user.get("courseProgress") or {}
        if not isinstance(progress, dict):
            raise ImportValidationError("student course progress has an invalid shape")
        for course_id, item in progress.items():
            ref(course_id, courses, "course progress course")
            lesson_list = item.get("completedLessons", []) if isinstance(item, dict) else item if isinstance(item, list) else []
            if not isinstance(lesson_list, list):
                raise ImportValidationError("student course progress has an invalid lesson list")
            if len(lesson_list) != len(set(lesson_list)):
                raise ImportValidationError("student course progress contains duplicate lesson entries")
            for lesson_id in lesson_list:
                if lesson_id not in lessons or lesson_course.get(lesson_id) != course_id:
                    raise ImportValidationError("student course progress contains an unresolved lesson reference")
    for row in stores["community_replies"]:
        ref(row.get("postId"), posts, "reply post"); ref(row.get("authorId"), users, "reply author")
    for row in stores["reports"]:
        ref(row.get("postId"), posts, "report post"); ref(row.get("reporterId"), users, "report reporter")
        ref(row.get("resolvedBy"), users, "report resolver", optional=True)
    open_reports = [(r.get("postId"), r.get("reporterId")) for r in stores["reports"] if r.get("status") == "open"]
    if len(open_reports) != len(set(open_reports)):
        raise ImportValidationError("reports contains duplicate open reports")
    for row in stores["conversations"]:
        ref(row.get("classId"), classes, "conversation class", optional=True)
        ref(row.get("createdBy"), users, "conversation creator")
        participants = row.get("participantIds", [])
        if len(participants) < 2 or len(participants) != len(set(participants)):
            raise ImportValidationError("conversation participants are missing or duplicated")
        for uid in participants: ref(uid, users, "conversation participant")
    for row in stores["messages"]:
        ref(row.get("conversationId"), conversations, "message conversation")
        ref(row.get("senderId"), users, "message sender")
        readers = row.get("readBy", [])
        if len(readers) != len(set(readers)):
            raise ImportValidationError("message contains duplicate read receipts")
        for uid in readers: ref(uid, users, "message reader")
        conversation = next(item for item in stores["conversations"] if item.get("id") == row.get("conversationId"))
        if row.get("senderId") not in conversation.get("participantIds", []):
            raise ImportValidationError("message sender is not a conversation participant")
        if any(uid not in conversation.get("participantIds", []) for uid in row.get("readBy", [])):
            raise ImportValidationError("message reader is not a conversation participant")
    for row in stores["notifications"]:
        ref(row.get("recipient_user_id"), users, "notification recipient")
    notification_keys = [(r.get("recipient_user_id"), r.get("event_key")) for r in stores["notifications"]]
    if len(notification_keys) != len(set(notification_keys)):
        raise ImportValidationError("notifications contains duplicate recipient event keys")
    for row in stores["ai_sessions"]:
        ref(row.get("student_id"), users, "AI session student")
        if user_roles.get(row.get("student_id")) != "student": raise ImportValidationError("AI session owner has an invalid role")
    for row in stores["ai_messages"]:
        ref(row.get("session_id"), ai_sessions, "AI message session")
        ref(row.get("student_id"), users, "AI message student")
        if user_roles.get(row.get("student_id")) != "student": raise ImportValidationError("AI message owner has an invalid role")
        session = next(item for item in stores["ai_sessions"] if item.get("id") == row.get("session_id"))
        if session.get("student_id") != row.get("student_id"):
            raise ImportValidationError("AI message owner does not match its session")
    for row in stores["ai_usage"]:
        ref(row.get("student_id"), users, "AI usage student")
    return {name: len(rows) for name, rows in stores.items()} | {"lessons": len(lessons)}


def _dt(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed
    except (ValueError, TypeError, AttributeError) as exc:
        raise ImportValidationError("Source contains an invalid timestamp") from exc


def _historical_timestamp(row: dict, *keys: str) -> datetime | None:
    """Accept known source aliases only; reject malformed or conflicting evidence."""
    values = [_dt(row[key]) for key in keys if key in row and row[key] is not None]
    if values and any(value != values[0] for value in values):
        raise ImportValidationError("Source contains conflicting historical timestamps")
    return values[0] if values else None


def _date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ImportValidationError("Source contains an invalid date") from exc


def _rows_for_tables(
    stores: dict[str, list[dict[str, Any]]],
    *,
    approved_legacy_created_at_ids: frozenset[str] = frozenset(),
    audit_events: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Transform source records into the schema while retaining legacy flexible fields."""
    rows: dict[str, list[dict[str, Any]]] = {name: [] for name in APP_TABLES}
    audit_events = audit_events if audit_events is not None else []
    known_legacy_ids = {LEGACY_UNKNOWN_CREATED_AT["user_id"]}
    if approved_legacy_created_at_ids - known_legacy_ids:
        raise ImportValidationError("Unknown legacy timestamp approval rule")
    if approved_legacy_created_at_ids and approved_legacy_created_at_ids != known_legacy_ids:
        raise ImportValidationError("Legacy timestamp approval must name the exact known record")
    # Validate populated timestamp evidence even when retained only in JSONB.
    # The sole exception is checked again by the narrow user mapping below.
    def check_times(value: Any, *, legacy_user: bool = False) -> None:
        if isinstance(value, list):
            for item in value:
                check_times(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("At") or key.endswith("_at") or key == "dueDate":
                    if not (legacy_user and key == "createdAt"):
                        _dt(item)
                elif isinstance(item, (dict, list)):
                    check_times(item)
    for store, records in stores.items():
        for record in records:
            check_times(record, legacy_user=store == "students")
    approved_rule_used = False
    lesson_ids: dict[str, str] = {}
    for user in stores["students"]:
        created_at_value = user.get("createdAt")
        try:
            user_created_at = _dt(created_at_value)
        except ImportValidationError:
            digest = hashlib.sha256(str(created_at_value).encode("utf-8")).hexdigest()
            is_exact_known_anomaly = (
                user.get("id") == LEGACY_UNKNOWN_CREATED_AT["user_id"]
                and isinstance(created_at_value, str)
                and PureWindowsPath(created_at_value).is_absolute()
                and digest == LEGACY_UNKNOWN_CREATED_AT["value_sha256"]
            )
            if not is_exact_known_anomaly or user.get("id") not in approved_legacy_created_at_ids:
                raise
            user_created_at = None
            approved_rule_used = True
            audit_events.append({
                "record_id": LEGACY_UNKNOWN_CREATED_AT["user_id"],
                "store": "students.json",
                "field": "createdAt",
                "observed_format": LEGACY_UNKNOWN_CREATED_AT["format"],
                "original_value_sha256": digest,
                "planned_import_value": None,
                "rule": "explicitly_approved_unknown_legacy_timestamp",
            })
        if user_created_at is None and user.get("id") not in approved_legacy_created_at_ids:
            raise ImportValidationError("students contains a missing creation timestamp")
        rows["users"].append({"id": user["id"], "email": user["email"].strip().lower(), "password_hash": user["passwordHash"], "role": user.get("role", "student"), "full_name": user.get("fullName", ""), "dev_only": bool(user.get("devOnly", False)), "created_at": user_created_at})
        if user.get("role", "student") == "student":
            rows["student_profiles"].append({"user_id": user["id"], "date_of_birth": _date(user.get("dateOfBirth")), "phone": user.get("phone"), "level": user.get("level"), "test_score": user.get("testScore"), "total_questions": user.get("totalQuestions"), "test_completed_at": _dt(user.get("testCompletedAt")), "legacy_course_progress": user.get("courseProgress") or {}, "legacy_gamification": user.get("gamification") or {}})
            game = user.get("gamification") or {}
            if game:
                if any(type(game.get(key)) is not int or game[key] < 0 for key in ("xp", "currentStreak", "longestStreak")):
                    raise ImportValidationError("Stored gamification state lacks valid counters")
                rows["gamification_state"].append({"student_id": user["id"], "xp": game["xp"], "current_streak": game["currentStreak"], "longest_streak": game["longestStreak"], "last_activity_date": _date(game.get("lastActivityDate"))})
            for badge in game.get("earnedBadges", []):
                if isinstance(badge, str):
                    raise ImportValidationError("Badge has no historical earned timestamp")
                elif isinstance(badge, dict) and badge.get("id"):
                    rows["user_badges"].append({"student_id": user["id"], "badge_id": badge["id"], "earned_at": _dt(badge.get("earnedAt"))})
            for action in game.get("awardedActions", []):
                # Strings are deduplication state, not timestamped event records.
                # Preserve them in legacy_gamification; never fabricate events.
                if isinstance(action, str) and action:
                    continue
                if not isinstance(action, dict) or not action.get("key"):
                    raise ImportValidationError("Invalid gamification action evidence")
                timestamp = _dt(action.get("createdAt"))
                if timestamp is None or "xp" not in action:
                    continue  # Incomplete evidence remains in legacy_gamification.
                if type(action["xp"]) is not int or action["xp"] < 0:
                    raise ImportValidationError("Invalid gamification action XP evidence")
                rows["gamification_actions"].append({"student_id": user["id"], "action_key": action["key"], "xp_awarded": action["xp"], "created_at": timestamp})

    if approved_legacy_created_at_ids and not approved_rule_used:
        raise ImportValidationError("Approved legacy timestamp rule did not match the exact known anomaly")

    for course in stores["courses"]:
        lesson_list = course.get("lessons") or []
        known = {"id", "title", "titleAr", "description", "descriptionAr", "level", "type", "active", "order", "requiredRank", "lessons"}
        rows["courses"].append({"id": course["id"], "title": course.get("title", ""), "title_ar": course.get("titleAr"), "description": course.get("description"), "description_ar": course.get("descriptionAr"), "level": course.get("level"), "type": course.get("type", "cefr"), "active": bool(course.get("active", True)), "display_order": int(course.get("order", 0)), "required_rank": course.get("requiredRank") if isinstance(course.get("requiredRank"), int) else None, "legacy_fields": {k: v for k, v in course.items() if k not in known or (k == "requiredRank" and not isinstance(v, int))}, "created_at": _historical_timestamp(course, "created_at", "createdAt"), "updated_at": _historical_timestamp(course, "updated_at", "updatedAt")})
        for lesson in lesson_list:
            lesson_ids[lesson["id"]] = course["id"]
            content = lesson.get("content") or {}
            if isinstance(content, str): content = {"explanation": content}
            known_lesson = {"id", "course_id", "title", "titleAr", "description", "descriptionAr", "content", "number", "order", "estimated_minutes", "published", "archived", "created_at", "updated_at"}
            rows["lessons"].append({"id": lesson["id"], "course_id": course["id"], "number": lesson.get("number"), "title": lesson.get("title", ""), "title_ar": lesson.get("titleAr"), "description": lesson.get("description"), "description_ar": lesson.get("descriptionAr"), "content": content, "display_order": int(lesson.get("order", lesson.get("number", 0)) or 0), "estimated_minutes": lesson.get("estimated_minutes", lesson.get("estimatedMinutes")), "published": bool(lesson.get("published", True)), "archived": bool(lesson.get("archived", False)), "created_at": _dt(lesson.get("created_at")), "updated_at": _dt(lesson.get("updated_at"))})
    for user in stores["students"]:
        progress = user.get("courseProgress") or {}
        if isinstance(progress, dict):
            for course_id, item in progress.items():
                completed = item.get("completedLessons", []) if isinstance(item, dict) else item if isinstance(item, list) else []
                for lesson_id in completed:
                    if lesson_id in lesson_ids and lesson_ids[lesson_id] == course_id:
                        rows["lesson_completions"].append({"student_id": user["id"], "lesson_id": lesson_id, "completed_at": None})

    for h in stores["homework"]:
        teacher = h.get("teacherId", h.get("createdBy"))
        rows["homework"].append({"id": h["id"], "created_by": h.get("createdBy", teacher), "teacher_id": teacher, "course_id": h.get("courseId"), "title": h.get("title", ""), "description": h.get("description", ""), "level": h.get("level"), "due_date": _dt(h.get("dueDate")), "status": h.get("status", "active"), "created_at": _dt(h.get("createdAt"))})
        for uid in h.get("assignedStudentIds", []): rows["homework_assignments"].append({"homework_id": h["id"], "student_id": uid})
    for item in stores["submissions"]:
        rows["homework_submissions"].append({"id": item["id"], "homework_id": item.get("homeworkId"), "student_id": item.get("studentId"), "answer": item.get("answer", ""), "status": item.get("status", "submitted"), "grade": item.get("grade"), "teacher_feedback": item.get("teacherFeedback"), "submitted_at": _dt(item.get("submittedAt")), "graded_at": _dt(item.get("gradedAt"))})

    for c in stores["classes"]:
        known = {"id", "teacherId", "courseId", "title", "startsAt", "durationMinutes", "status", "meetingProvider", "meetingUrl", "teacherJoinUrl", "studentJoinUrl", "zoomMeetingId", "studentIds", "assignedStudentIds", "createdAt"}
        rows["classes"].append({"id": c["id"], "teacher_id": c.get("teacherId"), "course_id": c.get("courseId"), "title": c.get("title", ""), "starts_at": _dt(c.get("startsAt")), "duration_minutes": c.get("durationMinutes"), "status": c.get("status", "scheduled"), "meeting_provider": c.get("meetingProvider", "none"), "meeting_url": c.get("meetingUrl"), "teacher_join_url": c.get("teacherJoinUrl"), "student_join_url": c.get("studentJoinUrl"), "zoom_meeting_id": c.get("zoomMeetingId"), "legacy_fields": {k: v for k, v in c.items() if k not in known}, "created_at": _dt(c.get("createdAt"))})
        for uid in c.get("studentIds", c.get("assignedStudentIds", [])): rows["class_students"].append({"class_id": c["id"], "student_id": uid})

    for p in stores["community_posts"]:
        rows["community_posts"].append({"id": p["id"], "author_id": p.get("authorId"), "scope": p.get("scope", "general"), "course_id": p.get("courseId"), "class_id": p.get("classId"), "title": p.get("title"), "content": p.get("content", ""), "status": p.get("status", "active"), "created_at": _dt(p.get("createdAt")), "updated_at": _dt(p.get("updatedAt"))})
        for uid in p.get("likesBy", []): rows["community_post_likes"].append({"post_id": p["id"], "user_id": uid, "created_at": None})
    for r in stores["community_replies"]:
        rows["community_replies"].append({"id": r["id"], "post_id": r.get("postId"), "author_id": r.get("authorId"), "content": r.get("content", ""), "status": r.get("status", "active"), "created_at": _dt(r.get("createdAt")), "updated_at": _dt(r.get("updatedAt"))})
    for r in stores["reports"]:
        rows["community_reports"].append({"id": r["id"], "post_id": r.get("postId"), "reporter_id": r.get("reporterId"), "reason": r.get("reason", ""), "resolution": r.get("resolution"), "status": r.get("status", "open"), "created_at": _dt(r.get("createdAt")), "resolved_at": _dt(r.get("resolvedAt")), "resolved_by": r.get("resolvedBy")})

    for c in stores["conversations"]:
        participants = sorted(c.get("participantIds", []))
        pair_key = "|".join(participants)
        rows["conversations"].append({"id": c["id"], "type": c.get("type", "student_teacher"), "class_id": c.get("classId"), "scope_key": c.get("classId") or "", "created_by": c.get("createdBy") or (participants[0] if participants else ""), "pair_key": pair_key, "created_at": _dt(c.get("createdAt"))})
        for uid in participants: rows["conversation_participants"].append({"conversation_id": c["id"], "user_id": uid})
    for m in stores["messages"]:
        rows["messages"].append({"id": m["id"], "conversation_id": m.get("conversationId"), "sender_id": m.get("senderId"), "content": m.get("content", ""), "created_at": _dt(m.get("createdAt"))})
        for uid in m.get("readBy", []): rows["message_reads"].append({"message_id": m["id"], "user_id": uid, "read_at": None})
    for n in stores["notifications"]:
        rows["notifications"].append({"id": n["id"], "recipient_user_id": n.get("recipient_user_id"), "event_key": n.get("event_key") or n["id"], "type": n.get("type", "info"), "title": n.get("title", ""), "message": n.get("message", ""), "related_entity_type": n.get("related_entity_type"), "related_entity_id": n.get("related_entity_id"), "severity": n.get("severity", "info"), "is_read": bool(n.get("read", False)), "created_at": _dt(n.get("created_at"))})
    for s in stores["ai_sessions"]:
        rows["ai_sessions"].append({"id": s["id"], "student_id": s.get("student_id"), "mode": s.get("mode", "conversation"), "cefr_level": s.get("cefr_level"), "status": s.get("status", "active"), "created_at": _dt(s.get("created_at")), "updated_at": _dt(s.get("updated_at")), "completed_at": _dt(s.get("completed_at"))})
    for m in stores["ai_messages"]:
        structured = {k: m.get(k) for k in ("grammar_feedback", "vocabulary_feedback", "clarity_feedback", "relevance_feedback") if k in m}
        rows["ai_messages"].append({"id": m["id"], "session_id": m.get("session_id"), "student_id": m.get("student_id"), "role": m.get("role", "user"), "content": m.get("content", ""), "feedback": m.get("feedback"), "score": m.get("score"), "corrections": m.get("corrections"), "next_step": m.get("next_step"), "structured_feedback": structured, "xp_awarded": int(m.get("xp_awarded", 0)), "created_at": _dt(m.get("created_at"))})
    for event in stores["ai_usage"]:
        rows["ai_usage_events"].append({"student_id": event.get("student_id"), "created_at": _dt(event.get("created_at"))})
    _validate_planned_rows(rows)
    return rows


def _validate_planned_rows(rows: dict[str, list[dict[str, Any]]]) -> None:
    """Fail before connection on unknown required values, keys, or references."""
    from sqlalchemy import DateTime, Integer, String, UniqueConstraint
    from db.base import Base
    from db import models  # noqa: F401
    for name, table in Base.metadata.tables.items():
        for constraint in [table.primary_key, *(c for c in table.constraints if isinstance(c, UniqueConstraint))]:
            keys = [tuple(row.get(col.name) for col in constraint.columns) for row in rows[name]]
            keys = [key for key in keys if all(value is not None for value in key)]
            if len(keys) != len(set(keys)):
                raise ImportValidationError(f"Duplicate planned keys in {name}")
        for row in rows[name]:
            for col in table.columns:
                value = row.get(col.name)
                if value is None:
                    if not col.nullable and not (col.autoincrement is True and col.name not in row):
                        raise ImportValidationError(f"Unknown required historical value: {name}.{col.name}")
                elif isinstance(col.type, DateTime):
                    _dt(value)
                elif isinstance(col.type, String) and (not isinstance(value, str) or '\x00' in value or (col.type.length and len(value) > col.type.length)):
                    raise ImportValidationError(f"Invalid planned text: {name}.{col.name}")
                elif isinstance(col.type, Integer) and (type(value) is not int or not -(2**31) <= value < 2**31):
                    raise ImportValidationError(f"Invalid planned integer: {name}.{col.name}")
            for constraint in table.foreign_key_constraints:
                key = tuple(row.get(e.parent.name) for e in constraint.elements)
                if any(value is None for value in key):
                    continue
                target = constraint.elements[0].column.table.name
                if key not in {tuple(r.get(e.column.name) for e in constraint.elements) for r in rows[target]}:
                    raise ImportValidationError(f"Unresolved planned relationship in {name}")


def _safe_summary(counts: dict[str, int], *, mode: str) -> str:
    lines = [f"Mode: {mode}", "Source validation: passed", "Record counts:"]
    lines.extend(f"  {name}: {count}" for name, count in sorted(counts.items()))
    lines.append("Sensitive row contents: not displayed")
    return "\n".join(lines)


def _write_safe_audit_report(path: Path, source: Path, events: list[dict[str, Any]], *, mode: str) -> None:
    """Write a non-PII anomaly record to a caller-designated protected location."""
    resolved = path.resolve()
    source_root = source.resolve()
    if resolved == source_root or source_root in resolved.parents:
        raise ImportValidationError("Audit report must be outside the source data directory")
    report = {
        "format_version": 1,
        "mode": mode,
        "status": "not_started" if mode == "apply" else "dry_run_validated_no_database_writes",
        "anomalies": events,
        "personal_data_included": False,
    }
    try:
        with resolved.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except FileExistsError as exc:
        raise ImportValidationError("Audit report already exists; refusing to overwrite it") from exc
    except OSError as exc:
        raise ImportValidationError("Could not create the protected audit report") from exc


def _set_audit_status(path: Path | None, status: str) -> None:
    """Durably replace only report metadata; never store database exceptions."""
    if path is None:
        return
    import tempfile
    report = json.loads(path.read_text(encoding="utf-8"))
    report["status"] = status
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


async def _apply_import(
    stores: dict[str, list[dict[str, Any]]], target_url: str, *,
    approved_legacy_created_at_ids: frozenset[str] = frozenset(),
    audit_report: Path | None = None,
) -> None:
    """Atomically insert validated rows into a migrated, empty staging schema."""
    from sqlalchemy import insert
    from sqlalchemy.ext.asyncio import create_async_engine
    from db.base import Base
    from db import models  # noqa: F401

    if target_url.startswith("postgres://"):
        target_url = "postgresql+asyncpg://" + target_url.removeprefix("postgres://")
    elif target_url.startswith("postgresql://"):
        target_url = "postgresql+asyncpg://" + target_url.removeprefix("postgresql://")
    validate_source(stores)
    transformed = _rows_for_tables(stores, approved_legacy_created_at_ids=approved_legacy_created_at_ids)
    engine = create_async_engine(target_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            transaction = await conn.begin()
            try:
                _set_audit_status(audit_report, "in_progress_outcome_not_confirmed")
                from sqlalchemy import inspect
                has_version_table = await conn.run_sync(lambda sync_conn: inspect(sync_conn).has_table("alembic_version"))
                if not has_version_table:
                    raise ImportValidationError("Target schema is missing; run reviewed Alembic migrations first")
                version = await conn.exec_driver_sql("SELECT version_num FROM alembic_version")
                if version.scalar_one_or_none() != EXPECTED_REVISION:
                    raise ImportValidationError("Target schema version is not the expected importer revision")
                if conn.dialect.name == "postgresql":
                    await conn.exec_driver_sql("LOCK TABLE " + ", ".join('"' + name + '"' for name in sorted(APP_TABLES)) + " IN EXCLUSIVE MODE")
                existing = await conn.run_sync(lambda sync_conn: _application_table_counts(sync_conn, Base.metadata))
                if any(existing.values()):
                    raise ImportValidationError("Target contains application rows; importer refuses to continue")
                for table in Base.metadata.sorted_tables:
                    table_rows = transformed.get(table.name, [])
                    if table_rows:
                        await conn.execute(insert(table), table_rows)
                if conn.dialect.name == "postgresql":
                    await conn.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
                actual = await conn.run_sync(lambda sync_conn: _application_table_counts(sync_conn, Base.metadata))
                if actual != {name: len(values) for name, values in transformed.items()}:
                    raise ImportValidationError("Pre-commit row reconciliation failed")
                _set_audit_status(audit_report, "commit_pending_outcome_unknown")
            except BaseException:
                try:
                    await transaction.rollback()
                except BaseException:
                    _set_audit_status(audit_report, "rollback_unconfirmed")
                    raise
                _set_audit_status(audit_report, "rolled_back")
                raise
            try:
                await transaction.commit()
            except BaseException:
                # A lost COMMIT response cannot safely be labelled rollback.
                _set_audit_status(audit_report, "commit_outcome_unknown_verify_target")
                raise
            _set_audit_status(audit_report, "committed")
    finally:
        await engine.dispose()


def _application_table_counts(connection, metadata) -> dict[str, int]:
    from sqlalchemy import func, select
    return {table.name: connection.execute(select(func.count()).select_from(table)).scalar_one() for table in metadata.sorted_tables if table.name != "alembic_version"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Explicit backend data directory; QA disposable paths are rejected")
    parser.add_argument("--apply", action="store_true", help="Request import execution (requires guarded target and explicit confirmation)")
    parser.add_argument("--confirm-target", help="Must exactly match the target host and database name for --apply")
    parser.add_argument("--allow-legacy-unknown-created-at", action="append", default=[], metavar="RECORD_ID", help="Explicitly approve the exact known legacy unknown timestamp record")
    parser.add_argument("--audit-report", type=Path, help="Create a new, non-PII anomaly audit report at a protected path outside the source directory")
    args = parser.parse_args(argv)
    try:
        stores = load_source(args.source)
        counts = validate_source(stores)
        mode = "dry-run" if not args.apply else "apply"
        print(_safe_summary(counts, mode=mode))
        audit_events: list[dict[str, Any]] = []
        approvals = frozenset(args.allow_legacy_unknown_created_at)
        try:
            planned = _rows_for_tables(stores, approved_legacy_created_at_ids=approvals, audit_events=audit_events)
        except ImportValidationError:
            print("Field transformation validation: failed. No target connection opened and no data written.")
            return 2
        print("Field transformation validation: passed")
        print("Planned application rows:")
        for name, values in sorted(planned.items()):
            print(f"  {name}: {len(values)}")
        if audit_events or args.apply or args.audit_report:
            if not args.audit_report:
                raise ImportValidationError("An explicit --audit-report path is required for an approved legacy anomaly")
            _write_safe_audit_report(args.audit_report, args.source, audit_events, mode=mode)
            print("Legacy timestamp anomaly: explicitly approved and summarized in the audit report; personal data omitted.")
        if args.apply:
            target_url = importer_target_url()
            actual_identity = importer_target_identity(target_url)
            if not args.confirm_target or args.confirm_target != actual_identity:
                raise ImportValidationError("--confirm-target must exactly match the explicitly configured target host and database name")
            asyncio.run(_apply_import(stores, target_url, approved_legacy_created_at_ids=approvals, audit_report=args.audit_report))
        else:
            print("No target connection opened and no data written.")
        return 0
    except (DatabaseConfigurationError, ImportValidationError) as exc:
        print(f"Import stopped safely: {exc}")
        return 2
    except Exception:
        # Driver errors can include DSNs or query parameters. Keep all details out of stdout.
        print("Import stopped safely: preflight or database operation failed; diagnostic details were suppressed")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
