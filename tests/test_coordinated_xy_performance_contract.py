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
    assert "selectedDiagnosticId == 2076u" in diagnostics
    assert "selectedDiagnosticId == 2077u" in diagnostics
    assert "selectedDiagnosticId == 2075u" in diagnostics
    assert "selectedDiagnosticId == 2085u" in diagnostics
    assert "selectedDiagnosticId == 2079u" in diagnostics
    assert "selectedDiagnosticId == 2078u" in diagnostics
    assert "2069 if coordinated_xy_performance_suite" in runner
    assert "2076 if coordinated_xy_status_sync_suite" in runner
    assert "2077 if coordinated_xy_40khz_suite" in runner
    assert "2075 if coordinated_xy_single_irq_suite" in runner
    assert "2085 if coordinated_xy_mres3_20khz_suite" in runner
    assert "2079 if coordinated_xy_x_direction_suite" in runner
    assert "2078 if coordinated_xy_camera_transition_suite" in runner
    assert 'add_argument("--coordinated-xy-performance-suite", action="store_true")' in runner
    assert 'add_argument("--coordinated-xy-status-sync-suite", action="store_true")' in runner
    assert 'add_argument("--coordinated-xy-40khz-suite", action="store_true")' in runner
    assert 'add_argument("--coordinated-xy-single-irq-suite", action="store_true")' in runner
    assert 'add_argument("--coordinated-xy-mres3-20khz-suite", action="store_true")' in runner
    assert 'add_argument("--coordinated-xy-mres3-rearm-suite", action="store_true")' in runner
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

    assert "runCoordinatedXyFocusedGeometrySuite ? 4u : 0u" in suite
    assert "!runCoordinatedXyFocusedGeometrySuite &&" in suite
    assert '"coordinated_xy_40khz_envelope_clear"' in suite
    assert 'runOne(2064u,\n                                         "coordinated_xy_performance_40khz"' in suite
    standalone_exit = suite.index(
        "if (runCoordinatedXyFocusedGeometrySuite) {",
        suite.index("for (uint32_t tier")
    )
    m1_start = suite.index("Aggregate m1Aggregate")
    assert standalone_exit < m1_start
    assert "restoreXyRates();" in suite[standalone_exit:m1_start]
    assert "return finishSelfTestNow();" in suite[standalone_exit:m1_start]
    assert "runCoordinatedXyMres3Suite ? 2081u : 2072u" in suite
    assert "emitIrqPathEvidence(" in suite
    assert '"ax=%lu;tf=%lu' in suite
    assert "runCoordinatedXyMres3Suite ? 2082u : 2073u" in suite
    assert "emitEntryLatenessEvidence(" in suite
    assert '"i2=%lu;s=%lu;mi=%lu;cm=%lu;ca=%lu;pm=%lu;"' in suite
    assert '"lc=%lu;dm=%lu;sm=%u;lf=%lu;sf=%lu;to=%lu;"' in suite
    assert '"la=%lu;ra=%lu;hm=%lu"' in suite
    assert "captureFirstFailure(" in suite
    assert "result.snapshot.terminalReason" in suite
    assert "result.snapshot.limitAbortRequestCount" in suite
    assert "result.snapshot.rawLimitAbortCount" in suite
    assert '"coord_xy_40khz_entry_lateness",\n                                false,' in suite


def test_single_irq_selector_is_retired_without_changing_the_two_edge_default():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    start = diagnostics.index("if (runCoordinatedXyPerformanceSuite)")
    end = diagnostics.index("if (runMotionTimingSuite)", start)
    suite = diagnostics[start:end]

    assert "runCoordinatedXySingleIrqSuite" in suite
    assert "requestedExecutionMode =\n                                CoordinatedXyExecutor::ExecutionMode::TwoEdge" in suite
    assert "class ScopedCoordinatedXyExecutionMode" in diagnostics
    guard_start = diagnostics.index("class ScopedCoordinatedXyExecutionMode")
    guard_end = diagnostics.index("static constexpr DiagnosticTestDescriptor", guard_start)
    guard = diagnostics[guard_start:guard_end]
    assert "~ScopedCoordinatedXyExecutionMode()" in guard
    assert "CoordinatedXyExecutor::ExecutionMode::TwoEdge" in guard
    retirement = suite.index('failRemaining(2060u, "single_irq_superseded")')
    fixture = suite.index("waitForOperatorResume(fixtureStage)")
    assert retirement < fixture


def test_mres3_diagnostic_selector_scales_geometry_rate_acceleration_and_homes():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    orchestrator = _read("firmware/Core/Src/Orchestrator.cpp")
    config = _read("firmware/Core/Inc/TMC2208Configuration.h")
    runner = _read("tools/run_selftest.py")
    start = diagnostics.index("if (runCoordinatedXyPerformanceSuite)")
    end = diagnostics.index("if (runMotionTimingSuite)", start)
    suite = diagnostics[start:end]

    assert "selectedDiagnosticId == 2085u" in diagnostics
    assert "selectedDiagnosticId == 2084u" in diagnostics
    assert "selectedDiagnosticId == 2086u" in diagnostics
    assert "runCoordinatedXy40KhzSuite || runCoordinatedXyMres3Suite" in diagnostics
    assert '"coordinated_xy_mres3_20khz_envelope_clear"' in suite
    assert "{{2500, 2500}, {12500, 2500}}" in suite
    assert "{{4458, 15250}, {250, 250}}" in suite
    assert "? 20000u : kRatesHz[tier]" in suite
    assert "? 70000.0f : savedXAcceleration" in suite
    assert "? 70000.0f : savedYAcceleration" in suite
    assert "? 53416u : 106832u" in suite
    assert "? 90000u : 180000u" in suite
    assert "? 110000u : 220000u" in suite
    assert "stepperP->getPosition() != pPositionBefore" in suite
    assert "stepperR->getPosition() != rPositionBefore" in suite
    assert "aggregate.deadlineSlackMinTicks >= 450u" in suite
    assert "aggregate.timer2Callbacks -\n                                     aggregate.moveCount" in suite
    assert "LC_TMC2208_DIAGNOSTIC_BUILD" in orchestrator
    assert "cmd.cmd != CMD_SELFTEST_START && cmd.cmd != CMD_DISABLE_MOTORS" in orchestrator
    assert "#define LC_TMC2208_MRES 2" in config
    assert "LC_TMC2208_DIAGNOSTIC_BUILD != 0 && LC_TMC2208_MRES == 3" in config
    assert "false,\n      true,\n      0x000000C1u" in config
    assert "2085 if coordinated_xy_mres3_20khz_suite" in runner
    assert "2084 if coordinated_xy_mres3_rearm_suite" in runner
    assert "2086 if coordinated_xy_mres3_conditional_rearm_suite" in runner


def test_mres3_rearm_selector_is_scoped_and_rebases_after_physical_edges():
    header = _read("firmware/Core/Inc/Gantry.h")
    gantry = _read("firmware/Core/Src/Gantry.cpp")
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")

    assert "RearmFromActualEdge = 1u" in _read(
        "firmware/Core/Inc/CoordinatedXyTimerSchedulePolicy.h"
    )
    assert "setCoordinatedTimerScheduleModeForDiagnostics" in header
    assert "Mode::FreeRunning" in gantry
    handler_start = gantry.index("bool Gantry::_handleCoordinatedTimerFromIsr")
    handler_end = gantry.index(
        "bool Gantry::dispatchCoordinatedTimerFromIsr", handler_start
    )
    handler = gantry[handler_start:handler_end]
    edge = handler.index("physicalEdgeEmitted = stepX || stepY")
    stop = handler.index("CLEAR_BIT(_coordinatedMasterTimer->Instance->CR1")
    reset = handler.index("__HAL_TIM_SET_COUNTER(_coordinatedMasterTimer, 0u)")
    clear_pending = handler.index("NVIC_ClearPendingIRQ(TIM2_IRQn)")
    restart = handler.index("SET_BIT(_coordinatedMasterTimer->Instance->CR1")
    assert edge < stop < reset < clear_pending < restart
    assert "_coordinatedTimerRearmPendingCount" in handler

    guard_start = diagnostics.index("class ScopedCoordinatedXyTimerScheduleMode")
    guard_end = diagnostics.index("class ScopedSelfTestEmissionPriority", guard_start)
    guard = diagnostics[guard_start:guard_end]
    assert "Mode::FreeRunning" in guard
    assert "~ScopedCoordinatedXyTimerScheduleMode" in guard
    assert '"coordinated_xy_mres3_rearm_envelope_clear"' in diagnostics
    assert "timer_schedule_unavailable" in diagnostics


def test_mres3_conditional_rearm_preserves_normal_order_and_bounds_injection():
    policy = _read("firmware/Core/Inc/CoordinatedXyTimerSchedulePolicy.h")
    header = _read("firmware/Core/Inc/Gantry.h")
    gantry = _read("firmware/Core/Src/Gantry.cpp")
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    runner = _read("tools/run_selftest.py")

    assert "ConditionalLateRearm = 2u" in policy
    assert "kConditionalGuardTicks = 1125u" in policy
    assert "kInjectionTargetSlackTicks = 900u" in policy
    assert "kInjectionMaxCoreCycles = 4500u" in policy
    assert "isInjectionPhaseEligible" in policy
    assert "armCoordinatedLateServiceInjectionForDiagnostics" in header
    assert "shouldAttemptInjection" in gantry
    assert "_coordinatedPlan.cruiseSteps" in gantry
    assert "injectionWaitExpired" in gantry
    assert "timerCount > timerArr" in gantry
    assert "NVIC_ClearPendingIRQ(TIM2_IRQn)" in gantry
    assert "intentionalWaitCycles" in gantry
    assert '"coord_xy_conditional_rearm"' in diagnostics
    assert "kExpectedDecisions = 219990u" in diagnostics
    assert 'add_argument("--coordinated-xy-mres3-conditional-rearm-suite"' in runner


def test_mres3_complete_row_collection_is_scoped_and_keeps_strict_results():
    report = _read("firmware/Core/Src/CoordinatedXyPerformanceReport.cpp")
    header = _read("firmware/Core/Inc/CoordinatedXyPerformanceReport.h")
    gantry = _read("firmware/Core/Src/Gantry.cpp")
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")

    assert "kMoveFailureScheduleSaturation = 1u << 29" in header
    assert "kMoveFailureTerminalReason = 1u << 30" in header
    assert "moveCanContinueAfterCompletion" in report
    assert "qualificationFailureMoveCount" in report
    assert "qualificationFailureMask" in report
    assert '"qm=%lu;sf=%lu' in report
    assert "collectCompletedMres3Evidence" in diagnostics
    assert "runCoordinatedXyMres3BaselineSuite ||" in diagnostics
    collection_start = diagnostics.index("const bool collectCompletedMres3Evidence")
    collection_end = diagnostics.index(";", collection_start)
    collection_scope = diagnostics[collection_start:collection_end]
    assert "runCoordinatedXyMres3BaselineSuite" in collection_scope
    assert "runCoordinatedXyMres3ConditionalRearmSuite" in collection_scope
    assert "runCoordinatedXyMres3RearmSuite" not in collection_scope
    assert "? forward.canContinue" in diagnostics
    assert "? forward.canContinue && reverse.canContinue" in diagnostics
    assert "aggregate,\n                                forward.observation" in diagnostics
    assert "MoveResult reverse = observeCompletedMove" in diagnostics
    assert "classifyMove(forward);" in diagnostics
    assert "classifyMove(reverse);" in diagnostics
    assert '"la=%lu;ra=%lu;hm=%lu"' in diagnostics

    dispatch = gantry.index("bool Gantry::_handleCoordinatedTimerFromIsr")
    body = gantry.index("bool Gantry::_handleCoordinatedTim2BodyFromIsr", dispatch)
    assert dispatch < body
    assert "_handleCoordinatedTim2BodyFromIsr<true>()" in gantry[dispatch:body]
    assert "_handleCoordinatedTim2BodyFromIsr<false>()" in gantry[dispatch:body]
    assert "recordSampleExcludingIntentionalWait" in gantry[body:]
    assert "recordSample(" in gantry[body:]


def test_status_sync_variant_is_static_bounded_and_restores_critical_mode():
    header = _read("firmware/Core/Inc/Comm.h")
    comm = _read("firmware/Core/Src/Comm.cpp")
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")

    assert "enum class StatusMetricsSyncMode : uint8_t" in header
    assert "CriticalSection = 0u" in header
    assert "TaskMutex = 1u" in header
    assert "StaticSemaphore_t _statusMetricsMutexStorage" in header
    assert "xSemaphoreCreateMutexStatic(&_statusMetricsMutexStorage)" in comm
    assert "pdMS_TO_TICKS(5u)" in comm
    assert "_statusMetricsSyncMode = StatusMetricsSyncMode::CriticalSection" in comm
    assert "if (!guard.acquired()) return false;" in comm
    assert "if (!guard.acquired()) return;" in comm
    assert "if (_statusMetricsLockFailures != 0xFFFFFFFFu)" in comm
    assert "StatusMetricsSnapshot Comm::getStatusMetricsSnapshot()" in comm

    reset_start = comm.index("bool Comm::resetStatusMetrics()")
    reset_end = comm.index("Comm::StatusMetricsSnapshot", reset_start)
    reset = comm[reset_start:reset_end]
    assert reset.index("if (!guard.acquired()) return false;") < reset.index(
        "s_statusChunk0Count = 0"
    )
    record_start = comm.index("void Comm::recordStatusSend")
    record_end = comm.index("void Comm::statusTask", record_start)
    record = comm[record_start:record_end]
    assert record.index("if (!guard.acquired()) return;") < record.index(
        "s_statusChunk0Count++"
    )

    guard_start = diagnostics.index("class ScopedStatusMetricsSyncMode")
    guard_end = diagnostics.index("static constexpr DiagnosticTestDescriptor", guard_start)
    guard = diagnostics[guard_start:guard_end]
    assert "Comm::resetStatusMetricsLockFailures();" in guard
    assert "Comm::setStatusMetricsSyncMode(mode)" in guard
    assert "Comm::StatusMetricsSyncMode::CriticalSection" in guard
    assert "~ScopedStatusMetricsSyncMode()" in guard

    suite_start = diagnostics.index("if (runCoordinatedXyPerformanceSuite)")
    suite_end = diagnostics.index("if (runMotionTimingSuite)", suite_start)
    suite = diagnostics[suite_start:suite_end]
    assert "runCoordinatedXyStatusSyncSuite" in suite
    assert "Comm::StatusMetricsSyncMode::TaskMutex" in suite
    assert "status_sync_unavailable" in suite
    assert "statusMetrics.lockFailures == 0u" in suite
    assert "lockFailures == 0u" in suite


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
    assert "g_lcCoordinatedTim2IrqEntryTimerCount = TIM2->CNT" in handler[before_start:before_end]
    assert "g_lcCoordinatedTim2IrqEntryTimerArr = TIM2->ARR" in handler[before_start:before_end]
    assert "g_lcCoordinatedTim2IrqEntryTimerValid = 1u" in handler[before_start:before_end]
    assert "MX_GANTRY_RecordTim2IrqExit(DWT->CYCCNT)" in handler[after_start:after_end]
    gantry_handler_start = gantry.index("bool Gantry::_handleCoordinatedTimerFromIsr")
    gantry_handler_end = gantry.index("bool Gantry::dispatchCoordinatedTimerFromIsr", gantry_handler_start)
    gantry_handler = gantry[gantry_handler_start:gantry_handler_end]
    pending_check = gantry_handler.index("__HAL_TIM_GET_FLAG(_coordinatedMasterTimer, TIM_FLAG_UPDATE)")
    consume_capture = gantry_handler.rindex("g_lcCoordinatedTim2IrqEntryTimerCount")
    aggregate_capture = gantry_handler.rindex("beginIrqPathSample")
    assert pending_check < consume_capture
    assert pending_check < aggregate_capture
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
    assert "kBaselineHomeGuardMarginSteps = 3000u" in suite
    assert "kBaselineXEnvelopeMaximumSteps = 45000u" in suite
    assert "kBaselineYEnvelopeMaximumSteps = 35000u" in suite
    assert "? 1500u : kBaselineHomeGuardMarginSteps" in suite
    assert "? 22500u : kBaselineXEnvelopeMaximumSteps" in suite
    assert "? 17500u : kBaselineYEnvelopeMaximumSteps" in suite
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
