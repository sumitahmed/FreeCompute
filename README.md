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
`kaggle/universal_dual_gpu_server.ipynb` is an identical compatibility copy.
The root text/image proof notebooks are historical examples.

1. Set **GPU T4 x2**, **Internet ON**, **Persistence None**. Enable Kaggle Secret
   `FREECOMPUTE_API_KEY` with the same private value as your local `.env`.
2. Optional: Add Input ? your own private assets dataset from
   `kaggle/dataset_builder.ipynb`. Cell 3 verifies engine/library and pinned GGUF
   hashes; Cell 4 verifies the engine version and both GPUs. No dataset is required.
3. Run code cells **1?8 in order**. Stop on errors. Fresh-session **Run All is safe**:
   Cell 9 skips shutdown unless you explicitly change its confirmation. Do not rerun
   setup/Run All while the CLI uses the worker. Avoid Save & Run All for interactive use.
4. Expect Cell 6 `SUPERVISOR HEALTHY` and Cell 8 `WORKER READY FOR LOCAL ACCEPTANCE`.
   Pass Cell 7's temporary URL to `freecompute --remote-url "URL"`.
5. Keep Kaggle running. After local work ends, explicitly enable **MANUAL SHUTDOWN**
   in Cell 9, run it, then click Kaggle **Stop Session**.

Cached assets avoid repeated builds/downloads. Without them, the notebook tries a
checksum-pinned historical build artifact, then the official pinned source if the
artifact is unavailable. Integrity or device failures stop deployment. There is
no claimed public binary release or guaranteed startup time. See
[fast-start/build provenance](knowledgebase/KAGGLE_FAST_START.md).

[Cloudflare documents that Quick Tunnels do not support SSE](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).
One historical session streamed; test the actual endpoint from your PC. A ready
marker or URL alone is not inference/streaming evidence. Use a supported private
or named-tunnel route if your Quick Tunnel buffers the stream.

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
existing fixed Qwen image workflow; arbitrary checkpoint/timeout switching is unsupported.
There is no current authenticated image deployment notebook. Use your own compatible
ComfyUI gateway; the historical root image notebooks are not V1 setup instructions.
Declared context and configured verification labels are not fresh measurements.

## CLI commands

| Command | Action |
| --- | --- |
| `/help` | Commands; `/help recovery` shows explicit reconciliation operations |
| `/status` | Fresh hardware/session observations with provenance; unknown values stay unknown |
| `/connect <URL>` | Reconnect the selected text worker with its existing key; refresh health/models without saving the URL |
| `/model [profile] [worker]` | Interactive text/code route selector for new tasks |
| `/connect-image <URL>` | Reconnect the selected image worker independently |
| `/image-model [profile] [worker]` | Interactive selector for configured image workflows |
| `/models`, `/workers` | Configured profiles and worker observations/held capacity |
| `/queue` | Durable queued/running/unknown requests |
| `/sessions`, `/resume <id>` | Saved sessions and receipt-based recovery; unique ID prefixes work |
| `/new` | New conversation on the next prompt |
| `/skills`, `/skill [name] [request]` | Bundled/user/project skills and interactive selection |
| `/diff`, `/undo` | Recorded diff and approved conflict-checked snapshot restoration |
| `/cancel [task-id]` | Cancel queued work; use Ctrl+C during active synchronous inference |
| `/clear`, `/exit` | Clear the terminal or leave the CLI |
| `/image <prompt>` | Configured ComfyUI image workflow |

Recovery commands include `/run-next`, `/actions`, `/reconcile`,
`/reconcile-inference`, `/quota` and the legacy `/image-server`. The CLI is
synchronous; queued work requires explicit `/run-next` or `/resume`, not a hidden
background daemon. Unknown commands never become inference requests.

Type `/` to open the command menu; `/mo` filters it immediately. Arrows navigate,
Enter selects, Tab completes, Escape dismisses. Enter sends a prompt;
**Alt+Enter** adds a line. History is kept in memory for this process. Help and
completion use the same command registry, including custom skill commands.
Supported terminals render streamed Markdown/code; redirected/dumb terminals use
plain text. Activity follows Core events; model reasoning is not displayed.

Bundled `/review`, `/research`, and `/leetcode` skills ship in the wheel.
Put user manifests in `~/.freecompute/skills` or project manifests in `skills/`;
project overrides user, which overrides bundled by name. `/skills` refreshes
those manifests. Allowed tools can narrow authority but never bypass approvals.
`search_web` and `fetch_url` execute locally through the ToolBroker, with actual
activity/receipts; network availability or search blocking can make them fail.

Text and image selection are independent. For a protected image gateway set
`FREECOMPUTE_IMAGE_API_KEY` in `.env` (or its own `workers[].api_key_env`), then use
`/connect-image URL`, `/image-model`, and `/image <prompt>`. Image reconnect reuses
that image key; it never forwards the text key implicitly. Endpoint changes are
in memory only. The existing Qwen GGUF workflow/nodes/files must exist on ComfyUI;
selecting a declared identity does not install or hot-swap a checkpoint.

`/status` shows GPU/CPU/RAM/disk and sample age when reported. Account session
age/limit/remaining and weekly quota stay unknown unless supported data or an
explicit setting exists. Supervisor/Linux/local connected ages are separate.
Optional telemetry refreshes during interactive model waits and never grants
capacity. See [telemetry sources and limits](knowledgebase/WORKER_TELEMETRY.md).

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
