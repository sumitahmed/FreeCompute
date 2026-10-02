"""
harness/skills/manager.py — Skill discovery, SKILL.md manifest parser, and slash-command dispatcher.
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import yaml
from harness.security import scrubber
from harness.tools.sandbox import validate_workspace_path


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
        required_capabilities: Optional[List[str]] = None,
    ):
        self.name = name.strip()
        self.description = description.strip()
        self.instructions = instructions.strip()
        self.slash_command = slash_command.strip() if slash_command else f"/{self.name}"
        if not self.slash_command.startswith("/"):
            self.slash_command = f"/{self.slash_command}"
        self.allowed_tools = list(allowed_tools) if allowed_tools is not None else None
        self.required_capabilities = list(required_capabilities or [])
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
            "required_capabilities": self.required_capabilities,
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
        self.diagnostics: List[str] = []
        self.discover_skills()

    def discover_skills(self) -> Dict[str, SkillManifest]:
        """Scans project and user skills directories for valid SKILL.md files."""
        self.skills.clear()
        self.command_map.clear()
        self.diagnostics.clear()

        # 1. User-level skills (base)
        if self.user_skills_dir.is_dir():
            self._scan_directory(self.user_skills_dir, scope="user")

        # 2. Project-level skills (project overrides user-level)
        if self.project_skills_dir.is_dir():
            self._scan_directory(self.project_skills_dir, scope="project")

        # Rebuild aliases after overrides; a replaced user command must not survive.
        for manifest in self.skills.values():
            key = manifest.slash_command.lower()
            if key in self.command_map and self.command_map[key].name != manifest.name:
                self.diagnostics.append(f"Duplicate skill command {key}; resolve the manifest conflict")
                self.command_map.pop(key)
            else:
                self.command_map[key] = manifest

        return self.skills

    def _scan_directory(self, base_dir: Path, scope: str):
        root = self.workspace_root if scope == "project" else self.user_skills_dir
        try:
            validate_workspace_path(base_dir, str(root))
            items = sorted(base_dir.iterdir())
        except Exception as exc:
            self.diagnostics.append(scrubber.scrub(exc))
            return
        for item in items:
            try:
                validate_workspace_path(item, str(root))
            except Exception as exc:
                self.diagnostics.append(scrubber.scrub(exc))
                continue
            if item.is_dir():
                skill_md = item / "SKILL.md"
                if skill_md.is_file():
                    manifest = self._parse_skill_file(skill_md, scope=scope, fallback_name=item.name)
                    if manifest:
                        self.skills[manifest.name.lower()] = manifest
            elif item.is_file() and item.suffix.lower() == ".md" and item.stem.lower() != "readme":
                manifest = self._parse_skill_file(item, scope=scope, fallback_name=item.stem)
                if manifest:
                    self.skills[manifest.name.lower()] = manifest

    def _parse_skill_file(self, file_path: Path, scope: str, fallback_name: str) -> Optional[SkillManifest]:
        try:
            root = self.workspace_root if scope == "project" else self.user_skills_dir
            validate_workspace_path(file_path, str(root))
            content = file_path.read_text(encoding="utf-8")
        except Exception as exc:
            self.diagnostics.append(scrubber.scrub(exc))
            return None

        match = self.FRONTMATTER_PATTERN.match(content)
        if match:
            fm_text, instructions = match.group(1), match.group(2)
            try:
                fm_data = yaml.safe_load(fm_text) or {}
            except Exception:
                self.diagnostics.append(f"Invalid YAML skill manifest: {file_path.name}")
                return None
        else:
            fm_data = {}
            instructions = content

        if not isinstance(fm_data, dict):
            self.diagnostics.append(f"Skill frontmatter must be a mapping: {file_path.name}")
            return None
        name = fm_data.get("name") or fallback_name
        description = fm_data.get("description") or f"Custom {name} skill"
        slash_cmd = fm_data.get("slash_command")
        allowed_tools = fm_data.get("allowed_tools")
        required = fm_data.get("required_capabilities", [])
        if (not isinstance(name, str) or not name.strip() or not isinstance(description, str)
            or slash_cmd is not None and (not isinstance(slash_cmd, str) or len(slash_cmd.split()) != 1)
            or allowed_tools is not None and (not isinstance(allowed_tools, list) or any(not isinstance(t, str) for t in allowed_tools))
            or not isinstance(required, list) or any(not isinstance(c, str) for c in required)):
            self.diagnostics.append(f"Invalid skill names, allowed_tools or required_capabilities: {file_path.name}")
            return None

        return SkillManifest(
            name=name,
            description=description,
            instructions=instructions,
            slash_command=slash_cmd,
            allowed_tools=allowed_tools,
            source_path=str(file_path),
            scope=scope,
            required_capabilities=required,
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
            re.sub(r"\binspect_file\b", "read_file", skill.instructions),
            "--- END SKILL INSTRUCTIONS ---",
        ]
        if user_args.strip():
            prompt_parts.append(f"\nUser Input/Target: {user_args.strip()}")
        else:
            prompt_parts.append("\nExecute the skill workflow on the current project context.")
        return scrubber.scrub("\n".join(prompt_parts))

    def restrictions(self, skill, available_tools, capabilities):
        missing = set(skill.required_capabilities) - set(capabilities)
        if missing:
            raise ValueError(f"Skill {skill.name} requires unavailable capabilities: {', '.join(sorted(missing))}; select a compatible profile")
        allowed = set(available_tools) if skill.allowed_tools is None else {"read_file" if t == "inspect_file" else t for t in skill.allowed_tools}
        unknown = allowed - set(available_tools)
        if unknown:
            raise ValueError(f"Skill {skill.name} requires unavailable tools: {', '.join(sorted(unknown))}; correct the manifest or install a compatible tool")
        return frozenset(allowed)

    def list_skills(self):
        return scrubber.structured([s.to_dict() for s in self.skills.values()])

    def read_skill(self, skill_name):
        skill = self.get_skill(skill_name)
        if not skill:
            return {"error": "Unknown skill; use list_skills to inspect available names"}
        return scrubber.structured(dict(skill.to_dict(), instructions=re.sub(r"\binspect_file\b", "read_file", skill.instructions)))

    def get_project_instructions(self):
        path = self.workspace_root / "AGENTS.md"
        try:
            path = validate_workspace_path(path, str(self.workspace_root))
            return scrubber.scrub(path.read_text(encoding="utf-8")) if path.is_file() else ""
        except Exception as exc:
            self.diagnostics.append(scrubber.scrub(exc))
            return ""

    def get_skills_prompt_summary(self):
        if not self.skills:
            return ""
        return scrubber.scrub("[Available Specialized Skills]\n" + "\n".join(
            f"{s.name} ({s.slash_command}): {s.description}" for s in self.skills.values()))

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
        if self.diagnostics:
            lines.extend(self.diagnostics)
        return scrubber.scrub("\n".join(lines))
