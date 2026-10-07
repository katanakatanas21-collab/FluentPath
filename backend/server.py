from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
import asyncio
from urllib.parse import urlparse
import hashlib
import logging
import os
import re
import secrets
# Imported so the store-write retry regression tests can neutralize the retry backoff.
import time  # noqa: F401
from typing import Literal, Optional
import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
import ai_teacher
import zoom_service
import persistence
from persistence import DataStoreError
from persistence.json_files import (
    STORE_REPLACE_ATTEMPTS,
    STORE_REPLACE_BACKOFF_SECONDS,
    TRANSIENT_STORE_REPLACE_ERRNOS,
    TRANSIENT_STORE_REPLACE_WINERRORS,
    read_json_list as _read_json_list,
    write_json_list as _write_json_list,
)


logging.basicConfig(
    level=os.getenv("FLUENT_PATH_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("fluentpath.api")

#: Request fields that are safe to record. Bodies, query strings, cookies and
#: authorization headers are excluded on purpose: they carry passwords, tokens
#: and personal data.
LOGGABLE_REQUEST_FIELDS = ("method", "path")


def request_log_context(request) -> dict:
    """Return the non-sensitive request fields worth logging.

    Built as an allowlist rather than by filtering a dict, so a new header or
    attribute cannot leak by default.
    """
    return {
        "fluentpath_method": getattr(request, "method", None),
        "fluentpath_path": getattr(getattr(request, "url", None), "path", None),
    }


async def log_request_failures(request, call_next):
    """Log unhandled exceptions and 5xx responses, then behave normally.

    The request itself is not logged on success, so request volume stays out of
    the log and no payload can leak through it.
    """
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled server error.", extra=request_log_context(request))
        raise

    if response.status_code >= 500:
        logger.error(
            "Server error response.",
            extra={
                **request_log_context(request),
                "fluentpath_status": response.status_code,
            },
        )
    return response


app = FastAPI(title="FluentPath API")
app.middleware("http")(log_request_failures)

APP_ENVIRONMENT = os.getenv("FLUENT_PATH_ENVIRONMENT", "development").lower()


@app.exception_handler(DataStoreError)
async def handle_data_store_error(request, error):
    return JSONResponse(status_code=503, content={"detail": "DATA_STORE_UNAVAILABLE"})

DEVELOPMENT_CORS_ORIGIN_DEFAULTS = "http://localhost:3000,http://127.0.0.1:3000"
LOOPBACK_CORS_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


def resolve_allowed_frontend_origins(environment, configured):
    """Resolve the CORS allowlist, refusing to guess outside development.

    Development keeps the localhost defaults so the local workflow needs no
    configuration. Every other environment has to name its own origins: an
    unset, empty, wildcard, loopback, or malformed value is a silent way to end
    up serving a browser-facing deployment from the wrong trust boundary, so
    this refuses to start rather than fall back.
    """
    origins = [
        origin.strip()
        for origin in (configured or "").split(",")
        if origin.strip()
    ]

    if environment == "development":
        return origins or [origin.strip() for origin in DEVELOPMENT_CORS_ORIGIN_DEFAULTS.split(",")]

    if not origins:
        raise RuntimeError(
            f"{environment} requires an explicit FLUENT_PATH_CORS_ORIGINS allowlist. "
            "No production or staging domain is hard-coded in this project; the "
            "deployment owner must supply the real frontend origins at deploy time."
        )

    for origin in origins:
        if origin == "*":
            raise RuntimeError(
                f"{environment} must not use a wildcard CORS allowlist. "
                "Name the exact frontend origins instead."
            )

        parsed = urlparse(origin)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise RuntimeError(
                f"{environment} requires FLUENT_PATH_CORS_ORIGINS entries to be "
                f"absolute origins such as https://your-frontend.example. "
                f'Received "{origin}".'
            )

        if (parsed.hostname or "").lower() in LOOPBACK_CORS_HOSTNAMES:
            raise RuntimeError(
                f"{environment} must not allow loopback CORS origins. "
                f'Received "{origin}".'
            )

    return origins


allowed_frontend_origins = resolve_allowed_frontend_origins(
    APP_ENVIRONMENT,
    os.getenv("FLUENT_PATH_CORS_ORIGINS"),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(exist_ok=True)

STUDENTS_FILE = DATA_DIR / "students.json"
COURSES_FILE = DATA_DIR / "courses.json"
HOMEWORK_FILE = DATA_DIR / "homework.json"
SUBMISSIONS_FILE = DATA_DIR / "submissions.json"
CLASSES_FILE = DATA_DIR / "classes.json"
COMMUNITY_POSTS_FILE = DATA_DIR / "community_posts.json"
COMMUNITY_REPLIES_FILE = DATA_DIR / "community_replies.json"
CONVERSATIONS_FILE = DATA_DIR / "conversations.json"
MESSAGES_FILE = DATA_DIR / "messages.json"
REPORTS_FILE = DATA_DIR / "reports.json"
NOTIFICATIONS_FILE = DATA_DIR / "notifications.json"
AI_SESSIONS_FILE = DATA_DIR / "ai_sessions.json"
AI_MESSAGES_FILE = DATA_DIR / "ai_messages.json"
AI_USAGE_FILE = DATA_DIR / "ai_usage.json"

_STORE_PATH_ATTRIBUTES = {
    "students": "STUDENTS_FILE",
    "courses": "COURSES_FILE",
    "homework": "HOMEWORK_FILE",
    "submissions": "SUBMISSIONS_FILE",
    "classes": "CLASSES_FILE",
    "community_posts": "COMMUNITY_POSTS_FILE",
    "community_replies": "COMMUNITY_REPLIES_FILE",
    "conversations": "CONVERSATIONS_FILE",
    "messages": "MESSAGES_FILE",
    "reports": "REPORTS_FILE",
    "notifications": "NOTIFICATIONS_FILE",
    "ai_sessions": "AI_SESSIONS_FILE",
    "ai_messages": "AI_MESSAGES_FILE",
    "ai_usage": "AI_USAGE_FILE",
}


def resolve_store_path(store_name):
    """Resolve a store path from its current module value.

    Reading the attribute on every call keeps a repointed module path in effect,
    which is what the automated suite does to isolate each test's data.
    """
    attribute = _STORE_PATH_ATTRIBUTES.get(store_name)
    return None if attribute is None else globals().get(attribute)


persistence.configure_from_environment(path_resolver=resolve_store_path)

CEFR_RANKS = {
    "A0": 0,
    "A1": 1,
    "A2": 2,
    "B1": 3,
    "B2": 4,
    "C1": 5,
    "C1+": 6,
}
PLACEMENT_ANSWER_KEY = (1, 1, 2, 2, 0)
COURSE_LEVEL_RANKS = {
    "A0 → A1": CEFR_RANKS["A1"],
    "A1 → A2": CEFR_RANKS["A2"],
    "A2 → B1": CEFR_RANKS["B1"],
    "B1 → B2": CEFR_RANKS["B2"],
    "B2 → C1": CEFR_RANKS["C1"],
    "C1+": CEFR_RANKS["C1+"],
}
XP_REWARDS = {
    "lesson_completed": 20,
    "homework_submitted": 15,
    "homework_graded": 20,
    "class_attended": 25,
    "placement_test_completed": 50,
    "ai_practice_completed": 10,
}
XP_LEVEL_THRESHOLDS = ((1, 0), (2, 100), (3, 250), (4, 500), (5, 1000))
BADGE_DEFINITIONS = (
    {"id": "first_lesson", "title": "First Lesson", "titleAr": "الدرس الأول", "description": "Complete your first lesson.", "descriptionAr": "أكمل درسك الأول.", "icon": "◈"},
    {"id": "first_homework", "title": "First Homework", "titleAr": "الواجب الأول", "description": "Submit your first homework.", "descriptionAr": "أرسل واجبك الأول.", "icon": "✓"},
    {"id": "first_class", "title": "First Class", "titleAr": "الحصة الأولى", "description": "Attend your first class.", "descriptionAr": "احضر حصتك الأولى.", "icon": "◷"},
    {"id": "streak_7", "title": "7 Day Streak", "titleAr": "سلسلة ٧ أيام", "description": "Learn on seven consecutive days.", "descriptionAr": "تعلّم سبعة أيام متتالية.", "icon": "✦"},
    {"id": "xp_100", "title": "100 XP", "titleAr": "١٠٠ نقطة خبرة", "description": "Earn 100 XP.", "descriptionAr": "اجمع ١٠٠ نقطة خبرة.", "icon": "★"},
    {"id": "xp_500", "title": "500 XP", "titleAr": "٥٠٠ نقطة خبرة", "description": "Earn 500 XP.", "descriptionAr": "اجمع ٥٠٠ نقطة خبرة.", "icon": "🏆"},
    {"id": "course_starter", "title": "Course Starter", "titleAr": "بداية الدورة", "description": "Complete your first course lesson.", "descriptionAr": "أكمل أول درس في دورة.", "icon": "➜"},
    {"id": "course_finisher", "title": "Course Finisher", "titleAr": "إنهاء الدورة", "description": "Complete all lessons in a course.", "descriptionAr": "أكمل جميع دروس إحدى الدورات.", "icon": "◆"},
)
DEVELOPMENT_JWT_SECRET_FALLBACK = "fluent-path-development-secret-change-me"
MINIMUM_JWT_SECRET_LENGTH = 32
JWT_SECRET = os.getenv(
    "FLUENT_PATH_JWT_SECRET",
    DEVELOPMENT_JWT_SECRET_FALLBACK,
)
if APP_ENVIRONMENT != "development" and (
    JWT_SECRET == DEVELOPMENT_JWT_SECRET_FALLBACK
    or len(JWT_SECRET) < MINIMUM_JWT_SECRET_LENGTH
):
    raise RuntimeError(
        f"{APP_ENVIRONMENT} requires a strong FLUENT_PATH_JWT_SECRET "
        f"of at least {MINIMUM_JWT_SECRET_LENGTH} characters"
    )
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 60
bearer_scheme = HTTPBearer(auto_error=False)
REVOKED_TOKENS = set()


class StudentRegister(BaseModel):
    fullName: str
    email: str
    password: str
    dateOfBirth: str
    phone: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


class HomeworkCreate(BaseModel):
    title: str
    description: str
    courseId: Optional[str] = None
    level: Optional[str] = None
    studentIds: list[str] = Field(default_factory=list)
    dueDate: Optional[str] = None


class HomeworkSubmissionCreate(BaseModel):
    answer: str


class HomeworkGrade(BaseModel):
    grade: Optional[float] = Field(default=None, ge=0, le=100)
    teacherFeedback: str = ""


class ClassInput(BaseModel):
    title: str
    description: str = ""
    courseId: Optional[str] = None
    level: Optional[str] = None
    studentIds: list[str] = Field(default_factory=list)
    date: str
    startTime: str
    endTime: str
    startsAt: Optional[str] = None
    meetingProvider: str = "none"
    meetingUrl: Optional[str] = None
    teacherJoinUrl: Optional[str] = None
    studentJoinUrl: Optional[str] = None


class CommunityPostCreate(BaseModel):
    title: str
    content: str
    scope: Literal["general", "course", "class"] = "general"
    courseId: Optional[str] = None
    classId: Optional[str] = None


class CommunityPostUpdate(BaseModel):
    title: str
    content: str


class CommunityReplyCreate(BaseModel):
    content: str


class CommunityReportCreate(BaseModel):
    reason: str


class CommunityReportResolve(BaseModel):
    action: Literal["dismiss", "hide", "restore"]


class CommunityModeration(BaseModel):
    action: Literal["hide", "restore"]


class ConversationCreate(BaseModel):
    classId: Optional[str] = None
    studentId: Optional[str] = None
    staffUserId: Optional[str] = None


class MessageCreate(BaseModel):
    content: str


class TestResult(BaseModel):
    studentId: Optional[str] = None
    answers: list[int] = Field(min_length=5, max_length=5)

    class Config:
        extra = "forbid"


class AdminCourseInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    titleAr: str = Field(default="", max_length=160)
    description: str = Field(default="", max_length=2000)
    descriptionAr: str = Field(default="", max_length=2000)
    level: str = "A0 → A1"
    order: Optional[int] = Field(default=None, ge=0, le=10000)


class AdminCourseStatus(BaseModel):
    active: bool


class LessonContent(BaseModel):
    introduction: str = Field(default="", max_length=5000)
    explanation: str = Field(default="", max_length=12000)
    examples: str = Field(default="", max_length=10000)
    vocabulary: str = Field(default="", max_length=10000)
    grammar_notes: str = Field(default="", max_length=10000)
    practice_instructions: str = Field(default="", max_length=8000)


class AdminLessonInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    titleAr: str = Field(default="", max_length=160)
    description: str = Field(default="", max_length=2000)
    descriptionAr: str = Field(default="", max_length=2000)
    content: LessonContent = Field(default_factory=LessonContent)
    estimated_minutes: int = Field(default=15, ge=1, le=480)


class AdminLessonStatus(BaseModel):
    published: Optional[bool] = None
    archived: Optional[bool] = None


class LessonReorder(BaseModel):
    lesson_ids: list[str]


class AISessionCreate(BaseModel):
    mode: Literal["conversation", "grammar", "vocabulary", "writing", "speaking"]


class AIMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=1500)


def load_students():
    students = read_store("students")
    for student in students:
        student.setdefault("role", "student")
        student.setdefault("courseProgress", {})
    return students


def save_students(students):
    write_store("students", students)


def ensure_gamification(student):
    state = student.get("gamification")
    if not isinstance(state, dict):
        state = {}
        student["gamification"] = state
    state.setdefault("xp", 0)
    state.setdefault("currentStreak", 0)
    state.setdefault("longestStreak", 0)
    state.setdefault("lastActivityDate", None)
    state.setdefault("earnedBadges", [])
    state.setdefault("awardedActions", [])
    return state


def xp_level_progress(xp):
    xp = max(0, int(xp or 0))
    current_index = max(
        index for index, (_, threshold) in enumerate(XP_LEVEL_THRESHOLDS)
        if xp >= threshold
    )
    level, start_xp = XP_LEVEL_THRESHOLDS[current_index]
    next_level = XP_LEVEL_THRESHOLDS[current_index + 1] if current_index + 1 < len(XP_LEVEL_THRESHOLDS) else None
    if next_level is None:
        return {
            "level": level, "currentLevelXp": start_xp, "nextLevelXp": None,
            "xpIntoLevel": xp - start_xp, "xpToNextLevel": 0, "progressPercent": 100,
        }
    next_level_number, next_xp = next_level
    span = next_xp - start_xp
    into_level = xp - start_xp
    return {
        "level": level, "currentLevelXp": start_xp, "nextLevel": next_level_number,
        "nextLevelXp": next_xp, "xpIntoLevel": into_level,
        "xpToNextLevel": next_xp - xp,
        "progressPercent": min(100, round(into_level * 100 / span)),
    }


def record_learning_day(state, activity_date=None):
    today = activity_date or datetime.now(timezone.utc).date()
    if isinstance(today, datetime):
        today = today.date()
    elif isinstance(today, str):
        today = date.fromisoformat(today[:10])
    today_text = today.isoformat()
    last_text = state.get("lastActivityDate")
    if last_text == today_text:
        return
    if last_text:
        try:
            days_since_last = (today - date.fromisoformat(last_text[:10])).days
        except (TypeError, ValueError):
            days_since_last = 0
    else:
        days_since_last = 0
    if not last_text or days_since_last != 1:
        state["currentStreak"] = 1
    else:
        state["currentStreak"] = int(state.get("currentStreak", 0)) + 1
    state["longestStreak"] = max(int(state.get("longestStreak", 0)), int(state["currentStreak"]))
    state["lastActivityDate"] = today_text


def refresh_student_badges(student, earned_at=None):
    state = ensure_gamification(student)
    earned = {item.get("id") for item in state["earnedBadges"] if isinstance(item, dict)}
    action_keys = set(state["awardedActions"])
    completed_courses = student.get("courseProgress", {})
    has_lesson = any(progress.get("completedLessons") for progress in completed_courses.values())
    has_finished_course = any(
        (course_progress := completed_courses.get(course.get("id"), {})).get("completedLessons")
        and len([lesson for lesson in course.get("lessons", []) if lesson_is_student_visible(lesson)]) > 0
        and all(lesson.get("id") in course_progress.get("completedLessons", []) for lesson in course.get("lessons", []) if lesson_is_student_visible(lesson))
        for course in load_courses() if course.get("type") == "cefr"
    )
    xp = int(state["xp"])
    eligible = {
        "first_lesson": has_lesson,
        "first_homework": any(key.startswith("homework_submitted:") for key in action_keys),
        "first_class": any(key.startswith("class_attended:") for key in action_keys),
        "streak_7": int(state["currentStreak"]) >= 7,
        "xp_100": xp >= 100,
        "xp_500": xp >= 500,
        "course_starter": has_lesson,
        "course_finisher": has_finished_course,
    }
    timestamp = earned_at or datetime.now(timezone.utc).isoformat()
    for definition in BADGE_DEFINITIONS:
        badge_id = definition["id"]
        if eligible.get(badge_id) and badge_id not in earned:
            state["earnedBadges"].append({"id": badge_id, "earnedAt": timestamp})


def award_learning_action(student, action_key, reward_key, course_id=None, activity_date=None):
    """Apply a fixed server-defined reward once for a trusted backend action."""
    reward = XP_REWARDS.get(reward_key)
    if reward is None:
        return False
    state = ensure_gamification(student)
    if action_key in state["awardedActions"]:
        return False
    previous_xp = int(state["xp"])
    previous_level = xp_level_progress(previous_xp)["level"]
    previous_badges = [item.get("id") for item in state.get("earnedBadges", []) if isinstance(item, dict)]
    state["awardedActions"].append(action_key)
    state["xp"] = int(state["xp"]) + reward
    record_learning_day(state, activity_date)
    refresh_student_badges(student)
    create_learning_notifications(student, previous_xp, previous_badges, previous_level)
    return True


def award_gamification_to_student(student_id, action_key, reward_key, course_id=None):
    students = load_students()
    student = next((item for item in students if item.get("id") == student_id), None)
    if student is None or student.get("role", "student") != "student":
        return False
    if not award_learning_action(student, action_key, reward_key, course_id=course_id):
        return False
    save_students(students)
    return True


def gamification_summary(student):
    state = ensure_gamification(student)
    earned_by_id = {item.get("id"): item.get("earnedAt") for item in state["earnedBadges"] if isinstance(item, dict)}
    recent = [
        {**definition, "earnedAt": earned_by_id[definition["id"]]}
        for definition in BADGE_DEFINITIONS if definition["id"] in earned_by_id
    ]
    recent.sort(key=lambda item: item.get("earnedAt") or "", reverse=True)
    return {
        "xp": int(state["xp"]),
        "level": xp_level_progress(state["xp"])["level"],
        "levelProgress": xp_level_progress(state["xp"]),
        "currentStreak": int(state["currentStreak"]),
        "longestStreak": int(state["longestStreak"]),
        "lastActivityDate": state.get("lastActivityDate"),
        "recentAchievements": recent[:5],
    }


def load_courses():
    return read_store("courses")


def read_store(store_name, path=None):
    """Read a whole logical store through the configured persistence backend."""
    return persistence.read_store(store_name, path=path)


def write_store(store_name, records, path=None):
    """Replace a whole logical store through the configured persistence backend."""
    return persistence.write_store(store_name, records, path=path)


def _resolve_store_name(file_path):
    """Resolve a product store path, refusing to fall back to a file on PostgreSQL.

    ``load_json_list``/``save_json_list`` exist so the JSON backend can serve
    store files directly. A PostgreSQL runtime has no file to serve, so an
    unresolved path there is a routing bug rather than scratch data, and it must
    fail closed. Silently writing a local JSON file would split the data in two
    and lose writes on restart, which is exactly the defect this guards.
    """
    store_name = persistence.store_name_for_path(file_path)
    if store_name is not None:
        return store_name
    if persistence.active_backend_name() != persistence.JSON_BACKEND:
        raise DataStoreError("Persistent storage is unavailable.")
    return None


def load_json_list(file_path):
    """Read a store through the configured backend, or a plain JSON file.

    Non-store paths exist for scratch data only, and only on the JSON backend.
    The API never persists product data outside the configured backend.
    """
    store_name = _resolve_store_name(file_path)
    if store_name is not None:
        return read_store(store_name, file_path)
    return _read_json_list(file_path)


def save_json_list(file_path, records):
    store_name = _resolve_store_name(file_path)
    if store_name is not None:
        write_store(store_name, records, file_path)
        return
    _write_json_list(file_path, records)


def load_homework():
    return read_store("homework")


def load_submissions():
    return read_store("submissions")


def load_classes():
    return read_store("classes")


def load_notifications():
    """Read notifications through the configured backend, never a JSON file."""
    return read_store("notifications")


def save_notifications(records):
    """Replace notifications through the configured backend, never a JSON file."""
    return write_store("notifications", records)


def create_notification(recipient_id, event_key, notification_type, title, message, related_type=None, related_id=None, severity="info"):
    """Persist one server-generated in-app notification per trusted event."""
    if not recipient_id or not event_key:
        return False
    records = load_notifications()
    if any(item.get("recipient_user_id") == recipient_id and item.get("event_key") == event_key for item in records):
        return False
    records.append({
        "id": secrets.token_hex(8), "recipient_user_id": recipient_id,
        "event_key": event_key, "type": notification_type, "title": title,
        "message": message, "read": False, "created_at": datetime.now(timezone.utc).isoformat(),
"related_entity_type": related_type, "related_entity_id": related_id, "severity": severity,
    })
    save_notifications(records)
    return True


def maybe_create_class_reminder(class_record, recipient_id):
    item = normalize_class(class_record)
    if item.get("status") == "cancelled" or not item.get("startsAt"):
        return
    try:
        starts_at = datetime.fromisoformat(item["startsAt"].replace("Z", "+00:00"))
        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=timezone.utc)
    except ValueError:
        return
    now = datetime.now(timezone.utc)
    if timedelta(0) <= starts_at - now <= timedelta(hours=24):
        create_notification(recipient_id, f"class_reminder:{item['id']}", "upcoming_class_reminder", "Upcoming class", f"{item.get('title', 'Your class')} starts within 24 hours.", "class", item["id"])


def create_learning_notifications(student, previous_xp=None, previous_badges=None, previous_level=None):
    state = ensure_gamification(student)
    xp = int(state["xp"])
    level = xp_level_progress(xp)["level"]
    old_xp = xp if previous_xp is None else int(previous_xp)
    if previous_level is not None and level > previous_level:
        create_notification(student["id"], f"level:{level}", "level_up", "Level up!", f"You reached level {level}.", "achievement", str(level))
    old_badges = set(previous_badges or [])
    for badge in state.get("earnedBadges", []):
        badge_id = badge.get("id")
        if badge_id and badge_id not in old_badges:
            definition = next((item for item in BADGE_DEFINITIONS if item["id"] == badge_id), None)
            if definition:
                create_notification(student["id"], f"badge:{badge_id}", "achievement_unlocked", "Achievement unlocked", definition["title"], "achievement", badge_id)
                for class_record in load_classes():
                    class_item = normalize_class(class_record)
                    if class_item.get("status") != "cancelled" and class_is_assigned_to_student(class_record, student):
                        create_notification(class_item.get("teacherId"), f"student_achievement:{student['id']}:{badge_id}", "student_achievement", "Student achievement milestone", f"{student.get('fullName', 'A student')} earned {definition['title']}.", "student", student["id"])
    if int(state.get("currentStreak", 0)) in (3, 7, 14, 30) and state.get("lastActivityDate"):
        create_notification(student["id"], f"streak:{state['lastActivityDate']}:{state['currentStreak']}", "streak_milestone", "Streak milestone", f"You reached a {state['currentStreak']}-day learning streak.", "streak", str(state["currentStreak"]))


def normalize_class(class_record):
    class_item = dict(class_record)
    starts_at = class_item.get("startsAt") or class_item.get("dateTime")
    start_datetime = None
    if starts_at:
        try:
            start_datetime = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
        except ValueError:
            start_datetime = None
    if start_datetime:
        class_item.setdefault("date", start_datetime.date().isoformat())
        class_item.setdefault("startTime", start_datetime.strftime("%H:%M"))
    if not class_item.get("endTime") and class_item.get("startTime"):
        try:
            start_time = datetime.strptime(class_item["startTime"], "%H:%M")
            end_time = start_time + timedelta(minutes=int(class_item.get("durationMinutes", 0)))
            class_item["endTime"] = end_time.strftime("%H:%M")
        except (ValueError, TypeError):
            class_item["endTime"] = class_item["startTime"]
    class_item["teacherId"] = class_item.get("teacherId") or class_item.get("teacher_id")
    class_item["assignedStudentIds"] = class_item.get("assignedStudentIds") or class_item.get("studentIds") or []
    class_item.setdefault("description", "")
    class_item.setdefault("level", None)
    class_item.setdefault("meetingProvider", "none")
    class_item["meetingUrl"] = safe_stored_meeting_url(class_item.get("meetingUrl"))
    class_item["teacherJoinUrl"] = safe_stored_meeting_url(class_item.get("teacherJoinUrl") or class_item.get("meetingUrl"))
    class_item["studentJoinUrl"] = safe_stored_meeting_url(class_item.get("studentJoinUrl") or class_item.get("meetingUrl"))
    class_item.setdefault("createdAt", None)
    class_item.setdefault("status", "scheduled")
    if start_datetime and class_item.get("durationMinutes") is not None:
        class_item.setdefault(
            "endTime",
            (start_datetime + timedelta(minutes=int(class_item["durationMinutes"]))).strftime("%H:%M"),
        )
    elif class_item.get("date") and class_item.get("startTime") and class_item.get("endTime"):
        class_item.setdefault(
            "startsAt",
            f"{class_item['date']}T{class_item['startTime']}:00",
        )
    if class_item.get("startTime") and class_item.get("endTime"):
        try:
            start_time = datetime.strptime(class_item["startTime"], "%H:%M")
            end_time = datetime.strptime(class_item["endTime"], "%H:%M")
            class_item["durationMinutes"] = int((end_time - start_time).total_seconds() / 60)
        except ValueError:
            pass
    return class_item


def class_is_assigned_to_student(class_record, student):
    class_item = normalize_class(class_record)
    if student.get("role", "student") != "student":
        return False
    if class_item["assignedStudentIds"]:
        return student["id"] in class_item["assignedStudentIds"]
    if class_item.get("level"):
        required_rank = CEFR_RANKS.get(class_item["level"].upper())
        if required_rank is None or student_level_rank(student) < required_rank:
            return False
    if class_item.get("courseId"):
        course = next((item for item in load_courses() if item["id"] == class_item["courseId"]), None)
        return bool(course and (course["type"] != "cefr" or course_is_available(course, student)))
    return bool(class_item.get("level"))


def class_time_state(class_record):
    class_item = normalize_class(class_record)
    starts_at = class_item.get("startsAt")
    if not starts_at:
        return "upcoming"
    try:
        start_datetime = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
    except ValueError:
        return "upcoming"
    if start_datetime.tzinfo is None:
        start_datetime = start_datetime.replace(tzinfo=timezone.utc)
    end_datetime = start_datetime + timedelta(minutes=int(class_item.get("durationMinutes", 0)))
    return "past" if end_datetime <= datetime.now(timezone.utc) else "upcoming"


def valid_meeting_url(url):
    if not url:
        return None
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise HTTPException(status_code=400, detail="رابط الاجتماع يجب أن يبدأ بـ https://")
    return url.strip()


def safe_stored_meeting_url(url):
    if not url:
        return None
    parsed = urlparse(url.strip())
    return url.strip() if parsed.scheme == "https" and parsed.netloc else None


def student_class_view(class_record):
    class_item = normalize_class(class_record)
    return {
        key: class_item.get(key)
        for key in (
            "id", "teacherId", "courseId", "level", "title", "description",
            "date", "startTime", "endTime", "startsAt",
            "durationMinutes", "meetingProvider", "studentJoinUrl", "meetingUrl",
            "status", "createdAt",
        )
    }


def find_student(student_id):
    return next(
        (student for student in load_students() if student["id"] == student_id),
        None,
    )


def student_level_rank(student):
    if not student or not student.get("level"):
        return -1

    levels = re.findall(r"C1\+|[ABC][0-9]", student["level"].upper())
    return max((CEFR_RANKS.get(level, -1) for level in levels), default=-1)


def course_is_available(course, student):
    return (
        course.get("active", True)
        and course.get("type") == "cefr"
        and student_level_rank(student) >= course.get("requiredRank", 99)
    )


def load_community_posts():
    return read_store("community_posts")


def load_community_replies():
    return read_store("community_replies")


def load_conversations():
    return read_store("conversations")


def load_messages():
    return read_store("messages")


def load_reports():
    return read_store("reports")


def active_classes_for_teacher_student(teacher_id, student, class_id=None):
    matches = []
    for record in load_classes():
        class_item = normalize_class(record)
        if class_item.get("status") == "cancelled" or class_item.get("teacherId") != teacher_id:
            continue
        if class_id and class_item.get("id") != class_id:
            continue
        if class_is_assigned_to_student(record, student):
            matches.append(class_item)
    return matches


def teacher_has_course(teacher_id, course_id):
    return any(
        item.get("status") != "cancelled"
        and normalize_class(item).get("teacherId") == teacher_id
        and normalize_class(item).get("courseId") == course_id
        for item in load_classes()
    )


def can_access_community_area(user, scope, course_id=None, class_id=None):
    role = user.get("role", "student")
    if role == "administrator":
        return True
    if scope == "general":
        return role in ("student", "teacher")
    if scope == "class":
        class_record = next((item for item in load_classes() if item.get("id") == class_id), None)
        if not class_record or normalize_class(class_record).get("status") == "cancelled":
            return False
        class_item = normalize_class(class_record)
        if role == "teacher":
            return class_item.get("teacherId") == user["id"]
        return class_is_assigned_to_student(class_record, user)
    if scope == "course" and course_id:
        course = next((item for item in load_courses() if item["id"] == course_id), None)
        if not course:
            return False
        if role == "teacher":
            return teacher_has_course(user["id"], course_id)
        return course_is_available(course, user)
    return False


def can_access_community_post(user, post):
    return can_access_community_area(
        user,
        post.get("scope", "general"),
        course_id=post.get("courseId"),
        class_id=post.get("classId"),
    )


def public_community_post(post, current_user, replies=None):
    users = {user["id"]: user for user in load_students()}
    author = users.get(post.get("authorId"))
    reply_records = replies if replies is not None else load_community_replies()
    likes = post.get("likesBy", [])
    return {
        "id": post["id"],
        "scope": post.get("scope", "general"),
        "courseId": post.get("courseId"),
        "classId": post.get("classId"),
        "title": post["title"],
        "content": post["content"],
        "author": {"id": author["id"], "fullName": author["fullName"], "role": author.get("role", "student")} if author else None,
        "createdAt": post.get("createdAt"),
        "updatedAt": post.get("updatedAt"),
        "status": post.get("status", "visible"),
        "likeCount": len(likes),
        "likedByMe": current_user["id"] in likes,
        "replyCount": sum(1 for reply in reply_records if reply.get("postId") == post["id"] and reply.get("status", "visible") != "deleted"),
    }


def public_community_reply(reply):
    author = find_student(reply.get("authorId"))
    return {
        "id": reply["id"],
        "postId": reply["postId"],
        "content": reply["content"],
        "author": {"id": author["id"], "fullName": author["fullName"], "role": author.get("role", "student")} if author else None,
        "createdAt": reply.get("createdAt"),
        "updatedAt": reply.get("updatedAt"),
        "status": reply.get("status", "visible"),
    }


def find_accessible_community_post(current_user, post_id, include_hidden=False):
    post = next((item for item in load_community_posts() if item.get("id") == post_id), None)
    if not post or not can_access_community_post(current_user, post):
        raise HTTPException(status_code=404, detail="المنشور غير موجود")
    if post.get("status", "visible") != "visible" and not include_hidden and current_user.get("role") != "administrator":
        raise HTTPException(status_code=404, detail="المنشور غير موجود")
    return post


def user_can_access_conversation(user, conversation):
    return user["id"] in conversation.get("participantIds", [])


def find_conversation(conversation_id, current_user):
    conversation = next((item for item in load_conversations() if item.get("id") == conversation_id), None)
    if not conversation or not user_can_access_conversation(current_user, conversation):
        raise HTTPException(status_code=404, detail="المحادثة غير موجودة")
    return conversation


def public_message(message, users, current_user_id):
    sender = users.get(message.get("senderId"))
    return {
        "id": message["id"],
        "conversationId": message["conversationId"],
        "content": message["content"],
        "sender": {"id": sender["id"], "fullName": sender["fullName"], "role": sender.get("role", "student")} if sender else None,
        "createdAt": message.get("createdAt"),
        "read": (
            any(user_id != message.get("senderId") for user_id in message.get("readBy", []))
            if current_user_id == message.get("senderId")
            else current_user_id in message.get("readBy", [])
        ),
    }


def student_progress(student, course):
    progress = student.get("courseProgress", {}).get(course["id"], {})
    completed_ids = progress.get("completedLessons", [])
    visible_lessons = [lesson for lesson in course.get("lessons", []) if lesson_is_student_visible(lesson)]
    lesson_count = len(visible_lessons)
    completed_count = len(
        [lesson for lesson in visible_lessons if lesson["id"] in completed_ids]
    )
    return {
        "completedLessons": [
            lesson["id"]
            for lesson in visible_lessons
            if lesson["id"] in completed_ids
        ],
        "completedCount": completed_count,
        "totalLessons": lesson_count,
        "percentage": round((completed_count / lesson_count) * 100)
        if lesson_count
        else 0,
        "updatedAt": progress.get("updatedAt"),
    }


def lesson_is_student_visible(lesson):
    # Existing catalog lessons predate the CMS and remain visible by default.
    return lesson.get("published", True) and not lesson.get("archived", False)


def course_is_active(course):
    return course.get("active", course.get("status") != "inactive")


def ordered_lessons(course, include_archived=False):
    lessons = course.get("lessons", [])
    if not include_archived:
        lessons = [lesson for lesson in lessons if not lesson.get("archived", False)]
    return sorted(lessons, key=lambda lesson: (lesson.get("order", lesson.get("number", 0)), lesson.get("id", "")))


def homework_teacher_id(homework):
    return homework.get("teacherId") or homework.get("createdBy")


def homework_is_assigned_to_student(homework, student):
    if student.get("role", "student") != "student":
        return False

    assigned_ids = homework.get("assignedStudentIds") or homework.get("studentIds") or []
    if assigned_ids:
        return student["id"] in assigned_ids

    level = homework.get("level")
    if level and (
        CEFR_RANKS.get(level.upper()) is None
        or student_level_rank(student) < CEFR_RANKS[level.upper()]
    ):
        return False

    course_id = homework.get("courseId")
    if course_id:
        course = next((item for item in load_courses() if item["id"] == course_id), None)
        if not course:
            return False
        return course["type"] != "cefr" or course_is_available(course, student)

    return bool(level)


def student_homework_view(homework, course_by_id, submissions_by_homework):
    submission = submissions_by_homework.get(homework["id"])
    return {
        "id": homework["id"],
        "title": homework["title"],
        "description": homework.get("description", ""),
        "courseId": homework.get("courseId"),
        "level": homework.get("level"),
        "dueDate": homework.get("dueDate"),
        "createdAt": homework.get("createdAt"),
        "status": homework.get("status"),
        "course": course_by_id.get(homework.get("courseId")),
        "submission": submission,
    }


def public_course(course, student=None):
    available = course_is_available(course, student) if student else False
    response = {
        "id": course["id"],
        "type": course["type"],
        "level": course["level"],
        "title": course["title"],
        "titleAr": course["titleAr"],
        "description": course["description"],
        "descriptionAr": course["descriptionAr"],
        "available": available,
        "locked": bool(student) and course["type"] == "cefr" and not available,
        "comingSoon": course["type"] == "future",
        "lessonCount": sum(1 for lesson in course.get("lessons", []) if lesson_is_student_visible(lesson)),
        "active": course_is_active(course),
        "order": course.get("order", 0),
    }
    if student:
        response["progress"] = student_progress(student, course)
    return response


def hash_password(password):
    salt = secrets.token_bytes(16)

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        100_000,
    )

    return salt.hex() + ":" + password_hash.hex()


def verify_password(password, stored_password):
    try:
        salt_hex, password_hex = stored_password.split(":", 1)
        candidate_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            100_000,
        )
        return secrets.compare_digest(candidate_hash.hex(), password_hex)
    except (ValueError, TypeError):
        return False


def public_user(student):
    return {
        "id": student["id"],
        "fullName": student["fullName"],
        "role": student.get("role", "student"),
        "level": student.get("level"),
    }


def self_user_view(student):
    return {
        **public_user(student),
        "email": student.get("email", ""),
        "dateOfBirth": student.get("dateOfBirth", ""),
        "phone": student.get("phone", ""),
        "testScore": student.get("testScore"),
        "totalQuestions": student.get("totalQuestions"),
        "testCompletedAt": student.get("testCompletedAt"),
        "createdAt": student.get("createdAt"),
        "devOnly": student.get("devOnly", False),
    }


def admin_user_view(user):
    return {**public_user(user), "email": user.get("email", ""), "createdAt": user.get("createdAt")}


def teacher_student_view(student):
    return {
        **public_user(student),
        "testScore": student.get("testScore"),
        "totalQuestions": student.get("totalQuestions"),
    }


def teacher_can_access_student(teacher, student):
    if student.get("role", "student") != "student":
        return False
    owns_class = any(
        item.get("teacherId") == teacher["id"]
        and item.get("status") != "cancelled"
        and class_is_assigned_to_student(item, student)
        for item in load_classes()
    )
    owns_homework = any(
        item.get("createdBy") == teacher["id"]
        and homework_is_assigned_to_student(item, student)
        for item in load_homework()
    )
    return owns_class or owns_homework


def create_access_token(student):
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {"sub": student["id"], "exp": expires_at, "jti": secrets.token_urlsafe(16)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def unauthorized(message="المصادقة مطلوبة"):
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=message,
        headers={"WWW-Authenticate": "Bearer"},
    )


def record_token_revocation(user, token):
    """Persist a logout so a revoked session cannot be reused after a restart.

    Only a one-way digest of the token is stored. Failure to persist does not fail
    the logout: the in-process revocation set still rejects the token immediately.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except InvalidTokenError:
        return False
    expires_at = payload.get("exp")
    if not expires_at:
        return False
    try:
        persistence.revoke_token(token, user["id"], datetime.fromtimestamp(int(expires_at), tz=timezone.utc))
    except DataStoreError:
        return False
    return True


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
):
    if credentials is None:
        raise unauthorized()
    if credentials.credentials in REVOKED_TOKENS:
        raise unauthorized("تم تسجيل الخروج من هذه الجلسة")
    if persistence.token_is_revoked(credentials.credentials):
        REVOKED_TOKENS.add(credentials.credentials)
        raise unauthorized("تم تسجيل الخروج من هذه الجلسة")

    try:
        payload = jwt.decode(
            credentials.credentials,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
        )
        student_id = payload.get("sub")
        if not student_id:
            raise unauthorized("رمز المصادقة غير صالح")
    except ExpiredSignatureError as error:
        raise unauthorized("انتهت صلاحية رمز المصادقة") from error
    except InvalidTokenError as error:
        raise unauthorized("رمز المصادقة غير صالح") from error

    student = find_student(student_id)
    if student is None:
        raise unauthorized("المستخدم غير موجود")
    return student


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
):
    if credentials is None:
        return None
    return get_current_user(credentials)


def require_role(*roles, allow_incomplete_placement=False):
    def role_dependency(current_user=Depends(get_current_user)):
        if current_user.get("role", "student") not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ليس لديك صلاحية للوصول إلى هذا القسم",
            )
        if (
            current_user.get("role", "student") == "student"
            and not allow_incomplete_placement
            and not (current_user.get("level") or current_user.get("testCompletedAt"))
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="PLACEMENT_REQUIRED")
        return current_user

    return role_dependency


UNAVAILABLE_HEALTH_BODY = {
    "status": "unavailable",
    "message": "FluentPath API cannot reach its storage backend",
}


def unavailable_health_response() -> JSONResponse:
    """Answer non-2xx without echoing any part of the cause.

    The body is a fixed literal on purpose. The failure may name a driver error,
    a host or a connection string, none of which belong in an unauthenticated
    response.
    """
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=UNAVAILABLE_HEALTH_BODY,
    )


def active_backend_label() -> str:
    """Return the backend name for logging, or ``unknown`` if unconfigured.

    Naming the backend is diagnostic; failing to resolve it must never turn a
    clean 503 into an unhandled error, so it is resolved defensively here.
    """
    try:
        return persistence.active_backend_name()
    except Exception:
        return "unknown"


@app.get("/api/health")
async def health():
    """Report readiness by asking the configured backend, not the process.

    Liveness alone would answer ok while the database is unreachable, so the
    check reads from the active store. The probe is read-only.
    """
    try:
        persistence.check_store_health()
    except DataStoreError:
        # No exception detail: a store failure can carry configuration or
        # connection information that must stay out of the log.
        logger.error(
            "Readiness check failed: the persistence backend is unavailable.",
            extra={"fluentpath_backend": active_backend_label()},
        )
        return unavailable_health_response()
    except Exception as failure:
        # An unexpected failure must not report readiness. Only the exception
        # type is recorded: a traceback here would reproduce the message, and a
        # misconfigured runtime is exactly where a connection string or a
        # credential can appear in one. The type is enough to tell a broken
        # runtime from an unreachable backend.
        logger.error(
            "Readiness check failed before reaching the backend.",
            extra={
                "fluentpath_backend": active_backend_label(),
                "fluentpath_error_type": type(failure).__name__,
            },
        )
        return unavailable_health_response()

    return {
        "status": "ok",
        "message": "FluentPath API is running"
    }


@app.post("/api/register")
async def register_student(student: StudentRegister):
    students = load_students()

    email = student.email.strip().lower()

    for existing_student in students:
        if existing_student["email"] == email:
            raise HTTPException(
                status_code=400,
                detail="هذا البريد الإلكتروني مسجل بالفعل"
            )

    new_student = {
        "id": secrets.token_hex(8),
        "fullName": student.fullName.strip(),
        "email": email,
        "passwordHash": hash_password(student.password),
        "role": "student",
        "dateOfBirth": student.dateOfBirth,
        "phone": student.phone.strip(),
        "level": None,
        "testScore": None,
        "totalQuestions": None,
        "testCompletedAt": None,
        "courseProgress": {},
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }

    students.append(new_student)
    save_students(students)
    for administrator in students:
        if administrator.get("role") == "administrator":
            create_notification(administrator["id"], f"registration:{new_student['id']}", "new_user_registration", "New student registered", f"{new_student['fullName']} created an account.", "user", new_student["id"])

    return {
        "success": True,
        "message": "تم إنشاء الحساب بنجاح",
        "access_token": create_access_token(new_student),
        "token_type": "bearer",
        "student": self_user_view(new_student),
    }


@app.post("/api/login")
async def login(credentials: LoginRequest):
    email = credentials.email.strip().lower()
    student = next(
        (candidate for candidate in load_students() if candidate["email"] == email),
        None,
    )

    if student is None or not verify_password(credentials.password, student["passwordHash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="البريد الإلكتروني أو كلمة المرور غير صحيحة",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if student.get("devOnly") and APP_ENVIRONMENT != "development":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="البريد الإلكتروني أو كلمة المرور غير صحيحة",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "access_token": create_access_token(student),
        "token_type": "bearer",
        "user": self_user_view(student),
    }


@app.get("/api/me")
async def current_user(current_user=Depends(get_current_user)):
    return self_user_view(current_user)


@app.get("/api/me/notifications")
async def get_my_notifications(current_user=Depends(require_role("student", "teacher", "administrator"))):
    records = [item for item in load_notifications() if item.get("recipient_user_id") == current_user["id"]]
    records.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return {"notifications": [{key: value for key, value in item.items() if key not in {"event_key", "recipient_user_id"}} for item in records]}


@app.get("/api/me/notifications/unread-count")
async def get_my_unread_notification_count(current_user=Depends(require_role("student", "teacher", "administrator"))):
    records = load_notifications()
    return {"unreadCount": sum(1 for item in records if item.get("recipient_user_id") == current_user["id"] and not item.get("read", False))}


@app.patch("/api/me/notifications/{notification_id}/read")
async def mark_my_notification_read(notification_id: str, current_user=Depends(require_role("student", "teacher", "administrator"))):
    records = load_notifications()
    notification = next((item for item in records if item.get("id") == notification_id), None)
    if notification is None or notification.get("recipient_user_id") != current_user["id"]:
        raise HTTPException(status_code=404, detail="الإشعار غير موجود")
    notification["read"] = True
    save_notifications(records)
    return {"success": True}


@app.post("/api/me/notifications/read-all")
async def mark_all_my_notifications_read(current_user=Depends(require_role("student", "teacher", "administrator"))):
    records = load_notifications()
    changed = False
    for item in records:
        if item.get("recipient_user_id") == current_user["id"] and not item.get("read", False):
            item["read"] = True
            changed = True
    if changed:
        save_notifications(records)
    return {"success": True}


@app.get("/api/profile")
async def profile(current_user=Depends(get_current_user)):
    return self_user_view(current_user)


@app.get("/api/me/gamification")
async def get_my_gamification(current_user=Depends(require_role("student"))):
    return gamification_summary(current_user)


@app.get("/api/me/achievements")
async def get_my_achievements(current_user=Depends(require_role("student"))):
    summary = gamification_summary(current_user)
    state = ensure_gamification(current_user)
    earned_at = {
        item.get("id"): item.get("earnedAt")
        for item in state["earnedBadges"] if isinstance(item, dict)
    }
    badges = [
        {
            **definition,
            "earned": definition["id"] in earned_at,
            "earnedAt": earned_at.get(definition["id"]),
        }
        for definition in BADGE_DEFINITIONS
    ]
    return {**summary, "badges": badges}


def ai_public_session(session):
    return {
        key: session.get(key)
        for key in ("id", "mode", "cefr_level", "status", "created_at", "updated_at", "completed_at")
    }


def ai_public_message(message):
    return {
        key: message.get(key)
        for key in ("id", "role", "content", "feedback", "score", "corrections", "next_step", "grammar_feedback", "vocabulary_feedback", "clarity_feedback", "relevance_feedback", "created_at", "xp_awarded")
        if key in message
    }


def enforce_ai_rate_limit(student_id):
    """Limit backend provider requests per student to control abuse and spend."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=1)
    usage = load_json_list(AI_USAGE_FILE)
    recent = []
    for entry in usage:
        try:
            requested_at = datetime.fromisoformat(entry.get("created_at", "").replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if requested_at >= cutoff:
            recent.append(entry)
    student_requests = sum(1 for entry in recent if entry.get("student_id") == student_id)
    if student_requests >= 20:
        raise HTTPException(status_code=429, detail="AI_TEACHER_RATE_LIMITED")
    recent.append({"student_id": student_id, "created_at": now.isoformat()})
    save_json_list(AI_USAGE_FILE, recent)


def ai_configuration_error():
    return HTTPException(status_code=503, detail="AI_TEACHER_NOT_CONFIGURED")


def ai_provider_error():
    return HTTPException(status_code=502, detail="AI_TEACHER_UNAVAILABLE")


async def generate_ai_turn(mode, cefr_level, messages):
    try:
        result = await ai_teacher.generate_ai_response(mode, cefr_level, messages)
        return ai_teacher.validate_ai_response(result)
    except ai_teacher.AIConfigurationError as error:
        raise ai_configuration_error() from error
    except ai_teacher.AIProviderError as error:
        raise ai_provider_error() from error


@app.post("/api/me/ai/sessions")
async def create_my_ai_session(session_request: AISessionCreate, current_user=Depends(require_role("student"))):
    enforce_ai_rate_limit(current_user["id"])
    result = await generate_ai_turn(session_request.mode, current_user.get("level"), [])
    now = datetime.now(timezone.utc).isoformat()
    session = {
        "id": secrets.token_urlsafe(18),
        "student_id": current_user["id"],
        "mode": session_request.mode,
        "cefr_level": current_user.get("level"),
        "status": "active",
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    assistant_message = {
        "id": secrets.token_urlsafe(18),
        "session_id": session["id"],
        "student_id": current_user["id"],
        "role": "assistant",
        "content": result["reply"],
        "feedback": result["feedback"],
        "score": result["score"],
        "corrections": result["corrections"],
        "next_step": result["next_step"],
        "grammar_feedback": result["grammar_feedback"],
        "vocabulary_feedback": result["vocabulary_feedback"],
        "clarity_feedback": result["clarity_feedback"],
        "relevance_feedback": result["relevance_feedback"],
        "xp_awarded": 0,
        "created_at": now,
    }
    sessions = load_json_list(AI_SESSIONS_FILE)
    messages = load_json_list(AI_MESSAGES_FILE)
    sessions.append(session)
    messages.append(assistant_message)
    save_json_list(AI_SESSIONS_FILE, sessions)
    save_json_list(AI_MESSAGES_FILE, messages)
    return {"session": ai_public_session(session), "message": ai_public_message(assistant_message)}


@app.get("/api/me/ai/sessions")
async def list_my_ai_sessions(current_user=Depends(require_role("student"))):
    sessions = [item for item in load_json_list(AI_SESSIONS_FILE) if item.get("student_id") == current_user["id"]]
    sessions.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or "", reverse=True)
    return {"sessions": [ai_public_session(item) for item in sessions[:50]]}


@app.get("/api/me/ai/sessions/{session_id}")
async def get_my_ai_session(session_id: str, current_user=Depends(require_role("student"))):
    session = next((item for item in load_json_list(AI_SESSIONS_FILE) if item.get("id") == session_id and item.get("student_id") == current_user["id"]), None)
    if session is None:
        raise HTTPException(status_code=404, detail="AI practice session not found")
    messages = [item for item in load_json_list(AI_MESSAGES_FILE) if item.get("session_id") == session_id and item.get("student_id") == current_user["id"]]
    messages.sort(key=lambda item: item.get("created_at") or "")
    return {"session": ai_public_session(session), "messages": [ai_public_message(item) for item in messages]}


@app.post("/api/me/ai/sessions/{session_id}/messages")
async def add_my_ai_message(session_id: str, message_request: AIMessageCreate, current_user=Depends(require_role("student"))):
    sessions = load_json_list(AI_SESSIONS_FILE)
    session = next((item for item in sessions if item.get("id") == session_id and item.get("student_id") == current_user["id"]), None)
    if session is None:
        raise HTTPException(status_code=404, detail="AI practice session not found")
    content = message_request.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Message cannot be blank")
    enforce_ai_rate_limit(current_user["id"])

    messages = load_json_list(AI_MESSAGES_FILE)
    session_messages = [item for item in messages if item.get("session_id") == session_id and item.get("student_id") == current_user["id"]]
    history = [
        {"role": item["role"], "content": item["content"]}
        for item in session_messages[-8:]
        if item.get("role") in {"user", "assistant"} and isinstance(item.get("content"), str)
    ]
    history.append({"role": "user", "content": content})
    result = await generate_ai_turn(session["mode"], session.get("cefr_level"), history)

    now = datetime.now(timezone.utc).isoformat()
    user_message = {
        "id": secrets.token_urlsafe(18), "session_id": session_id, "student_id": current_user["id"],
        "role": "user", "content": content, "created_at": now,
    }
    assistant_message = {
        "id": secrets.token_urlsafe(18), "session_id": session_id, "student_id": current_user["id"],
        "role": "assistant", "content": result["reply"], "feedback": result["feedback"],
        "score": result["score"], "corrections": result["corrections"], "next_step": result["next_step"],
        "grammar_feedback": result["grammar_feedback"], "vocabulary_feedback": result["vocabulary_feedback"],
        "clarity_feedback": result["clarity_feedback"], "relevance_feedback": result["relevance_feedback"],
        "xp_awarded": 0, "created_at": now,
    }

    existing_valid_turns = sum(
        1 for item in session_messages
        if item.get("role") == "user" and len(str(item.get("content", "")).strip()) >= (5 if session["mode"] == "conversation" else 1)
    )
    minimum_length = 20 if session["mode"] in {"writing", "speaking"} else 5 if session["mode"] == "conversation" else 1
    valid_turns = existing_valid_turns + int(len(content) >= minimum_length)
    completed = valid_turns >= (3 if session["mode"] == "conversation" else 1)
    xp_awarded = 0
    if completed and session.get("status") != "completed":
        activity_date = datetime.now(timezone.utc).date().isoformat()
        action_key = f"ai_practice:{activity_date}:{session['mode']}"
        student_records = load_students()
        student = next((item for item in student_records if item.get("id") == current_user["id"] and item.get("role", "student") == "student"), None)
        if student is not None and award_learning_action(student, action_key, "ai_practice_completed"):
            xp_awarded = XP_REWARDS["ai_practice_completed"]
            save_students(student_records)
        session["status"] = "completed"
        session["completed_at"] = now
        assistant_message["xp_awarded"] = xp_awarded

    session["updated_at"] = now
    messages.extend((user_message, assistant_message))
    save_json_list(AI_MESSAGES_FILE, messages)
    save_json_list(AI_SESSIONS_FILE, sessions)
    return {
        "session": ai_public_session(session),
        "user_message": ai_public_message(user_message),
        "message": ai_public_message(assistant_message),
        "xp_awarded": xp_awarded,
    }


@app.get("/api/leaderboard")
async def get_student_leaderboard(current_user=Depends(require_role("student"))):
    students = [
        student for student in load_students()
        if student.get("role", "student") == "student"
    ]
    students.sort(key=lambda student: (
        -int(ensure_gamification(student)["xp"]),
        student.get("fullName", "").casefold(),
        student.get("id", ""),
    ))
    return {
        "leaderboard": [
            {
                "rank": index,
                "displayName": student.get("fullName", "Student"),
                "xp": int(ensure_gamification(student)["xp"]),
                "level": xp_level_progress(ensure_gamification(student)["xp"])["level"],
            }
            for index, student in enumerate(students, start=1)
        ]
    }


@app.post("/api/logout")
async def logout(
    current_user=Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    REVOKED_TOKENS.add(credentials.credentials)
    record_token_revocation(current_user, credentials.credentials)
    return {"success": True, "message": "تم تسجيل الخروج بنجاح"}


@app.get("/api/teacher/dashboard")
async def teacher_dashboard(current_user=Depends(require_role("teacher"))):
    students = [student for student in load_students() if teacher_can_access_student(current_user, student)]
    homework = load_homework()
    classes = [
        normalize_class(scheduled_class) for scheduled_class in load_classes()
        if normalize_class(scheduled_class).get("teacherId") == current_user["id"]
        and class_time_state(scheduled_class) == "upcoming"
        and scheduled_class.get("status") != "cancelled"
    ]
    return {
        "role": current_user["role"],
        "currentUser": self_user_view(current_user),
        "assignedStudents": len(students),
        "courses": len(load_courses()),
        "homework": len([item for item in homework if item.get("createdBy") == current_user["id"]]),
        "upcomingClasses": classes,
        "message": "Teacher dashboard MVP",
    }


@app.get("/api/teacher/students")
async def teacher_students(current_user=Depends(require_role("teacher"))):
    courses = [course for course in load_courses() if course.get("type") == "cefr"]
    students = [
        student for student in load_students()
        if teacher_can_access_student(current_user, student)
    ]
    return {
        "students": [
            {
                **teacher_student_view(student),
                "courseProgress": [
                    {
                        "courseId": course["id"],
                        "courseTitle": course["title"],
                        "level": course["level"],
                        "progress": student_progress(student, course),
                    }
                    for course in courses
                ],
            }
            for student in students
        ]
    }


@app.get("/api/teacher/courses")
async def teacher_courses(current_user=Depends(require_role("teacher"))):
    del current_user
    return {
        "courses": [
            {
                **public_course(course),
                "lessons": [
                    {
                        "id": lesson["id"],
                        "number": lesson["number"],
                        "title": lesson["title"],
                        "titleAr": lesson["titleAr"],
                    }
                    for lesson in course.get("lessons", [])
                ],
            }
            for course in load_courses()
        ]
    }


@app.get("/api/teacher/homework")
async def teacher_homework(current_user=Depends(require_role("teacher"))):
    submissions = load_submissions()
    return {
        "homework": [
            {
                **item,
                "teacherId": homework_teacher_id(item),
                "submissionCount": sum(
                    1 for submission in submissions
                    if submission.get("homeworkId") == item["id"]
                ),
            }
            for item in load_homework()
            if homework_teacher_id(item) == current_user["id"]
        ]
    }


@app.post("/api/teacher/homework")
async def create_teacher_homework(
    homework: HomeworkCreate,
    current_user=Depends(require_role("teacher")),
):
    courses = load_courses()
    course = next(
        (item for item in courses if item["id"] == homework.courseId),
        None,
    ) if homework.courseId else None
    if homework.courseId and course is None:
        raise HTTPException(status_code=404, detail="الدورة غير موجودة")

    title = homework.title.strip()
    description = homework.description.strip()
    if not title or not description:
        raise HTTPException(status_code=400, detail="عنوان ووصف الواجب مطلوبان")

    level = homework.level.strip() if homework.level else None
    if level and level.upper() not in CEFR_RANKS:
        raise HTTPException(status_code=400, detail="مستوى CEFR غير صالح")
    if not course and not level and not homework.studentIds:
        raise HTTPException(
            status_code=400,
            detail="اختر دورة أو مستوى أو طالبًا واحدًا على الأقل",
        )

    due_date = None
    if homework.dueDate:
        try:
            due_date = datetime.fromisoformat(homework.dueDate.replace("Z", "+00:00"))
            if due_date.tzinfo is None:
                due_date = due_date.replace(tzinfo=timezone.utc)
        except ValueError as error:
            raise HTTPException(status_code=400, detail="تاريخ التسليم غير صالح") from error

    students_by_id = {
        student["id"]: student
        for student in load_students()
        if student.get("role", "student") == "student"
    }
    assigned_student_ids = list(dict.fromkeys(homework.studentIds))
    for student_id in assigned_student_ids:
        student = students_by_id.get(student_id)
        if student is None:
            raise HTTPException(status_code=400, detail="قائمة الطلاب تتضمن طالبًا غير صالح")
        if not teacher_can_access_student(current_user, student):
            raise HTTPException(status_code=403, detail="لا يمكنك إسناد واجب إلى طالب غير مرتبط بفصولك أو واجباتك")
        if course and course["type"] == "cefr" and not course_is_available(course, student):
            raise HTTPException(
                status_code=400,
                detail="لا يمكن إسناد الدورة لطالب لا يملك المستوى المطلوب",
            )
        if level and student_level_rank(student) < CEFR_RANKS[level.upper()]:
            raise HTTPException(
                status_code=400,
                detail="لا يمكن إسناد الواجب لطالب دون المستوى المطلوب",
            )

    records = load_homework()
    new_homework = {
        "id": secrets.token_hex(8),
        "title": title,
        "description": description,
        "teacherId": current_user["id"],
        "createdBy": current_user["id"],
        "courseId": homework.courseId,
        "level": level,
        "assignedStudentIds": assigned_student_ids,
        "dueDate": due_date.isoformat() if due_date else None,
        "status": "assigned",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    records.append(new_homework)
    save_json_list(HOMEWORK_FILE, records)
    recipients = [student["id"] for student in students_by_id.values() if homework_is_assigned_to_student(new_homework, student)]
    for student_id in recipients:
        create_notification(student_id, f"homework_assigned:{new_homework['id']}", "homework_assigned", "New homework assigned", title, "homework", new_homework["id"])
    return {"success": True, "homework": new_homework}


def find_teacher_homework(homework_id, teacher_id):
    homework = next(
        (item for item in load_homework() if item["id"] == homework_id),
        None,
    )
    if homework is None:
        raise HTTPException(status_code=404, detail="الواجب غير موجود")
    if homework_teacher_id(homework) != teacher_id:
        raise HTTPException(status_code=403, detail="لا يمكنك إدارة واجب لمعلم آخر")
    return homework


@app.get("/api/teacher/homework/{homework_id}/submissions")
async def teacher_homework_submissions(
    homework_id: str,
    current_user=Depends(require_role("teacher")),
):
    homework = find_teacher_homework(homework_id, current_user["id"])
    students_by_id = {
        student["id"]: public_user(student)
        for student in load_students()
    }
    return {
        "homework": homework,
        "submissions": [
            {
                **submission,
                "student": students_by_id.get(submission.get("studentId")),
            }
            for submission in load_submissions()
            if submission.get("homeworkId") == homework_id
        ],
    }


@app.patch("/api/teacher/homework/{homework_id}/submissions/{submission_id}/grade")
async def grade_homework_submission(
    homework_id: str,
    submission_id: str,
    grade: HomeworkGrade,
    current_user=Depends(require_role("teacher")),
):
    find_teacher_homework(homework_id, current_user["id"])
    submissions = load_submissions()
    submission = next(
        (
            item for item in submissions
            if item["id"] == submission_id and item.get("homeworkId") == homework_id
        ),
        None,
    )
    if submission is None:
        raise HTTPException(status_code=404, detail="التسليم غير موجود")
    if grade.grade is None and not grade.teacherFeedback.strip():
        raise HTTPException(status_code=400, detail="أضف درجة أو ملاحظات قبل حفظ التقييم")

    first_grade = submission.get("status") != "graded"
    submission["grade"] = grade.grade
    submission["teacherFeedback"] = grade.teacherFeedback.strip()
    submission["status"] = "graded"
    submission["gradedAt"] = datetime.now(timezone.utc).isoformat()
    save_json_list(SUBMISSIONS_FILE, submissions)
    if first_grade:
        award_gamification_to_student(
            submission.get("studentId"),
            f"homework_graded:{homework_id}",
            "homework_graded",
        )
        create_notification(submission.get("studentId"), f"homework_graded:{submission_id}", "homework_graded", "Homework graded", "Your teacher graded your homework and may have left feedback.", "homework", homework_id)
    return {"success": True, "submission": submission}


@app.get("/api/student/homework")
async def student_homework(current_user=Depends(require_role("student"))):
    submissions_by_homework = {
        submission["homeworkId"]: submission
        for submission in load_submissions()
        if submission.get("studentId") == current_user["id"]
    }
    courses_by_id = {course["id"]: course for course in load_courses()}
    records = [
        student_homework_view(item, courses_by_id, submissions_by_homework)
        for item in load_homework()
        if homework_is_assigned_to_student(item, current_user)
    ]
    records.sort(key=lambda item: item.get("dueDate") or "9999")
    return {"homework": records}


@app.get("/api/student/homework/{homework_id}")
async def get_student_homework(
    homework_id: str,
    current_user=Depends(require_role("student")),
):
    homework = next(
        (item for item in load_homework() if item["id"] == homework_id),
        None,
    )
    if homework is None or not homework_is_assigned_to_student(homework, current_user):
        raise HTTPException(status_code=404, detail="الواجب غير موجود")

    submission = next(
        (
            item for item in load_submissions()
            if item.get("homeworkId") == homework_id
            and item.get("studentId") == current_user["id"]
        ),
        None,
    )
    course = next(
        (item for item in load_courses() if item["id"] == homework.get("courseId")),
        None,
    )
    return {
        "homework": student_homework_view(
            homework,
            {course["id"]: course} if course else {},
            {homework_id: submission} if submission else {},
        )
    }


@app.post("/api/student/homework/{homework_id}/submissions")
async def submit_student_homework(
    homework_id: str,
    submission_request: HomeworkSubmissionCreate,
    current_user=Depends(require_role("student")),
):
    homework = next(
        (item for item in load_homework() if item["id"] == homework_id),
        None,
    )
    if homework is None or not homework_is_assigned_to_student(homework, current_user):
        raise HTTPException(status_code=404, detail="الواجب غير موجود")

    answer = submission_request.answer.strip()
    if not answer:
        raise HTTPException(status_code=400, detail="الإجابة مطلوبة")

    submissions = load_submissions()
    submission = next(
        (
            item for item in submissions
            if item.get("homeworkId") == homework_id
            and item.get("studentId") == current_user["id"]
        ),
        None,
    )
    first_submission = submission is None
    if submission and submission.get("status") == "graded":
        raise HTTPException(status_code=409, detail="تم تقييم هذا التسليم ولا يمكن تعديله")

    now = datetime.now(timezone.utc)
    due_date = homework.get("dueDate")
    is_late = False
    if due_date:
        try:
            is_late = now > datetime.fromisoformat(due_date.replace("Z", "+00:00"))
        except ValueError:
            is_late = False
    if submission is None:
        submission = {
            "id": secrets.token_hex(8),
            "homeworkId": homework_id,
            "studentId": current_user["id"],
        }
        submissions.append(submission)
    submission.update({
        "answer": answer,
        "submittedAt": now.isoformat(),
        "grade": None,
        "teacherFeedback": "",
        "status": "late" if is_late else "submitted",
    })
    save_json_list(SUBMISSIONS_FILE, submissions)
    if first_submission:
        award_gamification_to_student(
            current_user["id"],
            f"homework_submitted:{homework_id}",
            "homework_submitted",
        )
        teacher_id = homework_teacher_id(homework)
        create_notification(teacher_id, f"homework_submitted:{submission['id']}", "homework_submitted", "Student submitted homework", f"A student submitted: {homework.get('title', 'Homework')}.", "submission", submission["id"])
    return {"success": True, "submission": submission}


@app.get("/api/teacher/classes")
async def teacher_classes(current_user=Depends(require_role("teacher"))):
    for item in load_classes():
        if normalize_class(item).get("teacherId") == current_user["id"]:
            maybe_create_class_reminder(item, current_user["id"])
    return {
        "classes": [
            {
                **{key: value for key, value in normalize_class(item).items()
                   if not (normalize_class(item).get("meetingProvider") == "zoom"
                           and normalize_class(item).get("zoomMeetingId")
                           and key in ("teacherJoinUrl", "studentJoinUrl", "meetingUrl"))},
                "timeState": class_time_state(item),
            }
            for item in load_classes()
            if normalize_class(item).get("teacherId") == current_user["id"]
        ]
    }


def build_class_record(class_request, teacher_id, existing=None):
    title = class_request.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="عنوان الحصة مطلوب")
    try:
        class_date = datetime.strptime(class_request.date, "%Y-%m-%d").date()
        start_time = datetime.strptime(class_request.startTime, "%H:%M").time()
        end_time = datetime.strptime(class_request.endTime, "%H:%M").time()
    except ValueError as error:
        raise HTTPException(status_code=400, detail="تاريخ أو وقت الحصة غير صالح") from error
    if end_time <= start_time:
        raise HTTPException(status_code=400, detail="وقت انتهاء الحصة يجب أن يأتي بعد وقت البدء")

    course = None
    if class_request.courseId:
        course = next((item for item in load_courses() if item["id"] == class_request.courseId), None)
        if course is None:
            raise HTTPException(status_code=404, detail="الدورة غير موجودة")
    level = class_request.level.strip() if class_request.level else None
    if level and level.upper() not in CEFR_RANKS:
        raise HTTPException(status_code=400, detail="مستوى CEFR غير صالح")
    if not course and not level and not class_request.studentIds:
        raise HTTPException(status_code=400, detail="اختر دورة أو مستوى أو طالبًا واحدًا على الأقل")

    if class_request.meetingProvider not in ("none", "zoom"):
        raise HTTPException(status_code=400, detail="مزود الاجتماع يجب أن يكون none أو zoom")
    # Preserve older classes that used the Zoom label for teacher-entered URLs.
    # Newly selected automatic Zoom classes send no URLs and are provisioned server-side.
    manual_zoom_links = class_request.meetingProvider == "zoom" and any((class_request.meetingUrl, class_request.teacherJoinUrl, class_request.studentJoinUrl))
    meeting_provider = "none" if manual_zoom_links else class_request.meetingProvider
    if not manual_zoom_links and class_request.meetingProvider == "zoom":
        meeting_url = teacher_join_url = student_join_url = None
    else:
        meeting_url = valid_meeting_url(class_request.meetingUrl)
        teacher_join_url = valid_meeting_url(class_request.teacherJoinUrl) if class_request.teacherJoinUrl else meeting_url
        student_join_url = valid_meeting_url(class_request.studentJoinUrl) if class_request.studentJoinUrl else meeting_url

    students_by_id = {
        student["id"]: student
        for student in load_students()
        if student.get("role", "student") == "student"
    }
    assigned_student_ids = list(dict.fromkeys(class_request.studentIds))
    teacher = find_student(teacher_id)
    for student_id in assigned_student_ids:
        student = students_by_id.get(student_id)
        if student is None:
            raise HTTPException(status_code=400, detail="قائمة الطلاب تتضمن طالبًا غير صالح")
        if teacher is None or not teacher_can_access_student(teacher, student):
            raise HTTPException(status_code=403, detail="لا يمكنك إسناد حصة إلى طالب غير مرتبط بفصولك أو واجباتك")
        if course and course["type"] == "cefr" and not course_is_available(course, student):
            raise HTTPException(status_code=400, detail="الطالب لا يملك مستوى الدورة المطلوب")
        if level and student_level_rank(student) < CEFR_RANKS[level.upper()]:
            raise HTTPException(status_code=400, detail="الطالب دون المستوى المطلوب")

    starts_at = class_request.startsAt
    if starts_at:
        try:
            datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise HTTPException(status_code=400, detail="تاريخ بدء الحصة غير صالح") from error
    else:
        starts_at = datetime.combine(class_date, start_time, timezone.utc).isoformat()

    if not assigned_student_ids:
        for student in students_by_id.values():
            if course and course["type"] == "cefr" and not course_is_available(course, student):
                continue
            if level and student_level_rank(student) < CEFR_RANKS[level.upper()]:
                continue
            assigned_student_ids.append(student["id"])

    record = dict(existing or {})
    record.update({
        "id": record.get("id") or secrets.token_hex(8),
        "teacherId": teacher_id,
        "courseId": class_request.courseId,
        "level": level,
        "title": title,
        "description": class_request.description.strip(),
        "assignedStudentIds": assigned_student_ids,
        "date": class_date.isoformat(),
        "startTime": start_time.strftime("%H:%M"),
        "endTime": end_time.strftime("%H:%M"),
        "startsAt": starts_at,
        "durationMinutes": int((datetime.combine(class_date, end_time) - datetime.combine(class_date, start_time)).total_seconds() / 60),
        "meetingProvider": meeting_provider,
        "meetingUrl": meeting_url,
        "teacherJoinUrl": teacher_join_url,
        "studentJoinUrl": student_join_url,
        "status": (existing or {}).get("status", "scheduled"),
        "createdAt": (existing or {}).get("createdAt") or datetime.now(timezone.utc).isoformat(),
    })
    return record


def find_teacher_class(class_id, teacher_id):
    classes = load_classes()
    class_index = next((index for index, item in enumerate(classes) if item.get("id") == class_id), None)
    if class_index is None:
        raise HTTPException(status_code=404, detail="الحصة غير موجودة")
    if normalize_class(classes[class_index]).get("teacherId") != teacher_id:
        raise HTTPException(status_code=403, detail="لا يمكنك إدارة حصة لمعلم آخر")
    return classes, class_index


@app.post("/api/teacher/classes")
async def create_teacher_class(
    class_request: ClassInput,
    current_user=Depends(require_role("teacher")),
):
    classes = load_classes()
    class_record = build_class_record(class_request, current_user["id"])
    if class_record["meetingProvider"] == "zoom":
        try:
            class_record.update(await asyncio.to_thread(zoom_service.create_meeting, class_record))
        except zoom_service.ZoomError as error:
            raise_zoom_http_error(error)
    classes.append(class_record)
    try:
        save_json_list(CLASSES_FILE, classes)
    except Exception:
        if class_record.get("zoomMeetingId"):
            try:
                await asyncio.to_thread(zoom_service.delete_meeting, class_record["zoomMeetingId"])
            except zoom_service.ZoomError:
                pass
        raise
    return {"success": True, "class": normalize_class(class_record)}


@app.put("/api/teacher/classes/{class_id}")
async def update_teacher_class(
    class_id: str,
    class_request: ClassInput,
    current_user=Depends(require_role("teacher")),
):
    classes, class_index = find_teacher_class(class_id, current_user["id"])
    previous = normalize_class(classes[class_index])
    updated = build_class_record(
        class_request,
        current_user["id"],
        existing=previous,
    )
    try:
        if updated["meetingProvider"] == "zoom":
            if previous.get("meetingProvider") == "zoom" and previous.get("zoomMeetingId"):
                await asyncio.to_thread(zoom_service.update_meeting, previous["zoomMeetingId"], updated)
                updated.update({
                    "zoomMeetingId": previous["zoomMeetingId"],
                    "teacherJoinUrl": previous.get("teacherJoinUrl"),
                    "studentJoinUrl": previous.get("studentJoinUrl"),
                    "meetingUrl": previous.get("studentJoinUrl") or previous.get("meetingUrl"),
                })
            else:
                updated.update(await asyncio.to_thread(zoom_service.create_meeting, updated))
        elif previous.get("meetingProvider") == "zoom" and previous.get("zoomMeetingId"):
            await asyncio.to_thread(zoom_service.delete_meeting, previous["zoomMeetingId"])
    except zoom_service.ZoomError as error:
        raise_zoom_http_error(error)
    classes[class_index] = updated
    save_json_list(CLASSES_FILE, classes)
    return {"success": True, "class": normalize_class(classes[class_index])}


@app.post("/api/teacher/classes/{class_id}/cancel")
async def cancel_teacher_class(
    class_id: str,
    current_user=Depends(require_role("teacher")),
):
    classes, class_index = find_teacher_class(class_id, current_user["id"])
    classes[class_index] = normalize_class(classes[class_index])
    if classes[class_index].get("meetingProvider") == "zoom" and classes[class_index].get("zoomMeetingId"):
        try:
            await asyncio.to_thread(zoom_service.delete_meeting, classes[class_index]["zoomMeetingId"])
        except zoom_service.ZoomError as error:
            raise_zoom_http_error(error)
    classes[class_index]["status"] = "cancelled"
    save_json_list(CLASSES_FILE, classes)
    class_item = normalize_class(classes[class_index])
    for student_id in class_item.get("assignedStudentIds", []):
        create_notification(student_id, f"class_cancelled:{class_id}", "class_cancelled", "Class cancelled", class_item.get("title", "A class") + " has been cancelled.", "class", class_id, "warning")
    return {"success": True, "class": classes[class_index]}


@app.get("/api/student/classes")
async def student_classes(current_user=Depends(require_role("student"))):
    for item in load_classes():
        if class_is_assigned_to_student(item, current_user):
            maybe_create_class_reminder(item, current_user["id"])
    records = [
        student_class_view(item)
        for item in load_classes()
        if class_is_assigned_to_student(item, current_user)
    ]
    records.sort(key=lambda item: item.get("startsAt") or "")
    return {
        "upcoming": [item for item in records if class_time_state(item) == "upcoming" and item["status"] != "cancelled"],
        "past": [item for item in records if class_time_state(item) == "past" and item["status"] != "cancelled"],
        "cancelled": [item for item in records if item["status"] == "cancelled"],
    }


@app.get("/api/student/classes/{class_id}")
async def student_class_detail(
    class_id: str,
    current_user=Depends(require_role("student")),
):
    class_record = next((item for item in load_classes() if item.get("id") == class_id), None)
    if class_record is None or not class_is_assigned_to_student(class_record, current_user):
        raise HTTPException(status_code=404, detail="الحصة غير موجودة")
    class_item = normalize_class(class_record)
    teacher = next((user for user in load_students() if user["id"] == class_item["teacherId"]), None)
    course = next((item for item in load_courses() if item["id"] == class_item.get("courseId")), None)
    return {
        "class": {
            **{key: value for key, value in student_class_view(class_record).items() if key != "teacherId"},
            "teacher": {"id": teacher["id"], "fullName": teacher["fullName"]} if teacher else None,
            "course": public_course(course) if course else None,
        }
    }


@app.get("/api/admin/classes")
async def admin_classes(current_user=Depends(require_role("administrator"))):
    users = load_students()
    users_by_id = {user["id"]: user for user in users}
    courses_by_id = {course["id"]: course for course in load_courses()}
    records = []
    for item in load_classes():
        class_item = normalize_class(item)
        teacher = users_by_id.get(class_item.get("teacherId"))
        admin_class = {key: value for key, value in class_item.items() if key not in ("teacherJoinUrl", "studentJoinUrl", "meetingUrl")}
        records.append({
            **admin_class,
            "timeState": class_time_state(item),
            "teacher": public_user(teacher) if teacher else None,
            "course": public_course(courses_by_id[class_item["courseId"]]) if class_item.get("courseId") in courses_by_id else None,
            "students": [
                public_user(users_by_id[student_id])
                for student_id in class_item["assignedStudentIds"]
                if student_id in users_by_id
            ],
        })
    return {
        "classes": records,
        "total": len(records),
        "upcoming": sum(1 for item in records if item["timeState"] == "upcoming" and item["status"] != "cancelled"),
        "past": sum(1 for item in records if item["timeState"] == "past" and item["status"] != "cancelled"),
        "cancelled": sum(1 for item in records if item["status"] == "cancelled"),
    }


@app.get("/api/community/areas")
async def community_areas(current_user=Depends(require_role("student", "teacher", "administrator"))):
    role = current_user.get("role", "student")
    courses = []
    for course in load_courses():
        if role == "administrator":
            accessible = True
        elif role == "teacher":
            accessible = teacher_has_course(current_user["id"], course["id"])
        else:
            accessible = course["type"] != "cefr" or course_is_available(course, current_user)
        if accessible:
            courses.append({"id": course["id"], "title": course["title"], "titleAr": course["titleAr"], "level": course["level"]})

    classes = []
    for class_record in load_classes():
        class_item = normalize_class(class_record)
        if class_item.get("status") == "cancelled":
            continue
        if role == "administrator":
            accessible = True
        elif role == "teacher":
            accessible = class_item.get("teacherId") == current_user["id"]
        else:
            accessible = class_is_assigned_to_student(class_record, current_user)
        if accessible:
            classes.append({"id": class_item["id"], "title": class_item["title"], "courseId": class_item.get("courseId")})
    return {"areas": {"general": True, "courses": courses, "classes": classes}}


@app.get("/api/community/posts")
async def community_posts(
    scope: Optional[Literal["general", "course", "class"]] = None,
    course_id: Optional[str] = Query(default=None, alias="courseId"),
    class_id: Optional[str] = Query(default=None, alias="classId"),
    search: Optional[str] = None,
    current_user=Depends(require_role("student", "teacher", "administrator")),
):
    replies = load_community_replies()
    search_term = search.strip().casefold() if search else ""
    posts = []
    for post in load_community_posts():
        post_scope = post.get("scope", "general")
        if scope and post_scope != scope:
            continue
        if course_id and post.get("courseId") != course_id:
            continue
        if class_id and post.get("classId") != class_id:
            continue
        if not can_access_community_post(current_user, post):
            continue
        if post.get("status", "visible") == "deleted":
            continue
        if post.get("status", "visible") != "visible" and current_user.get("role") != "administrator":
            continue
        if search_term and search_term not in f"{post.get('title', '')} {post.get('content', '')}".casefold():
            continue
        posts.append(public_community_post(post, current_user, replies))
    posts.sort(key=lambda item: item.get("createdAt") or "", reverse=True)
    return {"posts": posts}


@app.post("/api/community/posts")
async def create_community_post(
    post_request: CommunityPostCreate,
    current_user=Depends(require_role("student", "teacher")),
):
    title = post_request.title.strip()
    content = post_request.content.strip()
    if not title or not content or len(title) > 180 or len(content) > 8000:
        raise HTTPException(status_code=400, detail="العنوان والمحتوى مطلوبان وبطول صالح")
    if post_request.scope == "general" and (post_request.courseId or post_request.classId):
        raise HTTPException(status_code=400, detail="المنطقة العامة لا تقبل دورة أو حصة")
    if post_request.scope == "course" and (not post_request.courseId or post_request.classId):
        raise HTTPException(status_code=400, detail="اختر دورة صالحة للنقاش")
    if post_request.scope == "class" and (not post_request.classId or post_request.courseId):
        raise HTTPException(status_code=400, detail="اختر حصة صالحة للنقاش")
    if not can_access_community_area(
        current_user,
        post_request.scope,
        course_id=post_request.courseId,
        class_id=post_request.classId,
    ):
        raise HTTPException(status_code=403, detail="لا يمكنك النشر في منطقة النقاش هذه")

    post = {
        "id": secrets.token_hex(8),
        "scope": post_request.scope,
        "courseId": post_request.courseId,
        "classId": post_request.classId,
        "title": title,
        "content": content,
        "authorId": current_user["id"],
        "authorRole": current_user.get("role", "student"),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "updatedAt": None,
        "status": "visible",
        "likesBy": [],
    }
    posts = load_community_posts()
    posts.append(post)
    save_json_list(COMMUNITY_POSTS_FILE, posts)
    if current_user.get("role") == "student" and post["scope"] in ("course", "class"):
        for class_record in load_classes():
            class_item = normalize_class(class_record)
            scope_matches = (
                post["scope"] == "class" and class_item.get("id") == post.get("classId")
            ) or (
                post["scope"] == "course" and class_item.get("courseId") == post.get("courseId")
            )
            if scope_matches and class_item.get("status") != "cancelled" and class_is_assigned_to_student(class_record, current_user):
                create_notification(class_item.get("teacherId"), f"community_activity:{post['id']}", "community_activity", "New community activity", f"{current_user.get('fullName', 'A student')} posted in a learning discussion.", "post", post["id"])
    return {"success": True, "post": public_community_post(post, current_user)}


@app.get("/api/community/posts/{post_id}")
async def community_post_detail(
    post_id: str,
    current_user=Depends(require_role("student", "teacher", "administrator")),
):
    post = find_accessible_community_post(current_user=current_user, post_id=post_id)
    replies = [
        public_community_reply(reply)
        for reply in load_community_replies()
        if reply.get("postId") == post_id and reply.get("status", "visible") == "visible"
    ]
    replies.sort(key=lambda item: item.get("createdAt") or "")
    return {"post": public_community_post(post, current_user), "replies": replies}


@app.patch("/api/community/posts/{post_id}")
async def update_community_post(
    post_id: str,
    post_update: CommunityPostUpdate,
    current_user=Depends(require_role("student", "teacher")),
):
    post = find_accessible_community_post(current_user, post_id)
    if post.get("authorId") != current_user["id"]:
        raise HTTPException(status_code=403, detail="لا يمكنك تعديل منشور مستخدم آخر")
    title, content = post_update.title.strip(), post_update.content.strip()
    if not title or not content or len(title) > 180 or len(content) > 8000:
        raise HTTPException(status_code=400, detail="العنوان والمحتوى مطلوبان وبطول صالح")
    posts = load_community_posts()
    stored_post = next(item for item in posts if item["id"] == post_id)
    stored_post.update({"title": title, "content": content, "updatedAt": datetime.now(timezone.utc).isoformat()})
    save_json_list(COMMUNITY_POSTS_FILE, posts)
    return {"success": True, "post": public_community_post(stored_post, current_user)}


@app.delete("/api/community/posts/{post_id}")
async def delete_community_post(
    post_id: str,
    current_user=Depends(require_role("student", "teacher")),
):
    post = find_accessible_community_post(current_user, post_id)
    if post.get("authorId") != current_user["id"]:
        raise HTTPException(status_code=403, detail="لا يمكنك حذف منشور مستخدم آخر")
    posts = load_community_posts()
    stored_post = next(item for item in posts if item["id"] == post_id)
    stored_post["status"] = "deleted"
    stored_post["updatedAt"] = datetime.now(timezone.utc).isoformat()
    save_json_list(COMMUNITY_POSTS_FILE, posts)
    return {"success": True}


@app.post("/api/community/posts/{post_id}/replies")
async def create_community_reply(
    post_id: str,
    reply_request: CommunityReplyCreate,
    current_user=Depends(require_role("student", "teacher")),
):
    find_accessible_community_post(current_user, post_id)
    content = reply_request.content.strip()
    if not content or len(content) > 5000:
        raise HTTPException(status_code=400, detail="نص الرد مطلوب وبطول صالح")
    reply = {
        "id": secrets.token_hex(8),
        "postId": post_id,
        "content": content,
        "authorId": current_user["id"],
        "authorRole": current_user.get("role", "student"),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "updatedAt": None,
        "status": "visible",
    }
    replies = load_community_replies()
    replies.append(reply)
    save_json_list(COMMUNITY_REPLIES_FILE, replies)
    author_id = next((item.get("authorId") for item in load_community_posts() if item.get("id") == post_id), None)
    if author_id and author_id != current_user["id"]:
        create_notification(author_id, f"community_reply:{reply['id']}", "community_reply", "New community reply", "Someone replied to your post.", "post", post_id)
    return {"success": True, "reply": public_community_reply(reply)}


@app.patch("/api/community/replies/{reply_id}")
async def update_community_reply(
    reply_id: str,
    reply_request: CommunityReplyCreate,
    current_user=Depends(require_role("student", "teacher")),
):
    replies = load_community_replies()
    reply = next((item for item in replies if item.get("id") == reply_id), None)
    if not reply:
        raise HTTPException(status_code=404, detail="الرد غير موجود")
    post = find_accessible_community_post(current_user, reply["postId"])
    if reply.get("authorId") != current_user["id"]:
        raise HTTPException(status_code=403, detail="لا يمكنك تعديل رد مستخدم آخر")
    content = reply_request.content.strip()
    if not content or len(content) > 5000:
        raise HTTPException(status_code=400, detail="نص الرد مطلوب وبطول صالح")
    reply.update({"content": content, "updatedAt": datetime.now(timezone.utc).isoformat()})
    save_json_list(COMMUNITY_REPLIES_FILE, replies)
    return {"success": True, "reply": public_community_reply(reply)}


@app.delete("/api/community/replies/{reply_id}")
async def delete_community_reply(
    reply_id: str,
    current_user=Depends(require_role("student", "teacher", "administrator")),
):
    replies = load_community_replies()
    reply = next((item for item in replies if item.get("id") == reply_id), None)
    if not reply:
        raise HTTPException(status_code=404, detail="الرد غير موجود")
    find_accessible_community_post(current_user, reply["postId"], include_hidden=True)
    is_owner = reply.get("authorId") == current_user["id"]
    is_moderator = current_user.get("role") == "administrator" or (
        current_user.get("role") == "teacher"
        and can_access_community_post(current_user, find_accessible_community_post(current_user, reply["postId"], include_hidden=True))
    )
    if not is_owner and not is_moderator:
        raise HTTPException(status_code=403, detail="لا يمكنك حذف هذا الرد")
    reply["status"] = "deleted"
    reply["updatedAt"] = datetime.now(timezone.utc).isoformat()
    save_json_list(COMMUNITY_REPLIES_FILE, replies)
    return {"success": True}


@app.post("/api/community/posts/{post_id}/like")
async def toggle_community_like(
    post_id: str,
    current_user=Depends(require_role("student", "teacher")),
):
    post = find_accessible_community_post(current_user, post_id)
    posts = load_community_posts()
    stored_post = next(item for item in posts if item["id"] == post_id)
    likes = stored_post.setdefault("likesBy", [])
    if current_user["id"] in likes:
        likes.remove(current_user["id"])
        liked = False
    else:
        likes.append(current_user["id"])
        liked = True
    save_json_list(COMMUNITY_POSTS_FILE, posts)
    return {"success": True, "liked": liked, "likeCount": len(likes)}


@app.post("/api/community/posts/{post_id}/reports")
async def report_community_post(
    post_id: str,
    report_request: CommunityReportCreate,
    current_user=Depends(require_role("student", "teacher")),
):
    post = find_accessible_community_post(current_user, post_id)
    if post.get("authorId") == current_user["id"]:
        raise HTTPException(status_code=400, detail="لا يمكنك الإبلاغ عن منشورك")
    reason = report_request.reason.strip()
    if not reason or len(reason) > 1000:
        raise HTTPException(status_code=400, detail="سبب الإبلاغ مطلوب")
    reports = load_reports()
    existing = next((item for item in reports if item.get("postId") == post_id and item.get("reporterId") == current_user["id"] and item.get("status") == "open"), None)
    if existing:
        raise HTTPException(status_code=409, detail="سبق إرسال بلاغ عن هذا المنشور")
    report = {
        "id": secrets.token_hex(8),
        "postId": post_id,
        "reporterId": current_user["id"],
        "reason": reason,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "status": "open",
        "resolvedBy": None,
        "resolvedAt": None,
        "resolution": None,
    }
    reports.append(report)
    save_json_list(REPORTS_FILE, reports)
    for administrator in load_students():
        if administrator.get("role") == "administrator":
            create_notification(administrator["id"], f"community_report:{report['id']}", "community_report", "Community report created", "A community post was reported.", "report", report["id"], "warning")
    return {"success": True, "report": {"id": report["id"], "status": report["status"]}}


@app.post("/api/community/posts/{post_id}/moderate")
async def moderate_community_post(
    post_id: str,
    moderation: CommunityModeration,
    current_user=Depends(require_role("teacher", "administrator")),
):
    post = find_accessible_community_post(current_user, post_id, include_hidden=True)
    if current_user.get("role") == "teacher" and not can_access_community_post(current_user, post):
        raise HTTPException(status_code=403, detail="لا يمكنك الإشراف على منطقة النقاش هذه")
    posts = load_community_posts()
    stored_post = next(item for item in posts if item["id"] == post_id)
    stored_post["status"] = "hidden" if moderation.action == "hide" else "visible"
    stored_post["moderatedBy"] = current_user["id"]
    stored_post["updatedAt"] = datetime.now(timezone.utc).isoformat()
    save_json_list(COMMUNITY_POSTS_FILE, posts)
    return {"success": True, "status": stored_post["status"]}


@app.get("/api/admin/community/reports")
async def admin_community_reports(current_user=Depends(require_role("administrator"))):
    posts = {item["id"]: item for item in load_community_posts()}
    users = {item["id"]: item for item in load_students()}
    reports = []
    for report in load_reports():
        post = posts.get(report.get("postId"))
        reporter = users.get(report.get("reporterId"))
        reports.append({
            **report,
            "post": public_community_post(post, current_user) if post else None,
            "reporter": {"id": reporter["id"], "fullName": reporter["fullName"]} if reporter else None,
        })
    reports.sort(key=lambda item: item.get("createdAt") or "", reverse=True)
    return {"reports": reports, "openCount": sum(1 for item in reports if item.get("status") == "open")}


@app.post("/api/admin/community/reports/{report_id}/resolve")
async def resolve_community_report(
    report_id: str,
    resolution: CommunityReportResolve,
    current_user=Depends(require_role("administrator")),
):
    reports = load_reports()
    report = next((item for item in reports if item.get("id") == report_id), None)
    if not report:
        raise HTTPException(status_code=404, detail="البلاغ غير موجود")
    if report["status"] != "open":
        raise HTTPException(status_code=409, detail="تمت معالجة هذا البلاغ مسبقًا")
    if resolution.action in ("hide", "restore"):
        posts = load_community_posts()
        post = next((item for item in posts if item.get("id") == report.get("postId")), None)
        if post:
            post["status"] = "hidden" if resolution.action == "hide" else "visible"
            post["moderatedBy"] = current_user["id"]
            post["updatedAt"] = datetime.now(timezone.utc).isoformat()
            save_json_list(COMMUNITY_POSTS_FILE, posts)
    report.update({
        "status": "resolved",
        "resolution": resolution.action,
        "resolvedBy": current_user["id"],
        "resolvedAt": datetime.now(timezone.utc).isoformat(),
    })
    save_json_list(REPORTS_FILE, reports)
    return {"success": True, "report": report}


def social_user_summary(user):
    return {"id": user["id"], "fullName": user["fullName"], "role": user.get("role", "student")}


def messaging_contacts(current_user):
    role = current_user.get("role", "student")
    contacts = []
    users_by_id = {user["id"]: user for user in load_students()}
    if role == "student":
        for class_record in load_classes():
            class_item = normalize_class(class_record)
            if class_item.get("status") == "cancelled" or not class_is_assigned_to_student(class_record, current_user):
                continue
            teacher = users_by_id.get(class_item.get("teacherId"))
            if teacher and teacher.get("role") == "teacher":
                contacts.append({"user": social_user_summary(teacher), "classId": class_item["id"], "classTitle": class_item["title"]})
    elif role == "teacher":
        for class_record in load_classes():
            class_item = normalize_class(class_record)
            if class_item.get("teacherId") != current_user["id"] or class_item.get("status") == "cancelled":
                continue
            for student in users_by_id.values():
                if student.get("role", "student") == "student" and class_is_assigned_to_student(class_record, student):
                    contacts.append({"user": social_user_summary(student), "classId": class_item["id"], "classTitle": class_item["title"]})
    elif role == "administrator":
        for staff in users_by_id.values():
            if staff.get("role") == "teacher":
                contacts.append({"user": social_user_summary(staff), "classId": None, "classTitle": None})

    unique = {}
    for contact in contacts:
        key = (contact["user"]["id"], contact.get("classId"))
        unique[key] = contact
    return list(unique.values())


def conversation_summary(conversation, current_user, messages, users):
    thread_messages = [message for message in messages if message.get("conversationId") == conversation["id"]]
    other_participants = [
        social_user_summary(users[participant_id])
        for participant_id in conversation.get("participantIds", [])
        if participant_id != current_user["id"] and participant_id in users
    ]
    unread_count = sum(
        1 for message in thread_messages
        if message.get("senderId") != current_user["id"]
        and current_user["id"] not in message.get("readBy", [])
    )
    last_message = max(thread_messages, key=lambda item: item.get("createdAt") or "", default=None)
    return {
        "id": conversation["id"],
        "type": conversation["type"],
        "classId": conversation.get("classId"),
        "createdAt": conversation.get("createdAt"),
        "lastMessageAt": last_message.get("createdAt") if last_message else conversation.get("createdAt"),
        "lastMessage": last_message.get("content") if last_message else "",
        "unreadCount": unread_count,
        "participants": other_participants,
    }


@app.get("/api/messaging/contacts")
async def get_messaging_contacts(current_user=Depends(require_role("student", "teacher", "administrator"))):
    return {"contacts": messaging_contacts(current_user)}


@app.get("/api/conversations")
async def list_conversations(current_user=Depends(require_role("student", "teacher", "administrator"))):
    users = {user["id"]: user for user in load_students()}
    messages = load_messages()
    conversations = [
        conversation_summary(item, current_user, messages, users)
        for item in load_conversations()
        if user_can_access_conversation(current_user, item)
    ]
    conversations.sort(key=lambda item: item.get("lastMessageAt") or "", reverse=True)
    return {"conversations": conversations, "unreadCount": sum(item["unreadCount"] for item in conversations)}


@app.post("/api/conversations")
async def start_conversation(
    request: ConversationCreate,
    current_user=Depends(require_role("student", "teacher", "administrator")),
):
    role = current_user.get("role", "student")
    class_id = None
    if role == "student":
        if not request.classId:
            raise HTTPException(status_code=400, detail="اختر حصة مشتركة لبدء المحادثة")
        class_record = next((item for item in load_classes() if item.get("id") == request.classId), None)
        if not class_record or normalize_class(class_record).get("status") == "cancelled" or not class_is_assigned_to_student(class_record, current_user):
            raise HTTPException(status_code=403, detail="لا يمكنك مراسلة معلم غير مرتبط بحصصك")
        teacher_id = normalize_class(class_record).get("teacherId")
        recipient = find_student(teacher_id)
        if not recipient or recipient.get("role") != "teacher":
            raise HTTPException(status_code=404, detail="المعلم غير موجود")
        class_id = request.classId
        conversation_type = "student_teacher"
    elif role == "teacher":
        if not request.classId or not request.studentId:
            raise HTTPException(status_code=400, detail="اختر طالبًا وحصة مشتركة")
        class_record = next((item for item in load_classes() if item.get("id") == request.classId), None)
        recipient = find_student(request.studentId)
        if not class_record or normalize_class(class_record).get("teacherId") != current_user["id"] or normalize_class(class_record).get("status") == "cancelled":
            raise HTTPException(status_code=403, detail="لا يمكنك بدء محادثة من حصة لا تديرها")
        if not recipient or not class_is_assigned_to_student(class_record, recipient):
            raise HTTPException(status_code=403, detail="الطالب غير مرتبط بهذه الحصة")
        class_id = request.classId
        conversation_type = "student_teacher"
    else:
        if not request.staffUserId:
            raise HTTPException(status_code=400, detail="اختر عضوًا من فريق العمل")
        recipient = find_student(request.staffUserId)
        if not recipient or recipient.get("role") != "teacher" or recipient["id"] == current_user["id"]:
            raise HTTPException(status_code=403, detail="يمكن للإدارة بدء محادثة مع المعلمين فقط")
        conversation_type = "admin_staff"

    participants = sorted([current_user["id"], recipient["id"]])
    conversations = load_conversations()
    existing = next((
        item for item in conversations
        if item.get("type") == conversation_type
        and item.get("classId") == class_id
        and item.get("participantIds") == participants
    ), None)
    if existing:
        return {"conversation": conversation_summary(existing, current_user, load_messages(), {user["id"]: user for user in load_students()})}

    conversation = {
        "id": secrets.token_hex(8),
        "type": conversation_type,
        "participantIds": participants,
        "classId": class_id,
        "createdBy": current_user["id"],
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    conversations.append(conversation)
    save_json_list(CONVERSATIONS_FILE, conversations)
    return {"conversation": conversation_summary(conversation, current_user, [], {user["id"]: user for user in load_students()})}


@app.get("/api/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    current_user=Depends(require_role("student", "teacher", "administrator")),
):
    conversation = find_conversation(conversation_id, current_user)
    messages = load_messages()
    updated = False
    thread = []
    users = {user["id"]: user for user in load_students()}
    for message in messages:
        if message.get("conversationId") != conversation_id:
            continue
        if message.get("senderId") != current_user["id"] and current_user["id"] not in message.setdefault("readBy", []):
            message["readBy"].append(current_user["id"])
            updated = True
        thread.append({
            **public_message(message, users, current_user["id"]),
            "mine": message.get("senderId") == current_user["id"],
            "readByOthers": any(user_id != message.get("senderId") for user_id in message.get("readBy", [])),
        })
    if updated:
        save_json_list(MESSAGES_FILE, messages)
    thread.sort(key=lambda item: item.get("createdAt") or "")
    return {
        "conversation": conversation_summary(conversation, current_user, messages, users),
        "messages": thread,
    }


@app.post("/api/conversations/{conversation_id}/messages")
async def send_conversation_message(
    conversation_id: str,
    message_request: MessageCreate,
    current_user=Depends(require_role("student", "teacher", "administrator")),
):
    conversation = find_conversation(conversation_id, current_user)
    content = message_request.content.strip()
    if not content or len(content) > 8000:
        raise HTTPException(status_code=400, detail="نص الرسالة مطلوب وبطول صالح")
    message = {
        "id": secrets.token_hex(8),
        "conversationId": conversation_id,
        "senderId": current_user["id"],
        "content": content,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "readBy": [current_user["id"]],
    }
    messages = load_messages()
    messages.append(message)
    save_json_list(MESSAGES_FILE, messages)
    recipient_ids = [participant_id for participant_id in conversation.get("participantIds", []) if participant_id != current_user["id"]]
    users = {user["id"]: user for user in load_students()}
    for recipient_id in recipient_ids:
        create_notification(recipient_id, f"message:{message['id']}", "new_message", "New message", f"New message from {current_user.get('fullName', 'Fluent Path user')}.", "conversation", conversation_id)
    return {"success": True, "message": {**public_message(message, users, current_user["id"]), "mine": True, "readByOthers": False}}


@app.get("/api/admin/dashboard")
async def admin_dashboard(current_user=Depends(require_role("administrator"))):
    users = load_students()
    recent_users = sorted(
        (admin_user_view(user) for user in users),
        key=lambda user: user.get("createdAt") or "",
        reverse=True,
    )[:5]
    total_completed_lessons = sum(
        len(lesson_ids)
        for user in users
        for lesson_ids in [
            progress.get("completedLessons", [])
            for progress in user.get("courseProgress", {}).values()
        ]
    )
    return {
        "role": current_user["role"],
        "currentUser": self_user_view(current_user),
        "totalStudents": len([user for user in users if user.get("role") == "student"]),
        "totalTeachers": len([user for user in users if user.get("role") == "teacher"]),
        "totalAdministrators": len([user for user in users if user.get("role") == "administrator"]),
        "totalCourses": len(load_courses()),
        "totalHomework": len(load_homework()),
        "totalCompletedLessons": total_completed_lessons,
        "recentUsers": recent_users,
        "message": "Administrator dashboard MVP",
    }


@app.get("/api/admin/users")
async def admin_users(current_user=Depends(require_role("administrator"))):
    del current_user
    return {"users": [admin_user_view(user) for user in load_students()]}


@app.get("/api/admin/courses")
async def admin_courses(current_user=Depends(require_role("administrator"))):
    del current_user
    courses = load_admin_courses_with_legacy_migration()
    ordered_courses = sorted(enumerate(courses), key=lambda pair: (pair[1].get("order", pair[0] + 1), pair[0]))
    return {
        "courses": [
            {
                **public_course(course),
                "lessons": course.get("lessons", []),
                "active": course_is_active(course),
                "order": course.get("order", index + 1),
            }
            for index, course in ordered_courses
        ]
    }


@app.get("/api/teacher/meeting-options")
async def teacher_meeting_options(current_user=Depends(require_role("teacher"))):
    return {"zoomConfigured": zoom_service.is_configured()}


@app.post("/api/teacher/classes/{class_id}/zoom-start")
async def teacher_zoom_start_url(class_id: str, current_user=Depends(require_role("teacher"))):
    classes, class_index = find_teacher_class(class_id, current_user["id"])
    class_item = normalize_class(classes[class_index])
    if class_item.get("meetingProvider") != "zoom" or not class_item.get("zoomMeetingId"):
        raise HTTPException(status_code=400, detail="This class does not have a connected Zoom meeting")
    if class_item.get("status") == "cancelled":
        raise HTTPException(status_code=400, detail="This class is cancelled")
    try:
        links = await asyncio.to_thread(zoom_service.get_meeting, class_item["zoomMeetingId"])
    except zoom_service.ZoomError as error:
        raise_zoom_http_error(error)
    classes[class_index].update(links)
    classes[class_index]["zoomStartUrlRefreshedAt"] = datetime.now(timezone.utc).isoformat()
    save_json_list(CLASSES_FILE, classes)
    return {"startUrl": links["teacherJoinUrl"]}


def raise_zoom_http_error(error):
    raise HTTPException(status_code=error.status_code, detail=str(error)) from error


def find_admin_course(courses, course_id):
    course = next((item for item in courses if item.get("id") == course_id), None)
    if course is None:
        raise HTTPException(status_code=404, detail="الدورة غير موجودة")
    return course


def load_admin_courses_with_legacy_migration():
    """Add CMS metadata to legacy catalog records without changing IDs or progress."""
    courses = load_courses()
    changed = False
    migration_time = datetime.now(timezone.utc).isoformat()
    for course_index, course in enumerate(courses, start=1):
        if "active" not in course:
            course["active"] = course.get("status") != "inactive"
            changed = True
        if "order" not in course:
            course["order"] = course_index
            changed = True
        if "lessons" not in course:
            course["lessons"] = []
            changed = True
        for lesson_index, lesson in enumerate(course["lessons"], start=1):
            defaults = {
                "course_id": course["id"], "description": "", "descriptionAr": "",
                "order": lesson.get("number", lesson_index), "estimated_minutes": 15,
                "published": True, "archived": False,
                "created_at": course.get("created_at") or course.get("createdAt") or migration_time,
                "updated_at": course.get("updated_at") or course.get("updatedAt") or migration_time,
            }
            for key, value in defaults.items():
                if key not in lesson:
                    lesson[key] = value
                    changed = True
            if "number" not in lesson:
                lesson["number"] = lesson["order"]
                changed = True
            if "content" not in lesson:
                lesson["content"] = {"explanation": ""}
                changed = True
            elif isinstance(lesson["content"], str):
                lesson["content"] = {"explanation": lesson["content"]}
                changed = True
    if changed:
        save_json_list(COURSES_FILE, courses)
    return courses


def validated_course_rank(level):
    rank = COURSE_LEVEL_RANKS.get(level)
    if rank is None:
        raise HTTPException(status_code=400, detail="مستوى CEFR غير صالح")
    return rank


@app.post("/api/admin/courses")
async def create_admin_course(course_request: AdminCourseInput, current_user=Depends(require_role("administrator"))):
    title = course_request.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="عنوان الدورة مطلوب")
    rank = validated_course_rank(course_request.level)
    courses = load_admin_courses_with_legacy_migration()
    course_id = f"course-{secrets.token_hex(6)}"
    order = course_request.order if course_request.order is not None else len(courses) + 1
    course = {
        "id": course_id, "type": "cefr", "level": course_request.level,
        "requiredRank": rank, "title": title, "titleAr": course_request.titleAr.strip(),
        "description": course_request.description.strip(), "descriptionAr": course_request.descriptionAr.strip(),
        "active": False, "order": order, "lessons": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    courses.append(course)
    save_json_list(COURSES_FILE, courses)
    return {"success": True, "course": course}


@app.get("/api/admin/courses/{course_id}")
async def get_admin_course(course_id: str, current_user=Depends(require_role("administrator"))):
    course = find_admin_course(load_admin_courses_with_legacy_migration(), course_id)
    return {"course": {**course, "active": course_is_active(course), "lessons": ordered_lessons(course, include_archived=True)}}


@app.put("/api/admin/courses/{course_id}")
async def update_admin_course(course_id: str, course_request: AdminCourseInput, current_user=Depends(require_role("administrator"))):
    courses = load_admin_courses_with_legacy_migration()
    course = find_admin_course(courses, course_id)
    if course.get("type") != "cefr":
        raise HTTPException(status_code=400, detail="لا يمكن تعديل محتوى برنامج غير منشور ضمن إدارة مسارات CEFR")
    title = course_request.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="عنوان الدورة مطلوب")
    course.update({
        "title": title, "titleAr": course_request.titleAr.strip(),
        "description": course_request.description.strip(), "descriptionAr": course_request.descriptionAr.strip(),
        "level": course_request.level, "requiredRank": validated_course_rank(course_request.level),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    if course_request.order is not None:
        course["order"] = course_request.order
    save_json_list(COURSES_FILE, courses)
    return {"success": True, "course": course}


@app.patch("/api/admin/courses/{course_id}/status")
async def update_admin_course_status(course_id: str, course_status: AdminCourseStatus, current_user=Depends(require_role("administrator"))):
    courses = load_admin_courses_with_legacy_migration()
    course = find_admin_course(courses, course_id)
    course["active"] = course_status.active
    course["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_json_list(COURSES_FILE, courses)
    return {"success": True, "active": course["active"]}


@app.get("/api/admin/courses/{course_id}/lessons")
async def get_admin_course_lessons(course_id: str, current_user=Depends(require_role("administrator"))):
    course = find_admin_course(load_admin_courses_with_legacy_migration(), course_id)
    return {"lessons": ordered_lessons(course, include_archived=True)}


@app.post("/api/admin/courses/{course_id}/lessons")
async def create_admin_lesson(course_id: str, lesson_request: AdminLessonInput, current_user=Depends(require_role("administrator"))):
    courses = load_admin_courses_with_legacy_migration()
    course = find_admin_course(courses, course_id)
    if course.get("type") != "cefr":
        raise HTTPException(status_code=400, detail="الدروس متاحة لمسارات CEFR فقط")
    now = datetime.now(timezone.utc).isoformat()
    order = max((int(item.get("order", item.get("number", 0))) for item in course.get("lessons", [])), default=0) + 1
    lesson = {
        "id": f"lesson-{secrets.token_hex(6)}", "course_id": course_id,
        "title": lesson_request.title.strip(), "titleAr": lesson_request.titleAr.strip(),
        "description": lesson_request.description.strip(), "descriptionAr": lesson_request.descriptionAr.strip(),
        "order": order, "number": order, "content": lesson_request.content.model_dump(),
        "estimated_minutes": lesson_request.estimated_minutes,
        "published": False, "archived": False, "created_at": now, "updated_at": now,
    }
    course.setdefault("lessons", []).append(lesson)
    course["updated_at"] = now
    save_json_list(COURSES_FILE, courses)
    return {"success": True, "lesson": lesson}


def find_admin_lesson(course, lesson_id):
    lesson = next((item for item in course.get("lessons", []) if item.get("id") == lesson_id), None)
    if lesson is None:
        raise HTTPException(status_code=404, detail="الدرس غير موجود")
    if lesson.get("course_id", course["id"]) != course["id"]:
        raise HTTPException(status_code=400, detail="الدرس لا ينتمي إلى هذه الدورة")
    return lesson


@app.put("/api/admin/courses/{course_id}/lessons/{lesson_id}")
async def update_admin_lesson(course_id: str, lesson_id: str, lesson_request: AdminLessonInput, current_user=Depends(require_role("administrator"))):
    courses = load_admin_courses_with_legacy_migration()
    course = find_admin_course(courses, course_id)
    lesson = find_admin_lesson(course, lesson_id)
    lesson.update({
        "title": lesson_request.title.strip(), "titleAr": lesson_request.titleAr.strip(),
        "description": lesson_request.description.strip(), "descriptionAr": lesson_request.descriptionAr.strip(),
        "content": lesson_request.content.model_dump(), "estimated_minutes": lesson_request.estimated_minutes,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    save_json_list(COURSES_FILE, courses)
    return {"success": True, "lesson": lesson}


@app.patch("/api/admin/courses/{course_id}/lessons/{lesson_id}/status")
async def update_admin_lesson_status(course_id: str, lesson_id: str, lesson_status: AdminLessonStatus, current_user=Depends(require_role("administrator"))):
    if lesson_status.published is None and lesson_status.archived is None:
        raise HTTPException(status_code=400, detail="حدد حالة النشر أو الأرشفة")
    courses = load_admin_courses_with_legacy_migration()
    course = find_admin_course(courses, course_id)
    lesson = find_admin_lesson(course, lesson_id)
    if lesson_status.archived is not None:
        lesson["archived"] = lesson_status.archived
        if lesson_status.archived:
            lesson["published"] = False
        else:
            next_order = max((int(item.get("order", item.get("number", 0))) for item in course.get("lessons", []) if item is not lesson and not item.get("archived", False)), default=0) + 1
            lesson["order"] = next_order
            lesson["number"] = next_order
    if lesson_status.published is not None and not lesson.get("archived", False):
        lesson["published"] = lesson_status.published
    lesson["updated_at"] = datetime.now(timezone.utc).isoformat()
    course["updated_at"] = lesson["updated_at"]
    save_json_list(COURSES_FILE, courses)
    return {"success": True, "lesson": lesson}


@app.post("/api/admin/courses/{course_id}/lessons/reorder")
async def reorder_admin_lessons(course_id: str, reorder: LessonReorder, current_user=Depends(require_role("administrator"))):
    courses = load_admin_courses_with_legacy_migration()
    course = find_admin_course(courses, course_id)
    lessons = course.setdefault("lessons", [])
    reorderable = [item for item in lessons if not item.get("archived", False)]
    reorder_ids = reorder.lesson_ids
    if len(reorder_ids) != len(set(reorder_ids)) or set(reorder_ids) != {item["id"] for item in reorderable}:
        raise HTTPException(status_code=400, detail="يجب أن تتضمن القائمة كل الدروس غير المؤرشفة مرة واحدة")
    by_id = {item["id"]: item for item in lessons}
    now = datetime.now(timezone.utc).isoformat()
    for order, lesson_id in enumerate(reorder_ids, start=1):
        by_id[lesson_id]["order"] = order
        by_id[lesson_id]["number"] = order
        by_id[lesson_id]["updated_at"] = now
    course["lessons"] = sorted(lessons, key=lambda item: (item.get("order", item.get("number", 0)), item.get("id", "")))
    course["updated_at"] = now
    save_json_list(COURSES_FILE, courses)
    return {"success": True, "lessons": ordered_lessons(course, include_archived=True)}


@app.post("/api/test-results")
async def save_test_result(
    result: TestResult,
    current_user=Depends(require_role("student", allow_incomplete_placement=True)),
):
    students = load_students()

    student = None

    for existing_student in students:
        if existing_student["id"] == current_user["id"]:
            student = existing_student
            break

    if student is None:
        raise HTTPException(
            status_code=404,
            detail="الطالب غير موجود"
        )

    if any(answer not in range(4) for answer in result.answers):
        raise HTTPException(status_code=422, detail="إجابات الاختبار غير صالحة")

    if result.studentId and result.studentId != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="لا يمكنك حفظ نتيجة لطالب آخر",
        )

    score = sum(answer == correct for answer, correct in zip(result.answers, PLACEMENT_ANSWER_KEY))
    level = "A1" if score <= 1 else "A2 - B1" if score <= 3 else "B2 - C1"
    student["testScore"] = score
    student["totalQuestions"] = len(PLACEMENT_ANSWER_KEY)
    student["level"] = level
    student["testCompletedAt"] = datetime.now(
        timezone.utc
    ).isoformat()

    award_learning_action(student, "placement_test_completed", "placement_test_completed")

    save_students(students)

    return {
        "success": True,
        "message": "تم حفظ نتيجة الاختبار بنجاح",
        "result": {
            "studentId": current_user["id"],
            "score": score,
            "totalQuestions": len(PLACEMENT_ANSWER_KEY),
            "level": level,
        }
    }


@app.get("/api/courses")
async def list_courses(current_user=Depends(get_optional_user)):
    if current_user and current_user.get("role", "student") != "student":
        raise HTTPException(status_code=403, detail="هذه الدورات مخصصة للطلاب")

    courses = load_courses()
    ordered = sorted(enumerate(courses), key=lambda pair: (pair[1].get("order", pair[0] + 1), pair[0]))
    return {"courses": [public_course(course, current_user) for _, course in ordered if course_is_active(course)]}


@app.get("/api/courses/{course_id}")
async def get_course(
    course_id: str,
    current_user=Depends(get_optional_user),
):
    course = next(
        (course for course in load_courses() if course["id"] == course_id and course_is_active(course)),
        None,
    )

    if course is None:
        raise HTTPException(status_code=404, detail="الدورة غير موجودة")

    if current_user and current_user.get("role", "student") != "student":
        raise HTTPException(status_code=403, detail="هذه الدورات مخصصة للطلاب")

    if course["type"] == "future" or current_user is None:
        return public_course(course, current_user)

    if not course_is_available(course, current_user):
        raise HTTPException(
            status_code=403,
            detail="هذه الدورة غير متاحة لمستواك الحالي",
        )

    response = public_course(course, current_user)
    response["lessons"] = [
        {
            **lesson,
            "completed": lesson["id"] in response["progress"]["completedLessons"],
        }
        for lesson in ordered_lessons(course)
        if lesson_is_student_visible(lesson)
    ]
    return response


@app.get("/api/course-progress")
@app.get("/api/students/{student_id}/course-progress")
async def get_student_course_progress(
    student_id: Optional[str] = None,
    current_user=Depends(require_role("student")),
):
    if student_id and student_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="لا يمكنك الوصول إلى تقدم طالب آخر")

    student = current_user
    student_id = current_user["id"]

    if student is None:
        raise HTTPException(status_code=404, detail="الطالب غير موجود")

    return {
        "studentId": student_id,
        "courses": [
            {
                "courseId": course["id"],
                "progress": student_progress(student, course),
            }
            for course in load_courses()
            if course["type"] == "cefr" and course_is_active(course)
        ],
    }


@app.post("/api/me/courses/{course_id}/lessons/{lesson_id}/complete")
@app.post("/api/students/{student_id}/courses/{course_id}/lessons/{lesson_id}/complete")
async def complete_lesson(
    course_id: str,
    lesson_id: str,
    student_id: Optional[str] = None,
    current_user=Depends(require_role("student")),
):
    if student_id and student_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="لا يمكنك تعديل تقدم طالب آخر")

    student_id = current_user["id"]
    students = load_students()
    student = next(
        (student for student in students if student["id"] == student_id),
        None,
    )
    course = next(
        (course for course in load_courses() if course["id"] == course_id),
        None,
    )

    if student is None:
        raise HTTPException(status_code=404, detail="الطالب غير موجود")
    if course is None:
        raise HTTPException(status_code=404, detail="الدورة غير موجودة")
    if course["type"] != "cefr" or not course_is_available(course, student):
        raise HTTPException(
            status_code=403,
            detail="لا يمكنك إكمال دروس هذه الدورة حاليًا",
        )
    if not any(lesson["id"] == lesson_id and lesson_is_student_visible(lesson) for lesson in course.get("lessons", [])):
        raise HTTPException(status_code=404, detail="الدرس غير موجود")

    course_progress = student.setdefault("courseProgress", {})
    progress = course_progress.setdefault(
        course_id,
        {"completedLessons": [], "updatedAt": None},
    )
    previous_percentage = student_progress(student, course)["percentage"]
    first_completion = lesson_id not in progress["completedLessons"]
    if lesson_id not in progress["completedLessons"]:
        progress["completedLessons"].append(lesson_id)
    progress["updatedAt"] = datetime.now(timezone.utc).isoformat()
    if first_completion:
        previous_level = xp_level_progress(ensure_gamification(student)["xp"])["level"]
        previous_badges = [item.get("id") for item in ensure_gamification(student).get("earnedBadges", []) if isinstance(item, dict)]
        award_learning_action(
            student,
            f"lesson_completed:{course_id}:{lesson_id}",
            "lesson_completed",
            course_id=course_id,
        )
        # Notify a teacher who is connected to the learner through an active class.
        for class_record in load_classes():
            class_item = normalize_class(class_record)
            if class_item.get("status") != "cancelled" and class_is_assigned_to_student(class_record, student):
                create_notification(class_item.get("teacherId"), f"lesson:{student_id}:{course_id}:{lesson_id}", "lesson_completed", "Student completed a lesson", f"{student.get('fullName', 'A student')} completed a lesson.", "course", course_id)
        current_percentage = student_progress(student, course)["percentage"]
        for milestone in (25, 50, 75, 100):
            if previous_percentage < milestone <= current_percentage:
                create_notification(student_id, f"course_progress:{course_id}:{milestone}", "course_progress_milestone", "Course progress milestone", f"You completed {milestone}% of this course.", "course", course_id)
    save_students(students)

    return {
        "success": True,
        "courseId": course_id,
        "lessonId": lesson_id,
        "progress": student_progress(student, course),
    }


@app.get("/api/students/{student_id}")
async def get_student(student_id: str, current_user=Depends(get_current_user)):
    if current_user["id"] != student_id:
        raise HTTPException(status_code=403, detail="لا يمكنك الوصول إلى ملف طالب آخر")
    return self_user_view(current_user)
