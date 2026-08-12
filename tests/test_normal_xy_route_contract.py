from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_normal_route_is_enabled_but_retains_compile_time_legacy_override():
    header = _read("firmware/Core/Inc/CoordinatedXyExecutor.h")
    gantry = _read("firmware/Core/Src/Gantry.cpp")

    assert "#ifndef LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE" in header
    assert "#define LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE 1" in header
    assert "#if LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE != 0" in gantry
    assert "return startCoordinatedXY(" in gantry
    assert "return moveBy(static_cast<int32_t>(dx)" in gantry


def test_gantry_returns_real_start_status_without_fake_completion_bits():
    gantry = _read("firmware/Core/Src/Gantry.cpp")
    move_to_start = gantry.index("CoordinatedStartStatus Gantry::moveTo")
    move_by_start = gantry.index("CoordinatedStartStatus Gantry::moveBy", move_to_start)
    move_to = gantry[move_to_start:move_by_start]

    assert "return startCoordinatedXY(" in move_to
    assert "xEventGroupSetBits" not in move_to
    assert "feedHz" in move_to
    assert "0u" in move_to
    assert "sx->isBusy()" in gantry
    assert "sy->isBusy()" in gantry


def test_mixed_xyz_is_rejected_before_motion_state_can_change():
    gantry = _read("firmware/Core/Src/Gantry.cpp")
    move_by_start = gantry.index("CoordinatedStartStatus Gantry::moveBy")
    start_coordinated = gantry.index("CoordinatedStartStatus Gantry::startCoordinatedXY", move_by_start)
    move_by = gantry[move_by_start:start_coordinated]

    reject = move_by.index("if (dz != 0 && (dx != 0 || dy != 0))")
    first_motion = min(
        move_by.index("startCoordinatedXY", reject),
        move_by.index("MX_STEPPERX_Move", reject),
    )
    assert reject < first_motion
    assert "CoordinatedStartStatus::UnsupportedMixedAxis" in move_by[reject:first_motion]


def test_raw_limit_sampling_precedes_any_new_coordinated_edge():
    stepper = _read("firmware/Core/Inc/Stepper.h")
    gantry = _read("firmware/Core/Src/Gantry.cpp")
    handler_start = gantry.index("bool Gantry::_handleCoordinatedTimerFromIsr")
    handler_end = gantry.index("bool Gantry::dispatchCoordinatedTimerFromIsr", handler_start)
    handler = gantry[handler_start:handler_end]

    x_sample = handler.index("_coordinatedX->_coordinatedLimitAssertedFast()")
    y_sample = handler.index("_coordinatedY->_coordinatedLimitAssertedFast()")
    edge = handler.index("CoordinatedXyExecutor::onTimerUpdate")
    assert x_sample < edge
    assert y_sample < edge
    assert "_coordinatedRawLimitAbortCount" in handler
    assert "observedLimit == CoordinatedXyExecutor::ControlDisposition::StopNow" in handler
    fast_start = stepper.index("_coordinatedLimitAssertedFast")
    fast_end = stepper.index("// your existing members", fast_start)
    fast_body = stepper[fast_start:fast_end]
    assert "__attribute__((always_inline)) inline bool" in stepper
    assert "_limPort->IDR" in fast_body
    assert "HAL_GPIO_ReadPin" not in fast_body


def test_coordinated_isr_tiny_bookkeeping_helpers_are_forced_inline():
    gantry = _read("firmware/Core/Src/Gantry.cpp")

    assert "#define LC_COORDINATED_HW_ALWAYS_INLINE" in gantry
    assert "LC_COORDINATED_HW_ALWAYS_INLINE\nuint32_t gantryCycleNow()" in gantry
    assert "LC_COORDINATED_HW_ALWAYS_INLINE\nvoid Gantry::_observeCoordinatedArr" in gantry


def test_abs_xy_operation_uses_one_all_bits_wait_and_fail_closed_validation():
    orchestrator = _read("firmware/Core/Src/Orchestrator.cpp")
    operation_start = orchestrator.index(
        "Orchestrator::AbsoluteXyExecutionResult Orchestrator::executeAbsoluteXy"
    )
    operation_end = orchestrator.index(
        "bool Orchestrator::validateResumedAbsoluteXy", operation_start
    )
    operation = orchestrator[operation_start:operation_end]

    assert "waitForBits(BIT_STEPPER1_DONE | BIT_STEPPER2_DONE)" in operation
    assert "waitForBit(BIT_STEPPER1_DONE" not in operation
    assert "evaluateAbsXyCompletion" in operation
    assert "snapshot.terminalReason" in operation
    assert "result.endpointMatches" in operation
    assert "result.targetsMatch" in operation
    assert "terminalFailure" in operation
    assert "exitMotionHold" in operation
    assert "latchXyMotionFailure(reason)" in operation


def test_failure_latch_blocks_resume_and_only_safe_recovery_clears_it():
    orchestrator = _read("firmware/Core/Src/Orchestrator.cpp")

    assert "if (_xyMotionFailureLatched)" in orchestrator
    assert "Resume ignored while motion failure is latched" in orchestrator
    assert "if (clearSettled)" in orchestrator
    assert "clearXyMotionFailure();" in orchestrator
    assert "performShutdown" in orchestrator
    shutdown = orchestrator[orchestrator.index("void Orchestrator::performShutdown"):]
    assert "clearXyMotionFailure();" in shutdown


def test_normal_route_diagnostic_is_explicit_bounded_and_keeps_protocol_shape():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    runner = _read("tools/run_selftest.py")
    suite_start = diagnostics.index("if (runNormalXyRouteSuite)")
    suite_end = diagnostics.index("if (runMotionTimingSuite)", suite_start)
    suite = diagnostics[suite_start:suite_end]

    for test_id in range(2050, 2058):
        assert f"{{{test_id}u," in diagnostics
        assert f"{test_id}u" in suite
    assert "selectedDiagnosticId == 2059u" in diagnostics
    assert "2059 if normal_xy_route_suite" in runner
    assert 'add_argument("--normal-xy-route-suite", action="store_true")' in runner
    assert "kPhysicalLimitWindowSteps = 200u" in suite
    assert "targetX = axis == Stepper::X_AXIS ? -100" in suite
    assert "targetY = axis == Stepper::Y_AXIS ? -100" in suite
    assert "before.finalBackoffSteps != 100" in suite
    assert "runXyLimitSwitchPreflight" in suite
    assert 'waitForOperatorResume("normal_route_envelope_clear")' in suite
    assert "before.limitTriggerSteps" in suite
    assert "result.rehomeLimitSteps = after.limitTriggerSteps" in suite
    assert "xLimit.rehomeLimitSteps" in suite
    assert "yLimit.rehomeLimitSteps" in suite
    assert suite.count("metrics_overflow") >= 5


def test_debug_size_optimization_is_limited_to_explicit_m4_and_m5_suites():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")

    assert diagnostics.count('optimize("Os"), noinline') == 2
    runner_signature = "DiagnosticsSummary DiagnosticsRunner::runSelfTest"
    runner_start = diagnostics.index(runner_signature)
    first_suite = diagnostics.index('optimize("Os"), noinline', runner_start)
    assert 'optimize("Os")' not in diagnostics[runner_start:first_suite]


def test_no_application_or_protocol_source_was_added_to_milestone_scope():
    milestone = _read("docs/coordinated_xy_milestone5_normal_route.md")
    assert "No opcode, frame, TLV, status payload, or host application API changes" in milestone
    assert "LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE=0" in milestone
