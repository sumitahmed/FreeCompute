# Local Core API V1

Implemented on `v1/gui`, 2026-10-03, from accepted backend `755e944`.
`harness/api` is an HTTP/SSE transport around the existing `CoreService`.
The native driver, SQLite authority, permissions, sandbox, tools, scheduler,
worker registry and inference adapters remain in Core. No schema migration,
second task database, frontend scheduler or remote filesystem executor was added.

## Launch

From the repository, with Python dependencies installed:

```powershell
npm --prefix apps/gui ci
npm --prefix apps/gui run build
python -m harness.api --demo --open
```

Open `http://127.0.0.1:8741`. The service prints the path to its `local-api-token`
file in the existing per-user runtime directory outside the repo and OneDrive.
Read that file locally and paste its value into the GUI Connect form. It is a
new local API token, not `FREECOMPUTE_API_KEY`. No token is logged or put into a
URL. The password field is cleared after connection; the GUI stores no key.

Demo mode does not load `.env`, real worker configuration or a remote client.
It uses deterministic **SIMULATED inference** and existing approval-gated tools
in OS temp `freecompute-gui-demo`, with persisted Core state. `--workspace` selects
another external demo directory. Existing files are never reset by startup.
To repeat the initial broken-calculator example, choose a fresh external demo
directory rather than deleting or overwriting an existing workspace.

Explicit real-worker mode, separately opt-in:

```powershell
python -m harness.api --config path-to-existing-config.yaml --open
```

It uses the existing config/environment precedence and registry. Task submission
can contact configured workers. This phase has not run that mode against Kaggle.
Only one Core process can own a workspace; close its CLI Core before attaching
this service. Browser closure leaves Core work running. Ctrl+C stops the service,
requests local cancellation, and preserves uncertain remote claims.

For frontend development, start the API with
`--origin http://127.0.0.1:5173` and run `npm --prefix apps/gui run dev`.
Connect to `http://127.0.0.1:8741` in that GUI. Built assets are served directly
by the Python service; no production Node server is required. The build is not
yet bundled into the Python wheel or a desktop installer.

## Authentication and browser boundary

- Listener is restricted to `127.0.0.1`; public bind addresses are rejected.
- Every request validates its exact loopback Host. Browser Origin must match
  the service's 127.0.0.1/localhost address or an explicitly configured loopback
  dev origin. No wildcard CORS. Use matching hostnames for GUI and API so the
  SameSite cookie remains same-site, especially with Vite.
- `POST /api/v1/auth/session` exchanges the local token for a random 12-hour
  HttpOnly, SameSite=Strict cookie and a CSRF nonce held in client memory.
- Cookie-authenticated mutations require both allowed Origin and
  `X-FreeCompute-CSRF`. CLI clients can use `Authorization: Bearer <TOKEN>`.
  Credentials never appear in event URLs.
- Restart rotates the root token and invalidates browser auth sessions; durable
  tasks remain in Core. The GUI requests reconnection instead of inventing state.
- Responses/events/errors pass through `SecretScrubber`. Access logs omit paths,
  headers and bodies. Built HTML has self-only script/style/connect CSP, no
  external assets, no framing, and no HTML rendering of model output.
- JSON bodies are bounded to 256 KiB, duplicate/non-finite/unknown fields are
  rejected, and eight simultaneous SSE connections are allowed. Slow viewer
  writes time out; they hold no Core locks or growing event queue.
- Auth state is transport-only memory. The token file uses mode 0600 on Unix;
  Windows uses the per-user profile directory's inherited ACL. Explicit Windows
  ACL provisioning and desktop bootstrap integration remain release work.

This is same-user local authentication, not an OS sandbox against hostile
processes running as the same user. Approved commands retain the existing trusted
host execution model. A Tauri webview Origin/auth bootstrap is not implemented.

## Commands and queries

All routes below use `/api/v1`; protected except the token exchange. `/healthz`
is a minimal unauthenticated readiness query with no workspace/worker details.
Errors are `{ "error": { "code": "...", "message": "..." } }`.
401 means auth is required, 403 a Host/Origin/CSRF rejection, 409 stale/duplicate
command delivery or a busy local operation, 400 invalid/unsupported Core commands.

| Method | Route | Contract |
| --- | --- | --- |
| GET / POST | `/auth/session` | Query cookie auth/CSRF or exchange `{token}` |
| POST | `/auth/logout` | Revoke this browser session; does not cancel a task |
| GET | `/status` | Mode, workspace, current Core defaults, active task and transport-runner error |
| GET / POST | `/sessions` | List summaries or create a backend-ID empty session, optional `profile_id` |
| GET | `/sessions/{id}` | Coherent committed session/tasks/pending-approvals snapshot plus durable cursor |
| GET | `/tasks?session_id=...` | Public task projections; no serialized driver/checkpoint internals |
| GET | `/tasks/{id}` | Task state, prompt, final answer, profile, timestamps, cancellation observations |
| POST | `/tasks` | `{prompt,session_id,request_id,profile_id?,worker_id?,max_turns?}`; returns 202 task projection |
| POST | `/tasks/{id}/resume` | Resume the session's current task; not an older task/newer-task alias |
| POST | `/tasks/{id}/cancel` | Existing Core cancel command; response is not remote cancellation acknowledgement |
| GET | `/workers`, `/profiles` | Registry declarations, compatibility, health, timestamps and observations; no credentials |
| POST | `/workers/refresh` | Explicit existing Core health query |
| POST | `/defaults` | `{profile_id,worker_id?}` selects Core defaults for this service; queued routes remain bound |
| GET | `/queue` | Public queue/lease projections and active local task |
| GET | `/actions?task_id=...` | Tool proposals/receipts, targets/hashes and revisions |
| GET | `/approvals?session_id=...` | Core pending approvals, exact previews, revision/hash bindings |
| POST | `/approvals/{id}/decision` | Strict boolean decision plus `action_revision`, `task_revision`, `arguments_hash`, `target_hash` |
| POST | `/reconcile/inference` | `{lease_id,confirmed_idle:true}` explicit operator idle assertion; never inferred from health |
| POST | `/reconcile/action` | `{action_id,outcome,expected_hash?,confirmed:true}` existing tool reconciliation |
| GET | `/sessions/{id}/events?after=N` | Ordered page, or SSE when Accept is `text/event-stream` |
| POST | `/demo/worker` | Demo-only `{connected:boolean}`; pre-dispatch simulated worker availability |

Query projections live in `harness/core/views.py`. Empty session creation is a
new additive Core command using the same session insertion path as submit. No
frontend-generated session/task/action/approval IDs become authoritative.
Client-generated `request_id` is only the existing idempotency command key.
Core defaults are process-scoped; restart defaults come from Core configuration.
For task submission, omitted `worker_id` inherits Core defaults; explicit JSON
`null` means the automatic eligible-worker route (Core's existing empty route
hint). Both choices are bound at submission and survive later default changes.

## Dispatch and approvals

One transport worker thread delegates queued work to `CoreService.run_next`.
It does not choose capacity, claim resources or bypass FIFO; those decisions
remain in Scheduler. Explicit resume invokes Core's existing session resume.
Confirmed receipts replay through Core; uncertain effects/leases stay fenced.

An approval-requested event is committed before the renderer sees its card.
The transport keeps only a temporary condition/wakeup for the active resolver.
An authenticated decision returns **202 decision_delivered**, not approved.
The Core thread then calls `PermissionService.resolve` with a freshly observed
file hash and its existing action/task/profile/epoch/capability/arguments bindings.
The durable `approval.decided` event is the actual decision receipt. Changed
files fail closed. No viewer, closing the tab or a transport reconnect never
grants consent. Service cancellation wakes the resolver with denial. Core restart
expires old pending approvals and issues fresh bound requests on explicit resume.

Reconciliation requires an explicit authenticated operator confirmation and uses
the existing Core checks. It is refused during an active local task. Reconciliation
does not certify remote cancellation or automatically retry a tool effect.

## Ordered events and reconnect

Core event version 1 retains backend `id`, `session_id`, `task_id`, `sequence`,
`entity_id`, `revision`, `kind`, `actor`, `payload`, `created_at`. Sequence is per
session. The API reads the durable event store in pages of 200; no event authority
or unbounded pub/sub buffer is maintained by the transport.

JSON replies contain `events`, `cursor`, `has_more`. SSE sends:

```text
id: 42
event: core
data: {"sequence":42,"kind":"tool.completed",...}

event: heartbeat
data: {}
```

`after` or `Last-Event-ID` selects replay strictly after that durable sequence;
invalid negative/future cursors are rejected. Heartbeats carry no model/task
progress. The GUI loads persisted history, connects after the last received
sequence, deduplicates replay, and reconnects with bounded backoff. Fetch-based
SSE supports HttpOnly credentials without tokens in URLs. Changing a session
or closing the browser aborts only the event reader. Polling refreshes registry,
queue and committed snapshots, with revision checks against stale task snapshots.

## Verification status

Tested final evidence: 22 HTTP/Core API tests in the **232-pass full unit suite**,
10 frontend transport/component tests, 5 Chromium browser flows, a strict
TypeScript/Vite production build and the normal CLI launcher smoke. Exact timings
and browser cases are recorded in [V1_GUI.md](V1_GUI.md).
Real GUI-to-GPU acceptance, OS isolation, desktop auth/bootstrap, distribution,
and high-volume multi-client performance remain **Unverified / Proposed**.
