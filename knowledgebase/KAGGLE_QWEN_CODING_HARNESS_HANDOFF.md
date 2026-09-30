# Kaggle × Qwen Coding Harness — Complete Handoff

**Status:** Architecture / audit handoff, not implementation authorization.  
**Date:** 2026-09-27  
**Owner:** User is hands-on engineering lead and final reviewer.  
**Implementation agent:** Codex or Antigravity may inspect, propose, and implement approved, bounded changes. Its reports alone are not proof of correct behavior.

## 1. Product vision and non-negotiable goal

Build an IDE-integrated coding agent experience resembling the *interaction quality* of Codex/Claude Code: submit short questions or long-horizon tasks; see streaming responses and an honest live timeline of what the agent is doing; inspect and approve commands, edits and diffs; interrupt/resume tasks; see runtime status and quota; work on a Windows/VS Code project. **Qwen inference and expensive model compute run remotely on Kaggle's dual T4 GPUs; filesystem operations, shell commands, Git, tests, project indexing and agent/tool orchestration run locally.** The user's PC remains the authoritative workspace; never sync the whole repository by default. Optional MCP adapters may expose tools but **MCP is not the inference transport**; use an authenticated model API.

Do not make a fake chat-only interface, cosmetic progress messages, arbitrary 1K output ceiling or fixed 5-minute task limit. Do not promise that T4 hardware will generate faster than its measured limits. Make tasks *usable* with streamed partial output, bounded/cancellable requests, prompt reuse, targeted retrieval, resumable work and verifiable telemetry. Long-horizon tasks may take many model/tool turns while retaining user control.

**Separate this experiment from Successful Study Center, Panvas and other existing project repositories.** The attached screenshot is a UX reference for the activity timeline, not a request to alter the SSC project.

## 2. Established user hardware, model and real tests

- User runs Kaggle Free with a **GPU T4 ×2** notebook; each GPU advertises **15,360 MiB**, about **30 GiB combined but NOT unified VRAM**. Kaggle notebook showed approximately 30 GiB CPU RAM. The user's dashboard showed a **12-hour session cap** and roughly **30 hours of weekly GPU quota**. The account-specific quota and reset must be read from authoritative user-facing or documented provider data; do not hardcode.
- Selected model: `huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF`, checkpoint `Huihui-Qwen3.8-27B-abliterated-UD-DW-Q4_K_M.gguf`, approximately **16.55 GB decimal**. Hugging Face revision observed: `3f101cd22b7999228bbd5d79a33975414eb9758b`.
- Built `llama.cpp` **commit `2b129ccfa03aea330d2d9ac4650a10de393dbe3a`**, CUDA T4 architecture 75, using `-DGGML_CUDA_NO_VMM=ON` to avoid the Kaggle missing `CUDA::cuda_driver` CMake target. Engine binary in the live notebook session: `/kaggle/tmp/qwen38-abliterated/llama.cpp/build/bin/llama-server`.
- Model in `/kaggle/tmp/qwen38-abliterated/models/`; scratch is **ephemeral**; do not assume files survive a session restart. Original server binds to `127.0.0.1:8080`, alias `qwen3.8-27b-huihui-abliterated-q4`, `--split-mode layer --tensor-split 1,1 --n-gpu-layers 999 --parallel 1 --cache-type-k f16 --cache-type-v f16 --jinja`, conservative private test. Snapshot of uploaded proof notebook initially had **32,768** context; user's live notebook later changed it to **65,536** and ran further tests. Do not misrepresent the uploaded snapshot as already containing the latest live modifications.
- Verified by user's executed Kaggle output: 32K server healthy, simple Python code generation PASS, structured `lookup_symbol` dummy tool-call PASS (no real tool executed), 23,544-token early-fact recall PASS in 77.1 seconds.
- After changing context to **65,536**, user reported: 46,722 API-reported input tokens, correct early-fact recall `jade river 93`, **171.5 seconds**, `48K RECALL: PASS`; GPU use **9,187 / 15,360 MiB** and **10,305 / 15,360 MiB**. This verifies **one 46.7K synthetic recall task**, not full 64K codebase competency or maximum practical output. Input and output share the configured context; request output may be capped separately by `max_tokens`.
- Long coding chat: 2,334 prompt tokens (2,293 reported cached), 4,096 completion tokens, **316.5 seconds**, `finish_reason=length` (truncated). Approximate observed output speed 13 tokens/sec. A multi-page answer was requested; waiting for a non-streamed 4,096-token response made it feel unusable. The solution is **not** a blanket tiny output cap; improve streaming, task decomposition, retrieval, cache locality, cancellation and suitable hardware expectations.
- Current test notebook had no API key and permissive CORS warning but bound to localhost. **Do not expose this server publicly or to a tunnel without an authenticated, policy-compliant architecture.**
- The user has a Kaggle notebook export named `qwen3-8-27b-abliterated-q4-kaggle-dual-t4-proof.ipynb` and may attach their current updated copy to the coding agent. Ask for the actual up-to-date notebook and report if the workspace lacks them; do not reconstruct hidden cells from memory or overwrite the only working copy.

## 3. Architecture: clear ownership boundaries

```text
VS Code/IDE or terminal client (prefer an existing open-source agent UI initially)
  -> Local harness / agent controller (persistent state, tools, approvals, telemetry)
       -> files, ripgrep/code index, Git, shell/tests, editor diffs on Windows
       -> optional locally hosted MCP tool adapters, explicitly permissioned
       -> authenticated streaming model API over a permitted secure connection
            -> Kaggle gateway/process monitor -> llama-server -> Qwen on T4 x2

Persistent local store: task/event journal, checkpoints, approvals, project context,
run IDs, connection metadata (non-secret), usage estimates, resume state.
```

Never give the Kaggle notebook unbounded access to the Windows filesystem, raw workspace root or full repo. The *agent controller* is responsible for path allowlists, user approvals, command sandboxing/guardrails, diff review, secret filtering, selective upload, and mapping tool responses into Qwen's tool loop. Local repo remains the source of truth. The model can propose a tool call; only the local controller may authorize/execute it. Image viewing/generation should appear as truthful typed events when a supported local tool actually performs them; do not claim the text-only Qwen checkpoint has image capabilities.

## 4. Session/quota UX: MUST be real and honest

The panel must show **separate** timers/status for (a) Kaggle notebook/session, (b) available account GPU quota and reset, and (c) each agent task/individual tool.

1. **Notebook session:** observed session start time if available, measured connected uptime, documented/configured maximum (user's notebook shows 12h), estimated time to cap when trustworthy, last heartbeat, GPU status (both devices VRAM/utilization), model-load state and active inference. If connected mid-session and provider start time is unknown, say `session start unknown` rather than claim precise remaining hours. Model-server stop, client disconnect, and Kaggle runtime Stop Session are **different actions**.
2. **Weekly quota:** show the last authoritative quota balance, its source and `as of` timestamp; if no documented machine-readable quota API exists, use user-entered/dashboard-observed balance and mark it `last observed`, not `live`. Locally tracked run consumption is an **estimate** and excludes other notebooks unless the provider reports account-wide totals. Display refresh/reset time only when supported by account/provider data. Never silently compute `30 minus 12` as exact remaining if other usage/variable allocation exists. No fabricated quota API. Notify before expiry or user-configured remaining-quota threshold if the data permits.
3. **Task timeline:** visible real elapsed timer including idle/waiting states; phases e.g. `planning`, `reading file`, `searching repo`, `requesting model`, `streaming tokens`, `tool proposed`, `awaiting approval`, `editing file`, `running command`, `running tests`, `viewing image`, `generating image` (only if actual supported tool exists), `reviewing diff`, `completed/failed/cancelled`. Include operation target (redacted when sensitive), start/finish time, duration, concise output/error, token usage/cache if available, connection state, retry/resume events, and a user-controlled cancellation button. No invented reasoning traces and no false claims that an operation succeeded.
4. **Lifecycle actions:** Connect/disconnect to existing running model; health-check; stop model server; start/restart model where verified and permitted; possibly start/stop interactive Kaggle session *only after official capability and provider policy are proven*. A button without functioning backing action is unacceptable. If not possible, visibly distinguish a supported manual provider step from an automatic action—do not fake control.

## 5. Research foundations (inspect versions; adapt rather than blindly copy)

- **Cline** provides a VS Code coding agent with plan/act, approvals for file edits and terminal commands, MCP/plugin extensions and OpenAI-compatible custom providers. Its SDK architecture documents separation of task lifecycle, approval, execution and session state: https://github.com/cline/cline ; https://github.com/cline/cline/blob/main/sdk/ARCHITECTURE.md
- **OpenCode** offers IDE/terminal agent clients, custom model base URLs, SDK and event/plugin hooks (`tool.execute.before/after`, `file.edited`, `permission.asked/replied`, `session.status`, etc.). Explore whether reuse is preferable to implementing a clone: https://opencode.ai/docs/sdk/ ; https://opencode.ai/docs/plugins/ ; https://opencode.ai/docs/providers
- **llama.cpp server** already offers OpenAI-compatible chat/tool calls, streaming, prompt-cache reuse, `/health`, `/slots`, optional monitoring/authentication, server timeouts and slot saving. Confirm exact features in the **pinned compiled commit**, not just current master: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- **Kaggle** docs describe GPU notebook runtime caps, scratch vs saved output, account quota visibility and an experimental VS Code/Jupyter connection. Their CLI documents `kernels push`, `kernels status`, and `kernels output`; this does **not** establish control of arbitrary interactive GPU sessions or reliable account-wide remaining quota: https://www.kaggle.com/docs/notebooks ; https://www.kaggle.com/docs/efficient-gpu-usage ; https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels.md
- Kaggle CLI supports private dataset creation/versioning. Investigate storing the compiled engine and GGUF in **private** Kaggle artifacts *only after checking model license, account/storage limits, binary compatibility and build provenance*. Do not automatically upload third-party weights or assume portability between runtime images: https://github.com/Kaggle/kaggle-cli/blob/main/docs/datasets.md
- Previous chat mentioned community Kaggle-LLM repos. **Verify repository existence, code and license yourself before trusting or copying them.** Do not use unreviewed tunnel/install scripts.

## 6. Performance plan (benchmark, not promises)

Maintain a fixed reproducible benchmark set: short Q&A, short code generation, larger code patch, tool-call JSON, 8K/24K/48K prompt prefill and one long agent workflow. Log time-to-first-token, prompt token count and cache hits, prompt processing rate, output tokens/sec, wall time, GPU VRAM both devices, CPU RAM, errors, quality/tests. Keep the known-good 64K f16 KV build as control. Evaluate one change at a time (cache configuration, prompt prefix stability, streaming flush/SSE heartbeat, batch/ubatch, slot policy, optional KV quantization or speculative decoding if compatible). Don't assume a change accelerates T4 generation; revert regressions. Ensure large tasks can produce complete outputs via incremental tool turns, without an arbitrary short HTTP timeout. Full 64K context is *capacity*, not a mandate to resend 64K each turn.

Context strategy: repo map + targeted symbol/file retrieval + persistent scratch/task summaries + deterministic context selection; keep stable system/tool prefix to exploit prompt reuse; preserve relevant tool results and decision history. Keep authentic diffs/tests as evidence. Long tasks need checkpoints, cancellation and safe resume after reconnect or context compaction. No unattended retries of non-idempotent file/terminal actions.

## 7. Security and deployment constraints

- Confirm Kaggle rules and networking feasibility **before** exposing a remote inference endpoint. No claim that Cloudflare/ngrok/SSH works or is permitted until tested. If Kaggle cannot reliably or permissibly serve the remote agent, propose a compliant GPU host while retaining the same OpenAI-compatible adapter.
- Default Kaggle server loopback only. For approved remote access: authenticated and encrypted transport, per-run scoped credentials, no credentials in notebooks/repositories/logs, least-privilege gateway, origin controls and rate limits. No public unauthenticated endpoint. Validate actual auth including unauthorized requests; rotate credentials.
- Local tools scoped to approved project roots. Prevent path traversal, symlink escapes, broad uploads, secret-file reads, destructive commands and unintended network exfiltration. Show and approve risky commands, writes and Git mutations; use patch/diff review, tests and recoverable rollback.
- Durable state is stored on the Windows/local controller. Kaggle `/kaggle/tmp/` is ephemeral and must not be the only copy of task progress. Protect logs from secrets and model inputs; explicit opt-in for file upload; report outages honestly.
- Hard stop if account quota, runtime, permissions or external policies disallow a requested step. Do not bypass restrictions with hidden keep-alive traffic.

## 8. Delivery phases and user approval gates

**Phase 0 — AUDIT AND ARCHITECTURE ONLY (first agent run):** inspect the actual up-to-date notebook, installed tooling, available provider APIs and exact pinned llama.cpp flags. Verify existing tests are supported by source/output; identify gaps. Evaluate Cline vs OpenCode vs custom local service; choose *minimal viable reuse* with a reasoned decision matrix (avoid writing a new IDE extension unless necessary). Investigate Kaggle quota/session API, permissible remote networking, persistence mechanics and threat model. Produce an architecture diagram, contracts and event schema, module layout, scoped backlog, acceptance tests and a reproducible microbenchmark plan. **No code edits, packages, credential requests, external tunnels, kernel restarts or quota-consuming tests without explicit approval.**

**Phase 1 — Reproducible Kaggle brain:** clone the working notebook; pinned binary/model hashes; conditional reuse of legitimate persistent artifacts; local-only authenticated gateway stub; health and metrics; benchmark baseline; secure start/stop of **model process** only. Validate two T4s and 64K configuration with real tests. Do not break the proof notebook.

**Phase 2 — Local model connection:** prove authenticated streaming request + structured tool-call roundtrip from Windows, health, cancellation, reconnect after transient network failure. Choose only networking that is provider-compliant and verifiable.

**Phase 3 — Existing coding-agent integration:** prefer OpenCode/Cline custom OpenAI-compatible provider, then add a minimal local supervisory controller if needed. Real file read/edit, terminal/test and Git tool events; permission gates; complete task timeline and timers. Use a disposable sample repo, never SSC/Panvas by default.

**Phase 4 — Long-horizon reliability and polished UI:** checkpoints/recovery, context management, real session/quota dashboard, explicit lifecycle controls, testing of user-visible errors and offline/disconnect states, documentation and operator runbook. Support common operations without pretending unsupported backend functionality exists.

Every phase requires a written diff, tests with command/output, manual UI test checklist, security review and user's explicit approval before next phase. Build/test claims must be based on actual executed commands or user-confirmed UI tests, not agent prose.

## 9. Acceptance criteria (not negotiable)

1. On a clean permitted Kaggle session, the brain starts reproducibly with measured setup time and validated model/engine integrity. No repeated compilation if a validated reusable build is available.
2. Local client can perform short and long streamed conversations, run a real tool-call loop, cancel, reconnect and report failures without fake progress. Benchmark speed honestly.
3. A disposable local repository can be read, patched, tested and diff-reviewed under user approval; no unsolicited writes to other directories or secret uploads.
4. UI visibly reports elapsed task time and each real command/edit/test/tool event including duration and outcome; pending approvals and cancellation are genuine. No inert controls.
5. Notebook session timer, two-GPU metrics, last-seen quota (clearly timestamped/source-labelled), model-process state and client connection state remain distinguishable. When exact quota/reset/session start cannot be read, display `unknown`/`last observed`, never an invented value.
6. Persisted task journal permits restart/reconnect without duplicate destructive actions; Kaggle session expiration results in a clear recovery path.
7. Auth-negative tests, path boundary tests, secret redaction, network disconnect and error-state tests pass. Existing proof notebook stays unchanged and working.

## 10. Immediate message to the implementation agent

> Read this entire handoff and inspect the actual latest Kaggle notebook export before proposing changes. **Do Phase 0 only: research/audit, architecture, interfaces, risk register, measurable performance plan, and an incremental implementation plan. Do not edit code, install packages, launch Kaggle, run costly GPU tasks, expose a tunnel or connect to any real project directory. Preserve the known-good Qwen notebook. Investigate provider lifecycle/quota limitations instead of inventing controls. Show the proposed repository structure and acceptance tests, and stop for my approval.**

For future implementation work, user is final reviewer; agents may perform *only approved scoped tasks* and must show diffs, tests and evidence.
