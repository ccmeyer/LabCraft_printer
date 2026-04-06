# Stream Analysis Pipeline Plan

## Status

- Date created: 2026-04-01
- Owner: Codex + user
- Status: Stage 5 raw fitting, cache-backed Stage 5 fast-review tooling, review-only gravimetric-confidence analysis, review-only recompute flow-fit tooling, and review-only unified descriptor tail-start tooling are implemented and tested; Stage 7 tail modeling remains deferred while Stage 5 onset timing is iterated from cached review inputs
- Scope: offline Python analysis only for the first increment. No MVC, firmware, or protocol changes are planned in the initial phases.

## Objective

Build an incremental, reviewable image-analysis pipeline for stream characterization that:

- uses grayscale processing rather than a single color channel
- uses direct grayscale ROI processing as the primary segmentation path
- keeps real-background subtraction available only as an optional comparison or fallback path
- tracks nozzle location frame by frame, seeded from the first low-emergence frames and regularized over time
- extracts the filled outer stream silhouette below the tracked nozzle location
- computes framewise visible volume `V(t)` from the silhouette only
- detects when fluid leaves the field of view and marks later volume estimates untrusted
- saves annotated artifacts and reports at every phase so each step can be reviewed before moving on
- later estimates total printed volume as the sum of trusted visible volume, a steady-rate middle extrapolation, and a tail estimate
- later fits a head / steady / tail model to trusted `V(t)` rather than to raw `dV/dt`

## Verified Dataset Inputs

### Experiment root

- `FreeRTOS-interface/Experiments/Stream_characterization-20260327_225650`

### Run directories

- Process root:
  - `FreeRTOS-interface/Experiments/Stream_characterization-20260327_225650/calibration_recordings/DropletTimecourseProcess`
- Each run directory contains:
  - `captures/`
  - `run_meta.json`
  - `events.jsonl`
  - `analysis.jsonl`
  - `verdict.json`

### Metadata table

- `FreeRTOS-interface/Experiments/Stream_characterization-20260327_225650/stream_metadata.csv`
- Verified metadata columns:
  - `Dataset name`
  - `Print PW`
  - `Print Pressure`
  - `Refuel PW`
  - `Refuel Pressure`
  - `Rep`
  - `Starting mass`
  - `Starting flash`
  - `Ending flash`
  - `Ending mass`
  - `Mass Change`
  - `Num printed`
  - `Mass/print`
  - `CV`
  - `Notes`

### Verified run mapping

- `Dataset name` matches run directory names directly.
- `stream_metadata.csv` contains 26 rows.
- `DropletTimecourseProcess/` contains 33 run directories.
- All 26 CSV-backed runs currently map to real run folders and are `completed`.
- The 7 extra run folders are not represented in `stream_metadata.csv`; several of them are `stopped`.

### Verified capture shape

- Each CSV-backed run currently contains 121 saved frames in `captures/`.
- Verified example image size: `1088 x 1456` pixels.
- Recorder metadata includes:
  - frame order via `capture_index`
  - saved image path via `image_relpath`
  - wall-clock capture time via `captured_at_utc`
  - flash delay encoded in recorder messages such as `Capturing timecourse frame @ 4750 us`

### Physical calibration inputs

- Pixel calibration: `1.5696 um/pixel`
- Fluid for this dataset: water
- Water density is known and can be used later for comparison to gravimetric measurements

## Repo Fit And Recommended Code Location

The cleanest fit is to keep this pipeline as an offline analysis package under `tools/`, not inside the live MVC application:

- existing offline analysis and export utilities already live in `tools/`
- related tests for those tools already live in `tests/`
- working engineering plans already live in `docs/`
- this work does not need UI or firmware integration in the first increment

Recommended first-location:

- package code under `tools/stream_analysis/`
- thin CLI entry script at `tools/run_stream_analysis.py`
- tests under `tests/`
- plan and progress tracking in this document

## Output Root And Artifact Policy

Default output root should be experiment-local:

- `FreeRTOS-interface/Experiments/Stream_characterization-20260327_225650/analysis/stream_characterization/`

This keeps generated artifacts beside the source dataset and avoids mixing them with unrelated repo-wide artifacts.

Proposed output layout:

- `analysis/stream_characterization/run_inventory.json`
- `analysis/stream_characterization/run_inventory.csv`
- `analysis/stream_characterization/unmatched_runs.csv`
- `analysis/stream_characterization/runs/<run_id>/stage_00_inventory/...`
- `analysis/stream_characterization/runs/<run_id>/stage_01_baseline/...`
- `analysis/stream_characterization/runs/<run_id>/stage_02_nozzle/...`
- `analysis/stream_characterization/runs/<run_id>/stage_03_silhouette/...`
- `analysis/stream_characterization/runs/<run_id>/stage_04_volume/...`
- `analysis/stream_characterization/runs/<run_id>/stage_05_fit/...`
- `analysis/stream_characterization/runs/<run_id>/stage_06_summary/...`
- `analysis/stream_characterization/runs/<run_id>/stage_07_tail/...`
- `analysis/stream_characterization/experiment_summary.csv`
- `analysis/stream_characterization/experiment_summary.json`

## Assumptions And Defaults

- Use `pathlib` throughout. No hardcoded string path joining.
- Default run scope is CSV-backed runs only.
- Extra run folders not present in the CSV are reported separately and excluded from default summaries.
- Use grayscale processing, not single-green-channel processing.
- Default segmentation path is direct grayscale thresholding inside a constrained central ROI, with below-nozzle restriction applied after nozzle tracking is available.
- Real-background subtraction is not the default because lingering droplets in late frames and grip-refresh pose shifts can introduce subtraction artifacts.
- If background subtraction is used later, it must remain configurable by policy and by explicit frame index or path.
- Nozzle location should be estimated for every frame, with confidence scoring and temporal regularization so abrupt grip-refresh shifts are preserved rather than averaged away.
- The outer dark contour is the physical stream edge.
- Filling logic is allowed so the bright stream core becomes one filled silhouette.
- Volume is computed only from the silhouette below the tracked nozzle location for that frame.
- Axisymmetry is assumed around a local centerline:
  - `centerline(y) = (x_left(y) + x_right(y)) / 2`
  - `radius(y) = (x_right(y) - x_left(y)) / 2`
- Visible volume is computed framewise as `V(t)` before any higher-level model fitting.
- Trust ends when the fluid leaves the field of view; later frames remain recorded but are marked untrusted.
- Prefer existing repo dependencies:
  - `numpy`
  - `pandas`
  - `opencv-python`
  - `scikit-image`
  - `scipy`
  - `matplotlib`
- If a new dependency becomes necessary, document it in this file before adding it.

## Proposed Module Layout

### Package code

- `tools/stream_analysis/__init__.py`
  - package marker and shared exports
- `tools/stream_analysis/dataset.py`
  - experiment discovery
  - metadata join
  - run filtering
  - frame indexing
  - recorder parsing
- `tools/stream_analysis/baseline.py`
  - grayscale conversion
  - ROI preparation
  - central corridor masking
  - direct-threshold baseline artifact generation
  - optional future comparison hooks for background-reference experiments
  - preview/contact-sheet generation
- `tools/stream_analysis/nozzle.py`
  - per-frame nozzle candidate detection
  - multi-cue nozzle fusion
  - temporal smoothing and shift segmentation
  - nozzle review overlays and track export
- `tools/stream_analysis/silhouette.py`
  - thresholding
  - morphology
  - fill logic
  - contour extraction
  - left/right edge tracing
- `tools/stream_analysis/volume.py`
  - centerline and radius computation
  - axisymmetric slice integration
  - `V(t)` tables and plots
- `tools/stream_analysis/fov.py`
  - field-of-view exit detection
  - trusted/untrusted frame labeling
- `tools/stream_analysis/fit.py`
  - near-nozzle width feature extraction
  - head / steady / tail phase detection
  - robust steady-rate fitting
  - middle-volume extrapolation between FOV exit and tail onset
  - tail-model hooks and uncertainty reporting
- `tools/stream_analysis/reporting.py`
  - annotated images
  - run manifests
  - CSV/JSON summaries
  - plots and reports
- `tools/stream_analysis/cli.py`
  - argument parsing
  - stage dispatch

### Entrypoint

- `tools/run_stream_analysis.py`
  - thin script wrapper around the package CLI

### Planned tests

- `tests/test_stream_analysis_dataset.py`
- `tests/test_stream_analysis_baseline.py`
- `tests/test_stream_analysis_nozzle.py`
- `tests/test_stream_analysis_silhouette.py`
- `tests/test_stream_analysis_volume.py`
- `tests/test_stream_analysis_cli.py`

The implementation should favor small reusable functions over one large script.

## CLI / Script Entrypoints

Primary entrypoint:

- `.\env\Scripts\python.exe tools\run_stream_analysis.py ...`

Planned CLI shape:

- `inventory`
  - discover runs
  - join metadata
  - emit run inventory and unmatched-run report
- `baseline`
  - run Stage 1 only
- `nozzle`
  - run through per-frame nozzle tracking and shift segmentation
- `silhouette`
  - run through silhouette extraction
- `volume`
  - run through visible-volume and FOV-exit detection
- `fit`
  - derive near-nozzle width features from the attached stream
  - detect head-end, steady window, and tail onset
  - fit the steady `dV/dt` from trusted `V(t)` only
  - extrapolate missing middle volume between FOV exit and tail onset
  - leave tail estimation as a distinct final slice until its model is validated
- `run-all`
  - execute all completed pipeline stages up to `--through-stage`

Planned common arguments:

- `--experiment-root`
- `--output-root`
- `--run-id`
- `--limit-runs`
- `--include-unmatched`
- `--background-policy`
- `--background-frame-index`
- `--background-image`
- `--early-frame-count`
- `--force`
- `--through-stage`

Default behavior:

- if `--run-id` is omitted, operate on the CSV-backed run set
- if `--output-root` is omitted, write to the experiment-local analysis directory
- if no background options are supplied, use the direct-threshold path with no subtraction

## Pipeline Stages

### Stage 0: Dataset Inventory And Frame Index

Goal:

- discover runs
- join metadata rows to run folders
- report unmatched run folders
- build a stable frame index for each run
- reconstruct flash-delay and capture ordering from recorder data

Implementation notes:

- use `stream_metadata.csv` as the default source of truth for the initial analysis set
- parse `run_meta.json` and `events.jsonl`
- derive per-frame records from `capture_saved` / `capture_result` events
- persist flash delay from recorder messages instead of inferring from filenames

Validation artifacts required:

- `run_inventory.csv`
- `run_inventory.json`
- `unmatched_runs.csv`
- per-run `frame_index.csv`
- per-run `frame_index.json`

Acceptance criteria:

- all 26 CSV rows map cleanly to run directories
- all 7 unmatched run folders are listed in the report
- each matched run has 121 indexed frames
- per-frame index contains `capture_index`, image path, and flash delay

### Stage 1: ROI-First Direct Threshold Baseline

Goal:

- load raw frames
- convert to grayscale
- crop or mask to the analysis ROI near the center of the image
- establish a direct-threshold segmentation baseline before introducing any background reference

Implementation notes:

- use direct grayscale thresholding as the primary path
- constrain processing to the expected stream corridor near the center of the image
- treat Stage 1 as nozzle-agnostic; the below-nozzle restriction begins after Stage 2 tracking
- save representative previews from early, mid, and late frames
- include optional side-by-side comparisons against a subtraction-based variant for a small reviewed subset only
- do not make subtraction the default path unless artifact review shows a clear benefit

Validation artifacts required:

- per-run Stage 1 manifest describing ROI and threshold settings
- grayscale ROI preview contact sheet
- threshold-mask preview contact sheet
- representative annotated PNGs for early, middle, and late frames
- optional raw-vs-subtracted comparison panels for reviewed runs when subtraction is tested

Acceptance criteria:

- direct grayscale thresholding produces a stable stream mask on representative runs without requiring subtraction
- the baseline review set must include at least:
  - a clean shorter-pulse run
  - a longer-pulse run with lingering detached droplets near the end
  - a run with a visible grip-refresh positional shift
- saved overlays show that the stream edge can be isolated reliably from the raw grayscale ROI alone
- if subtraction is tested, it must be documented as equal or better than the direct-threshold baseline before becoming part of the default workflow

### Stage 2: Per-Frame Nozzle Tracking And Shift Segmentation

Goal:

- estimate nozzle location in every frame
- detect grip-refresh pose shifts as segment boundaries
- export a temporally regularized nozzle trajectory for downstream measurement

Implementation notes:

- use multiple cues because the best nozzle evidence changes over time:
  - early attached-droplet frames: estimate nozzle center from the emerging droplet geometry
  - attached-stream frames: use the bright-core / dark / bright transition near the nozzle as the primary cue
  - detached late frames: use the small dark ellipse near the nozzle when it remains visible
  - weak-signal frames: fall back to static nozzle-head appearance inside a tight local ROI
- use explicit physical raw modes so reflected fluid, actual fluid, visible nozzle line, and low-confidence fills are not treated as the same geometry:
  - `attached_black_droplet_center`
  - `attached_core_separation`
  - `visible_nozzle_line`
  - `only_nozzle`
- reserve `segment_fill` as a tracked-output fallback only; it is not a physical raw cue
- use the direct grayscale ROI by default
- if a subtraction-based comparison is evaluated, treat it as optional support evidence rather than the primary Stage 2 input
- store per-frame `x`, `y`, confidence, and detection mode rather than a single run-level row
- derive attached-fluid `x` from the contour centerline at the selected nozzle row rather than from the uppermost contour prong
- smooth small frame-to-frame jitter, but preserve abrupt jumps caused by grip refresh events
- use high-confidence frames to stabilize nearby low-confidence frames within each stable pose segment
- drive grip-refresh shift segmentation only from stable physical modes rather than from every raw nozzle cue

Validation artifacts required:

- `nozzle_track.csv`
- `nozzle_track.json`
- `shift_events.json`
- `nozzle_track.png` showing `x(t)` and `y(t)`
- per-run nozzle review report
- annotated montages covering:
  - early attached-droplet frames
  - attached-stream frames
  - ambiguous low-confidence frames
  - detached late frames
  - frames around detected shift boundaries

Acceptance criteria:

- every indexed frame gets a nozzle estimate or an explicit low-confidence failure reason
- saved overlays make the per-frame nozzle location and detection mode easy to inspect
- low-confidence frames are clearly identifiable in the outputs
- abrupt grip-refresh shifts are represented as segment boundaries rather than averaged into one location
- within a stable segment, nozzle position varies only within expected frame-to-frame jitter
- downstream stages consume the tracked per-frame nozzle location

### Stage 3: Filled Silhouette Extraction

Goal:

- isolate the outer stream silhouette below the tracked nozzle location
- trace left and right boundaries for each valid image row

Implementation notes:

- threshold the direct grayscale ROI by default
- if a subtraction-based variant is evaluated, treat it as a comparison path rather than the default input
- use morphology and fill logic so the bright core merges into one filled contour
- keep the outer dark boundary as the physical edge
- measure only below the tracked nozzle location for each frame

Validation artifacts required:

- raw grayscale ROI vs mask comparison grids
- filled-mask overlays
- contour overlays
- optional raw-vs-subtracted-vs-mask comparison grids when subtraction is being evaluated
- per-frame edge tables containing `x_left(y)` and `x_right(y)`

Acceptance criteria:

- one primary filled contour is produced for the stream in usable frames
- saved overlays show that the extracted contour follows the outer stream edge
- per-row edge traces are available for downstream volume computation

### Stage 4: Visible Volume `V(t)` And FOV-Exit Detection

Goal:

- compute framewise visible volume from the silhouette only
- detect the first frame where the stream leaves the trustworthy field of view

Implementation notes:

- compute:
  - `centerline(y) = (x_left(y) + x_right(y)) / 2`
  - `radius(y) = (x_right(y) - x_left(y)) / 2`
- use the silhouette produced by the direct-threshold path unless a reviewed fallback path is explicitly selected
- convert pixels to micrometers using `1.5696 um/pixel`
- integrate an axisymmetric volume slice by slice below the tracked nozzle location for each frame
- generate trusted/untrusted flags based on field-of-view exit

Validation artifacts required:

- `frame_metrics.csv`
- `volume_timeseries.csv`
- `volume_timeseries.json`
- `Vt.png`
- `fov_exit_report.json`
- annotated overlays showing the first untrusted frame

Acceptance criteria:

- every indexed frame gets a visible-volume result or explicit failure reason
- trusted vs untrusted frames are clearly labeled
- the first FOV-exit point is saved as a concrete run-level event
- later model-fitting inputs use trusted `V(t)` only

### Stage 5: Near-Nozzle Width, Steady-Rate Fit, And Middle Extrapolation

Goal:

- segment each run into head, steady, and tail phases after the lower-level pipeline is validated
- estimate a per-run partial total printed volume as:
  - trusted visible volume before FOV exit
  - steady-rate extrapolated middle volume between FOV exit and tail onset
  - a placeholder for the still-unmodeled tail volume

Implementation notes:

- implement Stage 5 as a new standalone `fit` stage:
  - `tools/run_stream_analysis.py` -> `tools/stream_analysis/cli.py` -> `export_stage5_fit()` -> `tools/stream_analysis/fit.py`
  - recompute Stage 4 in-process rather than reading saved Stage 4 files back from disk
- keep the raw `fit` path as the stable baseline for now; current review-only Stage 5 iteration happens through:
  - `tools/run_stream_analysis.py` -> `tools/stream_analysis/cli.py` -> `export_stage5_review_cache()` -> `tools/stream_analysis/review_cache.py`
  - `tools/run_stream_analysis.py` -> `tools/stream_analysis/cli.py` -> `export_stage5_cached_review()` -> `tools/stream_analysis/review_cache.py` -> reusable `tools/stream_analysis/fit.py::_build_stage5_review_run()`
- do not estimate the core steady model directly from raw `dV/dt`
- use two signals together:
  - trusted visible volume `V(t)` from Stage 4
  - attached-primary near-nozzle width from Stage 3 edge traces
- derive the near-nozzle width only from the attached primary, not from detached components
- keep the raw visible-volume trace, width trace, and fitted phase model together in the outputs
- the cache-backed review path now adds first-class review artifacts for both signals:
  - gravimetric-equivalent centerline plus CI95 time band
  - width-trace and shrink-rate contact sheets
  - `V(t)` fit contact sheets with the selected flow-fit window and CI band
  - per-run tail candidate tables for review-only onset tuning

Recommended execution slices:

- Stage 5a: near-nozzle width feature extraction
  - derive a fixed physical band below the tracked nozzle using initial defaults:
    - `near_nozzle_band_top_px = 24`
    - `near_nozzle_band_height_px = 40`
  - for each frame with an attached primary, compute:
    - `attached_near_nozzle_width_median_px`
    - `attached_near_nozzle_width_iqr_px`
    - `attached_near_nozzle_band_valid_row_count`
    - `attached_near_nozzle_band_y0_px`
    - `attached_near_nozzle_band_y1_px`
  - smooth the width trace with a short rolling median before changepoint detection
  - this slice is geometry-only and should not yet produce extrapolated volume
- Stage 5b: steady-window detection and robust steady-rate fit
  - raw `fit` path:
    - fit only on frames where `volume_trust_label == "trusted"`
    - search for the earliest contiguous trusted window that satisfies the current steady defaults:
      - at least `8` frames
      - robust linear fit on `V(t)` with high goodness of fit
      - smoothed near-nozzle width remaining on a stable plateau
    - export:
      - `steady_start_capture_index`
      - `steady_end_capture_index`
      - `steady_rate_nl_per_us`
      - `steady_width_plateau_px`
      - fit residual diagnostics
  - review-only `fit-review` path:
    - supports `steady_fit_mode = frozen | recompute`
    - `frozen` replays the cached Stage 5 steady-fit payload exactly
    - `recompute` now separates:
      - `plateau window`: the first width-flat seed after lag, used for `steady_start_capture_index`, `steady_end_capture_index`, the plateau anchor, and tail-search anchoring
      - `flow-fit window`: the longer final `V(t)` fit window used for `steady_rate_nl_per_us`, `steady_intercept_nl`, CI, and gravimetric-equivalent timing
    - current review-side recompute defaults:
      - exclude the last `2` trusted frames before FOV exit from flow fitting
      - allow up to `3` earlier backfilled points before the plateau seed when width is already settling toward the plateau
      - allow at most one isolated interior outlier drop inside the flow-fit window
    - the final central rate and the CI95 slope interval are both computed from the same post-prune flow-fit point set
    - current review outputs expose:
      - plateau vs flow-fit boundaries
      - selected fit points and excluded near-exit trusted points
      - CI95 slope band
      - residual drift and max-residual diagnostics
      - gravimetric-equivalent centerline and CI95 time band derived from the steady-rate CI
- Stage 5c: tail-onset detection and middle-volume extrapolation
  - raw `fit` path:
    - continue monitoring the near-nozzle width after FOV exit while the attached primary remains measurable
    - confirm a tail break when the smoothed width falls below `0.92 * steady_width_plateau_px` for at least `3` consecutive frames
    - use the current shoulder-aware raw Stage 5 rule:
      - direct backtrack for simple declines
      - shoulder-aware adjustment when a flat shoulder remains above threshold before the final drop
      - truncated-width-loss fallback when width ends during a real final decline
    - compute:
      - `middle_extrapolation_start = first_untrusted_frame`
      - `middle_extrapolation_end = tail_start_frame`
      - `middle_extrapolated_volume_nl = steady_rate_nl_per_us * delta_t_us`
  - review-only `fit-review` path:
    - keeps the raw shoulder/direct path split available as diagnostic metadata
    - currently supports three tail-start modes:
      - `legacy`
      - `descriptor-score`
      - `descriptor-unified`
    - current recommended review mode is `descriptor-unified`, which:
      - uses one shared candidate window from `preliminary_tail_start` through `tail_confirmation`
      - computes per-candidate descriptors from the smoothed width trace and the tail-only shrink-rate peak:
        - `drop_to_threshold_frac`
        - `shrink_rate_ratio`
        - `tail_peak_lead_us`
      - chooses the earliest candidate inside the current gravimetric-calibrated descriptor band
      - falls back to the shared weighted descriptor score only if no candidate enters the band
      - keeps `tail_start_selection_mode` only as metadata rather than as the final candidate-window definition
    - review outputs now include:
      - `tail_start_candidates.csv`
      - selected tail descriptor fields in the run summary and experiment summary
      - width/shrink-rate plots showing the selected tail, the legacy anchor, and the tail-only shrink-rate peak
  - keep this slice separate from the tail estimate so the middle extrapolation can be reviewed independently
- Stage 5d: partial-total export with explicit tail placeholder
  - until the tail model exists, do not silently report a final total as if it were complete
  - instead export:
    - `trusted_visible_volume_nl`
    - `middle_extrapolated_volume_nl`
    - `partial_total_without_tail_nl`
    - `tail_volume_nl = null`
    - `final_total_status = "tail_pending"`

Validation artifacts required:

- `phase_features.csv`
- `phase_boundaries.json`
- `steady_fit.json`
- `middle_extrapolation.json`
- `Vt_fit.png`
- `width_trace.png`
- residual plot
- annotated segment-boundary plot

Acceptance criteria:

- the steady-rate fit consumes trusted visible-volume data only
- the head-end and tail-onset boundaries are reviewable on both the volume trace and the near-nozzle width trace
- the middle extrapolation is computed only between the first untrusted frame and the detected tail-onset frame
- detached components can contribute to Stage 4 trust, but only the attached primary drives the near-nozzle width signal
- raw traces, fitted traces, and boundary annotations are all preserved in outputs
- any run without a validated tail model must clearly report a partial total rather than an implied final total

### Stage 6: Run Summary, Metadata Join, And Gravimetric Residual Analysis

Goal:

- summarize per-run results
- join image-derived metrics back to stream metadata
- compare the Stage 5 partial totals against gravimetric totals
- group replicate runs by operating condition so the missing tail behavior can be studied before Stage 7

Implementation notes:

- join on run directory name / `Dataset name`
- report metadata fields alongside derived image metrics
- include artifact locations in the run summary
- keep the Stage 6 execution model long-run friendly:
  - recompute Stage 5 in-process for each selected run
  - write final manifest JSON to `stdout`
  - emit incremental progress lines to `stderr`
  - update a root-level `summary_progress.json` checkpoint after each completed run
- carry through Stage 5 outputs such as:
  - trusted visible volume before FOV exit
  - steady-rate estimate
  - extrapolated middle volume
  - partial total without tail
  - tail estimate or explicit tail-pending status
  - total-estimate quality flags
- add signed gravimetric comparison fields needed to study the missing tail:
  - `gravimetric_total_nl`
  - `partial_total_without_tail_nl`
  - `signed_residual_nl = gravimetric_total_nl - partial_total_without_tail_nl`
  - `signed_residual_fraction`
  - `partial_to_gravimetric_ratio`
  - `partial_exceeds_gravimetric`
- group results by print pressure and print pulse width so the residual tail behavior can be compared across operating conditions

Validation artifacts required:

- per-run summary JSON
- experiment summary CSV
- experiment summary JSON
- condition summary CSV
- condition summary JSON
- `summary_progress.json`
- gravimetric residual comparison plots grouped by pulse width and pressure
- replicate comparison plots grouped by pulse width and pressure

Acceptance criteria:

- each analyzed run produces one summary row
- summary rows include both source metadata and image-analysis outputs
- the gravimetric residual after Stage 5 partial-volume estimation is visible and comparable across replicate groups
- replicate groups can be reviewed without opening individual run folders
- long runs provide live progress via `stderr` and a machine-readable checkpoint file

### Stage 7: Tail-Volume Model And Final Total Estimate

Goal:

- develop and validate a tail-volume model after the Stage 6 gravimetric residual patterns are available
- convert the Stage 5 partial total into a final estimated total printed volume

Implementation notes:

- use Stage 6 residual analysis to choose the first tail-model family instead of hard-coding it in advance
- candidate tail approaches to evaluate:
  - residual attached-volume integration while the nozzle-connected body remains measurable
  - a width-decay-driven tail integral
  - a calibrated empirical tail fraction against gravimetric totals
  - a pressure / pulse-width-conditioned regression on `tail_residual_nl`
- preserve the Stage 5 partial total and Stage 7 tail estimate as separate reported terms
- include explicit uncertainty or confidence fields so the final total is not presented as exact

Validation artifacts required:

- `tail_model.json`
- `tail_fit_diagnostics.csv`
- `tail_residual_plots.png`
- `final_total_comparison.png`

Acceptance criteria:

- the chosen tail model improves agreement with gravimetric totals relative to the Stage 5 partial total alone
- the final total remains decomposable into:
  - trusted visible volume
  - middle extrapolated volume
  - tail estimated volume
- the model assumptions and residuals are reviewable across operating conditions

## Progress Update Policy

Every time a phase is completed, update this file with:

- what was implemented
- which files were added or changed
- which artifacts were generated
- open issues or quality concerns
- next steps

Recommended section format for future updates:

- `Status`
- `Completed phases`
- `Artifacts generated`
- `Open issues`
- `Next steps`

## Progress Log

### 2026-04-01

Completed:

- inspected repo structure and existing tooling conventions
- verified that `tools/` is the best home for this offline analysis work
- verified metadata-to-run mapping for the current stream-characterization dataset
- verified that CSV-backed runs map directly by run directory name
- confirmed that the default analysis scope should be the 26 CSV-backed runs
- confirmed that unmatched run folders should be reported separately
- confirmed that per-frame timing can be reconstructed from recorder outputs
- wrote the initial implementation plan in this document

Artifacts generated:

- none yet; planning only

Open issues:

- exact Stage 4 field-of-view exit rule remains to be tuned against review artifacts
- exact Stage 6 fit parameterization remains intentionally deferred until trusted `V(t)` exists
- exact Phase 2 cue-fusion and shift-segmentation thresholds remain to be tuned against review artifacts

Next steps:

- create Stage 0 inventory/index tooling under `tools/stream_analysis/`
- generate the first run inventory and unmatched-run reports
- review the first artifact set before implementing the direct-threshold Stage 1 baseline

### 2026-04-01 - Stage 0 Implemented And Reviewed

Completed:

- added `tools/stream_analysis/dataset.py` with:
  - experiment-root resolution
  - metadata CSV loading
  - run discovery
  - recorder parsing for timecourse summary and per-frame delay extraction
  - Stage 0 inventory export helpers
- added `tools/stream_analysis/cli.py` and `tools/run_stream_analysis.py` with an `inventory` command
- added focused tests:
  - `tests/test_stream_analysis_dataset.py`
  - `tests/test_stream_analysis_cli.py`
- generated Stage 0 artifacts for the real experiment under:
  - `FreeRTOS-interface/Experiments/Stream_characterization-20260327_225650/analysis/stream_characterization/`
- reviewed the generated inventory artifacts against the underlying dataset

Files added or changed:

- `tools/stream_analysis/__init__.py`
- `tools/stream_analysis/dataset.py`
- `tools/stream_analysis/cli.py`
- `tools/run_stream_analysis.py`
- `tests/test_stream_analysis_dataset.py`
- `tests/test_stream_analysis_cli.py`
- `docs/stream_analysis_plan.md`

Artifacts generated:

- `analysis/stream_characterization/run_inventory.csv`
- `analysis/stream_characterization/run_inventory.json`
- `analysis/stream_characterization/unmatched_runs.csv`
- `analysis/stream_characterization/inventory_manifest.json`
- 26 per-run frame index pairs under:
  - `analysis/stream_characterization/runs/<run_id>/stage_00_inventory/frame_index.csv`
  - `analysis/stream_characterization/runs/<run_id>/stage_00_inventory/frame_index.json`

Artifact review:

- `run_inventory.csv` contains 26 selected runs, matching the 26 CSV-backed rows
- all 26 selected runs are `completed`
- every selected run indexed 121 frames
- every selected run has `capture_file_count == indexed_frame_count`
- every selected run has `missing_indexed_files == 0`
- 26 per-run Stage 0 output directories were created
- `unmatched_runs.csv` contains 7 run folders not present in `stream_metadata.csv`
- unmatched runs break down into:
  - 3 `completed`
  - 4 `stopped`
- the matched runs span 5 distinct timecourse timing configurations:
  - start `4750` / emergence `4800`: 6 runs
  - start `4200` / emergence `4250`: 10 runs
  - start `5200` / emergence `5250`: 3 runs
  - start `5100` / emergence `5150`: 4 runs
  - start `4650` / emergence `4700`: 3 runs

Verification:

- targeted tests:
  - `.\env\Scripts\python.exe -m pytest -q tests/test_stream_analysis_dataset.py tests/test_stream_analysis_cli.py`
  - result: `4 passed`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `617 passed`

Open issues:

- completed unmatched runs may still be useful later, but they need metadata reconciliation before they should enter grouped summaries
- Stage 0 currently relies on recorder text such as `Timecourse: ...` and `Capturing timecourse frame @ ... us`; if recorder wording changes in future datasets, the parser will need a more structured fallback
- `run_inventory.csv` currently keeps a `metadata_raw` JSON column for completeness; if that becomes cumbersome, it can be trimmed in a later cleanup without affecting Stage 0 correctness

Next steps:

- implement the Stage 1 ROI-first direct grayscale threshold baseline
- generate review artifacts for a small representative subset first
- compare optional subtraction-based previews only as a secondary experiment

### 2026-04-01 - Plan Revision Before Stage 1

Completed:

- revised the Stage 1 strategy after discussing two dataset-specific risks:
  - lingering detached droplets in late frames make many end-of-run background frames unsafe
  - grip-refresh pose shifts make cross-frame subtraction vulnerable to registration artifacts
- changed the plan so direct grayscale thresholding in a constrained ROI is the default preprocessing path
- demoted real-background subtraction to an optional comparison or fallback path
- updated downstream Stage 3 and Stage 4 language so they now assume the direct-threshold silhouette is primary

Artifacts generated:

- none; planning update only

Open issues:

- Stage 1 still needs a concrete ROI-and-threshold review workflow for the first representative subset
- if subtraction is revisited later, it should be justified by side-by-side artifact review rather than assumption

Next steps:

- implement Stage 1 using the direct-threshold baseline
- select representative review runs that include:
  - a clean shorter-pulse run
  - a longer-pulse lingering-droplet run
  - a grip-refresh run
- keep subtraction optional and off by default during the first Stage 1 implementation

### 2026-04-01 - Stage 1 Implemented And Reviewed

Completed:

- added `tools/stream_analysis/baseline.py` with:
  - central ROI extraction from grayscale frames
  - direct Otsu-based dark-threshold masks
  - central corridor masking to suppress static dark edge structure
  - per-frame baseline metric export
  - per-run sample panel generation
  - per-run Stage 1 manifest export
- extended `tools/stream_analysis/cli.py` with a `baseline` command
- added focused baseline tests in:
  - `tests/test_stream_analysis_baseline.py`
  - updated `tests/test_stream_analysis_cli.py`
- generated Stage 1 artifacts for the representative review subset:
  - `run_20260327_230520_9567e1ee`
  - `run_20260327_234644_51439780`
  - `run_20260327_225848_829e10c1`
- reviewed the resulting Stage 1 metrics and artifact presence

Files added or changed:

- `tools/stream_analysis/baseline.py`
- `tools/stream_analysis/cli.py`
- `tests/test_stream_analysis_baseline.py`
- `tests/test_stream_analysis_cli.py`
- `docs/stream_analysis_plan.md`

Artifacts generated:

- experiment-level:
  - `analysis/stream_characterization/baseline_manifest.json`
- per reviewed run:
  - `analysis/stream_characterization/runs/<run_id>/stage_01_baseline/frame_metrics.csv`
  - `analysis/stream_characterization/runs/<run_id>/stage_01_baseline/baseline_manifest.json`
  - `analysis/stream_characterization/runs/<run_id>/stage_01_baseline/sample_contact_sheet.png`
  - `analysis/stream_characterization/runs/<run_id>/stage_01_baseline/samples/frame_<index>_panel.png`

Artifact review:

- all 3 representative runs exported successfully
- each reviewed run produced:
  - 121 per-frame metric rows
  - 9 sample panels
  - 1 sample contact sheet
- the Stage 1 ROI and corridor settings used for this review were:
  - `roi_width_frac = 0.35`
  - `roi_top_frac = 0.10`
  - `corridor_width_frac = 0.70`
- representative metric behavior was directionally sensible:
  - clean shorter-pulse run `run_20260327_230520_9567e1ee` fell back to late-frame dark fractions near `0.068`
  - longer-pulse lingering-droplet run `run_20260327_234644_51439780` remained higher at the end, with late-frame dark fraction near `0.101`
  - grip-refresh run `run_20260327_225848_829e10c1` showed similar mask behavior across frames `34` and `35`, supporting the choice to avoid subtraction as the default path
- threshold ranges stayed stable enough to support continued work:
  - clean run: `137` to `157`
  - lingering-droplet run: `137` to `154`
  - grip-refresh run: `138` to `161`

Verification:

- targeted tests:
  - `.\env\Scripts\python.exe -m pytest -q tests/test_stream_analysis_dataset.py tests/test_stream_analysis_baseline.py tests/test_stream_analysis_cli.py`
  - result: `6 passed`
- Stage 1 generation command:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py baseline --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --run-id run_20260327_230520_9567e1ee --run-id run_20260327_234644_51439780 --run-id run_20260327_225848_829e10c1 --sample-count 6 --extra-frame-index 34 --extra-frame-index 35 --extra-frame-index 118 --extra-frame-index 121 --roi-width-frac 0.35 --roi-top-frac 0.10 --corridor-width-frac 0.70`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `619 passed`

Open issues:

- the current Stage 1 mask is intentionally coarse; it is suitable for review and Stage 2 handoff, but not yet the final silhouette used for volume integration
- even after corridor masking, the dominant connected component still spans much of the central corridor in many frames, so Stage 3 will need stronger contour discrimination below the nozzle
- subtraction-based comparison artifacts remain unimplemented by design in this slice; the baseline path stays subtraction-free unless a later review shows a clear benefit

Next steps:

- implement Stage 2 per-frame nozzle tracking using the Stage 1 direct grayscale ROI as input
- use the reviewed Stage 1 subset first when tuning the nozzle-tracking cues and shift-segmentation heuristic
- once Stage 2 is stable, tighten Stage 3 contour extraction so it isolates the stream body more specifically than the Stage 1 coarse baseline

### 2026-04-01 - Plan Revision Before Stage 2

Completed:

- revised Stage 2 after discussing a second dataset-specific risk:
  - grip-refresh events can shift the printer head part way through a run, so a single fixed nozzle row is not reliable
- changed the plan so Stage 2 now estimates nozzle position for every frame instead of locking one run-level reference
- expanded the planned Stage 2 cues to cover:
  - early attached-droplet frames
  - attached-stream frames with bright-core / dark / bright structure near the nozzle
  - detached late frames where the nozzle remains visible as a small dark ellipse
  - weak-signal fallback to static nozzle-head appearance
- updated downstream Stage 3 and Stage 4 language so volume and silhouette measurements are taken below the tracked nozzle location for each frame

Artifacts generated:

- none; planning update only

Open issues:

- the exact cue-fusion logic and confidence scoring still need to be chosen during implementation
- the exact shift-detection threshold still needs to be tuned against real runs with visible grip-refresh events

Next steps:

- implement Stage 2 per-frame nozzle tracking and shift segmentation
- review the first Stage 2 artifacts on representative runs before scaling to the full dataset
- keep the saved nozzle track explicit so later silhouette and volume stages can consume it directly

### 2026-04-01 - Stage 2 Implemented And Reviewed

Completed:

- added `tools/stream_analysis/nozzle.py` with:
  - per-frame local-contrast nozzle candidate extraction using a blurred-background residual
  - top-band candidate geometry for a nozzle-location baseline
  - optional center-profile valley refinement when the bright-core / dark / bright cue is strong
  - temporal smoothing and low-confidence segment filling
  - grip-refresh shift segmentation based on stable-band nozzle motion
  - per-run nozzle-track plots and annotated review panels
- extended `tools/stream_analysis/cli.py` with a `nozzle` command
- added focused Phase 2 tests in:
  - `tests/test_stream_analysis_nozzle.py`
  - updated `tests/test_stream_analysis_cli.py`
- generated Stage 2 artifacts first for the representative review subset:
  - `run_20260327_230520_9567e1ee`
  - `run_20260327_234644_51439780`
  - `run_20260327_225848_829e10c1`
- after reviewing the subset, generated Stage 2 artifacts across all 26 CSV-backed runs

Files added or changed:

- `tools/stream_analysis/nozzle.py`
- `tools/stream_analysis/cli.py`
- `tests/test_stream_analysis_nozzle.py`
- `tests/test_stream_analysis_cli.py`
- `docs/stream_analysis_plan.md`

Artifacts generated:

- experiment-level:
  - `analysis/stream_characterization/nozzle_manifest.json`
- per analyzed run:
  - `analysis/stream_characterization/runs/<run_id>/stage_02_nozzle/nozzle_track.csv`
  - `analysis/stream_characterization/runs/<run_id>/stage_02_nozzle/nozzle_track.json`
  - `analysis/stream_characterization/runs/<run_id>/stage_02_nozzle/shift_events.json`
  - `analysis/stream_characterization/runs/<run_id>/stage_02_nozzle/nozzle_track.png`
  - `analysis/stream_characterization/runs/<run_id>/stage_02_nozzle/nozzle_manifest.json`
  - `analysis/stream_characterization/runs/<run_id>/stage_02_nozzle/sample_contact_sheet.png`
  - `analysis/stream_characterization/runs/<run_id>/stage_02_nozzle/samples/frame_<index>_panel.png`

Artifact review:

- all 26 CSV-backed runs exported successfully
- every analyzed run produced:
  - 121 per-frame nozzle-track rows
  - `nozzle_track.json`
  - `shift_events.json`
  - `nozzle_track.png`
  - a Stage 2 run manifest
  - a sample contact sheet plus sample panels
- the reviewed Stage 2 defaults were:
  - `search_width_frac = 0.22`
  - `search_top_frac = 0.08`
  - `search_bottom_frac = 0.30`
  - `blur_sigma = 12.0`
  - `residual_threshold = 18`
  - `shift_threshold_px = 6.0`
  - `confidence_threshold = 0.55`
- across the full 26-run batch:
  - shift-event counts ranged from `2` to `6` per run, with a mean of `3.115`
  - tracked-confidence means ranged from `0.588` to `0.706`, with a batch mean of `0.655`
  - low-confidence segment-filled frames ranged from `5` to `37` per run, with a mean of `19.27`
- representative subset review was directionally sensible:
  - lingering-droplet run `run_20260327_234644_51439780` held a very stable mid-run track over frames `20` to `90`, with tracked `x` span near `1.0 px` and tracked `y` span near `3.0 px`
  - grip-refresh run `run_20260327_225848_829e10c1` showed a stable attached-stream nozzle estimate around frames `34` and `35`, with tracked positions near `(605.5, 168)` and `(605.25, 169)` pixels respectively
  - early attached-stream frames such as `run_20260327_234644_51439780` frame `11` and frame `15` produced review panels where the local-contrast cue and tracked marker were visually aligned with the nozzle geometry
  - detached late frames such as frame `121` remain measurable but often rely on low-confidence fill or the late dark-ellipse cue, which is expected and now visible in the saved artifacts

Verification:

- targeted tests:
  - `.\env\Scripts\python.exe -m pytest -q tests/test_stream_analysis_dataset.py tests/test_stream_analysis_baseline.py tests/test_stream_analysis_nozzle.py tests/test_stream_analysis_cli.py`
  - result: `8 passed`
- representative Stage 2 generation command:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py nozzle --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --run-id run_20260327_230520_9567e1ee --run-id run_20260327_234644_51439780 --run-id run_20260327_225848_829e10c1 --sample-count 6 --extra-frame-index 11 --extra-frame-index 12 --extra-frame-index 15 --extra-frame-index 34 --extra-frame-index 35 --extra-frame-index 118 --extra-frame-index 121`
- full 26-run Stage 2 generation command:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py nozzle --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650"`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `621 passed`

Open issues:

- the current shift segmentation is intentionally conservative and still tends to report multiple stable-band shifts in some runs; if Stage 3 review shows this is too fragmented, near-adjacent shift events should be collapsed before the final summary stage
- late detached frames can still pull the raw nozzle estimate downward toward the detached dark ellipse; the tracked output now exposes this with lower confidence and segment filling, but Stage 3 should continue to respect the confidence field rather than trusting every late raw estimate equally
- early attached-droplet frames are sometimes stabilized by the temporal track rather than by a strong local bright-core valley cue; this is acceptable for the current incremental phase but remains a likely refinement target

Next steps:

- implement Stage 3 silhouette extraction using the tracked per-frame nozzle location as the above/below cutoff
- save Stage 3 overlays that make the interaction between the tracked nozzle marker and the extracted silhouette explicit
- revisit shift-event collapse only if the Stage 3 artifact review shows the current segmentation is too noisy for downstream use

### 2026-04-01 - Stage 2 Detector Fix Implemented And Reviewed

Completed:

- replaced the original Stage 2 top-band / valley baseline with a reflection-aware, mode-based detector in `tools/stream_analysis/nozzle.py`
- split the raw nozzle logic into two cue families:
  - static visible-line detection for detached or no-fluid frames
  - attached-fluid contour analysis for emerging droplets and attached streams
- changed attached-fluid `x` selection so it now comes from the contour centerline at the chosen nozzle row rather than from the uppermost contour band
- added explicit physical raw modes:
  - `attached_black_droplet_center`
  - `attached_core_separation`
  - `visible_nozzle_line`
  - `segment_fill`
- tightened Stage 2 tracking so confident physical raw detections are preserved and segment fill is used only for low-confidence gaps
- restricted shift segmentation to stable physical modes instead of allowing all raw cues to influence grip-refresh boundaries
- expanded the Stage 2 exports with additional diagnostic fields in `nozzle_track.csv` and `nozzle_track.json`, including:
  - `raw_mode`
  - `final_mode`
  - `static_line_x_px`
  - `static_line_y_px`
  - `attached_component_centroid_x_px`
  - `attached_component_centroid_y_px`
  - `attached_component_area_px`
  - `bright_core_upper_y_px`
  - `bright_core_lower_y_px`
  - `separation_band_y_px`
  - `used_segment_fill`
- replaced the Stage 2 sample panel layout so each panel now shows:
  - full-frame context with raw and final nozzle markers
  - top ROI / visible-line cue
  - attached contour ROI with centerline overlay
  - a zoomed nozzle crop with bright-core and separation-band guides
- updated the focused Stage 2 tests in `tests/test_stream_analysis_nozzle.py`
- regenerated Stage 2 artifacts for the targeted regression subset and then for the full 26-run CSV-backed dataset

Files added or changed:

- `tools/stream_analysis/nozzle.py`
- `tests/test_stream_analysis_nozzle.py`
- `docs/stream_analysis_plan.md`

Artifacts generated:

- updated experiment-level:
  - `analysis/stream_characterization/nozzle_manifest.json`
- updated per-run Stage 2 outputs for the 26 CSV-backed runs:
  - `analysis/stream_characterization/runs/<run_id>/stage_02_nozzle/nozzle_track.csv`
  - `analysis/stream_characterization/runs/<run_id>/stage_02_nozzle/nozzle_track.json`
  - `analysis/stream_characterization/runs/<run_id>/stage_02_nozzle/shift_events.json`
  - `analysis/stream_characterization/runs/<run_id>/stage_02_nozzle/nozzle_track.png`
  - `analysis/stream_characterization/runs/<run_id>/stage_02_nozzle/nozzle_manifest.json`
  - `analysis/stream_characterization/runs/<run_id>/stage_02_nozzle/sample_contact_sheet.png`
  - `analysis/stream_characterization/runs/<run_id>/stage_02_nozzle/samples/frame_<index>_panel.png`

Artifact review:

- the targeted regression frames in `run_20260327_230520_9567e1ee` now behave much more like the intended physical interpretation:
  - frame `1` now lands in the middle of the attached emerging droplet instead of at the reflected top edge
  - frame `11` now lands on the dark separation band between the reflected and actual attached stream, with the point centered on the stream rather than pulled onto a right-side prong
  - frames `97`, `118`, and `121` now use the visible nozzle line instead of drifting into detached blobs or the printer-head dark band
- the grip-refresh regression pair in `run_20260327_225848_829e10c1` now shows a small plausible shift:
  - frame `34` tracked near `(607.0, 165.0)` px
  - frame `35` tracked near `(606.0, 172.0)` px
- the long-pulse regression frame `run_20260327_234644_51439780` frame `15` now stays on the attached-stream separation band near `(579.5, 195.0)` px
- the updated review panels are materially easier to interpret because they explicitly separate the top visible-line cue, the attached contour cue, and the zoomed nozzle decision region
- across the full 26-run Stage 2 batch:
  - tracked-confidence means ranged from `0.856` to `0.967`, with a batch mean of `0.914`
  - segment-filled frames ranged from `0` to `6` per run, with a mean of `1.50`
  - shift-event counts ranged from `2` to `7` per run, with a mean of `3.692`
  - total raw-mode counts were:
    - `attached_black_droplet_center`: `348`
    - `attached_core_separation`: `2296`
    - `visible_nozzle_line`: `463`
    - `no_signal`: `39`

Verification:

- focused Stage 2 tests:
  - `.\env\Scripts\python.exe -m pytest -q tests/test_stream_analysis_nozzle.py tests/test_stream_analysis_cli.py`
  - result: `9 passed`
- targeted Stage 2 regeneration command:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py nozzle --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --run-id run_20260327_230520_9567e1ee --run-id run_20260327_234644_51439780 --run-id run_20260327_225848_829e10c1 --sample-count 8 --extra-frame-index 1 --extra-frame-index 3 --extra-frame-index 4 --extra-frame-index 6 --extra-frame-index 7 --extra-frame-index 9 --extra-frame-index 10 --extra-frame-index 11 --extra-frame-index 15 --extra-frame-index 34 --extra-frame-index 35 --extra-frame-index 91 --extra-frame-index 92 --extra-frame-index 97 --extra-frame-index 101 --extra-frame-index 102 --extra-frame-index 118 --extra-frame-index 121`
- full 26-run Stage 2 regeneration command:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py nozzle --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650"`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `626 passed`

Open issues:

- frames `3`, `101`, and `102` currently stay in `attached_black_droplet_center` mode rather than promoting to `attached_core_separation`; the resulting point is physically reasonable, but that promotion rule may still be worth refining if Stage 3 proves sensitive to it
- the attached-stream separation rows for some runs still come from a heuristic bright-band split rather than an explicitly detected nozzle line, so Stage 3 should continue to respect `raw_mode`, `final_mode`, and `tracked_confidence`
- shift-event counts remain somewhat conservative in a few runs; if Stage 3 review shows over-segmentation, near-adjacent grip-refresh boundaries should be collapsed before the summary stage

Next steps:

- implement Stage 3 silhouette extraction using the corrected tracked per-frame nozzle location as the above/below cutoff
- keep the Stage 3 overlays explicitly aligned with the tracked nozzle marker and the saved Stage 2 mode diagnostics
- only revisit the Stage 2 split heuristics if the Stage 3 artifact review shows a concrete failure mode that depends on nozzle-row placement

### 2026-04-01 - Ground-Truth-Guided Stage 2 Retune Implemented And Reviewed

Completed:

- added a new offline diagnostics command, `diagnose-nozzle`, under the existing `tools/run_stream_analysis.py` CLI
- expanded the annotation tooling in `tools/stream_analysis/annotations.py` so annotated frames can be joined against all Stage 2 raw candidate families and summarized in a diagnostics report
- refactored the raw Stage 2 nozzle detector in `tools/stream_analysis/nozzle.py` so it now exposes explicit candidate families for:
  - `attached_black_droplet_center`
  - `attached_core_separation`
  - `visible_nozzle_line`
  - `only_nozzle`
- added `only_nozzle` as a real Stage 2 raw/final mode rather than treating detached/no-stream nozzle frames as part of the attached visible-line logic
- redefined `visible_nozzle_line` to mean the attached dark ridge or band between the actual stream and its reflection
- added a new annotation-guided local-valley detector for long attached streams so the attached dark band can be detected even when the older global bright-peak split fails
- tightened the raw/final mode selection so strong `only_nozzle` detections win when the detached top-ROI cue is present and attached evidence is weak
- updated tracking so confident raw detections are preserved more often instead of being over-smoothed into nearby segment anchors, especially for:
  - `attached_black_droplet_center`
  - `attached_core_separation`
  - `visible_nozzle_line`
- kept the existing downstream Stage 2 interface unchanged:
  - `tracked_nozzle_x_px`
  - `tracked_nozzle_y_px`
- added focused tests for:
  - long attached visible-line detection
  - diagnostics export
  - `only_nozzle` mode separation
  - tracking preservation of confident raw detections

Files added or changed:

- `tools/stream_analysis/nozzle.py`
- `tools/stream_analysis/annotations.py`
- `tools/stream_analysis/cli.py`
- `tests/test_stream_analysis_nozzle.py`
- `tests/test_stream_analysis_annotations.py`
- `tests/test_stream_analysis_cli.py`
- `docs/stream_analysis_plan.md`

Tuning and holdout split:

- tuning runs:
  - `run_20260327_230520_9567e1ee`
  - `run_20260327_230807_2858b360`
- holdout acceptance run:
  - `run_20260327_231322_ecc89833`
- smoke-check-only partial run:
  - `run_20260327_231641_7f78f806`

Diagnostics artifacts generated:

- `analysis/stream_characterization/annotations/diagnostics/nozzle_candidate_diagnostics.csv`
- `analysis/stream_characterization/annotations/diagnostics/nozzle_candidate_summary.json`
- `analysis/stream_characterization/annotations/diagnostics/candidate_overlays/worst_final_error/`
- `analysis/stream_characterization/annotations/diagnostics/candidate_overlays/best_candidate_differs/`
- `analysis/stream_characterization/annotations/diagnostics/candidate_overlays/mode_mismatch/`

Threshold and logic decisions frozen from the tuning set:

- `only_nozzle` is preferred when the detached top-ROI cue is strong and attached candidates are weaker
- the attached long-stream `visible_nozzle_line` candidate now comes from the best local dark valley in the upper-to-mid attached stream when:
  - the component is long attached
  - the local valley score is at least `70`
- the older global bright-peak split remains active for shorter attached-core cases and for attached frames where the local-valley cue is weak
- tracking now preserves raw detections when confidence exceeds:
  - `0.55` for `attached_black_droplet_center`
  - `0.40` for `attached_core_separation`
  - `0.45` for `visible_nozzle_line`
  - `0.40` for `only_nozzle`
- attached shift anchors remain limited to stable higher-confidence attached physical modes rather than including all attached detections

Artifact review:

- tuning diagnostics improved substantially once the local attached-valley cue was added:
  - overall tuning prediction mean distance: `5.856 px`
  - overall tuning prediction median distance: `1.414 px`
  - tuning `visible_nozzle_line` prediction mean distance: `3.201 px`
  - tuning `visible_nozzle_line` prediction median distance: `1.414 px`
- the candidate report now shows that the attached visible-line annotations are overwhelmingly explained by the explicit `visible_nozzle_line` candidate rather than by the older centroid fallback:
  - `visible_nozzle_line` was the best candidate on `145` of `166` tuning frames annotated as `visible_nozzle_line`
- the holdout run improved dramatically relative to the pre-retune detector:
  - overall holdout mean distance: `6.113 px`
  - overall holdout median distance: `1.803 px`
- holdout per-mode results:
  - `visible_nozzle_line`: median `1.414 px`, mean `3.159 px`, mode match `0.940`
  - `only_nozzle`: median `2.062 px`, mean `8.110 px`, mode match `0.882`
  - `attached_black_droplet_center`: median `7.000 px`, mean `7.760 px`
  - `attached_core_separation`: median `24.502 px`, mean `22.482 px`
- this means the retune fully improved the main attached visible-line regime and brought the overall holdout median well below the `<= 10 px` target, but the droplet-center and attached-core-separation subsets still need more work

Verification:

- focused retune tests:
  - `.\env\Scripts\python.exe -m pytest -q tests/test_stream_analysis_nozzle.py tests/test_stream_analysis_annotations.py tests/test_stream_analysis_cli.py`
  - result: `23 passed`
- retuned Stage 2 regeneration on the annotated runs:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py nozzle --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --run-id run_20260327_230520_9567e1ee --run-id run_20260327_230807_2858b360 --run-id run_20260327_231322_ecc89833 --run-id run_20260327_231641_7f78f806 --sample-count 8`
- tuning diagnostics:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py diagnose-nozzle --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --run-id run_20260327_230520_9567e1ee --run-id run_20260327_230807_2858b360 --limit-worst-frames 20`
- holdout evaluation:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py evaluate-nozzle --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --run-id run_20260327_231322_ecc89833 --limit-worst-frames 20`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `640 passed`

Open issues:

- the `attached_core_separation` subset still underperforms on the holdout run, which means the shorter attached split logic is still not aligned with the annotations
- `attached_black_droplet_center` still has a wider-than-desired spread on holdout and should be revisited before Stage 2 is considered fully converged
- `only_nozzle` point placement is good in the median case, but the holdout mode match rate at `0.882` is still slightly below the `>= 0.90` target
- `diagnose-nozzle` currently writes one canonical diagnostics CSV/JSON per experiment-local annotations root; rerunning the command on a different subset overwrites the prior diagnostics summary

Next steps:

- use the current diagnostics artifacts to target the remaining `attached_core_separation` and `attached_black_droplet_center` failure modes before trusting Stage 2 as final
- after that narrower Stage 2 cleanup pass, rerun Stage 2 on the full dataset so the updated predictions can be reviewed before Stage 3 begins
- keep Stage 3 silhouette extraction explicitly tied to the tracked per-frame nozzle point and the saved Stage 2 mode fields

### 2026-04-01 - Stage 2 Accuracy Cleanup Implemented And Re-Reviewed

Completed:

- rewired `tools/stream_analysis/nozzle.py` so the exported Stage 2 pipeline now actually uses the newer cue-family logic end to end instead of leaving the export path on the older merged detector
- split Stage 2 into two independent cue families in the live export path:
  - filled attached-contour geometry for droplet-center and attached-stream cues
  - an independent top-ROI compact contour search for `only_nozzle`
- added the planned cue diagnostics to the raw detector payload and Stage 2 exports:
  - `compact_droplet_score`
  - `neck_y_px`
  - `neck_width_px`
  - `neck_score`
  - `line_band_y_px`
  - `line_band_score`
  - `only_nozzle_y_px`
  - `only_nozzle_score`
  - `attached_support_score`
- replaced the old fixed-priority export path with scored gating and sequential per-run context so each frame can use the previous frame’s nozzle location and recent mode history
- tightened tracking so confident raw detections are preserved more often, attached-family jumps are capped unless a shift boundary is present, and stale sample PNGs are cleared before regeneration
- extended `diagnose-nozzle` so it now exports the new cue scores and row locations in the canonical diagnostics CSV/JSON and in the candidate overlay images
- upgraded the Stage 2 sample panels so they now show:
  - the filled attached contour
  - the contour centerline
  - the neck row
  - the line-band row
  - the top-ROI `only_nozzle` cue
  - the chosen raw point and final tracked point
- refreshed the full `121`-frame Stage 2 review panels for:
  - `run_20260327_230520_9567e1ee`
  - `run_20260327_230807_2858b360`
  - `run_20260327_231322_ecc89833`
  - `run_20260327_231931_2fd25ece`

Files added or changed:

- `tools/stream_analysis/nozzle.py`
- `tools/stream_analysis/annotations.py`
- `tests/test_stream_analysis_nozzle.py`
- `docs/stream_analysis_plan.md`

Frozen thresholds after the cleanup pass:

- `only_nozzle`: `0.56`
- `attached_support_low`: `0.38`
- `attached_black_droplet_center`: `0.60`
- `visible_nozzle_line`: `0.28`
- `attached_core_separation`: `0.32`
- override margin between droplet and competing attached cues: `0.12`

Artifacts regenerated:

- `analysis/stream_characterization/nozzle_manifest.json`
- refreshed per-run Stage 2 outputs for:
  - `analysis/stream_characterization/runs/run_20260327_230520_9567e1ee/stage_02_nozzle/...`
  - `analysis/stream_characterization/runs/run_20260327_230807_2858b360/stage_02_nozzle/...`
  - `analysis/stream_characterization/runs/run_20260327_231322_ecc89833/stage_02_nozzle/...`
  - `analysis/stream_characterization/runs/run_20260327_231931_2fd25ece/stage_02_nozzle/...`
- refreshed diagnostics artifacts:
  - `analysis/stream_characterization/annotations/diagnostics/nozzle_candidate_diagnostics.csv`
  - `analysis/stream_characterization/annotations/diagnostics/nozzle_candidate_summary.json`
  - `analysis/stream_characterization/annotations/diagnostics/candidate_overlays/...`
- refreshed holdout evaluation artifacts:
  - `analysis/stream_characterization/annotations/nozzle_evaluation.csv`
  - `analysis/stream_characterization/annotations/nozzle_evaluation.json`
  - `analysis/stream_characterization/annotations/worst_frames/...`

Artifact review:

- tuning diagnostics on:
  - `run_20260327_230520_9567e1ee`
  - `run_20260327_230807_2858b360`
- tuning results:
  - predicted mean distance: `23.610 px`
  - predicted median distance: `3.162 px`
  - best-candidate mean distance: `15.450 px`
  - best-candidate median distance: `3.162 px`
- tuning best-candidate counts now break down as:
  - `attached_black_droplet_center`: `104`
  - `attached_core_separation`: `2`
  - `visible_nozzle_line`: `102`
  - `only_nozzle`: `21`
- tuning candidate medians are strongest for:
  - `only_nozzle`: `1.228 px`
  - `visible_nozzle_line`: `3.162 px`
- holdout evaluation on `run_20260327_231322_ecc89833`:
  - overall mean distance: `3.591 px`
  - overall median distance: `4.123 px`
  - max distance: `20.006 px`
- holdout per-annotation-mode results:
  - `attached_black_droplet_center`: median `0.581 px`, mean `0.870 px`, mode match `0.778`
  - `attached_core_separation`: median `2.476 px`, mean `4.570 px`, mode match `0.000`
  - `visible_nozzle_line`: median `5.099 px`, mean `4.218 px`, mode match `0.205`
  - `only_nozzle`: median `1.095 px`, mean `1.281 px`, mode match `0.000`
- this means the cleanup pass materially improved point placement on the holdout run, especially for droplet-center and nozzle-only geometry, but mode selection still lags the annotations in the attached `visible_nozzle_line` and `attached_core_separation` regimes

Verification:

- focused Stage 2 / annotation / CLI tests:
  - `.\env\Scripts\python.exe -m pytest -q tests/test_stream_analysis_nozzle.py tests/test_stream_analysis_annotations.py tests/test_stream_analysis_cli.py`
  - result: `23 passed`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `640 passed`
- Stage 2 regeneration on the reviewed runs:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py nozzle --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --run-id run_20260327_230520_9567e1ee --run-id run_20260327_230807_2858b360 --run-id run_20260327_231322_ecc89833 --run-id run_20260327_231931_2fd25ece --sample-count 121`
- tuning diagnostics:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py diagnose-nozzle --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --run-id run_20260327_230520_9567e1ee --run-id run_20260327_230807_2858b360 --limit-worst-frames 50`
- holdout evaluation:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py evaluate-nozzle --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --run-id run_20260327_231322_ecc89833 --limit-worst-frames 50`

Open issues:

- the attached `visible_nozzle_line` and `attached_core_separation` regimes still show weak mode agreement even when point placement is close, which means the current scored gating is still too conservative about promoting non-droplet attached cues
- the Stage 2 cleanup pass currently under-detects true grip-refresh segment boundaries on the reviewed runs; the latest regenerated four-run sample set reported `0` shift events, so shift anchoring should be revisited before Stage 3 depends on it
- `diagnose-nozzle` now records the new cue fields, but it still overwrites the canonical experiment-local diagnostics summary when rerun on a different subset

Next steps:

- use the refreshed per-frame sample panels in the four reviewed runs to identify exactly where the current attached-mode gating should switch from `attached_black_droplet_center` to `visible_nozzle_line` or `attached_core_separation`
- tighten the attached-family mode classifier without degrading the current good point-placement medians
- revisit grip-refresh shift segmentation using the stronger raw cue scores before starting Stage 3
- only begin Stage 3 after one more Stage 2 review pass confirms that the revised panels are physically interpretable on the problematic attached intervals

### 2026-04-01 - Visible Nozzle Line Bridge Rewrite Implemented And Re-Reviewed

Completed:

- rewrote the Stage 2 `visible_nozzle_line` detector in `tools/stream_analysis/nozzle.py` so it now scores a dark bridge across the attached stream interior instead of using the older generic valley logic
- changed visible-line search-center precedence so a stable recent visible-line prior now beats a weak neck cue
- added visible-line hysteresis so once the attached dark bridge is locked, neighboring frames can keep the mode with a lower threshold instead of dropping immediately into droplet fallback
- added explicit sequential visible-line state in the per-run raw pass:
  - `stable_visible_line_y_px`
  - `visible_line_streak_length`
  - `missing_visible_line_count`
- changed tracking so short attached visible-line gaps can fill from the stable visible-line prior rather than from a generic attached anchor above the stream
- extended the Stage 2 exports and diagnostics with the new bridge/search fields:
  - `stable_visible_line_y_px`
  - `visible_line_search_center_y_px`
  - `visible_line_search_radius_px`
  - `visible_line_span_width_px`
  - `visible_line_span_fraction`
  - `visible_line_dark_delta`
  - `visible_line_vertical_overlap`
  - `visible_line_used_hysteresis`
  - `visible_line_bridge_x0_px`
  - `visible_line_bridge_x1_px`
- upgraded Stage 2 sample panels and diagnostics overlays so they now show:
  - the visible-line search band
  - the stable visible-line prior row
  - the detected bridge segment across the stream
  - the raw and final tracked markers in the context of those cues
- refreshed full `121`-frame Stage 2 review panels for:
  - `run_20260327_230520_9567e1ee`
  - `run_20260327_230807_2858b360`
  - `run_20260327_231322_ecc89833`
  - `run_20260327_231931_2fd25ece`

Files added or changed:

- `tools/stream_analysis/nozzle.py`
- `tools/stream_analysis/annotations.py`
- `tests/test_stream_analysis_nozzle.py`
- `docs/stream_analysis_plan.md`

Artifacts regenerated:

- refreshed experiment-level Stage 2 manifest:
  - `analysis/stream_characterization/nozzle_manifest.json`
- refreshed per-run Stage 2 outputs for the four reviewed runs:
  - `analysis/stream_characterization/runs/<run_id>/stage_02_nozzle/nozzle_track.csv`
  - `analysis/stream_characterization/runs/<run_id>/stage_02_nozzle/nozzle_track.json`
  - `analysis/stream_characterization/runs/<run_id>/stage_02_nozzle/shift_events.json`
  - `analysis/stream_characterization/runs/<run_id>/stage_02_nozzle/nozzle_track.png`
  - `analysis/stream_characterization/runs/<run_id>/stage_02_nozzle/sample_contact_sheet.png`
  - `analysis/stream_characterization/runs/<run_id>/stage_02_nozzle/samples/frame_<index>_panel.png`
- refreshed tuning diagnostics:
  - `analysis/stream_characterization/annotations/diagnostics/nozzle_candidate_diagnostics.csv`
  - `analysis/stream_characterization/annotations/diagnostics/nozzle_candidate_summary.json`
  - `analysis/stream_characterization/annotations/diagnostics/candidate_overlays/...`
- refreshed holdout evaluation artifacts:
  - `analysis/stream_characterization/annotations/nozzle_evaluation.csv`
  - `analysis/stream_characterization/annotations/nozzle_evaluation.json`
  - `analysis/stream_characterization/annotations/worst_frames/...`

Artifact review:

- the main regression called out in `run_20260327_230520_9567e1ee` improved materially:
  - visible-line frames `14–27` stayed clean, with median `|dy| = 1.0 px`
  - visible-line frames `28–92` now have raw `visible_nozzle_line` on `62 / 65` annotated frames
  - that same `28–92` interval now has median `|dy| = 2.0 px`
  - remaining large misses in that interval are concentrated at frames `89–92`
- the remaining visible-line outliers in `run_20260327_230520_9567e1ee` are:
  - frame `89`: raw mode falls back to `attached_black_droplet_center` and final output is `segment_fill`, with `dy = -14 px`
  - frame `90`: raw mode is `visible_nozzle_line`, but the chosen bridge sits high by `13 px`
  - frame `91`: raw mode falls back to `attached_black_droplet_center` and final output is `segment_fill`, with `dy = -13 px`
  - frame `92`: raw mode is `visible_nozzle_line`, but the chosen bridge sits high by `11 px`
- tuning diagnostics on the two annotated tuning runs now report:
  - predicted mean distance: `23.610 px`
  - predicted median distance: `3.162 px`
  - best-candidate mean distance: `20.396 px`
  - best-candidate median distance: `3.162 px`
- on the tuning set, candidate quality is strongest for:
  - `only_nozzle`: median `1.370 px`
  - `visible_nozzle_line`: median `2.236 px`
- holdout evaluation on `run_20260327_231322_ecc89833` now reports:
  - overall mean distance: `3.591 px`
  - overall median distance: `4.123 px`
  - max distance: `20.006 px`
- holdout point placement is strongest for:
  - `attached_black_droplet_center`: median `0.581 px`
  - `only_nozzle`: median `1.095 px`
  - `attached_core_separation`: median `2.476 px`
- holdout `visible_nozzle_line` point placement improved enough for review but still trails the target:
  - median distance: `5.099 px`
  - mean distance: `4.218 px`
  - mode match: `0.205`
- grip-refresh shift segmentation improved only slightly in this slice:
  - the four reviewed reruns reported shift-event counts of `0`, `0`, `1`, and `0`
  - this remains too conservative for Stage 3 to depend on without another pass

Verification:

- syntax check:
  - `.\env\Scripts\python.exe -m py_compile tools\stream_analysis\nozzle.py tools\stream_analysis\annotations.py tests\test_stream_analysis_nozzle.py`
  - result: passed
- focused Stage 2 / annotation / CLI tests:
  - `.\env\Scripts\python.exe -m pytest -q tests/test_stream_analysis_nozzle.py tests/test_stream_analysis_annotations.py tests/test_stream_analysis_cli.py`
  - result: `27 passed`
- Stage 2 regeneration on the four reviewed runs:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py nozzle --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --run-id run_20260327_230520_9567e1ee --run-id run_20260327_230807_2858b360 --run-id run_20260327_231322_ecc89833 --run-id run_20260327_231931_2fd25ece --sample-count 121`
- tuning diagnostics:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py diagnose-nozzle --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --run-id run_20260327_230520_9567e1ee --run-id run_20260327_230807_2858b360 --limit-worst-frames 50`
- holdout evaluation:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py evaluate-nozzle --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --run-id run_20260327_231322_ecc89833 --limit-worst-frames 50`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `644 passed`

Open issues:

- the visible-line bridge rewrite fixed the long mid-run regression in `run_20260327_230520_9567e1ee`, but frames `89–92` still sit too high and need a narrower end-of-regime bridge rule
- mode classification still lags the annotations even when point placement is close:
  - holdout `visible_nozzle_line` mode match is `0.205`
  - holdout `attached_core_separation` mode match is `0.000`
  - holdout `only_nozzle` mode match is `0.000`
- shift segmentation is still too conservative on the reviewed reruns and needs another pass before Stage 3 depends on shift boundaries
- `diagnose-nozzle` still overwrites the canonical experiment-local diagnostics summary when rerun on a different subset

Next steps:

- do one narrower attached-mode cleanup pass focused on:
  - end-of-regime visible-line frames like `89–92`
  - mode switching between `visible_nozzle_line`, `attached_core_separation`, and `only_nozzle`
- revisit grip-refresh segmentation using the stronger stable-mode anchors before starting Stage 3
- begin Stage 3 only after one more Stage 2 review pass confirms that the updated per-frame panels are physically interpretable across the full attached-stream interval

### 2026-04-01 - Late-Regime Visible-Line Stabilization Patch Implemented And Re-Reviewed

Completed:

- kept the bridge-based `visible_nozzle_line` detector, but changed late-regime row selection so broad valid bridge bands are no longer forced to their uppermost row
- added exported late-regime bridge-band diagnostics in `tools/stream_analysis/nozzle.py`:
  - `visible_line_band_top_y_px`
  - `visible_line_band_bottom_y_px`
  - `visible_line_band_height_px`
  - `visible_line_used_relaxed_fallback`
  - `pending_visible_line_y_px`
- added a prior-locked relaxed fallback for short attached visible-line dropouts so late frames can stay in `visible_nozzle_line` instead of immediately dropping into centroid fallback
- added pending visible-line prior confirmation so a single upward late-frame candidate cannot immediately replace the stable visible-line anchor
- tightened `_apply_tracking()` so short attached visible-line gaps fill from the stable visible-line prior first, with a capped protected-fill window, rather than immediately falling back to a generic attached anchor
- updated Stage 2 sample panels and annotation diagnostics overlays so they now show:
  - visible-line band top/bottom
  - stable visible-line prior
  - pending visible-line prior candidate
  - relaxed-fallback state

Files added or changed:

- `tools/stream_analysis/nozzle.py`
- `tools/stream_analysis/annotations.py`
- `tests/test_stream_analysis_nozzle.py`
- `docs/stream_analysis_plan.md`

Artifacts regenerated:

- refreshed per-run Stage 2 outputs for:
  - `run_20260327_230520_9567e1ee`
  - `run_20260327_230807_2858b360`
  - `run_20260327_231322_ecc89833`
  - `run_20260327_231931_2fd25ece`
- refreshed tuning diagnostics:
  - `analysis/stream_characterization/annotations/diagnostics/nozzle_candidate_diagnostics.csv`
  - `analysis/stream_characterization/annotations/diagnostics/nozzle_candidate_summary.json`
  - `analysis/stream_characterization/annotations/diagnostics/candidate_overlays/...`
- refreshed holdout evaluation artifacts:
  - `analysis/stream_characterization/annotations/nozzle_evaluation.csv`
  - `analysis/stream_characterization/annotations/nozzle_evaluation.json`
  - `analysis/stream_characterization/annotations/worst_frames/...`

Artifact review:

- `run_20260327_230520_9567e1ee` still holds the good early visible-line interval:
  - frames `14-27` keep median `|dy| = 1.0 px`
  - frames `14-27` keep max `|dy| = 1.0 px`
- the broader attached visible-line interval remains mostly stable after the late-regime patch:
  - frames `28-92` keep raw `visible_nozzle_line` on `62 / 65` annotated frames
  - frames `28-92` keep median `|dy| = 2.0 px`
  - frames `28-92` keep median distance `= 2.236 px`
- the remaining late-regime failure is now sharply localized to frames `89-92`:
  - frames `89-92` have median `|dy| = 13.0 px`
  - frames `89-92` have max `|dy| = 14.0 px`
  - frames `89` and `91` still fail strict bridge detection and land in protected `segment_fill`
  - frames `90` and `92` reacquire `visible_nozzle_line`, but at `319-320 px` instead of the annotated `331-332 px`
  - those reacquired late-frame rows now appear in the new exported `pending_visible_line_y_px` field, which confirms the current remaining issue is a bad late bridge reacquisition rather than a total loss of the stable prior
- the refreshed tuning diagnostics on the two annotated tuning runs now report:
  - predicted mean distance: `15.792 px`
  - predicted median distance: `3.041 px`
  - best-candidate mean distance: `20.191 px`
  - best-candidate median distance: `3.041 px`
- candidate quality on the tuning set is still strongest for:
  - `only_nozzle`: median `1.307 px`
  - `visible_nozzle_line`: median `2.236 px`
- holdout evaluation on `run_20260327_231322_ecc89833` improved materially:
  - overall mean distance: `5.450 px`
  - overall median distance: `2.236 px`
  - `visible_nozzle_line` median distance: `2.236 px`
  - `visible_nozzle_line` median `|dy| = 2.0 px`
  - `visible_nozzle_line` mode match: `0.855`
  - `attached_black_droplet_center` median distance: `3.041 px`
  - `attached_core_separation` median distance: `4.272 px`
  - `only_nozzle` median distance: `1.499 px`
- grip-refresh shift segmentation did not improve in this pass:
  - the four reviewed reruns still reported shift-event counts of `0`, `0`, `0`, and `0`

Verification:

- syntax check:
  - `.\env\Scripts\python.exe -m py_compile tools\stream_analysis\nozzle.py tools\stream_analysis\annotations.py tests\test_stream_analysis_nozzle.py`
  - result: passed
- focused Stage 2 / annotation / CLI tests:
  - `.\env\Scripts\python.exe -m pytest -q tests/test_stream_analysis_nozzle.py tests/test_stream_analysis_annotations.py tests/test_stream_analysis_cli.py`
  - result: `31 passed`
- Stage 2 regeneration on the four reviewed runs:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py nozzle --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --run-id run_20260327_230520_9567e1ee --run-id run_20260327_230807_2858b360 --run-id run_20260327_231322_ecc89833 --run-id run_20260327_231931_2fd25ece --sample-count 121`
- tuning diagnostics:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py diagnose-nozzle --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --run-id run_20260327_230520_9567e1ee --run-id run_20260327_230807_2858b360 --limit-worst-frames 50`
- holdout evaluation:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py evaluate-nozzle --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --run-id run_20260327_231322_ecc89833 --limit-worst-frames 50`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `648 passed`

Open issues:

- frames `89-92` in `run_20260327_230520_9567e1ee` still sit too high at the end of the visible-line regime
- the late-regime pending-prior confirmation now exposes the remaining error clearly, but it is still confirming the wrong reacquired bridge row around `319-320 px`
- mode classification still lags the annotations for:
  - `attached_black_droplet_center`
  - `attached_core_separation`
  - `only_nozzle`
- shift segmentation is still too conservative for Stage 3 to depend on

Next steps:

- do one narrower Stage 2 pass focused only on end-of-regime attached visible-line reacquisition:
  - refine frames like `89-92`
  - bias late broad bands toward the lower boundary / top of the lower bright core instead of the current narrow reacquired bridge
- revisit mode switching between `visible_nozzle_line`, `attached_core_separation`, and `only_nozzle`
- revisit grip-refresh segmentation before starting Stage 3

### 2026-04-01 - Contour-Robust Late-Visible-Line Patch Implemented And Re-Reviewed

Completed:

- split the Stage 2 mask path in `tools/stream_analysis/nozzle.py` so the exported detector now uses:
  - a stricter `strong_mask` for bridge scoring
  - a more permissive `contour_mask` for filled outer-contour geometry
- replaced the old outer-contour cleanup with:
  - strong-mask cleanup on the stricter path
  - weak connected-pixel retention on the contour path
  - local weak-pixel contour augmentation near the stable visible-line prior
- added contour-completeness diagnostics ahead of bridge scoring:
  - `contour_completeness_score`
  - `contour_bilateral_row_fraction`
  - `contour_width_median_px`
  - `contour_width_iqr_px`
  - `contour_clipped_warning`
- added a late attached widening cue inside `visible_nozzle_line` and exported:
  - `late_widening_y_px`
  - `late_widening_score`
  - `late_widening_used`
  - `bridge_suppressed_by_clipped_contour`
- tightened the widening logic so it is only allowed as a true late-stage fallback around an already-established visible-line prior
- updated Stage 2 sample panels and annotation diagnostics overlays so they now show:
  - the permissive contour
  - contour-clipped warnings
  - widening-candidate rows
  - whether widening won or a bridge was suppressed

Files added or changed:

- `tools/stream_analysis/nozzle.py`
- `tools/stream_analysis/annotations.py`
- `tests/test_stream_analysis_nozzle.py`
- `docs/stream_analysis_plan.md`

Artifacts regenerated:

- refreshed per-run Stage 2 outputs for:
  - `run_20260327_230520_9567e1ee`
  - `run_20260327_230807_2858b360`
  - `run_20260327_231322_ecc89833`
  - `run_20260327_231931_2fd25ece`
- refreshed tuning diagnostics:
  - `analysis/stream_characterization/annotations/diagnostics/nozzle_candidate_diagnostics.csv`
  - `analysis/stream_characterization/annotations/diagnostics/nozzle_candidate_summary.json`
  - `analysis/stream_characterization/annotations/diagnostics/candidate_overlays/...`
- refreshed holdout evaluation artifacts:
  - `analysis/stream_characterization/annotations/nozzle_evaluation.csv`
  - `analysis/stream_characterization/annotations/nozzle_evaluation.json`
  - `analysis/stream_characterization/annotations/worst_frames/...`

Artifact review:

- the contour/widening patch preserved the already-good attached visible-line middle interval in `run_20260327_230520_9567e1ee`:
  - frames `14-27` still stay on `visible_nozzle_line`
  - frames `14-27` still keep median `|dy| = 1.0 px`
  - frames `28-92` still keep raw `visible_nozzle_line` on `62 / 65` annotated frames
  - frames `28-92` still keep median `|dy| = 2.0 px`
- the late four-frame target improved, but is not fully solved:
  - frames `89-92` now keep median `|dy| = 10.5 px`
  - frame `89` now lands at `329 px` via protected fill instead of collapsing far above the nozzle
  - frames `90`, `91`, and `92` still sit too high, at roughly `319-321 px` versus annotated `331-333 px`
- the refreshed tuning diagnostics on the two annotated tuning runs now report:
  - predicted mean distance: `4.340 px`
  - predicted median distance: `2.236 px`
  - best-candidate mean distance: `8.495 px`
  - best-candidate median distance: `2.236 px`
- the attached visible-line regime is now the strongest tuned family in the candidate report:
  - `visible_nozzle_line` candidate median distance: `2.5 px`
  - `visible_nozzle_line` predicted median distance: `2.5 px`
- holdout evaluation on `run_20260327_231322_ecc89833` stayed within the desired range:
  - overall mean distance: `3.446 px`
  - overall median distance: `2.236 px`
  - `visible_nozzle_line` median distance: `2.236 px`
  - `visible_nozzle_line` mode match: `0.880`
  - `attached_black_droplet_center` median distance: `3.0 px`
  - `attached_core_separation` median distance: `1.605 px`
  - `only_nozzle` median distance: `1.803 px`
- shift segmentation remains a weak point:
  - the latest four-run rerender reported shift-event counts of `0`, `0`, `0`, and `0`

Verification:

- syntax check:
  - `.\env\Scripts\python.exe -m py_compile tools\stream_analysis\nozzle.py tools\stream_analysis\annotations.py tests\test_stream_analysis_nozzle.py`
  - result: passed
- focused Stage 2 / annotation / CLI tests:
  - `.\env\Scripts\python.exe -m pytest -q tests/test_stream_analysis_nozzle.py tests/test_stream_analysis_annotations.py tests/test_stream_analysis_cli.py`
  - result: `36 passed`
- Stage 2 regeneration on the four reviewed runs:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py nozzle --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --run-id run_20260327_230520_9567e1ee --run-id run_20260327_230807_2858b360 --run-id run_20260327_231322_ecc89833 --run-id run_20260327_231931_2fd25ece --sample-count 121`
- tuning diagnostics:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py diagnose-nozzle --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --run-id run_20260327_230520_9567e1ee --run-id run_20260327_230807_2858b360 --limit-worst-frames 50`
- holdout evaluation:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py evaluate-nozzle --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --run-id run_20260327_231322_ecc89833 --limit-worst-frames 50`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `653 passed`

Open issues:

- frames `90-92` in `run_20260327_230520_9567e1ee` still reacquire the visible-line nozzle too high near `319-321 px`
- the permissive contour split helped the late regime, but frame `89` still does not reacquire a valid raw visible-line candidate; it succeeds only because protected fill now holds the stable prior
- mode classification still lags the annotations for:
  - `attached_black_droplet_center`
  - `attached_core_separation`
  - `only_nozzle`
- shift segmentation is still too conservative for Stage 3 to depend on

Next steps:

- do one narrower Stage 2 pass focused on end-of-regime attached visible-line reacquisition:
  - bias late broad bands toward the lower boundary / top of the lower bright core in frames like `90-92`
  - let late attached widening participate only when it agrees with that lower-boundary cue
- revisit the raw reacquisition logic for frame `89` so the late visible-line cue can recover without depending on protected fill
- revisit grip-refresh segmentation before starting Stage 3

### 2026-04-01 - Focused Late Visible-Line Plateau Patch Implemented And Re-Reviewed

Goal:

- fix the remaining late attached `visible_nozzle_line` drift in `run_20260327_230520_9567e1ee` frames `89-92` without disturbing the already-good visible-line middle interval or the holdout run

Completed:

- added a focused late-stage refinement in `tools/stream_analysis/nozzle.py` that:
  - prefers a near-prior hysteresis-valid bridge over a fresh bridge that sits too far above the stable visible-line prior
  - rewrites the late widening cue into a prior-centered width plateau cue instead of using the onset/top of widening
  - suppresses late high bridges when the plateau cue stays closer to the stable prior
  - prevents plateau-driven or relaxed-fallback late recoveries from redefining the stable visible-line anchor immediately
- extended the late-stage diagnostics exports and overlays with:
  - `visible_line_lower_peak_prior_constrained`
  - `visible_line_effective_lower_peak_y_px`
  - `bridge_suppressed_by_plateau`
  - `late_plateau_band_top_y_px`
  - `late_plateau_band_bottom_y_px`
  - `late_plateau_picked_y_px`
- added focused tests covering:
  - near-prior hysteresis beating a too-high fresh bridge
  - plateau fallback when the contour is complete but no bridge survives
  - plateau-based late recovery not updating the stable visible-line prior
  - plateau-centered late widening selection

Files added or changed:

- `tools/stream_analysis/nozzle.py`
- `tools/stream_analysis/annotations.py`
- `tests/test_stream_analysis_nozzle.py`
- `docs/stream_analysis_plan.md`

Validation:

- syntax check:
  - `.\env\Scripts\python.exe -m py_compile tools\stream_analysis\nozzle.py tools\stream_analysis\annotations.py tests\test_stream_analysis_nozzle.py`
  - result: passed
- focused Stage 2 / annotation / CLI tests:
  - `.\env\Scripts\python.exe -m pytest -q tests/test_stream_analysis_nozzle.py tests/test_stream_analysis_annotations.py tests/test_stream_analysis_cli.py`
  - result: `39 passed`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `656 passed`

Artifacts regenerated:

- refreshed per-run Stage 2 outputs with `sample-count 121` for:
  - `run_20260327_230520_9567e1ee`
  - `run_20260327_230807_2858b360`
  - `run_20260327_231322_ecc89833`
  - `run_20260327_231931_2fd25ece`
- refreshed tuning diagnostics:
  - `analysis/stream_characterization/annotations/diagnostics/nozzle_candidate_diagnostics.csv`
  - `analysis/stream_characterization/annotations/diagnostics/nozzle_candidate_summary.json`
  - `analysis/stream_characterization/annotations/diagnostics/candidate_overlays/...`
- refreshed holdout evaluation artifacts:
  - `analysis/stream_characterization/annotations/nozzle_evaluation.csv`
  - `analysis/stream_characterization/annotations/nozzle_evaluation.json`
  - `analysis/stream_characterization/annotations/worst_frames/...`

Artifact review:

- the already-good visible-line interval stayed stable in `run_20260327_230520_9567e1ee`:
  - frames `14-27` keep median `|dy| = 1.0 px`
  - frames `28-92` keep median `|dy| = 2.0 px`
  - frames `28-92` now keep raw `visible_nozzle_line` on `65 / 65` annotated frames
- the targeted late interval is now much closer to the annotations:
  - frames `89-92` now keep median `|dy| = 3.0 px`
  - frame `89`: tracked `329 px` vs annotated `333 px`
  - frame `90`: tracked `329 px` vs annotated `332 px`
  - frame `91`: tracked `329 px` vs annotated `332 px`
  - frame `92`: tracked `332 px` vs annotated `331 px`
- refreshed tuning diagnostics on the two annotated tuning runs now report:
  - predicted mean distance: `4.340 px`
  - predicted median distance: `2.236 px`
  - best-candidate mean distance: `6.069 px`
  - best-candidate median distance: `2.236 px`
- holdout evaluation on `run_20260327_231322_ecc89833` stayed stable:
  - overall mean distance: `3.446 px`
  - overall median distance: `2.236 px`
  - `visible_nozzle_line` median distance: `2.236 px`
  - `visible_nozzle_line` mode match: `0.880`
  - `attached_black_droplet_center` median distance: `3.0 px`
  - `attached_core_separation` median distance: `1.605 px`
  - `only_nozzle` median distance: `1.803 px`
- shift segmentation is still unresolved:
  - the latest four-run rerender still reports shift-event counts of `0`, `0`, `0`, and `0`

Open issues after this patch:

- the late interval is now usable for review, but frames `89-91` still sit a few pixels above the annotated nozzle band
- mode matching still lags point-placement quality for:
  - `attached_black_droplet_center`
  - `attached_core_separation`
  - `only_nozzle`
- shift segmentation is still too conservative for Stage 3 to trust

Next recommended step:

- review the refreshed `samples/` panels for the four rerun runs, especially `run_20260327_230520_9567e1ee` frames `89-92`
- if the remaining `3-4 px` late offset matters for Stage 3 volume anchoring, do one last narrow late-attachment calibration pass before starting Stage 3
- otherwise, pivot to finishing shift detection before Stage 3 begins

### 2026-04-01 - Focused Visible-Line To Only-Nozzle Transition Patch Implemented And Re-Reviewed

Goal:

- fix the late transition in `run_20260327_230807_2858b360` frames `93-96` without disturbing the already-good late attached behavior in `run_20260327_230520_9567e1ee` or the holdout run

Completed:

- added a focused late-transition refinement in `tools/stream_analysis/nozzle.py` that:
  - suppresses late `visible_nozzle_line` bridges when they conflict symmetrically with the stable visible-line prior and the plateau cue stays closer to that prior
  - adds a small multi-center ROI sweep for `only_nozzle` so transition frames no longer depend on one exact detached-search center
  - suppresses reflection-like droplet candidates when attached support has collapsed and the candidate sits far above the stable visible-line prior
  - preserves the stable visible-line prior across the first few near-prior detached frames so low-confidence but correct `only_nozzle` raw detections can remain final instead of being downgraded to generic fill
- extended diagnostics exports and overlays with:
  - `bridge_suppressed_by_prior_conflict`
  - `late_bridge_delta_from_prior_px`
  - `late_plateau_delta_from_prior_px`
  - `only_nozzle_roi_centers_y_px`
  - `only_nozzle_selected_roi_center_y_px`
  - `droplet_suppressed_as_reflection`
  - `transition_fill_used`
  - `transition_fill_source`
  - `anchor_rejected_as_reflection`
- added focused tests covering:
  - plateau/prior conflict beating a strong late bridge below the prior
  - reflection-droplet suppression during the visible-line to nozzle-only transition
  - `only_nozzle` ROI-center sweeping
  - stable visible-line prior preservation across nearby detached transition frames
  - transition tracking keeping low-confidence but near-prior `only_nozzle` raw detections as final results

Files added or changed:

- `tools/stream_analysis/nozzle.py`
- `tools/stream_analysis/annotations.py`
- `tests/test_stream_analysis_nozzle.py`
- `docs/stream_analysis_plan.md`

Validation:

- syntax check:
  - `.\env\Scripts\python.exe -m py_compile tools\stream_analysis\nozzle.py tools\stream_analysis\annotations.py tests\test_stream_analysis_nozzle.py`
  - result: passed
- focused Stage 2 / annotation / CLI tests:
  - `.\env\Scripts\python.exe -m pytest -q tests\test_stream_analysis_nozzle.py tests\test_stream_analysis_annotations.py tests\test_stream_analysis_cli.py`
  - result: `47 passed`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `664 passed`

Artifacts regenerated:

- refreshed per-run Stage 2 outputs with `sample-count 121` for:
  - `run_20260327_230520_9567e1ee`
  - `run_20260327_230807_2858b360`
  - `run_20260327_231322_ecc89833`
  - `run_20260327_231931_2fd25ece`
- refreshed tuning diagnostics:
  - `analysis/stream_characterization/annotations/diagnostics/nozzle_candidate_diagnostics.csv`
  - `analysis/stream_characterization/annotations/diagnostics/nozzle_candidate_summary.json`
  - `analysis/stream_characterization/annotations/diagnostics/candidate_overlays/...`
- refreshed holdout evaluation artifacts:
  - `analysis/stream_characterization/annotations/nozzle_evaluation.csv`
  - `analysis/stream_characterization/annotations/nozzle_evaluation.json`
  - `analysis/stream_characterization/annotations/worst_frames/...`

Artifact review:

- the late attached run stayed stable:
  - `run_20260327_230520_9567e1ee` frames `14-27` still keep median `|dy| = 1.0 px`
  - `run_20260327_230520_9567e1ee` frames `28-92` still keep median `|dy| = 2.0 px`
  - `run_20260327_230520_9567e1ee` frames `89-92` stay at median `|dy| = 3.0 px`
- the targeted late transition now behaves correctly in `run_20260327_230807_2858b360`:
  - frame `93`: final mode `visible_nozzle_line`, tracked `340 px` vs annotated `337 px`
  - frame `94`: raw/final mode `only_nozzle`, tracked `335.368 px` vs annotated `336 px`, with the reflected droplet suppressed and the selected detached ROI center at `332 px`
  - frame `95`: raw/final mode `only_nozzle`, tracked `335.095 px` vs annotated `336 px`
  - frame `96`: raw/final mode `only_nozzle`, tracked `335.220 px` vs annotated `336 px`
  - the late transition interval `93-96` no longer jumps upward to the reflected droplet or falls back to generic segment fill
- refreshed tuning diagnostics on the two annotated tuning runs now report:
  - predicted mean distance: `2.995 px`
  - predicted median distance: `2.236 px`
  - best-candidate mean distance: `5.462 px`
  - best-candidate median distance: `2.236 px`
- holdout evaluation on `run_20260327_231322_ecc89833` stayed stable:
  - overall mean distance: `2.508 px`
  - overall median distance: `2.236 px`
  - `visible_nozzle_line` median distance: `2.236 px`
  - `visible_nozzle_line` mode match: `0.916`
  - `attached_black_droplet_center` median distance: `1.803 px`
  - `attached_core_separation` median distance: `1.605 px`
  - `only_nozzle` median distance: `1.382 px`
- shift segmentation is still unresolved:
  - the latest four-run rerender still reports shift-event counts of `0`, `0`, `0`, and `0`

Open issues after this patch:

- frame `93` in `run_20260327_230807_2858b360` still sits about `3 px` low because the late bridge row still edges out the plateau cue there
- mode matching still lags point-placement quality for:
  - `attached_black_droplet_center`
  - `attached_core_separation`
  - `only_nozzle`
- shift segmentation is still too conservative for Stage 3 to trust

Next recommended step:

- review the refreshed `samples/` panels for `run_20260327_230807_2858b360` frames `93-96` and confirm the late transition is now acceptable for Stage 3 anchoring
- if the remaining `3 px` offset on frame `93` matters, do one final narrow late-visible-line preference pass before touching shift logic
- otherwise, pivot to finishing shift detection before Stage 3 begins

## Holdout Focused Patch: Frames 90-93

Call path reviewed:

- `tools/run_stream_analysis.py` -> `tools/stream_analysis/cli.py` -> `tools/stream_analysis/nozzle.py`
- diagnostics / overlays in `tools/stream_analysis/annotations.py`

Scope of this patch:

- `run_20260327_231322_ecc89833` frames `90-92`
  - allow late `visible_nozzle_line` recovery from the width plateau even when no strict bridge row survives
  - allow thick late-band rows near the stable visible prior to remain valid without being treated as fresh narrow-bridge detections
  - tighten bridge-vs-plateau conflict handling so the detector stays locked to the stable late band
- `run_20260327_231322_ecc89833` frame `93`
  - make `only_nozzle` transition scoring prior-aware so the actual nozzle contour near the stable prior beats the lower round reflected droplet
  - export the transition-scoring and lower-reflection rejection diagnostics through both Stage 2 CSV/JSON outputs and annotation diagnostics overlays

Files changed:

- `tools/stream_analysis/nozzle.py`
- `tools/stream_analysis/annotations.py`
- `tests/test_stream_analysis_nozzle.py`
- `docs/stream_analysis_plan.md`

Validation:

- syntax check:
  - `.\env\Scripts\python.exe -m py_compile tools\stream_analysis\nozzle.py tools\stream_analysis\annotations.py tests\test_stream_analysis_nozzle.py`
  - result: passed
- focused Stage 2 / annotation / CLI tests:
  - `.\env\Scripts\python.exe -m pytest -q tests\test_stream_analysis_nozzle.py tests\test_stream_analysis_annotations.py tests\test_stream_analysis_cli.py`
  - result: `51 passed`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `668 passed`

Artifacts regenerated:

- refreshed per-run Stage 2 outputs with `sample-count 121` for:
  - `run_20260327_230520_9567e1ee`
  - `run_20260327_230807_2858b360`
  - `run_20260327_231322_ecc89833`
  - `run_20260327_231931_2fd25ece`
- refreshed tuning diagnostics:
  - `analysis/stream_characterization/annotations/diagnostics/nozzle_candidate_diagnostics.csv`
  - `analysis/stream_characterization/annotations/diagnostics/nozzle_candidate_summary.json`
- refreshed holdout evaluation artifacts:
  - `analysis/stream_characterization/annotations/nozzle_evaluation.csv`
  - `analysis/stream_characterization/annotations/nozzle_evaluation.json`

Artifact review:

- targeted holdout frames now behave as intended:
  - `run_20260327_231322_ecc89833` frame `90`:
    - raw/final mode `visible_nozzle_line`
    - tracked y `329 px` vs annotated `331 px`
    - `visible_line_used_plateau_only_fallback = True`
  - `run_20260327_231322_ecc89833` frame `91`:
    - raw/final mode `visible_nozzle_line`
    - tracked y `329 px` vs annotated `331 px`
    - `visible_line_used_plateau_only_fallback = True`
  - `run_20260327_231322_ecc89833` frame `92`:
    - raw/final mode `visible_nozzle_line`
    - tracked y `329 px` vs annotated `330 px`
    - stays on the late band without reverting to generic fill
  - `run_20260327_231322_ecc89833` frame `93`:
    - raw/final mode `only_nozzle`
    - tracked y `329.06 px` vs annotated `330 px`
    - `only_nozzle_transition_scoring_used = True`
    - `only_nozzle_rejected_lower_reflection = True`
- no material regression in the previously stabilized runs:
  - `run_20260327_230520_9567e1ee` frames `89-92` remain:
    - `89`: `329 px`
    - `90`: `329 px`
    - `91`: `329 px`
    - `92`: `332 px`
  - `run_20260327_230807_2858b360` frames `93-96` remain:
    - `93`: `340 px`
    - `94`: `335.37 px`
    - `95`: `335.09 px`
    - `96`: `335.22 px`
- holdout evaluation remains stable:
  - overall mean distance: `1.944 px`
  - overall median distance: `2.236 px`
  - `visible_nozzle_line` median distance: `2.236 px`
  - `visible_nozzle_line` mode match: `0.952`
  - `only_nozzle` median distance: `1.263 px`

Late detached `only_nozzle` prior-band rescue:

- added a narrow prior-band Otsu pass for the first detached frames after `visible_nozzle_line`
- this rescues faint nozzle strips near the stable visible-line prior when whole-ROI Otsu only sees large upper/lower blobs
- transition scoring now:
  - zeros out `upperness` beyond `12 px` from the stable prior
  - gives a source bonus to `prior_band` candidates within `12 px`
  - rejects detached candidates farther than `20 px` from the stable prior unless a much stronger near-prior cue is absent
- target regression:
  - `run_20260327_230520_9567e1ee` frame `93`
  - actual outcome after rerender:
    - raw/final mode `only_nozzle`
    - tracked y `328.53 px` vs annotated `329 px`
    - `only_nozzle_candidate_source = prior_band`
    - `only_nozzle_prior_band_used = True`
    - `only_nozzle_rejected_far_from_prior = True`
- verified no meaningful regression in the previously stabilized transition windows:
  - `run_20260327_230807_2858b360` frames `94-96` remain near `335.5 px`
  - `run_20260327_231322_ecc89833` frames `90-93` remain:
    - `90`: `329 px`
    - `91`: `329 px`
    - `92`: `329 px`
    - `93`: `328.79 px`

Open issues after this patch:

- the holdout point placement is now good on `90-93`, but some non-targeted holdout frames still dominate the worst-frame list
- mode matching still trails point placement quality for:
  - `attached_black_droplet_center`
  - `attached_core_separation`
- shift segmentation is still unresolved:
  - the latest four-run rerender still reports shift-event counts of `0`, `0`, `0`, and `0`

Next recommended step:

- treat the Stage 2 nozzle-point retune as good enough to shift attention to grip-refresh segmentation
- if mode labels become important before Stage 3, do one small attached-family classifier cleanup pass without moving the point detector again

## Hollow-Bulb Acquisition Patch

Scope of this patch:

- `run_20260327_231931_2fd25ece` frames `5-80`
  - prevent first-time `visible_nozzle_line` acquisition from locking onto the lower closure of a hollow/U-shaped attached bulb
  - keep lower-bulb plateau cues from seeding the stable visible-line prior on no-prior frames
- `run_20260328_005146_dd931d49` frames `4-67`
  - apply the same hollow-bulb acquisition protections and provisional-anchor rules
- follow-up regression cleanup:
  - restore `run_20260327_230520_9567e1ee` after the first hollow-bulb pass over-constrained early acquisition on tall attached components

Files changed:

- `tools/stream_analysis/nozzle.py`
- `tools/stream_analysis/annotations.py`
- `tests/test_stream_analysis_nozzle.py`
- `docs/stream_analysis_plan.md`

Implementation notes:

- no-prior `visible_nozzle_line` acquisition is now upper-neck biased instead of using the first taper as the main reacquisition seed
- added a hollow-bulb morphology guard so lower-closure bridge rows are rejected on first acquisition frames
- added provisional visible-line state so suspicious first line rows do not immediately become stable anchors or segment-fill sources
- excluded provisional visible-line rows from generic fill-anchor propagation
- added acquisition diagnostics and overlays for:
  - acquisition search center and upper bound
  - hollow-bulb guard activity and rejection
  - provisional visible-line state
  - acquisition plateau suppression and upper-cue conflict rejection
- follow-up adjustment:
  - made the acquisition upper bound adaptive to recent upper attached continuity, capped at the upper `62%` of the component
  - this preserved the hollow-bulb protections while restoring legitimate early line acquisition in `run_20260327_230520_9567e1ee`

Validation:

- syntax check:
  - `.\env\Scripts\python.exe -m py_compile tools\stream_analysis\nozzle.py tests\test_stream_analysis_nozzle.py tools\stream_analysis\annotations.py`
  - result: passed
- focused Stage 2 / annotation / CLI tests:
  - `.\env\Scripts\python.exe -m pytest -q tests\test_stream_analysis_nozzle.py tests\test_stream_analysis_annotations.py tests\test_stream_analysis_cli.py`
  - result: `66 passed`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `683 passed`

Artifacts regenerated:

- refreshed per-run Stage 2 outputs with `sample-count 121` for:
  - `run_20260327_231931_2fd25ece`
  - `run_20260328_005146_dd931d49`
  - `run_20260327_230520_9567e1ee`
  - `run_20260327_230807_2858b360`
  - `run_20260327_231322_ecc89833`
- refreshed tuning diagnostics:
  - `analysis/stream_characterization/annotations/diagnostics/nozzle_candidate_diagnostics.csv`
  - `analysis/stream_characterization/annotations/diagnostics/nozzle_candidate_summary.json`
- refreshed annotated-set evaluation:
  - `analysis/stream_characterization/annotations/nozzle_evaluation.csv`
  - `analysis/stream_characterization/annotations/nozzle_evaluation.json`

Artifact review:

- newly annotated hollow-bulb runs now hold the nozzle correctly through the targeted acquisition intervals:
  - `run_20260327_231931_2fd25ece`
    - mean distance: `2.138 px`
    - median distance: `1.803 px`
    - targeted interval `5-80` no longer locks onto the lower bulb closure
  - `run_20260328_005146_dd931d49`
    - mean distance: `2.362 px`
    - median distance: `2.255 px`
    - targeted interval `4-67` no longer locks onto the lower bulb closure
- the temporary regression in `run_20260327_230520_9567e1ee` was recovered by the adaptive acquisition-bound follow-up:
  - mean distance: `3.029 px`
  - median distance: `2.062 px`
  - mode match: `0.843`
- previously stabilized runs remained effectively unchanged:
  - `run_20260327_230807_2858b360`
    - mean distance: `3.244 px`
    - median distance: `3.143 px`
  - `run_20260327_231322_ecc89833`
    - mean distance: `1.958 px`
    - median distance: `2.236 px`

Open issues after this patch:

- a few early `run_20260327_230520_9567e1ee` frames still dominate the worst-frame list because tracked values lag a late raw reacquisition by several frames even though the run-level median is back in range
- mode matching still trails point placement quality for:
  - `attached_black_droplet_center`
  - `attached_core_separation`
- shift segmentation remains too conservative to trust as a Phase 3 boundary signal

Next recommended step:

- use the tracked nozzle point directly for Stage 3 silhouette extraction and keep grip-refresh segmentation explicitly out of the critical path for now
- if the early tracked lag on `run_20260327_230520_9567e1ee` matters during later review, do one narrow tracking-cap cleanup pass without changing the raw point detector again

### Early attached fallback and tracking recovery pass

Goal:

- fix the early attached regression in `run_20260327_230520_9567e1ee` frames `8-13` without disturbing the hollow-bulb acquisition protections or the already-stable late transition behavior in the other reviewed runs

Root cause:

- frames `8-9` did not have a usable raw line/core cue, so `_apply_tracking()` accepted very weak `attached_black_droplet_center` points through `local_raw_fallback`
- those low-confidence fallback points then became the recent attached tracked reference
- frames `10-13` already had good raw `visible_nozzle_line` detections, but the attached `12 px/frame` cap still ramped from the bad fallback anchors instead of snapping back to the recovered raw nozzle row

Implementation:

- tightened `local_raw_fallback` in `_apply_tracking()` so early attached fallback is only allowed when the raw point is either:
  - reasonably confident, or
  - vertically close to the recent attached reference / acquisition search center
- added a short `attached_continuity_hold` path so rejected weak fallback points hold the previous tracked attached y for up to `2` frames instead of snapping to implausible droplet centroids
- made the attached tracking cap source-aware so prior `segment_fill`, `local_raw_fallback`, and `attached_continuity_hold` rows cannot act as trusted cap references
- added a reacquisition override so strong recovered `visible_nozzle_line` or `attached_core_separation` rows bypass the cap and snap directly to the raw y
- exported and rendered new diagnostics for:
  - fallback rejection and reference y
  - continuity hold usage/count
  - cap application / cap reference source
  - cap bypass on strong reacquisition

Validation:

- syntax check:
  - `.\env\Scripts\python.exe -m py_compile tools\stream_analysis\nozzle.py tools\stream_analysis\annotations.py tests\test_stream_analysis_nozzle.py`
  - result: passed
- focused Stage 2 / annotation / CLI tests:
  - `.\env\Scripts\python.exe -m pytest -q tests\test_stream_analysis_nozzle.py tests\test_stream_analysis_annotations.py tests\test_stream_analysis_cli.py`
  - result: `69 passed`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `686 passed`
- reran Stage 2 with `sample-count 121` for:
  - `run_20260327_230520_9567e1ee`
  - `run_20260327_231931_2fd25ece`
  - `run_20260328_005146_dd931d49`
  - `run_20260327_230807_2858b360`
  - `run_20260327_231322_ecc89833`
- refreshed tuning diagnostics:
  - `analysis/stream_characterization/annotations/diagnostics/nozzle_candidate_diagnostics.csv`
  - `analysis/stream_characterization/annotations/diagnostics/nozzle_candidate_summary.json`
- refreshed annotated-set evaluation:
  - `analysis/stream_characterization/annotations/nozzle_evaluation.csv`
  - `analysis/stream_characterization/annotations/nozzle_evaluation.json`

Artifact review:

- the targeted `run_20260327_230520_9567e1ee` regression is now corrected:
  - frame `8`:
    - weak droplet centroid `312.46 px` rejected
    - `attached_continuity_hold` used
    - tracked y held at `327.37 px`
  - frame `9`:
    - weak droplet centroid `277.62 px` rejected
    - `attached_continuity_hold` used
    - tracked y held at `327.37 px`
  - frames `10-13`:
    - strong recovered raw `visible_nozzle_line` rows at `325 / 329 / 327 / 327 px`
    - cap bypassed for reacquisition
    - tracked y now snaps directly to the raw line row instead of lagging upward
- updated annotated-set evaluation remains stable overall:
  - overall mean distance: `2.333 px`
  - overall median distance: `2.236 px`
- per-run evaluation after the fix:
  - `run_20260327_230520_9567e1ee`
    - mean distance: `2.016 px`
    - median distance: `1.997 px`
    - mode match: `0.843`
  - `run_20260327_231931_2fd25ece`
    - mean distance: `2.138 px`
    - median distance: `1.803 px`
  - `run_20260328_005146_dd931d49`
    - mean distance: `2.362 px`
    - median distance: `2.255 px`
  - `run_20260327_230807_2858b360`
    - mean distance: `3.244 px`
    - median distance: `3.143 px`
  - `run_20260327_231322_ecc89833`
    - mean distance: `1.958 px`
    - median distance: `2.236 px`

Open issues after this patch:

- the reviewed runs now hold the nozzle correctly through the specifically tuned intervals
- mode matching still trails point-placement quality for:
  - `attached_black_droplet_center`
  - `attached_core_separation`
- shift segmentation remains too conservative to trust as a Phase 3 boundary signal, but the tracked nozzle point is now stable enough to use directly for Phase 3 silhouette extraction

### 2026-04-03 - Phase 3 silhouette extraction implemented and reviewed

Call path implemented:

- `tools/run_stream_analysis.py` -> `tools/stream_analysis/cli.py` -> reusable Stage 2 builder in `tools/stream_analysis/nozzle.py` -> `tools/stream_analysis/silhouette.py`

Files changed:

- `tools/stream_analysis/silhouette.py`
- `tools/stream_analysis/nozzle.py`
- `tools/stream_analysis/cli.py`
- `tests/test_stream_analysis_silhouette.py`
- `tests/test_stream_analysis_cli.py`
- `docs/stream_analysis_plan.md`

Implemented:

- added Stage 3 export code in `tools/stream_analysis/silhouette.py` with:
  - dynamic ROI recentered on the tracked nozzle `x`
  - direct grayscale Otsu thresholding inside the ROI
  - corridor masking around the tracked nozzle `x`
  - below-nozzle cutoff using `tracked_nozzle_y_px + nozzle_guard_px`
  - morphology + hole fill so bright-core gaps collapse into one filled silhouette
  - nozzle-anchored connected-component selection rather than largest-component-only selection
  - per-row edge tracing exported as absolute `x_left_px`, `x_right_px`, `width_px`, and `center_x_px`
  - sample panels showing the tracked nozzle marker, cutoff line, raw mask, selected filled mask, and contour/edge overlays
- added a reusable internal Stage 2 run builder in `tools/stream_analysis/nozzle.py` so Stage 3 recomputes tracked nozzle rows in-process instead of requiring pre-existing Stage 2 files on disk
- added a `silhouette` command to `tools/stream_analysis/cli.py`
- added focused synthetic Stage 3 tests and a CLI integration test
- removed an old debug print from Stage 2 track plotting so CLI commands keep stdout machine-readable JSON

Validation:

- syntax check:
  - `.\env\Scripts\python.exe -m py_compile tools\stream_analysis\silhouette.py tools\stream_analysis\cli.py tools\stream_analysis\nozzle.py tests\test_stream_analysis_silhouette.py tests\test_stream_analysis_cli.py`
  - result: passed
- focused stream-analysis tests:
  - `.\env\Scripts\python.exe -m pytest -q tests\test_stream_analysis_silhouette.py tests\test_stream_analysis_cli.py tests\test_stream_analysis_nozzle.py`
  - result: `67 passed`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `692 passed`
- real-data Stage 3 export review:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py silhouette --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --output-root "tmp\stream_analysis_phase3_review" --run-id run_20260327_225848_829e10c1 --run-id run_20260327_230520_9567e1ee --run-id run_20260327_230807_2858b360 --run-id run_20260327_231322_ecc89833 --run-id run_20260327_231931_2fd25ece --run-id run_20260328_005146_dd931d49 --sample-count 12 --nozzle-guard-px 2 --min-component-area-px 120`
  - result: passed

Artifacts generated for review:

- `tmp/stream_analysis_phase3_review/silhouette_manifest.json`
- per-run Stage 3 outputs under:
  - `tmp/stream_analysis_phase3_review/runs/<run_id>/stage_03_silhouette/`

Artifact review summary:

- run-level status counts:
  - `run_20260327_225848_829e10c1`: `121 ok`
  - `run_20260327_230520_9567e1ee`: `120 ok`, `1 empty_mask`
  - `run_20260327_230807_2858b360`: `120 ok`, `1 empty_mask`
  - `run_20260327_231322_ecc89833`: `120 ok`, `1 no_component_selected`
  - `run_20260327_231931_2fd25ece`: `118 ok`, `3 empty_mask`
  - `run_20260328_005146_dd931d49`: `116 ok`, `5 empty_mask`
- all successful frames in the six-run review set produced contiguous `y` coverage with no row gaps in `edge_traces.csv`
- late-frame failures cluster where Stage 2 is already in low-confidence detached or `segment_fill` territory, which is consistent with the current Phase 3 policy of surfacing weak downstream geometry explicitly rather than silently fabricating edges

Open issues after this phase:

- a handful of very late detached frames end in `empty_mask` after the below-nozzle cutoff and direct-threshold path remove all usable signal
- `run_20260327_231322_ecc89833` frame `121` produced `no_component_selected` instead of `ok`
- Stage 3 currently reports low-confidence / `segment_fill`-anchored silhouettes faithfully, but Stage 4 will need to decide how those frames affect trust and FOV-exit labeling
- shift segmentation remains too conservative to use as a required Phase 3 dependency and stays out of the critical path

Next recommended step:

- begin Stage 4 visible-volume integration directly from `edge_traces.csv` / `edge_traces.json`
- define the Stage 4 trust/FOV rule around the current late-frame `empty_mask` and `no_component_selected` outcomes
- if late detached frame coverage becomes important, do one narrow Phase 3 selector/threshold refinement pass without reopening the Stage 2 point detector

### 2026-04-03 - Stage 3 open-bottom fill refinement for long attached streams

Call path updated:

- `tools/run_stream_analysis.py` -> `tools/stream_analysis/cli.py` -> reusable Stage 2 builder in `tools/stream_analysis/nozzle.py` -> `tools/stream_analysis/silhouette.py`

Files changed:

- `tools/stream_analysis/silhouette.py`
- `tests/test_stream_analysis_silhouette.py`
- `docs/stream_analysis_plan.md`

Implemented:

- added a post-selection fill refinement path in `tools/stream_analysis/silhouette.py`
  - keep the existing morphology + binary hole-fill path as the default
  - detect when the selected silhouette contains a bright interior region near the tracked centerline that stays connected to the ROI bottom border
  - switch only those frames to a row-envelope fill that spans each selected row from the left outer edge to the right outer edge
  - keep component selection unchanged so the fix only changes filling, not which component is chosen
- updated Stage 3 metrics to expose:
  - `fill_strategy`
  - `open_bottom_interior_detected`
  - `row_fill_added_pixel_count`
- updated Stage 3 sample panels and edge tracing so they use the refined final selected mask
- added focused regression coverage for:
  - the open-bottom interior topology that `binary_fill_holes` cannot close
  - the already-filled-body case that should remain on the default strategy
  - export-level confirmation that `row_envelope_fill` is emitted on a synthetic open-bottom frame

Validation:

- syntax check:
  - `.\env\Scripts\python.exe -m py_compile tools\stream_analysis\silhouette.py tests\test_stream_analysis_silhouette.py`
  - result: passed
- focused stream-analysis tests:
  - `.\env\Scripts\python.exe -m pytest -q tests\test_stream_analysis_silhouette.py tests\test_stream_analysis_cli.py tests\test_stream_analysis_nozzle.py`
  - result: `70 passed`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `695 passed`
- regenerated real-data review artifacts:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py silhouette --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --output-root "tmp\stream_analysis_phase3_review" --run-id run_20260327_225848_829e10c1 --run-id run_20260327_230520_9567e1ee --run-id run_20260327_230807_2858b360 --run-id run_20260327_231322_ecc89833 --run-id run_20260327_231931_2fd25ece --run-id run_20260328_005146_dd931d49 --sample-count 12 --extra-frame-index 56 --extra-frame-index 66 --extra-frame-index 77 --extra-frame-index 88 --extra-frame-index 99 --extra-frame-index 100`
  - result: passed

Targeted artifact review notes:

- regenerated review panels are under:
  - `tmp/stream_analysis_phase3_review/runs/run_20260328_005146_dd931d49/stage_03_silhouette/samples/`
- the originally reported long-stream frames now report:
  - frame `56`: `binary_hole_fill`, `row_fill_added_pixel_count=0`
  - frame `66`: `row_envelope_fill`, `row_fill_added_pixel_count=18947`
  - frame `77`: `row_envelope_fill`, `row_fill_added_pixel_count=18536`
  - frame `88`: `row_envelope_fill`, `row_fill_added_pixel_count=17829`
  - frame `99`: `row_envelope_fill`, `row_fill_added_pixel_count=9995`
  - frame `100`: `binary_hole_fill`, `row_fill_added_pixel_count=0`
- the regenerated panels for frames `66`, `77`, `88`, and `99` now show the bright core filled all the way through the selected silhouette even when the stream exits the field of view at the bottom
- frame `56` stays on the default fill path, which is consistent with the earlier numerical check that it was not failing for the same open-bottom reason

Residual note:

- this refinement intentionally stays narrow and only activates when the selected interior background leaks to the ROI bottom border; other late detached-frame outcomes remain governed by the existing Stage 3 thresholding and selection logic

### 2026-04-03 - Stage 3 offset open-bottom detector added for frame-56-type misses

Call path updated:

- `tools/run_stream_analysis.py` -> `tools/stream_analysis/cli.py` -> `export_stage3_silhouette()` -> `_refine_selected_fill()`

Files changed:

- `tools/stream_analysis/silhouette.py`
- `tests/test_stream_analysis_silhouette.py`
- `docs/stream_analysis_plan.md`

Root cause:

- frame `56` in `run_20260328_005146_dd931d49` still missed the lower bright-core fill because the existing Stage 3 trigger only searched for an open-bottom interior gap that straddled the tracked nozzle `x`
- on that frame, the lower cavity drifted about `13-15 px` left of the tracked nozzle `x`, so the selected silhouette still contained a real bottom-connected interior background component, but `_find_open_bottom_interior_seed()` never seeded into it

Implemented:

- kept the existing tracked-center seed detector as the fast path
- added a fallback interior-component detector in `tools/stream_analysis/silhouette.py` that scans `selected_mask == 0` for bottom-connected interior background components that:
  - do not touch the ROI top, left, or right borders
  - begin below the cutoff region
  - have enough area and height to be meaningful
  - are bounded by selected pixels on both sides for most of their occupied rows
- added `fill_trigger_source` to `silhouette_metrics.csv` with:
  - `none`
  - `tracked_center_gap`
  - `background_component_fallback`
- kept the repair action unchanged:
  - once either detector proves an eligible open-bottom interior, Stage 3 still applies the same row-envelope fill and traces edges from that final refined mask

Validation:

- syntax check:
  - `.\env\Scripts\python.exe -m py_compile tools\stream_analysis\silhouette.py tests\test_stream_analysis_silhouette.py`
  - result: passed
- focused stream-analysis tests:
  - `.\env\Scripts\python.exe -m pytest -q tests\test_stream_analysis_silhouette.py tests\test_stream_analysis_cli.py tests\test_stream_analysis_nozzle.py`
  - result: `74 passed`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `699 passed`
- regenerated real-data review artifacts:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py silhouette --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --output-root "tmp\stream_analysis_phase3_review" --run-id run_20260327_225848_829e10c1 --run-id run_20260327_230520_9567e1ee --run-id run_20260327_230807_2858b360 --run-id run_20260327_231322_ecc89833 --run-id run_20260327_231931_2fd25ece --run-id run_20260328_005146_dd931d49 --sample-count 12 --extra-frame-index 56 --extra-frame-index 66 --extra-frame-index 77 --extra-frame-index 88 --extra-frame-index 99 --extra-frame-index 100`
  - result: passed

Targeted artifact review notes:

- reviewed long-stream frames now report:
  - frame `56`: `row_envelope_fill`, `fill_trigger_source=background_component_fallback`, `row_fill_added_pixel_count=1295`
  - frame `66`: `row_envelope_fill`, `fill_trigger_source=tracked_center_gap`, `row_fill_added_pixel_count=18947`
  - frame `77`: `row_envelope_fill`, `fill_trigger_source=tracked_center_gap`, `row_fill_added_pixel_count=18536`
  - frame `88`: `row_envelope_fill`, `fill_trigger_source=tracked_center_gap`, `row_fill_added_pixel_count=17829`
  - frame `99`: `row_envelope_fill`, `fill_trigger_source=tracked_center_gap`, `row_fill_added_pixel_count=9995`
  - frame `100`: `binary_hole_fill`, `fill_trigger_source=none`, `row_fill_added_pixel_count=0`
- frame `57` remained on the default path:
  - `binary_hole_fill`, `fill_trigger_source=none`
- frame `55` also switched to `background_component_fallback`; a targeted debug panel shows the same kind of laterally shifted lower cavity appearing one frame earlier, so this looks like a physically consistent improvement rather than a new overfill regression

Residual note:

- the fallback detector is still intentionally constrained to bottom-connected interior cavities inside the selected component; if later reviews surface over-triggering on other runs, the next narrow refinement should tighten the bounded-row criterion rather than changing the row-envelope fill itself

### 2026-04-03 - Stage 3 multi-component fluid export and Phase 4a visible volume added

Call path added:

- `tools/run_stream_analysis.py` -> `tools/stream_analysis/cli.py` -> `export_stage3_silhouette()` / `export_stage4_volume()`

Files changed:

- `tools/stream_analysis/silhouette.py`
- `tools/stream_analysis/volume.py`
- `tools/stream_analysis/cli.py`
- `tests/test_stream_analysis_silhouette.py`
- `tests/test_stream_analysis_volume.py`
- `tests/test_stream_analysis_cli.py`
- `docs/stream_analysis_plan.md`

Implemented:

- refactored Stage 3 so one internal per-run builder now returns:
  - frame-level silhouette metrics
  - per-component metrics
  - multi-component edge traces
  - sampled frame inputs for overlays
- kept the attached-body selector authoritative:
  - `_select_primary_component()` still chooses one nozzle-connected `attached_primary`
  - Stage 3 frame status is still driven only by that attached primary
- added conservative detached-fluid acceptance on remaining connected components:
  - component must already pass the existing area threshold
  - component must start at least `24 px` below the cutoff row
  - component center must stay within the existing ROI corridor and within `max(32 px, 0.12 * roi_width)` of the attached anchor center
  - accepted detached components are sorted deterministically and exported as `detached_01`, `detached_02`, and so on
- applied the same fill refinement path to accepted detached components:
  - enclosed holes still use binary hole fill
  - open-bottom bright cores still switch to row-envelope fill, but now detached components use their own anchor center as the local horizontal reference
- expanded Stage 3 exports:
  - `edge_traces.csv` and `edge_traces.json` now include `component_id`, `component_role`, and `component_rank`
  - new `component_metrics.csv` records one row per accepted component per frame
  - `silhouette_metrics.csv` now records accepted attached/detached component counts and area totals
  - Stage 3 review panels now show all accepted visible fluid rather than only the attached body
- added Phase 4a visible-volume export in `tools/stream_analysis/volume.py`:
  - new `volume` CLI subcommand
  - recomputes Stage 3 in-process instead of reading saved Stage 3 files back from disk
  - integrates attached and detached components independently with the existing axisymmetric row model
  - exports `frame_metrics.csv`, `component_volumes.csv`, `volume_timeseries.csv`, `volume_timeseries.json`, `volume_manifest.json`, and sample panels
- intentionally left FOV-exit and trust labeling out of this slice:
  - Stage 4 now owns visible volume
  - trusted/untrusted and first-FOV-exit labeling are still pending for the later Stage 4 completion step

Validation:

- focused stream-analysis tests:
  - `.\env\Scripts\python.exe -m pytest -q tests\test_stream_analysis_silhouette.py tests\test_stream_analysis_volume.py tests\test_stream_analysis_cli.py tests\test_stream_analysis_nozzle.py`
  - result: `83 passed`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `708 passed`

Planned real-data review for this slice:

- regenerate Stage 3 and Stage 4 artifacts under `tmp/stream_analysis_phase4_review`
- explicitly review detached-droplet frames:
  - `run_20260327_230520_9567e1ee` frames `23`, `34`, `45`
- re-check the long-stream open-bottom frames to confirm the detached-component refactor did not disturb the recent fill fixes:
  - `run_20260328_005146_dd931d49` frames `56`, `66`, `77`, `88`, `99`, `100`

Residual note:

- Stage 4 in this slice computes visible volume only; because FOV-exit/trust labeling is still intentionally deferred, downstream consumers should not yet interpret `total_visible_volume_um3` as the final trusted run-level volume curve
- detached-fluid acceptance is intentionally conservative in v1 and currently excludes far side blobs or detached-only frames that are not clearly centered under the attached stream body

### 2026-04-03 - Stage 4 trust labeling and nL unit migration completed

Call path updated:

- `tools/run_stream_analysis.py` -> `tools/stream_analysis/cli.py` -> `export_stage4_volume()` -> `tools/stream_analysis/fov.py`

Files changed:

- `tools/stream_analysis/fov.py`
- `tools/stream_analysis/volume.py`
- `tests/test_stream_analysis_volume.py`
- `tests/test_stream_analysis_cli.py`
- `docs/stream_analysis_plan.md`

Implemented:

- added a small internal `tools/stream_analysis/fov.py` helper module for:
  - attached-primary bottom-contact detection
  - run-latched trusted/untrusted labeling
  - per-run FOV-exit report assembly
- completed Stage 4 trust semantics:
  - trust remains `trusted` while the attached primary stays above the ROI bottom
  - the first `ok` frame where the attached primary reaches the bottom ROI row becomes the first `untrusted_fov_exit` frame
  - all later frames stay `untrusted_fov_exit`, even if the attached primary later retreats upward or Stage 3 geometry becomes unavailable
  - pre-exit Stage 3 failures remain `unavailable_geometry`
- migrated Stage 4 public outputs from `um^3` to `nL`:
  - `frame_metrics.csv`
  - `component_volumes.csv`
  - `volume_timeseries.csv`
  - `volume_timeseries.json`
  - sample overlays
  - `volume_manifest.json`
- added the remaining Stage 4 artifacts:
  - `fov_exit_report.json`
  - `Vt.png`
- kept the ownership split explicit:
  - Stage 3 still produces geometry only
  - Stage 4 now owns visible-volume export, trust labeling, and FOV-exit detection

Validation:

- focused stream-analysis tests:
  - `.\env\Scripts\python.exe -m pytest -q tests\test_stream_analysis_volume.py tests\test_stream_analysis_cli.py tests\test_stream_analysis_silhouette.py tests\test_stream_analysis_nozzle.py`
  - result: `90 passed`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `715 passed`
- regenerated real-data review artifacts:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py volume --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --output-root "tmp\stream_analysis_phase4b_review" --run-id run_20260327_230520_9567e1ee --run-id run_20260328_005146_dd931d49 --sample-count 12 --extra-frame-index 23 --extra-frame-index 34 --extra-frame-index 45 --extra-frame-index 55 --extra-frame-index 56 --extra-frame-index 57 --extra-frame-index 66 --extra-frame-index 77 --extra-frame-index 88 --extra-frame-index 99 --extra-frame-index 100`
  - result: passed

Targeted artifact review notes:

- detached-droplet run `run_20260327_230520_9567e1ee`:
  - detached droplets remain included in visible volume and do not independently trigger FOV exit
  - frames `23`, `34`, and `45` remain `trusted`
  - example frame volumes:
    - frame `23`: attached `5.933 nL`, detached `11.878 nL`, total `17.811 nL`
    - frame `34`: attached `15.886 nL`, detached `12.670 nL`, total `28.556 nL`
    - frame `45`: attached `13.539 nL`, detached `15.987 nL`, total `29.526 nL`
  - first FOV exit is later in the run at frame `111`
- long-stream run `run_20260328_005146_dd931d49`:
  - first FOV exit is frame `37`
  - frame `36` remains `trusted` with `attached_bottom_touches_fov=False`
  - frame `37` is the first `untrusted_fov_exit` frame with `fov_exit_triggered=True`, `attached_bottom_touches_fov=True`, and reason `attached_primary_touches_bottom_roi`
  - later reviewed frames `55`, `56`, `57`, `66`, `77`, `88`, `99`, and `100` remain latched as `untrusted_fov_exit`
  - the recent open-bottom fill fixes remain intact under the new trust labeling

Residual note:

- this Stage 4 slice now defines trusted visible volume, but the later summary and fitting stages still need to be updated to explicitly consume the new `volume_trust_label == "trusted"` rows and the nL-facing public columns

### 2026-04-03 - Stage 4 trust trigger switched to any accepted fluid within 32 px of the ROI bottom

Call path updated:

- `tools/run_stream_analysis.py` -> `tools/stream_analysis/cli.py` -> `export_stage4_volume()` -> `tools/stream_analysis/fov.py`

Files changed:

- `tools/stream_analysis/fov.py`
- `tools/stream_analysis/volume.py`
- `tests/test_stream_analysis_volume.py`
- `tests/test_stream_analysis_cli.py`
- `docs/stream_analysis_plan.md`

Implemented:

- changed the Stage 4 FOV/trust trigger from attached-primary bottom contact to accepted-fluid near-bottom detection:
  - Stage 4 now evaluates every accepted Stage 3 component in the frame
  - for each accepted component, it computes `distance_from_bottom_px = (roi_y1 - 1) - last_valid_y_px`
  - the first `ok` frame with any accepted component at `distance_from_bottom_px <= 32` becomes the first `untrusted_fov_exit` frame
  - later frames remain latched as `untrusted_fov_exit`
- kept Stage 3 unchanged and kept trust ownership in Stage 4:
  - Stage 3 still exports geometry only
  - Stage 4 now decides trust using attached and detached accepted-fluid geometry together
- updated Stage 4 public outputs:
  - removed `attached_bottom_touches_fov`
  - added `accepted_fluid_near_fov_exit`
  - added `fov_near_component_count`
  - added `min_accepted_fluid_distance_from_bottom_px`
  - added `fov_near_bottom_px: 32` to `volume_manifest.json` and `fov_exit_report.json`
  - expanded `fov_exit_report.json` with `trigger_components`
- updated Stage 4 review visuals:
  - sample panels now describe the trigger as accepted fluid near the ROI bottom
  - `Vt.png` now marks the first accepted-fluid near-bottom frame instead of using attached-specific wording

Validation:

- focused stream-analysis tests:
  - `.\env\Scripts\python.exe -m pytest -q tests\test_stream_analysis_volume.py tests\test_stream_analysis_cli.py tests\test_stream_analysis_silhouette.py tests\test_stream_analysis_nozzle.py`
  - result: `91 passed`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `716 passed`
- regenerated real-data review artifacts:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py volume --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --output-root "tmp\stream_analysis_phase4c_review" --run-id run_20260327_230520_9567e1ee --run-id run_20260328_005146_dd931d49 --sample-count 12 --extra-frame-index 23 --extra-frame-index 29 --extra-frame-index 30 --extra-frame-index 34 --extra-frame-index 36 --extra-frame-index 37 --extra-frame-index 38 --extra-frame-index 45 --extra-frame-index 55 --extra-frame-index 56 --extra-frame-index 57 --extra-frame-index 66 --extra-frame-index 77 --extra-frame-index 88 --extra-frame-index 99 --extra-frame-index 100`
  - result: passed

Targeted artifact review notes:

- long-stream run `run_20260328_005146_dd931d49`:
  - the first untrusted frame moves earlier from frame `37` to frame `29`
  - the trigger component is `detached_01`, which is already within `25 px` of the ROI bottom on frame `29`
  - frame `29` now reports:
    - `accepted_fluid_near_fov_exit=True`
    - `fov_near_component_count=1`
    - `min_accepted_fluid_distance_from_bottom_px=25`
    - `fov_exit_triggered=True`
    - `fov_exit_reason=accepted_fluid_near_bottom_roi`
  - frame `30` still has the detached component touching bottom, but it is now a latched follow-on frame rather than the first trigger
  - later reviewed frames `55`, `56`, `57`, `66`, `77`, `88`, `99`, and `100` remain `untrusted_fov_exit`
- detached-droplet run `run_20260327_230520_9567e1ee`:
  - the first untrusted frame remains frame `37`
  - no accepted component is within `32 px` of the ROI bottom on frame `36`:
    - `min_accepted_fluid_distance_from_bottom_px=41`
    - `accepted_fluid_near_fov_exit=False`
  - frame `37` is the first trigger frame and is driven by detached accepted fluid:
    - trigger component `detached_01`
    - `distance_from_bottom_px=0`
  - detached droplets in frames `23`, `34`, and `45` still contribute to visible volume while trust stays `trusted` until the near-bottom boundary is crossed

Residual note:

- the trigger now covers accepted detached fluid as intended, but it is still limited to accepted Stage 3 components; raw threshold blobs outside Stage 3 acceptance still do not affect trust
- later stages still need to consume the current Stage 4 trust fields and the nL-facing public volume schema

### 2026-04-03 - Later-phase plan reordered around partial-volume estimation before summary analysis

Completed:

- revised the later-phase plan to match the current interpretation of the volume problem:
  - trusted visible volume before FOV exit
  - steady-rate extrapolation between FOV exit and tail onset
  - a distinct tail-volume estimate
- changed the planned steady/tail detection strategy so it now combines:
  - trusted Stage 4 visible volume
  - attached-primary near-nozzle width extracted from Stage 3 edge traces
- reordered the remaining stages so they now flow as:
  - Stage 5: per-run width features, steady-rate fit, tail-onset detection, middle extrapolation, and partial total
  - Stage 6: run summary, metadata join, and gravimetric residual analysis
  - Stage 7: tail-volume model and final total estimate
- split the future Stage 5 implementation into explicit reviewable slices:
  - Stage 5a: near-nozzle width feature extraction
  - Stage 5b: steady-window detection and robust steady-rate fitting
  - Stage 5c: tail-onset detection and middle-volume extrapolation
  - Stage 5d: partial-total export with explicit tail placeholder
- updated the planned module layout and CLI responsibilities so the next implementation pass has a concrete home:
  - `tools/stream_analysis/fit.py`
  - `fit` CLI subcommand
- updated Stage 6 so future run summaries will carry the new volume-estimation and gravimetric-residual fields once Stage 5 is implemented
- added a distinct Stage 7 placeholder so the tail model can be planned after the Stage 6 residual patterns are visible

Artifacts generated:

- none; planning update only

Open issues:

- the exact Stage 5a near-nozzle band defaults (`24 px` offset, `40 px` height) still need real-data review once implemented
- the exact steady-width plateau tolerance and tail-drop threshold are intentionally frozen only as initial review defaults and may need one narrow tuning pass
- the tail-volume model remains unresolved and should stay a separate Stage 7 slice until it is validated against real runs and gravimetric totals

Next steps:

- implement Stage 5a first and review the resulting width traces against the current `V(t)` plots on the same runs already reviewed for Stage 4
- implement Stage 5b second so the steady-rate fit can be reviewed before any extrapolated volume is reported
- implement Stage 5c third to produce the middle-volume estimate between first-untrusted and tail-onset
- keep Stage 5d as a partial-total export only, then use Stage 6 to study the residual tail against gravimetric totals before planning Stage 7

### 2026-04-03 - Stage 5 near-nozzle width, steady-rate fit, and middle extrapolation completed

Call path added:

- `tools/run_stream_analysis.py` -> `tools/stream_analysis/cli.py` -> `export_stage5_fit()` -> reusable `tools/stream_analysis/volume.py::_build_stage4_run()` -> `tools/stream_analysis/fit.py`

Files changed:

- `tools/stream_analysis/fit.py`
- `tools/stream_analysis/volume.py`
- `tools/stream_analysis/cli.py`
- `tests/test_stream_analysis_fit.py`
- `tests/test_stream_analysis_cli.py`
- `docs/stream_analysis_plan.md`

Implemented:

- added a standalone Stage 5 `fit` export stage and CLI subcommand
- refactored Stage 4 so `tools/stream_analysis/volume.py` now exposes a reusable `_build_stage4_run()` helper that returns:
  - labeled Stage 4 frame rows
  - Stage 4 component-volume rows
  - Stage 4 FOV report
  - pass-through Stage 3 geometry rows needed by Stage 5
- added attached-primary near-nozzle width extraction in `tools/stream_analysis/fit.py`
  - width band anchored to the tracked nozzle with the initial reviewed defaults:
    - `near_nozzle_band_top_px = 24`
    - `near_nozzle_band_height_px = 40`
  - width metrics exported per frame:
    - `attached_near_nozzle_width_median_px`
    - `attached_near_nozzle_width_iqr_px`
    - `attached_near_nozzle_band_valid_row_count`
    - `attached_near_nozzle_band_y0_px`
    - `attached_near_nozzle_band_y1_px`
    - `attached_near_nozzle_width_smoothed_px`
- added earliest-window steady detection using trusted Stage 4 `V(t)` and the attached width plateau together
  - candidate frames must be trusted, have visible volume, and have valid attached-band width
  - steady fit uses Theil-Sen on `delay_from_emergence_us` vs `total_visible_volume_nl`
  - the earliest qualifying window is selected and then extended forward while the fit and width-span criteria remain valid
- added tail-onset detection from the attached near-nozzle width trace
  - searches only after the steady window
  - detects the first persistent width drop below the steady plateau by `tail_drop_frac = 0.08` for `tail_persist_frames = 3`
- added conservative middle extrapolation
  - uses trusted visible volume at the last trusted frame
  - extrapolates only from first-untrusted to tail-onset
  - performs no middle extrapolation if the steady fit or tail onset is unresolved
  - exports `tail_volume_nl = null` and `final_total_status = "tail_pending"` rather than implying a finished total
- added Stage 5 outputs:
  - `phase_features.csv`
  - `phase_boundaries.json`
  - `steady_fit.json`
  - `middle_extrapolation.json`
  - `Vt_fit.png`
  - `width_trace.png`
  - per-run and top-level `fit_manifest.json`

Validation:

- focused stream-analysis tests:
  - `.\env\Scripts\python.exe -m pytest -q tests\test_stream_analysis_fit.py tests\test_stream_analysis_volume.py tests\test_stream_analysis_cli.py tests\test_stream_analysis_silhouette.py tests\test_stream_analysis_nozzle.py`
  - result: `101 passed`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `726 passed`
- regenerated real-data review artifacts:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py fit --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --output-root "tmp\stream_analysis_phase5_review" --run-id run_20260327_230520_9567e1ee --run-id run_20260328_005146_dd931d49 --sample-count 12`
  - result: passed

Targeted artifact review notes:

- review artifacts are under:
  - `tmp/stream_analysis_phase5_review/runs/<run_id>/stage_05_fit/`
- detached-droplet run `run_20260327_230520_9567e1ee`:
  - first untrusted frame remains `37`
  - earliest steady window selected: frames `14-36`
  - steady rate: `0.01898 nL/us`
  - steady width plateau: `74.0 px`
  - tail onset detected at frame `89`
  - trusted visible volume: `31.206 nL`
  - middle extrapolated volume: `49.357 nL`
  - partial total without tail: `80.563 nL`
  - near-nozzle width is visibly settling through frames `12-15` (`86.0 -> 81.5 -> 78.0 -> 74.0 px`), stays near `74 px` through the steady window, then begins its persistent drop at frame `89` (`66.0 px`)
- long-stream run `run_20260328_005146_dd931d49`:
  - first untrusted frame remains `29`
  - earliest steady window selected: frames `13-28`
  - steady rate: `0.02488 nL/us`
  - steady width plateau: `74.0 px`
  - tail onset detected at frame `94`
  - trusted visible volume: `28.292 nL`
  - middle extrapolated volume: `80.856 nL`
  - partial total without tail: `109.148 nL`
  - near-nozzle width settles through frames `11-13` (`85.0 -> 79.5 -> 75.0 px`), remains near `74 px` through the steady window and first-untrusted boundary, then begins its persistent drop at frame `94` (`64.0 px`)

Residual note:

- Stage 5 now produces a reviewed per-run partial total, but the tail term is still intentionally unresolved and exported only as `null`
- the initial width-band, width-drop, and steady-window defaults look promising on the two reviewed runs, but Stage 6 still needs the cross-run metadata join and gravimetric residual study before any tail model is planned

Next step:

- begin Stage 6 run-summary and metadata-join work so the new Stage 5 partial totals can be compared directly against gravimetric totals and grouped by print pressure / pulse width before planning Stage 7 tail estimation

### 2026-04-03 - Stage 6 run summary, metadata join, gravimetric residual analysis, and long-run progress reporting completed

Call path added:

- `tools/run_stream_analysis.py` -> `tools/stream_analysis/cli.py` -> `export_stage6_summary()` -> reusable `tools/stream_analysis/fit.py::_build_stage5_run()` -> `tools/stream_analysis/summary.py`

Files changed:

- `tools/stream_analysis/summary.py`
- `tools/stream_analysis/fit.py`
- `tools/stream_analysis/cli.py`
- `tests/test_stream_analysis_summary.py`
- `tests/test_stream_analysis_cli.py`
- `docs/stream_analysis_plan.md`

Implemented:

- added a standalone Stage 6 `summary` export stage and CLI subcommand
- refactored Stage 5 so `tools/stream_analysis/fit.py` now exposes a reusable `_build_stage5_run()` helper that returns:
  - Stage 5 phase-feature rows
  - phase boundaries
  - steady-fit payload
  - middle-extrapolation payload
  - Stage 5 summary values
  - pass-through Stage 4 data needed by Stage 6
- added per-run Stage 6 summary export:
  - `runs/<run_id>/stage_06_summary/run_summary.json`
- added experiment-level summary exports:
  - `experiment_summary.csv`
  - `experiment_summary.json`
  - `condition_summary.csv`
  - `condition_summary.json`
- added signed gravimetric residual diagnostics using the current water assumption:
  - `gravimetric_total_nl = metadata_mass_print * 1000`
  - `signed_residual_nl = gravimetric_total_nl - partial_total_without_tail_nl`
  - `signed_residual_fraction`
  - `partial_to_gravimetric_ratio`
  - `partial_exceeds_gravimetric`
- grouped summary outputs by `(print_pressure, print_pw_us)` and added condition-level aggregate fields such as:
  - `gravimetric_total_nl_mean`
  - `partial_total_without_tail_nl_mean`
  - `signed_residual_nl_mean`
  - `signed_residual_nl_std`
  - `signed_residual_fraction_mean`
  - `partial_to_gravimetric_ratio_mean`
  - `overprediction_run_count`
- added Stage 6 review plots:
  - `partial_vs_gravimetric_scatter.png`
  - `signed_residual_by_condition.png`
  - `signed_residual_fraction_by_condition.png`
  - `signed_residual_vs_middle_duration.png`
- added long-run progress reporting:
  - final manifest JSON stays on `stdout`
  - per-run progress lines go to `stderr`
  - root-level `summary_progress.json` is updated after each completed run so interrupted runs still leave a machine-readable checkpoint

Validation:

- focused stream-analysis tests:
  - `.\env\Scripts\python.exe -m pytest -q tests\test_stream_analysis_summary.py tests\test_stream_analysis_fit.py tests\test_stream_analysis_volume.py tests\test_stream_analysis_cli.py tests\test_stream_analysis_silhouette.py tests\test_stream_analysis_nozzle.py`
  - result: `107 passed`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `732 passed`
- regenerated full-dataset Stage 6 review artifacts:
  - `mkdir tmp\stream_analysis_phase6_review`
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py summary --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --output-root "tmp\stream_analysis_phase6_review" 1> tmp\stream_analysis_phase6_review\summary_stdout.json 2> tmp\stream_analysis_phase6_review\summary_progress.log`
  - result: completed with full outputs written under `tmp\stream_analysis_phase6_review`

Targeted artifact review notes:

- Stage 6 analyzed all `26` matched CSV-backed runs and produced `8` condition groups
- all `26` analyzed rows had usable gravimetric totals
- `24` of `26` runs have `partial_exceeds_gravimetric = true`, which means the current Stage 5 partial total is usually slightly high rather than obviously low
- the condition summaries show a narrow overprediction pattern for most conditions:
  - `0.65 bar / 2500 us`: mean signed residual `-3.13 nL`
  - `0.65 bar / 3000 us`: mean signed residual `-9.08 nL`
  - `0.75 bar / 2500 us`: mean signed residual `-3.73 nL`
  - `0.75 bar / 3000 us`: mean signed residual `-3.79 nL`
  - `0.75 bar / 3500 us`: mean signed residual `-2.35 nL`
  - `0.85 bar / 2500 us`: mean signed residual `-2.85 nL`
  - `0.85 bar / 3000 us`: mean signed residual `-3.59 nL`
- the main outlier condition is `0.65 bar / 3500 us`, whose mean signed residual is strongly positive because one run has unresolved tail onset:
  - `run_20260328_000102_5ef6ee34`
  - `tail_onset_status = unresolved`
  - `middle_extrapolation_status = unresolved_no_tail_onset`
  - `partial_total_without_tail_nl = 31.120 nL`
  - `gravimetric_total_nl = 97.600 nL`
  - `signed_residual_nl = 66.480 nL`
- two previously reviewed runs reproduce the Stage 5 numbers inside the full summary:
  - `run_20260327_230520_9567e1ee`: partial total `80.563 nL`, gravimetric `71.100 nL`, signed residual `-9.463 nL`
  - `run_20260328_005146_dd931d49`: partial total `109.148 nL`, gravimetric `103.700 nL`, signed residual `-5.448 nL`
- `summary_progress.log` and `summary_progress.json` both confirm that long full-dataset runs are observable while running and leave a usable checkpoint when complete

Residual note:

- Stage 6 confirms that the current Stage 5 baseline is usually a slight overprediction, which supports the earlier observation that tail contribution may often be small and that the next refinement likely belongs in tail-onset timing rather than in a large positive tail model
- one unresolved-tail outlier still needs targeted review before Stage 7 planning so it is not mistaken for a true large tail-volume regime

Next step:

- use the Stage 6 residual structure to decide whether Stage 5 tail onset should be refined with a narrow backtracking rule before planning or implementing Stage 7 tail-volume modeling

### 2026-04-03 - Stage 5 tail-onset refinement implemented and Stage 6 rerun reviewed

Call path refined:

- `tools/run_stream_analysis.py` -> `tools/stream_analysis/cli.py` -> `export_stage5_fit()` -> `tools/stream_analysis/fit.py`
- `tools/run_stream_analysis.py` -> `tools/stream_analysis/cli.py` -> `export_stage6_summary()` -> reusable `tools/stream_analysis/fit.py::_build_stage5_run()` -> `tools/stream_analysis/summary.py`

Files changed:

- `tools/stream_analysis/fit.py`
- `tools/stream_analysis/summary.py`
- `tests/test_stream_analysis_fit.py`
- `tests/test_stream_analysis_summary.py`
- `tests/test_stream_analysis_cli.py`
- `docs/stream_analysis_plan.md`

Implemented:

- refined Stage 5 tail detection so the width-threshold persistence rule now serves as a confirmation rule rather than the reported onset timestamp
- after a persistent break is confirmed, Stage 5 now backtracks through the smoothed width trace to the start of the decline episode and uses that backtracked frame as `tail_start_capture_index`
- added a narrow truncated-width-loss fallback for runs where the width decline is real but width availability disappears before the full persistence count completes
- added new Stage 5 outputs:
  - `tail_confirmation_capture_index`
  - `tail_confirmation_delay_from_emergence_us`
  - `tail_detection_mode`
  - `tail_confirmation_frame` in `phase_features.csv`
- carried the new tail fields through Stage 6 per-run summaries and run-level JSON

Validation:

- focused stream-analysis tests:
  - `.\env\Scripts\python.exe -m pytest -q tests\test_stream_analysis_fit.py tests\test_stream_analysis_summary.py tests\test_stream_analysis_volume.py tests\test_stream_analysis_cli.py tests\test_stream_analysis_silhouette.py tests\test_stream_analysis_nozzle.py`
  - result: `111 passed`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `736 passed`
- regenerated targeted Stage 5 review artifacts:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py fit --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --output-root "tmp\stream_analysis_phase5_refined_review" --run-id run_20260327_230520_9567e1ee --run-id run_20260328_005146_dd931d49 --run-id run_20260328_000102_5ef6ee34 --sample-count 12`
  - result: passed
- regenerated refined full-dataset Stage 6 review artifacts:
  - `mkdir tmp\stream_analysis_phase6_refined_review`
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py summary --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --output-root "tmp\stream_analysis_phase6_refined_review" 1> tmp\stream_analysis_phase6_refined_review\summary_stdout.json 2> tmp\stream_analysis_phase6_refined_review\summary_progress.log`
  - result: Stage 6 completed with full outputs written under `tmp\stream_analysis_phase6_refined_review`

Targeted artifact review notes:

- refined Stage 5 review artifacts are under:
  - `tmp/stream_analysis_phase5_refined_review/runs/<run_id>/stage_05_fit/`
- detached-droplet run `run_20260327_230520_9567e1ee`:
  - `tail_confirmation_capture_index = 89`
  - backtracked `tail_start_capture_index = 85`
  - partial total moved from `80.563 nL` to `76.766 nL`
  - gravimetric total is `71.100 nL`, so signed residual improved from `-9.463 nL` to `-5.666 nL`
- long-stream run `run_20260328_005146_dd931d49`:
  - `tail_confirmation_capture_index = 94`
  - backtracked `tail_start_capture_index = 79`
  - partial total moved from `109.148 nL` to `90.489 nL`
  - gravimetric total is `103.700 nL`, so signed residual moved from `-5.448 nL` to `13.211 nL`
- previously unresolved run `run_20260328_000102_5ef6ee34`:
  - `tail_detection_mode = confirmed_truncated_width_loss`
  - `tail_confirmation_capture_index = 109`
  - backtracked `tail_start_capture_index = 105`
  - partial total moved from `31.120 nL` to `98.902 nL`
  - gravimetric total is `97.600 nL`, so the signed residual is now `-1.302 nL`

Refined Stage 6 summary notes:

- Stage 6 again analyzed all `26` matched CSV-backed runs and produced `8` condition groups
- the refinement sharply reduced outright overprediction:
  - baseline Stage 6: `24 / 26` runs had `partial_exceeds_gravimetric = true`
  - refined Stage 6: `6 / 26` runs have `partial_exceeds_gravimetric = true`
- the mean signed residual moved from `-1.03 nL` in the baseline summary to `+4.35 nL` after the refinement, which means the dataset-wide bias shifted from slight overprediction to moderate underprediction
- mean absolute residual improved slightly:
  - baseline Stage 6: `6.15 nL`
  - refined Stage 6: `5.70 nL`
- the biggest baseline outlier is now resolved:
  - `run_20260328_000102_5ef6ee34` no longer has unresolved tail onset and no longer dominates the `0.65 bar / 3500 us` condition with a large positive residual
- the condition means moved substantially toward underprediction in several groups after the refinement, including:
  - `0.75 bar / 3000 us`: mean signed residual `-3.79 nL -> +4.41 nL`
  - `0.85 bar / 3000 us`: mean signed residual `-3.59 nL -> +13.35 nL`

Residual note:

- the backtracked-onset refinement fixed the obvious late-tail problem and resolved the truncated-tail outlier, but it appears too aggressive for some longer runs and now tends to underpredict at the dataset level
- Stage 7 tail modeling still should not begin until the Stage 5 onset timing is accepted, because the current refined residual pattern suggests there is still a Stage 5 boundary-placement problem rather than a clean standalone tail term

Next step:

- review the refined Stage 5 / Stage 6 artifacts and decide whether Stage 5 needs a narrower backtracking rule before any Stage 7 tail-volume model is attempted

### 2026-04-03 - Stage 5 shoulder-aware tail-onset refinement implemented and Stage 6 rerun reviewed

Call path refined:

- `tools/run_stream_analysis.py` -> `tools/stream_analysis/cli.py` -> `export_stage5_fit()` -> `tools/stream_analysis/fit.py`
- `tools/run_stream_analysis.py` -> `tools/stream_analysis/cli.py` -> `export_stage6_summary()` -> reusable `tools/stream_analysis/fit.py::_build_stage5_run()` -> `tools/stream_analysis/summary.py`

Files changed:

- `tools/stream_analysis/fit.py`
- `tools/stream_analysis/summary.py`
- `tests/test_stream_analysis_fit.py`
- `tests/test_stream_analysis_summary.py`
- `tests/test_stream_analysis_cli.py`
- `docs/stream_analysis_plan.md`

Implemented:

- investigated the five runs where the previous refined onset landed too early and confirmed that the failure mode was a long flat shoulder just below the steady-width plateau but still above the tail-width threshold
- kept the existing tail confirmation rules unchanged:
  - persistent threshold confirmation
  - truncated-width-loss confirmation
- kept the existing preliminary backtrack unchanged as the first onset candidate
- added a new shoulder-aware onset adjustment after confirmation:
  - searches the interval from the preliminary onset through the frame before confirmation
  - finds the last qualifying flat shoulder with:
    - at least `5` valid smoothed-width frames
    - width span `<= 1.0 px`
    - every width strictly above the tail threshold
    - a follow-on drop of at least `1.5 px` within the next `2` valid frames
  - if a shoulder is found, moves `tail_start_capture_index` to the first valid frame after the shoulder end
  - otherwise keeps the direct backtracked onset
- added new Stage 5 review fields:
  - `tail_start_selection_mode`
  - `tail_shoulder_end_capture_index`
  - `tail_shoulder_end_delay_from_emergence_us`
  - `tail_shoulder_end_frame` in `phase_features.csv`
- updated `width_trace.png` and `Vt_fit.png` so the shoulder-end marker is visible when the shoulder-aware rule applies
- carried the new tail-start fields through Stage 6 run-level summaries and experiment-level exports

Validation:

- focused stream-analysis tests:
  - `.\env\Scripts\python.exe -m pytest -q tests\test_stream_analysis_fit.py tests\test_stream_analysis_summary.py tests\test_stream_analysis_volume.py tests\test_stream_analysis_cli.py tests\test_stream_analysis_silhouette.py tests\test_stream_analysis_nozzle.py`
  - result: `114 passed`
- full Python suite:
  - `.\env\Scripts\python.exe -m pytest -q`
  - result: `739 passed`
- regenerated targeted 10-run Stage 5 review artifacts:
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py fit --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --output-root "tmp\stream_analysis_phase5_shoulder_review" --run-id run_20260327_230520_9567e1ee --run-id run_20260327_231322_ecc89833 --run-id run_20260327_230807_2858b360 --run-id run_20260327_235824_fc32934b --run-id run_20260328_000102_5ef6ee34 --run-id run_20260328_001819_65e7f48d --run-id run_20260328_003354_8cf1bfcb --run-id run_20260328_004724_cfc969f5 --run-id run_20260328_004925_93d336a3 --run-id run_20260328_005146_dd931d49 --sample-count 8`
  - result: passed
- regenerated full-dataset Stage 6 review artifacts:
  - `mkdir tmp\stream_analysis_phase6_shoulder_review`
  - `.\env\Scripts\python.exe tools\run_stream_analysis.py summary --experiment-root "FreeRTOS-interface\Experiments\Stream_characterization-20260327_225650" --output-root "tmp\stream_analysis_phase6_shoulder_review" 1> tmp\stream_analysis_phase6_shoulder_review\summary_stdout.json 2> tmp\stream_analysis_phase6_shoulder_review\summary_progress.log`
  - result: Stage 6 completed with full outputs written under `tmp\stream_analysis_phase6_shoulder_review`

Targeted Stage 5 review notes:

- the custom gravimetric-width review artifacts are under:
  - `tmp/stream_analysis_phase5_shoulder_review/gravimetric_width_review/`
- the five previously problematic runs now move later and much closer to the gravimetric-equality marker:
  - `run_20260327_235824_fc32934b`:
    - `tail_start_selection_mode = shoulder_adjusted`
    - `tail_shoulder_end_capture_index = 103`
    - `tail_start_capture_index = 104`
    - gravimetric-equality delay `5019.39 us`
    - tail start delay `5100 us`
  - `run_20260328_004925_93d336a3`:
    - `tail_start_selection_mode = shoulder_adjusted`
    - `tail_shoulder_end_capture_index = 91`
    - `tail_start_capture_index = 92`
    - gravimetric-equality delay `4461.64 us`
    - tail start delay `4500 us`
  - `run_20260328_005146_dd931d49`:
    - `tail_start_selection_mode = shoulder_adjusted`
    - `tail_shoulder_end_capture_index = 90`
    - `tail_start_capture_index = 91`
    - gravimetric-equality delay `4381.02 us`
    - tail start delay `4450 us`
  - `run_20260328_004724_cfc969f5`:
    - `tail_start_selection_mode = shoulder_adjusted`
    - `tail_shoulder_end_capture_index = 91`
    - `tail_start_capture_index = 92`
    - gravimetric-equality delay `4423.22 us`
    - tail start delay `4500 us`
  - `run_20260328_003354_8cf1bfcb`:
    - `tail_start_selection_mode = shoulder_adjusted`
    - `tail_shoulder_end_capture_index = 105`
    - `tail_start_capture_index = 106`
    - gravimetric-equality delay `5220.12 us`
    - tail start delay `5200 us`
- the known-good references stay effectively unchanged:
  - `run_20260327_230520_9567e1ee`:
    - `tail_detection_mode = confirmed_persistent`
    - `tail_start_selection_mode = direct_backtrack`
    - `tail_start_capture_index = 85`
  - `run_20260328_000102_5ef6ee34`:
    - `tail_detection_mode = confirmed_truncated_width_loss`
    - `tail_start_selection_mode = direct_backtrack`
    - `tail_start_capture_index = 105`
- one additional run also benefited from the shoulder-aware rule:
  - `run_20260327_230807_2858b360`
  - `tail_start_selection_mode = shoulder_adjusted`
  - `tail_shoulder_end_capture_index = 87`
  - `tail_start_capture_index = 88`

Shoulder-aware Stage 6 summary notes:

- Stage 6 again analyzed all `26` matched CSV-backed runs and produced `8` condition groups
- the shoulder-aware refinement improved dataset-level agreement substantially relative to the earlier backtracked-only refinement:
  - overprediction count: `6 / 26 -> 16 / 26`
  - mean signed residual: `+4.35 nL -> -0.70 nL`
  - mean absolute residual: `5.70 nL -> 2.38 nL`
- the five problematic long-shoulder runs all moved much closer to zero signed residual:
  - `run_20260327_235824_fc32934b`: `-1.593 nL`
  - `run_20260328_004925_93d336a3`: `-0.945 nL`
  - `run_20260328_005146_dd931d49`: `-1.716 nL`
  - `run_20260328_004724_cfc969f5`: `-1.909 nL`
  - `run_20260328_003354_8cf1bfcb`: `+0.448 nL`
- the previously unresolved-truncated run remains resolved and close to gravimetric:
  - `run_20260328_000102_5ef6ee34`
  - `signed_residual_nl = -1.302`
- condition means moved much closer to zero than in the backtracked-only refinement, including:
  - `0.65 bar / 3500 us`: `+5.42 nL -> +0.98 nL`
  - `0.75 bar / 3500 us`: `+7.35 nL -> +0.26 nL`
  - `0.85 bar / 3000 us`: `+13.35 nL -> -1.52 nL`

Residual note:

- the shoulder-aware refinement preserves the earlier win on truncated tails while avoiding the premature onset placement seen in long shoulder traces
- the full-dataset residuals are now much tighter and centered close to zero, which suggests the remaining disagreement is smaller and more appropriate for Stage 7 tail-model planning rather than another large Stage 5 boundary redesign

Next step:

- review the new Stage 6 residual plots and decide whether the remaining residual structure is small enough to move on to Stage 7 tail-model exploration or whether a final narrow Stage 5 tuning pass is still justified

### 2026-04-05 - Stage 5 fast-review cache and cache-only review loop implemented

Call path added:

- `tools/run_stream_analysis.py` -> `tools/stream_analysis/cli.py` -> `export_stage5_review_cache()` -> `tools/stream_analysis/review_cache.py`
- `tools/run_stream_analysis.py` -> `tools/stream_analysis/cli.py` -> `export_stage5_cached_review()` -> `tools/stream_analysis/review_cache.py` -> reusable `tools/stream_analysis/fit.py::_build_stage5_review_run()`

Files changed:

- `tools/stream_analysis/review_cache.py`
- `tools/stream_analysis/cli.py`
- `tools/stream_analysis/fit.py`
- `tests/test_stream_analysis_review_cache.py`
- `tests/test_stream_analysis_fit.py`
- `tests/test_stream_analysis_cli.py`
- `docs/stream_analysis_plan.md`

Implemented:

- added a canonical Stage 5 review cache under `analysis/stream_characterization/stage_05_review_cache/`
- added `fit-cache` to freeze reusable per-run review inputs:
  - `phase_input.csv`
  - `run_context.json`
  - top-level `cache_manifest.json`
- cache creation now uses the planned source precedence:
  - reuse an existing valid cache entry unless `--rebuild` is requested
  - import existing Stage 5 artifacts from `stage_05_fit/` when available
  - fall back to a one-time raw Stage 5 build only for missing runs
- added `fit-review` so width smoothing, tail-start placement, middle extrapolation, summaries, and plots can be regenerated from cached inputs without rerunning Stages 1-4
- froze the current steady-rate fit inside the cache by storing the Stage 5 steady-fit payload and replaying it during cache-only review
- carried frozen anchors through cache-only review:
  - `trusted_visible_volume_nl`
  - `first_untrusted_capture_index`
  - `first_untrusted_delay_from_emergence_us`
- added cache-review run summary fields:
  - `gravimetric_reference_status`
  - `include_in_gravimetric_plots`
  - `gravimetric_equality_delay_us`
  - `cache_source_kind`
  - `phase_input_csv`
  - `run_context_json`
- made cache-only review regenerate the same reviewable outputs needed for tail-start iteration:
  - per-run `phase_features.csv`, `steady_fit.json`, `middle_extrapolation.json`, `phase_boundaries.json`
  - per-run `width_trace.png`, `Vt_fit.png`, `run_summary.json`, `run_summary.csv`
  - experiment-level `experiment_summary.csv/json`, `condition_summary.csv/json`
  - experiment-level gravimetric comparison plots
  - `gravimetric_width_review/width_trace_review_index.csv`
  - per-run `gravimetric_width_review/run_<id>_width_trace_with_gravimetric.png`
- defaulted the cache-review comparison plots and condition means to exclude the suspect `0.65 bar / 3000 us` gravimetric references while still preserving those runs in:
  - the cache itself
  - per-run width plots
  - experiment summary tables
  - the gravimetric width-review index

Validation:

- focused cache / fit / CLI / summary tests:
  - `.\env\Scripts\python.exe -m pytest -q tests\test_stream_analysis_fit.py tests\test_stream_analysis_review_cache.py tests\test_stream_analysis_cli.py tests\test_stream_analysis_summary.py`
  - result: `37 passed`
- broader stream-analysis suite:
  - `.\env\Scripts\python.exe -m pytest -q tests -k stream_analysis`
  - result: `132 passed, 613 deselected`

Review workflow note:

- the intended Stage 5 iteration loop is now:
  - `fit-cache` once to freeze inputs
  - `fit-review` repeatedly while tuning only width smoothing and tail-start rules
- this should remove the slow repeated reruns of upstream image-analysis stages when only the Stage 5 onset logic is being adjusted

Next step:

- use `fit-cache` on the current experiment outputs, then iterate on Stage 5 tail-start rules with `fit-review` so onset consistency can be compared quickly against the cached width traces and gravimetric-equality markers

### 2026-04-05 - Stage 5 review-only flow-fit and descriptor tail-start tooling expanded

Call path expanded:

- `tools/run_stream_analysis.py` -> `tools/stream_analysis/cli.py` -> `export_stage5_cached_review()` -> `tools/stream_analysis/review_cache.py` -> reusable `tools/stream_analysis/fit.py::_build_stage5_review_run()`

Files changed:

- `tools/stream_analysis/fit.py`
- `tools/stream_analysis/review_cache.py`
- `tools/stream_analysis/cli.py`
- `tests/test_stream_analysis_fit.py`
- `tests/test_stream_analysis_review_cache.py`
- `tests/test_stream_analysis_cli.py`
- `docs/stream_analysis_plan.md`

Implemented:

- added review-only gravimetric-equivalent confidence analysis from cached Stage 5 inputs:
  - reconstructs a CI95 steady-rate band from the selected `V(t)` fit points
  - projects the gravimetric-equivalent center and CI95 band onto the width trace and normalized shrink-rate trace
  - exports gravimetric-equivalent width-position and shrink-rate descriptors
- added `V(t)` review contact sheets and review indexes so all runs can be compared visually:
  - selected fit points
  - excluded near-exit trusted points
  - flow-fit slope line
  - CI95 slope band
- expanded review-only steady-fit recompute mode:
  - separates the plateau seed window used for tail anchoring from the longer flow-fit window used for the rate and CI
  - supports near-exit trusted-point exclusion, limited pre-plateau backfill, and conservative one-point outlier pruning
  - now keeps the central flow rate and the CI95 slope interval on the same final point set
- expanded review-only tail-start selection modes:
  - `descriptor-score` for path-specific descriptor scoring
  - `descriptor-unified` for one shared candidate window from `preliminary_tail_start` through `tail_confirmation`
  - `descriptor-unified` currently uses the gravimetric-calibrated descriptor band first, then falls back to the shared score if no candidate enters the band
- added run-level audit artifacts for tail-start review:
  - `tail_start_candidates.csv`
  - `tail_start_refinement_mode`
  - `tail_start_band_selection_status`
  - selected descriptor values and candidate-window bounds in the review summaries and width-review index

Validation:

- focused fit / review-cache / CLI / summary tests:
  - `.\env\Scripts\python.exe -m pytest -q tests\test_stream_analysis_fit.py tests\test_stream_analysis_review_cache.py tests\test_stream_analysis_cli.py tests\test_stream_analysis_summary.py`
  - result: passed
- broader stream-analysis suite:
  - `.\env\Scripts\python.exe -m pytest -q tests -k stream_analysis`
  - result: passed
- current review iterations were regenerated from cache only, without rerunning Stages 1-4

Current review-state notes:

- the review-only flow-fit work suggests the remaining disagreement is more likely in tail placement than in the steady-rate fit itself
- the current review-only preferred tail-start mode is `descriptor-unified`, because it reduces the path-driven late-selection behavior seen when direct and shoulder runs used different final candidate windows
- the remaining known tail-start issue is inside the in-band chooser itself:
  - most runs pick the earliest acceptable point cleanly
  - a small number of runs likely need a score-guarded refinement so the chosen earliest in-band point is not allowed to drift too far from the best in-band score

Next step:

- keep the current unified descriptor band and candidate window, then refine the in-band chooser so it remains early without selecting a visibly worse in-band candidate

## Progress Checklist

- [x] Inspect repository structure and choose the cleanest analysis location
- [x] Inspect `stream_metadata.csv` and verify how runs map to image folders
- [x] Write this planning document
- [x] Implement Stage 0 inventory and frame indexing
- [x] Review Stage 0 artifacts and update this document
- [x] Implement Stage 1 ROI-first direct grayscale threshold baseline
- [x] Review Stage 1 artifacts and update this document
- [x] Implement Stage 2 per-frame nozzle tracking and shift segmentation
- [x] Review Stage 2 artifacts and update this document
- [x] Implement Stage 3 silhouette extraction
- [x] Review Stage 3 artifacts and update this document
- [x] Implement Stage 4 visible-volume and FOV-exit detection
- [x] Review Stage 4 artifacts and update this document
- [x] Implement Stage 5 near-nozzle width, steady-rate fit, and middle extrapolation
- [x] Review Stage 5 artifacts and update this document
- [x] Implement Stage 6 run summaries, metadata joins, and gravimetric residual analysis
- [x] Review Stage 6 artifacts and update this document
- [ ] Implement Stage 7 tail-volume model and final total estimate
- [ ] Review Stage 7 artifacts and update this document
