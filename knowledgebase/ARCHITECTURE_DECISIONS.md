# Knowledgebase: Architectural Decision Records (ADRs)

**Project:** Standalone Kaggle x Qwen Coding Harness  
**Last Updated:** 2026-09-27  

---

### ADR-001: Standalone Agent Harness with CLI First, Custom VS Code Extension Second
* **Status:** Accepted (2026-09-27)
* **Context:** Existing open-source agents (Cline, OpenCode, Aider, OpenHands) were evaluated. While Cline and OpenCode have rich features, using them as runtime dependencies restricts our ability to customize the task timeline, manage Kaggle session lifecycle/quota widgets, enforce bespoke diff approvals, and manage long-horizon resumption.
* **Decision:** Build our own standalone agent controller in Python (`harness/`). Build an interactive CLI with rich terminal UI first (Phase 3). Subsequently build a custom dedicated VS Code extension (Phase 4) communicating with the harness daemon via WebSocket/IPC. Cline and OpenCode remain research references only.
* **Consequences:** We control the exact event stream, token caching policy, approval gates, and error recovery without external runtime breakage.

---

### ADR-002: Universal Model & Accelerator Parameterization
* **Status:** Accepted (2026-09-27)
* **Context:** The immediate target is `Huihui-Qwen3.8-27B-abliterated-UD-DW-Q4_K_M.gguf` on Kaggle Dual Tesla T4 GPUs (30 GiB VRAM across two cards). However, users or future setups may have Colab A100/L4, Kaggle P100, or want to test other GGUF models (e.g. GLM-4/5, Llama-3, DeepSeek, Mistral).
* **Decision:** The remote deployment notebook (`kaggle/universal_dual_gpu_server.ipynb`) must isolate model and hardware settings into a clean, top-level `CONFIG` dictionary. The default configuration remains our proven Qwen 27B Dual T4 setup, but changing the Hugging Face repo, filename, context size, and GPU split mode requires only modifying that dictionary.
* **Consequences:** Notebook is future-proof and reusable across multiple hardware tiers and model families.

---

### ADR-003: Reusable Kaggle Dataset Caching Pattern
* **Status:** Accepted (2026-09-27)
* **Context:** Building `llama.cpp` from source takes ~3.5 minutes on Kaggle CPU. Downloading a 16.55 GB GGUF takes ~1.5 to 3 minutes. Repeating this every session wastes 5 to 10 minutes of GPU quota and adds friction.
* **Decision:** Adopt the pattern pioneered by community research (e.g. Tahsine):
  1. The server notebook checks if `/kaggle/input/` contains pre-compiled `llama-server` binaries or the model GGUF (from a private Kaggle Dataset).
  2. If found, it copies/links them in ~20 seconds, bypassing compilation and download.
  3. If not found (cold boot), it falls back to compiling from source (with pinned commit `2b129cc` and `-DGGML_CUDA_NO_VMM=ON`) and downloading from Hugging Face.
  4. Provide a helper notebook (`kaggle/dataset_builder.ipynb`) allowing the user to create their private dataset in one click.
* **Consequences:** Start time drops from ~7 minutes to ~30 seconds on subsequent runs. Zero quota wasted on recompilation.

---

### ADR-004: Ingress Security — Authenticated Gateway
* **Status:** Accepted (2026-09-27)
* **Context:** Kaggle drops all inbound public connections. Exposing an unauthenticated public tunnel (e.g., bare `trycloudflare` or public `ngrok`) exposes the model to arbitrary internet invocations, security scans, and token exhaustion.
* **Decision:** Deploy a lightweight Python supervisor on Kaggle (`kaggle/supervisor.py` on `:8081`). All requests require an `Authorization: Bearer <TOKEN>` header. Tunnel options:
  - **Option A (Recommended):** Tailscale userspace WireGuard mesh (`tailscale up --tun=userspace-networking`). Zero public port exposed; only user's devices can communicate.
  - **Option B:** Cloudflare Tunnel (`cloudflared`) pointing exclusively to the authenticated supervisor on `:8081`.
* **Consequences:** Guaranteed security; zero unauthorized access to Kaggle compute.

---

### ADR-005: Local Task Journaling for Long-Horizon Fault Tolerance
* **Status:** Accepted (2026-09-27)
* **Context:** Kaggle sessions enforce a hard 12-hour limit. If an agent task spans multiple hours or Kaggle runtime restarts, in-memory state would be lost.
* **Decision:** All task progress, decision history, completed milestones, and diffs are persisted locally on the Windows machine in SQLite and `.qwen_harness/journal.jsonl`.
* **Consequences:** If the remote brain disconnects or reaches the 12-hour cap, the task state is 100% preserved locally. Once reconnected to a fresh Kaggle session, the agent resumes execution seamlessly.

---

### ADR-006: Context Management & KV Cache Prefix Stability
* **Status:** Accepted (2026-09-27)
* **Context:** Autoregressive generation on Dual T4 is ~13 tokens/sec. Generating 4,000 tokens takes > 5 minutes. Prefilling 47,000 tokens takes ~171 seconds.
* **Decision:**
  1. Use targeted file and symbol retrieval (ripgrep) rather than loading entire repositories into the prompt.
  2. Maintain an immutable prompt header (system prompt + tool schemas) at the top of every turn, combined with `llama-server --no-context-shift`, enabling instant prompt KV cache reuse.
  3. Direct the model to output concise unified diffs (50–300 tokens) rather than full file rewrites.
* **Consequences:** Sub-second time-to-first-token on subsequent turns; minimal generation latency.
