# V1 real Kaggle acceptance

2026-10-03. Live acceptance completed on `v2/safety-and-agentdriver-spike`, preserving backend
checkpoint `df091b0ba2e202647a2fb5daf7bf5c64050cecbe`. The user manually started
the Kaggle worker. FreeCompute has now used that worker for real inference and
local tool round trips. This continuation has not restarted Kaggle or changed
its model, engine flags, context allocation, or transport. The earlier preparation
consumed no GPU quota; that statement describes preparation, not today's live run.

**Runtime correction:** the user's executable cell 4 reported Kaggle
glibc **2.35**, while the official `b11206` CUDA archive requires **2.38**.
Cell 4 now downloads a CPU-built Ubuntu 22.04 / CUDA 12.4 / SM75 artifact of the
same pinned commit with `GGML_CUDA_NO_VMM=ON`. Its build and version check passed in
[GitHub Actions](https://github.com/sumitahmed/FreeCompute/actions/runs/37052624160).
The cell checks the ZIP and tar SHA256 values before extraction, then verifies
the commit and both T4 devices before model download. The user's worker now runs
this replacement and has completed real streamed responses. Full weight,
tokenizer/template and deployed binary hashes have not been independently fetched.

## Observed repository and historical profile

Use `kaggle/freecompute_dual_gpu_server.ipynb` from this feature branch after the
preflight fix. `kaggle/universal_dual_gpu_server.ipynb` is an identical wrapper,
kept synchronized so the older name does not select a broken startup procedure.
No separately generated notebook is required. The root
`qwen3-8-27b-abliterated-q4-kaggle-dual-t4-proof.ipynb` is preserved historical
evidence: it has no authenticated supervisor/transport for the Stage 4 client.
The dataset builder is not needed for this acceptance.

Stage 4 uses the existing supervisor's authenticated `/health`, `/v1/models`
and `/v1/chat/completions` SSE protocol via `LlamaCppEngine`. It needs explicit
worker/profile declarations to exercise Kaggle identity and both-GPU resources;
the old printed single-endpoint CLI command instead selects compatibility
attachments. No remote component executes local tools.

| Property | Configured profile; measurement limits below |
| --- | --- |
| Worker / profile | `kaggle-qwen` / `kaggle-qwen-historical-64k` |
| Location / engine | Kaggle Free dual T4 / llama.cpp |
| Engine commit | `2b129ccfa03aea330d2d9ac4650a10de393dbe3a` |
| Engine distribution | FreeCompute CPU-built Ubuntu 22.04 / CUDA 12.4 / SM75 artifact, SHA256 pinned; matching CUDA libraries included |
| Model repository | `huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF` |
| Model filename | `Huihui-Qwen3.8-27B-abliterated-UD-DW-Q4_K_M.gguf` |
| Model revision | `3f101cd22b7999228bbd5d79a33975414eb9758b` |
| Alias | `qwen3.8-27b-huihui-abliterated-q4` |
| Context / slots | 65,536 / 1; shared input-output capacity |
| Placement | all GPU layers (`999`), layer split, tensor split `1,1` |
| Batches / KV | batch 512, microbatch 128, K/V both f16 |
| Other flags | `--fit off --flash-attn auto --jinja --no-context-shift` |
| Tokenizer/template | Embedded GGUF identities; no override; exact hashes unverified |
| Pool / resources / concurrency | `kaggle-dual-t4` / `gpu0`, `gpu1` / 1 |
| Auth / transport | Private bearer token / current Cloudflare Quick Tunnel; real SSE observed on this session, vendor support caveat below |
| GPU memory | Context runs observed CUDA0 9,193 MiB and CUDA1 10,309 MiB used, each 15,360 MiB total |

The historical handoff distinguishes the saved 32K proof notebook from the
user-reported later 64K allocation and 46,722-token synthetic recall. Neither
is new Stage 4 acceptance evidence. Preserve the 64K server allocation but start
actual inference with short inputs, then grow conservatively. Stop on load/OOM
failure; do not silently change context, weights, template or flags.

## Confirmed preparation defects and bounded fixes

- Both wrappers advertised Run All despite a final cell that stopped inference.
  Instructions now require code cells 1-8 individually; shutdown requires an explicit
  `CONFIRM_SHUTDOWN = True`. Startup/configuration/transport refuse active reruns.
- The first downloadable engine was an official CUDA 12.8 archive requiring
  glibc 2.38 / GLIBCXX 3.4.32. The user's Kaggle runtime reported glibc 2.35,
  so it could not load that archive. A CPU-only GitHub runner now builds the
  historical commit on Ubuntu 22.04 using GNU 11.4 and CUDA 12.4 for SM75.
  Code cell 4 downloads this artifact; it never builds on Kaggle or upgrades
  Kaggle's system libraries. Both ZIP and inner tar are SHA256 pinned; extraction
  rejects unsafe paths and the version/both-T4 probes stop on a mismatch or load
  failure. No CPU fallback or alternate engine version is selected. No inputs
  are needed. The first external job compiled successfully but failed packaging
  because `find` did not follow `/usr/local/cuda`; the corrected job passed.
- The compatible build enables the historical `GGML_CUDA_NO_VMM=ON` alongside
  CUDA and architecture 75. It also uses Release, `GGML_NATIVE=OFF`,
  `LLAMA_BUILD_TESTS=OFF`, and `LLAMA_CURL=OFF`. Model retrieval stays in Python.
  Cell 8 records the build run, archive fingerprints and observed CUDA devices.
- The user requested a Cloudflare URL as an alternative and does not want to use
  Tailscale for this run. The notebook now defaults to a Cloudflare Quick Tunnel;
  it requires only `FREECOMPUTE_API_KEY` in Kaggle Secrets. HTTP/2 does not
  remove Cloudflare's documented Quick Tunnel SSE limitation. Nevertheless,
  today's exact endpoint passed real SSE through CoreService, including a tool
  round trip. Record this as observed behavior of this session, not a vendor
  support guarantee or an inference that every Quick Tunnel supports SSE.
- The userspace Tailscale node had only an outbound SOCKS proxy, no explicit
  inbound forwarding, and missing auth silently selected a public tunnel.
  Tailscale remains an explicit optional mode with Serve TCP forwarding and its
  own required secret. There is no silent fallback between modes.
- A verification health request omitted required bearer auth. Readiness now
  authenticates health/model queries, checks readiness and alias, and has bounded
  timeouts. It issues no competing model generation during local acceptance.
- Keys were printed and embedded in suggested shell commands. Retrieve the
  bearer key from Kaggle Secrets and the Tailscale key only when its mode is
  selected. The notebook embeds the existing `SecretScrubber` for presentation;
  Tailscale passes its key via a temporary 0600 file and removes it after login.
  The Cloudflare URL is shown only at runtime and not placed in a saved log.
  No key is printed, stored in the notebook or placed in argv.

The canonical supervisor is unchanged and remains byte-identical to both embedded
copies. Model/quantization/revision/context/tensor split/engine flags are unchanged.
Dataset caches remain an opt-in historical convenience, not a verified acceptance
asset source. This pass does not certify raw upstream logs or external programs.

## Compatible engine artifact

Build run `37052624160`, repository commit `8e3cf74`, artifact `11247636682`:

- ZIP SHA256: `71487cea2572f9cd694f542b46598c612040d54c0199465eeaaef4aaff75b50a`.
- Inner tar SHA256: `c84d19cd871094f5a3cba730680bc23e969c667c5122aa408c4b7f38989ae0c0`.
- Download size: 445,007,258 bytes. The package includes the engine's shared
  libraries plus `libcudart.so.12`, `libcublas.so.12`, and `libcublasLt.so.12`.
- [The successful build](https://github.com/sumitahmed/FreeCompute/actions/runs/37052624160)
  checked the full source SHA, compiled on Ubuntu 22.04 and ran `--version`,
  observing `0.5.0-dev (build 1, commit 2b129cc)` / GNU 11.4.0. This CPU check
  does not test CUDA device execution, model load or inference.
- The ZIP digest comes from GitHub's artifact metadata and the tar digest from
  the successful packaging log. A public GET returned the expected artifact
  size. Local tests use fixtures; a partial local mirror download was stopped
  rather than treated as full archive checksum or ELF inspection evidence.
- [nightly.link](https://nightly.link/) supplies anonymous downloads of the
  exact GitHub artifact; no GitHub key is added to Kaggle. The expected hashes
  are fixed in cell 4. The artifact expires **2026-10-10 00:58 IST**; on expiry,
  rebuild off GPU and update the artifact identity/checksums before acceptance.

## Manual procedure

For the requested Cloudflare URL route, before allocating GPU time:

1. Choose a private random bearer token. Store it locally in the repository's
   ignored `.env` as `FREECOMPUTE_API_KEY=...` (preserve other entries). Do not
   commit or paste it into notebook source.
2. Upload the current `kaggle/freecompute_dual_gpu_server.ipynb` from this feature branch.
   Keep it private. In Kaggle's Secrets UI, add and enable `FREECOMPUTE_API_KEY`
   with the same bearer value. `TAILSCALE_AUTHKEY` is unnecessary in Cloudflare mode.
3. Set Accelerator **GPU T4 x2**, Internet **ON**, Persistence **None**. Attach
   **no datasets/inputs**. Start the interactive session only when ready.
4. Run code cells **1, 2, 3, 4, 5, 6, 7, 8**, individually, in order.
   Use the code-cell heading numbers; the introductory Markdown is not counted.
   Code cell 1 is MODEL SELECTION & RUNTIME CONFIGURATION. Stop on an error; report the redacted error.
   Cell 4 downloads about 445 MB, including the engine's shared libraries and
   matching CUDA runtime libraries; no compiler is needed. It must
   print `ENGINE DOWNLOAD VERIFIED; BOTH T4 GPUs DETECTED.` before continuing.
   For an already-uploaded notebook whose cells 1-3 finished successfully, paste
   the entire contents of `kaggle/download_llama_engine.py` into code cell 4.
   Run that replacement cell, then continue with cells 5-8. Do not replace the
   engine while the worker is running. Updated uploads include this cell already.
5. Code cell 6 must print `SUPERVISOR HEALTHY ON PORT 8081`; code cell 7 prints
   `CLOUDFLARE QUICK TUNNEL ONLINE` and the temporary `Remote URL`.
   Code cell 8 must print the manifest and `WORKER READY FOR LOCAL ACCEPTANCE`.
6. Return the code cell 7 remote URL, code cell 8 manifest, and confirmation
   that the bearer token is in the local `.env`. Do not send the bearer token.
   No manual local harness command is required yet. Verify streaming on the
   actual returned endpoint. Today's session passed SSE; the vendor's documented
   Quick Tunnel limitation still prevents treating that as universal support.
7. Leave the interactive session running for the bounded checks. **Do not Run All, Save
   & Run All, rerun code cells 1-7, run inference probes, restart the kernel, or run
   code cell 9 while FreeCompute uses the worker.** After acceptance finishes, set
   `CONFIRM_SHUTDOWN = True`, run code cell 9, then click Kaggle **Stop Session**.

A stopped model or disconnected CLI is not a stopped Kaggle GPU session.
Account quota/settings/permission and actual tunnel reachability remain external
observations. A local ready marker does not prove Windows-to-Kaggle connectivity.

## Local composition after the endpoint is returned

Codex will read the private bearer locally without printing it, register it with
the scrubber, and set `FREECOMPUTE_API_KEY` in the acceptance process. Explicit
worker `api_key_env` reads process environment, not the CLI loader's `.env` map;
do not assume `.env` alone populates explicit worker credentials. Populate an
ignored local config from these declarations with the returned URL:

```yaml
selected_profile: kaggle-qwen-historical-64k
selected_worker: kaggle-qwen
transport: cloudflare
request_timeout_seconds: 900
model_profiles:
  - profile_id: kaggle-qwen-historical-64k
    model: qwen3.8-27b-huihui-abliterated-q4
    engine: llama.cpp
    capabilities: [text, code_tools]
    context_capacity: 65536
    reserved_completion: 2048
    resource_requirements: [gpu0, gpu1]
    verification: unverified
workers:
  - worker_id: kaggle-qwen
    location: kaggle
    engine: llama.cpp
    url: http://127.0.0.1:8081 # replace locally with the returned Cloudflare URL
    api_key_env: FREECOMPUTE_API_KEY
    profiles: [kaggle-qwen-historical-64k]
    concurrency_limit: 1
    resource_pool: kaggle-dual-t4
    resources: [gpu0, gpu1]
```

Use a new temporary local workspace for the approved edit/test task. The eventual
CLI command, once private config and process environment are populated, is
`python -m harness.cli.main --config config.yaml --workspace <acceptance-workspace>`.
It is not a prerequisite for returning the connection details, and must not be
started alongside another core owning the same workspace. Local tool effects
still require their individual interactive approvals.

## Freshly tested locally

- Full unit suite: **205 tests passed in 50.284s**, including sixteen notebook
  regressions. Existing authenticated loopback CLI/engine and process recovery
  integration cases run as part of that suite.
- Sixteen focused notebook tests passed in 0.536s: wrapper/canonical equality,
  code compilation, retained profile, redaction, checksummed download/cache reuse,
  archive path rejection, engine identity and CUDA detection, runtime failure,
  acceptance of Kaggle glibc 2.35, pre-download glibc guard, active-worker guard,
  ZIP path/checksum manifest rejection,
  private TCP forwarding/key-file cleanup, transport failure cleanup,
  authenticated readiness/degraded rejection, guarded startup/shutdown,
  optional Tailscale secret selection, and Cloudflare URL capture without a log.
- The first full run in the restricted sandbox failed because Windows AppData
  owner-state writes were denied (11 failures, 58 errors). The authorized rerun
  with normal filesystem access passed all 199; no test assertion was weakened.
- All code cells compile; notebook JSON parses; no saved outputs/execution
  counts. `nbformat` is not installed, so its library schema validator was not
  run. No actual Kaggle execution is implied.
- Documented YAML validates through `HarnessConfig` and composes one Stage 4
  llama.cpp attachment requiring both GPU resources with fixture credentials,
  without network calls.
- Repository scanner: **482 files** (including local inspection files), zero
  configured secret-pattern findings.
  `git diff --check` passes. This is bounded pattern scanning, not perfect DLP.
- No packaged `harness` production file changed; fresh wheel/install checks are
  not repeated for this notebook/documentation/test-only patch.

Notebook control paths use local fakes; they do not execute CUDA, download model
weights, start a tunnel or launch an inference worker. The user selected the
Cloudflare route; no local Tailscale installation is required for its startup checks.

## Historical pre-live acceptance ledger

Before the user supplied the endpoint, these cases were **Unverified**: health/auth and
negative auth; model/profile/tokenizer/template visibility; stale/reconnected
health; short and incremental streaming generation; tool and multi-turn local
coding; progressively larger context; GPU memory; both-GPU admission/queue;
timeout/disconnect/interrupted stream/restart recovery; cancellation and actual
remote acknowledgement. No TTFT, token count, context pass or GUI-readiness claim
was made at that preparation stage. The live results below supersede only the
specific cases actually exercised; older fixture and notebook evidence remains historical.

## Live evidence — 2026-10-03

Acceptance completed on the user-started worker. Baseline authenticated health,
both Tesla T4s, model discovery and a streamed `READY` through Stage 4 were already
observed (~3.219 seconds first token). Those baseline generation checks were not
repeated in this continuation. Private artifacts live outside the repository in
a disposable Windows temporary directory; no URL or credential is committed.
The ignored local pointer is `scratch/v1-live-20261003/location.json`; case
reports are `<temporary-root>/<case>/report.json`, with local SQLite receipts
stored by the production runtime outside the repository/workspace.

- **Local read / real tools:** completed in 18.531 seconds across two model turns.
  The model proposed `read_file` for `probe.txt`; the local Core executed it and
  returned a durable receipt. The model subsequently quoted its exact marker.
  Server usage recorded 959 then 1,068 input tokens; both streams ended completely.
- **Coding agent / multiple turns:** the same saved task completed four real
  model turns and three model/tool/model cycles: read both Python fixtures,
  propose the `//` to `/` edit, propose the test command, then report its result.
  Both the edit and `python -m unittest -v test_calculator` received separate
  explicit user approvals through the local permission resolver. Four local tool
  receipts completed; the command exited 0 and all three tests passed. Its owned
  process exit was confirmed, duration 359 ms; tests remained byte-identical.
  Actual input tokens across the four turns were 1,270 / 1,732 / 1,919 / 2,128;
  completion tokens were 78 / 117 / 61 / 132. Network attempt times were
  11.753 / 12.305 / 11.325 / 11.764 seconds (47.147 total), final TTFT 1.907 seconds.
  Approval waits and waiting for an updated address are excluded from those
  attempt times; they are not model latency. The edit was not replayed after
  local Core recovery, even though its old approval expired on recovery.
  Files and the Python process belonged to the disposable Windows workspace
  outside FreeCompute. Kaggle received inference messages and tool schemas;
  local approvals, file changes, command execution and receipts remained in Core.
  No remote filesystem/command endpoint or shared local workspace was used.
- **Scheduler / both-GPU resources:** while a real 50-line inference was streaming,
  a second submission remained queued with zero inference attempts. There was one
  active lease and two exclusive claims (`gpu0`, `gpu1`). Direct admission returned
  `capacity busy`. After completion, allocation became idle, `/run-next` completed
  the second request, and claims were empty. Total case time: 97.735 seconds.
- **Reconnect:** a disposable loopback forwarding route to the existing worker
  was stopped before dispatch, making the worker unreachable. The task queued
  without an upstream inference call. Restoring the same local listener made it
  healthy and the queued task completed. Kaggle was not restarted. This verifies
  loss/recovery of a client route before dispatch; it is not a mid-stream Cloudflare
  outage or a remote process restart test.
- **Cancellation / restart fencing:** after the correction described below,
  a request for 150 lines was cancelled during its twelfth real reasoning event,
  before final text or completion. Case wall time was 5.578 seconds; first streamed
  token observation 2.625 seconds. The recorded delay from cancellation to local
  return was 0.000 seconds at the Windows timer's resolution, not a guarantee of
  zero latency. `requested=true`, `local_stop_confirmed=true`,
  `remote_cancel_confirmed=false`, and `remote_outcome=unknown`. No terminal usage
  receipt arrived. Both GPU claims stayed quarantined, the next task paused with
  zero attempts, and reopening the local Core retained the claims with no second
  POST. There was no remote cancellation acknowledgement and no idle inference
  from healthy status or low utilization. The final unknown lease remains held
  in the disposable acceptance store; no further GPU generation was attempted.
- **Context:** progressively tested the unchanged 65,536-capacity profile, with
  beginning/middle/end sentinel recall successful at every dispatched size.

| Case | User input UTF-8 bytes / characters | Actual server input tokens | Completion tokens | TTFT seconds | Wall seconds | Peak VRAM MiB, CUDA0 / CUDA1 | Outcome |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Short | 1,196 | 823 | 139 | 1.750 | 14.609 | 9,193 / 10,309 | Complete; three markers correct |
| Medium | 16,196 | 3,085 | 176 | 8.719 | 24.953 | 9,193 / 10,309 | Complete; three markers correct |
| Large | 60,196 | 9,714 | 113 | 30.328 | 41.203 | 9,193 / 10,309 | Complete; three markers correct |
| Local boundary | 70,196 | Not dispatched | None | None | 1.281 | 9,193 / 10,309 | `context_overflow`; zero inference attempts |

Actual token counts include the system prefix and chat framing; user bytes do
not. Large-case serialized message bytes were 62,807, HTTP request body 62,966.
The conservative local budget counted 62,806 input units plus 2,048 reserved
completion units (64,854 of 65,536). The larger candidate counted 72,806 plus
2,048 and was rejected. This UTF-8-byte estimate is intentionally not a verified
tokenizer. No budget bypass was used to claim a full 65,536-token pass. No OOM,
degraded health, or VRAM growth was observed in the three dispatched cases.

**Discovered fixes:** the client omitted `stream_options.include_usage`, leaving
the earlier READY usage null. It now requests usage using the pinned engine's
supported schema. A regression uses an empty-choices terminal usage chunk and
checks actual counts reach the client. The live read and context cases confirmed
the fix against the unchanged worker. At that checkpoint the full local suite passed **206 tests
in 29.063 seconds** after this change; the focused client and engine/CLI suites
also passed (5 and 12 tests). Older package/install evidence above is historical;
no new wheel was certified for this client change.

The first cancellation probe instead exposed a stream-accounting defect: after
1,001 reasoning events (5,668 UTF-8 reasoning bytes persisted), the broker's
65,536-byte allowance was exhausted by repeatedly counting its own JSON field
names on every packet. It failed after 111.469 seconds, before the text-only
cancellation trigger fired. This was a failed probe, not a cancellation pass.
Its unknown outcome correctly quarantined both claims and survived local restart
without redispatch. Text/reasoning accounting now counts their UTF-8 payload;
structured tool fragments remain byte-bounded. The allowance, global cap, SSE
line bound, deadlines and quarantine rules were not raised or disabled.

A regression reproduced the false failure for the same 7,500-byte output split
into smaller packets. It passes after the fix. Further regressions verify
oversized UTF-8 reasoning still quarantines and oversized tool fragments cannot
reach approval/execution. A fourth regression preserves quarantine when even an
empty packet precedes an adapter's later not-started error; packet observation
is tracked independently of payload size. All **30 runtime tests passed in 2.819 seconds**; the
required full command `python -m unittest discover -s tests/unit -p "test_*.py"`
finally passed **210 tests in 42.947 seconds**, without weakening existing assertions.

One full run exposed a Windows loopback fixture issue: the fake authentication
server left its POST body unread and the client observed connection abort
`WinError 10053` instead of the intended 401. Quarantine on that transport error
was correct. The fixture now drains the body before returning 401, retaining its
original assertions and adding a `remote_outcome=not_started` receipt witness.
The preceding modules plus this case passed together (17 tests in 1.895 seconds)
before the successful full run. The tracked-file secret scan covered 150 files,
found no configured pattern matches, and confirmed the actual local key was
absent from tracked content. Runtime URLs/keys remain private and ignored.

The user supplied an actual read-only Kaggle `/slots` observation:
`[{'id': 0, 'is_processing': False}]`. That observation supported explicit
reconciliation of the exact failed probe's lease; it was not a cancellation
acknowledgement. The queued diagnostic was cancelled locally without dispatch.
Only then was cancellation retried, counting either text or reasoning as real
stream progress. The successful retry above used the same model/profile/flags.
The initial probe and operator reconciliation records are retained separately as
`cancellation/report-before-stream-accounting-fix.json` and
`cancellation/operator-idle-reconciliation.json`.

The saved tunnel hostname also stopped resolving between the coding edit and its
next model turn while GitHub/Cloudflare DNS still resolved. FreeCompute queued the
turn without another inference attempt. The user supplied the current tunnel
address; only the ignored local connection URL changed. The same task then
continued from its completed edit receipt. No model restart/configuration change
or repeat of the already-passed baseline generation was performed.

## Acceptance decision and remaining boundaries

**Accepted for GUI development within the bounded V1 contract.** Real inference,
streaming, local read/edit/approved command, multi-turn continuation, single-store
both-GPU admission, cancellation fencing, progressive context and safe reconnect
have passed. No unresolved correctness blocker remains for a GUI client of the
existing Core. No GUI code was started and no merge to `main` is part of this pass.

Remaining backend/release gates are explicit:

- Full 65,536-token input capacity remains unverified; the largest actual input
  was 9,714 tokens. Keep the conservative byte budget and distinguish declared
  capacity from measured evidence until tokenizer-aware/full-context acceptance.
- Remote cancellation acknowledgement is unavailable. The GUI must show an
  unknown remote outcome, retained claims and explicit idle reconciliation;
  a local stop or healthy probe must not clear it automatically.
- Quick Tunnel streams worked in this session, but this does not certify stable
  transport service or broader transport/profile compatibility.
- Exact deployed weight/binary/tokenizer/template hashes and license review,
  a fresh release package and broader engine/hardware acceptance remain separate
  release work. Resource fencing remains local to one Core/store; other
  workspaces and external programs are outside that authority.

All live tests are finished. The user can shut down the Kaggle session. A later
run must establish a fresh worker connection and resolve any retained unknown
lease explicitly rather than reusing it as proof of remote completion.

## Transport references inspected

- [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
  explicitly exclude SSE. This describes documented support. Today's observed
  successful SSE cases are recorded separately; they do not change vendor policy.
- [Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve)
  documents private raw TCP forwarding. The retained 1.76.6 CLI implementation
  supports `serve --bg --tcp` and `up --auth-key=file:...`:
  [Serve source](https://github.com/tailscale/tailscale/blob/v1.76.6/cmd/tailscale/cli/serve_v2.go),
  [login source](https://github.com/tailscale/tailscale/blob/v1.76.6/cmd/tailscale/cli/up.go).
- [Pinned llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/2b129ccfa03aea330d2d9ac4650a10de393dbe3a/tools/server/README.md)
  matches the existing flags. This is static protocol evidence, not deployment.
- [Kaggle notebooks](https://www.kaggle.com/docs/notebooks) yielded no readable
  policy text to the research tool. No provider-policy or account-quota claim is
  inferred from that page or historical runtime assumptions.
