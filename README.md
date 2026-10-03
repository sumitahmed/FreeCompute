# FreeCompute

A local CLI coding agent powered by configurable inference workers. FreeCompute
owns file tools, command execution, approvals, durable sessions, diffs and undo on
your computer. A Kaggle, local or private worker supplies model inference.

V1 is a **CLI release candidate**. GUI/dashboard work is deferred and abandoned
for V1. Version `0.1.0` remains beta pending the user's final manual acceptance;
this repository does not claim a published production release.

## Install and launch

Python **3.10+** is required; this pass was executed on Windows/Python 3.12.
From a checkout, in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\freecompute.exe --help
```

Activation is optional. On macOS/Linux use `.venv/bin/python` and
`.venv/bin/freecompute`. The default installation does not require OpenHands,
Node, a browser service or a GUI token.

Create a private `.env` if it does not exist, or update your existing one:

```dotenv
FREECOMPUTE_API_KEY=your-session-api-key-from-kaggle
FREECOMPUTE_MODEL_ALIAS=qwen3.8-27b-huihui-abliterated-q4
FREECOMPUTE_TRANSPORT=cloudflare
```

Use the exact advertised model alias and the same
private bearer key enabled in the notebook. `.env` and `config.yaml` are ignored
by Git. Keep credentials out of command arguments and notebook source.
Supply the fresh Kaggle tunnel URL on each launch. When the installed CLI is on
your PATH, the command is simply:

```powershell
freecompute --remote-url "https://YOUR-KAGGLE-URL"
```

`--remote-url` overrides the selected text worker's saved URL for this run,
including a registry in `config.yaml`. The key still comes from the configured
dotenv/environment mechanism; neither the key nor this temporary URL is saved.
If the tunnel changes while the CLI is open:

```text
/connect https://YOUR-NEW-KAGGLE-URL
```

This uses the existing key, probes authenticated health/model discovery and
refreshes worker status without submitting a task. Unreachable startup remains
usable and shows reconnect guidance. Active/uncertain worker leases must be
resolved before changing their endpoint; reconnect never releases held capacity.

Choose an existing disposable project for the first test:

```powershell
.\.venv\Scripts\freecompute.exe --remote-url "https://YOUR-KAGGLE-URL" --workspace "C:\path\to\disposable-project"
```

Enter a coding request. Read each proposed edit/command and answer `y` only when
you approve it; Enter, `n`, EOF and broken input deny. `--prompt "your task"` runs
one task using the same approval flow and exits nonzero unless the task completes.
Closing the CLI does not stop a remote GPU session.

## Kaggle worker

Upload **`kaggle/freecompute_dual_gpu_server.ipynb`** from this checkout.
`kaggle/universal_dual_gpu_server.ipynb` is its synchronized wrapper. Historical
proof notebooks are evidence, not the current authenticated worker.

1. Set accelerator **GPU T4 x2**, Internet **ON**, Persistence **None**; no inputs
   or datasets are required by this notebook. Provider availability/quota varies.
2. Add and enable the private Kaggle Secret `FREECOMPUTE_API_KEY` matching your
   local key. Default Cloudflare mode does not require a Tailscale auth key.
3. Run code cells **1–8 individually and in order**. Stop on any error. **Do not
   Run All or Save & Run All**; the last code cell is guarded shutdown.
4. Cell 4 must verify the downloaded engine and both T4 GPUs, cell 6 the healthy
   supervisor, and cell 8 `WORKER READY FOR LOCAL ACCEPTANCE`. Pass cell 7's URL
   to `freecompute --remote-url "URL"` or `/connect URL`. A notebook ready marker alone does
   not prove connectivity or model inference from your computer.
5. While FreeCompute uses the worker, keep Kaggle running and do not rerun setup,
   model or transport cells. After work ends, use guarded code cell 9 and Kaggle
   **Stop Session** to end GPU allocation.

The pinned Ubuntu 22.04/SM75 engine artifact currently expires on **2026-10-10**;
on expiry its artifact identity/checksums must be refreshed before a new session.
Cloudflare Quick Tunnels have a documented SSE limitation. One historical live
session passed streaming; verify your actual endpoint rather than assuming all
Quick Tunnels will stream. See [the deployment and live evidence ledger](knowledgebase/V1_REAL_KAGGLE_ACCEPTANCE.md).

## Workers, models and configuration

For a registry with explicit resource identity, copy
[`harness/config.sample.yaml`](harness/config.sample.yaml), configure its
model/profile declarations and workspace, then run:

```powershell
.\.venv\Scripts\freecompute.exe --config config.yaml --remote-url "https://YOUR-KAGGLE-URL"
```

Precedence is defaults → YAML → `.env` beside the YAML → `.env` in the current
directory → process environment → CLI flags. `FREECOMPUTE_*` names beat legacy
`RELAYFORGE_*`/`HARNESS_*` aliases within the same layer. `api_key_env` resolves
against those dotenv files and the process environment without copying secrets
into worker declarations or durable state.

`--remote-url` overrides the selected worker's `workers[].url`, after applying
`--profile`/`--worker` selection. With no explicit selection, it targets the
first eligible text worker and selects that route. Other workers are unchanged.
Without a registry it overrides the legacy `remote_url`. Optional saved URLs
remain fallbacks; temporary URL overrides never write YAML or dotenv files.
The legacy `--api-key` and `--engine` flags remain single-worker flags; registry
protocol/key references come from `workers[].engine/api_key_env`.
`/model <profile-id> [worker-id]` changes new-task defaults for the current CLI
process. Queued tasks retain their submitted profile/worker route. Restart
defaults come from configuration, while `/resume` uses the task's recorded route.

llama.cpp supports the accepted text/tool protocol. Generic OpenAI-compatible
workers use text-only capabilities unless `code_tools` is explicitly declared
and that endpoint supports the tool protocol. ComfyUI is image-only and uses the
existing fixed workflow; arbitrary checkpoint/timeout switching is unsupported.
Declared context and configured verification labels are not fresh measurements.

## CLI commands

| Command | Action |
| --- | --- |
| `/help` | Commands; `/help recovery` shows explicit reconciliation operations |
| `/status` | Refresh health/GPU observations; label local timer/quota estimates |
| `/connect <URL>` | Reconnect the selected text worker with its existing key; refresh health/models without saving the URL |
| `/model [profile] [worker]` | Show/select the route for new tasks |
| `/models`, `/workers` | Configured profiles and worker observations/held capacity |
| `/queue` | Durable queued/running/unknown requests |
| `/sessions`, `/resume <id>` | Saved sessions and receipt-based recovery; unique ID prefixes work |
| `/new` | New conversation on the next prompt |
| `/skills` | Discovered local skills; registered skill slash commands also work |
| `/diff`, `/undo` | Recorded diff and approved conflict-checked snapshot restoration |
| `/cancel [task-id]` | Cancel queued work; use Ctrl+C during active synchronous inference |
| `/clear`, `/exit` | Clear the terminal or leave the CLI |
| `/image <prompt>` | Configured ComfyUI image workflow |

Recovery commands include `/run-next`, `/actions`, `/reconcile`,
`/reconcile-inference`, `/quota` and the legacy `/image-server`. The CLI is
synchronous; queued work requires explicit `/run-next` or `/resume`, not a hidden
background daemon. Unknown commands never become inference requests.

## Safety and limitations

The remote model can propose tools; only the local Core validates and executes
them. File tools block protected paths, traversal and symlink/reparse escapes.
Approved shell commands run with your user privileges and are **not an OS
sandbox**. Review the command and working directory before approval.

Prompts, selected file contents and tool results are sent to the inference
provider. Local tool authority, SQLite journals, receipts and snapshot artifacts
remain local. Output uses registered-secret redaction plus pattern matching;
this is not a guarantee against every unregistered secret in arbitrary text.

Cancellation distinguishes requested/local stop from remote acknowledgement.
Closing a stream does not prove that a GPU stopped. Unknown remote outcomes hold
capacity across restart until explicit operator idle reconciliation. Never
reconcile merely because utilization is low or `/health` succeeds.

Context budgets use a conservative UTF-8-byte/framing estimate. The declared
65,536-token profile has not been fully input-capacity certified. GPU availability,
quota, throughput and context behavior depend on the actual model/worker.

## Verification

```powershell
python -m unittest discover -s tests/unit -p "test_*.py"
python tests/security_scan.py
python tests/runtime/cli_release_acceptance.py
```

The last command builds a wheel from a fresh external source snapshot, installs
it in a clean environment and runs the installed CLI against explicit loopback
fixtures. Inference is deterministic test data; file edits, approvals, tests,
restart/resume and undo are real local effects. It never contacts Kaggle.

See [V1 CLI product behavior](knowledgebase/V1_CLI_PRODUCT.md),
[release-readiness evidence and manual checks](knowledgebase/V1_RELEASE_READINESS.md),
and the [historical real Kaggle acceptance](knowledgebase/V1_REAL_KAGGLE_ACCEPTANCE.md).
