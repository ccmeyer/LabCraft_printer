# Baseline Characterization Registry Setup

## What Is Seeded

Phase 2 seeds the calibration memory registries with:

### Reagent identities

- `water`
- `glycerol_25pct`
- `glycerol_50pct`

### Head types

- `nozzle_80um`
- `nozzle_100um`
- `nozzle_120um`

### Individual printer heads

- `nozzle_80um_h01` through `nozzle_80um_h05`
- `nozzle_100um_h01` through `nozzle_100um_h05`
- `nozzle_120um_h01` through `nozzle_120um_h05`

These live in:

- `FreeRTOS-interface/CalibrationMemory/entities/reagents.json`
- `FreeRTOS-interface/CalibrationMemory/entities/printer_head_types.json`
- `FreeRTOS-interface/CalibrationMemory/entities/printer_heads.json`

## Important Distinction

### Reagent identity

- `stock_id` identifies the actual loaded stock solution in the app
- `reagent_id` groups multiple stock solutions into one analysis family

For the baseline study, `reagent_id` is seeded, but the `stock_ids` arrays are intentionally left empty until you confirm the real stock ids used in your experiment design.

To make reagent identity explicit instead of inferred:

1. determine the actual stock ids produced by the experiment setup
2. add those stock ids to the matching item in `reagents.json`

Example:

```json
{
  "reagent_id": "water",
  "stock_ids": ["Water_0.00_--"]
}
```

### Printer-head identity

- `printer_head_id` identifies one physical head instance
- `head_type_id` groups that instance into a nozzle type

The 15 baseline head instances are already seeded in `printer_heads.json`, but the runtime `PrinterHead` object still needs an explicit id or stable alias to match one of them.

## Smallest Registration Path

The repo now supports two small, safe ways to make identity explicit.

### Option 1: registry-backed runtime metadata

Assign explicit metadata to the current objects before calibration:

```python
stock_solution.set_reagent_identity(
    reagent_id="glycerol_25pct",
    display_name="25% Glycerol",
    reagent_family="aqueous_glycerol",
    glycerol_percent=25.0,
)

printer_head.set_identity_metadata(
    printer_head_id="nozzle_100um_h03",
    head_type_id="nozzle_100um",
    display_name="100 um H03",
    nominal_nozzle_diameter_um=100.0,
)
```

### Option 2: registry helper assignment

Use the new registry helper methods:

```python
registry.assign_reagent_identity(stock_solution, "glycerol_25pct")
registry.assign_printer_head_identity(printer_head, "nozzle_100um_h03")
```

This is the cleanest path for the baseline study because it keeps the source of truth in the seeded registry files.

## Recommended Baseline Workflow

1. Confirm the actual `stock_id` values used for water, 25% glycerol, and 50% glycerol.
2. Add those `stock_id` values into `reagents.json`.
3. Decide which physical head is `h01` through `h05` for each nozzle diameter.
4. Ensure each runtime `PrinterHead` object gets the matching `printer_head_id`.
5. Run calibration.
6. Verify that the sidecar context shows:
   - `identity_quality.reagent_id = explicit`
   - `identity_quality.printer_head_id = explicit`
   - `identity_quality.head_type_id = explicit`

## Remaining Limitations

- there is still no UI for editing these registries
- there is still no automatic recommendation lookup
- there is still no pair-memory aggregation
- if a runtime head is not assigned an explicit identity, the system will still fall back to a weaker path such as `serial`, `id`, or `gripper_slot_<n>`

Until the runtime `printer_head_id` is explicit, those runs should be treated as lower-confidence for exact-pair analysis later.
