# FreeCompute

A local CLI coding agent powered by your choice of GPU inference worker.
Your PC owns files, tools, approvals, durable sessions and undo. The remote
Kaggle/local/private worker supplies **inference only**.

V1 is a **0.1.0 beta CLI candidate** pending manual acceptance. GUI is deferred.
No production release or unlimited/free GPU availability is promised.

## Install and connect

Python **3.10+**. From this checkout, in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\Activate.ps1
```

On Linux/macOS use `.venv/bin/python` and `source .venv/bin/activate`.
Default installation needs no OpenHands SDK, browser service or GUI token.
Create a private `.env`, or update your existing file:

```dotenv
FREECOMPUTE_API_KEY=your-session-api-key-from-kaggle
```

Use the same key enabled in the Kaggle notebook. `.env` and `config.yaml` are
ignored. With the installed command on PATH:

```powershell
freecompute --remote-url "PASTE-KAGGLE-URL-HERE"
```

If the URL changes while running, enter `/connect NEW-URL`. It reuses the key,
checks authenticated health/models and changes the endpoint **for this run only**.
Stale/unreachable startup leaves the prompt usable. Held/uncertain leases fence
reconnect; it never releases capacity or replays tasks.
Use `--workspace "C:\path\to\project"` for another existing project, or
`--prompt "task"` for one task. Approve each edit/command with `y`; blank/EOF denies.

## Kaggle quick start

Canonical notebook: **[kaggle/freecompute_dual_gpu_server.ipynb](kaggle/freecompute_dual_gpu_server.ipynb)**.
`universal_dual_gpu_server.ipynb` is an identical compatibility copy. Root proof/
image notebooks are historical examples, not current V1 deployments.

1. Set **GPU T4 x2**, **Internet ON**, **Persistence None**.
2. Enable private Kaggle Secret **FREECOMPUTE_API_KEY** matching local `.env`.
3. Optional: Add Input: your own private dataset from
   **[dataset_builder.ipynb](kaggle/dataset_builder.ipynb)**.
4. Run code cells **1 through 8 in heading order**. Stop on errors. Fresh-session Run All
   is safe: Cell 9 skips shutdown by default. Avoid Save & Run All for interactive use.
5. Expect Cell 6 `SUPERVISOR HEALTHY`, Cell 8 `WORKER READY FOR LOCAL ACCEPTANCE`.
   Pass Cell 7's temporary URL to the command above. Keep Kaggle running.
6. After local work ends, explicitly enable **MANUAL SHUTDOWN** in Cell 9, run it,
   then click Kaggle **Stop Session**. Do not rerun setup/Run All during local work.

Verified cached engine/libraries/GGUF skip repeated builds/downloads. Without a
cache, Cell 4 tries a checksum-pinned historical build artifact, then the official
pinned source if unavailable. Integrity/device failures stop. No public binary
release or fixed startup time is claimed. [Fast-start/provenance details](knowledgebase/KAGGLE_FAST_START.md).

[Quick Tunnels do not officially support SSE](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).
One historical session streamed; test your actual endpoint. Use a supported private
or named-tunnel route if it buffers. A ready marker alone is not inference evidence.

## Terminal commands and skills

Type `/` for the live command menu; `/mo` filters it. Arrows navigate, Enter selects,
Tab completes, Escape dismisses. Enter sends; **Alt+Enter** adds a line. History is
in memory. Supported terminals render streamed Markdown/code; dumb/redirected
terminals use plain text. Activity follows Core events; reasoning is not displayed.

| Command | Action |
| --- | --- |
| `/help`, `/status`, `/workers`, `/models` | Commands and labeled worker/hardware observations |
| `/model`, `/connect URL` | Select a configured text/code route; reconnect it |
| `/image-model`, `/connect-image URL`, `/image prompt` | Independent image route and generation |
| `/skills`, `/skill`, `/review`, `/research`, `/leetcode` | Bundled/user/project skills |
| `/sessions`, `/resume ID`, `/new` | Saved sessions and conversation control |
| `/diff`, `/undo` | Recorded change and approved sealed restore |
| `/queue`, `/cancel ID`, `/clear`, `/exit` | Queue, cancellation and prompt control |

`/help recovery` covers explicit dispatch/reconciliation. Queued work needs
`/run-next` or `/resume`; there is no inference retry daemon.
Put custom manifests in `~/.freecompute/skills` or project `skills/`; `/skills`
refreshes them. Project overrides user, which overrides bundled. Skills can narrow
scope and never bypass approval. `search_web`/`fetch_url` remain real local tools;
network/search blocking can make them fail. [CLI details](knowledgebase/V1_CLI_PRODUCT.md).

## Workers, images and telemetry

Optional registries use [config.sample.yaml](harness/config.sample.yaml).
Precedence: defaults < YAML < config-side `.env` < cwd `.env` < process environment
< CLI flags. `--remote-url` beats stale worker URLs. `api_key_env` uses the secure
config mechanism. Route changes apply to new tasks; queued tasks keep their route.

ComfyUI is image-only, with the existing fixed Qwen GGUF workflow/nodes/files.
Remote image gateways require their **own** `FREECOMPUTE_IMAGE_API_KEY` or worker
key reference. `/connect-image` never implicitly forwards the text key or changes
its route. No current authenticated image notebook or arbitrary checkpoint switching
is claimed; live image deployment remains a manual check.

`/status` reports available GPU/CPU/RAM/disk data with provenance and sample age.
Account session limits/remaining and weekly quota stay **unknown** without supported
observations/configuration. Supervisor/Linux/local connected ages are distinct.
Optional live-wait polling never grants capacity. [Telemetry contract](knowledgebase/WORKER_TELEMETRY.md).

## Safety and evidence

Edits/writes/commands/undo require explicit approval. File tools enforce workspace
and protected-path guards. **Approved commands use your host privileges, not an
OS sandbox.** Prompts, selected file contents and tool results reach the inference
host. Local journals/permissions remain local; redaction is not general DLP.

Socket closure does not confirm remote cancellation. Unknown outcomes retain
capacity across restart until approved idle reconciliation with independent evidence.
Declared 65,536-token capacity is not full input certification; prior live context
acceptance reached 9,714 actual input tokens. Stable prefixes do not guarantee KV
cache hits or TTFT. [Security](SECURITY.md) and [live evidence](knowledgebase/V1_REAL_KAGGLE_ACCEPTANCE.md).

```powershell
python -m unittest discover -s tests/unit -p "test_*.py"
python tests/security_scan.py
python tests/runtime/cli_release_acceptance.py
```

Package acceptance installs outside the repo: inference is an explicit HTTP fixture;
file edits, approvals, tests, restart/resume and undo are real local effects.
[Current readiness/manual checks](knowledgebase/V1_RELEASE_READINESS.md).
