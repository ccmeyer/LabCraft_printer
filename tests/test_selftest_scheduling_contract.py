from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_selftest_scheduler_selectors_and_default_cooperative_mode_are_local():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    assert "selectedDiagnosticId == 1039u" in diagnostics
    assert "selectedDiagnosticId == 1038u" in diagnostics
    assert "runSelfTestSchedulerNoYieldSuite" in diagnostics
    assert "SelfTestResultSchedulingMode::NoYield" in diagnostics
    assert ": SelfTestResultSchedulingMode::Cooperative" in diagnostics
    assert "vTaskDelay(pdMS_TO_TICKS(1u))" in diagnostics


def test_scheduler_results_are_safe_only_and_emitted_before_done():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    label = diagnostics.index("selftest_done:")
    context = diagnostics.index('sendResult(1044u, "pressure_wdg_context_safe"', label)
    scheduler = diagnostics.index('sendResult(1043u, "selftest_scheduler_safe"', context)
    done = diagnostics.index("DiagnosticResultEmitter::buildDonePayload", scheduler)
    assert label < context < scheduler < done
    assert "if (!request.fullProfile" in diagnostics[label:context]


def test_pressure_deadline_i2c_timeout_and_task_priority_remain_unchanged():
    watchdog = _read("firmware/Core/Src/WatchdogSupervisor.c")
    pressure = _read("firmware/Core/Src/PressureSensor.cpp")
    assert "case CRASH_TASK_PRESSURE: return 250u;" in watchdog
    assert "constexpr uint32_t kPressureI2cTimeoutMs = 20u;" in pressure
    assert "tskIDLE_PRIORITY+1" in pressure


def test_pressure_stack_headroom_is_sampled_only_at_diagnostic_snapshot():
    config = _read("firmware/Core/Inc/FreeRTOSConfig.h")
    pressure = _read("firmware/Core/Src/PressureSensor.cpp")
    assert "#define INCLUDE_uxTaskGetStackHighWaterMark     0" in config
    loop = pressure[pressure.index("void PressureSensor::taskLoop()"):
                    pressure.index("uint32_t PressureSensorWatchdog_BeginDiagnosticWindow")]
    assert "uxTaskGetStackHighWaterMark" not in loop
    snapshot = pressure[pressure.index("uint32_t PressureSensorWatchdog_GetSnapshot"):
                        pressure.index("void MX_PS_Init")]
    assert "vTaskGetInfo" in snapshot


def test_i2c_failure_timing_is_lightweight_and_failure_only():
    pressure = _read("firmware/Core/Src/PressureSensor.cpp")
    loop = pressure[pressure.index("void PressureSensor::taskLoop()"):
                    pressure.index("uint16_t PressureSensor::readSensorRaw")]
    receive = loop.index("readSensorRaw(port, &readStatus)")
    failure = loop.index("if (readStatus != HAL_OK)", receive)
    detail = loop.index("PressureSensorWatchdogTelemetry_NoteReadFailure", failure)
    assert "const uint32_t readStartMs = HAL_GetTick();" in loop[:receive]
    assert "const uint32_t readElapsedMs = HAL_GetTick() - readStartMs;" in loop[receive:failure]
    assert receive < failure < detail
    assert "Logger::instance" not in loop[failure:detail]

    telemetry = _read("firmware/Core/Inc/PressureSensorWatchdogTelemetry.h")
    assert "PRESSURE_SENSOR_WDG_RECOVERY_DELAY_TICKS 20u" in telemetry
    assert "PRESSURE_SENSOR_WDG_DURATION_MAX_MS 999u" in telemetry
    assert "const uint32_t readHalError = HAL_I2C_GetError(_hi2c);" in loop[failure:]


def test_pressure_fault_snapshot_is_captured_before_crash_record():
    watchdog = _read("firmware/Core/Src/WatchdogSupervisor.c")
    capture = watchdog.index("CrashLog_CapturePressureSensorContext(&pressureContext)")
    record = watchdog.index("CrashLog_RecordWatchdogFault(late)")
    assert capture < record


def test_scheduler_cli_selectors_are_mutually_exclusive(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/run_selftest.py"),
            "--selftest-scheduler-no-yield-suite",
            "--selftest-scheduler-cooperative-suite",
            "--out",
            str(tmp_path / "unused.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "not allowed with argument" in result.stderr


def test_existing_motion_selector_inventory_is_not_changed_by_scheduler_rows():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    scheduler_gate = diagnostics.index("if (!request.fullProfile", diagnostics.index("selftest_done:"))
    assert "runCoordinatedXySingleIrqSuite" not in diagnostics[scheduler_gate:scheduler_gate + 300]
    manifest = _read("tools/qualification/manifests/coordinated_xy_single_irq_v1.json")
    assert '"expected_test_ids": [2064, 2072, 2073, 2074]' in manifest
