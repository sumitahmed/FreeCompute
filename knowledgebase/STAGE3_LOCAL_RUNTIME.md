# Stage 3 local runtime

## Scope and implementation record

2026-10-02: authorized after native-driver qualification. The implemented
composition is one local CoreService with a task/session manager, proposal-only
driver, inference/tool brokers, permission service, ordered events, SQLite
checkpoints and private artifact references. The CLI consumes core state and
events. This is a new production boundary, not adoption of the experiment store.

The database lives in per-user local application data, keyed by canonical
workspace identity, outside the repository/OneDrive. A workspace ownership lock
rejects concurrent cores. Legacy JSON journals and undo data remain
readable and untouched; no destructive or implicit import is authorized.

Durability must distinguish completed receipts from uncertain effects. A crash
after execution intent without a receipt becomes `outcome_unknown`; fresh IDs
must not bypass reconciliation. Restarted approvals require a fresh decision.
SQLite and external effects cannot provide exactly-once execution.

## Current evidence

- Starting checkpoint `e869f1f`, clean tree, 94 existing unit tests passed.
- Native-driver checkpoint `fcef401` pushed after 100/100 unit tests passed.
- Production code now has normalized version-1 SQLite entities, transactions,
  ordered per-session events, task checkpoints, OS workspace ownership, private
  immutable blobs, and permission records bound to revisions/profile/epoch/
  arguments/capabilities/file hashes. These live in `harness/storage/runtime.py`,
  `artifacts.py`, and `harness/core/{sessions,permissions,tool_broker}.py`.
- `harness/core/{service,inference,runtime_models}.py` compose the real runtime
  and one-allocation inference interface. Generic budgeting stays separate from
  model-family prompt policy. Startup expires approvals, fences interrupted
  effects and quarantines uncertain inference capacity.
- Manual deterministic production smoke passed: approved write, final answer,
  one completed action receipt, separately approved snapshot restoration.
- Skills now validate manifests, use protected reads, repair missing APIs and
  distinguish absent tool restrictions from an explicit empty list. Enforcement
  is in the production core, including narrowing after `read_skill`.
- Bounded Stage 3 acceptance is complete: 140 unit tests, separate process/CLI
  recovery fixtures, installed-wheel verification and the sequential adversarial
  review below. Stop for branch review; this does not authorize Stage 4 or a release.

## Production contracts and authoritative state

`CoreService.from_config` constructs the existing text/image providers. The
llama.cpp engine uses the authenticated supervisor client's normalized stream;
it does not execute tools. CoreService calls `NativeAgentDriver.advance` with a
normalized response, then admits proposals to its own broker. The production
path never imports the optional SDK or experiment store. The original proposal
seed and `AgentOrchestrator` remain compatibility code, with their legacy
journals; their callers do not gain V2 recovery merely by installing this branch.

The schema is version 1. Stable-ID entities are `workspaces`, `sessions`, `tasks`,
`agents`, `inference_attempts`, `actions`, `approvals`, `events`, `checkpoints`,
`artifacts` and `snapshots`; `commands` owns submission idempotency. Foreign keys
bind them. Sessions/tasks/actions have revisions; events have version, stable ID,
per-session sequence, revision, actor, UTC time and sanitized payload. Critical
state and its event/checkpoint share a transaction before presentation.

Task, agent and inference IDs are locally created UUIDs. An action ID is locally
derived from task ID + driver turn + provider call ID; the provider call ID never
becomes unrestricted execution authority. Reused IDs with changed arguments are
rejected. Completed and denied receipts can be replayed without running the
handler again. Denial and its receipt are committed with the approval decision.

On Windows the default location is
`%LOCALAPPDATA%\FreeCompute\workspaces\<canonical-workspace-sha256>\runtime.sqlite3`.
SQLite uses foreign keys, WAL and FULL synchronization. A held OS lock refuses
another core for that canonical workspace under the same per-user app-data
root, even when a different database directory is requested. The override is
for controlled embedding/tests; workspace/OneDrive state directories are
refused. POSIX state directories/databases use 0700/0600; Windows inherits the
local user's application-data ACL. This is not cross-user/distributed ownership.

Fresh databases are initialized transactionally. An unversioned populated or
unsupported-version database is refused with a migration message; no reset or
silent import occurs. Legacy task journals are left intact. Existing undo JSON
is read only when present; an explicitly approved legacy restore goes through
the new durable broker and then updates that legacy ledger. The existing quota
ledger location is preserved and remains a wall-time estimate, not task authority
or provider billing data.

## Recovery, approval and artifact boundaries

Before execution the broker validates schema, task capabilities, profile/epoch
and protected target paths. Approval binds action revision, task revision,
profile/context epoch, capability and argument hashes, and the target pre-hash.
Only the literal boolean `True` allows a high-risk handler. Missing, false,
stale or interrupted approval denies it. The existing registry enforces another
gate and rechecks paths/hashes after approval. Reentrant broker callbacks are
refused; concurrent calls are serialized.

After approval, immutable preimage bytes are written and hashed in private local
blobs, then referenced with stable IDs in the SQLite execution-intent commit.
The workspace write uses the existing atomic replacement/guard. Receipt,
post-hash, snapshot seal, event and checkpoint are committed together. Restore
validates the snapshot/backup/conflict before intent and checks again at the
actual restore; missing or corrupt backups cannot authorize deletion. Undo is
another core-owned task/action and requires a fresh approval. Its sanitized
preview identifies the target, restore-or-delete operation, current/original
hashes and recorded diff, including redaction of historical legacy metadata.

Restart reconstructs driver state, history, pending action identities, attempts,
approvals and receipts. Grants interrupted before intent expire and require a
fresh decision. Interrupted execution becomes `outcome_unknown`; a fresh action
ID does not bypass the workspace mutation fence. Explicit reconciliation records
an operator assertion and, for known file targets, a stable current-file hash.
That witness is not a general proof of arbitrary command effects. Reconciliation
does not itself retry a handler. SQLite and external effects are not one atomic
transaction and no exactly-once guarantee is claimed.

An inference receipt committed before driver/checkpoint admission is replayed
from SQLite. No new inference is needed for a committed final-answer receipt.
An interrupted/unconfirmed inference quarantines allocation capacity; health or
closing a local socket is not remote completion evidence. The current adapter
has no remote cancellation acknowledgement. `/reconcile-inference` requires an
explicit operator confirmation that the worker is idle.

## CLI, budgeting, workers and skills

The CLI now constructs one CoreService and renders its events through
`harness/cli/core_client.py`; it no longer owns conversation history or builds
providers/tool registries. Existing prompt/stream/approval/status/quota/skills/
diff/undo/image/model behavior is retained. New commands are `/sessions`,
`/resume <session-id>`, `/new`, `/actions`, `/reconcile <action-id>
<completed|not_executed> [sha256|absent]`, `/reconcile-inference` and `/cancel`.
Ctrl+C requests local stop. Recorded, denied, uncertain and reconciled results
have truthful presentation; a denial is not shown as success.

Events cover task/session lifecycle, model attempts/receipts/replay, actual text
and server-provided reasoning, proposals/approval/intent/receipts, context,
skills and cancellation/outcomes. The approved command result reports its actual
exit status; the core does not invent a test pass or hidden reasoning. Child
lifecycle/workflow events are future contracts, not emitted by a fake child
runtime. Current rendering is synchronous for one CLI; a slow renderer can
delay progress, while renderer exceptions do not undo committed authority.
Bounded asynchronous subscriptions are deferred to the external-client stage.

Budget accounting separates the declared profile capacity/reserved completion,
frozen system and tool prefix, history, selected context and tool results. Counts
are labeled UTF-8 bytes plus framing estimates, not verified tokenizer counts.
Oversize input stops before an inference request. Tool context results have an
explicit byte-bounded truncation envelope; the complete sanitized receipt stays
in local state. Stream output also has a byte allowance. Model length/filter
truncation, incomplete streams, malformed calls, failures and maximum turns have
distinct outcomes. No family-specific `/no_think` is inserted by the new core.
The legacy orchestrator's old Qwen policy remains historical compatibility code.
Frozen prefixes offer cache reuse opportunities without a hit-rate/TTFT promise.

Version-1 `Worker`, `ModelProfile` and `EngineAdapter` contracts record engine,
location, immutable capabilities, declared context/completion capacity, health
and timestamped resource observations. One selected text profile and one local
inference allocation are supported. Existing ComfyUI requests share that
allocation. Completed image sessions can be inspected without regeneration;
an interrupted image job is not blindly resumed through the text driver.
Provider-job/artifact reconciliation and media profile conformance remain Stage
6 work. No remote worker, physical GPU pool, dynamic scheduler or concurrent
provider execution was added.

Project/user skill discovery and project precedence remain. Stale user command
aliases disappear after an override; invalid manifests and missing capabilities
have actionable diagnostics. Absent `allowed_tools` inherits the task scope;
an explicit empty list permits no tools. Legacy `inspect_file` maps to
`read_file`. Slash invocation and successful `read_skill` narrow the actual core
task capabilities; they cannot grant approval or widen a parent task scope.
Protected/symlink reads are checked through the sandbox. Frozen session prefixes
change only with explicit new-session/profile/tool-scope epochs. There is no
workflow/delegation/cron implementation hidden inside the skill manager.

## Verification and adversarial findings

- Final full unit run: **140 passed in 22.777 seconds**, including
  all 94 previous tests unchanged. Production regressions cover 26 local-runtime,
  six native-driver, three CLI/presentation and 11 process/ownership tests.
- Historical SDK suites rerun: **15 passed in 9.806 seconds** (one deliberately
  blocked tokenizer metadata connection); **28 passed in 146.575 seconds** with
  zero external connection attempts. Their optional fixture environment and
  rejection evidence are preserved; these are not production SDK adoption tests.
- Final scanner: 139 repository files checked, zero configured secret patterns.
  `git diff --check` passed. Scanner success is not a complete DLP/release proof.
- Actual CLI fixture: approved write + real Python verification command; second
  process `/resume` issued no new model request and left action receipts unchanged.
- Real process exits: before approval, after approval, denial commit, proposal
  checkpoint, execution intent, during effect, result, inference receipt and
  final-answer receipt. Interrupted effects fenced fresh IDs; operator
  reconciliation resumed without repeating the original counter effect. A
  separate held-owner process refused a second core.
- Adversarial review found and fixed: restore validation after intent; denial
  receipt crash window; reentrant callback overwriting authority; false success
  rendering for denial; missing stream byte bound, hidden invalid-manifest
  diagnostics and an opaque undo approval preview. The enriched preview also
  scrubs historical legacy metadata at the approval sink. Regressions passed.
- Fresh Python 3.12.10 wheel: all **44** packaged `harness` Python files matched
  the source snapshot, current repository and target install byte-for-byte.
  All **36** default modules imported from that install without loading or
  requiring the optional SDK. The opt-in adapter was separately imported with
  the pinned SDK environment and zero external connection attempts.
- Actual installed `freecompute.exe`, run outside the repository: help, approved
  file write and real Python assertion command passed. A second process resumed
  with no additional chat requests and unchanged completed receipts, then showed
  the undo target/deletion preview; denying it preserved the file. Totals: two
  chat requests, two completed tool receipts and one denied undo receipt. SQLite
  integrity passed. This used only an authenticated loopback fixture, not a GPU.
- Package report: `fc-stage3-final-package-s32cz9ks/report.json` in the local
  temporary directory. Unit log: `fc-stage3-final-unit-acceptance.log` there.
  These machine-local artifacts are not committed or published.

## Files in this phase

The cumulative change from preserved Stage 2 checkpoint `e869f1f` is exactly
28 files. The existing unit tests, `kaggle/`, historical SDK fixtures and
`harness/experiments/` are unchanged in this phase. Existing automatic checkpoint
history is preserved; no reset, squash or main-branch modification is needed.

Final scope verification matched all 28 intended paths and confirmed unchanged
prior unit-test files, notebooks and SDK experiments. `git diff --check` passed.
Local and remote `main` remained `1300566dca62a0f804487e7101767e688e551184`.
The final commits and push target only `v2/safety-and-agentdriver-spike`; no merge,
PR, deployment or remote GPU session is part of this handoff.

| Group | Included paths |
| --- | --- |
| CLI (3) | `harness/cli/core_client.py`, `harness/cli/formatter.py`, `harness/cli/main.py` |
| Core (9) | `harness/core/context.py`, `inference.py`, `native_driver.py`, `permissions.py`, `prompt.py`, `runtime_models.py`, `service.py`, `sessions.py`, `tool_broker.py` |
| Skills/storage/tools (4) | `harness/skills/manager.py`, `harness/storage/artifacts.py`, `harness/storage/runtime.py`, `harness/tools/registry.py` |
| Tests/fixture documentation (6) | `tests/runtime/crash_worker.py`, `tests/runtime/README.md`, `tests/unit/test_local_runtime.py`, `test_native_driver.py`, `test_runtime_cli.py`, `test_runtime_recovery.py` |
| Knowledge base (6) | `knowledgebase/CUSTOM_DRIVER_QUALIFICATION.md`, `FOUNDATION_DECISION.md`, `README.md`, `STAGE3_LOCAL_RUNTIME.md`, `V2_ROADMAP.md`, `V2_SYSTEM_ARCHITECTURE.md` |

## Remaining debt and next gate

Trusted-host commands validate cwd but are not an OS filesystem/process sandbox;
descendant cancellation can remain unknown. Private exact preimages and sanitized
history/receipts are unencrypted local data; retention/encryption/ACL policy and
bounded receipt storage still need release decisions. There is no multi-core
fencing outside the shared per-user app-data root, no crash/power-loss storage
certification, no authenticated external API and no automatic image-job
reconciliation. Schema upgrades/import/export require a reviewed migration plan.
Advanced compaction, semantic memory, native children, schedulers and physical
GPU profile manifests remain proposed.

Next recommended bounded stage: review this branch, then separately authorize
Stage 4 engine/worker conformance with exact model/template/tokenizer manifests,
auth/stream/cancel/idle evidence and observed resource limits. Real GPU acceptance
needs its own authorization and credentials/session. Stop for review here.

## Deferred scope

No full scheduler, delegation runtime, daemon, GUI, Rust/Tauri, new remote
deployment, multi-provider concurrency, advanced compaction, cron, embeddings or
video. Trusted-host shell execution and private unencrypted snapshots retain
their documented limitations.
