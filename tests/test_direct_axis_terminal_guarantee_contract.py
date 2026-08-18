from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_direct_gantry_commands_share_the_terminal_execution_helper():
    source = _read("firmware/Core/Src/Orchestrator.cpp")
    execute_start = source.index("void Orchestrator::executeCommand(")
    orchestrator = source[execute_start:]

    for command in (
        "CMD_MOVE_X",
        "CMD_MOVE_Y",
        "CMD_MOVE_Z",
        "CMD_ABS_X",
        "CMD_ABS_Y",
        "CMD_ABS_Z",
    ):
        case_start = orchestrator.index(f"case {command}:")
        case_end = orchestrator.index("break;", case_start)
        assert "executeDirectAxis(" in orchestrator[case_start:case_end]

    assert "validateResumedDirectAxis(_lastPausedCmd)" in source
    assert "evaluateDirectMoveCompletion" in source
    assert "retireFailedAcceptedCommands" in source


def test_paused_direct_move_retains_the_original_terminal_contract():
    stepper = _read("firmware/Core/Src/Stepper.cpp")

    assert "_directMoveResumeSnapshot = paused" in stepper
    assert "paused.targetPosition" in stepper
    assert "_directMoveEmittedOffset + _totalToggles" in stepper
    assert "Do not leave STEP asserted across a pause" in stepper


def test_stepper_records_fault_before_signaling_direct_completion():
    stepper = _read("firmware/Core/Src/Stepper.cpp")

    limit_start = stepper.index("bool Stepper::_stopForConfirmedLimitFromIsr()")
    limit_end = stepper.index("// This should be called", limit_start)
    limit_path = stepper[limit_start:limit_end]
    assert limit_path.index("DirectMoveTerminalReason::LimitAborted") < limit_path.index("stop();")
    assert limit_path.index("DirectMoveTerminalReason::LimitAborted") < limit_path.index(
        "xEventGroupSetBitsFromISR"
    )

    profile_start = stepper.index("if (!DirectStepperProfile::nextSample(")
    profile_end = stepper.index("arr = static_cast<int32_t>(sample.arr);", profile_start)
    profile_path = stepper[profile_start:profile_end]
    assert "DirectMoveTerminalReason::ProfileFault" in profile_path
    assert "_targetPos = _pos" not in profile_path


def test_existing_limit_escape_policy_is_direction_aware():
    policy = _read("firmware/Core/Inc/StepperLimitPolicy.h")
    tests = _read("firmware/tests_host/tests/test_stepper_limit_policy.cpp")

    assert "EscapeAssertedLimit" in policy
    assert "RejectAssertedTowardLimit" in policy
    assert "RejectUntilReleased" in policy
    assert "DirectMoveMayEscapeAnAlreadyAssertedLimit" in tests
    assert "DirectMoveRejectsTowardAnAssertedLimit" in tests


def test_retained_context_shape_and_live_protocol_remain_unchanged():
    context = _read("firmware/Core/Inc/XyMotionFaultContext.h")
    orchestrator = _read("firmware/Core/Inc/Orchestrator.h")
    machine = _read("FreeRTOS-interface/Machine_FreeRTOS.py")

    assert "XY_MOTION_FAULT_CONTEXT_VERSION 1u" in context
    assert "XY_MOTION_FAULT_CONTEXT_WIRE_SIZE 60u" in context
    assert "XY_MOTION_FAULT_Z_LIMIT = 7" in context
    assert "CMD_REL_XY = 0x0D" in orchestrator
    assert '"RELATIVE_XY"' not in machine[machine.index("GANTRY_TERMINAL_COMMAND_TYPES") :][
        :500
    ]
