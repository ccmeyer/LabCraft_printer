# SIL Interactive Simulation Milestone 4B Completion Record

Date: 2026-08-03 (America/Los_Angeles)

Parent plan: `docs/sil_interactive_simulation_and_composable_workflows_plan.md`

Implementation plan:
`docs/sil_interactive_simulation_milestone_4b_implementation_plan.md`

Baseline: `53aa2295c6914922394c40a2e2b2493210322d7b`

Status: `complete`

## Outcome

Milestone 4B extends the simulation-only, camera-free calibration presentation
to deterministic `droplet_to_stream` and `nominal_stream` results. Both results
apply through the existing calibration and execution-plan revision paths. The
Simulator Control dock also records explicitly simulated `failed`, `deferred`,
and `passed` manual-refuel outcomes through the existing Controller/Model API.
No bypass path is exposed.

The production camera/calibration path and operator manual-refuel dialog remain
unchanged. No hardware factory, serial port, camera, balance, firmware, protocol,
or physical calibration path is used by this milestone.

## Implementation Scope

The uncommitted milestone diff from the baseline is limited to:

- `FreeRTOS-interface/CalibrationClasses/Model.py`
- `FreeRTOS-interface/CalibrationClasses/View.py`
- `FreeRTOS-interface/ExecutionPlanRevision.py`
- `FreeRTOS-interface/View.py`
- `tools/sil/__init__.py`
- `tools/sil/calibration_application.py`
- `tools/sil/manual_refuel.py`
- `tools/sil/control.py`
- `tools/sil/session.py`
- `tools/virtual_workflows/page_drivers.py`
- `tests/test_execution_plan_revision.py`
- `tests/test_sil_calibration_application.py`
- `tests/test_sil_manual_refuel.py`
- `tests/test_sil_calibration_ui.py`
- `tests/test_sil_calibration_dialog_driver.py`
- `tests/test_simulator_control.py`
- `tests/system/test_sil_stream_calibration_lifecycle.py`
- `README.md`
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- `docs/sil_interactive_simulation_milestone_4b_implementation_plan.md`
- this completion record

`ExecutionPlanRevision.py` received one narrow defect correction discovered by
the second nominal-stream lifecycle: an unchanged target-count calibration
revision is classified by its changed calibration-record key instead of being
misclassified as a printer-head binding revision. Its immutable revision-history
coverage is recorded in `tests/test_execution_plan_revision.py`.

Core `Controller.py`, core `Model.py`, `ExecutionCalibrationStore.py`, the pure
Milestone 3 provider, experiment schemas, launcher CLI, firmware, and protocol
files did not change.

## Representative Deterministic Evidence

Successful retained root:

```text
C:\Users\conar\AppData\Local\LabCraft\SIL\interactive-sessions\20260804T020108467266Z-bce7eeccd868
```

Session ID: `52fe17f2c09a42dd8b8aada4e6bf0a34`

Fresh application session: `9f3212d01470422d8b841ded1c4da482`

Reload application session: `18306fadd640484f80b4d6428b192008`

Droplet-to-stream artifact:

- request fingerprint:
  `c1c00486964cf9bb78c419bbfda82e4aad1484eaedbd6ac087e81a44f0d6978c`
- result fingerprint:
  `3dcba2a5f1e49a3fc1b601560b41df4a6f1642b2a2b5c58a1d4bc8bc2fb82bf7`
- nominal/effective volume: `25.0 nL` / `40.0 nL`
- original/applied mode: `droplet` / `stream`
- pressure/pulse width: `0.5997 psi` / `1300 us`

Nominal-stream artifact:

- request fingerprint:
  `07706f446eff19a16e219962b7fc93c8eb3a7c03c03cc62ae4b04fb68e4cd05d`
- result fingerprint:
  `28a541f04667ee0baffe06098119f10b8d57135f0e6dd9b30d5e35fc46333963`
- nominal/effective volume: `40.0 nL` / `40.0 nL`
- original/applied mode: `stream` / `stream`
- pressure/pulse width: `0.5997 psi` / `1300 us`

Both canonical request/result pairs remain beneath
`artifacts/synthetic-calibration/9f3212d01470422d8b841ded1c4da482/`.
They retain provider version `milestone-3-v1`, profile version 1, seed 1, the
six-field source-row fingerprint, and all fixed synthetic-evidence limitations.

## Fresh Visible Windows Gate

The successful fresh session exercised the normal visible UI with:

```powershell
.\env\Scripts\python.exe tools\run_simulated_app.py `
  --keep-session `
  --seed 1 `
  --speed-multiplier 2
```

The operator connected only to `SIMULATED`, enabled/homed, regulated print and
refuel pressure, finalized A1-A24 with a 25 nL non-fill droplet stock, staged its
virtual head, and used the camera-free synthetic presentation. The retained
trace proves this ordered sequence:

1. `droplet_to_stream` generated and applied;
2. deferred preflight changed to `failed_refuel_check` after an explicit Failed;
3. Failed changed to `passed_refuel_check` after an explicit Passed;
4. `nominal_stream` generated and applied with a different calibration
   fingerprint;
5. the earlier pass was invalidated/deferred for the new calibration;
6. a new matching Passed restored `passed_refuel_check`;
7. a snapshot was exported, the simulator disconnected, and cleanup completed.

The terminal recorder counts include two synthetic generations, two synthetic
applications, three simulated manual-refuel outcomes, and no recorder failure.
The authoritative plan reached revision 4 with intended volume 25 nL, effective
volume 40 nL, stream mode, and the nominal-stream calibration record key. The
manual-refuel store contains source `sil_simulated_manual_refuel_check`, one
five-droplet trial, simulated operator judgment, canonical provider/seed notes,
the machine settings snapshot, and a current Passed tied to the nominal-stream
fingerprint. Progress remained at the clean start boundary; no print ran in the
successful root.

Two earlier roots were preserved rather than hidden or overwritten:

- `20260803T042546320622Z-06941f8011c3` was closed prematurely;
- `20260804T015127648440Z-4291741b1958` generated but did not apply the second
  nominal-stream result, then progressed the stock by printing.

Neither incomplete root was reused as successful evidence, and no ambiguous
write was retried.

## Retained-Root Reload Gate

The successful root was reopened with:

```powershell
.\env\Scripts\python.exe tools\run_simulated_app.py `
  --session-root "C:\Users\conar\AppData\Local\LabCraft\SIL\interactive-sessions\20260804T020108467266Z-bce7eeccd868"
```

`Untitled-20260803_190154` loaded through the existing Experiment Editor. The
reload recorder closed cleanly with no calibration or print events. Its terminal
projection and authoritative files reconciled revision 4, active/ready-to-start
state, the same stream head and nominal-stream calibration key, two calibration
records, current Passed manual-refuel evidence, and zero print progress.

## Automated Validation

Focused Milestone 4B and affected regression gate:

```text
230 passed, 140 warnings in 185.33s
```

Compilation of the implementation and affected application modules passed.

The root suite collected exactly 3,789 tests. Because the monolithic Windows
tool wrapper exceeded 30 minutes without exposing incremental output, the same
289 `test_*.py` files were run once in four stable alphabetical partitions:

```text
1,085 passed, 14 skipped
879 passed
727 passed, 23 skipped
1,060 passed, 1 skipped
```

Aggregate: `3,751 passed, 38 skipped`. No partition failed. `git diff --check`
passed; line-ending conversion notices were informational.

## Limitations And Exclusions

The evidence is explicitly synthetic. It does not validate physical ejection,
volume accuracy, pressure response, refuel behavior, camera segmentation,
motion/collision safety, firmware, protocol, or hardware communication. Print
execution, workflow migration, failure injection, Pi operation, and performance
remediation remain outside Milestone 4B.

## Rollback

Rollback removes the stream presentation support, simulated manual-refuel
adapter and dock controls, driver/tests, execution-plan classification fix, and
Milestone 4B documentation. Milestones 1 through 4A and the pure Milestone 3
provider remain intact. No firmware, protocol, schema, or retained-data migration
is required.

## Next Step

Create and review the concrete Milestone 5 implementation plan for manual
full-lifecycle characterization before beginning that work.
