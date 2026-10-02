# Stage 1 safety baseline — implemented evidence

2026-10-02. Branch: `v2/safety-and-agentdriver-spike`. Starting point: documentation commit `23b110cb49689a00868d16624316e7da568ea664`. Scope authorized by the subsequent Stage 1 / bounded Stage 2 request. This is a focused repair of the existing CLI, not the V2 runtime migration.

## Implemented changes

| Boundary | Change | Regression evidence |
| --- | --- | --- |
| Approval | `ToolRegistry.execute` validates an argument object, rejects unknown/wrong/missing arguments, and requires callback result `True` for writes, edits and commands. Missing callback and cancellation deny execution. CLI blank approval now declines. | Direct/headless/child denial, truthy nonboolean denial, blank CLI input, cancellation during approval |
| Child scope | A minimal `ToolBroker` presents a fixed allowed-tool set and rejects widening a child set. SDK tools are not registered as executable production tools. | Read-only child denies writes/commands and cannot widen |
| Paths | Check lexical and resolved names, case variants, Windows dot/space aliases, credential variants, private runtime folders, certificate extensions, ADS syntax; deny child symlinks and reparse points. Recursive traversal prunes unsafe directories and validates each file before reading. | Recursive secret search, protected listing/snapshot, traversal, symlink stat seam, real Windows junction escape |
| File writes | Write/edit/restore use temporary neighboring files, final sandbox/hash checks, fsync and atomic replacement. Existing file modes are preserved. | Replacement failure preserves target and snapshot; approval-time content conflicts |
| Undo | UUID identities, immutable snapshot records and preimages, persisted SHA-256 pre/post hashes, explicit sealing, conflict and missing/corrupt-backup checks, approval for restoration, recheck after approval. Unsealed legacy records cannot be restored automatically. | Unique IDs, reload/hashes, missing/corrupt backup, unsealed/modified target, restore denial, mutation during approval |
| Remote auth | Canonical supervisor refuses missing/blank credentials at startup, uses constant-time comparison, authenticates health/control/proxy routes, permits only models GET and chat-completions POST. Restart without an owned launch command returns conflict. | Missing/blank config, unauthenticated health, authenticated health, denied slots/props/unknown V1 paths |
| Deployment copies | Two text deployment notebook cells embed the canonical supervisor; notebook health polling sends auth and consumes the updated health shape. Empty keys fail before starting inference. No notebook was executed. | AST comparison of embedded source to canonical file, health-header check |
| Redaction | Shared scrubber below CLI; structured broker results/approval arguments, streaming text and reasoning buffering, inference payloads, exposed completion callbacks, journal/checkpoints, errors, terminal/UI/image displays. Registered secrets split across streamed chunks are held and scrubbed. | All registered-secret split positions, text/reasoning callbacks, journal/checkpoint/diff sinks |
| Config | Defaults < YAML < literal `.env` < process environment < explicit CLI options. In each environment layer, FREECOMPUTE beats RELAYFORGE then HARNESS. TIMEOUT works; extra YAML fields, unsupported transport, invalid URL and nonpositive budgets/timeouts are rejected. Secret input is hidden from validation errors/config repr. | Canonical/legacy precedence, process vs dotenv, timeout, missing explicit file, validation cases |
| Images | Comfy health uses actual `RemoteHealth` constructor names; unavailable session lifetime is zero/unknown rather than an invented 12h balance. Image-only capability stays separate. Remote filenames and local uploads/outputs are sandboxed. Legacy WebSocket completion is correlated to prompt ID and wait is bounded. | All Comfy health paths, modality tests, filename traversal rejection, protected image upload, wrong-job completion and timeout |
| Accounting | Quota is explicitly local task wall time, not GPU billing; completed intervals remain deducted since the last observation, a new observation resets the basis, stale active intervals are not resumed as measured usage. Session ages/caps are labeled estimates with their source. CLI reports server usage if supplied, otherwise unknown; chunks are never counted as tokens. | Completed/reloaded quota and new observation, estimate labels, unknown usage and existing telemetry suite |
| Cancellation | Thread-safe request flag; active HTTP socket interruption where available; checks before tools and after approvals. Command runner observes request/timeout, kills and waits for its owned shell, reports descendants unknown. Remote inference cancellation is never inferred from local closure. | Existing SSE cancellation, cancellation during approval, owned subprocess exit with unknown descendants |
| Checkpoints | Sanitized transcript is included; checkpoint replacement is atomic and corrupt existing checkpoint data fails visibly without overwriting it. | Existing journal suite, corrupt-file preservation, sanitized checkpoint |
| Minimal driver | Proposal-only protocol/reference adapter and serializable state with stable IDs, cancellation fields and explicit context epoch on profile change. Redacted checkpoint arguments require fresh proposals; no automatic replay. Existing orchestrator remains the CLI implementation. | Five AgentDriver contract tests |

## Configuration behavior

The documented `.env.example` assignments now load from the current working directory. `.env` supports literal `KEY=value`, matching quotes, comments on their own lines and optional `export `; it does not interpolate variables or execute commands. Relative YAML/workspace/journal paths retain their existing working-directory meaning. Missing explicitly named YAML is an error. Canonical names are preferred; legacy aliases remain accepted at the lower priority above.

`max_context_tokens` and `poll_health_interval_seconds` are validated configuration values, not a newly implemented tokenizer budget or polling service. Model/engine conformance and context budgeting remain later work. `/no_think` is appended only for Qwen aliases. The public CLI entry point remains `freecompute = harness.cli.main:main`.

## Validation

Baseline: 42 existing unit tests passed before edits. Final expanded unit suite: **81 tests, all passed, no skips** on Windows / CPython 3.12.10. Original positive undo/write fixtures were updated to supply explicit approval and seal postimages; their content/result assertions were retained. No failing assertion was removed or relaxed.

Additional evidence and exact SDK invocation are in [OPENHANDS_COMPATIBILITY_SPIKE.md](OPENHANDS_COMPATIBILITY_SPIKE.md). Packaging/import and final secret scan results are recorded there. No GPU, deployed notebook, real model, tunnel, or Comfy deployment was tested.

## Remaining limits and review findings

The adversarial-reviewer passes identified atomic-write failure and Windows filename alias hazards, fixed above. The remaining verdict is **CONCERNS** for release, not blanket safety acceptance:

- **Saboteur:** concurrent processes can still race a path check/open or update the separate file/undo/checkpoint ledgers. Atomic replacement reduces partial file writes but does not provide an atomic transaction across the filesystem and JSON ledger. A crash after write and before seal leaves an unsealed snapshot requiring manual reconciliation. No durable side-effect recovery, lock manager or migration was added.
- **New Hire:** `AgentDriver` is a contract experiment, not a selectable CLI backend. Driver profile epochs signal local invalidation; they do not prove llama.cpp KV-cache invalidation. The SDK matrix deliberately separates passing characterization tests from passing adoption gates. Legacy skills wiring/provider routing and older documentation claims remain as described in the baseline audit.
- **Security Auditor:** approved shell commands execute with the user's OS authority. A working directory and command denylist are not an OS sandbox. Narrow child tool sets cannot constrain arbitrary approved shell code. Registered secret redaction and regexes are not perfect DLP; encoded/unregistered secrets, binary image contents and arbitrary backend engine logs are not comprehensively protected. Private preimage backups retain exact original bytes for restoration; they are not sanitized logs and are not encrypted. Standalone Comfy deployment authentication is not hardened by the text supervisor fix.

Raw model tool arguments remain transient inside the FreeCompute transport/orchestrator until broker validation; they are not printed/persisted unredacted. Low-level filesystem helpers are trusted host primitives; model proposals must enter through the registry/broker. Python objects are not isolation against a malicious SDK executing arbitrary Python. A future isolation backend must define that threat boundary explicitly.

Old undo ledgers are preserved, not migrated or silently cleared. Corrupt ledgers/checkpoints produce an error. Storage synchronization under OneDrive remains a risk; Stage 3 should review single-owner durable state outside the synchronized repository. Main was not edited or merged, and implementation was not pushed or deployed.

## Files changed

Compared with the documentation starting commit (including current working changes):

```text
generate_image.py
harness/cli/formatter.py
harness/cli/image.py
harness/cli/main.py
harness/config.py
harness/core/agent_driver.py
harness/core/client.py
harness/core/models.py
harness/core/orchestrator.py
harness/providers/comfyui.py
harness/security.py
harness/storage/journal.py
harness/storage/undo.py
harness/telemetry/quota_ledger.py
harness/telemetry/session_tracker.py
harness/tools/atomic.py
harness/tools/fs.py
harness/tools/registry.py
harness/tools/sandbox.py
harness/tools/terminal.py
kaggle/freecompute_dual_gpu_server.ipynb
kaggle/supervisor.py
kaggle/universal_dual_gpu_server.ipynb
knowledgebase/BUILD_VS_REUSE_DECISION.md
knowledgebase/CURRENT_ARCHITECTURE_AUDIT.md
knowledgebase/OPENHANDS_COMPATIBILITY_SPIKE.md
knowledgebase/README.md
knowledgebase/STAGE1_SAFETY_BASELINE.md
knowledgebase/V2_ROADMAP.md
pyproject.toml
tests/spike/OPENHANDS_LICENSE.txt
tests/spike/requirements-windows-py312.lock.txt
tests/spike/test_openhands_compatibility.py
tests/unit/test_agent_driver.py
tests/unit/test_cli_smoke.py
tests/unit/test_orchestrator.py
tests/unit/test_security_baseline.py
tests/unit/test_undo.py
```
