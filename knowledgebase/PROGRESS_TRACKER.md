# Knowledgebase: Progress Tracker & Execution Journal

**Project:** Standalone Kaggle x Qwen Coding Harness  
**Authoritative Location:** Windows Local PC  
**Current Phase:** Phase 4 (Dedicated Custom VS Code Extension)  
**Last Updated:** 2026-09-27  

---

## 1. High-Level Phase Status

| Phase | Description | Status | Verification & Evidence |
| :--- | :--- | :--- | :--- |
| **Phase 0** | Audit, Research & Architecture Specification | **COMPLETED & APPROVED** | Detailed in `PHASE_0_AUDIT_AND_ARCHITECTURE.md` (433 lines, verified baseline). |
| **Phase 1** | Universal Remote Kaggle Brain & Supervisor | **COMPLETED** | `kaggle/supervisor.py`, `universal_dual_gpu_server.ipynb`, `dataset_builder.ipynb` created. |
| **Phase 2** | Local Core Harness Engine & Secure Transport | **COMPLETED** | Streaming SSE client, TTFT tracking, slot cancellation, session & quota telemetry, journal. 8/8 tests PASS. |
| **Phase 3** | Standalone Interactive CLI Coding Agent | **COMPLETED** | Path sandbox, safe fs tools, surgical diff patcher, command runner, orchestrator, CLI REPL. 18/18 tests PASS. |
| **Phase 4** | Dedicated Custom VS Code Extension | **READY TO START** | Sidebar webview, editor diffs, IPC with local daemon, status bar quota widgets. |
| **Phase 5** | Long-Horizon Reliability & Microbenchmarking | **PENDING** | Checkpoint recovery, context compaction, full microbenchmark validation. |

---

## 2. Granular Task Checklist

### Phase 0: Audit & Architecture (Complete)
- [x] Inspect existing proof notebook (`qwen3-8-27b-abliterated-q4-kaggle-dual-t4-proof.ipynb`)
- [x] Verify Dual T4 allocation at 32K and 65K context (9.2 GiB / 10.3 GiB VRAM)
- [x] Confirm measured token generation speed (~13.0 tokens/sec on Dual T4)
- [x] Audit Kaggle networking constraints (inbound blocked, outbound NAT)
- [x] Audit Kaggle quota & session limits (12.0h container cap, manual quota tracking)
- [x] Complete competitor & open-source research (Tahsine, Shabeeb Hasan, Aider, Cline)
- [x] Architectural pivot: Standalone harness + custom VS Code extension (Cline as reference only)

### Phase 1: Universal Kaggle Brain & Supervisor (Complete)
- [x] Setup `knowledgebase/` directory and documentation framework
- [x] Implement `kaggle/supervisor.py`:
  - [x] Token-based authentication gate (Bearer token)
  - [x] Process watchdog (auto-restart for `llama-server`)
  - [x] Health and telemetry endpoint (`/health`) reporting container uptime and GPU stats
  - [x] Streaming completions proxy (`/v1/chat/completions`)
  - [x] Process control endpoint (`/control/restart`, `/control/stop`)
- [x] Implement `kaggle/universal_dual_gpu_server.ipynb`:
  - [x] Parameterized configuration block (Qwen default, adaptable to any GGUF)
  - [x] Automated detection of attached Kaggle Datasets (skip compile/download if cached)
  - [x] Ephemeral build fallback (`-DGGML_CUDA_NO_VMM=ON`, commit `2b129cc`)
  - [x] Layer-split CUDA configuration (`--split-mode layer --tensor-split 1,1`)
  - [x] Integrated supervisor & secure tunnel launcher
- [x] Implement `kaggle/dataset_builder.ipynb`:
  - [x] One-time notebook to download model and compile `llama-server` into a reusable private Kaggle dataset.

### Phase 2: Local Core Engine & Transport (Complete)
- [x] Data models for messages, streaming chunks, tool calls, and GPU telemetry (`harness/core/models.py`)
- [x] Configuration loader with environment variable & YAML overrides (`harness/config.py`)
- [x] Authenticated streaming client with SSE parser, TTFT tracking, and cancellation (`harness/core/client.py`)
- [x] Prompt builder enforcing immutable prefix caching (`harness/core/prompt.py`)
- [x] Session tracker with container uptime, 12h countdown, and warning thresholds (`harness/telemetry/session_tracker.py`)
- [x] Quota ledger tracking user balance and local GPU consumption (`harness/telemetry/quota_ledger.py`)
- [x] Persistent task journal and milestone checkpoint system (`harness/storage/journal.py`)

### Phase 3: Standalone Interactive CLI Coding Agent (Complete)
- [x] Security path sandboxing & directory traversal protection (`harness/tools/sandbox.py`)
- [x] Safe filesystem tools: `read_file`, `write_file`, `list_dir`, `grep_search`, `edit_file` with surgical diffs (`harness/tools/fs.py`)
- [x] Sandboxed terminal command runner with execution timeouts and safety filters (`harness/tools/terminal.py`)
- [x] Tool registry mapping OpenAI function calling schemas with approval gate flags (`harness/tools/registry.py`)
- [x] Multi-turn autonomous agent turn loop with live streaming and approval gates (`harness/core/orchestrator.py`)
- [x] Interactive terminal REPL with activity timeline, session telemetry, and approval prompts (`harness/cli/main.py`)
- [x] Full automated test suite passing 18/18 tests across unit and integration tests (`tests/unit/test_*.py`)

---

## 3. Verified Metrics & Ground Truths

* **Model Checkpoint:** `Huihui-Qwen3.8-27B-abliterated-UD-DW-Q4_K_M.gguf` (16.55 GB decimal, SHA `3f101cd22b7999228bbd5d79a33975414eb9758b`).
* **llama.cpp Pinned Commit:** `2b129ccfa03aea330d2d9ac4650a10de393dbe3a`.
* **CMake Build Flags:** `-DGGML_CUDA=ON -DGGML_CUDA_NO_VMM=ON -DCMAKE_CUDA_ARCHITECTURES=75 -DCMAKE_BUILD_TYPE=Release -DLLAMA_BUILD_TESTS=OFF`.
* **Hardware Memory Footprint at 65,536 Context:**
  - CUDA0 (T4 #0): ~9,187 MiB / 15,360 MiB.
  - CUDA1 (T4 #1): ~10,305 MiB / 15,360 MiB.
  - Both cards leave > 5 GiB safety headroom.
* **Autoregressive Generation Speed:** ~12.7 to 13.5 tokens/sec.
* **Kaggle Session Limit:** Exactly 12.0 hours.
* **Weekly Account Quota:** ~30 hours GPU T4 (untracked by API, tracked locally as estimate against user-entered balance).
