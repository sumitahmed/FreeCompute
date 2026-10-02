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

## Public-boundary implementation attempt

**Observed:** checkpoint `7861a9f0cc2f47bde86c5755c77325ad9e599b5e` was pushed successfully to the feature branch. No main reference changed.

**Proposed / in progress:** isolated `harness/experiments/foundation/` adds a SQLite record store, actor grants, durable tool wrapper, a one-slot loopback-only inference broker and public SDK tool/LLM/FileStore/workspace adapters. Existing CLI source is untouched. SDK state is a sanitized projection; core action state owns approval and effects. Completed state and result must be committed together. Restart invalidates approval and quarantines interrupted execution. Streaming is buffered before SDK callbacks: no sub-second TTFT claim.

**Observed limitation, not yet dynamically tested:** the separately distributed `openhands-tools==1.50.1` native Delegate implementation constructs a child `LocalConversation(workspace=parent.workspace.working_dir, ...)`. It drops the custom workspace object and does not forward the custom FileStore. Its constructor has no public factory parameter for those boundaries. Tool package downloaded without installing browser/terminal dependencies; native delegation will be a negative boundary probe before any adoption claim.

**Rejected approach:** SDK client-tool acknowledgement as evidence of completed execution; unrestricted LocalWorkspace pointed at the real project; raw user callbacks as a redaction gate after SDK persistence; replaying an executing action. Public wrapped model calls are the positive experiment; unrestricted SDK profile creation is not assumed to be controlled.

## First execution results and corrections

**Tested:** public broker-tool round trips for read, approved/denied write, malformed arguments, protected path and tool failure now pass. First run failed before execution because native `MessageToolCall` requires explicit `origin="completion"`; the adapter was corrected rather than changing existing expectations. Cancelled approval stops the next model call, so its test checks the durable denial and missing effect rather than expecting another inference continuation.

**Security decision:** changing arguments during redaction cannot authorize writing placeholder credentials. The broker marks altered tool proposals for rejection/fresh proposal. A terminated shell still leaves descendant/effect outcome unknown. Recovery must not mark the authoritative task finished when an action requires reconciliation. These tighten the experimental contract; production source remains unchanged.

**In progress:** actual process-crash/restart fixtures and native delegation negative probes. Native source also logs task text before invoking child `send_message`, and produces unbounded final results. These are observed source risks pending dynamic evidence, not passed gates.

**Tested failure during real restart:** the SDK persisted the ActionEvent but deferred its active-branch HEAD update until the tool step returned. Restoring that stale HEAD missed the pending event and generated a fresh proposal. The effect counter exposed an extra approval attempt, even where overwrite protection prevented a second successful write. Core action deduplication alone does not fix a newly generated event ID. **Correction under test:** for the single linear pending-action fixture, use public `navigate_to` to reconcile the SDK projection to the exact action ID already owned by core before resuming. Multiple pending branches fail closed; no private SDK state is patched. SDK snapshots are now scoped by both actor and conversation ID.

## Native probes and authority review

**Tested:** the corrected four-point process-crash fixture passed. A separate native parent/child probe passed with a narrowed read-only core actor, brokered inference/tools and one slot. The later model-driven parent -> native spawn/delegate -> child read -> bounded core result loop also passed. These prove useful public composition, not preservation of every authority boundary.

**Tested adoption failures:** native child construction replaces the parent's restricted workspace with plain LocalWorkspace and loses the injected core projection store. The native result exceeds 10,000 characters when the child returns that much text; an outer core wrapper can bound it, but the executor does not. A raw registered task at the native entry is logged and recorded before inference input scrubbing. Public `switch_llm` with a plain SDK profile makes an unrecorded inference request. These are deliberate negative probes against disposable directories/loopback inference, never capabilities enabled in the existing CLI.

**Observed installation failure:** importing Delegate first imported file-editor and terminal re-exports; the reduced tools wheel lacked `binaryornot`. Three minimal import dependencies were added to the external fixture environment. Browser-use/tom-swe are intentionally uninstalled, so this is not a complete tools installation. Reproduction instructions record that limitation instead of suppressing it.

**Authority review changes:** a sanitized proposal denial now persists in core, not merely in an SDK observation. A high-risk handler error after approval is conservatively an unknown effect. Unknown effects block newly identified mutations as well as exact-ID replay, so fresh model IDs cannot bypass quarantine. Missing core action projections and ambiguous SDK action identity fail closed. General concurrent writers/branches remain outside this fixture.

**Security review finding and correction under test:** scrubbing the outer JSON response alone can miss a registered credential whose quote/backslash is escaped inside a function's JSON argument string. Arguments are now decoded, structurally scrubbed and re-encoded before any SDK parser/display/persistence sink; changed proposals are denied. The projection also decodes SDK JSON before sanitizing. A quoted-credential regression was added. Streamed tool-call deltas are explicitly rejected because only buffered text SSE is supported by this fixture.

## Foundation decision

**REJECT — OpenHands SDK/tools 1.50.1 as the general FreeCompute V2 foundation under the required authority, state and routing boundaries.** This is a decision about this pinned release and required feature envelope, not a claim that OpenHands is unusable or that a deep fork is proven inevitable for every possible integration.

The public single-agent composition works. Adopting that restricted subset would still require forbidding ordinary profile switches and native child construction, maintaining a separate authoritative ledger, reconciling SDK HEADs, imposing pre-entry redaction and explicitly binding every condenser/child model. Native Delegate has no public conversation/workspace/FileStore factory parameter to preserve the required child authority boundary. Replacing its child lifecycle or managing children entirely in FreeCompute would be additional foundation work beyond the small public adapter tested here. We do not force adoption by quietly excluding failed gates.

| Experiment | Evidence / outcome | Adoption implication |
| --- | --- | --- |
| Brokered tools | Actual SDK proposal -> core registry validation/approval -> real normalized observation -> next SDK request. Read, approved/denied write, malformed arguments, protected path, cancelled approval and tool failure covered. | Pass in configured restricted loop |
| Inference routing | Normal generation, sync/async public entries, retries, real condensation summary, native child and recovery requests are core-recorded with request/task/agent/profile/purpose/parent/start/end. Real OpenAI chat serialization; one loopback profile. | Pass for explicitly bound models; **fail universal SDK enforcement** because public plain model switch bypasses broker |
| Restart | `os._exit(73)` before approval, after approval/before effect, during effect, after successful effect/before SDK observation. Fresh core/SDK process reloads SQLite and stable action ID; exactly one durable effect counter entry in each case. | Pass for single linear action; no general branch/child recovery claim |
| Redaction | Registered fixture credentials in pre-entry input, output, fragmented SSE, tool arguments/results, exceptions, SDK events/projection/log captures and event visualization. Quoted/backslashed argument credentials decoded before sanitizing. Altered proposals denied. | Pass restricted paths; **fail unadapted native task entry** before inference gate. Pre-entry scrubbing fixes that particular sink, not lost workspace/store |
| Native children | Native registered research factory, distinct core actor, read-only capability, actual brokered child read/inference, model-driven parent spawn/delegate/result, one slot with no deadlock. Explicit core wrapper bounds parent result. | **Fail native authority/state propagation**: plain LocalWorkspace and separate SDK FileStore; native result itself unbounded |
| Cancellation | Real model SSE, blocked approval callback, owned subprocess and native child request. Requested state checked before local loop actually exits; returned synchronous loop records local stop. Shell exit observed; descendants/effects and remote request remain unknown. | Honest local semantics; native interrupt lacks automatic propagation; no engine cancellation acknowledgement tested |

### Recovery ownership

Core SQLite categories are `tasks`, `actions`, `events`, `requests`, and `sdk` (projection only). Actor grants are immutable capability subsets provisioned by trusted fixture code. Action records bind task/actor/event ID and argument fingerprint, with `pending`, `approved`, `executing`, `completed`, `failed`, `denied`, `outcome_unknown`. Completed state and result share a commit. Restart invalidates approved state and quarantines executing state. Missing projections, identity collisions and ambiguous/multiple actions fail closed. Any unknown task effect prevents further newly identified mutations until explicit reconciliation. Sanitized persisted arguments cannot silently regain replay authority.

The four crash outcomes are:

| Crash point | Recovery action | Successful effects / approval calls |
| --- | --- | --- |
| Before approval | Reload pending action; obtain approval; execute | 1 / 1 |
| Approved, not executed | Invalidate recorded approval; obtain fresh approval; execute | 1 / 2 |
| During execution | Preserve existing effect, return `outcome_unknown`; do not execute again | 1 / 1 |
| Completed, before SDK continuation | Return core's stored result for the same event; do not execute again | 1 / 1 |

The SDK can finish after receiving an unknown observation; the authoritative core task remains `needs_reconciliation`. Event records are supporting observations, not a production event-sourcing/audit guarantee across independent commits.

### Limits and review findings

- **Saboteur — fixed:** stale SDK HEAD and fresh action IDs could defeat effect deduplication; real crash tests exposed it. Public HEAD reconciliation and task quarantine address the fixture. Multi-process concurrent writers, multiple branches and lost projections still require explicit recovery design; no production scheduler was built.
- **Security auditor — fixed/rejected:** JSON-escaped credentials needed decoding before SDK parsing. Native child workspace/store loss and raw task sinks remain adoption failures. No private SDK methods were overridden to conceal them.
- **New hire — retained scope limit:** SDK global tool registration under a fixed name is suitable only for this controlled fixture; public SDK handles expose configuration switches. The adapter is explicitly experimental and is not imported by the production CLI. No public API stability or production concurrent ownership claim is made.
- **Observed source risk, unverified beyond source inspection:** SDK user-agent discovery still reads home-relative `~/.agents/agents` even when `OH_PERSISTENCE_DIR` isolates the OpenHands home. Ambient plugins/hooks/user definitions and SDK secret-registry entry paths have no complete isolation proof here. A denied workspace object is not an OS sandbox.
- The one slot controls local HTTP inference concurrency, not GPU lease quarantine after an unknown remote cancellation. Network timeout bounds local waiting; remote acknowledgement and physical resource accounting require a real engine protocol later.
- Buffered text streaming deliberately sacrifices token-by-token delivery. Streamed tool deltas and Responses API are rejected. Character-count token estimates are fixture-only; tokenizer budgeting, KV-cache behavior, real model quality, GPU latency, long-context behavior and transport compatibility remain unverified.
- SQLite is an external disposable database, with a single exclusive fixture writer and sequential process restart. No migration of user journals, retention/encryption policy, distributed transactions or durable native-child recovery is implemented.
- Tools-package environment is deliberately incomplete (browser-use/tom-swe absent). SDK dependency/license/security/platform acceptance is not a production release approval. Native private fields are inspected in tests only, never used to patch lifecycle behavior.

### Recommended next bounded stage

**Proposed, not implemented:** qualify a narrow custom FreeCompute AgentDriver against the already established proposal/broker/store contracts. Keep inference, tools, approval, cancellation and durable identity outside the driver; cover the same malformed-call, actual-result and crash fixtures. The existing proposal-only driver is a contract seed, not a newly adopted full foundation. Evaluate that small surface before authorizing Stage 3's production local runtime. Codex components, Cline and Pi were not evaluated or implemented in this phase. Stop for user review; no full V2 build follows this decision automatically.

### Exact files in this follow-up

- `harness/experiments/__init__.py`
- `harness/experiments/foundation/__init__.py`
- `harness/experiments/foundation/runtime.py`
- `harness/experiments/foundation/openhands_adapter.py`
- `tests/unit/test_foundation_runtime.py`
- `tests/foundation/support.py`
- `tests/foundation/crash_worker.py`
- `tests/foundation/test_foundation.py`
- `tests/foundation/requirements-windows-py312.txt`
- `tests/foundation/README.md`
- `knowledgebase/FOUNDATION_DECISION.md`
- `knowledgebase/OPENHANDS_COMPATIBILITY_SPIKE.md`
- `knowledgebase/V2_ROADMAP.md`

Production source, notebooks, package metadata, CLI entry point and all prior safety/characterization tests are unchanged from checkpoint `7861a9f`. Only the isolated experiment, its tests and the three knowledge-base documents change.

Primary pinned source: [SDK local conversation](https://github.com/OpenHands/software-agent-sdk/blob/1e1390acc8788346ba4804c34323284009bf3f5e/openhands-sdk/openhands/sdk/conversation/impl/local_conversation.py), [native Delegate implementation](https://github.com/OpenHands/software-agent-sdk/blob/1e1390acc8788346ba4804c34323284009bf3f5e/openhands-tools/openhands/tools/delegate/impl.py). Empirical assertions use installed SDK/tools wheels; [fixture reproduction instructions](../tests/foundation/README.md) record the reduced import environment.

## Final verification evidence

**Tested, 2026-10-02, Windows CPython 3.12.10:**

- Preserved checkpoint: 81 unit + 15 characterization tests passed before new experiment code, then `7861a9f0cc2f47bde86c5755c77325ad9e599b5e` pushed with message `feat: harden FreeCompute safety baseline and add AgentDriver spike`.
- Final core suite: **94 tests passed** (the original 81 unchanged plus 13 new core experiment regressions), latest run 4.841 seconds.
- Original pinned SDK suite: **15 tests passed**, 7.711 seconds. One attempted tokenizer-metadata external connection was blocked; it was not telemetry or a successful download.
- Foundation SDK suite: **28 tests passed**, 138.016 seconds, no skipped cases. All four real crash/restart subcases passed; zero external socket connection attempts in this fixture. Negative probes reproduce adoption failures and are not counted as passed adoption gates.
- SDK debug-log capture was strengthened after the full run: handlers attach directly to SDK loggers with DEBUG enabled, assert an actual framework message was captured, and verify the registered exception credential is absent. Its focused test passed; no production code changed afterward.
- Final wheel built from an external source snapshot: **all 33 harness Python files matched source bytes**; wheel installed into a separate external target; **25 installed modules imported** from outside the repo. Installed module and actual `freecompute.exe --help` passed. The first no-build-isolation attempt failed because the SDK venv lacked setuptools; standard PEP 517 isolated build succeeded without changing project metadata.
- Repository secret scanner: **120 files, zero pattern findings**; scanning is not arbitrary workspace DLP. No scanner rules or existing test assertions were weakened.
- `git diff --check` passed; production harness paths outside `harness/experiments/`, Kaggle/notebooks, README and pyproject had no changes relative to checkpoint `7861a9f`.
- Local `main` and `origin/main` remained `1300566dca62a0f804487e7101767e688e551184`. Final push is restricted to `v2/safety-and-agentdriver-spike`; no merge or PR is authorized or performed.

No GPU/cloud/model weights, live credentials, user journal migration, production driver switch, alternative implementation or full V2 stage was used. The feature branch is the review artifact; the exact final commit is identified in the handoff and Git history rather than embedding a self-referential commit hash in this document.
