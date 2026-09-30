"""
tests/unit/test_terminal.py — Unit tests for local command runner.
"""

import tempfile
import unittest
from harness.tools import terminal
from harness.tools.sandbox import SandboxSecurityViolation


class TestTerminalRunner(unittest.TestCase):
    def test_run_command_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            res = terminal.run_command("python -c \"print('runner_ok')\"", cwd=".", workspace_root=tmpdir)
            self.assertEqual(res["exit_code"], 0)
            self.assertIn("runner_ok", res["stdout"])
            self.assertFalse(res["timed_out"])
            self.assertGreater(res["duration_ms"], 0)

    def test_block_hazardous_commands(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(SandboxSecurityViolation):
                terminal.run_command("rmdir /s /q c:", workspace_root=tmpdir)

            with self.assertRaises(SandboxSecurityViolation):
                terminal.run_command("format d:", workspace_root=tmpdir)


if __name__ == "__main__":
    unittest.main()
