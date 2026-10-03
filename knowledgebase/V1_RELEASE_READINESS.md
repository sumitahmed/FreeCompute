# FreeCompute V1 CLI release readiness

## Current final CLI candidate - 2026-10-04

The final terminal/product/telemetry pass is implemented locally on
`v1/cli-release`, continuing from `5617ab6f1fc8c9f73816cae35ed837750a14375a`.
This is a **beta candidate for the user's manual test**, not a published release.
The earlier 2026-10-03 section below is historical evidence. It does not describe
today's terminal library, telemetry, notebook fast path or current test count.
GUI remains deferred. No push, merge, tag, release or deployment was performed.

### Fresh verified evidence

| Check | Result |
| --- | --- |
| Full unit suite | **285 passed in 116.888s**; original 240 tests preserved; 45 new terminal/assets/web/image/telemetry regressions |
| Wheel package acceptance | **21 passed**, running the installed console entrypoint outside the repo in a fresh venv |
| Packaged runtime | **51 Python files** byte-matched to source; configuration sample and three bundled skill manifests present; no experiments, GUI/API/tests or private dotenv |
| Windows interactive acceptance | **5 additional checks passed**, actual installed `freecompute.exe` launched by PowerShell through native ConPTY; decoded terminal screens inspected |
| Keyboard/menu | Immediate `/` palette with descriptions; `/mo` filtering; arrows/Enter, fast Tab, Escape; text/image selectors from actual registry; history; Alt+Enter multiline; 120-to-90-column resize |
| Prompt Ctrl+C | Clears pending input and leaves the CLI usable; active-task cancellation and approval denial remain independently tested |
| Stream/Markdown | Rendered heading, bold and fenced Python visible before deliberately held HTTP fixture completion; no broken ANSI fragments or hidden reasoning |
| Local coding effects | Real read, proposed edit, interactive approval, applied change, approved real unittest command, result inspection and final answer; two calculator tests passed |
| Durable state | Diff, restart/resume, completed effects without replay, sealed undo preview/denial and later approved restore; queue and unknown-outcome fences preserved |
| Text reconnect | Authenticated health/models; fresh URL overrides expired HTTP 530 config; wrong URL/key nonfatal; temporary URLs not written to config |
| Independent images | Separate key/HTTP endpoint; actual authenticated health, queued workflow and fixture artifact download; text request counts/routes unchanged by image connection/generation |
| Skills/web | Installed bundled `/review`, `/research`, `/leetcode` and actual project skill; `/research` performs real HTTP fixture search/page parsing through ToolBroker and three SSE model turns with visible search/fetch activity |
| Telemetry | Generic GPU/CPU/RAM/disk/session provenance; partial/malformed metrics, stale observations, runtime/manifest/config precedence, no default deadline/quota, optional telemetry failure without inference failure |
| Kaggle notebook | Canonical server and identical compatibility copy compile; builder compiles; outputs cleared; shutdown guard skips ordinary fresh-session Run All |
| Fast assets | Executed cache detection, complete library/model hashes and pin/version checks with local files/fakes; incompatible/tampered/path-invalid assets rejected; unavailable artifact takes pinned-source fallback |

All inference in **this pass** used explicit authenticated loopback fixtures.
No current Kaggle session was restarted, no new model/GPU request was made and
no GPU quota was consumed. Earlier real dual-T4 evidence is retained in
[V1_REAL_KAGGLE_ACCEPTANCE.md](V1_REAL_KAGGLE_ACCEPTANCE.md), including actual
inference/tool cycles, streaming and context escalation to 9,714 measured input
tokens. Fixtures are not new live model or image-generation certification.

The repeatable commands are in [tests/runtime/README.md](../tests/runtime/README.md).
Package scripts print external evidence directories holding `acceptance.json`,
transcripts and decoded `screens.json`. The final wheel's runtime is byte-identical
to the accepted wheel; its last rebuild corrects README metadata only.

### Product and public tree

- `prompt-toolkit>=3.0.48,<4` and `rich>=13.9,<15` are the two new direct product
  dependencies. `pywinpty` and `pyte` are optional acceptance-runner dependencies,
  not shipped requirements. No product dependency was removed.
- One command registry supplies help, aliases, completion and custom skill commands.
  `/model` switches text routes; `/image-model` switches only configured image routes.
  New tasks use the selection; saved queued tasks retain their original route.
- The canonical text notebook is `kaggle/freecompute_dual_gpu_server.ipynb`;
  `universal_dual_gpu_server.ipynb` is an identical compatibility copy.
  `dataset_builder.ipynb` is the optional private-dataset fast-start helper.
  Root text proof/image notebooks are clearly historical. No current authenticated
  V1 image notebook or arbitrary image-checkpoint switching is claimed.
- The old standalone image launchers now enter the Core-owned workflow. Historical
  prototype classes remain for compatibility/security regression tests.
- Generated `.archify` rendering artifacts and obsolete notebook generator scripts
  are removed from the tracked public tree and ignored locally. Existing local
  files and Git history are preserved. GUI is excluded; no frontend was imported.
- README, security/contribution/changelog/config-example/package metadata and
  knowledgebase links now describe the actual beta CLI and its limitations.
  Final secret/path scans and publication file inventory are recorded separately.

See [V1_CLI_PRODUCT.md](V1_CLI_PRODUCT.md), [WORKER_TELEMETRY.md](WORKER_TELEMETRY.md)
and [KAGGLE_FAST_START.md](KAGGLE_FAST_START.md) for exact contracts/procedures.

### Known limits and final manual test

The actual new Kaggle endpoint, revised CUDA builder/cache deployment, live image
gateway and the user's physical terminal fonts/wrapping remain manual checks.
ConPTY/PowerShell keyboard and screen behavior was executed; a physical Windows
Terminal screenshot is not claimed. Other OS/Python versions were not executed.
No full 65,536-token input certification or remote cancellation acknowledgement
was added. Quick Tunnel SSE is not officially supported; earlier streaming is
historical endpoint-specific evidence. Unknown leases still require independent
idle evidence and explicit reconciliation. Account session age/deadline/quota
can remain unknown; an old running supervisor cannot report newly added metrics
without a future notebook deployment. Do not restart it merely for telemetry.
Approved shell commands retain host privileges rather than an OS sandbox, and
prompts/tool results reach the inference provider.

Launch with the existing private key and your fresh Kaggle URL:

```powershell
freecompute --remote-url "PASTE-KAGGLE-URL-HERE"
```

1. Type `/`, then `/mo`; navigate with arrows, Enter/Tab and Escape.
2. Run `/model`, `/skills`, `/status`, `/workers`; verify actual routes, skill
   manifests and observed/unknown telemetry. Alt+Enter adds a prompt line.
3. Request a small task in a disposable project. Inspect the proposed file diff
   and exact test command/cwd, approve explicitly, then inspect the real result.
   Use `/diff`, `/sessions`, restart and `/resume ID`; completed work must not replay.
   Run `/undo` and deny first; the file must remain unchanged.
4. If the tunnel changes, use `/connect NEW-URL`. For a separately configured
   supported image gateway use `/connect-image IMAGE-URL`, `/image-model` and
   `/image PROMPT`; its own key comes from dotenv/config. Keep Kaggle running
   during this manual test, then explicitly shut it down when local work is done.

No further architecture or GUI phase is part of this handoff.

## Historical 2026-10-03 release pass

2026-10-03. **Local implementation and acceptance are complete; ready for the
user's manual CLI test.** This is a beta release candidate, not a published
production release or universal hardware/model certification. Work is local on
`v1/cli-release`, starting at accepted backend `755e944`. No push, merge, release,
deployment or change to `main` is part of this pass. GUI is **DEFERRED / ABANDONED
FOR V1**. The prior GUI experiment remains on its separate branch.

## Actual evidence

| Check | Tested result |
| --- | --- |
| Accepted backend before modifications | 210 unit tests passed in 82.084s |
| Focused existing CLI integration | 15 tests passed |
| Final full unit suite | **240 passed in 91.930s**; original 210 unchanged, 30 production regressions (11 for dynamic URL/reconnect) |
| Installed editable CLI, fresh temporary venv | Help/launch executed outside repo; baseline wrong-model banner, false ONLINE status and ignored coding `--prompt` reproduced before fixes |
| Clean wheel/source snapshot | `freecompute-0.1.0-py3-none-any.whl` built outside the repo |
| Wheel inventory | **46** production Python files byte-matched to snapshot; YAML sample present; no experiments, GUI/API/tests or private `.env` |
| Fresh venv wheel installation | Entrypoint/help/version/Core imports executed outside repo; OpenHands absent; metadata/import version `0.1.0` consistent |
| Reinstalled manual command | Verified wheel reinstalled into the existing Python installation without changing dependencies; bare `freecompute --help`/`--version` executed outside repo and imported installed site-packages |
| End-to-end wheel acceptance | **20 passed**, using installed `freecompute.exe`, isolated state and disposable paths with spaces/Unicode |
| Dynamic Kaggle URL | Fresh `--remote-url` overrode an expired HTTP 530 registry URL using the dotenv key; flag-selected compatible worker also checked |
| Runtime reconnect | Installed `/connect` refreshed authenticated health/models; bad URLs/wrong keys stayed nonfatal, keys stayed redacted, saved config unchanged |
| Reconnect recovery | Completed receipts/actions/tests were not replayed; queued tasks stayed queued until explicit dispatch; unknown leases retained their fence |
| Real local coding effects | 4 model/tool turns: read calculator → proposed `//` to `/` edit → approved real unittest command → actual result → one final response; 2 real tests passed |
| Restart/resume | Completed inference/actions/command receipts unchanged; HTTP request count and real test counter unchanged |
| Diff/undo | Real diff, undo preview/deny with unchanged file, later approved sealed restore without inference/test replay |
| First run/config/errors | No dotenv/config, invalid URL, unhealthy/offline worker, wrong bearer, ignored registry flags and unknown command checked |
| Streaming | Visible text reached stdout while fixture completion was held; markers emitted once; no reasoning/tool JSON displayed |
| Queue/resource semantics | Existing full-suite shared-resource/FIFO/restart tests preserved; installed CLI also persisted offline queue, cancelled one queued task without dispatch and ran another after recovery |
| Cancellation | Native Windows `CTRL_BREAK_EVENT` stopped installed CLI task locally; output explicitly left remote cancellation unconfirmed and remote outcome unknown; one-shot exit 1 |
| Interrupted inference | Incomplete stream held a quarantined lease across new CLI process; `/resume` made no additional request |
| Approval/security | Blank/EOF/OSError deny; old sandbox/approval/hash/undo/redirect tests preserved; split credential redacted and terminal controls removed |
| Final releasable-source scan | **155 files, zero findings**; ignored private config/key files excluded; matched secret text is never reprinted |

Wheel SHA256 observed in this run:
`62d1a2787cf80669039eea6cfe89e47959a03c871d6c90a78adca537a70dc091`.
Acceptance script prints its temporary evidence directory, containing
`acceptance.json` and `transcripts.json`; no private key is logged. The source
secret scanner reports locations/rules without reprinting a matched secret and
excludes ignored private files/generated caches. `git diff --check` also passed.

All inference in this pass used explicit loopback fixtures. It made **no real
Kaggle/model request and consumed no GPU quota**. Earlier live acceptance remains
historical evidence in [V1_REAL_KAGGLE_ACCEPTANCE.md](V1_REAL_KAGGLE_ACCEPTANCE.md),
including 9,714 actual input tokens and truthful cancellation fencing. Optional
SDK research suites were not rerun; they are not the shipped CLI runtime and
their historical evidence is retained separately.

## Known limitations, not newly invented success

- Final real-model usability/streaming in the user's terminal is pending manual
  acceptance. The screenshot's abandoned GUI demo is not model inference.
- Native Windows Ctrl+Break was executed. The physical Ctrl+C key and visual
  wrapping/colors in the user's PowerShell host remain manual checks. Unicode,
  spaces, subprocesses, editable install and clean wheel install were executed.
- Full 65,536-token input capacity is not certified. Budgets are conservative
  UTF-8-byte/framing estimates; declared capacities/verification labels are not
  current measurements. Other Python versions/OSes/models were not executed.
- Remote acknowledgement is unavailable for these adapters. Unknown outcomes
  hold capacity; operator reconciliation requires independent idle evidence.
  `/connect` cannot change a worker's endpoint while it holds active/uncertain
  leases; it never clears that hold or resubmits a task automatically.
- Quick Tunnel SSE is not universally supported. One earlier live session
  streamed successfully; the actual new endpoint must be tested.
- The downloadable Kaggle engine artifact expires on 2026-10-10; after expiry
  refresh its identity/checksums off GPU before a new deployment.
- Approved commands use the user's host privileges, not an OS sandbox. File
  path guards do not constrain an approved shell program. Prompts/read contents
  and tool results reach the inference provider; local authority/journals remain
  local. Redaction is not general data-loss prevention.
- The CLI is synchronous/line based. Queued work needs `/run-next` or `/resume`;
  no background daemon, GUI, automation or richer editor is a V1 requirement.
- ComfyUI retains the fixed workflow and protected endpoint contract; live image
  generation was not repeated in this pass. Existing fixture artifact recovery
  and modality separation tests pass with the full suite.

No fixable local release blocker remains from these checks. Release remains
blocked on the user's manual decision, not on green tests alone.

## Exact final manual test

From the repository on `v1/cli-release`, with the existing private key preserved:

After installation, the normal Kaggle launch is simply:

```powershell
freecompute --remote-url "https://YOUR-KAGGLE-URL"
```

If the tunnel changes during the session, use `/connect https://YOUR-NEW-KAGGLE-URL`.
No key argument or saved tunnel edit is required. Fresh checkout installation:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\freecompute.exe --version
```

Keep `FREECOMPUTE_API_KEY` in the existing private `.env`, matching the notebook
secret. For the explicit registry flow, copy `harness/config.sample.yaml` to
`config.yaml` only if that private file is missing; configure
`model_profiles[].model` to its exact advertised alias. Supply the fresh tunnel
URL at launch with `freecompute --remote-url "https://YOUR-KAGGLE-URL"`.
The CLI flag overrides the saved worker URL for that run; it does not write the
ephemeral URL to YAML or dotenv. When already running, use
`/connect https://YOUR-NEW-KAGGLE-URL`; this reuses the key and refreshes
authenticated health/models without submitting or replaying tasks.
`FREECOMPUTE_REMOTE_URL` controls only the legacy single-worker route, not an
explicit registry. The key is not a GUI/API token. Do not Run All or restart the
running Kaggle model. Make a new disposable local workspace:

```powershell
$taskProject = Join-Path $env:TEMP ('FreeCompute manual ' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $taskProject | Out-Null
@'
def divide(a, b):
    return a // b
'@ | Set-Content -Encoding UTF8 (Join-Path $taskProject 'calculator.py')
@'
import unittest
from calculator import divide
class CalculatorTests(unittest.TestCase):
    def test_fraction(self):
        self.assertEqual(divide(7, 2), 3.5)
    def test_whole(self):
        self.assertEqual(divide(8, 2), 4)
'@ | Set-Content -Encoding UTF8 (Join-Path $taskProject 'test_calculator.py')
$env:FREECOMPUTE_JOURNAL_DIR = Join-Path $env:TEMP ('FreeCompute manual ledger ' + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\freecompute.exe --config config.yaml --workspace $taskProject --remote-url "https://YOUR-KAGGLE-URL"
```

At `freecompute>` run `/status`, `/model`, `/workers`, `/models`, `/help`.
Then request:

```text
Inspect calculator.py and test_calculator.py. Fix division so 7 / 2 returns 3.5.
Propose the smallest edit, request my approval, and after approval propose
python -m unittest -v test_calculator. Wait for my command approval, inspect
the actual test result and give a short final answer.
```

Review and approve the exact edit and test command with `y`. Check live text,
read/edit/run activities, actual `Ran 2 tests`/`OK`, and a single final answer.
Run `/diff` and `/sessions`, copy the completed session ID, then `/exit`.
Reopen with the same command/workspace in the same PowerShell tab (keep
`$taskProject` set), use `/resume <session-id>` and verify
that completed effects/tests are not repeated. Run `/undo`, inspect the preview,
answer `n`, and confirm the edit remains. Use `/new` before a separate long-text
request; press Ctrl+C during generation and inspect `/queue` and cancellation
wording. Do not approve idle reconciliation without independent engine evidence.

Keep Kaggle running during that manual test. After you finish with the GPU,
use the notebook's guarded shutdown and **Stop Session**. A CLI exit is not a GPU
shutdown. Report the manual result; pushing/releasing is a separate next action.

For a clean packaged repeat without any GPU:

```powershell
python tests/runtime/cli_release_acceptance.py
```

This creates a fresh external snapshot/venv/workspace and leaves its evidence for
review. It does not alter an existing project or silently enable fixture mode in
the application.

## Files changed in the final pass

- CLI: `harness/cli/main.py`, `formatter.py`, `core_client.py`.
- Core reconnect/discovery: `harness/core/client.py`, `engines.py`, `service.py`.
- Configuration/package: `harness/config.py`, `harness/core/engine_config.py`,
  `harness/config.sample.yaml`, `harness/__init__.py`, `pyproject.toml`, `.env.example`.
- Acceptance/regressions: `tests/unit/test_cli_product.py`,
  `tests/runtime/cli_fixture.py`, `tests/runtime/cli_release_acceptance.py`,
  `tests/runtime/README.md`, `tests/security_scan.py`.
- Documentation: `README.md`, `knowledgebase/README.md`, `V1_CLI_PRODUCT.md`,
  `V1_RELEASE_READINESS.md`, `V1_REAL_KAGGLE_ACCEPTANCE.md`, `V2_ROADMAP.md`,
  `V2_SYSTEM_ARCHITECTURE.md`, `GUI_AND_WEBSITE_DIRECTION.md`.

Original unit files, scheduler/storage/sandbox/tool implementations, Kaggle
notebooks and historical SDK experiments are preserved. Any user-specific
private `config.yaml`, `.env`, temporary manual project and acceptance artifacts
are excluded from Git/package inventory. The existing key value is unchanged.
