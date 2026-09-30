"""
harness/config.py — Configuration loader and validator for local harness.
"""

import os
from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, Field


class HarnessConfig(BaseModel):
    remote_url: str = Field(default="http://127.0.0.1:8081", description="URL of the remote Kaggle supervisor")
    api_key: str = Field(default="", description="Bearer token for Kaggle supervisor")
    model_alias: str = Field(default="qwen3.8-27b-huihui-abliterated-q4", description="Model alias registered in llama-server")
    max_context_tokens: int = Field(default=65536, description="Maximum context window capacity")
    request_timeout_seconds: int = Field(default=900, description="HTTP timeout for model requests")
    transport: str = Field(default="tailscale", description="Network transport mode: tailscale or cloudflare")
    workspace_root: str = Field(default=".", description="Authoritative local project directory")
    journal_dir: str = Field(default=".qwen_harness", description="Directory to store journal and checkpoints")
    poll_health_interval_seconds: int = Field(default=5, description="Frequency of health/telemetry polling")
    image_server_url: str = Field(default="", description="Remote ComfyUI image server URL")

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "HarnessConfig":
        """Load configuration from YAML file or environment variables."""
        data = {}
        if config_path and Path(config_path).is_file():
            with open(config_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    data.update(loaded)
        elif Path("config.yaml").is_file():
            with open("config.yaml", "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    data.update(loaded)

        for k in ("FREECOMPUTE_REMOTE_URL", "RELAYFORGE_REMOTE_URL", "HARNESS_REMOTE_URL"):
            if k in os.environ:
                data["remote_url"] = os.environ[k]
                break
        for k in ("FREECOMPUTE_API_KEY", "RELAYFORGE_API_KEY", "HARNESS_API_KEY"):
            if k in os.environ:
                data["api_key"] = os.environ[k]
                break
        for k in ("FREECOMPUTE_IMAGE_SERVER", "RELAYFORGE_IMAGE_SERVER", "HARNESS_IMAGE_SERVER"):
            if k in os.environ:
                data["image_server_url"] = os.environ[k]
                break
        for k in ("FREECOMPUTE_MODEL_ALIAS", "RELAYFORGE_MODEL_ALIAS", "HARNESS_MODEL_ALIAS"):
            if k in os.environ:
                data["model_alias"] = os.environ[k]
                break
        for k in ("FREECOMPUTE_TRANSPORT", "RELAYFORGE_TRANSPORT", "HARNESS_TRANSPORT"):
            if k in os.environ:
                data["transport"] = os.environ[k]
                break
        for k in ("FREECOMPUTE_WORKSPACE", "RELAYFORGE_WORKSPACE", "HARNESS_WORKSPACE"):
            if k in os.environ:
                data["workspace_root"] = os.environ[k]
                break
        if False:
            data["remote_url"] = os.environ["HARNESS_REMOTE_URL"]
        if "HARNESS_API_KEY" in os.environ:
            data["api_key"] = os.environ["HARNESS_API_KEY"]
        if "HARNESS_MODEL_ALIAS" in os.environ:
            data["model_alias"] = os.environ["HARNESS_MODEL_ALIAS"]
        if "HARNESS_TRANSPORT" in os.environ:
            data["transport"] = os.environ["HARNESS_TRANSPORT"]

        return cls(**data)
