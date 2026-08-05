# Milestone 4C — Normal UI Path Convergence

## Baseline and objective

Baseline: clean worktree at `00e8473008390241b230d41844a4a489b536796e`.
Milestones 1–4B are complete.

Milestone 4C moves the simulator workflow behind the application's normal
Connect, Calibrate Printer Head, and Manual Refuel Check interfaces. Production
behavior remains the default. Simulation callbacks are installed only by
`SimulationSession` in the canonical hardware-isolated runtime.

```text
Normal Connect button
  -> SimulationSession callback
  -> Controller.connect_machine("SIMULATED")
  -> SimMachine

Normal Calibrate Printer Head button
  -> camera-free real DropletImagingDialog
  -> real Droplet/Stream Calibrate All control
  -> SyntheticCalibrationApplicationAdapter
  -> retained artifacts and transient synthetic row
  -> real preview, confirmation, and Apply paths
  -> ExperimentModel / Controller / authoritative writers

Normal Manual Refuel Check window
  -> existing command controls
  -> Controller -> SimMachine
  -> operator judgment
  -> SimulatedManualRefuelOutcomeAdapter
  -> existing Controller/Model persistence path
```

Firmware, protocol, serial communication, cameras, balances, physical
calibration behavior, workflow migration, failure injection, Pi operation,
printing, and performance remediation are excluded.

## Frozen behavior

- The normal connection surface shows one read-only `SIMULATED` target and
  delegates connect/disconnect to `SimulationSession`. The Controller's exact
  sentinel check remains authoritative.
- Simulator Control becomes diagnostics-only: identity, retained root, seed,
  timing, readiness/fingerprints, trace inspection, snapshot export, and status.
- The normal calibration button opens a canonical-simulation-only, full-layout,
  camera-free mode of the real dialog. Droplet and Stream tabs, summary rows,
  preview, confirmation, Apply, and close remain real. Physical acquisition,
  camera, movement, optics, debug, capture, and specialty controls are inert.
- The two Calibrate All buttons select profiles from current mode and tab:

| Current mode | Tab | Profile |
|---|---|---|
| Droplet | Droplet | `nominal_droplet` |
| Droplet | Stream | `droplet_to_stream` |
| Stream | Stream | `nominal_stream` |
| Stream | Droplet | `stream_to_droplet` |

- `stream_to_droplet` is an additive profile-v1 capability using the low bound
  of a symmetric request interval below 40 nL. Existing schema, profile, and
  provider versions remain unchanged so existing fingerprints remain stable.
- The real manual-refuel dialog keeps its command/trial rules. In simulation it
  receives an injected recorder accepting actual trial/droplet counts and
  `passed`, `failed`, `unclear`, or `deferred`. Stale fingerprints, ambiguous
  writes, and retries continue to fail closed. No bypass is exposed.
- Applied synthetic history is a read-only merge of fingerprint-validated
  retained artifacts and authoritative execution-calibration records. It does
  not populate or modify the physical `calibration.json` run history.
- Reloaded finalized experiments use a read-only projection of the
  authoritative execution plan for preview and pre-Apply checks; they never
  rerun optimization merely to reconstruct `plans_per_option`.
- Camera-free dialogs retain an explicit Qt owner while using asynchronous
  `open()`, and the known Calibrate All refresh restores their activation once.
- Refuel Only, Print Only, and relative refuel-pressure commands use the
  deterministic `SimulatedMachine` queue. State snapshots source calibration
  and refuel records from the authoritative runtime bundle when it is active.

## Implementation sequence

1. Record this frozen plan.
2. Bind normal connection controls after simulation construction.
3. Add the full-layout synthetic dialog mode and in-dialog generation.
4. Add the reverse profile and split generation from presentation.
5. Bind the real refuel dialog to simulated persistence.
6. Reduce the dock, update the QTest driver, and add focused tests.
7. Update developer documentation and mark implementation pending visible gates.
8. After all gates pass, record completion and mark Milestone 4C complete.

## Validation gates

Only changed-code and directly affected test modules will run; the full pytest
suite is intentionally excluded for this milestone at the user's request.

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_sil_normal_ui_convergence.py `
  tests\test_connection_widget_disconnect_state.py `
  tests\test_pressure_plotbox_buttons.py `
  tests\test_safe_application_construction.py `
  tests\test_simulation_session.py `
  tests\test_simulator_control.py `
  tests\test_sil_synthetic_calibration.py `
  tests\test_sil_calibration_application.py `
  tests\test_sil_calibration_ui.py `
  tests\test_droplet_imaging_summary_table.py `
  tests\test_manual_refuel_check_dialog.py `
  tests\test_sil_manual_refuel.py `
  tests\test_sil_calibration_dialog_driver.py `
  tests\test_simulated_machine.py `
  tests\test_sil_state_projection.py `
  tests\test_authoritative_execution_load.py `
  tests\system\test_sil_normal_ui_convergence_lifecycle.py
```

Compilation, `git diff --check`, and `git status --short` follow the focused
tests. The visible Windows gate uses only normal application controls, exports a
snapshot, closes cleanly, and then reopens the retained root through the normal
Experiment Editor. Failure roots are preserved and ambiguous writes are never
retried.

## Risks and rollback

The primary risks are accidentally invoking physical handlers, weakening the
exact simulator connection boundary, and changing production UI behavior.
Canonical-runtime callback binding, inert physical controls, the unchanged
Controller sentinel, production-path regression tests, and explicit synthetic
banners address them.

Rollback removes the 4C bindings, full-dialog mode, reverse profile, extended
outcome bridge, dock reduction, focused tests, and 4C documentation. Milestones
1–4B and retained experiment data require no migration or rollback.
