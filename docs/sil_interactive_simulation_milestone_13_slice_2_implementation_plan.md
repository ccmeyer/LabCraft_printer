# Milestone 13 Slice 13.2 Implementation Plan

Status: `complete`

Started: 2026-08-09

## Objective

Implement only the two frozen legal Milestone 13 sequences. Both must use real
Qt operator controls, continuously reconcile modeled and observed state, and
finish at an authoritative terminal reload. The normal generated corpus uses
a literal four-reaction, two-stock compact case with eight stock/well intents
and 44 commanded droplets. Milestone 11A remains a separate stress oracle.

## Call paths

### Seed 13: legal design/calibration terminal

```text
normalized sequence/oracle row
-> ExperimentEditorDriver QTest controls
-> View dialog signals
-> Controller/Model design validation and Optimize & Generate
-> Finalize authoritative plan/progress revision
-> Rack/Printer Head real controls
-> calibration Generate/Select/Apply dialog
-> Controller/Model keyed calibration persistence
-> clean simulated-session close
-> real loader selection and explicit activation
-> Start Print Array confirmation
-> Controller intent journal
-> Machine_FreeRTOS simulator DISPENSE queue
-> completion/progress persistence
-> terminal fresh-session read-only reload
-> assertions, screenshots, report, hashes, and cleanup
```

### Seed 29: legal refinalize/reload terminal

```text
prepared authoritative compact design
-> real prepared-editor open and reagent input change
-> regenerate through Controller/Model
-> refinalize through the normal replacement boundary
-> exact plan/design/progress revision continuity
-> matching head and calibration controls
-> close/reload/activate
-> Start/intent/simulator/completion path
-> terminal read-only reload
-> assertions, screenshots, report, hashes, and cleanup
```

No step uses a UI row/list position as identity. Design, stock, printer-head,
calibration, plan, progress, revision, intent, and command identities are
durable keys.

## State and oracle contracts

Seed 13 observes `draft_valid -> draft_generated -> prepared_zero_progress ->
calibration_available_unapplied -> calibration_selected_unapplied ->
calibrated_zero_progress -> session_closed -> reloaded_inactive ->
active_zero_progress -> terminal`.

Seed 29 begins at a prepared zero-progress compact authority, proves a real
reagent edit and regenerated/refinalized lineage, then follows the same
calibration/reload/activation/terminal path. Every operation retains its frozen
Slice 13.1 operation ID and oracle ID. M10's literal editor oracle validates
the compact input/output; the qualified 1300 us/9 nL calibration row is reused
for both durable head identities; M11's keyed calibration, clean session rotation,
intent/command, terminal persistence, and cleanup assertions validate the
lifecycle. Expected assignments and counts are literal test data and are not
computed from production behavior.

The compact contract is exactly four reactions, two executable stocks
including fill, eight intents, and 44 droplets. It remains below the broader
campaign caps while remaining the exact per-sequence workload.

## Scope and exclusions

In scope: compact literal case types/hashes, generated in-memory fixtures,
real Qt editor/head/calibration/loader/activation/Start actions, continuous
state evidence, exact dispatch/terminal assertions, direct/replay report
projection, four bounded screenshots, and focused tests.

Out of scope: every rejected operation, Milestone 12 safeguard composition,
aggregate v2, diagnostic execution, semantic coverage aggregation, reduction,
manifest capability registration, persistence fault injection, refill/resume,
active-authority mutation, optimizer-360 corpus reuse, firmware, protocol,
hardware, motion, pressure behavior, `pi_stress`, and the known 384x10 issue.

## Implementation plan

1. Freeze the compact literal case, fixture projection, durable identities,
   counts, calibration revisions, execution passes, and hashes.
2. Add a shared M13 legal lifecycle body and continuous state/operation
   projection using the existing editor and joined-lifecycle drivers.
3. Implement seed 13's create/configure/generate/finalize path through real Qt.
4. Implement seed 29's prepared reagent edit/regenerate/refinalize path through
   real Qt without replacing authority outside the normal operator flow.
5. Project exact operation/oracle/state, authoritative, dispatch, screenshot,
   budget, source, replay, and cleanup evidence into report v1.
6. Add focused contract, assertion, journey, CLI, and real-Qt system tests.
7. Run direct fresh-process and exact replay for both seeds, plus visible seed
   13 direct/replay, with the frozen 270/300-second limits.
8. Audit retained evidence, run `git diff --check`, and write the completion
   record before Slice 13.3 begins.

## Files expected to change

- new compact M13 interaction-case/fixture code under
  `tools/virtual_workflows/`;
- narrow additions to `journey_phases.py`, `journeys.py`, assertions/report
  projection helpers, and `tools/run_virtual_workflow.py`;
- M13 contract, journey, CLI, and system tests;
- this plan, the Slice 13.2 completion record, execution plan, and master plan.

Production `View.py`, `Controller.py`, `Model.py`, `Machine_FreeRTOS`, simulator
implementation, manifest, and all Milestone 8-12/11A literal fixtures are not
expected to change.

## Budgets and acceptance

Each sequence is capped at 18 semantic operations, 64 action-ledger rows,
three application sessions/two rotations, four screenshots, 256 files/48 MiB,
a 270-second scenario deadline and 300-second child watchdog. The direct
offscreen speed is 1000; visible speed is 20. Any counter overrun, unexpected
dialog, missing assertion, identity discontinuity, non-literal count,
unexpected dispatch, terminal reload mutation, or cleanup failure is a hard
failure.

Acceptance requires both direct fresh-process runs and their exact emitted
replays to pass, seed 13 visible direct/replay to pass, semantic report
projections to match their original normalized sequence hashes, all eight
intents and 44 droplets to join exactly once to simulator commands and durable
completions, all sessions to close cleanly, and focused unit/system tests plus
`git diff --check` to pass.

## Risks and rollback

Risks include deriving a compact expected mapping from production, exceeding
the action/screenshot cap by exposing internal mechanics, losing plan identity
during refinalize, activating on load, or accepting a completed in-memory state
without terminal reload. The compact expected mapping is therefore frozen as
literal contract data and independently hash tested; lifecycle checks operate
by durable IDs and exact retained revisions.

Rollback removes the compact case, M13 legal journey branches, CLI execution
enablement, tests, and Slice 13.2 records, then restores the Slice 13.1
execution-disabled guard. No deterministic Milestone 8-12/11A behavior or user
data is changed or deleted.
