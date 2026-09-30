"""
tests/unit/test_skills.py — Unit tests for SkillManager, frontmatter parsing, and slash commands.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from harness.skills.manager import SkillManager, SkillManifest


class TestSkillManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="freecompute_skills_test_")
        self.workspace = Path(self.test_dir) / "workspace"
        self.user_dir = Path(self.test_dir) / "user_skills"
        self.workspace.mkdir()
        self.user_dir.mkdir()

        # Create mock project skill
        p_skill = self.workspace / "skills" / "mock-skill"
        p_skill.mkdir(parents=True)
        (p_skill / "SKILL.md").write_text(
            "---\n"
            "name: mock-skill\n"
            "description: A mock project skill\n"
            "slash_command: /mock\n"
            "allowed_tools:\n"
            "  - inspect_file\n"
            "---\n"
            "# Mock Instructions\n"
            "Do something useful.\n",
            encoding="utf-8",
        )

        self.mgr = SkillManager(
            workspace_root=str(self.workspace),
            user_skills_dir=str(self.user_dir),
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_discover_project_skill(self):
        skill = self.mgr.get_skill("mock-skill")
        self.assertIsNotNone(skill)
        self.assertEqual(skill.name, "mock-skill")
        self.assertEqual(skill.description, "A mock project skill")
        self.assertEqual(skill.slash_command, "/mock")
        self.assertEqual(skill.allowed_tools, ["inspect_file"])
        self.assertEqual(skill.scope, "project")
        self.assertIn("Do something useful.", skill.instructions)

    def test_lookup_by_slash_command(self):
        skill = self.mgr.get_skill("/mock")
        self.assertIsNotNone(skill)
        self.assertEqual(skill.name, "mock-skill")

    def test_build_skill_prompt(self):
        skill = self.mgr.get_skill("mock-skill")
        prompt = self.mgr.build_skill_prompt(skill, user_args="target.py")
        self.assertIn("[ACTIVE SKILL: MOCK-SKILL]", prompt)
        self.assertIn("Do something useful.", prompt)
        self.assertIn("User Input/Target: target.py", prompt)

    def test_project_skill_overrides_user_skill(self):
        # Create user skill with same name but different description
        u_skill = self.user_dir / "mock-skill"
        u_skill.mkdir(parents=True)
        (u_skill / "SKILL.md").write_text(
            "---\n"
            "name: mock-skill\n"
            "description: User-level version\n"
            "slash_command: /mock\n"
            "---\n"
            "User instructions\n",
            encoding="utf-8",
        )

        reloaded = SkillManager(
            workspace_root=str(self.workspace),
            user_skills_dir=str(self.user_dir),
        )
        skill = reloaded.get_skill("mock-skill")
        self.assertIsNotNone(skill)
        # Project-level takes precedence
        self.assertEqual(skill.description, "A mock project skill")
        self.assertEqual(skill.scope, "project")

    def test_format_skills_list(self):
        table = self.mgr.format_skills_list()
        self.assertIn("/mock", table)
        self.assertIn("mock-skill", table)
        self.assertIn("A mock project skill", table)

    def test_live_project_starter_skills_discovery(self):
        # Point to the actual workspace skills directory
        live_mgr = SkillManager(workspace_root=".")
        skills = live_mgr.discover_skills()
        self.assertIn("code-reviewer", skills)
        self.assertIn("neetcode-solver", skills)
        self.assertIn("web-researcher", skills)
        self.assertIsNotNone(live_mgr.get_skill("/review"))
        self.assertIsNotNone(live_mgr.get_skill("/leetcode"))
        self.assertIsNotNone(live_mgr.get_skill("/research"))


if __name__ == "__main__":
    unittest.main()
