# Experiment Audit Plan

## Summary

Add an app-side experiment audit trail that records high-level experiment events in an append-only JSONL file, plus a read-only timeline window for reviewing the experiment after or during a run.

The audit trail should describe what the operator and app did at the experiment level without duplicating every low-level command sent to the MCU.

- No firmware or device protocol changes.
- No serial packet dump in the experiment audit.
- `progress.json`, `calibration.json`, and `calibration_recordings/` remain authoritative detailed artifacts.
- `experiment_audit.jsonl` becomes the concise timeline for review, reporting, and troubleshooting.

## Implementation Status

| Phase | Status | Completed | Validation |
| --- | --- | --- | --- |
| Phase 1: Plan and Schema | Complete | `docs/experiment_audit_plan.md` created with schema, call path, phases, risks, validation, and rollback. | Documentation-only; readback verified. |
| Phase 2: Audit Writer Core | Complete | Added standalone `ExperimentAuditLog` writer and focused tests in `tests/test_experiment_audit_log.py`; no Controller, CalibrationManager, or UI wiring yet. | `.\env\Scripts\python.exe -m pytest -q tests/test_experiment_audit_log.py` -> 8 passed. `py -m pytest -q tests/test_experiment_audit_log.py` could not run because the Windows `py` launcher reported no installed Python. |
| Phase 3: Experiment Lifecycle Integration | Complete | Added model-owned audit writer integration, experiment audit path derivation, runtime `experiment_initialized`/`experiment_loaded` lifecycle events, and focused integration tests in `tests/test_experiment_audit_integration.py`. | `.\env\Scripts\python.exe -m pytest -q tests/test_experiment_audit_log.py tests/test_experiment_audit_integration.py` -> 13 passed. `.\env\Scripts\python.exe -m pytest -q tests/test_experiment_progress_and_keys.py` -> 4 passed. |
| Phase 4: Print Array Events | Complete | Added Controller print-array audit snapshot helpers and lifecycle event hooks in `FreeRTOS-interface/Controller.py`; added focused print-array audit coverage in `tests/test_controller_experiment_audit.py`. | `.\env\Scripts\python.exe -m pytest -q tests/test_controller_experiment_audit.py tests/test_controller_print_guards.py` -> 52 passed. `.\env\Scripts\python.exe -m pytest -q tests/test_experiment_audit_log.py tests/test_experiment_audit_integration.py` -> 13 passed. |
| Phase 5: Calibration Events | Complete | Added CalibrationManager session/process audit helpers and lifecycle hooks in `FreeRTOS-interface/CalibrationClasses/Model.py`; added focused calibration audit coverage in `tests/test_calibration_experiment_audit.py`. | `.\env\Scripts\python.exe -m pytest -q tests/test_calibration_experiment_audit.py tests/test_calibration_recorder_toggle.py tests/test_calibration_phase_aliases.py` -> 18 passed. `.\env\Scripts\python.exe -m pytest -q tests/test_calibration_memory_integration.py` -> 12 passed. `.\env\Scripts\python.exe -m pytest -q tests/test_experiment_audit_log.py tests/test_experiment_audit_integration.py` -> 13 passed. |
| Phase 6: Audit Timeline Reader | Pending | Not started. | Pending |
| Phase 7: Audit Timeline Window | Pending | Not started. | Pending |
| Phase 8: Operator Notes and Export | Pending | Not started. | Pending |

## Call Path

The feature crosses the app MVC layers at semantic action boundaries:

- Experiment lifecycle:
  - View experiment actions -> Model.load_experiment_from_model/load_experiment_from_file -> ExperimentModel paths -> ExperimentAuditLog
- Print array:
  - View print/stop/resume action -> Controller.print_array/request_array_soft_stop -> ExperimentModel/progress.json -> Machine_FreeRTOS queued commands -> firmware status/ack -> Controller finalize hooks -> ExperimentAuditLog
- Calibration:
  - View calibration action -> Controller.start_*_calibration -> CalibrationManager/process -> Controller movement/settings/capture handlers -> Machine_FreeRTOS -> CalibrationManager result/calibration.json -> ExperimentAuditLog
- Audit review:
  - View audit menu/button -> AuditTimelineWindow -> read `experiment_audit.jsonl` -> table/detail view

## Goals

- Provide a human-readable experiment timeline.
- Preserve enough structured context to reproduce or diagnose a run.
- Keep writes append-only and best-effort so audit failures do not stop hardware operation.
- Make the first implementation small, tested, and app-side only.
- Separate high-level audit events from detailed calibration/process/command logs.

## Non-Goals

- Do not change message formats, opcodes, parsing, or firmware behavior.
- Do not record every small movement, pressure update, serial command, or status frame.
- Do not replace `progress.json`, `calibration.json`, calibration memory, or process recorders.
- Do not add editable audit history. Corrections should be appended as notes later.

## Output File

Each experiment directory should contain:

- `experiment_audit.jsonl`

The file should live beside:

- `experiment_design.json`
- `progress.json`
- `calibration.json`
- `key.csv`
- `concentration_key.csv`

Every line is one JSON object. The writer should create the file lazily when the first event is recorded.

## Event Schema v1

Required top-level fields:

- `schema_version`: integer, initially `1`
- `event_id`: UUID string
- `timestamp_utc`: ISO-8601 UTC timestamp with `Z`
- `elapsed_s`: seconds since the first event in the current audit file, or `null` if unavailable
- `event_type`: stable snake_case event name
- `level`: `info`, `warning`, or `error`
- `summary`: concise human-readable description
- `details`: object with event-specific structured fields
- `context`: object with experiment and app context

Recommended `context` fields:

- `experiment_name`
- `experiment_dir`
- `experiment_file_path`
- `progress_file_path`
- `calibration_file_path`
- `app_version`, if available
- `machine_id`, if available later
- `operator`, if available later

Recommended `details` fields when relevant:

- `stock_id`
- `stock_solution`
- `printer_head_id`
- `printer_head_slot`
- `printing_mode`
- `print_pressure_psi`
- `target_print_pressure_psi`
- `print_pulse_width_us`
- `droplet_volume_nL`
- `remaining_wells`
- `completed_wells`
- `target_droplets`
- `calibration_phase`
- `calibration_run_id`
- `calibration_result_summary`
- `artifact_refs`

## Initial Event Catalog

Experiment lifecycle:

- `experiment_initialized`
- `experiment_loaded`
- `experiment_design_saved`
- `experiment_progress_loaded`
- `experiment_progress_reset`

Print setup and parameters:

- `print_settings_applied`
- `print_profile_enabled`
- `print_profile_disabled`
- `printer_head_loaded`
- `printer_head_unloaded`

Print array:

- `print_array_requested`
- `print_array_started`
- `print_array_soft_stop_requested`
- `print_array_paused`
- `print_array_resumed`
- `print_array_completed`
- `print_array_refill_required`
- `print_array_aborted`

Calibration:

- `calibration_session_started`
- `calibration_session_ended`
- `calibration_process_started`
- `calibration_process_completed`
- `calibration_process_failed`
- `calibration_process_stopped`

Operator notes, later phase:

- `operator_note_added`

Warnings and errors:

- `audit_write_failed`
- `machine_warning`
- `machine_error`

## Phase 1: Plan and Schema

Purpose:

Document the audit system, event schema, event catalog, phase plan, risks, and validation strategy.

Files expected:

- `docs/experiment_audit_plan.md`

Tests:

- No automated tests required for this documentation-only phase.

Done when:

- The plan defines the JSONL file location.
- The plan defines schema v1 fields.
- The plan lists MVC integration points.
- The plan breaks implementation into testable phases.

## Phase 2: Audit Writer Core

Purpose:

Add the core append-only writer without changing UI behavior.

Likely files:

- `FreeRTOS-interface/ExperimentAuditLog.py`
- `FreeRTOS-interface/Model.py`
- `tests/test_experiment_audit_log.py`

Implementation notes:

- `ExperimentAuditLog` should be small and dependency-light.
- It should resolve the active audit path from `model.experiment_model.experiment_dir_path`.
- It should expose a single high-level method such as `record(event_type, summary, details=None, level="info")`.
- It should be best-effort by default: failures should be captured in memory or emitted as warnings without interrupting the active experiment.
- It should write UTF-8 JSONL with compact sorted-enough fields for review.
- It should avoid importing View classes.

Tests:

- Records valid JSONL.
- Adds required schema fields.
- Appends without rewriting existing events.
- Handles missing experiment directory gracefully.
- Handles non-JSON-serializable values with safe normalization.
- Preserves previous lines when a later write fails.

Done when:

- A standalone writer can append events to an experiment audit file.
- Unit tests validate append behavior and schema basics.
- No Controller or CalibrationManager hooks are required yet.

## Phase 3: Experiment Lifecycle Integration

Purpose:

Create and use the audit file path from the active experiment context.

Likely files:

- `FreeRTOS-interface/Model.py`
- `FreeRTOS-interface/ExperimentAuditLog.py`
- `tests/test_experiment_audit_integration.py`

Hook candidates:

- `Model.__init__`
  - create `self.experiment_audit_log`
- `ExperimentModel.update_all_paths`
  - derive `experiment_audit_file_path`
- `ExperimentModel.initialize_experiment`
  - record `experiment_initialized`
- `ExperimentModel.load_experiment`
  - record or enable `experiment_loaded`
- `Model.load_experiment_from_model`
  - record design assignment/load context after runtime bindings are available

Tests:

- New experiment gets an audit path in the experiment directory.
- Loading an existing experiment records a load event.
- Events include experiment file/progress/calibration path context.
- Audit failures do not prevent experiment load.

Done when:

- Basic experiment lifecycle events appear in `experiment_audit.jsonl`.
- Existing experiment load/create tests still pass.

## Phase 4: Print Array Events

Purpose:

Record the major print array lifecycle without logging every queued move or droplet command.

Likely files:

- `FreeRTOS-interface/Controller.py`
- `FreeRTOS-interface/ExperimentAuditLog.py`
- `tests/test_controller_experiment_audit.py`

Hook candidates:

- `Controller.print_array`
  - `print_array_requested`
  - `print_array_resumed` when starting from `resume_ready`
  - `print_array_started` after the array context is created and the runner state becomes `running`
- `Controller._start_array_run_context`
  - build stock/head/remaining-well context
- `Controller.request_array_soft_stop`
  - `print_array_soft_stop_requested`
- `Controller._begin_soft_stop_clear_and_park` or `_finish_array_finalize`
  - `print_array_paused` when soft stop reaches resume-ready state
- `Controller._finish_array_finalize`
  - `print_array_completed`
  - `print_array_refill_required`
  - `print_array_aborted`

Snapshot helper candidates:

- `_build_print_settings_snapshot`
- `_build_loaded_printer_head_snapshot`
- `_build_print_array_snapshot`
- `_record_print_array_audit_event`

Tests:

- Starting an array records requested and started events.
- Soft stop records requested and paused/resume-ready events.
- Resuming records resumed event with current settings snapshot.
- Completion records completed event.
- Refill-required records warning-level event.
- Hard abort records error-level event.
- Tests use fakes and do not require hardware.

Done when:

- Print array timeline is readable from a dry-run/fake test.
- No low-level movement or per-well event flood is added by default.

## Phase 5: Calibration Events

Purpose:

Record calibration milestones and link to detailed calibration artifacts.

Likely files:

- `FreeRTOS-interface/CalibrationClasses/Model.py`
- `FreeRTOS-interface/ExperimentAuditLog.py`
- `tests/test_calibration_experiment_audit.py`

Hook candidates:

- `CalibrationManager.begin_session`
  - `calibration_session_started`
- `CalibrationManager.end_session`
  - `calibration_session_ended`
- `CalibrationManager.start_active_calibration`
  - `calibration_process_started`
- `CalibrationManager.onCalibrationCompleted`
  - `calibration_process_completed`
- `CalibrationManager.onCalibrationError`
  - `calibration_process_failed` or `calibration_process_stopped`
- `CalibrationManager.onCalibrationDataUpdated`
  - optional compact result summary only for final/result payloads; avoid full duplication

Details should include:

- `calibration_file_path`
- `calibration_run_id`
- `calibration_phase`
- `process_name`
- `printer_head_id`
- `stock_solution`
- compact settings snapshot
- artifact references when available

Tests:

- Session start/end records events.
- Process start/completion records events.
- Error/stopped records correct event type and level.
- Calibration audit events include references to `calibration.json` instead of copying full calibration data.
- Calibration continues if audit writes fail.

Done when:

- Calibration events provide a useful timeline while detailed results remain in existing artifacts.

## Phase 6: Audit Timeline Reader

Purpose:

Add parsing and table-model logic before building the window.

Likely files:

- `FreeRTOS-interface/ExperimentAuditLog.py` or `FreeRTOS-interface/ExperimentAuditReader.py`
- `tests/test_experiment_audit_reader.py`

Implementation notes:

- Parse JSONL into stable event rows.
- Preserve file order.
- Compute display timestamps and elapsed time.
- Keep malformed lines visible as warning rows or return parse diagnostics.
- Do not mutate the audit file while reading.

Tests:

- Reads valid JSONL events.
- Preserves append order.
- Handles empty/missing audit file.
- Handles malformed lines without crashing.
- Provides detail JSON for selected rows.

Done when:

- UI code can consume a simple list/model of audit event rows.

## Phase 7: Audit Timeline Window

Purpose:

Add a read-only app window for reviewing the experiment timeline.

Likely files:

- `FreeRTOS-interface/View.py`
- `FreeRTOS-interface/Controller.py` if a Controller action is used to open/refresh the window
- `FreeRTOS-interface/ExperimentAuditReader.py`
- `tests/test_experiment_audit_window.py` or focused model/view tests

UI requirements:

- Read-only table.
- Columns:
  - time
  - elapsed
  - level/status
  - event type
  - summary
- Details panel for selected row showing formatted structured JSON.
- Refresh/reload action.
- Filters for level and event type may be added if simple.
- Clear empty state when no audit file exists.
- Malformed audit lines should be visible but should not break the window.

Tests:

- Table model renders event rows.
- Details panel receives selected event details.
- Empty/missing file state works.
- Malformed line diagnostics are represented.
- Refresh reloads newly appended events.

Done when:

- User can open an audit window from the main app and inspect the current experiment timeline.

## Phase 8: Operator Notes and Export

Purpose:

Add user-authored notes and optional human-readable exports after the core timeline is stable.

Likely files:

- `FreeRTOS-interface/View.py`
- `FreeRTOS-interface/Controller.py`
- `FreeRTOS-interface/ExperimentAuditLog.py`
- `tests/test_experiment_audit_notes.py`

Events:

- `operator_note_added`

Implementation notes:

- Notes should append new events.
- Existing audit rows should remain immutable.
- Export can be plain text, CSV, or Markdown after the timeline window exists.

Tests:

- Appending a note records a valid event.
- Notes appear in the reader/window.
- Empty notes are rejected or normalized.

Done when:

- Operators can add timestamped notes during an experiment without editing prior history.

## Validation Commands

Documentation-only phase:

- No automated test required.

Python phases:

- `python -m pytest -q tests/test_experiment_audit_log.py`
- `python -m pytest -q tests/test_experiment_audit_reader.py`
- `python -m pytest -q tests/test_controller_experiment_audit.py`
- `python -m pytest -q`

Firmware:

- Not required unless a future phase changes files under `firmware/`.

Manual checklist for the integrated feature:

- Create a new experiment.
- Confirm `experiment_audit.jsonl` appears in the experiment directory after the first event.
- Start a calibration and confirm session/process events appear.
- Start a print array with fake or safe dry-run hardware setup.
- Pause and resume the array.
- Complete or abort the array.
- Open the audit timeline window.
- Confirm event order, timestamps, event types, summaries, and details are understandable.
- Confirm `progress.json` and `calibration.json` remain unchanged in purpose.

## Risks and Mitigations

Risk: Audit noise makes the timeline difficult to use.

Mitigation:

- Only log semantic experiment events by default.
- Keep low-level command details in existing process/transport logs.

Risk: Audit write failure interrupts hardware operation.

Mitigation:

- Treat audit writes as best-effort.
- Surface write failures as warnings, not experiment-stopping errors.

Risk: Audit duplicates detailed calibration data and grows too large.

Mitigation:

- Store compact summaries plus artifact references to `calibration.json` and `calibration_recordings/`.

Risk: UI viewer mutates or corrupts audit data.

Mitigation:

- Keep reader/window read-only.
- Add notes through append-only writer events.

Risk: Event schema changes break existing logs.

Mitigation:

- Include `schema_version`.
- Keep reader tolerant of missing optional fields.
- Add migration only if a future schema requires it.

## Rollback Plan

For documentation-only Phase 1:

- Revert `docs/experiment_audit_plan.md`.

For later code phases:

- Remove or disable `ExperimentAuditLog` wiring from `Model`, `Controller`, and `CalibrationManager`.
- Leave existing experiment files, `progress.json`, `calibration.json`, and firmware behavior untouched.
- Delete generated `experiment_audit.jsonl` only if explicitly requested by the operator.

## Open Questions

- Should audit logging start immediately when an experiment is initialized, or only when the experiment is loaded into runtime?
- Should manual operator identity be captured now, or deferred until the app has a user/session concept?
- Should the timeline window live under the existing experiment UI, a tools menu, or a dedicated dock/window?
- Should per-well progress be summarized only at completion, or should optional detailed per-well audit events be available behind a debug setting?
