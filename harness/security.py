"""Shared output boundary. Pattern scanning supplements registered secrets; it is not DLP."""
import builtins
import re
from typing import Any


class SecretScrubber:
    DEFAULT_PATTERNS = [
        (re.compile(r"(Bearer\s+)[A-Za-z0-9_\-.]{8,}", re.I), r"\1[REDACTED_TOKEN]"),
        (re.compile(r"tskey-auth-[A-Za-z0-9_\-]+", re.I), "[REDACTED_TAILSCALE_KEY]"),
        (re.compile(r"sk-[A-Za-z0-9_\-]{8,}", re.I), "[REDACTED_SECRET_KEY]"),
        (re.compile(r"https?://[a-zA-Z0-9\-]+\.trycloudflare\.com", re.I), "https://[tunnel].trycloudflare.com"),
    ]

    def __init__(self):
        self._exact_secrets = set()

    def register_secret(self, secret):
        if isinstance(secret, str) and secret.strip():
            self._exact_secrets.add(secret.strip())

    def scrub(self, value: Any) -> str:
        text = "" if value is None else str(value)
        for secret in sorted(self._exact_secrets, key=len, reverse=True):
            text = text.replace(secret, "[REDACTED_SECRET]")
        for pattern, replacement in self.DEFAULT_PATTERNS:
            text = pattern.sub(replacement, text)
        return text

    def structured(self, value):
        if isinstance(value, dict):
            return {self.scrub(k): self.structured(v) for k, v in value.items()}
        if isinstance(value, (tuple, list)):
            return [self.structured(v) for v in value]
        return self.scrub(value) if isinstance(value, str) else value


scrubber = SecretScrubber()


class StreamRedactor:
    """Hold an unfinished word and registered-secret prefixes across chunk boundaries.

    Unregistered patterns with embedded whitespace are best-effort. A stream with no
    whitespace is buffered until completion, avoiding partial credential disclosure.
    """
    def __init__(self, source=None):
        self.source = source or scrubber
        self.pending = ""

    def feed(self, text):
        self.pending += text
        cuts = list(re.finditer(r"\s+", self.pending))
        cut = cuts[-1].end() if cuts else 0
        # Never release a prefix of a registered secret (including secrets with spaces).
        for secret in self.source._exact_secrets:
            for start in range(max(0, cut - len(secret)), cut):
                suffix = self.pending[start:]
                if secret.startswith(suffix) or self.pending.startswith(secret, start) and start + len(secret) > cut:
                    cut = min(cut, start)
        # A bearer prefix must stay with the token that follows it.
        bearer = re.search(r"Bearer\s+\S*$", self.pending, re.I)
        if bearer:
            cut = min(cut, bearer.start())
        output, self.pending = self.pending[:cut], self.pending[cut:]
        return self.source.scrub(output)

    def finish(self):
        output, self.pending = self.source.scrub(self.pending), ""
        return output


def safe_print(*values, **kwargs):
    builtins.print(*(scrubber.scrub(v) for v in values), **kwargs)
