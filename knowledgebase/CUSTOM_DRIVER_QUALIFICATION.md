# Native AgentDriver qualification

## Authorization and starting checkpoint

2026-10-02: the user authorized native proposal-driver qualification and automatic
continuation into Stage 3 when it passes. Work stays on
`v2/safety-and-agentdriver-spike`; no merge, PR, deployment or remote GPU session.
The preserved checkpoints are `7861a9f` (safety/initial driver) and `e869f1f`
(OpenHands experiment/rejection). Startup working tree was clean; all **94**
existing unit tests passed in 4.912 seconds.

## Qualification contract (in progress)

The native driver must contain no execution, provider, permissions or persistence
authority. It consumes normalized, completed inference responses and emits text
outcomes or complete action proposals. Malformed/incomplete batches are rejected
atomically; JSON state retains proposal identities, profile/context epochs and
cancellation without claiming remote cancellation. Core-owned brokers must prove
denial, narrow capabilities, sequential tool results and crash recovery before
this driver is accepted as the Stage 3 foundation.

Observed integration gaps: the CLI owns conversation state and constructs
providers/tools directly. Skill `allowed_tools` is parsed but unenforced; the
registry/prompt builder also refer to missing skill-manager methods. These are
Stage 3 repair targets, not accepted behavior.

The optional OpenHands adapter remains an isolated historical experiment. It
will not be renamed into production or made a mandatory dependency.

## Evidence log

- Initial baseline: 94/94 unit tests pass; no production changes yet.
- Native driver qualification, production broker recovery and package/CLI
  acceptance: pending. Claims will be updated from actual runs.
