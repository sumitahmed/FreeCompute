# GUI and landing/documentation direction

## Current product decision — 2026-10-03

GUI is **DEFERRED / ABANDONED FOR V1**. The user chose the CLI as the V1 product
and abandoned the separate `v1/gui` experiment. Its frontend/API code is not part
of `v1/cli-release`, which begins at accepted backend `755e944`. No GUI, desktop,
website, API server, installer or deployment work is authorized by the final CLI
pass. The design material below is preserved as historical research for a later
decision. Current handoff: [V1_RELEASE_READINESS.md](V1_RELEASE_READINESS.md).

Research/design only, 2026-10-02. No GUI, website, screenshots, deployment or frontend scaffold was created.

## Lessons from inspected products

Codex app-server separates clients from runtime protocol and approvals; OpenCode exposes server/session services; Cline SDK separates local/Hub hosts from agents; Pi RPC drives agent-session independently of its interactive UI. OpenHands exposes application API clients separately from its SDK agent runtime. These support one FreeCompute core with several clients. They do not establish permission to copy product branding, proprietary UI assets, or whole desktop implementations. Pinned sources are in [RESEARCH_EVIDENCE.md](RESEARCH_EVIDENCE.md).

## GUI target

Recommend a local browser dashboard backed by the optional authenticated core daemon after CLI/API contracts stabilize. It is easy to attach/detach and avoids requiring desktop packaging for the first GUI. Desktop shell and VS Code client remain later options; evaluate OS integration, signing/update cost and approval UX before choosing. The dashboard must not require a hosted account or upload workspace state.

Proposed workspace screen:

```text
Workspace / session     | Local-only constraint | Worker/model choice
Tasks and agent tree    | Conversation + truthful ordered timeline
Queued/running agents  | Tool proposals, reviewed diffs, approval controls
Workers and models     | Context/usage, artifacts, tests and outcomes
Skills and knowledge   | Detail drawer: provenance, freshness, safe logs
```

This is an information layout, not an implemented mockup. The core publishes all displayed states; the UI does not infer “thinking,” progress percentages, GPU release or successful tests from silence.

| Surface | Behavior |
| --- | --- |
| Worker/model picker | Separates location, engine and loaded profile; shows validated operations, policy/privacy and unavailable reasons |
| Worker panel | Ready/degraded/unknown/expired, authenticated measurement timestamp, tested slots, queue and observed VRAM |
| Agent tree | Parent/child/independent identity, goal, model route, queue vs inference/tool/approval wait, cancellation status |
| Timeline | Sequence-backed events with elapsed spans, tool outcomes and recoverable reconnect cursor |
| Approval | Exact target/diff/command/scope and revision; approve/deny; detect drift before execution |
| Context inspector | Rendered/estimated token budget, response reserve, selected sources, compaction provenance, prefix version |
| Skills | Source/version/arguments, effective tool subset, unmet capability and approval requests |
| Knowledge | Proposed versus promoted entries, evidence citations, review diff, freshness and scope |
| Artifacts/logs | Correlated task/job IDs, bounded authenticated downloads, sanitized previews and retention |
| Session controls | Resume/cancel with acknowledgement state; disconnect differs from cancelling daemon work |

Accessibility: keyboard-first approvals/navigation, screen-reader event summaries, no color-only states, clear responsive diff reading, stable focus while streaming and reduced motion. Show queue wait separately from TTFT/decode and never count chunks as tokens. GPU/session/quota fields say unknown or estimated when appropriate.

## Positioning

Headline direction: **Open-weight agents. Your workspace. Your choice of compute.** Supporting copy explains local authority and optional remote inference. Do not promise unlimited free GPUs, perpetual notebook sessions, guaranteed sub-second responses, universal model support, refusal-free quality, or zero remote traces. “FreeCompute” is a product name, not a guarantee that every provider is free.

Audience: developers with local models, notebook experimentation, private GPU machines, or homelab workers who want reviewable coding/media workflows. Explain the supported first release narrowly. Capability/engine/model compatibility is a versioned evidence matrix, not a catalog of unsupported logos.

## Site information architecture

| Page | Content and evidence |
| --- | --- |
| Home | Product promise, local/remote boundary diagram, tested workflow, primary install/docs links |
| Getting started | Supported OS/runtime, local-first setup, attach existing model, approved read/edit/test walkthrough |
| Providers/workers | Engine vs location distinction, tested profiles, policy and transport prerequisites |
| Agent workflows | Single task, bounded children, queue states, permissions and recovery examples |
| Skills and memory | Portable manifests, argument examples, reviewed promotion, trust and privacy |
| Security/privacy | Data sent to workers, local tool authority, execution modes, secrets, retention and reporting |
| Reference | CLI commands, config precedence, API/events, errors, manifests and compatibility versions |
| Troubleshooting | Auth, unsupported capability, transport/SSE, stale worker, OOM, context overflow, cancel uncertainty |
| Architecture/contributing | Public design, license notices, development checks, SDK integration rationale |
| Releases | Reproducible artifacts/checksums, migration notes, benchmark provenance and limitations |

Use a static documentation framework with accessible search and Markdown sources; choose the actual stack only when implementation is approved. Avoid embedding a second agent backend into the marketing site. Keep release docs synchronized with shipped behavior and link research proposals separately.

## Install and demo flow

Provide a lightweight pinned CLI package with optional SDK/MCP/image extras, OS-specific prerequisites, and readable install steps. No default installer should download large models, open public tunnels or execute a remote one-liner without showing its scope. First setup attaches a user-chosen endpoint and validates auth/capabilities; local/no-remote mode is visible.

Remote onboarding is a separate guide: privacy disclosure, applicable provider policy, reproducible deployment manifest, secret setup, authenticated health and streaming/tool/cancel tests. Notebook setup is optional and cannot block the local/private-server quickstart.

Future screenshots/demo should show an actual supported release completing a bounded read/edit/test, a queued child on a single slot, a denied tool, recovery after reconnect, and a reviewed memory proposal. Remove real paths/credentials/output and disclose model/engine/OS/version. A marketing demo can replay sanitized fixture events, clearly labeled as a replay; it must not silently invoke arbitrary tools or pretend a model is live. Hosted interactive demos need separately scoped infrastructure and approval.

Reuse the Markdown architecture diagram as a first explanatory asset. Any later interactive diagram must show trust and physical resource boundaries, not imply every agent has its own GPU. Current `.archify` receipts certify diagram rendering only and should not serve as runtime evidence.
