# Calibration Memory UI Phase 5

## Scope

Phase 5 adds a compact, opt-in calibration-memory recommendation panel to the modern `DropletImagingDialog`. The dialog now shows the best available prior for the current reagent / printer-head / pulse-width context, makes the provenance and confidence visible, and lets the user explicitly preload the recommended seed into the existing startup controls.

This phase does not change the calibration algorithm. The live calibration process still validates real droplet behavior and remains authoritative.

## Files Changed

- `FreeRTOS-interface/CalibrationClasses/View.py`
- `FreeRTOS-interface/CalibrationClasses/Model.py`
- `FreeRTOS-interface/CalibrationMemoryStore.py`
- `tests/test_calibration_memory_ui_recommendation.py`
- `tests/test_calibration_memory_integration.py`

## Where The Recommendation Is Shown

The recommendation is shown in a new `Calibration Memory Recommendation` group inside `DropletImagingDialog`, next to the existing calibration controls.

Displayed fields:

- source / aggregation level
- confidence
- pulse-width match quality
- recommended pulse width
- recommended start pressure
- expected pressure band
- expected emergence time
- expected droplet volume
- expected CV
- contributing run count / source count
- current runtime mode (`off`, `advisory`, `seed_start`)

## User-Confirmed Apply Behavior

The new buttons are:

- `Refresh Recommendation`
- `Use Recommended Seed`
- `Keep Manual Start`

`Use Recommended Seed` is conservative:

- it does not start calibration
- it does not bypass verification logic
- it only preloads the existing UI startup controls
- it updates `start_pressure_spin`
- it updates `print_pulse_width_spinbox` only after explicit user action

If the prior is reference-only or fails conservative qualification, the recommendation is still shown, but `Use Recommended Seed` stays disabled.

## Runtime Mode Interaction

The panel does not replace the Phase 4 runtime mode architecture.

- `off`: no internal automatic prior steering; the panel remains manual-only
- `advisory`: recommendation is shown, but nothing changes unless the user clicks apply
- `seed_start`: runtime may also seed startup internally; the panel makes that visible and still only preloads controls when the user clicks apply

## Logging And Sidecar Integration

New UI interaction events are tracked through `CalibrationManager` and flushed into the sidecar run once a run starts:

- `ui_recommendation_shown`
- `ui_recommendation_applied`
- `ui_recommendation_ignored`

Run summaries now include a nested `ui_recommendation` block containing:

- whether the recommendation was shown
- whether it was applied
- whether it was ignored
- aggregation level
- confidence
- qualification result
- seed values
- target pulse width / target volume context

Raw runs remain the source of truth. The UI telemetry is additive.

## Hooks Added

View hooks:

- recommendation panel widgets in `DropletImagingDialog`
- `refresh_calibration_memory_recommendation()`
- `apply_calibration_memory_recommendation()`
- `ignore_calibration_memory_recommendation()`
- refresh hooks from design-label updates, pulse-width changes, summary-table refresh, and selected-summary-row load

Manager hooks:

- `preview_calibration_memory_recommendation(...)`
- `record_calibration_memory_ui_interaction(...)`
- `get_calibration_memory_ui_recommendation_summary()`
- queued pre-run UI events flushed when the sidecar run is created

Store hooks:

- `ui_recommendation` added to initial and final run-summary writes

## Validation

Automated validation run:

```powershell
.\env\Scripts\python.exe -m pytest -q
```

Result at implementation time: `320 passed`.

## Known Limitations

- The panel is still read-mostly; it only preloads the current startup controls.
- There is no UI editor yet for calibration-memory runtime mode.
- Grouped fallbacks are visible, but Phase 5 keeps them reference-only unless they already pass the conservative qualification policy.
- There is still no export / downstream analysis UI in this phase.
