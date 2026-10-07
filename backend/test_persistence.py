"""Offline checks for the persistence boundary.

These tests need no database. They cover the parts of the cutover that can be
proven without one: backend selection and its fail-closed rules, the JSON
backend's behaviour, and the equivalence between the runtime record-to-row
mapping and the importer mapping that was already validated against staging.

The PostgreSQL runtime itself is proven by test_postgres_runtime, which needs an
explicit disposable TEST_DATABASE_URL and skips when one is not configured.
"""

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import persistence
import persistence.runtime as runtime
import server  # noqa: F401  imported for its side effect of configuring the default JSON store
from import_json_to_postgres import (
    LEGACY_UNKNOWN_CREATED_AT,
    STORE_NAMES,
    _rows_for_tables,
    load_source,
)
from persistence.errors import DataStoreError, PersistenceConfigurationError
from persistence.json_backend import JsonStoreBackend
from persistence.records import (
    STORE_WRITE_TABLES,
    ReadContext,
    WriteContext,
    records_from_rows,
    rows_from_records,
)
from persistence.runtime import (
    JSON_BACKEND,
    POSTGRES_BACKEND,
    build_store,
    resolve_backend_name,
    store_name_for_path,
)

DATA_DIRECTORY = Path(__file__).resolve().parent / "data"
APPROVAL = frozenset({LEGACY_UNKNOWN_CREATED_AT["user_id"]})
NO_APPROVAL: frozenset[str] = frozenset()

# Relationships whose timestamp the legacy JSON never recorded. The importer
# stores NULL for these; the runtime keeps the value it already knows, because
# dropping it on the next write would erase a real moment.
UNKNOWN_HISTORY_TIMES = {
    "lesson_completions": ("student_id", "lesson_id", "completed_at"),
    "community_post_likes": ("post_id", "user_id", "created_at"),
    "message_reads": ("message_id", "user_id", "read_at"),
}


def json_records(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class BackendSelectionTests(unittest.TestCase):
    def test_development_and_test_default_to_json(self):
        for environment in ("development", "test"):
            with self.subTest(environment=environment):
                self.assertEqual(resolve_backend_name({"FLUENT_PATH_ENVIRONMENT": environment}), JSON_BACKEND)

    def test_development_and_test_may_request_postgres_explicitly(self):
        environ = {"FLUENT_PATH_ENVIRONMENT": "test", "FLUENT_PATH_PERSISTENCE": "postgres"}
        self.assertEqual(resolve_backend_name(environ), POSTGRES_BACKEND)

    def test_staging_and_production_always_resolve_to_postgres(self):
        for environment in ("staging", "production"):
            with self.subTest(environment=environment):
                self.assertEqual(resolve_backend_name({"FLUENT_PATH_ENVIRONMENT": environment}), POSTGRES_BACKEND)

    def test_staging_and_production_refuse_to_downgrade_to_json(self):
        for environment in ("staging", "production"):
            with self.subTest(environment=environment):
                with self.assertRaises(PersistenceConfigurationError):
                    resolve_backend_name({
                        "FLUENT_PATH_ENVIRONMENT": environment,
                        "FLUENT_PATH_PERSISTENCE": JSON_BACKEND,
                    })

    def test_unknown_backend_name_is_rejected(self):
        with self.assertRaises(PersistenceConfigurationError):
            resolve_backend_name({"FLUENT_PATH_PERSISTENCE": "sqlite"})

    def test_postgres_without_a_database_url_fails_to_start(self):
        with self.assertRaises(PersistenceConfigurationError):
            build_store({"FLUENT_PATH_ENVIRONMENT": "staging"}, path_resolver=lambda name: None)

    def test_json_backend_requires_path_resolution(self):
        with self.assertRaises(PersistenceConfigurationError):
            build_store({"FLUENT_PATH_ENVIRONMENT": "development"}, path_resolver=None)

    def test_json_backend_is_built_without_any_database_configuration(self):
        store = build_store({"FLUENT_PATH_ENVIRONMENT": "development"}, path_resolver=lambda name: None)
        self.assertEqual(store.name, JSON_BACKEND)


class StorePathTests(unittest.TestCase):
    def setUp(self):
        self.previous_store = persistence.active_store()
        self.directory = Path(tempfile.mkdtemp())
        self.paths = {name: self.directory / f"{name}.json" for name in STORE_NAMES}
        persistence.configure(
            JsonStoreBackend(lambda name: self.paths.get(name)),
            timeout=5.0,
        )

    def tearDown(self):
        persistence.configure(self.previous_store, timeout=5.0)
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_store_paths_resolve_by_name_and_filename(self):
        for name in STORE_NAMES:
            with self.subTest(store=name):
                self.assertEqual(store_name_for_path(self.paths[name]), name)
                self.assertEqual(store_name_for_path(self.directory / f"{name}.json"), name)

    def test_unrelated_scratch_paths_are_not_stores(self):
        self.assertIsNone(store_name_for_path(self.directory / "atomic-test.json"))
        self.assertIsNone(store_name_for_path(self.directory / "reports-export.json"))

    def test_building_a_throwaway_store_does_not_replace_the_installed_resolver(self):
        # A store built only to be inspected must not be able to change how the
        # running process maps paths to stores. While build_store installed its
        # own resolver globally, a single inspection call anywhere in the process
        # could repoint product store paths and reopen the silent JSON fallback.
        persistence.configure(
            JsonStoreBackend(lambda name: None),
            timeout=5.0,
            path_resolver=lambda name: self.paths.get(name),
        )
        build_store({"FLUENT_PATH_ENVIRONMENT": "development"},
                    path_resolver=lambda name: None)
        for name in STORE_NAMES:
            with self.subTest(store=name):
                self.assertEqual(store_name_for_path(self.paths[name]), name)

    def test_canonical_store_filenames_resolve_even_with_no_resolver_installed(self):
        # Defence in depth. If no resolver was ever installed, a product store
        # filename must still identify its store rather than looking like scratch
        # data, because a scratch-looking store path is exactly what let writes
        # fall through to JSON files on a PostgreSQL runtime.
        persistence.configure(JsonStoreBackend(lambda name: None), timeout=5.0)
        with mock.patch.object(runtime, "_path_resolver", None):
            for name in STORE_NAMES:
                with self.subTest(store=name):
                    self.assertEqual(store_name_for_path(self.paths[name]), name)
            self.assertIsNone(store_name_for_path(self.directory / "atomic-test.json"))
            self.assertIsNone(store_name_for_path(self.directory / "notifications.json.bak"))

    def test_reading_a_missing_store_returns_an_empty_store(self):
        self.assertEqual(persistence.read_store("reports"), [])

    def test_write_then_read_returns_the_same_records(self):
        records = [{"id": "a", "value": 1}, {"id": "b", "value": 2}]
        persistence.write_store("reports", records)
        self.assertEqual(persistence.read_store("reports"), records)
        self.assertEqual(json_records(self.paths["reports"]), records)

    def test_write_replaces_the_whole_store(self):
        persistence.write_store("reports", [{"id": "a"}, {"id": "b"}])
        persistence.write_store("reports", [{"id": "c"}])
        self.assertEqual(persistence.read_store("reports"), [{"id": "c"}])

    def test_an_explicit_path_overrides_the_configured_store_location(self):
        elsewhere = self.directory / "elsewhere" / "reports.json"
        elsewhere.parent.mkdir()
        persistence.write_store("reports", [{"id": "explicit"}], path=elsewhere)
        self.assertEqual(json_records(elsewhere), [{"id": "explicit"}])
        self.assertFalse(self.paths["reports"].exists())
        self.assertEqual(persistence.read_store("reports", path=elsewhere), [{"id": "explicit"}])

    def test_a_corrupt_store_file_raises_a_data_store_error(self):
        self.paths["reports"].write_bytes(b'{"unexpected":"object"}')
        with self.assertRaises(DataStoreError):
            persistence.read_store("reports")

    def test_records_are_copied_so_callers_cannot_mutate_stored_state(self):
        record = {"id": "a", "tags": ["one"]}
        persistence.write_store("reports", [record])
        record["tags"].append("two")
        self.assertEqual(persistence.read_store("reports"), [{"id": "a", "tags": ["one"]}])

    def test_an_unknown_store_name_is_refused(self):
        with self.assertRaises(KeyError):
            persistence.read_store("secret_backdoor")
        with self.assertRaises(KeyError):
            persistence.write_store("secret_backdoor", [])


class _MappingParity(unittest.TestCase):
    """Compare the runtime mapping with the validated importer mapping."""

    @classmethod
    def setUpClass(cls):
        cls.stores = load_source(DATA_DIRECTORY)
        cls.planned = _rows_for_tables(cls.stores, approved_legacy_created_at_ids=APPROVAL)
        cls.lesson_courses = {
            lesson["id"]: course["id"]
            for course in cls.stores["courses"]
            for lesson in course.get("lessons", [])
        }

    def rows_for(self, store_name, records):
        return rows_from_records(store_name, records, WriteContext(self.lesson_courses))

    def assert_rows_match(self, table, produced, *, expected_table=None):
        self.assertEqual(self.canonical(produced), self.canonical(self.planned[expected_table or table]), table)

    @staticmethod
    def canonical(rows):
        """Order-independent, type-safe row comparison.

        Rendering values with repr keeps the comparison total: a NULL timestamp,
        a datetime, a JSON document and a string must all be sortable together.
        """
        return sorted(
            tuple(sorted((key, repr(value)) for key, value in row.items()))
            for row in rows
        )

    def assert_unknown_history_times(self, table, produced):
        """The importer records these times as unknown; the runtime keeps them."""
        first_key, second_key, time_column = UNKNOWN_HISTORY_TIMES[table]
        mine = produced.get(table, [])
        theirs = self.planned[table]
        if not mine and not theirs:
            return
        with self.subTest(table=table):
            self.assertEqual(
                sorted((row[first_key], row[second_key]) for row in mine),
                sorted((row[first_key], row[second_key]) for row in theirs),
                f"{table}: the same relationships must exist either way",
            )
            self.assertTrue(
                all(row[time_column] is None for row in theirs),
                f"{table}: the importer must record these times as unknown",
            )
            self.assertTrue(
                all(row[time_column] is not None for row in mine),
                f"{table}: the runtime must keep a time it already knows",
            )

    def assert_store_matches_importer(self, store_name, records, planned):
        """Every table of one store must match the validated importer mapping."""
        self.planned = planned
        produced = self.rows_for(store_name, records)
        for table in STORE_WRITE_TABLES[store_name]:
            if table in UNKNOWN_HISTORY_TIMES:
                self.assert_unknown_history_times(table, produced)
                continue
            with self.subTest(table=table):
                self.assert_rows_match(table, produced.get(table, []))


class ImportedFixtureMappingTests(_MappingParity):
    def test_runtime_mapping_matches_the_importer_for_every_store(self):
        for store_name in STORE_NAMES:
            with self.subTest(store=store_name):
                self.assert_store_matches_importer(store_name, self.stores[store_name], self.planned)

    def test_unknown_history_times_exist_somewhere_to_compare(self):
        # Guard against the parity table silently becoming vacuous.
        covered = {
            table
            for store_name in STORE_NAMES
            for table in STORE_WRITE_TABLES[store_name]
            if table in UNKNOWN_HISTORY_TIMES
        }
        self.assertEqual(covered, set(UNKNOWN_HISTORY_TIMES))

    def test_every_store_is_covered_by_a_write_mapping(self):
        self.assertEqual(
            set(STORE_WRITE_TABLES),
            set(STORE_NAMES),
            "a store without a write mapping would silently stop persisting",
        )


STAMP = "2026-09-28T10:00:00+00:00"
TEACHER_ID = "t-1"
STUDENT_ID = "s-1"
COURSE_ID = "c-1"
LESSON_ID = "l-1"


def minimal_universe():
    """A complete, self-consistent store set for API-shaped record tests.

    Every store is present and every foreign key resolves, so the importer can
    build a plan for it without borrowing anything from the legacy fixture files.
    """
    stores = {name: [] for name in STORE_NAMES}
    stores["students"] = [
        {"id": TEACHER_ID, "fullName": "Teacher", "email": "teacher@example.com",
         "passwordHash": "salt:hash", "role": "teacher", "devOnly": True,
         "dateOfBirth": "", "phone": "", "level": None, "testScore": None,
         "totalQuestions": None, "testCompletedAt": None, "courseProgress": {},
         "createdAt": "2026-09-25T04:00:00+04:00"},
        {"id": STUDENT_ID, "fullName": "New Student", "email": "New@Example.com",
         "passwordHash": "salt:hash", "role": "student", "dateOfBirth": "2000-01-01",
         "phone": "", "level": None, "testScore": None, "totalQuestions": None,
         "testCompletedAt": None, "courseProgress": {}, "createdAt": STAMP},
    ]
    stores["courses"] = [{
        "id": COURSE_ID, "type": "cefr", "level": "A0 - A1", "requiredRank": 1,
        "title": "Course", "titleAr": "Ø¯ÙˆØ±Ø©", "description": "Desc", "descriptionAr": "ÙˆØµÙ",
        "active": True, "order": 1, "lessons": [{
            "id": LESSON_ID, "course_id": COURSE_ID, "number": 1, "title": "Lesson",
            "titleAr": "Ø¯Ø±Ø³", "description": "", "descriptionAr": "",
            "content": {"explanation": "Hi"}, "order": 1, "estimated_minutes": 15,
            "published": True, "archived": False, "created_at": STAMP, "updated_at": STAMP,
        }],
    }]
    stores["homework"] = [{
        "id": "h-1", "title": "Introduce yourself", "description": "Five sentences.",
        "courseId": COURSE_ID, "level": None, "createdBy": TEACHER_ID, "teacherId": TEACHER_ID,
        "status": "published", "dueDate": None, "createdAt": STAMP,
        "assignedStudentIds": [STUDENT_ID],
    }]
    stores["submissions"] = [{
        "id": "sub-1", "homeworkId": "h-1", "studentId": STUDENT_ID, "answer": "Hello",
        "status": "submitted", "grade": None, "teacherFeedback": None,
        "submittedAt": STAMP, "gradedAt": None,
    }]
    stores["classes"] = [{
        "id": "cl-1", "teacherId": TEACHER_ID, "courseId": None, "level": "A2",
        "title": "Conversation lab", "description": "Practice speaking.",
        "assignedStudentIds": [STUDENT_ID], "date": "2026-10-01",
        "startTime": "16:00", "endTime": "16:45", "startsAt": "2026-10-01T16:00:00+00:00",
        "durationMinutes": 45, "meetingProvider": "none", "meetingUrl": None,
        "teacherJoinUrl": None, "studentJoinUrl": None, "status": "scheduled",
        "createdAt": STAMP,
    }]
    stores["community_posts"] = [{
        "id": "p-1", "authorId": STUDENT_ID, "scope": "general", "courseId": None,
        "classId": None, "title": "Hello", "content": "Hi", "status": "active",
        "createdAt": STAMP, "updatedAt": None, "likesBy": [],
    }]
    stores["community_replies"] = [{
        "id": "r-1", "postId": "p-1", "authorId": TEACHER_ID, "content": "Welcome",
        "status": "active", "createdAt": STAMP, "updatedAt": None,
    }]
    stores["reports"] = [{
        "id": "rep-1", "postId": "p-1", "reporterId": TEACHER_ID, "reason": "spam",
        "resolution": None, "status": "open", "createdAt": STAMP, "resolvedAt": None,
        "resolvedBy": None,
    }]
    stores["conversations"] = [{
        "id": "cv-1", "type": "student_teacher", "classId": None, "createdBy": STUDENT_ID,
        "participantIds": [STUDENT_ID, TEACHER_ID], "createdAt": STAMP,
    }]
    stores["messages"] = [{
        "id": "m-1", "conversationId": "cv-1", "senderId": STUDENT_ID, "content": "Hello",
        "readBy": [], "createdAt": STAMP,
    }]
    stores["notifications"] = [{
        "id": "n-1", "recipient_user_id": TEACHER_ID, "event_key": "registration:s-1",
        "type": "new_user_registration", "title": "New student registered",
        "message": "A student created an account.", "read": False, "created_at": STAMP,
        "related_entity_type": "user", "related_entity_id": STUDENT_ID, "severity": "info",
    }]
    stores["ai_sessions"] = [{
        "id": "as-1", "student_id": STUDENT_ID, "mode": "conversation",
        "cefr_level": "A2 - B1", "status": "active", "completed_at": None,
        "created_at": STAMP, "updated_at": STAMP,
    }]
    stores["ai_messages"] = [{
        "id": "am-1", "session_id": "as-1", "student_id": STUDENT_ID, "role": "assistant",
        "content": "Hello!", "feedback": "Good", "score": 88, "corrections": ["a"],
        "next_step": "Speak more", "grammar_feedback": "ok", "vocabulary_feedback": "ok",
        "clarity_feedback": "ok", "relevance_feedback": "ok", "xp_awarded": 0, "created_at": STAMP,
    }]
    stores["ai_usage"] = [{"student_id": STUDENT_ID, "created_at": STAMP}]
    return stores


class ApplicationShapedRecordMappingTests(_MappingParity):
    """The runtime mapping must agree with the importer on API-produced records."""

    def setUp(self):
        self.universe = minimal_universe()
        self.lesson_courses = {LESSON_ID: COURSE_ID}

    def plan(self, **overrides):
        stores = dict(self.universe)
        for name, records in overrides.items():
            stores[name] = records
        return _rows_for_tables(stores, approved_legacy_created_at_ids=NO_APPROVAL)

    def check(self, store_name, **overrides):
        planned = self.plan(**overrides)
        records = overrides.get(store_name, self.universe[store_name])
        self.assert_store_matches_importer(store_name, records, planned)

    def test_students_map_the_same_way(self):
        self.check("students")

    def test_a_student_with_progress_streaks_badges_and_actions_maps_the_same_way(self):
        gamer = {
            "id": "s-gamer", "fullName": "Gamer", "email": "gamer@example.com",
            "passwordHash": "salt:hash", "role": "student",
            "courseProgress": {COURSE_ID: {"completedLessons": [LESSON_ID], "updatedAt": STAMP}},
            "gamification": {
                "xp": 215, "currentStreak": 3, "longestStreak": 9,
                "lastActivityDate": "2026-09-28",
                "earnedBadges": [{"id": "first_lesson", "earnedAt": STAMP}],
                "awardedActions": [
                    f"lesson_completed:{COURSE_ID}:{LESSON_ID}",
                    {"key": "homework_submitted:h-1", "xp": 15, "createdAt": STAMP},
                ],
            },
            "createdAt": STAMP,
        }
        self.check("students", students=[*self.universe["students"], gamer])

    def test_a_badge_without_a_usable_time_is_not_dropped_from_the_record(self):
        gamer = {
            "id": "s-badge", "fullName": "Badger", "email": "badger@example.com",
            "passwordHash": "salt:hash", "role": "student", "courseProgress": {},
            "gamification": {
                "xp": 5, "currentStreak": 1, "longestStreak": 1,
                "lastActivityDate": "2026-09-28",
                "earnedBadges": [{"id": "legacy_badge"}],
                "awardedActions": [],
            },
            "createdAt": STAMP,
        }
        rows = rows_from_records("students", [gamer], WriteContext({LESSON_ID: COURSE_ID}))
        self.assertEqual(rows["user_badges"], [], "an undated badge must not be given an invented time")
        rebuilt = records_from_rows("students", ReadContext(rows))
        badge = next(record for record in rebuilt if record["id"] == "s-badge")
        self.assertEqual(badge["gamification"]["earnedBadges"], [{"id": "legacy_badge"}])

    def test_a_student_without_history_grows_no_gamification_state_row(self):
        rows = rows_from_records("students", [self.universe["students"][1]], WriteContext({}))
        self.assertEqual(rows["gamification_state"], [])
        rebuilt = records_from_rows("students", ReadContext(rows))
        self.assertNotIn("gamification", rebuilt[0], "a read must not invent a gamification key")

    def test_courses_and_lessons_map_the_same_way(self):
        self.check("courses")

    def test_a_class_record_maps_the_same_way(self):
        self.check("classes")

    def test_homework_and_assignments_map_the_same_way(self):
        self.check("homework")

    def test_submissions_map_the_same_way(self):
        self.check("submissions")

    def test_a_graded_submission_keeps_its_grade_and_feedback(self):
        graded = {
            "id": "sub-2", "homeworkId": "h-1", "studentId": STUDENT_ID, "answer": "Hello",
            "status": "graded", "grade": 92, "teacherFeedback": "Well done",
            "submittedAt": STAMP, "gradedAt": "2026-09-26T10:00:00+00:00",
        }
        # One submission per student per assignment, so this replaces rather than adds.
        self.check("submissions", submissions=[graded])

    def test_community_and_messaging_records_map_the_same_way(self):
        for store_name in ("community_posts", "community_replies", "reports", "conversations", "messages"):
            with self.subTest(store=store_name):
                self.check(store_name)

    def test_notifications_map_the_same_way(self):
        self.check("notifications")

    def test_a_read_notification_keeps_its_read_state(self):
        read = {**self.universe["notifications"][0], "id": "n-2", "event_key": "level:2",
                "read": True, "created_at": "2026-09-28T09:41:12.716136+00:00"}
        self.check("notifications", notifications=[*self.universe["notifications"], read])

    def test_ai_sessions_and_messages_map_the_same_way(self):
        self.check("ai_sessions")
        self.check("ai_messages")

    def test_ai_usage_maps_the_same_way(self):
        self.check("ai_usage")

    def test_a_student_without_course_progress_maps_no_completions(self):
        rows = rows_from_records("students", [self.universe["students"][1]], WriteContext({}))
        self.assertEqual(rows["lesson_completions"], [])
        self.assertEqual(rows["user_badges"], [])
        self.assertEqual(rows["gamification_actions"], [])

    def test_a_post_like_is_mapped_without_inventing_a_time(self):
        # The record shape stores likesBy as bare user ids with no timestamp, so
        # the like must be recorded with an unknown time rather than a fabricated one.
        post = {**self.universe["community_posts"][0], "likesBy": [TEACHER_ID, STUDENT_ID]}
        rows = rows_from_records("community_posts", [post])
        self.assertEqual(
            sorted((row["post_id"], row["user_id"]) for row in rows["community_post_likes"]),
            [("p-1", STUDENT_ID), ("p-1", TEACHER_ID)],
        )
        self.assertTrue(all(row["created_at"] is None for row in rows["community_post_likes"]))
        rebuilt = records_from_rows("community_posts", ReadContext(rows))
        self.assertEqual(sorted(rebuilt[0]["likesBy"]), sorted([TEACHER_ID, STUDENT_ID]))

    def test_a_message_read_is_mapped_without_inventing_a_time(self):
        message = {**self.universe["messages"][0], "readBy": [STUDENT_ID, TEACHER_ID]}
        rows = rows_from_records("messages", [message])
        self.assertEqual(
            sorted((row["message_id"], row["user_id"]) for row in rows["message_reads"]),
            [("m-1", STUDENT_ID), ("m-1", TEACHER_ID)],
        )
        self.assertTrue(all(row["read_at"] is None for row in rows["message_reads"]))
        rebuilt = records_from_rows("messages", ReadContext(rows))
        self.assertEqual(sorted(rebuilt[0]["readBy"]), sorted([STUDENT_ID, TEACHER_ID]))

class RowToRecordTests(unittest.TestCase):
    """Records rebuilt from rows must keep the fields the API reads."""

    def records_from_planned(self, store_name):
        return records_from_rows(store_name, ReadContext(self.planned))

    @classmethod
    def setUpClass(cls):
        cls.stores = load_source(DATA_DIRECTORY)
        cls.planned = _rows_for_tables(cls.stores, approved_legacy_created_at_ids=APPROVAL)

    def same_moment(self, produced, source):
        if produced is None or source is None:
            return produced is source
        try:
            return datetime.fromisoformat(produced) == datetime.fromisoformat(source)
        except (TypeError, ValueError):
            return produced == source

    def test_students_keep_the_fields_the_profile_views_read(self):
        records = {record["id"]: record for record in self.records_from_planned("students")}
        legacy_id = LEGACY_UNKNOWN_CREATED_AT["user_id"]
        known_id = next(record["id"] for record in self.stores["students"] if record["id"] != legacy_id
                        and record.get("role") == "student" and str(record.get("createdAt", "")).startswith("20"))
        for source_id in (legacy_id, known_id):
            source = next(record for record in self.stores["students"] if record["id"] == source_id)
            rebuilt = records[source_id]
            for field in ("fullName", "email", "passwordHash", "role", "dateOfBirth",
                          "phone", "level", "testScore", "totalQuestions", "courseProgress"):
                with self.subTest(user=source_id, field=field):
                    self.assertEqual(rebuilt.get(field), source.get(field))
            for field in ("createdAt", "testCompletedAt"):
                if field == "createdAt" and source_id == legacy_id:
                    continue
                with self.subTest(user=source_id, field=field):
                    self.assertTrue(
                        self.same_moment(rebuilt.get(field), source.get(field)),
                        f"{field}: {rebuilt.get(field)!r} is not the same moment as {source.get(field)!r}",
                    )

    def test_a_corrupt_historical_creation_time_stays_unknown_instead_of_being_invented(self):
        legacy = next(record for record in self.stores["students"]
                      if record["id"] == LEGACY_UNKNOWN_CREATED_AT["user_id"])
        rebuilt = next(record for record in self.records_from_planned("students")
                       if record["id"] == legacy["id"])
        self.assertNotEqual(legacy.get("createdAt"), None)
        self.assertIsNone(rebuilt["createdAt"])

    def test_course_progress_lesson_order_is_preserved(self):
        source = next(record for record in self.stores["students"] if record.get("courseProgress"))
        rebuilt = next(record for record in self.records_from_planned("students") if record["id"] == source["id"])
        for course_id, progress in source["courseProgress"].items():
            with self.subTest(course=course_id):
                self.assertEqual(
                    rebuilt["courseProgress"][course_id]["completedLessons"],
                    progress["completedLessons"],
                )

    def test_courses_keep_lessons_titles_and_bilingual_fields(self):
        rebuilt = {record["id"]: record for record in self.records_from_planned("courses")}
        source = {record["id"]: record for record in self.stores["courses"]}
        for course_id, record in rebuilt.items():
            with self.subTest(course=course_id):
                self.assertEqual(record["title"], source[course_id].get("title"))
                self.assertEqual(record["titleAr"], source[course_id].get("titleAr"))
                self.assertEqual(record["level"], source[course_id].get("level"))
                self.assertEqual(record.get("requiredRank"), source[course_id].get("requiredRank"))
                self.assertEqual(len(record["lessons"]), len(source[course_id].get("lessons", [])))
                for rebuilt_lesson, source_lesson in zip(record["lessons"], source[course_id].get("lessons", [])):
                    with self.subTest(lesson=source_lesson.get("id")):
                        self.assertEqual(rebuilt_lesson["content"], source_lesson.get("content"))
                        self.assertEqual(rebuilt_lesson["title"], source_lesson.get("title"))
                        self.assertEqual(rebuilt_lesson["order"], source_lesson.get("order"))

    def test_classes_keep_their_schedule_and_legacy_display_fields(self):
        rebuilt = self.records_from_planned("classes")[0]
        source = self.stores["classes"][0]
        self.assertEqual(rebuilt["startsAt"], source["startsAt"])
        self.assertEqual(rebuilt["durationMinutes"], source["durationMinutes"])
        self.assertEqual(rebuilt["status"], source["status"])
        self.assertEqual(rebuilt["teacherId"], source["teacherId"])

    def test_notifications_expose_read_and_never_leak_the_column_name(self):
        rebuilt = self.records_from_planned("notifications")
        self.assertEqual(len(rebuilt), len(self.stores["notifications"]))
        for record in rebuilt:
            with self.subTest(notification=record["id"]):
                self.assertIn("read", record)
                self.assertNotIn("is_read", record)
                self.assertIsInstance(record["read"], bool)
                self.assertTrue(record["event_key"])

    def test_records_are_json_serializable(self):
        for store_name in STORE_NAMES:
            with self.subTest(store=store_name):
                json.dumps(self.records_from_planned(store_name))


class RoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stores = load_source(DATA_DIRECTORY)
        cls.lesson_courses = {
            lesson["id"]: course["id"]
            for course in cls.stores["courses"]
            for lesson in course.get("lessons", [])
        }

    def test_records_rebuilt_from_rows_map_back_to_the_same_rows(self):
        for store_name in STORE_NAMES:
            with self.subTest(store=store_name):
                source = self.stores[store_name]
                first = rows_from_records(store_name, source, WriteContext(self.lesson_courses))
                rebuilt = records_from_rows(store_name, ReadContext(first))
                second = rows_from_records(store_name, rebuilt, WriteContext(self.lesson_courses))
                self.assertEqual(second, first, "a row -> record -> row round trip must be stable")

    def test_api_created_timestamps_survive_a_round_trip(self):
        stamp = datetime.now(timezone.utc) - timedelta(days=3)
        record = {"id": "n-2", "recipient_user_id": "dev-admin-2026", "event_key": "level:2",
                  "type": "level_up", "title": "Level up!", "message": "You reached level 2.",
                  "read": False, "created_at": stamp.isoformat(),
                  "related_entity_type": "achievement", "related_entity_id": "2", "severity": "info"}
        rows = rows_from_records("notifications", [record])
        stored = {**rows["notifications"][0], "is_read": rows["notifications"][0]["is_read"]}
        rebuilt = records_from_rows("notifications", ReadContext({"notifications": [stored]}))
        self.assertEqual(rebuilt[0]["created_at"], record["created_at"])
        self.assertEqual(rebuilt[0]["read"], record["read"])


class ColumnComparisonTests(unittest.TestCase):
    """The change detection a repeat write depends on.

    ``bool`` is a subclass of ``int``, so a boolean column used to reach the
    Decimal comparison and raise InvalidOperation, which failed every write of
    the students store after the first. These run without a database.
    """

    def test_a_boolean_column_compares_without_raising(self):
        from persistence.postgres_backend import _values_match

        self.assertTrue(_values_match(False, False))
        self.assertTrue(_values_match(True, True))
        self.assertFalse(_values_match(True, False))
        self.assertFalse(_values_match(False, True))

    def test_a_numeric_column_compares_by_value(self):
        from decimal import Decimal

        from persistence.postgres_backend import _values_match

        self.assertTrue(_values_match(Decimal("1.00"), 1))
        self.assertTrue(_values_match(1, 1.0))
        self.assertFalse(_values_match(Decimal("1.00"), 2))

    def test_a_null_compares_only_against_null(self):
        from persistence.postgres_backend import _values_match

        self.assertTrue(_values_match(None, None))
        self.assertFalse(_values_match(None, False))
        self.assertFalse(_values_match(None, 0))
        self.assertFalse(_values_match(0, None))


class ProfileFieldContractTests(unittest.TestCase):
    """A user with no student profile must still report "" for the profile form.

    Teachers and administrators have no student_profiles row, and the JSON
    records give them "". Returning null instead would hand the profile page's
    <input type="date"> a null value.
    """

    def _user_row(self, role="teacher"):
        return {"id": "t-9", "email": "t@example.com", "password_hash": "hash",
                "role": role, "full_name": "Teacher", "dev_only": False,
                "created_at": None}

    def test_a_user_without_a_profile_reports_empty_strings(self):
        records = records_from_rows("students", ReadContext({"users": [self._user_row()]}))
        self.assertEqual(records[0]["dateOfBirth"], "")
        self.assertEqual(records[0]["phone"], "")

    def test_an_administrator_without_a_profile_reports_empty_strings(self):
        row = self._user_row(role="administrator")
        records = records_from_rows("students", ReadContext({"users": [row]}))
        self.assertEqual(records[0]["dateOfBirth"], "")
        self.assertEqual(records[0]["phone"], "")

    def test_a_null_profile_date_still_reads_as_an_empty_string(self):
        rows = {"users": [self._user_row(role="student")],
                "student_profiles": [{"user_id": "t-9", "date_of_birth": None, "phone": None,
                                      "level": None, "test_score": None, "total_questions": None,
                                      "test_completed_at": None, "legacy_course_progress": {},
                                      "legacy_gamification": {}}]}
        record = records_from_rows("students", ReadContext(rows))[0]
        self.assertEqual(record["dateOfBirth"], "")
        self.assertEqual(record["phone"], "")


if __name__ == "__main__":
    unittest.main()

