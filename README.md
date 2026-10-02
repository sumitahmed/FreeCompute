# FreeCompute

Run open-source LLMs and image models on free cloud GPUs, controlled from your local terminal.

[![Kaggle Notebook](https://img.shields.io/badge/Kaggle-Run%20on%20Dual%20T4-20BEFF?logo=kaggle&logoColor=white)](https://www.kaggle.com/code/sumitahmed3/relayforge)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Tests: Passing](https://img.shields.io/badge/Tests-42%2F42%20Passing-success.svg)](tests/)

---

## Why this exists

Kaggle gives everyone **30 hours per week of free dual Tesla T4 GPUs (30 GB total VRAM)**. Almost nobody actually takes advantage of it.

FreeCompute bridges that free compute to your local terminal. Instead of frying your laptop running heavy models locally or paying monthly API fees:

- The model runs on Kaggle's dual GPUs (Qwen, GLM, DeepSeek, or any unfiltered/abliterated GGUF from Hugging Face).
- A secure Cloudflare tunnel routes inference back to your machine.
- Your code, file edits, bash commands, and git history stay strictly on your local machine.
- The remote server is just an untrusted inference box. It never touches your local files directly.
- The agent asks for your confirmation before writing code or running shell commands, and you can revert any mistake instantly with `/undo`.

---

## Quickstart

### 1. Launch the Remote GPU Server

1. Open the [FreeCompute Kaggle Notebook](https://www.kaggle.com/code/sumitahmed3/relayforge) (or upload `kaggle/universal_dual_gpu_server.ipynb`).
2. Set Accelerator to **GPU T4 x2** and toggle Internet to **ON**.
3. Run all cells. Once loaded, it prints your tunnel URL:
   ```text
   ======================================================================
     FREECOMPUTE REMOTE GPU SUPERVISOR ONLINE
   ======================================================================
     Public URL : https://your-tunnel-url.trycloudflare.com
     API Key    : your-bearer-token
   ======================================================================
   ```

### 2. Install FreeCompute Locally

```bash
git clone https://github.com/sumitahmed/FreeCompute.git
cd FreeCompute

python -m venv .venv

# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

pip install -e .
```

### 3. Connect

```bash
freecompute --remote-url "https://your-tunnel-url.trycloudflare.com" --api-key "your-bearer-token"
```

*(You can also drop these into `.env` so you just run `freecompute` directly without flags).*

---

## Tested Models (Kaggle Dual T4 / 30 GB VRAM)

The notebook splits layers 50/50 across both T4 GPUs. You can swap any GGUF from Hugging Face by updating `CONFIG` in Cell 2:

| Model | Size / Quant | VRAM | Context | Notes | Hugging Face |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Qwen 3.8-27B Abliterated** *(Default)* | 27B Q4_K_M | ~19.5 GB | **65,536** | Uncensored, great reasoning and coding. Handles large repos without refusals. | [Link](https://huggingface.co/huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF) |
| **Qwen 2.5 Coder 32B Instruct** | 32B Q4_K_M | ~22.0 GB | **48,000** | Top-tier open coding model for complex refactoring. | [Link](https://huggingface.co/Qwen/Qwen2.5-Coder-32B-Instruct-GGUF) |
| **DeepSeek-R1 Distill Qwen 32B** | 32B Q4_K_M | ~22.0 GB | **32,768** | Strong reasoning and math for difficult algorithms. | [Link](https://huggingface.co/unsloth/DeepSeek-R1-Distill-Qwen-32B-GGUF) |
| **Mistral Small 24B Instruct 2501** | 24B Q4_K_M | ~16.5 GB | **32,768** | Fast generation, low latency. | [Link](https://huggingface.co/bartowski/mistral-small-24b-instruct-2501-GGUF) |
| **Qwen 2.5 Coder 14B / 7B** | 14B/7B Q8 | ~10–14 GB | **65,536** | Fast alternative; also fits single-GPU Colab free tier. | [Link](https://huggingface.co/Qwen/Qwen2.5-Coder-14B-Instruct-GGUF) |

---

## CLI Commands

Inside `freecompute>`:

| Command | Action |
| :--- | :--- |
| `<task description>` | Run pair-programming task. Agent inspects files, drafts diffs, and requests approval. |
| `/status` | Check Kaggle container age, remaining time in 12h session, and dual-GPU VRAM usage. |
| `/quota <hours>` | Save your weekly Kaggle GPU quota balance (e.g. `/quota 22.5`). |
| `/diff` | Show colorized diff of the last file modified by the agent. |
| `/undo` | Rollback the last file change immediately. |
| `/skills` | List installed skills and slash commands. |
| `/image <prompt>` | Send prompt to remote ComfyUI instance (if configured). |
| `/model` | Show active model, context length, and remote URL. |
| `/clear` | Clear terminal. |
| `exit` | Quit the CLI session. |

---

## Adding Custom Skills

Drop a folder inside `./skills/<skill-name>/` with a `SKILL.md`:

```markdown
---
name: database-designer
description: Designs clean SQL schemas and migrations
slash_command: /db
---

# Database Designer
When designing database tables:
1. Always add created_at and updated_at timestamps.
2. Use UUIDv7 or BIGINT for primary keys.
3. Write rollback SQL scripts for all migrations.
```

Trigger it directly in the REPL using `/db <task>` or `/skill database-designer`.

---

## Testing

```bash
# Run unit tests
python -m unittest discover -s tests/unit -p "test_*.py"

# Secret leak scan
python tests/security_scan.py
```

---

## License

[Apache 2.0](LICENSE)
