# Stage 3 local runtime

## Scope and implementation record

2026-10-02: authorized after native-driver qualification. Planned production
composition is one local CoreService with a task/session manager, proposal-only
driver, inference/tool brokers, permission service, ordered events, SQLite
checkpoints and private artifact references. The CLI will consume core state and
events. This is a new production boundary, not adoption of the experiment store.

The database will live in per-user local application data, keyed by canonical
workspace identity, outside the repository/OneDrive. A workspace ownership lock
will reject concurrent cores. Legacy JSON journals and undo data will remain
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
- Restart regressions, CLI integration, package checks and final security review
  remain pending. The smoke is not full Stage 3 acceptance.

## Deferred scope

No full scheduler, delegation runtime, daemon, GUI, Rust/Tauri, new remote
deployment, multi-provider concurrency, advanced compaction, cron, embeddings or
video. Trusted-host shell execution and private unencrypted snapshots retain
their documented limitations.
