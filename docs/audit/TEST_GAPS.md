# Audit Test Gaps

## Scope
- Date: 2026-02-26
- Commit/Branch: Working tree audit of `FreeRTOS-interface/` only
- Existing Test Suite Summary: Good baseline for protocol framing, queue status transitions, model assignment/progress consistency, and selected controller guardrails. Significant gaps remain in failure-mode handling and UI/event-loop edge cases.

## Missing Tests By Subsystem

## Model
- ~~`Model.load_experiment_from_model` (`Model.py`:5522-5526)~~
  - Covered by: `tests/test_experiment_assignment_auto.py::test_load_experiment_randomization_does_not_mutate_global_rng`
- `ExperimentModel.create_progress_file`/`save_experiment` (`Model.py`:2406-2407, 2452-2476)
  - Gap: no atomic write protection.
  - Missing test: fault-injection write interruption test (expect non-corrupt file state).
- ~~`ExperimentModel.read_progress_file`/`return_progress_data` (`Model.py`:2984-2995)~~
  - Covered by: `tests/test_experiment_progress_io_resilience.py::test_read_progress_file_handles_invalid_json_with_safe_fallback`
  - Covered by: `tests/test_experiment_progress_io_resilience.py::test_return_progress_data_handles_missing_file_with_safe_fallback`
- ~~`ExperimentModel.load_progress` (`Model.py`:3014-3017)~~
  - Covered by: `tests/test_experiment_update_well_plate.py::test_load_progress_skips_unknown_reagent_ids_gracefully`
- `WellPlate.clear_all_wells` (`Model.py`:3787-3791)
  - Gap: excluded well state reset typo not covered.
  - Missing test: exclude wells -> clear -> verify exclusion set truly reset.
- `ExperimentModel.reset_experiment_model` (`Model.py`:3077-3085)
  - Gap: profile-dependent fill-droplet defaults after reset not covered.
  - Missing test: legacy/current profile reset preserves expected fill droplet volume defaults.

## Controller
- ~~`Controller.move_to_location` (`Controller.py`:773-792)~~
  - Covered by: `tests/test_controller_move_to_location.py::test_move_to_location_enforces_safe_z_when_below_threshold`
  - Covered by: `tests/test_controller_move_to_location.py::test_move_to_location_camera_transition_applies_safe_z_before_xyz`
  - Covered by: `tests/test_controller_move_to_location.py::test_move_to_location_slot_transition_applies_safe_z_before_xyz`
  - Covered by: `tests/test_controller_move_to_location.py::test_move_to_location_balance_route_applies_safe_z_then_safe_y_then_x_then_xyz`
- `Controller._classify_port` (`Controller.py`:214-220)
  - Gap: case normalization/heuristics not fully validated.
  - Missing test: synthetic `ListPortInfo` variants covering prolific/stm/balance strings and vid-only cases.
- `Controller.disconnect_droplet_camera_signals` (`Controller.py`:141-146)
  - Gap: disconnect-scoping behavior with multi-subscriber signals.
  - Missing test: ensure only controller handlers are disconnected.
- `Controller.print_array` (`Controller.py`:1018-1086)
  - Gap: queue-nonempty, profile branches, refill cutoff, and last-well completion orchestration not fully covered.
  - Missing test: integration-lite with fake machine queue and well fixtures.
- Duplicate method definitions (`Controller.py`:751-753 and 1006-1008)
  - Gap: no static guardrail against duplicate method names.
  - Missing test: lightweight AST lint test for duplicate member definitions in critical classes.
- `Controller.move_to_location` legacy profile path (`Controller.py`)
  - Gap: safe-height threshold behavior for `profile.name == "legacy"` is not covered after safe-Z fix.
  - Missing test: unit test asserting `safe_z=5000` routing behavior and ordering in legacy profile mode.

## Comms Boundary (Host Protocol + Threading)
- ~~`Machine.connect_board`/`_hello_timeout` (`Machine_FreeRTOS.py`:1347-1390)~~
  - Covered by: `tests/test_machine_connection_retries.py::test_connect_board_retry_does_not_leak_reader_or_serial`
- ~~`Machine.clear_command_queue`/`_on_clear_ack` (`Machine_FreeRTOS.py`:1716-1737)~~
  - Covered by: `tests/test_machine_clear_queue_contract.py::test_clear_queue_timeout_keeps_tx_blocked_until_clear_status`
- ~~`SerialReader._parse_ack`/`run` (`Machine_FreeRTOS.py`:781-783, 810-819)~~
  - Covered by: `tests/test_serial_reader_failures.py::test_serial_reader_ignores_malformed_ack_and_continues`
- `parse_tlv_payload` (`Machine_FreeRTOS.py`:744-758)
  - Gap: malformed TLV diagnostics absent.
  - Missing test: malformed tag length and unknown tag coverage with expected warning counters.
- ~~`Machine._write_frame` (`Machine_FreeRTOS.py`:1626-1629)~~
  - Covered by: `tests/test_machine_send_path_guards.py::test_write_frame_with_closed_serial_emits_error_without_crash`
- `Machine._on_goodbye_done` (`Machine_FreeRTOS.py`:1481-1489)
  - Gap: blocking sleep impact on event loop not tested.
  - Missing test: disconnect responsiveness timing assertion under Qt event loop.
- Protocol contract envelope
  - Gap: explicit test for payload length <= 255 boundary.
  - Missing test: unit test enforcing frame length guard semantics for future command growth.
- `Machine._on_any_ack` seq matching (`Machine_FreeRTOS.py`)
  - Gap: no direct test for seq32/seq8 fallback matching across mixed ACK payloads.
  - Missing test: ACK handling matrix asserting pending-ACK cleanup for seq32-present, seq32-absent, and mismatched seq8 cases.

## View
- ~~`MainWindow.closeEvent` (`View.py`:388-405)~~
  - Covered by: `tests/test_mainwindow_closeevent.py::test_mainwindow_closeevent_has_timeout_if_disconnect_signal_missing`
  - Covered by: `tests/test_mainwindow_closeevent.py::test_mainwindow_closeevent_returns_quickly_when_disconnect_signal_arrives`
- ~~`popup_yes_no` decision handling (`View.py`:301-303 + callers)~~
  - Covered by: `tests/test_view_popup_yes_no_roles.py::test_popup_yes_no_callers_do_not_depend_on_button_text_literals`
  - Covered by: `tests/test_view_popup_yes_no_roles.py::test_popup_yes_no_no_response_preserves_negative_paths`
- `ExperimentDesignDialog` lock/refresh interactions (`View.py`:4544-4988)
  - Gap: combined lock precedence and external subscriber interactions are only partially covered.
  - Missing test: multiple lock-mode transitions (uploaded/manual/gripper) with explicit enable-state matrix assertions.
- `open_experiment_designer` modal path (`View.py`:1416-1420)
  - Gap: no regression around reopen/close interactions under active print state beyond basic interlock checks.
  - Missing test: integration-lite flow with active runtime state + open/close cycles + no apply behavior.

## Priority Backlog (Hardware-Free First)
- [x] Add comms failure-mode tests for HELLO/CLEAR/ACK malformed frames.
- [x] Add safe-height routing tests for `move_to_location` edge cases.
- [ ] Add file-corruption resilience tests in `ExperimentModel` (invalid-progress fallback now covered; atomic-write fault injection still missing).
- [ ] Add remaining dialog lock-precedence regression tests (close-event timeout portion now covered).

## Deferred (Needs Hardware / HIL)
- [ ] Validate real UART timing jitter against CLEAR/GOODBYE timeout assumptions.
- [ ] Validate gripper-confirmation flow timing with actual hardware latency.
- [ ] Validate camera trigger/flash edge timing robustness on target Pi + MCU.
