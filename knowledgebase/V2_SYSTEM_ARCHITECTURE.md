
# V2 system architecture

## Current V1 boundary — 2026-10-03

The V1 product is CLI → Core → native agent runtime → durable queue/scheduler →
worker/model registry → llama.cpp/compatible text engines or image-only ComfyUI.
Tool authority, approvals, journals, receipts and undo stay local. The final CLI
branch `v1/cli-release` starts at accepted backend `755e944`; it includes no GUI,
HTTP API or frontend additions from the abandoned `v1/gui` experiment. GUI is
**DEFERRED / ABANDONED FOR V1**. The broader designs below remain historical
proposals, not shipped CLI features. See [V1_CLI_PRODUCT.md](V1_CLI_PRODUCT.md)
and [V1_RELEASE_READINESS.md](V1_RELEASE_READINESS.md) for current behavior/evidence.

Updated, 2026-10-02. The user authorized the narrow native driver, Stage 3 runtime and subsequently the bounded V1 engine/worker/queue backend. Broader delegation, advanced scheduling, GUI and daemon architecture below remains proposed. The pinned SDK was rejected in [FOUNDATION_DECISION.md](FOUNDATION_DECISION.md); historical Stage 3 acceptance is in [STAGE3_LOCAL_RUNTIME.md](STAGE3_LOCAL_RUNTIME.md), and current V1 evidence is in [STAGE4_ENGINE_WORKERS.md](STAGE4_ENGINE_WORKERS.md).

## Implemented Stage 3 slice

This section records the accepted Stage 3 baseline; the bounded V1 additions are
mapped separately below. Its one-allocation statements are historical to Stage 3.

The actual entry point now constructs `CoreService.from_config` and a
`harness/cli/core_client.py` presentation adapter. CoreService owns providers,
session/task state, inference and tool brokers, permission service, skill scope,
versioned SQLite, checkpoints and private snapshot references. `NativeAgentDriver`
receives only serializable state and normalized responses; it has no broker or
filesystem handle. Its only outputs are proposals and explicit outcomes.

| Production boundary | Actual path/API |
| --- | --- |
| Composition and task loop | `harness/core/service.py`: `submit`, `run`, `resume`, `cancel` |
| Sessions and idempotent submissions | `harness/core/sessions.py`: `SessionManager.submit` |
| Driver and budget | `harness/core/native_driver.py`, `harness/core/context.py` |
| One inference allocation | `harness/core/inference.py`: `infer`, quarantine, operator idle confirmation |
| Worker/engine/profile contracts | `harness/core/runtime_models.py`: `Worker`, `ModelProfile`, `EngineAdapter`, `LlamaCppEngine` |
| Approved local effects | `harness/core/tool_broker.py`, `harness/core/permissions.py`, existing `harness/tools/registry.py` and sandbox |
| Durable state and preimages | `harness/storage/runtime.py`, `harness/storage/artifacts.py` |

The current CLI uses an in-process API and sanitized ordered events. Its session
history is persisted by the core. The new database is local application data,
outside OneDrive/repository; OS ownership refuses a second core for the same
canonical workspace under the same application-data root. Legacy journals are
preserved. Legacy undo can be explicitly restored through a new durable approval.
The older `AgentOrchestrator` remains a compatibility API and does not acquire
the new runtime's SQLite/recovery guarantees.

Stage 3 uses one selected text profile and serializes text/image inference on one
local allocation. This is not a physical GPU scheduler. Interrupted transport
quarantines that allocation; remote health alone is not proof it became idle.
Context counts are labeled UTF-8 estimates; advanced compaction and verified
tokenizers/profile manifests are later work. Process restart tests are not
power-loss durability certification. No real GPU session was used.

Bounded Stage 3 acceptance passed 140 unit tests and the fresh installed CLI's
edit/test, restart/resume and undo-denial workflow. The exact 28-file phase
inventory and remaining release/worker limits are recorded in
[STAGE3_LOCAL_RUNTIME.md](STAGE3_LOCAL_RUNTIME.md#files-in-this-phase). The
subsequently authorized V1 backend adds bounded engine/worker and basic queue
contracts; evidence is in [STAGE4_ENGINE_WORKERS.md](STAGE4_ENGINE_WORKERS.md)
and [V1_SCHEDULER.md](V1_SCHEDULER.md). Broader stages require separate review.

## Implemented V1 backend slice

Core now admits tasks to the same local SQLite authority with atomic queue
submission. `WorkerRegistry` persists separate worker/profile declarations and
timestamped health; `Scheduler` enforces eligible FIFO, per-worker concurrency
and exclusive physical pool/resource claims. `InferenceBroker` records attempt,
lease and claims before calling the chosen engine. Committed responses release
capacity; unknown remote outcomes quarantine their leases across restart.
Reconnection cannot prove them idle. Explicit operator reconciliation releases
one recorded allocation without executing work.

`engines.py` and `engine_config.py` isolate llama.cpp, generic OpenAI-compatible
and the existing ComfyUI transport. Profile declarations remain model-specific,
while one model can serve multiple workers. The CLI's `/workers`, `/models`,
`/queue`, selection, cancellation and `/run-next` remain in-process Core clients.
Changing a default never rebinds existing tasks. One local approval/tool loop
remains sequential; no parallel agents or dispatcher daemon is introduced.

| Added production boundary | Path |
| --- | --- |
| Engine adapters/composition | `harness/core/engines.py`, `harness/core/engine_config.py` |
| Compatible transport | `harness/providers/openai_compatible.py`, existing `harness/core/client.py` |
| Durable declarations/health | `harness/core/workers.py`, expanded `runtime_models.py` |
| Queue/capacity/physical claims | `harness/core/scheduler.py`, expanded `inference.py` |
| Additive schema version 2 | `harness/storage/scheduler_schema.py`, expanded `runtime.py` |

Network credentials/endpoints stay outside persisted descriptors. Generic
model-list health is not GPU telemetry or tool-template certification. The
existing Comfy workflow is image only and records a local artifact witness for
result recovery; it adds no arbitrary checkpoint switching or acknowledged
remote cancellation. Pool declarations are trusted configuration and do not
coordinate other workspaces/programs. Current deterministic tests are local
fixture evidence; hardware/profile/performance acceptance remains unverified.

## Shape: modular local core, optional daemon

Start with one local Python process and explicit module boundaries. An in-process API supports CLI and tests. Later an authenticated local service exposes the same commands and events to GUI, SDK and automation. Avoid microservices, Redis, an external queue, or a vector database for the first release. Remote services perform inference only.

```mermaid
flowchart TB
  CLI[CLI] --> API[Local command and query API]
  GUI[Future GUI] --> API
  SDK[SDK and automation] --> API
  API --> Sessions[Session and task manager]
  Sessions --> Driver[Replaceable AgentDriver]
  Driver --> Context[Context and skills selection]
  Driver --> Inference[Inference broker]
  Inference --> Router[Model router and worker registry]
  Router --> Scheduler[Resource scheduler]
  Scheduler --> Engines[Engine adapters via permitted transport]
  Driver --> Tools[Local tool broker]
  Tools --> Policy[Permissions and workspace policy]
  Policy --> Exec[Filesystem and isolated process execution]
  Sessions --> Store[Local durable state and artifact store]
  Tools --> Store
  Scheduler --> Store
  Store --> Events[Ordered sanitized client events]
  Engines --> Remote[Local or remote inference workers]
```

The diagram shows the broader proposed target. Its basic registry/inference scheduler now exists in the bounded V1 slice; GUI/SDK automation, delegation and distributed scheduling remain proposed. CoreService calls brokers; the driver cannot call them. Engine adapters receive model/input/cancellation data, not tool authority. Local Python extensions and approved shell commands remain trusted-host code, not an OS sandbox.

## Contracts

| Interface | Inputs and results | Authority |
| --- | --- | --- |
| `CoreService.submit_task` | workspace ID, user request, skill/agent profile, route constraints, request ID -> task ID | Validates client identity, scope and configuration |
| `AgentDriver.advance` | task/context snapshot, normalized inference events, completed tool observations -> proposals/outcome | Produces proposals; cannot grant or execute directly |
| `InferenceBroker.generate` | typed content, model profile, prompt version, limits, cancellation -> normalized stream | Validates disclosure; obtains scheduler lease; maps provider protocol |
| `ToolBroker.propose/execute` | tool schema/version, arguments, task/agent ID, policy scope -> approval/execution/result IDs | Only local execution authority |
| `PermissionService.decide` | canonical target, diff/content hash, command/environment/network scope -> deny/ask/scoped grant | Missing interactive resolver never means allow |
| `WorkerRegistry.observe` | authenticated manifest/health with timestamps -> versioned worker observation | Claims remain untrusted measurements until validated |
| `Scheduler.acquire/release` | resource requirements, task priority, attempt ID -> fenced lease | Does not load arbitrary models merely because a request exists |
| `MemoryService.propose/promote` | evidence-backed knowledge delta -> proposal/review/version | Promotion requires trusted approval |
| `StateStore.commit` | expected revision, events and state transitions -> sequence | Single authoritative local transaction boundary |

Content uses typed text, image, video and artifact parts; tool arguments are schema-validated JSON. Adapter-specific fields remain namespaced and validated. Errors have stable codes such as `unsupported_capability`, `approval_required`, `context_overflow`, `worker_unavailable`, `auth_failed`, `cancel_unconfirmed`, `conflict`, and `outcome_unknown`, plus scrubbed descriptions.

## IDs, state and event delivery

Use distinct IDs for workspace, session, task, agent, child relation, inference attempt, engine request, resource lease, tool execution, approval, artifact, checkpoint, and schedule occurrence. Client request idempotency keys prevent duplicate task submissions; they do not promise exactly-once external side effects.

Task state: `created -> queued -> running`, with `waiting_approval`, `waiting_child`, `waiting_worker`, `paused`, and `cancel_requested` intermediate states. Terminal results are `completed`, `failed`, or `cancelled`; `outcome_unknown` requires reconciliation, not a fabricated successful result. A completed conversation does not automatically mean tests passed.

Normalized events include task transitions, model/worker selection, queue wait, lease changes, inference start/deltas/finish, tool proposal, approval request/decision, execution intent/start/result, child relation/result, context compaction, knowledge proposal/promotion, cancellation acknowledgement, and recovery conflict. Each durable event carries schema version, IDs, monotonic per-session sequence, UTC timestamp, actor, state revision and sanitized payload.

Commit critical state transitions before broadcasting them. Clients subscribe from the last sequence and receive a snapshot plus replay after reconnect. Stream deltas can be batched into bounded sanitized chunks, but message completion and tool/approval outcomes are durable. Slow subscribers must not block execution: bound buffers, coalesce deltas, and offer catch-up reads. An in-process event bus is delivery plumbing, not the durable source of truth.

## Persistence and external effects

SQLite with transactions/schema migrations is the proposed authority store for sessions, tasks, agents, attempts, approvals, schedules, events, and artifact references. Local blobs store bounded outputs and immutable snapshots with hashes; logs reference them. Keep runtime state in a per-user local application-data directory keyed by canonical workspace identity, especially for this OneDrive workspace. Do not put a live WAL database under a sync directory by default.

For a write: resolve/authorize target, obtain write ownership, compare approved content hash, persist intent and immutable preimage, apply atomic replacement, persist result/postimage hash, then publish outcome. On restart, inspect hashes and intent status. Filesystem and SQLite are not one transaction; do not promise transactional exactly-once edits. External commands and MCP actions may be unrecoverable: present uncertainty and require reconciliation before retries.

Undo is an authorized new operation with its own intent and conflict checks. A missing backup is an error, never permission to delete. Runtime state and backup retention need quota, purge, and optional encryption controls.

## Client and job lifecycle

The CLI renders shared events and resolves approvals; it does not own policy or provider construction. Closing an in-process CLI stops that process; closing a client connected to the optional daemon does not stop an authorized daemon job. Make this distinction explicit. Running two cores against one workspace requires ownership locks and fencing or refusal; SQLite alone does not stop duplicate effects.

The daemon defaults to same-user local access, OS-owned discovery/token files, restricted named pipe/Unix socket or authenticated loopback API, origin/CSRF protection, and no network listener exposed by default. Automation is another authenticated client with a narrow grant, not an approval bypass. Secret references are resolved locally and omitted from event/query payloads.

## Proposed repository structure

```text
freecompute/
  pyproject.toml
  harness/
    api/                 # commands, queries, event contracts; local service later
    core/                # sessions, tasks, agent profiles, service composition
    agents/              # AgentDriver interface; optional pinned SDK adapters
    inference/           # normalized protocols, broker, token/context accounting
    workers/             # registry, health, manifests, location adapters
    engines/             # llama.cpp, OpenAI-compatible, vLLM, ComfyUI jobs
    transports/          # direct TLS/private-network/tunnel profiles, no silent fallback
    scheduling/          # resource pools, admission, leases, persistent jobs
    permissions/         # grants, approval binding, trusted config
    tools/               # workspace fs, processes, web, MCP broker
    skills/              # discovery, manifest validation, slash parsing, workflows
    memory/              # retrieval, proposals, promotion, context integration
    storage/             # SQLite schemas, migrations, artifacts, snapshots, recovery
    telemetry/           # measurements, uncertainty and timestamps
    clients/cli/         # CLI formatting and approval UI
  workers/               # minimal remote inference-only supervisor packages
  kaggle/                # generated notebook wrappers for canonical supervisor
  skills/                # bundled portable project skills
  knowledgebase/         # design and implementation decisions
  tests/
    unit/
    contract/            # fake protocols/workers and policy boundaries
    integration/         # local crash/process/artifact/recovery tests
    acceptance/          # opt-in real worker fixtures and recorded benchmarks
  apps/                  # future GUI, after approved client API
  docs/                  # future released user/developer documentation
```

This is a target layout, not a directory creation request. Move modules only when a staged migration needs the boundary; preserve the current entry point during migration. Centralize supervisor code and generate notebooks reproducibly rather than maintaining divergent copies. Keep lightweight CLI install separate from optional SDK/image/engine deployment dependencies.

## Telemetry truth

Separate queue time, transport connection time, prefill/TTFT, decode time, tool execution, approval wait and full task elapsed. Use tokenizer/server-reported token counts; label estimates. GPU free VRAM is an observation with age, not an allocatable promise. Show worker session deadline separately from supervisor/process/Linux uptime. Local quota estimates never masquerade as provider account balance. Stable prefixes improve cache opportunity; they do not guarantee 100% KV hits or sub-second TTFT.
