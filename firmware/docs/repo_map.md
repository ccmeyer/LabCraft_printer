# Firmware Repo Map

This document maps the `firmware/` directory, startup/runtime entry points, major subsystems, and build/test boundaries.

## 1) Firmware Directory Structure

- `firmware/Core/Inc/`
  - Project headers (application modules and Cube-generated config headers).
  - Examples: `main.h`, `stm32f4xx_hal_conf.h`, `stm32f4xx_it.h`, `FreeRTOSConfig.h`, `Comm.h`, `Orchestrator.h`, `Stepper.h`, `PressureRegulator.h`, `PressureSensor.h`, `Printer.h`.
- `firmware/Core/Src/`
  - Main application/Cube startup source + module implementations.
  - Key files: `main.c`, `freertos.c`, `stm32f4xx_it.c`, `system_stm32f4xx.c`, `stm32f4xx_hal_msp.c`, plus C++ modules (`Comm.cpp`, `Orchestrator.cpp`, `Stepper.cpp`, `Printer.cpp`, `Pressure*.cpp`, etc.).
- `firmware/Core/Startup/`
  - Startup assembly: `startup_stm32f446zetx.s`.
- `firmware/Drivers/`
  - MCU vendor/device support:
  - `Drivers/CMSIS/`
  - `Drivers/STM32F4xx_HAL_Driver/`
- `firmware/Middlewares/`
  - `Middlewares/Third_Party/FreeRTOS/`
  - `Middlewares/ST/STM32_USB_Device_Library/`
- `firmware/tests_host/`
  - Host unit test harness (CMake + CppUTest).
  - Files: `tests_host/CMakeLists.txt`, `tests_host/main.cpp`, `tests_host/tests/test_smoke.cpp`.
- `firmware/third_party/cpputest/`
  - CppUTest framework used by `tests_host`.
- `firmware/scripts/`
  - `run_fw_checks.ps1`, `run_fw_unit_tests.ps1`, `build_firmware_headless.ps1`.
  - `run_fw_hil_windows.ps1` (Windows launcher for Pi flash + selftest + report pullback).
- `firmware/artifacts/`
  - Intended firmware binary output location.
- Build/IDE metadata present in-tree:
  - `.project`, `.cproject`, `.mxproject`, `.ioc`, `.settings/`, `.metadata/`, `Debug/`, `Debug_Legacy/`.

## 2) Runtime Entry Points and Forever Loops

### Boot/system init

- Reset vector/startup: `firmware/Core/Startup/startup_stm32f446zetx.s`.
- System clock and CMSIS init support: `firmware/Core/Src/system_stm32f4xx.c`.
- Main entry: `firmware/Core/Src/main.c`
  - `int main(void)`
  - `SystemClock_Config(void)`
  - Peripheral init sequence (`MX_GPIO_Init`, `MX_DMA_Init`, `MX_USART*_Init`, `MX_TIM*_Init`, etc.)
  - Module init calls (`MX_LED_Init`, `MX_GRIPPER_Init`, `MX_PRINTER_Init`, `MX_FLASH_Init`, `MX_ORCH_Init`, `MX_LOGGER_Init`, `MX_TMC2208_Init`, `MX_LEDSTRIP_Init`)
  - Creates default RTOS thread: `StartDefaultTask`
  - Starts scheduler: `osKernelStart()`

### Scheduler handoff / superloop

- After `osKernelStart()`, `main.c` has `while (1)` fallback (should not execute during normal RTOS operation).
- `StartDefaultTask(void const * argument)` in `main.c` performs runtime bring-up and then loops forever:
  - Starts heartbeat and pressure sensor stack (`MX_HEARTBEAT_Start`, `MX_PS_Init`)
  - Initializes motion/pressure regulators (`MX_GANTRY_Init`, `MX_STEPPERP_Init`, `MX_PRESSURE_REGP_Init`, optional R channel)
  - Starts comms task (`MX_COMM_Init(&huart2)`)
  - `for(;;) { osDelay(1); }`

### FreeRTOS support hooks

- `firmware/Core/Src/freertos.c`
  - Static allocation hooks: `vApplicationGetIdleTaskMemory`, `vApplicationGetTimerTaskMemory`
  - Runtime stats weak hooks: `configureTimerForRunTimeStats`, `getRunTimeCounterValue` (overridden in `main.c` user code)

### ISR/callback entry points

- Central IRQ file: `firmware/Core/Src/stm32f4xx_it.c`
  - EXTI handlers: `EXTI9_5_IRQHandler`, `EXTI15_10_IRQHandler`
  - Timer IRQ handlers: `TIM1_BRK_TIM9_IRQHandler`, `TIM1_UP_TIM10_IRQHandler`, `TIM2_IRQHandler`, `TIM3_IRQHandler`, `TIM4_IRQHandler`, `TIM6_DAC_IRQHandler`, `TIM7_IRQHandler`, `TIM8_*`, etc.
  - UART IRQ handlers: `USART1_IRQHandler`, `USART2_IRQHandler`
  - DMA IRQ handler: `DMA2_Stream7_IRQHandler`
- HAL callback fan-out in `firmware/Core/Src/main.c`
  - `HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin)` -> `MX_FLASH_TriggerCallback` or limit/home handlers (`MX_ATTACH_LIMIT`, `MX_REG_INNER_LIMIT`)
  - `HAL_TIM_OC_DelayElapsedCallback(TIM_HandleTypeDef* htim)` -> flash one-shot path (`MX_FLASH_ONCE`, `MX_FLASH_Acknowledge`)
  - `HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)` -> `HAL_IncTick` and stepper dispatch (`MX_DISPATCH`)
- Additional callback bridge:
  - `firmware/Core/Src/callbacks.cpp`: `HAL_UART_TxCpltCallback` -> comm/logger TX-complete notifications.

## 3) Module Map (Subsystems -> Primary Files)

### Motion (XYZ + syringe steppers, drivers, homing/limits)

- Core classes:
  - `firmware/Core/Inc/Stepper.h`, `firmware/Core/Src/Stepper.cpp`
  - `firmware/Core/Inc/Gantry.h`, `firmware/Core/Src/Gantry.cpp`
  - `firmware/Core/Inc/TMC2208Driver.h`, `firmware/Core/Src/TMC2208Driver.cpp`
- Key functions:
  - `Stepper::move`, `Stepper::moveTo`, `Stepper::home`, `Stepper::dispatch`, `Stepper::handleExtiFromIsr`
  - C wrappers used by orchestrator/main: `MX_STEPPERX_Home`, `MX_STEPPERY_Home`, etc.
  - `Gantry::moveBy`, `Gantry::moveTo`

### Print pulse generation / droplet sequencing

- `firmware/Core/Inc/Printer.h`, `firmware/Core/Src/Printer.cpp`
- Key functions:
  - `Printer::enqueue`, `Printer::taskLoop`, `Printer::onCompareMatch`
  - Wrappers: `MX_PRINTER_Enqueue*`, `MX_PRINTER_COMPARE_MATCH`

### Pressure sensing and regulation (including valve behavior)

- Sensors:
  - `firmware/Core/Inc/PressureSensor.h`, `firmware/Core/Src/PressureSensor.cpp`
  - Functions: `PressureSensor::start`, `PressureSensor::taskLoop`, `getControlSample`, `getLatestRaw`, `getAverageRaw`
- Regulation:
  - `firmware/Core/Inc/PressureRegulator.h`, `firmware/Core/Src/PressureRegulator.cpp`
  - Functions: `PressureRegulator::start`, `PressureRegulator::controlLoop`, `notifyPulseStart`, `notifyPulseEnd`, `homeWithValve`, `openValve`, `closeValve`, `handleInnerLimitFromIsr`
- Shared math/helpers:
  - `firmware/Core/Inc/PressureRegulatorMath.h`, `firmware/Core/Src/PressureRegulatorMath.cpp`
  - Includes pressure sample validation, recovery/feedforward math, and deadline-slip helpers used by both runtime code and host tests.
  - `firmware/Core/Inc/PressureQualificationMath.h`, `firmware/Core/Src/PressureQualificationMath.cpp`
  - Includes bounded arithmetic and aggregation helpers for FULL pressure qualification diagnostics and host tests.
  - `firmware/Core/Inc/ValvePulseQualificationMath.h`, `firmware/Core/Src/ValvePulseQualificationMath.cpp`
  - Includes pressure-trace pulse-drop, recovery, deadline-slip, and outlier aggregation helpers for FULL valve pulse diagnostics and host tests.
  - `firmware/Core/Inc/GripperSealQualificationMath.h`, `firmware/Core/Src/GripperSealQualificationMath.cpp`
  - Includes closed-seal pressure-drop, slope, threshold-duration, and repeat-span helpers for the local operator-gated gripper seal suite and host tests.
- Pressure trace capture:
  - `firmware/Core/Inc/PressureTraceRecorder.h`, `firmware/Core/Src/PressureTraceRecorder.cpp`
  - Records bounded pressure/control samples and events during pressure-focused FULL self-tests.

### Vacuum/gripper/valves

- `firmware/Core/Inc/Gripper.h`, `firmware/Core/Src/Gripper.cpp`
- Key functions:
  - `Gripper::open`, `Gripper::close`, `Gripper::stopPump`, `Gripper::refreshTaskEntry`

### Command/comms and orchestration

- Serial framing + packet handling:
  - `firmware/Core/Inc/Comm.h`, `firmware/Core/Src/Comm.cpp`
  - Functions: `Comm::begin`, `Comm::onRxByte`, `Comm::onRxBytes`, `Comm::handlePacket`, `Comm::statusTask`
  - HAL hooks in same file: `HAL_UART_RxCpltCallback`, `HAL_UART_ErrorCallback`
- High-level command execution/state machine:
  - `firmware/Core/Inc/Orchestrator.h`, `firmware/Core/Src/Orchestrator.cpp`
  - `firmware/Core/Inc/Diagnostics.h`, `firmware/Core/Src/Diagnostics.cpp`
  - `firmware/Core/Inc/DiagnosticResultEmitter.h`, `firmware/Core/Src/DiagnosticResultEmitter.cpp`
  - `firmware/Core/Inc/OrchestratorCompletionPolicy.h`, `firmware/Core/Src/OrchestratorCompletionPolicy.cpp`
  - `firmware/Core/Inc/SelfTestCommandPolicy.h`
  - Functions: `Orchestrator::begin`, `Orchestrator::_run`, `Orchestrator::executeCommand`, `enqueueFromISR`, `startHomeAsync`, `startRegHomeAsync`, `_flashTaskLoop`
  - Self-test entrypoint: `CMD_SELFTEST_START` remains dispatched from `Orchestrator::executeCommand`, but the SAFE/FULL diagnostic sequence now lives in `DiagnosticsRunner::runSelfTest`. `DiagnosticResultEmitter` owns the byte layout for `CMD_SELFTEST_RESULT` and `CMD_SELFTEST_DONE` payloads.
  - Motion qualification diagnostics `2007 motion_home_repeatability_factory` and `2008 motion_pattern_return_factory` live in `DiagnosticsRunner::runSelfTest`, use existing X/Y homing and gantry motion primitives, and publish compact repeatability metrics for Python-side candidate analysis.
  - Pressure qualification diagnostics `2201 pressure_hold_leak_factory`, `2202 pressure_target_cycle_repeatability_factory`, and `2203 pressure_motor_position_hysteresis_factory` live in `DiagnosticsRunner::runSelfTest`, use existing print-channel pressure regulator/sensor primitives, restore the baseline target, pause the regulator at exit, and publish compact hold/leak/repeatability/hysteresis metrics for Python-side candidate analysis.
  - Valve pulse qualification diagnostics `2401 print_valve_pulse_drop_repeatability_factory`, `2402 refuel_valve_pulse_drop_repeatability_factory`, and `2403 dual_valve_interaction_factory` live in `DiagnosticsRunner::runSelfTest`, reuse `PressureTraceRecorder` and `Printer::enqueueWithTimeout`, restore pulse widths/regulator targets through the existing trace runner, and publish compact pressure-drop repeatability metrics for Python-side candidate analysis.
  - Gripper seal diagnostics `2501 gripper_seal_closed_decay_factory`, `2502 gripper_seal_hold_duration_factory`, and `2503 gripper_seal_repeatability_factory` live in `DiagnosticsRunner::runSelfTest` behind the explicit selector `2500`; they are not part of default FULL, apply `1 psi` through `Printer` diagnostic print/refuel valve hold, keep regulator vent valves closed during measurement, keep the gripper closed through firmware execution, close pressure paths at exit, and require Python operator-gated teardown.
  - `SelfTestCommandPolicy` resolves the logical self-test `run_id` and optional timeout TLVs independently from transport `seq32`, keeping HIL self-test compatible with the sliding-window queue-ACK transport.
  - `OrchestratorCompletionPolicy` centralizes the pure “did an interruptible command really finish?” bookkeeping used to decide when executed/retired frontiers may advance after pause-aware waits.
  - Flash session safety lives here: `CMD_INIT_FLASH` / `CMD_STOP_FLASH`, PE8 arm/disarm policy, PE9 output ownership, and fault latch logging (`FLASH_ARMED`, `FLASH_DISARMED`, `FLASH_FAULT`). Active imaging sessions now only hard-fault on `line_high_on_arm`; once armed, duplicate triggers while a flash is already pending are ignored and the task simply waits for PE8 to return low without latching on slow release.

  - `Orchestrator::drainAckQueue()` now flushes deferred `CMD_QUEUE_ACK` traffic from both the main loop and interruptible wait loops so `CMD_PAUSE_AFTER_SEQ32` requests can be acknowledged promptly during long move/dispense commands.

### Logging/status/indicators

- Logging:
  - `firmware/Core/Inc/Logger.h`, `firmware/Core/Src/Logger.cpp`
  - Functions: `Logger::begin`, `Logger::log`, `Logger::statsTask`
- Heartbeat:
  - `firmware/Core/Src/Heartbeat.c` (`for(;;)` blink/task loop)
- LED indicators:
  - `firmware/Core/Inc/LEDController.h`, `firmware/Core/Src/LEDController.cpp` (`taskLoop`)
  - `firmware/Core/Inc/LEDStrip.h`, `firmware/Core/Src/LEDStrip.cpp`

### Flash trigger/imaging path

- `firmware/Core/Inc/Flash.h`, `firmware/Core/Src/Flash.cpp`
- `firmware/Core/Inc/FlashOutputState.h`
- `firmware/Core/Inc/FlashSafety.h`, `firmware/Core/Src/FlashSafety.cpp`
- Main integration through callbacks in `main.c` and orchestrator flash task functions.
- `main.c` now re-applies PE8 as `GPIO_MODE_IT_RISING` + `GPIO_PULLDOWN` in the post-GPIO-init user block and logs `PE8_BIAS ...` after logger startup.
- PE9 is kept in a safe idle GPIO-low state unless the flash session is explicitly armed; logs emit `PE9_SAFE_IDLE` and `PE9_ARMED_OUTPUT`, while the hot flash-trigger path intentionally avoids per-trigger logging to protect small task stacks.
- The self-test RTOS task snapshot now reports `prnt_hwm_words`, `flashmon_hwm_words`, and `flashmon_present` so flash-trigger stack headroom can be verified after firmware changes.
- Hardware requirement: the PE9 flash-driver trigger net must have an external `10 kOhm` pull-down at the flash-driver input side so the output path never floats when the MCU is not actively driving a flash pulse.

### Non-volatile configuration

- `firmware/Core/Inc/nvm.h`, `firmware/Core/Src/nvm.c`
- Functions: `nvm_load`, `nvm_defaults`, `nvm_save`
- Used early in `main()` before full runtime bring-up.

## 4) Dependencies and Boundaries

## HAL/FreeRTOS-coupled modules (firmware-target only)

- Strong HAL/IRQ/timer/UART/GPIO dependencies:
  - `main.c`, `stm32f4xx_it.c`, `stm32f4xx_hal_msp.c`, `system_stm32f4xx.c`
  - `Stepper.cpp`, `Gantry.cpp`, `Printer.cpp`, `PressureSensor.cpp`, `PressureRegulator.cpp`, `Comm.cpp`, `Gripper.cpp`, `LEDStrip.cpp`, `LEDController.cpp`, `Logger.cpp`, `Flash.cpp`, `Heartbeat.c`
- FreeRTOS task/queue/event dependencies are prevalent in:
  - `Orchestrator.cpp`, `Printer.cpp`, `PressureSensor.cpp`, `PressureRegulator.cpp`, `Comm.cpp`, `LEDController.cpp`, `Gripper.cpp`, `Logger.cpp`

## Better candidates for `tests_host` pure-logic extraction

- Packet/frame parsing and command decode logic currently inside `Comm::handlePacket` / RX state handling.
- Command interpretation/state transitions from `Orchestrator::executeCommand` (if HAL calls are wrapped at boundaries).
- Pressure regulator math parts in `PressureRegulator::controlLoop` (clamp/rate-limit/integrator behavior) separated from hardware I/O.
- Stepper trajectory/profile math in `Stepper` if isolated from timer/GPIO register interaction.
- NVM record validation/encoding logic from `nvm.c` (if decoupled from flash write primitives).

Current host tests are minimal: `tests_host/tests/test_smoke.cpp` only verifies test harness operation.

## 5) Build and Test Commands

From repo root:

- Full firmware checks (unit tests + headless build):
  - `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1`
- Host unit tests only:
  - `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_unit_tests.ps1 -Config Debug`
- Headless firmware build only:
  - `powershell -ExecutionPolicy Bypass -File firmware/scripts/build_firmware_headless.ps1`

Script notes:

- `run_fw_checks.ps1` currently chains:
  1. `firmware/scripts/run_fw_unit_tests.ps1`
  2. `firmware/scripts/build_firmware_headless.ps1`
- `run_fw_unit_tests.ps1` uses CMake in `firmware/tests_host` and runs `fw_tests*.exe` from `firmware/tests_host/build`.
- `build_firmware_headless.ps1` imports the CubeIDE project and performs `-cleanBuild "$ProjName/$Cfg"`; then copies the newest `.bin` to `firmware/artifacts/`, skipping the copy if the build output is already the artifact path.

## 7) HIL Host Tooling (Pi camera benchmark)

- `tools/run_selftest.py`
  - Runs protocol selftest and writes the main JSON report.
  - Optional camera benchmark mode:
    - `--camera-benchmark`
    - `--camera-benchmark-order auto|pre_selftest|post_selftest` (default `auto`)
    - `--camera-benchmark-mode flash_only|print_then_flash` (default `flash_only`)
    - `--camera-benchmark-preflight-pressure-timeout-ms N`
    - emits host check `camera_flash_benchmark`
    - writes `<out_base>_camera_benchmark.json`
- `tools/camera_flash_benchmark.py`
  - Pi-side camera + GPIO benchmark logic used by `run_selftest.py`.
  - Includes:
    - mode labels (`flash_only` vs `print_then_flash`)
    - print-path machine-ready preflight (`enable motors`, `home XY`, `home pressure regs`, `start regulators`, bounded pressure-ready wait)
    - init diagnostic snapshot and per-cycle GPIO probe metadata
  - For SAFE-profile HIL stability, `print_then_flash` is typically run with `--camera-benchmark-order post_selftest` to avoid affecting selftest memory-headroom metrics.
  - Measures stage timings:
    - trigger -> ack
    - ack -> arm
    - arm -> selected frame
    - end-to-end cycle
- `firmware/hil/flash_and_test.sh`
  - Passes camera-benchmark flags through to `run_selftest.py`.
  - Still returns non-zero on flash/selftest failure.
- `firmware/scripts/run_fw_hil_windows.ps1`
  - Adds camera-benchmark parameters and pulls the benchmark JSON artifact when enabled.

## 6) Protocol / Message Map (Opcodes, Payloads, Direction)

### 6.1 Framing and CRC rules

All protocol traffic uses this wire frame format in `firmware/Core/Src/Comm.cpp`:

- Frame: `[START=0xAA][LEN:1][PAYLOAD:LEN][CRC16_LO][CRC16_HI]`
- CRC function: `Comm::crc16(...)` (Modbus-style CRC16: init `0xFFFF`, polynomial `0xA001`, little-endian CRC bytes on wire).
- Parser state machine: `HAL_UART_RxCpltCallback(...)` with states `WAIT_START`, `WAIT_LEN`, `WAIT_DATA`.
- Payload parse entry: `Comm::handlePacket(const uint8_t* buf, uint8_t len)`.

Command payload is TLV-based after `[cmd, seq8]`:

- `TAG_P1 = 0x01`, `TAG_P2 = 0x02`, `TAG_P3 = 0x03`, `TAG_SEQ32 = 0x10`
- Generic form: `[tag][len][value bytes little-endian]`

### 6.2 Buffer and size constraints

- RX buffer: `Comm::_rxBuf[64]` (`firmware/Core/Inc/Comm.h`)
  - In `HAL_UART_RxCpltCallback`, packet is accepted only if `LEN + 2 <= sizeof(_rxBuf)`.
  - Effective max payload accepted by current parser: **62 bytes** (`LEN <= 62`) because the parser stores payload+CRC in `_rxBuf`.
- TX scratch buffer: `Comm::_txBuf[160]` declared in header (current send path uses local stack buffers in `sendFrame`/`sendAckWithSeq32`).
- Length field is 1 byte (`uint8_t`), so on-wire payload max representable is 255 bytes, but current RX parser cap is smaller (62).
- Status payload chunks are built with fixed arrays (`payload[1 + 18*(1+1+4)]` and `payload[1 + 19*(1+1+4)]`) and sent via `sendFrame`.

### 6.3 Command opcodes (`Orchestrator::CmdType`) and handling

Common parse path for host->MCU commands:

- Parse: `Comm::handlePacket(...)` in `firmware/Core/Src/Comm.cpp`
- Queue/control dispatch: `Orchestrator::enqueueFromISR(...)` in `firmware/Core/Src/Orchestrator.cpp`
- Normal execution switch: `Orchestrator::executeCommand(...)` in `firmware/Core/Src/Orchestrator.cpp`

| Opcode | Name | Direction | Payload fields (TLV) | Parsed/Handled | Emitted/Serialized |
|---|---|---|---|---|---|
| `0x01` | `CMD_LED` | host->MCU | none currently used | `Comm::handlePacket` -> `Orchestrator::executeCommand` (`CMD_LED`) | n/a |
| `0x02` | `CMD_MOVE_X` | host->MCU | `p1=dir`, `p2=steps`, `p3=freqHz` | `executeCommand` (`Stepper::stepperX()->move`) | n/a |
| `0x03` | `CMD_MOVE_Y` | host->MCU | `p1=dir`, `p2=steps`, `p3=freqHz` | `executeCommand` (`Stepper::stepperY()->move`) | n/a |
| `0x04` | `CMD_MOVE_Z` | host->MCU | `p1=dir`, `p2=steps`, `p3=freqHz` | `executeCommand` (`Stepper::stepperZ()->move`) | n/a |
| `0x05` | `CMD_HOME_X` | host->MCU | `p1=fastHz`, `p2=slowHz`, `p3=backoffSteps` | `executeCommand` (`MX_STEPPERX_Home`) | n/a |
| `0x06` | `CMD_HOME_Y` | host->MCU | `p1=fastHz`, `p2=slowHz`, `p3=backoffSteps` | `executeCommand` (`MX_STEPPERY_Home`) | n/a |
| `0x07` | `CMD_HOME_Z` | host->MCU | `p1=fastHz`, `p2=slowHz`, `p3=backoffSteps` | `executeCommand` (`MX_STEPPERZ_Home`) | n/a |
| `0x08` | `CMD_ENABLE_MOTORS` | host->MCU | none | `executeCommand` | n/a |
| `0x09` | `CMD_DISABLE_MOTORS` | host->MCU | none | `executeCommand` | n/a |
| `0x0A` | `CMD_ABS_X` | host->MCU | `p1=sign/dir`, `p2=targetPos`, `p3=freqHz` | `executeCommand` (`Stepper::moveTo`) | n/a |
| `0x0B` | `CMD_ABS_Y` | host->MCU | `p1=sign/dir`, `p2=targetPos`, `p3=freqHz` | `executeCommand` (`Stepper::moveTo`) | n/a |
| `0x0C` | `CMD_ABS_Z` | host->MCU | `p1=sign/dir`, `p2=targetPos`, `p3=freqHz` | `executeCommand` (`Stepper::moveTo`) | n/a |
| `0x0D` | `CMD_REL_XY` | host->MCU | declared only | no `executeCommand` case in current source | n/a |
| `0x0E` | `CMD_ABS_XY` | host->MCU | `p1=x`, `p2=y`, `p3=freqHz` | `executeCommand` (`Gantry::moveTo`) | n/a |
| `0x10` | `CMD_GRIPPER_OPEN` | host->MCU | none | `executeCommand` (`MX_GRIPPER_Open`) | n/a |
| `0x11` | `CMD_GRIPPER_CLOSE` | host->MCU | none | `executeCommand` (`MX_GRIPPER_Close`) | n/a |
| `0x12` | `CMD_GRIPPER_OFF` | host->MCU | none | `executeCommand` (`MX_GRIPPER_ForceOff`) | n/a |
| `0x20` | `CMD_PRINT` | host->MCU | none | `executeCommand` (`Printer::pulsePrint`) | n/a |
| `0x21` | `CMD_REFUEL` | host->MCU | none | `executeCommand` (`Printer::pulseRefuel`) | n/a |
| `0x22` | `CMD_DISPENSE` | host->MCU | `p1=count`, `p2=rateHz` | `executeCommand` (`Printer::enqueue(..., BOTH)`) | n/a |
| `0x23` | `CMD_DISPENSE_PRINT` | host->MCU | `p1=count`, `p2=rateHz` | `executeCommand` (`Printer::enqueue(..., PRINT_ONLY)`) | n/a |
| `0x24` | `CMD_DISPENSE_REFUEL` | host->MCU | `p1=count`, `p2=rateHz` | `executeCommand` (`Printer::enqueue(..., REFUEL_ONLY)`) | n/a |
| `0x30` | `CMD_LEDSTRIP_ON` | host->MCU | none | `executeCommand` (`MX_LEDSTRIP_FadeTo`) | n/a |
| `0x31` | `CMD_LEDSTRIP_OFF` | host->MCU | none | `executeCommand` (`MX_LEDSTRIP_FadeTo`) | n/a |
| `0x40` | `CMD_SET_AXIS_MAXSPEED` | host->MCU | `p1=axis`, `p2=maxHz` | `executeCommand` | n/a |
| `0x41` | `CMD_SET_AXIS_ACCEL` | host->MCU | `p1=axis`, `p2=accel` | `executeCommand` | n/a |
| `0x42` | `CMD_SET_AXIS_PROFILE` | host->MCU | `p1=axis`, `p2=profile` | `executeCommand` | n/a |
| `0x43` | `CMD_HOME_XY` | host->MCU | `p1=fastHz`, `p2=slowHz`, `p3=backoffSteps` | `executeCommand` (`startHomeAsync`) | n/a |
| `0x44` | `CMD_HOME_PR_BOTH` | host->MCU | `p1=fastHz`, `p2=slowHz`, `p3=backoffSteps` | `executeCommand` (`startRegHomeAsync`) | n/a |
| `0x50` | `CMD_WAIT` | host->MCU | `p1=waitMs` | `executeCommand` (`pauseAwareDelayTicks`) | n/a |
| `0x60` | `CMD_ENABLE_PRINT_PROFILE` | host->MCU | none | `executeCommand` | n/a |
| `0x61` | `CMD_DISABLE_PRINT_PROFILE` | host->MCU | none | `executeCommand` | n/a |
| `0x62` | `CMD_SET_GRIPPER_PARAMS` | host->MCU | `p1=refreshMs`, `p2=pulseMs` | `executeCommand` | n/a |
| `0xC0` | `CMD_INIT_FLASH` | host->MCU | none | `executeCommand` | n/a |
| `0xC1` | `CMD_STOP_FLASH` | host->MCU | none | `executeCommand` | n/a |
| `0xC2` | `CMD_SET_FLASH_DURATION` | host->MCU | `p1=duration` | `executeCommand` (`Flash::setDurationNs`) | n/a |
| `0xC3` | `CMD_SET_FLASH_DELAY` | host->MCU | `p1=delay` | `executeCommand` (`setFlashDelay`) | n/a |
| `0xC4` | `CMD_SET_IMAGING_DROPLETS` | host->MCU | `p1=droplets` | `executeCommand` (`setImagingDroplets`) | n/a |
| `0xD0` | `CMD_SET_PW_PRINT` | host->MCU | `p1=printPulseUs` | `executeCommand` (`Printer::setPrintPulse`) | n/a |
| `0xD1` | `CMD_SET_PW_REFUEL` | host->MCU | `p1=refuelPulseUs` | `executeCommand` (`Printer::setRefuelPulse`) | n/a |
| `0xE0` | `CMD_PR_PRINT` | host->MCU | `p1=targetPressure` | `executeCommand` (`PressureRegulator::regP`) | n/a |
| `0xE1` | `CMD_PR_REFUEL` | host->MCU | `p1=targetPressure` | `executeCommand` (`PressureRegulator::regR`, if dual-port) | n/a |
| `0xE2` | `CMD_HOME_PRINT` | host->MCU | `p1=fastHz`, `p2=slowHz`, `p3=backoffSteps` | `executeCommand` (`regP().homeWithValve`) | n/a |
| `0xE3` | `CMD_HOME_REFUEL` | host->MCU | `p1=fastHz`, `p2=slowHz`, `p3=backoffSteps` | `executeCommand` (`regR().homeWithValve`, if dual-port) | n/a |
| `0xE4` | `CMD_P_VALVE_OPEN` | host->MCU | none | `executeCommand` | n/a |
| `0xE5` | `CMD_P_VALVE_CLOSE` | host->MCU | none | `executeCommand` | n/a |
| `0xE6` | `CMD_R_VALVE_OPEN` | host->MCU | none | `executeCommand` (dual-port only) | n/a |
| `0xE7` | `CMD_R_VALVE_CLOSE` | host->MCU | none | `executeCommand` (dual-port only) | n/a |
| `0xE8` | `CMD_P_REG_START` | host->MCU | none | `executeCommand` | n/a |
| `0xE9` | `CMD_P_REG_STOP` | host->MCU | none | `executeCommand` | n/a |
| `0xEA` | `CMD_R_REG_START` | host->MCU | none | `executeCommand` (dual-port only) | n/a |
| `0xEB` | `CMD_R_REG_STOP` | host->MCU | none | `executeCommand` (dual-port only) | n/a |
| `0xEC` | `CMD_PR_PRINT_REL` | host->MCU | `p1=signBool`, `p2=delta` | `executeCommand` (`regP().setRelativeTargetSafe`) | n/a |
| `0xED` | `CMD_PR_REFUEL_REL` | host->MCU | `p1=signBool`, `p2=delta` | `executeCommand` (`regR().setRelativeTargetSafe`, if dual-port) | n/a |
| `0xEE` | `CMD_RESET_PRINT` | host->MCU | none | `executeCommand` (`regP().resetSyringe`) | n/a |
| `0xEF` | `CMD_RESET_REFUEL` | host->MCU | none | `executeCommand` (`regR().resetSyringe`, if dual-port) | n/a |
| `0xF0` | `CMD_PAUSE` | host->MCU | none | handled early in `enqueueFromISR` (not queued) | n/a |
| `0xF1` | `CMD_RESUME` | host->MCU | none | handled early in `enqueueFromISR` (not queued) | n/a |
| `0xF2` | `CMD_CLEAR` | host->MCU | none | handled early in `enqueueFromISR`; ACK in `_run` | emits `CMD_CLEAR_ACK` |
| `0xF3` | `CMD_HELLO` | host->MCU | none | handled early in `enqueueFromISR`; ACK in `_run` | emits `CMD_HELLO_ACK` |
| `0xF5` | `CMD_GOODBYE` | host->MCU | none | handled early in `enqueueFromISR`; shutdown in `_run` | emits `CMD_BYE_ACK`, later `CMD_BYE_DONE` |
| `0xF4` | `CMD_HELLO_ACK` | MCU->host | `[cmd, seq8]` + optional `TAG_SEQ32` | built in `_run` via `sendAckWithSeq32` | `Comm::sendAckWithSeq32` |
| `0xF6` | `CMD_BYE_ACK` | MCU->host | `[cmd, seq8]` + optional `TAG_SEQ32` | built in `_run` via `sendAckWithSeq32` | `Comm::sendAckWithSeq32` |
| `0xF7` | `CMD_CLEAR_ACK` | MCU->host | `[cmd, seq8]` + optional `TAG_SEQ32` | built in `_run` via `sendAckWithSeq32` | `Comm::sendAckWithSeq32` |
| `0xF8` | `CMD_BYE_DONE` | MCU->host | `[cmd, seq8]` + optional `TAG_SEQ32` | built in `performShutdown` | `Comm::sendAckWithSeq32` |
| `0x02` | `CMD_STATUS` | MCU->host | status TLVs (below) | built in `Comm::statusTask` | `Comm::sendFrame` |

### 6.4 Status telemetry tags (`Comm.h` constants)

`CMD_STATUS` frames are emitted in `Comm::statusTask()` (alternating chunk 0/chunk 1). TLV value width is encoded by `len` (mostly 2 or 4 bytes).

| Tag ID | Name | Emitted? | Source in firmware |
|---|---|---|---|
| `0x10` | `TAG_LED_TOTAL` | not currently emitted | constant in `Comm.h` |
| `0x11` | `TAG_LED_REMAIN` | not currently emitted | constant in `Comm.h` |
| `0x12` | `TAG_PRINT_P` | yes | `PressureSensor::getPrintPressure()` |
| `0x13` | `TAG_REFUEL_P` | yes | `PressureSensor::getRefuelPressure()` |
| `0x14` | `TAG_TAR_PRINT_P` | yes | `PressureRegulator::regP().getTarget()` |
| `0x15` | `TAG_TAR_REFUEL_P` | yes | `PressureRegulator::regR().getTarget()` (dual-port) |
| `0x20` | `TAG_X_POS` | yes | `Gantry::getPosition().x` |
| `0x21` | `TAG_Y_POS` | yes | `Gantry::getPosition().y` |
| `0x22` | `TAG_Z_POS` | yes | `Gantry::getPosition().z` |
| `0x23` | `TAG_P_POS` | yes | `Stepper::stepperP()->getPosition()` |
| `0x24` | `TAG_R_POS` | yes | `Stepper::stepperR()->getPosition()` (dual-port) |
| `0x25` | `TAG_TAR_X_POS` | yes | `Stepper::stepperX()->getTargetPosition()` |
| `0x26` | `TAG_TAR_Y_POS` | yes | `Stepper::stepperY()->getTargetPosition()` |
| `0x27` | `TAG_TAR_Z_POS` | yes | `Stepper::stepperZ()->getTargetPosition()` |
| `0x28` | `TAG_TAR_P_POS` | not currently emitted | constant in `Comm.h` |
| `0x29` | `TAG_TAR_R_POS` | not currently emitted | constant in `Comm.h` |
| `0x30` | `TAG_DROP_TOTAL` | yes | `Printer::getTotalDispensed()` |
| `0x31` | `TAG_DROP_REMAIN` | yes | `Printer::getRemaining()` |
| `0x32` | `TAG_PRINT_PW` | yes | `Printer::getPrintPulse()` |
| `0x33` | `TAG_REFUEL_PW` | yes | `Printer::getRefuelPulse()` |
| `0x34` | `TAG_DISP_FREQ` | yes | `Printer::getDispenseHz()` |
| `0x40` | `TAG_ACTIVE_P` | yes | `PressureRegulator::regP().isActive()` |
| `0x41` | `TAG_ACTIVE_R` | yes | `PressureRegulator::regR().isActive()` |
| `0x50` | `TAG_CMD_DEPTH` | yes | `Orchestrator::getCommandDepth()` |
| `0x51` | `TAG_LAST_CMD` | yes | `Orchestrator::getLastCmdNum()` |
| `0x52` | `TAG_CURR_CMD` | yes | `Orchestrator::getCurrentCmdNum()` |
| `0x60` | `TAG_FLASH_NUM` | yes | `Flash::getPulses()` |
| `0x61` | `TAG_FLASH_WIDTH` | yes | `Flash::getPulseDuration()` |
| `0x62` | `TAG_FLASH_DELAY` | yes | `Orchestrator::getFlashDelay()` |
| `0x63` | `TAG_FLASH_DROPS` | yes | `Orchestrator::getImagingDroplets()` |
| `0x64` | `TAG_EXT_COUNT` | yes | `Orchestrator::getExtCount()` |
| `0x70` | `TAG_X_MAX_HZ` | yes | `Stepper::stepperX()->maxSpeedHz()` |
| `0x71` | `TAG_Y_MAX_HZ` | yes | `Stepper::stepperY()->maxSpeedHz()` |
| `0x72` | `TAG_Z_MAX_HZ` | yes | `Stepper::stepperZ()->maxSpeedHz()` |
| `0x73` | `TAG_X_ACCEL` | yes | `Stepper::stepperX()->accelStepsPerSec2()` |
| `0x74` | `TAG_Y_ACCEL` | yes | `Stepper::stepperY()->accelStepsPerSec2()` |
| `0x75` | `TAG_Z_ACCEL` | yes | `Stepper::stepperZ()->accelStepsPerSec2()` |
| `0x80` | `TAG_GRIP_PULSE` | yes | `Gripper::getPulseDurationMs()` |
| `0x81` | `TAG_GRIP_REFRESH` | yes | `Gripper::getRefreshPeriodMs()` |

### 6.5 Golden vector opportunities for `tests_host`

Pure host-side encode/decode vectors that do not require HAL peripherals:

1. **Frame parser vectors (`Comm` RX state machine + CRC):**
   - Valid frame with `CMD_HELLO`, no TLVs.
   - Valid frame with `CMD_MOVE_X` + TLVs `P1/P2/P3` + `SEQ32`.
   - Corrupt CRC frame (must be ignored).
   - Oversize LEN frame (`LEN=63+`) rejected by current RX bound.
   - Truncated TLV (`tag,len` but short value) should stop parsing safely.

2. **ACK encode vectors (`sendAckWithSeq32`):**
   - `includeSeq32=false` yields payload `[ack, seq8]`.
   - `includeSeq32=true` yields `[ack, seq8, TAG_SEQ32, 4, seq32_le]`.
   - Golden CRC bytes for each payload variant.

3. **Status TLV serialization vectors (`statusTask` payload construction helpers):**
   - Verify TLV byte layout and little-endian encoding for representative signed and unsigned values.
   - Verify chunk split (`CHUNK_0` vs `CHUNK_1`) command byte + tag ordering stability.

4. **Opcode-to-action decode vectors (`Orchestrator::executeCommand` extraction target):**
   - Table-driven tests asserting command -> expected action parameters (e.g., `CMD_SET_AXIS_MAXSPEED`, `CMD_WAIT`, `CMD_PR_PRINT_REL`).
   - Unknown opcode falls into default path without crash.

5. **Session-control vectors:**
   - `CMD_HELLO` triggers ACK intent and state reset behavior.
   - `CMD_GOODBYE` triggers ACK then BYE_DONE path.
   - `CMD_CLEAR` triggers queue reset intent and CLEAR_ACK path.

6. **Pressure self-test/trace vectors:**
   - `tools/run_selftest.py` decodes pressure trace sample/event chunks from `CMD_SELFTEST_RESULT` frames.
   - FULL diagnostic runs can enable raw pressure-trace export with `--pressure-trace`, which writes separate `*_trace_<test_id>.json` artifacts next to the main self-test report.

Notes:

- `Comm.h` declares `onRxByte/onRxBytes`, `txWrite`, and `sendFramed`, but current `Comm.cpp` send/parse paths are through `HAL_UART_RxCpltCallback`, `handlePacket`, `sendFrame`, and `sendAckWithSeq32`.
- `comm_usb_bridge.h` declares USB bridge hooks; implementations are not present in current `Core/Src` tree.
