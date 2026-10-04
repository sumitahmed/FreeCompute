# Developer & Agent Guidelines for FreeCompute

This document provides architectural guidance, conventions, and security rules for AI coding agents and human contributors working on the FreeCompute codebase.

---

## 1. Architectural Philosophy

FreeCompute is a **local-first AI agent harness** designed to run high-capability coding workflows powered by remote GPU inference (e.g. Kaggle dual Tesla T4s, Colab, or private clusters).

- **Local Machine as Source of Truth:** All tool execution (`inspect_file`, `edit_file`, `write_file`, `run_command`), sandbox boundaries, task journaling, undo snapshots, and human approval gates live strictly on the local machine.
- **Remote Compute as Inference Engine:** The remote GPU runs `llama-server` behind an authenticated supervisor (`kaggle/supervisor.py` on `:8081`). The remote side is an untrusted inference engine; it has no access to the user's local filesystem or terminal.
- **Provider & Capability Isolation:** Modalities are strictly isolated behind `BaseProvider` and `Capability`. An LLM provider must not attempt image generation, and a ComfyUI provider must not attempt text conversation. Unsupported operations must produce clean, actionable errors.
- **Prompt Prefix Stability:** Keep the prompt header (system prompt + tool schemas) stable across turns where possible. This supports llama.cpp prefix reuse; it does not guarantee KV cache hits, sub-second TTFT, or full 65,536-token live acceptance.

---

## 2. Directory Structure

```
freecompute/
├── harness/
│   ├── cli/            # User-facing REPL, terminal formatting, secret scrubbing
│   ├── core/           # Client, prompt builder, orchestrator, data models
│   ├── providers/      # Modality backends (llama.cpp, ComfyUI) and capability router
│   ├── skills/         # Extensible skill discovery and slash-command manager
│   ├── storage/        # Task journaling, checkpoints, and transactional undo ledger
│   ├── telemetry/      # Optional worker observations, configured limits, quota ledger
│   └── tools/          # Sandboxed tools (fs, terminal, web, registry)
├── kaggle/             # Remote supervisor proxy, deployment notebooks
├── skills/             # Project-level skills (SKILL.md manifests)
├── tests/              # Automated unit and integration tests
├── .gitignore          # Strict exclusion of secrets, journals, and caches
├── pyproject.toml      # Standard PEP 517/518 build specification
└── README.md           # Public documentation
```

---

## 3. Security & Safety Rules

1. **Zero Secret Leaking:** Never hardcode API keys, passwords, or live ephemeral TryCloudflare URLs into source code, sample configs, or notebooks.
2. **Mandatory Redaction:** All output streams, logs, and exception messages must pass through `SecretScrubber` before being printed or persisted.
3. **Sandbox Enforcement:** All filesystem operations must pass through `harness/tools/sandbox.py` to prevent path traversal outside the workspace root and block access to sensitive files (`.git`, `.ssh`, `.env`).
4. **Approval Gates:** High-risk actions (`edit_file`, `write_file`, `run_command`) require explicit interactive approval from the user.

---

## 4. Testing & Verification

Before submitting changes or preparing a release, run the automated test suite:

```bash
python -m unittest discover -s tests/unit -p "test_*.py"
```

All unit tests must pass with 100% success rate. Never bypass failing tests or alter expected results to force a pass.
