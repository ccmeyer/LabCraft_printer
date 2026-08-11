# Milestone 11 Slice 11.2 Implementation Plan

Status: complete (2026-08-08)

## Objective

Compose and verify the first application-session boundary for the frozen
joined case: create/finalize the seed-4321 design through the real Qt editor,
prove authoritative revision 1 against the literal oracle, stage the Design A
head, apply the real 1800 us / 18 nL calibration, and prove the resulting
revision-3 calibrated state has zero progress and zero execution lifecycle
events.

Do not rotate or reopen the application, activate execution, calibrate Water or
Design B, start an array, register a scenario/capability/suite, publish a
scenario report, run visibly, or change production MVC behavior.

## Exact call path

```text
JoinedInteractionCase -> Milestone 10 editor_specification
-> ExperimentEditorDriver -> real ExperimentDesignDialog Generate/Finalize
-> ExperimentModel/Model authoritative design + revision-1 execution files
-> literal joined design assertion keyed by stock/well identity
-> rack/head identity bind -> MachineControlsDriver/RackDriver
-> real CalibrationDialogDriver Generate/Select/Apply
-> ExperimentModel lock revision 2 -> apply_execution_calibration revision 3
-> calibration record + plan stock/head + progress reference joins
-> literal calibrated stock/well oracle + zero lifecycle assertion
-> clean application teardown without execution activation or dispatch
```

## Files

Add:

- `tests/system/test_virtual_workflow_randomized_calibration_lifecycle.py`
- `docs/sil_interactive_simulation_milestone_11_slice_2_implementation_plan.md`
- `docs/sil_interactive_simulation_milestone_11_slice_2_completion_record.md`

Update:

- `tools/virtual_workflows/journey_phases.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/assertions.py`
- `tests/test_virtual_workflow_journey_phases.py`
- `tests/test_virtual_workflow_assertions.py`
- `tests/test_virtual_workflow_contract_freeze.py`
- only the Milestone 11 current-action text in
  `docs/sil_interactive_simulation_and_composable_workflows_plan.md`

The existing editor and calibration page drivers, action IDs, authoritative
evidence reader, and report projection are sufficient and are not initially
expected to change.

## Implementation steps

1. Add a typed calibration-only phase input that reuses the existing stock
   staging and real calibration dialog actions but cannot start or resume an
   array.
2. Add the generic phase that binds/stages one stock/head, performs real
   Generate/Select/Apply, captures before/after count snapshots, and returns
   exact calibration evidence without execution.
3. Add read-only joined assertions for revision-1 randomized design identity
   and revision-3 calibration/head/progress/count identity, using the
   Milestone 9 normalizer only on observations and literal case-owned expected
   rows.
4. Compose an unregistered joined checkpoint body that installs a bounded
   execution observer, drives the real editor and Design A calibration,
   records the three required checkpoint screenshots, and proves no dispatch.
5. Add unit/contract tests for typed phase validation, exact action sequence,
   keyed comparisons, revision/head/calibration joins, and fail-closed
   mutations; freeze the new assertion/action composition without changing
   registered selectors.
6. Add one focused offscreen `sil_lifecycle` test using a direct harness (no
   scenario report) and assert real Qt actions, literal mapping/counts,
   revisions 1/2/3, one calibration record, zero progress/events, isolation,
   and clean teardown.
7. Run the focused adjacent Milestone 9/10 unit/contract suite and the single
   selected offscreen checkpoint test, inspect the diff, and run
   `git diff --check`.
8. Record exact results, advance to Slice 11.3, and commit as
   `test: add randomized calibrated zero-progress checkpoint`.

## Entrance prerequisites and exit criteria

Entrance requires committed Slice 11.1 hashes and a clean worktree. Exit
requires exact revision-1 source design, revisions 1/2/3 in history, one
Design A calibration linked to `virtual-head-m11-design-a-v1`, literal
revision-3 target counts, unchanged Design B counts, matching plan/progress
references, absent resume, zero added/completed/intent/simulator events, idle
controller, drained simulator, no hardware interface, and clean teardown.

## Tests and retained evidence

Focused non-SIL tests cover joined contracts, phase/action composition,
assertions, experiment-design cases, count normalization, authoritative
evidence, manifest/registry freeze, and contract freeze. The only authorized
SIL check is the selected offscreen checkpoint test:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_randomized_calibration_lifecycle.py
```

Retain the focused command results and checkpoint diagnostics/screenshots
(`design_generated`, `prepared_randomized`, `calibrated_zero_progress`) in the
completion record. Do not retain or accept a scenario report/replay for this
partial lifecycle.

## Compatibility, deferred validation, and rollback

Preserve the qualified editor/calibration drivers, production direct-Model
authoring and Apply paths, all action/assertion IDs, report-v1, Milestone 9/10
hashes/selectors/replays, and negative no-mutation evidence. Expected values
must remain literal and stock/well keyed. A mismatch suggesting a production
defect stops this slice for a separate reviewed correction plan.

Fresh-session rotation, reload/activation, remaining calibrations, execution,
terminal reload, exact replay, visible qualification, lifecycle and host
regressions, and the complete Python suite remain deferred to later slices,
normally Slice 11.5.

Rollback is the independent Slice 11.2 commit. Reverting it removes the
calibration-only composition, joined assertions/system checkpoint, and slice
records while retaining the frozen Slice 11.1 case. No data migration or
production rollback is required.
