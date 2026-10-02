"""
harness/tools/registry.py — Tool Registry and Schema Definitions.
Registers all available tools, specifies OpenAI function calling schemas,
and defines which operations require human approval gates.
"""

from typing import Dict, Any, Callable, List, Optional
from harness.tools import fs, terminal, web
from harness.tools.sandbox import validate_workspace_path
from harness.security import scrubber
from harness.storage.undo import file_hash
import copy


class ToolDefinition:
    def __init__(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable[..., Any],
        requires_approval: bool = True,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.requires_approval = requires_approval

    def to_openai_tool(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(
        self,
        workspace_root: str = ".",
        skill_manager: Optional[Any] = None,
        undo_manager: Optional[Any] = None,
    ):
        self.workspace_root = workspace_root
        self.skill_manager = skill_manager
        self.undo_manager = undo_manager
        self.tools: Dict[str, ToolDefinition] = {}
        self._register_default_tools()

    def register(self, tool_def: ToolDefinition):
        self.tools[tool_def.name] = tool_def

    def _handle_write_file(self, path: str, content: str, overwrite: bool = False) -> Dict[str, Any]:
        snapshot = self.undo_manager.record_pre_change(path) if self.undo_manager else None
        res = fs.write_file(path, content, overwrite, workspace_root=self.workspace_root)
        if snapshot:
            self.undo_manager.record_post_change(snapshot, res.get("diff", ""))
        return res

    def _handle_edit_file(self, path: str, old_str: str, new_str: str) -> Dict[str, Any]:
        snapshot = self.undo_manager.record_pre_change(path) if self.undo_manager else None
        res = fs.edit_file(path, old_str, new_str, workspace_root=self.workspace_root)
        if snapshot:
            self.undo_manager.record_post_change(snapshot, res.get("diff", ""))
        return res

    def _register_default_tools(self):
        # 1. read_file
        self.register(
            ToolDefinition(
                name="read_file",
                description="Read contents of a file in the workspace. Returns line-numbered contents.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path to the file"},
                        "start_line": {"type": "integer", "description": "Optional start line number (1-indexed)"},
                        "end_line": {"type": "integer", "description": "Optional end line number (1-indexed)"},
                    },
                    "required": ["path"],
                },
                handler=lambda path, start_line=None, end_line=None: fs.read_file(
                    path, start_line, end_line, workspace_root=self.workspace_root
                ),
                requires_approval=False,
            )
        )

        # 2. list_dir
        self.register(
            ToolDefinition(
                name="list_dir",
                description="List files and directories in the workspace with optional glob pattern.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path to directory (default '.')"},
                        "pattern": {"type": "string", "description": "Glob pattern like '*.py' (default '*')"},
                    },
                },
                handler=lambda path=".", pattern="*": fs.list_dir(
                    path, pattern, workspace_root=self.workspace_root
                ),
                requires_approval=False,
            )
        )

        # 3. grep_search
        self.register(
            ToolDefinition(
                name="grep_search",
                description="Search for a regex or string pattern across text files in the workspace.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "String or regex pattern to search for"},
                        "path": {"type": "string", "description": "Subdirectory to search in (default '.')"},
                    },
                    "required": ["query"],
                },
                handler=lambda query, path=".": fs.grep_search(
                    query, path, workspace_root=self.workspace_root
                ),
                requires_approval=False,
            )
        )

        # 4. write_file (Requires Approval)
        self.register(
            ToolDefinition(
                name="write_file",
                description="Create a new file or completely overwrite an existing file with new content.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path of the file to create/overwrite"},
                        "content": {"type": "string", "description": "Complete text content to write"},
                        "overwrite": {"type": "boolean", "description": "Must be true if file already exists"},
                    },
                    "required": ["path", "content"],
                },
                handler=self._handle_write_file,
                requires_approval=True,
            )
        )

        # 5. edit_file (Requires Approval)
        self.register(
            ToolDefinition(
                name="edit_file",
                description="Surgically search and replace an exact block of code in an existing file. Returns a unified diff.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path of the file to edit"},
                        "old_str": {"type": "string", "description": "Exact existing code snippet to be replaced"},
                        "new_str": {"type": "string", "description": "New replacement code snippet"},
                    },
                    "required": ["path", "old_str", "new_str"],
                },
                handler=self._handle_edit_file,
                requires_approval=True,
            )
        )

        # 6. run_command (Requires Approval)
        self.register(
            ToolDefinition(
                name="run_command",
                description="Execute a terminal command (e.g. tests, lint, git) in the workspace.",
                parameters={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The command line string to run"},
                        "cwd": {"type": "string", "description": "Subdirectory to run in (default '.')"},
                        "timeout_seconds": {"type": "integer", "description": "Timeout in seconds (default 60)"},
                    },
                    "required": ["command"],
                },
                handler=lambda command, cwd=".", timeout_seconds=60: terminal.run_command(
                    command, cwd, timeout_seconds, workspace_root=self.workspace_root
                ),
                requires_approval=True,
            )
        )

        # 7. search_web
        self.register(
            ToolDefinition(
                name="search_web",
                description="Search the web using DuckDuckGo to find real-time documentation, algorithms, or API references.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The search query string"},
                        "max_results": {"type": "integer", "description": "Number of results to return (default 5)"},
                    },
                    "required": ["query"],
                },
                handler=lambda query, max_results=5: web.search_web(query, max_results),
                requires_approval=False,
            )
        )

        # 8. fetch_url
        self.register(
            ToolDefinition(
                name="fetch_url",
                description="Fetch and extract readable text content from a web page URL.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Web page URL to fetch"},
                        "max_chars": {"type": "integer", "description": "Maximum text characters to return (default 4000)"},
                    },
                    "required": ["url"],
                },
                handler=lambda url, max_chars=4000: web.fetch_url(url, max_chars),
                requires_approval=False,
            )
        )

        # 9. list_skills
        self.register(
            ToolDefinition(
                name="list_skills",
                description="List all available specialized domain skills installed in the workspace.",
                parameters={"type": "object", "properties": {}},
                handler=lambda: self.skill_manager.list_skills() if self.skill_manager else [],
                requires_approval=False,
            )
        )

        # 10. read_skill
        self.register(
            ToolDefinition(
                name="read_skill",
                description="Load the complete instructions, rules, and best practices for a specialized domain skill.",
                parameters={
                    "type": "object",
                    "properties": {
                        "skill_name": {"type": "string", "description": "The exact name of the skill to load (e.g. 'neetcode-solver')"},
                    },
                    "required": ["skill_name"],
                },
                handler=lambda skill_name: self.skill_manager.read_skill(skill_name) if self.skill_manager else {"error": "No SkillManager configured"},
                requires_approval=False,
            )
        )

    def get_openai_schemas(self) -> List[Dict[str, Any]]:
        """Return all registered tools as OpenAI function schemas."""
        return [tool.to_openai_tool() for tool in self.tools.values()]

    def is_approval_required(self, tool_name: str) -> bool:
        tool = self.tools.get(tool_name)
        return tool_name in {"write_file", "edit_file", "run_command"} or tool.requires_approval if tool else True

    def execute(self, tool_name, arguments, *, approval_callback=None, cancellation_token=None):
        """The authoritative gate, shared by interactive and headless callers."""
        tool = self.tools.get(tool_name)
        if not tool:
            return {"error": "Unknown tool"}
        try:
            if not isinstance(arguments, dict):
                raise ValueError("Arguments must be an object")
            arguments = copy.deepcopy(arguments)
            properties = tool.parameters.get("properties", {})
            if set(arguments) - set(properties):
                raise ValueError("Unknown tool argument")
            if any(k not in arguments for k in tool.parameters.get("required", [])):
                raise ValueError("missing required argument")
            types = {"string": str, "integer": int, "boolean": bool, "object": dict, "array": list}
            for name, value in arguments.items():
                expected = types.get(properties[name].get("type"))
                if expected and (not isinstance(value, expected) or expected is int and isinstance(value, bool)):
                    raise ValueError("Invalid argument type")
            target = None
            before = None
            if tool_name in {"write_file", "edit_file"}:
                target = validate_workspace_path(arguments["path"], self.workspace_root, True)
                before = file_hash(target)
            if cancellation_token and cancellation_token.is_cancelled:
                return {"status": "rejected", "message": "Cancellation requested"}
            if self.is_approval_required(tool_name):
                if approval_callback is None or approval_callback(tool_name, scrubber.structured(arguments)) is not True:
                    return {"status": "rejected", "message": "Explicit approval required"}
            if cancellation_token and cancellation_token.is_cancelled:
                return {"status": "rejected", "message": "Cancellation requested"}
            if target:
                validate_workspace_path(arguments["path"], self.workspace_root, True)
                if file_hash(target) != before:
                    raise ValueError("File changed during approval")
            return scrubber.structured(tool.handler(**arguments))
        except Exception as exc:
            return {"error": scrubber.scrub(f"Tool execution failed: {type(exc).__name__}: {exc}")}


class ToolBroker:
    """Capability view over the existing registry; children can only narrow it."""
    def __init__(self, registry, allowed_tools=None):
        self._registry = registry
        self.allowed_tools = frozenset(registry.tools if allowed_tools is None else allowed_tools)
        if not self.allowed_tools <= registry.tools.keys():
            raise ValueError("Unknown capability")

    def child(self, allowed_tools):
        if not set(allowed_tools) <= self.allowed_tools:
            raise ValueError("Child permissions cannot widen")
        return ToolBroker(self._registry, allowed_tools)

    def execute(self, name, arguments, **authority):
        if name not in self.allowed_tools:
            return {"status": "rejected", "message": "Tool outside permitted capabilities"}
        return self._registry.execute(name, arguments, **authority)
