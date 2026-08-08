# Milestone 11 Slice 11.4 Implementation Plan

Status: complete (2026-08-08)

## Objective and non-goals

Complete the joined lifecycle from fresh active revision 3: reconnect/home the
second-session simulator, calibrate Water then Design B through the real dialog,
freeze exact count-stable revision 5, execute Design A, Design B, and Water in
literal stock-ID order, reconcile all 24 stock/well intents and 80 droplets,
reach completed revision 6, and inspect it read-only in a third fresh
application session. Only after the full focused system journey passes, append
the one scenario/capability and lifecycle-suite registration.

Do not modify production MVC behavior, recalibrate during execution passes,
extend two-stock Apply, add refill/resume or safeguards, add a matrix, change a
persisted schema/report version, or touch firmware/protocol/hardware/release
metadata.

## Exact call path

```text
fresh active revision 3 / clean resume
-> machine startup through real controls
-> Water stock/head lookup by ID -> stage -> real Generate/Select/Apply
-> Water return -> active revision 4
-> Design B stock/head lookup by ID -> stage -> real Generate/Select/Apply
-> Design B return -> active revision 5
-> literal plan/progress/runtime counts + three record/head/stock joins
-> stage already-calibrated Design A by stock ID -> real array Start
-> durable intent -> Controller -> Machine_FreeRTOS -> SimulatedMachine DISPENSE
-> persisted progress -> pass boundary 8
-> repeat Design B -> pass boundary 16
-> repeat Water -> pass boundary 24 / completed revision 6
-> exact intent/command/simulator/progress/terminal reconciliation
-> restore second observer -> clean close -> third application session
-> real Qt completed read-only inspection without activation
-> exact terminal plan/progress/calibration/files and zero third-session dispatch
```

## Files expected to change

Add:

- `docs/sil_interactive_simulation_milestone_11_slice_4_implementation_plan.md`
- `docs/sil_interactive_simulation_milestone_11_slice_4_completion_record.md`

Update as evidence requires:

- `tools/virtual_workflows/journey_phases.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/assertions.py`
- `tools/virtual_workflows/registry.py`
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`
- focused phase/assertion/registry/manifest/selection/composition/contract tests;
- `tests/system/test_virtual_workflow_randomized_calibration_lifecycle.py`;
- only the Milestone 11 current-action text in the master plan.

The production MVC, firmware, protocol, existing matrix catalog, and historical
scenario definitions are not expected to change.

## Implementation steps

1. Extend the calibration-only phase with an optional real rack return action;
   preserve its default Slice 11.2 sequence.
2. Add a typed pre-calibrated stock-pass phase that stages by stock/head ID,
   starts through the existing ArrayDriver, waits/validates the existing
   durable boundary, captures a named checkpoint, and returns the head without
   opening or applying calibration.
3. Add case-owned builders for Water 1300 us / 9 nL and Design B 1400 us /
   10.8 nL calibration, plus Design A/B/Water pass specs with cumulative
   completion counts 8/16/24 and active/active/completed states.
4. Add the revision-5 assertion for three calibration records and plan-stock /
   head joins, literal final keyed counts, exact history 1-5, and zero progress.
5. Extend the joined body through startup, remaining calibration, three passes,
   observer restore, exact revision-6 terminal reconciliation, and the existing
   generic completed read-only reload in application session 3.
6. Add exact joined terminal assertions for 24 unique keyed begins,
   attachments/completions, 24 simulator DISPENSE commands, 80 droplets, pass
   boundaries/order, progress targets/added, calibration joins, revision 6,
   three fresh application IDs, and zero session-1/session-3 dispatch.
7. Run the unregistered complete focused system test. Only after it passes,
   append the composed journey definition, runtime registry entry, manifest
   scenario/capability/assertion evidence, and lifecycle-suite membership.
8. Run focused unit/contract/selection/manifest and existing calibration/
   reload/terminal tests plus the registered full system scenario, audit the
   diff, run `git diff --check`, record results, and commit as
   `test: add randomized calibration reload execution SIL journey`.

## Entrance and exit criteria

Entrance requires committed Slice 11.3 (`25deb6a`) and a clean worktree. Exit
requires plan history exactly 1-6, three calibration records joined by stock
ID to the literal heads/volumes/pulses, unchanged Design B count map, literal
revision-5 and revision-6 target maps, 24 unique intents/commands/completions,
80 total commanded/persisted droplets, pass order Design A/B/Water, no
position-based association, zero overflow/starvation/discard/error, completed
analysis-only terminal state, three distinct application sessions, zero
session-1/session-3 dispatch, no activation in session 3, all eleven named
screenshots, at most 96 actions, clean teardown, and exact registry/manifest/
suite agreement.

## Tests and retained evidence

Unit/contract tests cover optional calibration return, pre-calibrated phase
validation/action composition, stock-ID order independence, revision/count/
record joins, exact lifecycle reconciliation, terminal mutations, registry,
manifest, selection order/timeouts, and historical contract freeze.

The focused offscreen system test first runs the complete body directly while
unregistered. After it passes, the same module runs the registered composed
definition and validates report-v1 plus
`metrics.persistence.values.randomized_calibration_lifecycle`. Existing
calibration, authoritative reload, and completed-terminal cases run unchanged.

Retain diagnostic system output, all eleven named screenshots, three
application-session records, action/assertion ledgers, exact inventories and
hashes, calibration previews/records, observer lifecycle, pass boundaries,
terminal files, and the emitted replay command. This slice does not claim the
retained direct/replay/visible qualification reserved for Slice 11.5.

## Compatibility, risks, rollback, and deferred validation

Preserve all Milestone 9/10 hashes and catalogs, historical scenario order
except the intentional lifecycle append, action/assertion vocabulary, report
schema, selector/replay grammar, paused/terminal reload behavior, and negative
no-mutation evidence. The Milestone 9 normalizer applies only to observations;
every expected assignment/stock/count value remains literal and case-owned.

Risks are selecting by list position, unintentionally recalibrating while
printing, duplicate dispatch after rotation, or accepting terminal in-memory
state without persisted reload. Fail closed on any mismatch. A production
defect requires a separate reviewed correction plan. Rollback removes the
Slice 11.4 registration, complete journey, assertions, and pre-calibrated pass
phase while retaining the independently useful Slice 11.3 rotation phase.

Retained source-current direct/replay, visible/replay, full lifecycle and host
regression suites, complete pytest, evidence audit, operator documentation, and
milestone closeout remain deferred to Slice 11.5.
