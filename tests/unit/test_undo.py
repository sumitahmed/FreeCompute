"""
tests/unit/test_undo.py — Unit tests for transactional file snapshotting and undo rollback.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from harness.storage.undo import UndoManager


class TestUndoManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="freecompute_undo_test_")
        self.workspace = Path(self.test_dir) / "workspace"
        self.storage = Path(self.test_dir) / "storage"
        self.workspace.mkdir()
        self.storage.mkdir()
        self.undo_mgr = UndoManager(
            workspace_root=str(self.workspace),
            storage_dir=str(self.storage),
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_undo_restores_modified_file(self):
        # 1. Create original file
        target_file = self.workspace / "sample.py"
        target_file.write_text("def hello():\n    return 'original'\n", encoding="utf-8")

        # 2. Record pre-change snapshot
        self.undo_mgr.record_pre_change(
            target_path="sample.py",
            operation="edit_file",
            diff="- return 'original'\n+ return 'modified'",
        )

        # 3. Simulate agent modifying the file
        target_file.write_text("def hello():\n    return 'modified'\n", encoding="utf-8")
        self.assertEqual(target_file.read_text(encoding="utf-8"), "def hello():\n    return 'modified'\n")

        # 4. Trigger undo
        res = self.undo_mgr.undo_last()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["action"], "restored")

        # 5. Verify restored content matches original
        self.assertEqual(target_file.read_text(encoding="utf-8"), "def hello():\n    return 'original'\n")

    def test_undo_deletes_newly_created_file(self):
        # 1. Record pre-change on a non-existent file
        new_file = self.workspace / "created.py"
        self.assertFalse(new_file.exists())

        self.undo_mgr.record_pre_change(
            target_path="created.py",
            operation="write_file",
            diff="+ print('new file')",
        )

        # 2. Simulate agent creating the file
        new_file.write_text("print('new file')\n", encoding="utf-8")
        self.assertTrue(new_file.exists())

        # 3. Trigger undo
        res = self.undo_mgr.undo_last()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["action"], "deleted")

        # 4. Verify file is deleted
        self.assertFalse(new_file.exists())

    def test_empty_undo_returns_safe_status(self):
        res = self.undo_mgr.undo_last()
        self.assertEqual(res["status"], "empty")

    def test_history_persistence_and_reload(self):
        f = self.workspace / "file.txt"
        f.write_text("v1", encoding="utf-8")
        self.undo_mgr.record_pre_change("file.txt", "edit_file", "v1 -> v2")

        # Create a second manager pointing to the same storage dir
        reloaded_mgr = UndoManager(
            workspace_root=str(self.workspace),
            storage_dir=str(self.storage),
        )
        history = reloaded_mgr.get_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["operation"], "edit_file")
        self.assertTrue(history[0]["has_backup"])


if __name__ == "__main__":
    unittest.main()
