# Milestone 10 Execution Plan: Curated Experiment-Design Pairwise Matrix

Status: executing; Slices 10.1-10.3 complete, Slice 10.4 next

Prepared: 2026-08-08

This is an implementation plan, not an implementation record. Preparing this
document did not run a SIL matrix, change production behavior, or authorize
firmware, protocol, hardware, motion, pressure, or physical-calibration work.
Each future slice must be planned, reviewed, validated, and committed
independently. A production defect discovered by a slice stops that slice and
requires a separate reviewed correction plan and commit.

## Verified entrance baseline

All Milestone 10 prerequisites were satisfied before this plan was written:

- Milestone 9 is recorded complete in
  `docs/sil_interactive_simulation_milestone_9_slice_6_completion_record.md`.
- The required Milestone 9 validation artifacts are retained. All eight
  recorded matrix/lifecycle/host-regression aggregate paths exist and their
  SHA-256 values match the completion record.
- The expected Milestone 9 commits are ancestors of the current branch:
  `19faf52`, `56c89d1`, `de002a9`, `5ad5f70`, `d2e3a96`, `792a7b0`, and
  closeout commit `a10a63f`.
- The planning baseline is
  `a10a63f2bd15c81e038ccefc5cb0be879e45fc91` on
  `feature/general_bug_fix_1`, equal to its remote-tracking tip, with a clean
  worktree before these documentation edits.
- The stable Milestone 9 count evidence is reusable through
  `StockWellCount`, `normalize_stock_well_counts()`, `plan_target_counts()`,
  and `runtime_target_counts()` in
  `tools/virtual_workflows/dispense_counts.py`. The frozen Milestone 9 catalog
  hashes are:
  - `calibration_requantization_v1`:
    `d826a9e54c2e6190acfd5afdb0b2475de2be62557647aafa378890ca826c55af`;
  - `mixed_mode_calibration_v1`:
    `d2439c2e47cb9825ad5a5024e014fd4429ff6b28dcafa54809c92fa674cff884`.

The unchanged reference editor fixture is
`tools/virtual_workflows/fixtures/experiment_editor_create_finalize_v1.json`,
SHA-256
`fc2bdf34fa5a7d8a9e851ace7a099aa8e05c61c2d0cd075b620d69937f8bfc45`.
Milestone 10 should derive case fixtures from it in memory; no tracked fixture
per case is planned.

## Scope and non-goals

Milestone 10 adds a Windows-host SIL matrix named
`experiment_design_pairwise_v1`. It exercises the real experiment editor,
authoritative finalization, Qt directory reload, and exact in-memory
reconstruction from the saved plan. It does not print, calibrate, connect to a machine,
or dispatch simulator commands.

The following are non-goals for every slice:

- no production MVC refactor or assumed production change;
- no changes below `FreeRTOS-interface/` unless a separate defect correction
  is approved after a failing independent oracle exposes a production defect;
- no matrix Cartesian product, generated fixture per case, or unrestricted UI
  instruction data;
- no report-v2, matrix-plan-v2, matrix-aggregate-v2, fixture migration, or
  reinterpretation of historical evidence;
- no calibration, execution, refill-required/resume, firmware, protocol,
  serial, hardware, motion, pressure, camera, balance, or physical droplet
  claims;
- no full Python suite or complete Milestone 10 matrix before Slice 10.6,
  unless an earlier slice documents a concrete reason to promote one of those
  gates.

## Existing call paths to preserve

### Editor finalization and authoritative files

The repository does not currently route editor finalization through a
Controller method. The exact path is:

```text
matrix case fixture
-> JourneyExecutor
-> run_editor_preparation()
-> ExperimentEditorDriver.create_and_finalize()
-> drive_editor_create_finalize()
-> QTest opens ExperimentDesignDialog from the Experiment Editor button
-> ExperimentDesignDialog updates ExperimentModel inputs
-> Optimize & Generate calls ExperimentModel.optimize_stock_solutions()
   and ExperimentModel.generate_experiment()
-> Finalize Design calls MainWindow.complete_experiment_design()
-> Model.load_experiment_from_model(finalize_execution_plan=True)
-> experiment_design.json
-> execution_plan.json and execution_plan_revisions/
-> progress.json
-> key.csv and concentration_key.csv
-> Model.experiment_loaded signal
```

`MainWindow` owns the Qt handoff and calls `Model` directly. `Controller` is
not an authoring intermediary. Milestone 10 must record this fact and must not
introduce a Controller pass-through merely to make the diagram look more
layered.

### Matrix selection and fresh-process execution

```text
tools/run_virtual_workflow.py --matrix experiment_design_pairwise_v1
-> get_matrix_definition() / resolve_matrix_plan()
-> MatrixRegistry and MatrixDefinition validation
-> matrix_plan.json with catalog and per-case SHA-256 identities
-> matrix_runner.execute_matrix()
-> one fresh child process per selected case
-> journeys.run_matrix_case()
-> bounded experiment-design journey-family dispatch
-> editor driver and assertions
-> report-v1 child evidence
-> matrix aggregate v1 and exact replay command
```

The new journey family is additive. Unknown families, cases, catalog drift,
case drift, report mismatch, missing/ambiguous report selection, child failure,
and timeout continue to fail closed before an aggregate can pass.

### Reload and reconstructed runtime assignment

Positive cases extend the current editor inspection boundary through the
existing untouched-PREPARED reload path:

```text
finalized PREPARED bundle
-> ExperimentLoaderDriver opens Experiment Editor
-> Qt folder dialog selects the isolated authoritative experiment directory
-> ExperimentDesignDialog._on_load_design()
-> ExperimentModel.load_experiment() validates the saved execution
-> untouched PREPARED remains editable and ready_to_start, with runtime inactive
-> _project_reconstructed_execution_plan() reconstructs stocks, reactions,
   printer-head identities, and well map from the saved plan
-> Controller array-run state remains idle
-> exact catalog-to-plan-to-reconstructed-assignment comparison
```

The reload must create or modify no authoritative file. Evidence must
distinguish reconstructed in-memory assignments from an active authoritative
runtime. `Load Execution` remains the existing contract for locked saved
executions and is not expected for an untouched PREPARED design.

### Rejected finalization and no mutation

`ExperimentModel.initialize_experiment()` creates an isolated draft directory
with `experiment_design.json`, `progress.json`, and `calibration.json` when the
normal New action runs. Negative cases therefore take their baseline after
New/configuration and immediately before the attempted Finalize action:

```text
normal New and Qt configuration
-> read-only directory inventory and file hashes
-> QTest attempts Finalize Design
-> production capacity or optimization warning/status
-> dismiss expected modal through QTest
-> second read-only inventory plus model/runtime/queue snapshot
-> exact no-new/no-changed execution-artifact assertion
```

The proof requires the baseline files to remain byte-identical; no
`execution_plan.json`, execution-plan revision, key export, concentration
export, runtime activation, durable intent, simulator dispense, or completion
may appear. The initially created draft directory is retained as evidence and
is not misreported as a successful authoritative execution.

## Recommended architecture and frozen compatibility policy

The following decisions are supported by the current repository and should be
treated as settled unless implementation evidence exposes a material defect:

1. Add `tools/virtual_workflows/experiment_design_cases.py` for frozen case
   types, literal expected values, required pair interactions, and the
   in-memory reference-fixture builder. Keeping expected truth outside Model,
   View, and the generic registry makes accidental oracle coupling easier to
   detect.
2. Register the matrix in `tools/virtual_workflows/matrices.py` only when the
   first executable cases land in Slice 10.2. Slice 10.1 may exercise a
   test-local definition but must not publish a selectable placeholder.
3. Append executable cases in the final nine-case order. Existing case hashes
   remain frozen as later slices expand the matrix; the catalog hash is
   refrozen after each intentional prefix expansion and finally frozen in
   Slice 10.6.
4. Reuse `experiment_editor_create_finalize_v1.json` unchanged. Case names,
   inputs, and expected values are transformed in memory beneath the isolated
   scenario root.
5. Use the generic matrix plan, fresh-process runner, aggregate, report-v1,
   and replay contracts without a schema change. Put additive case evidence at
   `metrics.persistence.values.matrix_case` and detailed design evidence at
   `metrics.persistence.values.experiment_design_evidence`.
6. Reuse the Milestone 9 stock/well count normalizers to capture observed plan
   and runtime counts. The expected rows remain literal catalog data; they
   must never be computed by `optimize_stock_solutions()`,
   `generate_experiment()`, execution-plan builders, or runtime reconstruction.
7. A required-pair ledger, not an all-values Cartesian generator, defines
   coverage. The audit proves that every named high-risk pair has at least one
   case and that every case carries only recognized dimension values.
8. Matrices remain outside registered scenario capability aggregation. The
   capability manifest may add action/assertion vocabulary and update editor
   limitations, but matrix aggregates must not masquerade as suite capability
   evidence.

Compatibility frozen throughout all six slices:

- report schema `labcraft.virtual_workflow.report` version 1;
- matrix plan and aggregate schema version 1;
- existing matrix IDs, order within each existing catalog, case hashes,
  catalog hashes, selectors, fresh-child behavior, and replay commands;
- existing editor fixture bytes, scenario ID, required action/assertion IDs,
  direct legacy runner, composed journey, screenshots, and lifecycle-suite
  membership;
- authoritative design, plan, revision, progress, resume, calibration, key,
  concentration-key, and audit schemas;
- production startup and hardware isolation.

## Curated case catalog and independent oracle

The nine cases are intentionally ordered as follows. Exact normalized decimal
strings, stock IDs, stock/well rows, reaction multisets, assignments, warning
fragments, and hashes are frozen by the typed catalog before each case is
registered.

| Order | Case ID | Inputs and independent expected outcome |
| ---: | --- | --- |
| 1 | `single_reagent_control` | One additive, target `1 x`, fixed `1 x` stock, 10 nL droplet, 10 nL printed/final volume, one replicate, `A1`, no randomization. Expect one reaction, one stock, one drop, successful finalization and reconstruction. |
| 2 | `multi_reagent_seed_4321` | Two additives with targets `[1, 2] x` and `[1, 3] x`, fixed `10 x` stocks, 10 nL droplets, 100 nL printed/final volume, two replicates, eight wells, random seed 4321. Expect eight reactions, two non-fill stock identities, the literal eight-member multiset and seed-4321 assignment. |
| 3 | `one_stock_feasible` | One additive, targets `[0.1, 0.2] mM`, 10 nL droplets, 20 nL printed and 500 nL final volume, no fixed stock, one-stock mode. Independent solution: one `5.00 mM` stock with one/two-drop target rows; finalization succeeds. |
| 4 | `two_stock_required` | The same formulation as case 3 with a 10 nL printed-volume budget. The first normal-UI one-stock optimization is rejected with the existing enable-two-stock guidance and no authoritative mutation; enabling the checkbox and regenerating yields literal `5.00 mM` and `10.00 mM` one-drop legs, then finalization/reconstruction succeeds. |
| 5 | `custom_wells_with_exclusions` | One three-target additive, a sparse six-well custom picker set, two preconfigured exclusions within that set, and three reactions. Exclusions are staged before editor launch; the picker must display them disabled, refuse selection, and assign only the catalog's three non-excluded wells. |
| 6 | `multi_reagent_seed_1234` | Same chemistry, reaction multiset, replicates, and well set as case 2, but seed 1234. Its literal mapping differs from case 2 while its reaction-multiset hash is identical. Exact replay must reproduce the seed-1234 mapping. |
| 7 | `exact_custom_capacity` | One additive with two targets and two replicates, four custom printable wells, no exclusions. Four reactions exactly fill the four-well capacity and finalize/reconstruct successfully. |
| 8 | `capacity_plus_one_rejected` | Five reactions against the same four-well custom capacity. Finalize must show `Insufficient Well Capacity`, including required `5` and available `4`, and create or modify no authoritative execution artifact. |
| 9 | `fixed_stock_exceeds_max_rejected` | A fixed `35 mM` stock with a `20 mM` maximum. Finalize must show `Optimization failed`, retain the production status/message fragment `exceeds max stock`, and create or modify no authoritative execution artifact. |

The independent oracle contains, as applicable:

- exact reaction count and a canonical reaction-multiset hash;
- exact stock roles, identities, concentrations, modes, and target droplet
  rows;
- exact custom, excluded, available, and assigned well sets;
- exact reaction-to-well mapping for non-random and seeded cases;
- expected plan state/revision, zero progress, and start eligibility;
- exact key and concentration-key rows after finalization;
- capacity required/available values;
- expected terminal kind: `prepared`, `capacity_rejected`, or
  `formulation_rejected`;
- exact dialog title, stable message fragments, status class, and required
  no-mutation fields for rejection cases.

The required-pair audit covers these named interactions without claiming all
possible pairs: multi-reagent/multi-target, multi-reagent/randomized,
multi-target/multiple-replicate, optimized/one-stock,
optimized/two-stock, one-stock-rejection/two-stock-success,
custom-wells/exclusions, custom-wells/exact-capacity,
custom-wells/over-capacity, same-design/same-seed replay,
same-design/different-seed divergence, rejection/no-authoritative-mutation,
and success/reload/runtime-reconstruction.

## Slice 10.1: Typed catalog, oracle, pairwise audit, hashing, and selectors

### Objective and non-goals

Define all nine immutable cases, literal oracle records, pairwise dimension
tags, and validation rules. Prove they can participate in the existing generic
registry and plan hashing through a test-local definition. Do not register the
production matrix, launch Qt, alter a journey, or make any case selectable.

### Exact call path

```text
typed ExperimentDesignCase.normalized()
-> independent oracle validation and pairwise audit
-> test-local MatrixDefinition / MatrixRegistry
-> resolve_plan()
-> canonical case and catalog SHA-256 validation
-> no application construction
```

### Contracts and evidence introduced

- frozen reagent, stock-policy, well-policy, expected-plan, and expected-
  rejection dataclasses;
- exact JSON normalization with no NaN/Infinity, bool-as-int, duplicate ID,
  duplicate well, ambiguous terminal, or unknown coverage tag;
- literal reaction/count/assignment oracles and cross-case seed comparison;
- required-pair audit and nine-case order;
- test-local matrix plan showing compatibility with generic hashing and
  selector validation;
- import-boundary test forbidding production Model/View optimizer or
  assignment imports from the oracle module.

### Initial files expected to change

- add `tools/virtual_workflows/experiment_design_cases.py`;
- add `tests/test_virtual_workflow_experiment_design_cases.py`;
- update `tests/test_virtual_workflow_matrices.py`;
- update `tests/test_virtual_workflow_matrix_runner.py`;
- add `docs/sil_interactive_simulation_milestone_10_slice_1_implementation_plan.md`;
- add `docs/sil_interactive_simulation_milestone_10_slice_1_completion_record.md`;
- update only the Milestone 10 current-action text in the master plan.

### Cases added

All nine typed cases are defined and audited, but zero cases are added to the
operator registry in this slice.

### Targeted automated tests

Run only the new case/oracle tests plus focused registry/runner hashing tests.
Freeze all nine normalized case hashes, the full planned-catalog projection,
the pairwise audit result, and unchanged Milestone 7-9 hashes. Prove a
test-local selection, case filter, drift rejection, and unknown-family
rejection without Qt construction.

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_experiment_design_cases.py `
  tests\test_virtual_workflow_matrices.py `
  tests\test_virtual_workflow_matrix_runner.py
```

### Manual or visible SIL checks

None. Confirm `--list matrices` and dry-run output remain byte-for-byte
compatible for the two existing matrix definitions and do not expose
`experiment_design_pairwise_v1`.

### Retained evidence

Retain test output, the normalized planned catalog and hashes in the
completion record, and the exact before/after existing selector output. No SIL
report is expected.

### Compatibility contracts

All globally frozen contracts above remain unchanged. In particular, no
placeholder matrix, schema change, or change to the current two matrix hashes
is allowed.

### Commit boundary

One commit: `test: define experiment design matrix contracts`.

### Risks and rollback

Risk is limited to accidentally coupling the expected oracle to production or
publishing an unexecutable selector. Rollback removes the new module/tests and
slice records; no runtime data or retained report changes.

### Entrance and exit criteria

Entrance: the verified Milestone 9 baseline above still holds. Exit: all nine
cases and required pairs validate, frozen hashes are recorded, production
matrix listing is unchanged, focused tests pass, and `git diff --check`
passes.

### Validation deferred to Slice 10.6

Qt/system tests, any design-matrix execution, complete matrix/replay,
lifecycle and host regressions, and the full Python suite.

## Slice 10.2: Reusable editor inputs, control, and multi-reagent positives

### Objective and non-goals

Generalize the existing editor driver and composed editor journey only enough
to execute cases 1 and 2, then register the two-case prefix. Add explicit
prepared reload plus exact reconstructed-assignment evidence. Do not add feasibility, exclusion, alternate-seed,
capacity, or negative-finalization behavior.

### Exact call path

```text
matrix selector -> fresh child -> experiment_design journey family
-> in-memory case fixture -> EditorPreparationSpec
-> ExperimentEditorDriver -> normal Qt New/configure/Optimize/Finalize
-> MainWindow -> Model authoritative finalization
-> Qt directory reload -> editable untouched-PREPARED inspection
-> Model saved-plan projection -> reconstructed assignments with runtime inactive
-> Controller idle-state observation
-> catalog/plan/progress/key/runtime assertion -> report-v1
```

### Contracts and evidence introduced

- reusable tuple-of-reagent inputs and explicit random-seed control;
- generated editor evidence for controls, stock-table rows, reaction count,
  and status;
- reuse of the prepared reload driver with exact `ready_to_start`, inactive
  runtime, and byte-identical-file checks;
- assertions `experiment.design_case_oracle_exact` and
  `experiment.prepared_runtime_reconstructed_exact`;
- additive `matrix_case` identity and `experiment_design_evidence` in
  report-v1;
- required action ID for prepared Qt directory load.

### Initial files expected to change

- `tools/virtual_workflows/experiment_design_cases.py`;
- `tools/virtual_workflows/matrices.py`;
- `tools/virtual_workflows/actions.py`;
- `tools/virtual_workflows/page_drivers.py`;
- `tools/virtual_workflows/journey_phases.py`;
- `tools/virtual_workflows/journeys.py`;
- `tools/virtual_workflows/assertions.py`;
- `tools/virtual_workflows/authoritative_evidence.py`;
- `tools/virtual_workflows/editor_reporting.py`;
- `tools/virtual_workflows/manifests/capability_coverage_v1.json` only for
  additive action/assertion vocabulary and corrected limitations;
- `tests/test_virtual_workflow_experiment_design_cases.py`;
- `tests/test_virtual_workflow_matrices.py`;
- `tests/test_virtual_workflow_page_drivers.py`;
- `tests/test_virtual_workflow_journey_phases.py`;
- `tests/test_virtual_workflow_assertions.py`;
- `tests/test_virtual_workflow_authoritative_evidence.py`;
- `tests/test_virtual_workflow_editor_reporting.py`;
- `tests/test_virtual_workflow_composition.py`;
- `tests/test_virtual_workflow_contract_freeze.py`;
- add `tests/system/test_virtual_workflow_experiment_design_matrix.py`;
- add Slice 10.2 implementation-plan/completion-record documents and update
  only the master-plan current action.

### Cases added

Register `single_reagent_control` and `multi_reagent_seed_4321`, in that
order. Freeze both case hashes and the two-case catalog hash.

### Targeted automated tests

Run the listed focused unit/contract tests and only the two selected
fresh-process system cases with `--run-sil-lifecycle`. Assert exact actions,
screenshots, plan/progress/key/concentration data, reload immutability,
reconstructed mapping, hardware isolation, and cleanup.

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_experiment_design_cases.py `
  tests\test_virtual_workflow_matrices.py `
  tests\test_virtual_workflow_matrix_runner.py `
  tests\test_virtual_workflow_actions.py `
  tests\test_virtual_workflow_page_drivers.py `
  tests\test_virtual_workflow_journey_phases.py `
  tests\test_virtual_workflow_assertions.py `
  tests\test_virtual_workflow_authoritative_evidence.py `
  tests\test_virtual_workflow_editor_reporting.py `
  tests\test_virtual_workflow_composition.py `
  tests\test_virtual_workflow_contract_freeze.py

.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_experiment_design_matrix.py `
  -k "single_reagent_control or multi_reagent_seed_4321"
```

### Manual or visible SIL checks

Run `multi_reagent_seed_4321` visibly on Windows and execute its retained
replay. Inspect the two reagent rows, random-seed control, generated stock
table, finalization, untouched-PREPARED reload state, and reconstructed well mapping.

### Retained evidence

Retain offscreen reports for both cases, the visible report/replay, report
hashes, catalog/case hashes, named screenshots, action/assertion ledgers,
authoritative inventories, and exact replay commands.

### Compatibility contracts

The existing editor scenario remains unchanged and directly runnable. The
existing prepared-inspection method remains nonactivating and editable for an
untouched PREPARED bundle. Existing matrix hashes and schemas remain frozen.

### Commit boundary

One commit: `test: add control and multi-reagent design SIL cases`.

### Risks and rollback

Primary risks are accidental changes to the legacy editor action sequence and
confusing reconstructed assignments with active runtime. Rollback removes the new
journey family/two-case registration and catalog-only driver extensions while
leaving the existing editor journey intact.

### Entrance and exit criteria

Entrance: Slice 10.1 committed and clean; two cases match their frozen
oracles. Exit: both cases pass targeted offscreen execution, the visible case
and replay pass, reconstructed runtime evidence is exact, focused tests pass,
and completion evidence is recorded.

### Validation deferred to Slice 10.6

The remaining seven cases, complete matrix/aggregate replay, lifecycle and
host regressions, and the full Python suite.

## Slice 10.3: One-stock and two-stock formulation feasibility

### Objective and non-goals

Add cases 3 and 4. Prove the hand-derived one-stock solution and the bounded
one-stock-rejection/two-stock-success transition through normal editor
controls. Do not add custom wells, exclusions, negative terminal cases, or a
production optimizer change.

### Exact call path

```text
typed formulation case -> editor stock inputs
-> Optimize & Generate
-> case 3 one-stock stock-table/target preview
or case 4 expected one-stock warning -> Qt toggle -> regenerate two-stock
-> normal Finalize -> authoritative files -> Qt reload/reconstruction
-> exact stock identity/count/reconstructed-assignment oracle
```

### Contracts and evidence introduced

- optional fixed/max stock inputs without sentinel numeric values;
- typed ordered optimization attempts with expected outcome/status;
- exact one-stock and two-stock stock rows and per-target count rows;
- evidence that case 4's rejected first attempt creates no execution plan
  before the later accepted attempt;
- no optimizer-derived expected value at assertion time.

### Initial files expected to change

- `tools/virtual_workflows/experiment_design_cases.py`;
- `tools/virtual_workflows/matrices.py`;
- `tools/virtual_workflows/actions.py`;
- `tools/virtual_workflows/page_drivers.py`;
- `tools/virtual_workflows/journey_phases.py`;
- `tools/virtual_workflows/journeys.py`;
- `tools/virtual_workflows/assertions.py`;
- `tools/virtual_workflows/manifests/capability_coverage_v1.json` if the
  explicit two-stock-toggle action requires additive vocabulary;
- `tests/test_virtual_workflow_experiment_design_cases.py`;
- `tests/test_virtual_workflow_matrices.py`;
- `tests/test_virtual_workflow_matrix_runner.py`;
- `tests/test_virtual_workflow_actions.py`;
- `tests/test_virtual_workflow_page_drivers.py`;
- `tests/test_virtual_workflow_journey_phases.py`;
- `tests/test_virtual_workflow_assertions.py`;
- `tests/test_virtual_workflow_composition.py`;
- `tests/test_virtual_workflow_contract_freeze.py`;
- `tests/system/test_virtual_workflow_experiment_design_matrix.py`;
- add `docs/sil_interactive_simulation_milestone_10_slice_3_implementation_plan.md`;
- add `docs/sil_interactive_simulation_milestone_10_slice_3_completion_record.md`;
- update only the Milestone 10 current-action text in
  `docs/sil_interactive_simulation_and_composable_workflows_plan.md`.

### Cases added

Append `one_stock_feasible` and `two_stock_required`. Preserve the first two
case hashes; freeze the four-case catalog hash and new case hashes.

### Targeted automated tests

Test the literal 5 mM one-stock and 5/10 mM two-stock oracle, ordered warning
and toggle actions, UI stock rows, target previews, plan/runtime stock IDs,
count rows, and failure on any extra/missing stock. Run only the two new
fresh-process system cases plus adjacent editor/matrix contracts.

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_experiment_design_cases.py `
  tests\test_virtual_workflow_matrices.py `
  tests\test_virtual_workflow_matrix_runner.py `
  tests\test_virtual_workflow_actions.py `
  tests\test_virtual_workflow_page_drivers.py `
  tests\test_virtual_workflow_journey_phases.py `
  tests\test_virtual_workflow_assertions.py `
  tests\test_virtual_workflow_composition.py `
  tests\test_virtual_workflow_contract_freeze.py

.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_experiment_design_matrix.py `
  -k "one_stock_feasible or two_stock_required"
```

### Manual or visible SIL checks

Run `two_stock_required` visibly and replay it. Inspect the one-stock failure
guidance, enabled two-stock toggle, two stock rows, successful Finalize, and
reconstructed assignments.

### Retained evidence

Retain both case reports, visible report/replay, the initial rejected-attempt
snapshot, stock-table screenshot, authoritative/runtime count evidence,
hashes, and replay commands.

### Compatibility contracts

Cases 1-2 and all Milestone 7-9 contracts remain unchanged. Two-stock support
is design-only; it does not extend calibration Apply or printing behavior.

### Commit boundary

One commit: `test: add formulation feasibility design SIL cases`.

### Risks and rollback

The main risk is silently accepting a different optimizer result as expected.
The literal oracle must fail instead. Any production mismatch opens a
separate correction plan. Rollback removes cases 3-4 and their bounded driver
branch while cases 1-2 remain independently runnable.

### Entrance and exit criteria

Entrance: Slice 10.2 committed and clean; the independent arithmetic for both
solutions is reviewed. Exit: both cases and the visible replay pass, exact
stock/count identities survive reload and reconstruction, earlier hashes remain
fixed, focused tests pass, and evidence is recorded.

### Validation deferred to Slice 10.6

The five remaining cases, complete matrix/replay, broader regressions, and
the full Python suite.

## Slice 10.4: Custom wells, exclusions, and deterministic randomization

### Objective and non-goals

Add cases 5 and 6. Stage exclusions only as an explicit isolated precondition,
drive the printable-well picker and random-seed spin box through Qt, and prove
exact assignments. Do not use manual/uploaded assignments, mutate production
plate catalogs, or add generated exploration.

### Exact call path

```text
case precondition -> isolated WellPlate.excluded_wells
-> Qt editor/well picker with disabled excluded cells
-> normal custom selection or random-seed control
-> Optimize/Finalize -> authoritative plan mapping
-> Qt reload -> reconstructed mapping
-> literal assignment and reaction-multiset oracle
```

### Contracts and evidence introduced

- typed isolated exclusion precondition and picker expectations;
- exact selected/disabled/assigned well evidence;
- random-seed control evidence and canonical reaction-multiset/assignment
  hashes;
- cross-case contract: cases 2 and 6 have the same multiset hash, distinct
  assignment hashes, and each case's exact replay reproduces its mapping;
- proof that the process-global RNG remains outside the matrix oracle.

### Initial files expected to change

- `tools/virtual_workflows/experiment_design_cases.py`;
- `tools/virtual_workflows/matrices.py`;
- `tools/virtual_workflows/actions.py`;
- `tools/virtual_workflows/page_drivers.py`;
- `tools/virtual_workflows/journey_phases.py`;
- `tools/virtual_workflows/journeys.py`;
- `tools/virtual_workflows/assertions.py`;
- `tests/test_virtual_workflow_experiment_design_cases.py`;
- `tests/test_virtual_workflow_matrices.py`;
- `tests/test_virtual_workflow_actions.py`;
- `tests/test_virtual_workflow_page_drivers.py`;
- `tests/test_virtual_workflow_journey_phases.py`;
- `tests/test_virtual_workflow_assertions.py`;
- `tests/test_virtual_workflow_composition.py`;
- `tests/test_virtual_workflow_contract_freeze.py`;
- `tests/system/test_virtual_workflow_experiment_design_matrix.py`;
- add `docs/sil_interactive_simulation_milestone_10_slice_4_implementation_plan.md`;
- add `docs/sil_interactive_simulation_milestone_10_slice_4_completion_record.md`;
- update only the Milestone 10 current-action text in
  `docs/sil_interactive_simulation_and_composable_workflows_plan.md`.

### Cases added

Append `custom_wells_with_exclusions` and `multi_reagent_seed_1234`.
Preserve hashes for cases 1-4 and freeze the six-case catalog hash.

### Targeted automated tests

Cover rejected selection of excluded cells, exact picker state, custom-well
normalization, exact plan/runtime assignments, same-design multiset equality,
different-seed mapping divergence, same-seed deterministic reconstruction,
global-RNG isolation, and malformed/duplicate well rejection. Run only cases
5-6 in fresh-process system tests plus adjacent contracts.

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_experiment_design_cases.py `
  tests\test_virtual_workflow_matrices.py `
  tests\test_virtual_workflow_actions.py `
  tests\test_virtual_workflow_page_drivers.py `
  tests\test_virtual_workflow_journey_phases.py `
  tests\test_virtual_workflow_assertions.py `
  tests\test_virtual_workflow_composition.py `
  tests\test_virtual_workflow_contract_freeze.py `
  tests\test_experiment_assignment_auto.py `
  tests\test_experiment_design_well_selection_ui.py

.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_experiment_design_matrix.py `
  -k "custom_wells_with_exclusions or multi_reagent_seed_1234"
```

### Manual or visible SIL checks

Run `custom_wells_with_exclusions` visibly and replay it. Inspect disabled
cells before selection, the selected-well summary, generated mapping, and
reloaded runtime. Inspect the two randomized offscreen reports side by side;
no extra visible randomized run is required in this slice.

### Retained evidence

Retain both case reports and replays, the visible exclusion screenshots,
selected/disabled/assigned sets, seed and mapping hashes, multiset hashes,
source/case/catalog identities, and cleanup evidence.

### Compatibility contracts

Manual uploaded well assignments retain their existing precedence and are not
used by these cases. Exclusions remain scenario-local and are never written
to the tracked plate catalog. Existing randomization behavior and global RNG
contract remain unchanged.

### Commit boundary

One commit: `test: add well selection and randomization design SIL cases`.

### Risks and rollback

Risks are confusing picker display order with authoritative identity and
leaking exclusions between sessions. Compare by exact well/reaction identity,
not incidental row position, and require teardown isolation. Rollback removes
cases 5-6 and their precondition/driver additions while cases 1-4 remain.

### Entrance and exit criteria

Entrance: Slice 10.3 committed and clean; exclusions are known to be
scenario-local. Exit: cases 5-6 and required replays pass, excluded wells are
never selectable/assigned, seed comparisons pass, earlier hashes remain
fixed, and focused tests/evidence are complete.

### Validation deferred to Slice 10.6

Capacity/rejection cases, complete matrix/replay, broader regressions, and
the full Python suite.

## Slice 10.5: Exact capacity and rejected finalization boundaries

### Objective and non-goals

Append cases 7-9 and complete the catalog. Prove exact capacity succeeds and
both over-capacity and infeasible formulations fail through the real Finalize
control with exact warning/status and no authoritative execution mutation.
Do not repair or bypass a production guard.

### Exact call path

Positive case:

```text
four-reaction/four-well Qt design -> Finalize
-> authoritative PREPARED bundle -> Qt reload/reconstruction
-> exact reconstructed mapping
```

Negative cases:

```text
normal Qt New/configuration -> pre-attempt directory/runtime snapshot
-> click Finalize Design
-> expected capacity or optimization warning/status
-> QTest dismiss -> post-attempt snapshot
-> no-new/no-changed authoritative execution evidence -> report-v1
```

### Contracts and evidence introduced

- expected-finalization terminal kinds and exact warning/status contracts;
- reusable expected-modal Finalize driver with bounded title/message matching;
- shared `experiment.finalization_rejected_no_mutation` assertion;
- byte-level directory comparison plus explicit absence of execution plan,
  revision, key, concentration key, resume, runtime, intent, simulator,
  completion, and array-start evidence;
- final nine-case order, pairwise audit, case hashes, and catalog hash.

### Initial files expected to change

- `tools/virtual_workflows/experiment_design_cases.py`;
- `tools/virtual_workflows/matrices.py`;
- `tools/virtual_workflows/actions.py`;
- `tools/virtual_workflows/page_drivers.py`;
- `tools/virtual_workflows/journey_phases.py`;
- `tools/virtual_workflows/journeys.py`;
- `tools/virtual_workflows/assertions.py`;
- `tools/virtual_workflows/authoritative_evidence.py`;
- `tools/virtual_workflows/editor_reporting.py`;
- `tools/virtual_workflows/manifests/capability_coverage_v1.json` for final
  action/assertion vocabulary only;
- `tests/test_virtual_workflow_experiment_design_cases.py`;
- `tests/test_virtual_workflow_matrices.py`;
- `tests/test_virtual_workflow_matrix_runner.py`;
- `tests/test_virtual_workflow_actions.py`;
- `tests/test_virtual_workflow_page_drivers.py`;
- `tests/test_virtual_workflow_journey_phases.py`;
- `tests/test_virtual_workflow_assertions.py`;
- `tests/test_virtual_workflow_authoritative_evidence.py`;
- `tests/test_virtual_workflow_editor_reporting.py`;
- `tests/test_virtual_workflow_composition.py`;
- `tests/test_virtual_workflow_contract_freeze.py`;
- `tests/system/test_virtual_workflow_experiment_design_matrix.py`;
- add `docs/sil_interactive_simulation_milestone_10_slice_5_implementation_plan.md`;
- add `docs/sil_interactive_simulation_milestone_10_slice_5_completion_record.md`;
- update only the Milestone 10 current-action text in
  `docs/sil_interactive_simulation_and_composable_workflows_plan.md`.

### Cases added

Append `exact_custom_capacity`, `capacity_plus_one_rejected`, and
`fixed_stock_exceeds_max_rejected`. Preserve hashes for cases 1-6 and freeze
all nine case hashes plus the final catalog and representative dry-run plan
hashes.

### Targeted automated tests

Cover exact capacity acceptance, required/available count drift, exact modal
order/title/fragments, status evidence, baseline timing, any changed/new file,
runtime mutation, action leakage, missing dialog, extra dialog, and malformed
negative oracle. Run only cases 7-9 in fresh-process system tests plus the
focused contracts.

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_experiment_design_cases.py `
  tests\test_virtual_workflow_matrices.py `
  tests\test_virtual_workflow_matrix_runner.py `
  tests\test_virtual_workflow_actions.py `
  tests\test_virtual_workflow_page_drivers.py `
  tests\test_virtual_workflow_journey_phases.py `
  tests\test_virtual_workflow_assertions.py `
  tests\test_virtual_workflow_authoritative_evidence.py `
  tests\test_virtual_workflow_editor_reporting.py `
  tests\test_virtual_workflow_composition.py `
  tests\test_virtual_workflow_contract_freeze.py `
  tests\test_experiment_design_capacity_guard.py `
  tests\test_experiment_design_stock_input_validation.py

.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_experiment_design_matrix.py `
  -k "exact_custom_capacity or capacity_plus_one_rejected or fixed_stock_exceeds_max_rejected"
```

### Manual or visible SIL checks

Run `exact_custom_capacity` and both rejection cases visibly; execute each
retained replay. Inspect the four assigned wells, `Insufficient Well Capacity`
with `5`/`4`, `Optimization failed` with `exceeds max stock`, and the negative
inventory/no-activation evidence.

### Retained evidence

Retain all three case reports/replays, warning-visible screenshots, exact
directory inventories and hashes, missing-artifact lists, zero-dispatch
evidence, final catalog/case/plan hashes, and replay commands. Failed
qualification attempts remain retained and are never overwritten.

### Compatibility contracts

The production warning strings and safeguards are observed, not altered.
Draft initialization remains allowed and explicitly separated from execution
artifacts. Existing report/matrix schemas, editor paths, and cases 1-6 remain
unchanged.

### Commit boundary

One commit: `test: add experiment design rejection boundaries`.

### Risks and rollback

The main risk is a false no-mutation claim caused by baselining too early or
ignoring draft files. Baseline immediately before Finalize and compare every
file, while separately requiring execution artifacts absent. Any production
mutation is a blocker requiring a correction plan. Rollback removes cases
7-9 and expected-rejection tooling while cases 1-6 remain runnable.

### Entrance and exit criteria

Entrance: Slice 10.4 committed and clean; the two production warning
contracts are captured by focused tests. Exit: case 7 succeeds, cases 8-9
fail closed exactly, visible replays pass, the nine-case pairwise audit and
hash freezes pass, prior hashes remain unchanged, and completion evidence is
recorded.

### Validation deferred to Slice 10.6

The complete nine-case aggregate/replay, lifecycle and host-regression suites,
and the full Python suite.

## Slice 10.6: Qualification, retained evidence, documentation, and closeout

### Objective and non-goals

Qualify the source-current complete nine-case matrix and compatibility lanes,
replay them, rerun representative visible positive/negative cases, inspect
retained evidence, update operator documentation, and close Milestone 10.
This is a qualification/documentation slice; source defects require a separate
reviewed correction and a complete qualification restart.

### Exact call path

```text
clean committed Slice 10.5 source
-> matrix list and deterministic dry-run
-> complete nine-case fresh-process matrix
-> exact aggregate replay
-> selected visible cases and exact replays
-> lifecycle and host-regression suite aggregates/replays
-> full default pytest suite once
-> evidence/hash inspection -> documentation-only closeout
```

### Contracts and evidence introduced

- final source identity, matrix listing, catalog hash, ordered case hashes,
  and dry-run plan hash;
- aggregate/replay child identity and report hash audit;
- cross-report same-seed/different-seed comparison;
- final completion record with representative positive, two-stock, exclusion,
  randomization, exact-capacity, and negative no-mutation evidence;
- operator commands, selection guidance, limitations, and troubleshooting.

### Initial files expected to change

- add `docs/sil_interactive_simulation_milestone_10_slice_6_implementation_plan.md`;
- add `docs/sil_interactive_simulation_milestone_10_slice_6_completion_record.md`;
- update `README.md`;
- update `docs/sil_virtual_workflow_operator_runbook.md`;
- update only Milestone 10 status/results and Current Next Action in
  `docs/sil_interactive_simulation_and_composable_workflows_plan.md`.

No code, fixture, manifest, or production file is expected to change in this
slice.

### Cases added

None. Qualify the frozen nine-case catalog from Slice 10.5.

### Targeted and complete automated validation

Before execution, record a clean worktree, exact commit/source fingerprint,
matrix listing, and dry-run plan. Then run:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --matrix experiment_design_pairwise_v1 `
  --output-root verification_reports\matrices `
  --seed 1 --speed-multiplier 1000 --timeout-seconds 90 `
  --qt-platform offscreen

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --suite lifecycle --output-root verification_reports\suites `
  --seed 1 --speed-multiplier 1000 --qt-platform offscreen

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --suite host_regression --output-root verification_reports\suites `
  --seed 1 --speed-multiplier 1000 --qt-platform offscreen

.\env\Scripts\python.exe -m pytest -q --basetemp <fresh-external-temp-path>
```

Execute the emitted exact replay for the matrix and both suite aggregates.
Run the full Python suite exactly once after all selected/focused gates pass;
do not enable the unrelated analysis pipeline.

### Manual or visible SIL checks

With `QT_QPA_PLATFORM=windows`, `--visible`, 20x speed, and a 120-second
watchdog, run and exactly replay:

- `multi_reagent_seed_4321`;
- `two_stock_required`;
- `custom_wells_with_exclusions`;
- `capacity_plus_one_rejected`;
- `fixed_stock_exceeds_max_rejected`.

Inspect every named screenshot, warning/status, assignment, child process,
report classification, hardware-isolation field, and cleanup result.

### Retained evidence

Retain the matrix plan/aggregate/replay, lifecycle and host-regression
aggregates/replays, all authoritative child reports, visible reports/replays,
screenshots, logs, manifests, SHA-256 values, source identity, and full-suite
result cited by the completion record. Do not delete historical failures or
earlier slice evidence.

### Compatibility contracts

All frozen contracts in this document must still pass. Additionally verify
the two Milestone 9 catalog hashes and representative dry-run plan hashes,
the unchanged editor fixture hash, report-v1, matrix plan/aggregate v1,
legacy editor direct/composed contracts, exact replay behavior, and hardware
isolation.

### Commit boundary

One documentation closeout commit:
`test: close experiment design SIL milestone`.

### Risks and rollback

Any source correction invalidates prior source-current closeout evidence and
restarts Slice 10.6 after its separate commit. Rollback reverts only the
Slice 10.6 documentation commit; Slices 10.1-10.5 and retained historical
evidence remain intact. No artifact cleanup is part of rollback.

### Entrance and exit criteria

Entrance: Slices 10.1-10.5 committed, reviewed, clean, and individually
complete; all nine case/catalog hashes are frozen. Exit: matrix and replay
pass 9/9; visible positive/negative cases and replays pass; lifecycle and
host-regression suites/replays pass; the full default Python suite passes;
representative evidence is inspected and hashed; documentation is current;
`git diff --check` passes; and Milestone 10 is recorded complete.

### Validation deferred beyond Milestone 10

Host stress, Pi qualification, firmware checks, physical hardware, release
operations, Milestone 11 design/calibration/execution interaction, Milestone
12 safeguards outside finalization, Milestone 13 exploration, and
refill-required/resume.

## Autonomous execution rules

For each future Goal-mode slice:

1. Confirm the prior slice's completion commit/record and a clean worktree.
2. Write the slice-specific implementation plan before code changes, restating
   its exact call path, files, tests, safety boundary, and rollback.
3. Implement only that slice's cases and the smallest reusable harness change.
4. Stop on any independent-oracle mismatch that indicates a production
   defect; do not weaken the oracle or patch production within the slice.
5. Run only the slice's targeted validation and selected SIL cases/replays.
6. Inspect and hash retained evidence, write the completion record, run
   `git diff --check`, and make exactly the suggested independent commit.
7. Recheck cleanliness and recorded hashes before advancing.

No material architecture, production behavior, schema, or scope decision is
left open by this plan. Reversible names and formatting may be chosen locally
without stopping. A future agent should surface only evidence that would
require production changes, a report/matrix schema change, a new tracked
fixture, a change to the nine-case scope, or expansion into hardware-related
work.
