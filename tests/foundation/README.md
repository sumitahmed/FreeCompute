# Bounded foundation experiment

This is a compatibility experiment, not a production runtime or a supported
OpenHands integration. All workspaces/databases are disposable. The existing
CLI does not import the experiment. Python 3.12 and pinned OpenHands 1.50.1 are
required for the SDK fixtures; core unit tests do not require the SDK.

From the repository root, in an external disposable virtual environment:

```powershell
python -m pip install -r tests/foundation/requirements-windows-py312.txt
python -m pip install --no-deps "openhands-tools==1.50.1"
$env:PYTHONDONTWRITEBYTECODE="1"
python -m unittest discover -s tests/unit -p "test_*.py"
python -m unittest discover -s tests/spike -p "test_*.py"
python -m unittest discover -s tests/foundation -p "test_*.py"
python tests/security_scan.py
```

The tools wheel SHA-256 is
`a19da59aa23e4472f1e34e85d2fe987406be7e39e739a35bb9ea844a28b0bc6d`.
The tools distribution imports file-editor/terminal classes even when only
Delegate is requested, requiring three additional import dependencies above.
Browser-use and tom-swe are intentionally absent; `pip check` therefore reports
an incomplete tools distribution. This reduced environment reproduces the
Delegate probe, not the complete supported tools dependency graph. No default
SDK terminal/browser/editor tool is instantiated. Repository MIT notice is
preserved in [the existing SDK license file](../spike/OPENHANDS_LICENSE.txt).

`support.py` clears observability/provider/automation variables in the fixture
process, sets an isolated SDK home, and blocks non-loopback socket connections
before SDK import. It does not modify the user's environment files. The fake
server accepts OpenAI chat messages and emits deterministic completions/SSE.

`crash_worker.py` uses `os._exit(73)` in four separate-process scenarios; the
parent recreates the core and SDK from the same SQLite database. A durable
effect counter must contain exactly one entry. Recovery invalidates approval,
reconciles the SDK's stale HEAD with public `navigate_to`, returns completed
results without replay and quarantines interrupted execution. Unknown effects
keep the core task in `needs_reconciliation` even if the SDK loop finishes.

Tests with `negative_probe`/`boundary_lost` in their names assert an actual SDK
limitation. Green tests do not mean those adoption gates passed. Native SDK
private attributes are inspected solely to measure child state; adapter code
does not override private SDK methods or monkeypatch SDK behavior.

Limits: single exclusive writer, one linear pending recovery action, buffered
text streaming, fixture token estimate, one frozen chat profile, process-local
tool registration. No durable child recovery, real engine acknowledgement,
production OS isolation, full scheduler or deployment is claimed. See
[FOUNDATION_DECISION.md](../../knowledgebase/FOUNDATION_DECISION.md).
