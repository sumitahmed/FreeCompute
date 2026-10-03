"""
harness/config.py — Configuration loader and validator for local harness.
"""

import os
from pathlib import Path
from typing import Optional, Literal
import yaml
from pydantic import BaseModel, Field, PrivateAttr, ConfigDict, field_validator
from harness.security import scrubber
from urllib.parse import urlsplit


class ModelDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    profile_id: str
    model: str
    engine: str
    capabilities: set[str]
    context_capacity: int = Field(default=65536, gt=0, strict=True)
    reserved_completion: int = Field(default=2048, gt=0, strict=True)
    max_tool_result_bytes: int = Field(default=16000, ge=256, strict=True)
    engine_requirements: set[str] = Field(default_factory=set)
    resource_requirements: set[str] = Field(default_factory=set)
    tokenizer: Optional[str] = None
    template: Optional[str] = None
    verification: str = "declared"


class WorkerConnection(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    worker_id: str
    location: Literal["local", "kaggle", "private", "homelab", "remote-supervisor"]
    engine: Literal["llama.cpp", "openai-compatible", "ComfyUI"]
    url: str
    api_key: str = Field(default="", repr=False)
    api_key_env: str = ""
    profiles: list[str]
    concurrency_limit: int = Field(default=1, ge=1, le=64, strict=True)
    resource_pool: str = ""
    resources: set[str] = Field(default_factory=set)
    timeout_seconds: Optional[int] = Field(default=None, gt=0, strict=True)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value):
        url = urlsplit(value)
        try:
            port = url.port
        except ValueError:
            raise ValueError("Worker endpoint has an invalid port") from None
        if any(c.isspace() or ord(c) < 32 for c in value) or url.scheme not in {"http", "https"} or not url.hostname or port == 0 or url.username or url.password or url.query or url.fragment:
            raise ValueError("Worker endpoint must be HTTP(S) without URL credentials, queries or fragments")
        return value

    @field_validator("api_key_env")
    @classmethod
    def validate_key_env(cls, value):
        import re
        if value and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("Expected an environment variable name")
        return value


class HarnessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, hide_input_in_errors=True)
    _dotenv_values: dict[str, str] = PrivateAttr(default_factory=dict)
    remote_url: str = Field(default="http://127.0.0.1:8081", description="URL of the remote Kaggle supervisor")
    api_key: str = Field(default="", repr=False, description="Bearer token for Kaggle supervisor")
    model_alias: str = Field(default="qwen3.8-27b-huihui-abliterated-q4", description="Model alias registered in llama-server")
    max_context_tokens: int = Field(default=65536, gt=0, description="Maximum context window capacity")
    request_timeout_seconds: int = Field(default=900, gt=0, description="HTTP timeout for model requests")
    transport: str = Field(default="tailscale", description="Network transport mode: tailscale or cloudflare")
    workspace_root: str = Field(default=".", description="Authoritative local project directory")
    journal_dir: str = Field(default=".qwen_harness", description="Directory to store journal and checkpoints")
    poll_health_interval_seconds: int = Field(default=5, gt=0, description="Frequency of health/telemetry polling")
    image_server_url: str = Field(default="", description="Remote ComfyUI image server URL")
    engine: Literal["llama.cpp", "openai-compatible"] = "llama.cpp"
    model_profiles: list[ModelDeclaration] = Field(default_factory=list)
    workers: list[WorkerConnection] = Field(default_factory=list)
    selected_profile: str = ""
    selected_worker: str = ""

    @field_validator("remote_url", "image_server_url")
    @classmethod
    def validate_url(cls, value):
        if value:
            url = urlsplit(value)
            try:
                port = url.port
            except ValueError:
                raise ValueError("Endpoint has an invalid port") from None
            if url.scheme not in {"http", "https"} or not url.hostname or port == 0 or url.username or url.password or url.query or url.fragment:
                raise ValueError("Expected HTTP(S) URL without embedded credentials")
        return value

    @field_validator("transport")
    @classmethod
    def validate_transport(cls, value):
        if value not in {"tailscale", "cloudflare"}:
            raise ValueError("Unsupported transport")
        return value

    @classmethod
    def load(cls, config_path=None):
        """Defaults < YAML < config-side .env < cwd .env < process env."""
        data = {}
        path = Path(config_path or "config.yaml")
        if config_path or path.exists():
            try:
                loaded = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
            except yaml.YAMLError as exc:
                mark = getattr(exc, "problem_mark", None)
                location = f" at line {mark.line + 1}" if mark else ""
                raise ValueError("Invalid YAML configuration" + location + "; check its syntax") from None
            if not isinstance(loaded, dict):
                raise ValueError("Configuration YAML must be a mapping")
            data.update(loaded)
        environment, dotenv_layers = {}, []
        dotenv_paths = [path.resolve().parent / ".env", Path(".env").resolve()]
        for dotenv in dict.fromkeys(dotenv_paths):
            if not dotenv.is_file():
                continue
            values = {}
            # Literal KEY=value syntax only: no interpolation or command execution.
            for raw in dotenv.read_text(encoding="utf-8-sig").splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                key, separator, value = line.removeprefix("export ").partition("=")
                if not separator:
                    raise ValueError("Malformed .env assignment")
                value = value.strip()
                if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
                    value = value[1:-1]
                values[key.strip()] = value
            environment.update(values)
            dotenv_layers.append(values)
        names = {"remote_url": "REMOTE_URL", "api_key": "API_KEY", "image_server_url": "IMAGE_SERVER",
                 "model_alias": "MODEL_ALIAS", "transport": "TRANSPORT", "workspace_root": "WORKSPACE",
                 "request_timeout_seconds": "TIMEOUT", "max_context_tokens": "MAX_CONTEXT_TOKENS",
                 "journal_dir": "JOURNAL_DIR", "poll_health_interval_seconds": "POLL_HEALTH_INTERVAL_SECONDS"}
        names.update(engine="ENGINE", selected_profile="PROFILE", selected_worker="WORKER")
        # Resolve each layer separately: even a legacy process variable beats .env.
        for layer in (*dotenv_layers, os.environ):
            for field, suffix in names.items():
                for prefix in ("FREECOMPUTE", "RELAYFORGE", "HARNESS"):
                    key = prefix + "_" + suffix
                    if key in layer:
                        data[field] = layer[key]
                        break
        for layer in (data, environment, os.environ):
            for key, value in layer.items():
                if "API_KEY" in key or key == "api_key":
                    scrubber.register_secret(value)
        config = cls(**data)
        config._dotenv_values = environment
        return config

    def resolve_api_key(self, name):
        """Resolve worker credentials without mutating the process environment."""
        return os.environ.get(name, self._dotenv_values.get(name, ""))

    def override_remote_url(self, value):
        """Change only the selected text worker's endpoint for this process."""
        WorkerConnection.validate_url(value)
        if not self.workers:
            self.remote_url = value
            return
        selected = self.selected_profile or next(
            (p.profile_id for p in self.model_profiles if "text" in p.capabilities), "")
        candidates = [w for w in self.workers if selected in w.profiles and
                      (not self.selected_worker or w.worker_id == self.selected_worker)]
        if not candidates or candidates[0].engine == "ComfyUI":
            raise ValueError("--remote-url requires a selected text worker; use --profile and --worker")
        target = candidates[0]
        self.workers = [w.model_copy(update={"url": value}) if w.worker_id == target.worker_id else w
                        for w in self.workers]
        self.selected_worker = target.worker_id
