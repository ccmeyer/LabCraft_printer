# Audit Issues

## Scope
- Date: 2026-02-26
- Auditor: Codex (GPT-5)
- Commit/Branch: Working tree audit of `FreeRTOS-interface/` only
- Covered Areas: `App.py`, `Controller.py`, `Model.py`, `Machine_FreeRTOS.py`, `View.py`

## Severity Labels (Normalized)
- `Critical`: unsafe motion/state risk or host/firmware desync likely.
- `High`: likely runtime failure/data corruption under plausible conditions.
- `Medium`: meaningful correctness/robustness gap with operational impact.
- `Low`: cleanup/maintainability issue with lower immediate risk.

## Protocol Assumptions Used
- Frame format assumed: `0xAA + length(1B) + payload + CRC16(LE,2B)`.
- `payload[0]` is command byte; `CMD_STATUS=0x02` payload uses TLV tags from `TAG_MAP`.
- ACK/control payload assumed `[ack_cmd, seq8, TLVs...]`, optional `SEQ32` TLV (`tag=0x10`, `len=4`).
- Threading assumption: Qt main thread owns timers/TX; `SerialReader`/`LogReader` run QThreads and emit Qt signals.
- Timing assumptions used in host: HELLO_ACK 1000 ms, CLEAR_ACK 2000 ms (+ 500 ms post-clear fallback), BYE_DONE 3000 ms.

## Must-Fix Before Further Changes

### AUD-2026-001
- Severity: Critical
- Category: Safety
- Location: `FreeRTOS-interface/Controller.py`, `Controller.move_to_location`, lines 773-775
- Issue: Safe-height check appears inverted (`current_z < safe_z` logs "Already above safe height" and disables safe-height routing).
- Why it matters: Can bypass required Z-clearance and increase collision risk.
- What test would catch it: Unit test asserting `set_absolute_Z(safe_z)` is queued when current or target Z is below safe height.
- Status: Resolved (Milestone 2)
- Resolution Reference:
  - Code: `FreeRTOS-interface/Controller.py`, `Controller.move_to_location` safe-height bypass condition
  - Tests:
    - `tests/test_controller_move_to_location.py::test_move_to_location_enforces_safe_z_when_below_threshold`
    - `tests/test_controller_move_to_location.py::test_move_to_location_balance_route_applies_safe_z_then_safe_y_then_x_then_xyz`

### AUD-2026-002
- Severity: Critical
- Category: Protocol
- Location: `FreeRTOS-interface/Machine_FreeRTOS.py`, `Machine.clear_command_queue` / `_on_clear_ack`, lines 1716-1737
- Issue: CLEAR timeout path clears host queue and unpauses TX without confirmed firmware clear.
- Why it matters: Host/firmware queue divergence; stale commands may execute while UI shows empty queue.
- What test would catch it: Integration-lite test dropping `CLEAR_ACK`; assert TX remains blocked until status proves queue empty.
- Status: Resolved (Milestone 1)
- Resolution Reference:
  - Code: `FreeRTOS-interface/Machine_FreeRTOS.py`, `_on_clear_ack` (TX remains paused until clear-status reconciliation in `update_status`)
  - Test: `tests/test_machine_clear_queue_contract.py::test_clear_queue_timeout_keeps_tx_blocked_until_clear_status`

### AUD-2026-003
- Severity: High
- Category: Resource Management
- Location: `FreeRTOS-interface/Machine_FreeRTOS.py`, `Machine.connect_board` / `_hello_timeout`, lines 1347-1390
- Issue: Retry path recursively reconnects without deterministic teardown between attempts.
- Why it matters: Can leak serial handles/reader threads and destabilize reconnection.
- What test would catch it: Fake-serial HELLO-timeout retry test asserting single active reader and single open handle each attempt.
- Status: Resolved (Milestone 1)
- Resolution Reference:
  - Code: `FreeRTOS-interface/Machine_FreeRTOS.py`, `_teardown_transport_for_retry()` used from `_hello_timeout`
  - Test: `tests/test_machine_connection_retries.py::test_connect_board_retry_does_not_leak_reader_or_serial`

### AUD-2026-004
- Severity: High
- Category: UX/Operational
- Location: `FreeRTOS-interface/View.py`, `MainWindow.closeEvent`, lines 398-405
- Issue: `QEventLoop.exec()` waits indefinitely for disconnect signal (no timeout).
- Why it matters: App shutdown can hang forever.
- What test would catch it: Qt close-event test with mock machine that never emits disconnect; assert bounded return.
- Status: Resolved (Milestone 4)
- Resolution Reference:
  - Code: `FreeRTOS-interface/View.py`, `MainWindow._wait_for_disconnect` + timeout use in `MainWindow.closeEvent`
  - Tests:
    - `tests/test_mainwindow_closeevent.py::test_mainwindow_closeevent_has_timeout_if_disconnect_signal_missing`
    - `tests/test_mainwindow_closeevent.py::test_mainwindow_closeevent_returns_quickly_when_disconnect_signal_arrives`

## High Priority

### AUD-2026-005
- Severity: High
- Category: Protocol
- Location: `FreeRTOS-interface/Machine_FreeRTOS.py`, `SerialReader._parse_ack` and `SerialReader.run`, lines 781-783, 810-819
- Issue: Malformed non-status frame parsing can break reader loop silently.
- Why it matters: Loss of ACK/status processing leads to stalled control.
- What test would catch it: Parser/reader test with empty and truncated ACK payloads; assert reader survives and emits diagnostics.
- Status: Resolved (Milestone 1)
- Resolution Reference:
  - Code: `FreeRTOS-interface/Machine_FreeRTOS.py`, `_parse_ack` and `SerialReader.run` malformed-frame guards
  - Test: `tests/test_serial_reader_failures.py::test_serial_reader_ignores_malformed_ack_and_continues`

### AUD-2026-006
- Severity: High
- Category: Data Integrity
- Location: `FreeRTOS-interface/Model.py`, `ExperimentModel.save_experiment` / `create_progress_file`, lines 2406-2407, 2452-2476
- Issue: JSON writes are non-atomic.
- Why it matters: Interrupted writes can corrupt design/progress artifacts.
- What test would catch it: Fault-injection persistence test asserting never-partial JSON after interrupted write.

### AUD-2026-007
- Severity: High
- Category: Error Handling
- Location: `FreeRTOS-interface/Model.py`, `ExperimentModel.load_progress` + progress read helpers, lines 2984-2995, 3014-3017
- Issue: Missing reagent IDs and malformed JSON are not handled robustly.
- Why it matters: Reload flow can crash on stale/corrupt progress files.
- What test would catch it: Unit tests for invalid JSON and unknown stock IDs; expect graceful skip/fallback.
- Status: Resolved (Milestone 3)
- Resolution Reference:
  - Code: `FreeRTOS-interface/Model.py`, `read_progress_file`, `return_progress_data`, `load_progress`
  - Tests:
    - `tests/test_experiment_progress_io_resilience.py::test_read_progress_file_handles_invalid_json_with_safe_fallback`
    - `tests/test_experiment_progress_io_resilience.py::test_return_progress_data_handles_missing_file_with_safe_fallback`
    - `tests/test_experiment_update_well_plate.py::test_load_progress_skips_unknown_reagent_ids_gracefully`

### AUD-2026-008
- Severity: High
- Category: Correctness
- Location: `FreeRTOS-interface/Model.py`, `Model.load_experiment_from_model`, lines 5522-5526
- Issue: Uses global `random.seed()`/`random.shuffle()`.
- Why it matters: Mutates global RNG state and leaks nondeterminism into unrelated flows/tests.
- What test would catch it: Unit test asserting external RNG sequence unchanged before/after assignment randomization.
- Status: Resolved (Milestone 3)
- Resolution Reference:
  - Code: `FreeRTOS-interface/Model.py`, `load_experiment_from_model` now uses local RNG instance for shuffle
  - Test: `tests/test_experiment_assignment_auto.py::test_load_experiment_randomization_does_not_mutate_global_rng`

### AUD-2026-009
- Severity: High
- Category: Error Handling
- Location: `FreeRTOS-interface/Machine_FreeRTOS.py`, `Machine._write_frame`, lines 1626-1629
- Issue: Write path lacks explicit serial-open guards.
- Why it matters: Disconnect races can throw during timer-driven send and lose queue state.
- What test would catch it: Closed-serial send test asserting controlled error path and TX pause.
- Status: Resolved (Milestone 1)
- Resolution Reference:
  - Code: `FreeRTOS-interface/Machine_FreeRTOS.py`, `_write_frame` open-state guard + `send_command_to_board` controlled error handling
  - Test: `tests/test_machine_send_path_guards.py::test_write_frame_with_closed_serial_emits_error_without_crash`

### AUD-2026-010
- Severity: High
- Category: Data Integrity
- Location: `FreeRTOS-interface/Model.py`, `WellPlate.clear_all_wells`, lines 3787-3791
- Issue: Likely typo (`exclude_wells` vs `excluded_wells`) leaves exclusion state inconsistent.
- Why it matters: Incorrect well assignment eligibility after clear/reset.
- What test would catch it: Exclude-wells reset test verifying exclusion state is actually cleared.

## Medium

### AUD-2026-011
- Severity: Medium
- Category: Configuration
- Location: `FreeRTOS-interface/App.py`, `load_settings`, lines 44-46
- Issue: Startup settings load has no exception handling.
- Why it matters: Missing/corrupt settings cause hard startup failure.
- What test would catch it: Unit test for missing/invalid settings with deterministic fallback/error path.

### AUD-2026-012
- Severity: Medium
- Category: Correctness
- Location: `FreeRTOS-interface/Controller.py`, `Controller._classify_port`, line 219
- Issue: Lowercased description is checked against mixed-case token `"Prolific"`.
- Why it matters: Port classification misses expected balance devices.
- What test would catch it: Port classification parameterized test including prolific/stm/balance variants.

### AUD-2026-013
- Severity: Medium
- Category: Resource Management
- Location: `FreeRTOS-interface/Controller.py`, `disconnect_droplet_camera_signals`, lines 141-146
- Issue: Broad `disconnect()` calls can remove unrelated subscribers.
- Why it matters: Can break other camera/calibration listeners.
- What test would catch it: Multi-subscriber signal test ensuring only controller handlers are disconnected.

### AUD-2026-014
- Severity: Medium
- Category: Timing
- Location: `FreeRTOS-interface/Machine_FreeRTOS.py`, `Machine._on_goodbye_done`, line 1482
- Issue: Blocking `time.sleep(0.05)` in Qt-owned machine path.
- Why it matters: Event-loop stalls and timing nondeterminism.
- What test would catch it: Qt responsiveness test around disconnect flow latency.

### AUD-2026-015
- Severity: Medium
- Category: Protocol
- Location: `FreeRTOS-interface/Machine_FreeRTOS.py`, `parse_tlv_payload` and `Command.__init__`, lines 744-758, 1051
- Issue: Silent TLV parse drops and no payload-length guard (`len<=255`) for frame envelope.
- Why it matters: Protocol drift/expansion can fail silently or produce invalid frames.
- What test would catch it: Contract tests for malformed TLVs and oversized payload rejection.

## Low / Cleanup

### AUD-2026-016
- Severity: Low
- Category: Maintainability
- Location: `FreeRTOS-interface/Controller.py`, duplicate `check_if_all_completed`, lines 751-753 and 1006-1008
- Issue: Duplicate method definition in same class.
- Why it matters: Refactor risk and ambiguity.
- What test would catch it: AST-based static test preventing duplicate method names in critical classes.

### AUD-2026-017
- Severity: Low
- Category: UX/Operational
- Location: `FreeRTOS-interface/View.py`, `popup_yes_no` usage, lines 301-303 + callers
- Issue: Branching compares literal button text (`"&Yes"`, `"&No"`).
- Why it matters: Locale/theme text changes can break logic.
- What test would catch it: Qt test asserting decision logic by button role, not display text.
- Status: Resolved (Milestone 4)
- Resolution Reference:
  - Code: `FreeRTOS-interface/View.py`, role-based `popup_yes_no` return and `_is_yes_response`/`_is_no_response` caller checks
  - Tests:
    - `tests/test_view_popup_yes_no_roles.py::test_popup_yes_no_callers_do_not_depend_on_button_text_literals`
    - `tests/test_view_popup_yes_no_roles.py::test_popup_yes_no_no_response_preserves_negative_paths`

### AUD-2026-018
- Severity: Low
- Category: Correctness
- Location: `FreeRTOS-interface/Model.py`, `ExperimentModel.reset_experiment_model`, lines 3077-3085
- Issue: Reset hardcodes fill droplet volume to 10.0 regardless of profile.
- Why it matters: Legacy profile defaults can silently drift after reset.
- What test would catch it: Legacy-profile reset test asserting expected fill droplet default.

### AUD-2026-019
- Severity: Medium
- Category: Protocol
- Location: `FreeRTOS-interface/Machine_FreeRTOS.py`, `Machine._on_any_ack`
- Issue: ACK matching supports seq32 and seq8 fallback but lacks explicit regression coverage for mixed/partial ACK payload variants.
- Why it matters: Pending-ACK cleanup can regress silently if firmware ACK payload composition changes.
- What test would catch it: Parameterized ACK-matching unit test for seq32 present, seq32 missing, seq8 mismatch, and duplicate ACK cases.

### AUD-2026-020
- Severity: Low
- Category: Maintainability
- Location: `FreeRTOS-interface/Controller.py`, `Controller.move_to_location`
- Issue: Z-axis sign convention (higher Z means farther down) is implicit and easy to misread in safety logic.
- Why it matters: Future edits can accidentally reintroduce inverted safe-height logic.
- What test would catch it: Explicit convention test for both `current` and `legacy` profiles plus inline doc/comment assertion in review checklist.
