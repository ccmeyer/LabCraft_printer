# Milestone 10 Slice 10.4 Implementation Plan

Status: complete (2026-08-08)

## Objective and non-goals

Append only `custom_wells_with_exclusions` and
`multi_reagent_seed_1234` to the executable experiment-design matrix. Prove
the real picker disables and rejects excluded wells, authoritative assignment
uses only the selected non-excluded wells, seed 1234 is repeatable, and the
seed-4321/seed-1234 cases have equal reaction multisets but distinct exact
assignments.

Do not add capacity or terminal rejection cases, manual/uploaded assignments,
production MVC changes, tracked plate-catalog changes, generated exploration,
printing, firmware, protocol, hardware, motion, pressure, timing, or physical
calibration behavior.

## Exact call path

```text
matrix selector -> fresh child -> experiment_design journey
-> ExperimentEditorDriver -> Qt New Experiment reset
-> typed scenario-local Model.well_plate.excluded_wells precondition
-> Qt Printable Wells dialog
-> WellSelectionDialog(disabled_wells=...) rejects excluded-cell clicks
-> ExperimentModel.set_well_selection(non-excluded custom wells)
or Qt randomize checkbox + literal seed 1234
-> Optimize/Generate -> Finalize Design
-> MainWindow -> application Model authoritative plan/key/concentration files
-> Qt reload -> reconstructed exact assignments
-> excluded/selected/assigned and multiset/assignment hash assertions
```

Controller is observed only at the reload boundary. No comms or firmware
handler is reached.

## Initial files expected to change

- `tools/virtual_workflows/experiment_design_cases.py`
- `tools/virtual_workflows/matrices.py` through its existing generated prefix
- `tools/virtual_workflows/actions.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/assertions.py`
- focused catalog, matrix, action/assertion, assignment, and picker tests
- `tests/system/test_virtual_workflow_experiment_design_matrix.py`
- this slice completion record plus Milestone 10 status/current-action text

Repository evidence shows no change is required in production View/Model,
page drivers, journey phases, schemas, fixtures, or manifests.

## Implementation steps

1. Extend the executable prefix from four to six cases and freeze only the
   additive six-case catalog/control-plan hashes.
2. Apply typed exclusions to the isolated scenario WellPlate after the real
   New Experiment reset and before the picker; record the exact precondition
   and fail on any pre-existing exclusion state.
3. Generalize the existing picker driver to click declared excluded cells,
   prove they remain disabled/unselected, and select only the declared
   non-excluded printable wells.
4. Extend the exact prepared oracle with selected, excluded, disabled, and
   assigned set checks plus canonical reaction-multiset and assignment hashes.
5. Add focused contracts and fresh-process cases 5-6, including explicit
   seed-4321/seed-1234 equality/divergence and existing global-RNG isolation.
6. Run/replay both selected cases offscreen; run/replay the exclusion case
   visibly and inspect picker/generated/reload evidence.
7. Inspect retained evidence and the diff, run `git diff --check`, write the
   completion record, update the plans, and commit as
   `test: add well selection and randomization design SIL cases`.

## Contracts, validation, and evidence

The exclusion case must record declared wells `A1`-`A6`, disabled/rejected
`A2` and `A5`, selected printable wells `A1`, `A3`, `A4`, `A6`, and exact
authoritative assignments only in `A1`, `A3`, and `A4`. Exclusions must remain
scenario-local and teardown must leave no cross-session state.

The randomized cases must preserve the independently frozen equal reaction
multiset hash, distinct assignment hashes, exact seed controls, and exact
same-seed replay mappings. Production outputs may be normalized for
comparison but may not calculate expected values.

Run the approved Slice 10.4 focused command, cases 5-6 fresh-process tests,
selected CLI runs/replays, and the visible exclusion representative/replay.
Retain reports, evidence manifests, screenshots, action/assertion ledgers,
selected/disabled/assigned sets, hashes, and cleanup evidence. Capacity cases,
the complete matrix/replay, broader regressions, and the complete Python suite
remain deferred to Slice 10.6.

## Compatibility, risks, rollback, entrance, and exit

Keep cases 1-4, Milestone 7-9 identities, report-v1, matrix plan/aggregate v1,
replay formatting, fixture SHA, legacy editor action order, manual-assignment
precedence, and global RNG behavior unchanged. The six-case extension is
additive only.

Risks are confusing the declared selection window with the actual printable
set, relying on display order, or leaking exclusions across sessions. Compare
exact well IDs, reject any pre-existing exclusion state, and use fresh child
processes. Rollback reverts only this slice commit and restores the four-case
prefix.

Entrance is clean Slice 10.3 commit `b68d17a`. Exit requires both selected
cases/replays, the visible exclusion case/replay, exact cross-seed comparison,
focused tests, manual evidence inspection, completion record,
`git diff --check`, and one clean focused commit.
