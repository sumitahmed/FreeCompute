> **Historical document ? notice added 2026-10-02.** Its original body is preserved. Completion, safety and performance statements below are prior reports, not current acceptance evidence. Read the [V2 research index](README.md) and [current source audit](CURRENT_ARCHITECTURE_AUDIT.md) before implementation. V2 remains awaiting explicit user review and approval.

# Knowledgebase: Deployment Runbook & Operator Guide

**Project:** Standalone Kaggle x Qwen Coding Harness  
**Audience:** Developer / Operator  
**Last Updated:** 2026-09-27  

---

## 1. Kaggle Environment Preflight

Before launching the server notebook on Kaggle, ensure the following session settings are selected in the Kaggle notebook sidebar:

* **Accelerator:** `GPU T4 x2` (Verifies two Tesla T4 15,360 MiB GPUs).
* **Internet:** `ON` (Required for initial model download, packages, and secure tunnel).
* **Language:** `Python`.
* **Persistence:** `None` or `Variables and Files` (Code runs out of `/kaggle/tmp/` to keep saved output quota clean).

> [!IMPORTANT]
> Do NOT use "Save & Run All (Commit)" for the interactive server! It is designed to run interactively with the browser tab open or with background execution.

---

## 2. Choosing Your Startup Method

### Method A: Fast Start via Private Kaggle Datasets (Recommended — ~30s boot)
If you have created private Kaggle datasets for the model GGUF and precompiled `llama-server`:
1. In the Kaggle notebook sidebar, click **+ Add Input**.
2. Select your private datasets:
   - `qwen38-27b-abliterated-gguf` (contains `Huihui-Qwen3.8-27B-abliterated-UD-DW-Q4_K_M.gguf`)
   - `llama-cpp-t4-bin` (contains precompiled `llama-server`)
3. Run the notebook cells. The notebook will automatically detect `/kaggle/input/...`, link the binaries in seconds, and skip all compilation and downloading!

### Method B: Cold Start from Source (~6–7 mins boot)
If running on a fresh account without pre-created datasets:
1. Simply run the notebook cells in order.
2. The notebook will:
   - Verify both T4 GPUs via `nvidia-smi`.
   - Clone `llama.cpp` commit `2b129cc` and compile with `-DGGML_CUDA_NO_VMM=ON` (~3.5 mins).
   - Download the exact GGUF checkpoint from Hugging Face (~2 mins).
   - Launch `supervisor.py` and `llama-server`.

---

## 3. Secure Transport Setup

### Option 1: Tailscale Userspace WireGuard (Recommended — Zero Attack Surface)
1. Generate an ephemeral, reusable auth key in your [Tailscale Admin Console](https://login.tailscale.com/admin/settings/keys) (tagged e.g. `tag:kaggle-server`).
2. In Kaggle, paste your key into the secret/config cell:
   ```python
   TAILSCALE_AUTHKEY = "tskey-auth-..."
   ```
3. The notebook starts `tailscaled --tun=userspace-networking` and connects as a node named `kaggle-qwen-brain` directly on your private tailnet.
4. On your local Windows machine, you can access the model directly via its Tailscale IP (e.g. `http://100.x.y.z:8081`). No public port is exposed to anyone else.

### Option 2: Cloudflare Tunnel with Bearer Token
1. If using Cloudflare Tunnel, run `cloudflared` pointing to loopback port `8081` (the supervisor port).
2. The supervisor enforces an API key:
   ```python
   SUPERVISOR_API_KEY = "your-custom-secret-key"
   ```
3. The generated Cloudflare URL (`https://xxxx.trycloudflare.com`) requires the header:
   `Authorization: Bearer <your-custom-secret-key>`. Unauthenticated requests receive HTTP 401.

---

## 4. Connecting Your Windows Local Harness

Once the remote Kaggle server reports `SUPERVISOR HEALTHY`:
1. Note the remote URL and auth token from the notebook output:
   - URL: `http://100.x.y.z:8081` (Tailscale) OR `https://xxxx.trycloudflare.com` (Cloudflare)
   - API Key: `your-secret-token`
2. In your local Windows terminal, launch the harness:
   ```powershell
   python -m harness.cli.main --remote-url "http://100.x.y.z:8081" --api-key "your-secret-token"
   ```
3. The CLI will verify connection, display the real 12h countdown timer, and enter interactive coding agent mode.

---

## 5. Monitoring & Lifecycle Rules

1. **The 12-Hour Hard Limit:**
   - Kaggle shuts down after 12 hours.
   - The supervisor reports `/proc/uptime`. The local harness displays a prominent countdown.
   - If the countdown reaches < 30 minutes, wrap up tasks or let the harness save the current task checkpoint.
2. **Stopping the Server to Save Quota:**
   - When finished with a coding session, run the shutdown cell in Kaggle or click **Stop Session** in the Kaggle web interface to stop burning weekly GPU quota.
   - Stopping `llama-server` process alone does NOT stop Kaggle quota consumption; you must click **Stop Session** on Kaggle.
