# Firmware Test Plan Backlog

## Header + Scope
Purpose: define a prioritized firmware test backlog grounded in `firmware/docs/repo_map.md`, `tests_host`, and current HIL self-test infrastructure.

Scope split:
- Host-testable (`tests_host`) first
- HIL self-test coverage (SAFE now, FULL planned)

Priority legend:
- `P0` critical protocol/session safety
- `P1` high-value logic and integration confidence
- `P2` medium-value math/state and expansion coverage

## Current Baseline
- Host harness compiles `CommCodec.cpp` and tests in `firmware/tests_host/tests/`.
- Existing covered host tests:
  - CRC16 known vector
  - Frame encode/decode vectors
  - RX parser recovery vectors
- Existing HIL SAFE self-test baseline (firmware + Pi script):
  - `1001 comm_crc_known_vector`
  - `1002 comm_frame_roundtrip`
  - `1003 status_frame_shape`
  - `1004 uptime_counter_read`
  - `1005 flash_config_readonly`
  - `1006 fw_build_info`

## HIL SelfTest Profiles

### SAFE Profile (implementable now)
No motion/pressure actuation; read-only and protocol/session checks.

- `1001 comm_crc_known_vector`
- `1002 comm_frame_roundtrip`
- `1003 status_frame_shape`
- `1004 uptime_counter_read`
- `1005 flash_config_readonly`
- `1006 fw_build_info`
- `1010 session_hello_ack`
- `1011 session_goodbye_ack`
- `1012 session_goodbye_done`
- `1013 clear_queue_ack`
- `1020 status_chunk_alternation_safe`
- `1021 status_cadence_safe`
- `1030 uart_recovery_after_noise_safe`

### FULL Profile (planned / HIL fixture required)
Includes controlled motion/pressure/actuation checks with fixture and explicit safety gating.

- `2001 motion_home_cycle_full`
- `2002 motion_absolute_move_bounds_full`
- `2003 pressure_regulator_step_response_full`
- `2004 valve_actuation_sequence_full`
- `2005 print_refuel_pulse_integrity_full`
- `2006 emergency_abort_and_safe_stop_full`

## Prioritized Backlog Entries

### Host-testable (`tests_host`)

#### `TST-COMM-001` (P0) CommCodec Framing + CRC Golden Vectors (covered)
- Target module + file(s):
  - `CommCodec` (`firmware/Core/Inc/CommCodec.h`, `firmware/Core/Src/CommCodec.cpp`)
- Function/API under test:
  - `crc16`, `encodeFrame`, `buildAckPayload`, `decodeCommand`
- Test type:
  - golden vector
- Concrete input/output examples:
  - payload `[0xF3,0x01]` -> frame `[0xAA,0x02,0xF3,0x01,0x84,0x80]`
  - payload `[0xF4,0x22,0x10,0x04,0x78,0x56,0x34,0x12]` -> CRC `0x93D1`
- Expected assertions:
  - exact byte-for-byte frame/CRC equality
  - decoded TLVs match little-endian values
- Stubs required:
  - none

#### `TST-COMM-002` (P0) CommCodec RX Parser Recovery Vectors (covered)
- Target module + file(s):
  - `CommCodec` (`firmware/Core/Inc/CommCodec.h`, `firmware/Core/Src/CommCodec.cpp`)
- Function/API under test:
  - `feedRxByte` (state transitions/recovery)
- Test type:
  - state-machine
- Concrete input/output examples:
  - noise + valid frame stream
  - two valid frames back-to-back
  - corrupt/truncated frame followed by valid
  - oversize LEN (`0x3F`) then valid
- Expected assertions:
  - exact counts of `FrameReady`, `CrcMismatch`, `LengthRejected`
  - parser returns `WAIT_START` after error paths
- Stubs required:
  - none

#### `TST-COMM-003` (P0) CommCodec Frame Boundary/Property Checks
- Target module + file(s):
  - `CommCodec` (`firmware/Core/Inc/CommCodec.h`, `firmware/Core/Src/CommCodec.cpp`)
- Function/API under test:
  - `encodeFrame`, `feedRxByte`
- Test type:
  - property/edge-case
- Concrete input/output examples:
  - `len=0` payload `[]` -> frame `[0xAA,0x00,crc_lo,crc_hi]`
  - `len=62` accepted by parser; `len=63` rejected
  - `outCap < len+4` returns 0
- Expected assertions:
  - frame length and CRC correctness at boundaries
  - parser accepts max current payload and rejects oversize
- Stubs required:
  - none

#### `TST-COMM-004` (P1) TLV Decode Edge Semantics
- Target module + file(s):
  - `CommCodec` (`firmware/Core/Inc/CommCodec.h`, `firmware/Core/Src/CommCodec.cpp`)
- Function/API under test:
  - `decodeCommand`
- Test type:
  - property/edge-case
- Concrete input/output examples:
  - duplicate `TAG_P1` entries
  - unknown tag `0x99` plus valid known tags
  - `TAG_SEQ32` with `len != 4`
- Expected assertions:
  - last-write-wins duplicate behavior
  - unknown tags ignored
  - `hasSeq32` false unless `len==4`
- Stubs required:
  - none

#### `TST-COMM-005` (P1) Status TLV Serialization Helper Extraction (after extraction)
- Target module + file(s):
  - extraction target: `firmware/Core/Src/Comm.cpp`
  - proposed helper: `firmware/Core/Src/CommStatusCodec.cpp` + header
- Function/API under test:
  - pure status payload chunk builders
- Test type:
  - golden vector + chunk alternation
- Concrete input/output examples:
  - mixed telemetry sample values to expected TLV bytes
- Expected assertions:
  - exact layout, LE encoding, stable tag ordering
- Stubs required:
  - none (pure helper)

#### `TST-COMM-006` (P0) Session-Control ACK Framing Vectors (new)
- Target module + file(s):
  - `CommCodec` (`firmware/Core/Src/CommCodec.cpp`)
- Function/API under test:
  - `buildAckPayload`, `encodeFrame`, `decodeCommand`
- Test type:
  - golden vector
- Concrete input/output examples:
  - ACK payloads for `CMD_HELLO_ACK (0xF4)`, `CMD_BYE_ACK (0xF6)`, `CMD_BYE_DONE (0xF8)` with `seq8` and `TAG_SEQ32`
- Expected assertions:
  - exact payload bytes and frame CRCs
  - seq8 + seq32 preserved through decode
- Stubs required:
  - none

#### `TST-COMM-007` (P1) SelfTest TLV Frame Vectors (new)
- Target module + file(s):
  - `CommCodec` (`firmware/Core/Src/CommCodec.cpp`)
- Function/API under test:
  - `encodeFrame`, `decodeCommand`
- Test type:
  - golden vector + edge-case
- Concrete input/output examples:
  - `CMD_SELFTEST_START` with `TAG_PROFILE`, `TAG_RUN_ID`, `TAG_TIMEOUT_MS`
  - `CMD_SELFTEST_DONE` with `TAG_TOTAL`, `TAG_PASSED`, `TAG_FAILED`, `TAG_ABORTED`
- Expected assertions:
  - stable TLV encoding/decoding for self-test commands
  - malformed TLV lengths ignored safely
- Stubs required:
  - none

#### `TST-ORCH-001` (P1) Orchestrator Opcode-to-Intent Decode Table
- Target module + file(s):
  - extraction target: `firmware/Core/Src/Orchestrator.cpp`
  - proposed helper: `firmware/Core/Src/OrchestratorDecode.cpp`
- Function/API under test:
  - opcode + TLV -> normalized intent
- Test type:
  - table-driven golden vector
- Concrete input/output examples:
  - `CMD_SET_AXIS_MAXSPEED`, `CMD_WAIT`, unknown opcode
- Expected assertions:
  - correct intent mapping; unknown -> safe no-op
- Stubs required:
  - none (pure helper)

#### `TST-NVM-001` (P1) NVM Record Validation/Encoding
- Target module + file(s):
  - extraction target: `firmware/Core/Src/nvm.c`
  - proposed helper: `firmware/Core/Src/nvm_codec.c`
- Function/API under test:
  - pure config encode/decode + validation/checksum
- Test type:
  - golden vector + edge-case
- Concrete input/output examples:
  - valid bytes round-trip
  - checksum/version mismatch
- Expected assertions:
  - valid accepted; invalid rejected/defaulted
- Stubs required:
  - none (pure helper)

#### `TST-PR-001` (P2) Pressure Regulator Math Core
- Target module + file(s):
  - extraction target: `firmware/Core/Src/PressureRegulator.cpp`
- Function/API under test:
  - clamp/rate-limit/integrator math step
- Test type:
  - property/edge-case
- Concrete input/output examples:
  - bounded target/measurement sequences
- Expected assertions:
  - bounded outputs, monotonic behavior, no windup overflow
- Stubs required:
  - none (pure helper)

#### `TST-STEP-001` (P2) Stepper Profile Math Core
- Target module + file(s):
  - extraction target: `firmware/Core/Src/Stepper.cpp`
- Function/API under test:
  - interval/profile math
- Test type:
  - property/edge-case
- Concrete input/output examples:
  - accel/decel and zero/negative guards
- Expected assertions:
  - no division-by-zero, bounded interval, monotonic profile
- Stubs required:
  - none (pure helper)

### HIL SelfTest Backlog (concrete)

Verification command for every HIL item:
- `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 -PiHost labcraft.local`

#### `TST-HIL-ST-001` (P0) `1001 comm_crc_known_vector` (SAFE)
- Required firmware-side metrics:
  - `crc` (uint16)

#### `TST-HIL-ST-002` (P0) `1002 comm_frame_roundtrip` (SAFE)
- Required firmware-side metrics:
  - `frame_len` (uint16)
  - `cmd` (uint8)
  - `seq8` (uint8)

#### `TST-HIL-ST-003` (P0) `1003 status_frame_shape` (SAFE)
- Required firmware-side metrics:
  - `tag_count` (uint16)
  - `has_seq32` (bool)

#### `TST-HIL-ST-004` (P1) `1004 uptime_counter_read` (SAFE)
- Required firmware-side metrics:
  - `delta_ms` (uint32)

#### `TST-HIL-ST-005` (P1) `1005 flash_config_readonly` (SAFE)
- Required firmware-side metrics:
  - `flash_delay_us` (uint32)
  - `flash_width_ns` (uint32)

#### `TST-HIL-ST-006` (P1) `1006 fw_build_info` (SAFE)
- Required firmware-side metrics:
  - `version_len` (uint16)
  - `build_epoch` (uint32/string)

#### `TST-HIL-ST-007` (P0) `1010 session_hello_ack` (SAFE)
- Required firmware-side metrics:
  - `ack_cmd` (`0xF4`)
  - `seq8_match` (bool)
  - `seq32_match` (bool when present)

#### `TST-HIL-ST-008` (P0) `1011 session_goodbye_ack` (SAFE)
- Required firmware-side metrics:
  - `ack_cmd` (`0xF6`)
  - `seq8_match` (bool)
  - `seq32_match` (bool when present)

#### `TST-HIL-ST-009` (P0) `1012 session_goodbye_done` (SAFE)
- Required firmware-side metrics:
  - `done_cmd` (`0xF8`)
  - `seq8_match` (bool)
  - `seq32_match` (bool when present)

#### `TST-HIL-ST-010` (P1) `1013 clear_queue_ack` (SAFE)
- Required firmware-side metrics:
  - `ack_cmd` (`0xF7`)
  - `seq8_match` (bool)
  - `queue_depth_after_clear` (uint16)

#### `TST-HIL-ST-011` (P1) `1020 status_chunk_alternation_safe` (SAFE)
- Required firmware-side metrics:
  - `chunk0_seen` (uint16)
  - `chunk1_seen` (uint16)
  - `alternation_errors` (uint16)

#### `TST-HIL-ST-012` (P2) `1021 status_cadence_safe` (SAFE)
- Required firmware-side metrics:
  - `period_ms_avg` (uint32/float)
  - `period_ms_max_jitter` (uint32)

#### `TST-HIL-ST-013` (P1) `1030 uart_recovery_after_noise_safe` (SAFE)
- Required firmware-side metrics:
  - `noise_bytes_injected` (uint16)
  - `frames_recovered` (uint16)
  - `crc_mismatch_count` (uint16)
  - `length_reject_count` (uint16)

#### `TST-HIL-ST-101` (P2) `2001 motion_home_cycle_full` (SAFE gate + FULL fixture implemented)
- Required firmware-side metrics:
  - Current SAFE gate metrics:
    - `profile`
    - `executed`
    - `fixture_required`
    - `motion`
    - `gate`
  - FULL fixture metrics:
  - `home_time_ms`
  - `home_success_axes`
  - `limit_hits`

#### `TST-HIL-ST-102` (P2) `2002 motion_absolute_move_bounds_full` (SAFE gate + FULL fixture implemented)
- Required firmware-side metrics:
  - Current SAFE gate metrics:
    - `profile`
    - `executed`
    - `fixture_required`
    - `motion`
    - `gate`
  - FULL fixture metrics:
  - `target_x`, `target_y`, `target_z`
  - `final_error_steps`
  - `bound_violation` (bool)

#### `TST-HIL-ST-103` (P2) `2003 pressure_regulator_step_response_full` (SAFE gate + FULL fixture implemented)
- Required firmware-side metrics:
  - Current SAFE gate metrics:
    - `profile`
    - `executed`
    - `fixture_required`
    - `pressure`
    - `gate`
  - FULL fixture metrics:
  - `target_pressure`
  - `settle_time_ms`
  - `overshoot`
  - `steady_state_error`

#### `TST-HIL-ST-104` (P2) `2004 valve_actuation_sequence_full` (FULL, deferred fixture)
- Required firmware-side metrics:
  - `valve_open_count`
  - `valve_close_count`
  - `sequence_order_ok` (bool)

#### `TST-HIL-ST-105` (P2) `2005 print_refuel_pulse_integrity_full` (FULL, deferred fixture)
- Required firmware-side metrics:
  - `pulse_count`
  - `pulse_width_min_ns`
  - `pulse_width_max_ns`

#### `TST-HIL-ST-106` (P0) `2006 emergency_abort_and_safe_stop_full` (FULL, deferred fixture)
- Required firmware-side metrics:
  - `abort_latency_ms`
  - `motors_disabled` (bool)
  - `regulators_stopped` (bool)
  - `valves_safe_state` (bool)

## Implementable Now Subset

`P0/P1` items implementable immediately without firmware architecture refactor:
- `TST-COMM-003`
- `TST-COMM-004`
- `TST-COMM-006`
- `TST-COMM-007`
- `TST-HIL-ST-001` .. `TST-HIL-ST-013` (SAFE profile)
- `TST-HIL-ST-101` .. `TST-HIL-ST-103` (FULL profile with fixture)

Items requiring extraction or fixture before implementation:
- Host extraction dependent: `TST-COMM-005`
- FULL-profile HIL fixture dependent: `TST-HIL-ST-101` .. `TST-HIL-ST-106`

## Completion Notes

- Milestone 1 complete (`commit bce03eb`):
  - Host-test IDs: `TST-COMM-003`, `TST-COMM-004`, `TST-COMM-006`, `TST-COMM-007`
  - HIL self-test IDs: `1001`, `1002`, `1010`, `1011`, `1012`
- Milestone 2 complete (`commit b8bdc2d`):
  - Host-test IDs: `TST-COMM-006` (extended with `CMD_CLEAR_ACK` framing coverage)
  - HIL self-test IDs: `1003`, `1013`, `1020`, `1021`
- Milestone 3 complete (`commit 819cac8`):
  - Host-test IDs: `TST-COMM-002`, `TST-COMM-003` (retained parser guardrails)
  - HIL self-test IDs: `1004`, `1005`, `1006`, `1030`
- Milestone 4 complete (`commit 2dd4ff1`):
  - Host-test IDs: `TST-ORCH-001`, `TST-NVM-001`, `TST-PR-001`, `TST-STEP-001`
  - HIL self-test IDs: SAFE regression gate rerun only (`1001`-`1006`, `1010`-`1013`, `1020`, `1021`, `1030`)
- Milestone 5 SAFE gating slice complete (`commit 762f6bc`):
  - Host-test IDs: `TST-COMM-007` (extended self-test result framing guard)
  - HIL self-test IDs: `2001`, `2002`, `2003` emitted in SAFE with `executed=0` gating metrics
- Milestone 5 FULL fixture execution complete (`commit 3902394`):
  - Host-test IDs: `TST-COMM-007` (self-test start profile mirror guard)
  - HIL self-test IDs: `2001`, `2002`, `2003` executed on fixture with FULL metrics

