# Refuel Camera Integration Plan

## Purpose

The refuel camera window is a diagnostic and dataset-capture tool. The intended production use is different: while the user is working inside the droplet imager, the refuel camera should quietly monitor the printer-head channel level from the side-view camera and provide advisory feedback when the level drifts.

The first integration should be conservative. The monitor should run only while the droplet imager workflow is active, should sample slowly enough to avoid interfering with droplet or stream calibration, and should not automatically change pressure or pulse width. Automatic or semi-automatic control can be considered later after the advisory traces are trusted.

## Current State

- The detector is implemented in `ImageAnalysisThread` and is validated offline against the first labeled dataset.
- `RefuelCameraModel.start_analysis(...)` already runs detector analysis on a `QThread`.
- The refuel camera window currently owns live capture through its own timer and is mainly useful for preview, dataset capture, and detector inspection.
- The droplet imager window now has a default-off refuel-level panel, imager-scoped monitor lifecycle, timing telemetry, optional calibration lifecycle markers, advisory logic, and generic ejection counting.
- The likely remaining UI-latency risk is synchronous refuel camera capture, not detector analysis itself.

## Guiding Constraints

- Do not change firmware or device protocol for the initial integration.
- Do not block or slow droplet/stream calibration steps.
- Keep the first versions advisory-only: warnings and recommendations, not automatic control.
- Start monitoring only while the droplet imager is open/active and stop when it closes.
- Use a modest sample rate first, likely `0.5-1 Hz`; increase only if timing data says it is safe.
- If refuel capture or analysis fails, disable or degrade the monitor without failing the active calibration process.

## Phase 1: Passive Droplet-Imager Panel

Add a compact refuel-level panel near the bottom of the droplet imager left/control panel. This phase does not start new hardware capture. It only displays data already present in `RefuelCameraModel`.

Status: implemented as a disabled-by-default passive panel. The master toggle shows/hides the panel and updates `RefuelCameraModel.refuel_tracking_enabled`, but no refuel camera capture or monitor timer is started in this phase. The droplet-imager left/control panel is scrollable so enabling the refuel panel does not hide controls on shorter screens.

Panel contents:

- monitor state: off, unavailable, monitoring, warning
- latest detector status: visible, full, empty, not_found
- latest level in pixels when visible
- small rolling level plot with a fixed 100-sample display window
- last valid sample time
- fixed empty-to-full Y scale based on detected channel height when available
- latest advisory message
- button or link to open the full refuel camera window for inspection

Implementation notes:

- Prefer a small embedded chart consistent with the existing droplet imager chart style.
- Connect to `RefuelCameraModel.update_level_ui_signal`.
- Make the panel useful with fake or injected samples in tests before connecting live capture.

Validation:

- Unit/UI tests can inject sample traces and verify panel labels/plot data.
- Opening the droplet imager should not start refuel camera hardware yet.
- Existing droplet/stream calibration tests should remain unchanged.

Exit criteria:

- The user can see refuel level/status in the droplet imager when samples exist.
- The panel has clear off/unavailable states.
- No calibration behavior is changed.

## Phase 2: Imager-Scoped Monitor Service

Add a monitor that starts and stops with the droplet imager, independent of the diagnostic refuel camera window.

Status: implemented as an opt-in `1000 ms` droplet-imager monitor behind the Phase 1 master toggle. The monitor starts/stops the refuel camera, skips while analysis is still running or the diagnostic refuel window is actively capturing, and marks failures as unavailable without interrupting calibration controls.

Behavior:

- Start refuel camera monitoring when the droplet imager opens or when the user enables the monitor in that window.
- Stop monitoring when the droplet imager closes.
- Capture at a conservative interval, initially `1000 ms`.
- Call the existing `capture_refuel_image_with_context(analyze=True)` path so `RefuelCameraModel` receives samples.
- If analysis is already in progress, skip the sample rather than queueing stale work.
- If the camera is unavailable, mark monitor state as unavailable and keep droplet/stream calibration usable.

Implementation notes:

- The monitor lifecycle should live at the droplet-imager/controller/model level, not inside `RefuelCameraWindow`.
- Avoid duplicate monitor timers if the refuel camera window is also open.
- Consider storing monitor counters: attempted captures, successful captures, skipped captures, failed captures.

Validation:

- Tests should verify start/stop lifecycle and skip-on-analysis-in-progress behavior.
- Hardware errors should update monitor state without raising into active calibration flows.
- Manual validation should confirm the imager remains responsive at `1 Hz`.

Exit criteria:

- The droplet imager can collect refuel level samples while open.
- The refuel camera window is no longer required for live monitoring.
- Monitoring failure does not interrupt droplet/stream calibration.

## Phase 3: Timing And Non-Interference Instrumentation

Measure whether refuel monitoring has any practical effect on the droplet/stream workflows.

Status: implemented as in-memory timing telemetry for the imager-scoped monitor. The monitor records capture, copy/resize, detector, total latency, skip, and failure timing without changing capture rate or moving capture off the UI thread.

Metrics to record:

- capture duration
- resize/copy duration
- detector runtime
- total frame-to-result latency
- skipped sample count due to analysis already running
- camera failure count
- time since last valid sample

Implementation notes:

- Store recent timing in `RefuelCameraModel` for UI display and tests.
- Include timing fields in recorder/audit output when record mode is enabled.
- Do not optimize prematurely; use this phase to decide whether capture needs a worker.

Validation:

- Unit tests should verify timing payload shape.
- Manual validation should compare droplet/stream calibration responsiveness with monitor off vs on.

Exit criteria:

- We know whether synchronous refuel camera capture is acceptable at `0.5-1 Hz`.
- If latency is measurable, the next phase can target capture-threading with evidence.

## Phase 4: Calibration Lifecycle Markers

Teach the monitor to mark meaningful phases during droplet and stream calibration.

Status: implemented as a separate default-off `Monitor Calibration Processes` toggle under the refuel level tracking toggle. When enabled, the droplet imager records calibration lifecycle markers and process drift summaries while keeping live level tracking independent. Disabling level tracking also disables process monitoring.

Examples:

- baseline/start level
- active calibration/process phase
- post-print or post-refuel sample window
- end level
- process drift summary

Implementation notes:

- Use existing calibration manager signals where possible.
- Keep this observational; do not block or alter calibration steps.
- Store phase markers in a dedicated `RefuelCameraModel.refuel_process_marker_log` and recorder output.
- Stamp future level samples with the active process context instead of adding marker-only rows to `sample_trace`.

Validation:

- Tests should simulate calibration lifecycle signals and verify phase markers.
- Manual validation should confirm traces line up with droplet/stream actions.

Exit criteria:

- A calibration run produces a refuel-level trace with useful phase boundaries.
- Baseline-to-end drift can be computed repeatably.

## Phase 5: Advisory Logic

Turn the passive trace into operator guidance.

Status: implemented as advisory-only guidance gated by the existing `Monitor Calibration Processes` toggle. Basic refuel level tracking remains passive when that toggle is off.

Advisories:

- level decreased over process: suggest increasing refuel pressure or refuel pulse width
- level increased over process: suggest decreasing refuel pressure or refuel pulse width
- near empty: warn before continuing
- near full: warn before continuing
- stale or unavailable monitor: show monitor unavailable/stale, without interrupting unless configured later

Implementation notes:

- Start with simple thresholds in pixels.
- Prefer recommendations over modal dialogs at first.
- The advisory should explain the observed drift and suggested direction.
- No automatic pressure or pulse-width changes in this phase.
- The advisory toggle is the same process-monitoring toggle from Phase 4.

Validation:

- Unit tests should cover low/high/stable/stale/near-empty/near-full cases.
- Manual validation should compare recommendations with observed traces.

Exit criteria:

- The user gets actionable guidance without needing to watch the refuel camera window.
- The advisory system is understandable and not disruptive.

## Phase 5B: Generic Ejection Counting

Track how many ejections happened during monitored calibration processes so drift can be normalized as pixels per ejection.

Status: implemented as an imager-scoped counter that resets when refuel level tracking is enabled. The counter records observed successful droplet-camera captures and commanded print/dispense requests separately, then process summaries resolve a single ejection count for drift normalization.

Count-source priority:

- `printed_capture_count` from stream gravimetric-style capture state payloads when available
- observed successful droplet-camera capture counts
- commanded print/dispense counts as a fallback

Implementation notes:

- `RefuelCameraModel` stores a capped ejection event log and exposes session totals for the refuel panel.
- Process summaries include `ejection_count_delta`, `ejection_count_source`, and `drift_px_per_ejection`.
- Level samples are stamped with active process ejection context when process monitoring is enabled.
- Advisories include drift-per-ejection text when a valid process count exists.
- The counter is still observational; it does not adjust pressure or pulse width.

Validation:

- Tests cover counter reset, observed/commanded events, reported stream counts, zero-count behavior, panel text, and controller capture/dispense hooks.

Exit criteria:

- A monitored calibration can report both total drift and drift per ejection.
- The panel shows general ejection totals while level tracking is enabled.
- Count source is explicit enough to distinguish gravimetric replay, observed capture counts, and commanded fallbacks.

## Phase 6: Diagnostic Handoff To Refuel Camera Window

Make it easy to inspect the underlying image when the imager panel reports a warning or odd level.

Behavior:

- The imager panel can open the refuel camera window.
- The refuel camera window remains the detailed diagnostic surface:
  - raw preview
  - annotated preview
  - detector parameters
  - dataset capture
  - manual snapshots

Implementation notes:

- Avoid starting competing capture loops if both views are open.
- The diagnostic window should reflect the same latest frame/status when possible.

Validation:

- Opening the diagnostic window from the imager does not stop the monitor.
- Closing the diagnostic window does not stop imager-scoped monitoring unless the imager itself closes.

Exit criteria:

- The user can move from advisory panel to detailed inspection smoothly.

## Phase 7: Optional Assisted Or Closed-Loop Adjustment

Only consider this after collecting enough successful advisory traces.

Possible progression:

1. Advisory text only.
2. Advisory plus "Apply suggested change" button.
3. Semi-automatic adjustment with confirmation.
4. Fully automatic adjustment, only if proven safe.

Control targets:

- refuel pressure
- refuel pulse width

Safety requirements:

- explicit bounds
- rate limits
- audit records for every recommendation and applied change
- clear rollback behavior
- disable automatic changes by default

Exit criteria:

- Real calibration traces demonstrate that advisory logic is reliable enough to justify assisted changes.
- The operator can always understand and override the monitor.

## Recommended Next Implementation

Continue with Phase 6 diagnostic handoff:

1. Wire the droplet-imager panel button to open the refuel camera window where the app already exposes that launcher.
2. Avoid competing capture loops between imager monitoring and the diagnostic refuel camera window.
3. Surface the latest warning/advisory context in the diagnostic path.
4. Keep the handoff optional; closing the diagnostic window should not stop imager-scoped monitoring.

This makes odd advisory states easy to inspect without adding automatic pressure or pulse-width changes.
