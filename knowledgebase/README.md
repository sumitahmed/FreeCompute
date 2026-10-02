# FreeCompute V2 research and architecture

Research date: **2026-10-02**. Audited baseline: `main`, `ea6d39a44d40e50f2ffebc84c0fce83a198ba24b`.

**Current status:** Stage 1 safety repairs and the **REJECTED** pinned OpenHands experiment are preserved. The qualified native driver and accepted Stage 3 runtime are the baseline for the subsequently authorized minimal V1 engine/worker registry and durable queue/scheduler. That bounded backend passed **189 unit + 15 SDK + 28 foundation tests** and fresh installed-wheel acceptance (50 source/install files matched). Evidence and limits are recorded below. This milestone stops for branch review. Delegation, advanced scheduling, GUI, daemon and real GPU/deployment work remain proposed.

Read these in order:

| Document | Purpose |
| --- | --- |
| [STAGE1_SAFETY_BASELINE.md](STAGE1_SAFETY_BASELINE.md) | Implemented changes, tests and remaining safety limits |
| [OPENHANDS_COMPATIBILITY_SPIKE.md](OPENHANDS_COMPATIBILITY_SPIKE.md) | Exact SDK pin, compatibility matrix, decision and review gate |
| [FOUNDATION_DECISION.md](FOUNDATION_DECISION.md) | Historical SDK experiment/rejection and preserved evidence |
| [CUSTOM_DRIVER_QUALIFICATION.md](CUSTOM_DRIVER_QUALIFICATION.md) | Native proposal-only foundation and qualification results |
| [STAGE3_LOCAL_RUNTIME.md](STAGE3_LOCAL_RUNTIME.md) | Actual production boundaries, SQLite/recovery, CLI, tests, limitations |
| [STAGE4_ENGINE_WORKERS.md](STAGE4_ENGINE_WORKERS.md) | Minimal V1 engines, registry, CLI and current local acceptance evidence |
| [V1_SCHEDULER.md](V1_SCHEDULER.md) | Durable FIFO admission, resources, failure/restart semantics and phase inventory |
| [FREECOMPUTE_V2_VISION.md](FREECOMPUTE_V2_VISION.md) | Product boundaries, recommended direction, unresolved choices |
| [CURRENT_ARCHITECTURE_AUDIT.md](CURRENT_ARCHITECTURE_AUDIT.md) | Actual code, defects, evidence strength, components to preserve |
| [RESEARCH_EVIDENCE.md](RESEARCH_EVIDENCE.md) | Inspection coverage, test/probe results, immutable upstream source inventory |
| [OPEN_SOURCE_AGENT_RESEARCH.md](OPEN_SOURCE_AGENT_RESEARCH.md) | Source-level comparison of eight harness families and OpenHands SDK |
| [BUILD_VS_REUSE_DECISION.md](BUILD_VS_REUSE_DECISION.md) | Component reuse, integration limits, acceptance spike |
| [V2_SYSTEM_ARCHITECTURE.md](V2_SYSTEM_ARCHITECTURE.md) | Local core, contracts, state/events, repository layout |
| [PROVIDER_AND_WORKER_MODEL.md](PROVIDER_AND_WORKER_MODEL.md) | Locations, engines, transports, models, capabilities, resource pools |
| [MULTI_AGENT_ARCHITECTURE.md](MULTI_AGENT_ARCHITECTURE.md) | Bounded delegation, queues, leases, cancellation, write ownership |
| [MEMORY_AND_CONTEXT_ARCHITECTURE.md](MEMORY_AND_CONTEXT_ARCHITECTURE.md) | Durable knowledge, context selection, checkpoint/recovery semantics |
| [SKILLS_AND_WORKFLOWS.md](SKILLS_AND_WORKFLOWS.md) | Portable SKILL.md, slash commands, constrained workflows |
| [V2_SECURITY_MODEL.md](V2_SECURITY_MODEL.md) | Trust boundaries, fail-closed permissions, redaction, sandboxing |
| [GUI_AND_WEBSITE_DIRECTION.md](GUI_AND_WEBSITE_DIRECTION.md) | Client experience, product positioning, docs and installation design |
| [V2_ROADMAP.md](V2_ROADMAP.md) | Staged work, evidence gates, risk register, decisions needing input |

The older six knowledge-base documents are historical context. Their completion, safety, transport, watchdog, quota, and performance claims are not current acceptance evidence. They have a dated notice pointing here; their original bodies remain intact. In particular, reported user benchmark results must remain distinguishable from saved notebook outputs and newly reproduced results.

Evidence vocabulary throughout this set:

- **Observed:** inspected source or executed local fixture result.
- **Tested:** a specific executed check with its actual result and limits.
- **Historical:** preserved notebook output or prior user report; not rerun here.
- **Inference:** a risk deduced from code or documentation, with no live reproduction.
- **Proposed:** future behavior; not implemented or authorized.
- **Unverified:** a declaration or compatibility claim without acceptance evidence.

The implemented foundation is a **modular Python local core** with a replaceable narrow native proposal driver and minimal SQLite inference scheduler. OpenHands remains an optional historical experiment. Authoritative execution, approvals and state stay in FreeCompute. An authenticated daemon, delegation and reviewed memory services remain later stages.
