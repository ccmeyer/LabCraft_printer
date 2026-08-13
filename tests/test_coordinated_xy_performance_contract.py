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
    assert "MotionUnitScale::quantizeDisplacement(initialX, dx)" in gantry
    assert "MotionUnitScale::toNativeRate" in gantry
    assert "MotionUnitScale::toNativeAcceleration" in gantry
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


def test_performance_report_is_strict_fixed_two_edge_conditional():
    header = _read("firmware/Core/Inc/CoordinatedXyPerformanceReport.h")
    source = _read("firmware/Core/Src/CoordinatedXyPerformanceReport.cpp")
    assert "observation.expectedMasterSteps * 2u" in source
    assert "observation.timer2Callbacks - 1u" in source
    assert "kConditionalGuardTicks" in source
    assert "moveCanContinueAfterCompletion" not in header + source
    assert "qualificationFailure" not in header + source
    assert "aggregate.exactAndSafe" in source
    assert "kMoveFailureScheduleSaturation" in header
    assert "kMoveFailureTerminalReason" in header


def test_diagnostics_exposes_only_production_xy_direct_lut_and_camera_selectors():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    assert "selectedDiagnosticId == 2097u" in diagnostics
    assert "selectedDiagnosticId == 2096u" in diagnostics
    assert "selectedDiagnosticId == 2078u" in diagnostics
    for selector in (2049, 2059, 2069, 2075, 2076, 2077, 2079, 2084, 2085, 2086):
        assert f"selectedDiagnosticId == {selector}u" not in diagnostics
    assert "runProductionCoordinatedDiagnostic" in diagnostics
    assert "runDirectXyzLutSuite" in diagnostics


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
    assert "10u,\n                                53416u" in suite
    assert "90000u" in suite
    assert "110000u" in suite
    assert "aggregate.timer2Callbacks == 220000u" in suite
    assert "aggregate.conditionalDecisionCount == 219990u" in suite
    assert "aggregate.timerRearmPendingCount == 0u" in suite


def test_production_results_use_reduced_metric_contract():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    for result_id in (2087, 2088, 2089, 2090):
        assert f"runOne({result_id}u" in diagnostics
    assert '"i2=%lu;s=%lu;mi=%lu;am=%lu;tm=%lu;fm=%lu;pu=%lu;"' in diagnostics
    assert '"ds=%lu;di=%lu;md=%lu;sl=%lu;dc=%lu;ci=%lu;ns=%lu;"' in diagnostics
    production_suite = diagnostics[
        diagnostics.index("if (runCoordinatedXyPerformanceSuite)") :
        diagnostics.index("if (runDirectXyzLutSuite)")
    ]
    for removed_metric in ("qf=", "qm=", "hm=", "sm=", "lf=", "ic=", "ix="):
        assert removed_metric not in production_suite


def test_camera_transition_uses_production_scaling_and_direct_home_counts():
    diagnostics = _read("firmware/Core/Src/Diagnostics.cpp")
    assert "aggregate, 2u, 8416u, 30000u, 30000u, limits" in diagnostics
    assert "homeIsr.totalEntries == 101u" in diagnostics
    assert "homeIsr.completedPulses == 50u" in diagnostics
    assert 'runOne(2071u' in diagnostics


def test_active_v2_manifests_match_remaining_selectors_and_reduced_metrics():
    production = json.loads(
        _read("tools/qualification/manifests/coordinated_xy_production_mres3_v2.json")
    )
    camera = json.loads(
        _read("tools/qualification/manifests/coordinated_xy_camera_transition_v2.json")
    )
    assert production["lifecycle"] == "active"
    assert production["expected_test_ids"] == [2087, 2088, 2089, 2090]
    assert production["analysis_rules"]["2089"]["metrics"]["dc"]["equals"] == 219990
    assert production["analysis_rules"]["2089"]["metrics"]["rp"]["equals"] == 0
    assert camera["lifecycle"] == "active"
    assert camera["analysis_rules"]["2071"]["metrics"]["xe"]["equals"] == 8416
    assert camera["analysis_rules"]["2071"]["metrics"]["hi"]["equals"] == 101


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
        "coordinated_xy_camera_transition_v1",
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
