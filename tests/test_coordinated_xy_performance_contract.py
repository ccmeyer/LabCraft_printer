from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_performance_suite_has_fixed_ids_selector_rates_and_fail_stop_totals():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    runner = _read("tools/run_selftest.py")
    start = diagnostics.index("if (runCoordinatedXyPerformanceSuite)")
    end = diagnostics.index("if (runMotionTimingSuite)", start)
    suite = diagnostics[start:end]

    for test_id in (*range(2060, 2069), 2070):
        assert f"{{{test_id}u," in diagnostics
        assert f"{test_id}u" in suite
    assert "selectedDiagnosticId == 2069u" in diagnostics
    assert "selectedDiagnosticId == 2077u" in diagnostics
    assert "selectedDiagnosticId == 2079u" in diagnostics
    assert "selectedDiagnosticId == 2078u" in diagnostics
    assert "2069 if coordinated_xy_performance_suite" in runner
    assert "2077 if coordinated_xy_40khz_suite" in runner
    assert "2079 if coordinated_xy_x_direction_suite" in runner
    assert "2078 if coordinated_xy_camera_transition_suite" in runner
    assert 'add_argument("--coordinated-xy-performance-suite", action="store_true")' in runner
    assert 'add_argument("--coordinated-xy-40khz-suite", action="store_true")' in runner
    assert 'add_argument("--coordinated-xy-x-direction-suite", action="store_true")' in runner
    assert 'add_argument("--coordinated-xy-camera-transition-suite", action="store_true")' in runner
    assert "60000 if coordinated_xy_performance_suite else 5000" in runner
    assert "5000u, 10000u, 20000u, 30000u, 40000u" in suite
    assert "106832u" in suite and "180000u" in suite and "220000u" in suite
    assert "29416u" in suite and "50000u" in suite and "61000u" in suite
    assert "90000u" in suite and "362000u" in suite and "412000u" in suite
    assert "84160u" in suite and "300000u" in suite
    assert "168000u" in suite
    assert "failRemaining" in suite
    assert "rate_tier" in suite and "raster" in suite and "camera_repeat" in suite

    position_start = suite.index("auto positionTo")
    position_end = suite.index("auto addPair", position_start)
    setup_positioning = suite[position_start:position_end]
    assert "snapshot.pendingUpdateCount == 0u" in setup_positioning
    assert "snapshot.xStepLow && snapshot.yStepLow" in setup_positioning
    assert "!snapshot.timerOwned" in setup_positioning
    assert "pendingObservations" not in setup_positioning
    assert "activeMaxCycles" not in setup_positioning
    assert "terminalMaxCycles" not in setup_positioning


def test_standalone_40khz_selector_reuses_only_existing_tier_four_and_exits():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    start = diagnostics.index("if (runCoordinatedXyPerformanceSuite)")
    end = diagnostics.index("if (runMotionTimingSuite)", start)
    suite = diagnostics[start:end]

    assert "runCoordinatedXy40KhzSuite ? 4u : 0u" in suite
    assert "!runCoordinatedXy40KhzSuite &&" in suite
    assert '"coordinated_xy_40khz_envelope_clear"' in suite
    assert 'runOne(2064u,\n                                         "coordinated_xy_performance_40khz"' in suite
    standalone_exit = suite.index(
        "if (runCoordinatedXy40KhzSuite) {", suite.index("for (uint32_t tier")
    )
    m1_start = suite.index("Aggregate m1Aggregate")
    assert standalone_exit < m1_start
    assert "restoreXyRates();" in suite[standalone_exit:m1_start]
    assert "return finishSelfTestNow();" in suite[standalone_exit:m1_start]
    assert 'runOne(2072u,' in suite
    assert "emitIrqPathEvidence(aggregate)" in suite
    assert '"ax=%lu;tf=%lu' in suite


def test_outer_tim2_instrumentation_stays_in_generated_user_blocks_and_brackets_hal():
    irq = _read("firmware/Core/Src/stm32f4xx_it.c")
    gantry = _read("firmware/Core/Src/Gantry.cpp")
    start = irq.index("void TIM2_IRQHandler(void)")
    end = irq.index("void TIM3_IRQHandler(void)", start)
    handler = irq[start:end]

    before_start = handler.index("/* USER CODE BEGIN TIM2_IRQn 0 */")
    before_end = handler.index("/* USER CODE END TIM2_IRQn 0 */")
    hal = handler.index("HAL_TIM_IRQHandler(&htim2);")
    after_start = handler.index("/* USER CODE BEGIN TIM2_IRQn 1 */")
    after_end = handler.index("/* USER CODE END TIM2_IRQn 1 */")
    assert before_start < before_end < hal < after_start < after_end
    assert "g_lcCoordinatedTim2IrqEntryCycle = DWT->CYCCNT" in handler[before_start:before_end]
    assert "MX_GANTRY_RecordTim2IrqExit(DWT->CYCCNT)" in handler[after_start:after_end]
    assert "completeIrqPath" in gantry


def test_performance_suite_has_only_the_combined_fixture_prompt_after_regression():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    start = diagnostics.index("if (runCoordinatedXyPerformanceSuite)")
    end = diagnostics.index("if (runMotionTimingSuite)", start)
    suite = diagnostics[start:end]

    assert suite.count("waitForOperatorResume(") == 1
    assert "coordinated_xy_performance_fixture_clear" in suite
    for required in (
        "coord_x_limit_press",
        "coord_x_limit_release",
        "coord_y_limit_press",
        "coord_y_limit_release",
    ):
        assert required not in suite
    assert "manual switch preflight and low-rate homing" in suite
    assert "normal_route_envelope_clear" not in suite


def test_performance_homing_is_step_bounded_and_preserves_failure_evidence():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    report_header = _read("firmware/Core/Inc/CoordinatedXyPerformanceReport.h")
    stepper_header = _read("firmware/Core/Inc/Stepper.h")
    start = diagnostics.index("if (runCoordinatedXyPerformanceSuite)")
    end = diagnostics.index("if (runMotionTimingSuite)", start)
    suite = diagnostics[start:end]

    assert "boundedHomeGuardSteps" in report_header
    assert "kHomeGuardMarginSteps = 3000u" in suite
    assert "kXEnvelopeMaximumSteps = 45000u" in suite
    assert "kYEnvelopeMaximumSteps = 35000u" in suite
    assert "stepper->setHomeGuardSteps(result.guardSteps)" in suite
    assert "stepper->setHomeGuardSteps(savedGuard)" in suite
    assert "cancelActiveHomesAndWait(homeBit)" in suite
    for field in (
        "coarseCommandSteps",
        "coarseAccountedSteps",
        "moveTimeoutCount",
        "limitSeen",
        "limitAsserted",
    ):
        assert field in stepper_header


def test_performance_has_direction_isolated_x_speed_and_acceleration_gate():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    start = diagnostics.index("if (runCoordinatedXyPerformanceSuite)")
    end = diagnostics.index("if (runMotionTimingSuite)", start)
    suite = diagnostics[start:end]
    focus_start = suite.index("auto runFocusedXDirectionQualification")
    focus_end = suite.index("for (uint32_t tier", focus_start)
    focus = suite[focus_start:focus_end]

    assert "{30000u, kFocusedNormalAcceleration," in focus
    assert "{35000u, kFocusedNormalAcceleration," in focus
    assert "{40000u, kFocusedReducedAcceleration," in focus
    assert "{40000u, kFocusedNormalAcceleration," in focus
    assert "kFocusedAwayPosition = 20100" in suite
    assert "kFocusedReducedAwayPosition = 24100" in suite
    assert "aggregate,\n                                  8u,\n                                  168000u" in focus
    assert "reaches a real 40 kHz cruise section" in focus
    assert 'runOne(2070u,' in focus
    assert "failureStage = 2u" in focus
    assert "moveFailureMask(" in focus
    assert '"case=%lu;dir=%lu;fs=%lu;fm=%lu;n=%lu;xe=%lu;"' in focus
    assert "failureStage == 3u" in focus
    assert 'failRemaining(2064u, "x_direction")' in suite
    assert "if (runCoordinatedXyDirectionSuite)" in suite
    assert "return finishSelfTestNow();" in suite[focus_end:]


def test_performance_integration_does_not_change_limit_or_homing_semantics():
    gantry = _read("firmware/Core/Src/Gantry.cpp")
    handler_start = gantry.index("bool Gantry::_handleCoordinatedTimerFromIsr")
    handler_end = gantry.index("bool Gantry::dispatchCoordinatedTimerFromIsr", handler_start)
    handler = gantry[handler_start:handler_end]

    x_limit = handler.index("_coordinatedX->_coordinatedLimitAssertedFast()")
    y_limit = handler.index("_coordinatedY->_coordinatedLimitAssertedFast()")
    edge = handler.index("CoordinatedXyExecutor::onTimerUpdate")
    timing = handler.index("CoordinatedXyIsrInstrumentation::recordSample")
    assert x_limit < edge and y_limit < edge
    assert timing > x_limit and timing > y_limit
    assert "startHomeAsync" not in gantry


def test_camera_transition_diagnostic_is_single_pair_immediate_home_and_fail_stop():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    stepper = _read("firmware/Core/Inc/Stepper.h")
    start = diagnostics.index("auto runCameraHomeTransitionQualification")
    end = diagnostics.index("if (runCoordinatedXyDirectionSuite)", start)
    focused = diagnostics[start:end]

    assert "{8916, 30500}, {500, 500}" in focused
    assert "setMaxSpeedHz(5000u)" in focused
    assert "setMaxSpeedHz(40000u)" in focused
    assert "addPair(aggregate, kCameraPair, 40000u)" in focused
    assert "enableOutputsAssertedForDiagnostics" in focused
    assert "coordinated_xy_camera_transition_x_home" in focused
    assert focused.index("addPair(aggregate") < focused.index("runBoundedAxisHome(")
    assert "aggregate,\n                                  2u,\n                                  16832u,\n                                  60000u" in focused
    assert 'runOne(2071u,' in focused
    assert 'failRemaining(2072u, "camera_home_transition")' in focused
    assert "_enPort->ODR" in stepper and "_enPort2->ODR" in stepper


def test_instrumentation_hot_recording_uses_only_bounded_integer_operations():
    source = _read("firmware/Core/Src/CoordinatedXyIsrInstrumentation.cpp")
    assert '#pragma GCC optimize("O2")' in source
    assert "LC_XY_ISR_INSTRUMENTATION_ALWAYS_INLINE" in source
    assert "constexpr uint32_t kUint32Max" in source
    record_start = source.index("void recordSample")
    record_end = source.index("Snapshot makeSnapshot", record_start)
    hot = source[record_start:record_end]

    for forbidden in ("cos(", "float", "double", "new ", "malloc", "free(", "%", " / "):
        assert forbidden not in hot
    assert "saturatingIncrement" in hot
    assert "saturatingAdd" in hot
    assert "completeSampleTiming" in hot


def test_performance_report_accepts_only_the_expected_single_dwt_wrap():
    header = _read("firmware/Core/Inc/CoordinatedXyPerformanceReport.h")
    source = _read("firmware/Core/Src/CoordinatedXyPerformanceReport.cpp")

    assert "uint32_t maxCycleWrapsPerMove = 1u;" in header
    assert "timing.cycleWraps > limits.maxCycleWrapsPerMove" in source
    assert "aggregate.cycleWraps <= aggregate.moveCount" in source


def test_performance_completion_uses_the_all_bits_wait_result():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    orchestrator = _read("firmware/Core/Src/Orchestrator.cpp")
    start = diagnostics.index("if (runCoordinatedXyPerformanceSuite)")
    end = diagnostics.index("if (runMotionTimingSuite)", start)
    suite = diagnostics[start:end]

    assert "observation.completionTogether = completed;" in suite
    assert "xEventGroupWaitBits(\n            _doneEvents, completionBits, pdTRUE, pdTRUE" in orchestrator


def test_performance_reference_drift_and_status_cadence_use_valid_observation_windows():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    start = diagnostics.index("if (runCoordinatedXyPerformanceSuite)")
    end = diagnostics.index("if (runMotionTimingSuite)", start)
    suite = diagnostics[start:end]

    drift_start = suite.index("auto homeAndMeasureDrift")
    drift_end = suite.index("auto emitAggregate", drift_start)
    drift = suite[drift_start:drift_end]
    assert "xAfter.limitTriggerSteps, 0" in drift
    assert "yAfter.limitTriggerSteps, 0" in drift
    assert "xReference.limitTriggerSteps" not in drift
    assert "yReference.limitTriggerSteps" not in drift

    position_start = suite.index("auto positionTo")
    position_end = suite.index("auto addPair", position_start)
    assert "comm->setStatusPaused(false);" in suite[position_start:position_end]
    home_start = suite.index("auto runSequentialXyHome")
    home_end = suite.index("MotionQualificationMath::AxisHomeSample xReference", home_start)
    assert "comm->setStatusPaused(false);" in suite[home_start:home_end]
    emit_start = suite.index("auto emitAggregate")
    emit_end = suite.index("for (uint32_t tier", emit_start)
    assert "comm->setStatusPaused(true);" in suite[emit_start:emit_end]


def test_pressure_case_uses_direct_gantry_route_and_restores_safe_paths():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    start = diagnostics.index("Aggregate pressureAggregate")
    end = diagnostics.index("return finishSelfTestNow();", start)
    pressure = diagnostics[start:end]

    assert "gantry->moveTo(target.x, target.y, 0u)" in diagnostics
    assert "regP.setTargetSafe(kPressure2Raw)" in pressure
    assert "regR.setTargetSafe(kPressure2Raw)" in pressure
    assert "pForwardMoved" in pressure and "rForwardMoved" in pressure
    assert "pressureChecksumsMatch" in pressure
    assert "rejectDeltaP == 0u" in pressure
    assert "pressureFault" in pressure
    assert "closePressurePaths();" in pressure
    assert "pressureAggregate.cycleWraps" in pressure
