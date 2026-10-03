# Contributing

Follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). V1 is the CLI/local Core product;
GUI, delegation and advanced scheduling are deferred. Keep changes scoped and
preserve existing acceptance evidence as dated history.

```powershell
git clone https://github.com/sumitahmed/FreeCompute.git
cd FreeCompute
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests/unit -p "test_*.py"
.\.venv\Scripts\python.exe tests/security_scan.py
.\.venv\Scripts\python.exe tests/runtime/cli_release_acceptance.py
```

On Linux/macOS use `.venv/bin/python`. Python 3.10+ is the declared minimum;
Windows/Python 3.12 is the executed release environment. No optional OpenHands SDK,
frontend, browser daemon or GPU is required for the CLI tests. Package acceptance
installs a fresh wheel outside the repo and runs deterministic HTTP inference
fixtures with real local file/command effects. Do not call fixtures GPU acceptance.

Create a feature branch from `main`. Run the full existing unit suite without
bypassing failures, add regressions for genuine bugs, check `git diff --check`,
and run the scanner before submitting a PR. Keep keys/live tunnel URLs/private
data/generated binaries out of commits and wheel artifacts. Update docs and
CHANGELOG when behavior changes.

Core owns durable tasks, queues, leases, permission gates, receipt replay and
sealed undo. Endpoint/model defaults must not rebind queued tasks. Unknown remote
outcomes stay quarantined. Local tools use the ToolBroker; remote models never
execute commands or access files directly. Skills may narrow scope and never
bypass approval. Telemetry is optional and never grants capacity.

Stable system/tool prefixes improve cache opportunities; they do not guarantee
KV cache hit rates or sub-second TTFT. Distinguish observations, configured
capacity, estimates, historical evidence and unverified claims.

Notebook changes must preserve empty outputs, compile every code cell, synchronize
canonical/wrapper modules, and check dataset/hash/path/runtime guards without
allocating GPU time. See [the current notebook procedure](knowledgebase/KAGGLE_FAST_START.md).
