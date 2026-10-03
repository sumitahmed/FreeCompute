# FreeCompute V1 GUI foundation

Implemented on `v1/gui`, 2026-10-03, from `755e944`. The prior 210-test backend
and bounded real Kaggle evidence remain the baseline. This GUI phase uses no
Kaggle session, remote model, GPU quota, Rust, Tauri, installer or website.

## Implemented

React 19.3.0 + TypeScript 7.0.2 + Vite 8.3.2 under `apps/gui`, with pinned npm
lockfile and ordinary CSS. No large component framework or external fonts.
Primary framework references: [React versions](https://react.dev/versions),
[Vite guide](https://vite.dev/guide/), [Playwright web server](https://playwright.dev/docs/test-webserver).
`APIClient` isolates browser transport; a later desktop client can replace its
bootstrap/transport while preserving versioned Core commands/events. The current
browser client restricts API URLs to loopback HTTP; Tauri Origin integration
will be a separate reviewed change.

The developer workspace has sessions left, conversation/tasks middle, and
worker/model/context/queue/timeline details right. Worker/profile selectors are
registry-based, incompatible routes explain their disabled state, and only new
tasks use the current selection. Settings list registered workers/profiles,
Core defaults and auth/connection status. Dark/light appearance is client-only.
Responsive narrow layout, visible keyboard focus, labelled controls and explicit
approve/deny buttons are included.

User prompts, streamed assistant text, actual emitted reasoning (only if present),
tool arguments, real local receipts, command output/exit code, edit diffs, final
answers, elapsed time and task status are shown. Core's durable sequence drives
the ordered timeline. Context is labelled estimated/declared and TTFT/usage say
not reported when absent. GPU observations do not grant inferred capacity.

Approval cards show exact local scope/target/command/replacement or content,
action/task revision, context epoch, target/arguments hashes. They deliver a
decision to the existing Core resolver; only the committed Core event means
approved/denied. Missing viewers never approve. Replacement diffs show only the
exact replacement strings; the full target is bound by Core's SHA-256 witness.

Queue entries, active local task, active/quarantined leases and waiting reasons
are visible. Local stop and remote uncertainty are distinct. Existing tool and
lease reconciliation require explicit operator observations; no remote idle or
cancellation acknowledgement is fabricated. Browser closure does not cancel.
Refresh reloads persisted Core sessions/history; reconnect resumes event replay.
See [LOCAL_API.md](LOCAL_API.md) for auth, endpoints and exact launch commands.

## Simulated development

`python -m harness.api --demo --open` uses a persistent disposable workspace
outside the repo and Core's normal runtime store. Streaming inference is a
deterministic **SIMULATED** engine. Read/edit/test proposals execute real sandboxed
local tools after explicit approvals. Fixtures include a fractional calculator
bug, file-creation denial, long streaming/cancellation, queued disconnected worker,
reconnect, authentication failure, and context overflow. Startup never resets
existing files. An already-fixed calculator is read/tested without proposing a
stale replacement. No `.env` or live worker configuration is loaded in demo mode.

No fixture result is new GPU acceptance. The accepted backend evidence remains
in [V1_REAL_KAGGLE_ACCEPTANCE.md](V1_REAL_KAGGLE_ACCEPTANCE.md).

## Tested / final evidence

Final local evidence, Windows, 2026-10-03:

| Check | Exact result |
| --- | --- |
| `python -m unittest discover -s tests/unit -p "test_*.py"` | **230 passed, 66.546s**: original 210 unchanged + 20 HTTP/Core tests |
| `npm --prefix apps/gui run test` | **10 passed**, one test file, **2.59s** |
| `npm --prefix apps/gui run build` | Strict TypeScript project check and Vite production build passed; Vite **296ms** |
| `npm --prefix apps/gui run e2e` | **5 Chromium browser flows passed, 16.3s**; no retries |
| Normal `python -m harness.api --demo --workspace <fresh external directory> --port 0` launcher smoke | Built GUI and authenticated API served; correct simulated workspace; external token file; no credential output |
| Tracked-file secret scan | **0 credential findings**; one unchanged scanner-definition rule literal self-match classified separately; no scanner changes |
| `git diff --check` | Passed |

The browser flows exercised streamed read → separately approved edit → separately
approved real unittest command → receipt/final answer → refresh with the same
session; viewer closure/reconnect then explicit write denial; disconnected worker
queue and browser offline/online replay; local cancellation/unknown lease fencing
then explicit reconciliation; compatibility/engine failure and 390px light layout.
Changing a selector during approval retained the running task's bound profile
and declared context in details. No browser exceptions occurred in the coding flow.

Generated screenshots (local ignored artifacts, regenerated by browser tests):
`apps/gui/test-results/freecompute-approval.png`, `freecompute-workspace.png`,
`freecompute-mobile-light.png`. These are actual simulated-fixture screenshots,
not live Kaggle evidence or distribution assets.

Meaningful regressions include Windows viewer detach, stale approval delivery,
changed-file denial, idempotent submissions, durable replay/restart, no-viewer
approval safety, real edit/unittest receipts, unknown cancellation quarantine,
explicit reconciliation, disconnected-worker queuing/reconnect, context overflow,
registry compatibility and refusing an old-task resume alias to a newer task.

## Discovered issues and fixes

- Windows `ConnectionAbortedError` is a normal event-viewer detach; it no longer
  creates an unsanitized server traceback or cancels Core work.
- Resume must name the session's current task; old task IDs cannot alias a newer
  task through session-based Core resume.
- API shutdown must not implicitly cancel/reconcile a previously quarantined
  terminal task; only currently running local work is cancelled during shutdown.
- Replacement previews without trailing newlines now render separate diff lines.
- Client snapshot updates compare committed session revisions so a delayed older
  response cannot roll a newer task/approval view backwards.
- The simulation recognizes an already-fixed calculator instead of proposing a
  replacement that no longer matches the real local file.
- Task detail worker/profile/context follows the committed task route rather
  than selectors for a future task. Same-service `localhost` Origin supports
  cookie-authenticated commands; unrelated loopback ports remain rejected.
- Generated TypeScript build state is ignored rather than shipped as source.

## Proposed / Unverified before desktop release

Tauri wrapper, packaged Python sidecar/assets, installed launch path, Windows
token ACL provisioning, webview Origin/bootstrap, signing/update/installer,
supported OS/browser matrix, accessibility audit and sustained large-session /
multi-client performance remain open. No production GUI-to-GPU run was made.
Worker/profile declarations are shown truthfully; the historical 65,536 setting
is not full context certification. No website, subagents, delegation or advanced
memory/scheduling has been implemented in this phase.
