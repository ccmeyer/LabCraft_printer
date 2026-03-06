# Reagent Memory and Calibration Dataset Design

## Purpose

This document proposes a concrete design for:

- a reagent memory system that can reuse prior calibration knowledge
- a structured calibration dataset logging system for later analysis

This is a design-only step. It is intentionally shaped to fit the current architecture described in [docs/calibration_reagent_memory_recon.md](c:\Users\conar\OneDrive\Documents\PlatformIO\Projects\LabCraft_printer\docs\calibration_reagent_memory_recon.md), with minimal disruption to the existing calibration flow.

## Design Goals

1. Keep the current calibration flow working.
2. Add write-only structured logging first, then add read/reuse behavior later.
3. Use simple, inspectable persistence formats now.
4. Support analysis across:
   - reagent type
   - nozzle diameter / printer head type
   - individual printer head instance
   - pulse width
   - pressure
   - emergence behavior
   - single-droplet band
   - trajectory / velocity
   - droplet volume
   - CV / repeatability
5. Avoid forcing a major refactor of `CalibrationManager`, process classes, or the UI.

## Non-Goals for the First Implementation

- No database dependency.
- No ML-based recommendation engine.
- No automatic design mutation without user confirmation.
- No attempt to replace `calibration.json`, `calibration_recordings`, or `droplet_imager_captures` in phase 1.

## Current Architecture Constraints That Shape the Design

From the current codebase:

- `FreeRTOS-interface/View.py:1207` `PressurePlotBox.droplet_imager()` is the primary modern entry point.
- `FreeRTOS-interface/CalibrationClasses/View.py:169` `DropletImagingDialog` is the main modern calibration UI.
- `FreeRTOS-interface/CalibrationClasses/Model.py:670` `CalibrationManager` owns orchestration and `calibration.json` updates.
- `FreeRTOS-interface/Model.py:5449` `Model.reload_droplet_model()` recreates both `DropletCameraModel` and `CalibrationManager`.
- `FreeRTOS-interface/CalibrationClasses/Model.py:1892` `_safe_get_stock_solution()` currently resolves stock context too weakly.
- `FreeRTOS-interface/CalibrationClasses/Model.py:1900` `_safe_get_printer_head_id()` currently falls back to `str(ph)`.
- `FreeRTOS-interface/CalibrationClasses/Model.py:1771` `onCalibrationDataUpdated()` is the best current run-summary hook.
- `FreeRTOS-interface/CalibrationClasses/Model.py:2064` `BaseCalibrationProcess` already exposes `_record_event`, `_record_analysis`, `_record_capture`, and `_record_error`.
- `FreeRTOS-interface/CalibrationClasses/Model.py:10695` `_record_pressure_sweep_analysis()` and `:12015` `_record_pressure_result()` are already rich structured observation hooks.

These constraints point to a design where:

- persistence is not owned by `View` or `Controller`
- durable reagent memory is not stored only in `CalibrationManager` instance state
- new logging is added in parallel with the existing persistence paths

## Proposed Core Concept

Introduce a new durable store that lives outside experiment-local calibration state:

- code module:
  - `FreeRTOS-interface/CalibrationMemoryStore.py`
- data root:
  - `FreeRTOS-interface/CalibrationMemory/`

The store does four jobs:

1. Maintain stable entity registries for reagents, printer head types, and printer head instances.
2. Write append-only raw observations for each calibration run.
3. Write per-run summarized calibration results.
4. Maintain derived memory snapshots used for reuse and recommendation.

## Recommended Entity Model

### 1. `ReagentProfile`

Purpose:

- canonical reagent identity for memory lookup and analysis

Key:

- `reagent_id`

Examples:

- `water`
- `glycerol_25pct`
- `glycerol_50pct`

Recommended fields:

- `reagent_id`
- `display_name`
- `family_id`
- `composition`
- `tags`
- `active`

For the planned initial dataset:

- `family_id = "aqueous_glycerol"`
- `composition.glycerol_pct = 0`, `25`, `50`

### 2. `PrinterHeadType`

Purpose:

- canonical nozzle/head family identity

Key:

- `head_type_id`

Examples:

- `nozzle_80um`
- `nozzle_100um`
- `nozzle_120um`

Recommended fields:

- `head_type_id`
- `display_name`
- `nominal_nozzle_diameter_um`
- `notes`
- `active`

### 3. `PrinterHeadInstance`

Purpose:

- stable identity for an individual physical head

Key:

- `printer_head_id`

Examples:

- `nozzle_80um_h01`
- `nozzle_80um_h02`
- `nozzle_100um_h03`

Recommended fields:

- `printer_head_id`
- `head_type_id`
- `nominal_nozzle_diameter_um`
- `serial_or_label`
- `status`
- `notes`

### 4. `CalibrationRun`

Purpose:

- one structured record for one calibration session

Key:

- `run_id`

This should align with the current `CalibrationManager.begin_session()` run concept, not replace it.

### 5. `CalibrationObservation`

Purpose:

- append-only raw facts recorded during calibration

Key:

- `observation_id`
- grouped by `run_id`

### 6. `MemorySnapshot`

Purpose:

- derived reusable knowledge, built from many runs

Stored at four scopes:

- reagent-only
- head-type-only
- head-instance-only
- reagent + head-instance pair

Recommended additional derived scope:

- reagent + head-type pair

This derived pair-type scope is important because the planned dataset includes 5 heads per nozzle type and the system needs a fallback for a new head of a known type.

## Reagent Memory Concept

### What entity should be saved?

The memory system should save three layers:

1. Raw run facts
   - every observation and every run summary
2. Derived reusable summaries
   - per reagent
   - per head type
   - per printer head instance
   - per reagent + head type
   - per reagent + printer head instance
3. Recommendation records
   - a compact record of seed settings and expected behavior

### What should be keyed by reagent?

Key: `reagent_id`

Use for properties that generalize across heads:

- reagent family and composition metadata
- same-family similarity metadata
- aggregate emergence timing by head type and pulse width
- aggregate single-droplet band tendencies by head type and pulse width
- aggregate characterization expectations by head type and pulse width
- recommended fallback seed when no exact head match exists

Example reagent-only memory fields:

- `family_id`
- `composition.glycerol_pct`
- `same_family_neighbors`
- `per_head_type`
  - `per_pulse_width`
    - median emergence delay
    - median primary band
    - median trajectory-valid band
    - mean/median droplet volume
    - median CV
    - sample counts

### What should be keyed by printer head?

Keys:

- `head_type_id`
- `printer_head_id`

Use for properties that generalize across reagents:

- static metadata:
  - nozzle diameter
  - head type
  - instance label
- health / history:
  - run counts
  - last calibration time
  - last successful conditions
  - water baseline behavior
- head-specific offsets:
  - persistent shift in start pressure
  - persistent shift in emergence delay
  - persistent tendency toward higher/lower CV

Practical recommendation:

- keep both `head_type_memory` and `printer_head_memory`
- use `head_type_memory` for same-type fallback
- use `printer_head_memory` for instance-specific drift tracking

### What should be keyed by reagent + printer head pair?

Key:

- `pair_key = reagent_id + "::" + printer_head_id`

This is the main operational memory record.

It should store:

- last valid run used for this pair
- best known seed settings
- per-pulse-width summaries
- recommended pressure seed for each pulse width
- expected emergence delay
- single-droplet band
- trajectory-valid pressure band
- recommended stable condition from characterization
- confidence counts

Recommended structure:

- top-level exact pair memory
- `per_pulse_width` map

This is the record the calibration flow should consult first.

### What should be keyed by reagent + head type?

Key:

- `pair_type_key = reagent_id + "::" + head_type_id`

This should exist even though it was not explicitly requested, because it is the safest and most useful fallback for:

- a new printer head instance of an existing nozzle type
- a head with insufficient pair-specific history

### Initial similarity model

Keep similarity simple and explicit:

- printer head similarity:
  - same `head_type_id`
- reagent similarity:
  - same `family_id`
  - nearest `composition.glycerol_pct`

For the planned initial dataset, this is concrete and sufficient.

### Recommended lookup order

When the system needs a seed or suggestion:

1. exact pair + exact pulse width
2. exact pair, nearest pulse width
3. reagent + head type + exact pulse width
4. same-family nearest reagent + same head type + exact pulse width
5. reagent-only + exact head type
6. head-type-only
7. current UI defaults

This gives “similar reagents and printer heads” behavior without requiring a statistical model in phase 1.

## Raw Observation Logging Schema

## Recommendation

- format: `JSONL`
- one line per observation
- one file per run
- append-only

Why:

- matches the current `events.jsonl` and `analysis.jsonl` pattern
- robust to partial writes
- easy to inspect manually
- easy to post-process into CSV or pandas later

### Common observation envelope

Every raw observation record should include:

- `schema_name`
- `schema_version`
- `observation_id`
- `run_id`
- `ts_utc`
- `phase`
- `observation_type`
- `context`
- `settings`
- `machine`
- `analysis`
- `artifact_refs`

### Required context fields

- `reagent_id`
- `reagent_display_name`
- `family_id`
- `composition`
- `stock_id`
- `printer_head_id`
- `head_type_id`
- `nozzle_diameter_um`
- `identity_quality`
- `experiment_dir`
- `calibration_file_path`
- `profile_name`

### Canonical observation types for phase 1

- `emergence_candidate`
- `pressure_scan_replicate`
- `pressure_scan_result`
- `trajectory_point`
- `trajectory_fit`
- `characterization_frame`
- `characterization_batch`
- `memory_seed_used`

### Example raw observation record

```json
{
  "schema_name": "labcraft.calibration_memory.observation",
  "schema_version": 1,
  "observation_id": "obs_20260306_180402_000117",
  "run_id": "run_1c8d4b9b",
  "ts_utc": "2026-03-06T18:04:02Z",
  "phase": "pressure_sweep_characterization",
  "observation_type": "characterization_frame",
  "context": {
    "reagent_id": "glycerol_25pct",
    "reagent_display_name": "25% Glycerol",
    "family_id": "aqueous_glycerol",
    "composition": {
      "glycerol_pct": 25.0
    },
    "stock_id": "glycerol_25pct_1.00_--",
    "printer_head_id": "nozzle_100um_h03",
    "head_type_id": "nozzle_100um",
    "nozzle_diameter_um": 100,
    "identity_quality": {
      "reagent": "explicit",
      "printer_head": "explicit"
    },
    "experiment_dir": "FreeRTOS-interface/Experiments/Untitled-20260306_175500",
    "calibration_file_path": "FreeRTOS-interface/Experiments/Untitled-20260306_175500/calibration.json",
    "profile_name": "current"
  },
  "settings": {
    "print_pulse_width_us": 1500,
    "print_pressure_psi": 1.62,
    "flash_delay_us": 5150,
    "flash_duration_ns": 1000,
    "num_droplets": 1,
    "exposure_time_us": 30000
  },
  "machine": {
    "position": {
      "X": 12450,
      "Y": 8840,
      "Z": 13610
    }
  },
  "analysis": {
    "accepted": true,
    "volume_nL": 9.86,
    "circularity_ellipse": 0.95,
    "focus": 5240000.0,
    "center_px": [552, 304]
  },
  "artifact_refs": {
    "camera_save_dir": "FreeRTOS-interface/CalibrationMemory/runs/run_1c8d4b9b",
    "frame_index": 17
  }
}
```

## Summarized Calibration Result Schema

## Recommendation

- format: `JSON`
- one summary per run
- atomic overwrite

Why:

- easy to inspect
- easy to rewrite atomically
- stable input to pair-memory aggregation

### Summary scope

One run summary should contain:

- run context
- process-level outputs
- per-pulse-width results
- recommended seed condition
- artifact references back to existing current files

### Required summary sections

- `context`
- `run_timing`
- `process_results`
  - `nozzle_position`
  - `nozzle_focus`
  - `droplet_emergence`
  - `pressure_scan`
  - `pressure_trajectory`
  - `pressure_sweep_characterization`
- `recommended_seed`
- `artifact_refs`

### Example run summary

```json
{
  "schema_name": "labcraft.calibration_memory.run_summary",
  "schema_version": 1,
  "run_id": "run_1c8d4b9b",
  "context": {
    "reagent_id": "glycerol_25pct",
    "stock_id": "glycerol_25pct_1.00_--",
    "printer_head_id": "nozzle_100um_h03",
    "head_type_id": "nozzle_100um",
    "nozzle_diameter_um": 100,
    "profile_name": "current"
  },
  "run_timing": {
    "started_at_utc": "2026-03-06T17:55:00Z",
    "ended_at_utc": "2026-03-06T18:12:31Z"
  },
  "process_results": {
    "droplet_emergence": {
      "emergence_time_us": 4300,
      "real_nozzle_center_px": [541, 212]
    },
    "pressure_scan": {
      "pulse_width_us": 1500,
      "primary_band_psi": [1.48, 1.84],
      "single_bands_psi": [[1.46, 1.87]]
    },
    "pressure_trajectory": {
      "trajectory_pressure_band_psi": [1.52, 1.78],
      "valid_fit_pressures_psi": [1.52, 1.58, 1.64, 1.70, 1.76]
    },
    "pressure_sweep_characterization": {
      "pulse_width_us": 1500,
      "pressure_points": [
        {
          "pressure_psi": 1.52,
          "mean_volume_nL": 9.12,
          "cv_pct": 6.4,
          "valid": true
        },
        {
          "pressure_psi": 1.58,
          "mean_volume_nL": 9.61,
          "cv_pct": 4.7,
          "valid": true
        },
        {
          "pressure_psi": 1.64,
          "mean_volume_nL": 10.04,
          "cv_pct": 3.9,
          "valid": true
        }
      ]
    }
  },
  "recommended_seed": {
    "selection_method": "lowest_cv_within_band_overlap",
    "print_pulse_width_us": 1500,
    "print_pressure_psi": 1.64,
    "flash_delay_us": 4300,
    "expected_mean_volume_nL": 10.04,
    "expected_cv_pct": 3.9
  },
  "artifact_refs": {
    "calibration_json_path": "FreeRTOS-interface/Experiments/Untitled-20260306_175500/calibration.json",
    "process_recordings_root": "FreeRTOS-interface/Experiments/Untitled-20260306_175500/calibration_recordings",
    "camera_capture_root": "FreeRTOS-interface/Experiments/Untitled-20260306_175500/droplet_imager_captures"
  }
}
```

## Derived Memory Snapshot Schema

This is the actual reusable memory record.

## Recommendation

- format: `JSON`
- one aggregate file per scope
- atomically rewritten after each completed run

Primary files:

- `reagent_memory.json`
- `head_type_memory.json`
- `printer_head_memory.json`
- `pair_memory.json`
- `pair_type_memory.json`

### Example exact pair memory entry

```json
{
  "pair_key": "glycerol_25pct::nozzle_100um_h03",
  "schema_version": 1,
  "reagent_id": "glycerol_25pct",
  "printer_head_id": "nozzle_100um_h03",
  "head_type_id": "nozzle_100um",
  "last_updated_at_utc": "2026-03-06T18:12:31Z",
  "run_count": 4,
  "recommended_default_seed": {
    "print_pulse_width_us": 1500,
    "print_pressure_psi": 1.64,
    "flash_delay_us": 4300,
    "source_scope": "exact_pair"
  },
  "per_pulse_width": {
    "1500": {
      "single_droplet_band_psi": [1.48, 1.84],
      "trajectory_pressure_band_psi": [1.52, 1.78],
      "recommended_pressure_psi": 1.64,
      "expected_mean_volume_nL": 10.04,
      "expected_cv_pct": 3.9,
      "median_emergence_time_us": 4300,
      "sample_count": 4
    },
    "1600": {
      "single_droplet_band_psi": [1.42, 1.76],
      "trajectory_pressure_band_psi": [1.48, 1.70],
      "recommended_pressure_psi": 1.58,
      "expected_mean_volume_nL": 10.62,
      "expected_cv_pct": 4.2,
      "median_emergence_time_us": 4410,
      "sample_count": 3
    }
  }
}
```

## Persistence Approach

## File formats

Recommended now:

- `JSON` for registries, per-run summaries, and derived memory snapshots
- `JSONL` for raw observations and run catalog/index files
- `CSV` only as a later export format, not as the primary source of truth
- no `pickle`
- no `SQLite` in phase 1

### Why not SQLite yet?

Because the current app already uses:

- atomic JSON writes
- append-only JSONL logs

And the planned initial dataset size is small:

- 3 reagents
- 3 head types
- 5 heads per head type
- 6 pulse widths

That is small enough that:

- human-inspectable files are practical
- migration risk is low
- runtime complexity stays low

SQLite can be added later if:

- observation count grows very large
- concurrent reads/writes become important
- query latency becomes a real issue

## Folder structure

Recommended data root:

- `FreeRTOS-interface/CalibrationMemory/`

Recommended layout:

```text
FreeRTOS-interface/
  CalibrationMemory/
    schema.json
    entities/
      reagents.json
      printer_head_types.json
      printer_heads.json
    indices/
      run_catalog.jsonl
      reagent_memory.json
      head_type_memory.json
      printer_head_memory.json
      pair_type_memory.json
      pair_memory.json
    runs/
      run_1c8d4b9b/
        run_summary.json
        observations.jsonl
```

### Why a global store instead of experiment-local only?

Because reagent memory is meant to persist across experiments, while current `calibration.json` is experiment-local.

### Why separate raw observations from summary records?

Because they have different purposes:

- raw observations are append-only and high volume
- summaries are curated and stable
- memory snapshots are derived and rewritten

That separation:

- keeps write paths simple
- keeps read paths fast
- makes later analysis easier
- avoids needing to parse all raw observations for common UI lookups

## Schema Versioning

Recommendation:

- every file and every record includes:
  - `schema_name`
  - `schema_version`
- root file:
  - `CalibrationMemory/schema.json`

Example:

```json
{
  "schema_family": "labcraft.calibration_memory",
  "schema_version": 1,
  "created_at_utc": "2026-03-06T18:30:00Z"
}
```

Versioning rules:

1. Start with integer `schema_version = 1`.
2. Allow additive fields within version 1.
3. For breaking changes, bump to version 2 and add a migration script.
4. Never silently reinterpret old fields.

## Backward Compatibility Plan

### Keep the current calibration flow intact

In phase 1:

- `calibration.json` remains unchanged as the current in-app summary store
- `calibration_recordings` remains unchanged
- `droplet_imager_captures` remains unchanged
- the UI summary table still uses `CalibrationManager.get_pressure_sweep_summary_rows()`

### New persistence runs in parallel

The new memory store should be:

- optional
- best-effort
- non-blocking from a workflow perspective

If it fails:

- calibration should continue
- the user should get a warning
- existing current outputs should still be written

### Stable ID rollout should be gradual

Current problem:

- `PrinterHead` has no stable `serial` or `id`
- current stock identification is weakly derived from reagent name

Phase 1 fallback strategy:

- allow `identity_quality` to mark fields as:
  - `explicit`
  - `derived`
- write the data anyway
- only use exact-pair recommendations when both reagent and head identity are explicit

### Existing legacy files should not be repurposed immediately

- `FreeRTOS-interface/Presets/Reagents.json` exists but is not actively loaded in the current app flow.
- It should not become the primary runtime memory file in phase 1.
- If useful later, it can be imported into the new entity registry with a dedicated migration step.

## Later Analysis Without Major Refactors

This design supports later analysis because:

1. Raw observations use a common envelope with stable IDs.
2. Run summaries already flatten the calibration flow into one place.
3. Memory snapshots are derived, not hand-authored.
4. Existing process-specific details remain available through `artifact_refs`.
5. A later export tool can read `runs/*/run_summary.json` and `runs/*/observations.jsonl` without needing app changes.

Recommended later analysis tools:

- `tools/export_calibration_memory_csv.py`
- `tools/plot_calibration_memory_trends.py`

These should be offline tools, not runtime dependencies.

## Proposed Modules and Class Names

### New code modules

- `FreeRTOS-interface/CalibrationMemoryStore.py`
  - `CalibrationMemoryStore`
  - `CalibrationContextBuilder`
  - `CalibrationMemoryRecommender`

### Why one module first?

Because phase 1 should stay small. One module is enough to:

- build context
- write observations
- write run summaries
- maintain memory snapshots

It can be split later if it grows.

## Proposed Runtime Responsibilities

### `CalibrationMemoryStore`

Owns:

- path setup
- atomic JSON writes
- JSONL append helpers
- entity registry loading
- run start/end
- observation append
- run summary write
- memory aggregation
- recommendation lookup

### `CalibrationContextBuilder`

Owns:

- translating current `Model`, `RackModel`, `PrinterHead`, and stock context into a stable memory context
- attaching:
  - `reagent_id`
  - `stock_id`
  - `printer_head_id`
  - `head_type_id`
  - `nozzle_diameter_um`
  - `identity_quality`

### `CalibrationMemoryRecommender`

Owns:

- exact-pair lookup
- same-head-type fallback
- same-family-nearest-reagent fallback
- confidence metadata on returned recommendations

## Proposed Phased Implementation Plan

### Phase 1: Add the store as a parallel write-only sidecar

Goal:

- no UI behavior change
- no calibration logic change

Steps:

1. Add `CalibrationMemoryStore.py`.
2. Add `FreeRTOS-interface/CalibrationMemory/` root creation.
3. Write entity registry files manually or from a small seed helper.
4. Create a run when `CalibrationManager.begin_session()` starts.
5. Write a run summary when `CalibrationManager.onCalibrationDataUpdated()` receives step results.
6. Write raw observations from existing process-level `_record_*` hooks.

Safety:

- existing files remain authoritative
- if the new store fails, calibration still completes

### Phase 2: Add explicit reagent and head identities

Goal:

- stop relying on reagent-name-only and `str(ph)` fallbacks

Steps:

1. Add stable fields to `PrinterHead`:
   - `printer_head_id`
   - `head_type_id`
   - `nominal_nozzle_diameter_um`
2. Seed the planned head registry:
   - `nozzle_80um_h01` to `nozzle_80um_h05`
   - `nozzle_100um_h01` to `nozzle_100um_h05`
   - `nozzle_120um_h01` to `nozzle_120um_h05`
3. Add reagent registry entries:
   - `water`
   - `glycerol_25pct`
   - `glycerol_50pct`
4. Replace weak context builders with explicit registry-backed IDs where available.

Safety:

- continue logging derived IDs if explicit IDs are missing

### Phase 3: Normalize richer raw observations

Goal:

- capture enough data for later analysis without changing process behavior

Steps:

1. Mirror `BaseCalibrationProcess._record_event()` into memory observations.
2. Mirror `BaseCalibrationProcess._record_analysis()` into memory observations.
3. Mirror `BaseCalibrationProcess._record_capture()` into memory artifact refs.
4. Add explicit observation normalization in:
   - `DropletSearchCalibrationProcess`
   - `PressureSweepCharacterizationProcess`
   - `PressureTrajectoryCalibrationProcess`
   - `DropletEmergenceCalibrationProcess`

Safety:

- use append-only JSONL
- keep existing recorder outputs unchanged

### Phase 4: Build derived memory snapshots

Goal:

- produce reusable memory without changing the calibration UI yet

Steps:

1. Aggregate exact pair memory from completed run summaries.
2. Aggregate reagent + head type memory.
3. Aggregate reagent-only and head-type-only fallback memory.
4. Write `pair_memory.json`, `pair_type_memory.json`, `reagent_memory.json`, and `head_type_memory.json`.

Safety:

- derived files can always be regenerated from run summaries

### Phase 5: Use memory as an optional recommendation source

Goal:

- add reuse without breaking current behavior

Steps:

1. Add a lookup call before starting a run in `DropletImagingDialog`.
2. Show the recommended seed as:
   - start pressure
   - expected pressure band
   - expected emergence delay
   - recommended pulse width
3. Keep application of the seed user-confirmed at first.

Safety:

- do not silently override machine settings
- make recommendations opt-in

### Phase 6: Add analysis/export tooling

Goal:

- support trend analysis without touching runtime flow

Steps:

1. Export run summaries to CSV.
2. Export raw observations to CSV only when needed.
3. Add plotting notebooks/scripts using the global memory root.

## Exact Code Touch Points Based on the Current Repo

### Core model construction and lifetime

- `FreeRTOS-interface/Model.py`
  - `Model.__init__`
  - `Model.reload_droplet_model`
  - `ExperimentModel.set_calibration_manager`

Why:

- this is where a durable store should be created once and reattached when the transient calibration manager is recreated

### Identity and metadata

- `FreeRTOS-interface/Model.py`
  - `StockSolutionManager._make_stock_id`
  - `PrinterHead.__init__`
  - `PrinterHead.get_stock_id`
  - `PrinterHeadManager.create_printer_heads`
  - `RackModel.get_gripper_printer_head`

Why:

- these are the main current identity sources for reagent and head context

### Calibration manager summary and session hooks

- `FreeRTOS-interface/CalibrationClasses/Model.py`
  - `CalibrationManager.__init__`
  - `CalibrationManager._build_recorder_meta`
  - `CalibrationManager.begin_session`
  - `CalibrationManager.onCalibrationDataUpdated`
  - `CalibrationManager._safe_get_stock_solution`
  - `CalibrationManager._safe_get_printer_head_id`
  - `CalibrationManager.get_last_characterization_mean_nL`
  - `CalibrationManager.get_pressure_sweep_summary_rows`

Why:

- these are the best current hooks for parallel summary persistence and future recommendation lookup

### Common process-level observation hooks

- `FreeRTOS-interface/CalibrationClasses/Model.py`
  - `BaseCalibrationProcess._record_event`
  - `BaseCalibrationProcess._record_analysis`
  - `BaseCalibrationProcess._record_capture`
  - `BaseCalibrationProcess._record_error`

Why:

- these let the new dataset logging layer attach without rewriting every state machine first

### Rich process-specific observation producers

- `FreeRTOS-interface/CalibrationClasses/Model.py`
  - `DropletSearchCalibrationProcess._save_capture`
  - `DropletSearchCalibrationProcess._append_analysis`
  - `DropletSearchCalibrationProcess.onAnalyze`
  - `DropletSearchCalibrationProcess.onCharacterization`
  - `DropletSearchCalibrationProcess.onAnalyzeCharacterization`
  - `PressureSweepCharacterizationProcess._record_pressure_sweep_analysis`
  - `PressureSweepCharacterizationProcess._record_pressure_result`
  - `PressureSweepCharacterizationProcess.onAnalyzeBatch`
  - `PressureSweepCharacterizationProcess.onCompleted`
  - `PressureTrajectoryCalibrationProcess.onCalibrationCompleted`
  - `DropletEmergenceCalibrationProcess.onCalibrationCompleted`

Why:

- these already expose most of the structured data needed for the planned dataset

### Camera-side logging helpers

- `FreeRTOS-interface/CalibrationClasses/Model.py`
  - `DropletCameraModel.start_saving`
  - `DropletCameraModel.save_frame_with_metadata`
  - `DropletCameraModel.append_analysis_record`
  - `DropletCameraModel.write_json`

Why:

- these are the best places to record file references without duplicating images

### UI read-path and recommendation surfaces

- `FreeRTOS-interface/CalibrationClasses/View.py`
  - `DropletImagingDialog._bridge_get_current_reagent_name`
  - `DropletImagingDialog._preferred_char_mean_nL`
  - `DropletImagingDialog._bridge_preview_from_last_char`
  - `DropletImagingDialog.populate_summary_table`
  - `DropletImagingDialog._apply_previewed_droplet_volume`

Why:

- these are the natural seams for exposing memory-backed recommendations later

## Recommended Initial Registry for the Planned Dataset

### Reagents

- `water`
- `glycerol_25pct`
- `glycerol_50pct`

### Head types

- `nozzle_80um`
- `nozzle_100um`
- `nozzle_120um`

### Head instances

- `nozzle_80um_h01` to `nozzle_80um_h05`
- `nozzle_100um_h01` to `nozzle_100um_h05`
- `nozzle_120um_h01` to `nozzle_120um_h05`

### Pulse widths to preserve explicitly in summaries and memory

- `1300`
- `1400`
- `1500`
- `1600`
- `1700`
- `1800`

Use these exact pulse widths as string keys inside `per_pulse_width` maps in memory snapshot files.

## Final Recommendations

- Use a separate durable store, not `CalibrationManager` instance state, as the long-lived owner of reagent memory.
- Use `JSONL` for raw observations and `JSON` for registries, summaries, and derived memory.
- Keep raw observations separate from summary records.
- Keep current files and UI behavior intact in phase 1.
- Make stable reagent and head IDs explicit as early as possible.
- Start with exact-pair and head-type fallback logic, then add same-family reagent fallback.
- Treat `pair_memory.json` and `pair_type_memory.json` as the main operational recommendation sources.
- Defer SQLite until the data volume or query needs justify it.
