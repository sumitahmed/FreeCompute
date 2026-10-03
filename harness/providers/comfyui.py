"""
harness/providers/comfyui.py — Provider implementation for ComfyUI image generation backend.
"""

import json
import os
import random
import time
import urllib.parse
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from harness.core.models import GpuTelemetry, Message, RemoteHealth, StreamChunk
from harness.providers.base import BaseProvider, Capability
from harness.security import scrubber
from harness.tools.sandbox import validate_workspace_path


class ComfyUIProvider(BaseProvider):
    """
    Provider for ComfyUI backends (e.g. Qwen-Image-2.1 / SD / FLUX).
    Supported capabilities: IMAGE_GEN.
    """

    def __init__(self, server_url: str = "", output_dir: str = "output", workspace_root: str = ".", api_key: str = ""):
        super().__init__(name="ComfyUI (Qwen-Image-2.1)")
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        scrubber.register_secret(api_key)
        scrubber.register_secret(self.server_url)
        self.workspace_root = workspace_root
        self.output_dir = validate_workspace_path(output_dir, workspace_root, True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _open(self, request, timeout):
        if not self.api_key:
            return urllib.request.urlopen(request, timeout=timeout)
        request.add_header("Authorization", "Bearer " + self.api_key)
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        try:
            return urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise ValueError("Image worker authentication failed; check its configured API key") from None
            raise

    def get_capabilities(self) -> Set[Capability]:
        return {Capability.IMAGE_GEN}

    def get_health(self) -> RemoteHealth:
        """Check ComfyUI server health and GPU memory stats."""
        if not self.server_url:
            return RemoteHealth(
                status="unconfigured",
                supervisor_uptime_s=0.0,
                container_uptime_s=0.0,
                max_session_s=0.0,
                seconds_remaining_12h=0.0,
                gpus=[],
                raw={},
            )

        url = f"{self.server_url}/system_stats"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "FreeCompute/0.1.0"})
            with self._open(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                devices = data.get("devices", [])
                gpus = []
                for d in devices:
                    vram_total = d.get("vram_total", 0) // (1024 * 1024)
                    vram_free = d.get("vram_free", 0) // (1024 * 1024)
                    vram_used = max(0, vram_total - vram_free)
                    gpus.append(GpuTelemetry(
                        index=d.get("index", 0),
                        name=d.get("name", "Unknown GPU"),
                        vram_used_mib=vram_used,
                        vram_total_mib=vram_total,
                        temp_c=0,
                        utilization_pct=0,
                    ))
                return RemoteHealth(
                    status="healthy",
                    supervisor_uptime_s=0.0,
                    container_uptime_s=0.0,
                    max_session_s=0.0,
                    seconds_remaining_12h=0.0,
                    gpus=gpus,
                    raw=scrubber.structured(data),
                )
        except Exception as exc:
            return RemoteHealth(
                status="unreachable",
                supervisor_uptime_s=0.0,
                container_uptime_s=0.0,
                max_session_s=0.0,
                seconds_remaining_12h=0.0,
                gpus=[],
                raw={"error": scrubber.scrub(exc)},
            )

    def stream_chat(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        cancellation: Optional[Any] = None,
        on_chunk: Optional[Callable[[StreamChunk], None]] = None,
    ) -> Dict[str, Any]:
        self.assert_capability(
            Capability.TEXT,
            guidance="ComfyUIProvider is dedicated to image generation. For text and coding, use LlamaCppProvider.",
        )

    def build_qwen_image_workflow(
        self,
        prompt: str,
        negative_prompt: str = "ugly, blurry, low quality, distorted, bad anatomy",
        width: int = 768,
        height: int = 768,
        steps: int = 8,
        cfg: float = 3.5,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Construct the Qwen-Image-2.1 GGUF node execution graph."""
        if seed is None or seed <= 0:
            seed = random.randint(100000000000000, 999999999999999)

        return {
            "1": {
                "inputs": {
                    "unet_name": "qwen_image_2.1_q4_k_m.gguf",
                },
                "class_type": "UnetLoaderGGUF",
            },
            "2": {
                "inputs": {
                    "clip_name": "qwen_2.5_vl_8b_instruct_q8_0.gguf",
                    "type": "sd3",
                },
                "class_type": "CLIPLoaderGGUF",
            },
            "3": {
                "inputs": {
                    "vae_name": "qwen_image_vae.safetensors",
                },
                "class_type": "VAELoader",
            },
            "4": {
                "inputs": {
                    "text": prompt,
                    "clip": ["2", 0],
                },
                "class_type": "CLIPTextEncode",
            },
            "5": {
                "inputs": {
                    "text": negative_prompt,
                    "clip": ["2", 0],
                },
                "class_type": "CLIPTextEncode",
            },
            "6": {
                "inputs": {
                    "width": width,
                    "height": height,
                    "batch_size": 1,
                },
                "class_type": "EmptySD3LatentImage",
            },
            "7": {
                "inputs": {
                    "seed": seed,
                    "steps": steps,
                    "cfg": cfg,
                    "sampler_name": "euler",
                    "scheduler": "simple",
                    "denoise": 1.0,
                    "model": ["1", 0],
                    "positive": ["4", 0],
                    "negative": ["5", 0],
                    "latent_image": ["6", 0],
                },
                "class_type": "KSampler",
            },
            "8": {
                "inputs": {
                    "samples": ["7", 0],
                    "vae": ["3", 0],
                },
                "class_type": "VAEDecode",
            },
            "9": {
                "inputs": {
                    "filename_prefix": "freecompute_qwen",
                    "images": ["8", 0],
                },
                "class_type": "SaveImage",
            },
        }

    def generate_image(
        self,
        prompt: str,
        width: int = 768,
        height: int = 768,
        steps: int = 8,
        cfg: float = 3.5,
        seed: Optional[int] = None,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, Any]:
        """Submit image workflow to ComfyUI and retrieve the output image."""
        if not self.server_url:
            raise ValueError("ComfyUI server URL not configured. Set FREECOMPUTE_IMAGE_SERVER.")

        client_id = str(uuid.uuid4())
        workflow = self.build_qwen_image_workflow(
            prompt=scrubber.scrub(prompt),
            width=width,
            height=height,
            steps=steps,
            cfg=cfg,
            seed=seed,
        )

        payload = {
            "prompt": workflow,
            "client_id": client_id,
        }

        # 1. Queue prompt via HTTP POST
        req = urllib.request.Request(
            f"{self.server_url}/prompt",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "FreeCompute/0.1.0"},
            method="POST",
        )
        with self._open(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            prompt_id = data.get("prompt_id")

        if not prompt_id:
            raise RuntimeError("Failed to queue prompt with remote ComfyUI engine.")

        # 2. Poll history until task completes
        start_time = time.time()
        timeout = 180.0
        saved_filename = None

        while time.time() - start_time < timeout:
            time.sleep(1.0)
            hist_req = urllib.request.Request(
                f"{self.server_url}/history/{prompt_id}",
                headers={"User-Agent": "FreeCompute/0.1.0"},
            )
            try:
                with self._open(hist_req, timeout=5) as h_resp:
                    h_data = json.loads(h_resp.read().decode("utf-8"))
                    if prompt_id in h_data:
                        outputs = h_data[prompt_id].get("outputs", {})
                        if "9" in outputs:
                            images = outputs["9"].get("images", [])
                            if images:
                                saved_filename = images[0].get("filename")
                                break
            except Exception:
                pass

        if not saved_filename:
            raise TimeoutError(f"Image generation timed out after {timeout} seconds.")

        # 3. Download generated image to local output directory
        view_url = f"{self.server_url}/view?filename={urllib.parse.quote(saved_filename)}&type=output"
        if Path(saved_filename).name != saved_filename or "/" in saved_filename or "\\" in saved_filename:
            raise ValueError("Invalid remote output filename")
        local_dest = validate_workspace_path(str(self.output_dir / saved_filename), self.workspace_root, True)
        if self.api_key:
            import shutil
            with self._open(urllib.request.Request(view_url), timeout=30) as response, local_dest.open("wb") as output:
                shutil.copyfileobj(response, output)
        else:
            urllib.request.urlretrieve(view_url, local_dest)

        return {
            "status": "success",
            "file_path": str(local_dest),
            "filename": saved_filename,
            "width": width,
            "height": height,
            "steps": steps,
            "prompt_id": prompt_id,
        }
