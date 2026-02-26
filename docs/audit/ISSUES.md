# Audit Issues

## Scope
- Date: 2026-02-26
- Auditor: Codex (GPT-5)
- Commit/Branch: Working tree audit of `FreeRTOS-interface/` only
- Covered Areas: `App.py`, `Controller.py`, `Model.py`, `Machine_FreeRTOS.py`, `View.py`

## Triage Summary (Open Only)
- Open issue count: 0
- Highest open severity: n/a
- Deduping performed:
  - Removed resolved/covered items from active queue.
  - Merged protocol-test drift concerns under `AUD-2026-015` + `AUD-2026-019`.

## Medium Priority

No open Medium issues.

## Recently Resolved (Milestone M6)

## AUD-2026-014
- Status: Resolved
- Resolution Reference:
  - Code: `FreeRTOS-interface/Machine_FreeRTOS.py`, `_on_goodbye_done` (removed blocking sleep; immediate cleanup path)
  - Tests:
    - `tests/test_machine_disconnect_timing.py::test_on_goodbye_done_does_not_block_with_sleep`
    - `tests/test_machine_disconnect_timing.py::test_on_goodbye_done_still_disconnects_when_buffer_reset_fails`

## AUD-2026-011
- Status: Resolved
- Resolution Reference:
  - Code: `FreeRTOS-interface/App.py`, `load_settings` (deterministic fallback for missing/invalid settings payloads)
  - Tests:
    - `tests/test_app_settings_fallback.py::test_load_settings_returns_defaults_when_file_missing`
    - `tests/test_app_settings_fallback.py::test_load_settings_returns_defaults_when_json_invalid`
    - `tests/test_app_settings_fallback.py::test_load_settings_reads_valid_json`

## Recently Resolved (Milestone M5)

## AUD-2026-020
- Status: Resolved
- Resolution Reference:
  - Tests:
    - `tests/test_controller_move_to_location.py::test_move_to_location_legacy_profile_uses_legacy_safe_height_before_balance_route`
    - `tests/test_controller_move_to_location.py::test_move_to_location_enforces_safe_z_when_below_threshold`
    - `tests/test_controller_move_to_location.py::test_move_to_location_inverted_z_convention_skips_safe_z_when_already_high`

## Recently Resolved (Milestone M4 Coverage Debt)
- Status: Covered by new tests (no direct issue ID closed)
- Coverage Reference:
  - Tests:
    - `tests/test_experiment_designer_interlock.py::test_experiment_designer_lock_precedence_matrix`
    - `tests/test_experiment_designer_interlock.py::test_experiment_designer_gripper_lock_dominates_uploaded_manual_modes`
    - `tests/test_experiment_designer_reopen.py::test_open_close_designer_does_not_apply_when_not_finished`
    - `tests/test_experiment_designer_reopen.py::test_open_close_repeated_cycles_do_not_mutate_runtime_state`
    - `tests/test_experiment_designer_reopen.py::test_finish_path_still_applies_once_on_reopen_session`

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
