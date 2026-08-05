# Milestone 4C Manual-Refuel Dispatch-Handoff Correction

## Summary

The retained visible session
`20260805T122813738682Z-69447896d7bc` proved that a manual-refuel trial
launched through the post-calibration handoff could be accepted by the
simulator but remain blocked until its dialog closed. The Print Array launch
path executed the same trial immediately.

The corrected call path is:

```text
stream calibration Apply
  -> loading move completion handler
  -> schedule a zero-delay Qt callback
  -> simulator completion stack unwinds
  -> simulator clears its non-reentrant completion guard
  -> real ManualRefuelCheckDialog opens
  -> trial commands execute while the dialog remains open
```

This correction does not change the simulator command guard, Controller,
Model, calibration or refuel contracts, persistence, physical UI behavior, or
hardware interfaces.

## Implementation

1. Preserve the existing loading move, launch-pending state, dialog ownership,
   and duplicate-launch guards.
2. Schedule the post-loading dialog launch on the next Qt event-loop turn
   instead of entering its modal event loop from the move completion handler.
3. Revalidate ownership and pending state in the scheduled callback.
4. Add focused regression coverage for callback ordering, single launch, and
   command dispatch while the dialog remains open.

Files are limited to:

- `FreeRTOS-interface/View.py`
- `tests/test_pressure_plotbox_buttons.py`
- `tests/test_sil_normal_ui_convergence.py`
- this plan document

`tests/test_simulated_machine.py` may be extended only if the application-level
regression cannot exercise the real completion guard adequately.

## Validation

Run no full Python suite:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_pressure_plotbox_buttons.py `
  tests\test_sil_normal_ui_convergence.py `
  tests\test_manual_refuel_check_dialog.py `
  tests\test_simulated_machine.py

.\env\Scripts\python.exe -m py_compile `
  FreeRTOS-interface\View.py

git diff --check
git status --short
```

The visible regression must use a fresh retained root. After applying a stream
calibration and accepting the post-Apply refuel prompt, Run Trial must execute
and allow an outcome to be recorded while the refuel dialog remains open. The
dialog must still be launchable through Print Array, and close/disconnect must
remain clean. Reopen the new retained root only after that succeeds.

## Evidence, Risk, and Rollback

The original retained failure root remains read-only evidence and must not be
retried or modified. The main risk is weakening dialog ownership during the
asynchronous handoff; retaining the existing pending flag and revalidating it
before launch addresses that risk.

Rollback removes the zero-delay handoff and its focused regressions. No schema,
data, firmware, protocol, or retained-session migration is required.
