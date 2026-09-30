"""
tests/unit/test_sandbox.py — Unit tests for workspace security and path traversal protection.
"""

import tempfile
import unittest
from pathlib import Path

from harness.tools.sandbox import validate_workspace_path, SandboxSecurityViolation


class TestSandboxSecurity(unittest.TestCase):
    def test_safe_paths_within_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            sub = root / "src" / "parser.py"

            resolved = validate_workspace_path("src/parser.py", workspace_root=str(root))
            self.assertEqual(resolved, sub)

    def test_path_traversal_detection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()

            # Attempting to escape via ../
            with self.assertRaises(SandboxSecurityViolation):
                validate_workspace_path("../../etc/passwd", workspace_root=str(root))

            with self.assertRaises(SandboxSecurityViolation):
                validate_workspace_path("../outside.txt", workspace_root=str(root))

    def test_protected_files_and_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()

            # Attempting to read .env
            with self.assertRaises(SandboxSecurityViolation):
                validate_workspace_path(".env", workspace_root=str(root))

            # Attempting to access private keys
            with self.assertRaises(SandboxSecurityViolation):
                validate_workspace_path("server.key", workspace_root=str(root))

            # Attempting to access .git internals
            with self.assertRaises(SandboxSecurityViolation):
                validate_workspace_path(".git/config", workspace_root=str(root))


if __name__ == "__main__":
    unittest.main()
