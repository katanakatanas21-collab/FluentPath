"""Historical mapping tests; database tests use synthetic data and local SQLite.

The real apply code runs against a real SQLAlchemy transaction via a small async
adapter. No configured database URL, staging connection, or provider is used.
This verifies transactional row rollback, not PostgreSQL sequence rollback.
"""
import asyncio
import copy
import json
import os
import unittest
from contextlib import asynccontextmanager, redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles, deregister

import import_json_to_postgres as imp
from db.base import Base
from db import models  # noqa: F401

SOURCE = Path(__file__).resolve().parent / 'data'
APPROVAL = frozenset({imp.LEGACY_UNKNOWN_CREATED_AT['user_id']})
STAMP = '2026-09-01T01:02:03+00:00'


def fixture():
    stores = {name: [] for name in imp.STORE_NAMES}
    known = next(u for u in imp.load_source(SOURCE)['students'] if u['id'] in APPROVAL)
    stores['students'] = [{'id': known['id'], 'createdAt': known['createdAt'],
        'email': 'synthetic@example.test', 'passwordHash': 'synthetic-only', 'role': 'student',
        'courseProgress': {'course': {'completedLessons': ['lesson'], 'updatedAt': STAMP}}}]
    stores['courses'] = [{'id': 'course', 'title': 'Synthetic', 'lessons': [
        {'id': 'lesson', 'created_at': STAMP, 'updated_at': STAMP}]}]
    return stores


class HistoricalMappingTests(unittest.TestCase):
    def plan(self, stores):
        return imp._rows_for_tables(stores, approved_legacy_created_at_ids=APPROVAL)

    def test_current_dataset_unknowns_and_preserved_state(self):
        stores = imp.load_source(SOURCE)
        before = copy.deepcopy(stores)
        rows = self.plan(stores)
        self.assertEqual(stores, before)
        self.assertEqual(sum(len(v) for v in rows.values()), 62)
        self.assertEqual(len(rows['gamification_state']), 3)
        self.assertEqual(rows['gamification_actions'], [])
        self.assertEqual(sum(len(r['legacy_gamification'].get('awardedActions', [])) for r in rows['student_profiles']), 3)
        self.assertEqual(sum(r['created_at'] is None for r in rows['courses']), 16)
        self.assertEqual(sum(r['updated_at'] is None for r in rows['courses']), 16)
        self.assertIsNone(rows['classes'][0]['created_at'])
        self.assertEqual([r['completed_at'] for r in rows['lesson_completions']], [None, None])
        self.assertEqual(rows['homework'][0]['status'], 'published')

    def test_two_cli_dry_runs_plan_identical_data_without_wall_clock(self):
        plans = []
        original = imp._rows_for_tables
        def capture(*args, **kwargs):
            result = original(*args, **kwargs)
            plans.append(copy.deepcopy(result))
            return result
        class NoClock(datetime):
            @classmethod
            def now(cls, *args, **kwargs):
                raise AssertionError('Import must not consult the wall clock')
        with patch.object(imp, 'load_source', return_value=imp.load_source(SOURCE)), \
             patch.object(imp, '_rows_for_tables', side_effect=capture), \
             patch.object(imp, '_write_safe_audit_report'), \
             patch.object(imp, 'datetime', NoClock), \
             patch('sqlalchemy.ext.asyncio.create_async_engine', side_effect=AssertionError('Dry-run connected')):
            for _ in range(2):
                with redirect_stdout(StringIO()):
                    self.assertEqual(imp.main(['--source', str(SOURCE), '--allow-legacy-unknown-created-at', next(iter(APPROVAL)), '--audit-report', 'unused-test-report']), 0)
        self.assertEqual(len(plans), 2)
        self.assertEqual(plans[0], plans[1])
        self.assertNotIn('datetime.now', Path(imp.__file__).read_text(encoding='utf-8'))

    def test_source_timestamp_aliases_are_deterministic_and_conflicts_rejected(self):
        stores = fixture()
        stores['courses'][0].update(createdAt=STAMP, updated_at=STAMP)
        row = self.plan(stores)['courses'][0]
        self.assertEqual(row['created_at'], datetime.fromisoformat(STAMP))
        self.assertEqual(row['updated_at'], datetime.fromisoformat(STAMP))
        stores['courses'][0]['created_at'] = '2025-01-01T00:00:00Z'
        with self.assertRaises(imp.ImportValidationError): self.plan(stores)

    def test_other_malformed_missing_and_naive_timestamps_fail_closed(self):
        for value in ('bad', '', False, '2026-01-01', '2026-01-01T12:00:00'):
            stores = fixture()
            stores['courses'][0]['created_at'] = value
            with self.subTest(value_type=type(value).__name__), self.assertRaises(imp.ImportValidationError):
                self.plan(stores)
        stores = fixture()
        del stores['courses'][0]['lessons'][0]['created_at']
        with self.assertRaisesRegex(imp.ImportValidationError, 'Unknown required'): self.plan(stores)
        stores = fixture()
        stores['students'][0]['courseProgress']['course']['updatedAt'] = 'bad'
        with self.assertRaises(imp.ImportValidationError): self.plan(stores)

    def test_only_complete_action_evidence_becomes_an_event(self):
        stores = fixture()
        game = {'xp': 17, 'currentStreak': 1, 'longestStreak': 2,
                'awardedActions': ['dedup-only', {'key': 'incomplete'}, {'key': 'event', 'xp': 7, 'createdAt': STAMP}]}
        stores['students'][0]['gamification'] = game
        rows = self.plan(stores)
        self.assertEqual(len(rows['gamification_actions']), 1)
        self.assertEqual(rows['gamification_actions'][0]['xp_awarded'], 7)
        self.assertEqual(rows['gamification_actions'][0]['created_at'], datetime.fromisoformat(STAMP))
        self.assertEqual(rows['gamification_state'][0]['xp'], 17)
        self.assertEqual(rows['student_profiles'][0]['legacy_gamification'], game)
        game['awardedActions'].append({'key': 'invalid', 'createdAt': 'bad'})
        with self.assertRaises(imp.ImportValidationError): self.plan(stores)


class LocalDatabaseAdapter:
    """Async interface over an actual isolated SQLAlchemy SQLite connection."""
    def __init__(self, engine, fail_after=None, corrupt_counts=False, commit_error=False):
        self.engine = engine
        self.fail_after = fail_after
        self.corrupt_counts = corrupt_counts
        self.commit_error = commit_error
        self.insert_calls = 0
        self.rows_seen_before_failure = 0
        self.count_calls = 0

    @asynccontextmanager
    async def connect(self):
        with self.engine.connect() as sync:
            adapter = self
            class Connection:
                dialect = sync.dialect
                async def begin(self):
                    tx = sync.begin()
                    class Transaction:
                        async def rollback(self): tx.rollback()
                        async def commit(self):
                            if adapter.commit_error:
                                raise RuntimeError('simulated lost response')
                            tx.commit()
                    return Transaction()
                async def run_sync(self, fn):
                    result = fn(sync)
                    if isinstance(result, dict):
                        adapter.count_calls += 1
                        if adapter.corrupt_counts and adapter.count_calls == 2:
                            result['users'] += 1
                    return result
                async def exec_driver_sql(self, sql): return sync.exec_driver_sql(sql)
                async def execute(self, statement, values):
                    adapter.insert_calls += 1
                    if adapter.fail_after == adapter.insert_calls:
                        adapter.rows_seen_before_failure = sum(imp._application_table_counts(sync, Base.metadata).values())
                        # Genuine DB constraint failure, not an exception-only mock.
                        return sync.exec_driver_sql("INSERT INTO courses (id) VALUES ('injected-failure')")
                    return sync.execute(statement, values)
            yield Connection()

    async def dispose(self): pass  # Keep memory DB alive for independent assertions.


class ApplyTransactionTests(unittest.TestCase):
    def setUp(self):
        compiles(JSONB, 'sqlite')(lambda element, compiler, **kw: 'JSON')
        self.engine = create_engine('sqlite:///:memory:')
        @event.listens_for(self.engine, 'connect')
        def foreign_keys(connection, _): connection.execute('PRAGMA foreign_keys=ON')
        Base.metadata.create_all(self.engine)
        with self.engine.begin() as conn:
            conn.exec_driver_sql('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)')
            conn.exec_driver_sql('INSERT INTO alembic_version VALUES (?)', (imp.EXPECTED_REVISION,))
        self.directory = SOURCE.parent / '.qa-tests' / ('import-' + uuid4().hex)
        self.directory.mkdir(parents=True)
        self.audit = self.directory / 'audit.json'
        self.stores = fixture()
        events = []
        imp._rows_for_tables(self.stores, approved_legacy_created_at_ids=APPROVAL, audit_events=events)
        imp._write_safe_audit_report(self.audit, SOURCE, events, mode='apply')

    def tearDown(self):
        self.engine.dispose()
        deregister(JSONB)
        for path in self.directory.iterdir(): path.unlink()
        self.directory.rmdir()

    def apply(self, adapter, **kwargs):
        with patch('sqlalchemy.ext.asyncio.create_async_engine', return_value=adapter):
            asyncio.run(imp._apply_import(self.stores, 'postgresql://unused/unused', audit_report=self.audit, **kwargs))

    def status(self): return json.loads(self.audit.read_text(encoding='utf-8'))['status']

    def assert_empty(self):
        with self.engine.connect() as conn:
            self.assertEqual(set(imp._application_table_counts(conn, Base.metadata).values()), {0})

    def test_apply_preserves_exact_approved_legacy_null_and_commits_report(self):
        self.apply(LocalDatabaseAdapter(self.engine), approved_legacy_created_at_ids=APPROVAL)
        with self.engine.connect() as conn:
            self.assertIsNone(conn.exec_driver_sql('SELECT created_at FROM users').scalar_one())
            self.assertEqual(sum(imp._application_table_counts(conn, Base.metadata).values()), 5)
        self.assertEqual(self.status(), 'committed')
        text = self.audit.read_text(encoding='utf-8')
        self.assertNotIn('synthetic@example.test', text)
        self.assertNotIn('synthetic-only', text)

    def test_apply_rejects_unapproved_changed_or_missing_legacy_value_before_connection(self):
        for value, approvals in [(self.stores['students'][0]['createdAt'], frozenset()), ('bad', APPROVAL), (None, APPROVAL)]:
            self.stores['students'][0]['createdAt'] = value
            with patch('sqlalchemy.ext.asyncio.create_async_engine', side_effect=AssertionError('Connected')):
                with self.assertRaises(imp.ImportValidationError):
                    asyncio.run(imp._apply_import(self.stores, 'postgresql://unused/unused', approved_legacy_created_at_ids=approvals))
        self.assert_empty()

    def test_same_path_classification_with_wrong_digest_is_rejected(self):
        self.stores['students'][0]['createdAt'] = 'C:\\different\\legacy-value'
        with patch('sqlalchemy.ext.asyncio.create_async_engine', side_effect=AssertionError('Connected')):
            with self.assertRaises(imp.ImportValidationError):
                asyncio.run(imp._apply_import(self.stores, 'postgresql://unused/unused', approved_legacy_created_at_ids=APPROVAL))
        self.assert_empty()

    def test_exact_known_value_on_another_user_is_rejected(self):
        self.stores['students'][0]['id'] = 'different-user'
        with patch('sqlalchemy.ext.asyncio.create_async_engine', side_effect=AssertionError('Connected')):
            with self.assertRaises(imp.ImportValidationError):
                asyncio.run(imp._apply_import(self.stores, 'postgresql://unused/unused', approved_legacy_created_at_ids=APPROVAL))
        self.assert_empty()

    def test_mid_import_database_failure_rolls_back_every_application_row(self):
        from sqlalchemy.exc import IntegrityError
        adapter = LocalDatabaseAdapter(self.engine, fail_after=3)
        with self.assertRaises(IntegrityError): self.apply(adapter, approved_legacy_created_at_ids=APPROVAL)
        self.assertGreater(adapter.rows_seen_before_failure, 0)
        self.assert_empty()
        self.assertEqual(self.status(), 'rolled_back')

    def test_precommit_reconciliation_failure_rolls_back_every_row(self):
        with self.assertRaisesRegex(imp.ImportValidationError, 'reconciliation'):
            self.apply(LocalDatabaseAdapter(self.engine, corrupt_counts=True), approved_legacy_created_at_ids=APPROVAL)
        self.assert_empty()
        self.assertEqual(self.status(), 'rolled_back')

    def test_old_staging_revision_is_rejected_without_any_insert(self):
        with self.engine.begin() as conn:
            conn.exec_driver_sql("UPDATE alembic_version SET version_num='0002_nullable_user_created_at'")
        adapter = LocalDatabaseAdapter(self.engine)
        with self.assertRaisesRegex(imp.ImportValidationError, 'revision'):
            self.apply(adapter, approved_legacy_created_at_ids=APPROVAL)
        self.assertEqual(adapter.insert_calls, 0)
        self.assert_empty()

    def test_commit_response_failure_is_not_reported_as_rollback(self):
        with self.assertRaises(RuntimeError):
            self.apply(LocalDatabaseAdapter(self.engine, commit_error=True), approved_legacy_created_at_ids=APPROVAL)
        self.assertEqual(self.status(), 'commit_outcome_unknown_verify_target')

    def test_cli_passes_approval_to_real_apply_path(self):
        self.audit.unlink()
        env = {'FLUENT_PATH_ENVIRONMENT': 'staging', 'FLUENT_PATH_IMPORT_CONFIRM': 'I_CONFIRM_STAGING_IMPORT', 'IMPORT_DATABASE_URL': 'postgresql://unused@localhost/local_staging'}
        with patch.dict(os.environ, env), patch.object(imp, 'load_source', return_value=self.stores), \
             patch('sqlalchemy.ext.asyncio.create_async_engine', return_value=LocalDatabaseAdapter(self.engine)), redirect_stdout(StringIO()):
            result = imp.main(['--source', str(SOURCE), '--apply', '--confirm-target', 'localhost/local_staging',
                '--allow-legacy-unknown-created-at', next(iter(APPROVAL)), '--audit-report', str(self.audit)])
        self.assertEqual(result, 0)
        self.assertEqual(self.status(), 'committed')


class HistoricalMigrationTests(unittest.TestCase):
    def test_exact_nullable_scope_and_offline_upgrade_downgrade(self):
        from alembic import command
        from alembic.config import Config
        import importlib.util
        path = SOURCE.parent / 'migrations/versions/0003_unknown_history_times.py'
        spec = importlib.util.spec_from_file_location('historical_revision', path)
        revision = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(revision)
        columns = {('courses','created_at'),('courses','updated_at'),('classes','created_at'),('lesson_completions','completed_at')}
        self.assertEqual(set(revision.COLUMNS), columns)
        for table, col in columns: self.assertTrue(Base.metadata.tables[table].c[col].nullable)
        self.assertFalse(Base.metadata.tables['classes'].c.starts_at.nullable)
        self.assertFalse(Base.metadata.tables['lessons'].c.created_at.nullable)
        config = Config()
        config.set_main_option('script_location', str(SOURCE.parent / 'migrations'))
        with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://offline:offline@localhost/offline'}):
            config.output_buffer = StringIO()
            command.upgrade(config, '0002_nullable_user_created_at:head', sql=True)
            upgrade = config.output_buffer.getvalue()
            config.output_buffer = StringIO()
            command.downgrade(config, 'head:0002_nullable_user_created_at', sql=True)
            downgrade = config.output_buffer.getvalue()
        self.assertEqual(upgrade.count('DROP NOT NULL'), 4)
        self.assertEqual(downgrade.count('SET NOT NULL'), 4)
        for table, col in columns:
            self.assertIn(f'ALTER TABLE {table} ALTER COLUMN {col} DROP NOT NULL', upgrade)
            self.assertIn(f'WHERE {col} IS NULL', downgrade)
        self.assertLess(downgrade.index('RAISE EXCEPTION'), downgrade.index('SET NOT NULL'))
        self.assertNotIn('UPDATE courses', upgrade)
        self.assertNotIn('now()', upgrade)
        import re
        changes = re.findall(r'ALTER TABLE (\w+) ALTER COLUMN (\w+) (DROP|SET) NOT NULL;', upgrade)
        self.assertEqual(set(changes), {(table, col, 'DROP') for table, col in columns})
        self.assertEqual(upgrade.count('ALTER TABLE'), 4)
        self.assertNotRegex(upgrade, r'CREATE (?:TABLE|INDEX)|DROP (?:TABLE|INDEX)|ADD COLUMN|DROP COLUMN')


if __name__ == '__main__': unittest.main()
