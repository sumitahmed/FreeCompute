"""
tests/unit/test_fs_tools.py — Unit tests for read_file, write_file, edit_file, list_dir, and grep_search.
"""

import tempfile
import unittest
from pathlib import Path

from harness.tools import fs


class TestFileSystemTools(unittest.TestCase):
    def test_write_and_read_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. Write file
            res_write = fs.write_file("test.py", "def hello():\n    return 42\n", workspace_root=tmpdir)
            self.assertEqual(res_write["status"], "created")

            # 2. Read full file
            res_read = fs.read_file("test.py", workspace_root=tmpdir)
            self.assertEqual(res_read["total_lines"], 2)
            self.assertIn("1: def hello():", res_read["content"])

            # 3. Read slice
            res_slice = fs.read_file("test.py", start_line=2, end_line=2, workspace_root=tmpdir)
            self.assertIn("2:     return 42", res_slice["content"])
            self.assertNotIn("1: def hello():", res_slice["content"])

    def test_edit_file_surgical_patch_and_diff(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            initial = "def compute(x):\n    return x * 2\n"
            fs.write_file("calc.py", initial, workspace_root=tmpdir)

            # Surgical replacement
            old_str = "    return x * 2"
            new_str = "    return x * 3  # Tripled"
            res_edit = fs.edit_file("calc.py", old_str, new_str, workspace_root=tmpdir)

            self.assertEqual(res_edit["status"], "applied")
            self.assertIn("-    return x * 2", res_edit["diff"])
            self.assertIn("+    return x * 3  # Tripled", res_edit["diff"])

            # Verify file content on disk
            updated = fs.read_file("calc.py", workspace_root=tmpdir)["raw_content"]
            self.assertIn("return x * 3  # Tripled", updated)

    def test_edit_file_error_on_missing_or_ambiguous(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fs.write_file("dup.py", "val = 1\nval = 1\n", workspace_root=tmpdir)

            # Ambiguous (matches twice)
            with self.assertRaises(ValueError):
                fs.edit_file("dup.py", "val = 1", "val = 2", workspace_root=tmpdir)

            # Missing pattern
            with self.assertRaises(ValueError):
                fs.edit_file("dup.py", "nonexistent = 99", "val = 2", workspace_root=tmpdir)

    def test_list_dir_and_grep_search(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fs.write_file("module/sub.py", "KEYWORD_FLAG = 'activated'\n", workspace_root=tmpdir)
            fs.write_file("main.py", "import module.sub\n", workspace_root=tmpdir)

            # List dir
            listed = fs.list_dir(".", pattern="*.py", workspace_root=tmpdir)
            self.assertEqual(listed["count"], 1)  # main.py

            # Grep search
            grep_res = fs.grep_search("KEYWORD_FLAG", workspace_root=tmpdir)
            self.assertEqual(grep_res["total_matches"], 1)
            self.assertIn("activated", grep_res["matches"][0]["text"])


if __name__ == "__main__":
    unittest.main()
