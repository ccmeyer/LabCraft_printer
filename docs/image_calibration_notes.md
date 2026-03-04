# Droplet Imaging Calibration Analysis

## Scope
- Reviewed:
  - `FreeRTOS-interface/CalibrationClasses/Model.py`
  - `FreeRTOS-interface/CalibrationClasses/View.py`
- Baseline test run on current branch:
  - `.\env\Scripts\python.exe -m pytest -q`
  - Result: `164 passed`

## System Architecture (How It Works)

### 1) UI subsystem (`DropletImagingDialog` in `View.py`)
- Provides manual imaging controls and calibration buttons.
- Each calibration button calls a controller method (`start_*_calibration`, `stop_calibration`).
- Receives status/error/image updates from `CalibrationManager` and displays:
  - status label + stage log table
  - analyzed image previews
  - readiness-gated button enable/disable states
  - characterization summary table

### 2) Orchestration subsystem (`CalibrationManager` in `Model.py`)
- Owns process lifecycle:
  - single active process (`activeCalibration`)
  - queued run (`calibration_queue`)
  - optional pulse-width sweep orchestration across full queue reruns
- Owns persistence:
  - run envelope (`run_id`, stock, printer head, start/end timestamps)
  - per-step payload storage under `runs[].steps[phase]`
  - atomic JSON writes (`.tmp` + replace)
- Acts as async signal bus for processes:
  - `captureImageRequested(callback)`
  - `moveRequested(move, callback)`
  - `moveAbsoluteRequested(target, callback)`
  - `changeSettingsRequested(settings, callback)`
  - completion signals (`captureCompleted`, `moveCompleted`, `settingsChangeCompleted`)

### 3) Process framework (`BaseCalibrationProcess`)
- Each calibration is a `QStateMachine`.
- Shared features:
  - capture retry policy (`_capture_with_policy`)
  - timeout helpers for capture operations
  - stage text + completion/error signals
- Important limitation:
  - no built-in move timeout equivalent to capture timeout.

### 4) Computer vision subsystem (`DropletCameraModel`)
- Provides shared CV methods used by almost every process:
  - `identify_nozzle`
  - `calc_emergence_area`
  - `identify_droplet_contour`
  - `identify_droplets`
  - `characterize_droplet`
  - `compute_tenengrad_variance`
- Also provides pixel<->stage conversions through calibration matrix inverse (`A_inv`).

## Complete Runtime Flow

1. User clicks a calibration button in `DropletImagingDialog`.
2. `View` calls controller start method (`Controller.start_*`).
3. Controller calls `CalibrationManager.start_*`.
4. Manager instantiates process, wires signals, starts process state machine.
5. Process state handlers request capture/move/settings via manager signals.
6. Controller handlers execute hardware commands and call callbacks on completion.
7. Callback emits manager completion signal, driving next state transition.
8. Process emits `calibrationDataUpdated` and `calibrationCompleted` (or `calibrationError`).
9. Manager persists payload and either starts next queue item or completes.
10. View updates logs/readiness/buttons based on manager signals.

## Calibration Pipeline and Data Dependencies

Queue order in `add_all_calibrations_to_queue()`:
1. `nozzle_position`
2. `nozzle_focus`
3. `droplet_emergence`
4. `pressure_scan` (pressure band)
5. `pressure_trajectory`
6. `pressure_sweep_characterization`

Key outputs that downstream steps consume:
- Nozzle position:
  - background image
  - nozzle center (machine + image coordinates)
- Emergence:
  - emergence flash delay
- Pressure band:
  - primary pressure band
- Pressure trajectory:
  - per-pressure trajectory fit
- Sweep/search:
  - per-pressure droplet volume/cv summaries

## Major Inconsistencies

1. Phase naming drift across subsystems
- Example: `TrajectoryCalibrationProcess` uses `phase_name = "trajectory_calibration"` while aliases/readiness/queue keys use other names (`trajectory`, `droplet_trajectory`, `trajectory_pressure_scan`).
- Impact: harder to reason about persistence, readiness, and summaries; fragile integration points.

2. Duplicate/overridden methods and duplicate definitions
- `View.py` defines `_apply_previewed_droplet_volume` twice.
- `DropletCameraModel` defines `get_save_root_directory` twice.
- Impact: dead code confusion and maintenance risk.

3. Safety configuration overridden
- `PressureBandCalibrationProcess` constructor takes `auto_stop_on_nozzle_wet` but sets `self.auto_stop_on_nozzle_wet = False` unconditionally.
- Impact: configured safety behavior is silently disabled.

4. Manager process-start behavior can instantiate process just to read phase
- `_try_start_process` computes `phase_name` by potentially constructing `proc_cls(self, self.model)` even when checking prerequisites.
- Impact: avoidable side effects/exceptions during readiness checks.

5. Mixed semantics in settings snapshots vs apply keys
- Persistence snapshots use `print_width`; settings apply uses `print_pulse_width`.
- Works in many places but is easy to break and causes key translation overhead.

## Vulnerabilities and Unintended-Action Risks

### High
1. No process-level absolute movement bounds in `NozzlePositionCalibrationProcess`
- It clamps per-move delta but does not clamp absolute XYZ targets.
- Repeated recenter attempts can drift outside intended imaging chamber if global boundaries are loose/misconfigured.

2. Recenter abort check occurs after move dispatch in nozzle-position logic
- `_recenter_iters` is incremented and move requested before limit check abort.
- One extra unsafe move can happen before stopping.

3. Move failure can stall state machines indefinitely
- Processes often wait on `moveCompleted`, but base class has no move timeout.
- Controller move handlers do not guarantee callback on blocked/collision returns.
- Result: hangs mid-calibration with partial settings/motion state.

4. Manual droplet characterization can raise runtime error when contour exists
- In `DropletSearchCalibrationProcess.onAnalyze`, analysis record uses `x,y,w,h` before assignment when contour is present and saving is enabled.
- This path is active in manual characterization mode.

### Medium
5. Focus contour selection bug
- `NozzleFocusCalibrationProcess._build_focus_mask` sorts candidates, then overwrites chosen contour with unsorted first item.
- Can cause unstable/incorrect focus behavior and extra moves.

6. Trajectory/search offset update references wrong attributes
- `DropletSearchCalibrationProcess._update_xz_track_offset` uses undefined method/fields (`_predict_target_xyz`, `vec_steps_per_s`), then swallows exceptions.
- Feature silently does not work.

7. Timecourse start uses wrong manager attribute
- `DropletTimecourseProcess.start` references `self.manager` instead of `self.calibration_manager` (caught by fallback).
- Behavior becomes implicit and less predictable.

## Fragility Drivers (CV and Control)

1. Hard-coded thresholds dominate many detectors
- Examples: binary threshold `60`, contour area `>1000/2000`, fixed ROI fractions, shape ratio cutoffs.
- Sensitive to illumination drift, focus drift, background texture, reagent appearance.

2. Mixed detector paradigms across steps
- Some steps use dark-only diff, others absolute diff.
- Different steps can disagree on the same frame condition.

3. Contour rejection can be overly strict
- `identify_nozzle` rejects multiple large contours entirely.
- `characterize_droplet` treats multiple contours as `"Multiple"` and may repeatedly retest pressure.

4. Retry loops are capped but still expensive in worst-case failure
- Multiple nested loops (capture retries, delay sweeps, pressure nudges, recenter/focus loops) cause slow recovery from bad conditions.

## Efficiency/Performance Opportunities (Low-Risk)

1. Reduce expensive recapture loops where confidence is already high
- Current defaults are large in some paths (`num_images=100` in droplet search, high per-pressure replicate counts in sweep).
- Add early-stop criteria based on stable rolling mean/CV and center variance.

2. Reuse/crop ROI aggressively
- Most detectors can start from predicted region or prior center and only expand when detection confidence drops.
- This reduces full-frame threshold/contour cost.

3. Standardize detector core
- Consolidate to one robust dark-droplet detector with parameter profile per step.
- Fewer divergent failure modes and easier tuning.

4. Batch settings changes with explicit completion contract
- Current key-by-key callback chaining adds latency and possible ordering assumptions.
- A single transactional “apply settings + ack” call would reduce jitter and complexity.

5. Add move timeouts matching capture timeouts
- Prevent long stalls and improve recovery speed when motion callbacks do not arrive.

## Recommended Validation Tests

### A) Safety-critical state machine tests
1. `NozzlePosition` movement-bound test
- Inject large pixel offset repeatedly.
- Verify emitted moves never exceed configured XYZ bounds.

2. Move-callback-loss timeout test
- Simulate blocked move (collision fail/no callback).
- Expect deterministic error within timeout (no hang).

3. Pressure safety stop tests
- For pressure scan:
  - droplet too close after first sample -> early terminate.
  - nozzle wet -> terminate when safety flag enabled.

### B) CV robustness tests (synthetic image fixtures)
4. Nozzle detector with:
- low contrast, dual bright blobs, edge-touching contours, dark noise.
- Ensure deterministic status (`OK/NONE/NO_SIGNAL`) and stable point selection.

5. Emergence detector ROI stress
- Shift droplet around ROI boundaries, brightness shifts, weak droplets.
- Verify bounded delay progression and proper convergence/failure.

6. Focus mask contour-choice regression
- Two valid contours where lower one should win.
- Verify selected contour remains stable.

### C) Integration tests with fake controller/machine
7. Full queue happy path with deterministic fake frames
- Ensure stage ordering, persistence payload shape, readiness transitions.

8. Queue abort path
- Induce error at each stage and verify:
  - active process stops
  - queue clears
  - no stale callbacks continue motion/capture.

9. Manual characterization runtime safety
- Enable save mode with valid contour sequence.
- Ensure no runtime exception in analysis-record path.

### D) Performance regression tests
10. Per-frame CV budget
- Benchmark `identify_droplets`, `characterize_droplet`, `calc_emergence_area` at camera resolution.
- Track p50/p95 timing in CI.

11. End-to-end cycle budget
- For representative good-condition runs, assert max frame count and wall-time by step.

## Priority Fix Order

1. Add move timeout + guaranteed callback behavior on move rejection.
2. Add absolute movement clamps to nozzle-position search path.
3. Fix manual characterization runtime bug (`x,y,w,h` usage before assignment).
4. Fix focus contour selection overwrite bug.
5. Re-enable/obey nozzle-wet safety option in pressure scan.
6. Normalize phase/readiness key naming across manager/process/view.
7. Add the safety + CV robustness tests above before broader algorithm tuning.

## Recorder + Verdict + Replay Workflow

### Runtime Recorder
- `CalibrationManager` now supports per-process recorder runs under:
  - `<experiment_dir>/calibration_recordings/<ProcessClassName>/<run_id>/`
- Recorded artifacts:
  - `run_meta.json` (run envelope + start/end + outcome)
  - `events.jsonl` (state/move/settings/capture/decision/error timeline)
  - `analysis.jsonl` (structured process analysis payloads)
  - `captures/` (raw captured images)
  - `verdict.json` (operator outcome + notes)

### Verdict Capture
- At process completion/error, `DropletImagingDialog` prompts for an operator verdict.
- Verdict fields:
  - outcome (`success` / `failed` / `unknown`)
  - failure summary
  - suspected cause
  - notes
- Verdict is written to the latest recorder run and echoed as a recorder event.

### Offline Replay
- Utility:
  - `tools/replay_calibration_run.py`
- Current scope:
  - Replays `NozzlePositionCalibrationProcess` detection status from recorded background/droplet image pairs.
- Usage:
  - Single run: `python tools/replay_calibration_run.py --run-dir <run_dir>`
  - Batch root: `python tools/replay_calibration_run.py --root <calibration_recordings_root>`
- Output:
  - JSON report with matched/mismatched/skipped counts plus per-case details.
