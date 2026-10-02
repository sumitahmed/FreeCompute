# V2 security model

Proposed, 2026-10-02. The [current audit](CURRENT_ARCHITECTURE_AUDIT.md) identifies defects that are still present. This document is not a statement that they were fixed.

## Trust boundaries

Trusted local authority comprises the authenticated user, explicit grants, workspace policy, tool broker, state store and secret resolver. Models, remote workers, fetched pages, repository instruction files, skill packages, tool output, MCP servers and generated summaries are untrusted inputs. Remote compute is inference-only and receives only approved context/media; it cannot access local filesystem or terminal handles.

An approved remote route is a data disclosure decision. TLS protects transport, not the remote operator's memory/logs. Notebook scratch paths and deletion scripts do not prove confidentiality or zero trace. Keep source provenance and distinguish trusted user instructions from quoted external text to limit prompt injection; local enforcement remains necessary even if the model follows hostile text.

## Permission enforcement

Put fail-closed authorization in `ToolBroker`, independent of CLI, SDK, plugins or agent role. Every invocation, including nested tools, MCP, undo, snapshotting, scheduled jobs and child agents, passes through it. Preserve explicit interactive approval for edit/write/command operations. Missing approval handler, disconnection or timeout does not authorize execution.

Approval records bind user/agent/task, tool/schema version, canonical target, exact args/diff, preimage hash, command/environment/network scope, policy revision, expiry and single-use/bounded-use status. Revalidate immediately before side effect. Changed files or arguments require a new review. Hard denials cannot be overridden by a skill or model risk score. Narrow standing grants are possible only through deliberate user authorization; defaults remain interactive.

Children inherit the intersection of parent and child scope. Never mutate a global permission object to allow all child tools. Third-party tool annotations and a model saying a command is read-only are advisory, not policy.

## Filesystem and undo

Resolve roots/targets using OS-aware canonical identity and case rules. Block sensitive filename families, not just `.env`: protected directory variants, credentials, key files and alternate secret names. Validate each recursive-search/list/read target and every traversed link; follow no link outside scope. Bound file/result sizes and binary reads. Reject unsafe UNC/device/alternate-stream/reparse-point cases on Windows unless explicitly supported by a reviewed backend.

Avoid check-then-open races where possible with handle/relative-directory operations and revalidation. If a platform cannot establish containment, return an actionable denial rather than claim sandboxing. Listing metadata and pre-change snapshots are reads requiring the same boundary. Restore is a write requiring fresh checks; persisted paths are untrusted.

Use unique immutable snapshot IDs, hashes, atomic replacement and expected-state checks. Never use integer timestamp plus path as sole identity. Missing/corrupt backups fail safely. If another task or the user edited a file, undo produces a conflict instead of overwriting unrelated work. Git changes, deletes, network operations and arbitrary shell commands do not become reversible merely because a file undo ledger exists.

Byte-exact authorized snapshots are private data, not logs; scrubbing their contents would corrupt restoration. Store them outside the repo/sync tree with restricted ACLs, bounded retention and an explicit encryption/secret-retention policy. Protected secret files cannot be snapshotted through ordinary editing tools. Display only scrubbed previews and safe hashes; never export raw backup payloads in diagnostic bundles.

## Process execution

Cwd guards and command substring filters are not a process sandbox. An approved command can read/write host files and contact networks with the user's identity unless an OS/container isolation backend constrains it.

Separate modes: explicitly approved trusted-host execution, and an isolated backend with declared filesystem/network/environment mounts. Label the mode truthfully. Windows needs process-tree ownership/cancellation and tested isolation; evaluate Job Objects for process lifetime, but do not equate them with complete filesystem/network confinement. Container/WSL execution has its own mount/secrets boundary. Do not claim a universal sandbox before OS acceptance tests.

Default process environment is a minimal allowlist. Resolve approved credentials only for the specific operation, redact stdout/stderr, bound captured output, and do not place tokens in command-line arguments or shell history. Structured argv is preferred; shell syntax is allowed only as the reviewed command in an explicitly approved backend. Cancellation kills owned descendants and records uncertain effects; detached processes need a separately approved lifecycle.

## Web, MCP and plugins

Web tools validate schemes, redirects, resolved addresses, egress grants, response sizes, MIME types and timeouts. Deny private/link-local/metadata networks by default for untrusted fetches; explicitly configured private inference endpoints are a separate allowlisted transport role. Revalidate redirects and DNS results to reduce rebinding risks.

MCP is a protocol, not an authorization or isolation boundary. Gate server installation/start, exposed tool schema changes, executable/environment scope, remote auth and each invocation. An MCP server process may itself access the host; isolate or label that trust accurately. Provider-side remote tools must remain disabled unless a separately designed nonlocal authority scope is approved; they cannot be passed off as local harness tools.

Skill scripts and plugin hooks pass through the same broker. No install/discovery action silently runs scripts, changes approved policy, or opens a public listener. Untrusted manifest preferences are routing requests, not privileges.

## Secrets and output sinks

Resolve keys from environment/OS secret storage by reference; fail on unknown/missing configuration and never log values. Register known secrets centrally. Validate layered config and reject ambiguity; canonical variables take precedence over explicitly supported legacy aliases with warnings that contain no values. Public examples use nonlive placeholders and no ephemeral tunnel URLs.

Scrub structured fields plus text before rendering, event persistence, journal/log/tracing, exceptions, telemetry export and model-context disclosure. Audit all SDK visualizers/loggers/caches, not just FreeCompute's formatter. Buffer streamed output enough to detect registered secrets split across chunks; carry redaction state across chunk boundaries. Do not collect raw hidden reasoning by default.

SecretScrubber/regex scanning reduces risk but cannot prove arbitrary secrets absent. Combine forbidden-file reads, minimized environment, secret references, structured sensitive-field handling, bounded retention, test fixtures and optional external scanning. Protect transient raw payloads in memory, avoid debug dumps, and quarantine/report unsafe artifacts. User-controlled file content may contain unknown secrets; review remote disclosure scope and avoid marketing a guarantee of automatic perfect detection.

## Remote gateway

One canonical supervisor implementation, reproducibly packaged/generated into notebook wrappers. Startup rejects absent/blank keys; no predictable default. Rotate scoped credentials, restrict engine binding to loopback/private interfaces, and authenticate every data/control/telemetry endpoint. A public health route, if ever necessary, must expose only explicitly reviewed minimal liveness, not GPU/model/runtime data.

Use explicit route allowlists, body/response limits, concurrency/rate limits, idle/deadline controls and authenticated artifact downloads. Restart/stop/load actions need operator scope and engine ownership. Do not expose arbitrary backend admin/invocation routes through a wildcard proxy. SSE/WS forwarding must be tested for prompt flushing, disconnect cleanup, framing, backpressure and request-ID correlation. Never disable TLS verification as a fallback.

No silent private-to-public transport fallback. Notebook policy and account limits are external constraints; deployment modes require current validation. Published limitations of Quick Tunnels and managed Colab are summarized in [PROVIDER_AND_WORKER_MODEL.md](PROVIDER_AND_WORKER_MODEL.md).

## Local daemon/client boundary

Same-user socket/pipe or authenticated loopback, owner-only discovery files and keys, restrictive origins, CSRF protection, bounded requests and per-client scopes. Loopback alone is not authentication against malicious browser pages or other local users/processes. Tokenless remote binding is prohibited. Approval responses require authenticated ownership and match the exact pending revision; stale GUI decisions cannot authorize updated proposals.

## Required adversarial acceptance

Missing callbacks deny; recursive search cannot read protected variants/links; undo cannot snapshot outside root; stream-split secrets cannot reach outputs/logs; SDK default persistence/telemetry is intercepted; empty remote keys prevent startup; health/admin/artifact endpoints reject unauthenticated access; subprocess descendants cancel; SSRF redirects fail; child grants only narrow; unknown effects never auto-replay; stale approvals and worker leases fail safely. These checks complement the existing suite and must pass before release claims.
