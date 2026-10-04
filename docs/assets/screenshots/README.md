# Actual CLI screenshots for the landing page

Native Windows capture was unavailable during the final audit: the Computer Use
helper could not connect its native pipe, including after retry and reinitialization.
No terminal mockup, HTML reconstruction, or generated screenshot is supplied.
ConPTY keyboard/rendering acceptance is evidence, not a product screenshot.

Use a real connected text worker for these images. Do not substitute fixture GPU,
model, health, or telemetry output. Missing metrics and limits must remain unknown.
Use a terminal around 120 columns by 40 rows, a readable font, and no debug logs.

## Prepare a disposable project

From the FreeCompute checkout in PowerShell, with the existing private `.env` and
configured text worker preserved:

```powershell
$repoRoot = (Get-Location).Path
$demoRoot = Join-Path $env:PUBLIC ('FreeCompute-demo-' + [guid]::NewGuid().ToString('N'))
$demoProject = Join-Path $demoRoot 'demo-project'
New-Item -ItemType Directory -Path $demoProject | Out-Null
@'
def divide(a, b):
    return a // b
'@ | Set-Content -Encoding UTF8 (Join-Path $demoProject 'calculator.py')
@'
import unittest
from calculator import divide
class CalculatorTests(unittest.TestCase):
    def test_fraction(self): self.assertEqual(divide(7, 2), 3.5)
    def test_whole(self): self.assertEqual(divide(8, 2), 4)
'@ | Set-Content -Encoding UTF8 (Join-Path $demoProject 'test_calculator.py')
$env:FREECOMPUTE_JOURNAL_DIR = Join-Path $demoRoot 'legacy-ledger'
$freshUrl = Read-Host 'Fresh Kaggle worker URL'
Clear-Host
freecompute --config (Join-Path $repoRoot 'config.yaml') --workspace $demoProject --remote-url $freshUrl
```

The neutral public workspace avoids displaying a personal username. `config.yaml`
must already describe the real worker; the URL flag overrides its stale URL for
this run. Never type an API key into the terminal command. Keep Kaggle running.

## Capture six scenes

Save screenshots here with these filenames. Capture only the terminal window;
inspect every image before publication for keys, private URLs, personal paths,
sensitive session IDs, raw ANSI fragments, and unrelated PowerShell output.

| Filename | Exact action and capture point |
| --- | --- |
| `freecompute-cli-home.png` | After authenticated startup, before typing. Show the actual model, worker/provider, observed health/hardware, neutral workspace and command hint. |
| `freecompute-command-palette.png` | Type `/` without Enter. Capture the live menu with descriptions. `/r` narrows the menu to commands and `/review`/`/research` skills when a shorter frame is needed; Escape dismisses it. |
| `freecompute-agent-edit.png` | Submit the coding task below. Capture the genuine reading/search activity and proposed diff while edit approval is pending, then approve the inspected edit with `y`. |
| `freecompute-tests.png` | Approve the exact proposed test command with `y`. Capture the real command exit, `Ran 2 tests`/`OK`, and the concise final response; exclude the session-ID footer from the frame. |
| `freecompute-web-search.png` | Run `/new`, then the research task below. Capture genuine search/fetch activity and the final sourced answer. If the network blocks research, retain the error and retry later; never stage a success. |
| `freecompute-worker-status.png` | Run `/clear`, then `/status`. Capture real GPU/VRAM and any available CPU/RAM/session observations with their provenance. Unconfigured session limit/remaining stays unknown; do not invent a 12-hour limit. |

Coding task:

```text
Search the workspace for divide, then read calculator.py and test_calculator.py.
Fix division so divide(7, 2) returns 3.5 with the smallest edit. Request my edit
approval. Then propose python -m unittest -v test_calculator, wait for my command
approval, inspect its actual result, and give a short final answer.
```

Research task:

```text
/research Search the web for the official Python unittest documentation, fetch
the official page, and explain how to run test_calculator in two sentences with
the source URL. Use search_web and fetch_url.
```

After capture, use `/diff` and `/sessions`, then `/exit`. Reopen with the same
workspace and use `/resume <completed-session-id>` to confirm no completed effect
repeats. Finally use the notebook's explicit shutdown and Stop Session when done.
Image files remain ignored until individually inspected and intentionally added;
do not force-add a screenshot containing secrets.
