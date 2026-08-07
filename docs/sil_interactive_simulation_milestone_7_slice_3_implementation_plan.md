# Milestone 7 Slice 3 — Composed Prepared Edit/Refinalize

Status: `implemented — approved and completed on 2026-08-06`

Planning baseline: `f8bba35b83593c5b4dfd7a70844c5463d1404f45`.

## Objective

Migrate only `experiment_editor_prestart_rename_refinalize_v1` from the
branch-heavy legacy editor runner to the Slice 2.5 typed composition layer.
The composed journey will create and finalize the initial A1/A2 design, reopen
the untouched prepared design through the normal Experiment Editor control,
rename it, materially revise it to the tracked six-well stream design,
regenerate and refinalize it, and reopen the result through the normal Qt
folder-selection path. It must preserve the authoritative prepared-execution,
archive, runtime-assignment, key-file, evidence, failure, and teardown
contracts already covered by the legacy scenario.

This slice does not migrate soft stop/resume, authoritative reload/resume,
post-start lock/editable copy, 96-well regression, 384x10 stress, disconnect,
or another workflow. It does not add a parameter matrix, seeded sequence
exploration, fault injection, performance remediation, Pi operation,
firmware/protocol work, or hardware operation.

No file under `FreeRTOS-interface/` or `firmware/` is in scope.

## Audit Baseline

- The worktree was clean at the planning baseline.
- Milestone 7 Slices 1, 2, and 2.5 are committed and their tracked plans,
  completion records, implementation, and tests are present.
- The retained Slice 2.5 baseline, post-refactor, and visible evidence roots
  are present locally. This plan relies on the tracked completion record for
  their reviewed results and does not reinterpret them as Slice 3 evidence.
- The tracked Slice 3 fixture contract test passed.
- The existing legacy success and controlled-refinalization-failure lifecycle
  nodes passed with `--run-sil-lifecycle`: `2 passed` in 3.79 seconds. The
  initial invocation without that option correctly skipped the two marked
  lifecycle nodes.
- The complete Python suite was not run and remains deferred to the final
  Milestone 7 validation.

## Current Call Paths And Duplication

### Registry and legacy automation

```text
tools/run_virtual_workflow.py
  -> registry.run_registered_scenario()
  -> runner_family == "experiment_editor"
  -> scenario-ID branches
  -> editor_scenarios.run_editor_prestart_rename_refinalize_scenario()
  -> _run_editor_lifecycle_scenario()
       -> create/finalize common branch
       -> rename/refinalize branch
       -> scenario-specific validation/failure mapping/report assembly
       -> legacy teardown
```

`_run_editor_lifecycle_scenario()` is approximately 1,800 lines and owns
session construction, application launch, three editor scenario branches,
read-only persistence inspection, assertion bookkeeping, failure mapping,
screenshots, report-v1 assembly, and teardown. These generic responsibilities
now duplicate `JourneyExecutor`, `AutomationHarness`, and
`ComposedReportAdapter`.

`drive_editor_prestart_rename_refinalize()` already performs the needed
bounded QTest operations, but it calls the legacy action executor internally.
Copying that roughly 500-line modal driver into a new journey would recreate
the problem Slice 2.5 solved. Slice 3 will add the same injected action-runner
boundary already used by `drive_editor_create_finalize()` and expose it
through the single `ExperimentEditorDriver` surface.

The legacy branch also contains a large inline refinalized-bundle inspector.
Its checks belong in reusable, read-only assertion helpers, not in the new
journey body.

### Production application path exercised

```text
QTest -> WellPlateWidget "Experiment Editor" button
  -> View.open_experiment_designer()
  -> ExperimentDesignDialog
       -> New Experiment -> MainWindow.start_new_experiment_session()
          -> Controller.start_new_experiment_session() -> Model
       -> normal line edit/spin/combo/well-selection controls
          -> ExperimentDesignDialog -> ExperimentModel
       -> Optimize & Generate -> ExperimentModel design generation
       -> Finalize Design -> MainWindow.complete_experiment_design()
          -> Model.load_experiment_from_model() for initial finalization
          -> Model.commit_prepared_experiment_design_from_editor() for
             prepared rename/refinalization
          -> ExperimentModel.rename_experiment() and authoritative writers
       -> Load Design... -> Qt folder dialog -> ExperimentModel load
```

The editor intentionally updates `ExperimentModel` from its View/dialog for
most design operations; it does not route every field through `Controller`.
That is the production application path, not an automation bypass. The SIL
constructs a simulated application profile but this journey never connects
the machine or issues a command. There is therefore no comms or firmware
handler in the path and no physical behavior claim.

### Target composed path

```text
CLI / generic registry dispatch
  -> run_composed_journey(JourneyRunConfig)
  -> JourneyDefinition for prepared rename/refinalize
  -> JourneyExecutor / AutomationHarness / SimulationSession
       -> existing editor-preparation phase for initial design
       -> PreparedEditorRevisionSpec
       -> reusable prepared-revision phase
          -> ExperimentEditorDriver
          -> existing bounded QTest mechanics with harness action runner
       -> reusable prepared/refinalized/reload assertions
       -> existing ExperimentLoaderDriver through Qt folder dialog
       -> ComposedReportAdapter
       -> shared failure evidence and teardown
```

The new journey body must be a short composition of those pieces. It must not
contain its own Qt timer loop, persistence parser, report envelope, or teardown
implementation.

## Frozen Slice Decisions

1. **One migration only.** Keep the existing scenario ID, scenario name,
   version, fixture bytes, completion count, required assertion IDs, and
   capability claims. Do not register a variation or add suite membership.
2. **Reuse the current modal mechanics.** Add an optional harness action runner
   to the existing prepared-revision QTest routine and a page-driver method
   that delegates to it. Preserve the default legacy executor so the old
   direct runner remains callable as the parity oracle. Do not duplicate the
   modal implementation.
3. **Typed phase input.** Add one frozen, validated
   `PreparedEditorRevisionSpec` derived from the tracked fixture. Values such
   as names, wells, volumes, modes, targets, and replicate count are data; they
   do not produce a new runner or registry branch.
4. **Truthful action surfaces.** The editor open, rename, edit, regenerate,
   refinalize, and prepared folder-load operations must all report `ui` and be
   driven through QTest. Assertions, screenshots, report work, and teardown
   report `harness`. No direct Model mutation may claim UI coverage.
5. **Explicit reviewed action-contract change.** Remove the legacy
   `validation.prepared_bundle`, `validation.refinalized_bundle`, and direct
   `experiment.reload_authoritative` entries from this scenario's manifest
   action list. Read-only validation belongs in assertion results, and reload
   will use `experiment.load_authoritative_via_ui`. The required assertion IDs
   remain unchanged.
6. **Read-only persistence inspection.** Reusable assertion helpers may read
   the design, plan/history, progress, calibration, audit, hashes, key files,
   archive, and directory layout. They may not repair, rewrite, activate, or
   advance application state.
7. **Stable report parity, not byte identity.** Preserve the workload meaning,
   assertion decisions, persistence evidence, terminal prepared state,
   screenshots, failure classification, seed, and replay command. Allow the
   composed report's standard artifact/ledger fields and nondeterministic
   IDs, paths, hashes containing IDs, timestamps, and durations.
8. **Targeted validation only.** Run the focused tests and visible/replay gate
   below. Do not run the full suite until the final Milestone 7 validation.

## Exact Files To Touch During Implementation

Required implementation files:

- `tools/virtual_workflows/actions.py`
- `tools/virtual_workflows/page_drivers.py`
- `tools/virtual_workflows/journey_phases.py`
- `tools/virtual_workflows/assertions.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/registry.py`
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`

Required focused tests:

- `tests/test_virtual_workflow_actions.py`
- `tests/test_virtual_workflow_page_drivers.py`
- `tests/test_virtual_workflow_journey_phases.py`
- `tests/test_virtual_workflow_assertions.py`
- `tests/test_virtual_workflow_manifest.py`
- `tests/test_virtual_workflow_contract_freeze.py`
- new `tests/system/test_virtual_workflow_editor_refinalize_composed.py`

Required implementation documentation:

- `README.md`
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- this implementation plan, for status only
- new
  `docs/sil_interactive_simulation_milestone_7_slice_3_completion_record.md`

The tracked fixture
`tools/virtual_workflows/fixtures/experiment_editor_prestart_rename_refinalize_v1.json`
must remain byte-identical. `editor_scenarios.py`, `composition.py`,
`harness.py`, `report.py`, production MVC files, simulator response models,
Pi scripts, firmware, protocol, and hardware files are not expected to change.
If implementation proves one of those files necessary, stop and revise this
plan before editing it.

## Implementation Steps

1. **Freeze the legacy baseline and contracts.** Run the existing fixture,
   success, and controlled failure nodes; retain one direct legacy report; and
   record its stable workload, action/assertion order, persistence keys,
   screenshots, failure decisions, and cleanup outcome. Do not edit the
   fixture or legacy scenario runner.
2. **Expose the existing QTest mechanics through the shared surface.** Add the
   optional action-runner hook to `drive_editor_prestart_rename_refinalize()`;
   add `ExperimentEditorDriver.revise_prepared_design()`; and verify that both
   legacy and harness runners receive exactly the five semantic editor action
   boundaries without duplicating the modal loop.
3. **Add the typed prepared-revision phase.** Define and validate
   `PreparedEditorRevisionSpec`, add a normalized action-plan helper, and add
   `run_prepared_editor_revision()`. Unit-test alternate valid values/orderable
   inputs and invalid names, wells, modes, targets, and volumes without
   registering or executing additional workflows.
4. **Extract reusable read-only assertions.** Add helpers that snapshot the
   initial prepared identity and evaluate rename isolation, material design
   changes, fresh plan identity, superseded-plan/design archive, zero progress,
   empty calibration history, unique directory/current plan, audit advance,
   key/concentration consistency, reload readiness, and runtime assignments.
   Preserve the ten existing required assertion IDs and fail closed on missing
   or ambiguous evidence.
5. **Compose and register the journey.** Add the fixture loader, concise body,
   required actions/UI actions/screenshots/assertions, bounded report payload,
   summary, and `JourneyDefinition` in `journeys.py`. Change only this registry
   entry to `composed_journey`; leave the post-start editor workflow on the
   legacy family and remove no legacy callable.
6. **Update manifest and contract tests.** Replace the three reviewed legacy
   action entries with the normal-UI prepared-load action, point test nodes at
   the new composed system test, and verify the exact action/assertion/
   capability/artifact contract and generic registry dispatch. Do not change
   suite membership or claim new coverage.
7. **Run focused parity, failure, visible, and replay gates.** Compare composed
   success against the retained legacy report using an explicit stable-field
   projection; inject a failure at refinalization and verify failed/incomplete
   assertions, screenshot retention, teardown, and unlocked session state;
   then run one visible CLI journey and its emitted replay command and compare
   stable projections.
8. **Document and close the slice.** Update README commands, roadmap status,
   limitations, troubleshooting, exact test results, visible/replay evidence,
   risks, and rollback in a completion record. Stop before soft stop/resume or
   any other Milestone 7 migration.

## Focused Automated Gates

Use an explicit temp-root base outside the repository because reused Windows
pytest roots may be inaccessible and repository-contained bases correctly
violate `SimulationSession` root-containment rules.

```powershell
.\env\Scripts\python.exe -m pytest -q `
  --basetemp "$env:TEMP\LabCraft\pytest-m7-slice3-unit" `
  tests\test_virtual_workflow_actions.py `
  tests\test_virtual_workflow_page_drivers.py `
  tests\test_virtual_workflow_journey_phases.py `
  tests\test_virtual_workflow_assertions.py `
  tests\test_virtual_workflow_composition.py `
  tests\test_virtual_workflow_report.py `
  tests\test_virtual_workflow_manifest.py `
  tests\test_virtual_workflow_contract_freeze.py
```

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  --basetemp "$env:TEMP\LabCraft\pytest-m7-slice3-lifecycle" `
  tests\system\test_virtual_workflow_editor_composed.py `
  tests\system\test_virtual_workflow_editor_refinalize_composed.py `
  tests\system\test_virtual_workflow_editor_lifecycle.py
```

Run the three lifecycle files individually if a combined in-process Windows
Qt run stops making progress. A hung combined process is not allowed to turn
into a silent 15-minute wait: stop it, identify and terminate only confirmed
orphan processes for that run, then run the exact affected nodes separately.
Every node must pass; isolation is diagnostic, not a waiver.

Also run:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  --basetemp "$env:TEMP\LabCraft\pytest-m7-slice3-adjacent" `
  tests\test_experiment_dialog_handoff_minimal.py `
  tests\test_initial_execution_plan_integration.py `
  tests\test_execution_artifact_policy.py `
  tests\test_authoritative_execution_load.py

.\env\Scripts\python.exe -m py_compile `
  tools\virtual_workflows\actions.py `
  tools\virtual_workflows\page_drivers.py `
  tools\virtual_workflows\journey_phases.py `
  tools\virtual_workflows\assertions.py `
  tools\virtual_workflows\journeys.py `
  tools\virtual_workflows\registry.py

git diff --check
```

## Visible And Replay Gate

Run once with the normal UI visible:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario experiment_editor_prestart_rename_refinalize_v1 `
  --output-root verification_reports\milestone7-slice3-visible `
  --visible --seed 1 --speed-multiplier 2 --timeout-seconds 60
```

Inspect the retained report and screenshots and require:

- simulation banner present and all hardware interfaces disabled;
- exact editor action ordering and `ui` surfaces;
- initial A1/A2 prepared design followed by renamed A1-A6 stream design;
- a fresh revision-1 `PREPARED` plan with zero progress and no resume state;
- old directory absent, one renamed directory, no staging directories, one
  current plan, and intact superseded plan/design archive;
- changed runtime assignments matching the new plan and unchanged after UI
  reload;
- all ten assertions passing;
- all ten milestone screenshots present and non-empty;
- no unexpected dialogs, errors, failed actions, or failed cleanup;
- report, summary, events, ledgers, evidence manifest, stdout, and scenario
  root retained; and no failure traceback or session lock.

Then execute the exact `run.replay_command` emitted by that report into the
same output root. Compare the stable report projection, fixture hash, seed,
action IDs/order/surfaces/statuses, assertion decisions, workload values,
prepared/refinalized state, archive checks, screenshot names, and
classification. Ignore only documented nondeterministic identities, paths,
timestamps, durations, and identity-bearing hashes.

## Risks And Mitigations

- **QTest duplication or another large journey:** reuse the current modal
  routine through injection and enforce focused source-shape tests that the
  journey body contains no QTimer/QTest loop, report writer, or teardown.
- **Action-ledger drift:** freeze exact action order and surfaces. Treat the
  direct-reload-to-UI-load change as an explicit manifest update, not silent
  parity.
- **Rename/refinalize mutates the wrong bundle:** assert initial and final
  plan/design identities, archive content, directory uniqueness, progress,
  calibration history, audit, and runtime assignments.
- **Validation accidentally changes state:** keep inspectors read-only and
  test hashes/state before and after assertion evaluation.
- **Failure leaves dialogs or locks:** inject at refinalization, require failure
  screenshot and retained ledgers, and assert cleanup closes dialogs,
  simulator resources, stdout capture, and the session lock.
- **Over-generalization:** introduce only one typed revision spec and one
  reusable phase exercised by this scenario plus pure variation tests. No DSL,
  plugin registry, matrix runner, or seeded generator.
- **Windows Qt batching instability:** use bounded 60-second scenario
  deadlines, explicit external temp roots, and isolated node reruns when a
  combined process demonstrably stalls.

## Rollback

Keep `run_editor_prestart_rename_refinalize_scenario()` and the default legacy
action executor intact until all gates pass. If the migration fails, restore
only this registry entry and manifest test-node/action metadata to the
`experiment_editor` compatibility family; remove the prepared-revision
definition, phase/spec, assertion helpers, driver hook tests, composed system
test, and Slice 3 documentation. Do not revert the Slice 2.5 executor,
existing composed journeys, fixture, production experiment data, or other
Milestone 7 work.

No firmware/protocol, Pi, production MVC, or hardware rollback is required.

## Approval Gate

This plan was approved and implemented. Its approval covered only the exact
scope, files, eight steps, targeted-test policy, visible/replay gate, and
rollback above. Slice 4 and every production MVC change, fixture revision,
additional workflow migration, active matrix, or seeded exploration remain
unapproved.
