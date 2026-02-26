# Audit Issues

## Scope
- Date: 2026-02-26
- Auditor: Codex (GPT-5)
- Commit/Branch: Working tree audit of `FreeRTOS-interface/` only
- Covered Areas: `App.py`, `Controller.py`, `Model.py`, `Machine_FreeRTOS.py`, `View.py`

## Triage Summary (Open Only)
- Open issue count: 3
- Highest open severity: `High`
- Deduping performed:
  - Removed resolved/covered items from active queue.
  - Merged protocol-test drift concerns under `AUD-2026-015` + `AUD-2026-019`.
  - Kept `AUD-2026-020` as documentation/maintainability (distinct from behavior bug fixed in `AUD-2026-001`).

## High Priority

## Medium Priority

## AUD-2026-014
- Severity: Medium
- Category: Timing
- Location: `FreeRTOS-interface/Machine_FreeRTOS.py`, `Machine._on_goodbye_done` (around line 1482)
- Description: Blocking `time.sleep(0.05)` in Qt-controlled path.
- Impact: Event-loop stalls and timing nondeterminism.
- Verification Note: Measure disconnect latency/responsiveness under active UI loop.
- Test Coverage Note: Missing (disconnect responsiveness timing test).

## AUD-2026-011
- Severity: Medium
- Category: Configuration
- Location: `FreeRTOS-interface/App.py`, `load_settings` (around lines 44-46)
- Description: Startup settings load lacks robust error/fallback handling.
- Impact: Corrupt/missing settings can hard-fail startup.
- Verification Note: Boot with missing/invalid settings file and assert deterministic fallback behavior.
- Test Coverage Note: Missing (startup settings fallback test).

## Low Priority / Cleanup

## AUD-2026-020
- Severity: Low
- Category: Maintainability
- Location: `FreeRTOS-interface/Controller.py`, `Controller.move_to_location`
- Description: Inverted Z-axis convention is implicit.
- Impact: Future edits may reintroduce unsafe routing assumptions.
- Verification Note: Add explicit convention assertions/docs tied to movement logic.
- Test Coverage Note: Partial (current-profile safe-Z covered; legacy/convention tests still missing).

## Recently Resolved (Milestone M1)

## AUD-2026-006
- Status: Resolved
- Resolution Reference:
  - Code: `FreeRTOS-interface/Model.py`, `_atomic_json_dump` used by `save_experiment` and `create_progress_file`
  - Tests:
    - `tests/test_model_atomic_writes.py::test_save_experiment_atomic_write_preserves_previous_file_on_replace_failure`
    - `tests/test_model_atomic_writes.py::test_create_progress_file_atomic_write_preserves_previous_file_on_replace_failure`

## AUD-2026-010
- Status: Resolved
- Resolution Reference:
  - Code: `FreeRTOS-interface/Model.py`, `WellPlate.clear_all_wells` now resets `excluded_wells` correctly
  - Tests:
    - `tests/test_wellplate_clear_all_wells.py::test_clear_all_wells_resets_excluded_wells_and_restores_availability`

## AUD-2026-018
- Status: Resolved
- Resolution Reference:
  - Code: `FreeRTOS-interface/Model.py`, `reset_experiment_model` now uses profile-aware default helper
  - Tests:
    - `tests/test_experiment_model_reset_defaults.py::test_reset_experiment_model_uses_current_profile_fill_default`
    - `tests/test_experiment_model_reset_defaults.py::test_reset_experiment_model_uses_legacy_profile_fill_default`

## Recently Resolved (Milestone M2)

## AUD-2026-015
- Status: Resolved
- Resolution Reference:
  - Code: `FreeRTOS-interface/Machine_FreeRTOS.py`, `parse_tlv_payload` diagnostics + explicit payload-size guards in `build_frame` and `Command.__init__`
  - Tests:
    - `tests/test_protocol_tlv_parser.py::test_parse_tlv_payload_logs_unknown_and_malformed_entries`
    - `tests/test_protocol_tlv_parser.py::test_parse_tlv_payload_logs_length_mismatch`
    - `tests/test_protocol_frame.py::test_build_frame_rejects_payload_length_over_255`
    - `tests/test_protocol_frame.py::test_command_rejects_payload_length_over_255`

## AUD-2026-019
- Status: Resolved
- Resolution Reference:
  - Code: `FreeRTOS-interface/Machine_FreeRTOS.py`, `_on_any_ack` deterministic seq32/seq8 handling contract
  - Tests:
    - `tests/test_machine_ack_matching.py::test_on_any_ack_matches_seq32_key_when_present`
    - `tests/test_machine_ack_matching.py::test_on_any_ack_falls_back_to_seq8_when_seq32_absent`
    - `tests/test_machine_ack_matching.py::test_on_any_ack_does_not_fallback_to_seq8_when_seq32_present_but_mismatched`
    - `tests/test_machine_ack_matching.py::test_on_any_ack_duplicate_ack_only_consumes_once`

## Recently Resolved (Milestone M3)

## AUD-2026-012
- Status: Resolved
- Resolution Reference:
  - Code: `FreeRTOS-interface/Controller.py`, `_classify_port` balance heuristics now consistently lowercase-matched
  - Tests:
    - `tests/test_controller_port_classification.py::test_classify_port_case_insensitive_heuristics`

## AUD-2026-013
- Status: Resolved
- Resolution Reference:
  - Code: `FreeRTOS-interface/Controller.py`, `disconnect_droplet_camera_signals` now disconnects controller-owned handlers explicitly
  - Tests:
    - `tests/test_controller_signal_scoping.py::test_disconnect_droplet_camera_signals_only_removes_controller_handlers`

## AUD-2026-016
- Status: Resolved
- Resolution Reference:
  - Code: `FreeRTOS-interface/Controller.py`, duplicate `check_if_all_completed` definition removed
  - Tests:
    - `tests/test_controller_static_guards.py::test_controller_has_no_duplicate_method_definitions`
