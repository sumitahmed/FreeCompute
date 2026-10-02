# V1 durable inference queue and scheduler

2026-10-02. Authorized minimal backend continuation after Stage 3; no delegation,
GUI, daemon, advanced scheduling, Redis or distributed coordination.

## Planned bounded semantics

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

These are implementation targets, not test results. Deterministic multi-worker,
restart, failure, resource-conflict and CLI evidence will be recorded below.
