# Contributing to FreeCompute

Thank you for your interest in contributing to FreeCompute! We welcome contributions, bug reports, feature requests, and documentation improvements.

All participants are expected to adhere to our [Code of Conduct](CODE_OF_CONDUCT.md).

---

## Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-org/FreeCompute.git
   cd FreeCompute
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv

   # Windows (PowerShell):
   .venv\Scripts\Activate.ps1

   # Linux / macOS:
   source .venv/bin/activate
   ```

3. **Install dependencies in editable mode:**
   ```bash
   pip install -e .
   pip install -r requirements.txt
   ```

---

## Testing Guidelines

FreeCompute enforces a strict testing standard. All unit tests must pass before submitting a pull request:

```bash
# Run all unit tests
python -m unittest discover -s tests/unit -p "test_*.py"

# Run deep security & secret leak audit
python tests/security_scan.py
```

When contributing new features or bug fixes:
- Core systems (`harness/storage`, `harness/providers`, `harness/tools`, `harness/telemetry`, `harness/skills`, `harness/cli`) must include unit tests under `tests/unit/`.
- Mock external network calls and remote GPU responses; automated tests must never require a live Kaggle or Colab instance to pass.
- Test both success and failure/edge cases (e.g. timeouts, disconnected backends, denied user approvals).

---

## Coding & Architectural Standards

- **Python:** Target Python 3.10+ compatibility.
- **Type Annotations:** Use explicit type hints for all public classes, functions, and interfaces.
- **Local Machine as Source of Truth:** All tool execution (`inspect_file`, `edit_file`, `write_file`, `run_command`), sandbox boundaries, task journaling, and undo snapshots live strictly on the local machine.
- **Security & Redaction:** Always sanitize user input, respect the sandbox boundaries in `harness/tools/sandbox.py`, and register any sensitive parameters with `SecretScrubber`. Never hardcode API keys or live tunnel URLs in source files, tests, or notebooks.
- **Modality Isolation:** Keep model backends isolated behind `BaseProvider` and `Capability` in `harness/providers/`. Never assume an LLM can generate images or vice-versa. Unsupported operations must produce clean, actionable errors.
- **Prompt Prefix Stability:** Ensure system prompts and tool schemas remain immutable across turns to preserve 100% KV cache hit rates on remote GPU inference engines.

---

## Pull Request Process

1. Fork the repo and create your branch from `master` (e.g. `feat/my-feature` or `fix/issue-description`).
2. Implement your changes following the coding standards above.
3. Verify that all 42+ unit tests pass (`python -m unittest discover -s tests/unit -p "test_*.py"`).
4. Run the security scanner (`python tests/security_scan.py`) to confirm zero secrets are present.
5. Update `CHANGELOG.md` and documentation if introducing new features or commands.
6. Open a Pull Request with a clear summary of changes, rationale, and verification steps.
