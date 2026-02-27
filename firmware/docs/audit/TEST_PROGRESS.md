# Firmware Test Progress Tracker

Purpose: single source of truth for firmware test backlog status and execution tracking.

## Checklist Table

| ID | priority | module | description | host-testable | file to add | status |
|---|---|---|---|---|---|---|
| `TST-COMM-001` | `P0` | `CommCodec` | Framing/CRC golden vectors | `Yes` | `firmware/tests_host/tests/test_comm_codec.cpp` | `Done` |
| `TST-COMM-002` | `P0` | `CommCodec` | RX recovery state-machine vectors | `Yes` | `firmware/tests_host/tests/test_comm_codec.cpp` | `Done` |
| `TST-COMM-003` | `P0` | `CommCodec` | Frame boundary/property checks | `Yes` | `firmware/tests_host/tests/test_comm_codec_edges.cpp` | `Todo` |
| `TST-COMM-004` | `P1` | `CommCodec` | TLV decode edge semantics (duplicates/unknown/len) | `Yes` | `firmware/tests_host/tests/test_comm_codec_tlv.cpp` | `Todo` |
| `TST-COMM-005` | `P1` | `Comm(status)` | Status TLV serialization helper vectors | `Yes (after extraction)` | `firmware/tests_host/tests/test_comm_status_codec.cpp` | `Deferred-Extraction` |
| `TST-ORCH-001` | `P1` | `Orchestrator` | Opcode-to-intent table decode vectors | `Yes (after extraction)` | `firmware/tests_host/tests/test_orchestrator_decode.cpp` | `Deferred-Extraction` |
| `TST-NVM-001` | `P1` | `NVM` | Record encode/validate vectors | `Yes (after extraction)` | `firmware/tests_host/tests/test_nvm_codec.c` | `Deferred-Extraction` |
| `TST-PR-001` | `P2` | `PressureRegulator` | Clamp/rate-limit/integrator math | `Yes (after extraction)` | `firmware/tests_host/tests/test_pressure_regulator_math.cpp` | `Deferred-Extraction` |
| `TST-STEP-001` | `P2` | `Stepper` | Profile math edge/property tests | `Yes (after extraction)` | `firmware/tests_host/tests/test_stepper_profile_math.cpp` | `Deferred-Extraction` |
| `TST-HIL-COMM-001` | `P1` | `Comm/HAL` | UART ISR rearm + error recovery | `No (HIL/Deferred)` | `N/A` | `HIL/Deferred` |
| `TST-HIL-ORCH-001` | `P1` | `Orchestrator/RTOS` | HELLO/CLEAR/GOODBYE end-to-end sequencing | `No (HIL/Deferred)` | `N/A` | `HIL/Deferred` |
| `TST-HIL-STATUS-001` | `P2` | `Comm/RTOS` | Status task timing and chunk alternation on target | `No (HIL/Deferred)` | `N/A` | `HIL/Deferred` |
| `TST-HIL-MOTION-001` | `P0` | `Motion/Pressure` | Hardware safety validation for motion/pressure commands | `No (HIL/Deferred)` | `N/A` | `HIL/Deferred` |

## Status Definitions
- `Done`
- `In Progress`
- `Todo`
- `Deferred-Extraction`
- `HIL/Deferred`

## Update Policy
- Any new host test PR must:
  - add or update row(s) in `TEST_PROGRESS.md`
  - reference test ID in commit message (example: `test: add comm tlv edge vectors (TST-COMM-004)`)
  - update `status` and note extracted-helper dependencies when introduced
