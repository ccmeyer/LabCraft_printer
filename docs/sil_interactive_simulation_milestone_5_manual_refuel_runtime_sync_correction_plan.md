# Milestone 5 Manual-Refuel Runtime Synchronization Correction

## Summary

Baseline: `130c47fb3e109b974cb4a687e2cc44c815c99196`, with the current
Milestone 5 qualification and focused corrections intentionally uncommitted.

Retained failure evidence:

```text
C:\Users\conar\AppData\Local\LabCraft\SIL\interactive-sessions\
  20260806T191023960919Z-7ae703378c6f
```

The mixed-mode journey applied a valid 60 nL stream calibration and persisted a
Passed manual-refuel record. The following print preflight rejected the
application's own `execution_calibrations.json` write as an external change.
The exported snapshot reconciled with zero mismatches, the queue was empty, and
no stream target had printed.

```text
ManualRefuelCheckDialog
  -> Controller.record_manual_refuel_check_outcome()
  -> ExperimentModel.record_manual_refuel_check_outcome()
  -> execution_calibrations.json durable write
  -> active authoritative runtime identity/cache remains stale
  -> print guard reports an external file change
```

This is a focused production-seam bookkeeping correction. It does not change
the manual-refuel contract, calibration contract, UI, Controller, simulator,
hardware communication, experiment schema, or printing behavior.

## Implementation

1. Preserve the closed retained failure root and write a SHA-256 inventory that
   excludes the inventory file itself.
2. Add a regression that activates an authoritative execution, applies a
   stream calibration, records a manual-refuel outcome, and immediately uses
   the authoritative runtime guard/print-intent path.
3. Before a sidecar-backed manual-refuel write, guard the active authoritative
   runtime against prior out-of-band changes.
4. Persist once through the existing strict execution-calibration writer.
5. Only after the write succeeds, accept the new
   `execution_calibrations.json` identity and replace the active/cached bundle's
   calibration document with the validated document that was written.
6. Preserve fail-closed behavior for an external sidecar mutation, a write
   failure, or ambiguity while accepting no failed write.
7. Run focused tests, compilation, diff, and worktree checks.
8. Repeat the mixed-mode journey in a fresh retained root and complete its
   retained-root reload before resuming Milestone 5 qualification.

Files to touch:

- `FreeRTOS-interface/Model.py`
- `tests/test_initial_execution_plan_integration.py`
- `tests/test_authoritative_execution_runtime_cache.py`
- this correction-plan document

## Focused Validation

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_initial_execution_plan_integration.py `
  tests\test_authoritative_execution_runtime_cache.py `
  tests\test_experiment_model_runtime_refresh.py `
  tests\test_controller_print_guards.py

.\env\Scripts\python.exe -m py_compile FreeRTOS-interface\Model.py
git diff --check
git status --short
```

The tests must prove that the accepted refuel write remains visible in the
active bundle, the next authoritative guard succeeds, and an unrelated external
sidecar mutation still invalidates the runtime without being overwritten.

No full Python suite is required for this focused correction.

## Visible Regression and Rollback

Use a fresh retained root. Recreate the 24-well mixed droplet/stream journey,
complete the droplet pass, apply the 60 nL/2500 us stream calibration, complete
one real simulated manual-refuel trial with Passed judgment, and start the
stream pass without reloading or explicitly reactivating. Complete all 48
targets, export reconciled evidence, close, reopen the retained root, and verify
the terminal state through Experiment Editor.

Rollback reverts the runtime synchronization change and its tests. No retained
experiment, schema, firmware, protocol, or hardware rollback is required. The
preserved failure root must not be retried or modified.
