# Firmware Test Roadmap (Milestones)

Purpose: sequence the updated backlog into vertical-slice milestones that combine host codec/unit confidence with HIL self-test coverage.

## Verification Commands (applies to every milestone)
- Local:
  - `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug`
- HIL:
  - `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 -PiHost 192.168.0.29`

---

## Milestone 1: Protocol Baseline Hardening

Status: Completed (`commit bce03eb`)

### Test IDs completed
- Host-test IDs:
  - `TST-COMM-003`
  - `TST-COMM-004`
  - `TST-COMM-006`
  - `TST-COMM-007`
- HIL self-test IDs:
  - `1001` `comm_crc_known_vector`
  - `1002` `comm_frame_roundtrip`
  - `1010` `session_hello_ack`
  - `1011` `session_goodbye_ack`
  - `1012` `session_goodbye_done`

### Acceptance criteria
- Host tests validate frame boundaries, TLV edge semantics, and session/self-test command framing vectors.
- HIL report contains passing results for all listed SAFE protocol/session tests.
- `host_checks.goodbye_ack == true` and `host_checks.goodbye_done == true` in the self-test JSON.

### Verification commands
- `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug`
- `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 -PiHost 192.168.0.29`

---

## Milestone 2: SAFE Status and Queue Semantics

Status: Completed (`commit b8bdc2d`)

### Test IDs completed
- Host-test IDs:
  - `TST-COMM-006` (extended with `CMD_CLEAR_ACK` framing coverage)
- HIL self-test IDs:
  - `1003` `status_frame_shape`
  - `1013` `clear_queue_ack`
  - `1020` `status_chunk_alternation_safe`
  - `1021` `status_cadence_safe`

### Acceptance criteria
- Status payload shape and queue-clear ACK behavior are stable on target.
- Status chunk alternation and cadence metrics are emitted and within configured tolerances.
- If `TST-COMM-005` is in scope, host golden vectors match emitted status ordering/encoding.

### Verification commands
- `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug`
- `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 -PiHost 192.168.0.29`

---

## Milestone 3: SAFE Runtime Robustness

Status: Completed (`commit 819cac8`)

### Test IDs completed
- Host-test IDs:
  - `TST-COMM-002` (already covered; retained as guardrail)
  - `TST-COMM-003` (already covered; retained as guardrail)
- HIL self-test IDs:
  - `1004` `uptime_counter_read`
  - `1005` `flash_config_readonly`
  - `1006` `fw_build_info`
  - `1030` `uart_recovery_after_noise_safe`

### Acceptance criteria
- SAFE runtime read-only checks pass and expose required metrics.
- UART/noise recovery test demonstrates parser/session recovery on hardware without unsafe commands.
- No regressions in existing CommCodec parser recovery host tests.

### Verification commands
- `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug`
- `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 -PiHost 192.168.0.29`

---

## Milestone 4: Extraction Prerequisites for Deeper Coverage

Status: Completed (`commit 2dd4ff1`)

### Test IDs completed
- Host-test IDs:
  - `TST-ORCH-001`
  - `TST-NVM-001`
  - `TST-PR-001`
  - `TST-STEP-001`
- HIL self-test IDs:
  - None new required; rerun SAFE suite (`1001`-`1006`, `1010`-`1013`, `1020`, `1021`, `1030`) as regression gate.

### Acceptance criteria
- Pure helper extractions are test-covered with deterministic vectors/properties.
- Existing SAFE HIL self-test remains green after extraction refactors.
- No protocol behavior changes.

### Verification commands
- `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug`
- `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 -PiHost 192.168.0.29`

---

## Milestone 5: FULL Profile Bring-Up (Fixture-Gated)

Status: SAFE gating slice completed (`commit 762f6bc`); FULL fixture execution completed (`commit 3902394`).

### Test IDs completed
- Host-test IDs:
  - `TST-COMM-006` and `TST-COMM-007` as compatibility guards for any profile/control TLV changes (no protocol format changes expected).
- HIL self-test IDs:
  - `2001` `motion_home_cycle_full`
  - `2002` `motion_absolute_move_bounds_full`
  - `2003` `pressure_regulator_step_response_full`

### Acceptance criteria
- SAFE profile emits stable IDs `2001`..`2003` with explicit gating metrics and no motion/pressure execution.
- FULL profile runs fixture-gated homing, bounded gantry motion, and pressure step response with deterministic metrics.
- Motion and pressure tests meet agreed tolerances and do not violate safety constraints when FULL execution is enabled.
- SAFE profile remains unchanged and passing.

### Verification commands
- `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug`
- `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 -PiHost 192.168.0.29`

---

## Milestone 6: FULL Profile Safety Completion

Status: Completed (`commit 941e592`)

### Test IDs completed
- Host-test IDs:
  - `TST-COMM-006` (session ACK framing regression guard)
- HIL self-test IDs:
  - `2004` `valve_actuation_sequence_full`
  - `2005` `print_refuel_pulse_integrity_full`
  - `2006` `emergency_abort_and_safe_stop_full`

### Acceptance criteria
- FULL actuator tests pass with required metrics and no unsafe transitions.
- Emergency abort path meets latency and safe-state criteria.
- End-to-end HIL run exits cleanly with complete JSON report.

### Verification commands
- `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug`
- `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 -PiHost 192.168.0.29`

