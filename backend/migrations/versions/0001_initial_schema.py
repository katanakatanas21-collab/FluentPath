"""Initial PostgreSQL schema foundation, frozen as DDL.

Revision ID: 0001_initial_schema
Revises:
"""
from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_STATEMENTS = [
    "CREATE TABLE courses (\n\tid VARCHAR(128) NOT NULL, \n\ttitle VARCHAR(300) NOT NULL, \n\ttitle_ar VARCHAR(300), \n\tdescription TEXT, \n\tdescription_ar TEXT, \n\tlevel VARCHAR(8), \n\ttype VARCHAR(32) NOT NULL, \n\tactive BOOLEAN DEFAULT 'true' NOT NULL, \n\tdisplay_order INTEGER DEFAULT '0' NOT NULL, \n\trequired_rank INTEGER, \n\tlegacy_fields JSONB DEFAULT '{}' NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id)\n)",
    'CREATE INDEX ix_courses_active_order ON courses (active, display_order)',
    'CREATE INDEX ix_courses_level ON courses (level)',
    "CREATE TABLE users (\n\tid VARCHAR(128) NOT NULL, \n\temail VARCHAR(320) NOT NULL, \n\tpassword_hash TEXT NOT NULL, \n\trole VARCHAR(24) NOT NULL, \n\tfull_name VARCHAR(240) NOT NULL, \n\tdev_only BOOLEAN DEFAULT 'false' NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_users_role CHECK (role IN ('student','teacher','administrator')), \n\tUNIQUE (email)\n)",
    'CREATE INDEX ix_users_role_created ON users (role, created_at)',
    'CREATE TABLE ai_sessions (\n\tid VARCHAR(128) NOT NULL, \n\tstudent_id VARCHAR(128) NOT NULL, \n\tmode VARCHAR(32) NOT NULL, \n\tcefr_level VARCHAR(8), \n\tstatus VARCHAR(24) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcompleted_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_ai_session_id_owner UNIQUE (id, student_id), \n\tFOREIGN KEY(student_id) REFERENCES users (id) ON DELETE CASCADE\n)',
    'CREATE INDEX ix_ai_sessions_student_created ON ai_sessions (student_id, created_at)',
    'CREATE TABLE ai_usage_events (\n\tid SERIAL NOT NULL, \n\tstudent_id VARCHAR(128) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(student_id) REFERENCES users (id) ON DELETE CASCADE\n)',
    'CREATE INDEX ix_ai_usage_student_created ON ai_usage_events (student_id, created_at)',
    "CREATE TABLE classes (\n\tid VARCHAR(128) NOT NULL, \n\tteacher_id VARCHAR(128) NOT NULL, \n\tcourse_id VARCHAR(128), \n\ttitle VARCHAR(300) NOT NULL, \n\tstarts_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tduration_minutes INTEGER, \n\tstatus VARCHAR(24) NOT NULL, \n\tmeeting_provider VARCHAR(24) DEFAULT 'none' NOT NULL, \n\tmeeting_url TEXT, \n\tteacher_join_url TEXT, \n\tstudent_join_url TEXT, \n\tzoom_meeting_id VARCHAR(128), \n\tlegacy_fields JSONB DEFAULT '{}' NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(teacher_id) REFERENCES users (id), \n\tFOREIGN KEY(course_id) REFERENCES courses (id) ON DELETE SET NULL\n)",
    'CREATE INDEX ix_classes_course ON classes (course_id)',
    'CREATE INDEX ix_classes_teacher_start ON classes (teacher_id, starts_at)',
    'CREATE TABLE gamification_actions (\n\tstudent_id VARCHAR(128) NOT NULL, \n\taction_key VARCHAR(300) NOT NULL, \n\txp_awarded INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (student_id, action_key), \n\tFOREIGN KEY(student_id) REFERENCES users (id) ON DELETE CASCADE\n)',
    "CREATE TABLE gamification_state (\n\tstudent_id VARCHAR(128) NOT NULL, \n\txp INTEGER DEFAULT '0' NOT NULL, \n\tcurrent_streak INTEGER DEFAULT '0' NOT NULL, \n\tlongest_streak INTEGER DEFAULT '0' NOT NULL, \n\tlast_activity_date DATE, \n\tPRIMARY KEY (student_id), \n\tFOREIGN KEY(student_id) REFERENCES users (id) ON DELETE CASCADE\n)",
    "CREATE TABLE homework (\n\tid VARCHAR(128) NOT NULL, \n\tcreated_by VARCHAR(128) NOT NULL, \n\tteacher_id VARCHAR(128) NOT NULL, \n\tcourse_id VARCHAR(128), \n\ttitle VARCHAR(300) NOT NULL, \n\tdescription TEXT DEFAULT '' NOT NULL, \n\tlevel VARCHAR(8), \n\tdue_date TIMESTAMP WITH TIME ZONE, \n\tstatus VARCHAR(24) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(created_by) REFERENCES users (id), \n\tFOREIGN KEY(teacher_id) REFERENCES users (id), \n\tFOREIGN KEY(course_id) REFERENCES courses (id) ON DELETE SET NULL\n)",
    'CREATE INDEX ix_homework_course ON homework (course_id)',
    'CREATE INDEX ix_homework_teacher_created ON homework (teacher_id, created_at)',
    "CREATE TABLE lessons (\n\tid VARCHAR(128) NOT NULL, \n\tcourse_id VARCHAR(128) NOT NULL, \n\tnumber INTEGER, \n\ttitle VARCHAR(300) NOT NULL, \n\ttitle_ar VARCHAR(300), \n\tdescription TEXT, \n\tdescription_ar TEXT, \n\tcontent JSONB DEFAULT '{}' NOT NULL, \n\tdisplay_order INTEGER DEFAULT '0' NOT NULL, \n\testimated_minutes INTEGER, \n\tpublished BOOLEAN DEFAULT 'false' NOT NULL, \n\tarchived BOOLEAN DEFAULT 'false' NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(course_id) REFERENCES courses (id) ON DELETE CASCADE\n)",
    'CREATE INDEX ix_lessons_course_order ON lessons (course_id, display_order)',
    'CREATE INDEX ix_lessons_course_published ON lessons (course_id, published)',
    "CREATE TABLE notifications (\n\tid VARCHAR(128) NOT NULL, \n\trecipient_user_id VARCHAR(128) NOT NULL, \n\tevent_key VARCHAR(300) NOT NULL, \n\ttype VARCHAR(64) NOT NULL, \n\ttitle VARCHAR(300) NOT NULL, \n\tmessage TEXT NOT NULL, \n\trelated_entity_type VARCHAR(64), \n\trelated_entity_id VARCHAR(128), \n\tseverity VARCHAR(24) NOT NULL, \n\tis_read BOOLEAN DEFAULT 'false' NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_notifications_recipient_event UNIQUE (recipient_user_id, event_key), \n\tFOREIGN KEY(recipient_user_id) REFERENCES users (id) ON DELETE CASCADE\n)",
    'CREATE INDEX ix_notifications_recipient_created ON notifications (recipient_user_id, created_at)',
    'CREATE INDEX ix_notifications_unread ON notifications (recipient_user_id, created_at) WHERE is_read = false',
    'CREATE TABLE revoked_tokens (\n\ttoken_id VARCHAR(128) NOT NULL, \n\tuser_id VARCHAR(128) NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\trevoked_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (token_id), \n\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE\n)',
    'CREATE INDEX ix_revoked_tokens_expiry ON revoked_tokens (expires_at)',
    "CREATE TABLE student_profiles (\n\tuser_id VARCHAR(128) NOT NULL, \n\tdate_of_birth DATE, \n\tphone VARCHAR(64), \n\tlevel VARCHAR(8), \n\ttest_score INTEGER, \n\ttotal_questions INTEGER, \n\ttest_completed_at TIMESTAMP WITH TIME ZONE, \n\tlegacy_course_progress JSONB DEFAULT '{}' NOT NULL, \n\tlegacy_gamification JSONB DEFAULT '{}' NOT NULL, \n\tPRIMARY KEY (user_id), \n\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE\n)",
    'CREATE TABLE user_badges (\n\tstudent_id VARCHAR(128) NOT NULL, \n\tbadge_id VARCHAR(100) NOT NULL, \n\tearned_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (student_id, badge_id), \n\tFOREIGN KEY(student_id) REFERENCES users (id) ON DELETE CASCADE\n)',
    "CREATE TABLE ai_messages (\n\tid VARCHAR(128) NOT NULL, \n\tsession_id VARCHAR(128) NOT NULL, \n\tstudent_id VARCHAR(128) NOT NULL, \n\trole VARCHAR(16) NOT NULL, \n\tcontent TEXT NOT NULL, \n\tfeedback TEXT, \n\tscore NUMERIC(5, 2), \n\tcorrections JSONB, \n\tnext_step TEXT, \n\tstructured_feedback JSONB DEFAULT '{}' NOT NULL, \n\txp_awarded INTEGER DEFAULT '0' NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT fk_ai_messages_session_owner FOREIGN KEY(session_id, student_id) REFERENCES ai_sessions (id, student_id) ON DELETE CASCADE, \n\tFOREIGN KEY(student_id) REFERENCES users (id) ON DELETE CASCADE\n)",
    'CREATE INDEX ix_ai_messages_session_created ON ai_messages (session_id, created_at)',
    'CREATE INDEX ix_ai_messages_student_created ON ai_messages (student_id, created_at)',
    'CREATE TABLE class_students (\n\tclass_id VARCHAR(128) NOT NULL, \n\tstudent_id VARCHAR(128) NOT NULL, \n\tPRIMARY KEY (class_id, student_id), \n\tFOREIGN KEY(class_id) REFERENCES classes (id) ON DELETE CASCADE, \n\tFOREIGN KEY(student_id) REFERENCES users (id) ON DELETE CASCADE\n)',
    "CREATE TABLE community_posts (\n\tid VARCHAR(128) NOT NULL, \n\tauthor_id VARCHAR(128) NOT NULL, \n\tscope VARCHAR(16) NOT NULL, \n\tcourse_id VARCHAR(128), \n\tclass_id VARCHAR(128), \n\ttitle VARCHAR(300), \n\tcontent TEXT NOT NULL, \n\tstatus VARCHAR(24) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_community_post_scope CHECK (scope IN ('general','course','class')), \n\tFOREIGN KEY(author_id) REFERENCES users (id), \n\tFOREIGN KEY(course_id) REFERENCES courses (id) ON DELETE SET NULL, \n\tFOREIGN KEY(class_id) REFERENCES classes (id) ON DELETE SET NULL\n)",
    'CREATE INDEX ix_community_posts_scope_created ON community_posts (scope, created_at)',
    "CREATE TABLE conversations (\n\tid VARCHAR(128) NOT NULL, \n\ttype VARCHAR(24) NOT NULL, \n\tclass_id VARCHAR(128), \n\tscope_key VARCHAR(128) DEFAULT '' NOT NULL, \n\tcreated_by VARCHAR(128) NOT NULL, \n\tpair_key VARCHAR(260) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_conversation_type_scope_pair UNIQUE (type, scope_key, pair_key), \n\tFOREIGN KEY(class_id) REFERENCES classes (id) ON DELETE SET NULL, \n\tFOREIGN KEY(created_by) REFERENCES users (id)\n)",
    'CREATE INDEX ix_conversations_created ON conversations (created_at)',
    'CREATE TABLE homework_assignments (\n\thomework_id VARCHAR(128) NOT NULL, \n\tstudent_id VARCHAR(128) NOT NULL, \n\tPRIMARY KEY (homework_id, student_id), \n\tFOREIGN KEY(homework_id) REFERENCES homework (id) ON DELETE CASCADE, \n\tFOREIGN KEY(student_id) REFERENCES users (id) ON DELETE CASCADE\n)',
    'CREATE TABLE homework_submissions (\n\tid VARCHAR(128) NOT NULL, \n\thomework_id VARCHAR(128) NOT NULL, \n\tstudent_id VARCHAR(128) NOT NULL, \n\tanswer TEXT NOT NULL, \n\tstatus VARCHAR(24) NOT NULL, \n\tgrade NUMERIC(6, 2), \n\tteacher_feedback TEXT, \n\tsubmitted_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tgraded_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_submission_homework_student UNIQUE (homework_id, student_id), \n\tFOREIGN KEY(homework_id) REFERENCES homework (id) ON DELETE CASCADE, \n\tFOREIGN KEY(student_id) REFERENCES users (id) ON DELETE CASCADE\n)',
    'CREATE INDEX ix_submissions_student_submitted ON homework_submissions (student_id, submitted_at)',
    'CREATE TABLE lesson_completions (\n\tstudent_id VARCHAR(128) NOT NULL, \n\tlesson_id VARCHAR(128) NOT NULL, \n\tcompleted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (student_id, lesson_id), \n\tFOREIGN KEY(student_id) REFERENCES users (id) ON DELETE CASCADE, \n\tFOREIGN KEY(lesson_id) REFERENCES lessons (id) ON DELETE CASCADE\n)',
    'CREATE TABLE community_post_likes (\n\tpost_id VARCHAR(128) NOT NULL, \n\tuser_id VARCHAR(128) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (post_id, user_id), \n\tFOREIGN KEY(post_id) REFERENCES community_posts (id) ON DELETE CASCADE, \n\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE\n)',
    'CREATE TABLE community_replies (\n\tid VARCHAR(128) NOT NULL, \n\tpost_id VARCHAR(128) NOT NULL, \n\tauthor_id VARCHAR(128) NOT NULL, \n\tcontent TEXT NOT NULL, \n\tstatus VARCHAR(24) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(post_id) REFERENCES community_posts (id) ON DELETE CASCADE, \n\tFOREIGN KEY(author_id) REFERENCES users (id)\n)',
    'CREATE INDEX ix_community_replies_post_created ON community_replies (post_id, created_at)',
    'CREATE TABLE community_reports (\n\tid VARCHAR(128) NOT NULL, \n\tpost_id VARCHAR(128) NOT NULL, \n\treporter_id VARCHAR(128) NOT NULL, \n\treason TEXT NOT NULL, \n\tresolution VARCHAR(32), \n\tstatus VARCHAR(24) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tresolved_at TIMESTAMP WITH TIME ZONE, \n\tresolved_by VARCHAR(128), \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(post_id) REFERENCES community_posts (id) ON DELETE CASCADE, \n\tFOREIGN KEY(reporter_id) REFERENCES users (id) ON DELETE CASCADE, \n\tFOREIGN KEY(resolved_by) REFERENCES users (id) ON DELETE SET NULL\n)',
    'CREATE INDEX ix_community_reports_status_created ON community_reports (status, created_at)',
    "CREATE UNIQUE INDEX uq_open_community_report ON community_reports (post_id, reporter_id) WHERE status = 'open'",
    'CREATE TABLE conversation_participants (\n\tconversation_id VARCHAR(128) NOT NULL, \n\tuser_id VARCHAR(128) NOT NULL, \n\tPRIMARY KEY (conversation_id, user_id), \n\tFOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE, \n\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE\n)',
    'CREATE TABLE messages (\n\tid VARCHAR(128) NOT NULL, \n\tconversation_id VARCHAR(128) NOT NULL, \n\tsender_id VARCHAR(128) NOT NULL, \n\tcontent TEXT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE, \n\tFOREIGN KEY(sender_id) REFERENCES users (id)\n)',
    'CREATE INDEX ix_messages_conversation_created ON messages (conversation_id, created_at)',
    'CREATE INDEX ix_messages_sender_created ON messages (sender_id, created_at)',
    'CREATE TABLE message_reads (\n\tmessage_id VARCHAR(128) NOT NULL, \n\tuser_id VARCHAR(128) NOT NULL, \n\tread_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (message_id, user_id), \n\tFOREIGN KEY(message_id) REFERENCES messages (id) ON DELETE CASCADE, \n\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE\n)',
]

DROP_TABLES = [
    'message_reads',
    'messages',
    'conversation_participants',
    'community_reports',
    'community_replies',
    'community_post_likes',
    'lesson_completions',
    'homework_submissions',
    'homework_assignments',
    'conversations',
    'community_posts',
    'class_students',
    'ai_messages',
    'user_badges',
    'student_profiles',
    'revoked_tokens',
    'notifications',
    'lessons',
    'homework',
    'gamification_state',
    'gamification_actions',
    'classes',
    'ai_usage_events',
    'ai_sessions',
    'users',
    'courses',
]

def upgrade():
    for statement in SCHEMA_STATEMENTS:
        op.execute(statement)

def downgrade():
    for table_name in DROP_TABLES:
        op.execute(f'DROP TABLE IF EXISTS {table_name} CASCADE')
