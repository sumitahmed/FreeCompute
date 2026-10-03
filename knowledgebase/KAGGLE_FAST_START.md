# Current Kaggle text worker and reusable assets

2026-10-04. Canonical notebook: **`kaggle/freecompute_dual_gpu_server.ipynb`**.
`universal_dual_gpu_server.ipynb` is an identical compatibility copy. Root proof
and image notebooks are historical examples, not current authenticated V1 workers.

1. GPU **T4 x2**, Internet **ON**, Persistence **None**.
2. Enable Kaggle Secret `FREECOMPUTE_API_KEY`; match it in your local `.env`.
3. Optionally Add Input → your **own private** assets dataset from the builder.
4. Run code cells **1–8**, in numbered heading order. Stop on errors. Fresh-session
   Run All skips the final shutdown cell by default. Do not rerun setup/Run All
   while the CLI uses the worker. Save & Run All starts a different committed run.
5. Expect Cell 6 `SUPERVISOR HEALTHY`, Cell 8 `WORKER READY FOR LOCAL ACCEPTANCE`.
   On your PC: `freecompute --remote-url "PASTE-CELL-7-URL-HERE"`.
6. Keep Kaggle running. When finished, explicitly enable the **MANUAL SHUTDOWN**
   confirmation in Cell 9, run it, then click Kaggle **Stop Session**.

The temporary URL is shown only to the notebook owner and is never committed to
configuration. Streaming must be tested from your PC: [Cloudflare documents an
SSE limitation for Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).
Use a supported private or named-tunnel transport if your Quick Tunnel buffers or
rejects the stream. No GPU availability, free quota or startup timing is promised.

## Fast start

Cell 3 searches `/kaggle/input/**/freecompute-assets.json`. It checks the pinned
source SHA, SM75 build flags, Linux x86_64/glibc compatibility, all engine/library
SHA256 hashes, and the pinned GGUF repo/revision/filename/size/hash. It rejects
traversal, symlinks, changed/missing/unlisted engine files and incompatible manifests.
It copies a complete verified engine to writable scratch space; the GGUF can remain
on the read-only input mount. Cell 4 still probes `--version` and both T4 devices.
An engine-only dataset avoids compilation; a matching model dataset also avoids
the large model download. Hashing a large GGUF and loading it still take time.

No input is required. Cell 4 may use the existing checksum-pinned historical
GitHub Actions artifact. It is a build artifact, **not a published release**;
its historical availability is not guaranteed. Download unavailability falls back
to the exact pinned official llama.cpp source and the documented build flags.
An integrity/version/device failure stops immediately; it never executes an
unverified alternate download. A source fallback can take significant time.

## One-time builder

Upload **`kaggle/dataset_builder.ipynb`**. GPU T4 x2 / Internet ON supplies a CUDA
toolkit; the build makes no generation requests but consumes allocation time.
Run code cells 1–3 once, or Save & Run All. The default includes the pinned GGUF;
the documented advanced `DOWNLOAD_MODEL=False` option builds engine-only assets.
Save the complete `freecompute-assets/` output as a **private Kaggle dataset**,
including `engine/`, all shared/CUDA runtime libraries and `freecompute-assets.json`.
Attach that dataset to the server notebook using Add Input. Normal server setup
needs no Python edits.

The manifest records commit `2b129ccfa03aea330d2d9ac4650a10de393dbe3a`, architecture
75, CUDA/no-VMM/release/no-tests/no-curl/no-native build flags, observed engine
version, conservative builder-host minimum glibc, platform and per-file SHA256.
It records the pinned model revision and checksum if included. These are provenance
and integrity checks for an executable you trust, not a signature making any
third-party dataset safe.

For a CPU-only reproducible CUDA build, the checked-in
`.github/workflows/build_kaggle_llama_engine.yml` describes an Ubuntu 22.04 /
CUDA 12.4.1 development container, official pinned clone, CMake SM75/no-VMM flags
and full library packaging. Run that build in your own trusted environment, then
create the same schema-1 manifest using `kaggle/assets.py`; verify file hashes and
runtime compatibility before saving a private dataset. This pass does not dispatch
that workflow, publish a release asset, or claim a new GPU build was executed.

Tests execute dataset detection, checksum/path/library rejection, cached-engine
version/device checks and expired-download source fallback with local fakes. All
notebook cells compile and have empty outputs. Newly built CUDA binaries and the
revised notebook startup remain live-runtime manual checks.
