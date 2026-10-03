# V1 durable inference queue and scheduler

For the live dual-T4 acceptance, `kaggle-qwen` has concurrency 1
and exclusive `gpu0` + `gpu1` in pool `kaggle-dual-t4`. The notebook startup and
Cloudflare procedure and observed support limits are in
[V1_REAL_KAGGLE_ACCEPTANCE.md](V1_REAL_KAGGLE_ACCEPTANCE.md). Real queue/resource
and safe pre-dispatch reconnect and running-cancellation cases have passed. The
live checks do not change scheduler semantics
or release quarantined leases without explicit reconciliation.

## Live observations — 2026-10-03

During a real streamed inference, one active lease held both `gpu0` and `gpu1`.
A second task stayed queued with zero inference attempts; direct scheduler
admission returned `kaggle-qwen: capacity busy`. The first task completed, both
claims were released, and `run_next()` completed the second task. The store then
had no claims and idle allocation. This tests actual network inference with
the same local Core/store, not independent workspaces or external programs.

A disposable local forwarding listener was stopped before inference dispatch.
Refresh marked the worker unreachable and the task stayed queued without an
upstream POST. Restoring the route made the worker healthy and the queued task
completed. This did not interrupt an active remote stream or restart Kaggle.
Exact measurements and remaining boundaries are in the live acceptance ledger.

Running cancellation was observed during the twelfth streamed reasoning event
of a real long-response request. The local task became `cancelled` with
`local_stop_confirmed=true`, `remote_cancel_confirmed=false` and remote outcome
`unknown`. One quarantined lease retained both GPU claims. A second task paused
without an inference attempt; closing/reopening the local Core preserved the
lease and claims, with one upstream POST total for that probe. No remote cancel
acknowledgement or automatic idle reconciliation was invented.

The first probe hit a genuine output-accounting defect before its text-only
cancel trigger. Its unknown outcome also retained both claims. The user then
reported the actual Kaggle slot as `is_processing=False`; only that concrete
idle observation supported explicit reconciliation of the exact lease. The
queued diagnostic was cancelled before dispatch, and the affected case was
retried after fixing packet-dependent text/reasoning byte accounting. The final
cancellation lease remains quarantined in the disposable acceptance store.
Successful health alone never released either unknown lease.

The four-turn real coding task also resumed from local receipts after a saved
tunnel address became unreachable and the user supplied its current address.
The approved edit and command each executed once; all three local tests passed.
The required full local suite passed **209 tests in 41.157 seconds** after the
stream-accounting fix. These results qualify the bounded backend for GUI
development, with unknown outcomes and reconciliation exposed through Core.
All live tests are complete; the user can shut down Kaggle.

2026-10-02. Authorized minimal backend continuation after Stage 3; no delegation,
GUI, daemon, advanced scheduling, Redis or distributed coordination.

## Implemented bounded semantics — Observed

- SQLite remains the local authority under the existing workspace owner lock.
  Add schema version 2 transactionally without deleting version-1 entities.
- Submission enters a durable queue. Inference turns acquire an eligible healthy
  attached worker, matching profile/engine/capabilities and any explicit route.
  FIFO applies among requests that can run; busy/unavailable requests wait.
- Worker concurrency counts active and quarantined leases. A named physical pool
  and exclusive resource IDs prevent overlap through differently named workers.
  No fractional GPU packing, VRAM optimizer, autoscaling or global discovery.
- Intent/lease/attempt are committed before network inference. A complete receipt
  releases capacity in the same transaction; unknown remote outcomes keep it.
  Restart preserves queued work and quarantines interrupted remote allocations.
- Cancellation before dispatch is definitive. Running cancellation stops locally;
  it cannot invent a server acknowledgement. Tool effects retain Stage 3 fencing.
- One local task/approval loop remains sequential. Multiple workers are routing
  options; this milestone does not add concurrent agent loops or a daemon.

## Durable admission and routing

Schema version 2 adds `model_profiles`, `workers`, `worker_profiles`,
`inference_queue`, `inference_leases` and `resource_claims`. Migration checks the
canonical workspace before transactionally creating these tables and advancing
the version. It retains version-1 tasks/actions/receipts/approvals/checkpoints,
immutable backup files and ownership lock/WAL/FULL behavior. Unsupported versions
remain refused. No destructive migration or runtime-state reset is used.

Submission writes task, idempotency command, first queue entry, events and
checkpoint atomically. Each later inference turn has one queue identity per
task/context-epoch/turn. Profile/route/capability/request fingerprints cannot be
changed under that identity. Tasks retain their profile and optional worker route
when the user's default model changes.

Before dispatch, refresh attached candidate health. An eligible worker must serve
the profile, accepted engine, required capabilities and resources; be attached
and healthy within TTL; have remaining concurrency; and have no conflicting
physical claims. Generic advertised models must contain the requested identity.
Among ready jobs, admission honors queue sequence. Busy/unhealthy heads can be
skipped so an independent healthy worker can run. Direct `run` cannot let a newer
ready task bypass an older ready task. `/run-next` dispatches one eligible task;
there is no background polling/dispatcher.

The local task/approval loop remains sequential. A second text task submitted
while it is busy stays queued with a reason; no simultaneous local tool loop is
created. The broker itself permits declared parallel slots: tests hold two actual
inferences on a two-slot worker and prove a third request waits. That is capacity
accounting, not multi-agent execution.

## Capacity and physical resources

Active **and quarantined** leases count against each worker's declared limit.
Resources are exclusive `(resource_pool, resource_id)` claims, inserted with
admission/attempt intent in one SQLite transaction. A request uses its declared
profile resources, or all worker resources when no narrower requirement is known.
SQL uniqueness prevents alias workers claiming the same physical resource.

Fixture example: `kaggle-qwen` capacity 1 uses pool `kaggle-dual-t4` resources
`gpu0` + `gpu1`. An image worker alias using `gpu0` in that same pool waits until
the lease is definitively released. An independent local pool remains eligible.
Observed free VRAM does not raise concurrency or subdivide claims. Empty resource
sets provide only worker-capacity accounting; operators must declare shared
physical pools accurately. Legacy default attachments conservatively share one
token. This is not a GPU allocator, discovery system or cross-workspace lock.

## Failure, restart and cancellation

| Event | Durable outcome / allowed next action |
| --- | --- |
| Busy, unhealthy, stale, detached or model-missing worker | Request waits; no inference or tool effect; health/reattachment can make it eligible later |
| Complete text stream or accepted image result receipt | Response and queue/lease finish recorded atomically; claims released; receipt consumed by Core |
| Request rejected before dispatch (e.g. auth rejection) | Failed receipt, confirmed not started; capacity released without claiming success |
| Connection failure, timeout, incomplete stream or local cancellation without server acknowledgement | Failed/cancelled local result; remote outcome unknown; lease quarantined, claims retained |
| Core exits during active inference | Next owner marks attempt interrupted and lease quarantined; no automatic re-dispatch or resource expiry |
| Worker reconnects and reports healthy | Can serve unrelated capacity; quarantined claims stay held |
| Explicit queued task cancellation | Task/driver/event/checkpoint and queue cancellation persist; no engine call |
| Active cancellation | Durable request plus local token/socket stop; no invented remote acknowledgement; late cancel cannot overwrite completed task |
| Complete receipt saved before Core finishes task | Restart consumes text/error receipt or validated image witness; no repeat network inference |
| Image file missing/changed or no witness | Fail closed for inspection; do not regenerate |
| Unknown local command/file effect | Existing Stage 3 reconciliation fences remain; no blind side-effect replay |

Operator idle confirmation must return literal `True`. A single unknown lease may
use the shorthand; multiple unknown leases require exact lease IDs and separate
confirmations tied to recorded worker/profile/resources. Reconciliation records
actor/events/history and releases only that lease; it does not run anything.
Unfinished jobs become queued; terminal jobs become cancelled. A migrated v1
unknown allocation has no trustworthy pool identity and fences all new admission
until explicit idle confirmation. No automatic retries or timeout-based release.

## Test and review evidence

**Tested locally:** 31 focused worker/scheduler tests and 12 authenticated engine/
actual-CLI tests passed. Three migration tests verify populated v1 data plus undo
preimages survive, foreign workspace refusal precedes migration, and a migration
collision rolls back without altering the old version/rows. Three new process
tests use `os._exit(73)` and a fresh owner process: FIFO drains exactly once,
queued cancellation stays cancelled, and active inference retains both GPU
claims without retry until explicit reconciliation. Final aggregate evidence is
recorded in [STAGE4_ENGINE_WORKERS.md](STAGE4_ENGINE_WORKERS.md).

Bug fixes found by sequential adversarial review include atomic submission,
admission-engine capture, per-task route selection, terminal cancel protection,
and receipt consumption after a crash. Health-only release, TTL-based remote
lease expiry, automatic worker discovery, GPU packing, scheduling priorities,
fairness, Redis, leader election and a background daemon were rejected as
unnecessary or unsafe for this milestone. They are not implemented features.

**Unverified:** full-context/tokenizer/profile conformance, external process
resource fencing, power-loss durability and cross-machine coordination. Real
text/read-tool inference and one-store both-GPU queuing now have live evidence;
that does not promote every deterministic case to real-worker certification.
**Historical:** Kaggle benchmarks and earlier Stage 1-3 acceptance remain dated
evidence, not newly reproduced hardware results.

## Historical files in the 2026-10-02 phase (relative to aa15fc9)

Production changes (15):

- `harness/config.py`
- `harness/cli/core_client.py`, `harness/cli/main.py`
- `harness/core/client.py`, `harness/core/runtime_models.py`
- `harness/core/engines.py`, `harness/core/engine_config.py`
- `harness/core/workers.py`, `harness/core/scheduler.py`
- `harness/core/inference.py`, `harness/core/service.py`, `harness/core/sessions.py`
- `harness/providers/openai_compatible.py`
- `harness/storage/runtime.py`, `harness/storage/scheduler_schema.py`

New tests and fixture documentation (6):

- `tests/unit/test_workers_scheduler.py`
- `tests/unit/test_engine_workers_cli.py`
- `tests/unit/test_scheduler_migration.py`
- `tests/unit/test_worker_queue_recovery.py`
- `tests/runtime/worker_queue_process.py`, `tests/runtime/README.md`

Knowledge base (5): `STAGE4_ENGINE_WORKERS.md`, `V1_SCHEDULER.md`,
`V2_SYSTEM_ARCHITECTURE.md`, `V2_ROADMAP.md`, `README.md`.
All original unit test files, historical SDK experiment/foundation fixtures and
Kaggle notebooks/supervisor are unchanged from the accepted Stage 3 checkpoint.
