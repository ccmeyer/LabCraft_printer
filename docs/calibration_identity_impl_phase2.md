# Calibration Identity Phase 2

## Summary

Phase 2 adds explicit, registry-backed calibration identity for reagents and printer heads without changing calibration execution semantics.

- `stock_id` remains the canonical identity for the actual loaded stock solution when available.
- `reagent_id` is now a separate grouped identity for memory and analysis.
- `printer_head_id` is now a separate physical-head identity.
- `head_type_id` is now a separate grouped nozzle/head-type identity.
- Phase 1 sidecar writes remain best-effort and write-only.
- Recommendation lookup and pair-memory aggregation are still not implemented.

## Files Changed

- `FreeRTOS-interface/CalibrationIdentity.py`
- `FreeRTOS-interface/CalibrationMemoryStore.py`
- `FreeRTOS-interface/Model.py`
- `FreeRTOS-interface/CalibrationMemory/entities/reagents.json`
- `FreeRTOS-interface/CalibrationMemory/entities/printer_head_types.json`
- `FreeRTOS-interface/CalibrationMemory/entities/printer_heads.json`
- `tests/test_calibration_identity_registry.py`
- `tests/test_calibration_memory_store.py`
- `tests/test_calibration_memory_integration.py`

## What Changed

### Explicit identity registries

Added a new registry layer under `FreeRTOS-interface/CalibrationMemory/entities/`:

- `reagents.json`
- `printer_head_types.json`
- `printer_heads.json`

The new `CalibrationIdentityRegistry` owns:

- schema/version validation
- default-seed initialization
- load/save helpers
- lookup helpers by id
- upsert helpers
- runtime resolution helpers
- helper methods to assign registry identity back onto `StockSolution` and `PrinterHead`

### Runtime model metadata

Added optional identity metadata fields to the existing domain models:

- `StockSolution`
  - `reagent_id`
  - `display_name`
  - `reagent_family`
  - `glycerol_percent`
  - `tags`
  - `notes`
  - helper: `set_reagent_identity(...)`
- `PrinterHead`
  - `printer_head_id`
  - `head_type_id`
  - `display_name`
  - `nominal_nozzle_diameter_um`
  - `measured_nozzle_diameter_um`
  - `manufacturer_batch`
  - `identity_tags`
  - `identity_notes`
  - helper: `set_identity_metadata(...)`

These fields are optional and do not affect existing calibration behavior when unset.

### Sidecar context upgrade

`CalibrationContextBuilder` now resolves identity in this order:

1. explicit runtime metadata on `StockSolution` / `PrinterHead`
2. explicit registry-backed lookup
3. registry alias match
4. weak fallback

Weak fallback remains:

- grouped reagent identity from normalized reagent name
- printer-head identity from stable runtime `serial`/`id` when present
- final fallback to `gripper_slot_<n>`

## Identity Fields Added To Run Context

The sidecar context now includes:

- `reagent_id`
- `reagent_display_name`
- `reagent_family`
- `glycerol_percent`
- `reagent_tags`
- `reagent_notes`
- `stock_id`
- `stock_display_name`
- `printer_head_id`
- `printer_head_display_name`
- `head_type_id`
- `head_type_display_name`
- `nominal_nozzle_diameter_um`
- `measured_nozzle_diameter_um`
- `manufacturer_batch`
- `printer_head_tags`
- `printer_head_notes`
- `identity_sources`
- expanded `identity_quality`

Legacy fields are preserved:

- `reagent_name`
- `stock_concentration`
- `stock_units`
- `gripper_slot_number`
- `nozzle_diameter_um`

## Backward Compatibility

Old Phase 1 runs remain readable.

- legacy `identity_quality.derived` is normalized to `inferred`
- legacy `identity_quality.missing` is normalized to `unknown`
- old runs with weak identity are still usable for analysis, but they are not exact-pair ready

Phase 2 does not change `calibration.json`, UI summaries, or process execution.

## Remaining Weak-Identity Paths

These still exist in the repo and are intentional for now:

- reagent grouping can still fall back to normalized reagent-name alias matching when `stock_id` is not mapped in the reagent registry
- printer-head identity can still fall back to unregistered runtime `serial` / `id`
- printer-head identity can still fall back to `gripper_slot_<n>` when no explicit id is available
- `head_type_id` can still be inferred from `nominal_nozzle_diameter_um`

Those paths are lower confidence and should not be treated as exact-pair priors later unless the relevant identity is explicit.

## Tests Run

```powershell
.\env\Scripts\python.exe -m pytest -q tests/test_calibration_identity_registry.py tests/test_calibration_memory_store.py tests/test_calibration_memory_integration.py tests/test_calibration_process_recorder.py tests/test_model_atomic_writes.py
```

Result:

- `12 passed`
