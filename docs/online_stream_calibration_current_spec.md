# Online Stream Calibration Current Spec

## Purpose

This document is the current operational reference for the shipped `OnlineStreamCalibrationProcess`.

Use it when you need to:

- understand how the online stream calibration currently works
- investigate a new experiment root or an individual recorder run
- replay a stored run from recorder artifacts
- debug why a run overpredicted, underpredicted, stopped early, or produced no prediction

If this document disagrees with the code, the source of truth is:

- `FreeRTOS-interface/CalibrationClasses/Model.py`
- `tools/stream_analysis/online_calibration.py`
- `tools/stream_analysis/online_fit.py`
- `tools/stream_analysis/online_runtime.py`
- `tools/stream_analysis/online_tail.py`

## Current Call Path

The live process path is:

`View.py -> Controller.start_online_stream_calibration(...) -> CalibrationManager.start_online_stream_calibration(...) -> OnlineStreamCalibrationProcess -> online_runtime.analyze_online_stream_frame(...) -> online_calibration.summarize_online_stream_flow_delay(...) / online_fit.fit_online_stream_flow_phase(...) -> online_tail.summarize_online_stream_tail_delay(...) / online_tail.resolve_online_stream_tail_fit(...)`

The process also writes recorder artifacts during execution:

- `plan_snapshot.json`
- `prior_resolution.json`
- `frames.jsonl`
- `flow_fit.json`
- `tail_fit.json`

## Process Summary

The current process is a two-phase sparse capture algorithm:

1. Adaptive flow phase
2. Tail scout + backtrack phase

The final predicted volume is:

- `predicted_volume_nl = flow_intercept_nl + flow_rate_nl_per_us * tail_start_delay_from_emergence_us`

That result is only emitted when:

- the flow fit resolves
- the tail phase resolves

## Current Flow Phase

Current default policy from `tools/stream_analysis/online_calibration.py`:

| Item | Default |
| --- | --- |
| Start offset from emergence | `+650 us` |
| Scout step | `100 us` |
| Target accepted delays | `20` |
| Minimum accepted delays for fit | `12` |
| Max printed flow captures | `30` |
| Nominal / hard capture budget | `55 / 61` |
| Soft bottom clearance | `150 px` |
| Late coverage threshold | `>= 2250 us` or `<= 300 px` visible-fluid clearance |
| Late coverage confidence minimum | `0.70` |
| Extension confidence floor | `0.55` |
| CI extension step | `50 us` |
| Safe densify window / step | `600 us / 50 us` |

Flow control modes:

- `scout`
  - walks rightward at `100 us` spacing
- `span_fill`
  - fills missing offsets inside the accepted safe window
- `ci_refine`
  - inserts midpoint delays until the fit is good enough or captures run out

Important frame-level flow gates:

- geometry QC
- optical confidence
- completeness gate
  - frames with materially omitted plausible fluid are excluded from the fit

Important flow result signals:

- `flow_rate_nl_per_us`
- `flow_intercept_nl`
- `steady_width_baseline_px`
- `late_coverage_reached`
- `late_slope_stable`
- `lag_equivalent_us`
- `flow_fit_stop_reason`

Important flow stop reasons:

- `ci_target_met`
- `flow_max_captures_reached`
- `hard_budget_exhausted`
- `tail_budget_preserved`

## Current Tail Phase

Current default policy from `tools/stream_analysis/online_tail.py`:

| Item | Default |
| --- | --- |
| Scout anchor | last accepted flow delay |
| Scout step | `500 us` |
| Scout replicates | `1` |
| Max scout delays | `10` |
| Backtrack step | `50 us` |
| Backtrack replicates | `1` |
| Prepad / postpad | `100 us / 100 us` |
| Left extension | one allowed extension |
| Collapse confirmation window | `100 us` |

Tail scout only triggers on robust right-bracket landmarks:

- `separated_from_nozzle`
- `attached_width_unavailable`
- `strong_width_collapse_backup`

The first small `< 0.99` width dip does not trigger scout by itself.

Tail backtrack behavior:

- choose the latest plateau-like left anchor from scout history
- build a dense local window at `50 us`
- extend left once if the first local window has no plateau
- compress the backtrack window when budget is tight

Tail resolver behavior:

- classify local rows into plateau / transition / collapse evidence
- find the first confirmed collapse using the `100 us` confirmation window
- choose the earliest transition immediately before that collapse
- otherwise choose the midpoint between the last plateau and the confirmed collapse
- never use a separated/unattached row directly as the selected onset

Important tail result signals:

- `tail_phase.status`
- `tail_phase.termination_reason`
- `tail_start_delay_from_emergence_us`
- `confirmed_collapse_delay_from_emergence_us`
- `tail_start_selection_method`
- `tail_backtrack_compressed`
- `required_tail_capture_count`

## Recorder Artifact Map

For a completed run directory such as:

- `FreeRTOS-interface/Experiments/<experiment>/calibration_recordings/OnlineStreamCalibrationProcess/<run_id>/`

the most useful files are:

### `run_meta.json`

Use for:

- start/end time
- printer head / reagent context
- settings snapshot
- overall outcome

### `events.jsonl`

Use for:

- state-machine sequence
- settings requested / settings completed timing
- capture attempts
- capture saved / capture result transitions
- timing between captures

### `plan_snapshot.json`

Use for:

- actual flow policy used
- actual tail policy used
- capture-budget snapshot
- prior contract copied into the run

### `prior_resolution.json`

Use for:

- whether exact-condition priors were found
- whether a fallback path was used
- warnings from prior lookup / application

### `frames.jsonl`

This is the main per-frame debug file.

Use for:

- flow frames: `phase = flow_rate`
- tail scout frames: `phase = tail_scout`
- tail backtrack frames: `phase = tail_backtrack`
- QC results
- widths
- visible volumes
- confidence values
- completeness flags
- warnings
- image references

### `flow_fit.json`

Use for:

- accepted flow delay summaries
- weighted fit diagnostics
- late coverage
- late slope stability
- warnings and stop reason

### `tail_fit.json`

Use for:

- planned scout anchor and policy
- scout delay summaries
- backtrack delay summaries
- bracket diagnostics
- final tail selection method
- budget compression diagnostics

## How To Investigate A New Experiment Root

Start at the experiment root:

- `FreeRTOS-interface/Experiments/<experiment_name>/`

### 1. Map the sessions

Open:

- `stream_capture_log.jsonl`

Use it to identify:

- dataset process type
- `dataset_run_id`
- session pressure / pulse width
- child process run ids
- whether a session is timecourse or online stream
- whether a session errored or was discarded

For online-stream investigation, the most important child runs are:

- `NozzlePositionCalibrationProcess`
- `DropletEmergenceCalibrationProcess`
- `OnlineStreamCalibrationProcess`

### 2. Group runs by condition

Before diagnosing variability, group by:

- printer head / reagent
- print pressure
- pulse width

Do not compare runs across mixed conditions unless the goal is specifically to study condition dependence.

### 3. Identify the failure class

The fastest useful split is:

- no prediction at all
- prediction exists but looks too low / too high
- flow fit looks wrong
- tail result looks wrong
- capture budget or settings timing problem

That determines which artifact to inspect first:

- no prediction:
  - `tail_fit.json`
  - `flow_fit.json`
  - `events.jsonl`
- bad flow estimate:
  - `frames.jsonl`
  - `flow_fit.json`
- bad tail estimate:
  - `frames.jsonl`
  - `tail_fit.json`

## How To Investigate A Single Run

### 1. Check top-level outcome

Open:

- `run_meta.json`
- `flow_fit.json`
- `tail_fit.json`

Look first at:

- `flow_fit.fit.fit_status`
- `flow_fit.fit.flow_rate_nl_per_us`
- `flow_fit.fit.flow_intercept_nl`
- `tail_fit.result.tail_phase.status`
- `tail_fit.result.tail_phase.termination_reason`
- `tail_fit.result.predicted_volume_nl`

### 2. Check whether the run actually captured enough trusted flow data

In `flow_fit.json`, inspect:

- `accepted_delay_point_count`
- `flow_fit_delay_start_from_emergence_us`
- `flow_fit_delay_end_from_emergence_us`
- `late_coverage_reached`
- `late_slope_stable`
- `warnings`

Common flow warning patterns:

- `flow_fit_late_coverage_not_reached`
- `flow_fit_late_slope_unstable`
- `tail_budget_preserved_early_finalize`

### 3. Check per-frame flow acceptance

In `frames.jsonl`, filter `phase == flow_rate`.

Pay special attention to:

- `flow_measurement_usable`
- `flow_volume_geometry_ok`
- `flow_volume_complete_ok`
- `flow_point_confidence`
- `flow_optical_confidence_active`
- `min_accepted_fluid_distance_from_bottom_px`
- `plausible_unaccepted_visible_volume_nl`
- `warnings`

This tells you whether the flow fit is biased by:

- geometry rejection
- completeness rejection
- late optical confidence
- bottom-of-FOV truncation

### 4. Check tail planning and bracket quality

In `tail_fit.json`, inspect:

- `tail_plan.scout_anchor_delay_from_emergence_us`
- `tail_plan.required_tail_capture_count`
- `tail_phase.landmark_delay_from_emergence_us`
- `tail_phase.confirmed_collapse_delay_from_emergence_us`
- `tail_phase.last_plateau_delay_from_emergence_us`
- `tail_phase.tail_start_delay_from_emergence_us`
- `tail_phase.tail_start_selection_method`
- `tail_phase.tail_backtrack_compressed`

In `frames.jsonl`, then filter:

- `phase == tail_scout`
- `phase == tail_backtrack`

This shows whether:

- scout entered at a sensible time
- the local bracket actually contains a plateau
- the backtrack window was compressed
- the final onset came from transition evidence or midpoint fallback

## Replay Workflow

The repo already includes a replay entry point:

```powershell
.\env\Scripts\python.exe tools\replay_online_stream_run.py --run-dir "<run_dir>"
```

For a batch of runs:

```powershell
.\env\Scripts\python.exe tools\replay_online_stream_run.py --runs-root "<online_stream_runs_root>"
```

Optional saved report:

```powershell
.\env\Scripts\python.exe tools\replay_online_stream_run.py --run-dir "<run_dir>" --write-report "<report_path>"
```

The replay path uses:

- `plan_snapshot.json`
- `prior_resolution.json`
- `frames.jsonl`
- `flow_fit.json`
- `tail_fit.json`

and recomputes:

- replayed flow fit
- replayed tail result
- comparisons between stored and replayed values

The replay report is the fastest way to answer:

- did the stored run serialize correctly?
- does the current code still reproduce the stored fit and tail result?
- which fields no longer match after a code change?

## Manual Frame Re-analysis Workflow

When you need to inspect raw images rather than only stored summaries, re-analyze frames with:

- `tools.stream_analysis.online_runtime.analyze_online_stream_frame(...)`

Important requirement:

- use the **emergence-selected nozzle center**
- not the earlier nozzle-position center

The correct per-run anchor usually comes from the child emergence run:

- `DropletEmergenceCalibrationProcess/.../analysis.jsonl`
- fields:
  - `result.flash_delay`
  - `result.selected_center_px`
  - fallback: `result.pressure_band_nozzle_center_px`

This is a frequent source of apples-to-apples mistakes. Re-analyzing online or timecourse frames with the wrong nozzle center can make widths and volumes look dramatically different even when the stored run is fine.

## Common Failure Patterns

### 1. No predicted volume

Check for:

- `missing_flow_baseline`
- `capture_budget_exhausted`
- `unresolved_missing_left_bracket`
- settings timeout / capture timeout in `events.jsonl`

First files to inspect:

- `flow_fit.json`
- `tail_fit.json`
- `events.jsonl`

### 2. Flow estimate too low or too high

Check for:

- poor late coverage
- unstable late slope
- many flow frames excluded on geometry or completeness
- early flow finalize due to `tail_budget_preserved`
- run-to-run changes in `lag_equivalent_us`

First files to inspect:

- `frames.jsonl`
- `flow_fit.json`

### 3. Tail start too early or too late

Check for:

- scout landmark type
- whether a plateau was captured in the local backtrack window
- whether the resolver used:
  - `earliest_transition_before_confirmed_collapse`
  - or `plateau_confirmed_collapse_midpoint`

First files to inspect:

- `tail_fit.json`
- `frames.jsonl`

### 4. Partial-silhouette bias

Check for:

- `flow_volume_complete_ok = false`
- `plausible_unaccepted_visible_volume_nl > 0`
- `flow_volume_incomplete` warning

If those appear, the current process should exclude the frame from the fit rather than using a partial visible volume.

### 5. Budget-driven behavior

Check for:

- `tail_budget_preserved`
- `tail_backtrack_compressed`
- `required_tail_capture_count`
- `tail_backtrack_requested_capture_count`
- `tail_backtrack_applied_capture_count`

That tells you whether the process changed behavior mainly because of capture budget, not because of image evidence.

## Comparing Online Runs To Timecourse Runs

For fair comparisons:

- use the same runtime analyzer for both
- use the emergence-selected nozzle center for both
- compare by `delay_from_emergence_us`, not raw `flash_delay`
- exclude errored or fluid-starved runs explicitly

Recommended comparison products:

- matched `V(t)` overlays
- per-offset mean / SD / CV
- slope variation across runs
- replay reports for stored online runs

## Practical Debugging Order

For most new failures, this order is fastest:

1. `stream_capture_log.jsonl`
2. `run_meta.json`
3. `flow_fit.json`
4. `tail_fit.json`
5. `frames.jsonl`
6. `events.jsonl`
7. `tools/replay_online_stream_run.py`
8. raw-frame re-analysis with `online_runtime.analyze_online_stream_frame(...)` if needed

## Useful Test Coverage

When changing the process, the most relevant automated coverage is:

- `tests/test_stream_online_calibration_helpers.py`
- `tests/test_stream_online_fit.py`
- `tests/test_stream_online_fit_replay.py`
- `tests/test_stream_online_runtime.py`
- `tests/test_stream_online_replay.py`
- `tests/test_stream_online_tail.py`
- `tests/test_stream_online_tail_replay.py`
- `tests/test_calibration_online_stream_process.py`

These are the best first places to look when you need examples of:

- expected artifact shape
- replay assumptions
- helper usage
- edge cases the current implementation is meant to handle
