# Milestone 7 Slice 1 — Composed Editor Create/Finalize/Reload

Status: `complete — implemented and validated 2026-08-06`

Planning baseline: `f9d13b78002ea8aa3400953ab0f4b0ee8c1fb21f`.

## Scope

Migrate only `experiment_editor_create_finalize_v1` from the legacy
`editor_scenarios.py` runner to the Milestone 6 shared harness. The journey
will create and finalize the tracked two-well design, validate its prepared
authoritative bundle, reopen it through the normal Experiment Editor **Load
Design…** control, and validate the reloaded prepared state.

This slice does not migrate prepared rename/refinalize, post-start lock/copy,
multi-stock, soft-stop, authoritative reload/resume, 96-well, stress, Pi, or
comparison workflows. It adds no production fault injection, performance
work, firmware/protocol work, physical behavior, or hardware operations.

No fixture or production MVC behavior should change. The tracked
`experiment_editor_create_finalize_v1.json` recipe remains two wells, one
droplet stock, 10 nL, and one finalization.

## Audited Call Paths

### Current registry and legacy runner

```text
tools/run_virtual_workflow.py
  -> registry.run_registered_scenario()
  -> runner_family == "experiment_editor"
  -> editor_scenarios.run_editor_create_finalize_scenario()
  -> editor_scenarios._run_editor_lifecycle_scenario()
```

The legacy runner independently owns QApplication/application construction,
temporary roots, stdout capture, event logs, dialog handling, screenshots,
failure capture, cleanup, assertion classification, and report-v1 assembly.

### Current create/finalize UI path

```text
Experiment Editor button (QTest click)
  -> ExperimentDesignDialog
  -> New experiment / editor controls / Printable Wells dialog (QTest)
  -> Optimize & Generate (QTest)
  -> Finalize Design (QTest)
  -> MainWindow completion handler
  -> Model.load_experiment_from_model()
  -> authoritative design/plan/progress/key writers
```

`drive_editor_create_finalize()` already performs bounded QTest interactions,
but it directly calls `execute_action()` internally. Consequently the shared
harness cannot currently enforce recorder-health, dialog, and snapshot gates
at every editor sub-action.

### Current reload path and bypass

After finalization the legacy runner calls, directly:

```text
ExperimentModel.load_experiment(design_path, experiment_dir)
  -> Model.load_authoritative_execution_runtime()
  -> read authoritative plan/progress/resume state
```

That bypasses the normal **Experiment Editor → Load Design…** UI and the
action ledger labels it only as `experiment.reload_authoritative`. It also
activates a runtime solely for verification, although the user-facing prepared
reload contract is `ready_to_start` and does not require runtime activation.

### Target composed path

```text
CLI / registry
  -> typed composed journey
  -> AutomationHarness / SimulationSession
  -> ExperimentEditorDriver with harness-owned semantic action boundaries
  -> normal Finalize Design path
  -> read-only prepared-bundle assertions
  -> ExperimentLoaderDriver
       -> Experiment Editor button
       -> Load Design…
       -> Qt folder dialog
       -> normal Model.load_experiment() UI handler
  -> read-only prepared-reload assertions
  -> report-v1 adapter / evidence manifest / teardown
```

No connection, homing, pressure, calibration, rack, print command, firmware
handler, or device-protocol path is involved.

## Frozen Design Decisions

1. **One scenario only.** Registry cutover applies only to
   `experiment_editor_create_finalize_v1`. The rename/refinalize and
   post-start-lock IDs remain on `editor_scenarios.py`.
2. **Legacy oracle retained.** `run_editor_create_finalize_scenario()` remains
   directly callable during Milestone 7 so targeted parity tests can compare
   old and new results. Shared legacy editor code is not deleted until all
   dependent editor scenarios migrate.
3. **Normal prepared reload.** Reload uses the visible Experiment Editor and
   **Load Design…** controls. It does not call `load_experiment()` or
   `load_authoritative_execution_runtime()` from the journey, action, or test.
   The reloaded plan stays `PREPARED`, eligibility stays `ready_to_start`, the
   runtime stays inactive, and the resume file stays absent. This intentionally
   replaces the legacy runner's verification-only runtime activation; the
   assertion remains equivalent at the user-visible prepared-reopen boundary.
4. **Truthful file-selection mechanics.** The page driver may set the tracked,
   harness-contained directory on the Qt `QFileDialog`, because that is fixture
   selection rather than application-state mutation. Opening Experiment Editor,
   clicking **Load Design…**, accepting the folder, and closing the inspection
   dialog must use bounded QTest input. Evidence records this mechanic. Native
   OS automation, a patched dialog return value, and direct Model loading are
   not allowed. The owned visible automation session sets Qt's
   `AA_DontUseNativeDialogs` application attribute before creating its
   `QApplication`; borrowed offscreen test applications must expose the same Qt
   dialog or fail before the action starts.
5. **Harness owns action boundaries.** Every editor sub-action must pass through
   `AutomationHarness.run_action()` so unexpected dialogs, deadline exhaustion,
   recorder health, snapshot correlation, failure stage, and interaction
   surface are checked before an action can pass.
6. **Report-v1 compatibility.** Preserve scenario/workload/version identities,
   the five existing screenshots, existing assertion IDs, and the legacy
   `metrics.persistence.values.prepared_bundle` and `reload_activation` paths.
   Add seed/replay/session/evidence-manifest fields and action surfaces in the
   same form as the Milestone 6 smoke. `reload_activation` will explicitly
   record `activation_performed: false` and `runtime_active: false`.
7. **No false UI claim.** Editor creation/finalization and prepared loading may
   claim `ui`; assertions, waits, snapshots, report work, and teardown remain
   `harness`. A successful report fails validation if a required UI action is
   missing or has a non-UI surface.
8. **Targeted validation policy.** This slice runs all directly affected and
   adjacent editor/harness tests, plus the Milestone 6 smoke regression. It
   does not run the full Python suite. The complete suite is deferred to the
   final Milestone 7 validation after all approved slices are integrated.

## Required Parity Contract

The legacy and composed runs must agree on stable behavior, not generated
identity fields:

- scenario, version, workload, fixture SHA-256, and A1/A2 order;
- all eight required assertion IDs and `pass` decisions;
- revision-1 `PREPARED` plan, valid design hash, exact plan wells, one history
  revision, zero progress, and absent calibration/printing history;
- exact key and concentration-key wells/targets;
- unchanged runtime reaction assignments after UI reload;
- `ready_to_start` prepared eligibility and inactive runtime;
- no unexpected dialogs, errors, print commands, or physical interfaces;
- required screenshots, ledgers, hashes, terminal snapshot, and clean teardown.

UUIDs, plan IDs, timestamps, durations, report/session paths, and hashes that
contain those identities are excluded from parity. The resume difference is
reviewed explicitly: the composed UI reload requires no resume file because it
does not perform the legacy runner's direct runtime activation.

## Implementation Steps

1. Freeze the fixture, registry, report-v1, assertion, action-order, and legacy
   direct-runner contracts in targeted tests. Add a stable parity normalizer
   that compares the legacy runner with the composed journey while excluding
   documented identity-bearing fields.
2. Generalize the Milestone 6 composed-journey configuration and common report
   finalization so the smoke and editor share session identity, seed/replay,
   action/assertion ledgers, evidence manifest, classification, and teardown
   logic. Preserve the existing smoke report through its focused tests.
3. Make `ExperimentEditorDriver` execute its existing modal QTest stages through
   a harness-supplied semantic action runner. Keep the legacy
   `drive_editor_create_finalize()` wrapper as a compatibility adapter with no
   behavior change for the two unmigrated editor scenarios.
4. Add `ExperimentLoaderDriver.load_prepared_design()` for the bounded normal
   Editor → Load Design… → Qt folder-dialog path. It must verify the loaded
   name, plan identity, prepared guidance, inactive runtime, and contained
   source path before closing the dialog through QTest.
5. Add reusable read-only editor assertions for real application construction,
   create/finalize action completion, the full prepared bundle, key-file
   consistency, prepared UI reload, unchanged runtime assignments, required
   artifacts, and cleanup. Missing evidence is `incomplete`; assertions never
   repair, activate, or write state.
6. Add the short typed editor composition and dispatch only
   `experiment_editor_create_finalize_v1` to it. Switch its manifest actions to
   truthful surfaces and preserve its five capability claims only when the new
   passing assertions back them. Leave both other editor IDs on the legacy
   runner.
7. Add success, parity, and controlled unexpected-dialog/failure-evidence tests.
   Prove exact UI surfaces, incomplete downstream assertions, retained failure
   artifacts, recorder closure, and lock-free teardown without adding a
   production fault-injection option.
8. Run the targeted gates below, one visible Windows run, and the exact emitted
   replay command. Inspect both reports/session roots, update README/roadmap,
   and write the slice completion record. Do not run the full suite in this
   slice.

## Exact Implementation File Set

New files:

- `tests/system/test_virtual_workflow_editor_composed.py`
- `docs/sil_interactive_simulation_milestone_7_slice_1_completion_record.md`

Modified files:

- `tools/virtual_workflows/harness.py`
- `tools/virtual_workflows/page_drivers.py`
- `tools/virtual_workflows/actions.py`
- `tools/virtual_workflows/assertions.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/registry.py`
- `tools/virtual_workflows/report.py`
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`
- `tests/test_virtual_workflow_harness.py`
- `tests/test_virtual_workflow_page_drivers.py`
- `tests/test_virtual_workflow_actions.py`
- `tests/test_virtual_workflow_assertions.py`
- `tests/test_virtual_workflow_manifest.py`
- `tests/test_virtual_workflow_contract_freeze.py`
- `tests/system/test_virtual_workflow_editor_lifecycle.py`
- `tests/system/test_virtual_workflow_smoke.py`
- `README.md`
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- this plan

The tracked editor fixture and `editor_scenarios.py` should remain unchanged.
No file under `FreeRTOS-interface/`, `firmware/`, Pi tooling, performance tests,
comparison/baseline tooling, or another workflow implementation is approved.
If the normal prepared-load UI cannot preserve the authoritative prepared plan,
stop with evidence and write a separate scoped seam plan rather than adding a
direct Model workaround or expanding this file set.

## Targeted Automated Gates

Run the shared contract/unit gate:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_simulation_session.py `
  tests\test_virtual_workflow_harness.py `
  tests\test_virtual_workflow_page_drivers.py `
  tests\test_virtual_workflow_actions.py `
  tests\test_virtual_workflow_assertions.py `
  tests\test_virtual_workflow_manifest.py `
  tests\test_virtual_workflow_contract_freeze.py
```

Run the migrated scenario, its legacy parity oracle, and adjacent editor
compatibility tests:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_editor_composed.py `
  tests\system\test_virtual_workflow_editor_lifecycle.py `
  tests\system\test_virtual_workflow_editor_post_start_lifecycle.py
```

Run the existing composed-smoke regression:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\system\test_virtual_workflow_smoke.py
```

Also run:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py --help
.\env\Scripts\python.exe -m py_compile `
  tools\virtual_workflows\harness.py `
  tools\virtual_workflows\page_drivers.py `
  tools\virtual_workflows\actions.py `
  tools\virtual_workflows\assertions.py `
  tools\virtual_workflows\journeys.py `
  tools\virtual_workflows\registry.py `
  tools\virtual_workflows\report.py
git diff --check
git status --short
```

Do **not** run `.\env\Scripts\python.exe -m pytest -q` without a targeted test
path in this slice. Record the cumulative full-suite gate as deferred to the
end of Milestone 7.

## Visible And Replay Gates

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario experiment_editor_create_finalize_v1 `
  --output-root verification_reports\milestone7-slice1-visible `
  --visible --seed 1 --speed-multiplier 2 --timeout-seconds 120
```

The visible run passes only when the normal Experiment Editor creates and
finalizes the two-well design, the normal Load Design path reopens the retained
prepared experiment without finalizing again, all required assertions pass,
and close leaves a healthy recorder with no session lock. Run the exact replay
command from its report and compare the stable parity fields listed above.

## Risks And Mitigations

- **Prepared reload changes plan identity:** fail before classification if UI
  loading rewrites/finalizes the design; retain both identities and stop rather
  than accepting a direct Model workaround.
- **File-dialog race or native dialog escape:** accept only the expected Qt
  `QFileDialog` title and contained fixture path under one deadline; reject any
  other modal. Do not automate a native OS dialog.
- **False per-action evidence:** route every modal editor stage through the
  harness runner and test that an unexpected dialog marks that exact UI action
  failed rather than passing before the boundary check.
- **Report drift breaks the smoke:** refactor common report code additively and
  retain the Milestone 6 smoke as a mandatory targeted regression.
- **Legacy parity hides semantic change:** explicitly record the removal of
  verification-only runtime activation and prove the user-visible prepared
  reload contract instead of comparing resume-file presence blindly.
- **Temporary duplication:** keep the legacy create/finalize runner only as a
  Milestone 7 parity oracle because its implementation is shared with two
  unmigrated scenarios; remove it only after those scenarios migrate.
- **No per-slice full suite:** run all affected and adjacent editor/harness tests
  in every slice, preserve small reversible commits, and require one complete
  Python suite before Milestone 7 is declared complete.

## Rollback

Restore `experiment_editor_create_finalize_v1` to `runner_family =
"experiment_editor"` and its legacy dispatch. Revert only its manifest action/
assertion mapping and remove the composed editor journey/driver/assertions that
have no other consumer. Keep the Milestone 6 smoke harness and all unmigrated
legacy editor scenarios intact.

No fixture, authoritative-schema, production MVC, firmware/protocol, Pi,
hardware, or retained-evidence deletion is required. Retained success/failure
roots may remain for inspection.

## Approval Gate

This plan was approved and implemented for this one scenario. The targeted,
visible, and exact-replay results are recorded in
`docs/sil_interactive_simulation_milestone_7_slice_1_completion_record.md`.
Any additional workflow migration, production seam, fault-injection feature,
performance work, Pi operation, firmware/protocol change, or hardware work
requires a separate decision.
