# Open-source agent research

Source inspection dated 2026-10-02. Exact commits, root licenses, file links, and downloaded-byte hashes are recorded in [RESEARCH_EVIDENCE.md](RESEARCH_EVIDENCE.md). Findings are source-level; no upstream runtime was installed or benchmarked. Recommendations are our architectural inferences. Root licenses were verified; reuse still needs subtree/dependency/notice review.

## Comparison

| Foundation | Loop, provider, tool architecture | State, context, client separation | FreeCompute fit and limit |
| --- | --- | --- | --- |
| Codex, Apache-2.0, Rust | Session turn loop; tool sandbox/approval orchestration; unified process execution; bounded child spawning | Compaction and rollout/state machinery; app-server protocol; skills and separate memory extension | Strong authority/process/client patterns. Current wire API requires Responses; no drop-in chat-only provider. Whole fork would be substantial. |
| OpenCode, MIT, TypeScript | Effect-based session processor, provider adapters, permission service, locked file editing, task tool | Persistent message parts, compaction, server services, skills/MCP; experimental background children | Strong server-first reference. Language/runtime change and deep internal coupling make selective adaptation more realistic than Python imports. |
| Cline SDK, Apache-2.0, TypeScript | Separate agents, llms, core packages; host hooks and approval; tool execution modes | Host-independent local/Hub lifecycle, persistence, checkpoint restore, teams, durable cron | Credible complete foundation if changing stack. Node >=22/Bun build/workspace packaging and host-policy integration need evaluation. |
| Aider, Apache-2.0, Python | Coder edit loop, model/editor configurations, structured edit formats, commands | Repo-map retrieval, history summarization, Git-oriented workflow | Useful retrieval/edit ideas. Not the general multimodal/scheduled-worker authority layer. Edit fallback can search other chat files; do not inherit that as approved-path semantics. |
| OpenHands application + software-agent SDK, MIT, Python SDK | Typed actions/observations; Agent step/astep; LLM adapters; tools, confirmation, parallel executor | Local conversation/state/event store, condenser, pause/resume-oriented APIs, model switching, delegation/MCP | Best provisional language-aligned SDK candidate. Python >=3.12, sizable dependencies, NeverConfirm default, persistence/telemetry ordering are integration blockers until addressed. |
| Continue, Apache-2.0, TypeScript | Provider abstraction, CLI permissions, subagent executor | CLI history/compaction, codebase indexing, markdown skills | Good indexing/policy references; inspected child executor temporarily installs wildcard allow. Do not reuse that delegation security behavior. |
| Goose, Apache-2.0, Rust | Provider trait, streamed agent, MCP extensions, permission inspection, subagent recipes | SQLite sessions, model configuration, context management, recipes | Mature persistence and recipe reference. Rust adoption/extension surface broad; no evidence its task parallelism accounts for our physical GPU pools. |
| Pi / pi-mono, MIT, TypeScript | Small agent-loop package, typed ai providers, AbortSignal, tool hooks | Separate agent-session/session-manager, branchable entries, compaction, RPC mode, skills/extensions | Strong small-runtime alternative. Host must add permissions, durable scheduler, and isolation. Small does not mean safe by default. |

## Codex: authority and process ownership

Inspected `core/src/session/turn.rs`, `tools/sandboxing.rs`, `unified_exec/process_manager.rs`, `tools/handlers/multi_agents_v2/spawn.rs`, `compact.rs`, `client.rs`, skills metadata loader, app-server documentation, and model-provider definition. The loop has explicit tool/runtime machinery rather than embedding execution inside a provider. Sandboxing code carries approval requirements and execution context; process management is a separate concern. Child spawning has explicit parameters and lifecycle handling, not a fictional second model call labeled “agent.”

The [provider source](https://github.com/openai/codex/blob/a20fe6335f960a350483d0079db2ec281c68202c/codex-rs/model-provider-info/src/lib.rs#L97) rejects `wire_api = "chat"`; `WireApi` has Responses. Therefore “point Codex at FreeCompute's current chat endpoint” is not a sufficient integration plan. Current [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/207bdab95010a0489e661bad8ca109c96aad46a8/tools/server/README.md) includes `/v1/responses`, translating to chat; exact streaming/tool/session behavior still requires compatibility tests against the deployed binary. Endpoint presence is not full Codex compatibility.

Adapt approval state, process ownership, and client/event separation concepts. Avoid importing its whole state model or provider assumptions. The proprietary desktop experience is not automatically covered by the open-source CLI license. The inspected memory extension entrypoint exposes memory tools but alone does not establish a promotion algorithm; FreeCompute's controlled promotion is a deliberate product policy.

## OpenCode: server services and permission-aware editing

Inspected session prompt/processor/compaction, permission evaluation, provider transport, edit/shell/task tools, server, skill and MCP modules. `processor.ts` persists distinct tool states and detects repeated identical calls, asking a `doom_loop` permission rather than looping indefinitely. `edit.ts` uses a per-resolved-file semaphore and preserves line endings/BOM; empty old text cannot replace an existing file implicitly. These are useful behaviors for Windows editing, but FreeCompute must also bind approvals to content hashes and workspace policy.

`task.ts` explicitly limits subagent depth (default one), derives child permissions, and gates background mode behind an experimental flag. This is an actual child-session mechanism. It is not proof of GPU admission control. Provider code includes SSE wrapping/abort logic; an adapter must distinguish network stream lifetime from remote request termination.

Reuse patterns for session-part events, client server separation, read-before-write editing, doom-loop stops, and child scope derivation. Do not transplant unbounded asynchronous loops as a resource scheduler. Full application adoption is a valid alternative only if the user accepts TypeScript and a larger fork surface.

## Cline: evaluate its current SDK, not only its VS Code history

The inspected tree has `@cline/agents`, `@cline/llms`, and `@cline/core`, with host-independent agent execution and separate UI hosts. `agent-runtime.ts` prepares tool calls, normalizes/validates inputs, applies hooks, and executes adjacent parallel groups while respecting sequential barriers. The OpenAI-compatible provider is a concrete candidate for open-weight inference. `local-runtime-host.ts` and persistence service own lifecycle rather than forcing every client to own the loop.

`tool-approval.ts:29-102` denies if approval IPC is not configured and denies on timeout. That specific path is better aligned with FreeCompute than an absent-callback auto-approve fallback; it is not an audit of every Cline host configuration. File-based IPC also needs ownership/security review before adoption.

Team multi-agent source includes queued async runs. Actual cron sources are under `cron/service/` and `cron/store/`: the service wires lifecycle/watcher/runner; SQLite store has leasing and global/per-spec concurrency concepts. This is a serious background-runtime reference. It still does not supply physical GPU admission or notebook policy on our behalf.

Adopting Cline would replace more of FreeCompute's runtime stack than a Python SDK adapter. It offers substantial existing lifecycle/UI/automation machinery and must remain a real alternative, not dismissed as “IDE-only.” Evaluate package maturity, supported exports, telemetry disablement, transitive licenses, packaging, and model compatibility before choosing it.

## Aider: focused coding components

`base_coder.py` separates run/send/edit behavior; model settings support different editing roles/formats. `repomap.py` uses parsed tags and ranking to select repository context. `history.py` measures tokens, summarizes older head messages, preserves a recent tail, reserves a response buffer, and recurses when needed. This is useful precedent for bounded selection rather than blindly sending the whole repo.

`editblock_coder.py:41-77` can try another file already in chat when the target replacement fails. That behavior is unsuitable for an approval tied to one reviewed path. Adopt the idea of explicit dry-run diff preview and parser tests; reject ambiguous cross-file fallback. Aider's Git/editor workflow is not FreeCompute's worker scheduler or general artifact runtime. If reusing repo-map code, isolate the component with its parser/caching dependencies and license notices rather than dragging in the full interactive coder.

## OpenHands SDK: candidate agent machinery, not delegated authority

Current OpenHands application is primarily a product host; the inspected SDK contains actual Python agent/conversation/tool code. `Agent` uses typed events, confirmation decisions, tool execution and synchronous/asynchronous steps. `ParallelToolExecutor` has bounded threads and declared-resource locks, returns results in input order, and skips pending calls on cancellation. Its locks are per instance and depend on accurate tool declarations; FreeCompute still needs cross-agent workspace locks.

`ConversationState` defaults to `NeverConfirm`; confirmation policies also include `AlwaysConfirm` and risk thresholds. Model-derived risk is not our authority decision. Custom tool executors must route every side effect through FreeCompute even if SDK policy is wrong or absent.

`LocalConversation` has persistence, state locks, pause/reject, model-switch, and streaming callbacks. Critically, around `439-469`, default persistence occurs before user callbacks, and a visualizer can run before persistence. Adding a scrubber to the last callback is therefore insufficient. A safe integration must control raw sinks upstream or avoid those SDK-owned sinks. A pinned SDK version currently requires Python >=3.12 and dependencies including LiteLLM, FastMCP, tracing packages, parsing, and image support; this is not a tiny zero-cost import.

The SDK's condenser and conversation state are reusable candidates; event-store append and custom FileStore boundaries need a spike. Delegate/terminal/MCP defaults must not bypass our broker. Do not enable SDK autonomous delegation until every model request is scheduled and every tool call centrally authorized. Reuse is worthwhile only if public interfaces achieve these boundaries without a continuing fork of deep internals.

## Continue: useful retrieval, unsafe child pattern for this product

Inspected LLM/OpenAI adapters, CLI session/compaction, permission checker/precedence, subagent executor, markdown skill loading, and codebase indexing. Permission checks begin with ask, match tool/argument patterns, and honor a dynamically disabled tool. Code indexing serializes work to avoid SQLite write conflicts. Skill loading validates frontmatter and discovers `SKILL.md` resources.

However, [the inspected child executor](https://github.com/continuedev/continue/blob/5522c6f44ca0ac3528b37244818fbfa39b5af470/extensions/cli/src/subagent/executor.ts#L78) temporarily changes shared permission state to `tool: "*", permission: "allow"`. FreeCompute must not copy this approach: children may only narrow grants, and shared global permission mutation is not per-task isolation. Use retrieval and manifest concepts, with a separate security design.

## Goose: durable sessions, MCP and recipes

Inspected agent/provider traits, extension manager, permission inspector, child handler/config, recipes, context management, and session manager. SQLite session storage uses WAL and schema management. Session records include parent, schedule, provider/model, and usage fields, keeping runtime metadata out of mere chat text. Context management understands paired tool requests/responses, which should remain paired during reduction.

Permission inspection divides approved/needs-approval/denied calls; absent matching decisions default to approval-needed in the inspected processing path. MCP extensions and parameterized recipes show a workflow layer beyond prose-only skills. Subagent execution carries cancellation and child configuration. These are patterns to adapt; external MCP annotations and model read-only judgments must not become trusted permission grants.

A whole Goose fork would add Rust and broader product/storage concerns. Recipes are a useful workflow reference, but their retries must be translated into FreeCompute's uncertain-side-effect rules.

## Pi: the smallest plausible reusable loop

The agent loop accepts a stream function, context transformation hooks, typed events, tools, and cancellation. It explicitly exits on error/aborted responses and fails tool calls in a length-truncated response instead of executing potentially incomplete arguments. `runToolCall` passes nested tool use through the same preparation/hooks pipeline. FreeCompute should adopt both invariants even if it selects a different SDK.

Coding-agent session code separates persistence, model changes, compaction, extensions, and skills. Session entries include parent IDs and model/compaction/branch records; RPC mode exposes prompt/abort/set-model/compact without forcing the interactive UI. That makes Pi a credible Node alternative if the OpenHands boundary spike fails.

Do not infer OS sandboxing or standing approval from the availability of tool hooks. Pi's minimal runtime is valuable precisely because the host can supply these policies, but that also leaves substantial FreeCompute-owned work.

## Cross-project conclusions

1. Reuse a loop/provider/context component through a replaceable adapter. Keep authorization outside every model SDK.
2. Persistent session stores and client events are runtime concerns, not formatted terminal output.
3. Compaction/repo maps are not durable project memory. None of the inspected mechanisms justifies unreviewed model rewrites of trusted knowledge.
4. Subagents need child identity, bounded depth/budget, private context, inherited restrictions, and cancellation. Thread/tool concurrency alone is not GPU scheduling.
5. SDK telemetry, caches, visualizers, MCP callbacks, plugins, and retries must all be included in the data-flow/security audit.
6. Prefer engine APIs to embedded engine code. Verified licenses: llama.cpp MIT, vLLM Apache-2.0, ComfyUI GPL license text, official MCP Python SDK MIT. Keep ComfyUI as a separately operated service; distribution or code combination requires its own license review.

Website/layout conclusions derive from these client architectures, not screenshots copied from other brands. [GUI_AND_WEBSITE_DIRECTION.md](GUI_AND_WEBSITE_DIRECTION.md) applies the shared-session/event model to FreeCompute.
