# Audit Issues

## Scope
- Date: 2026-02-26
- Auditor: Codex (GPT-5)
- Commit/Branch: Working tree audit of `FreeRTOS-interface/` only
- Covered Areas: `App.py`, `Controller.py`, `Model.py`, `Machine_FreeRTOS.py`, `View.py`

## Triage Summary (Open Only)
- Open issue count: 6
- Highest open severity: `High`
- Deduping performed:
  - Removed resolved/covered items from active queue.
  - Merged protocol-test drift concerns under `AUD-2026-015` + `AUD-2026-019`.
  - Kept `AUD-2026-020` as documentation/maintainability (distinct from behavior bug fixed in `AUD-2026-001`).

## High Priority

## Medium Priority

## AUD-2026-012
- Severity: Medium
- Category: Correctness
- Location: `FreeRTOS-interface/Controller.py`, `Controller._classify_port` (around line 219)
- Description: Lowercased description is compared against mixed-case token (`"Prolific"`).
- Impact: Some balance ports may be misclassified.
- Verification Note: Replay synthetic `ListPortInfo` variants with different casing and descriptors.
- Test Coverage Note: Partial (basic coverage exists; edge-casing/heuristics still missing).

## AUD-2026-013
- Severity: Medium
- Category: Resource Management
- Location: `FreeRTOS-interface/Controller.py`, `disconnect_droplet_camera_signals` (around lines 141-146)
- Description: Broad `disconnect()` may remove unrelated subscribers.
- Impact: Other listeners can silently break.
- Verification Note: Multi-subscriber signal wiring before/after controller disconnect call.
- Test Coverage Note: Missing (subscriber-scoping test).

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

## AUD-2026-016
- Severity: Low
- Category: Maintainability
- Location: `FreeRTOS-interface/Controller.py`, duplicate `check_if_all_completed` (around lines 751-753, 1006-1008)
- Description: Duplicate class method definition.
- Impact: Confusing override behavior and refactor risk.
- Verification Note: Static parse to detect duplicate method names in critical classes.
- Test Coverage Note: Missing (AST static guard test).

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
