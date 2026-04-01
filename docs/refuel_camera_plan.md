# Refuel Camera Investigation and Working Plan

## Purpose

This document captures how the refuel camera system works in the current codebase so future work can start from the implemented behavior instead of memory.

The short version is:

- The current refuel camera path is a host-side monitoring tool, not a closed-loop controller.
- It captures still images from a dedicated Pi camera, estimates the channel liquid level from image intensity changes, and displays the result in a separate Qt dialog.
- Manual tuning still happens through operator actions: adjust refuel pressure/pulse width, fire print-only or refuel-only bursts, and watch whether the measured level drifts.
- The code already contains the basic pieces for this workflow, but the feature looks only partially integrated into the main UI and has several rough edges.

## Status Update: Dataset-First Capture Workflow

The current refuel dialog is now intended primarily for dataset collection, not target locking or burst tuning.
Where this section conflicts with older notes below, this section is the current behavior.

### What is in the window now

- `Capture`
  - `Start Capturing Images`
  - `Save Snapshot`
  - current level readout
  - visible snapshot folder and last snapshot path

- `Analysis`
  - left offset
  - channel width
  - threshold
  - prominence
  - empty cutoff

- `Dataset Capture`
  - start/end dataset session
  - start new scene
  - capture single
  - capture sequence
  - reject last capture
  - visible dataset run path, current scene, and status

The older `Setpoint`, `Burst Test`, and `Session Summary` sections are no longer surfaced in this window.

### How to gather training data

1. Open `Refuel Camera` from the main UI.
2. Click `Start Capturing Images` to confirm the channel is framed correctly in the rotated live preview.
3. Use `Save Snapshot` only for ad hoc raw-image saves.
4. For dataset collection:
   - click `Start Dataset Session`
   - confirm the run path shown in the dialog
   - click `Start New Scene` whenever head position, focus, exposure, lighting, or framing changes
   - use manual `print_only` and `refuel_only` pulses to move the fluid level
   - use `Capture Single` for distinct still frames
   - use `Capture Sequence` only when you want a short temporal run
   - use `Reject Last Capture` for the most recent bad frame
   - click `End Dataset Session` when finished
5. Annotate later with the offline dataset annotation tool. The capture window does not label images during collection.

### Where files are saved

- Ad hoc snapshots:
  - `artifacts/refuel_camera_frames/refuel_frame_<timestamp>.png`

- Dataset captures:
  - `calibration_recordings/RefuelLevelDatasetCaptureProcess/run_<timestamp>_<id>/captures/cap_<index>_raw.png`

The dataset run directory also contains:

- `run_meta.json`
- `events.jsonl`
- `scenes.jsonl`
- `frames.jsonl`
- `analysis.jsonl`
- `labels.jsonl`

### Raw image handling

- The live preview still uses a rotated analysis view so the channel is easy to inspect.
- Saved snapshots and dataset captures now use the raw camera frame as the source of truth.
- Resize/rotate operations are applied only to analysis/display copies, not to the saved training data.

## Current High-Level Model

The refuel system is split into three mostly separate concerns:

1. Refuel imaging
   - A dedicated `RefuelCameraWindow` opens a separate dialog.
   - It starts a Pi camera, turns on a local illumination LED, and periodically captures frames.
   - Each frame is analyzed in a background thread to estimate the liquid level.

2. Manual refuel tuning controls
   - Pressure and pulse controls are sent through the normal controller/machine command queue.
   - The operator can adjust refuel pressure, refuel pulse width, and trigger print-only or refuel-only pulse bursts.

3. Firmware pulse execution
   - The MCU executes refuel pressure setpoints and refuel pulses through the existing pressure-regulator and printer subsystems.
   - The refuel camera does not directly coordinate timing with firmware the way the droplet imager does.

The most important design point is that the current refuel camera system is observational only. It measures level drift, but it does not automatically change refuel settings or drive a calibration state machine.

## Main Code Map

### App/model/controller setup

- `FreeRTOS-interface/App.py`
  - Creates `Model`, `Machine`, `Controller`, and `MainWindow`.

- `FreeRTOS-interface/Model.py`
  - Creates `self.refuel_camera_model = CalibrationClasses.RefuelCameraModel()`.

- `FreeRTOS-interface/Machine_FreeRTOS.py`
  - Creates `self.refuel_camera = RefuelCamera()` when the active hardware profile supports it.

- `FreeRTOS-interface/hardware/profile.py`
  - `CURRENT_PROFILE` has `has_refuel_camera=True`.
  - `LEGACY_PROFILE` has `has_refuel_camera=False`.

### Refuel-specific UI/model/driver pieces

- `FreeRTOS-interface/CalibrationClasses/View.py`
  - `RefuelCameraWindow`

- `FreeRTOS-interface/CalibrationClasses/Model.py`
  - `ImageAnalysisThread`
  - `RefuelCameraModel`

- `FreeRTOS-interface/Machine_FreeRTOS.py`
  - `RefuelCamera`
  - `Machine.start_refuel_camera()`
  - `Machine.capture_refuel_image()`
  - `Machine.stop_refuel_camera()`
  - `Machine.refuel_led_on()`
  - `Machine.refuel_led_off()`

- `FreeRTOS-interface/Controller.py`
  - `start_refuel_camera()`
  - `capture_refuel_image()`
  - `stop_refuel_camera()`

### Manual tuning controls that matter to refuel work

- `FreeRTOS-interface/View.py`
  - Main pressure UI for refuel pressure and refuel pulse width.

- `FreeRTOS-interface/CalibrationClasses/View.py`
  - Refuel window keyboard shortcuts for refuel pressure changes and print/refuel pulse bursts.

- `FreeRTOS-interface/Controller.py`
  - `set_relative_refuel_pressure()`
  - `set_absolute_refuel_pressure()`
  - `set_refuel_pulse_width()`
  - `print_only()`
  - `refuel_only()`

- `FreeRTOS-interface/Machine_FreeRTOS.py`
  - Converts psi to raw pressure units and queues the refuel-related commands.

- `firmware/Core/Src/Orchestrator.cpp`
  - Handles `CMD_PR_REFUEL`, `CMD_PR_REFUEL_REL`, `CMD_SET_PW_REFUEL`, `CMD_DISPENSE_PRINT`, `CMD_DISPENSE_REFUEL`, and `CMD_RESET_REFUEL`.

- `firmware/Core/Src/Printer.cpp`
  - Executes `PulseMode::PRINT_ONLY` and `PulseMode::REFUEL_ONLY`, with refuel pulses waiting for refuel pressure to be in range before pulsing the valve.

## End-to-End Refuel Camera Flow

### 1. Window creation

The refuel workflow currently lives in `CalibrationClasses.View.RefuelCameraWindow`.

When the dialog is constructed:

- it stores references to `main_window`, `model`, `controller`, and `model.refuel_camera_model`
- it builds a separate UI for level monitoring
- it immediately starts the refuel camera
- it immediately pushes the current analysis parameters into the shared `RefuelCameraModel`

Unlike the droplet imager, I did not find a current main-window launcher for `RefuelCameraWindow`. The class exists and is wired internally, but no active caller in the main UI currently instantiates it.

### 2. Camera start

`RefuelCameraWindow.start_camera()` calls:

- `Controller.start_refuel_camera()`
- `Machine.start_refuel_camera()`
- `RefuelCamera.start_camera()`

The controller also turns on the refuel LED through:

- `Machine.refuel_led_on()`
- `RefuelCamera.led_on()`

The refuel camera wrapper is much simpler than the droplet imager:

- it uses `Picamera2(0)`
- it uses a still configuration, not a free-running video grabber
- it does synchronous `capture_array()` image acquisition
- it controls a local LED on GPIO 27 directly from the Pi

Based on the README camera overlay configuration plus the camera indices used in code, the likely intended mapping is:

- camera 0 -> refuel camera (`IMX219` on CAM0)
- camera 1 -> droplet imager (`IMX296` on CAM1)

That mapping is an inference from:

- `README.md` camera overlay notes (`imx219` on CAM0, `imx296` on CAM1)
- `RefuelCamera.start_camera()` using `Picamera2(0)`
- `DropletCamera.start_camera()` using `Picamera2(1)`

### 3. Repeated capture

The refuel dialog uses a `QTimer` to call `capture_image()` on a fixed interval.

Current behavior:

- button text toggles between start/stop capture
- timer period is `500 ms`
- each timer tick calls `Controller.capture_refuel_image()`

This path is synchronous up to the point where the frame has been captured:

- `Machine.capture_refuel_image()` returns `self.refuel_camera.capture_image()`
- `RefuelCamera.capture_image()` calls `self.camera.capture_array()`

So the UI thread can block during capture/readout. That is different from the droplet imager, which uses an async retrying capture worker and a free-running frame buffer.

### 4. Analysis handoff

After the controller receives the frame, it immediately calls:

- `model.refuel_camera_model.start_analysis(frame)`

`RefuelCameraModel.start_analysis()` does three things:

1. Resizes the captured frame to `480 x 640`
2. Creates a new `ImageAnalysisThread`
3. Connects `analysis_done` to `update_ui_with_analysis()` and starts the thread

The model stores only in-memory state:

- `current_level`
- `level_log` (rolling, max 100 entries)
- `original_image`
- `annotated_image`

There is no built-in persistence of level history, setpoint, pressure adjustments, or refuel session metadata.

### 5. Image analysis algorithm

The implemented level detector is simple and highly geometry-dependent.

### Step A: rotate the image

`ImageAnalysisThread.analyze_image()` rotates the resized image `90 degrees counter-clockwise`.

This means:

- the analysis does not run on the raw sensor orientation
- the model's stored `original_image` is already rotated
- the "original" frame shown/saved by the refuel UI is not the untouched raw camera capture

### Step B: detect the printer head

`find_printer_head()`:

- converts to grayscale
- thresholds with a fixed value
- finds external contours
- keeps contours with:
  - area > 1000 px
  - bounding-box `x` between 100 and 400
- selects the largest remaining contour

This is a hard-coded framing assumption. It only works if the printer head appears in about the expected place after resize and rotation.

### Step C: derive the channel ROI

`get_channel_bounds()` does not detect the channel directly.

Instead it assumes:

- the full printer head bounding box was found correctly
- the channel is a vertical strip inside that box

The channel ROI is computed as:

- `x0 = x + left_offset`
- `y0 = y`
- `width = channel_width`
- `height = printer_head_box_height`

So the operator tunes channel placement manually through:

- left offset
- channel width

### Step D: build a 1-D intensity profile

`get_channel_profile()`:

- crops the channel ROI
- converts to grayscale
- applies a `5x5` Gaussian blur
- averages each row

The result is a 1-D vertical intensity profile for the channel.

### Step E: find the meniscus row

`detect_meniscus_row()`:

- differentiates the profile with `np.diff(profile)`
- optionally flips the sign depending on whether fluid is expected to be darker or lighter
- uses `scipy.signal.find_peaks(...)`
- filters by prominence
- optionally chooses the peak nearest the previous row

The actual call in the refuel path uses:

- `fluid_darker=False`
- `search_band=(0, h0 - 30)`
- `min_prominence=self.prominence`

So the current implementation expects the meniscus to appear as an upward intensity step in the processed profile, not the default "fluid darker" case described in the method docstring.

### Step F: fallback full/empty classification

If no suitable peak is found, `check_fill_state()` is used as a fallback.

It:

- takes a square patch near the bottom of the channel
- compares it against a reference patch immediately to the right
- computes SSIM

Current fallback logic:

- `score < empty_cutoff` -> treat as empty -> return `h0 - 3`
- otherwise -> treat as full -> return `3`

This is not a general level estimate. It is a coarse fallback that snaps the level near "empty" or near "full".

### Step G: produce the displayed level value

After the meniscus row is chosen, the thread computes:

- `level_data = h0 - meniscus_row`

So the displayed number is best interpreted as:

- approximate fluid height in pixels measured upward from the bottom of the channel ROI

That means:

- larger number -> fuller channel
- smaller number -> emptier channel

The annotated image overlays:

- red horizontal line at the detected meniscus
- blue rectangle for the channel ROI
- green rectangle for the full printer head bounding box

### 6. UI update

When analysis completes, `RefuelCameraModel.update_ui_with_analysis()`:

- stores the latest rotated frame
- stores the latest annotated frame
- updates `current_level`
- appends to `level_log`
- emits `update_level_ui_signal`

`RefuelCameraWindow.update_refuel_ui()` then:

- converts the annotated image into a `QPixmap`
- updates the image panel
- updates the `Current Level` label
- redraws the line chart from `level_log`

The chart is a simple rolling plot of recent level values. It is not tied to pressure events, droplet events, timestamps, or calibration phases.

## Manual Refuel Tuning Control Path

The refuel window itself is only the measurement surface. Manual tuning uses the standard machine control path.

### Pressure changes

Refuel pressure can be changed through:

- `Controller.set_relative_refuel_pressure()`
- `Controller.set_absolute_refuel_pressure()`

The machine layer converts psi to raw pressure counts, then queues:

- `RELATIVE_PRESSURE_R`
- `ABSOLUTE_PRESSURE_R`

Firmware handles those as:

- `CMD_PR_REFUEL_REL`
- `CMD_PR_REFUEL`

### Refuel pulse width

Refuel pulse width goes through:

- `Controller.set_refuel_pulse_width()`
- `Machine.set_refuel_pulse_width()`
- command queue entry `SET_WIDTH_R`
- firmware `CMD_SET_PW_REFUEL`

### Manual print/refuel bursts

The current manual calibration actions map cleanly to existing commands:

- `Controller.print_only(n)` -> machine `DISPENSE_PRINT` -> firmware `CMD_DISPENSE_PRINT`
  print-only path in `Printer.cpp` uses `PulseMode::PRINT_ONLY`

- `Controller.refuel_only(n)` -> machine `DISPENSE_REFUEL` -> firmware `CMD_DISPENSE_REFUEL`
  refuel-only path in `Printer.cpp` uses `PulseMode::REFUEL_ONLY`

On the firmware side, refuel-only dispensing:

- waits for refuel pressure to be ready
- uses the current refuel pulse width
- fires the refuel valve

This matches the manual workflow you described: use isolated print/refuel actions and pressure changes while watching whether the observed level drifts up or down.

## Relationship to the Droplet Imager

The refuel camera and droplet imager share the same machine "camera" station, but they are not software-integrated today.

### Shared pieces

- same overall app/model/controller stack
- same physical station name in motion logic: `"camera"`
- same printer/refuel pressure control infrastructure
- same operator goal of working near the front of the print head

### Different pieces

Refuel camera:

- `Picamera2(0)`
- still capture
- synchronous `capture_array()`
- local LED directly controlled by Pi GPIO 27
- no firmware timing handshake for capture
- separate dialog class
- custom level-estimation algorithm

Droplet imager:

- `Picamera2(1)`
- free-running video/grabber thread
- Pi GPIO trigger plus MCU flash-ack GPIO handshake
- firmware `START_READ_CAMERA` / `STOP_READ_CAMERA`
- capture retries and frame-selection logic
- formal main-window launcher and preflight checks
- broader calibration-manager integration

In other words:

- same machine position
- different cameras
- different capture strategy
- different level of integration

## Current Gaps, Quirks, and Risks

These are the most important findings for future work.

### 1. The refuel dialog appears to be orphaned from the main UI

I found the `RefuelCameraWindow` implementation, but I did not find an active caller that opens it from the main window.

What does exist today:

- main-window shortcuts to start/stop the refuel camera hardware
- main-window pressure controls for refuel pressure and pulse width

What I did not find:

- a current button/menu/launcher that creates `RefuelCameraWindow`

### 2. No preflight checks equivalent to the droplet imager

The droplet imager verifies things like:

- command queue empty
- head loaded
- print pressure regulated
- machine positioned at `"camera"`

The refuel window currently does none of that before starting the camera or capture loop.

### 3. The "previous row" tracking looks inconsistent

`detect_meniscus_row()` expects `last_row` to be the previously detected row index.

But the refuel model passes:

- `last_level = self.level_log[-1]`

and `level_log` stores:

- `level_data = h0 - meniscus_row`

So the temporal tracking value being passed forward is a prior level-from-bottom, not a prior row-from-top.

That means the "pick the peak nearest last_row" logic is likely biased or inverted relative to the actual coordinate system it expects.

This is one of the most important code-level issues to fix before trusting automated tracking behavior.

### 4. Capture/analysis concurrency is not guarded

Each capture starts a fresh `ImageAnalysisThread`, but there is no overlap protection or "analysis in progress" guard.

At the current `500 ms` timer period this may be fine most of the time, but it is much less controlled than the droplet-imager path.

### 5. No `None` guard on captured frames

`RefuelCameraModel.start_analysis(frame)` immediately calls `cv2.resize(frame, ...)`.

If `frame` is `None`, this will fail.

That matters because:

- `NullCamera.capture_image()` returns `None`
- `RefuelCamera.capture_image()` also returns `None` if the camera is not started

So the current path is not robust on unsupported systems or camera-start failures.

### 6. Camera settings are not explicitly locked

Unlike the droplet imager, the refuel camera does not set explicit controls such as:

- exposure time
- frame duration
- auto-exposure disable
- auto-white-balance disable

Because no camera controls are applied in `RefuelCamera.start_camera()`, the refuel path currently relies on Picamera2 defaults. That likely means measurement stability can change with scene brightness or camera auto-adjustment behavior.

This is an inference from the absence of explicit control settings in the current code.

### 7. Geometry assumptions are hard-coded

The head/channel detector depends on:

- fixed thresholding
- contour area filters
- expected x-position after resize/rotation
- manually tuned offset/width values

So the current system is tightly tied to one camera framing and one printer-head presentation.

### 8. Save path looks stale

`RefuelCameraWindow.save_frame()` writes to:

- `./MVC-interface/Images/Refuel/...`

That path does not currently exist in the repo root. So the save feature likely needs cleanup before it can be relied on.

### 9. There is stale/unused code around the feature

Examples:

- `FreeRTOS-interface/RefuelCamera.py` contains an older standalone refuel camera wrapper that does not appear to be used anywhere.
- `RefuelCameraModel` contains fields/methods like `stable`, `update_blur`, `update_left_bound`, and `update_right_bound` that do not appear to participate in the active refuel workflow.

This suggests the feature evolved in-place and was never fully cleaned up.

### 10. No test coverage found for the refuel imaging path

I did not find tests covering:

- `RefuelCameraWindow`
- `RefuelCameraModel`
- `ImageAnalysisThread`
- refuel-camera capture/analysis/controller flow

The existing test suite covers many machine-model and pressure-control areas, but not the actual refuel imaging path.

## What the Current System Already Does Well

Even with the gaps above, the current implementation already gives us a useful foundation:

- a dedicated second camera path exists
- a live rolling level display exists
- the manual refuel workflow maps naturally onto existing pressure/pulse commands
- the UI already provides tunable analysis parameters for ROI placement and peak detection
- the system is separate from the droplet imager, which makes investigation safer while the logic is still exploratory

That means we do not need to invent the feature from scratch. The starting point should be refinement, stabilization, and integration.

## Recommended Reading Order

If we revisit this system later, the best reading order is:

1. `FreeRTOS-interface/CalibrationClasses/View.py`
   - `RefuelCameraWindow`
2. `FreeRTOS-interface/Controller.py`
   - `start_refuel_camera()`
   - `capture_refuel_image()`
   - `stop_refuel_camera()`
   - refuel pressure / pulse methods
3. `FreeRTOS-interface/Machine_FreeRTOS.py`
   - `RefuelCamera`
   - refuel pressure/pulse command methods
4. `FreeRTOS-interface/CalibrationClasses/Model.py`
   - `ImageAnalysisThread`
   - `RefuelCameraModel`
5. `FreeRTOS-interface/View.py`
   - refuel pressure and pulse controls in the main pressure box
6. `firmware/Core/Src/Orchestrator.cpp`
   - refuel-related command handlers
7. `firmware/Core/Src/Printer.cpp`
   - `PulseMode::REFUEL_ONLY`
   - refuel pulse execution path
8. `docs/droplet_imager_info.md`
   - for comparison with the more mature imaging stack

## Recommended Next Work Packages

If the goal is to start active development on the refuel camera system again, these are the most sensible next steps.

### Phase 1: make the current tool reliable

1. Add a proper launcher for `RefuelCameraWindow` from the main UI.
2. Add preflight checks similar to the droplet imager:
   - machine at `"camera"`
   - queue empty
   - appropriate head loaded
   - relevant pressure channels ready
3. Guard against `None` frames and camera-start failure.
4. Fix the row-vs-level mismatch in temporal tracking.
5. Clean up the stale save path and stale helper methods.
6. Add a simple image-fixture test harness for the meniscus detector.

### Phase 2: make the measurement meaningful for calibration

1. Define a stable setpoint representation:
   - target row
   - target level
   - acceptable drift band
2. Record calibration session metadata:
   - print pressure
   - refuel pressure
   - print pulse width
   - refuel pulse width
   - level trace over time
3. Add structured "print burst then measure drift" helpers instead of relying only on manual shortcuts.

### Phase 3: integrate with droplet imaging

1. Decide whether the future UX should be:
   - a separate refuel window
   - a tab inside the droplet imager
   - a combined droplet/refuel calibration workflow
2. Reuse the droplet-imager preflight and camera-position checks.
3. Share calibration metadata/logging so a droplet imaging run can also produce a refuel-balance record.

## Bottom Line

Today the refuel camera system is a manual level-monitoring tool built on:

- a dedicated Pi camera (`Picamera2(0)`)
- a simple host-controlled LED
- a custom image-analysis thread that estimates the meniscus position from row-wise intensity changes
- existing machine commands for refuel pressure, refuel pulse width, print-only bursts, and refuel-only bursts

It is not yet an integrated calibration workflow or automatic controller.

The fastest path forward is not to redesign it from zero. It is to:

1. reconnect the existing dialog to the main UI,
2. stabilize the current measurement path,
3. fix the most obvious implementation mismatches,
4. then decide how tightly it should merge with the droplet imager workflow.
