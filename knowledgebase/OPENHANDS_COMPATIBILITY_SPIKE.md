# OpenHands SDK compatibility spike

2026-10-02. Branch `v2/safety-and-agentdriver-spike`. **Current decision: REJECT OpenHands 1.50.1 as the general V2 foundation under the required boundaries.** The original Stage 1 characterization below concluded NEEDS MORE EVIDENCE and is preserved as historical evidence. The newly authorized durable experiment is recorded in [FOUNDATION_DECISION.md](FOUNDATION_DECISION.md); no production SDK integration or alternative foundation was started.

## Exact experiment

**Historical:** the setup, matrix and original conclusion below, until the Authorized follow-up evidence section, describe the first 15 characterization tests. They do not describe the later broker/restart/native-child experiment.

- Package: `openhands-sdk==1.50.1`, current PyPI release checked on the experiment date; requires Python >=3.12. Production FreeCompute still declares Python >=3.10.
- Release tag: [`v1.50.1`](https://github.com/OpenHands/software-agent-sdk/tree/v1.50.1), commit `1e1390acc8788346ba4804c34323284009bf3f5e`. The experiment installed the PyPI wheel, not moving GitHub main. Installed `llm.py` and `local_conversation.py` were byte-compared (normalized line endings) to this release commit and matched.
- Wheel SHA-256 verified against [PyPI metadata](https://pypi.org/pypi/openhands-sdk/1.50.1/json): `a0a6f11a47802650aa50a68c60deefe3b8ace0dea1838893360358893ea23302`.
- Optional `spike` extra only; installation and tests ran in an external disposable virtual environment, with disposable workspaces and a loopback fake OpenAI-compatible gateway. No actual model, Kaggle, GPU, tunnel, cloud worker or model weights were used.
- Resolved Windows CPython 3.12 dependency snapshot: [requirements-windows-py312.lock.txt](../tests/spike/requirements-windows-py312.lock.txt), 139 packages including the SDK. This is the spike environment, not a portable production lockfile or a recommendation to ship the graph.
- Real APIs exercised: `LLM.completion`, `Agent`, `LocalConversation`, client tools, `AlwaysConfirm`, `reject_pending_actions`, injected `InMemoryFileStore`, real `LLMSummarizingCondenser.get_condensation`, `arun`, `interrupt`, and serialized `ActionEvent` IDs. The [`official SDK docs`](https://docs.openhands.dev/sdk) provide API context; assertions use the installed pinned package.
- The fixture clears LMNR/OTEL/provider-key environment variables, disables completion logging/visualization, isolates SDK persistence home, and denies external socket connections before SDK import. This is a test guard, not a shipped network sandbox.

## Hard requirement matrix

Passing a characterization test means its stated observation is reproduced. It does **not** turn partial coverage into a passed adoption gate.

| # | Requirement | Observed result | Gate |
| --- | --- | --- | --- |
| 1 | Every inference request through FreeCompute | Normal, retry, real condenser, and separately configured child-labelled LLM requests hit the controlled loopback gateway. Condenser and child/profile LLM configuration can independently change base URL. No production enforcement of every nested request/profile was implemented. | Partial; universal routing unproven |
| 2 | SDK tools cannot bypass broker | Agent tools/default tools/MCP omitted; a client-tool proposal paused without executing. No SDK terminal/browser/file/delegation executor was installed/enabled. Integration with executable broker result observations, hooks/plugins and recovery is incomplete. | Partial; restricted fixture safe |
| 3 | Missing approval denies | FreeCompute broker denied direct/child writes without callback; SDK `AlwaysConfirm` paused a pending client action and rejection preserved the workspace. SDK default is `NeverConfirm`, so unwrapped defaults are unsuitable. | Pass for configured proposal fixture |
| 4 | External telemetry disabled | `should_enable_observability()` was false; no external connections during ordinary run. Later real condensation attempted a tokenizer metadata download, blocked by the guard. This is not observed telemetry export, but means disabling observability alone does not make the whole dependency stack offline. | Pass for isolated observability fixture; broader egress unproven |
| 5 | Redact before all SDK sinks | Synthetic raw user input was already in the SDK event store when caller redaction callback ran. Gateway/output and pre-API input scrubbing kept a separate configured callback/store fixture clean. Default persistence precedes callbacks; default visualization precedes persistence. All raw-response/retry/error/stream/visualizer/child sinks have not been intercepted and tested. | Fail for defaults; complete adapter unproven |
| 6 | FreeCompute sole durable owner | Public `LocalConversation(file_store=InMemoryFileStore())` avoids an SDK disk ledger. The `Conversation` factory rejects `file_store`; using the public local class works. A core-owned durable store mapping and crash reconciliation are not implemented. | Partial |
| 7 | Pending state recoverable with stable IDs | Real pending ActionEvent round-tripped with stable event/tool-call IDs; FreeCompute DriverState also round-trips pending proposals. Full SDK conversation/process restart with policy revalidation and external tool-result reconciliation remains unproven. | Partial |
| 8 | Requested vs confirmed cancellation | Real async SDK `interrupt()` stopped `arun()` and emitted `InterruptEvent` with local paused state. FreeCompute distinguishes requested/local stop/remote acknowledgement. The fake backend still owns its in-flight work; no remote acknowledgement is inferred. Sync `pause()` is only a local transition. | Pass for local async observation; engine cancellation unknown |
| 9 | No partial malformed tool execution | Core proposal parser rejects fragments/nonobjects/duplicate IDs atomically; orchestrator also refuses incomplete/truncated streams and malformed JSON. No full native SDK malformed-fragment/repair/retry matrix was run with executable broker tools. | Partial; core guard verified |
| 10 | Narrower child permissions | Core broker rejects child widening and writes from read-only scope. A copied child LLM can change endpoints independently; native SDK delegation/grants/hooks were not integrated. | Partial |
| 11 | Single slot no delegation deadlock | Two real SDK inference calls, parent then child-labelled, completed while the fixture released one semaphore slot between them. This does not test native SDK delegation holding a parent lease; no scheduler was built. | Partial; native delegation unproven |
| 12 | Profile/cache invalidation | Core profile change clears pending proposals and advances context epoch; SDK model copies accept changed context limits. Engine KV-cache reset, resumed condensers and child profile changes are not governed by a production adapter. | Partial |

## Integration problems and dependency/license impact

The SDK requires a context window of at least 16,384 by default; the first 4,096-token fake profile was rejected. The final fixture uses 32,768, without disabling the check. SDK `num_retries=2` provides the fixture's initial attempt plus retry; `1` did not retry its first simulated server failure. The production FreeCompute retry behavior was not changed to match this SDK convention.

Client tools produce SDK acknowledgement observations; this is not automatically the real FreeCompute execution result. A safe adapter must pause, obtain a broker decision, and map the actual result back without premature success, stale approvals or replay. The fixture verifies a pending proposal and rejection, not the complete approved execution/recovery path.

`LocalConversation` offers public storage injection, and pre-API/gateway sanitization can address demonstrated sinks. These escape hatches mean the experiment has **not proven a deep fork is unavoidable**. Conversely, configured normal paths do not prove universal authority. That is why the decision is NEEDS MORE EVIDENCE rather than adoption or categorical rejection.

The pinned SDK root license is [MIT at the release commit](https://github.com/OpenHands/software-agent-sdk/blob/1e1390acc8788346ba4804c34323284009bf3f5e/LICENSE); its notice is preserved in [OPENHANDS_LICENSE.txt](../tests/spike/OPENHANDS_LICENSE.txt). Existing FreeCompute remains Apache-2.0. Dependencies include LiteLLM, MCP/FastMCP, Laminar/OpenTelemetry, Redis/Lua, tokenizers, tree-sitter and platform packages. The whole resolved graph's notices, vulnerabilities, portability and release-size impact have not been approved for production. Root SDK MIT does not establish licensing for every dependency/model/tool. No tools package, model weights or hosted OpenHands application was adopted.

## Validation and reproducibility

```powershell
python -m unittest discover -s tests/unit -p "test_*.py"
# In a disposable Python 3.12+ virtual environment:
python -m pip install "openhands-sdk==1.50.1"
python -m unittest discover -s tests/spike -p "test_*.py"
python tests/security_scan.py
```

- Existing plus new safety/driver unit suite: **81 passed**, no skipped tests.
- Pinned SDK fake-inference characterization: **15 passed**. One external connection attempt from real-condensation tokenizer metadata fetching was blocked, not silently allowed. No broad gate is declared passed solely because the suite is green.
- Package/import checks: a wheel was built from a temporary copy of the working source; wheel contents matched all 29 current harness Python files byte-for-byte, installation passed, installed `freecompute --help` passed, and 21 discoverable installed modules imported successfully from outside the repository.
- Repository pattern scan: no findings after final verification; this is pattern-scan evidence, not a guarantee that no secret can exist.
- No live GPU/model/Comfy/notebook/deployment validation. `main` remains at `1300566dca62a0f804487e7101767e688e551184`; no merge, PR, implementation push or deployment was performed.

## Next review decision

Review Stage 1 source/notebook changes and this matrix. If further OpenHands work is authorized, the next bounded test should be an approved broker tool-result round trip plus process restart using a FreeCompute-owned store, with enforced profile routing and pre-SDK sanitization for all normal/retry/condenser/child/stream/error paths. Run native one-slot delegation only after those ownership boundaries are demonstrated. Do not begin Stage 3 or evaluate another SDK without that review.

## Authorized follow-up evidence — 2026-10-02

**Tested:** actual public ToolExecutor observations now carry FreeCompute registry results and the SDK continues. Seven tool cases are covered. Normal/sync/async calls, retries and real condensation summaries route through the core broker with request/actor/task/profile/purpose/parent/timing records. A frozen wrapped profile rejects mutation; Responses API is explicitly unsupported and fails closed.

**Tested:** four real process crashes now recover without duplicate successful effects; pending/approved actions require fresh approval, interrupted execution is quarantined, completed results return without execution. The first restart attempt exposed a stale SDK active HEAD; a public projection reconciliation repaired the single linear fixture. This is not general branch or child recovery.

**Tested limitation:** public `switch_llm` to an ordinary SDK LLM sends a request without a core broker record. Provisioned wrapped profiles route correctly, but SDK-wide enforcement does not exist. A restricted facade must forbid plain profiles; a controlled URL alone is insufficient.

**Tested limitation:** native Delegate can use an explicitly registered child factory with a distinct core actor, read-only tool grant and wrapped inference; one slot completes without deadlock. However its child constructor drops the deny-capability workspace and core FileStore. Native child result size is unbounded, and its interrupt method does not propagate core cancellation automatically. Explicit shared core cancellation works but remote acknowledgement stays unknown.

**Tested limitation:** a raw registered fixture credential passed through the native Delegate task entry is logged and added to its own event store before brokered inference sanitizes it. The restricted adapter's input/output/tool/exception/fragment/display/persistence paths pass their scrubbing tests. This does not establish universal SDK redaction. Pre-sanitizing the native task would address that one sink; it does not restore the lost workspace/store boundary.

**Decision:** reject this pinned release as the general foundation within this experiment's scope. A deliberately restricted single-agent adapter works; the full required envelope has failed native-child authority/state and universal routing gates. No claim is made that every future SDK integration necessarily requires a deep fork. See the decision document for exact limits, verification and the next bounded candidate.
