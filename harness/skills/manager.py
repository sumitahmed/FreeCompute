"""
harness/skills/manager.py — Skill discovery, SKILL.md manifest parser, and slash-command dispatcher.
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import yaml


class SkillManifest:
    """Represents a loaded skill specification parsed from a SKILL.md file."""

    def __init__(
        self,
        name: str,
        description: str,
        instructions: str,
        slash_command: Optional[str] = None,
        allowed_tools: Optional[List[str]] = None,
        source_path: str = "",
        scope: str = "project",
    ):
        self.name = name.strip()
        self.description = description.strip()
        self.instructions = instructions.strip()
        self.slash_command = slash_command.strip() if slash_command else f"/{self.name}"
        if not self.slash_command.startswith("/"):
            self.slash_command = f"/{self.slash_command}"
        self.allowed_tools = allowed_tools or []
        self.source_path = source_path
        self.scope = scope  # "project" or "user"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "slash_command": self.slash_command,
            "allowed_tools": self.allowed_tools,
            "source_path": self.source_path,
            "scope": self.scope,
        }


class SkillManager:
    """
    Manages discovery, loading, and resolution of agent skills across project
    and user configurations.
    """

    FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)

    def __init__(self, workspace_root: str = ".", user_skills_dir: Optional[str] = None):
        self.workspace_root = Path(workspace_root).resolve()
        self.project_skills_dir = self.workspace_root / "skills"
        if user_skills_dir:
            self.user_skills_dir = Path(user_skills_dir).expanduser().resolve()
        else:
            self.user_skills_dir = (Path.home() / ".freecompute" / "skills").resolve()

        self.skills: Dict[str, SkillManifest] = {}
        self.command_map: Dict[str, SkillManifest] = {}
        self.discover_skills()

    def discover_skills(self) -> Dict[str, SkillManifest]:
        """Scans project and user skills directories for valid SKILL.md files."""
        self.skills.clear()
        self.command_map.clear()

        # 1. User-level skills (base)
        if self.user_skills_dir.is_dir():
            self._scan_directory(self.user_skills_dir, scope="user")

        # 2. Project-level skills (project overrides user-level)
        if self.project_skills_dir.is_dir():
            self._scan_directory(self.project_skills_dir, scope="project")

        return self.skills

    def _scan_directory(self, base_dir: Path, scope: str):
        for item in base_dir.iterdir():
            if item.is_dir():
                skill_md = item / "SKILL.md"
                if skill_md.is_file():
                    manifest = self._parse_skill_file(skill_md, scope=scope, fallback_name=item.name)
                    if manifest:
                        self.skills[manifest.name] = manifest
                        self.command_map[manifest.slash_command.lower()] = manifest
            elif item.is_file() and item.suffix.lower() == ".md" and item.stem.lower() != "readme":
                manifest = self._parse_skill_file(item, scope=scope, fallback_name=item.stem)
                if manifest:
                    self.skills[manifest.name] = manifest
                    self.command_map[manifest.slash_command.lower()] = manifest

    def _parse_skill_file(self, file_path: Path, scope: str, fallback_name: str) -> Optional[SkillManifest]:
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            return None

        match = self.FRONTMATTER_PATTERN.match(content)
        if match:
            fm_text, instructions = match.group(1), match.group(2)
            try:
                fm_data = yaml.safe_load(fm_text) or {}
            except Exception:
                fm_data = {}
        else:
            fm_data = {}
            instructions = content

        name = fm_data.get("name") or fallback_name
        description = fm_data.get("description") or f"Custom {name} skill"
        slash_cmd = fm_data.get("slash_command")
        allowed_tools = fm_data.get("allowed_tools")

        return SkillManifest(
            name=name,
            description=description,
            instructions=instructions,
            slash_command=slash_cmd,
            allowed_tools=allowed_tools,
            source_path=str(file_path),
            scope=scope,
        )

    def get_skill(self, name_or_command: str) -> Optional[SkillManifest]:
        """Lookup skill by exact name or registered slash command."""
        key = name_or_command.strip().lower()
        if key in self.command_map:
            return self.command_map[key]
        if key.startswith("/"):
            key_no_slash = key[1:]
            if key_no_slash in self.skills:
                return self.skills[key_no_slash]
        if key in self.skills:
            return self.skills[key]
        return None

    def build_skill_prompt(self, skill: SkillManifest, user_args: str = "") -> str:
        """Construct the prompt injected into the agent orchestrator."""
        prompt_parts = [
            f"[ACTIVE SKILL: {skill.name.upper()}]",
            skill.description,
            "\n--- SKILL INSTRUCTIONS ---",
            skill.instructions,
            "--- END SKILL INSTRUCTIONS ---",
        ]
        if user_args.strip():
            prompt_parts.append(f"\nUser Input/Target: {user_args.strip()}")
        else:
            prompt_parts.append("\nExecute the skill workflow on the current project context.")
        return "\n".join(prompt_parts)

    def format_skills_list(self) -> str:
        """Render a readable summary table of all discovered skills."""
        if not self.skills:
            return "No skills currently discovered. Place SKILL.md in ./skills/<name>/."

        lines = [
            "Available Skills & Slash Commands:",
            "-" * 68,
            f"{'Command':<18} {'Skill Name':<20} {'Scope':<9} {'Description'}",
            "-" * 68,
        ]
        for name, s in sorted(self.skills.items()):
            lines.append(f"{s.slash_command:<18} {s.name:<20} {s.scope:<9} {s.description}")
        lines.append("-" * 68)
        return "\n".join(lines)
