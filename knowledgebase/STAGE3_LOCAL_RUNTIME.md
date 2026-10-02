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
- Implementation, restart tests, event/approval bindings, CLI/package checks and
  final security review: pending.

## Deferred scope

No full scheduler, delegation runtime, daemon, GUI, Rust/Tauri, new remote
deployment, multi-provider concurrency, advanced compaction, cron, embeddings or
video. Trusted-host shell execution and private unencrypted snapshots retain
their documented limitations.
