# Milestone 10 Slice 10.2 Implementation Plan

Status: implementation in progress (2026-08-08)

## Objective and non-goals

Make `single_reagent_control` and `multi_reagent_seed_4321` executable through
normal Qt editor controls, authoritative finalization, Qt directory reload,
and exact reconstruction of saved assignments. Register only that two-case
prefix in `experiment_design_pairwise_v1` and retain exact design/reload
evidence.

Do not add formulation transitions, custom exclusions, the alternate seed,
capacity boundaries, rejected finalization, printing, production MVC changes,
schema changes, or any firmware/protocol/hardware behavior.

## Exact call path

```text
matrix selector
-> fresh child process
-> experiment_design journey family
-> SHA-verified in-memory case fixture
-> EditorPreparationSpec
-> ExperimentEditorDriver
-> normal Qt New / controls / Optimize & Generate / Finalize Design
-> ExperimentDesignDialog._on_finish
-> MainWindow.complete_experiment_design
-> Model.load_experiment_from_model(finalize_execution_plan=True)
-> authoritative design / plan / progress / key / concentration files
-> ExperimentLoaderDriver Qt directory selection
-> ExperimentModel.load_experiment
-> editable untouched-PREPARED inspection
-> saved plan projected into reconstructed stocks/reactions/well assignments
-> Controller array state idle
-> exact case oracle and reconstructed-runtime assertions
-> report-v1 and matrix child aggregate contracts
```

The finalization handoff intentionally remains the existing direct
`MainWindow -> Model` application path; no new Controller mediation is
introduced. Controller participation begins at post-load array-state
observation. Untouched PREPARED executions intentionally remain editable and
runtime-inactive; `Load Execution` is reserved for a locked saved execution.

## Initial files expected to change

- `tools/virtual_workflows/experiment_design_cases.py`
- `tools/virtual_workflows/matrices.py`
- `tools/virtual_workflows/actions.py`
- `tools/virtual_workflows/page_drivers.py`
- `tools/virtual_workflows/journey_phases.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/assertions.py`
- `tools/virtual_workflows/authoritative_evidence.py`
- `tools/virtual_workflows/editor_reporting.py`
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`
- focused unit/contract tests for each changed module
- add `tests/system/test_virtual_workflow_experiment_design_matrix.py`
- add the Slice 10.2 completion record
- update only Milestone 10 Current Next Action in the master plan

Files from this list that repository evidence shows do not need modification
will remain untouched and will be identified in the completion record.

## Implementation steps

1. Project typed cases into reusable editor inputs, including multiple
   reagents, optional stock bounds, selected wells, and explicit random seed.
2. Extend the Qt editor driver additively to enter and report those controls
   and generated stock/reaction evidence without changing the legacy action
   sequence.
3. Reuse the prepared Qt directory loader and prove `ready_to_start`, an
   inactive runtime, byte-identical files, and exact reconstructed assignments.
4. Add independent exact prepared/reconstructed-runtime assertions and an
   additive experiment-design report payload.
5. Add an experiment-design composed matrix body and register only the first
   two cases, preserving all existing schema, catalog, and journey identities.
6. Add focused contract/system tests; run only the two selected offscreen SIL
   cases and their exact replays.
7. Run and replay `multi_reagent_seed_4321` visibly, inspect retained evidence,
   and record hashes and compatibility results.
8. Run `git diff --check`, write the completion record, advance Current Next
   Action to Slice 10.3, and commit as
   `test: add control and multi-reagent design SIL cases`.

## Contracts, tests, and retained evidence

Introduce the two exact assertions
`experiment.design_case_oracle_exact` and
`experiment.prepared_runtime_reconstructed_exact`; additive `matrix_case` and
`experiment_design_evidence` report fields; and named screenshots for editor
opening, generation, finalization, prepared reload, and validation. Retain
child reports, manifests, screenshots, ledgers,
authoritative inventories/hashes, case/catalog/plan hashes, and replay
commands.

Run the focused unit/contract command listed in the approved execution plan,
then:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_experiment_design_matrix.py `
  -k "single_reagent_control or multi_reagent_seed_4321"
```

Run only the two selected cases through the CLI as needed to retain their
reports and exact replays. The full two-case matrix aggregate, the remaining
seven cases, lifecycle/host-regression suites, and full Python suite remain
deferred to Slice 10.6.

## Compatibility, risks, and rollback

Keep report-v1, matrix plan/aggregate v1, the unchanged editor fixture SHA,
legacy editor direct/composed action order, Milestone 7-9 hashes, generic
fresh-process behavior, replay format, and hardware isolation unchanged. The
new matrix must preserve the existing distinction between editable untouched
PREPARED reload and locked-execution `Load Execution` activation.

Risks are UI-driver ambiguity, an independent-oracle mismatch, and confusing
reconstructed assignments with an active runtime. Fail closed on all three. Any production
defect stops the slice for a separate reviewed correction plan. Rollback is
the independent Slice 10.2 commit and removes only the new journey family,
two-case registration, and additive harness/report contracts.

## Entrance, exit, and deferred validation

Entrance is satisfied by clean Slice 10.1 commit `74657bc` and the frozen
case hashes. Exit requires both offscreen cases and replays to pass, the
visible multi-reagent case and replay to pass, exact prepared/runtime evidence
to be inspected, focused tests to pass, existing hashes/schemas to remain
unchanged, the completion record to exist, and `git diff --check` to pass.

Complete matrix qualification/replay, lifecycle and host-regression suites,
and the full default Python suite are deferred to Slice 10.6.
