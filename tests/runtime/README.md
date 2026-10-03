# Production local runtime fixtures

The final CLI release check is `python tests/runtime/cli_release_acceptance.py`.
It builds from an external source snapshot, installs in a clean venv and runs
the installed entrypoint without source `PYTHONPATH`. Its explicit loopback
fixture is in `cli_fixture.py`; it is not packaged or a default inference mode.
The 2026-10-04 pass adds terminal menus, generic telemetry, web activity,
authenticated independent image connections and verified notebook assets.
Current counts and evidence are in `knowledgebase/V1_RELEASE_READINESS.md`;
the older 240-test/20-check result is historical.

On Windows, also exercise the installed wheel's keyboard and rendered screens
in PowerShell through native ConPTY (optional **test-runner** dependencies):

```powershell
python -m pip install pywinpty pyte
python tests/runtime/cli_polish_acceptance.py --package-dir "DIRECTORY-PRINTED-BY-CLI-RELEASE-ACCEPTANCE"
```

This runs the installed `freecompute.exe` outside the checkout. It captures
terminal screens for `/`, filtering, arrows/Enter/Tab/Escape, model selectors,
bundled/project skills, resize, history and multiline input; checks streamed
Markdown while fixture completion is held; and authenticates separate image
health/generation/artifact HTTP requests. A separate installed CLI process uses
an explicit test-only transport to map web searches/pages onto real loopback
HTTP fixtures. Parsing, Core tool execution, three model turns and activity
rendering remain real. This does not certify an Internet search service, actual
image model, physical Windows Terminal renderer or GPU. Neither pywinpty nor
pyte is a product dependency.

Run the complete existing and new unit suite from the repository root:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest discover -s tests/unit -p "test_*.py"
python tests/security_scan.py
```

`test_native_driver.py` checks the proposal-only state machine.
`test_local_runtime.py` exercises the production CoreService, real file tools
and a real approved Python test command. `test_runtime_cli.py` launches actual
CLI processes through an authenticated loopback SSE supervisor and inspects
SQLite receipts after a second process resumes the session.

`test_runtime_recovery.py` launches `crash_worker.py` in fresh temporary
workspaces outside the repository. The worker exits with code 73 at proposal,
approval, denial, execution-intent, during-effect, result and inference-receipt
boundaries. Recovery is a new process; the counter and approval ledger are real
files, not mocked restart callbacks. An uncertain action fences fresh IDs until
an explicit reconciliation decision. Another process test holds the workspace
owner lock and verifies a second core is refused.

Fixtures do not start Kaggle/Colab, load model weights or create remote workers.
Reported token usage in the CLI supervisor is synthetic fixture data. Assertions
about crash recovery concern process exit, not filesystem/SQLite durability
under power loss. The historical optional SDK suites remain separately
documented in `knowledgebase/OPENHANDS_COMPATIBILITY_SPIKE.md` and
`tests/foundation/README.md`.

The bounded V1 backend adds `test_workers_scheduler.py` for three deterministic
workers, shared physical claims, FIFO/capacity, health, cancellation and routing;
`test_scheduler_migration.py` for populated schema-v1 migration/rollback/undo;
and `test_engine_workers_cli.py` for authenticated loopback compatible/llama
streaming, negative auth/redirect/timeout cases, ComfyUI artifact recovery and
actual CLI commands. These run under the complete unit command above.

`test_worker_queue_recovery.py` invokes `worker_queue_process.py` with separate
processes and `os._exit(73)`. A real durable counter verifies FIFO request counts,
cancelled work is never dispatched, and an interrupted both-GPU lease survives
restart without retry until explicit idle reconciliation. Fixtures use temporary
workspaces outside the repository; no actual GPU is involved.

Package acceptance uses a fresh source snapshot outside the repository,
`python -m pip wheel --no-deps`, a separate target install, byte comparison of
every packaged `harness` Python file, installed-module imports, and the actual
installed `freecompute.exe` against the same loopback edit/test/resume workflow.
Results and limitations are recorded in `knowledgebase/STAGE3_LOCAL_RUNTIME.md`.
Fresh V1 results, the expanded package file count and its installed CLI acceptance
are recorded in `knowledgebase/STAGE4_ENGINE_WORKERS.md`; Stage 3 results remain
historical rather than being overwritten.
