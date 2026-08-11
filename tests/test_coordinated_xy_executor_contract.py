from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_pure_executor_has_no_hal_rtos_float_or_dynamic_runtime_dependency():
    header = _read("firmware/Core/Inc/CoordinatedXyExecutor.h")
    source = _read("firmware/Core/Src/CoordinatedXyExecutor.cpp")
    combined = header + source

    for forbidden in (
        "stm32", "HAL_", "FreeRTOS", "cmsis_os", "taskENTER", "float ",
        "double ", "cos(", "malloc", "calloc", "operator new", "throw ",
    ):
        assert forbidden not in combined
    assert "#include \"CoordinatedXyPlanner.h\"" in header
    assert "LC_COORDINATED_XY_EXECUTOR_ENABLE 1" in header
    assert "LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE 0" in header
    assert "#error \"Coordinated XY normal routing requires" in header


def test_hardware_adapter_routes_owned_tim2_and_limits_before_legacy_handlers():
    stepper = _read("firmware/Core/Src/Stepper.cpp")
    gantry = _read("firmware/Core/Src/Gantry.cpp")

    dispatch = stepper.index("void Stepper::dispatch(TIM_HandleTypeDef* htim)")
    coordinated_dispatch = stepper.index("Gantry::dispatchCoordinatedTimerFromIsr(htim)", dispatch)
    legacy_loop = stepper.index("for (int i = 0; i < NUM_AXES; ++i)", dispatch)
    assert coordinated_dispatch < legacy_loop
    assert "Gantry::requestCoordinatedLimitAbortFromIsr(_axis);" in stepper
    assert "htim == _coordinatedY->_htim" in gantry
    assert "htim != _coordinatedMasterTimer" in gantry
    assert "BIT_STEPPER1_DONE | BIT_STEPPER2_DONE" in gantry


def test_reservations_precede_gpio_changes_and_failed_y_reservation_rolls_back_x():
    gantry = _read("firmware/Core/Src/Gantry.cpp")
    start = gantry.index("CoordinatedStartStatus Gantry::startCoordinatedXY")
    reserve_x = gantry.index("sx->_tryReserveCoordinated()", start)
    reserve_y = gantry.index("sy->_tryReserveCoordinated()", reserve_x)
    rollback_x = gantry.index("sx->_releaseCoordinatedReservation();", reserve_y)
    stop_timers = gantry.index("HAL_TIM_Base_Stop_IT(sx->_htim);", reserve_y)
    prepare_x = gantry.index("sx->_prepareCoordinatedAxis", stop_timers)

    assert reserve_x < reserve_y < rollback_x < stop_timers < prepare_x
    assert "reservedTargetX" in gantry
    assert "reservedTargetY" in gantry
    assert gantry.count("sx->_isLimitAsserted() || sy->_isLimitAsserted()") == 2


def test_coordinated_edge_and_terminal_paths_use_bounded_register_operations():
    stepper = _read("firmware/Core/Src/Stepper.cpp")
    gantry = _read("firmware/Core/Src/Gantry.cpp")

    write_step = stepper.index("void Stepper::_writeCoordinatedStep(bool high)")
    account_step = stepper.index("void Stepper::_accountCoordinatedPulse()", write_step)
    write_body = stepper[write_step:account_step]
    assert "->BSRR =" in write_body
    assert "HAL_GPIO_WritePin" not in write_body

    finish = gantry.index("void Gantry::_finishCoordinatedHardware(bool aborted)")
    finish_from_isr = gantry.index("void Gantry::_finishCoordinatedFromIsr", finish)
    finish_body = gantry[finish:finish_from_isr]
    assert "gantryStopAndClearUpdateTimer(_coordinatedMasterTimer)" in finish_body
    assert "HAL_TIM_Base_Stop_IT" not in finish_body

    stop_helper = gantry.index("void gantryStopAndClearUpdateTimer")
    stop_helper_end = gantry.index("bool coordinatedStartAccepted", stop_helper)
    assert "timer->State = HAL_TIM_STATE_READY;" in gantry[stop_helper:stop_helper_end]


def test_target_build_optimizes_only_the_bounded_coordinated_edge_path():
    executor = _read("firmware/Core/Src/CoordinatedXyExecutor.cpp")
    planner = _read("firmware/Core/Src/CoordinatedXyPlanner.cpp")
    gantry = _read("firmware/Core/Src/Gantry.cpp")
    stepper = _read("firmware/Core/Src/Stepper.cpp")

    assert '#define LC_COORDINATED_EDGE_OPTIMIZED __attribute__((optimize("O2"), hot))' in executor
    assert "LC_COORDINATED_EDGE_OPTIMIZED\nTickStatus onTimerUpdate" in executor
    assert '#define LC_COORDINATED_STEP_OPTIMIZED __attribute__((optimize("O2"), hot))' in planner
    assert "LC_COORDINATED_STEP_OPTIMIZED\nTraceStatus currentEvent" in planner
    assert "LC_COORDINATED_STEP_OPTIMIZED\nTraceStatus completeCurrentStep" in planner
    assert "LC_COORDINATED_STEP_OPTIMIZED\nbool planMatchesCursor" in planner
    assert "LC_COORDINATED_STEP_OPTIMIZED\nStepMask nextMask" in planner
    assert "LC_COORDINATED_STEP_OPTIMIZED\nvoid primeEvent" in planner
    assert "LC_COORDINATED_EDGE_OPTIMIZED\nuint32_t hashWord" in executor
    assert "LC_COORDINATED_EDGE_OPTIMIZED\nvoid setTerminal" in executor
    assert "LC_COORDINATED_EDGE_OPTIMIZED\nvoid setPlannerFault" in executor
    assert "LC_COORDINATED_EDGE_OPTIMIZED\nTickStatus applyDeferredControl" in executor
    assert "const uint8_t eventMask = static_cast<uint8_t>(cursor.cachedEvent.mask);" in planner
    assert "const uint8_t tickMask = static_cast<uint8_t>(tick.mask);" in gantry
    assert '#define LC_COORDINATED_HW_OPTIMIZED __attribute__((optimize("O2"), hot))' in gantry
    assert "LC_COORDINATED_HW_OPTIMIZED\nbool Gantry::_handleCoordinatedTimerFromIsr" in gantry
    assert "LC_COORDINATED_HW_OPTIMIZED\nuint32_t gantryCycleNow" in gantry
    assert "LC_COORDINATED_HW_OPTIMIZED\nvoid gantryStopAndClearUpdateTimer" in gantry
    assert '#define LC_COORDINATED_GPIO_OPTIMIZED __attribute__((optimize("O2"), hot))' in stepper
    assert "LC_COORDINATED_GPIO_OPTIMIZED\nvoid Stepper::_writeCoordinatedStep" in stepper
    assert "LC_COORDINATED_GPIO_OPTIMIZED\nvoid Stepper::_accountCoordinatedPulse" in stepper
    assert "LC_COORDINATED_GPIO_OPTIMIZED\nvoid Stepper::_finishCoordinatedAxis" in stepper


def test_xy_home_limits_hard_stop_without_debounce_or_task_scheduling():
    stepper = _read("firmware/Core/Src/Stepper.cpp")

    x_init = stepper.index('extern "C" void MX_STEPPERX_Init(void)')
    y_init = stepper.index('extern "C" void MX_STEPPERY_Init(void)', x_init)
    z_init = stepper.index('extern "C" void MX_STEPPERZ_Init(void)', y_init)
    assert "s1.setHomeHardStopOnLimit(true);" in stepper[x_init:y_init]
    assert "s2.setHomeHardStopOnLimit(true);" in stepper[y_init:z_init]
    assert "HAL_NVIC_SetPriority(_extiIRQn, 5, 0);" in stepper
    assert "HAL_NVIC_SetPriority(EXTI9_5_IRQn, 6, 0);" not in stepper

    tick = stepper.index("void Stepper::_stepTick()")
    profile_math = stepper.index("auto ease01", tick)
    hard_stop = stepper.index(
        "_homeHardStopOnLimit && (_limitSeenThisMove || _isLimitAsserted())", tick
    )
    assert tick < hard_stop < profile_math
    hard_stop_body = stepper[hard_stop:profile_math]
    assert "stop();" in hard_stop_body
    assert "(_togglesDone & 1u) != 0u" in hard_stop_body
    assert "_stepPort->BSRR" in hard_stop_body
    assert "xEventGroupSetBitsFromISR" in hard_stop_body

    raw_handler = stepper.index("void Stepper::_onLimitTriggeredFromIsr")
    debounce_handler = stepper.index("void Stepper::_debounceTimerCb", raw_handler)
    raw_body = stepper[raw_handler:debounce_handler]
    hard_stop_branch = raw_body.index("if (_homeHardStopOnLimit)")
    soft_stop_branch = raw_body.index("_requestSoftStop();", hard_stop_branch)
    assert "stop();" not in raw_body[hard_stop_branch:soft_stop_branch]


def test_executor_diagnostic_uses_sequential_low_rate_xy_homing_and_cancels_timeout():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    suite_start = diagnostics.index("if (runCoordinatedXyExecutorSuite)")
    suite_end = diagnostics.index("if (runMotionTimingSuite)", suite_start)
    suite = diagnostics[suite_start:suite_end]

    assert "kXyHomeFastHz = 3000u" in suite
    assert "kXyHomeSlowHz = 1000u" in suite
    assert "runSequentialXyHome" in suite
    assert 'sendProgressStage("coord_x_home_low")' in suite
    assert 'sendProgressStage("coord_y_home_low")' in suite
    assert "runXyHomeDiagnosticAttempt" not in suite
    assert "orchestrator.cancelActiveHomesForPause();" in diagnostics


def test_executor_diagnostic_measures_teardown_home_against_established_zero():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    suite_start = diagnostics.index("if (runCoordinatedXyExecutorSuite)")
    suite_end = diagnostics.index("if (runMotionTimingSuite)", suite_start)
    suite = diagnostics[suite_start:suite_end]
    drift_start = suite.index("const uint32_t xHomeDrift")
    drift_end = suite.index("const bool homeDriftPass", drift_start)
    drift = suite[drift_start:drift_end]

    assert "xHomeAfter.limitTriggerSteps, 0" in drift
    assert "yHomeAfter.limitTriggerSteps, 0" in drift
    assert "xHomeBefore.limitTriggerSteps" not in drift
    assert "yHomeBefore.limitTriggerSteps" not in drift


def test_executor_diagnostic_requires_stationary_manual_limit_preflight_before_motion():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    suite_start = diagnostics.index("if (runCoordinatedXyExecutorSuite)")
    suite_end = diagnostics.index("if (runMotionTimingSuite)", suite_start)
    suite = diagnostics[suite_start:suite_end]

    preflight = suite.index("auto runXyLimitSwitchPreflight")
    z_home = suite.index('runZClearanceHomePreflight("coord_z_clearance_home"')
    assert preflight < z_home
    assert "stepperX->disableMotor();" in suite[preflight:z_home]
    assert "stepperY->disableMotor();" in suite[preflight:z_home]
    for stage in (
        "coord_x_limit_press",
        "coord_x_limit_release",
        "coord_y_limit_press",
        "coord_y_limit_release",
    ):
        assert f'waitForOperatorResume("{stage}")' in suite[preflight:z_home]
    assert suite[preflight:z_home].count("isLimitAssertedForDiagnostics()") == 4
    assert 'emitSkippedExecutor(2040u, "limit_switch_preflight")' in suite


def test_diagnostic_is_explicit_full_selector_without_protocol_shape_change():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    runner = _read("tools/run_selftest.py")

    for test_id in range(2040, 2047):
        assert f"{{{test_id}u," in diagnostics
    assert "selectedDiagnosticId == 2049u" in diagnostics
    assert "2049 if coordinated_xy_executor_suite" in runner
    assert 'add_argument("--coordinated-xy-executor-suite", action="store_true")' in runner


def test_host_prompts_for_each_non_motion_limit_preflight_stage():
    runner = _read("tools/run_selftest.py")
    for stage in (
        "coord_x_limit_press",
        "coord_x_limit_release",
        "coord_y_limit_press",
        "coord_y_limit_release",
    ):
        assert f'"{stage}"' in runner
    assert "if _is_operator_prompt_stage(stage)" in runner
