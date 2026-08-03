# SIL Interactive Simulation Milestone 4A Completion Record

## Completion Status

Status: `complete`

Milestone 4A was implemented and validated against baseline commit
`220df24bec011ee9a32f595bafe43a1389fd14c6`. The implementation remains an
intentional uncommitted worktree pending review; no commit was created by this
validation work.

The completed call path is:

```text
Simulator Control
  -> SimulationSession
  -> SyntheticCalibrationApplicationAdapter
  -> nominal_droplet provider request/result evidence
  -> CalibrationManager transient candidate
  -> simulation-only presentation DropletImagingDialog
  -> real preview and Apply handler
  -> ExperimentModel calibration revision
  -> execution_calibrations.json / execution_plan.json / progress.json
  -> retained-root reload through Experiment Editor
```

No firmware, protocol, production hardware factory, physical camera,
Controller, core Model, experiment schema, or launcher CLI contract changed.

## Implemented Files

Application and simulation integration:

- `FreeRTOS-interface/CalibrationClasses/Model.py`
- `FreeRTOS-interface/CalibrationClasses/View.py`
- `FreeRTOS-interface/CalibrationClasses/__init__.py`
- `FreeRTOS-interface/View.py`
- `tools/sil/calibration_application.py`
- `tools/sil/__init__.py`
- `tools/sil/control.py`
- `tools/sil/session.py`
- `tools/virtual_workflows/page_drivers.py`

Tests:

- `tests/test_sil_calibration_application.py`
- `tests/test_sil_calibration_ui.py`
- `tests/test_sil_calibration_dialog_driver.py`
- `tests/system/test_sil_synthetic_calibration_lifecycle.py`

Documentation:

- `docs/sil_interactive_simulation_milestone_4a_implementation_plan.md`
- `docs/sil_interactive_simulation_milestone_4a_completion_record.md`
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- `README.md`

## Automated Validation

Post-restart expanded focused gate:

```text
111 passed, 140 warnings in 126.81s
```

The focused gate covered the adapter, presentation UI, Qt page driver,
authoritative lifecycle/reload, physical-dialog regressions, Milestone 3
compatibility, Simulator Control, and SimulationSession.

Clean full Python gate with a 30-minute allowance:

```text
3738 passed, 38 skipped, 270 warnings in 939.81s
```

Additional gates passed:

- Python compilation for every modified/new Python module;
- plain `import tools.sil` without application path setup;
- simulator forbidden-hardware import isolation, including ten repeated
  subprocess probes while investigating one non-reproducible host event;
- `git diff --check`;
- standalone Git status/diff reads under the managed Windows sandbox.

No camera, balance, serial, GPIO, physical factory, firmware, or protocol path
was invoked by focused presentation tests. Default physical-dialog construction
and teardown regression coverage remained green.

## Visible Windows Evidence

Successful retained root:

```text
C:\Users\conar\AppData\Local\LabCraft\SIL\interactive-sessions\20260803T020621647655Z-b971afd21d79
```

Experiment: `Untitled-20260802_190623`

The operator confirmed the synthetic banner and information were visible. The
normal UI was used to connect to `SIMULATED`, enable/home, finalize and load the
droplet experiment, stage its virtual head, regulate pressure, generate the
synthetic result, inspect the amber Synthetic row and preview, Apply it, export
a snapshot, print the reagent pass, disconnect, and close.

Authoritative evidence after the first application session:

- exactly 24 wells, A1 through A24;
- two plan stock rows: one non-fill reagent plus Water fill;
- plan revision 3 and progress revision 3;
- one execution-calibration record;
- deterministic request/result artifacts present;
- `synthetic_calibration_generated` and `synthetic_calibration_applied` trace
  events present;
- queue drained, disconnect completed, recorder closed, and cleanup completed.

The same root was reopened with `--session-root`. The experiment was loaded
through Experiment Editor and the application connected/homed before closing.
Post-reload evidence remained identical for plan revision, stock/well counts,
progress revision, and execution-calibration record count. Both application
sessions report `completed`, both recorders report `closed`, and terminal
cleanup reports `complete`.

## Representative Canonical Artifacts

Artifact directory:

```text
artifacts/synthetic-calibration/a7ffa88551c8438dbb7ba089f9319bef/14ed51f08241bb5b2edd2df0a79d894e82a3d60deaeed0a1481aedccf61b85ba/
```

Identity and values:

- profile: `nominal_droplet`, profile version 1;
- provider: `milestone-3-v1`;
- seed: 1;
- stock: `reagent-1_27.78_mM`;
- nominal volume: 9.0 nL;
- measured/effective volume: 9.330827341 nL;
- pressure: 0.5997 psi;
- pulse width: 1300 us;
- request fingerprint:
  `c9681df22c2d8b90cc2b5d6f34d87957da2b9a58f5c2e7526aa603f345c72253`;
- result fingerprint:
  `14ed51f08241bb5b2edd2df0a79d894e82a3d60deaeed0a1481aedccf61b85ba`.

The physical `calibration.json` contains one empty run envelope created by the
existing experiment-load path before synthetic generation. Trace ordering
shows experiment-load events 19/22 before synthetic generation event 522. The
synthetic run ID is absent from physical history; the applied record is stored
only through the existing execution-calibration path.

## Inspected Failure and Recovery Evidence

All diagnostic roots were preserved:

- `20260801T163319963569Z-a069d64208c5` exposed that the initial adapter allowed
  a multi-stock experiment. The adapter now requires exactly one non-fill
  execution stock, permitting the normal Water fill row. A negative test proves
  rejection before evidence writes or candidate injection.
- `20260802T235412413270Z-beaa17b21bdf` proved visible generation/Apply but used
  only three wells, so it was retained as partial evidence and not counted as
  the 24-well gate.
- a `dxgmms2.sys` host restart interrupted one validation run. Post-restart ACL,
  create/update/delete, interpreter, compilation, pytest, and standalone Git
  probes passed before validation resumed.

Ambiguous evidence persistence was never retried. The adapter now latches any
ambiguous persistence failure and rejects all later generation attempts in that
application session.

## Limitations and Rollback

This evidence is synthetic and provides no proof of camera processing,
segmentation, physical ejection, volume accuracy, pressure response, refuel
behavior, collision safety, firmware, or protocol behavior. Stream calibration,
mode switching, and manual refuel remain Milestone 4B.

Rollback removes the additive adapter/control, transient candidate surface,
presentation-only UI/launcher, page driver, tests, and Milestone 4A
documentation. The Milestone 3 provider remains. No data migration, firmware
rollback, protocol rollback, or production experiment-data migration is
required.

