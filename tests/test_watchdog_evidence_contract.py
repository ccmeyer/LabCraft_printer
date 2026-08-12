from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WATCHDOG_HEADER = REPO_ROOT / "firmware" / "Core" / "Inc" / "WatchdogSupervisor.h"
WATCHDOG_SOURCE = REPO_ROOT / "firmware" / "Core" / "Src" / "WatchdogSupervisor.c"
PRESSURE_SOURCE = REPO_ROOT / "firmware" / "Core" / "Src" / "PressureRegulator.cpp"
CRASHLOG_SOURCE = REPO_ROOT / "firmware" / "Core" / "Src" / "CrashLog.c"


def _function_body(source: str, signature: str) -> str:
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening + 1 : index]
    raise AssertionError(f"unterminated function: {signature}")


def test_watchdog_arm_modes_are_numeric_and_invalid_values_fail_compilation():
    header = WATCHDOG_HEADER.read_text(encoding="utf-8")

    assert "#define WATCHDOG_ARM_IMMEDIATE 0" in header
    assert "#define WATCHDOG_ARM_AFTER_HELLO_ACK 1" in header
    assert "#define LC_WATCHDOG_ARM_MODE WATCHDOG_ARM_AFTER_HELLO_ACK" in header
    assert "LC_WATCHDOG_ARM_MODE != WATCHDOG_ARM_IMMEDIATE" in header
    assert "LC_WATCHDOG_ARM_MODE != WATCHDOG_ARM_AFTER_HELLO_ACK" in header
    assert '#error "LC_WATCHDOG_ARM_MODE must select a supported watchdog arm mode"' in header

    source = WATCHDOG_SOURCE.read_text(encoding="utf-8")
    start_task = _function_body(source, "void Watchdog_StartTask(void)")
    assert "LC_WATCHDOG_ARM_MODE == WATCHDOG_ARM_IMMEDIATE" in start_task
    assert "Watchdog_Arm();" in start_task


def test_check_in_only_updates_the_participant_timestamp():
    source = WATCHDOG_SOURCE.read_text(encoding="utf-8")
    body = _function_body(source, "void Watchdog_CheckIn(CrashTaskId taskId)")

    assert "g_lastSeen[(uint32_t)taskId] = HAL_GetTick();" in body
    assert "g_enabledMask" not in body
    assert "taskENTER_CRITICAL" not in body


def test_participation_transitions_publish_mask_and_timestamp_atomically():
    source = WATCHDOG_SOURCE.read_text(encoding="utf-8")
    enable = _function_body(source, "void Watchdog_EnableTask(CrashTaskId taskId)")
    disable = _function_body(source, "void Watchdog_DisableTask(CrashTaskId taskId)")

    for body in (enable, disable):
        assert "taskENTER_CRITICAL();" in body
        assert "taskEXIT_CRITICAL();" in body
        assert "g_participationGeneration" in body
    assert enable.index("g_lastSeen[(uint32_t)taskId] = nowMs;") < enable.index(
        "WatchdogParticipation_Enable"
    )
    assert disable.index("WatchdogParticipation_Disable") < disable.index(
        "g_lastSeen[(uint32_t)taskId] = 0u;"
    )


def test_pressure_control_loop_checks_in_without_changing_participation():
    source = PRESSURE_SOURCE.read_text(encoding="utf-8")
    loop = _function_body(source, "void PressureRegulator::controlLoop()")
    release = _function_body(
        source,
        "void PressureRegulator::_releaseWatchdog(WatchdogHold reason, bool checkIn)",
    )

    loop_body = loop[loop.index("for (;;)") :]
    assert "_checkInWatchdogIfEligible();" in loop_body
    assert "_synchronizeWatchdogParticipation();" not in loop_body
    assert release.index("_synchronizeWatchdogParticipation();") < release.index(
        "_checkInWatchdogIfEligible();"
    )


def test_healthy_boot_clears_pending_without_erasing_fault_history():
    source = CRASHLOG_SOURCE.read_text(encoding="utf-8")
    body = _function_body(source, "void CrashLog_MarkBootHealthy(void)")

    assert "~CRASHLOG_FLAG_PENDING" in body
    assert "CRASHLOG_FLAG_VALID" in body
    assert "CRASHLOG_BKP_LAST_FAULT" not in body
    assert "CRASHLOG_BKP_LAST_TASK" not in body
    assert "CrashLog_ClearFaultContext" not in body


def test_non_exception_fault_paths_clear_incompatible_extended_context():
    source = CRASHLOG_SOURCE.read_text(encoding="utf-8")
    signatures = (
        "void CrashLog_RecordFault(CrashFaultKind kind, CrashTaskId taskIdHint)",
        "void CrashLog_RecordWatchdogFault(CrashTaskId lateTask)",
        "void CrashLog_RecordFaultFromHandler(CrashFaultKind kind, CrashTaskId taskIdHint)",
        "void CrashLog_RecordStackOverflowFromHook(CrashTaskId taskIdHint, const char* taskName)",
    )

    for signature in signatures:
        body = _function_body(source, signature)
        assert body.index("CrashLog_ClearFaultContext();") < body.index(
            "CrashLog_WriteFaultRecord("
        )
