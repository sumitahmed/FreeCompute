"""A normal terminal prompt with a live command menu; no full-screen UI."""
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.filters import has_completions
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style

from harness.cli.commands import CommandRegistry
from harness.cli.formatter import terminal_text


class CommandCompleter(Completer):
    def __init__(self, registry, client):
        self.registry, self.client = registry, client

    def candidates(self, text):
        if not text.startswith("/") or "\n" in text:
            return []
        parts = text.split(" ")
        if len(parts) == 1:
            return [(c.name, c.description) for c in self.registry.entries() if c.name.startswith(text.lower())]
        command, word = self.registry.canonical(parts[0].lower()), parts[-1]
        # Cached declarations only: a keypress never makes a remote request.
        if command in {"/model", "/image-model"}:
            profiles = self.client.models()
            capability = "image_gen" if command == "/image-model" else "text"
            if len(parts) > 2:
                profile = next((p for p in profiles if p["profile_id"] == parts[1]), None)
                values = [(w, "Worker for " + parts[1]) for w in profile["workers"]] if profile else []
            else:
                values = [(p["profile_id"], f"{p['model']} | {', '.join(p['capabilities'])} | context {p['context_capacity']:,} declared")
                          for p in profiles if capability in p["capabilities"]]
        elif command == "/resume":
            values = [(s["id"], s["status"] + " | " + s["updated_at"]) for s in self.client.list_sessions()]
        elif command == "/skill":
            values = [(s.name, s.slash_command + " | " + s.description) for s in self.registry.skills.skills.values()]
        else:
            values = []
        return [(value, description) for value, description in values if value.lower().startswith(word.lower())]

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        start = -len(text.split(" ")[-1])
        for value, description in self.candidates(text):
            yield Completion(terminal_text(value), start_position=start, display_meta=terminal_text(description))


def bindings():
    keys = KeyBindings()

    @keys.add("enter")
    def enter(event):
        buffer = event.current_buffer
        if buffer.complete_state and buffer.complete_state.current_completion:
            buffer.apply_completion(buffer.complete_state.current_completion)
        else:
            buffer.validate_and_handle()

    @keys.add("escape", "enter")
    def newline(event):
        event.current_buffer.insert_text("\n")

    @keys.add("escape", filter=has_completions)
    def dismiss(event):
        event.current_buffer.cancel_completion()

    return keys


class TerminalInput:
    def __init__(self, registry, client, *, interactive=None):
        self.interactive = (sys.stdin.isatty() and sys.stdout.isatty()) if interactive is None else interactive
        self.session = None
        if self.interactive:
            self.session = PromptSession(history=InMemoryHistory(), completer=CommandCompleter(registry, client),
                                         complete_while_typing=True, reserve_space_for_menu=8,
                                         key_bindings=bindings(), multiline=True,
                                         style=Style.from_dict({"prompt": "bold ansicyan"}))
            self.session.app.ttimeoutlen = .05
            self.session.app.timeoutlen = .15

    def read(self):
        if not self.session:
            return input("freecompute> ")
        return self.session.prompt([("class:prompt", "freecompute> ")])

    def choose(self, command, rows):
        if not self.session or not rows:
            return None
        # Reuses the contextual completer and arrow keys without another UI.
        def show():
            self.session.default_buffer.start_completion(select_first=False)
        answer = self.session.prompt([("class:prompt", "Choose> ")], default=command + " ", pre_run=show)
        return answer[len(command):].strip() if answer.startswith(command + " ") else None
