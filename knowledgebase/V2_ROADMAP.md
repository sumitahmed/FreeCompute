# V2 staged roadmap and review decisions

Subsequent V1 real-acceptance preparation is authorized separately from the
bounded backend milestone below. The notebook preflight fixes and exact manual
procedure are in [V1_REAL_KAGGLE_ACCEPTANCE.md](V1_REAL_KAGGLE_ACCEPTANCE.md).
No GPU quota has been consumed in preparation; real results and GUI readiness
remain unverified until the user supplies the manually started worker endpoint.

Updated, 2026-10-02. **The user authorized Stages 1-3 and subsequently a bounded V1 backend slice: engines, worker/model registry, basic durable FIFO queue and resource accounting. Delegation, advanced memory/automation/scheduling, GUI, daemon, deployment, GPU sessions, merge and PR remain outside this milestone.** Older completion claims are historical.

## Recorded progress ? 2026-10-02

- Stage 1: focused repairs implemented on `v2/safety-and-agentdriver-spike`; [evidence and release concerns](STAGE1_SAFETY_BASELINE.md). Expanded unit suite: 81 passed. Canonical supervisor and two embedded text notebook cells were repaired and compared locally; no notebook executed.
- Stage 2: the initial 15-test characterization was preserved and checkpointed. The subsequently authorized core broker/SQLite/public SDK experiment completed actual tool round trips, four process-crash/restart cases and native child/cancellation probes. Final suites: 94 unit + 15 original SDK + 28 foundation tests passed. [Foundation decision](FOUNDATION_DECISION.md): **REJECT OpenHands 1.50.1 as the general foundation**; native child authority/store propagation and universal routing fail. Restricted adapter results are explicitly separated from adoption gates.
- Native foundation: six initial qualification tests passed at `fcef401`; [qualification record](CUSTOM_DRIVER_QUALIFICATION.md). Production core authority remains outside the replaceable driver. No Cline/Pi evaluation or deep SDK fork was started.
- Stage 3: bounded local runtime completed for review on this branch. [Runtime record](STAGE3_LOCAL_RUNTIME.md): actual CLI/CoreService, versioned SQLite/checkpoints/artifacts, scoped approvals, restart/resume, generic context budgets and one inference allocation. Final unit acceptance: 140 passed with the prior 94 tests unchanged; the installed wheel passed edit/test/resume and explicit undo preview/denial. All 44 packaged Python files matched source and the default install requires no SDK. This is local fixture evidence, not real GPU or release acceptance.
- V1 backend: bounded engine adapters, SQLite worker/profile registry, durable eligible FIFO queue, capacity/resource leases, restart/cancellation fencing and useful CLI queries are implemented. Final acceptance: **189 unit + 15 SDK + 28 foundation tests passed**; 50 packaged Python files matched source/install and the installed CLI passed edit/test, zero-replay resume, queue restart/dispatch and ComfyUI download. Exact evidence and limits are in [STAGE4_ENGINE_WORKERS.md](STAGE4_ENGINE_WORKERS.md) and [V1_SCHEDULER.md](V1_SCHEDULER.md). No real GPU, deployment, delegation, daemon or advanced scheduling was started. Stop for review.

## Sequence and evidence gates

| Stage | Scope | Acceptance gate |
| --- | --- | --- |
| 0: review | Review audit, foundation, scope, policy and language decisions | User explicitly approves architecture and next work scope |
| 1: safety/baseline | Focused current defects: fail-closed approvals/auth, protected recursive reads/snapshots, unique conflict-safe undo, redaction sinks, config precedence, Comfy health; remove unsupported claims in a later authorized docs pass | Existing suite plus targeted regressions; no permission/secret boundary bypass; notebook changes separately reviewed |
| 2: foundation spike | Pinned OpenHands SDK via replaceable driver; fake endpoint, broker tools, controlled persistence/telemetry | All hard tests in BUILD_VS_REUSE_DECISION; public interfaces sufficient; user decides foundation based on evidence |
| 3: local runtime | Shared commands/events, SQLite authority, full checkpoint/recovery, one worker/profile, CLI thin client, context budget | Approved edit/test survives reconnect/restart; uncertain effects reconciled, denial and truncation safe |
| 4: engines/workers | Minimal llama.cpp, compatible and existing ComfyUI adapters/registry implemented in V1; real pinned profile conformance remains unverified | Local fixtures now; separately authorized real engine/model/license manifests and network acceptance later |
| 5: scheduler/delegation | Minimal durable queue, capacity and physical claims implemented in V1; child budgets/grants, delegation and advanced scheduling remain proposed | Local FIFO/capacity/GPU alias/cancel/failure/restart evidence now; delegation requires separate scope |
| 6: skills/knowledge/media | Repaired portable skill commands/workflows, controlled knowledge promotion, Comfy job/artifact adapter; embeddings only if needed | Skill compatibility, protected promotion, memory provenance, job-ID correlation/auth/path/retention tests |
| 7: persistent automation | Optional daemon, approved schedules, headless grants, homelab worker lifecycle | Restart/overlap/DST/missed-run cases; no silent risky effects or notebook keepalive dependency |
| 8: GUI/docs site | Authenticated dashboard client and released documentation/landing site | Same-core approval/recovery behavior, accessibility, evidence-backed compatibility/demo/install claims |
| Later | Validated video operations, more engines, editor/desktop clients, advanced retrieval | Operation-specific model/hardware/license tests and demonstrated need |

Stages can contain bounded parallel design tasks, but dependency gates remain. Security fixes and SDK evaluation may be reviewed together; do not begin broad refactoring while current behavior is unclear. Images can move earlier if the user makes them first-release scope, without skipping authority/artifact gates. Timelines/cost estimates require the foundation spike; no invented completion dates are supplied.

## Validation strategy

Keep `python -m unittest discover -s tests/unit -p "test_*.py"` green; do not weaken expectations to force passes. Add meaningful regressions for observed failures and contract tests with deterministic fake workers. Use integration tests for crash/restart, process trees, symlinks/platform paths, stale approvals, and artifact handling. No redundant test scaffolding for documentation-only changes.

Real worker acceptance is opt-in and separately authorized: record OS/GPU/driver, engine/model/weights/template hashes and licenses, context per slot, auth scope, transport, TTFT breakdown, token usage, memory and cancellation acknowledgement. Test short/tool/long-context workloads plus mixed resource contention. Historical notebook output cannot replace a fresh release-profile check.

Before distributing, validate optional dependency installs, actual packaged CLI entry points, Windows behavior, notices/SBOM, migration/backups and security reporting. A successful source unit test does not prove the package, notebook, GUI, or hosted release.

## Migration principles

Keep the current entry point as a client facade while new boundaries stabilize. Do not rename/move everything in a single cleanup. Treat journals and runtime config as user data; read-only inspection and explicit backup/import plans precede migration. No deletion/reset or history rewriting for diagnosis.

Reproduce canonical supervisor builds into notebook wrappers with a generation check. Keep the saved proof notebook as historical evidence rather than editing its outputs to suggest current validation. Deprecate legacy config aliases visibly with clear precedence. Do not silently switch transports, workers, model weights or telemetry policy during migration.

## Risk register

| Risk | Impact | Mitigation/gate |
| --- | --- | --- |
| SDK cannot yield authority/sinks | Unsafe tools or secret persistence despite wrapper | Public-interface spike; reject deep security fork; return for user review before alternatives |
| Python 3.12 and dependencies | Install size/compatibility/regression | Optional extras, pinned lock/package verification, user decision |
| Prompt/template variance | Invalid tools, truncated context, bad output | Per-profile conformance, tokenizer budget, incomplete-call rejection |
| Dual-T4 memory/KV pressure | OOM/slow prefill under agents/media | Conservative one slot, per-device accounting, measured profiles |
| Remote disconnect/cancel ambiguity | Duplicate inference/effects or wrong capacity | IDs, lease quarantine, reconciliation, no blind side-effect retries |
| Windows process/path edge cases | Sandbox escape or lingering children | Platform acceptance; honest host-exec mode; isolation backend decision |
| Notebook policy/availability | Unavailable or impermissible deployment mode | Optional policy gate, no 24/7 dependence, persistent workers for jobs |
| SSE transport mismatch | Broken streaming/TTFT/cancellation | Verified transport matrix; Quick Tunnel excluded as default |
| Knowledge poisoning/staleness | Wrong trusted instructions/facts | Reviewed promotion, provenance, freshness, conflict/version checks |
| Sync-directory runtime database | Locking/corruption/conflicted artifacts | Per-user local runtime state, explicit export/import |
| License/model/node obligations | Distribution/use constraints | Exact component/weight/node notices review, not root-license assumption |
| Premature GUI/site | Attractive interface hides incomplete core | Shared event/permission contracts and released-evidence claims |

## Decisions requiring user input

1. **Foundation:** the user selected the qualified narrow native driver after the OpenHands rejection. Review the completed production integration and its stated limits before Stage 4 worker conformance.
2. **First-release scope:** coding/text first with image adapter after the local authority baseline, or image jobs included earlier. Video stays later.
3. **Execution mode:** approved trusted-host commands versus required isolated container/WSL execution; Windows release scope and supported OS matrix.
4. **Workers/privacy:** first supported local/private server profiles; acceptable remote data disclosure and transport; notebook modes require current provider-policy confirmation.
5. **State/knowledge:** accept runtime data outside OneDrive/repo; opt into versioned reviewed `.freecompute/knowledge`; retention/encryption preferences for private snapshots/artifacts.
6. **Autonomy:** which schedules may have standing grants, with what paths/actions/network/budgets/expiry? Default headless tasks cannot auto-approve.
7. **Client:** local browser dashboard first versus desktop or editor priority after API stabilization.

Next gate: review the bounded V1 backend and its final local test/install evidence, then separately authorize a real local/private/Kaggle acceptance profile if desired. The historical SDK experiment store remains isolated. Minimal registry/scheduler are implemented; verified hardware/model manifests, delegation, advanced scheduling, daemon, GUI and cloud sessions remain unverified or proposed. Stop at this milestone.
