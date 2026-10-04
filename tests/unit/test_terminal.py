"""
tests/unit/test_terminal.py — Unit tests for local command runner.
"""

import tempfile
import sys
import unittest
from unittest.mock import patch
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

    def test_format_in_python_expression_is_a_definitive_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            res = terminal.run_command(f'"{sys.executable}" -c "print(format(7, \'d\'))"', workspace_root=tmpdir)
            self.assertEqual(res["exit_code"], 0)
            self.assertEqual(res["stdout"].strip(), "7")
            self.assertTrue(res["owned_process_exit_confirmed"])

    def test_format_utilities_remain_blocked_before_subprocess_start(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(terminal.subprocess, "Popen") as start:
            for command in ('format d:', 'FORMAT.COM d:', 'format.exe d:', 'format/Q d:',
                            'echo safe & format d:', 'powershell -Command "format d:"'):
                with self.subTest(command=command), self.assertRaises(SandboxSecurityViolation):
                    terminal.run_command(command, workspace_root=tmpdir)
            start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
