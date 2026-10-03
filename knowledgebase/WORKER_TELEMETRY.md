# V1 worker telemetry contract

Implemented 2026-10-04. `harness/telemetry/models.py` normalizes optional provider
observations; the Core/scheduler does not contain Kaggle/Colab deadline rules.
`WorkerTelemetry` schema 1 has `observed_at`, `metrics`, and `gpus`. Each metric
contains `value`, `status`, and `source`. Status is `observed`, `provider-reported`,
`configured`, `estimated`, `user-provided`, or `unknown`; unknown values are null.
Malformed optional metrics become unknown without making a healthy engine unusable.

Metrics cover provider/worker identity, account session age/limit/remaining,
supervisor uptime, Linux/kernel uptime, local connected uptime, GPU count,
GPU name/VRAM/utilization/temperature, CPU utilization/count, RAM used/total,
disk free/total, engine health, loaded model and active engine slots.

The Kaggle supervisor acquires `nvidia-smi`, `/proc/stat` deltas, `/proc/meminfo`,
filesystem usage and optional read-only llama-server `/slots` and `/v1/models`
samples. Linux RAM/CPU/uptime are the host/container-visible view, not a promise
about the account's allocation or cgroup limit. The first CPU delta is unknown.
An unsupported slots endpoint stays unknown; utilization never proves an idle slot.
The authenticated proxy still does not publicly expose `/slots` or execute tools.

ComfyUI translates optional `/system_stats` GPU/RAM data at its provider boundary.
Temperature, utilization, model loading and account limits stay unknown unless
reported by a compatible adapter. Its fixed workflow identity is configured, not
proof the checkpoint is loaded. Remote process argv is omitted from stored stats.
Generic OpenAI-compatible engines can be healthy while hardware/session data is
unknown. A Colab-compatible supervisor uses the same contract and a configured
`FREECOMPUTE_PROVIDER=colab`; no Colab deployment or quota API is claimed here.

## Deadlines and quota

Deadline precedence: valid runtime/provider telemetry → authoritative legacy
runtime fields → explicit worker config → unknown. `workers[].session_limit_seconds`
is an explicitly configured assumption. `session_has_no_deadline: true` declares
a persistent worker with no session deadline; it must not also have a limit.
A configured limit without an actual account session age cannot produce remaining
time. An explicit `none` limit has no countdown. There is no default 12-hour cap.

Supervisor process age and `/proc/uptime` are displayed separately. Old
`sessionAgeSource=supervisor_start_estimate` is retained as a compatibility label;
the normalized account age remains unknown. Local connected uptime measures time
since this process first observed that endpoint healthy; it is not continuous
network availability or billable GPU allocation time.

`/status` and `/workers` show sample age, mark samples older than 30 seconds stale,
and label each available metric. During an interactive model wait, a bounded
15-second optional poll displays a compact line before streamed text begins.
It does not interrupt Markdown paragraphs or approval input. Warnings at 60/30/10
minutes require a fresh sample and a reported or explicitly configured limit;
they label remaining time as sampled/estimated and warn once per threshold/task.
Polling errors never cancel inference or grant/release a scheduler lease.

Weekly account quota is **unknown** by default. `/quota <hours>` records a
user-provided dashboard observation with its timestamp; it can become stale.
The ledger's local task wall-time estimate is separate from the observed balance
and excludes idle allocation/other clients. No authoritative Kaggle or Colab
account balance API is invented.

## Tests and limits

Regression fixtures cover absent/malformed/partial data, stale samples, configured
limits, runtime precedence, unknown age, local no deadline, Colab unknown deadline,
GPU/CPU/RAM presentation and independent image routes. Supervisor/notebook health
remains authenticated. This pass uses local fixtures and static notebook checks;
new live GPU telemetry must be observed in the user's next session.

ComfyUI field definitions: [upstream API schema](https://github.com/Comfy-Org/ComfyUI/blob/master/openapi.yaml).
