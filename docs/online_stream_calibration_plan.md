# Online Stream Calibration Plan

## Status

- Date: 2026-04-06
- Scope: Phase 1 planning only
- Goal: convert the offline stream-analysis pipeline into a staged online calibration flow for the droplet camera imager

## Purpose

The current `tools/stream_analysis` pipeline assumes a dense offline time course and then derives:

- per-frame nozzle position
- a filled stream silhouette
- visible volume `V(t)`
- the steady flow-rate fit
- field-of-view exit timing
- tail-start timing

For online calibration we want the same final outputs, but with far fewer captured frames so reagent waste stays low. The calibration target is a loaded head / reagent pair at a fixed print pressure and pulse width.

The proposed online process should answer two questions:

1. What steady flow rate should be used for the visible stream body?
2. When does the tail actually begin, so the steady flow should stop contributing to predicted volume?

## What The Offline Pipeline Currently Does

The implemented offline flow is:

1. Stage 0 indexes the run and reconstructs flash delays from recorder metadata.
2. Stage 1 applies direct grayscale thresholding in a central ROI.
3. Stage 2 tracks nozzle position frame by frame and segments grip-refresh shifts.
4. Stage 3 extracts the attached primary silhouette below the tracked nozzle and also keeps accepted detached components.
5. Stage 4 integrates visible volume from the silhouette, then marks frames untrusted once accepted fluid reaches the bottom-of-FOV trigger zone.
6. Stage 5 derives a near-nozzle width trace, finds the steady window, fits the steady `V(t)` slope, and detects tail onset from width decline.
7. Stage 6 summarizes the run and compares the partial predicted volume against gravimetric measurements.

The parts that matter most for the online design are:

- Stage 1-4 give us the per-frame geometry needed to measure volume from a single image.
- Stage 5 steady fitting currently depends on a dense, contiguous time course.
- Stage 5 tail onset currently depends on a dense width trace and a confirmation/backtrack workflow.
- Stage 6 is valuable as a prior-mining layer: it tells us where steady flow and tail onset usually occur for a given operating condition.

## Evidence From The Existing Offline Dataset

Reference dataset used for this planning pass:

- `FreeRTOS-interface/Experiments/Stream_characterization-20260327_225650`

Reference command used to regenerate the current late-stage outputs:

```powershell
.\env\Scripts\python.exe tools\run_stream_analysis.py summary --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650"
```

The regenerated summary covered 26 runs and 8 pressure / pulse-width conditions.

Current limitation of those priors:

- this dataset is the current water stream-characterization set, so the absolute timings should be treated as initial priors, not universal reagent-independent constants

### Overall timing medians

- `flow_fit_start_delay_from_emergence_us`: `550 us`
- `steady_start_delay_from_emergence_us`: `600 us`
- `steady_end_delay_from_emergence_us`: `950 us`
- `flow_fit_end_delay_from_emergence_us`: `1475 us`
- `fov_exit_delay_from_emergence_us`: `1625 us`
- `tail_start_delay_from_emergence_us`: `4200 us`
- `tail_confirmation_delay_from_emergence_us`: `4400 us`
- `tail_confirmation - tail_start`: `200 us`
- `tail_start_to_tail_peak_delta_us`: `250 us`

### Condition-specific timing medians

These are more useful than the global medians because the flow window shifts with pressure.

| Pressure | PW (us) | Flow-fit start (us) | Flow-fit end (us) | FOV exit (us) | Tail start (us) |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0.65 bar | 2500 | 625 | 1600 | 1750 | 3250 |
| 0.65 bar | 3000 | 550 | 1600 | 1750 | 4150 |
| 0.65 bar | 3500 | 550 | 1550 | 1700 | 5050 |
| 0.75 bar | 2500 | 550 | 1400 | 1550 | 3350 |
| 0.75 bar | 3000 | 450 | 1350 | 1500 | 4300 |
| 0.75 bar | 3500 | 600 | 1500 | 1650 | 5150 |
| 0.85 bar | 2500 | 500 | 1200 | 1350 | 3400 |
| 0.85 bar | 3000 | 500 | 1200 | 1350 | 4400 |

Key observations:

- The steady / flow-fit window begins much earlier than tail behavior and sits in a relatively narrow band around `500-700 us` after emergence.
- FOV exit depends strongly on pressure; higher pressure leaves less usable time before the stream reaches the bottom of the image.
- Tail start is much later and scales mainly with pulse width, but pressure still shifts it enough that condition-specific priors are preferable.
- The selected tail start is subtle. In the current offline summary, the chosen tail-start width drop is usually only about `1-3%` below the steady plateau, while the confirmation rule happens later.

### Sparse replay check for flow-rate capture count

I replayed the dense offline traces with sparse subsampling to see whether five unique delays are enough to reproduce the offline steady-rate fit.

Results:

- Five delays at `650, 850, 1050, 1250, 1450 us` after emergence gave:
  - median absolute relative steady-rate error about `0.75%`
  - max absolute relative error about `3.1%`
- Four-delay schedules were noticeably worse:
  - median error about `1.0-1.4%`
  - max error about `5.8-5.9%`

Important limitation:

- This replay used the offline-derived geometry, so it does not include new capture noise, focus drift, or segmentation failures.
- It still strongly suggests that five unique delays is a reasonable target and that dropping to four unique delays is much riskier.

## What Should Transfer Well To An Online Process

These offline ideas should carry over cleanly:

- Direct grayscale thresholding in a constrained ROI. The offline pipeline already prefers this over background subtraction, and nothing in Phase 1 suggests we should change that.
- Per-frame silhouette-to-volume measurement. Once the nozzle location is known, a single frame can be processed independently through silhouette extraction and axisymmetric volume integration.
- Using a near-nozzle width baseline from attached-primary geometry. This is exactly the right reference signal for tail work.
- Using emergence-relative time rather than raw flash delay. That keeps the online process aligned with existing priors and offline analytics.
- Using condition-specific priors mined from prior calibrations. The current dataset already shows that pressure and pulse width matter enough to justify this.

## What Looks Fragile If Reused Unchanged

These parts of the offline implementation should not be copied directly into the online sparse-capture flow.

### 1. The current steady-window finder assumes a dense time course

The current Stage 5 steady fit expects:

- contiguous candidate windows
- at least 8 steady frames
- rolling-median width smoothing
- a wider flow-fit window after plateau seeding
- optional backfill and outlier pruning

That works offline because each run has 121 frames at 50 us spacing. It is not the right primitive for 5 delays with a few replicates each.

Recommendation:

- reuse the offline outputs as priors for where to sample
- do not reuse `_recompute_steady_fit_from_feature_rows(...)` as the online steady-window detector
- online flow-rate fitting should be a direct robust line fit over intentionally chosen sparse delays

### 2. Direct tail-start detection is much more fragile than flow-rate fitting

The current offline tail-start logic works because it has:

- a dense smoothed width trace
- a confirmation rule over consecutive frames
- shoulder-aware backtracking
- descriptor scoring over a candidate window
- access to the tail shrink-rate peak

In the current dataset, the final chosen tail start usually happens before the coarse width-loss confirmation. The selected onset is often only `1-3%` below the steady width plateau. That is a small signal and is likely to be sensitive to:

- focus drift
- threshold drift
- nozzle-center drift
- silhouette fill variation
- occasional detached droplets near the nozzle

Recommendation:

- use sparse online captures to detect a later, more robust tail trigger
- infer the actual tail start from that trigger using priors plus local backfill frames
- do not expect single-step sparse sampling to directly identify the final onset frame without refinement

### 3. The current FOV-exit trigger is conservative for online flow-rate sampling

Offline trust currently ends when accepted fluid near the bottom of the ROI is detected, and accepted fluid includes:

- `attached_primary`
- `detached_accepted`

That is reasonable offline because Stage 4 wants a trustworthy total visible-volume trace. For online flow-rate fitting, this can be slightly too conservative because a detached component may hit the bottom before the attached body is unusable for fitting.

Recommendation:

- keep the current Stage 4 bottom-of-FOV logic as a hard stop / QC signal
- but use an earlier online safety margin for advancing delays
- prefer the attached-primary bottom distance for the phase-1 stepping decision
- treat accepted detached components as a warning that the flow point may be too late for rate fitting

## Phase-1 Assessment Of The Proposed Two-Phase Online Approach

### What is already strong in the proposed approach

- Splitting the process into flow-rate first and tail timing second is the right decomposition.
- Reusing emergence time as the timing anchor is consistent with the offline pipeline.
- Measuring volume from a small set of well-chosen delays is much better than trying to reproduce the whole offline time course online.
- Reusing the phase-1 width baseline for phase-2 tail work is aligned with the existing offline logic.
- Stopping the flow-rate phase before the bottom of the FOV is the right reagent-saving move.

### What needs adjustment

- The online flow-rate phase should not wait to discover the steady region from scratch; it should start from priors.
- Tail phase should not start from a generic "middle duration" alone when exact condition priors exist. It should start from a condition-specific tail-start prior, or from an interpolated prior if the exact condition is missing.
- Tail phase should not rely on one frame per step all the way through the trigger region. Coarse single-frame scouting is fine early, but once width begins to move, local confirmation or bracketing frames are needed.
- Three replicates at every tail-search delay is probably unnecessary. Replicates are more valuable near the suspected onset than far from it.

## Recommended Online Calibration Design

### Session setup

Before either phase starts:

- Assume nozzle is already centered and in focus.
- Assume emergence time is already known.
- Load priors for the exact `(head, reagent, pressure, pulse width)` pair when available.
- If no exact prior exists, fall back to nearby condition priors plus a conservative generic schedule.

Per-session state that should be cached:

- nozzle center
- ROI and corridor bounds
- emergence-relative priors
- steady-width prior
- last successful flow-rate fit
- last successful tail-start estimate

### Phase 1: Flow-rate calibration

Recommended default:

- capture 5 unique delays
- capture 3 images per accepted delay
- fit the steady slope from the accepted volumes only

Recommended default generic schedule:

- `650, 850, 1050, 1250, 1450 us` after emergence

Why this schedule:

- it sits well inside the observed offline flow-fit window
- it replayed well against the offline dense dataset
- it is less risky than a 4-delay schedule

Better schedule when exact priors exist:

- start from the condition-specific median `flow_fit_start_delay_from_emergence_us`
- use `200 us` steps
- collect 5 unique delays unless the online stop rule triggers earlier

Recommended phase-1 acceptance loop:

1. Capture the delay.
2. Run nozzle validation, silhouette extraction, and volume measurement.
3. Reject and retry the same delay if the frame fails basic geometry QC.
4. Once 2 or 3 good replicates exist, compute:
   - median volume
   - replicate spread
   - median attached width
5. Advance only if the attached-primary body is still comfortably above the bottom safety margin.
6. After 5 accepted delays, fit a robust line to delay vs volume.

Recommended phase-1 QC rules:

- Require `silhouette_status == ok`.
- Require an attached primary component.
- Reject frames with obviously low nozzle confidence or missing cutoff geometry.
- Stop stepping later if the attached body approaches the bottom safety margin.
- Treat detached-component appearance as a warning that the point may be too late for the flow fit.

Recommended reagent-saving optimization:

- Consider `2 replicates by default, auto-promote to a 3rd only if spread exceeds a threshold`.

This is a good optional optimization because the offline replay suggests the five unique delays matter more than extra repeats at every delay. If statistical uniformity is more important than reagent savings, keep the fixed 3-replicate plan.

### Phase 2: Tail-start calibration

Phase 2 should reuse:

- the phase-1 steady-width baseline
- the condition-specific tail-start prior
- the condition-specific confirmation-to-onset lag prior

Recommended approach:

1. Start coarse search a little before the expected tail start, not from the start of the whole middle phase.
2. Use single captures, or at most duplicate captures, while width remains clearly on the plateau.
3. Detect a robust tail trigger first.
4. Then backfill or bracket the onset region with smaller delay steps.

Recommended coarse-search starting point:

- `tail_start_prior - 300 us` to `tail_start_prior - 400 us`

Recommended coarse step:

- `100 us`

Recommended coarse trigger:

- a clear width reduction relative to the steady baseline
- or sustained shrink-rate increase
- or detached behavior near the nozzle that matches the late-stage transition

Recommended refinement after the first trigger:

- step back into the trigger window with `50 us` spacing
- add local replicate captures only around the candidate onset bracket

Reason for this two-step tail search:

- the offline tail start is subtle
- the offline confirmation event typically occurs about `100-300 us` after the selected tail start
- the width peak / shrink-rate peak is typically about `150-350 us` after the selected tail start

That means the online process should treat the first strong trigger as a landmark, not as the final answer.

## Recommended Online Outputs

The online calibration should save enough information to replay or audit the result later.

Minimum saved outputs:

- per-capture image path
- emergence-relative delay
- nozzle QC result
- silhouette QC result
- attached width
- visible volume
- replicate grouping
- selected flow-rate fit
- selected tail-trigger delay
- selected tail-start estimate
- priors used
- any fallback or warning flags

This will let the later `CalibrationManager` integration reuse the same calibration-memory and replay ideas already present elsewhere in the repo.

## Recommended Safety And Robustness Changes

- Use exact-condition priors whenever possible. Pressure dependence is large enough that pulse-width-only priors are not sufficient.
- Keep a larger online bottom-of-FOV safety margin than the offline `32 px` trust boundary.
- Do not rerun full time-course nozzle tracking online if the nozzle is already locked in the imager. Revalidate the nozzle, but do not make every frame rediscover it from scratch unless QC fails.
- Fail early when QC is bad instead of continuing to spend reagent on low-confidence frames.
- Save every accepted online calibration frame so the sparse procedure can still be reviewed offline.
- Update priors after each successful run so the online process becomes more condition-specific over time.

## Phase-1 Conclusions

- Your proposed split into flow-rate then tail-start is the right direction.
- The current offline Stage 1-4 image geometry work is a solid base for online single-frame measurement.
- The current offline Stage 5 logic is valuable mainly as a prior source and validation target, not as a direct online algorithm.
- Five unique flow-rate delays looks well justified by the current dataset.
- Tail-start detection should use a coarse-to-fine search, because the final onset signal is too subtle to trust from sparse one-pass stepping alone.

## Phase-2 Preparation Notes

When moving into the implementation-planning pass for `CalibrationManager`, Phase 2 should study:

- how current calibration processes request captures
- where per-capture QC can be inserted
- how priors are loaded and written back
- how multi-step calibration state is persisted
- how a sparse calibration run can save enough replay data without pretending to be a full offline time course

## Phase-2 Findings: Calibration Framework Integration

### Current Launch Path

The existing droplet-imager calibration launch path is already a good fit for an online stream calibration:

- `FreeRTOS-interface/CalibrationClasses/View.py`
  - UI buttons call `toggle_start_*` methods.
- `FreeRTOS-interface/Controller.py`
  - `start_*` methods mostly forward directly into `CalibrationManager`.
- `FreeRTOS-interface/CalibrationClasses/Model.py`
  - `CalibrationManager.start_*` methods call `_try_start_process(...)`.
  - `_try_start_process(...)` applies any supported prior seeding, checks `missing_requirements(...)`, instantiates the process, and calls `start_active_calibration()`.
  - `start_active_calibration()` auto-starts a calibration session if needed, wires process signals, starts recorder output, and starts the process state machine.
- `BaseCalibrationProcess`
  - owns the `QStateMachine`
  - requests settings through `_request_settings_with_recording(...)`
  - requests images through `_capture_with_policy(...)`
  - records captures, decisions, and analysis into the process recorder
- `Controller.connect_droplet_camera_signals()`
  - bridges manager capture/move/settings signals into machine commands
  - routes completed captures back through `_on_image_captured()`
  - resolves the pending per-capture callback used by the process state machine

The practical call path for a new process is:

`View button -> Controller.start_online_stream_calibration(...) -> CalibrationManager.start_online_stream_calibration(...) -> _try_start_process(OnlineStreamCalibrationProcess) -> BaseCalibrationProcess/QStateMachine -> manager request signals -> Controller handlers -> machine/camera -> Controller._on_image_captured() -> process callback -> calibrationDataUpdated/calibrationCompleted -> CalibrationManager persistence`

### Best Architectural Fit

The best fit is a single new calibration process, not two separately launched calibrations.

Recommended shape:

- class name: `OnlineStreamCalibrationProcess`
- phase name: `online_stream_calibration`
- one UI entry point
- one recorder run
- one result payload
- two internal stages:
  - `flow_rate`
  - `tail_start`

Why a single process is preferable:

- The tail phase depends directly on the flow-phase outputs:
  - steady-state width baseline
  - flow-rate fit
  - validated nozzle/silhouette QC
- The same background, emergence reference, and nozzle center should be reused across both phases.
- A single process keeps the sparse capture set in one recorder directory and one `calibration.json` step payload.
- It avoids extra UI complexity and avoids having to persist an intermediate handoff artifact between two separate calibration launches.

If expert-only debugging is needed later, the internal phases can still be exposed as separate developer entry points, but they do not need to be the primary user-facing workflow.

### Existing Pieces To Reuse Directly

The current framework already has most of the scaffolding needed for this feature.

Strong reuse candidates:

- `BaseCalibrationProcess`
  - capture retries
  - settings callbacks
  - move callbacks
  - timeout guards
  - recorder hooks
- `CalibrationManager.onCalibrationDataUpdated(...)`
  - automatically persists the final payload into `calibration.json`
- `CalibrationProcessRecorder`
  - already stores run metadata, events, analysis rows, verdicts, and captured images
- `DropletEmergenceCalibrationProcess`
  - good example of:
    - adaptive replicate use
    - iterative search
    - restoring original settings
    - writing emergence-centered nozzle image position back into the manager
- `PreBreakupMorphologyCalibrationProcess`
  - strongest existing example of a coarse-to-fine scout followed by a more targeted decision stage
  - useful model for the tail-start search
- `PreBreakupDatasetAcquisitionProcess`
  - strongest existing example of:
    - condition-oriented sparse acquisition
    - per-frame metadata
    - JSONL sidecar outputs in the recorder directory
    - replay-friendly storage
- calibration-memory advisory prior machinery in `CalibrationManager`
  - useful foundation for loading expected flow/tail timing priors and writing back new observations

### Existing Pieces That Should Not Be Reused Unchanged

The current `DropletTimecourseProcess` is not the right template for the new calibration.

It is useful mainly as proof that the manager/controller/camera callback path works, but it is too thin for the new job because it:

- assumes a dense contiguous sweep
- has no `missing_requirements(...)` readiness hook
- is not included in `CalibrationManager._emit_readiness()`
- does not save structured per-frame measurements beyond success/failure at each delay
- does not use priors
- does not perform online stop conditions such as:
  - bottom-of-FOV safety stop
  - replicate QC stop
  - tail-trigger bracket refinement

So the new process should borrow its basic capture loop only conceptually, not structurally.

### Integration Gaps And Fragilities To Plan Around

#### 1. Pulse-width settings key mismatch

`Controller.handle_settings_change_request(...)` applies `print_pulse_width`, not `print_width`.

That matters because some newer calibration code currently builds settings dictionaries with `print_width`. For the online stream calibration, we should avoid inheriting that ambiguity. Recommended approach:

- standardize the new process on controller-facing keys such as `print_pulse_width`
- or add a controller alias for `print_width` if we want broader cleanup

The safer short-term plan is to make the new process explicit and use the controller-facing key.

#### 2. Readiness wiring is opt-in, not automatic

Adding a new process is more than adding `missing_requirements(...)`.

For a new UI-facing process we will also need to update:

- `CalibrationManager._emit_readiness()`
- `CalibrationManager.start_calibration_queue()` mapping if queue support is desired
- `CalibrationManager.PHASE_ALIASES`
- `FreeRTOS-interface/CalibrationClasses/View.py:on_readiness_changed(...)`

Without that, the process can still exist, but the UI will not present a clean enabled/disabled readiness state.

#### 3. UI button lifecycle touches multiple places

If Phase 3 adds a dedicated button, it will need to be registered in several view helpers, not just the layout:

- button creation and toggle handler
- `reset_calibration_buttons()`
- flash-fault disable list in `_apply_flash_safety_ui_state()`
- stream-capture lockout list in `_sync_stream_capture_panel_state()`
- readiness mapping in `on_readiness_changed(...)`

That is manageable, but it means UI plumbing is a little more scattered than the main process plumbing.

#### 4. Cross-step state is partly in-memory only

`CalibrationManager.get_emergence_time()` can recover emergence timing from persisted step payloads, but other prerequisites such as:

- background image
- nozzle center image position
- emergence-derived real nozzle center

are still mainly manager instance state.

Because `Model.reload_droplet_model()` recreates both `DropletCameraModel` and `CalibrationManager`, the new online stream calibration should not assume all prerequisites survive closing and reopening the imager. Practical implication:

- treat background capture as something the new process can cheaply refresh
- treat nozzle/emergence references as prerequisites that may need to be re-established or revalidated

#### 5. Normalized per-frame rows are not yet written into `calibration.json`

`CalibrationManager.onCalibrationDataUpdated(...)` persists the full step payload, but its `flat_measurements` normalization helper is still commented out.

That means the safest replay path for the new process is the same pattern used by `PreBreakupDatasetAcquisitionProcess`:

- keep the final summary in `calibration.json`
- keep detailed per-frame rows in recorder-side JSONL artifacts

If we later want summary-table or memory-store queries over sparse stream captures, we can either:

- revive/adapt `flat_measurements`
- or teach the calibration-memory store to consume the recorder-side artifacts directly

#### 6. Automatic prior seeding currently targets pressure processes only

`CalibrationManager._prepare_calibration_memory_prior_application(...)` currently auto-seeds only:

- `PressureBandCalibrationProcess`
- `PressureCalibrationProcess`

So the new stream calibration cannot rely on existing auto-seed behavior as-is. It will need one of:

- an expanded prior-application path for `OnlineStreamCalibrationProcess`
- or an explicit in-process prior lookup step that records which priors were used

For this feature, the second option is likely cleaner because we need more than one seeded value:

- starting flow delay
- flow delay spacing
- expected FOV exit region
- tail coarse-search start
- tail coarse step

### Recommended New Process Shape

Internally, the new process should look more like `PreBreakupMorphologyCalibrationProcess` plus `PreBreakupDatasetAcquisitionProcess` than like `DropletTimecourseProcess`.

Suggested internal states:

1. `prepare_context`
2. `capture_background`
3. `load_or_build_priors`
4. `plan_flow_schedule`
5. `capture_flow_replicates`
6. `fit_flow_rate`
7. `plan_tail_search`
8. `capture_tail_search`
9. `refine_tail_start`
10. `restore_settings`
11. `finalize`

Expected data flow between the two internal phases:

- Flow phase produces:
  - steady width baseline
  - flow-rate fit
  - per-delay QC
  - stop reason for the flow schedule
- Tail phase consumes:
  - width baseline
  - predicted tail prior window
  - previous accepted nozzle/silhouette QC thresholds

### Recommended Persistence Shape

The current framework supports a good split between:

- summary payload in `calibration.json`
- detailed replay artifacts in the recorder directory

Recommended final payload shape:

```json
{
  "measurements": [
    {
      "phase": "flow_rate",
      "delay_us": 0,
      "delay_from_emergence_us": 0,
      "replicate_index": 1,
      "volume_nl": 0.0,
      "width_px": 0.0,
      "qc_pass": true,
      "image_ref": {}
    }
  ],
  "result": {
    "condition": {
      "print_pressure_psi": 0.0,
      "print_pulse_width_us": 0
    },
    "priors": {},
    "flow_phase": {},
    "tail_phase": {},
    "predicted_stream_duration_us": 0,
    "predicted_volume_nl": 0.0,
    "warnings": []
  }
}
```

Recommended recorder-side detailed artifacts:

- `captures/` images already handled by the recorder
- `frames.jsonl`
  - one row per accepted or rejected capture
- `plan_snapshot.json`
  - actual sparse schedule used
- optional `flow_fit.json`
  - fitted slope/intercept and diagnostics
- optional `tail_fit.json`
  - trigger bracket and refined onset estimate

This mirrors the successful storage strategy already used by `PreBreakupDatasetAcquisitionProcess`.

### Files Likely Needed In Phase 3

If we implement this in the existing architecture, the likely file set is:

- `FreeRTOS-interface/CalibrationClasses/Model.py`
  - new `OnlineStreamCalibrationProcess`
  - new `CalibrationManager.start_online_stream_calibration(...)`
  - readiness, phase alias, and queue mapping updates
  - optional prior-lookup/result-cache helpers
- `FreeRTOS-interface/Controller.py`
  - new `start_online_stream_calibration(...)`
  - possibly a small settings-key compatibility cleanup
- `FreeRTOS-interface/CalibrationClasses/View.py`
  - new button/toggle handler if we expose this in the UI immediately
  - readiness and button-state plumbing
- `docs/online_stream_calibration_plan.md`
  - this planning document

`FreeRTOS-interface/Model.py` likely does not need structural changes beyond the existing manager instantiation path unless we decide to expose the latest online stream result outside the calibration manager.

### Phase-2 Conclusion

The existing calibration framework is capable of supporting the new staged online stream calibration with relatively little architectural change.

The most promising implementation path is:

- a new single `BaseCalibrationProcess` subclass
- internal two-phase state machine
- recorder-rich sparse capture logging modeled on `PreBreakupDatasetAcquisitionProcess`
- coarse-to-fine decision logic modeled on `PreBreakupMorphologyCalibrationProcess`
- explicit prior handling rather than reusing the current `DropletTimecourseProcess`

The main fragilities to account for in Phase 3 are:

- pulse-width settings key consistency
- readiness/UI plumbing for a new button
- dependence on in-memory manager state
- richer per-frame persistence than `calibration.json` alone currently provides

## Phase-3 Implementation Contract

This section freezes the recommended v1 implementation contract so the next step can be a staged execution plan instead of another open-ended design pass.

### V1 Scope

V1 should implement one new sparse online calibration for one already-loaded condition:

- one printer head / reagent pair
- one print pressure
- one print pulse width
- one known emergence time
- one calibration run started from the droplet imager

V1 should include:

- one new calibration process: `OnlineStreamCalibrationProcess`
- one user-facing launch path in the droplet imager
- one fresh background capture at process start
- sparse flow-rate measurement
- sparse tail-start measurement
- recorder-side replay artifacts for every accepted capture
- one final summary payload written into `calibration.json`

V1 should explicitly defer:

- automatic rerunning of nozzle position, focus, or emergence inside the process
- `Calibrate All` queue integration
- multi-condition batch calibration across multiple pressures or pulse widths
- full calibration-memory auto-seeding through `CalibrationManager._prepare_calibration_memory_prior_application(...)`
- adaptive algorithm tuning from operator controls in the first UI pass
- automatic recovery after the imager has been reloaded and prerequisites are stale or missing

### Frozen Process Contract

#### Process identity

- class: `OnlineStreamCalibrationProcess`
- phase: `online_stream_calibration`
- manager entry point: `CalibrationManager.start_online_stream_calibration(...)`
- controller entry point: `Controller.start_online_stream_calibration(...)`
- UI entry point: one new droplet-imager button

#### Required prerequisites

The process should refuse to start unless all of the following are available:

- nozzle center in machine coordinates
- emergence-derived nozzle center in image coordinates
- emergence time
- droplet camera availability
- active printer head / reagent context

The process should capture its own fresh background image after startup rather than depending on a previously cached background image.

#### Settings contract

The new process should use controller-facing setting keys only:

- `flash_delay`
- `num_droplets`
- `print_pressure`
- `print_pulse_width`

It should not use `print_width` in its settings requests.

#### High-level stages

The process should expose these user-visible internal stages:

1. `prepare_context`
2. `capture_background`
3. `load_priors`
4. `plan_flow_phase`
5. `capture_flow_phase`
6. `fit_flow_rate`
7. `plan_tail_phase`
8. `capture_tail_phase`
9. `refine_tail_start`
10. `restore_settings`
11. `finalize`

#### Completion contract

On success, the process should produce one final result containing:

- the exact condition used
- priors used
- flow schedule and accepted measurements
- fitted flow-rate summary
- tail coarse-search summary
- tail refinement summary
- predicted stream duration
- predicted volume
- warnings / fallback flags

On error or user stop, the process should:

- restore modified settings as best effort
- keep recorder-side partial artifacts
- not publish a final successful calibration result

### Frozen V1 Decision Policy

#### Flow phase

V1 should target exactly five unique flow delays when safety and QC allow.

Recommended default flow plan:

- start at `emergence_time + 650 us` when no exact-condition prior is available
- use `200 us` spacing
- target delays:
  - `+650 us`
  - `+850 us`
  - `+1050 us`
  - `+1250 us`
  - `+1450 us`
- capture `3` replicates per delay

If an exact-condition prior exists, V1 may shift the start delay and end delay, but it should still keep:

- `5` unique delays
- approximately `200 us` spacing
- `3` replicates per delay

Flow stop policy:

- stop early if the accepted silhouette is within `96 px` of the bottom of the FOV
- stop early if QC repeatedly fails at the current delay
- abort the flow fit if fewer than `3` delays produce accepted measurements

Flow measurement contract per accepted frame:

- nozzle QC pass/fail
- silhouette QC pass/fail
- attached width
- visible volume
- bottom-of-FOV clearance

Flow fitting contract:

- fit visible volume vs delay using only accepted flow-phase measurements
- compute:
  - `flow_rate_nl_per_us`
  - `flow_fit_delay_start_from_emergence_us`
  - `flow_fit_delay_end_from_emergence_us`
  - `steady_width_baseline_px`
  - flow-fit quality diagnostics

#### Tail phase

V1 should use a coarse-to-fine search, not a one-pass tail onset pick.

Recommended default tail coarse search:

- start at `tail_start_prior - 300 us` when an exact-condition prior exists
- otherwise start at `emergence_time + 3800 us`
- use `100 us` coarse steps
- use `2` replicates per coarse delay

V1 tail baseline:

- define `steady_width_baseline_px` as the median attached width from accepted flow-phase frames

V1 coarse tail trigger:

- first delay where median attached width is `<= 90%` of the steady-width baseline
- or a strong late-stage morphology flag indicating attached-width collapse / tail onset

V1 refinement contract:

- refine between the last coarse non-trigger delay and the first coarse trigger delay
- use `50 us` refinement spacing
- use `2` replicates per refined delay
- choose the earliest refined delay that satisfies either:
  - median attached width `<= 95%` of the baseline
  - confirmed late-stage morphology trigger

Tail failure policy:

- abort with warning if no coarse trigger is found within the allowed capture budget
- do not invent a tail start from extrapolation alone when no trigger was observed

#### Capture budget

V1 should be conservative about reagent use.

Recommended budget:

- nominal target: `<= 30` printed droplets/captures
- hard stop budget: `36` printed droplets/captures

If the process exceeds the hard-stop budget before reaching a valid result, it should fail with an explicit budget-exhausted warning.

### Frozen Persistence Contract

#### `calibration.json`

The final `online_stream_calibration` step payload should include:

- `measurements`
  - one compact row per accepted measurement
- `result`
  - `condition`
  - `priors`
  - `flow_phase`
  - `tail_phase`
  - `predicted_stream_duration_us`
  - `predicted_volume_nl`
  - `warnings`

#### Recorder-side artifacts

The recorder directory should be treated as the detailed replay source of truth.

Required artifacts:

- captured images in `captures/`
- `frames.jsonl`
  - one row per attempted capture, including accepted and rejected frames
- `plan_snapshot.json`
  - actual sparse schedules and thresholds used for this run

Recommended artifacts:

- `flow_fit.json`
- `tail_fit.json`

Every frame row should include enough metadata to reconstruct the decision path:

- phase
- delay
- delay from emergence
- replicate index
- QC results
- width
- visible volume when available
- trigger flags
- image reference

### Frozen Validation Contract

#### Offline replay validation

Before calling V1 complete, the sparse decision policy should be replayed against the existing offline stream dataset.

Acceptance targets for the current water dataset:

- flow-rate replay median absolute relative error `<= 2%`
- flow-rate replay worst-case absolute relative error `<= 5%`
- tail-start replay median absolute timing error `<= 200 us`
- tail-start replay worst-case timing error `<= 300 us`

If the tail-start targets are not met on replay, the implementation should still proceed only if:

- the failure mode is understood
- and the result is downgraded to an advisory tail estimate rather than a fully trusted calibration

#### Automated code-level validation

The implementation should add automated checks for:

- schedule construction
- prior fallback behavior
- result payload shape
- budget accounting
- flow-fit helper logic
- tail-trigger / refinement helper logic

The critical decision helpers should be structured so they can be unit tested without requiring live camera hardware.

#### Manual on-machine validation

Manual validation for a known stable water condition should confirm:

- the process starts only when prerequisites are met
- settings are restored after completion or stop
- the process stays within the expected capture budget
- accepted flow frames remain comfortably above the bottom-of-FOV guard
- the final predicted volume is in the expected range for that condition
- recorder artifacts are sufficient to review why a given run succeeded or failed

### Exit Criteria For Moving To Phase 4

Phase 3 is complete once the team agrees that:

- the v1 scope above is acceptable
- the fixed heuristics above are acceptable as a first pass
- the persistence contract is sufficient
- the validation targets are sufficient

At that point, the next step should be a staged implementation plan, not more high-level design.

## Phase-4 Staged Implementation Plan

The implementation should be split into small milestones that each end in a runnable or testable checkpoint. The main sequencing rule should be:

- build and test the pure decision logic before wiring the full UI
- build and test the process skeleton before adding the full algorithm
- complete the flow phase before adding the tail phase
- add priors and UI polish only after the base algorithm works reliably

### Current Implementation Status

As of `2026-04-06`, the staged plan has progressed as follows:

- Stage 1: implemented
  - `tools/stream_analysis/online_calibration.py` now contains the frozen policy defaults, prior normalization, schedule builders, budget helpers, prior-resolution artifact builders, and JSON-safe payload builders.
- Stage 2: implemented
  - `Controller.start_online_stream_calibration(...)`, `CalibrationManager.start_online_stream_calibration(...)`, and `OnlineStreamCalibrationProcess` now exist and can launch the process through the existing calibration framework.
- Stage 3: implemented
  - the process now performs flow-phase acquisition, per-frame QC, replay-friendly artifact writing, and sparse flow stop logic.
- Stage 4: implemented
  - the process now performs a sparse post-acquisition flow-rate fit, writes `flow_fit.json`, and emits a partial calibration result with flow-fit diagnostics.
- Stage 5: implemented
  - the process now performs the tail coarse search and interior refinement, writes `tail_fit.json`, and emits non-null predicted duration and predicted volume for captured runs.
- Stage 6: implemented
  - the droplet-imager now exposes `Calibrate Stream Volume`, and the button follows the existing readiness, flash-fault, and stream-capture safety rules.
- Stage 7: implemented
  - exact-condition online-stream priors are now looked up from calibration memory, recorded into run artifacts/results, exported in run summaries, and validated through replay tooling.

Current implemented behavior:

- the online stream calibration can now run end-to-end from the droplet imager through flow fit, tail detection, and final predicted stream volume
- successful runs now write:
  - `prior_resolution.json`
  - `plan_snapshot.json`
  - `frames.jsonl`
  - `flow_fit.json`
  - `tail_fit.json`
- exact pulse-width and exact print-pressure online-stream priors are reused automatically for matching reagent/head conditions
- unresolved or stopped runs fall back safely and do not become reusable priors
- replay tooling now supports recomputing stored online-stream results from recorder artifacts for validation and audit
- queue integration and cross-pressure prior borrowing remain intentionally deferred from v1

Latest automated validation completed for the implemented stages:

- `.\env\Scripts\python.exe -m pytest -q tests/test_stream_online_calibration_helpers.py tests/test_stream_online_prior_lookup.py tests/test_stream_online_replay.py tests/test_calibration_online_stream_process.py tests/test_calibration_memory_export_tools.py`
  - `59 passed`
- `.\env\Scripts\python.exe -m pytest -q tests/test_stream_online_fit.py tests/test_stream_online_fit_replay.py tests/test_stream_online_tail.py tests/test_stream_online_tail_replay.py tests/test_calibration_memory_integration.py tests/test_calibration_phase_aliases.py tests/test_calibration_process_recorder.py tests/test_calibration_recorder_toggle.py tests/test_calibration_online_stream_process.py`
  - `60 passed`

### Stage 1: Pure Helper And Schema Layer

Key changes:

- add pure helper functions or small helper classes for:
  - flow schedule construction
  - tail schedule construction
  - capture-budget accounting
  - result payload assembly
  - prior normalization / fallback selection
- define the stable output schema for:
  - accepted measurement rows
  - `frames.jsonl` rows
  - final `result` payload
- add unit tests for the frozen Phase-3 policy:
  - default flow schedule
  - default tail coarse schedule
  - refinement bracket expansion
  - budget stop behavior
  - payload shape

Expected outcome:

- the v1 policy is encoded in testable logic
- schedule and payload behavior can be validated without camera hardware
- later process stages can call stable helpers instead of embedding all policy directly into the state machine

### Stage 2: Minimal End-To-End Process Skeleton

Key changes:

- add `OnlineStreamCalibrationProcess` as a new `BaseCalibrationProcess` subclass
- add:
  - `CalibrationManager.start_online_stream_calibration(...)`
  - `Controller.start_online_stream_calibration(...)`
  - `CalibrationManager.PHASE_ALIASES` entry
- implement only the minimal runtime path:
  - prerequisite check
  - background capture
  - recorder setup
  - best-effort settings restore
  - final stub payload emission
- keep the process launchable even if the UI button is not added yet

Expected outcome:

- the new process can be started through the existing manager/controller path
- it can capture a background frame, create recorder artifacts, emit an `online_stream_calibration` step, and stop cleanly
- stop/error/restore behavior is verified before the algorithm becomes complex

### Stage 3: Flow-Phase Acquisition

Key changes:

- implement the flow-phase state sequence:
  - plan flow schedule
  - apply delay and imaging settings
  - capture replicates
  - run per-frame QC
  - record accepted and rejected frames
- add flow-phase measurement extraction:
  - attached width
  - visible volume
  - bottom-of-FOV clearance
  - nozzle / silhouette QC flags
- implement flow-specific stop rules:
  - bottom-of-FOV guard
  - repeated QC failure
  - insufficient accepted-delay guard
- write replay-friendly recorder-side artifacts:
  - `frames.jsonl`
  - `plan_snapshot.json`

Expected outcome:

- the process can complete a flow-only sparse acquisition run
- the run produces accepted measurements and rejected-frame diagnostics
- reagent use stays inside the expected budget during the flow phase

### Stage 4: Flow-Rate Fit And Partial Calibration Result

Key changes:

- implement the flow fit from accepted flow-phase measurements
- compute and persist:
  - `flow_rate_nl_per_us`
  - flow-fit start and end delays
  - steady-width baseline
  - flow-fit quality metrics
- add unit tests and offline replay checks for the flow-phase helpers against the existing dataset
- surface flow warnings when:
  - too few accepted delays are available
  - fit quality is poor
  - budget margins are exhausted

Expected outcome:

- the process can produce a trustworthy flow-only result even before the tail phase exists
- the offline replay check confirms the sparse flow schedule performs within the agreed error bounds
- this stage gives a stable midpoint checkpoint before adding tail logic

### Stage 5: Tail Coarse Search And Refinement

Key changes:

- implement tail-phase planning from:
  - priors when available
  - fallback defaults when priors are missing
- implement:
  - coarse tail search
  - trigger detection
  - refinement within the trigger bracket
- compute and persist:
  - coarse trigger delay
  - refined tail-start delay
  - tail warnings / fallback flags
  - predicted stream duration
- extend budget accounting across both phases
- add offline replay checks for tail timing against the existing dataset

Expected outcome:

- the process can complete the full two-phase online stream calibration end-to-end
- tail timing is derived from observed trigger evidence rather than extrapolation alone
- the algorithm can now be evaluated as a complete replacement for the dense offline timecourse in this use case

### Stage 6: UI, Readiness, And Operator Safety Integration

Key changes:

- add the droplet-imager UI entry point
- update readiness plumbing:
  - `CalibrationManager._emit_readiness()`
  - view readiness mapping
- update button lifecycle plumbing:
  - reset button text
  - flash-fault disable list
  - stream-capture lockout list
- add stage/progress text that clearly distinguishes:
  - flow phase
  - tail phase
  - restore/finalize

Expected outcome:

- an operator can start the new calibration from the normal droplet-imager workflow
- the button is enabled only when prerequisites are satisfied
- the UI safely blocks the process during flash faults or conflicting stream-capture activity

### Stage 7: Priors, Replay Tooling, And V1 Hardening

Key changes:

- add explicit prior lookup inside the new process
- record which priors were used and which fallbacks were taken
- write back new observations needed for future exact-condition recommendations
- extend recorder-side review artifacts such as:
  - `tail_fit.json`
  - any additional replay / review payloads needed beyond the Stage 4 `flow_fit.json`
- tighten automated tests and manual validation around:
  - repeated runs of the same condition
  - missing-prior fallback behavior
  - stop/restart/reload edge cases

Expected outcome:

- repeated calibrations become more condition-aware and more efficient
- the process is robust enough for broader operator use rather than developer-only testing
- the v1 implementation reaches the Phase-3 validation contract

### Recommended Stage Boundaries

The preferred stopping points for review and verification are:

- after Stage 2:
  - verify the new process path, recorder behavior, and stop/restore logic
- after Stage 4:
  - verify that flow-only calibration behavior is sound before adding tail logic
- after Stage 5:
  - verify the full algorithm headlessly and against offline replay data
- after Stage 6:
  - verify safe operator-facing behavior in the imager
- after Stage 7:
  - verify the complete v1 package

### Recommended First Implementation Slice

The first coding slice should be Stage 1 plus Stage 2, not the full flow phase.

Reason:

- it locks the schema and helper contracts first
- it proves the new process can live inside the existing calibration framework
- it gives a low-risk place to validate start/stop/restore/recording behavior before we spend time on image-analysis decision logic
