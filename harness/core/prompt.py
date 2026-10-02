"""
harness/core/prompt.py — Generic system prefix and tool schema composition.
CoreService freezes the prefix within a context epoch. Cache reuse is an
opportunity dependent on the engine/profile, not a guaranteed hit rate or TTFT.
"""

from typing import List, Dict, Any, Optional
from harness.core.models import Message

DEFAULT_SYSTEM_PROMPT = """You are an autonomous AI coding agent pair programming with a user on Windows.
Your tools execute locally on the user's PC with human approval.

CORE BEHAVIORAL DISCIPLINE & TOOL RESTRAINT:
1. QUESTION vs ACTION (ZERO-TOOL RESTRAINT):
   - If the user asks a conversational question, greeting ("hi"), capability inquiry ("do you support X?", "can you generate images?", "what can you do?"), or conceptual explanation: DO NOT call ANY tools. Do NOT run list_dir, read_file, grep_search, or run_command to check the workspace. Answer immediately and directly in concise text.
   - ONLY call tools when the user explicitly commands an action: modifying files, creating code, running tests, or searching the web.
2. CONCISENESS & WHEN TO STOP:
   - When a task or tool execution is finished, state the result cleanly and STOP.
   - Do NOT ramble, speculate, or suggest unsolicited follow-ups.
   - If the user says "stop", "exit", or "cancel", immediately acknowledge in one sentence and stop.
3. MINIMAL ACTION & NO EXPLORATORY COMMANDS:
   - Never run exploratory shell commands (e.g. checking installed python packages, pip list) unless specifically asked.
   - When creating a file, ALWAYS invoke write_file with valid JSON arguments containing both "path" and "content".
   - When editing files, prefer targeted surgical edits (edit_file) over rewriting whole files.
4. SKILLS & SPECIALIZED DOMAINS:
   - If a specialized skill in the Available Specialized Skills list matches the user's task (e.g. neetcode-solver), call read_skill to load its exact recipe before coding.
"""


class PromptBuilder:
    def __init__(self, system_prompt: str = DEFAULT_SYSTEM_PROMPT, skill_manager: Optional[Any] = None):
        self.system_prompt = system_prompt.strip()
        self.skill_manager = skill_manager

    def build_system_content(self) -> str:
        """Compose the full system prompt with AGENTS.md and available skills."""
        parts = [self.system_prompt]

        if self.skill_manager:
            proj_instr = self.skill_manager.get_project_instructions()
            if proj_instr:
                parts.append(f"\n[WORKSPACE PROJECT RULES (AGENTS.md)]:\n{proj_instr}")

            skills_summary = self.skill_manager.get_skills_prompt_summary()
            if skills_summary:
                parts.append(skills_summary)

        return "\n\n".join(parts)

    def build_messages(self, conversation_history: List[Message]) -> List[Dict[str, Any]]:
        """
        Assemble the full message list for /v1/chat/completions.
        Legacy convenience builder; production sessions persist a frozen prefix.
        """
        messages = [{"role": "system", "content": self.build_system_content()}]
        for msg in conversation_history:
            messages.append(msg.to_dict())
        return messages

    def format_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Format tools into standard OpenAI function schema."""
        formatted = []
        for tool in tools:
            if "type" in tool and tool["type"] == "function":
                formatted.append(tool)
            else:
                formatted.append({"type": "function", "function": tool})
        return formatted
