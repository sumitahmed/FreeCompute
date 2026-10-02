"""
harness/config.py — Configuration loader and validator for local harness.
"""

import os
from pathlib import Path
from typing import Optional, Literal
import yaml
from pydantic import BaseModel, Field, ConfigDict, field_validator
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
    timeout_seconds: int = Field(default=900, gt=0, strict=True)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value):
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
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
            if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
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
        """Defaults < YAML < .env < process env; canonical names beat legacy aliases."""
        data = {}
        path = Path(config_path or "config.yaml")
        if config_path or path.exists():
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(loaded, dict):
                raise ValueError("Configuration YAML must be a mapping")
            data.update(loaded)
        environment = {}
        dotenv = Path(".env")
        if dotenv.is_file():
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
                environment[key.strip()] = value
        names = {"remote_url": "REMOTE_URL", "api_key": "API_KEY", "image_server_url": "IMAGE_SERVER",
                 "model_alias": "MODEL_ALIAS", "transport": "TRANSPORT", "workspace_root": "WORKSPACE",
                 "request_timeout_seconds": "TIMEOUT", "max_context_tokens": "MAX_CONTEXT_TOKENS",
                 "journal_dir": "JOURNAL_DIR", "poll_health_interval_seconds": "POLL_HEALTH_INTERVAL_SECONDS"}
        names.update(engine="ENGINE", selected_profile="PROFILE", selected_worker="WORKER")
        # Resolve each layer separately: even a legacy process variable beats .env.
        for layer in (environment, os.environ):
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
        return cls(**data)
