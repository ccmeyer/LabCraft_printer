# Droplet Imager Implementation Notes

## Purpose

This document describes the currently implemented droplet-imager capture path in this repo, from the Qt dialog and calibration state machines, through the Raspberry Pi camera/GPIO logic, into the STM32 firmware that coordinates print and flash timing, and back to the Python image-analysis pipeline.

The goal is to capture how the system actually works today so future changes can be made without having to rediscover the control flow.

## High-level model

The droplet imager is split across three layers:

1. Python UI / calibration orchestration
   - Opens the droplet-imager dialog.
   - Starts the Pi camera locally.
   - Sends configuration commands to the MCU over the existing command queue.
   - Requests captures from calibration processes.
   - Consumes the selected flashed frame and passes it to analysis.

2. Raspberry Pi local capture logic
   - Holds the camera open and continuously grabs frames.
   - Drives one GPIO from Pi to MCU as the "capture/print now" trigger.
   - Watches one GPIO from MCU to Pi as "flash fired".
   - Uses the flash-fired edge to decide which newly captured frame most likely contains the LED strobe.

3. STM32 firmware timing/orchestration
   - Watches the Pi trigger line with an EXTI interrupt.
   - Starts either:
     - a pure flash after a programmed delay, or
     - a print sequence where the flash is scheduled immediately after the last print pulse.
   - Raises a short "flash fired" acknowledgment pulse back to the Pi when the flash actually fires.

## Main code entrypoints

### UI and controller

- `FreeRTOS-interface/View.py`
  - `View.droplet_imager()` reloads the calibration UI/model, reconnects signals, enables the print profile, and opens `CalibrationClasses.View.DropletImagingDialog`.

- `FreeRTOS-interface/CalibrationClasses/View.py`
  - `DropletImagingDialog.__init__()` starts the local Pi camera via `controller.start_droplet_camera()` and tells the MCU to start flash-trigger monitoring via `controller.start_read_camera()`.
  - The dialog also pushes the current settings down to the system:
    - exposure time
    - flash delay
    - flash duration
    - imaging droplet count

- `FreeRTOS-interface/Controller.py`
  - `connect_droplet_camera_signals()` wires calibration-manager capture/move/settings requests to controller handlers and connects `machine.droplet_camera.image_captured_signal` to `_on_image_captured()`.
  - `handle_capture_request()` stores a pending callback and starts an async capture through `machine.capture_droplet_image()`.
  - `_on_image_captured()` pulls the chosen frame from `machine.droplet_camera`, forwards it into `model.droplet_camera_model.update_image(...)`, and resolves the pending callback for the active calibration process.
  - `_on_capture_failed()` resolves the pending callback with `None` and emits `calibration_manager.captureFailed`.

### Pi camera and GPIO implementation

- `FreeRTOS-interface/Machine_FreeRTOS.py`
  - `DropletCamera`
    - Pi output GPIO: BCM 17, used to trigger the MCU.
    - Pi input GPIO: BCM 22, used to receive the MCU "flash fired" pulse.
    - Uses `Picamera2(1)` in video mode.
    - Keeps a rolling ring buffer of recent frames and metadata.
    - Runs a dedicated grabber thread which is the only place that evaluates candidate flashed frames.

### Firmware

- `firmware/Core/Src/main.c`
  - `HAL_GPIO_EXTI_Callback()` routes the trigger input interrupt into `MX_FLASH_TriggerCallback(GPIO_Pin)`.
  - `HAL_TIM_OC_DelayElapsedCallback()` handles the TIM12 compare event, fires the flash, then calls `MX_FLASH_Acknowledge()`.

- `firmware/Core/Src/Orchestrator.cpp`
  - `CMD_INIT_FLASH` creates the flash-monitor task and the short ack timer.
  - `flashNotifyFromISR()` latches a rising edge on the Pi trigger line and notifies the flash task.
  - `_flashTaskLoop()` decides whether to:
    - flash only after `_flashDelay`, or
    - print `_imagingDroplets` and schedule flash on the final pulse.
  - `scheduleFlashIn()` programs TIM12 for microsecond-delay scheduling.
  - `MX_FLASH_Acknowledge()` raises the flash-ack GPIO briefly so the Pi can arm its frame search after the real flash event.

- `firmware/Core/Src/Printer.cpp`
  - The print path supports `setFlashOnLast(true)`.
  - On the final print pulse, if `_flashOnLast` is set, the printer asks the orchestrator to schedule the flash immediately after that pulse.

## End-to-end capture sequence

### 1. Droplet-imager dialog startup

Opening the droplet-imager dialog does two separate things:

1. Starts the local camera on the Pi:
   - `Controller.start_droplet_camera()`
   - `Machine.start_droplet_camera()`
   - `DropletCamera.start_camera()`

2. Arms the MCU side trigger/flash task:
   - `Controller.start_read_camera()`
   - `Machine.start_read_camera()`
   - command queue entry `START_READ_CAMERA` (`0xC0`)
   - firmware `CMD_INIT_FLASH`

That separation matters: the Pi camera can be running even if the firmware flash-monitor task is not armed yet.

### 2. Settings are applied through the normal machine command queue

The droplet-imager UI and calibration processes do not directly poke firmware internals. They use the normal controller/machine command path:

- `SET_WIDTH_F` (`0xC2`) for flash duration
- `SET_DELAY_F` (`0xC3`) for flash delay
- `SET_IMAGE_DROPLETS` (`0xC4`) for the number of droplets to print before the flash

Exposure time is different: it is local to the Pi camera and is set directly on `Picamera2` by `DropletCamera.change_exposure_time(...)`.

### 3. A calibration process requests a capture

Calibration processes do not talk to the camera directly. They emit:

- `CalibrationManager.captureImageRequested(callback)`

The controller receives that through `handle_capture_request()`, stores the callback as `pending_capture_callback`, and calls:

- `Machine.capture_droplet_image()`
- `DropletCamera.capture_with_retry_async(...)`

This is important because the calibration state machines are callback-driven. They do not block waiting for the image; they expect the controller to hand the result back later.

### 4. Pi raises the trigger line and waits for real flash acknowledgement

Inside `DropletCamera.capture_non_blocking(...)`:

1. Any stale ack edges on the input GPIO are drained.
2. Pi trigger GPIO is driven high.
3. Python waits for the MCU flash-ack GPIO rising edge.

If no ack edge arrives within the timeout, the capture attempt is marked as:

- `reason = "edge_timeout"`

and the attempt fails immediately.

This means the Python side does not assume a flash happened just because it requested one. It waits for the firmware to assert that the flash actually fired.

### 5. Firmware reacts to the trigger line

When the Pi trigger goes high:

1. STM32 EXTI callback runs:
   - `HAL_GPIO_EXTI_Callback(GPIO_PIN_8)`
   - `MX_FLASH_TriggerCallback(GPIO_Pin)`
   - `Orchestrator::flashNotifyFromISR(GPIO_Pin)`

2. `flashNotifyFromISR()`:
   - verifies the correct trigger pin
   - suppresses repeated notifications while the line remains high
   - wakes the flash-monitor task

3. `_flashTaskLoop()` begins a single flash cycle:
   - sets `_flashInProgress = true`
   - clears `BIT_FLASH_DONE`

Then it chooses one of two modes:

### Mode A: flash only

If `_imagingDroplets == 0`, firmware does not print first. It simply calls:

- `Orchestrator::scheduleFlashIn()`

which programs TIM12 compare channel 1 to fire after `_flashDelay` microseconds.

### Mode B: print then flash

If `_imagingDroplets > 0`, firmware does:

- `Printer::instance()->setFlashOnLast(true)`
- `Printer::instance()->enqueue(_imagingDroplets, _imagingFreq, PulseMode::BOTH)`

Later, inside the print loop in `Printer.cpp`, when the last print pulse is reached, firmware calls:

- `Orchestrator::instance()->scheduleFlashIn()`

This means the flash delay is measured from the last print pulse, not from the original Pi trigger edge, when droplets are being printed as part of the capture.

### 6. TIM12 fires the flash and acknowledges it back to the Pi

When TIM12 reaches the programmed compare point:

1. `HAL_TIM_OC_DelayElapsedCallback()` stops the one-shot compare.
2. `MX_FLASH_ONCE()` fires the flash hardware.
3. `MX_FLASH_Acknowledge()` raises the dedicated "flash fired" GPIO back to the Pi.

`MX_FLASH_Acknowledge()` also starts a short FreeRTOS software timer so that the ack line is returned low shortly afterward.

This ack pulse is the key synchronization signal for frame selection on the Pi.

### 7. Pi arms the frame search only after the ack pulse

As soon as the Pi sees the flash-ack edge:

1. It drops the trigger GPIO low.
2. It records `arm_ns = time.monotonic_ns()`.
3. It computes a brightness threshold from recent pre-arm frames:
   - baseline mean/std from up to 4 earlier frames
   - threshold = `base_mean + k_sigma * max(base_std, 1.0) + min_delta`
   - capped at `150.0`

Only frames whose completion timestamp is strictly later than `arm_ns` are eligible to be selected.

This is a critical implementation detail:

- the camera is not externally triggered
- the system continuously grabs frames
- the selected "flash frame" is inferred by time-gating and brightness, not by hardware frame-sync

### 8. Grabber thread chooses the flashed frame

The grabber thread continuously captures requests from Picamera2 and appends each frame to a small ring buffer:

- `(arr, metadata, t_done_ns, mean_intensity)`

While a capture is active, the grabber considers only post-arm frames and uses this policy:

1. Count post-arm frames.
2. Track the brightest post-arm frame seen so far.
3. If any post-arm frame has mean intensity above the computed threshold:
   - select it immediately
   - mark `reason = "threshold"`
4. If no frame crosses threshold before either:
   - `max_new_frames` is reached, or
   - the deadline expires
   then select the brightest post-arm frame:
   - `reason = "fallback"`
5. If nothing useful was seen at all, select the current frame as:
   - `reason = "last_resort"`

The current retry wrapper only accepts a capture as successful when:

- `reason == "threshold"`

Fallback or last-resort selections are kept in capture metadata, but they are treated as failed attempts and retried.

### 9. Selected frame is handed back to the controller and model

Once a frame is selected:

1. `DropletCamera._complete_capture_locked(...)`
   - stores `latest_frame`
   - stores capture metadata in `_cap_result`
   - optionally rotates the image 90 degrees clockwise
   - emits `image_captured_signal`

2. `Controller._on_image_captured()`
   - reads `latest_frame`
   - reads `get_last_capture_result()`
   - calls `model.droplet_camera_model.update_image(frame, capture_info=cap_info)`
   - invokes the pending calibration callback with the frame

3. `DropletCameraModel.update_image(...)`
   - stores the latest frame
   - stores the latest capture metadata
   - optionally queues the image for saving
   - emits `droplet_image_updated`

Capture metadata currently preserved with the image includes:

- selected frame mean intensity
- threshold used
- capture id
- selection reason (`threshold`, `fallback`, `last_resort`, `edge_timeout`)

## How image-based calibration uses the capture result

The calibration layer is organized as state-machine processes under `FreeRTOS-interface/CalibrationClasses/Model.py`.

The common contract is:

1. A process emits `changeSettingsRequested(...)` as needed.
2. Then it emits `captureImageRequested(callback)`.
3. The callback receives either:
   - `frame` on success, or
   - `None` on capture failure
4. The process continues with its analysis state once `captureCompleted` is emitted.

Examples:

- `NozzleFocusCalibrationProcess`
  - captures a droplet image
  - computes a Tenengrad-based focus metric
  - moves the Y axis to optimize focus

- `TrajectoryCalibrationProcess`
  - applies one flash delay at a time
  - captures several replicates
  - uses `DropletCameraModel.identify_droplets(...)` against the saved background image
  - fits the observed droplet positions across delays

- `PressureTrajectoryCalibrationProcess`
  - sweeps pressure and delay combinations
  - uses repeated capture/analyze/adjust loops to map droplet flight path behavior

The important boundary is that frame selection happens before analysis. Analysis functions such as `identify_droplets(...)` assume the frame handed to them is already the best candidate for the flash event.

## Current frame-identification logic

The frame-identification step is intentionally simple and purely image-statistics-based:

- no camera hardware trigger
- no MCU timestamp returned with the image
- no per-frame GPIO timestamp correlation beyond local monotonic timing
- no ROI-based flash detection; selection is based on whole-frame mean intensity

This has a few consequences:

1. The system assumes the flashed frame is globally brighter than nearby frames.
2. If the flash is weak or illumination varies, the threshold path can fail and trigger retries.
3. If the flash does not brighten the full frame strongly enough, a visually useful frame may still be classified as `fallback`, which the retry wrapper currently treats as failure.
4. Any future change to camera exposure, gain, crop, or scene brightness can change capture reliability even if the firmware timing stays correct.

## Firmware timing notes

There are two separate timing anchors in the implemented design:

1. Pi trigger edge to firmware flash task wakeup
2. Last print pulse to flash fire, when imaging droplets are printed

The firmware path is designed so the actual flash timing is owned by the MCU, not the Pi:

- the Pi requests a cycle
- the MCU decides when the flash occurs
- the Pi only begins selecting candidate frames after the MCU reports that the flash fired

That division is good and should be preserved. It keeps microsecond-level timing on the MCU side where it belongs.

## Important implementation details and hotspots

### 1. `START_READ_CAMERA` really means "arm the MCU flash monitor"

The Python name suggests camera behavior, but on the firmware side `CMD_INIT_FLASH` creates the trigger-monitoring task. If this command is not sent, the Pi can raise the trigger GPIO forever and never get a flash-ack edge.

### 2. The Pi camera is free-running

The selected image is not a hardware-triggered exposure. It is the best frame inferred after a flash-fired notification. Any attempt to improve timing should start from this fact.

### 3. Success is narrower than selection

`DropletCamera` can select frames for reasons `threshold`, `fallback`, or `last_resort`, but `capture_with_retry_sync()` only treats `threshold` as success. That means some usable frames may still cause retries or failure.

### 4. Rotation happens in the camera wrapper

`DropletCamera._complete_capture_locked()` rotates the selected frame 90 degrees clockwise before the rest of the app sees it. Any pixel-space calibration or saved image review has to remember that the stored/displayed image is not the raw sensor orientation.

### 5. Delay meaning depends on droplet count

- `num_droplets == 0`: flash delay is measured from the trigger event.
- `num_droplets > 0`: flash delay is measured from the final print pulse.

That distinction matters when comparing calibration results across modes.

### 6. Exposure is local, flash settings are remote

- exposure time is applied on the Pi camera object
- flash delay/duration and imaging droplet count are firmware settings

If settings appear inconsistent, check both sides.

## Suggested reading order for future changes

If revisiting this system later, read in this order:

1. `FreeRTOS-interface/CalibrationClasses/View.py`
   - how the dialog starts the camera and pushes settings
2. `FreeRTOS-interface/Controller.py`
   - signal wiring and capture callback handoff
3. `FreeRTOS-interface/Machine_FreeRTOS.py`
   - `DropletCamera`
   - machine command methods for flash settings
4. `firmware/Core/Src/Orchestrator.cpp`
   - flash trigger task
   - `scheduleFlashIn()`
   - ack signaling
5. `firmware/Core/Src/Printer.cpp`
   - final-pulse flash scheduling
6. `FreeRTOS-interface/CalibrationClasses/Model.py`
   - calibration processes using the returned image
   - `DropletCameraModel.identify_droplets(...)`

## Likely improvement areas

These are the main places to look if capture reliability needs improvement:

1. Pi-side flashed-frame detection
   - use ROI-based brightness instead of full-frame mean
   - accept some `fallback` frames when quality metrics are good
   - record more timing/debug metadata per attempt

2. Firmware-to-Pi observability
   - expose more timing/status information in machine status or logs
   - make it easier to confirm whether flash timing or frame selection is the failure

3. Calibration-process robustness
   - distinguish "capture synchronization failed" from "image captured but droplet analysis failed"
   - persist capture metadata alongside calibration results for later diagnosis

4. Naming cleanup
   - `START_READ_CAMERA` / `STOP_READ_CAMERA` are misleading names for what is effectively flash-trigger monitor start/stop on the MCU.

## Short summary

Today the droplet imager works as a split system:

- Python owns the camera, GPIO handshake, retries, and analysis orchestration.
- Firmware owns precise flash timing and the decision to flash directly or after printing droplets.
- The chosen flashed frame is identified on the Pi by waiting for the MCU flash-fired edge and then selecting the first sufficiently bright post-ack frame from a free-running camera stream.

That is the key design assumption to keep in mind before changing anything in this path.

## HIL Camera Benchmark

The repository now includes a host-side camera benchmark integrated with the HIL self-test runner:

- runner integration: `tools/run_selftest.py` (`--camera-benchmark`)
- benchmark module: `tools/camera_flash_benchmark.py`
- artifact: `<selftest_out_base>_camera_benchmark.json`
- execution order: configurable
  - default: `auto`
    - resolves to `pre_selftest` for `flash_only`
    - resolves to `post_selftest` for `print_then_flash` and `coordinated_flash`
  - explicit override: `pre_selftest` or `post_selftest` (runner re-sends HELLO before post-selftest benchmark to resume status frames)

### Methodology

For fixed settings (no per-shot setting churn), the benchmark:

1. If mode is `print_then_flash`, runs bounded machine-ready preflight:
   - `CMD_ENABLE_MOTORS`
   - `CMD_HOME_XY` (with explicit fast/slow/backoff params)
   - `CMD_HOME_PR_BOTH` (with explicit fast/slow/backoff params)
   - `CMD_P_REG_START` / `CMD_R_REG_START`
   - waits for pressure-ready status within timeout
2. If mode is `coordinated_flash`, runs the same homing/pressure setup, sets
   print/refuel pressure targets to 0.6 psi, starts regulation, sets gripper
   refresh/pulse defaults to 5000 ms / 500 ms, opens the gripper, and then
   configures the flash path with at least one imaging droplet so the firmware
   uses the print/refuel valve path. The refresh and pulse can be overridden
   with `--camera-benchmark-coordinated-gripper-refresh-ms` and
   `--camera-benchmark-coordinated-gripper-pulse-ms`.
3. Sends imaging config commands to firmware:
   - `CMD_INIT_FLASH`
   - `CMD_SET_FLASH_DURATION`
   - `CMD_SET_FLASH_DELAY`
   - `CMD_SET_IMAGING_DROPLETS`
4. Runs warm-up trigger cycles first, then repeated counted trigger cycles using Pi GPIO trigger/ack lines.
   `--camera-benchmark-min-trigger-period-ms` can enforce a minimum
   trigger-start-to-trigger-start period; cycles that already exceed the
   period are not delayed further.
5. Selects flashed frames using the same time-gated threshold/fallback pattern as normal capture.
6. Stores per-cycle timestamps and aggregate latency/FPS statistics.

Mode options:

- `flash_only` (default baseline): forces `num_droplets=0` to isolate trigger/ack path.
- `print_then_flash`: uses print path (`num_droplets>0`) and performs pressure-ready preflight before cycles.
- `coordinated_flash`: uses print path (`num_droplets>=1`) while pressure regulation,
  valve actuation, and stochastic gripper refresh overlap are active.

Practical run-order note:

- `print_then_flash` or `coordinated_flash` in `pre_selftest` order can lower SAFE selftest memory-headroom margins because the benchmark executes additional homing/regulation work before selftest metrics are captured.
- For stable SAFE selftest pass/fail behavior plus print-path benchmarking, use `post_selftest`.

### Recorded per-cycle timestamps

- `t_cycle_start`
- `t_trigger_high`
- `t_ack_edge`
- `t_arm_gate`
- `t_selected_frame_done`
- `t_cycle_end`

Derived durations:

- `trigger_to_ack_ms`
- `ack_to_arm_ms`
- `arm_to_frame_ms`
- `trigger_to_frame_ms`
- `cycle_total_ms`

Selection metadata:

- `reason`
- `threshold`
- `selected_mean`
- `post_arm_frames_seen`
- `attempt_index`
- `success_bool`
- `ack_seen_bool`
- `ack_level_high_seen_bool`
- `frame_selected_bool`
- `edge_timeout_subreason` (`no_edge_no_level|level_seen_no_edge|line_high_no_edge`)
- GPIO probe fields (`trigger_level_after_set_high`, `ack_level_before_wait`, `ack_level_after_wait`, etc.)

### Aggregate metrics

The benchmark summary includes:

- `requested_cycles`
- `completed_cycles`
- `success_cycles`
- `success_rate`
- `ack_seen_cycles`
- `ack_level_high_seen_cycles`
- `frame_selected_cycles`
- `threshold_cycles`
- `fallback_cycles`
- `last_resort_cycles`
- `effective_fps`
- `reason_distribution`
- `timeout_count`
- `error_count`
- p50/p90/p99/mean for each duration metric

`success_cycles` currently means cycles where an ack was observed and a frame was selected (`threshold`, `fallback`, or `last_resort`), not only strict threshold hits.

Benchmark artifacts also include:

- `status_snapshot_pre`
- `status_snapshot_post`
- `status_snapshot_delta` (`ext_count_delta`, `flash_num_delta`)

These use firmware status frames to indicate whether the MCU observed trigger edges / flash events even when Pi edge-capture reports timeouts.

Additional diagnostic blocks:

- `preflight` (for `print_then_flash` mode), including pass/fail and last pressure/active snapshot.
- `init_diag` with best-effort status verification that flash delay/width/imaging-droplet settings were applied.

### Throughput mode in UI capture loop

Repeated capture in the droplet camera view uses `throughput_mode=True`:

- allows `fallback` as a valid capture reason
- reduces retry budget (`attempts=2`, `attempt_timeout_s=0.2`, smaller inter-attempt gap)
- guards against overlapping async capture workers so timer ticks do not spawn stacked retries

Strict mode (`threshold` only, longer retry budget) remains available for calibration-critical usage.

### Flash safety guardrails

To protect the illumination LED from over-long pulses, flash width is now hard-clamped in both host and firmware:

- minimum: `100 ns`
- maximum: `5000 ns`

Any higher requested value is reduced to the max before the pulse is applied.

The PE8 trigger line remains protected, and the PE9 flash-driver output path now also has an explicit safe-idle requirement:

- firmware re-applies an internal `GPIO_PULLDOWN` for PE8 after generated GPIO init, then clears stale EXTI8 pending state before normal runtime
- boot logs include `PE8_BIAS ...` so bring-up can confirm the trigger input is biased low
- the machine wiring must include a `10 kOhm` pull-down from the PE9 flash-driver trigger net to ground at the flash-driver input side
- firmware now keeps PE9 in `GPIO_MODE_OUTPUT_PP` + `GPIO_PULLDOWN` and drives it low unless the flash session is explicitly armed
- when the flash session is armed, firmware hands PE9 over to `TIM1_CH1` with `GPIO_PULLDOWN`, then reclaims it back to GPIO-low on stop, shutdown, or flash fault
- logs now include `PE9_SAFE_IDLE`, `PE9_ARMED_OUTPUT`, and `PE9_FLASH_FIRE`

### Flash safety session behavior

`START_READ_CAMERA` still means "arm the MCU flash session", but the MCU now latches a flash fault and disarms on unsafe trigger conditions:

- `FLASH_FAULT reason=line_high_on_arm`
- `FLASH_FAULT reason=retrigger_while_high`
- `FLASH_FAULT reason=line_stuck_high`

When a fault latches:

- the firmware logs `FLASH_DISARMED reason=fault`
- no additional trigger edges are accepted until the host performs an explicit `STOP_READ_CAMERA` then `START_READ_CAMERA`
- the host UI disables capture controls and shows the fault reason

Recommended bring-up sequence after this change:

1. Validate the new machine with the illumination LED disconnected or replaced by a safe dummy load if possible.
2. Confirm the boot log shows `PE8_BIAS ... line=0`.
3. Confirm the boot log shows `PE9_SAFE_IDLE ... line=0` before the imager is opened.
4. Close and reopen the droplet imager or dataset window to clear a latched flash fault after the wiring issue is fixed and PE8 is low again.
