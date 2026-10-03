"""One command catalogue for help, completion and dispatch aliases."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    name: str
    description: str
    arguments: str = ""
    group: str = "Workspace"
    aliases: tuple = ()


COMMANDS = (
    Command("/help", "Show commands", "[recovery]"),
    Command("/status", "Refresh hardware and session observations", group="Workers", aliases=("/health",)),
    Command("/connect", "Reconnect text worker; retain key, temporary URL", "<URL>", "Workers"),
    Command("/model", "Choose a configured text/code route", "[profile] [worker]", "Workers"),
    Command("/models", "List configured model profiles", group="Workers"),
    Command("/workers", "Refresh worker health, hardware and held slots", group="Workers"),
    Command("/connect-image", "Reconnect image worker independently", "<URL>", "Images", ("/image-server",)),
    Command("/image-model", "Choose a configured image route", "[profile] [worker]", "Images"),
    Command("/image", "Generate with the selected image workflow", "<prompt>", "Images"),
    Command("/skills", "List bundled, user and project skills", group="Skills"),
    Command("/skill", "Choose or run a skill", "[name] [request]", "Skills"),
    Command("/queue", "Inspect durable requests and held capacity"),
    Command("/sessions", "List saved sessions"),
    Command("/resume", "Resume a saved session", "<id>"),
    Command("/new", "Start a new conversation on the next prompt"),
    Command("/diff", "Show the latest recorded file change"),
    Command("/undo", "Preview and approve a sealed snapshot restore"),
    Command("/cancel", "Cancel queued work; Ctrl+C cancels active work", "[task-id]"),
    Command("/clear", "Clear the terminal"),
    Command("/exit", "Save local state and exit", aliases=("/quit",)),
    Command("/run-next", "Dispatch oldest eligible queued task", group="Recovery"),
    Command("/actions", "Inspect local actions and file hashes", group="Recovery"),
    Command("/reconcile", "Resolve an uncertain local effect after approval", "<action> <completed|not_executed> [sha256|absent]", "Recovery"),
    Command("/reconcile-inference", "Reconcile held lease after independent idle observation", "[lease]", "Recovery"),
    Command("/quota", "View/set a user-observed quota balance", "[hours]", "Recovery"),
)


class CommandRegistry:
    def __init__(self, skills=None):
        self.skills = skills

    def entries(self):
        entries = list(COMMANDS)
        reserved = {name for c in entries for name in (c.name, *c.aliases)}
        if self.skills:
            for name, skill in sorted(self.skills.command_map.items()):
                if name not in reserved:
                    entries.append(Command(name, skill.name + ": " + skill.description, "[request]", "Skills"))
        return entries

    def canonical(self, name):
        for command in COMMANDS:
            if name in command.aliases:
                return command.name
        return name

    def help_lines(self, recovery=False):
        entries = self.entries()
        for group in ('Workspace', 'Workers', 'Images', 'Skills', 'Recovery'):
            if (group == 'Recovery') != recovery:
                continue
            yield group
            for command in entries:
                if command.group == group:
                    yield f"  {command.name} {command.arguments}".rstrip()
                    yield "    " + command.description
