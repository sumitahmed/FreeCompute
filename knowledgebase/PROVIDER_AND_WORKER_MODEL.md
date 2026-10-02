# Provider and worker model

Proposed, 2026-10-02. Provider declarations below are future contracts, not verified support for every listed engine/location.

## Separate the axes

| Concept | Meaning | Example |
| --- | --- | --- |
| Location | Where compute exists and its lifecycle/policy | Local host, Kaggle notebook, private server |
| Worker | One authenticated compute identity at a location | User-attached dual-T4 runtime |
| Engine service | Inference API/process, not local tool authority | llama.cpp, vLLM, ComfyUI, opaque compatible endpoint |
| Transport | How the local broker reaches that service | Direct TLS, permitted private mesh, named tunnel |
| Model profile | Weights/revision/template/operation/configuration | Quantized coding model with measured context limit |
| Loaded allocation | Actual model instance with resource reservation | One llama-server instance across GPU0+GPU1 |
| Resource pool | Physical capacity shared by allocations/services | Both T4 devices, host RAM, service slots |
| Provider adapter | Typed operation-to-protocol implementation | ChatCompletion stream or Comfy prompt/history/view |

One worker may host several engine endpoints sharing the same GPUs. Several URLs can alias one engine. Neither case creates extra physical capacity. For opaque hosted endpoints, report capacity as configured/observed request limits, with GPU metrics `unknown`.

## Manifest and health

A worker manifest identifies stable worker ID, location, operator trust, persistent/ephemeral class, engine/version/boot ID, model allocations, GPU identities/VRAM, concurrency limits, supported operations, auth reference, transport reference, policy profile, and evidence references. No keys or ephemeral URLs belong in public examples.

Health observation records authenticated timestamp, last heartbeat, model state, engine process state, observed free VRAM/host RAM, queue/service slots, provider deadline/quota source, and measurement confidence. Stale observations mark a worker `unknown`; they cannot release a lease solely because a heartbeat expired. Worker states include disconnected, connecting, ready, busy, draining, degraded, expired, failed and unknown. Reconnect with a different boot ID invalidates old engine-request assumptions.

Lifecycle commands are distinct capabilities: attach/query, start/stop model, load/unload, restart engine, and provision/terminate compute. An existing compatible endpoint may allow only attach/query. Destructive controls require explicit authorization and scope. Notebook adapters must not imply that an API can start a permitted interactive GPU session until official support/policy is verified.

## Capability truth

Effective support is the intersection of **model operation**, **engine/API implementation**, **loaded assets and configuration**, **transport functionality**, **operator policy**, and **validated evidence**. A vision enum does not make a text-only GGUF understand images. ComfyUI image generation is a different operation from image input to an LLM.

| Operation/profile property | Evidence needed | Unsupported behavior |
| --- | --- | --- |
| Text generation | Template/tokenizer, stream and finish conformance | Reject before task admission |
| Tool calling | Real schema/fragment/arguments roundtrip, not just JSON-shaped prose | Use explicitly selected text-only workflow or another model |
| Reasoning behavior | Model-supported option/template; documented output handling | Do not append model-specific directives globally |
| Coding suitability | Versioned task/edit/test benchmark | Label measured/untested; not a routing guarantee |
| Vision input | Model projector/processor, media format and size test | No silent image dropping |
| Image generation | Workflow/node/weight manifest, auth/job/artifact roundtrip | Route to image job adapter, never chat method |
| Video understanding | Temporal/media limits, model/API verified | Separate from video synthesis |
| Video generation | Workflow/license/time/artifact contract | Queue as long job; no fabricated text substitute |
| Embeddings | Dimensions, normalization, tokenizer/model version | Keep index namespaces separate across models |

Unknown capability remains unverified. Prefer operator-confirmed manifests plus small conformance tests over asking the model what it can do. Catalog/model advertisements are not sufficient. Maximum context is the lesser of model, engine-per-slot, tested memory-safe profile and local policy limits.

## Engine adapters

Text adapters normalize event kinds, request IDs, tool fragments, usage, finish reasons, reasoning summaries where exposed, errors and cancellation acknowledgements. Chat Completions and Responses are distinct wire protocols. Support varies by pinned engine version; do not assume one “OpenAI-compatible” switch proves all APIs.

[Current llama.cpp docs](https://github.com/ggml-org/llama.cpp/blob/207bdab95010a0489e661bad8ca109c96aad46a8/tools/server/README.md) advertise chat/responses/embeddings, multimodal and continuous batching. Deployment profile, template, tokenizer, projector, cache type, slots and per-slot context still require verification. The old proof binary cannot inherit capabilities from today's documentation.

[vLLM's pinned serving documentation](https://github.com/vllm-project/vllm/blob/4056c8ac1f8a7e8fb50cf1c56ff96649fcadccc6/docs/serving/online_serving/openai_compatible_server.md) distinguishes model-dependent tool/API support and warns API-key auth does not cover all endpoints. Use a restrictive gateway, not a broad public engine listener. Treat vLLM hardware/model support as a separate tested profile; no promise that arbitrary large models/quantizations run on T4s.

ComfyUI uses a job adapter: submit workflow -> engine prompt ID -> correlated progress/history -> artifact metadata -> bounded authenticated download. Confirm workflow IDs, installed custom nodes and exact weight names/revisions. Engine-supplied filenames are not trusted paths. Stream events filter the job ID; timeouts/cancel/reconnect reconcile history before resubmitting. Retain remote artifacts until acknowledged download or a stated retention deadline, rather than deleting at an arbitrary 60 seconds.

## Physical admission

For a dual-T4 coding allocation, initialize one tested request slot. Account for model weights, per-device KV cache, activations, workspace/scratch and safety margin; sum VRAM alone is insufficient because allocations can be uneven across devices. Two requests at half-sized context are not automatically equivalent to one 64K request. Continuous batching can change measured capacity, not abolish it.

Track allocation memory separately from active-request leases. A loaded but idle model still occupies VRAM. A ComfyUI endpoint on the same devices either uses proven spare capacity or queues behind an explicitly authorized unload/reload transition. Measured free VRAM is advisory; engine-side OOM can still occur. Quarantine/reduce profile after repeated OOM; never retry indefinitely.

## Routing

Filter by user privacy/location allowlist, operation evidence, media limits, approved model profile and estimated lifetime. Rank eligible options by availability, queue delay, resource fit, quality evidence, cost/quota confidence and cache affinity. Return an explanation and route version. The user's Local-only constraint is absolute. Do not silently change location or disclose context to a new host when a worker fails.

Retries may choose another already-authorized worker for a replayable inference request, with a new attempt ID and explicit event. Tool side effects do not move to workers and are not retried by provider code. Model switching rebuilds context and invalidates incompatible cache assumptions.

## Transport and notebook policies

Preferred persistent-worker transport is direct authenticated TLS on a private network or a permitted private mesh. Named tunnels require explicit configuration, authenticated service endpoints, streaming tests and provider-policy review. Quick Tunnels are unsuitable as the default SSE transport because of the [published limitation](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/); no silent fallback from private mode to a public endpoint.

Kaggle is an optional user-attached ephemeral worker; quota/session boundaries are observed with source and uncertainty. Current policy/quotas were not extractable from the official pages during research, so must be checked against the account UI and official terms before enabling any deployment mode. Never implement keepalive, auto-account cycling, or quota bypass.

Colab support is conditional: [the official FAQ](https://research.google.com/colaboratory/faq.html) restricts managed-runtime uses including remote serving patterns, with additional free-tier restrictions. A compatible interactive/dedicated/self-hosted mode must be established; do not advertise the present free-tier tunnel notebook as an unattended worker solution.

Ephemeral worker expiration produces `waiting_worker`/failure with retained local state. Persistent homelab automation uses persistent workers; a notebook does not become reliable 24/7 infrastructure through a transport setting.
