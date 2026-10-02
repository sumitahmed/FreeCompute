# V1 engine and worker backend

2026-10-02. Authorized continuation from Stage 3 checkpoint
`aa15fc9fa87c45624acfc8eaf1aa5795f6603578` on
`v2/safety-and-agentdriver-spike`. Preserve Stages 1-3 and main.

## Starting evidence and scope

**Tested:** the unchanged starting unit suite passed 140 tests in 22.947 seconds.
**Observed:** Stage 3 has one attached engine/profile and one durable allocation;
the CLI already delegates authority to CoreService.

**Proposed for this authorized milestone:** interchangeable llama.cpp,
OpenAI-compatible and existing ComfyUI adapters; a small SQLite worker/profile
registry; durable FIFO inference requests and capacity/resource leases; useful
CLI worker/model/queue visibility. Tools, approvals and file recovery remain local.
No real model, GPU session, notebook execution or deployment is authorized here.

Keep profile identity independent of its eligible workers. Configured model
capabilities/context/resources are declarations until a pinned real profile is
tested. Generic OpenAI compatibility does not imply tool or cancellation support.
Network secrets/endpoints stay in local configuration/adapter memory, never in
registry rows or events. No discovery service, background daemon or extra engine
implementation for servers already using the compatible protocol.

Implementation and verification evidence will be recorded as it is produced.
