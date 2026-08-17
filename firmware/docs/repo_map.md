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
  - Periodic runtime statistics and their TIM5 counter hooks are disabled. `configUSE_TRACE_FACILITY` remains enabled only for explicitly invoked diagnostics such as the SAFE RTOS memory-headroom self-test.

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
  - `firmware/Core/Inc/MotionUnitScale.h`
  - `firmware/Core/Inc/StepperIsrInstrumentation.h`, `firmware/Core/Src/StepperIsrInstrumentation.cpp`
  - `firmware/Core/Inc/StepperInstrumentationReport.h`, `firmware/Core/Src/StepperInstrumentationReport.cpp`
  - `firmware/Core/Inc/NormalizedCosineProfile.h`, `firmware/Core/Src/NormalizedCosineProfile.cpp`
  - `firmware/Core/Inc/DirectStepperProfile.h`, `firmware/Core/Src/DirectStepperProfile.cpp`
  - `firmware/Core/Inc/DirectStepperProfileReport.h`, `firmware/Core/Src/DirectStepperProfileReport.cpp`
  - `firmware/Core/Inc/CoordinatedXyPlanner.h`, `firmware/Core/Src/CoordinatedXyPlanner.cpp`
  - `firmware/Core/Inc/CoordinatedXyExecutor.h`, `firmware/Core/Src/CoordinatedXyExecutor.cpp`
  - `firmware/Core/Inc/CoordinatedXyIsrInstrumentation.h`, `firmware/Core/Src/CoordinatedXyIsrInstrumentation.cpp`
  - `firmware/Core/Inc/CoordinatedXyPerformanceReport.h`, `firmware/Core/Src/CoordinatedXyPerformanceReport.cpp`
  - `firmware/Core/Inc/Gantry.h`, `firmware/Core/Src/Gantry.cpp`
  - `firmware/Core/Inc/TMC2208Driver.h`, `firmware/Core/Src/TMC2208Driver.cpp`
- Key functions:
  - `Stepper::move`, `Stepper::moveTo`, `Stepper::home`, `Stepper::dispatch`, `Stepper::handleExtiFromIsr`
  - `MotionUnitScale` is the pure logical/native boundary for the MRES=3 migration. Public commands, stored positions, targets, speeds, accelerations, homes, and status remain in legacy MRES=2 logical units; native cycle count, rate, and acceleration are divided by two. Odd signed displacements truncate toward zero, and targets/status use the resulting reachable logical coordinate.
  - `Stepper::enableOutputsAssertedForDiagnostics` reads the primary and optional secondary enable GPIO output states for explicit qualification evidence; it does not write either output or participate in production motion.
  - `Stepper::home` accepts a cooperative cancellation token and returns distinct succeeded, failed, or canceled outcomes; every blocking home phase polls the token and restores home-only motion settings before exit.
  - `StepperIsrInstrumentation` is the compile-gated, fixed-size X/Y legacy ISR measurement state. `StepperInstrumentationReport` validates completed snapshots and formats compact post-move metrics; neither helper changes timer periods, pulse accounting, or routing.
  - `NormalizedCosineProfile` owns the 257-point Q20 velocity-squared cosine transformed into timer period, reciprocal time-reversed deceleration, Q0.32 quotient/remainder cursor, bounded integer interpolation, and cached current ARR. It has no HAL or FreeRTOS dependency; ISR-callable `currentArr()`/`advance()` do not divide or use floating point. Milestone 5 reaches it through the coordinated planner/executor for normal XY motion.
  - `DirectStepperProfile` adapts that LUT to the independent Stepper toggle-phase contract. Ordinary cosine-profile X/Y/Z moves use it; homing, limit soft stop, P/R, and alternate profiles keep the legacy calculation. `DirectStepperProfileReport` validates exact cursor and optional X/Y ISR coverage for selector `2096`.
  - `CoordinatedXyPlanner` derives a shared X/Y master rate and acceleration, sizes the transformed cosine ramp with a conservative velocity-envelope bound, and emits cached complete-step ARR/DDA mask events with exact centered-error endpoint counts. Preparation may divide and uses a bounded binary search for triangular peak rate; its per-step cursor has no HAL, FreeRTOS, timer, GPIO, floating-point, division, or allocation dependency.
  - `CoordinatedXyExecutor` is the pure Milestone 4 two-edge state machine. It caches one planner event for STEP high and low, advances/accounting only on the falling edge, and implements bounded pause, resume, cancel, limit-priority, and terminal behavior without HAL or FreeRTOS dependencies.
  - `CoordinatedXyIsrInstrumentation` is the bounded production timing state. It retains per-phase and terminal maxima, complete IRQ/entry/deadline coverage, pending updates/streaks, entry lateness, scheduled timer ticks, duration, DWT wraps, and saturation. Obsolete means/sums, software-pulse, injection, and intentional-wait fields were removed. `CoordinatedXyPerformanceReport` applies the fixed two-edge conditional-rearm contract and fails incomplete production evidence closed.
  - `Gantry::startCoordinatedXY` is the unconditional normal X/Y hardware adapter. It reserves both X/Y steppers, checks position/limit/timer constraints, keeps TIM7 stopped, and drives shared DDA/LUT events from TIM2. Every nonterminal physical edge samples TIM2 after the edge/ARR write; service with at most 1,125 ticks remaining, pending UIF, or `CNT > ARR` rebases the next interval from that actual edge. `Stepper` retains direct-axis/homing ownership and forwards X/Y limits to the coordinated cursor.
  - `Gantry::moveTo` and XY-only `moveBy` always use the coordinated executor. The legacy routing switches and fallback are removed; rollback is by a recorded source/artifact identity. Mixed XY+Z `moveBy` remains rejected, while Z-only, direct-axis, homing, and pressure motion keep their own engines. The normal XY `feedHz` argument is still ignored and is tracked as a separate behavior change.
  - Explicit selector `2078` runs the production-scaled camera/home transition: 5 kHz logical positioning, one camera-ratio round trip with 8,416 X and 30,000 Y native cycles/60,000 TIM2 callbacks, then a bounded X home with 50 native pulses/101 timer entries. It emits result `2071` under `coordinated_xy_camera_transition_v2`.
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
  - Includes pressure-trace pulse-drop, recovery, deadline-slip, and outlier aggregation helpers for standalone valve characterization diagnostics and host tests.
  - `firmware/Core/Inc/GripperSealQualificationMath.h`, `firmware/Core/Src/GripperSealQualificationMath.cpp`
  - Includes closed-seal pressure-drop, slope, threshold-duration, and repeat-span helpers for the local operator-gated gripper seal suite and host tests.
  - `firmware/Core/Inc/RegulatorProfileCommandPolicy.h`, `firmware/Core/Src/RegulatorProfileCommandPolicy.cpp`
  - Pure command decode and bounds policy for RAM-only runtime regulator recovery/slew/ready profile commands (`0x68`-`0x6C`); host-tested and free of HAL/FreeRTOS dependencies.
- Pressure trace capture:
  - `firmware/Core/Inc/PressureTraceRecorder.h`, `firmware/Core/Src/PressureTraceRecorder.cpp`
  - Records bounded pressure/control samples and events during pressure-focused FULL self-tests.

### Vacuum/gripper/valves

- `firmware/Core/Inc/Gripper.h`, `firmware/Core/Src/Gripper.cpp`
- Key functions:
  - `Gripper::open`, `Gripper::close`, `Gripper::enableDeferredRefresh`, `Gripper::disableDeferredRefresh`, `Gripper::claimPendingRefreshAfterDispenseWithGateHeld`
  - Explicit open/close commands issue one pulse but do not enable periodic behavior. Deferred expiry is a one-shot timer callback that only marks pending work; it never starts the pump or waits on the shared vacuum gate.
  - After a successful dispense, `Printer` transfers its already-held gate to `Gripper` when pending work is claimed. The deferred pulse starts before print completion is signalled, the interval rearms from pump-off completion, and the next dispense waits through a fixed `3000 ms` cooldown. Motion and other non-dispense commands remain available during that cooldown.
- `firmware/Core/Inc/GripperRefreshPolicy.h`, `firmware/Core/Src/GripperRefreshPolicy.cpp`
  - Pure, host-tested deferred-refresh state policy. It owns enable/disable state, pending-refresh coalescing, pulse-completion timing, and wrap-safe dispense-cooldown calculations without HAL or FreeRTOS dependencies. Production `Gripper`, `Printer`, and `Orchestrator` consume this policy under short critical sections.

### Command/comms and orchestration

- `firmware/Core/Inc/FlashPrintCompletionPolicy.h`, `firmware/Core/Src/FlashPrintCompletionPolicy.cpp`
  - Pure, host-tested imaging print deadline calculation. It retains the existing pulse-duration grace and `1000..30000 ms` base bounds, then adds a saturating startup-delay budget. The production flash task supplies `Gripper::DISPENSE_COOLDOWN_MS`, so a one-droplet 20 Hz imaging print receives `4050 ms` and a valid cooldown wait cannot latch `print_completion_timeout`.

- Serial framing + packet handling:
  - `firmware/Core/Inc/Comm.h`, `firmware/Core/Src/Comm.cpp`
  - Functions: `Comm::begin`, `Comm::onRxByte`, `Comm::onRxBytes`, `Comm::handlePacket`, `Comm::statusTask`
  - HAL hooks in same file: `HAL_UART_RxCpltCallback`, `HAL_UART_ErrorCallback`
- High-level command execution/state machine:
  - `firmware/Core/Inc/Orchestrator.h`, `firmware/Core/Src/Orchestrator.cpp`
  - `firmware/Core/Inc/Diagnostics.h`, `firmware/Core/Src/Diagnostics.cpp`
  - `firmware/Core/Inc/DiagnosticResultEmitter.h`, `firmware/Core/Src/DiagnosticResultEmitter.cpp`
  - `firmware/Core/Inc/CrashWatchdogSelfTestPolicy.h`, `firmware/Core/Src/CrashWatchdogSelfTestPolicy.cpp`
  - `firmware/Core/Inc/WatchdogSupervisor.h`, `firmware/Core/Src/WatchdogSupervisor.c`, `firmware/Core/Inc/WatchdogParticipationPolicy.h`
  - `firmware/Core/Inc/OrchestratorCompletionPolicy.h`, `firmware/Core/Src/OrchestratorCompletionPolicy.cpp`
  - `firmware/Core/Inc/HomeInterruptionPolicy.h`, `firmware/Core/Src/HomeInterruptionPolicy.cpp`
  - `firmware/Core/Inc/RegulatorPausePolicy.h`, `firmware/Core/Src/RegulatorPausePolicy.cpp`
  - `firmware/Core/Inc/SelfTestCommandPolicy.h`
  - Functions: `Orchestrator::begin`, `Orchestrator::_run`, `Orchestrator::executeCommand`, `enqueueFromISR`, `startHomeAsync`, `startRegHomeAsync`, `_flashTaskLoop`
  - Self-test entrypoint: `CMD_SELFTEST_START` remains dispatched from `Orchestrator::executeCommand`, but the SAFE/FULL diagnostic sequence now lives in `DiagnosticsRunner::runSelfTest`. `DiagnosticResultEmitter` owns the byte layout for `CMD_SELFTEST_RESULT` and `CMD_SELFTEST_DONE` payloads.
  - Stack-overflow crash attribution records the active command plus the mapped FreeRTOS task ID and compact task-name prefix so `RESET_REPORT` can identify the overflowing task when possible.
  - `CrashWatchdogSelfTestPolicy` owns the host-tested pass/fail policy and compact metrics for SAFE rows `1041 crash_record_retained_safe` and `1042 watchdog_supervisor_safe`; `DiagnosticsRunner` samples runtime state and emits the unchanged result frames. Row `1041` fails active recovery (`pending=1`, subject only to the existing sticky-status exception) but passes recovered history (`pending=0`) while continuing to report the retained last-fault fields.
  - The watchdog task is created unarmed by default and arms after the first accepted HELLO. Participant enable/disable transitions atomically publish the mask and initial timestamp; `Watchdog_CheckIn()` updates only the timestamp. Pressure-regulator state transitions own participation changes, while the 5 ms control loop only checks in.
  - `PressureSensorWatchdogTelemetry` records pressure loop gaps, I2C phase/failures/recoveries, completion age, and stack headroom with wrap-safe/saturating host-tested logic. Generation-validated snapshots leave interrupts enabled and fail closed if they intersect an update. When the supervisor identifies `CRASH_TASK_PRESSURE`, it captures this state into a checksummed `.noinit` context before `CrashLog_RecordWatchdogFault()`; the backup-register layout and reset-report wire format are unchanged.
  - `SelfTestSchedulingPolicy` owns result-frame transmit/yield counters, cooperative emission-priority/timeout selection, and SAFE result formatting. `DiagnosticsRunner` wraps each cooperative result/progress transmission plus its one-tick delay in an RAII guard that temporarily lowers only the emitting orchestrator to the pressure task's priority. Tick-level time slicing lets pressure interrupt polling UART output without also sharing CPU with the idle task; the original priority is then restored. `Comm::sendFrameWithTimeout()` gives only cooperative self-test frames a 50 ms cap and returns failure for incomplete evidence; ordinary communication and selector `1039` retain 25 ms. P3 selectors `1039` and `1038` run the ordinary SAFE inventory in no-yield and cooperative modes. Ordinary SAFE and those selectors append `1044 pressure_wdg_context_safe` and `1043 selftest_scheduler_safe`; focused motion result inventories remain unchanged. The pressure-sensor watchdog deadline is 500 ms, while strict cooperative qualification still requires pressure age/gap at or below 125 ms.
  - `PressureSensorWatchdogTelemetry` adds failure-only I2C attribution to those rows: `h` is the failed HAL receive result, `r` its elapsed milliseconds, `x` the active/latest read-recovery wall duration, and `e` the `HAL_I2C_GetError()` bitmask captured before recovery. Normal successful reads add only two tick reads; recovery retains its existing 20 one-tick delays and no continuous tracing or loop-time stack scan is enabled.
  - Custom regulator pressure traces use selector `2110` plus self-test start TLVs `TAG_TRACE_CHANNEL`, `TAG_TRACE_PRESSURE_MPSI`, `TAG_TRACE_PULSE_US`, `TAG_TRACE_PULSE_COUNT`, and `TAG_TRACE_FREQUENCY_HZ`; `Orchestrator` copies them into `DiagnosticsRequest::customPressureTrace`, and `DiagnosticsRunner` validates the RAM-only recipe before calling the shared pressure trace runner.
  - Motion qualification diagnostics `2007 motion_home_repeatability_factory` and `2008 motion_pattern_return_factory` live in `DiagnosticsRunner::runSelfTest`, use existing X/Y homing and gantry motion primitives, and publish compact repeatability metrics for Python-side candidate analysis.
  - Selector `2029` runs operator-gated legacy X/Y timing diagnostics `2020`-`2025`. It uses the existing result frames, requires a 6 kHz equal-axis probe before the 40 kHz vectors, keeps positioning moves at 6 kHz, and reports ISR phase-cycle maxima, exact entries/pulses, pending updates, status cadence, and watchdog age outside the ISR.
  - Selector `2039` runs only explicit SAFE result `2030 profile_lut_cycle_benchmark_safe`. It benchmarks the unused fixed-point profile against the legacy cosine over forward/reverse 258-, 1,000-, and 11,430-interval ramps with per-call PRIMASK save/restore and no motion, GPIO, pressure, valve, or homing access. Ordinary SAFE does not include it.
  - Pressure qualification diagnostics `2201 pressure_hold_leak_factory`, `2202 pressure_target_cycle_repeatability_factory`, and `2203 pressure_motor_position_hysteresis_factory` live in `DiagnosticsRunner::runSelfTest`, use existing print-channel pressure regulator/sensor primitives, restore the baseline target, pause the regulator at exit, and publish compact hold/leak/repeatability/hysteresis metrics for Python-side candidate analysis.
  - Standalone pressure regulator diagnostics `2210`-`2219` and refuel vacuum diagnostics `2220`-`2221` live behind explicit self-test selectors. The refuel vacuum command path and rows home the refuel regulator through `Orchestrator::startRegHomeAsync()` before `PressureRegulator::regR().enterVacuumModeAfterHome()`, temporarily lower only the refuel pressure sensor validation minimum for below-atmospheric samples, cycle between `-1 psi` and atmosphere, restore validation and regulator state at exit, and publish compact sensor-shift, settle, trace, and motor-travel guard metrics.
  - Legacy valve pulse diagnostics `2401 print_valve_pulse_drop_repeatability_factory`, `2402 refuel_valve_pulse_drop_repeatability_factory`, and `2403 dual_valve_interaction_factory` are retired from default FULL/factory acceptance runs after producing non-actionable pressure-drop warnings.
  - Standalone valve characterization diagnostics `2473`-`2479` live in `DiagnosticsRunner::runSelfTest`, reuse `PressureTraceRecorder` and `Printer::enqueueWithTimeout`, restore pulse widths/regulator targets through the existing trace runner, and publish trace artifacts for Python-side valve analysis.
  - Gripper seal diagnostics `2501 gripper_seal_closed_decay_factory`, `2502 gripper_seal_hold_duration_factory`, and `2503 gripper_seal_repeatability_factory` live in `DiagnosticsRunner::runSelfTest` behind the explicit selector `2500`; they are not part of default FULL, home P/R regulators through the existing async regulator-home task path so the orchestrator can keep checking into the watchdog, run two unscored conditioning bursts, recharge to `1 psi`, pause regulators during repeated `Printer` diagnostic extended one-pulse print/refuel valve bursts, keep regulator vent valves closed during measurement, keep the gripper closed through firmware execution, emit a normal done frame on setup failures when possible, close pressure paths at exit, and require Python operator-gated teardown plus normal `GOODBYE` shutdown after fixture removal.
  - Operator-gated stress rows `2511` and `2512` use the production `DeferredUntilDispense` path. Row `2511` proves expiry remains non-actuating through idle/direct pressure traces, a successful `Printer::enqueueWithTimeout()` boundary claims exactly one pulse, the timer rearms only after pump-off, and the next dispense is delayed at least `3000 ms`. Row `2512` permits expiry during the motion raster and proves motion/direct diagnostic pulses neither consume pending work nor actuate the gripper. Metrics report mode, pending state, refresh-count delta, pulse-completion tick, and measured cooldown where applicable; every diagnostic exit disables deferred mode.
  - Active manifest `gripper_seal_stress_v2` adds a host-side production-wire layer before selector `2599`: `CLOSE_GRIPPER`, `ENABLE_PRINT_PROFILE(p1=1)`, real `CMD_DISPENSE_PRINT` boundaries, disable, and a 31-second `p1=0` negative window. It consumes existing queue ACK and status-retirement fields only, writes `production_path.json`, and requires `gripper_refresh_production_path` plus the self-test progress watchdog. Archived v1 retains its old metric contract for historical normalization.
  - `SelfTestCommandPolicy` resolves the logical self-test `run_id` and optional timeout TLVs independently from transport `seq32`, keeping HIL self-test compatible with the sliding-window queue-ACK transport.
  - `OrchestratorCompletionPolicy` centralizes the pure “did an interruptible command really finish?” bookkeeping used to decide when executed/retired frontiers may advance after pause-aware waits. Normal ABS_XY retirement additionally requires accepted startup, shared two-bit completion, a completed coordinated terminal reason, and exact endpoint/target agreement. Limit, planner, rejection, and mismatch outcomes latch a fail-closed transport pause until successful CLEAR or GOODBYE cleanup; pause and intentional clear/shutdown interruption remain resumable or safely cancelable.
  - `RegulatorPausePolicy` owns the host-tested one-shot active-channel snapshot used to stop pressure regulation for manual pause, restore only previously active channels on resume, and discard restoration state on clear or session shutdown.
  - `HomeInterruptionPolicy` owns the host-tested, generation-tagged cancel/restart lifecycle. Orchestrator home workers are persistent static tasks: Pause hard-stops active home axes and closes regulator valves, Resume re-runs interrupted autonomous recovery homes before restarting the interrupted opcode, and a genuine failure remains paused and unretired until Clear.
  - Each persistent X/Y/Z/P/R home worker registers its static stack bounds with `CrashLog`. `Stepper::home` records phase transitions plus task-level checkpoints (`phase_entry`, `before_event_clear`, `before_move`, `waiting_for_move`, `after_move`, `before_limit_sample`, `after_limit_sample`, or `finishing`). There is no per-step or timer-ISR instrumentation, and parallel X/Y or P/R scheduling is unchanged.
  - Homing interruption does not add or change any serial opcode, TLV, ACK, or status field; the existing paused flag and non-advancing completion watermark represent a latched failure to the host.
  - Flash session safety lives here: `CMD_INIT_FLASH` / `CMD_STOP_FLASH`, PE8 arm/disarm policy, PE9 output ownership, and fault latch logging (`FLASH_ARMED`, `FLASH_DISARMED`, `FLASH_FAULT`). Active imaging sessions now only hard-fault on `line_high_on_arm`; once armed, duplicate triggers while a flash is already pending are ignored and the task simply waits for PE8 to return low without latching on slow release. Imaging print completion uses `FlashPrintCompletionPolicy` with the full fixed gripper cooldown as startup budget; cancellation and fault-latch behavior remain unchanged after that bounded deadline.

  - `Orchestrator::drainAckQueue()` now flushes deferred `CMD_QUEUE_ACK` traffic from both the main loop and interruptible wait loops so `CMD_PAUSE_AFTER_SEQ32` requests can be acknowledged promptly during long move/dispense commands.
  - Runtime regulator profile calibration entrypoints `CMD_SET_REG_RECOVERY_PROFILE`, `CMD_SET_REG_SLEW_PROFILE`, `CMD_SET_REG_READY_PROFILE`, and `CMD_RESTORE_REG_PROFILE` validate existing `p1/p2/p3` TLVs through `RegulatorProfileCommandPolicy`, apply candidate settings in RAM only, capture a session baseline before the first candidate apply, and restore either that baseline or firmware defaults on request. `CMD_QUERY_REG_PROFILE` is reserved/no-op until a response format is documented.

### Logging/status/indicators

- Logging:
  - `firmware/Core/Inc/Logger.h`, `firmware/Core/Src/Logger.cpp`
  - Functions: `Logger::begin`, `Logger::log`
  - No periodic `LogStats` task is created. The former `vTaskGetRunTimeStats` path was removed because its unbounded formatter overflowed its 512-byte buffer as the task population grew, corrupting adjacent application state and adding periodic scheduler-suspended stack scans.
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
- The explicitly invoked self-test RTOS task snapshot uses a bounded 32-entry array and reports `task_total`, `task_cap`, `prnt_hwm_words`, `flashmon_hwm_words`, and `flashmon_present`. Its stack scan is not run periodically.
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
- `build_firmware_headless.ps1` imports the CubeIDE project and performs `-cleanBuild "$ProjName/$Cfg"`. It now stops before artifact discovery/copy when CubeIDE returns a build failure, preventing a stale `.bin` from replacing the versioned artifact. Coordinated XY has one production `Debug` configuration; the diagnostic-only MRES3 configuration was removed.

## 7) HIL Host Tooling (Pi camera benchmark)

- `tools/run_selftest.py`
  - Runs protocol selftest and writes the main JSON report.
  - `--selftest-scheduler-no-yield-suite` and `--selftest-scheduler-cooperative-suite` select P3 values `1039` and `1038`. Both remain SAFE/no-motion; their mode-specific manifests and `tools/compare_selftest_scheduler_ab.py` validate the counterbalanced six-arm experiment.
  - `--motion-timing-suite` selects existing self-test selector `2029`; no protocol layout changes are required.
  - `--profile-lut-benchmark` selects existing P3 selector `2039` and returns only non-motion SAFE result `2030`; `profile_lut_benchmark_v1` supplies the permanent qualification gates.
  - Coordinated XY has three supported focused selectors. `--coordinated-xy-production-mres3-suite` maps to `2097` and emits `[2087,2088,2089,2090,2098]` under active manifest `coordinated_xy_production_mres3_v3`. It strictly gates the fixed MRES3/two-edge/conditional-rearm implementation, exact 53,416/90,000/110,000 native totals, 220,000 callbacks, complete IRQ/entry/deadline coverage, bounded timing, status/watchdog evidence, homes, driver configuration, and continuous 15 ms X/Y limit confirmation. `MotionLimitDebouncePolicy.h` provides the shared wrap-safe `Idle`/`Pending`/`Confirmed` state machine used by coordinated TIM2 and direct X/Y/Z/P/R timer paths; raw EXTI callbacks only start/mask candidates.
  - `--direct-xyz-lut-suite` selects production P3 selector `2096` under `FULL` and emits results `2091`-`2095`. It homes Z/XY, runs direct 14,000-logical-unit X/Y/Z moves plus a 2,000-unit triangular X move at 40 kHz logical rate, then homes again. One RAII-guarded status window remains open across the complete bounded row so sub-second move boundaries cannot hide cadence; while that selector-only window is active, the common self-test emitter resumes status after its mandatory per-frame pause. Aggregate result `2095` reports and gates status frames, a 125 ms maximum period, 100 ms watchdog age, alternation, and snapshot validity. `direct_xyz_lut_v1` requires exact MRES=3 native pulses, complete normalized cursor coverage, bounded X/Y active ISR cost with zero pending/saturation evidence, live host status/progress-watchdog checks, legacy-path homes, no P/R displacement, and the production driver configuration.
  - The completed Z speed-ladder experiment selected the retained production profile of 30 kHz logical rate and 140,000 logical steps/s^2. Diagnostic selector `2199`, `ZAxisSpeedLadderReport`, and the Z-only TIM10 entry/exit instrumentation were removed from firmware. Archived manifests v1-v3 and catalog rows `2190`-`2197` remain host-side for raw historical normalization only; they cannot launch hardware.
  - `--coordinated-xy-camera-transition-suite` maps to `2078`, emits `2071`, and is normalized by active manifest `coordinated_xy_camera_transition_v2`. It checks the production-scaled camera-ratio round trip and immediate bounded X home.
- `tools/qualification/gripper_refresh_production.py`
  - Uses the existing four-byte P1/P2/P3 TLVs, queue ACKs, `seq32`, alternating status chunks, and `TAG_LAST_RETIRED` to qualify the public gripper-refresh command lifecycle without importing Qt. It first establishes the production `Printer` precondition with a safe 1 psi target and fresh active/ready pressure status, then owns the fixed 30-second expiry waits, 1500 ms fast-dispense gates, `3000..7000 ms` deferred gap, artifact schema, profile-disable/pressure-deregulate/CLEAR cleanup, and no-release safety boundary.
- `firmware/scripts/run_gripper_refresh_hil_windows.ps1`
  - Composes `run_fw_hil_windows.ps1 -Profile FULL` with active `gripper_seal_stress_v2`, forces the `dummy_blocked_head_motion_v1` operator gate, uploads current qualification tooling, uses interactive SSH for support/plate prompts, downloads all selected artifacts, and fails unless ordinary FULL, the production host check, and rows `2510`-`2513` all pass.
  - Superseded coordinated-XY manifests remain in `tools/qualification/manifests/` with `lifecycle: archived`. They are available only for `--raw-report` normalization. Their firmware selectors and `run_selftest.py` launch flags are removed, and archived manifests are not shown in the qualification UI or accepted by campaigns/live runs.
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
- Status payload chunks are built with fixed local arrays (`payload[160]` for chunk 0 and `payload[176]` for chunk 1) and sent via `sendFrame`; both chunks remain below the 255-byte frame length limit.

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
| `0x60` | `CMD_ENABLE_PRINT_PROFILE` | host->MCU | `p1=0`: pressure profile on + deferred refresh off; `p1=1`: pressure profile on + fresh 30 s deferred interval; other values are logged and safely treated as refresh off | `executeCommand` | n/a |
| `0x61` | `CMD_DISABLE_PRINT_PROFILE` | host->MCU | none; disables/clears/stops deferred refresh before pressure teardown | `executeCommand` | n/a |
| `0x62` | `CMD_SET_GRIPPER_PARAMS` | host->MCU | `p1=refreshMs`, `p2=pulseMs` | `executeCommand` | n/a |
| `0x65` | `CMD_REFUEL_VACUUM_ENTER` | host->MCU | `p1=targetRaw`, `p2=prepPositionSteps`, `p3=moveHz` | `executeCommand` (`enterRefuelVacuumModeWithAsyncHome`) | dual-port only |
| `0x66` | `CMD_REFUEL_VACUUM_SET_TARGET` | host->MCU | `p1=targetRaw` | `executeCommand` (`regR().setVacuumTargetSafe`) | dual-port only |
| `0x67` | `CMD_REFUEL_VACUUM_EXIT` | host->MCU | `p1=restoreTargetRaw` | `executeCommand` (`regR().exitVacuumMode`) | dual-port only |
| `0x68` | `CMD_SET_REG_RECOVERY_PROFILE` | host->MCU | chunked recovery config in existing `p1/p2/p3` TLVs | `RegulatorProfileCommandPolicy` -> `PressureRegulator::applyRuntimeRecoveryConfig` | RAM-only candidate |
| `0x69` | `CMD_SET_REG_SLEW_PROFILE` | host->MCU | `p1=channel`, `p2=up/down`, `p3=bypassTicks` | `RegulatorProfileCommandPolicy` -> `PressureRegulator::applyRuntimeSlewConfig` | RAM-only candidate |
| `0x6A` | `CMD_SET_REG_READY_PROFILE` | host->MCU | `p1=channel`, `p2=readyTolRaw`, `p3=consecutiveSamples` | `RegulatorProfileCommandPolicy` -> `PressureRegulator::applyRuntimeReadyConfig` | RAM-only candidate |
| `0x6B` | `CMD_RESTORE_REG_PROFILE` | host->MCU | `p1=channelMask`, `p2=source`, `p3=0` | `executeCommand` restores session baseline or firmware defaults | no persistence |
| `0x6C` | `CMD_QUERY_REG_PROFILE` | host->MCU | reserved | `executeCommand` logs reserved/no-op | response TBD |
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
| `0xF9` | `CMD_RESET_REPORT` | MCU->host | reset-report TLVs (below) | built after `HELLO_ACK` when `ResetReportPolicy` says to report | `Comm::sendResetReport` |
| `0x02` | `CMD_STATUS` | MCU->host | status TLVs (below) | built in `Comm::statusTask` | `Comm::sendFrame` |

### 6.4 Reset report tags (`Comm.h` constants)

`CMD_RESET_REPORT` frames are emitted at most once per MCU boot after the first accepted `HELLO` / `HELLO_ACK` path when retained crash state or reset-cause policy requires a report. A later host session on the same boot therefore receives no startup report. TLV value width is encoded by `len`; all multi-byte numeric fields are little-endian. The Python app treats missing optional tags as backward-compatible absent fields. `tools/run_selftest.py` retains a HELLO-sequence/run-ID-matched frame as nullable top-level `startup_reset_report`, including when it shares a serial read with `HELLO_ACK`; top-level `reset_report` remains reserved for a non-startup report that fails the active run closed.

| Tag ID | Name | Width | Source in firmware |
|---|---|---|---|
| `0x10` | `TAG_RESET_SEQ32` | 4 | host/control sequence attached to the report |
| `0x11` | `TAG_RESET_CAUSE` | 1 | `CrashLogSnapshot.resetCause` classified from retained RCC flags |
| `0x12` | `TAG_RESET_FLAGS` | 4 | `CrashLogSnapshot.flags` retained crash-log flags |
| `0x13` | `TAG_RESET_LAST_FAULT` | 1 | `CrashLogSnapshot.lastFault` |
| `0x14` | `TAG_RESET_LAST_TASK` | 1 | `CrashLogSnapshot.lastTask` |
| `0x15` | `TAG_RESET_BOOT_COUNT` | 4 | `CrashLogSnapshot.bootCount` |
| `0x16` | `TAG_RESET_FAULT_COUNT` | 4 | `CrashLogSnapshot.faultCountTotal` |
| `0x17` | `TAG_RESET_WATCHDOG_COUNT` | 4 | `CrashLogSnapshot.watchdogResetCount` |
| `0x18` | `TAG_RESET_WATCHDOG_STICKY_CT` | 4 | `CrashLogSnapshot.watchdogStickyCount` |
| `0x19` | `TAG_RESET_WATCHDOG_RAW_SR` | 4 | `CrashLogSnapshot.watchdogRawStatus` |
| `0x1A` | `TAG_RESET_UPTIME_MS` | 4 | `CrashLogSnapshot.uptimeMs` |
| `0x1B` | `TAG_RESET_BOOT_STAGE` | 1 | `CrashLogSnapshot.bootStage` |
| `0x1C` | `TAG_RESET_RECOVERY_BOOT` | 1 | `CrashLog_IsWatchdogRecoveryBoot()` result |
| `0x1D` | `TAG_RESET_FAULT_STAGE` | 1 | `CrashLogSnapshot.faultStage` |
| `0x1E` | `TAG_RESET_WATCHDOG_LATE_TASK` | 1 | `CrashLogSnapshot.watchdogLateTask` |
| `0x1F` | `TAG_RESET_ACTIVE_COMMAND` | 1 | `CrashLogSnapshot.activeCommand` |
| `0x20` | `TAG_RESET_RCC_FLAGS` | 4 | optional raw `CrashLogSnapshot.resetFlagsRaw`; Python decodes names from `LPWRRSTF`, `WWDGRSTF`, `IWDGRSTF`, `SFTRSTF`, `PORRSTF`, `PINRSTF`, and `BORRSTF` bits |
| `0x21` | `TAG_RESET_TASK_NAME4` | 4 | optional packed 4-byte prefix of the FreeRTOS task name captured by the stack-overflow hook |
| `0x22` | `TAG_RESET_REG_CONTEXT` | 30 | optional packed `RegulatorTelemetryResetContext` retained in `.noinit` SRAM for non-power reset reports |
| `0x23` | `TAG_RESET_FAULT_CONTEXT` | 132 | optional version-2 Cortex-M exception frame, R0-R12, fault/FPU registers, task stack bounds, and X/Y/Z/P/R homing phases/checkpoints |

`TAG_RESET_REG_CONTEXT` uses `RegulatorTelemetry.h` flag bits (`active`, `homing`, `resetting`, `motion_hold`, `quiet`, `stepping`, `inactive_hold`, `motion_hold_wdg`, `recovery_hold`) and event codes for start/pause, motion-hold enter/exit, home/reset begin/end, quiet begin/end, inner-limit, step-limit, and safety-home transitions.

### Retained fault context

`CrashLog.c` stores `CrashFaultContextRetained` in the linker `NOLOAD` `.noinit` section. The wrapper contains magic, version, size, and an FNV-1a checksum. Fault entry clears magic first, writes the 132-byte context and checksum, executes a memory barrier, and commits magic last. Boot accepts this context whenever the wrapper validates, including after healthy recovery clears `pending`; the existing 20-register RTC record remains the fallback. A healthy boot preserves it. Power/low-power reset classification and a newer incompatible base fault clear it under the existing retention rules.

HardFault, MemManage, BusFault, and UsageFault use GCC naked entries in `stm32f4xx_it.c`. Their first instructions select MSP or PSP from `EXC_RETURN`, save R4-R11, and pass both stack pointers to the non-returning capture path. R0-R3, R12, LR, PC, and xPSR always begin at the hardware-supplied SP. `EXC_RETURN` bit 4 changes only the validated allocation from 8 to 26 words. A core frame is marked valid only when the complete allocation is within registered stack/linker RAM bounds, xPSR has the Thumb bit, and PC is within linker-defined flash or `.RamFunc` executable bounds. Capture also stores CFSR, HFSR, MMFAR, BFAR, FPCCR, FPCAR, CONTROL, BASEPRI, PRIMASK, and FAULTMASK. Configurable fault enables are unchanged.

The version-2 TLV is little-endian. Bytes 0-3 are version, fault kind, task ID, and active command; bytes 4-5 are 16-bit flags; bytes 6-10 are X/Y/Z/P/R phases; bytes 11-15 are X/Y/Z/P/R checkpoints; and bytes 16-19 are CONTROL, BASEPRI, PRIMASK, and FAULTMASK. The remaining 28 words are `EXC_RETURN`, active SP, MSP, PSP, matched stack low/high, R0-R12, LR, PC, xPSR, CFSR, HFSR, MMFAR, BFAR, FPCCR, and FPCAR. Flags identify semantic core-frame validity, extended FPU allocation, task-stack match, valid MMFAR/BFAR, handler mode, stack-allocation validity, saved R4-R11/FPU state, executable PC, Thumb xPSR, and valid checkpoints. Updated hosts also decode 112-byte version-1 records and apply PC/xPSR plausibility checks; unknown or malformed versions are ignored independently of the rest of the report. The maximum report with both optional contexts is 252 bytes. `INCLUDE_uxTaskGetStackHighWaterMark` remains disabled.

`CrashLog_TriggerHardFaultForTest()` and `CrashLog_TriggerExtendedFrameHardFaultForTest()` are debugger-only: neither has a protocol, command, or UI entrypoint. The extended variant executes `vmov s0, s0` before `udf` to exercise the 26-word FPU frame. On a motion-disabled bench, invoke it from a debugger, reconnect, and export the reset bundle. Preserve the exact ELF and map used for the flashed binary, then resolve the captured PC with:

```powershell
arm-none-eabi-addr2line -e firmware/Debug/LabCraft_firmware.elf -f -C 0x08001235
```

Reset-report tags share numeric values with status tags, for example `0x20` / `0x21`, but the tag namespaces are separated by frame opcode (`CMD_RESET_REPORT` vs `CMD_STATUS`).

### 6.5 Status telemetry tags (`Comm.h` constants)

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
| `0x90` | `TAG_ORCH_STACK_HWM` | yes | `Orchestrator::getOrchStackHwmWords()` |
| `0x91` | `TAG_ORCH_STACK_PHASE` | yes | `Orchestrator::getOrchStackPhase()` |
| `0x92` | `TAG_ORCH_STACK_CMD` | yes | `Orchestrator::getOrchStackCmdNum()` |

### 6.6 Golden vector opportunities for `tests_host`

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
   - Regulator calibration can request custom selector `2110` through `--pressure-trace-custom` with channel, pressure, pulse width, pulse count, and frequency arguments; fixed selectors `2101`-`2104` remain unchanged.

Notes:

- `Comm.h` declares `onRxByte/onRxBytes`, `txWrite`, and `sendFramed`, but current `Comm.cpp` send/parse paths are through `HAL_UART_RxCpltCallback`, `handlePacket`, `sendFrame`, and `sendAckWithSeq32`.
- `comm_usb_bridge.h` declares USB bridge hooks; implementations are not present in current `Core/Src` tree.
