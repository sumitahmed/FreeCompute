# Final V1 pre-push audit

2026-10-04. Branch: `v1/cli-release`. This pass starts at `34cca5c` and is local
only. The final handoff records the resulting HEAD, fresh package SHA256 and test
counts. No push, merge, tag, release, cloud deployment or live GPU request is part
of this audit.

## Confirmed release blocker and correction

The previous command guard searched for `format` as an arbitrary substring.
An approved `powershell -NoProfile -Command "Get-Date -Format o"` therefore never
started a subprocess: the guard rejected its harmless `-Format` argument after
Core had persisted an execution intent, and the resulting error was fenced as
`outcome_unknown`. This was reproduced against the original candidate.

The guard now distinguishes the format utility from `-Format` and Python
`format()` expressions. Actual `format`, `format.com` and `format.exe` utility
tokens, including compound commands and attached switches, remain blocked.
Known successful and unsuccessful exit codes with captured stdout/stderr retain
completed receipts. Crash, timeout, interruption and recovery logic is unchanged.

Four added unit regressions cover harmless formatting, blocked utilities,
definitive exit 0/7 receipts and resume without replay, and actual Windows
PowerShell Get-Date. The installed-package acceptance also exercises both
command outcomes and a resumed session without repeated effects.

## Verification boundaries

The complete unit suite covers shipped CLI integration, workers/model routes,
approval/security, web tools/activity, durable sessions/recovery, cancellation,
telemetry and notebook/static validation. The final repeat runs after the local
commit, from a clean checkout.

`tests/runtime/cli_release_acceptance.py` builds a fresh external source snapshot
and wheel, creates a new venv, byte-compares all 51 packaged Python files, and
launches the installed executable outside the checkout. Its inference is an
authenticated HTTP fixture. Edits, approvals, calculator tests, command exits,
diff/undo, restart/resume and queue effects are real local operations.

`cli_polish_acceptance.py` uses that installation for native PowerShell/ConPTY
palette, filtering, arrows/Enter/Tab/Escape, history, multiline input, resize and
Markdown checks. Web research parses actual fixture HTTP search/page responses
and returns them through three model turns. Image health/generation/artifact
requests use an independent authenticated fixture route. These are not live
Internet search, image model or GPU certifications.

## Telemetry and Kaggle

The normalized contract already provides optional provider/worker/model/engine
identity, health, supervisor/kernel/connection ages, GPU/VRAM/utilization/
temperature, CPU/RAM, model/slot activity and observation provenance. The first
CPU delta, unsupported slots, old supervisors and missing observations can remain
unknown. Telemetry errors do not prevent inference. Configured/runtime/manifest
limits are labeled; remaining is estimated only with a known account session
age. No global Kaggle/Colab deadline or weekly quota is invented. See
[WORKER_TELEMETRY.md](WORKER_TELEMETRY.md).

Canonical text notebook: `kaggle/freecompute_dual_gpu_server.ipynb`. Its identical
compatibility copy and the builder have cleared outputs and compiled cells.
Ordinary fresh-session Run All skips the guarded final shutdown cell.
The optional private `kaggle/dataset_builder.ipynb` assets retain pinned commit,
CUDA/build flags, engine/library SHA256 and model identity. Verified attached
assets avoid compilation/download; absence takes the pinned build/download
fallback. New CUDA builds and live notebook startup remain manual checks. See
[KAGGLE_FAST_START.md](KAGGLE_FAST_START.md).

## Publication inventory and secrets

The current tracked tree contains source, tests, public docs, package metadata,
skills, notebooks and build workflow. No GUI, scratch workspace, private dotenv,
private configuration, runtime journal, generated diagram or temporary package
directory is tracked. Existing ignored local data is preserved.

The source scanner covers releasable files and notebook sources/outputs. The
additional reachable-history audit checks credential/tunnel patterns and the
current private credential literal without printing matched values. Two matches
in old security-test blobs are synthetic keys created for their local supervisor
fixtures, not external credentials. No current credential matches were found.
Earlier commits still contain removed `.archify` metadata with machine-specific
paths; that historical metadata is disclosed, not erased through a history
rewrite. It is absent from the current public file tree.

AGENTS.md now avoids unsupported cache/latency guarantees and a fixed 12-hour
telemetry description. README already documents the actual CLI commands,
independent image route, local authority, remote prompt visibility and limits.

## Actual screenshots and final manual run

Native visual capture was unavailable after retry/reinitialization of the Windows
helper. No product screenshot was fabricated. The exact six-shot checklist,
neutral disposable workspace setup, coding task and research task are in
[docs/assets/screenshots/README.md](../docs/assets/screenshots/README.md).
Decoded ConPTY screens are test evidence rather than landing-page screenshots.

With your existing private key and a fresh URL, run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\freecompute.exe --remote-url "PASTE-CURRENT-KAGGLE-URL-HERE"
```

Then exercise `/`, `/mo`, arrows/Enter/Tab/Escape, `/skills`, `/model`, `/status`,
`/workers`, the small approved coding task, `/diff`, exit/restart and `/resume`.
If the URL changes, `/connect NEW-URL` changes only the text route. Use
`/connect-image IMAGE-URL` only with a separately configured supported image
gateway and its own key. Keep Kaggle running until manual acceptance ends.
Live image generation, revised live GPU telemetry, full 65,536-token capacity,
remote cancellation acknowledgement and universal Quick Tunnel SSE remain
unverified; the physical screenshot run is still manual.
