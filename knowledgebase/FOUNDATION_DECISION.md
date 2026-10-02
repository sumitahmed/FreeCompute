# FreeCompute foundation decision experiment

2026-10-02. Branch: `v2/safety-and-agentdriver-spike`.

## Checkpoint preservation

**Observed:** the previously uncommitted Stage 1 work is now present in local checkpoint history through `2675686`, and the working tree was clean at the start of this task. The cumulative Stage 1 change set still contains the same 38 files. No reset, discard, reconstruction, or history rewrite was performed. Local/main tracking references remain `1300566dca62a0f804487e7101767e688e551184`.

**Tested:** before new experiment code, `python -m unittest discover -s tests/unit -p "test_*.py"` passed all 81 tests. The pinned optional OpenHands 1.50.1 fixture suite passed all 15 tests. Its tokenizer metadata connection was blocked as before. These results establish preservation of the baseline, not completion of the foundation gates.

The named checkpoint commit is `feat: harden FreeCompute safety baseline and add AgentDriver spike`; it includes this verification record and backs up the existing feature-branch history. Only this feature branch is authorized for pushing.

## Authorized experiment and initial hypotheses

**Proposed, not yet verified:** a public SDK tool executor can call FreeCompute's broker and return the real normalized result, avoiding client-tool acknowledgement as a substitute for execution. A public LLM subclass may route normal/async/condenser/child inference through a FreeCompute-owned broker before SDK logging or persistence. A small SQLite store may own action transitions and an SDK persistence projection, with uncertain effects quarantined instead of replayed.

**Unverified:** native delegation can retain narrower permissions, route all nested inference, propagate cancellation, and avoid deadlock with one fake resource slot. SDK recovery/profile loading may recreate unbrokered LLM instances or expose workspace capabilities; these are explicit tests, not assumptions.

No full scheduler, worker registry, GUI, daemon, automation, cloud/GPU work, or alternative foundation implementation is authorized. New prototype code will be kept separate from the current CLI. Progress, rejected approaches, concrete failures and final evidence will be appended during the experiment.
