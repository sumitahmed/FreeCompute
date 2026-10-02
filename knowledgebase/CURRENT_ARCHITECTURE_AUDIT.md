# Current architecture audit

Audit: 2026-10-02, baseline `ea6d39a44d40e50f2ffebc84c0fce83a198ba24b`. Source paths/line numbers below refer to that baseline. Local fixture results are in [RESEARCH_EVIDENCE.md](RESEARCH_EVIDENCE.md). No live inference service was contacted.

Subsequent authorized work: [Stage 1 fixes and remaining limits](STAGE1_SAFETY_BASELINE.md), [OpenHands spike](OPENHANDS_COMPATIBILITY_SPIKE.md). Findings below remain the historical baseline; they are not a fresh assertion that every defect is still present.

## What runs today

`freecompute` enters `harness/cli/main.py`; configuration builds a llama.cpp provider and a synchronous REPL. The REPL handles a few local slash commands, tracks an in-memory conversation, then runs `AgentOrchestrator`. The orchestrator requests streamed chat, collects tool proposals, asks the CLI for risky-action approval, executes local tools, and appends JSONL journal records. Image generation also has separate CLI/standalone entry points. Kaggle notebooks build/download models, start llama-server or ComfyUI, and expose services through notebook-created transports.

This is a coding-agent prototype with an additional image workflow. It is not a general multi-worker or multimodal agent runtime. The entire existing **42-test unit suite passes**; most transport/provider tests use mocks. Passing does not establish deployment, isolation, cancellation, recovery, or 64K performance.

## Architectural and correctness findings

| ID | Verified source or fixture | Consequence |
| --- | --- | --- |
| A01 | `cli/main.py:419-420,456-468` constructs prompt/registry without a skills manager and passes `llama_prov.client`; `core/orchestrator.py:99` calls the concrete client. `BaseProvider.stream_chat` and client streaming contracts differ. | Provider abstraction is bypassed; swapping an image or other provider into the agent loop is not supported. |
| A02 | `providers/llamacpp.py:35` returns text/tool capabilities unconditionally; `core/models.py` message content is a string. | Capabilities are declarations, not tested model/engine availability. Typed image/video input, embeddings, and routing are absent. |
| A03 | `core/prompt.py:38-45` references missing manager methods; registry skill handlers reference `list_skills`/`read_skill`, also absent. CLI manual `/review`, `/leetcode`, `/research` injection follows a separate path. | Some slash shortcuts work, but prompt integration and skill tools break when wired. README `/skill name` is not implemented as documented. `allowed_tools` is not enforced; starter skills mention `inspect_file` while actual tool is `read_file`. |
| A04 | `storage/journal.py` appends JSONL and rewrites checkpoints; orchestrator checkpoint records only `turn` and `history_len` around line 207. | No reconstructable transcript checkpoint, session resume command, atomic checkpoint, or recovery reconciler. In-memory history disappears after process exit. |
| A05 | `storage/undo.py:100` derives backup identity from path and integer seconds. Two fixture snapshots of one file collide; two undos delete the file. Ledger is popped before restore; missing backup falls into deletion around `149-151`. | Undo is not transactional. It lacks unique immutable snapshots, conflict hashes, atomic writes, and a safe failure path. |
| A06 | Registry optional undo path calls nonexistent `snapshot_pre_change`/`record_post_change`. CLI avoids this path; orchestrator snapshots separately and ignores failures. Actual fs diff is not persisted into undo metadata. | Green standalone undo tests do not prove CLI `/diff` integration or safe snapshots for every mutation. |
| A07 | Cancellation is checked while receiving stream lines; `run_command` uses blocking `subprocess.run(shell=True)`; no per-request remote cancel acknowledgement. | Silent network waits, shell children, partial tool calls, and freed GPU slots have no complete cancellation contract. Prompt/task cancellation cannot be equated with confirmed worker cancellation. |
| A08 | Client default output cap is 2,048; configured max context is not a context budget. Finish reason/length handling is incomplete; loop has a 15-turn cap without an explicit budget-exhausted outcome. `/no_think` is appended unconditionally. | Truncation or budget exhaustion may look like completion. Model-specific prompt controls leak into generic orchestration. |
| A09 | `config.py:65-70` reapplies legacy `HARNESS_*` after canonical values. Fixture confirms legacy key wins. `.env.example` timeout variable is not loaded; no dotenv loading exists. Config fallback/unknown-key behavior is permissive. | Configuration precedence and documentation disagree. Transport and health interval fields do not implement transport lifecycle/polling. |
| A10 | Quota fixture logs one hour then still reports 25 remaining. Remaining estimate uses active elapsed time without subtracting prior recorded total. Session timer uses `/proc/uptime` and a fixed 12h assumption. | Telemetry is a local estimate, not authoritative account quota or notebook session age. Task elapsed includes tools/approvals; token counter counts chunks. CamelCase banner lookups disagree with snake_case health fields. |
| A11 | `ComfyUIProvider.get_health()` passes `supervisor_uptime_seconds` to a dataclass expecting `_s`; fixture raises `TypeError`. Provider polls despite claims of WebSocket progress. Model filenames/loader nodes differ from notebook workflow. | Unified provider image health is broken; standalone image paths are distinct and do not establish provider interoperability. |
| A12 | Image WebSocket completion does not consistently correlate `prompt_id`; sync HTTP occurs inside async flow; no bounded remote cancellation; output destinations bypass the workspace policy. | Concurrent image tasks can misattribute completion. Unknown remote filenames and user output paths need artifact validation. |

## Security findings that remain present

| ID | Source/verification | Risk |
| --- | --- | --- |
| S01 | `core/orchestrator.py:164-171` approves risky tools when no callback is installed; fixture writes a temporary file. Registry executes without independent authorization. | A different client or background task can silently bypass the intended approval gate. |
| S02 | `tools/sandbox.py` exact/case-sensitive filename checks allow `.env.local` and Windows `.ENV` in fixtures. `fs.py:181` validates only search root; fixture search reads `secrets.yaml`. | Protected-file rules are bypassed through variants and recursive traversal. Per-file symlink containment is not enforced; that specific symlink scenario was inferred, not live-tested. |
| S03 | Orchestrator snapshots a raw path before registry sandbox validation; `UndoManager.record_pre_change` resolves without sandbox. Fixture snapshots an outside-workspace file. | Even a subsequently denied edit can read and persist forbidden content through undo. Restore is also an authority path. |
| S04 | `terminal.py` validates cwd, uses inherited host environment and `shell=True`, and a substring denylist. `web.py` fetches arbitrary URLs/redirects. | Cwd validation does not isolate a process. Commands can access host/network resources; web tools need explicit egress/SSRF policy. These broad escape risks are code-derived, not exercised against private data. |
| S05 | `SecretScrubber` exists, but raw model/reasoning chunks, proposal/approval text, diffs, exceptions, image paths, and journal payloads do not consistently pass through it. | Secrets can enter display or persistence even when known-key registration exists. A regex scanner cannot establish safe sinks or redact split stream chunks. |
| S06 | `kaggle/supervisor.py:30` has a predictable nonempty fallback credential; an explicitly empty environment credential makes `check_auth` accept requests. `/health` executes before auth around `135-164`; in-memory handler fixture confirms auth is skipped. | Missing-key startup is not fail-closed; public health exposes model/runtime/GPU metadata. Ordinary private localhost engine binding is not the same as protected public gateway endpoints. |
| S07 | Supervisor and notebook embedded copy proxy broadly; image notebooks tunnel ComfyUI directly without the authenticated supervisor; standalone clients provide no equivalent auth. | Security guarantees vary by entry point. Public service exposure must be reviewed as a complete surface, not only chat routing. |

## Supervisor and notebook audit

`kaggle/supervisor.py` has restart handling, but no implemented watchdog loop despite an imported threading module and watchdog field. Normal script launch does not supply a managed llama command; notebooks start a separate process. `/control/stop` is absent. Proxy read/framing, request size, concurrency, and idle-stream handling require integration testing. Linux boot uptime is not universally container/notebook allocation age.

The two text server notebooks are byte-identical, each with ten unexecuted cells and no saved output. A comment advertises pinning `2b129cc`, but installation clones upstream HEAD without checking out that commit. Dataset-first executable reuse has no complete binary/library/hash manifest. `build_universal_nb.py` differs from shipped notebooks; it cannot be assumed the canonical generator.

The embedded supervisor is a separate source string with the same auth/health concerns. Tailscale mode falls back to a public Quick Tunnel when a key is missing. Userspace networking setup is not evidence of an inbound reachable service. The chat verification cell tests plain generation rather than a real tool roundtrip. The final shutdown cell runs under “Run All,” so the documented flow terminates the services it just started.

The saved proof notebook records commit `2b129ccfa03aea330d2d9ac4650a10de393dbe3a`, two T4s, configured context **32,768**, one server slot, and a skipped long-context performance test. Its simple generation output is historical evidence. The older handoff separately records a user-reported 46,722-token recall run at a 65,536 configuration; preserve that as a user report, not as output in the shipped universal notebooks or a fresh benchmark.

Image notebooks have no saved execution outputs. Their janitor deletes by elapsed age rather than confirmed download. Source claims about hiding activity, avoiding bans, or leaving no trace are not security guarantees: hosts and transport providers may observe activity and retained data. Colab compatibility requires policy review; this phase neither ran nor endorsed unattended notebook serving.

[Cloudflare documents that Quick Tunnels do not support SSE](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/). Current FreeCompute streams SSE through that default. This is a documented compatibility concern, not a live failure reproduced here; changing the tunnel connection protocol does not remove the published limitation.

## Documentation and evidence corrections

The historical tracker/changelog's “watchdog,” “transactional undo,” “slot cancellation,” “truthful tokens/sec,” instant TTFT, and all-complete phase claims exceed inspected implementation or evidence. The tracked `.archify` diagram and browser receipts describe rendering checks at an earlier revision/path; they do not validate the runtime security or provider flow.

The security scanner returned zero matches on its 85-file scan before new docs. It searches selected patterns with broad line exemptions; it does not check runtime output sinks, token defaults, full Git history, or all secret forms. No release-safety conclusion follows from that result.

## Preserve, with clear limits

- Local execution/remote inference separation and the current Apache-2.0 project license.
- User-visible tool proposals, explicit CLI approvals, progress display, and small filesystem tools as behavior to preserve; their implementation needs stronger authority boundaries.
- Stable prompt-prefix intention, SKILL.md discovery, slash shortcut experience, local journal/undo intent, and existing tests as regression seeds.
- Health/usage models, model presets, and reproducible notebook proof provenance as inputs to a validated worker manifest, without copying unsupported guarantees.
- Separate image engine support; preserve working standalone workflow knowledge while consolidating it through one authenticated artifact/job contract later.

Fixing these defects is future authorized work. This audit changed no production source or notebooks.
