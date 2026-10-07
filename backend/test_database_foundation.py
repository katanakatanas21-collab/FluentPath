import unittest
import ast
import json
import os
import re
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from db_config import DatabaseConfigurationError, importer_target_identity, importer_target_url, load_database_settings, require_test_database_url
from import_json_to_postgres import ImportValidationError, LEGACY_UNKNOWN_CREATED_AT, STORE_NAMES, _rows_for_tables, load_source, main, validate_source
from db.base import Base
from db import models  # noqa: F401 - import registers ORM metadata


class DatabaseConfigurationTests(unittest.TestCase):
    def test_optional_database_url_keeps_json_development_configuration_valid(self):
        settings = load_database_settings({"FLUENT_PATH_ENVIRONMENT": "development"})
        self.assertIsNone(settings.database_url)
        self.assertEqual(settings.environment, "development")

    def test_database_url_accepts_postgresql_and_rejects_other_schemes(self):
        settings = load_database_settings({"DATABASE_URL": "postgresql+asyncpg://user:pass@db.example/staging"})
        self.assertTrue(settings.database_url.startswith("postgresql+asyncpg://"))
        with self.assertRaises(DatabaseConfigurationError):
            load_database_settings({"DATABASE_URL": "sqlite:///app.db"})
        with self.assertRaises(DatabaseConfigurationError):
            load_database_settings({"FLUENT_PATH_ENVIRONMENT": "production"})

    def test_test_database_requires_explicit_test_url_and_never_falls_back(self):
        with self.assertRaises(DatabaseConfigurationError):
            require_test_database_url({"DATABASE_URL": "postgresql://u:p@prod.example/production"})
        with self.assertRaises(DatabaseConfigurationError):
            load_database_settings({"FLUENT_PATH_ENVIRONMENT": "test", "DATABASE_URL": "postgresql://u:p@prod.example/production"})
        settings = load_database_settings({"FLUENT_PATH_ENVIRONMENT": "test", "DATABASE_URL": "postgresql://u:p@prod.example/production", "TEST_DATABASE_URL": "postgresql://u:p@localhost/fluent_path_test"})
        self.assertEqual(settings.database_url, "postgresql://u:p@localhost/fluent_path_test")
        self.assertEqual(
            require_test_database_url({"DATABASE_URL": "postgresql://u:p@prod.example/production", "TEST_DATABASE_URL": "postgresql://u:p@localhost/fluent_path_test"}),
            "postgresql://u:p@localhost/fluent_path_test",
        )
        with self.assertRaises(DatabaseConfigurationError):
            require_test_database_url({"TEST_DATABASE_URL": "postgresql://u:p@localhost/fluent_path"})

    def test_importer_requires_separate_explicit_staging_target(self):
        with self.assertRaises(DatabaseConfigurationError):
            importer_target_url({"DATABASE_URL": "postgresql://u:p@localhost/fluent_path_test"})
        env = {"FLUENT_PATH_ENVIRONMENT": "staging", "FLUENT_PATH_IMPORT_CONFIRM": "I_CONFIRM_STAGING_IMPORT", "IMPORT_DATABASE_URL": "postgresql://u:p@localhost/fluent_path_staging"}
        self.assertEqual(importer_target_url(env), env["IMPORT_DATABASE_URL"])
        self.assertEqual(importer_target_identity(env["IMPORT_DATABASE_URL"]), "localhost/fluent_path_staging")
        with self.assertRaises(DatabaseConfigurationError):
            importer_target_url({**env, "IMPORT_DATABASE_URL": "postgresql://u:p@prod.example/fluent_path_production"})
        with self.assertRaises(DatabaseConfigurationError):
            importer_target_url({**env, "IMPORT_DATABASE_URL": "postgres-db.example/fluent_path_staging"})


class JsonImportPreflightTests(unittest.TestCase):
    def test_explicit_current_store_dry_run_inventory_validates(self):
        stores = load_source(Path(__file__).resolve().parent / "data")
        counts = validate_source(stores)
        self.assertEqual(len(stores), len(STORE_NAMES))
        self.assertIn("lessons", counts)

    def test_current_store_rows_map_to_the_initial_schema_without_count_loss(self):
        stores = load_source(Path(__file__).resolve().parent / "data")
        stores = {name: [dict(row) for row in source_rows] for name, source_rows in stores.items()}
        # Existing local records contain one non-ISO creation value. Keep the
        # user's JSON untouched and normalize only this in-memory test fixture.
        for user in stores["students"]:
            if isinstance(user.get("createdAt"), str) and ("\\" in user["createdAt"] or "/" in user["createdAt"]):
                user["createdAt"] = "2026-09-29T00:00:00+00:00"
        counts = validate_source(stores)
        rows = _rows_for_tables(stores)
        self.assertEqual(len(rows["users"]), counts["students"])
        self.assertEqual(len(rows["courses"]), counts["courses"])
        self.assertEqual(len(rows["lessons"]), counts["lessons"])
        self.assertEqual(len(rows["homework"]), counts["homework"])
        self.assertEqual(len(rows["classes"]), counts["classes"])
        self.assertEqual(len(rows["homework_submissions"]), counts["submissions"])
        self.assertEqual(len(rows["community_posts"]), counts["community_posts"])
        self.assertEqual(len(rows["community_replies"]), counts["community_replies"])
        self.assertEqual(len(rows["conversations"]), counts["conversations"])
        self.assertEqual(len(rows["messages"]), counts["messages"])
        self.assertEqual(len(rows["community_reports"]), counts["reports"])
        self.assertEqual(len(rows["notifications"]), counts["notifications"])
        self.assertEqual(len(rows["ai_sessions"]), counts["ai_sessions"])
        self.assertEqual(len(rows["ai_messages"]), counts["ai_messages"])
        self.assertEqual(len(rows["ai_usage_events"]), counts["ai_usage"])

    def test_qa_disposable_source_is_rejected(self):
        source = Path(__file__).resolve().parent / ".qa-disposable" / "data"
        with self.assertRaises(ImportValidationError):
            load_source(source)

    def test_source_is_never_modified_and_duplicate_ids_are_rejected(self):
        source = Path(__file__).resolve().parent / "data"
        initial = {name: (source / f"{name}.json").read_bytes() for name in STORE_NAMES}
        stores = load_source(source)
        stores["students"] = [
            {"id": "u1", "email": "same@example.test", "passwordHash": "opaque-test-hash", "role": "student"},
            {"id": "u1", "email": "other@example.test", "passwordHash": "opaque-test-hash", "role": "student"},
        ]
        with self.assertRaises(ImportValidationError):
            validate_source(stores)
        self.assertEqual(initial, {name: (source / f"{name}.json").read_bytes() for name in STORE_NAMES})

    def test_dry_run_summarizes_then_stops_on_legacy_bad_timestamp_without_rows(self):
        source = Path(__file__).resolve().parent / "data"
        output = StringIO()
        with redirect_stdout(output):
            result = main(["--source", str(source)])
        self.assertEqual(result, 2)
        self.assertIn("Mode: dry-run", output.getvalue())
        self.assertIn("Field transformation validation: failed", output.getvalue())
        self.assertNotIn("passwordHash", output.getvalue())
        self.assertNotIn("@", output.getvalue())

    def test_legacy_timestamp_fails_by_default(self):
        stores = load_source(Path(__file__).resolve().parent / "data")
        with self.assertRaisesRegex(ImportValidationError, "invalid timestamp"):
            _rows_for_tables(stores)

    def test_explicit_exact_legacy_timestamp_rule_maps_only_known_value_to_null(self):
        source = Path(__file__).resolve().parent / "data"
        source_bytes = (source / "students.json").read_bytes()
        stores = load_source(source)
        before = json.dumps(stores, sort_keys=True)
        audit = []
        rows = _rows_for_tables(
            stores,
            approved_legacy_created_at_ids=frozenset({LEGACY_UNKNOWN_CREATED_AT["user_id"]}),
            audit_events=audit,
        )
        imported = next(row for row in rows["users"] if row["id"] == LEGACY_UNKNOWN_CREATED_AT["user_id"])
        self.assertIsNone(imported["created_at"])
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["field"], "createdAt")
        self.assertIsNone(audit[0]["planned_import_value"])
        self.assertNotIn("email", audit[0])
        self.assertEqual(json.dumps(stores, sort_keys=True), before)
        self.assertEqual((source / "students.json").read_bytes(), source_bytes)

    def test_approval_does_not_convert_arbitrary_invalid_timestamp_to_null(self):
        stores = load_source(Path(__file__).resolve().parent / "data")
        record = next(row for row in stores["students"] if row["id"] == LEGACY_UNKNOWN_CREATED_AT["user_id"])
        record["createdAt"] = "not-a-timestamp"
        with self.assertRaisesRegex(ImportValidationError, "invalid timestamp"):
            _rows_for_tables(
                stores,
                approved_legacy_created_at_ids=frozenset({LEGACY_UNKNOWN_CREATED_AT["user_id"]}),
            )

    def test_safe_anomaly_audit_report_is_non_sensitive_and_never_overwritten(self):
        stores = load_source(Path(__file__).resolve().parent / "data")
        audit = []
        _rows_for_tables(
            stores,
            approved_legacy_created_at_ids=frozenset({LEGACY_UNKNOWN_CREATED_AT["user_id"]}),
            audit_events=audit,
        )
        report = Path(__file__).resolve().parent / ".qa-temp" / "migration-audit-test.json"
        report.parent.mkdir(exist_ok=True)
        report.unlink(missing_ok=True)
        from import_json_to_postgres import _write_safe_audit_report
        try:
            _write_safe_audit_report(report, Path(__file__).resolve().parent / "data", audit, mode="dry-run")
            saved = json.loads(report.read_text(encoding="utf-8"))
            self.assertFalse(saved["personal_data_included"])
            self.assertNotIn("email", report.read_text(encoding="utf-8"))
            with self.assertRaisesRegex(ImportValidationError, "refusing to overwrite"):
                _write_safe_audit_report(report, Path(__file__).resolve().parent / "data", audit, mode="dry-run")
        finally:
            report.unlink(missing_ok=True)

    def test_valid_timestamp_needs_no_exception(self):
        stores = load_source(Path(__file__).resolve().parent / "data")
        record = next(row for row in stores["students"] if row["id"] == LEGACY_UNKNOWN_CREATED_AT["user_id"])
        record["createdAt"] = "2026-09-29T00:00:00+00:00"
        rows = _rows_for_tables(stores)
        imported = next(row for row in rows["users"] if row["id"] == LEGACY_UNKNOWN_CREATED_AT["user_id"])
        self.assertEqual(imported["created_at"].isoformat(), "2026-09-29T00:00:00+00:00")

    def test_invalid_reference_is_rejected_without_showing_row_contents(self):
        stores = load_source(Path(__file__).resolve().parent / "data")
        stores["students"] = [{"id": "student-safe-id", "email": "safe@example.test", "passwordHash": "never-print-this", "role": "student"}]
        stores["ai_sessions"] = [{"id": "session1", "student_id": "missing-user"}]
        with self.assertRaisesRegex(ImportValidationError, "unresolved reference") as caught:
            validate_source(stores)
        self.assertNotIn("never-print-this", str(caught.exception))


class PostgreSQLSchemaFoundationTests(unittest.TestCase):
    def test_alembic_head_fits_version_column_and_matches_importer_gate(self):
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        import import_json_to_postgres

        config = Config()
        config.set_main_option("script_location", str(Path(__file__).resolve().parent / "migrations"))
        script = ScriptDirectory.from_config(config)
        head = "0003_unknown_history_times"
        self.assertEqual(script.get_heads(), [head])
        revisions = list(script.walk_revisions())
        self.assertEqual([(r.revision, r.down_revision) for r in revisions], [
            (head, "0002_nullable_user_created_at"), ("0002_nullable_user_created_at", "0001_initial_schema"), ("0001_initial_schema", None),
        ])
        self.assertTrue(all(len(r.revision) <= 32 for r in revisions))
        tree = ast.parse(Path(import_json_to_postgres.__file__).read_text(encoding="utf-8"))
        apply_import = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "_apply_import")
        gates = [node for node in ast.walk(apply_import) if isinstance(node, ast.Compare)
                 and isinstance(node.left, ast.Call) and isinstance(node.left.func, ast.Attribute)
                 and node.left.func.attr == "scalar_one_or_none"]
        self.assertEqual(len(gates), 1)
        self.assertIsInstance(gates[0].ops[0], ast.NotEq)
        self.assertEqual(gates[0].comparators[0].id, "EXPECTED_REVISION")
        self.assertEqual(import_json_to_postgres.EXPECTED_REVISION, head)

    def test_offline_upgrade_and_downgrade_use_compatible_revision(self):
        from alembic import command
        from alembic.config import Config

        config = Config()
        config.set_main_option("script_location", str(Path(__file__).resolve().parent / "migrations"))
        head = "0003_unknown_history_times"
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://offline:offline@localhost/offline"}):
            config.output_buffer = StringIO()
            command.upgrade(config, "head", sql=True)
            upgrade = config.output_buffer.getvalue()
            capacity = int(re.search(r"version_num VARCHAR\((\d+)\)", upgrade).group(1))
            self.assertLessEqual(len(head), capacity)
            self.assertIn(head, upgrade)
            self.assertIn("ALTER TABLE users ALTER COLUMN created_at DROP NOT NULL", upgrade)
            config.output_buffer = StringIO()
            command.downgrade(config, "head:base", sql=True)
            downgrade = config.output_buffer.getvalue()
            self.assertIn(head, downgrade)
            self.assertIn("Cannot restore NOT NULL while unknown legacy timestamps exist", downgrade)
            self.assertIn("ALTER TABLE users ALTER COLUMN created_at SET NOT NULL", downgrade)
            self.assertIn("DROP TABLE IF EXISTS users CASCADE", downgrade)

    def test_initial_schema_contains_all_json_domains_and_relationship_tables(self):
        tables = set(Base.metadata.tables)
        expected = {
            "users", "student_profiles", "courses", "lessons", "lesson_completions",
            "homework", "homework_assignments", "homework_submissions", "classes",
            "class_students", "community_posts", "community_post_likes", "community_replies",
            "community_reports", "conversations", "conversation_participants", "messages",
            "message_reads", "notifications", "ai_sessions", "ai_messages", "ai_usage_events",
            "gamification_state", "user_badges", "gamification_actions", "revoked_tokens",
        }
        self.assertEqual(tables, expected)
        self.assertTrue(Base.metadata.tables["ai_messages"].foreign_keys)

    def test_alembic_initial_revision_is_frozen_and_offline_generatable(self):
        revision = Path(__file__).resolve().parent / "migrations" / "versions" / "0001_initial_schema.py"
        source = revision.read_text(encoding="utf-8")
        self.assertIn("SCHEMA_STATEMENTS", source)
        self.assertNotIn("Base.metadata.create_all", source)

    def test_legacy_timestamp_revision_allows_null_and_guards_downgrade(self):
        table = Base.metadata.tables["users"]
        self.assertTrue(table.c.created_at.nullable)
        revision = Path(__file__).resolve().parent / "migrations" / "versions" / "0002_nullable_user_created_at.py"
        source = revision.read_text(encoding="utf-8")
        self.assertIn('down_revision = "0001_initial_schema"', source)
        self.assertIn("Cannot restore NOT NULL", source)


if __name__ == "__main__":
    unittest.main()
