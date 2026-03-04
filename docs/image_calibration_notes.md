# Droplet Imaging Calibration Notes (Updated March 4, 2026)

## Scope and Baseline
- Reviewed:
  - `FreeRTOS-interface/CalibrationClasses/Model.py`
  - `FreeRTOS-interface/CalibrationClasses/View.py`
  - `FreeRTOS-interface/Controller.py`
  - `FreeRTOS-interface/Machine_FreeRTOS.py` (capture edge-wait compatibility fix)
  - nozzle-related tests in `tests/`
- Current automated baseline:
  - `.\env\Scripts\python.exe -m pytest -q`
  - Result: `209 passed`

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
      - analyze background top-band brightness first to infer whether head is above FOV.
      - if head is not visible:
        - move down by 0.25 FOV and retry
        - cap downward recovery to 4 steps (1.0 FOV total).
      - if head is visible:
        - perform anchored X scan around start point:
          - first: move right of start (decrease X) by half FOV
          - second: move left of start (increase X) by half FOV
          - then abort with deterministic alignment error if still missing.

## Data-driven head-in-view heuristic (from Pi recordings)
- Source pulled from Pi:
  - `/home/labcraft/LabCraft_printer/FreeRTOS-interface/Experiments/Untitled-20260304_111121/calibration_recordings/NozzlePositionCalibrationProcess/`
- Examined successful runs including:
  - `run_20260304_111716_24e5f347`
  - `run_20260304_111834_bd110e6d`
  - `run_20260304_111854_2a69ca52`
- Examined failed run:
  - `run_20260304_112539_e1c3d3e3` (X scan exhausted)
- Observed metric separation in background images:
  - Successful X-scan runs: top/mid ratio about `0.24-0.44`, top-mid delta about `136-186`.
  - Failed run (all 3 backgrounds): top/mid ratio about `0.94-0.95`, top-mid delta about `13-14`.
- Implemented decision rule:
  - classify `head_not_in_view` when:
    - `top_to_mid_ratio >= 0.90` and
    - `top_mid_delta <= 25`.
  - else classify `head_in_view`.

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
- Missing-contour path may require X scans plus up to four downward recovery retries before final abort.

## Suggested Next Changes (No Code Yet, for Next Iteration)
1. Optionally restore baseline settings on completion/error (or make this behavior configurable).
2. Add detector safety guard for image shape mismatch and emit calibrated error instead of raw exception.
3. Revisit contour ranking policy with your domain intent (stream-first vs lowest-extent-first).
4. Consider ROI-first detection once a stable nozzle location is seen in this run.

## NozzleFocusCalibrationProcess: Goal, Flow, Prerequisites, Risks, and Improvements

## Goal
- Move along machine `Y` to maximize image sharpness (Tenengrad variance) for the nozzle/stream region.
- Persist a focused machine-space nozzle center (`calibration_manager.set_nozzle_center(...)`).
- Record focus trace (`focus_curve`) for debugging and later analysis.

## Current call path
1. UI: `DropletImagingDialog.toggle_start_focus_calibration(...)` in `CalibrationClasses/View.py`.
2. Controller: `Controller.start_nozzle_focus_calibration()`.
3. Model manager: `CalibrationManager.start_nozzle_focus_calibration()`.
4. Process: instantiate `NozzleFocusCalibrationProcess` and start its `QStateMachine`.
5. Capture path:
   - process calls `_capture_with_policy(...)` -> manager `captureImageRequested` -> controller `handle_capture_request` -> machine capture -> controller `_on_image_captured` callback.
6. Move path:
   - process calls `_request_move_relative_with_timeout(...)` -> manager `moveRequested` -> controller `handle_move_request` -> machine relative move -> callback.
7. Completion path:
   - process emits `nozzleFocused` -> final state emits `calibrationDataUpdated` + `calibrationCompleted`.
8. Manager handles completion/error, persists step data, updates queue/session.

## Current process state and algorithm flow
- FSM states:
  - `state_capture` -> `state_analyze` -> (`moveCompleted` back to capture, or `nozzleFocused` to final).
- Search modes inside `onAnalyze()`:
  - `probe_dir`: sample one side first (`+step`), decide direction.
  - `probe_dir_neg`: if first side not improving, try opposite side.
  - `run_up`: continue in improving direction with growing step (`STEP_GROWTH`) until decline/bound.
  - `refine`: bracket and midpoint-style refinement with oscillation guard.
- Safety controls already present:
  - move timeout guard (`_request_move_relative_with_timeout`, default 15 s).
  - local sweep span around start (`SAFE_SWEEP_STEPS`, currently +/-500 Y steps).
  - eval caps (`MAX_EVALS`, refine fallback, oscillation detection).

## Effective prerequisites (current behavior)
- Camera capture path must be active and stable.
- Machine motion on `Y` must be available and not safety-rejected.
- A useful background image should already exist in manager cache (`calibration_manager.get_background_image()`), usually from nozzle-position calibration.
- Droplet imaging settings must already be in a useful state (for example `num_droplets=1` and suitable flash delay/pressure), because focus process does not explicitly set them.
- Nozzle/stream should be within usable FOV for focus mask extraction.

## Inconsistencies and edge cases that can hinder performance

## High priority risks
1. No prerequisite gate when started from UI.
- `CalibrationManager.start_nozzle_focus_calibration()` directly instantiates the process (does not use `_try_start_process`), so `missing_requirements` cannot protect this entry point.

2. Missing/poor ROI silently degrades to full-frame focus.
- `_build_focus_mask(...)` returns `None` on many failure paths.
- `compute_tenengrad_variance(gray, mask=None)` then scores the entire frame, which can optimize background texture/noise instead of droplet/nozzle sharpness.

3. No validity gate before accepting a final focus point.
- Process can converge and write a new nozzle center even if mask quality was repeatedly poor or droplet signal was not credible.

4. Sweep bounds are local, not axis-aware.
- Focus search clamps to `[startY-500, startY+500]` but not pre-clamped to actual axis limits.
- Controller safety may reject moves near hard bounds, causing avoidable calibration aborts.

## Medium priority risks
5. Focus mask thresholds are absolute and resolution/contrast sensitive.
- Area cutoff (`>=2000 px`) and morphology parameters are fixed constants.
- Low-contrast reagents, different optics, or resolution changes can cause unstable ROI detection.

6. Multi-contour ranking is deterministic but semantically brittle.
- Lowest contour preference can still select detached droplets/reflections in some scenes.

7. Background is inherited, not captured in-process.
- Focus run recorder may not include the exact background used for masking.
- If the cached background is stale, analysis quality drops but no explicit error is raised.

8. Potential numeric robustness issue for empty mask slices.
- `np.var(G2[mask > 0])` can produce warnings/NaN if mask has no active pixels (rare but possible in malformed masks).

## Performance limitations
1. Full-frame Sobel gradients are computed each evaluation, even when a small ROI would suffice.
2. Up to `MAX_EVALS=60` image captures can be consumed before forced finish in difficult cases.
3. Retry-heavy capture policy (`attempts_total=7`) can increase wall time significantly during camera instability.

## Recommended reliability and performance changes (next implementation phase)

## Control-path changes
1. Add `NozzleFocusCalibrationProcess.missing_requirements(cm)` and enforce it on all start paths.
- Change `CalibrationManager.start_nozzle_focus_calibration()` to `_try_start_process(NozzleFocusCalibrationProcess)`.
- Requirements should include at least: camera availability, machine position read, and cached background (or explicit in-process background capture enabled).

2. Add explicit setup stage before first capture.
- Set known-safe imaging settings for focus (`num_droplets=1`, flash delay from current/nozzle baseline).
- Optionally capture a fresh background in this process for deterministic masking and recorder completeness.

3. Add validity gates.
- Require minimum count of "valid-mask" evaluations before allowing completion.
- Abort with clear actionable error if consecutive invalid-mask/no-signal frames exceed threshold.

4. Axis-aware move clamping.
- Clamp Y targets with machine/location bounds before issuing move requests, not only local +/- sweep span.

## Analysis-path changes
5. Promote mask quality to first-class status.
- Return explicit mask status (`ok`, `none`, `tiny`, `low_confidence`) and record in analysis JSONL.
- Use status to decide retry/reacquire/abort branches.

6. Use ROI-scoped focus computation.
- Compute Sobel/Tenengrad only inside padded bbox around chosen contour, with fallback expansion strategy.
- This improves both speed and resistance to irrelevant background texture.

7. Normalize contour thresholds.
- Express area/size constraints as fractions of image area/height where practical.
- Keep absolute lower bounds only as safety floor.

8. Harden metric numerics.
- Explicitly guard empty/invalid masks and NaN/inf focus values.
- Treat invalid metric as analysis failure path, not a normal score.

## Recommended tests for NozzleFocus (currently missing)
1. Start-path prerequisite tests:
- standalone focus start with missing background should fail with deterministic message.
- UI start path should honor `missing_requirements` once routed through `_try_start_process`.

2. Signal-quality gating tests:
- repeated mask failures should trigger calibrated abort, not silent full-frame optimization.
- low-signal frames should follow retry/reacquire branch and remain deterministic.

3. Motion safety tests:
- near-axis-bound start position should never command out-of-bounds Y targets.
- move rejection/timeout during focus should exit cleanly with calibration error.

4. Numeric robustness tests:
- empty/degenerate mask should not produce NaN-driven control flow.
- focus metric invalid values should be handled explicitly.

5. Performance regression tests (non-blocking benchmark):
- synthetic ROI case verifies ROI-scoped Tenengrad is faster than full-frame baseline.
- benchmark contract should record p50/p95 timing trends for focus analysis.

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
- Nozzle search strategy (X scan, multi-contour backoff, downward recovery):
  - `tests/test_calibration_nozzle_position_search_strategy.py`
- Nozzle focus contour selection regression:
  - `tests/test_calibration_focus_mask_selection.py`

## Important nozzle tests still missing
1. Shape mismatch (`bg.shape != droplet.shape`) returns controlled calibration error.
2. Candidate ranking regression tests with known stream-vs-detached-droplet ground truth.
3. Settings restore behavior at process end (if/when restore is implemented).

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
