# Droplet Volume Calibration Recon

## Scope

This report is based on repository inspection only. I did not run the UI or hardware. Every statement below is tied to concrete files, classes, and methods found in the repo.

## Concise Architecture Summary

- The active non-legacy droplet-volume workflow starts from `FreeRTOS-interface/View.py`, in `PressurePlotBox.droplet_imager()`, which reloads the droplet calibration stack, reconnects controller/camera signals, enables the print pressure profile, and opens `CalibrationClasses.DropletImagingDialog`.
- Inside `FreeRTOS-interface/CalibrationClasses/View.py`, `DropletImagingDialog` is the main orchestration UI. It exposes direct start buttons for individual calibration processes and an automated `Calibrate All` queue.
- The orchestration core is `FreeRTOS-interface/CalibrationClasses/Model.py`, in `CalibrationManager`. It starts processes, brokers movement/capture/settings requests through controller signals, persists per-run summaries into `calibration.json`, and publishes summary rows back to the UI.
- Image capture is split across two layers:
  - Hardware-trigger/config commands go through `Controller` -> `Machine_FreeRTOS` -> firmware commands.
  - Actual image acquisition is local camera capture through `Machine_FreeRTOS.DropletCamera.capture_with_retry_async()`.
- Image analysis is done in `CalibrationClasses.Model.DropletCameraModel`, mainly in `identify_droplet_contour()` and `characterize_droplet()`.
- Modern calibration results do not update `PrinterHead.set_calibration_data()`. That only happens in the legacy mass-based path in `FreeRTOS-interface/legacy/mass_calibration.py`.
- Experiment-design updates happen only if the user explicitly uses the design bridge in `DropletImagingDialog`:
  - Preview: `_bridge_preview_from_last_char()`
  - Apply: `_apply_previewed_droplet_volume()`
  - Model mutation: `ExperimentModel.apply_droplet_volume_for_option()` or `ExperimentModel.apply_fill_droplet_volume()`
- Persistence is currently fragmented across:
  - `calibration.json`
  - per-process `calibration_recordings/...`
  - `droplet_imager_captures/...`
  - experiment design/progress/key files
- `Model.reload_droplet_model()` recreates both `DropletCameraModel` and `CalibrationManager` every time the imager is opened. That means the current manager is a poor place to own durable reagent memory by itself.

## Calibration Paths Found

### 1. Modern camera-based path: primary droplet-volume path

Main entry point:

- `FreeRTOS-interface/View.py`
  - `PressurePlotBox.droplet_imager()`

What it does:

1. `controller.disconnect_droplet_camera_signals()`
2. reloads `CalibrationClasses`
3. `model.reload_droplet_model()`
4. `controller.connect_droplet_camera_signals()`
5. `controller.enable_print_profile()`
6. opens `CalibrationClasses.DropletImagingDialog`

Within `DropletImagingDialog`, the volume-relevant start buttons are:

- `toggle_start_all_calibration()`
- `toggle_start_pressure_sweep_calibration()`
- `toggle_start_characterization_calibration()`

The automated queue in `CalibrationManager.add_all_calibrations_to_queue()` currently runs:

1. `nozzle_position`
2. `nozzle_focus`
3. `droplet_emergence`
4. `pressure_scan`
5. `pressure_trajectory`
6. `pressure_sweep_characterization`

This is the main current path for producing droplet-volume characterization data.

### 2. Current `Calibrate Pressure` button: not the main droplet-volume path

Entry point:

- `FreeRTOS-interface/View.py`
  - `PressurePlotBox.calibrate_pressure()`

Behavior:

- On non-legacy hardware it opens `CalibrationClasses.RefuelCameraWindow`.
- On legacy hardware it opens `MassCalibrationDialog`.

So, despite the button label, the current non-legacy `Calibrate Pressure` path is not the primary droplet-volume characterization pipeline.

### 3. Legacy mass-based path

Files:

- `FreeRTOS-interface/App.py`
- `FreeRTOS-interface/legacy/mass_calibration.py`
- `FreeRTOS-interface/hardware/profile.py`

How it is enabled:

- `App.py` only constructs `MassCalibrationModel` and `Balance` when `profile.name == "legacy"`.
- `hardware/profile.py` sets `CURRENT_PROFILE.has_mass_calibration = False` and `LEGACY_PROFILE.has_mass_calibration = True`.

Important behavior:

- `MassCalibrationModel.complete_measurement()` computes droplet volume from balance mass difference.
- `MassCalibrationModel.apply_calibrations_to_printer_head()` then calls `PrinterHead.set_calibration_data(...)`.

This legacy path is the only path I found that writes calibration outputs back into `PrinterHead` calibration metadata.

### 4. Older/secondary process still present in code

There is also a standalone `TrajectoryCalibrationProcess` in `FreeRTOS-interface/CalibrationClasses/Model.py`, and `Controller.start_trajectory_calibration()` still exists, but the dedicated trajectory button is commented out in `DropletImagingDialog`. The active UI path uses `PressureTrajectoryCalibrationProcess` instead.

## Full Modern Flow: UI -> Commands -> Image -> Analysis -> Persistence -> Design Update

### A. User starts calibration

1. `PressurePlotBox.droplet_imager()` opens `DropletImagingDialog`.
2. `DropletImagingDialog.__init__()`:
   - starts the droplet camera
   - calls `controller.start_read_camera()`
   - wires dialog buttons to controller start methods
   - wires summary/bridge UI to `CalibrationManager`

Relevant methods:

- `FreeRTOS-interface/CalibrationClasses/View.py`
  - `DropletImagingDialog.__init__()`
  - `toggle_start_all_calibration()`
  - `toggle_start_pressure_sweep_calibration()`
  - `toggle_start_characterization_calibration()`

### B. Controller starts the calibration process

Relevant methods:

- `FreeRTOS-interface/Controller.py`
  - `start_head_prime_calibration()`
  - `start_nozzle_calibration()`
  - `start_nozzle_focus_calibration()`
  - `start_droplet_emergence_calibration()`
  - `start_pressure_scan_calibration()`
  - `start_pressure_trajectory_calibration()`
  - `start_droplet_characterization_calibration()`
  - `start_all_calibrations()`

These all delegate into `model.calibration_manager`.

### C. `CalibrationManager` owns process orchestration

Relevant methods:

- `FreeRTOS-interface/CalibrationClasses/Model.py`
  - `CalibrationManager.begin_session()`
  - `CalibrationManager.start_active_calibration()`
  - `CalibrationManager.start_*` methods
  - `CalibrationManager.add_all_calibrations_to_queue()`
  - `CalibrationManager.onCalibrationCompleted()`
  - `CalibrationManager.onCalibrationError()`
  - `CalibrationManager.onCalibrationDataUpdated()`

Important details:

- `begin_session()` creates or loads `calibration.json`, then appends a run envelope with:
  - `run_id`
  - `printer_head_id`
  - `stock_solution`
  - per-phase `steps`
  - `flat_measurements`
- `start_active_calibration()` connects process signals and starts the process.
- The manager carries process prerequisites such as:
  - background image
  - nozzle center
  - emergence nozzle center
  - pressure band
  - trajectory results

But most of that state is in-memory only.

### D. Calibration processes request movement, settings, and image capture

Signal bridge:

- `FreeRTOS-interface/Controller.py`
  - `connect_droplet_camera_signals()`
  - `handle_capture_request()`
  - `handle_move_request()`
  - `handle_absolute_move_request()`
  - `handle_settings_change_request()`

Process types involved:

- `FreeRTOS-interface/CalibrationClasses/Model.py`
  - `HeadPrimeCalibrationProcess`
  - `NozzlePositionCalibrationProcess`
  - `NozzleFocusCalibrationProcess`
  - `DropletEmergenceCalibrationProcess`
  - `PressureBandCalibrationProcess`
  - `PressureTrajectoryCalibrationProcess`
  - `DropletSearchCalibrationProcess`
  - `PressureSweepCharacterizationProcess`

The main volume-producing processes are:

- `DropletSearchCalibrationProcess`
  - direct manual characterization path
  - per-capture search, center, characterize, then final mean/CV result
- `PressureSweepCharacterizationProcess`
  - runs characterization across multiple pressures
  - emits incremental single-pressure rows and final completion metadata

### E. Machine and firmware command flow

Python machine layer:

- `FreeRTOS-interface/Machine_FreeRTOS.py`
  - `set_absolute_print_pressure()`
  - `set_print_pulse_width()`
  - `set_flash_duration()`
  - `set_flash_delay()`
  - `set_imaging_droplets()`
  - `capture_droplet_image()`
  - `start_droplet_camera()`
  - `start_read_camera()`
  - `print_droplets()`

Local camera layer:

- `FreeRTOS-interface/Machine_FreeRTOS.py`
  - `class DropletCamera`
  - `capture_with_retry_async()`
  - `get_last_capture_result()`
  - `set_capture_profile()`

Firmware command mapping:

- `FreeRTOS-interface/Machine_FreeRTOS.py`
  - `CMD_MAP`
- `firmware/Core/Inc/Orchestrator.h`
- `firmware/Core/Src/Orchestrator.cpp`
- `firmware/Core/Inc/Printer.h`

Relevant command families:

- `START_READ_CAMERA` / `STOP_READ_CAMERA` map to the firmware flash/read-camera subsystem (`CMD_INIT_FLASH` / `CMD_STOP_FLASH`)
- `SET_WIDTH_F`, `SET_DELAY_F`, `SET_IMAGE_DROPLETS`
- `SET_WIDTH_P`
- `ABSOLUTE_PRESSURE_P`
- `DISPENSE`, `DISPENSE_PRINT`, `DISPENSE_REFUEL`
- `ENABLE_PRINT_PROFILE`, `DISABLE_PRINT_PROFILE`

Important detail:

- Actual image acquisition in the modern path is local async camera capture in `DropletCamera.capture_with_retry_async()`.
- The controller then receives the frame in `_on_image_captured()` and forwards it into `DropletCameraModel.update_image()`.

### F. Image capture and droplet analysis

Main analysis class:

- `FreeRTOS-interface/CalibrationClasses/Model.py`
  - `class DropletCameraModel`

Key methods:

- `update_image()`
- `identify_droplet_contour()`
- `characterize_droplet()`
- `load_step_calibration()`
- `calculate_move_to_target()`
- `convert_pixel_position_to_motor_steps()`
- `append_analysis_record()`
- `start_saving()`
- `save_frame_with_metadata()`
- `save_aux_image()`
- `write_json()`

How analysis is used:

- `DropletSearchCalibrationProcess.onAnalyze()` uses `identify_droplet_contour()`
- `DropletSearchCalibrationProcess.onCharacterization()` uses `characterize_droplet()`
- `DropletSearchCalibrationProcess.onAnalyzeCharacterization()` computes final mean/CV and emits `calibrationDataUpdated`
- `PressureSweepCharacterizationProcess` uses the same imaging/characterization primitives, but does it across a pressure plan and records richer per-pressure validity/quality ratios

### G. Result storage

Primary summary persistence:

- `FreeRTOS-interface/CalibrationClasses/Model.py`
  - `CalibrationManager.onCalibrationDataUpdated()`
  - `CalibrationManager._save_atomic()`

This writes into `calibration.json` as:

- `runs[]`
  - `run_id`
  - `printer_head_id`
  - `stock_solution`
  - `steps[phase_name]`
  - `flat_measurements`

Per-process recording:

- `FreeRTOS-interface/CalibrationClasses/Model.py`
  - `CalibrationProcessRecorder`
  - `CalibrationManager.record_analysis()`
  - `CalibrationManager.record_capture_frame()`
  - `CalibrationManager.submit_latest_process_verdict()`

Outputs:

- `calibration_recordings/<ProcessName>/<run_id>/events.jsonl`
- `calibration_recordings/<ProcessName>/<run_id>/analysis.jsonl`
- `calibration_recordings/<ProcessName>/<run_id>/run_meta.json`
- `calibration_recordings/<ProcessName>/<run_id>/verdict.json`
- `calibration_recordings/<ProcessName>/<run_id>/captures/*`

Camera-save stream:

- `FreeRTOS-interface/CalibrationClasses/Model.py`
  - `DropletCameraModel.start_saving()`
  - `DropletCameraModel.append_analysis_record()`

Outputs:

- `droplet_imager_captures/<run>/metadata.jsonl`
- `droplet_imager_captures/<run>/analysis.jsonl`
- captured images and overlays
- `droplet_search_summary.json` for the manual search/characterization process

Important current limitation:

- `CalibrationManager._try_append_flat_rows_from_payload()` exists to normalize per-droplet replicates into `flat_measurements`, but the call is currently commented out inside `onCalibrationDataUpdated()`. So `calibration.json` is not currently collecting a normalized per-observation table even though the hook exists.

### H. Design/reagent update after calibration

UI bridge:

- `FreeRTOS-interface/CalibrationClasses/View.py`
  - `_bridge_get_current_reagent_name()`
  - `_bridge_refresh_design_labels()`
  - `_preferred_char_mean_nL()`
  - `_bridge_preview_from_last_char()`
  - `_apply_previewed_droplet_volume()`
  - `populate_summary_table()`
  - `load_selected_summary_row()`

Model mutation:

- `FreeRTOS-interface/Model.py`
  - `ExperimentModel.find_option_by_reagent_name()`
  - `ExperimentModel.find_key_for_reagent()`
  - `ExperimentModel.preview_requantized_for_option()`
  - `ExperimentModel.apply_droplet_volume_for_option()`
  - `ExperimentModel.preview_fill_requantized()`
  - `ExperimentModel.apply_fill_droplet_volume()`

What actually changes:

- `apply_droplet_volume_for_option()` updates:
  - stock plan cache
  - `OptionSpec.droplet_nL`
  - regenerated experiment state
  - key/concentration key files if runtime assignments exist
- `apply_fill_droplet_volume()` updates `metadata["fill_droplet_volume_nL"]` and regenerates the experiment

What does not happen automatically:

- Neither method saves `experiment_design.json`.
- The user still needs the usual save flow to persist the updated design.

Important limitation:

- `apply_droplet_volume_for_option()` only supports single-stock reagents.
- The bridge can preview two-stock reagents, but auto-apply is disabled for them.

## Process-by-Process Data Produced

### Nozzle position

- File: `FreeRTOS-interface/CalibrationClasses/Model.py`
- Class: `NozzlePositionCalibrationProcess`
- Key method: `_recenter_or_finish()`

Outputs pushed into `CalibrationManager`:

- `set_background_image(...)`
- `set_nozzle_center_image_position(...)`
- `set_nozzle_center(...)`

### Nozzle focus

- File: `FreeRTOS-interface/CalibrationClasses/Model.py`
- Class: `NozzleFocusCalibrationProcess`
- Key method: `onCalibrationCompleted()`

Outputs:

- refined Y position via `set_nozzle_center(final)`
- focus curve data via `calibrationDataUpdated`

### Droplet emergence

- File: `FreeRTOS-interface/CalibrationClasses/Model.py`
- Class: `DropletEmergenceCalibrationProcess`
- Key methods:
  - `_finish_success()`
  - `onCalibrationCompleted()`

Outputs:

- emergence-centered nozzle image position via `set_emergence_nozzle_center_image_position(...)`
- droplet-emergence timing stored in the `droplet_emergence` step payload
- later read back by `CalibrationManager.get_emergence_time()`

### Pressure scan

- File: `FreeRTOS-interface/CalibrationClasses/Model.py`
- Class: `PressureBandCalibrationProcess`
- Key method: `onCalibrationCompleted()`

Outputs:

- `primary_band`
- full per-pressure classifications
- manager update via `set_primary_pressure_band(result)`

### Pressure trajectory

- File: `FreeRTOS-interface/CalibrationClasses/Model.py`
- Class: `PressureTrajectoryCalibrationProcess`
- Key method: `onCalibrationCompleted()`

Outputs:

- trajectory scan results across pressures
- `trajectory_pressure_band`
- `valid_fit_pressures`
- manager update via `set_pressure_trajectory_result(result)`

### Manual droplet characterization

- File: `FreeRTOS-interface/CalibrationClasses/Model.py`
- Class: `DropletSearchCalibrationProcess`
- Key methods:
  - `_save_capture()`
  - `_append_analysis()`
  - `onAnalyze()`
  - `onCharacterization()`
  - `onAnalyzeCharacterization()`

Outputs:

- per-frame search and characterization data
- final `mean_volume` and `cv_volume_percent`
- summary row source for `phase == "search"`

### Pressure sweep characterization

- File: `FreeRTOS-interface/CalibrationClasses/Model.py`
- Class: `PressureSweepCharacterizationProcess`
- Key methods:
  - `_record_pressure_sweep_analysis()`
  - `_record_pressure_result()`
  - `onAnalyzeBatch()`
  - `onCompleted()`

Outputs:

- per-pressure accepted/invalid results
- per-pressure mean/CV
- invalid ratios, multiple-droplet counts, stream-like counts
- summary row source for `phase == "sweep"`

## File-by-File Map of the Calibration Pipeline

| File | Main classes / methods | Role in the pipeline |
| --- | --- | --- |
| `FreeRTOS-interface/View.py` | `PressurePlotBox.droplet_imager()`, `PressurePlotBox.calibrate_pressure()` | Main non-legacy and legacy entry points from the primary UI |
| `FreeRTOS-interface/CalibrationClasses/View.py` | `DropletImagingDialog`, `toggle_start_*`, `populate_summary_table()`, `_bridge_preview_from_last_char()`, `_apply_previewed_droplet_volume()` | Calibration UI, result summary, and bridge from calibration output back into experiment design |
| `FreeRTOS-interface/Controller.py` | `connect_droplet_camera_signals()`, `handle_capture_request()`, `handle_move_request()`, `handle_settings_change_request()`, `start_*` methods | Signal bridge between calibration processes and hardware/model actions |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `CalibrationManager`, calibration process classes, `CalibrationProcessRecorder`, `DropletCameraModel` | Orchestration, analysis, per-run persistence, summary extraction |
| `FreeRTOS-interface/Machine_FreeRTOS.py` | `Machine.set_absolute_print_pressure()`, `set_print_pulse_width()`, `set_flash_delay()`, `set_imaging_droplets()`, `capture_droplet_image()`, `DropletCamera.capture_with_retry_async()` | Hardware command queue plus local asynchronous image capture |
| `firmware/Core/Inc/Orchestrator.h` | command enum values | Firmware command definitions used by calibration |
| `firmware/Core/Src/Orchestrator.cpp` | handlers for `CMD_PR_PRINT`, `CMD_SET_PW_PRINT`, `CMD_SET_FLASH_DELAY`, `CMD_SET_IMAGING_DROPLETS`, `CMD_DISPENSE`, `CMD_ENABLE_PRINT_PROFILE` | Firmware-side execution of pressure, pulse width, flash, and dispense commands |
| `firmware/Core/Inc/Printer.h` | `Printer::enqueue(...)` | Dispense execution primitive used by firmware command handlers |
| `FreeRTOS-interface/Model.py` | `ExperimentModel`, `StockSolution`, `Reagent`, `StockSolutionManager`, `PrinterHead`, `PrinterHeadManager`, `Model.reload_droplet_model()` | Reagent/head metadata, experiment design state, runtime assignment state, droplet-imager model lifecycle |
| `FreeRTOS-interface/App.py` | legacy-only `MassCalibrationModel` wiring | Enables the mass-based calibration path only on legacy profile |
| `FreeRTOS-interface/legacy/mass_calibration.py` | `MassCalibrationModel`, `MassCalibrationDialog` | Legacy balance-driven calibration path that writes calibration back to `PrinterHead` |
| `FreeRTOS-interface/hardware/profile.py` | `CURRENT_PROFILE`, `LEGACY_PROFILE` | Decides which calibration path is even available on a given hardware profile |

## Printer Head Setup and Reagent Metadata

### Printer head metadata

Primary classes:

- `FreeRTOS-interface/Model.py`
  - `PrinterHead`
  - `PrinterHeadManager`
  - `RackModel.get_gripper_printer_head()`

Current relevant printer-head fields:

- `stock_solution`
- `color`
- `current_volume`
- `effective_resistance`
- `bias`
- `target_droplet_volume`
- `predictive_model`
- `resistance_pulse_width`

Important finding:

- `CalibrationManager._safe_get_printer_head_id()` tries `serial` or `id`, but `PrinterHead` does not define either. The code falls back to `str(ph)`.
- So the current modern path does not have a strong stable printer-head identity for cross-run memory.

### Reagent metadata

Primary classes:

- `FreeRTOS-interface/Model.py`
  - `StockSolution`
  - `Reagent`
  - `StockSolutionManager`
  - `OptionSpec`
  - `FactorSpec`

Current relevant reagent identity fields:

- `StockSolution.stock_id`
- `StockSolution.reagent_name`
- `StockSolution.concentration`
- `StockSolution.units`
- `OptionSpec.name`
- `OptionSpec.targets`
- `OptionSpec.droplet_nL`
- `OptionSpec.starting_conc`

Important findings:

- `StockSolutionManager._make_stock_id()` already creates a stable stock key of `reagent_name_concentration_units`.
- But `CalibrationManager._safe_get_stock_solution()` does not use `stock_id`; it prefers `reagent_name`.
- The design bridge also mostly works in terms of reagent display name:
  - `_bridge_get_current_reagent_name()`
  - `ExperimentModel.find_option_by_reagent_name()`
- `ExperimentModel.find_key_for_reagent()` already shows why this is weak: it raises if a reagent name is ambiguous across groups unless `group_name` is supplied.

## Where a Reagent Memory System Best Fits

### Architectural recommendation

Best fit: a separate persistence service owned at the model/domain layer, used by `CalibrationManager` and optionally by `ExperimentModel`.

Why:

- `View` should not own persistence.
- `Controller` is a hardware/transport bridge, not a domain-state owner.
- `CalibrationManager` is the natural producer of calibration events, but it is recreated in `Model.reload_droplet_model()` every time the imager opens.
- `ExperimentModel` owns durable design/reagent metadata, but not the per-frame/per-pressure calibration workflow.

So the clean split is:

- `CalibrationManager` and process classes produce events/results
- a persistence service stores and indexes them by stable reagent/head keys
- `ExperimentModel` consumes the latest or recommended memory entry when the user wants to preview/apply it

### Concrete seams to modify for reagent memory

| File | Function / method | Why it matters |
| --- | --- | --- |
| `FreeRTOS-interface/Model.py` | `Model.reload_droplet_model()` | Current manager/camera recreation destroys in-memory calibration context; durable memory must survive this |
| `FreeRTOS-interface/Model.py` | `StockSolutionManager._make_stock_id()` | Existing stable stock key source; likely should become the canonical reagent-memory key input |
| `FreeRTOS-interface/Model.py` | `PrinterHead` class (`__init__` or a new stable-id accessor) | Current printer heads have no stable `serial`/`id` field, so head-specific memory is weak |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `CalibrationManager._safe_get_stock_solution()` | Currently uses reagent name, not stable stock identity |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `CalibrationManager._safe_get_printer_head_id()` | Currently falls back to `str(ph)`; needs a real head identifier |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `CalibrationManager._build_recorder_meta()` | Recorder metadata is where stable reagent/head keys should be attached to every run |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `CalibrationManager.begin_session()` | Run envelope currently stores weak `stock_solution` / `printer_head_id` fields |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `CalibrationManager.onCalibrationDataUpdated()` | Central place where completed calibration results are normalized and persisted |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `CalibrationManager.get_last_characterization_mean_nL()` | Current lookup is only "latest value for current stock"; reagent memory would need richer selection logic |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `CalibrationManager.get_pressure_sweep_summary_rows()` | Current summary filter uses only `run["stock_solution"] == cur_stock`; this ignores head identity and concentration-specific distinctions |
| `FreeRTOS-interface/CalibrationClasses/View.py` | `DropletImagingDialog._bridge_get_current_reagent_name()` | UI bridge currently reduces current context to reagent name |
| `FreeRTOS-interface/CalibrationClasses/View.py` | `DropletImagingDialog._preferred_char_mean_nL()` | Good insertion point for "use remembered best/recommended prior calibration" logic |
| `FreeRTOS-interface/CalibrationClasses/View.py` | `DropletImagingDialog._bridge_preview_from_last_char()` | Current preview source selection would need to understand reagent-memory entries |
| `FreeRTOS-interface/Model.py` | `ExperimentModel.find_option_by_reagent_name()` | Uses reagent display name; may be ambiguous for durable memory lookups |
| `FreeRTOS-interface/Model.py` | `ExperimentModel.find_key_for_reagent()` | Better design-side lookup seam because it can disambiguate with `group_name` |

## Where Rich Per-Test Observations Should Be Recorded

### Best location conceptually

Record them at two levels:

1. Process/event level while the calibration is running
2. Normalized cross-run observation level when a step completes

That means:

- process classes keep emitting dense frame/decision data
- `CalibrationManager` forwards them to a durable observation store
- a separate persistence service normalizes them by stable reagent/head keys

### Concrete seams to modify for full observation logging

| File | Function / method | Why it matters |
| --- | --- | --- |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `CalibrationManager.onCalibrationDataUpdated()` | Central summary hook for every completed calibration step |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `CalibrationManager._try_append_flat_rows_from_payload()` | Existing normalization hook for per-droplet rows; currently not called |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `CalibrationManager._build_recorder_meta()` | Attach stable reagent/head/session context to every observation stream |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `CalibrationManager.record_analysis()` | Central analysis-event sink |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `CalibrationManager.record_capture_frame()` | Central capture-image sink |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `BaseCalibrationProcess._record_event()` | Lowest common event hook across all calibration FSMs |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `BaseCalibrationProcess._record_analysis()` | Lowest common analysis hook across processes |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `BaseCalibrationProcess._record_capture()` | Lowest common capture hook across processes |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `BaseCalibrationProcess._record_error()` | Needed for failed-observation analysis, not just successful runs |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `DropletSearchCalibrationProcess._save_capture()` | Per-frame raw capture metadata in the manual search/characterization path |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `DropletSearchCalibrationProcess._append_analysis()` | Per-frame derived observation stream in the manual path |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `DropletSearchCalibrationProcess.onAnalyze()` | Search-stage contour outcome and center data |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `DropletSearchCalibrationProcess.onCharacterization()` | Per-frame volume, circularity, focus data |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `DropletSearchCalibrationProcess.onAnalyzeCharacterization()` | Final batch-level mean/CV and replicate arrays |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `PressureSweepCharacterizationProcess._record_pressure_sweep_analysis()` | Already the richest structured per-pressure/per-frame hook in the codebase |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `PressureSweepCharacterizationProcess._record_pressure_result()` | Produces normalized per-pressure batch records, including invalid reasons and quality ratios |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `PressureSweepCharacterizationProcess.onAnalyzeBatch()` | Final accepted/invalid batch decision per pressure |
| `FreeRTOS-interface/CalibrationClasses/Model.py` | `DropletCameraModel.append_analysis_record()` | Existing camera-side JSONL writer for high-volume append-only observations |
| `FreeRTOS-interface/Model.py` | `Model.record_image_metadata()` | Legacy CSV metadata writer; should either be aligned with current save paths or retired |

### Best current producer for rich observations

If the goal is "record everything so it can be analyzed across many reagent/head combinations later", the best existing producer is `PressureSweepCharacterizationProcess`. It already records:

- invalid-frame ratios
- multiple-droplet hits
- stream-like detections
- accepted vs captured replicate counts
- per-pressure validity decisions

That is a better starting point than the coarse summary rows in `calibration.json`.

## Recommendation: Which Layer Should Own Persistence?

Recommended owner: separate persistence service

Reasoning:

- `UI/view`: should not own data durability
- `controller`: should not own domain persistence
- `model` alone: owns durable experiment state, but not the details of the calibration FSM
- `calibration manager` alone: currently mixes orchestration and persistence, and is recreated on each imager reload

Recommended split:

- `CalibrationManager` remains the orchestration producer
- a separate persistence service handles:
  - stable key construction
  - run/result indexing
  - per-observation logging
  - lookups such as "best prior calibration for this reagent/head combo"
- `ExperimentModel` remains the consumer when the user decides to preview/apply a droplet-volume update

If forced to keep persistence inside an existing layer, `ExperimentModel` is the least bad durable owner. But the clean architecture is a separate service.

## Existing Persistence Mechanisms Already in Use

| Format | Path / producer | Current use |
| --- | --- | --- |
| JSON | `experiment_design.json` via `ExperimentModel.save_experiment()` | Durable experiment metadata and factor definitions, including `OptionSpec.droplet_nL` |
| JSON | `progress.json` via `ExperimentModel.create_progress_file()` | Runtime well/progress snapshot |
| JSON | `calibration.json` via `CalibrationManager.begin_session()` and `_save_atomic()` | Per-run calibration envelopes and per-phase step payloads |
| JSONL | `calibration_recordings/.../events.jsonl` via `CalibrationProcessRecorder.append_event()` | Per-process event log |
| JSONL | `calibration_recordings/.../analysis.jsonl` via `CalibrationProcessRecorder.append_analysis()` | Per-process analysis log |
| JSON | `calibration_recordings/.../run_meta.json` | Per-process run metadata |
| JSON | `calibration_recordings/.../verdict.json` | Operator/system verdict for a process run |
| Image files | `calibration_recordings/.../captures/*` via `CalibrationProcessRecorder.save_capture_image()` | Per-process raw/derived captures |
| JSONL | `droplet_imager_captures/.../metadata.jsonl` via `DropletCameraModel.start_saving()` / `update_image()` | Camera-side capture metadata stream |
| JSONL | `droplet_imager_captures/.../analysis.jsonl` via `DropletCameraModel.append_analysis_record()` | Camera-side analysis stream |
| JSON | `droplet_search_summary.json` via `DropletSearchCalibrationProcess.onAnalyzeCharacterization()` | Manual droplet-search batch summary |
| CSV | `key.csv` via `ExperimentModel.create_key_file()` | Well-to-design mapping |
| CSV | `concentration_key.csv` via `ExperimentModel.create_concentration_key_file()` | Well concentration map |
| CSV | `uploaded_design.csv` via `_materialize_uploaded_design_csv()` | Materialized uploaded/manual design source |
| CSV | `metadata.csv` via `Model.record_image_metadata()` | Legacy image metadata writer; appears separate from the newer JSONL camera-save path |
| JSONL | `records.jsonl` and JSON `session_meta.json` in `NozzlePositionChecklistStore` | Checklist-driven nozzle image dataset capture, adjacent to but separate from the droplet-volume pipeline |
| JSON | `FreeRTOS-interface/Presets/*.json` | Settings, colors, locations, plates, printer-head colors, step conversion |
| Joblib / `.pkl` | `FreeRTOS-interface/Presets/Predictive_models*` and legacy mass calibration loaders | Legacy predictive/resistance model loading |

Additional note:

- `FreeRTOS-interface/Presets/Reagents.json` exists in the repo, but repo search did not find an active load path using it in the current application flow.

Search results found no SQLite usage in the application code path inspected.

## Key Findings for Reagent Memory and Cross-Run Analysis

1. The modern droplet-volume path is camera-based and centered on `DropletImagingDialog` plus `CalibrationManager`, not on the `Calibrate Pressure` button.
2. Modern calibration stores useful outputs, but identity is weak:
   - stock is effectively keyed by reagent name in several places
   - printer head identity is not stable
3. The current summary table is grouped by current `stock_solution` string only, not by reagent concentration plus printer-head identity.
4. The calibration manager is recreated every time the imager is opened, so durable reagent memory should not live only in manager instance state.
5. Modern calibration does not write back into `PrinterHead.set_calibration_data()`. Only the legacy mass path does.
6. The best existing hook for rich per-test logging is `PressureSweepCharacterizationProcess._record_pressure_sweep_analysis()`, with `CalibrationManager.onCalibrationDataUpdated()` as the best normalization point.
7. `ExperimentModel.apply_droplet_volume_for_option()` updates design state and keys, but not `experiment_design.json` unless the user later saves.
8. Legacy mass persistence is incomplete: `MassCalibrationModel.save_calibration_data()` is currently `pass`.
9. Persistence rehydration is partial: `CalibrationManager.get_emergence_time()` reads the latest persisted `droplet_emergence` step, but background image, nozzle center, primary pressure band, and trajectory result are otherwise kept as manager instance state.

## Bottom-Line Recommendation

For a reagent memory system and durable cross-run calibration analytics:

- keep process orchestration in `CalibrationManager`
- add a separate persistence/indexing service under the model/domain layer
- key records by stable `stock_id` plus a real printer-head identifier
- feed that service from:
  - `CalibrationManager.onCalibrationDataUpdated()`
  - `BaseCalibrationProcess._record_*()` hooks
  - the richer per-pressure hooks already present in `PressureSweepCharacterizationProcess`

That is the cleanest fit with the code as it exists today.
