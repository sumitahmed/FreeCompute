# FreeCompute V1 CLI product

2026-10-03. Final CLI pass on local `v1/cli-release`, based on accepted backend
`755e944`. CLI → Core → native agent runtime → queue/scheduler → worker/model
registry → local/Kaggle/private inference is the V1 product. GUI is
**DEFERRED / ABANDONED FOR V1**. No frontend, browser API, daemon or subagents
are imported from the separate GUI experiment.

## Implemented

- Compact startup uses the selected Core profile/worker instead of stale legacy
  model fields. Health is the observed status, including unhealthy/unreachable;
  a successful HTTP call is not promoted to `healthy`. Context and verification
  labels remain declared/configured, not fresh certification.
- Visible text streams as Core emits it. Activity is separated from the current
  text line; raw tool JSON and model reasoning are not terminal output. Core
  reasoning events remain in the existing private runtime; no reasoning viewer
  is introduced. Terminal control characters from model/tool text are removed.
- Reading/editing/running labels follow actual execution-intent events. Waiting
  for model follows a real model-request event. Queued/waiting states follow
  Core events/results. There are no invented percentages, animations or claims
  that silence implies completion.
- Edits show replacement diffs without stripping indentation. Commands show
  their actual requested cwd and remind users they execute with local user
  privileges. Only `y`/`yes` approves; empty input, `n`, EOF, broken input and
  Ctrl+C at the approval prompt deny. Core still binds the exact arguments,
  revisions, profile/context and current file hashes before effects.
- Commands display actual exit status, elapsed time and bounded stdout/stderr
  previews; complete results remain in sealed local receipts. Exit 0 is not
  generically renamed “tests passed.” A model's final answer is displayed once.
- `--prompt` now runs a coding task rather than being silently ignored. It uses
  the same approvals and exits nonzero if the Core task did not complete.
- `/resume` and `/model` accept full IDs or a unique prefix. Ambiguous/unknown
  IDs fail without guessing. Resume uses existing Core receipts and routes;
  completed inference, effects and test commands are not replayed.
- `/undo` retains approved sealed snapshot restoration and conflict checks.
  Denial/conflict/corrupt state is surfaced without dropping the REPL or blindly
  overwriting a changed file. `/diff` refers to the workspace's latest recorded
  change, including earlier sessions.
- Missing configuration, invalid URLs/ports/YAML, offline workers and wrong keys
  produce concise guidance. Expected failures do not print tracebacks. Explicit
  `--debug` permits scrubbed error tracebacks, never a reasoning display.
- Unknown slash commands are rejected locally and never sent as model requests.
  The main help lists user commands; `/help recovery` lists actual supported
  queue/action reconciliation and legacy quota/image-endpoint operations.

## Configuration and first run

The single-worker flow uses private `.env` entries `FREECOMPUTE_REMOTE_URL`,
`FREECOMPUTE_API_KEY`, `FREECOMPUTE_MODEL_ALIAS` and optional protocol/transport
settings. `--remote-url` remains supported there. Explicit registries use
`model_profiles`, `workers`, `selected_profile` and `selected_worker` from YAML;
the packaged `harness/config.sample.yaml` declares one dual-T4 profile/worker.

Precedence: defaults < YAML < `.env` beside YAML < cwd `.env` < process environment
< CLI flags. Canonical `FREECOMPUTE_*` names beat legacy aliases in each layer.
Worker `api_key_env` now reads the same dotenv/process values without mutating
process environment or storing credentials in durable worker descriptions.
Programmatically constructed `HarnessConfig` objects still resolve references
from current process environment. The old process-only behavior in the live
acceptance ledger is historical.

Registry mode rejects single-worker `--remote-url`/`--api-key`/`--engine` flags
instead of silently ignoring them. Non-loopback text endpoints require a bearer
key. Local loopback engines may explicitly run without auth; the public Kaggle
supervisor's mandatory authentication remains unchanged. ComfyUI keeps its
existing protected-endpoint requirement and lacks a bearer transport contract.

No worker configured means setup guidance, not simulated inference or a created
tunnel. Local state uses the existing per-user runtime outside workspace/OneDrive;
`journal_dir` retains legacy quota/undo compatibility. The unused historical poll
interval remains parseable for compatibility but does not create a background
health poller. Model route selection applies to new tasks in this process;
restart defaults come from configuration. Existing queued tasks do not rebind.

## Commands

`/help`, `/status`, `/model [profile] [worker]`, `/models`, `/workers`, `/queue`,
`/sessions`, `/resume <id>`, `/new`, `/skills`, `/diff`, `/undo`,
`/cancel [task-id]`, `/clear`, `/image <prompt>`, `/exit`.

Recovery help exposes `/run-next`, `/actions`,
`/reconcile <action-id> <completed|not_executed> [sha256|absent]`,
`/reconcile-inference [lease-id]`, `/quota [hours]`, and `/image-server [url]`.
Existing `exit`/`quit`, `/quit`, `/health` and `/skills list` aliases remain.
Registered skill commands are discovered locally; unknown commands are errors.

## Cancellation and recovery

The CLI is synchronous. While it is generating, use Ctrl+C (Windows Ctrl+Break
also has a handler); `/cancel [task-id]` is available at the prompt for queued
work. Cancellation requested, local task stop, remote confirmation and remote
outcome are separate fields from Core. The CLI never promotes socket closure
to remote acknowledgement. Incomplete/unknown requests retain their resource
lease across restart, and their capacity is displayed as held.

`/run-next` or `/resume` dispatches eligible queued work; there is no daemon.
Explicit idle reconciliation requires independent engine-idle evidence and
approval. Healthy status or low GPU utilization is insufficient. Uncertain local
effects require action inspection and explicit reconciliation, not blind retry.

## Tested and unverified

The full **229-test** suite preserved all original **210** tests. The installed
wheel passed **16** explicit loopback acceptance checks with real local file/test
effects, including a 4-turn coding flow, restart/no replay, queue recovery, undo,
cross-chunk redaction and native Windows Ctrl+Break. This is deterministic model
fixture evidence, not a new GPU test. The wheel contains **46** production Python
files and the YAML sample, excluding SDK experiments and all GUI/API/test code.

The physical Ctrl+C key in the user's own terminal, visual wrapping/colors across
terminal hosts and the final real Kaggle CLI flow remain manual checks. Windows
Python 3.12 was executed; other supported Python/OS versions were not executed
in this pass. The REPL remains line based and uses ordinary terminal wrapping.
No richer editor or desktop packaging is a V1 blocker.

Earlier real Kaggle inference/tools/queue/context/cancellation/reconnect evidence
is preserved in [V1_REAL_KAGGLE_ACCEPTANCE.md](V1_REAL_KAGGLE_ACCEPTANCE.md).
Full 65,536-token input certification and remote cancellation acknowledgement
remain unavailable/unverified. Current Quick Tunnel SSE behavior must be checked
on the actual endpoint. See [V1_RELEASE_READINESS.md](V1_RELEASE_READINESS.md) for
the exact evidence, known limits and manual release gate.
