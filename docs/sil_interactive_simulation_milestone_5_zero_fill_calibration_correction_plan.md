# Milestone 5 Zero-Fill Execution-Calibration Correction

## Summary

Baseline: `130c47fb3e109b974cb4a687e2cc44c815c99196`, with the Milestone 5
qualification documentation intentionally uncommitted.

Retained session
`20260806T165651925531Z-edbea4a66eed` exposed an execution-calibration
defect in the prepared one-stock journey. The finalized 9 nL design correctly
omitted its zero-target Water stock, but calibration target requantization
unconditionally required one identifiable fill stock.

```text
Normal calibration Apply
  -> ExperimentModel.apply_droplet_volume_for_option()
  -> ExperimentModel.apply_execution_calibration()
  -> ExperimentModel._calibrated_target_counts()
  -> zero-target fill stock absent from the frozen execution plan
  -> incorrect unconditional fill-stock rejection
```

The failure root, canonical synthetic evidence, exported state snapshot, named
screenshot, and SHA-256 inventory are retained unchanged. No calibration record
or printing progress was written by the failed Apply.

## Correction

1. Preserve the existing behavior when exactly one identified fill stock is in
   the execution plan.
2. Continue to reject ambiguous or malformed fill-stock identity.
3. When the plan contains no fill stock, recompute the calibrated non-fill
   targets and use the finalized design's fill-droplet volume to determine
   whether the residual would round to zero fill dispenses under the same rule
   used at experiment generation.
4. Permit the revision only when every well continues to require zero fill
   dispenses. Never add a stock identity during calibration.
5. Fail before authoritative calibration persistence when any well would require
   a missing fill stock.
6. Add focused execution-plan and normal SIL lifecycle regressions, then repeat
   the one-stock manual journey in a fresh retained root.

Files to touch:

- `FreeRTOS-interface/Model.py`
- `tests/test_initial_execution_plan_integration.py`
- `tests/system/test_sil_normal_ui_convergence_lifecycle.py` only if the focused
  model regression does not cover the normal application call path
- this correction plan

No Controller, UI, synthetic provider, calibration schema, experiment schema,
firmware, protocol, or retained-root file will change.

## Validation

Run only directly affected tests:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_initial_execution_plan_integration.py `
  tests\test_sil_calibration_application.py `
  tests\system\test_sil_normal_ui_convergence_lifecycle.py

.\env\Scripts\python.exe -m py_compile FreeRTOS-interface\Model.py
git diff --check
git status --short
```

The regressions must prove that an exact 9 nL calibration of a one-stock,
zero-fill plan succeeds and reconciles, while a calibration that would require
an absent fill stock fails without creating a calibrated revision, calibration
record, or progress mutation. The normal initial calibration lock may already
exist at that boundary. Existing plans containing one valid fill stock must
remain unchanged in behavior.

## Manual Gate and Rollback

Use a new retained root and repeat the one-stock prepared reload, calibration,
stop-after-well, process reload, resume, completion, and terminal reload gates.
The retained failure root is evidence and must not be reused or repaired.

Rollback reverts the guarded zero-fill branch, its regressions, and this plan.
No stored data, schema, firmware, protocol, or hardware rollback is required.
