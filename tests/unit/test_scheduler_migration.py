"""Additive migration preserves real edit receipts, checkpoints and undo blobs."""
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from harness.core.models import StreamChunk
from harness.core.runtime_models import ModelProfile
from harness.core.service import CoreService
from harness.storage.runtime import RuntimeStore, SCHEMA


PROFILE = ModelProfile("migration", "worker", "fixture", "fixture", frozenset({"text", "code_tools"}))


class Engine:
    def __init__(self):
        self.calls = 0

    def stream(self, *args):
        self.calls += 1
        if self.calls == 1:
            yield StreamChunk(tool_call_deltas=[{"index": 0, "id": "edit", "function": {"name": "edit_file",
                "arguments": json.dumps({"path": "data.txt", "old_str": "old", "new_str": "new"})}}], finish_reason="tool_calls")
        else:
            yield StreamChunk(delta_content="done", finish_reason="stop")
        yield StreamChunk(stream_complete=True)


class SchedulerMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fc-v1-migration-")
        self.base = Path(self.temp.name)
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        (self.workspace / "data.txt").write_text("old")
        core = CoreService(self.workspace, Engine(), PROFILE, state_dir=self.base / "source", system_prompt="fixture")
        self.task_id = core.submit("edit")
        self.assertEqual(core.run(self.task_id, approval_resolver=lambda *_: True)["status"], "completed")
        core.close()
        self.directory = self.base / "v1"
        self.directory.mkdir()
        source = sqlite3.connect(self.base / "source" / "runtime.sqlite3")
        target = sqlite3.connect(self.directory / "runtime.sqlite3")
        target.executescript(SCHEMA)
        self.before = {}
        for (table,) in target.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            rows = source.execute('SELECT * FROM "' + table + '"').fetchall()
            self.before[table] = rows
            if rows:
                target.executemany('INSERT INTO "' + table + '" VALUES(' + ','.join('?' for _ in rows[0]) + ')', rows)
        target.execute("PRAGMA user_version=1")
        target.commit()
        source.close()
        target.close()
        shutil.copytree(self.base / "source" / "blobs", self.directory / "blobs")

    def tearDown(self):
        self.temp.cleanup()

    def test_version_one_rows_ids_and_blobs_survive_migration(self):
        store = RuntimeStore(self.workspace, self.directory)
        try:
            self.assertEqual(store.one("PRAGMA user_version")["user_version"], 2)
            for table, rows in self.before.items():
                self.assertEqual([tuple(row.values()) for row in store.all('SELECT * FROM "' + table + '"')], rows)
            self.assertEqual(store.all("PRAGMA foreign_key_check"), [])
        finally:
            store.close()
        engine = Engine()
        core = CoreService(self.workspace, engine, PROFILE, state_dir=self.directory, system_prompt="fixture")
        try:
            self.assertEqual(core.run(self.task_id)["status"], "completed")
            self.assertEqual(engine.calls, 0)
            self.assertEqual(core.undo_last(approval_callback=lambda *_: True)["status"], "success")
            self.assertEqual((self.workspace / "data.txt").read_text(), "old")
        finally:
            core.close()

    def test_failed_migration_rolls_back_without_changing_version_or_rows(self):
        connection = sqlite3.connect(self.directory / "runtime.sqlite3")
        connection.execute("CREATE TABLE workers(collision TEXT)")
        connection.commit()
        connection.close()
        with self.assertRaises(sqlite3.OperationalError):
            RuntimeStore(self.workspace, self.directory)
        connection = sqlite3.connect(self.directory / "runtime.sqlite3")
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='model_profiles'").fetchone())
        for table, rows in self.before.items():
            self.assertEqual(connection.execute('SELECT * FROM "' + table + '"').fetchall(), rows)
        connection.close()

    def test_legacy_unknown_allocation_requires_explicit_reconciliation(self):
        connection = sqlite3.connect(self.directory / "runtime.sqlite3")
        connection.execute("INSERT OR REPLACE INTO metadata VALUES('allocation',?)", ('{"state":"quarantined"}',))
        connection.commit()
        connection.close()
        core = CoreService(self.workspace, Engine(), PROFILE, state_dir=self.directory, system_prompt="fixture")
        try:
            task_id = core.submit("new", allowed_tools=[])
            self.assertEqual(core.run(task_id)["status"], "paused")
            self.assertEqual(core.inference.allocation()["state"], "quarantined")
            with self.assertRaises(ValueError):
                core.inference.reconcile_idle(lambda *_: False)
            self.assertEqual(core.inference.reconcile_idle(lambda *_: True)["state"], "idle")
        finally:
            core.close()


if __name__ == "__main__":
    unittest.main()
