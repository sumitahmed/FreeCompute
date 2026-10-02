# Build versus reuse decision

Proposed decision, 2026-10-02; not approved. Evidence: [source research](OPEN_SOURCE_AGENT_RESEARCH.md), [pins/licenses](RESEARCH_EVIDENCE.md).

## Recommendation

Build a thin, authoritative local FreeCompute core around a replaceable `AgentDriver`. **Evaluate OpenHands software-agent SDK first**, pinned behind an optional dependency/adapter. Reuse its typed agent loop and context machinery only if the boundary tests below pass. Do not import its full hosted product or accept its default tools, delegation, confirmation, logging, or persistence behavior unchanged.

This recommendation preserves the current Python codebase and local-first architecture while avoiding a custom reimplementation of every agent loop. It requires a deliberate Python 3.12 floor decision. Integration is not proven: default `NeverConfirm`, callbacks after persistence, visualizers before persistence, transitive telemetry, and SDK state ownership are concrete risks.

If safe integration requires deep overrides or a permanent security fork, stop and evaluate **Cline SDK** for a Node/TypeScript core. Pi is the smaller TypeScript fallback when host policy ownership matters more than built-in lifecycle/cron machinery. Do not quietly implement a custom loop after the first SDK fails. A narrow custom driver is the last option after documenting why reusable candidates failed the same acceptance tests.

## Alternatives

| Option | Benefits | Cost or exclusion | Decision |
| --- | --- | --- | --- |
| Build every subsystem | Maximum interface control | Reimplements stream parsing, tools, compaction, events, model variants, delegation; larger safety burden | Reject as default |
| Fork entire Codex | Rich mature execution/client architecture | Rust fork, Responses compatibility, broad product semantics | Reference/adapt selected patterns |
| Fork OpenCode | Server architecture and current multi-agent tooling | TypeScript/Effect migration and long-term fork maintenance | Revisit only if adopting its whole product direction |
| Adopt Cline SDK | Existing host-independent loop/lifecycle/teams/cron | Stack change, package exports/stability/telemetry/dependencies | Credible second foundation |
| Adapt OpenHands SDK | Python typed loop, tools, condenser, events | Python >=3.12, dependencies and raw sink/ownership gates | First bounded evaluation |
| Use Pi packages | Smaller composable loop and RPC/session examples | TypeScript bridge/rewrite and more host features to own | Credible minimal alternative |
| Adopt Aider as product | Strong focused edit/repo workflow | General jobs/media/worker model not its core | Reuse isolated retrieval/edit ideas only |
| Adopt Goose or Continue wholesale | Existing providers/MCP/product features | Stack/scope mismatch; selected unsafe delegation behavior in Continue | Component patterns, not foundation now |

## Ownership and reuse map

| Component | Proposed owner/reuse | Integration constraint |
| --- | --- | --- |
| Agent loop, typed actions, condenser | OpenHands SDK through adapter | No direct SDK authority; every inference and tool path intercepted |
| Text HTTP protocol | Proven SDK/HTTP transport where compatible | Provider contract conformance; finish reasons, tool arguments, timeout/cancel semantics |
| MCP protocol implementation | Official MCP Python SDK, pinned | Broker authorizes exposed tools; stdio subprocess launch and network connections need grants |
| Repo symbol retrieval | Adapt Aider repo-map approach; possibly isolated code later | Exact subtree license/dependency review; no wholesale coder import |
| Editing | Preserve small local tools; adapt reviewed-diff/read-hash/line-ending patterns | Deterministic target, no ambiguous replacement or cross-file fallback |
| Permission, sandbox and secret boundary | FreeCompute | Cannot outsource to model risk scores or SDK defaults |
| Durable authority store and recovery | FreeCompute | Single authoritative schema; SDK state is internal/derived, not a competing source of truth |
| Worker registry, routing, GPU scheduler | FreeCompute | Physical resource identity and notebook lifecycle are product-specific |
| Skills parsing | Agent Skills-compatible validation; existing discovery behavior | Manifest never grants permissions; portable metadata plus namespaced extensions |
| Project knowledge promotion | FreeCompute | Reviewable proposals with evidence, provenance and scope |
| UI/API | FreeCompute clients over shared commands/events | Adapt Codex/OpenCode/Cline/Pi separation patterns; do not copy branding |
| Inference engines | External llama.cpp/vLLM/ComfyUI services | Do not reimplement generation; separate engine/model/plugin license review |
| Scheduled jobs | FreeCompute thin scheduler; adapt Cline/Goose persistence concepts | Existing generic cron parsing library, durable run IDs, no notebook keepalive automation |

## Bounded compatibility spike after approval

Use a disposable branch/worktree, pinned SDK and synthetic workspace. Begin with fake OpenAI-compatible server fixtures; only a later separately authorized run contacts an actual worker. No large model installation is needed for contract tests.

Hard acceptance criteria:

1. Route normal generation, condenser requests, child requests, and retries through one FreeCompute inference broker. No hidden calls bypass queue/privacy/budget admission.
2. Implement SDK tools as wrappers over `ToolBroker`; no default terminal/browser/delegate tool can execute outside it. Missing approval provider denies, including children and headless sessions.
3. Ensure scrubbed bytes precede **every** SDK logger, visualizer, tracer, cache, event persistence, and callback. Explicitly disable external telemetry and prove it with network-denied fixtures. A final user callback is insufficient given inspected ordering.
4. Maintain one authoritative local event/state store. Evaluate public Agent step/astep and custom storage interfaces; prove serialization/restoration of pending tool calls and stable IDs. Do not assume a user callback replaces SDK persistence.
5. Test complete/length/error/aborted responses, fragmented tools, malformed arguments, quiet-stream cancellation, and mid-tool crash. No partial call executes and no uncertain mutation auto-replays.
6. Demonstrate bounded child delegation with narrower permissions, queue admission on a single fake resource slot, and no parent/child lease deadlock.
7. Change model profile, compact context, and recover after restart with stable prompt-version metadata and an explicit cache invalidation event.
8. Record Python/package/license/installation impact and public API stability. Keep upstream changes small enough to submit and carry responsibly; do not hide a deep subclass fork behind an adapter name.

Success means proceed with that driver; failure means report the exact broken contract and evaluate Cline/Pi against equivalent fixtures. A benchmark score is not a substitute for the authority gates.

## License and maintenance policy

Keep FreeCompute's Apache-2.0 license unless the user chooses otherwise. Before actual reuse, record upstream SHA, component paths, root/subtree license, required copyright/NOTICE text, dependency licenses, modifications, and update ownership. Prefer dependency APIs over copied internals. MIT/Apache root verification supports evaluating reuse; it is not a blanket clearance for all assets or dependencies.

Treat model weights, tokenizer templates, datasets, ComfyUI custom nodes, cloud binaries, and branded UI assets separately. No upstream code was copied during this research phase. Engine upgrades and provider policies must be rechecked at implementation time because the pinned research snapshot will age.
