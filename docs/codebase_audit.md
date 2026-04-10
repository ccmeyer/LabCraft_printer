# Codebase Audit

Date: 2026-03-20

Scope:
- Repository-wide static audit of Python app, calibration/tooling, host comms, and firmware sources.
- No application or firmware code was modified.
- No runtime tests, builds, or HIL flows were executed for this audit; findings are based on source, docs, and existing tests.

Method:
- Traced the primary control path from UI -> Controller -> Model -> host comms -> firmware orchestrator.
- Reviewed core sources in `FreeRTOS-interface/`, `firmware/Core/`, `tools/`, and `tests/`.
- Cross-checked protocol/status contracts against existing parity tests and firmware headers.

Backlog size:
- 17 ranked findings
- 1 critical
- 8 high
- 8 medium

## Subsystem Map

| Subsystem | Primary files | Notes |
|---|---|---|
| App bootstrap | `FreeRTOS-interface/App.py` | Creates `Model`, `Machine`, `Controller`, `View`, and selects hardware profile. |
| UI / view layer | `FreeRTOS-interface/View.py`, `FreeRTOS-interface/CalibrationClasses/View.py` | Qt widgets, dialogs, pressure/camera controls, experiment designer surfaces. |
| Control orchestration | `FreeRTOS-interface/Controller.py` | Main UI -> machine orchestration, routing, print-array flow, calibration actions, DFU/reset handling. |
| Domain/state model | `FreeRTOS-interface/Model.py` | Machine state, locations, racks, experiment model, persistence, calibration/session state. |
| Host comms + cameras | `FreeRTOS-interface/Machine_FreeRTOS.py` | Command framing, serial reader, ACK tracking, queueing, Pi camera/flash integration. |
| Calibration memory/data | `FreeRTOS-interface/CalibrationMemoryStore.py`, `FreeRTOS-interface/CalibrationMemoryAggregator.py`, `FreeRTOS-interface/CalibrationIdentity.py` | Atomic JSONL/JSON storage, priors, aggregation, reagent/head identity. |
| Legacy calibration | `FreeRTOS-interface/legacy/mass_calibration.py` | Legacy balance-driven calibration UI/processes; still wired in `legacy` profile. |
| Tools / HIL support | `tools/run_selftest.py`, `tools/replay_calibration_run.py`, export/plot tools | Host-side self-test runner, replay/export/analysis scripts. |
| Firmware protocol + session | `firmware/Core/Src/Comm.cpp`, `firmware/Core/Src/CommCodec.cpp`, `firmware/Core/Inc/Comm.h` | UART framing, TLV decode, ACK/status emission, session control. |
| Firmware command execution | `firmware/Core/Src/Orchestrator.cpp`, `firmware/Core/Inc/Orchestrator.h` | Command queue, executeCommand switch, SAFE/FULL self-test dispatch. |
| Firmware motion / pressure / print | `firmware/Core/Src/Stepper.cpp`, `Gantry.cpp`, `PressureRegulator.cpp`, `PressureSensor.cpp`, `Printer.cpp`, `Gripper.cpp` | Hardware-facing execution for motion, regulation, pulse generation, gripper timing. |

## Test Coverage Map By Subsystem

| Subsystem | Coverage | Evidence | Main gaps |
|---|---|---|---|
| Experiment design / plate assignment / persistence | High | Large pytest surface: `test_experiment_*`, `test_wellplate_*`, `test_progress_*`, `test_model_atomic_writes.py` | Few correctness gaps found; main risk is interaction with controller print flow. |
| Calibration memory / export / prior application | High | `test_calibration_memory_*`, `test_calibration_prior_application.py`, `test_process_recorder.py`, `test_prebreakup_dataset_export_tool.py` | Good data-path coverage; less end-to-end wiring coverage back into print/calibration execution. |
| Calibration processes / CV / replay tools | High | `test_calibration_*`, `test_replay_*`, `test_pressure_*`, `test_pull_pi_calibration_records_tool.py` | Strong algorithm/tool coverage, but weaker coverage at the controller/hardware boundary. |
| Controller routing / guards | Medium | `test_controller_*` | Missing branch coverage around zero-work arrays, cleanup ordering, stale expected-location invalidation, and enqueue-failure propagation. |
| Host comms / protocol boundary | Medium | `test_protocol_*`, `test_machine_*`, `test_serial_reader*`, `test_status_tlv_map.py` | Shared opcode parity is only partially checked; no regression for gripper params, gripper refresh tag, or fast-ACK race windows. |
| View/UI misc | Low-Medium | `test_view_popup_yes_no_roles.py`, `test_mainwindow_closeevent.py`, `test_app_settings_fallback.py` | Thin direct coverage for calibration print UI wiring and pressure defaults. |
| Firmware pure logic / codecs | Medium | `firmware/tests_host/CMakeLists.txt` includes `CommCodec.cpp`, `OrchestratorDecode.cpp`, `nvm_codec.c`, pressure/stepper/crashlog math tests | Runtime `Comm.cpp` status serialization and `Orchestrator.cpp` executeCommand side effects are not directly host-tested. |
| Firmware runtime / HIL | Medium | SAFE/FULL backlog documented in `firmware/docs/audit/TEST_PLAN.md`; host-side selftest tooling has good pytest coverage | No source-level proof here that gripper param/status parity or runtime status tags are asserted end-to-end. |

## Top 10 Priority Fixes

1. Fix `SET_GRIPPER_PARAMS` opcode parity (`AUD-001`).
2. Remove or correctly implement `RESET_ACCEL` / `CHANGE_ACCEL`, then harden the refill path (`AUD-002`).
3. Invalidate machine positions/targets after board reset before any route planning resumes (`AUD-006`).
4. Stop mutating controller expected position/location unless the move command was actually accepted (`AUD-004`).
5. Clear `expected_location` after arbitrary jog/absolute moves so routing logic cannot trust stale named positions (`AUD-005`).
6. Register ACK waits before sending HELLO/CLEAR/GOODBYE frames, or buffer early ACKs (`AUD-003`).
7. Move array/refill completion side effects onto the final cleanup command rather than firing before cleanup executes (`AUD-007`).
8. Make `print_array()` handle the zero-work case deterministically (`AUD-008`).
9. Enforce droplet-count limits in `Machine.print_*` methods instead of only logging them (`AUD-009`).
10. Repair the calibration print API so requested pulse width/pressure are actually honored end-to-end (`AUD-010`).

## Top 10 Highest-Value Missing Tests

1. Full opcode parity test between `Machine_FreeRTOS.CMD_MAP` and `firmware/Core/Inc/Orchestrator.h`, including gripper, flash, and pressure commands.
2. Controller test proving failed `machine.set_absolute_*` calls do not mutate `expected_position` or `expected_location`.
3. Controller test proving a relative/absolute jog clears named-location assumptions before the next `move_to_location()`.
4. Reset-recovery test using a real `MachineModel` to assert positions/targets are invalidated, not preserved.
5. Print-array test for the zero-work branch where the active stock has no remaining droplets.
6. Print-array test asserting `array_complete` fires only after pause/profile cleanup commands complete.
7. Machine command test asserting invalid droplet counts do not enqueue `DISPENSE`, `DISPENSE_PRINT`, or `DISPENSE_REFUEL`.
8. Calibration print test asserting explicit `pulse_width` and `pressure` requests queue the right setup commands before dispense.
9. Status-tag regression for `TAG_GRIP_REFRESH` -> `MachineModel.gripper_refresh_period`.
10. Fake-serial ACK-race test where ACK arrives during `_write_frame` and still satisfies the wait.

## Findings

### AUD-001: `SET_GRIPPER_PARAMS` host opcode does not match firmware
- ID: `AUD-001`
- Title: `SET_GRIPPER_PARAMS` never reaches the firmware handler
- Subsystem: Host comms / firmware protocol boundary
- Files/functions involved:
  - `FreeRTOS-interface/Machine_FreeRTOS.py` `CMD_MAP`
  - `FreeRTOS-interface/Machine_FreeRTOS.py` `Machine.set_gripper_params()`
  - `firmware/Core/Inc/Orchestrator.h` `CMD_SET_GRIPPER_PARAMS`
  - `firmware/Core/Src/Orchestrator.cpp` `executeCommand()`
  - `tests/test_protocol_contract_firmware_boundary.py`
- Category: Protocol mismatch / silent failure
- Severity: High
- Confidence: High
- Evidence:
  - Host maps `SET_GRIPPER_PARAMS` to `0x70` at `FreeRTOS-interface/Machine_FreeRTOS.py:852`.
  - Firmware defines `CMD_SET_GRIPPER_PARAMS = 0x62` at `firmware/Core/Inc/Orchestrator.h:84`.
  - Firmware implements the handler at `firmware/Core/Src/Orchestrator.cpp:859-865`.
  - Existing parity test only checks a subset of shared opcodes and omits this one at `tests/test_protocol_contract_firmware_boundary.py:13-39`.
- User-visible risk or engineering risk:
  - Gripper timing updates can be silently ignored, leaving host expectations and live gripper timing out of sync.
- Suggested fix:
  - Change the host opcode to `0x62` and add a single source-of-truth parity test for all exposed opcodes.
- Suggested test:
  - Extend `tests/test_protocol_contract_firmware_boundary.py` with `SET_GRIPPER_PARAMS`, then assert a queued command uses the firmware value.
- Estimated effort: Small

### AUD-002: Refill handling still calls dead acceleration commands
- ID: `AUD-002`
- Title: Mid-array refill path can raise because it calls unsupported acceleration commands
- Subsystem: Controller print orchestration / host protocol
- Files/functions involved:
  - `FreeRTOS-interface/Controller.py` `refill_printer_head_handler()`
  - `FreeRTOS-interface/Machine_FreeRTOS.py` `reset_acceleration()`
  - `FreeRTOS-interface/Machine_FreeRTOS.py` `change_acceleration()`
  - `FreeRTOS-interface/Machine_FreeRTOS.py` `CMD_MAP`
- Category: Unsupported command path / runtime exception
- Severity: High
- Confidence: High
- Evidence:
  - Refill handler calls `self.machine.reset_acceleration()` at `FreeRTOS-interface/Controller.py:1064-1070`.
  - `reset_acceleration()` queues `RESET_ACCEL`, but `RESET_ACCEL` is not present in `CMD_MAP`; `Command` resolves opcodes via `CMD_MAP[command_type]` at `FreeRTOS-interface/Machine_FreeRTOS.py:1374-1378`.
  - `change_acceleration()` queues `CHANGE_ACCEL` at `FreeRTOS-interface/Machine_FreeRTOS.py:2247-2249`, but host maps it to `0x51` at `FreeRTOS-interface/Machine_FreeRTOS.py:847`, and firmware has no corresponding command enum or `executeCommand` case.
- User-visible risk or engineering risk:
  - A low-volume refill event can abort the callback path with an exception, skipping pause cleanup and leaving progress/state updates incomplete.
- Suggested fix:
  - Remove the dead API, or re-map it to a supported command path before the refill handler uses it.
- Suggested test:
  - Force the `expected_volume < 10` branch in `Controller.print_array()` and assert the refill callback completes without exception and queues only supported cleanup commands.
- Estimated effort: Small to medium

### AUD-003: ACK wait registration is racy for HELLO, CLEAR, and GOODBYE
- ID: `AUD-003`
- Title: Control-frame ACKs can be dropped as stray if they arrive before the wait is registered
- Subsystem: Host comms / session management
- Files/functions involved:
  - `FreeRTOS-interface/Machine_FreeRTOS.py` `_send_hello()`
  - `FreeRTOS-interface/Machine_FreeRTOS.py` `clear_command_queue()`
  - `FreeRTOS-interface/Machine_FreeRTOS.py` `disconnect_board()`
  - `FreeRTOS-interface/Machine_FreeRTOS.py` `_on_any_ack()`
- Category: Race condition / session reliability
- Severity: High
- Confidence: Medium-High
- Evidence:
  - `_send_hello()` writes the frame before calling `_start_ack_wait()` at `FreeRTOS-interface/Machine_FreeRTOS.py:1724-1731`.
  - `clear_command_queue()` does the same for `CLEAR_ACK` at `FreeRTOS-interface/Machine_FreeRTOS.py:2155-2163`.
  - `disconnect_board()` does the same for `BYE_ACK` at `FreeRTOS-interface/Machine_FreeRTOS.py:1879-1889`.
  - `_on_any_ack()` discards unmatched ACKs as stray at `FreeRTOS-interface/Machine_FreeRTOS.py:1690-1707`.
- User-visible risk or engineering risk:
  - Fast or in-process ACK delivery can create intermittent false timeouts, stray reconnects, or unnecessary session recovery.
- Suggested fix:
  - Register the pending ACK waiter before writing the frame, or retain unmatched control ACKs briefly so an immediately-following waiter can consume them.
- Suggested test:
  - Use a fake serial path that injects an ACK during `_write_frame()` and assert HELLO/CLEAR/GOODBYE still complete normally.
- Estimated effort: Medium

### AUD-004: Controller mutates expected coordinates even when a move was rejected
- ID: `AUD-004`
- Title: Optimistic expected-position updates can desynchronize the controller from the real machine
- Subsystem: Controller routing / movement orchestration
- Files/functions involved:
  - `FreeRTOS-interface/Controller.py` `set_relative_X/Y/Z()`
  - `FreeRTOS-interface/Controller.py` `set_absolute_X/Y/Z()/set_absolute_XY()/set_absolute_coordinates()`
  - `FreeRTOS-interface/Machine_FreeRTOS.py` `set_absolute_*()/set_relative_*()`
- Category: Stale UI/model synchronization
- Severity: High
- Confidence: High
- Evidence:
  - Controller mutates `expected_position` unconditionally after calling machine methods at `FreeRTOS-interface/Controller.py:389-390`, `400-401`, `411-412`, `422-423`, `433-445`, `455-456`, and `600-601`.
  - Machine move methods can return `False` on local validation failure, for example `set_absolute_XY()` at `FreeRTOS-interface/Machine_FreeRTOS.py:2272-2280`, `set_absolute_Z()` at `FreeRTOS-interface/Machine_FreeRTOS.py:2326-2333`, and the same pattern across other axis helpers.
  - `set_absolute_coordinates()` never checks the return value of `self.machine.set_absolute_XY()` or `self.machine.set_absolute_Z()` before updating controller state at `FreeRTOS-interface/Controller.py:580-601`.
- User-visible risk or engineering risk:
  - Collision checks, route planning, and UI expectations can advance to a position the machine never accepted, amplifying later motion errors.
- Suggested fix:
  - Treat machine move helper return values as authoritative; only mutate `expected_position` after successful enqueue.
- Suggested test:
  - Mock `machine.set_absolute_Z()` and `machine.set_absolute_XY()` to return `False` and assert `Controller.set_absolute_coordinates()` returns `False` without mutating expected state.
- Estimated effort: Medium

### AUD-005: Named-location routing stays stale after arbitrary jogs
- ID: `AUD-005`
- Title: `expected_location` is not invalidated by non-location moves, so later routing can trust the wrong origin
- Subsystem: Controller route planning
- Files/functions involved:
  - `FreeRTOS-interface/Controller.py` `set_relative_X/Y/Z()`
  - `FreeRTOS-interface/Controller.py` `set_absolute_X/Y/Z()/set_absolute_XY()`
  - `FreeRTOS-interface/Controller.py` `move_to_location()`
  - `FreeRTOS-interface/Model.py` `MachineModel.update_current_location()`
- Category: Routing-state inconsistency
- Severity: High
- Confidence: High
- Evidence:
  - Jog/absolute move helpers update coordinates but never clear `expected_location` at `FreeRTOS-interface/Controller.py:382-457`.
  - `move_to_location()` chooses slot/camera/balance safety routing from `expected_location` at `FreeRTOS-interface/Controller.py:782-829`.
  - Named location state only changes when `LocationModel.current_location_updated` fires into `MachineModel.update_current_location()` at `FreeRTOS-interface/Model.py:6385-6386` and `FreeRTOS-interface/Model.py:6442`, not when arbitrary moves are sent.
- User-visible risk or engineering risk:
  - After a manual jog away from a slot/camera/balance position, the next routed move can apply the wrong safety path assumptions.
- Suggested fix:
  - Clear `expected_location` whenever a non-`move_to_location()` move is accepted; only restore it when a named-location move fully completes.
- Suggested test:
  - Start from `"slot-1"`, perform a relative move, then call `move_to_location("plate")` and assert slot-specific routing is not reused from stale state.
- Estimated effort: Small to medium

### AUD-006: Reset recovery preserves stale axis state after the board has rebooted
- ID: `AUD-006`
- Title: Board resets clear homing state but keep old coordinates, which the controller immediately reuses
- Subsystem: Reset recovery / machine-state model
- Files/functions involved:
  - `FreeRTOS-interface/Machine_FreeRTOS.py` `_on_reset_report()`
  - `FreeRTOS-interface/Model.py` `MachineModel.recover_after_board_reset()`
  - `FreeRTOS-interface/Controller.py` `handle_reset_report()`
- Category: Invalid machine state after reset
- Severity: Critical
- Confidence: High
- Evidence:
  - Reset handling starts recovery but emits the reset report immediately at `FreeRTOS-interface/Machine_FreeRTOS.py:1928-1932`.
  - `MachineModel.recover_after_board_reset()` clears connectivity, home, and command flags, but does not reset `current_x/current_y/current_z/current_p/current_r` or targets at `FreeRTOS-interface/Model.py:6082-6096`.
  - `Controller.handle_reset_report()` then copies `expected_position = self.model.machine_model.get_current_position_dict()` at `FreeRTOS-interface/Controller.py:289-292`.
- User-visible risk or engineering risk:
  - After a watchdog/power reset, subsequent planning can still assume the pre-reset physical coordinates are real, which is unsafe until the system is re-homed.
- Suggested fix:
  - Invalidate or zero current/target positions during reset recovery and gate routed motion on an explicit re-home.
- Suggested test:
  - Seed nonzero axis values, simulate a reset report through the real `MachineModel`, and assert positions/targets plus controller expected state are cleared before recovery proceeds.
- Estimated effort: Medium

### AUD-007: Array/refill completion side effects run before cleanup motion completes
- ID: `AUD-007`
- Title: Print completion is declared before the queued pause/profile cleanup actually finishes
- Subsystem: Controller print orchestration
- Files/functions involved:
  - `FreeRTOS-interface/Controller.py` `last_well_complete_handler()`
  - `FreeRTOS-interface/Controller.py` `refill_printer_head_handler()`
  - `FreeRTOS-interface/View.py` `array_complete` consumer wiring
  - `tests/test_controller_print_guards.py`
- Category: Sequencing error / stale UI unlock
- Severity: High
- Confidence: High
- Evidence:
  - `last_well_complete_handler()` queues `disable_print_profile()` and two `move_to_location()` calls, then records progress and emits `array_complete` in the same callback at `FreeRTOS-interface/Controller.py:1039-1052`.
  - `refill_printer_head_handler()` follows the same pattern at `FreeRTOS-interface/Controller.py:1062-1073`.
  - The current test only asserts that those side effects happen, not that they happen after cleanup finishes, at `tests/test_controller_print_guards.py:53-92`.
- User-visible risk or engineering risk:
  - The UI can refresh slots and treat the print as complete while the machine is still moving to pause or exiting print profile.
- Suggested fix:
  - Make the last cleanup command carry the completion handler, so `array_complete` and progress persistence happen only after cleanup finishes.
- Suggested test:
  - Assert `array_complete` is emitted only after the final cleanup command handler runs, not merely after cleanup commands are enqueued.
- Estimated effort: Medium

### AUD-008: `print_array()` has no deterministic zero-work path
- ID: `AUD-008`
- Title: Empty per-stock arrays still enter print mode and never signal completion
- Subsystem: Controller print orchestration
- Files/functions involved:
  - `FreeRTOS-interface/Controller.py` `print_array()`
- Category: Control-flow gap
- Severity: High
- Confidence: High
- Evidence:
  - `print_array()` always queues close-gripper / pause / print-profile setup at `FreeRTOS-interface/Controller.py:1118-1125`.
  - `wells_with_droplets` is calculated later at `FreeRTOS-interface/Controller.py:1144-1146`.
  - If that list is empty, the loop at `FreeRTOS-interface/Controller.py:1146-1165` never installs a terminal handler or cleanup path.
- User-visible risk or engineering risk:
  - Operators can end up with print profile enabled and no completion/update signal even though nothing needed to be printed.
- Suggested fix:
  - Short-circuit when `wells_with_droplets` is empty, before entering print mode, or run a dedicated no-op completion path.
- Suggested test:
  - Build a plate where the active stock has zero remaining droplets everywhere and assert no print-profile state is left behind.
- Estimated effort: Small

### AUD-009: Invalid droplet counts are still queued after validation fails
- ID: `AUD-009`
- Title: Print count guards only log errors; they do not prevent invalid dispense commands
- Subsystem: Host command validation
- Files/functions involved:
  - `FreeRTOS-interface/Machine_FreeRTOS.py` `print_droplets()`
  - `FreeRTOS-interface/Machine_FreeRTOS.py` `print_only()`
  - `FreeRTOS-interface/Machine_FreeRTOS.py` `refuel_only()`
  - `FreeRTOS-interface/Machine_FreeRTOS.py` `print_calibration_droplets()`
  - `FreeRTOS-interface/Machine_FreeRTOS.py` `check_param_limits()`
- Category: Validation gap
- Severity: High
- Confidence: High
- Evidence:
  - `print_droplets()` calls `check_param_limits()` and still unconditionally queues `DISPENSE` at `FreeRTOS-interface/Machine_FreeRTOS.py:2452-2454`.
  - `print_only()` and `refuel_only()` do the same at `FreeRTOS-interface/Machine_FreeRTOS.py:2541-2547`.
  - `print_calibration_droplets()` repeats the pattern at `FreeRTOS-interface/Machine_FreeRTOS.py:2565-2572`.
- User-visible risk or engineering risk:
  - Out-of-range droplet requests can still reach firmware and distort prints or calibration runs even after the host logged an error.
- Suggested fix:
  - Return `False` immediately when `check_param_limits()` fails, and avoid queue mutation.
- Suggested test:
  - Call each API with `0` and `1001` droplets and assert no command enters the queue.
- Estimated effort: Small

### AUD-010: Calibration print overrides are not honored end-to-end
- ID: `AUD-010`
- Title: Calibration print API drift can silently ignore requested pressure/pulse width
- Subsystem: Calibration execution path
- Files/functions involved:
  - `FreeRTOS-interface/View.py` `print_calibration_droplets()`
  - `FreeRTOS-interface/Controller.py` `print_calibration_droplets()`
  - `FreeRTOS-interface/Machine_FreeRTOS.py` `print_calibration_droplets()`
  - `FreeRTOS-interface/legacy/mass_calibration.py` `initiate_calibration_print()`
- Category: Calibration correctness / API mismatch
- Severity: High
- Confidence: High
- Evidence:
  - The view passes `self.target_pressure` as the second positional argument at `FreeRTOS-interface/View.py:1350-1357`, but the controller signature is `(droplets, manual=False, pressure=None, pulse_width=None)` at `FreeRTOS-interface/Controller.py:1021-1024`.
  - The machine method accepts `pressure` and `pulse_width` but never uses them at `FreeRTOS-interface/Machine_FreeRTOS.py:2565-2572`.
  - Legacy mass calibration explicitly relies on `pulse_width=...` at `FreeRTOS-interface/legacy/mass_calibration.py:1184-1188`.
- User-visible risk or engineering risk:
  - Calibration sweeps can run with stale machine settings instead of the requested pulse width/pressure, invalidating results without an obvious failure.
- Suggested fix:
  - Make pressure/pulse-width inputs keyword-only and explicitly queue the corresponding setup commands before the dispense.
- Suggested test:
  - Assert that a calibration print request with a nondefault `pulse_width` and `pressure` queues setup commands before the dispense command.
- Estimated effort: Medium

### AUD-011: Gripper refresh telemetry is never applied to the model
- ID: `AUD-011`
- Title: Status parser/model use different field names for gripper refresh timing
- Subsystem: Status telemetry / model synchronization
- Files/functions involved:
  - `FreeRTOS-interface/Machine_FreeRTOS.py` `TAG_MAP`
  - `FreeRTOS-interface/Model.py` `update_state()`
- Category: Tag-name mismatch
- Severity: Medium
- Confidence: High
- Evidence:
  - Status parsing maps `TAG_GRIP_REFRESH` to `Grip_refresh` at `FreeRTOS-interface/Machine_FreeRTOS.py:798-799`.
  - `Model.update_state()` only looks for `Grip_period` at `FreeRTOS-interface/Model.py:6982-6985`.
  - Firmware emits `TAG_GRIP_REFRESH` in status chunk 1 at `firmware/Core/Src/Comm.cpp:544-545`.
- User-visible risk or engineering risk:
  - The host model can hold an out-of-date gripper refresh period after profile or gripper-timing changes.
- Suggested fix:
  - Standardize on one field name across parser, model, and tests.
- Suggested test:
  - Feed a parsed status dict containing `TAG_GRIP_REFRESH` through `Model.update_state()` and assert `MachineModel.gripper_refresh_period` changes.
- Estimated effort: Small

### AUD-012: CP210-based MCU ports can still evade MCU classification
- ID: `AUD-012`
- Title: Port classification lowercases the description but matches uppercase `CP210`
- Subsystem: Serial-port discovery
- Files/functions involved:
  - `FreeRTOS-interface/Controller.py` `_classify_port()`
  - `tests/test_controller_port_classification.py`
- Category: Heuristic bug
- Severity: Medium
- Confidence: High
- Evidence:
  - `_classify_port()` lowercases `desc` at `FreeRTOS-interface/Controller.py:222`.
  - The MCU heuristic checks `"CP210" in desc` at `FreeRTOS-interface/Controller.py:225-227`, which can never match a lowercased CP210x description.
  - Existing tests cover lowercase balance/manufacturer cases, but not CP210-class bridges at `tests/test_controller_port_classification.py:60-73`.
- User-visible risk or engineering risk:
  - Wrong-port guards are less reliable on CP210x-based controller boards, increasing the chance of confusing the balance and MCU ports.
- Suggested fix:
  - Match against `"cp210"` and add a dedicated regression test.
- Suggested test:
  - Assert `description="Silicon Labs CP210x USB to UART Bridge"` is classified as `"mcu"`.
- Estimated effort: Small

### AUD-013: Opcode parity tests do not cover the full user-exposed command surface
- ID: `AUD-013`
- Title: Partial contract tests allowed a real host/firmware opcode drift to ship
- Subsystem: Test coverage / protocol boundary
- Files/functions involved:
  - `tests/test_protocol_contract_firmware_boundary.py`
  - `FreeRTOS-interface/Machine_FreeRTOS.py` `CMD_MAP`
  - `firmware/Core/Inc/Orchestrator.h`
- Category: Missing coverage
- Severity: Medium
- Confidence: High
- Evidence:
  - The contract test only asserts a subset of commands at `tests/test_protocol_contract_firmware_boundary.py:13-39`.
  - The same file omits `SET_GRIPPER_PARAMS`, flash-control opcodes, and the pressure/regulator control family.
  - `AUD-001` demonstrates that this gap already permitted protocol drift.
- User-visible risk or engineering risk:
  - Future host/firmware contract drift can compile cleanly and fail only on hardware.
- Suggested fix:
  - Expand the explicit matrix to all user-exposed commands or generate parity assertions from one shared manifest.
- Suggested test:
  - A single test that iterates all expected host opcodes and compares them to the matching firmware enums.
- Estimated effort: Medium

### AUD-014: Firmware host tests still stop short of runtime `Comm.cpp`/`Orchestrator.cpp` behavior
- ID: `AUD-014`
- Title: Runtime status serialization and command execution remain lightly protected compared with codec/math layers
- Subsystem: Firmware test coverage
- Files/functions involved:
  - `firmware/tests_host/CMakeLists.txt`
  - `firmware/Core/Src/Comm.cpp`
  - `firmware/Core/Src/Orchestrator.cpp`
- Category: Missing coverage
- Severity: Medium
- Confidence: High
- Evidence:
  - Host tests compile `CommCodec.cpp`, `OrchestratorDecode.cpp`, and pure math/codecs at `firmware/tests_host/CMakeLists.txt:11-34`.
  - Runtime status emission lives in `firmware/Core/Src/Comm.cpp:384-560`.
  - Runtime execution branches for gripper params, flash, pressure, and print profile live in `firmware/Core/Src/Orchestrator.cpp:598-865`.
- User-visible risk or engineering risk:
  - Tag omissions, status ordering drift, and executeCommand regressions can slip past host tests and only appear on hardware.
- Suggested fix:
  - Extract pure helpers for status chunk building / command intent translation where possible, and add HIL assertions for runtime-only branches that cannot be host-tested cleanly.
- Suggested test:
  - Add either a pure status-builder unit test or HIL assertions that verify gripper/flash/command-counter tags and `CMD_SET_GRIPPER_PARAMS` side effects.
- Estimated effort: Large

### AUD-015: Print-array tests still miss the highest-risk orchestration branches
- ID: `AUD-015`
- Title: Existing controller print tests do not cover zero-work arrays or cleanup-after-completion ordering
- Subsystem: Test coverage / controller orchestration
- Files/functions involved:
  - `tests/test_controller_print_guards.py`
  - `docs/audit/TEST_GAPS.md`
  - `FreeRTOS-interface/Controller.py` `print_array()`
- Category: Missing coverage
- Severity: Medium
- Confidence: High
- Evidence:
  - Current tests cover guard rails and current completion behavior at `tests/test_controller_print_guards.py:32-92`.
  - The repo's own open audit gap still flags print-array branch coverage at `docs/audit/TEST_GAPS.md:15-19`.
  - No current test exercises the empty-array case or defers completion until cleanup motion actually finishes.
- User-visible risk or engineering risk:
  - End-of-array regressions can reach hardware before the test suite notices.
- Suggested fix:
  - Add an integration-lite matrix for empty arrays, refill events, and last-well cleanup ordering.
- Suggested test:
  - Mock the machine queue/handlers so the test can assert exact ordering of cleanup commands, progress writes, and `array_complete`.
- Estimated effort: Small to medium

### AUD-016: Reset-recovery tests do not verify axis/target invalidation
- ID: `AUD-016`
- Title: Current reset tests clear flags but do not assert that stale coordinates are removed from planning state
- Subsystem: Test coverage / reset recovery
- Files/functions involved:
  - `tests/test_machine_model_state.py`
  - `tests/test_controller_reset_report.py`
  - `FreeRTOS-interface/Model.py` `MachineModel.recover_after_board_reset()`
  - `FreeRTOS-interface/Controller.py` `handle_reset_report()`
- Category: Missing coverage
- Severity: Medium
- Confidence: High
- Evidence:
  - `tests/test_machine_model_state.py:38-65` verifies flag/banner behavior only.
  - `tests/test_controller_reset_report.py` stubs `get_current_position_dict()` instead of validating the real reset behavior of `MachineModel`.
  - No test currently asserts that current/target axes are invalidated after reset.
- User-visible risk or engineering risk:
  - The stale-position problem in `AUD-006` can recur without a failing regression test.
- Suggested fix:
  - Add a real-model reset test that seeds nonzero axis values and confirms they are cleared before route planning resumes.
- Suggested test:
  - Use an actual `MachineModel`, seed positions/targets, simulate reset handling, and assert they are no longer trusted.
- Estimated effort: Small

### AUD-017: Calibration print overrides are untested end-to-end
- ID: `AUD-017`
- Title: No regression test currently proves calibration print requests honor requested pulse width/pressure
- Subsystem: Test coverage / calibration execution
- Files/functions involved:
  - `FreeRTOS-interface/View.py` `print_calibration_droplets()`
  - `FreeRTOS-interface/Controller.py` `print_calibration_droplets()`
  - `FreeRTOS-interface/Machine_FreeRTOS.py` `print_calibration_droplets()`
  - `FreeRTOS-interface/legacy/mass_calibration.py`
- Category: Missing coverage
- Severity: Medium
- Confidence: High
- Evidence:
  - The call path exists, including legacy pulse-width use at `FreeRTOS-interface/legacy/mass_calibration.py:1184-1188`.
  - No matching pytest file in `tests/` covers `print_calibration_droplets`.
  - `AUD-010` shows the path is already internally inconsistent.
- User-visible risk or engineering risk:
  - Calibration regressions can silently degrade data quality without tripping the test suite.
- Suggested fix:
  - Add an end-to-end controller/machine unit test for calibration print requests with explicit overrides.
- Suggested test:
  - Assert that requesting `pulse_width=...` and `pressure=...` results in the corresponding setup commands and a final calibration dispense.
- Estimated effort: Small to medium
