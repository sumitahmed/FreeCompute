# Production local runtime fixtures

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

Package acceptance uses a fresh source snapshot outside the repository,
`python -m pip wheel --no-deps`, a separate target install, byte comparison of
every packaged `harness` Python file, installed-module imports, and the actual
installed `freecompute.exe` against the same loopback edit/test/resume workflow.
Results and limitations are recorded in `knowledgebase/STAGE3_LOCAL_RUNTIME.md`.
