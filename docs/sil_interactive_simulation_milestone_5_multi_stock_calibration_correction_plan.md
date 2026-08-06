# Milestone 5 Multi-Stock Synthetic Calibration Correction

## Summary

Baseline: `130c47fb3e109b974cb4a687e2cc44c815c99196`, with the Milestone 5
qualification and zero-fill correction intentionally uncommitted.

Retained session
`20260806T183623168760Z-c2fcb49be09e` exposed an obsolete application-adapter
restriction. Its valid two-stock plan contains one dispense of each non-fill
stock in every well, but the simulation availability check rejects every plan
containing more than one non-fill execution stock before resolving the currently
loaded head.

```text
Normal Calibrate Printer Head button
  -> simulation calibration availability callback
  -> SyntheticCalibrationApplicationAdapter.availability()
  -> obsolete plan-wide one-non-fill-stock guard
  -> valid loaded stock rejected before the calibration dialog opens
```

The retained failure root contains the prepared plan, exported state evidence,
named screenshot, and SHA-256 inventory. It remains unchanged. The failed
availability check wrote no calibration artifact, calibration sidecar, plan
revision, or printing progress.

## Correction

1. Remove only the plan-wide non-fill stock count restriction.
2. Retain the existing requirement that the loaded printer head resolve to
   exactly one execution stock by stock ID.
3. Retain exact head, stock, factor, option/fill, requested mode, applied mode,
   settings, fingerprint, idle-array, empty-queue, and execution-lock checks.
4. Prove that a matching loaded stock in a multi-stock plan can generate and
   register its own deterministic candidate without selecting another stock.
5. Prove that duplicate or mismatched loaded-stock identity still fails before
   artifact persistence, candidate injection, or event recording.
6. Run focused adapter, normal-UI, and lifecycle tests, then restart the
   two-stock manual journey in a fresh retained root.

Files to touch:

- `tools/sil/calibration_application.py`
- `tests/test_sil_calibration_application.py`
- this correction plan

Add a system lifecycle test only if the focused adapter regression identifies a
second affected call path. No Controller, ExperimentModel, calibration manager,
UI, provider schema, firmware, protocol, or hardware behavior will change.

## Validation

Run no full suite:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_sil_calibration_application.py `
  tests\test_sil_normal_ui_convergence.py `
  tests\system\test_sil_normal_ui_convergence_lifecycle.py `
  tests\test_initial_execution_plan_integration.py

.\env\Scripts\python.exe -m py_compile tools\sil\calibration_application.py
git diff --check
git status --short
```

The visible gate uses a new two-stock root. It must calibrate and print the 9 nL
stock, exchange heads through the rack, calibrate and print the 18 nL stock, and
finish with exactly 48 completions, two applied calibration records, an empty
queue, successful reconciliation, and a completed read-only reload.

## Rollback

Rollback restores the plan-wide guard and its former rejection test, and removes
this document. The retained failure root requires no repair or migration.
