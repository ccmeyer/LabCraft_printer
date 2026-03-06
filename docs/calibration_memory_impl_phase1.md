# Calibration Memory Phase 1

## Summary

Phase 1 adds a write-only calibration memory sidecar that runs in parallel with the existing calibration pipeline.

- No UI behavior changed.
- No recommendation lookup was added.
- No calibration parameter reuse was added.
- `calibration.json`, `calibration_recordings`, and existing droplet imager outputs remain authoritative and unchanged.

## Files Changed

- `FreeRTOS-interface/CalibrationMemoryStore.py`
- `FreeRTOS-interface/CalibrationMemory/.gitkeep`
- `FreeRTOS-interface/Model.py`
- `FreeRTOS-interface/CalibrationClasses/Model.py`
- `tests/test_calibration_memory_store.py`
- `tests/test_calibration_memory_integration.py`
- `tests/calibration_test_utils.py`

## Hooks Used

The sidecar is attached only at existing seams.

- `Model.__init__`
  - creates and initializes `self.calibration_memory_store`
- `Model.reload_droplet_model`
  - reuses or recreates the store and rebinds it to the current `Model`
- `CalibrationManager.begin_session`
  - starts a sidecar run via `CalibrationMemoryStore.create_run(...)`
- `CalibrationManager.onCalibrationDataUpdated`
  - rewrites `run_summary.json` from the current authoritative in-memory run
- `CalibrationManager.end_session`
  - rewrites `run_summary.json` one final time with `ended_at`
- `BaseCalibrationProcess._record_event`
  - appends `process_event` observations
- `BaseCalibrationProcess._record_analysis`
  - appends `process_analysis` observations
- `BaseCalibrationProcess._record_capture`
  - appends `process_capture` observations with artifact references
- `BaseCalibrationProcess._record_error`
  - appends `process_error` observations

## Schema Files and Sidecar Outputs

The store bootstraps the root under `FreeRTOS-interface/CalibrationMemory/`.

Created or populated by the app:

- `FreeRTOS-interface/CalibrationMemory/schema.json`
- `FreeRTOS-interface/CalibrationMemory/indices/run_catalog.jsonl`
- `FreeRTOS-interface/CalibrationMemory/runs/<run_id>/run_summary.json`
- `FreeRTOS-interface/CalibrationMemory/runs/<run_id>/observations.jsonl`

Bootstrapped directories:

- `FreeRTOS-interface/CalibrationMemory/entities/`
- `FreeRTOS-interface/CalibrationMemory/indices/`
- `FreeRTOS-interface/CalibrationMemory/runs/`

Not created yet in Phase 1:

- reagent/head memory aggregate files
- recommendation indices
- export datasets

## Behavior Notes

- All sidecar writes are best-effort.
- If the memory store fails, calibration continues.
- Failures are surfaced as console warnings with the `[CalibrationMemory]` prefix.
- Capture observations store references to existing artifacts rather than copying files.
- Identity fields include `identity_quality` so derived ids can be distinguished from explicit ids.
- `stock_id` is preferred when the current printer head exposes it.

## Known Limitations Before Real Dataset Collection

- `head_type_id` and `nozzle_diameter_um` are still `null` because the current repo does not expose authoritative nozzle metadata at the printer-head model layer.
- `printer_head_id` falls back to a derived `gripper_slot_<n>` identifier if no explicit serial/id is available.
- The run summary is intentionally conservative: it mirrors the latest per-phase result from the authoritative current run and does not yet compute pair-memory aggregates or recommendations.
- Raw observations come from the existing process recorder hooks only; Phase 1 does not yet ingest the full droplet-imager metadata stream as a first-class sidecar dataset.
- Error paths currently produce both a generic `process_event` with `event_type=error` and a dedicated `process_error` observation.

## Tests Run

Executed with the project environment interpreter:

```powershell
.\env\Scripts\python.exe -m pytest -q tests/test_calibration_memory_store.py tests/test_calibration_memory_integration.py tests/test_calibration_process_recorder.py tests/test_model_atomic_writes.py
```

Result:

- `7 passed`
