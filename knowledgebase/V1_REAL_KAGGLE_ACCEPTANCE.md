# V1 real Kaggle acceptance

2026-10-03. Preparation on `v2/safety-and-agentdriver-spike`, preserving backend
checkpoint `df091b0ba2e202647a2fb5daf7bf5c64050cecbe`. **Agent preparation has
started no Kaggle GPU session, tunnel, remote health request or real inference.**

**Runtime correction:** the user's executable cell 4 reported Kaggle
glibc **2.35**, while the official `b11206` CUDA archive requires **2.38**.
Cell 4 now downloads a CPU-built Ubuntu 22.04 / CUDA 12.4 / SM75 artifact of the
same pinned commit with `GGML_CUDA_NO_VMM=ON`. Its build and version check passed in
[GitHub Actions](https://github.com/sumitahmed/FreeCompute/actions/runs/37052624160).
The cell checks the ZIP and tar SHA256 values before extraction, then verifies
the commit and both T4 devices before model download. Actual Kaggle GPU execution
of this replacement remains unverified until the user runs it.

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

| Property | Requested profile, not freshly GPU verified |
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
| Auth / transport | Private bearer token / Cloudflare Quick Tunnel URL for startup checks; optional Tailscale Serve TCP for SSE |
| GPU memory | Must be freshly observed in code cells 2, 6 and 8; no fresh number yet |

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
  remove Cloudflare's documented Quick Tunnel SSE limitation. Startup and
  authenticated health/model checks can proceed, but streaming and downstream
  Core inference acceptance remain unverified or blocked on this route.
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
   No manual local harness command is required yet. The Cloudflare URL permits
   startup/health checks; its SSE limit blocks full streaming acceptance.
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

## Unverified real acceptance ledger

All real cases remain **Unverified — awaiting manual endpoint**: health/auth and
negative auth; model/profile/tokenizer/template visibility; stale/reconnected
health; short and incremental streaming generation; tool and multi-turn local
coding; progressively larger context; GPU memory; both-GPU admission/queue;
timeout/disconnect/interrupted stream/restart recovery; cancellation and actual
remote acknowledgement. No TTFT, token count, context pass or GUI-readiness claim
is made at this stage.

## Transport references inspected

- [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
  explicitly exclude SSE. This requested second route cannot complete the
  streaming acceptance; record that result as blocked, not passed.
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
