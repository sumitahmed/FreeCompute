# Native AgentDriver qualification

## Authorization and starting checkpoint

2026-10-02: the user authorized native proposal-driver qualification and automatic
continuation into Stage 3 when it passes. Work stays on
`v2/safety-and-agentdriver-spike`; no merge, PR, deployment or remote GPU session.
The preserved checkpoints are `7861a9f` (safety/initial driver) and `e869f1f`
(OpenHands experiment/rejection). Startup working tree was clean; all **94**
existing unit tests passed in 4.912 seconds.

## Qualification decision

**PASS for the bounded Stage 3 sequential local runtime.** The production driver
passed its six initial contract tests and the real core's tool, approval, state,
process-crash, cancellation, context and CLI fixtures. This does not qualify
delegation/scheduling, physical GPU profiles, advanced compaction or future
external clients.

The native driver must contain no execution, provider, permissions or persistence
authority. It consumes normalized, completed inference responses and emits text
outcomes or complete action proposals. Malformed/incomplete batches are rejected
atomically; JSON state retains proposal identities, profile/context epochs and
cancellation without claiming remote cancellation. Core-owned brokers must prove
denial, narrow capabilities, sequential tool results and crash recovery before
this driver is accepted as the Stage 3 foundation.

Observed starting integration gaps: the CLI owned conversation state and constructed
providers/tools directly. Skill `allowed_tools` was parsed but unenforced; the
registry/prompt builder also refer to missing skill-manager methods. These are
Stage 3 repair targets are now corrected in the production boundary.

The optional OpenHands adapter remains an isolated historical experiment. It
will not be renamed into production or made a mandatory dependency.

## Evidence log

- Initial baseline: 94/94 unit tests pass; no production changes yet.
- Native implementation: `harness/core/native_driver.py`, explicit normalized
  response/decision/state contracts; no tools, providers or durable I/O. Generic
  input accounting: `harness/core/context.py`. Atomic JSON rejection includes
  duplicate keys, non-finite values, duplicate call IDs and sensitive arguments.
- Initial six qualification tests cover sequential results/state round trips,
  text completion, truncation/incomplete/failure/cancel/max-turn separation,
  context/profile epochs, and the existing broker's denial/child restriction
  boundaries. The prior 94 regressions remain unchanged.
- Production fixtures now prove actual edit/test receipts, missing/false
  approvals, immutable snapshot conflict checks, ordered events/checkpoints,
  scope narrowing, one active allocation, and recovery in separate processes.
  The focused runtime group passed **50 tests**, including 11 process/ownership
  tests and three actual CLI/presentation tests. The full unit suite and packaged
  entry point are being checked next. The experiment is not substituted for this
  evidence.
- Initial implementation failures found and fixed: restore validation happened
  after execution intent; denial had a crash window before its receipt; a
  reentrant callback could overwrite action state; the old formatter printed
  denial as success. Focused regressions cover the corrections.
