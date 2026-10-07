"""Initial PostgreSQL schema for a gradual JSON-to-database transition."""

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    full_name: Mapped[str] = mapped_column(String(240), nullable=False)
    dev_only: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # NULL is reserved for imported legacy users whose historical creation time
    # is unknown. Application-created users must still provide an aware UTC time.
    created_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    __table_args__ = (CheckConstraint("role IN ('student','teacher','administrator')", name="ck_users_role"), Index("ix_users_role_created", "role", "created_at"))


class StudentProfile(Base):
    __tablename__ = "student_profiles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    date_of_birth: Mapped[object | None] = mapped_column(Date)
    phone: Mapped[str | None] = mapped_column(String(64))
    level: Mapped[str | None] = mapped_column(String(8))
    test_score: Mapped[int | None] = mapped_column(Integer)
    total_questions: Mapped[int | None] = mapped_column(Integer)
    test_completed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    legacy_course_progress: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    legacy_gamification: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    title_ar: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    description_ar: Mapped[str | None] = mapped_column(Text)
    level: Mapped[str | None] = mapped_column(String(8))
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    required_rank: Mapped[int | None] = mapped_column(Integer)
    legacy_fields: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    updated_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    __table_args__ = (Index("ix_courses_active_order", "active", "display_order"), Index("ix_courses_level", "level"))


class Lesson(Base):
    __tablename__ = "lessons"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    number: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    title_ar: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    description_ar: Mapped[str | None] = mapped_column(Text)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    estimated_minutes: Mapped[int | None] = mapped_column(Integer)
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (Index("ix_lessons_course_order", "course_id", "display_order"), Index("ix_lessons_course_published", "course_id", "published"))


class LessonCompletion(Base):
    __tablename__ = "lesson_completions"
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), primary_key=True)
    completed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)


class Homework(Base):
    __tablename__ = "homework"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    level: Mapped[str | None] = mapped_column(String(8))
    due_date: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (Index("ix_homework_teacher_created", "teacher_id", "created_at"), Index("ix_homework_course", "course_id"))


class HomeworkAssignment(Base):
    __tablename__ = "homework_assignments"
    homework_id: Mapped[str] = mapped_column(ForeignKey("homework.id", ondelete="CASCADE"), primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class HomeworkSubmission(Base):
    __tablename__ = "homework_submissions"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    homework_id: Mapped[str] = mapped_column(ForeignKey("homework.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    grade: Mapped[float | None] = mapped_column(Numeric(6, 2))
    teacher_feedback: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    graded_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("homework_id", "student_id", name="uq_submission_homework_student"), Index("ix_submissions_student_submitted", "student_id", "submitted_at"))


class ClassRecord(Base):
    __tablename__ = "classes"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    starts_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    meeting_provider: Mapped[str] = mapped_column(String(24), nullable=False, server_default="none")
    meeting_url: Mapped[str | None] = mapped_column(Text)
    teacher_join_url: Mapped[str | None] = mapped_column(Text)
    student_join_url: Mapped[str | None] = mapped_column(Text)
    zoom_meeting_id: Mapped[str | None] = mapped_column(String(128))
    legacy_fields: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (Index("ix_classes_teacher_start", "teacher_id", "starts_at"), Index("ix_classes_course", "course_id"))


class ClassStudent(Base):
    __tablename__ = "class_students"
    class_id: Mapped[str] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class CommunityPost(Base):
    __tablename__ = "community_posts"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id", ondelete="SET NULL"))
    class_id: Mapped[str | None] = mapped_column(ForeignKey("classes.id", ondelete="SET NULL"))
    title: Mapped[str | None] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("scope IN ('general','course','class')", name="ck_community_post_scope"), Index("ix_community_posts_scope_created", "scope", "created_at"))


class CommunityPostLike(Base):
    __tablename__ = "community_post_likes"
    post_id: Mapped[str] = mapped_column(ForeignKey("community_posts.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CommunityReply(Base):
    __tablename__ = "community_replies"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    post_id: Mapped[str] = mapped_column(ForeignKey("community_posts.id", ondelete="CASCADE"), nullable=False)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_community_replies_post_created", "post_id", "created_at"),)


class CommunityReport(Base):
    __tablename__ = "community_reports"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    post_id: Mapped[str] = mapped_column(ForeignKey("community_posts.id", ondelete="CASCADE"), nullable=False)
    reporter_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    resolution: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    __table_args__ = (
        Index("ix_community_reports_status_created", "status", "created_at"),
        Index("uq_open_community_report", "post_id", "reporter_id", unique=True, postgresql_where=(status == "open")),
    )


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    type: Mapped[str] = mapped_column(String(24), nullable=False)
    class_id: Mapped[str | None] = mapped_column(ForeignKey("classes.id", ondelete="SET NULL"))
    scope_key: Mapped[str] = mapped_column(String(128), nullable=False, server_default="")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    pair_key: Mapped[str] = mapped_column(String(260), nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("type", "scope_key", "pair_key", name="uq_conversation_type_scope_pair"), Index("ix_conversations_created", "created_at"))


class ConversationParticipant(Base):
    __tablename__ = "conversation_participants"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    sender_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"), Index("ix_messages_sender_created", "sender_id", "created_at"))


class MessageRead(Base):
    __tablename__ = "message_reads"
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    read_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    recipient_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_key: Mapped[str] = mapped_column(String(300), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    related_entity_type: Mapped[str | None] = mapped_column(String(64))
    related_entity_id: Mapped[str | None] = mapped_column(String(128))
    severity: Mapped[str] = mapped_column(String(24), nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("recipient_user_id", "event_key", name="uq_notifications_recipient_event"), Index("ix_notifications_recipient_created", "recipient_user_id", "created_at"), Index("ix_notifications_unread", "recipient_user_id", "created_at", postgresql_where=(is_read == False)))


class AISession(Base):
    __tablename__ = "ai_sessions"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    cefr_level: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("id", "student_id", name="uq_ai_session_id_owner"), Index("ix_ai_sessions_student_created", "student_id", "created_at"))


class AIMessage(Base):
    __tablename__ = "ai_messages"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    feedback: Mapped[str | None] = mapped_column(Text)
    score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    corrections: Mapped[list | None] = mapped_column(JSONB)
    next_step: Mapped[str | None] = mapped_column(Text)
    structured_feedback: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    xp_awarded: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (ForeignKeyConstraint(["session_id", "student_id"], ["ai_sessions.id", "ai_sessions.student_id"], ondelete="CASCADE", name="fk_ai_messages_session_owner"), Index("ix_ai_messages_session_created", "session_id", "created_at"), Index("ix_ai_messages_student_created", "student_id", "created_at"))


class AIUsageEvent(Base):
    __tablename__ = "ai_usage_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (Index("ix_ai_usage_student_created", "student_id", "created_at"),)


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"
    token_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (Index("ix_revoked_tokens_expiry", "expires_at"),)


class GamificationState(Base):
    __tablename__ = "gamification_state"
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    xp: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    current_streak: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    longest_streak: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_activity_date: Mapped[object | None] = mapped_column(Date)


class UserBadge(Base):
    __tablename__ = "user_badges"
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    badge_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    earned_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class GamificationAction(Base):
    __tablename__ = "gamification_actions"
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    action_key: Mapped[str] = mapped_column(String(300), primary_key=True)
    xp_awarded: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class AlembicVersionPlaceholder:
    """Marker only; Alembic creates alembic_version itself."""
