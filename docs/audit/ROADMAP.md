# Audit Remediation Roadmap

## Summary
- Objective: Implement the highest-value missing tests from `docs/audit/TEST_GAPS.md` with hardware-free determinism first.
- Scope: `FreeRTOS-interface/` only (Model / Controller / comms boundary / View).
- Rule: No production behavior changes unless required to enable dependency injection/testability.

## Test Harness Choice
- Framework: `pytest` (chosen over `unittest`).
- Why:
  - Existing suite already uses pytest-style fixtures and passes under `pytest -q`.
  - Easier parametrization for routing/protocol matrices.
  - Better monkeypatch fixture support for serial/ports/timers.
- Qt handling: continue with current `qapp` fixture in `tests/conftest.py` (offscreen Qt).

## FakeComm / Simulation Boundary Design

### Boundary Contract (Host Side)
- Primary seam: `Machine` in `FreeRTOS-interface/Machine_FreeRTOS.py`.
- Existing DI to leverage:
  - `Machine.__init__(..., serial_factory=serial.Serial)`
  - `LogReader(..., serial_factory=serial.Serial)`
- Fake transport objects to add in tests only:
  - `FakeSerialMain` (command/status channel)
    - API: `write`, `flush`, `read`, `read_until`, `reset_input_buffer`, `cancel_read`, `close`, `is_open`
    - Behavior: scripted frame stream + capture outbound writes.
  - `FakeSerialLog` (log channel)
    - API: `read_until`, `cancel_read`, `close`, `is_open`
    - Behavior: scripted text lines for stats/messages.
  - `FakeSerialFactory`
    - Returns fake channel instance based on port arg (`machine port` vs `log port`).

### Simulation Rules
- Frame fixtures should be explicit byte payloads with known CRC and malformed variants.
- No sleeps in tests when avoidable; use timer triggering and direct slot invocation.
- All queue/ACK tests assert both model state and side effects (TX pause, timer state, pending ack keys).

## First 10 Tests To Implement

1. `test_move_to_location_enforces_safe_z_when_below_threshold`
- Area: Controller
- Asserts:
  - `Controller.move_to_location` queues `set_absolute_Z(safe_z)` before XY/Z target move when current/target Z below safe threshold.
- Mocks/Fakes:
  - Fake `model.location_model`, fake `machine_model`, spy methods on controller (`set_absolute_Z`, `set_absolute_coordinates`).

2. `test_clear_queue_timeout_keeps_tx_blocked_until_clear_status`
- Area: comms boundary
- Asserts:
  - After CLEAR timeout, TX remains paused until a status frame proves clear (`cmd_depth=0,current=0,last=0`).
- Mocks/Fakes:
  - `FakeSerialMain` scripted no `CLEAR_ACK`, then status frame; fake timers/monotonic.

3. `test_connect_board_retry_does_not_leak_reader_or_serial`
- Area: comms boundary
- Asserts:
  - HELLO timeout retries do not accumulate multiple readers/open handles.
- Mocks/Fakes:
  - `FakeSerialFactory` returning non-ACKing serial; spy on reader lifecycle (`begin_reader_thread`/`stop_reader_thread`).

4. `test_serial_reader_ignores_malformed_ack_and_continues`
- Area: comms boundary
- Asserts:
  - Malformed non-status payload does not kill reader loop; later valid status still emitted.
- Mocks/Fakes:
  - `FakeSerialMain.read` scripted: malformed frame then valid status frame.

5. `test_write_frame_with_closed_serial_emits_error_without_crash`
- Area: comms boundary
- Asserts:
  - Sending while serial closed/nonexistent does not raise uncaught exception and triggers controlled error path.
- Mocks/Fakes:
  - `Machine.ser` fake with `is_open=False` or `None`; signal spy on `error_occurred`.

6. `test_load_experiment_randomization_does_not_mutate_global_rng`
- Area: Model
- Asserts:
  - RNG stream outside `load_experiment_from_model` remains unchanged when randomization enabled.
- Mocks/Fakes:
  - `experiment_model_factory` fixture + controlled reactions/wells; compare random sequence before/after.

7. `test_load_progress_skips_unknown_reagent_ids_gracefully`
- Area: Model
- Asserts:
  - `ExperimentModel.load_progress` skips stale reagent keys without exception; known reagents still applied.
- Mocks/Fakes:
  - tmp progress file with one invalid stock id and one valid id; runtime well/reaction context fixture.

8. `test_read_progress_file_handles_invalid_json_with_safe_fallback`
- Area: Model
- Asserts:
  - Invalid JSON in progress input does not crash load path; returns empty/default progress.
- Mocks/Fakes:
  - tmp_path invalid JSON file; direct call to read/return progress helpers.

9. `test_mainwindow_closeevent_has_timeout_if_disconnect_signal_missing`
- Area: View
- Asserts:
  - `MainWindow.closeEvent` exits within bounded time even if disconnect signal never fires.
- Mocks/Fakes:
  - Fake controller/machine that never emits disconnect complete; Qt timer-driven timeout hook.

10. `test_popup_yes_no_callers_do_not_depend_on_button_text_literals`
- Area: View
- Asserts:
  - Pause/reset flow decisions follow button role, not literal string text.
- Mocks/Fakes:
  - Monkeypatch `popup_yes_no`/QMessageBox result role behavior; verify controller method calls.

## Minimal Refactors Needed For Dependency Injection (If Tests Require Them)

1. `FreeRTOS-interface/Machine_FreeRTOS.py`
- Add optional `log_serial_factory` (default to `serial_factory`) so log and main serial can be independently faked in tests.
- Target points:
  - `Machine.__init__` signature
  - `Machine.begin_log_thread` constructor call for `LogReader`

2. `FreeRTOS-interface/Machine_FreeRTOS.py`
- Add guarded send helper return path (non-behavioral except error reporting) to avoid uncaught closed-serial writes in tests.
- Target points:
  - `Machine._write_frame`
  - `Machine.send_command_to_board`

3. `FreeRTOS-interface/View.py`
- Add optional close-wait timeout constant/injection point for `MainWindow.closeEvent` to make deadlock prevention testable deterministically.
- Target points:
  - `MainWindow.closeEvent`
  - optional helper method wrapping disconnect wait loop.

4. `FreeRTOS-interface/Controller.py`
- Extract safe-height decision into a tiny pure helper for deterministic unit testing.
- Target points:
  - `Controller.move_to_location`
  - new private helper function/method (no protocol impact).

## Milestone Rollout (4-6 Batches)

### M1: Comms failure harness
- Status: Done
- Commit: `<commit-hash-placeholder>`
- Deliver tests: #2, #3, #4, #5
- Completed test files:
  - `tests/test_machine_clear_queue_contract.py`
  - `tests/test_machine_connection_retries.py`
  - `tests/test_serial_reader_failures.py`
  - `tests/test_machine_send_path_guards.py`
  - `tests/fakes/fake_serial.py`
- Notes:
  - Added comms failure harness and fake serial transport for deterministic no-hardware tests.
  - Minimal production updates landed in `FreeRTOS-interface/Machine_FreeRTOS.py` for retry teardown, malformed ACK resilience, guarded send path, and CLEAR-state TX gating.

### M2: Controller safety and routing
- Status: Done
- Commit: `<commit-hash-placeholder>`
- Deliver tests: #1
- Completed test files:
  - `tests/test_controller_move_to_location.py`
- Notes:
  - Added parameterized safe-height and routing-order tests for camera/slot/balance transitions.
  - Applied minimal controller-only fix in `FreeRTOS-interface/Controller.py` to enforce safe-Z pre-move under inverted Z-axis convention (higher Z = farther down).

### M3: Model persistence/integrity
- Deliver tests: #6, #7, #8
- Optional refactors: only if required for graceful fallback paths

### M4: View shutdown/dialog robustness
- Deliver tests: #9, #10
- Optional refactor: close-event timeout injection seam

### M5: Stabilization
- Consolidate fixtures/fakes in `tests/fakes/` and enforce deterministic runtime (`pytest -q` clean pass)

## Acceptance Criteria
- `pytest -q` passes with no hardware connected.
- First 10 tests implemented and green.
- Any refactor remains minimal, DI-oriented, and does not alter wire protocol/opcodes.
- New failures point clearly to one subsystem: Model / Controller / comms boundary / View.
