# Firmware Test Plan Backlog

## Header + Scope
Purpose: define a prioritized firmware test backlog grounded in the current `tests_host` harness and `firmware/docs/repo_map.md`.

Scope split:
- Host-testable (`tests_host`) first
- HIL/Deferred for HAL/RTOS/peripheral behavior

Priority legend:
- `P0` critical protocol safety
- `P1` high-value pure-logic extraction
- `P2` medium-value math/state extraction
- `P3` low-priority/maintenance

## Current Baseline
- Host harness currently compiles `CommCodec.cpp` and tests in `tests_host/tests/`.
- Existing covered tests include:
  - CRC16 known vector
  - Frame encode/decode vectors
  - Parser recovery vectors (noise/back-to-back/corrupt/oversize)
- Major remaining gaps:
  - Status TLV serialization vectors
  - Orchestrator opcode decode intent vectors
  - Pressure/Stepper/NVM pure-logic extraction tests
  - HAL/RTOS-integrated behavior (deferred to HIL/manual validation)

## Prioritized Backlog Entries

### `TST-COMM-001` (P0) CommCodec Framing + CRC Golden Vectors (already covered)
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

### `TST-COMM-002` (P0) CommCodec RX Parser Recovery Vectors (already covered)
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

### `TST-COMM-003` (P0) CommCodec Frame Boundary/Property Checks
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

### `TST-COMM-004` (P1) TLV Decode Edge Semantics
- Target module + file(s):
  - `CommCodec` (`firmware/Core/Inc/CommCodec.h`, `firmware/Core/Src/CommCodec.cpp`)
- Function/API under test:
  - `decodeCommand`
- Test type:
  - property/edge-case
- Concrete input/output examples:
  - duplicate `TAG_P1` entries in one packet
  - unknown tag `0x99` plus valid known tags
  - `TAG_SEQ32` with `len != 4`
- Expected assertions:
  - deterministic overwrite policy on duplicates (current behavior: last write wins)
  - unknown tags ignored without affecting known tags
  - `hasSeq32` false unless `len==4`
- Stubs required:
  - none

### `TST-COMM-005` (P1) Status TLV Serialization Helper Extraction (host-testable after extraction)
- Target module + file(s):
  - extraction target: `firmware/Core/Src/Comm.cpp` status payload build logic
  - proposed helper: `firmware/Core/Src/CommStatusCodec.cpp` + corresponding header
- Function/API under test:
  - pure builder for chunk-0/chunk-1 status payload TLVs
- Test type:
  - golden vector + state-machine (chunk alternation)
- Concrete input/output examples:
  - telemetry sample with mixed values (e.g., `x=-12`, `printP=250`, `flashDelay=1000`)
  - expected TLV bytes include `CMD_STATUS` and stable tag ordering
- Expected assertions:
  - exact byte layout/little-endian encoding
  - stable chunk split and tag ordering
- Stubs required:
  - none for helper tests
  - extraction only (no HAL/RTOS dependencies inside helper)

### `TST-ORCH-001` (P1) Orchestrator Opcode-to-Intent Decode Table (host-testable after extraction)
- Target module + file(s):
  - extraction target: `firmware/Core/Src/Orchestrator.cpp`
  - proposed helper: `firmware/Core/Src/OrchestratorDecode.cpp`
- Function/API under test:
  - opcode + TLV -> normalized command intent/action enum
- Test type:
  - table-driven golden vector
- Concrete input/output examples:
  - `CMD_SET_AXIS_MAXSPEED` with `p1=axis`, `p2=maxHz`
  - `CMD_WAIT` with `p1=waitMs`
  - unknown opcode `0xFF`
- Expected assertions:
  - expected action enum + parsed params
  - unknown opcode routes to safe default/no-op intent
- Stubs required:
  - none for helper tests

### `TST-NVM-001` (P1) NVM Record Validation/Encoding (host-testable after extraction)
- Target module + file(s):
  - extraction target: `firmware/Core/Src/nvm.c`
  - proposed helper: `firmware/Core/Src/nvm_codec.c`
- Function/API under test:
  - pure config encode/decode + validation/checksum
- Test type:
  - golden vector + edge-case
- Concrete input/output examples:
  - valid record bytes -> decoded config struct
  - corrupted checksum/version mismatch bytes
- Expected assertions:
  - valid record accepted and round-trips
  - invalid record rejected and defaults chosen
- Stubs required:
  - none for helper tests

### `TST-PR-001` (P2) Pressure Regulator Math Core (host-testable after extraction)
- Target module + file(s):
  - extraction target: `firmware/Core/Src/PressureRegulator.cpp`
  - proposed helper: `PressureRegulatorMath.*`
- Function/API under test:
  - clamp/rate-limit/integrator update step
- Test type:
  - property/edge-case
- Concrete input/output examples:
  - target/measurement sequences with bounds
- Expected assertions:
  - bounded outputs, monotonicity, no wind-up overflow
- Stubs required:
  - none for math helper

### `TST-STEP-001` (P2) Stepper Profile Math Core (host-testable after extraction)
- Target module + file(s):
  - extraction target: `firmware/Core/Src/Stepper.cpp`
  - proposed helper: `StepperProfileMath.*`
- Function/API under test:
  - step interval/profile calculations
- Test type:
  - property/edge-case
- Concrete input/output examples:
  - accel/decel inputs, zero/negative guard cases
- Expected assertions:
  - no division by zero, bounded interval, monotonic profile
- Stubs required:
  - none for math helper

## HIL/Deferred (explicitly not host-testable now)

### `TST-HIL-COMM-001` UART ISR Rearm/Error Recovery
- Reason deferred:
  - depends on HAL IRQ/UART handles and ISR timing
- Suggested manual validation:
  - inject UART noise/errors and verify comm recovers with valid command acceptance within retry budget
  - confirm no lockup and `CMD_HELLO` still ACKs

### `TST-HIL-ORCH-001` Session Control End-to-End (`HELLO/CLEAR/GOODBYE`)
- Reason deferred:
  - depends on RTOS queue/task sequencing and hardware callbacks
- Suggested manual validation:
  - run scripted command sequence from host app
  - confirm ACK/BYE_DONE ordering and queue reset behavior

### `TST-HIL-STATUS-001` Status Task Timing/Chunk Alternation On Target
- Reason deferred:
  - depends on RTOS scheduling and live subsystem values
- Suggested manual validation:
  - capture UART stream for 10 seconds
  - verify alternating status chunks at expected cadence and stable tag ordering

### `TST-HIL-MOTION-001` Motion/Pressure Safety Behavior
- Reason deferred:
  - requires physical actuators/sensors
- Suggested manual validation:
  - controlled dry-run on hardware fixture with limits/valves observed
  - confirm no unsafe motion/pressure transitions
