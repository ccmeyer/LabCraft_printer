# Droplet Imaging Calibration Notes (Updated March 3, 2026)

## Scope and Baseline
- Reviewed:
  - `FreeRTOS-interface/CalibrationClasses/Model.py`
  - `FreeRTOS-interface/CalibrationClasses/View.py`
  - `FreeRTOS-interface/Controller.py`
  - `FreeRTOS-interface/Machine_FreeRTOS.py` (capture edge-wait compatibility fix)
  - nozzle-related tests in `tests/`
- Current automated baseline:
  - `.\env\Scripts\python.exe -m pytest -q`
  - Result: `198 passed`

## What Has Already Been Implemented and Addressed

### Motion safety and determinism
- Added guarded move helpers in `BaseCalibrationProcess`:
  - `_request_move_relative_with_timeout(...)`
  - `_request_move_absolute_with_timeout(...)`
- Effect:
  - calibration FSMs no longer wait forever when move completion callbacks are missing.
  - timed-out moves now emit calibration errors deterministically.
- Controller move handlers now emit calibration errors when moves are rejected or fail:
  - `Controller.handle_move_request`
  - `Controller.handle_absolute_move_request`

### Nozzle recenter hard bounds
- `NozzlePositionCalibrationProcess` now clamps both:
  - per-step move magnitude (`_clamp_move`)
  - absolute XYZ target (`_clamp_abs_target`) using axis bounds -> location bounds -> fallback span.
- Iteration cap is checked before issuing the next recenter move.
- Recenter now aborts with explicit calibration error if:
  - max iterations reached
  - clamped move collapses to `(0,0,0)` at bounds.

### Correctness fixes already landed
- `DropletSearchCalibrationProcess.onAnalyze`: fixed undefined `x,y,w,h` path in save-enabled analysis.
- `NozzleFocusCalibrationProcess._build_focus_mask`: fixed contour selection overwrite.
- `DropletTimecourseProcess.start`: fixed manager reference path.
- Removed duplicate method definitions:
  - duplicate `_apply_previewed_droplet_volume` in `View.py`
  - duplicate `get_save_root_directory` in `DropletCameraModel`
- Pressure scan now honors constructor `auto_stop_on_nozzle_wet`.

### Phase naming consistency
- Canonical trajectory key is now `trajectory`.
- Backward alias path for legacy `trajectory_calibration` is maintained in `CalibrationManager.PHASE_ALIASES` and alias-aware read paths.

### Recorder + verdict + replay
- Added per-process recorder (`CalibrationProcessRecorder`) with:
  - `run_meta.json`, `events.jsonl`, `analysis.jsonl`, raw `captures/`, optional `verdict.json`
- Added end-of-run verdict dialog in calibration UI.
- Added offline replay utility:
  - `tools/replay_calibration_run.py`
  - currently supports replaying nozzle-position detection outcomes.

### Dataset capture tooling for nozzle process
- Added dedicated `NozzlePositionDatasetCaptureWindow` and checklist store.
- Checklist location:
  - `FreeRTOS-interface/CalibrationClasses/test_images/NozzlePositionCalibrationProcess/`
- Implemented:
  - atomic case manifest (`checklist_manifest.v1.json`)
  - tooltips for each checklist row
  - paired capture mode (`Capture Background + Droplet`)
  - pair metadata (`pair_id`, role/order, subtract-background links)
  - preview-only capture (no save)
  - reject-last capture flow (marks capture rejected; does not delete old images)
  - movement shortcuts and focus behavior fixes
  - camera cleanup safeguards on close, plus reuse of already-connected camera session when possible.

### Capture error fix that was observed during checklist use
- Resolved float timeout compatibility issue in camera edge-wait path by adding `_wait_edge_events_compat(...)` in `Machine_FreeRTOS.py`.
- This prevents repeated failures like float-to-int timeout signature mismatches while waiting for flash-fired edge events.

## NozzlePositionCalibrationProcess: Goal and Intended Outcome

## Goal
- Find the nozzle image position robustly from a background/droplet pair.
- Recenter the machine so the nozzle is near image top-center.
- Persist:
  - background image for downstream subtraction
  - nozzle center in image coordinates
  - nozzle center in machine coordinates

## Success criteria
- Detector returns `status == "OK"`.
- Nozzle point is inside configured top-center tolerance:
  - x within `center_tol_frac * width`
  - y within `top_band_frac * height` around `top_margin_frac * height`.

## Failure criteria
- Recenter iteration cap reached.
- Recenter target clamps to zero move at bounds.
- Capture retries exhausted.
- Move request fails or move callback timeout fires.
- Delay/pressure scan options exhausted without valid detection.

## Process Call Path and State Flow

## Call path
1. UI starts nozzle-position calibration.
2. Controller calls `CalibrationManager.start_nozzle_calibration()`.
3. Manager instantiates `NozzlePositionCalibrationProcess` and starts its state machine.
4. Process requests motion/settings/capture via manager signals.
5. Controller executes hardware action and returns via callback.
6. Manager emits completion signal, driving state transitions.
7. Process emits completion or error, manager persists step result and updates queue flow.

## FSM states (high-level)
1. `state_initial_position`
2. `state_prepare_background`
3. `state_capture_background`
4. `state_prepare_droplet`
5. `state_capture_droplet`
6. `state_analyze`
7. `state_final`

## Core analyze loop behavior
1. If warm-up throwaway is pending:
   - discard current droplet frame
   - request re-capture with same settings.
2. Run `_detect_nozzle_point(background, droplet)`:
   - returns `status in {"OK", "NONE", "NO_SIGNAL"}` plus nozzle point and debug overlay.
3. Branch by status:
   - `OK`:
     - if multiple contours, decrement flash delay by 200 us (floor 2000 us) and re-capture.
     - if single contour, attempt `_recenter_or_finish(nozzle_px)`.
   - `NO_SIGNAL` and `NONE`:
     - treat as likely out-of-FOV condition.
     - perform anchored X scan around start point:
       - first: move right of start (decrease X) by half FOV
       - second: move left of start (increase X) by half FOV
       - then: abort with deterministic error if still missing.

## Detection algorithm used today
- Input: absolute difference `abs(droplet - background)`.
- Preprocessing: Gaussian blur.
- Thresholding: fixed threshold (`fixed_thresh_value`, default 30), not Otsu.
- No-signal gate: reject as `NO_SIGNAL` if foreground pixel count below `no_signal_min_fg_px`.
- Morphology: open then close with 3x3 ellipse.
- Contour filtering:
  - area >= 2000
  - bbox height >= `min_stream_bbox_h_px`
  - contour top inside top search band (`search_top_band_frac`).
- Candidate ranking:
  - choose contour with highest bottom y, tie-break by larger area.
- Nozzle point:
  - x = bbox midpoint
  - y = contour top.

## Current Strengths
- Move timeout guards prevent deadlocks from missing callbacks.
- Recenter now constrained by absolute axis bounds.
- Analyze path emits structured recorder events and analysis payloads, which improves debugging and replay.
- Explicit status classes (`OK`, `NONE`, `NO_SIGNAL`) make branch behavior observable.

## Remaining Risks and Edge Cases (Open Items)

## High priority
1. No explicit settings restore on completion/error.
- Process changes `num_droplets` and `flash_delay`.
- It does not explicitly restore prior settings at the end.
- Risk: later manual actions/calibrations may start from unintended settings.

## Medium priority
2. Candidate ranking may select detached droplet over stream in some multi-contour frames.
- Current rule prefers contour with largest bottom y.
- This is deterministic, but may conflict with "true nozzle anchor" intent in some scenes.

3. Fixed thresholds and hard contour area limits are not resolution-normalized.
- `fixed_thresh_value=30`, `area>=2000`, `min_stream_bbox_h_px=10`.
- Risk: sensitivity shifts with lighting, reagent appearance, optics drift, or resolution changes.

4. Multi-contour branch can still terminate if detached droplet persists at delay floor.
- This is intentional fail-fast behavior.
- Risk: operator intervention required for unstable ejection/nozzle conditions.

## Lower priority
5. `_axis_bounds` fallback can still be broad if machine/location bounds are unavailable.
- Fallback span is conservative but synthetic (`_default_axis_spans`).
- Risk: acceptable as fail-safe, but not as robust as true machine bounds.

6. No explicit shape compatibility check before `cv2.absdiff`.
- If background and droplet shapes mismatch, OpenCV raises.
- This should be turned into deterministic calibration error with recorded context.

## Performance Bottlenecks in Current Nozzle Process
- Warm-up discard adds an extra droplet capture per scan start and after delay/backoff adjustments.
- Full-frame threshold + contour pass is run for each analyze cycle.
- Every successful recenter move returns to recapture background and restart droplet prep sequence.
- Missing-contour path may require two additional X-scan relocations before abort.

## Suggested Next Changes (No Code Yet, for Next Iteration)
1. Optionally restore baseline settings on completion/error (or make this behavior configurable).
2. Add detector safety guard for image shape mismatch and emit calibrated error instead of raw exception.
3. Revisit contour ranking policy with your domain intent (stream-first vs lowest-extent-first).
4. Consider ROI-first detection once a stable nozzle location is seen in this run.

## Validation Coverage Status

## Already covered by automated tests
- Move timeout behavior:
  - `tests/test_calibration_move_timeouts.py`
- Controller move rejection/exception routing:
  - `tests/test_controller_calibration_move_handlers.py`
- Nozzle recenter safety bounds and iteration cap ordering:
  - `tests/test_calibration_nozzle_position_safety.py`
- CV edge-case determinism in shared camera model:
  - `tests/test_calibration_cv_edge_cases.py`
- Checklist manifest and store behavior:
  - `tests/test_nozzle_position_checklist_manifest.py`
  - `tests/test_nozzle_position_checklist_store.py`
- Recorder/verdict/replay contracts:
  - `tests/test_calibration_process_recorder.py`
  - `tests/test_calibration_verdict_dialog.py`
  - `tests/test_replay_nozzle_position.py`

## Important nozzle tests still missing
1. Anchored X-scan path is deterministic for both `NONE` and `NO_SIGNAL` statuses.
2. Multi-contour delay backoff decrements by 200 us and honors 2000 us floor.
3. Shape mismatch (`bg.shape != droplet.shape`) returns controlled calibration error.
4. Candidate ranking regression tests with known stream-vs-detached-droplet ground truth.
5. Settings restore behavior at process end (if/when restore is implemented).

## Data Collection and Replay Assets (Current State)
- Atomic-case checklist manifest for nozzle process:
  - 17 single-step edge cases
  - required minimum replicates per case: background 1, droplet 3
- Capture storage root:
  - `./FreeRTOS-interface/CalibrationClasses/test_images/NozzlePositionCalibrationProcess/`
- Pairing fields for subtractability:
  - `pair_id`, `pair_role`, `pair_order`
  - `subtract_background_record_id`, `subtract_background_image_relpath`
- Offline replay path:
  - `python tools/replay_calibration_run.py --run-dir <run_dir>`
  - `python tools/replay_calibration_run.py --root <calibration_recordings_root>`
