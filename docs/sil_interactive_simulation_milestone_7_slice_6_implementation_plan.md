# Milestone 7 Slice 6 - Composed Post-Start Lock/Editable Copy

Status: `implemented and validated on 2026-08-06`

Completion record:
`docs/sil_interactive_simulation_milestone_7_slice_6_completion_record.md`

Planning baseline: `1db0ce658329cb9dbd17b2f18422b08e27bef54c` with
Milestone 7 Slice 5 committed and a clean worktree before this planning-only
documentation update.

## Objective

Migrate only `experiment_editor_post_start_lock_v1` from the branch-heavy
legacy editor runner to the Milestone 6 / Slice 2.5 typed composition harness.
The journey will create and finalize the tracked A1/A2 design through normal
Qt controls, explicitly activate its authoritative runtime and cross the
zero-progress `printing_started` lock boundary through two truthfully reported
Model actions, reopen the real editor, prove every in-place mutation surface
is locked, create an editable copy through the normal dialog, make the
tolerance-only edit, finalize the copy, and reload the resulting prepared
copy through the normal editor folder dialog without activating it.

This slice does not connect a simulated machine, issue a print command, claim
that activation or the synthetic lock was driven through the UI, or change
production behavior. It does not migrate the 96-well regression, 384x10
stress, disconnect, or another workflow. It does not add parameter matrices,
seeded sequence exploration, simulator/product fault injection, performance
remediation, Pi operation, firmware/protocol work, or hardware operation.

No file under `FreeRTOS-interface/`, `firmware/`, the simulator response model,
or the fixture is in scope.

## Audit Baseline

- HEAD is `1db0ce658329cb9dbd17b2f18422b08e27bef54c`; the worktree, complete
  diff, and `git diff --check` were clean before this plan was written.
- Slice 5 is present and routes `authoritative_reload_resume_24_v1` through
  `composed_journey`. The shared harness, page drivers, typed phases,
  authoritative evidence, assertions, editor reporting, and generic registry
  dispatch are available.
- `experiment_editor_post_start_lock_v1` remains the sole next migration in
  the roadmap and still has `runner_family="experiment_editor"`.
- The fixture remains schema v1 with source
  `sil-editor-post-start-lock-v1`, copy `sil-editor-post-start-copy-v1`, plate
  `shallow-384_well_plate`, wells A1/A2, one 1x droplet stock, 10 nL printed
  and final volume, source tolerance 0 nL, and copy tolerance 1 nL.
- The fixture SHA-256 is
  `37EB774BC484C875F4B4115FCBCCA4E7AE3C511D6FF21302CCC512681B532FD2`.
- Its three existing fixture, success, and controlled-failure tests passed
  before planning: `3 passed in 23.16s` with `--run-sil-lifecycle`.
- The full Python suite was not run and remains deferred to the final
  Milestone 7 validation.

## Current Call Paths And Duplication

### Legacy automation path

```text
tools/run_virtual_workflow.py
  -> registry.run_registered_scenario()
  -> runner_family == "experiment_editor"
  -> editor_scenarios.run_editor_lifecycle_scenario(post_start_lock=True)
       -> common create/finalize branch
       -> direct Model.load_authoritative_execution_runtime()
       -> direct ExperimentModel.lock_execution_plan("printing_started")
       -> authoritative bundle/directory validation embedded in runner
       -> actions.drive_editor_post_start_lock_and_copy()
            -> private QTimer/QTest modal state machine
            -> inspect locked controls and reject an in-place edit
            -> drive the editable-copy name dialog
            -> edit, optimize, and finalize the copy
       -> copy/source bundle validation embedded in runner
       -> direct Model.load_experiment() and runtime activation for reload
       -> legacy report/failure/teardown assembly
```

The raw post-start editor driver is over 400 lines in `actions.py`, although
the repository now assigns raw QTest ownership to one page driver per
application surface. Source-lock, copy freshness, source immutability, reload,
assertion routing, report, and teardown policy remain interleaved in the
legacy scenario-family branch. The final legacy reload directly mutates the
Model and activates the copy even though `ExperimentLoaderDriver` can inspect
a prepared design through the real editor and leave it inactive.

The two synthetic setup actions are also currently classified by the default
action map as `harness`. They call production Model APIs and must be reported
as `model`; neither may contribute to UI coverage.

### Production application path exercised

```text
QTest -> Experiment Editor -> New Experiment -> configure/generate/finalize
  -> ExperimentDesignDialog -> ExperimentModel finalization writers

typed Model step -> Model.load_authoritative_execution_runtime()
typed Model step -> ExperimentModel.lock_execution_plan("printing_started")
  -> revision-2 ACTIVE plan/progress/resume/audit persistence

QTest -> Experiment Editor
  -> ExperimentDesignDialog lifecycle classifier
  -> read-only controls, "Execution Loaded", and copy guidance
QTest -> Create Editable Copy...
  -> ExperimentDesignDialog._on_duplicate_design()
  -> ExperimentModel.duplicate_design_from()
  -> fresh copy beside the source, without execution history
QTest -> tolerance edit -> Optimize/Generate -> Finalize Design
  -> fresh revision-1 PREPARED authoritative bundle
QTest -> Load Design... -> QFileDialog folder selection -> inspect -> Escape
  -> prepared copy remains runtime-inactive and ready_to_start
```

The SIL boundary ends before Controller/comms/SimulatedMachine. This slice
changes no production MVC, device protocol, firmware, motion, pressure,
timing-sensitive hardware, calibration behavior, or physical dispensing.

### Target composed path

```text
generic registry dispatch -> JourneyExecutor -> AutomationHarness
  -> existing run_editor_preparation(EditorPreparationSpec)
  -> typed authoritative activation and printing-start lock Model steps
  -> shared immutable source-lock evidence/assertion phase
  -> ExperimentEditorDriver.inspect_lock_and_create_editable_copy(...)
  -> shared immutable source/copy evidence/assertion phase
  -> ExperimentLoaderDriver.load_prepared_design(...)
  -> existing editor report adapter and generic failure/teardown
```

The named journey body must remain a short composition. It must not install a
Qt timer loop, parse persistence files, construct a report envelope, implement
teardown, or duplicate source/copy validation policy.

## Frozen Slice Decisions

1. **One migration only.** Preserve the scenario ID, name, version, fixture
   bytes/hash, lifecycle suite membership, workload values, nine required
   assertion IDs, ten milestone/screenshot names, and expected pass outcome.
2. **Retain the deliberate zero-progress boundary.** Use the public
   `load_authoritative_execution_runtime()` and
   `lock_execution_plan("printing_started")` APIs without connecting a
   machine or issuing a print command. This isolates editor lifecycle policy
   and is not evidence that normal printing-start UI was exercised.
3. **Truthful surfaces.** `experiment.activate_authoritative` and
   `execution.lock_for_printing` report `model`. Editor create, lock
   inspection, rejection, copy, edit, finalize, and prepared reload report
   `ui`. Milestones, assertions, snapshots, waits, reporting, and teardown
   report `harness`.
4. **One page driver per surface.** Move the bounded post-start timer/QTest
   mechanics and lock-control inspection into `ExperimentEditorDriver`.
   Semantic action wrappers retain action IDs, and the direct oracle delegates
   to the same driver while parity is required.
5. **Read-only authoritative policy.** Centralized evidence/assertions compare
   the locked source before/after copy byte-for-byte and validate a distinct,
   fresh, revision-1 PREPARED copy with no resume, progress, calibration, or
   inherited history. Assertion helpers may not activate, repair, or write.
6. **UI reload does not activate.** Reload the finalized copy with
   `ExperimentLoaderDriver.load_prepared_design()`, require
   `ready_to_start`, runtime inactive, exact plan identity, and no resume
   sidecar. Remove the direct runtime-activating reload from the composed path.
7. **Reuse before extension.** Use the existing editor preparation phase,
   authoritative bundle/directory projection, prepared reload assertions,
   editor report adapter, generic executor, evidence manifest, and teardown.
   Add one typed post-start spec/phase and one assertion family, not a runner.
8. **Targeted validation only.** Run the focused gates below. The full Python
   suite remains deferred until the final Milestone 7 validation.

Generated plan IDs, paths, timestamps, durations, and identity-bearing hashes
may differ between direct and composed reports. Stable source/copy semantics,
ledger order/surfaces, persistence relationships, assertions, screenshots,
classification, and cleanup must match.

## Frozen Composed Contract

Required assertions remain exactly:

```text
sil.host_hardware_disabled
ui.real_app_constructed
experiment.active_edit_lock
experiment.in_place_edit_rejected
experiment.source_bundle_immutable
experiment.editable_copy_created
experiment.editable_copy_fresh_execution
experiment.editable_copy_editable
artifacts.required_present
```

Visible milestones/screenshots remain exactly:

```text
editor_opened
generated
initial_finalized
source_locked
locked_editor_opened
in_place_edit_rejected
editable_copy_created
copy_edited
copy_finalized
validated
```

The exact composed action contract will include the existing normal-UI editor
creation prefix and this ordered boundary window:

```text
editor.finish_via_ui                    ui
artifact.capture_milestone              harness  (initial_finalized)
experiment.activate_authoritative       model
execution.lock_for_printing             model
artifact.capture_milestone              harness  (source_locked)
editor.inspect_active_lock_via_ui       ui
artifact.capture_milestone              harness  (locked_editor_opened)
editor.reject_in_place_edit_via_ui      ui
artifact.capture_milestone              harness  (in_place_edit_rejected)
editor.create_editable_copy_via_ui      ui
artifact.capture_milestone              harness  (editable_copy_created)
editor.edit_copy_via_ui                 ui
artifact.capture_milestone              harness  (copy_edited)
editor.finalize_copy_via_ui             ui
artifact.capture_milestone              harness  (copy_finalized)
experiment.load_authoritative_via_ui    ui       (prepared inspection only)
artifact.capture_milestone              harness  (validated)
scenario.teardown                       harness
```

Contract tests will freeze the complete action order and multiplicity,
interaction surfaces, assertions, screenshots, report paths, and required
artifacts. Required artifacts change from the legacy-only list to the standard
composed set: report, summary, event trace, action/assertion ledgers, evidence
manifest, screenshots, and scenario root.

## Code-Shape And Reuse Gates

- the named post-start journey body is at most 110 physical lines;
- its payload builder is at most 70 physical lines;
- all scenario-specific constants, fixture adapter, body, payload, summary,
  and definition add at most 220 physical lines;
- the typed post-start spec/phase and assertion additions together add at
  most 300 physical lines before legacy delegation/removal;
- total touched runtime net growth is at most 450 physical lines;
- raw QTest for this boundary exists only in `ExperimentEditorDriver`, and
  moving it out of `actions.py` is net-negative across those two files;
- activation/lock/source/copy policy has one implementation used by composed
  assertions and the retained direct oracle's parity projection;
- `registry.run_registered_scenario()` gains no scenario-ID conditional;
- no harness, session-rotation, report-schema, fixture, or production-MVC
  change is introduced.

Line limits are review gates, not permission to compress or obscure behavior.
If they cannot be met cleanly, stop and amend this plan before adding a
parallel runner or helper family.

## Exact Files To Touch During Implementation

Required runtime files:

- `tools/virtual_workflows/actions.py`
- `tools/virtual_workflows/page_drivers.py`
- `tools/virtual_workflows/journey_phases.py`
- `tools/virtual_workflows/authoritative_evidence.py`
- `tools/virtual_workflows/assertions.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/editor_scenarios.py`
- `tools/virtual_workflows/registry.py`
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`

Required focused tests:

- `tests/test_virtual_workflow_actions.py`
- `tests/test_virtual_workflow_page_drivers.py`
- `tests/test_virtual_workflow_journey_phases.py`
- `tests/test_virtual_workflow_authoritative_evidence.py`
- `tests/test_virtual_workflow_assertions.py`
- `tests/test_virtual_workflow_composition.py`
- `tests/test_virtual_workflow_report.py`
- `tests/test_virtual_workflow_manifest.py`
- `tests/test_virtual_workflow_contract_freeze.py`
- existing
  `tests/system/test_virtual_workflow_editor_post_start_lifecycle.py`
- new
  `tests/system/test_virtual_workflow_editor_post_start_composed.py`

Required implementation documentation:

- `README.md`
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- this implementation plan, for status only
- new
  `docs/sil_interactive_simulation_milestone_7_slice_6_completion_record.md`

`tools/virtual_workflows/harness.py`, `tools/virtual_workflows/composition.py`,
`tools/virtual_workflows/editor_reporting.py`, `tools/virtual_workflows/report.py`,
the fixture, production MVC, simulator response models, Pi scripts, firmware,
protocol, and hardware files are validation inputs but are not expected to
change. If implementation proves one necessary, stop and amend this plan
before editing it.

## Implementation Steps

1. **Freeze the direct oracle.** Retain fixed-input legacy stable projections
   for fixture identity, action/assertion outcomes, all five post-start
   persistence sections, source/copy inventories, dialog/lock state, plan and
   resume facts, screenshots, failure classification, and cleanup. Record the
   fixture hash before edits.
2. **Consolidate the editor driver.** Move lock-control inspection and the
   bounded post-start QTest/modal state machine into `ExperimentEditorDriver`;
   retain exact modal titles, width minima, current-source selection,
   lifecycle banner/action labels, and fail-closed unexpected-dialog/deadline
   behavior; make the legacy action a thin delegate.
3. **Add typed setup and boundary phases.** Define a validated post-start spec
   for source/copy names and tolerance; execute activation and lock as explicit
   Model-surface semantic steps; invoke the shared driver; and reload the
   finalized copy through `ExperimentLoaderDriver.load_prepared_design()`.
4. **Consolidate read-only evidence and assertions.** Use one source-lock and
   copy-freshness projection to prove ACTIVE revision 2 with zero progress,
   complete UI lock/rejection, byte-identical source, fresh distinct PREPARED
   revision 1 copy, exact A1/A2 keys, no inherited execution artifacts, and
   inactive prepared reload. Adapt legacy parity data to those projections.
5. **Compose and register the journey.** Add a concise fixture adapter, body,
   payload, summary, artifact assertion, and `JourneyDefinition`; classify the
   two direct setup actions as `model`; switch only this registry entry to
   generic `composed_journey`; and update manifest actions/artifacts/node IDs
   without adding or broadening capability claims.
6. **Add focused success, parity, and controlled-failure tests.** Freeze the
   complete composed contract; compare stable direct/composed projections;
   inject a locked-control violation and an inherited-copy-runtime violation;
   require later assertions incomplete, retained failure evidence, best-effort
   teardown, and no source mutation.
7. **Run targeted unit, production-adjacent, lifecycle, visible, and replay
   gates.** Run only the selections below, then inspect the visible report,
   ledgers, evidence manifest, hashes, source/copy directories, ten images,
   failure artifacts, and exact replay projection.
8. **Document and close Slice 6.** Update README commands/troubleshooting,
   roadmap status, measured code shape, exact results, retained evidence,
   risks, and rollback. Stop before planning or implementing the 96-well
   regression.

## Focused Automated Gates

Use distinct temporary roots. If a Qt lifecycle node exceeds its internal
60-second scenario deadline or stops making progress materially beyond its
normal approximately 25-second baseline, inspect and terminate only that
confirmed process and rerun the exact node separately; do not wait for an
unrelated 15-minute outer timeout.

Reusable driver, phase, evidence, assertion, report, and contract tests:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  --basetemp "$env:TEMP\LabCraft\pytest-m7-slice6-unit" `
  tests\test_virtual_workflow_actions.py `
  tests\test_virtual_workflow_page_drivers.py `
  tests\test_virtual_workflow_journey_phases.py `
  tests\test_virtual_workflow_authoritative_evidence.py `
  tests\test_virtual_workflow_assertions.py `
  tests\test_virtual_workflow_composition.py `
  tests\test_virtual_workflow_report.py `
  tests\test_virtual_workflow_manifest.py `
  tests\test_virtual_workflow_contract_freeze.py
```

Production-adjacent lock/copy contracts, with no production edits expected:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  --basetemp "$env:TEMP\LabCraft\pytest-m7-slice6-adjacent" `
  tests\test_experiment_designer_interlock.py `
  tests\test_experiment_duplicate_design.py `
  tests\test_execution_plan_revision.py `
  tests\test_execution_lifecycle_hardening.py `
  tests\test_authoritative_execution_runtime_cache.py `
  tests\test_initial_execution_plan_integration.py
```

Composed success/parity/failure and focused editor regressions:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  --basetemp "$env:TEMP\LabCraft\pytest-m7-slice6-lifecycle" `
  tests\system\test_virtual_workflow_editor_post_start_composed.py `
  tests\system\test_virtual_workflow_editor_post_start_lifecycle.py `
  tests\system\test_virtual_workflow_editor_refinalize_composed.py `
  tests\system\test_virtual_workflow_editor_composed.py
```

Also run:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py --help
.\env\Scripts\python.exe -m py_compile `
  tools\virtual_workflows\actions.py `
  tools\virtual_workflows\page_drivers.py `
  tools\virtual_workflows\journey_phases.py `
  tools\virtual_workflows\authoritative_evidence.py `
  tools\virtual_workflows\assertions.py `
  tools\virtual_workflows\journeys.py `
  tools\virtual_workflows\editor_scenarios.py `
  tools\virtual_workflows\registry.py
git diff --check
git status --short
```

Do not run unscoped `pytest -q` in Slice 6. The complete Python suite remains
the final Milestone 7 validation gate.

## Success, Parity, And Controlled-Failure Gates

The composed success test must prove:

- hardware access is disabled and a real application/editor is constructed;
- source creation and finalization use the normal Qt editor controls;
- activation and the synthetic `printing_started` lock each appear once as
  `model`, produce ACTIVE revision 2 with clean zero-intent resume and zero
  progress, and are absent from UI coverage;
- the locked editor shows the exact source, visible copy guidance including
  `Calibration may still update`, `Execution Loaded`, every mutating control
  locked, and `Create Editable Copy...` enabled;
- an attempted in-place name/finalize action changes neither the dialog nor
  the source;
- the copy-name dialog is exactly `Duplicate Experiment Design`, identifies
  the automatically selected current source, has minimum dialog/field widths
  640/480 px, and uses no source-folder dialog;
- the copy is editable, accepts only the planned 1 nL tolerance change,
  optimizes, and finalizes through normal controls;
- source inventory and every source file remain byte-identical;
- the copy is a distinct valid revision-1 PREPARED plan, `ready_to_start`,
  with new plan identity, one history row, exact A1/A2 design/keys, zero
  progress, no resume, no calibration, and no inherited execution history;
- final prepared reload uses the Qt folder dialog, does not activate runtime,
  preserves plan identity, and creates no resume sidecar;
- all nine assertions, ten screenshots, standard composed artifacts, generic
  cleanup, and final no-lock checks pass.

Stable direct/composed parity compares fixture/workload identity, source lock,
control matrix and guidance, copy-dialog facts, source immutability, copy
semantics/tolerance/freshness, plan/resume/key relationships, assertion
decisions, milestone/screenshot keys, classification, and limitations. It
ignores only the reviewed action-plumbing and reload-activation difference,
plus generated identities, paths, timestamps, durations, and hashes bearing
those identities.

At minimum, inject (a) one supposedly locked mutating control enabled and
(b) one copy carrying a resume/history/progress artifact from the source.
Each must fail at its authoritative boundary, mark dependent later assertions
incomplete, retain screenshot/trace/ledgers/evidence manifest, finish
best-effort teardown, and leave the source unchanged. Unit tests must also
reject an unexpected modal or QFileDialog, wrong title/action label, missing
copy guidance, insufficient dialog width, wrong auto-selected source,
destination collision, expired deadline, and prepared reload activation.
These are harness-level controlled failures, not simulator or product fault
injection.

## Visible And Replay Gate

Run once through the normal Windows UI:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario experiment_editor_post_start_lock_v1 `
  --output-root verification_reports\milestone7-slice6-visible `
  --visible --seed 1 --speed-multiplier 2 --timeout-seconds 60
```

Inspect the report, action/assertion ledgers, evidence manifest, event trace,
state-recorder output, locked source and prepared copy directories, and all
ten screenshots. Verify visually that the source editor is locked, the copy
guidance and current source are clear, no source picker appears, the copy is
editable, and final prepared reload does not activate it. Confirm hardware
access remains disabled.

Then execute the exact `run.replay_command` emitted by that report into the
same output root. Require equal stable projection for fixture hash/seed,
action IDs/multiplicity/surfaces/statuses, dialog facts, assertion decisions,
milestone/screenshot keys, source/copy persistence relationships,
classification, and cleanup. Ignore only documented generated identities,
paths, timestamps, durations, and identity-bearing hashes.

## Risks And Mitigations

- **Synthetic setup is mistaken for UI coverage:** freeze both setup actions
  as `model`, exclude them from required UI actions, and state the limitation
  in the report and README.
- **Source is mutated while the dialog changes to the copy:** snapshot the
  entire source before opening the editor and compare inventory/hashes after
  copy finalization and reload; fail before success classification on any
  change.
- **Copy inherits physical history:** require new plan identity, revision 1,
  one history entry, zero progress, no resume/calibration, inactive runtime,
  and no copied audit/progress relationships.
- **UI driver accepts the wrong modal or source:** require exact types/titles,
  auto-selected source identity, width minima, destination, and action labels;
  reject unexpected file or message dialogs immediately.
- **Prepared reload silently activates:** assert runtime inactive and resume
  absent before and after Escape; use only `load_prepared_design()`.
- **Migration duplicates another runner:** enforce the body/helper/net-growth
  limits and single-driver/single-policy gates before parity approval.
- **Windows Qt batching stalls:** retain the 60-second scenario deadline,
  distinct temp roots, and isolate a stalled node promptly instead of waiting
  for a broad outer timeout.

## Rollback

Keep `run_editor_post_start_lock_scenario()` directly callable until all
focused parity and evidence gates pass. If migration fails, restore only the
`experiment_editor_post_start_lock_v1` registry and manifest entry to
`experiment_editor`; remove its composed definition, typed phase/assertions,
new composed test, and Slice 6 documentation; and restore the legacy action's
local driver only if delegation caused the regression.

Retain independently passing generic page-driver or evidence helpers only if
their focused tests pass and no active scenario selects incomplete behavior;
otherwise remove those additions too. Do not revert Slice 5, the fixture,
existing composed journeys, production data, or unrelated Milestone 7 work.
No production MVC, firmware/protocol, simulator-response, Pi, or hardware
rollback is required.

## Approval Gate

The user approved this plan and the bounded implementation is complete. Any
production MVC or fixture change, report-schema revision, second workflow
migration, active parameter matrix, seeded exploration, product/simulator
fault injection, performance work, Pi operation, firmware/protocol change,
or hardware work still requires an amended plan and separate approval.
