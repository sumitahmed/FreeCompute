#!/usr/bin/env python3
"""
================================================================================
KAGGLE x QWEN-IMAGE-2.1 UNCENSORED — INTERACTIVE STANDALONE REPL CLI
================================================================================
Provides the full coding-agent-style terminal experience for image generation:
- Interactive prompt loop: 'qwen-image> '
- Slash commands: /status, /settings, /server, /history, /help, /clear, exit
- Live execution timeline & progress bar on Kaggle Dual T4 GPUs
- Automatic local download and image viewer launch on Windows
- Auto-prompts for new Kaggle Cloudflare URL if previous session expired
"""

import sys

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from harness.security import safe_print as print, scrubber
from harness.tools.sandbox import validate_workspace_path
import argparse
import asyncio
import json
import os
import random
import re
import shlex
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

try:
    import websockets
except ImportError:
    print("[ERROR] websockets package is required. Run: pip install websockets")
    sys.exit(1)

CONFIG_URL_FILE = Path(".image_server_url")
FALLBACK_SERVER = os.environ.get("COMFYUI_SERVER_URL", "")


def get_stored_server_url() -> str:
    if CONFIG_URL_FILE.exists():
        try:
            val = CONFIG_URL_FILE.read_text(encoding="utf-8").strip()
            if val.startswith("http"):
                return val
        except Exception:
            pass
    return FALLBACK_SERVER


def save_server_url(url: str):
    try:
        CONFIG_URL_FILE.write_text(url.strip(), encoding="utf-8")
    except Exception:
        pass


class ImageHarnessSession:
    def __init__(self, server_url: str):
        self.server_url = server_url.rstrip("/")
        scrubber.register_secret(self.server_url)
        self.width = 1344
        self.height = 768
        self.steps = 25
        self.cfg = 1.0
        self.denoise = 0.75
        self.history = []

    def set_server(self, new_url: str):
        cleaned = new_url.strip().rstrip("/")
        if not cleaned.startswith("http"):
            print("  [ERROR] URL must start with http:// or https://")
            return False
        self.server_url = cleaned
        scrubber.register_secret(cleaned)
        save_server_url(cleaned)
        print(f"  [OK] Server URL updated & saved: {self.server_url}")
        return True

    def print_banner(self):
        print("\n" + "=" * 76)
        print("  [+] KAGGLE x QWEN-IMAGE-2.1 UNCENSORED (INTERACTIVE CLI HARNESS)")
        print("=" * 76)
        print(f"  Remote Brain  : {self.server_url}")
        print(f"  Model Engine  : Qwen-Image-2.1-UC (Q4_K_M GGUF) + Qwen3-VL 8B (Int8)")
        print(f"  Hardware      : Tesla T4 x2 (30 GB VRAM) + 30 GB System RAM")
        print(f"  Active Config : {self.width}x{self.height} | {self.steps} steps | CFG {self.cfg}")
        print(f"  Local Output  : {Path('./output').resolve()}")
        print("=" * 76)
        print("  Type your image prompt, or /status, /settings, /server, /history, /help, exit.")
        print("-" * 76 + "\n")

    def get_telemetry(self):
        try:
            req = urllib.request.Request(f"{self.server_url}/system_stats", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"error": str(e)}
        return {"error": "unreachable"}

    def show_status(self):
        print("\n--- REMOTE KAGGLE RUNTIME TELEMETRY ---")
        stats = self.get_telemetry()
        if "error" in stats:
            print(f"  Status        : DISCONNECTED ({stats['error']})")
            print("  Please check that Cell 4 is currently running in your Kaggle notebook,")
            print(f"  or update your endpoint URL with: /server <new_url>")
            return

        sys_info = stats.get("system", {})
        ram_total = sys_info.get("ram_total", 0) / (1024**3)
        ram_free = sys_info.get("ram_free", 0) / (1024**3)
        ram_used = ram_total - ram_free
        comfy_ver = sys_info.get("comfyui_version", "Unknown")
        py_ver = sys_info.get("python_version", "Python 3").split()[0]

        print(f"  Remote Server : {self.server_url} (ONLINE 200 OK)")
        print(f"  ComfyUI Core  : v{comfy_ver} (Python {py_ver})")
        print(f"  System Memory : {ram_used:.1f} / {ram_total:.1f} GB RAM Used ({ram_free:.1f} GB Free)")
        print("  GPUs Detected :")
        devices = stats.get("devices", [])
        for d in devices:
            v_tot = d.get("vram_total", 0) / (1024**3)
            v_free = d.get("vram_free", 0) / (1024**3)
            v_used = v_tot - v_free
            name = d.get("name", "GPU").split(":")[0]
            role = "Active Diffusion Model (VRAM)" if v_used > 3.0 else "Standby VRAM"
            print(f"    [{name}] {v_used:.1f} / {v_tot:.1f} GB VRAM Used ({role})")

        print(f"  Active Defaults : {self.width}x{self.height} | {self.steps} steps | CFG {self.cfg}")
        print(f"  Session Created : {len(self.history)} image(s) generated in this session")
        print("-" * 42 + "\n")

    def show_settings(self, arg_str=""):
        if not arg_str:
            print("\n--- ACTIVE GENERATION SETTINGS ---")
            print(f"  Width   : {self.width}px")
            print(f"  Height  : {self.height}px")
            print(f"  Steps   : {self.steps} (8=fast preview ~2m, 12=balanced, 20=max detail)")
            print(f"  CFG     : {self.cfg}")
            print(f"  Denoise : {self.denoise} (for Image-to-Image)")
            print("\nTo change: /settings steps=12 width=1024 height=1024")
            print("-" * 38 + "\n")
            return

        for part in arg_str.split():
            if "=" in part:
                k, v = part.split("=", 1)
                k = k.lower().strip()
                v = v.strip()
                if k == "width":
                    self.width = int(v)
                elif k == "height":
                    self.height = int(v)
                elif k == "steps":
                    self.steps = int(v)
                elif k == "cfg":
                    self.cfg = float(v)
                elif k == "denoise":
                    self.denoise = float(v)
        print(f"  [OK] Updated settings: {self.width}x{self.height} | {self.steps} steps | CFG {self.cfg} | Denoise {self.denoise}\n")

    def show_history(self):
        print("\n--- SESSION GENERATION HISTORY ---")
        if not self.history:
            print("  No images generated yet in this session.")
        else:
            for idx, item in enumerate(self.history, 1):
                print(f"  {idx}. \"{item['prompt']}\"")
                print(f"     File: file:///{Path(item['path']).resolve().as_posix()}")
                print(f"     Stats: {item['width']}x{item['height']}, {item['steps']} steps, {item['time']}s")
        print("-" * 42 + "\n")

    def show_help(self):
        print("\nCOMMANDS & SHORTCUTS:")
        print("  /status               Show Kaggle remote health, Dual GPU VRAM, and RAM")
        print("  /server <new_url>     Switch to a new Cloudflare URL when Kaggle restarts")
        print("  /settings             View current width, height, steps, and CFG scale")
        print("  /settings steps=12    Change generation parameters on the fly")
        print("  /history              View all images generated in this session")
        print("  /clear                Clear the terminal screen")
        print("  exit / quit           Exit the harness")
        print("\nGENERATION SYNTAX:")
        print("  <any text prompt>     Generate image with active settings")
        print("  Example: a cybernetic dragon flying over neon Tokyo")
        print("\nINLINE OVERRIDES:")
        print("  You can override settings inline in any prompt:")
        print("  a neon samurai --steps 12 --width 1024 --height 1024")
        print("\nIMAGE-TO-IMAGE:")
        print("  /i2i <path_to_image> [prompt] [--denoise 0.7]")
        print("-" * 60 + "\n")

    def upload_image(self, image_path: Path) -> str:
        image_path = validate_workspace_path(str(image_path))
        print(f"  [>] Uploading reference image: {image_path.name}...")
        boundary = "----WebKitFormBoundary" + str(random.randint(100000, 999999))
        with open(image_path, "rb") as f:
            file_bytes = f.read()

        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{image_path.name}"\r\n'
            f"Content-Type: image/png\r\n\r\n"
        ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

        req = urllib.request.Request(
            f"{self.server_url}/upload/image",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            print(f"  [OK] Image uploaded successfully as: {res['name']}")
            return res["name"]

    def build_workflow(self, prompt, negative_prompt="", width=None, height=None, steps=None, cfg=None, seed=None, input_image_name=None, denoise=None):
        w = width or self.width
        h = height or self.height
        s = steps or self.steps
        c = cfg or self.cfg
        d = denoise or (self.denoise if input_image_name else 1.0)
        sd = seed or random.randint(1, 1000000000)

        nodes = {
            "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "qwen-image-2.1-UC-Q4_K_M.gguf"}},
            "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image"}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {"text": scrubber.scrub(prompt), "clip": ["2", 0]}},
            "5": {"class_type": "CLIPTextEncode", "inputs": {"text": scrubber.scrub(negative_prompt), "clip": ["2", 0]}},
            "7": {"class_type": "KSampler", "inputs": {"seed": sd, "steps": s, "cfg": c, "sampler_name": "euler", "scheduler": "simple", "denoise": d, "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0]}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
            "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "QwenImage", "images": ["8", 0]}}
        }

        if input_image_name:
            nodes["10"] = {"class_type": "LoadImage", "inputs": {"image": input_image_name}}
            nodes["6"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["10", 0], "vae": ["3", 0]}}
        else:
            nodes["6"] = {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}}

        return nodes, w, h, s

    async def execute_generation(self, prompt, negative="", width=None, height=None, steps=None, cfg=None, image_path=None, denoise=None, custom_out=None):
        uploaded_name = None
        if image_path:
            p = validate_workspace_path(image_path)
            if not p.exists():
                print(f"  [ERROR] Image not found: {p}")
                return
            uploaded_name = self.upload_image(p)

        workflow, w, h, s = self.build_workflow(
            prompt=prompt,
            negative_prompt=negative,
            width=width,
            height=height,
            steps=steps,
            cfg=cfg,
            input_image_name=uploaded_name,
            denoise=denoise
        )

        client_id = str(uuid.uuid4())
        ws_protocol = "wss" if self.server_url.startswith("https") else "ws"
        host = self.server_url.replace("https://", "").replace("http://", "")
        ws_uri = f"{ws_protocol}://{host}/ws?clientId={client_id}"

        node_titles = {
            "1": "Loading Diffusion weights",
            "2": "Loading Qwen3-VL text encoder",
            "4": "Encoding prompt tokens",
            "5": "Encoding negative prompt",
            "6": "Initializing latents",
            "7": "Sampling diffusion steps",
            "8": "Decoding latents with VAE",
            "9": "Saving output image",
            "10": "Reading input reference image",
        }

        mode_str = "IMAGE-TO-IMAGE" if image_path else f"TEXT-TO-IMAGE ({w}x{h}, {s} steps)"
        print(f"\n  Mode   : {mode_str}")
        print(f"  Prompt : \"{prompt}\"")
        print(f"  [*] Connecting WebSocket to: {ws_uri}...")

        try:
            async with websockets.connect(ws_uri, max_size=100_000_000) as ws:
                print("  [OK] WebSocket connected! Submitting task to Kaggle...")
                payload = json.dumps({"prompt": workflow, "client_id": client_id}).encode("utf-8")
                req = urllib.request.Request(f"{self.server_url}/prompt", data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    prompt_id = res.get("prompt_id")
                    if not isinstance(prompt_id, str) or not prompt_id:
                        raise ValueError("ComfyUI did not return a job ID")
                    print(f"  [OK] Prompt Queued! Task ID: {prompt_id}\n")

                print("  " + "-" * 72)
                print("  LIVE EXECUTION TIMELINE ON KAGGLE DUAL T4:")
                print("  " + "-" * 72)

                start_t = time.time()
                while True:
                    remaining = 1800 - (time.time() - start_t)
                    if remaining <= 0:
                        raise TimeoutError("Image job wait expired; remote outcome unknown")
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    except asyncio.TimeoutError:
                        raise TimeoutError("Image job wait expired; remote outcome unknown") from None
                    if not isinstance(msg, str):
                        continue
                    event = json.loads(msg)
                    event_type = event.get("type")
                    event_data = event.get("data", {})
                    if event_type in {"execution_start", "executing", "progress", "execution_error"} and event_data.get("prompt_id") != prompt_id:
                        continue

                    if event_type == "execution_start":
                        print("  [START] Kaggle execution pipeline started.")
                    elif event_type == "executing":
                        node_id = str(event_data.get("node"))
                        if node_id == "None":
                            print("\n  [DONE] All pipeline stages completed on Kaggle!")
                            break
                        title = node_titles.get(node_id, f"Node {node_id}")
                        elapsed = int(time.time() - start_t)
                        print(f"\n  [{elapsed:3d}s] Stage: {title} (Node {node_id})")
                    elif event_type == "progress":
                        val = event_data.get("value", 0)
                        max_val = event_data.get("max", 1)
                        pct = int((val / max(1, max_val)) * 100)
                        bar_len = 30
                        filled = int((pct / 100) * bar_len)
                        bar = "#" * filled + "-" * (bar_len - filled)
                        elapsed = int(time.time() - start_t)
                        sys.stdout.write(scrubber.scrub(f"\r  [{elapsed:3d}s] Denoising: [{bar}] {pct:3d}% (Step {val}/{max_val})"))
                        sys.stdout.flush()
                    elif event_type == "execution_error":
                        print(f"\n  [ERROR] Kaggle execution failed: {event_data.get('exception_message')}")
                        return

                print("\n  " + "-" * 72)
                print("  Downloading generated image over tunnel to local PC...")
                req_hist = urllib.request.Request(f"{self.server_url}/history/{prompt_id}")
                with urllib.request.urlopen(req_hist) as resp:
                    history = json.loads(resp.read().decode("utf-8"))

                outputs = history.get(prompt_id, {}).get("outputs", {})
                images = outputs.get("9", {}).get("images", [])
                if not images:
                    print("  [ERROR] No image was found in output history.")
                    return

                img = images[0]
                filename = img["filename"]
                subfolder = img.get("subfolder", "")
                img_type = img.get("type", "output")

                view_url = self.server_url + "/view?" + urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": img_type})
                if custom_out:
                    out_path = Path(custom_out)
                else:
                    ts = time.strftime("%Y%m%d_%H%M%S")
                    out_path = Path(f"./output/qwen_{ts}.png")

                out_path = validate_workspace_path(str(out_path), allow_write_to_new_file=True)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                urllib.request.urlretrieve(view_url, out_path)

                total_sec = int(time.time() - start_t)
                file_mb = out_path.stat().st_size / (1024 * 1024)

                print(f"  [OK] SUCCESS! ({file_mb:.2f} MB in {total_sec}s)")
                print(f"  Saved to:\n    file:///{out_path.resolve().as_posix()}")
                print("=" * 76 + "\n")

                self.history.append({
                    "prompt": scrubber.scrub(prompt),
                    "path": str(out_path),
                    "width": w,
                    "height": h,
                    "steps": s,
                    "time": total_sec
                })

                if sys.platform == "win32":
                    try:
                        os.startfile(str(out_path.resolve()))
                    except Exception:
                        pass

        except Exception as e:
            print(f"\n  [ERROR] Connection or execution error: {e}")


def parse_inline_prompt(user_text):
    tokens = shlex.split(user_text)
    prompt_tokens = []
    overrides = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--steps" and i + 1 < len(tokens):
            overrides["steps"] = int(tokens[i + 1])
            i += 2
        elif tok == "--width" and i + 1 < len(tokens):
            overrides["width"] = int(tokens[i + 1])
            i += 2
        elif tok == "--height" and i + 1 < len(tokens):
            overrides["height"] = int(tokens[i + 1])
            i += 2
        elif tok == "--cfg" and i + 1 < len(tokens):
            overrides["cfg"] = float(tokens[i + 1])
            i += 2
        elif tok == "--denoise" and i + 1 < len(tokens):
            overrides["denoise"] = float(tokens[i + 1])
            i += 2
        elif tok == "--negative" and i + 1 < len(tokens):
            overrides["negative"] = tokens[i + 1]
            i += 2
        elif tok == "--image" and i + 1 < len(tokens):
            overrides["image"] = tokens[i + 1]
            i += 2
        elif tok in ("--aspect", "--ar") and i + 1 < len(tokens):
            ar = tokens[i + 1].strip().lower()
            if ar in ("16:9", "16/9"):
                overrides["width"], overrides["height"] = 1344, 768
            elif ar in ("9:16", "9/16"):
                overrides["width"], overrides["height"] = 768, 1344
            elif ar in ("1:1", "square"):
                overrides["width"], overrides["height"] = 1024, 1024
            elif ar in ("4:3", "4/3"):
                overrides["width"], overrides["height"] = 1152, 864
            elif ar in ("3:4", "3/4"):
                overrides["width"], overrides["height"] = 864, 1152
            i += 2
        elif tok == "--output" and i + 1 < len(tokens):
            overrides["output"] = tokens[i + 1]
            i += 2
        else:
            prompt_tokens.append(tok)
            i += 1

    clean_prompt = " ".join(prompt_tokens).strip()
    return clean_prompt, overrides


def check_health_or_prompt_user(session: ImageHarnessSession):
    while True:
        stats = session.get_telemetry()
        if "error" not in stats:
            return True

        print(f"\n  [!] Could not connect to remote Kaggle at: {session.server_url}")
        print("      If your Kaggle session restarted, paste your new Cloudflare URL below:")
        try:
            new_url = input("  New Kaggle URL (or press Enter to retry / 'exit' to quit): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            sys.exit(0)

        if not new_url:
            continue
        if new_url.lower() in ("exit", "quit"):
            sys.exit(0)

        session.set_server(new_url)


def main():
    default_url = get_stored_server_url()

    parser = argparse.ArgumentParser(description="Interactive Kaggle x Qwen-Image-2.1 Generation Harness")
    parser.add_argument("--server", type=str, default=default_url, help="Remote Kaggle Cloudflare Tunnel URL")
    parser.add_argument("--prompt", type=str, default=None, help="Execute single prompt directly")
    parser.add_argument("--width", type=int, default=1344, help="Width")
    parser.add_argument("--height", type=int, default=768, help="Height")
    parser.add_argument("--steps", type=int, default=25, help="Steps")
    parser.add_argument("--cfg", type=float, default=1.0, help="CFG Scale")
    parser.add_argument("--image", type=str, default=None, help="Input image for I2I")
    parser.add_argument("--denoise", type=float, default=0.75, help="Denoise for I2I")
    parser.add_argument("--output", type=str, default=None, help="Output path")
    args = parser.parse_args()

    # If --server explicitly passed, save it
    if args.server != default_url:
        save_server_url(args.server)

    session = ImageHarnessSession(server_url=args.server)
    session.width = args.width
    session.height = args.height
    session.steps = args.steps
    session.cfg = args.cfg
    session.denoise = args.denoise

    session.print_banner()

    # Preflight check health; prompt user if unreachable
    print("  [*] Verifying connection to remote Kaggle brain...")
    check_health_or_prompt_user(session)
    print("  [OK] Remote Kaggle GPU is ONLINE and responding!")

    # If single prompt passed via CLI, execute and enter REPL
    if args.prompt:
        asyncio.run(session.execute_generation(
            prompt=args.prompt,
            image_path=args.image,
            denoise=args.denoise,
            custom_out=args.output
        ))

    # Enter interactive REPL loop
    while True:
        try:
            cmd = input("\nqwen-image> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nSession ended.")
            break

        if not cmd:
            continue

        if cmd.lower() in ("exit", "quit", "/exit", "/quit"):
            print("Session ended. To preserve GPU quota, remember to Stop Session in Kaggle!")
            break

        if cmd.lower() in ("/status", "/health"):
            session.show_status()
            continue

        if cmd.lower().startswith("/server"):
            parts = cmd.split(maxsplit=1)
            if len(parts) > 1:
                session.set_server(parts[1])
            else:
                print(f"  Current Server: {session.server_url}")
                print("  To update: /server <url>")
            continue

        if cmd.lower().startswith("/settings") or cmd.lower().startswith("/config"):
            arg_part = cmd[len("/settings"):].strip() if cmd.lower().startswith("/settings") else cmd[len("/config"):].strip()
            session.show_settings(arg_part)
            continue

        if cmd.lower() in ("/history", "/list"):
            session.show_history()
            continue

        if cmd.lower() in ("/help", "/?"):
            session.show_help()
            continue

        if cmd.lower() in ("/clear", "cls", "clear"):
            os.system("cls" if sys.platform == "win32" else "clear")
            session.print_banner()
            continue

        if cmd.startswith("/i2i"):
            parts = cmd[len("/i2i"):].strip().split(maxsplit=1)
            if not parts:
                print("  Usage: /i2i <path_to_image> [prompt]")
                continue
            img_path = parts[0]
            p_text = parts[1] if len(parts) > 1 else "enhance and restyle this image"
            clean_p, overrides = parse_inline_prompt(p_text)
            asyncio.run(session.execute_generation(
                prompt=clean_p,
                image_path=img_path,
                width=overrides.get("width"),
                height=overrides.get("height"),
                steps=overrides.get("steps"),
                cfg=overrides.get("cfg"),
                denoise=overrides.get("denoise"),
                custom_out=overrides.get("output")
            ))
            continue

        # Standard prompt execution
        clean_p, overrides = parse_inline_prompt(cmd)
        if not clean_p:
            continue

        asyncio.run(session.execute_generation(
            prompt=clean_p,
            image_path=overrides.get("image"),
            width=overrides.get("width"),
            height=overrides.get("height"),
            steps=overrides.get("steps"),
            cfg=overrides.get("cfg"),
            negative=overrides.get("negative", ""),
            denoise=overrides.get("denoise"),
            custom_out=overrides.get("output")
        ))


if __name__ == "__main__":
    main()
