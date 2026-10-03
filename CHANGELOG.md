# Changelog

All notable changes to **FreeCompute** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## Unreleased V1 CLI candidate ? 2026-10-04

- Fixed Windows ANSI prompt fragments; live slash/context menus, arrows/Enter/Tab/
  Escape, multiline/history and streamed Markdown presentation.
- Shared help/completion registry; bundled /review, /research, /leetcode manifests.
- Independent text/image route selection and temporary reconnect with separate
  dotenv credentials and authenticated gateway transport for remote ComfyUI.
- Generic optional GPU/CPU/RAM/disk/session telemetry with provenance, stale samples,
  unknown account limits/quota and bounded model-wait refresh.
- Verified private Kaggle dataset reuse, complete runtime library packaging,
  repaired optional builder, pinned-source fallback and manual shutdown.
- Preserved approval/durable queue/quarantine/receipt/undo behavior; added focused
  menu/telemetry/asset/web regressions and fresh installed-wheel acceptance.
- Public docs/security/packaging corrected. Beta version remains 0.1.0; no production
  release, GPU availability or universal context/transport certification is claimed.

## Historical implementation notes ? 2026-09-29 (not a published release)

The items below are original milestone notes. Cache/timing/session/image claims
are historical, not current verified guarantees. Current behavior and evidence
are in README and knowledgebase/V1_RELEASE_READINESS.md.

### Added
- **Unified Standalone CLI:** Interactive REPL (`freecompute` / `run.bat` / `run.ps1`) with live terminal formatting, Markdown rendering, and truthful streaming statistics.
- **Remote GPU Inference Architecture:** Verified support for Kaggle Dual Tesla T4 GPUs (30 GiB VRAM) running Huihui-Qwen3.8-27B-Abliterated Q4 on `llama-server` with 65,536 configured context.
- **Remote Supervisor Gateway:** Lightweight Python reverse proxy (`kaggle/supervisor.py`) providing Bearer token authentication, real container uptime from `/proc/uptime`, dual-GPU telemetry, and watchdog monitoring on port 8081.
- **Prefix Cache Stabilization:** Header-stabilized prompt builder enabling instant sub-second TTFT via `llama.cpp` KV cache reuse.
- **Provider & Capability Abstraction:** Modular `BaseProvider` and `Capability` router (`TEXT`, `CODE_TOOLS`, `IMAGE_GEN`) with explicit capability checks and actionable error guidance.
- **Integrated ComfyUI Backend:** Dedicated `ComfyUIProvider` for Qwen-Image-2.1 generation via WebSocket and HTTP API without external scripts.
- **Transactional Undo Ledger:** Automatic pre-change file snapshotting in `harness/storage/undo.py` with `/diff` inspection and `/undo` rollback commands.
- **Extensible Skills System:** Markdown-based `SKILL.md` parser with frontmatter metadata, slash-command discovery, and starter skills (`code-reviewer`, `neetcode-solver`, `web-researcher`).
- **Telemetry & Quota Tracking:** Container age monitoring with 12h cutoff estimation, plus honest local consumption tracking distinguished from user-observed weekly quota.
- **Credential Redaction Engine:** `SecretScrubber` filtering API keys, Bearer tokens, private URLs, and credentials before terminal output or disk logging.
- **Comprehensive Packaging:** Standard `pyproject.toml`, `requirements.txt`, `.env.example`, `.gitignore`, and Apache-2.0 license.
