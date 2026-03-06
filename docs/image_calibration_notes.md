# Droplet Imaging Calibration Notes (Updated March 5, 2026)

## Scope and Baseline
- Reviewed:
  - `FreeRTOS-interface/CalibrationClasses/Model.py`
  - `FreeRTOS-interface/CalibrationClasses/View.py`
  - `FreeRTOS-interface/Controller.py`
  - `FreeRTOS-interface/Machine_FreeRTOS.py` (capture edge-wait compatibility fix)
  - calibration-related tests in `tests/`
- Current automated baseline:
  - `.\env\Scripts\python.exe -m pytest -q`
  - Result: `217 passed`

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
1. Background quality can still vary between runs.
- Focus process now has prerequisite gating and quality checks, but still depends on the provided background quality and stream visibility.

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

## DropletEmergenceCalibrationProcess: Goal, Flow, Prerequisites, Risks, and Improvements

## Goal
- Estimate a robust emergence-time flash delay where the ejected fluid stream is visible but not fully detached.
- Persist the selected delay (`result.flash_delay`) for downstream pressure/trajectory/characterization processes.
- Present a live emergence overlay to the operator while scanning.

## Current call path
1. UI: `DropletImagingDialog.toggle_start_emergence_calibration(...)`.
2. Controller: `Controller.start_droplet_emergence_calibration()`.
3. Model manager: `CalibrationManager.start_droplet_emergence_calibration()`.
4. Process: instantiate `DropletEmergenceCalibrationProcess` and start its `QStateMachine`.
5. Capture/settings path:
   - process emits `changeSettingsRequested` and `captureImageRequested`;
   - controller applies settings and triggers camera capture callbacks;
   - manager emits `settingsChangeCompleted` / `captureCompleted`.
6. Analyze path:
   - process calls `DropletCameraModel.calc_emergence_area(background, droplet)`;
   - updates search phase and next delay;
   - emits `continueSearch`, `replicateContinue`, or `dropletDetected`.

## Current process state and algorithm flow
- FSM states:
  - `state_prepare_background`
  - `state_capture_background`
  - `state_set_delay`
  - `state_capture_droplet`
  - `state_analyze`
  - `state_final`
- Capture strategy:
  - capture one background (`num_droplets=0`);
  - at each candidate delay, capture `REPLICATES=3` droplet frames (`num_droplets=1`);
  - aggregate by median area per delay.
- Search phases:
  1. `seek_visible`:
     - if aggregate area is tiny, increase delay by `BIG_JUMP_US` (default 800 us);
     - else switch to `scan_down`.
  2. `scan_down`:
     - decrease delay by `COARSE_STEP` (500 us) while area is too high;
     - if area falls below window, switch to `fine_adjust`.
  3. `fine_adjust`:
     - adjust by `FINE_STEP` (100 us) until area enters `[MIN_AREA, MAX_AREA]`.
- Success:
  - emits completion with selected `flash_delay`;
  - updates manager nozzle image position to detected center.
- Failure:
  - max delay exceeded without visibility;
  - max evaluations exceeded in scan/fine phases.

## Detection algorithm currently used (`calc_emergence_area`)
- Uses dark-only subtraction (`background - image`) to emphasize darker fluid.
- Restricts analysis to a fixed top-center ROI:
  - `roi_top_frac=0.06`, `roi_bottom_frac=0.55`,
  - `roi_x_center_frac=0.50`, `roi_x_half_frac=0.18`.
- Thresholding:
  - mean+2.5 sigma first, fallback to Otsu.
- Morphology:
  - open then close with 3x3 kernel.
- Candidate selection:
  - keep contours above `min_contour_area`;
  - choose contour with largest bottom-y then largest area;
  - output bounding-box area (`w*h`) and bbox center.

## Effective prerequisites (expected vs enforced)
- Expected by process intent:
  - nozzle is already near top-center FOV from nozzle-position calibration;
  - nozzle/stream is in acceptable focus from focus calibration;
  - droplet print settings are in a plausible range (pressure/pulse width).
- Currently enforced by code:
  - none via `missing_requirements` (not implemented for this process).
- Start-path behavior:
  - `CalibrationManager.start_droplet_emergence_calibration()` currently instantiates directly (no `_try_start_process` gate).

## Inconsistencies and edge cases that can hinder performance

## High priority risks
1. No explicit prerequisite gate.
- Emergence can be started when nozzle is not centered/in focus, leading to avoidable scan failures and slow retries.

2. Fixed ROI is not anchored to calibrated nozzle location.
- Detector uses fixed top-center fractions instead of `nozzle_center_image_position`.
- If nozzle drifts in X/Y, emergence may be missed even when physically present.

3. Candidate ranking can prefer detached droplet instead of attached stream.
- Current key uses bottom-most contour first; detached droplets lower in image can dominate.
- This can bias delay selection toward detached states.

4. Success path overwrites nozzle center image position using emergence bbox center.
- `set_nozzle_center_image_position(center)` is called on success.
- Emergence center is not guaranteed to be the nozzle tip; downstream processes may inherit shifted reference.

5. Area metric is bounding-box area (`w*h`) with fixed absolute window.
- Sensitive to contour orientation/reflections and camera scale.
- Hard thresholds (`MIN_AREA=3000`, `MAX_AREA=8000`) are not normalized.

## Medium priority risks
6. No monotonic/consistency guard despite existing hook.
- Monotonic check code is present but commented out.
- Non-monotonic area noise can cause oscillation or wrong convergence.

7. No explicit settings restore at process end/error.
- Process modifies `num_droplets` and `flash_delay`.
- It does not restore prior user settings automatically.

8. No settings-change timeout guard.
- Uses direct `changeSettingsRequested.emit(...)` transitions.
- Missing callback/ack can leave FSM waiting indefinitely.

9. Limited persisted diagnostics for postmortem.
- Final result stores only `flash_delay`; per-delay confidence/quality is not persisted in calibration result.

## Performance bottlenecks
1. Mandatory 3 replicates at every candidate delay can be expensive in stable conditions.
2. Visibility search uses large jumps then full replicate batches; misses can consume many captures before fail.
3. Recorder capture writes (when recorder enabled) add synchronous disk cost per frame.

## Recommended reliability and performance changes (next implementation phase)

## Control-path changes
1. Add `DropletEmergenceCalibrationProcess.missing_requirements(cm)` and start via `_try_start_process(...)`.
- Require at least: nozzle-center image position, recent background/nozzle calibration context, camera readiness.

2. Anchor ROI to calibrated nozzle center.
- Use `cm.get_nozzle_center_image_position()` as ROI center and row reference.
- Keep fallback to top-center only when calibration center unavailable.

3. Add settings timeout wrapper for phase transitions.
- Use a guarded settings helper (similar move timeout pattern) to prevent indefinite waits.

4. Preserve or optionally restore original imaging settings at completion/error.
- Restore `num_droplets` and `flash_delay` unless explicitly disabled.

## Analysis-path changes
5. Replace bbox area as primary target metric.
- Prefer contour area and/or nozzle-anchored vertical extent near the nozzle.
- Keep bbox metrics as secondary diagnostics.

6. Add contour classification to prefer attached stream.
- Rank by proximity/overlap to nozzle row before bottom-most extent.
- Down-rank free detached droplets for emergence timing.

7. Reinstate robust monotonic guard with tolerance band.
- If area trend is non-physical across decreasing delays, treat as noise and branch deterministically.

8. Emit confidence diagnostics with result.
- Store selected-delay quality payload:
  - replicate areas, contour class, signal strength (`p95`), and decision phase.

## Performance changes
9. Adaptive replicate count.
- Use minimum replicates (e.g., 2) and stop early when area variance is below threshold.
- Escalate to 3+ only in noisy/ambiguous frames.

10. Two-stage search scheduling.
- coarse visibility pass with single-replicate probes,
- then replicate-confirm only near candidate window.

## Recommended tests for DropletEmergence (currently missing)
1. Start-path prerequisite tests:
- starting emergence with missing nozzle-center context should fail fast with clear message.

2. Detector classification tests:
- attached-stream vs detached-droplet multi-contour frames should select expected contour class.

3. ROI anchoring tests:
- nozzle shifted in X/Y should still detect emergence when anchored ROI is used.

4. Trend/branch determinism tests:
- non-monotonic synthetic sequences should follow defined recovery path.

5. Bounds and timeout tests:
- delay bounds (`DELAY_MIN/DELAY_MAX`) and max-eval exits should be deterministic;
- missing settings-completion callback should not hang FSM.

6. Regression tests for center reference integrity:
- emergence completion must not corrupt nozzle tip reference unless explicitly intended.

## PressureTrajectoryCalibrationProcess: Goal, Flow, Prerequisites, Risks, and Improvements

## Goal
- Measure droplet trajectory as a per-pressure velocity fit (`vx_px_per_us`, `vy_px_per_us`) for downstream pressure sweep planning.
- Capture enough timepoints per pressure to fit a stable line `center(t)` while handling edge-of-FOV conditions.
- Persist result payload through `CalibrationManager.set_pressure_trajectory_result(...)`.

## Current call path
1. UI: `DropletImagingDialog.toggle_start_pressure_trajectory_calibration(...)`.
2. Controller: `Controller.start_pressure_trajectory_calibration()`.
3. Manager: `CalibrationManager.start_pressure_trajectory_calibration()` -> `_try_start_process(PressureTrajectoryCalibrationProcess)`.
4. Process FSM:
   - `state_prepare_bg` -> `state_apply` -> (`state_capture` <-> `state_analyze` <-> `state_decide` / `state_set_delay`) -> `state_final`.
5. Settings/capture execution:
   - process emits `changeSettingsRequested` and `captureImageRequested`;
   - controller/machine callbacks drive `settingsChangeCompleted` / `captureCompleted`.

## Current algorithm flow
1. Build pressure set:
- If no explicit pressures are passed, use primary band `[lo, mid, hi]`.
- Else use provided list.

2. Build delay set:
- Default delays are `emergence_time + pulse_width + 1500 us` with 700 us spacing (3 points).

3. Per-pressure loop:
- Apply pressure + initial delay.
- Capture replicate frames per delay (default 3, median center used).
- If no/failed detections exceed cap: mark delay skipped.
- If edge-of-FOV is hit: stop exploring later delays and insert earlier/mid delays to reach `min_points`.
- If multiple droplets: reduce pressure by 0.01 psi and restart same pressure slot.
- If weak/reversing radial motion: increase pressure by 0.01 psi and restart same pressure slot.

4. Fit and persist:
- If enough points (`>= min_points`), fit `(vx, vy)` by least squares.
- Append per-pressure fit (or `fit=None` if insufficient points).
- Final state emits `set_pressure_trajectory_result(...)`.

## Enforced prerequisites (today)
- `Nozzle center (machine coords)`
- `Nozzle center (image coords)`
- `Background image`
- `Emergence time`
- `Primary pressure band`

## Key inconsistencies, vulnerabilities, and edge cases

## High priority
1. Settings transitions are not timeout-guarded.
- `onPrepare`, `onApplyPressure`, and `onSetDelay` emit settings requests directly (no timeout helper), so missing callbacks can stall FSM progress.

2. Pressure adjustment loop guard is effectively disabled.
- `_restart_current_pressure_with(...)` increments `_adjust_attempts_at_pressure`, but later resets it to `0` before reapply, so repeated adjust loops can continue far longer than intended.

3. Process can complete with zero valid fits.
- Completion always emits success payload even when all pressure entries have `fit=None`; downstream sweep then fails later with poorer operator feedback.

4. Delay plan mutates globally across pressures.
- Earlier/mid delay insertion modifies `self.delays_us` permanently; later pressures inherit expanded delay lists, increasing runtime and changing behavior pressure-to-pressure.

5. Multiple-droplet branch triggers on any single frame.
- A single noisy multi-contour frame can force immediate pressure decrement/restart, with no replicate consensus check.

## Medium priority
6. Stream-like single discrimination is not used in this process.
- `identify_droplets(...)` supports rich details (`is_stream_like`, aspect, circularity), but trajectory process calls it without `return_details=True`; elongated stream cases can be misinterpreted as clean singles.

7. Primary band requirement is unconditional.
- Even if explicit `pressures` are provided by caller, `missing_requirements` still requires a primary band.

8. Default `[lo, mid, hi]` pressure set is not deduplicated.
- Narrow bands can create duplicate pressures after rounding, wasting captures and reducing information value.

9. Band is modified during trajectory adjustment.
- `_restart_current_pressure_with(...)` attempts to update manager primary band in-process; this side effect can narrow/widen later planning unexpectedly.

10. Fixed spatial thresholds are resolution-dependent.
- `edge_guard_px=200`, `min_area=900`, and related constants are not normalized by image size/nozzle scale.

## Lower priority
11. Unused state fields indicate incomplete logic paths.
- `_saw_multiple_this_pressure` and `_edge_close_now` are set but not consumed for decisions.

12. `num_droplets=0` prepare stage does not recapture background.
- Process relies on cached background and still incurs a settings step; this can add latency without new image quality assurance.

## Recommended reliability and performance changes

## Control-path changes
1. Wrap all settings requests with timeout/recording helper.
- Use `_request_settings_with_recording(...)` plus timeout handling in `onPrepare`, `onApplyPressure`, and `onSetDelay`.

2. Fix adjustment-attempt guard semantics.
- Track attempts per pressure slot without resetting on each restart.
- Hard-fail or skip slot deterministically once cap is reached.

3. Do not emit success when no usable fit exists.
- Require at least one valid fit for process success; otherwise emit calibration error with per-pressure diagnostics.

4. Make primary-band requirement conditional.
- If explicit `pressures` are supplied, allow start without primary band.

5. Remove in-loop band mutation side effects.
- Keep trajectory pressure adjustments local; update primary band only through a clearly scoped policy at process end (or not at all).

## Analysis-path changes
6. Enable `identify_droplets(..., return_details=True)` and apply quality gates.
- Reject or down-rank stream-like singles.
- Require replicate consensus before triggering pressure adjust (`multiple` or `low_pressure_retraction`).

7. Preserve per-pressure delay plans.
- Keep immutable base delays and clone per pressure; do not carry inserted delays across pressure slots.

8. Add fit quality metrics.
- Persist residual error/R^2 and mark low-confidence fits.
- Use confidence thresholds before accepting fit for downstream interpolation.

9. Normalize key thresholds.
- Scale edge guard and min-area gates with image dimensions and expected droplet size.

## Performance changes
10. Reduce unnecessary restarts and captures.
- Require 2-of-3 replicate evidence before pressure restart.
- Early-stop delay probing when fit confidence is already above threshold.
- Deduplicate pressure list before scan.

## Recommended tests (currently missing)
1. Start-path requirements:
- explicit pressures with no primary band should be allowed.
- missing required prerequisites should fail with deterministic message.

2. Settings timeout safety:
- missing `settingsChangeCompleted` callback should emit error, not hang.

3. Adjustment loop guard:
- repeated `multiple` or `retraction` conditions must stop at configured attempt cap.

4. Delay-plan isolation:
- inserted delays at pressure A should not alter delay schedule at pressure B.

5. Fit validity contract:
- process should error when no pressure yields a valid fit.

6. Stream/auxiliary classification:
- stream-like single frames should not be treated as clean trajectory points without confirmation.

## PressureSweepCharacterizationProcess: Goal, Flow, Prerequisites, Risks, and Improvements

## Goal
- Characterize droplet volume repeatability across a pressure set derived from trajectory and pressure-band results.
- For each pressure, predict droplet location from trajectory velocity, move there, then center/focus and collect replicate volume measurements.
- Persist per-pressure records used by the summary table and final pressure selection.

## Current call path
1. UI: `DropletImagingDialog.toggle_start_pressure_sweep_calibration(...)`.
2. Controller: `Controller.start_pressure_sweep_characterization()`.
3. Manager: `CalibrationManager.start_pressure_sweep_characterization()` -> `_try_start_process(PressureSweepCharacterizationProcess, ...)`.
4. Process FSM:
- `state_pick` -> `state_applyP` -> `state_move` -> `state_prepBG` -> `state_capBG` -> `state_setDelay` -> `state_capture` -> `state_analyze` -> `state_center` -> `state_char` -> `state_anBatch` -> `state_final`.
5. Settings/capture/move execution:
- process emits `changeSettingsRequested`, `captureImageRequested`, and move requests;
- controller/machine callbacks drive `settingsChangeCompleted`, `captureCompleted`, and move completion.
6. Persistence path:
- process emits incremental `calibrationDataUpdated` payloads per pressure;
- manager appends steps and updates summary rows.

## Current algorithm flow
1. Build pressure plan:
- use primary pressure band when available, else use min/max of trajectory-tested pressures;
- build count-based pressure grid with minimum separation;
- interpolate `vx, vy` for each pressure from trajectory fit points.

2. For each pressure:
- apply pressure (`print_pressure`) and prep background (`num_droplets=0`);
- predict target XYZ at `emergence_time + sphere_delay` using interpolated velocity;
- apply persistent X/Z tracking offset and Y focus offset;
- move to predicted target and capture background.

3. Search for droplet at this pressure:
- set droplet capture settings (`flash_delay`, `num_droplets=1`);
- capture/analyze using `identify_droplet_contour(...)`;
- if not found, sweep delay offsets `[0, +500, -500, +1000, -1000, +1500, -1500]`;
- if sweep exhausted, perform up to 2 half-frame-up probes, then nudge along trajectory;
- if repeated search failures exceed cap, mark pressure invalid and advance.

4. Centering:
- when contour found, center to image center with clamped X/Z moves;
- guard with recenter and out-of-bounds limits.

5. Characterization loop:
- run `characterize_droplet(...)` on each replicate frame;
- enforce center-first policy before focus moves;
- if focus below threshold, move Y and recapture;
- accept replicate when focus passes threshold and store volume/circularity/focus/center;
- early-stop when rolling mean/CV drift converges.

6. Batch decision:
- keep only replicates with `circularity_ellipse < threshold`;
- if enough good replicates, mark valid and store mean volume, CV, and machine-space center;
- otherwise mark invalid and advance to next pressure.

## Enforced prerequisites (today)
- `Nozzle center (machine coords)` via `cm.get_nozzle_center()`.
- `Nozzle center (image coords)` via `cm.get_nozzle_center_image_position()`.
- `Background image`.
- `Emergence time`.
- `Pressure trajectory scan results`.

## Effective prerequisites (operational)
- Trajectory fits must be physically meaningful (not sparse/noisy) so interpolation predicts usable targets.
- Pressure band or trajectory pressure range must cover at least one stable single-droplet regime.
- Camera capture and stage motion callback paths must be stable.

## Key risks and edge cases

## High priority
1. Nozzle reference source mismatch.
- Sweep still uses `get_nozzle_center_image_position()` instead of the emergence-derived real nozzle center path.
- Risk: attached/near-nozzle classification and centering can be biased when legacy nozzle point tracks reflection geometry.

2. Settings transitions in this process are not timeout-guarded.
- `onApplyPressure`, `onPrepareBG`, and `onSetDelay` emit settings changes directly.
- Risk: missing settings callback can stall the FSM.

3. Multiple-droplet evidence is not used as a hard invalidation signal.
- In `onCharacterizeLoop`, `result == "Multiple"` increments a counter and skips replicate, but does not disqualify pressure.
- Risk: pressure can still be marked valid after repeated auxiliary-droplet events.

4. Stream-like elongated contours can pass as single droplets.
- `characterize_droplet(...)` does not apply explicit stream-shape rejection beyond a loose width/height filter.
- Risk: high-pressure streams can bias volume statistics and pressure selection.

5. Validity decision can pass on partial/biased subsets.
- Final validity only checks circularity-filtered count threshold, not invalid-hit ratio, stream-hit ratio, or multiple-hit ratio.
- Risk: false-valid pressures in noisy sessions.

## Medium priority
6. Interpolation accepts fit records with missing velocity keys as zero.
- Planning uses `rec.get("fit", {}).get("vx_px_per_us", 0.0)` and same for `vy`.
- Risk: silent zero-velocity plans can move to poor targets instead of failing fast.

7. Presentation throttling knobs are mostly unused.
- `lightweight_overlays` and `present_every_k` are configured but not consistently applied in hot loops.
- Risk: avoidable UI/render overhead.

8. No explicit settings restore on completion/error.
- Process changes `print_pressure`, `flash_delay`, and `num_droplets` without restoring prior values.
- Risk: next manual action or process starts from an unintended state.

9. Debug `print(...)` calls remain in high-frequency paths.
- Risk: avoidable console I/O latency and noisy logs during long sweeps.

## Performance bottlenecks
1. High default replicate target (`20`) with focus/centering recaptures can produce many captures per pressure.
2. Characterization path re-runs full-frame diff/threshold/contours each capture.
3. Search fallback (delay sweep + probes + nudge cycles) can consume many captures before skip.
4. Recorder-enabled runs add per-capture I/O overhead (expected but should be operator-toggleable for speed checks).

## Recommended reliability and performance changes

## Control-path changes
1. Switch sweep nozzle image prerequisite/source to emergence-real center.
- Use `get_pressure_scan_nozzle_center_image_position()` (or `get_real_nozzle_center_image_position()`) in `missing_requirements` and initialization.

2. Use trajectory-derived pressure band as the sweep planning source.
- Use trajectory-qualified outputs (`valid_fit_pressures` / `trajectory_pressure_band`) from pressure-trajectory results.
- Do not use pressure-band-process `primary_band` as the sweep planner source.

3. Add settings timeout wrapper usage in sweep states.
- Route settings changes through a timeout-aware helper (same deterministic behavior as move timeout guards).

4. Add strict pressure invalidation policy for multi/stream evidence.
- Disqualify a pressure when replicate evidence includes multiple droplets or stream-like singles above configured limits.

5. Tighten validity gate before marking a pressure valid.
- Require minimum accepted replicates plus maximum allowed invalid/multiple/stream hit ratios.

## Analysis-path changes
5. Add stream-shape rejection to characterization.
- Include aspect/circularity/area gates (or reuse `identify_droplets(..., return_details=True)` geometry flags) before accepting a replicate.

6. Fail fast on unusable trajectory fit inputs.
- Reject fit points missing velocity fields rather than silently substituting zeros.

7. Normalize key thresholds by image dimensions where possible.
- Focus, area, and edge guard thresholds should scale better across optics/resolution changes.

## Performance changes
8. Apply overlay throttling consistently.
- Emit overlays every `k` frames in search/char loops unless an error branch requires immediate display.

9. Add ROI-first path for characterization contouring.
- Reuse last center as cropped ROI first, with full-frame fallback on miss.

10. Keep fixed statistical replicate collection for CV.
- Keep the sweep target at 20 accepted replicates per pressure for representative CV.
- Disable early-stop by default in this process so runs capture the full sample count.
- Keep a bounded max-attempt policy only as a safety escape hatch.

## Implemented in current pressure-sweep patch
1. Search confidence hysteresis and streak guards.
- Added per-pressure streak tracking for low-signal, no-contour, and center-jump conditions.
- Added stable-hit requirement before accepting a search detection and entering centering.
- Added deterministic pressure invalidation when configured streak limits are exceeded.

2. Centering stability checks.
- Added center-jump rejection guard during centering.
- Added stable-center hit requirement before applying persistent X/Z trajectory bias updates.
- Added structured decision/analysis records for center lock and recenter actions.

3. Background refresh runaway guard.
- Added per-pressure cap on background refresh loops when repeated movement marks background stale.
- Exceeding the cap now invalidates the pressure deterministically instead of looping indefinitely.

4. Characterization quality gating.
- Added stream-like frame rejection via `circularity_ellipse` threshold.
- Added invalid/multiple/stream ratio tracking during characterization attempts.
- Added early partial-batch bailout when quality-ratio limits are exceeded.

5. Final batch validity policy hardening.
- Batch validity now checks accepted replicate count plus max invalid/multiple/stream ratios.
- Invalid pressure records now carry richer diagnostics (`invalid_frame_hits`, stream/multiple counts, ratios).

6. Search nudge correction.
- Replaced ineffective +2 us nudge with meaningful delay-anchor adjustments (hundreds to thousands of microseconds).

7. Replay tooling coverage.
- `tools/replay_calibration_run.py` now supports `PressureSweepCharacterizationProcess` summary replay in addition to nozzle replay.

## Recommended tests (currently missing)
1. Prerequisite/source tests:
- sweep should require emergence-real nozzle center path (with backward-compatible fallback only when intended).

2. Settings timeout tests:
- missing `settingsChangeCompleted` callback should error out, not hang.

3. Multi/stream invalidation tests:
- repeated `Multiple` or stream-like single detections should invalidate pressure deterministically.

4. Validity gate tests:
- partial batches with high invalid ratios must not be marked valid.

5. Interpolation integrity tests:
- missing fit velocity fields should produce deterministic start/plan failure.

6. Performance contract tests:
- benchmark capture count and loop wall-time on synthetic fixtures;
- keep non-blocking trend outputs (p50/p95) for regression visibility.

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
- Nozzle focus quality/prerequisite and manager routing:
  - `tests/test_calibration_focus_process_quality_gate.py`
- Recorder mode toggle/finalize behavior:
  - `tests/test_calibration_recorder_toggle.py`

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
