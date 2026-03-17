# PreBreakupDatasetAcquisitionProcess Plan

## Status

- Date created: 2026-03-14
- Owner: Codex + user
- Status: implementation in progress
- Scope: Python MVC acquisition process only. No firmware or protocol changes.

## Goal

Create a dedicated acquisition-only process that captures a dense pre-breakup morphology dataset across pulse width, pressure, and flash delay without making online calibration decisions.

This process exists to support offline analysis first:

- build a large image dataset with exact machine conditions attached to every frame
- join those frames to known single-pressure-band labels
- study how pulse width, pressure, flash delay, reagent, and nozzle change morphology metrics
- use those results to design a more robust deterministic pre-breakup calibration process later

This process is not intended to recommend pressures during acquisition.

## Why A New Process

### Not `PreBreakupMorphologyCalibrationProcess`

`PreBreakupMorphologyCalibrationProcess` in `FreeRTOS-interface/CalibrationClasses/Model.py` is optimized for online decision-making:

- delay scout
- pressure scan
- early stopping
- safe-window recommendation
- same-session handoff to later calibrations

Those behaviors are useful for calibration, but they bias data collection and make it harder to interpret the resulting dataset cleanly.

### Not `DropletTimecourseProcess` Unchanged

`DropletTimecourseProcess` in `FreeRTOS-interface/CalibrationClasses/Model.py` already captures dense flash-delay sweeps, which is the right acquisition primitive, but it is too narrow for the dataset we need:

- it only captures one delay sweep for one machine state
- it saves through `DropletCameraModel.start_saving(...)`, not primarily through the per-process recorder
- it does not define pressure grids, pulse-width grids, or condition manifests
- it does not attach label keys for later offline joins

### Recommended Direction

Create a new process:

- class name: `PreBreakupDatasetAcquisitionProcess`
- phase name: `pre_breakup_dataset_acquisition`

This process should:

- reuse the existing `BaseCalibrationProcess` state-machine pattern
- reuse the existing manager/controller/view launch path pattern
- reuse `CalibrationProcessRecorder` for run-scoped storage
- optionally reuse `DropletCameraModel.analyze_prebreakup_morphology(...)` for convenience metrics
- avoid all online classification-based termination

## Existing Repo Architecture To Mirror

### Launch Path

Existing calibration launch path:

- `FreeRTOS-interface/CalibrationClasses/View.py`
- `FreeRTOS-interface/Controller.py`
- `CalibrationManager.start_<process>(...)` in `FreeRTOS-interface/CalibrationClasses/Model.py`
- `_try_start_process(...)` in `FreeRTOS-interface/CalibrationClasses/Model.py`
- process class in `FreeRTOS-interface/CalibrationClasses/Model.py`

For this process, follow the same structure:

- `View.toggle_start_prebreakup_dataset_acquisition()`
- `Controller.start_prebreakup_dataset_acquisition(...)`
- `CalibrationManager.start_prebreakup_dataset_acquisition(...)`
- `PreBreakupDatasetAcquisitionProcess`

### Recorder Path

Existing run recording path already exists in `CalibrationProcessRecorder`:

- `run_meta.json`
- `events.jsonl`
- `analysis.jsonl`
- `verdict.json`
- `captures/`

The new process should use that path as its primary storage root under:

- `calibration_recordings/PreBreakupDatasetAcquisitionProcess/run_<timestamp>_<id>/`

### Reusable Capture/Analysis Helpers

Relevant existing components:

- `BaseCalibrationProcess`
- `_capture_with_policy(...)`
- `_request_settings_with_recording(...)`
- `CalibrationProcessRecorder`
- `DropletCameraModel.analyze_prebreakup_morphology(...)`
- `DropletTimecourseProcess`

## Proposed Process Definition

### Name

- class: `PreBreakupDatasetAcquisitionProcess`
- phase: `pre_breakup_dataset_acquisition`
- controller entry: `start_prebreakup_dataset_acquisition(...)`
- manager entry: `start_prebreakup_dataset_acquisition(...)`
- UI button label: `Acquire Pre-Breakup Dataset`

### Purpose

Capture a structured dataset of pre-breakup images across a planned grid of:

- pulse width
- pressure
- flash delay
- replicate index

with exact per-frame metadata and optional per-frame morphology analysis.

### Non-Goals

- do not estimate safe pressure online
- do not terminate early because of stream morphology
- do not try to optimize pulse width
- do not replace the current calibration process yet

## Recommended Acquisition Model

### Condition-Oriented Acquisition

Define a condition as:

- reagent / stock solution
- printer head / nozzle identity
- pulse width
- pressure
- delay sweep definition
- replicate count

For each condition:

1. apply pulse width and pressure
2. capture a fresh background
3. sweep all flash delays
4. capture every replicate at every delay
5. save all raw frames
6. optionally compute morphology metrics immediately
7. move to the next condition

There should be no early exit based on image analysis.

### Delay Definition

Support two modes:

- emergence-relative sweep
- absolute-delay sweep

Default should be emergence-relative because it is easier to compare across pulse widths.

Recommended planned fields:

- `delay_start_offset_us`
- `delay_stop_offset_us`
- `delay_step_us`

Actual delay computation:

- `delay_start_us = emergence_time_us + delay_start_offset_us`
- `delay_stop_us = emergence_time_us + delay_stop_offset_us`

The acquisition process should over-collect rather than infer when to stop.

## Dataset Structure

The dataset should be structured in four logical layers.

### 1. Run Layer

One row per acquisition run.

Recommended fields:

- `run_id`
- `process_name`
- `phase_name`
- `started_at_utc`
- `ended_at_utc`
- `experiment_dir`
- `operator`
- `stock_solution`
- `printer_head_id`
- `nozzle_id`
- `notes`
- `plan_path`
- `camera_defaults`
- `machine_position_start`

Storage:

- `run_meta.json`

### 2. Condition Layer

One row per planned acquisition condition.

Recommended fields:

- `condition_id`
- `run_id`
- `stock_solution`
- `printer_head_id`
- `nozzle_id`
- `pulse_width_us`
- `pressure_psi`
- `delay_mode`
- `delay_start_us`
- `delay_stop_us`
- `delay_step_us`
- `delay_start_offset_us`
- `delay_stop_offset_us`
- `replicates_per_delay`
- `background_policy`
- `emergence_time_us`
- `nozzle_center_px`
- `label_key`
- `notes`

Storage:

- `conditions.jsonl`

### 3. Frame Layer

One row per captured frame.

Recommended fields:

- `frame_id`
- `condition_id`
- `capture_index`
- `replicate_index`
- `capture_role`
- `image_relpath`
- `background_image_relpath`
- `flash_delay_us`
- `delay_from_emergence_us`
- `pulse_width_us`
- `pressure_psi`
- `emergence_time_us`
- `nozzle_center_px`
- `stock_solution`
- `printer_head_id`
- `label_key`

Storage:

- `frames.jsonl`
- `captures/`

### 4. Label Layer

This should be separate from raw acquisition.

Recommended fields:

- `label_key`
- `stock_solution`
- `printer_head_id`
- `nozzle_id`
- `pulse_width_us`
- `band_low_psi`
- `band_high_psi`
- `recommended_pressure_psi`
- `label_source_process`
- `label_source_run_id`
- `label_confidence`
- `notes`

This can live initially as:

- a manually prepared JSON/CSV file under the experiment directory
- or a dedicated `labels.jsonl`

Offline derived pressure labels:

- `pressure < band_low_psi` -> `too_low`
- `band_low_psi <= pressure <= band_high_psi` -> `good`
- `pressure > band_high_psi` -> `too_high`

## Per-Frame Analysis Data

The acquisition process should optionally run `DropletCameraModel.analyze_prebreakup_morphology(...)` and save the output for each frame.

Important derived fields to persist:

- `status`
- `reason`
- `contour_class`
- `protrusion_length_px`
- `distance_nozzle_to_neck_px`
- `neck_width_px`
- `neck_to_bulb_ratio`
- `max_width_px`
- `tip_y_px`
- `neck_y_px`
- `secondary_lobe_count`
- `detached_secondary_count`
- `largest_detached_secondary_area_px`
- `largest_detached_secondary_area_ratio`
- `nozzle_side_area_ratio`
- `distal_area_px`
- `p95`
- `bottom_clipped`
- `fov_bottom_clipped`
- `seed_contact_detected`

Important rule:

- raw captures are the source of truth
- online analysis is convenience metadata
- offline analysis must be able to recompute features later

## Recommended Storage Layout

Use the existing recorder layout, not only `droplet_imager_captures`.

Recommended run layout:

```text
calibration_recordings/
  PreBreakupDatasetAcquisitionProcess/
    run_YYYYMMDD_HHMMSS_<id>/
      run_meta.json
      verdict.json
      events.jsonl
      analysis.jsonl
      conditions.jsonl
      frames.jsonl
      plan_snapshot.json
      captures/
        cap_000001_background.jpg
        cap_000002_frame.jpg
        ...
```

Why this layout:

- consistent with the rest of the calibration system
- compatible with `tools/pull_pi_calibration_records.ps1`
- easy to replay/export later
- groups all data for one acquisition job together

## Plan Definition Format

The process should be driven by a condition plan, not only free-form UI inputs.

### Recommended First Plan Format

JSON is the easiest first format because it can carry lists and metadata without fragile CSV parsing.

Suggested file:

- `prebreakup_dataset_plan.json`

Suggested schema:

```json
{
  "schema_version": 1,
  "notes": "Initial morphology dataset acquisition",
  "default_background_policy": "per_condition",
  "conditions": [
    {
      "condition_id": "r1_pw1300_p040",
      "stock_solution": "reagent-1",
      "printer_head_id": "ph-001",
      "nozzle_id": "n1",
      "pulse_width_us": 1300,
      "pressure_psi": 0.40,
      "delay_mode": "emergence_relative",
      "delay_start_offset_us": 100,
      "delay_stop_offset_us": 2200,
      "delay_step_us": 50,
      "replicates_per_delay": 2,
      "label_key": "reagent-1_n1_pw1300",
      "notes": ""
    }
  ]
}
```

### Optional Later CSV Support

CSV can be added later if needed for spreadsheet workflows, but JSON should be the first implementation target.

## Proposed Process Flow

### High-Level State Machine

Recommended states:

1. `prepare_plan`
2. `prepare_condition`
3. `capture_background`
4. `apply_delay`
5. `capture_frame`
6. `analyze_frame` (optional, can still run even in acquisition-only mode)
7. `advance_replicate_or_delay`
8. `advance_condition`
9. `restore_settings`
10. `final`

### Condition Loop

For each condition:

1. apply pulse width and pressure
2. set `num_droplets = 0`
3. capture background
4. iterate delays
5. for each delay, iterate replicates
6. save frame + metadata + optional analysis
7. move to next condition

### Background Policy

V1 recommendation:

- capture one fresh background per condition

That is simpler and more robust than trying to share one background across many pressures or pulse widths.

## UI / Workflow Plan

### First Prototype UI

Add one new button to the calibration UI:

- `Acquire Pre-Breakup Dataset`

Minimal controls:

- plan path
- optional save format toggle (`jpg` / `png`)
- optional `run analysis online` checkbox
- optional `save overlays` checkbox

If plan-path UI is too much for the first slice, add a minimal grid UI instead:

- pulse width list
- pressure start / stop / step
- delay start / stop / step
- replicates

But the longer-term target should still be a plan-driven process.

### Readiness Requirements

Recommended prerequisites:

- nozzle center in image coordinates
- emergence time
- droplet camera available

Reuse the pattern used by `PreBreakupMorphologyCalibrationProcess`.

## Persistence Plan

### `calibration.json`

The acquisition process should still write a summary step into `calibration.json`, but the summary should stay lightweight.

Recommended result block:

- `plan_path`
- `condition_count`
- `frame_count`
- `background_count`
- `analysis_enabled`
- `run_dir`
- `conditions`
  - compact condition summaries only

Do not try to flatten the full dataset into `calibration.json`.

### Recorder Files

Use the recorder directory for the detailed data.

That is the primary analysis source.

## Labeling Workflow

The acquisition process should not own the pressure-band labels.

Recommended workflow:

1. acquire data with `PreBreakupDatasetAcquisitionProcess`
2. obtain known single-pressure bands from the existing post-ejection method
3. store those labels in a separate label table
4. join them offline to the acquired frames

This keeps acquisition neutral and avoids circular logic.

## Recommended Acquisition Campaign Structure

### Phase 1

Single reagent, single nozzle.

Pulse widths:

- `1300`
- `1400`
- `1500`
- `1600`
- `1800`

For each pulse width:

- choose a pressure grid spanning below, through, and above the known band
- run a full delay sweep at each pressure

### Phase 2

Repeat for:

- additional reagents
- additional nozzle sizes / printer heads

### Phase 3

Use offline analysis to:

- compute feature trends
- test deterministic thresholds
- simulate scout/pressure-scan logic offline

Only after that should the online calibration process be retuned again.

## Proposed Implementation Slices

### Slice 1: Smallest Viable Acquisition Process

Goal:

- one new acquisition-only process
- one pulse width
- one pressure
- one delay sweep
- recorder-backed raw frame saving

Deliverables:

- `PreBreakupDatasetAcquisitionProcess`
- start method in manager/controller/view
- `conditions.jsonl`
- `frames.jsonl`
- raw captures in recorder run directory
- summary step in `calibration.json`

No online morphology analysis required in this slice.

### Slice 2: Condition Grids

Goal:

- multiple conditions in one run
- pulse-width and pressure grids
- plan-file-driven execution

Deliverables:

- JSON plan parsing
- condition loop
- per-condition backgrounds
- full recorder metadata

### Slice 3: Online Feature Extraction

Goal:

- compute morphology metrics during acquisition for convenience

Deliverables:

- `analysis.jsonl` entries for every frame
- optional overlay saving
- per-frame metric persistence

### Slice 4: Offline Dataset Export

Goal:

- flatten recorder artifacts into analysis-ready tables

Deliverables:

- exporter under `tools/`
- join with label table
- CSV/Parquet-ready output

This slice is intentionally deferred until acquisition is working.

## Testing Plan

### Unit / Process Tests

Add focused tests for:

- plan parsing
- condition scheduling
- delay scheduling
- per-condition background capture
- frame metadata recording
- `calibration.json` summary result shape

Suggested test file:

- `tests/test_calibration_prebreakup_dataset_acquisition_process.py`

### Recorder Tests

Verify:

- run directory created correctly
- `conditions.jsonl` written
- `frames.jsonl` written
- capture metadata paths line up with actual files

### Manual Validation

First hardware checks:

1. run a single-condition acquisition
2. confirm all images are saved
3. confirm `frames.jsonl` rows match actual delays and pressures
4. confirm background frame and droplet frames are distinguishable
5. confirm the pull script copies the new run cleanly

## Risks

- storage volume may grow quickly
- acquisition time may become long for dense pressure × delay grids
- known pressure-band labels may drift over time if not acquired close to dataset capture
- reagent aging and nozzle wetting may introduce within-run nonstationarity

Mitigations:

- keep labels separate and time-stamped
- record exact run ids and capture times
- start with modest grids
- capture one background per condition

## Rollback Plan

If implementation causes workflow issues:

1. disable the new UI button
2. revert the new manager/controller start methods
3. remove the new process class
4. leave existing calibration flows unchanged

This plan does not require any firmware rollback because no firmware changes are expected.

## Progress Checklist

### Planning

- [x] Decide to create a new acquisition-only process instead of extending pre-breakup calibration
- [x] Define dataset layers: run, condition, frame, label
- [x] Define recorder-backed storage layout
- [x] Define plan-driven acquisition model

### Implementation Slice 1

- [x] Add `PreBreakupDatasetAcquisitionProcess` class
- [x] Add manager/controller/view launch path
- [x] Implement single-condition delay sweep
- [x] Save raw captures into recorder-backed run directory
- [x] Write `conditions.jsonl`
- [x] Write `frames.jsonl`
- [x] Emit compact `calibration.json` summary
- [x] Add focused process tests

### Implementation Slice 2

- [x] Add JSON plan parsing
- [x] Add multi-condition execution
- [x] Add pulse-width and pressure grid support
- [x] Add per-condition background handling

### Implementation Slice 3

- [x] Add optional online morphology analysis
- [x] Persist per-frame metrics in `analysis.jsonl`
- [x] Add optional overlay saving

### Implementation Slice 4

- [x] Add offline dataset export tool
- [x] Add label-table join support
- [x] Validate exported tables against recorder artifacts

## Recommended Next Step

Slices 1 through 4 are now in place. The next step is to use the pipeline on real acquired experiments:

- acquire multi-condition pre-breakup datasets on hardware
- pull the runs locally with `tools/pull_pi_calibration_records.ps1`
- export flat tables with the Slice 4 exporter
- join the exported frames to known pressure-band labels
- begin offline metric studies and simulated decision-logic sweeps

That is the point where we can stop guessing from a few live runs and start analyzing the full delay-pressure-pulse-width space from actual recorded data.
