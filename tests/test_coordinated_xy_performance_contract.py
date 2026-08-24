import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_schedule_policy_is_one_fixed_conditional_contract():
    policy = _read("firmware/Core/Inc/CoordinatedXyTimerSchedulePolicy.h")
    assert "kConditionalGuardTicks = 1125u" in policy
    assert "remainingTicks <= kConditionalGuardTicks" in policy
    assert "updatePending || timerCount > timerArr" in policy
    assert "return {true, false, false, 0u}" in policy
    for retired in (
        "enum class Mode",
        "FreeRunning",
        "RearmFromActualEdge",
        "ConditionalLateRearm",
        "Injection",
    ):
        assert retired not in policy


def test_production_mres3_and_motion_unit_scaling_are_fixed():
    config = _read("firmware/Core/Inc/TMC2208Configuration.h")
    scale = _read("firmware/Core/Inc/MotionUnitScale.h")
    gantry = _read("firmware/Core/Src/Gantry.cpp")
    stepper = _read("firmware/Core/Src/Stepper.cpp")

    assert "kMres = 3u" in config
    assert "doubleEdge = true" in config
    assert "multistepFilter = false" in config
    assert "0x30000053u" in config
    assert "static_cast<uint32_t>(kMres) << 24u" in config
    assert "LC_TMC2208" not in config
    assert "logicalUnitsPerNativeStepForMres" in scale
    assert "mres == 3u ? 2u : 1u" in scale
    assert "TMC2208Configuration::kMres" in scale
    assert "coordinatedActiveEdgesPerNativeStep" in scale
    assert "logicalUnitsPerCoordinatedActiveEdge" in scale
    assert "toCoordinatedActiveEdges" in gantry
    assert "MotionUnitScale::quantizeDisplacement(initialX, dx)" in gantry
    coordinated_start = gantry[gantry.index("CoordinatedStartStatus Gantry::startCoordinatedXY"):]
    assert "MotionUnitScale::toNativeRate" not in coordinated_start
    assert "MotionUnitScale::toNativeAcceleration" not in coordinated_start
    assert "MotionUnitScale::quantizeDisplacement(_pos, requestedDelta)" in stepper
    assert "MotionUnitScale::toNativeRate(freqHz)" in stepper
    assert "MotionUnitScale::toNativeAcceleration(_accel_sps2)" in stepper


def test_complete_step_injection_and_runtime_schedule_modes_are_removed():
    files = "\n".join(
        _read(path)
        for path in (
            "firmware/Core/Inc/CoordinatedXyExecutor.h",
            "firmware/Core/Src/CoordinatedXyExecutor.cpp",
            "firmware/Core/Inc/Gantry.h",
            "firmware/Core/Src/Gantry.cpp",
            "firmware/Core/Inc/CoordinatedXyIsrInstrumentation.h",
            "firmware/Core/Src/CoordinatedXyIsrInstrumentation.cpp",
        )
    )
    for retired in (
        "CompleteStep",
        "lateInjection",
        "intentionalWait",
        "recordCompleteStepPulse",
        "setCoordinatedTimerScheduleModeForDiagnostics",
        "setCoordinatedExecutionModeForDiagnostics",
    ):
        assert retired not in files


def test_status_metrics_use_one_short_critical_section_implementation():
    header = _read("firmware/Core/Inc/Comm.h")
    source = _read("firmware/Core/Src/Comm.cpp")
    combined = header + source
    assert "StatusMetricsSyncMode" not in combined
    assert "statusMetricsMutex" not in combined
    assert "StatusMetricsGuard" in source
    assert "taskENTER_CRITICAL" in source
    assert "taskEXIT_CRITICAL" in source
    assert "resetStatusMetrics" in source
    assert "getStatusMetricsSnapshot" in source


def test_isr_telemetry_keeps_bounded_maxima_and_drops_experiment_sums():
    header = _read("firmware/Core/Inc/CoordinatedXyIsrInstrumentation.h")
    for retained in (
        "totalCallbacks",
        "pendingObservations",
        "maxPendingStreak",
        "phaseMaxCycles",
        "terminalMaxCycles",
        "terminalStageSamples",
        "terminalTotalCycles",
        "worstTerminalCommonCycles",
        "worstTerminalShutdownCycles",
        "worstTerminalInstrumentationCycles",
        "fullIrqMaxCycles",
        "entryTimerSamples",
        "entryTimerMissing",
        "entryTimerCountMax",
        "deadlineMisses",
        "deadlineSlackMinTicks",
        "saturationFlags",
    ):
        assert retained in header
    for removed in (
        "phaseCycleSums",
        "terminalCycleSum",
        "preHandlerCycleSum",
        "fullIrqCycleSum",
        "entryTimerCountSum",
        "MeanCycles",
        "completeStepPulse",
        "intentionalWait",
    ):
        assert removed not in header


def test_performance_report_is_strict_active_edge_conditional():
    header = _read("firmware/Core/Inc/CoordinatedXyPerformanceReport.h")
    source = _read("firmware/Core/Src/CoordinatedXyPerformanceReport.cpp")
    assert "observation.timer2Callbacks != observation.expectedMasterEdges" in source
    assert "timing.activeEdgeEvents != observation.expectedMasterEdges" in source
    assert "observation.cleanupEdgeEvents != 0u" in source
    assert "observation.edgeSpacingViolations != 0u" in source
    assert "kConditionalGuardTicks" in source
    assert "moveCanContinueAfterCompletion" not in header + source
    assert "qualificationFailure" not in header + source
    assert "aggregate.exactAndSafe" in source
    assert "kMoveFailureScheduleSaturation" in header
    assert "kMoveFailureTerminalReason" in header
    assert "canContinueAfterTerminalBudgetOnlyFailure" in header + source
    assert "timing.terminalStageSamples != 1u" in source
    assert "kCoordinatedTerminalHandlerBudgetCycles = 3500u" in header
    assert "terminalMaxCycles = kCoordinatedTerminalHandlerBudgetCycles" in header


def test_shallow_suite_uses_fixed_finite_profile_expectations():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    report = _read("firmware/Core/Src/CoordinatedXyPerformanceReport.cpp")
    assert "shallowMoveTimingExpectation" in diagnostics + report
    assert "requireShallowExpectation" in diagnostics
    assert "kMoveFailureSelectedRate" in diagnostics
    for value in (
        "10000u", "17100u", "19574u", "36986u", "2432u", "12160u",
        "39571u", "2273u", "11365u", "8999u", "44995u",
    ):
        assert value in report


def test_diagnostics_exposes_production_shallow_direct_lut_and_camera_selectors():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    assert "selectedDiagnosticId == 2097u" in diagnostics
    assert "selectedDiagnosticId == 2096u" in diagnostics
    assert "selectedDiagnosticId == 2109u" in diagnostics
    assert "selectedDiagnosticId == 2078u" in diagnostics
    assert "selectedDiagnosticId == 2099u" in diagnostics
    assert '2100u, "coord_xy_terminal_timing"' in diagnostics
    for selector in (2049, 2059, 2069, 2075, 2076, 2077, 2079, 2084, 2085, 2086):
        assert f"selectedDiagnosticId == {selector}u" not in diagnostics
    assert "runProductionCoordinatedDiagnostic" in diagnostics
    assert "runDirectXyzLutSuite" in diagnostics


def test_pause_resume_qualification_settles_home_and_opens_status_windows():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    start = diagnostics.index("auto runMotionPauseResumeQualification")
    end = diagnostics.index("if (runMotionPauseResumeSuite)", start)
    suite = diagnostics[start:end]

    for axis in ("z", "xy"):
        settle = suite.index(f'pause_resume_{axis}_settle_home')
        reference = suite.index(f'pause_resume_{axis}_reference_home')
        assert settle < reference
    assert 'emitSkipped("settle_home")' in suite
    assert suite.count("(void)Comm::resetStatusMetrics();") == 2
    assert suite.count("comm->setStatusPaused(false);") == 2
    assert suite.count("comm->setStatusPaused(true);") == 2


def test_production_suite_freezes_geometry_counts_and_strict_evidence():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    start = diagnostics.index("if (runCoordinatedXyPerformanceSuite)")
    end = diagnostics.index("if (runDirectXyzLutSuite)", start)
    suite = diagnostics[start:end]
    for point in (
        "{{5000, 5000}, {25000, 5000}}",
        "{{5000, 5000}, {5000, 25000}}",
        "{{5000, 5000}, {25000, 25000}}",
        "{{5000, 5000}, {10000, 25000}}",
        "{{8916, 30500}, {500, 500}}",
    ):
        assert point in suite
    assert "10u,\n                                106832u" in suite
    assert "180000u" in suite
    assert "220000u" in suite
    assert "aggregate.timer2Callbacks == 220000u" in suite
    assert "aggregate.conditionalDecisionCount == 219990u" in suite
    assert "aggregate.timerRearmPendingCount == 0u" in suite


def test_production_results_use_reduced_metric_contract():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    for result_id in (2087, 2088, 2089, 2090, 2098, 2106, 2107, 2105):
        assert f"runOne({result_id}u" in diagnostics
    assert '"i2=%lu;s=%lu;mi=%lu;am=%lu;tm=%lu;fm=%lu;pu=%lu;"' in diagnostics
    assert '"ds=%lu;di=%lu;md=%lu;sl=%lu;dc=%lu;ci=%lu;ns=%lu;"' in diagnostics
    production_suite = diagnostics[
        diagnostics.index("if (runCoordinatedXyPerformanceSuite)") :
        diagnostics.index("if (runDirectXyzLutSuite)")
    ]
    shallow_start = production_suite.rindex("if (runCoordinatedXyShallowEdgeSuite)")
    shallow_end = production_suite.index("if (runCoordinatedXyTransitionSuite)", shallow_start)
    production_suite = production_suite[:shallow_start] + production_suite[shallow_end:]
    for removed_metric in ("qf=", "qm=", "hm=", "sm=", "lf=", "ic=", "ix="):
        assert removed_metric not in production_suite


def test_xy_motion_limits_use_edge_aware_tim5_confirmation_without_raw_stop():
    policy = _read("firmware/Core/Inc/MotionLimitDebouncePolicy.h")
    header = _read("firmware/Core/Inc/Stepper.h")
    stepper = _read("firmware/Core/Src/Stepper.cpp")
    gantry = _read("firmware/Core/Src/Gantry.cpp")
    timer = _read("firmware/Core/Src/MotionLimitDebounceTimer.cpp")
    main = _read("firmware/Core/Src/main.c")
    interrupts = _read("firmware/Core/Src/stm32f4xx_it.c")
    pressure = _read("firmware/Core/Src/PressureRegulator.cpp")

    assert "kDebounceMs = 15u" in policy
    assert "enum class Phase" in policy
    assert "Idle = 0u" in policy
    assert "Pending = 1u" in policy
    assert "Confirmed = 2u" in policy
    assert "kHardwareDebounceUs = kDebounceMs * 1000u" in policy
    assert "noteHardwareTransition" in policy
    assert "evaluateHardwareExpiry" in policy
    assert "TickType_t    debounceMs" not in header
    assert '"LmtDbnc"' in stepper  # Z/P/R retain the software-timer path.
    assert "GPIO_MODE_IT_RISING_FALLING" in stepper
    assert "MotionLimitDebounceTimer::attach" in stepper
    assert "s1.attachLimitSwitch(GPIOG, GPIO_PIN_6);" in stepper
    assert "s2.attachLimitSwitch(GPIOG, GPIO_PIN_9);" in stepper
    assert "s4.attachLimitSwitch(GPIOG, GPIO_PIN_11);" in stepper
    assert "s5.attachLimitSwitch(GPIOG, GPIO_PIN_12);" in stepper
    assert "GPIO_PIN_10,\n                       true,\n                       StepperLimitPolicy::PullMode::None" in stepper

    raw_exti = stepper[
        stepper.index("void Stepper::_onRawLimitInterruptFromIsr()") :
        stepper.index("void Stepper::handleExtiFromIsr", stepper.index("void Stepper::_onRawLimitInterruptFromIsr()"))
    ]
    assert "_limitSeenThisMove = true" not in raw_exti
    assert "requestCoordinatedLimitAbort" not in raw_exti
    assert "stop()" not in raw_exti
    assert "_observeLimitLevelFromIsr" in raw_exti
    assert "MotionLimitDebounceTimer::onExtiFromIsr" in raw_exti
    assert "_takeConfirmedLimitFromIsr" in stepper
    assert "_takeConfirmedLimitFromIsr" in gantry
    assert "MotionLimitDebouncePolicy::Phase::Pending" not in gantry
    assert "_limitDebounceIgnoreUntilRelease" in gantry
    assert "kExpectedTickHz = 1000000u" in timer
    assert "TIM_IT_CC1" in timer
    assert "TIM_IT_CC2" in timer
    assert "TIM_IT_CC3" in timer
    assert "stickyTransition" in timer
    assert "closeUnmaskRace" in timer
    assert "MX_MotionLimitDebounceTimer_Init();" in main
    assert "void TIM5_IRQHandler(void)" in interrupts
    assert "pdMS_TO_TICKS(15)" in pressure


def test_coordinated_terminal_path_uses_one_optimized_debounce_completion():
    header = _read("firmware/Core/Inc/MotionLimitDebounceTimer.h")
    timer = _read("firmware/Core/Src/MotionLimitDebounceTimer.cpp")
    gantry = _read("firmware/Core/Src/Gantry.cpp")
    stepper = _read("firmware/Core/Src/Stepper.cpp")

    assert "void completeCoordinatedMoveFromIsr(int32_t xStoppedPosition" in header
    completion = timer[
        timer.index("void completeCoordinatedMoveFromIsr(") : timer.index(
            "void cancel(Axis axis",
            timer.index("void completeCoordinatedMoveFromIsr("),
        )
    ]
    assert '__attribute__((optimize("O2"), hot))' in timer
    assert "xState.confirmation.consumedPosition = xStoppedPosition" in completion
    assert "yState.confirmation.consumedPosition = yStoppedPosition" in completion
    assert "__HAL_TIM_DISABLE_IT(g_timer, TIM_IT_CC1 | TIM_IT_CC2)" in completion
    assert "__HAL_TIM_CLEAR_FLAG(g_timer, TIM_FLAG_CC1 | TIM_FLAG_CC2)" in completion
    assert "xState.moveGeneration = 0u" in completion
    assert "yState.moveGeneration = 0u" in completion
    assert "xState.debounce.phase == MotionLimitDebouncePolicy::Phase::Idle" in completion
    assert "yState.debounce.phase == MotionLimitDebouncePolicy::Phase::Idle" in completion
    assert "return;" in completion
    assert "xState.debounce.phase = MotionLimitDebouncePolicy::Phase::Idle" in completion
    assert "yState.debounce.phase = MotionLimitDebouncePolicy::Phase::Idle" in completion
    assert "EXTI->PR = mask" in completion
    assert "EXTI->IMR |= mask" in completion
    for out_of_line_helper in (
        "axisState(",
        "disableAxisCompare(",
        "cancelHardware(",
        "clearExti(",
        "unmaskExti(",
        "ExtiDebounce::lineMask(",
    ):
        assert out_of_line_helper not in completion

    isr_finish = gantry[
        gantry.index("void Gantry::_finishCoordinatedFromIsr(") : gantry.index(
            "bool Gantry::_handleCoordinatedTimerFromIsr(",
            gantry.index("void Gantry::_finishCoordinatedFromIsr("),
        )
    ]
    assert isr_finish.count(
        "MotionLimitDebounceTimer::completeCoordinatedMoveFromIsr("
    ) == 1
    assert "_finishCoordinatedHardware(aborted, true)" in isr_finish

    for name in (
        "_finishAbortedCoordinatedAxisFromLow",
        "_finishCompletedCoordinatedAxisFromLow",
    ):
        start = stepper.index(f"void Stepper::{name}()")
        end = stepper.index("\n}\n", start) + 2
        finalizer = stepper[start:end]
        assert "MotionLimitDebounceTimer::" not in finalizer
        assert "recordStopPositionFromIsr" not in finalizer
        assert "MotionLimitDebounceTimer::cancel(" not in finalizer


def test_xy_confirmation_clean_path_is_optimized_and_has_no_nested_policy_calls():
    header = _read("firmware/Core/Inc/Stepper.h")
    timer = _read("firmware/Core/Src/MotionLimitDebounceTimer.cpp")

    hardware_classifier = header[
        header.index("bool _usesHardwareLimitDebounce() const") : header.index(
            "bool _confirmReleasedForNextApproach(",
            header.index("bool _usesHardwareLimitDebounce() const"),
        )
    ]
    assert "__attribute__((always_inline))" in header[
        header.rindex("#if defined(__GNUC__)", 0, header.index("bool _usesHardwareLimitDebounce() const")) :
        header.index("bool _usesHardwareLimitDebounce() const")
    ]
    assert "_axis == X_AXIS || _axis == Y_AXIS" in hardware_classifier

    confirmation = timer[
        timer.index("bool takeConfirmedFromIsr(") : timer.index(
            "void recordStopPositionFromIsr(",
            timer.index("bool takeConfirmedFromIsr("),
        )
    ]
    assert '__attribute__((optimize("O2"), hot))' in timer[
        timer.rindex("#if defined(__GNUC__)", 0, timer.index("bool takeConfirmedFromIsr(")) :
        timer.index("bool takeConfirmedFromIsr(")
    ]
    assert "g_axes[axis == Axis::Y ? 1u : 0u]" in confirmation
    assert "state.moveGeneration == 0u" in confirmation
    assert "state.moveGeneration != moveGeneration" in confirmation
    assert "axisState(" not in confirmation
    assert "MotionLimitDebouncePolicy::hardwareGenerationMatches(" not in confirmation


def test_camera_transition_uses_production_scaling_and_direct_home_counts():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    assert "aggregate, 2u, 16832u, 60000u, 60000u, limits" in diagnostics
    assert "homeIsr.totalEntries == 101u" in diagnostics
    assert "homeIsr.completedPulses == 50u" in diagnostics
    assert 'runOne(2071u' in diagnostics


def test_shallow_suite_reports_the_exact_move_failure_mask_and_timing_maxima():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    suite = diagnostics[diagnostics.rindex("if (runCoordinatedXyShallowEdgeSuite)") :]
    suite = suite[: suite.index("if (runCoordinatedXyTransitionSuite)")]
    assert "tiers[0].moveFailureMask |" in suite
    assert "tiers[1].moveFailureMask" in suite
    assert "moveFailures == 0u" in suite
    assert '"tm=%lu;de=%lu;sg=%lu;wd=%lu;sf=%lu;to=%lu"' in suite
    assert "canContinueAfterTerminalBudgetOnlyFailure" in diagnostics
    assert "observePair(" in suite
    assert "if (!pairResult.safeToContinue)" in suite
    assert "completionTogether = execution.waitCompleted &&" in diagnostics
    assert "driversEnabled;" in diagnostics
    assert "const bool homePassed = motionSafeToContinue &&" in suite
    assert "tiers[0].terminalSampleCount == 12u" in suite
    assert "tiers[1].terminalSampleCount == 12u" in suite
    for metric in (
        "bl=%lu", "n1=%lu", "tl1=%lu", "ta1=%lu", "tm1=%lu", "ob1=%lu",
        "n2=%lu", "tl2=%lu", "ta2=%lu", "tm2=%lu", "ob2=%lu",
        "cm=%lu", "sm=%lu", "im=%lu", "pm=%lu", "fm=%lu", "av=%lu",
    ):
        assert metric in suite


def test_terminal_stage_timestamps_are_confined_to_completed_terminal_path():
    gantry = _read("firmware/Core/Src/Gantry.cpp")
    instrumentation = _read(
        "firmware/Core/Src/CoordinatedXyIsrInstrumentation.cpp"
    )
    assert "if (completedTerminal) terminalShutdownStartCycle = gantryCycleNow();" in gantry
    assert "if (completedTerminal) terminalShutdownEndCycle = gantryCycleNow();" in gantry
    assert "recordTerminalStages(" in gantry + instrumentation
    assert "stageTotal != static_cast<uint64_t>(totalCycles)" in instrumentation


def test_active_handler_budget_and_camera_failure_telemetry_are_shared():
    header = _read("firmware/Core/Inc/CoordinatedXyPerformanceReport.h")
    report = _read("firmware/Core/Src/CoordinatedXyPerformanceReport.cpp")
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    assert "kCoordinatedActiveHandlerRegressionBudgetCycles =\n    2600u" in header
    assert "activeMaxCycles =\n      kCoordinatedActiveHandlerRegressionBudgetCycles" in header
    assert "buildCameraTransitionMetrics(" in report + diagnostics
    assert '"hi=%lu;hpc=%lu;hpu=%lu;hd=%lu;mf=%lu;ab=%lu;am=%lu;tm=%lu;"' in report


def test_shallow_result_metrics_fit_frame_at_acceptance_domain_maxima():
    motion = (
        "h1=10000;h2=40000;n=24;xe=241592;ye=241592;me=430192;"
        "i2=430192;i7=0;ce=0;sv=0;en=1;xd=25;yd=25;ok=1;mf=0;"
        "am=2600;tm=3500;de=100;sg=100;wd=100;sf=0;to=0"
    )
    terminal = (
        "bl=3500;h1=10000;n1=12;tl1=3500;ta1=3500;tm1=3500;ob1=0;"
        "h2=40000;n2=12;tl2=3500;ta2=3500;tm2=3500;ob2=0;"
        "cm=3500;sm=3500;im=3500;pm=4294967295;fm=4294967295;av=0;sf=0"
    )
    assert len(motion) <= 230 - min(len("coord_xy_shallow_edge_distribution"), 32)
    assert len(terminal) <= 230 - min(len("coord_xy_terminal_timing"), 32)


def test_camera_transition_failure_metrics_fit_frame_with_exact_timing():
    metrics = (
        "fs=2;n=1;xe=8416;ye=30000;i2=30000;i7=0;pu=0;en=0;sl=1;ow=0;"
        "lb=0;hs=25000;he=100;hg=48000;hi=101;hpc=50;hpu=0;"
        "hd=4294967295;mf=4294967295;ab=2600;"
        "am=4294967295;tm=4294967295;sf=0;to=1"
    )
    assert len(metrics) <= 230 - min(len("coord_xy_camera_home_transition"), 32)


def test_windows_hil_wrapper_downloads_failure_report_before_exiting():
    script = _read("firmware/scripts/run_fw_hil_windows.ps1")
    remote = script.index("$remoteHilExitCode = $LASTEXITCODE")
    download = script.index('Write-Host "=== Download report ==="', remote)
    parse = script.index("$reportObj = Get-Content $localReport", download)
    summarize_failure = script.index("if ($failed -gt 0", parse)
    assert remote < download < parse < summarize_failure
    assert "attempting to download its failure report" in script
    assert "Pi flash/selftest failed with rc=$remoteHilExitCode and its report could not be downloaded" in script


def test_windows_hil_wrapper_uses_long_shallow_defaults_but_preserves_overrides():
    script = _read("firmware/scripts/run_fw_hil_windows.ps1")
    assert '$PSBoundParameters.ContainsKey("SelfTestTimeoutMs")' in script
    assert '$effectiveSelfTestTimeoutMs = 240000' in script
    assert '$PSBoundParameters.ContainsKey("StatusOnlyTimeoutMs")' in script
    assert '$effectiveStatusOnlyTimeoutMs = 120000' in script
    assert '"--selftest-timeout-ms", $effectiveSelfTestTimeoutMs' in script
    assert '"--status-only-timeout-ms", $effectiveStatusOnlyTimeoutMs' in script


def test_hil_wrappers_forward_confirmation_preauthorization_explicitly():
    windows = _read("firmware/scripts/run_fw_hil_windows.ps1")
    pi = _read("firmware/hil/flash_and_test.sh")

    assert "[switch]$PreauthorizeConfirmationPrompts" in windows
    assert "$PreauthorizeConfirmationPrompts.IsPresent" in windows
    assert '$flashArgs += "--preauthorize-confirmation-prompts"' in windows
    assert "PREAUTHORIZE_CONFIRMATION_PROMPTS=0" in pi
    assert "--preauthorize-confirmation-prompts) PREAUTHORIZE_CONFIRMATION_PROMPTS=1" in pi
    assert "cmd+=(--preauthorize-confirmation-prompts)" in pi


def test_active_coordinated_manifests_share_timing_budgets_and_archive_predecessors():
    production = json.loads(
        _read("tools/qualification/manifests/coordinated_xy_production_mres3_v7.json")
    )
    production_v6 = json.loads(
        _read("tools/qualification/manifests/coordinated_xy_production_mres3_v6.json")
    )
    camera = json.loads(
        _read("tools/qualification/manifests/coordinated_xy_camera_transition_v4.json")
    )
    camera_v3 = json.loads(
        _read("tools/qualification/manifests/coordinated_xy_camera_transition_v3.json")
    )
    shallow = json.loads(
        _read("tools/qualification/manifests/coordinated_xy_shallow_edge_v4.json")
    )
    shallow_v3 = json.loads(
        _read("tools/qualification/manifests/coordinated_xy_shallow_edge_v3.json")
    )
    assert production["lifecycle"] == "active"
    assert production_v6["lifecycle"] == "archived"
    assert production["expected_test_ids"] == [2087, 2088, 2089, 2090, 2098, 2106, 2107, 2105]
    assert production["analysis_rules"]["2087"]["metrics"]["xe"]["equals"] == 106832
    assert production["analysis_rules"]["2087"]["metrics"]["ye"]["equals"] == 180000
    assert production["analysis_rules"]["2087"]["metrics"]["me"]["equals"] == 220000
    assert production["analysis_rules"]["2087"]["metrics"]["ce"]["equals"] == 0
    assert production["analysis_rules"]["2087"]["metrics"]["sv"]["equals"] == 0
    assert production["analysis_rules"]["2087"]["metrics"]["am"]["max"] == 2600
    assert production["analysis_rules"]["2087"]["metrics"]["tm"]["max"] == 3500
    assert production["analysis_rules"]["2089"]["metrics"]["rp"]["equals"] == 0
    debounce = production["analysis_rules"]["2098"]["metrics"]
    assert debounce["db"]["equals"] == 15
    assert debounce["xf"]["equals"] == 0
    assert debounce["yf"]["equals"] == 0
    assert debounce["tv"]["equals"] == 1
    assert debounce["hz"]["equals"] == 1000000
    assert debounce["du"]["min"] == 15000
    assert debounce["du"]["max"] == 16000
    assert production["analysis_rules"]["2106"]["metrics"]["hz"]["equals"] == 40000
    assert production["analysis_rules"]["2107"]["metrics"]["hz"]["equals"] == 30000
    assert production["analysis_rules"]["2106"]["metrics"]["rs"]["equals"] == 3000
    assert production["analysis_rules"]["2107"]["metrics"]["rs"]["equals"] == 3000
    crossing = production["analysis_rules"]["2105"]["metrics"]
    assert crossing["n"]["equals"] == 2
    assert crossing["xb"]["max"] == 50
    assert crossing["yb"]["max"] == 50
    assert camera["lifecycle"] == "active"
    assert camera_v3["lifecycle"] == "archived"
    assert camera["analysis_rules"]["2071"]["metrics"]["xe"]["equals"] == 16832
    assert camera["analysis_rules"]["2071"]["metrics"]["hi"]["equals"] == 101
    assert camera["analysis_rules"]["2071"]["metrics"]["mf"]["equals"] == 0
    assert camera["analysis_rules"]["2071"]["metrics"]["ab"]["equals"] == 2600
    assert camera["analysis_rules"]["2071"]["metrics"]["am"]["max"] == 2600
    assert camera["analysis_rules"]["2071"]["metrics"]["tm"]["max"] == 3500
    assert "3,500-cycle" in camera["description"]
    assert shallow["lifecycle"] == "active"
    assert shallow_v3["lifecycle"] == "archived"
    assert shallow["analysis_rules"]["2099"]["metrics"]["am"]["max"] == 2600
    assert shallow["analysis_rules"]["2099"]["metrics"]["tm"]["max"] == 3500
    assert shallow["analysis_rules"]["2100"]["metrics"]["bl"]["equals"] == 3500


def test_historical_manifests_are_archived_without_deleting_catalog_data():
    archived = (
        "coordinated_xy_executor_v1",
        "normal_xy_route_v1",
        "coordinated_xy_performance_v1",
        "coordinated_xy_40khz_v1",
        "coordinated_xy_status_sync_v1",
        "coordinated_xy_single_irq_v1",
        "coordinated_xy_mres3_20khz_v1",
        "coordinated_xy_mres3_rearm_v1",
        "coordinated_xy_mres3_conditional_rearm_v3",
        "coordinated_xy_production_mres3_v1",
        "coordinated_xy_production_mres3_v2",
        "coordinated_xy_production_mres3_v3",
        "coordinated_xy_production_mres3_v4",
        "coordinated_xy_camera_transition_v1",
        "coordinated_xy_camera_transition_v2",
        "coordinated_xy_camera_transition_v3",
        "coordinated_xy_shallow_edge_v1",
        "coordinated_xy_shallow_edge_v2",
        "coordinated_xy_shallow_edge_v3",
    )
    catalog = _read("tools/qualification/test_catalog.py")
    for manifest_id in archived:
        payload = json.loads(
            _read(f"tools/qualification/manifests/{manifest_id}.json")
        )
        assert payload["lifecycle"] == "archived"
    for test_id in (2040, 2050, 2060, 2072, 2073, 2074, 2080, 2081, 2082, 2083):
        assert str(test_id) in catalog


def test_diagnostic_build_configuration_and_binary_are_removed():
    project = _read("firmware/.cproject")
    build_script = _read("firmware/scripts/build_firmware_headless.ps1")
    assert "MRES3_Diagnostic" not in project + build_script
    assert not (ROOT / "firmware/artifacts/LabCraft_firmware_mres3_diagnostic.bin").exists()


def test_headless_build_never_copies_an_artifact_after_a_failed_build():
    build_script = _read("firmware/scripts/build_firmware_headless.ps1")
    failure_gate = build_script.index("if ($exit -ne 0)")
    artifact_copy = build_script.index("Copy-Item")

    assert failure_gate < artifact_copy
    assert "artifact was not updated" in build_script
