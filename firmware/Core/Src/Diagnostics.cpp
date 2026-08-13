#if defined(__GNUC__)
#pragma GCC push_options
#pragma GCC optimize ("Os")
#endif

#include "BoardConfig.h"
#include "Diagnostics.h"
#include "CrashWatchdogSelfTestPolicy.h"
#include "DiagnosticResultEmitter.h"
#include "DirectStepperProfileReport.h"
#include "Orchestrator.h"
#include "OrchestratorCompletionPolicy.h"
#include "OrchestratorDecode.h"
#include "SelfTestCommandPolicy.h"
#include "LEDController.h"
#include "Stepper.h"
#include "Gripper.h"
#include "Printer.h"
#include "PressureRegulator.h"
#include "MotionQualificationMath.h"
#include "MotionUnitScale.h"
#include "NormalizedCosineProfile.h"
#include "StepperProfileMath.h"
#include "StepperInstrumentationReport.h"
#include "PressureRegulatorMath.h"
#include "PressureQualificationMath.h"
#include "GripperSealQualificationMath.h"
#include "PressureTargetPolicy.h"
#include "ValvePulseQualificationMath.h"
#include "PressureSensor.h"
#include "Logger.h"
#include "Gantry.h"
#include "CoordinatedXyPerformanceReport.h"
#include "Comm.h"
#include "CommCodec.h"
#include "CrashLog.h"
#include "WatchdogSupervisor.h"
#include "PressureTraceRecorder.h"
#include "PressureSensorWatchdogTelemetry.h"
#include "SelfTestSchedulingPolicy.h"
#include "TMC2208Driver.h"
#include "TMC2208Configuration.h"
#include "cmsis_os.h"
#include "task.h"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <limits>

#if (configUSE_PREEMPTION != 1) || (configUSE_TIME_SLICING != 1)
#error "Cooperative self-test emission requires preemptive FreeRTOS time slicing"
#endif

#if LC_HAS_IMAGING > 0
  #include "Flash.h"
  #include "Flash.hpp"
#endif

#if LC_HAS_LED_STRIP > 0
  #include "LEDStrip.h"
#endif

extern "C" uint32_t RTOS_StackOverflowHookFired(void);

namespace {

static constexpr uint16_t kPressureTraceCustomTestId = 2110u;
static constexpr uint16_t kTracePressureMilliPsiMin = 100u;
static constexpr uint16_t kTracePressureMilliPsiMax = 2500u;
static constexpr uint16_t kTracePulseUsMin = 100u;
static constexpr uint16_t kTracePulseUsMax = 10000u;
static constexpr uint16_t kTracePulseCountMin = 1u;
static constexpr uint16_t kTracePulseCountMax = 100u;
static constexpr uint16_t kTraceFrequencyHzMin = 1u;
static constexpr uint16_t kTraceFrequencyHzMax = 50u;
static constexpr uint32_t kTraceMaxPulseWindowMs = 10000u;

class ScopedStatusMetricsSyncMode {
public:
    explicit ScopedStatusMetricsSyncMode(Comm::StatusMetricsSyncMode mode) {
        Comm::resetStatusMetricsLockFailures();
        _activated = Comm::setStatusMetricsSyncMode(mode);
    }

    ~ScopedStatusMetricsSyncMode() {
        (void)Comm::setStatusMetricsSyncMode(
            Comm::StatusMetricsSyncMode::CriticalSection);
    }

    bool activated() const { return _activated; }

private:
    bool _activated = false;
};

class ScopedCoordinatedXyExecutionMode {
public:
    ScopedCoordinatedXyExecutionMode(
        Gantry* gantry,
        CoordinatedXyExecutor::ExecutionMode mode)
        : _gantry(gantry) {
        _activated = _gantry != nullptr &&
            _gantry->setCoordinatedExecutionModeForDiagnostics(mode);
    }

    ~ScopedCoordinatedXyExecutionMode() {
        if (_gantry != nullptr) {
            (void)_gantry->setCoordinatedExecutionModeForDiagnostics(
                CoordinatedXyExecutor::ExecutionMode::TwoEdge);
        }
    }

    bool activated() const { return _activated; }

private:
    Gantry* _gantry = nullptr;
    bool _activated = false;
};

class ScopedCoordinatedXyTimerScheduleMode {
public:
    ScopedCoordinatedXyTimerScheduleMode(
        Gantry* gantry,
        CoordinatedXyTimerSchedulePolicy::Mode mode)
        : _gantry(gantry),
          _previous(_gantry != nullptr
                        ? _gantry->coordinatedTimerScheduleMode()
                        : CoordinatedXyTimerSchedulePolicy::Mode::FreeRunning) {
        _activated = _gantry != nullptr &&
            _gantry->setCoordinatedTimerScheduleModeForDiagnostics(mode);
    }

    ~ScopedCoordinatedXyTimerScheduleMode() {
        if (_gantry != nullptr) {
            (void)_gantry->setCoordinatedTimerScheduleModeForDiagnostics(
                _previous);
        }
    }

    bool activated() const { return _activated; }

private:
    Gantry* _gantry = nullptr;
    CoordinatedXyTimerSchedulePolicy::Mode _previous =
        CoordinatedXyTimerSchedulePolicy::Mode::FreeRunning;
    bool _activated = false;
};

class ScopedSelfTestEmissionPriority {
public:
    explicit ScopedSelfTestEmissionPriority(SelfTestResultSchedulingMode mode)
        : _task(xTaskGetCurrentTaskHandle()),
          _originalPriority(uxTaskPriorityGet(_task)),
          _emissionPriority(static_cast<UBaseType_t>(
              SelfTestScheduling_SelectEmissionPriority(
                  mode, static_cast<uint32_t>(_originalPriority)))) {
        if (_emissionPriority != _originalPriority) {
            vTaskPrioritySet(_task, _emissionPriority);
            _changed = true;
        }
    }

    ~ScopedSelfTestEmissionPriority() {
        if (_changed) {
            vTaskPrioritySet(_task, _originalPriority);
        }
    }

private:
    TaskHandle_t _task = nullptr;
    UBaseType_t _originalPriority = tskIDLE_PRIORITY;
    UBaseType_t _emissionPriority = tskIDLE_PRIORITY;
    bool _changed = false;
};

static constexpr DiagnosticTestDescriptor kDiagnosticTests[] = {
    {1001u, "comm_crc_known_vector", "protocol", "SAFE", "always"},
    {1002u, "comm_frame_roundtrip", "protocol", "SAFE", "always"},
    {1010u, "session_hello_ack", "protocol", "SAFE", "always"},
    {1011u, "session_goodbye_ack", "protocol", "SAFE", "always"},
    {1012u, "session_goodbye_done", "protocol", "SAFE", "always"},
    {1003u, "status_frame_shape", "status", "SAFE", "always"},
    {1013u, "clear_queue_ack", "protocol", "SAFE", "always"},
    {1020u, "status_chunk_alternation_safe", "status", "SAFE", "always"},
    {1021u, "status_cadence_safe", "status", "SAFE", "always"},
    {1004u, "uptime_counter_read", "status", "SAFE", "always"},
    {1005u, "flash_config_readonly", "flash", "SAFE", "always"},
    {1007u, "flash_imaging_burst_diag_safe", "flash", "SAFE", "always"},
    {1006u, "fw_build_info", "build", "SAFE", "always"},
    {1030u, "uart_recovery_after_noise_safe", "protocol", "SAFE", "always"},
    {1040u, "rtos_memory_headroom_safe", "rtos", "SAFE", "always"},
    {1041u, "crash_record_retained_safe", "crash", "SAFE", "compile_gate"},
    {1042u, "watchdog_supervisor_safe", "watchdog", "SAFE", "compile_gate"},
    {1044u, "pressure_wdg_context_safe", "watchdog", "SAFE", "safe_terminal"},
    {1043u, "selftest_scheduler_safe", "watchdog", "SAFE", "safe_terminal"},
    {2001u, "motion_home_cycle_full", "motion", "FULL", "safe_gate_or_full"},
    {2002u, "motion_absolute_move_bounds_full", "motion", "FULL", "safe_gate_or_full"},
    {2007u, "motion_home_repeatability_factory", "motion", "FULL", "safe_gate_or_full"},
    {2008u, "motion_pattern_return_factory", "motion", "FULL", "safe_gate_or_full"},
    {2010u, "motion_xy_long_travel_factory", "motion", "FULL", "explicit_selection"},
    {2011u, "motion_xy_raster_repeatability_factory", "motion", "FULL", "explicit_selection"},
    {2012u, "motion_xy_reverse_travel_factory", "motion", "FULL", "explicit_selection"},
    {2013u, "motion_xy_diagonal_factory", "motion", "FULL", "explicit_selection"},
    {2014u, "motion_384_plate_raster_factory", "motion", "FULL", "explicit_selection"},
    {2015u, "motion_z_long_travel_factory", "motion", "FULL", "explicit_selection"},
    {2016u, "motion_limit_triggered_home_fact", "motion", "FULL", "explicit_selection"},
    {2020u, "motion_timing_low_xy", "motion", "FULL", "explicit_selection"},
    {2021u, "motion_timing_x_only", "motion", "FULL", "explicit_selection"},
    {2022u, "motion_timing_y_only", "motion", "FULL", "explicit_selection"},
    {2023u, "motion_timing_equal_xy", "motion", "FULL", "explicit_selection"},
    {2024u, "motion_timing_camera_ratio", "motion", "FULL", "explicit_selection"},
    {2025u, "motion_timing_short_tri", "motion", "FULL", "explicit_selection"},
    {2030u, "profile_lut_cycle_benchmark_safe", "performance", "SAFE", "explicit_selection"},
    {2040u, "coordinated_xy_x_only_low", "motion", "FULL", "explicit_selection"},
    {2041u, "coordinated_xy_y_only_low", "motion", "FULL", "explicit_selection"},
    {2042u, "coordinated_xy_equal_low", "motion", "FULL", "explicit_selection"},
    {2043u, "coordinated_xy_asymmetric_low", "motion", "FULL", "explicit_selection"},
    {2044u, "coordinated_xy_pause_resume", "motion", "FULL", "explicit_selection"},
    {2045u, "coordinated_xy_cancel", "motion", "FULL", "explicit_selection"},
    {2046u, "coordinated_xy_limit_abort", "motion", "FULL", "explicit_selection"},
    {2050u, "normal_xy_route_x_only_low", "motion", "FULL", "explicit_selection"},
    {2051u, "normal_xy_route_y_only_low", "motion", "FULL", "explicit_selection"},
    {2052u, "normal_xy_route_equal_low", "motion", "FULL", "explicit_selection"},
    {2053u, "normal_xy_route_asymmetric_low", "motion", "FULL", "explicit_selection"},
    {2054u, "normal_xy_route_long_status", "motion", "FULL", "explicit_selection"},
    {2055u, "normal_xy_route_control_low", "motion", "FULL", "explicit_selection"},
    {2056u, "normal_xy_route_physical_limit", "motion", "FULL", "explicit_selection"},
    {2057u, "normal_xy_route_legacy_smoke", "motion", "FULL", "explicit_selection"},
    {2060u, "coordinated_xy_performance_5khz", "performance", "FULL", "explicit_selection"},
    {2061u, "coordinated_xy_performance_10khz", "performance", "FULL", "explicit_selection"},
    {2062u, "coordinated_xy_performance_20khz", "performance", "FULL", "explicit_selection"},
    {2063u, "coordinated_xy_performance_30khz", "performance", "FULL", "explicit_selection"},
    {2064u, "coordinated_xy_performance_40khz", "performance", "FULL", "explicit_selection"},
    {2065u, "coord_xy_perf_m1_comparison", "performance", "FULL", "explicit_selection"},
    {2066u, "coord_xy_perf_raster", "performance", "FULL", "explicit_selection"},
    {2067u, "coord_xy_perf_camera_repeat", "performance", "FULL", "explicit_selection"},
    {2068u, "coord_xy_perf_pressure", "performance", "FULL", "explicit_selection"},
    {2070u, "coord_xy_perf_x_direction", "performance", "FULL", "explicit_selection"},
    {2071u, "coord_xy_camera_home_transition", "performance", "FULL", "explicit_selection"},
    {2072u, "coord_xy_40khz_irq_path", "performance", "FULL", "explicit_selection"},
    {2073u, "coord_xy_40khz_entry_lateness", "performance", "FULL", "explicit_selection"},
    {2074u, "coord_xy_single_irq_pulse", "performance", "FULL", "explicit_selection"},
    {2080u, "coord_xy_mres3_20khz_motion", "performance", "FULL", "explicit_selection"},
    {2081u, "coord_xy_mres3_20khz_irq_path", "performance", "FULL", "explicit_selection"},
    {2082u, "coord_xy_mres3_entry_margin", "performance", "FULL", "explicit_selection"},
    {2083u, "tmc2208_mres3_configuration", "configuration", "FULL", "explicit_selection"},
    {2087u, "coord_xy_prod_mres3_motion", "performance", "FULL", "explicit_selection"},
    {2088u, "coord_xy_prod_mres3_irq_path", "performance", "FULL", "explicit_selection"},
    {2089u, "coord_xy_prod_conditional_rearm", "performance", "FULL", "explicit_selection"},
    {2090u, "tmc2208_production_mres3_config", "configuration", "FULL", "explicit_selection"},
    {2091u, "direct_lut_x_cruise", "performance", "FULL", "explicit_selection"},
    {2092u, "direct_lut_y_cruise", "performance", "FULL", "explicit_selection"},
    {2093u, "direct_lut_z_cruise", "performance", "FULL", "explicit_selection"},
    {2094u, "direct_lut_x_triangular", "performance", "FULL", "explicit_selection"},
    {2095u, "direct_lut_isolation", "configuration", "FULL", "explicit_selection"},
    {2003u, "pressure_regulator_step_response_full", "pressure", "FULL", "safe_gate_or_full"},
    {2201u, "pressure_hold_leak_factory", "pressure", "FULL", "safe_gate_or_full"},
    {2202u, "pressure_target_cycle_repeatability_factory", "pressure", "FULL", "safe_gate_or_full"},
    {2203u, "pressure_motor_position_hysteresis_factory", "pressure", "FULL", "safe_gate_or_full"},
    {2210u, "pressure_sensor_idle_stability_factory", "pressure", "FULL", "explicit_selection"},
    {2211u, "pressure_regulator_home_repeatability_factory", "pressure", "FULL", "explicit_selection"},
    {2212u, "pressure_hold_leak_print_factory", "pressure", "FULL", "explicit_selection"},
    {2213u, "pressure_hold_leak_refuel_factory", "pressure", "FULL", "explicit_selection"},
    {2214u, "pressure_target_cycle_print_factory", "pressure", "FULL", "explicit_selection"},
    {2215u, "pressure_target_cycle_refuel_factory", "pressure", "FULL", "explicit_selection"},
    {2216u, "pressure_motor_hysteresis_print_factory", "pressure", "FULL", "explicit_selection"},
    {2217u, "pressure_motor_hysteresis_refuel_factory", "pressure", "FULL", "explicit_selection"},
    {2218u, "pressure_step_ladder_print_factory", "pressure", "FULL", "explicit_selection"},
    {2219u, "pressure_step_ladder_refuel_factory", "pressure", "FULL", "explicit_selection"},
    {2220u, "refuel_vacuum_sensor_shift_factory", "pressure", "FULL", "explicit_selection"},
    {2221u, "refuel_vacuum_cycle_repeatability_factory", "pressure", "FULL", "explicit_selection"},
    {2004u, "valve_actuation_sequence_full", "pressure", "FULL", "safe_gate_or_full"},
    {2005u, "print_refuel_pulse_integrity_full", "pulse", "FULL", "safe_gate_or_full"},
    {2473u, "valve_char_print_2psi_repeat_linearity", "pulse", "FULL", "explicit_selection"},
    {2474u, "valve_char_refuel_2psi_repeat_linearity", "pulse", "FULL", "explicit_selection"},
    {2475u, "valve_char_channel_balance_2psi", "pulse", "FULL", "explicit_selection"},
    {2476u, "valve_gap_print_1500us_2psi", "pulse", "FULL", "explicit_selection"},
    {2477u, "valve_gap_refuel_1500us_2psi", "pulse", "FULL", "explicit_selection"},
    {2478u, "valve_gap_print_control_2psi", "pulse", "FULL", "explicit_selection"},
    {2479u, "valve_gap_refuel_control_2psi", "pulse", "FULL", "explicit_selection"},
    {2501u, "gripper_seal_closed_decay_factory", "gripper", "FULL", "explicit_selection"},
    {2502u, "gripper_seal_hold_duration_factory", "gripper", "FULL", "explicit_selection"},
    {2503u, "gripper_seal_repeatability_factory", "gripper", "FULL", "explicit_selection"},
    {2510u, "gripper_static_pressure_matrix_factory", "gripper", "FULL", "explicit_selection"},
    {2511u, "gripper_refresh_hold_3psi_factory", "gripper", "FULL", "explicit_selection"},
    {2512u, "gripper_motion_raster_3psi_factory", "gripper", "FULL", "explicit_selection"},
    {2513u, "gripper_post_motion_seal_compare_factory", "gripper", "FULL", "explicit_selection"},
    {2006u, "emergency_abort_and_safe_stop_full", "safety", "FULL", "safe_gate_or_full"},
    {2101u, "pressure_recovery_trace_print_single", "pressure_trace", "FULL", "explicit_flag"},
    {2102u, "pressure_recovery_trace_print_repeated", "pressure_trace", "FULL", "explicit_flag"},
    {2103u, "pressure_recovery_trace_refuel_repeated", "pressure_trace", "FULL", "explicit_flag"},
    {2104u, "pressure_recovery_trace_dual_interleaved", "pressure_trace", "FULL", "explicit_flag"},
    {kPressureTraceCustomTestId, "pressure_recovery_trace_custom", "pressure_trace", "FULL", "explicit_flag"},
    {2301u, "pressure_sweep_core", "pressure_sweep", "FULL", "explicit_selection"},
    {2302u, "pressure_sweep_extended", "pressure_sweep", "FULL", "explicit_selection"},
    {2303u, "pressure_sweep_focused", "pressure_sweep", "FULL", "explicit_selection"},
    {2304u, "pressure_sweep_micro", "pressure_sweep", "FULL", "explicit_selection"},
};

} // namespace

const DiagnosticTestDescriptor* DiagnosticsRunner::registry(size_t* count)
{
    if (count) {
        *count = sizeof(kDiagnosticTests) / sizeof(kDiagnosticTests[0]);
    }
    return kDiagnosticTests;
}

DiagnosticsSummary DiagnosticsRunner::runSelfTest(Orchestrator& orchestrator,
                                                  const DiagnosticsRequest& request)
{
    DiagnosticsSummary summary{};
    Comm* comm = Comm::instance();
    if (!comm || !comm->handle()) {
        return summary;
    }

    const uint8_t outSeq8 = request.seq8;
    const uint32_t runId = request.runId;
    (void)request.timeoutMs;

    auto& _selfTestAbortRequested = orchestrator._selfTestAbortRequested;
    auto& _resumeRequested = orchestrator._resumeRequested;
    auto& _cmdQueue = orchestrator._cmdQueue;
    auto& _doneEvents = orchestrator._doneEvents;
    auto& _flashTaskHandle = orchestrator._flashTaskHandle;
    auto& _imagingDroplets = orchestrator._imagingDroplets;

    auto waitForBit = [&](EventBits_t bit) -> bool { return orchestrator.waitForBit(bit); };
    auto msToAtLeast1Tick = [](uint32_t ms) -> TickType_t { return Orchestrator::msToAtLeast1Tick(ms); };
    auto performShutdown = [&](uint8_t byeSeq8, uint32_t byeSeq32, bool have32) {
        orchestrator.performShutdown(byeSeq8, byeSeq32, have32);
    };
    auto setImagingDroplets = [&](uint16_t imagingDroplets) {
        orchestrator.setImagingDroplets(imagingDroplets);
    };
    auto startHomeAsync = [&](Stepper* s,
                              uint32_t fastHz,
                              uint32_t slowHz,
                              uint32_t backoffSteps,
                              EventBits_t doneBit) {
        orchestrator.startHomeAsync(s, fastHz, slowHz, backoffSteps, doneBit);
    };
    auto startRegHomeAsync = [&](PressureRegulator* r,
                                 uint32_t fastHz,
                                 uint32_t slowHz,
                                 uint32_t backoffSteps,
                                 EventBits_t doneBit) {
        orchestrator.startRegHomeAsync(r, fastHz, slowHz, backoffSteps, doneBit);
    };

    static constexpr uint8_t CMD_HELLO_ACK = static_cast<uint8_t>(Orchestrator::CMD_HELLO_ACK);
    static constexpr uint8_t CMD_BYE_ACK = static_cast<uint8_t>(Orchestrator::CMD_BYE_ACK);
    static constexpr uint8_t CMD_BYE_DONE = static_cast<uint8_t>(Orchestrator::CMD_BYE_DONE);
    static constexpr uint8_t CMD_CLEAR_ACK = static_cast<uint8_t>(Orchestrator::CMD_CLEAR_ACK);

    const uint32_t selftestStartMs = HAL_GetTick();
    uint32_t lastProgressEmitMs = 0u;
    uint16_t total = 0;
    uint16_t passed = 0;
    uint16_t failed = 0;
    bool aborted = false;
    const uint16_t selectedDiagnosticId =
        (request.selectedDiagnosticId != 0u) ? request.selectedDiagnosticId : request.selectedPressureTraceTest;
    const uint16_t selectedPressureTraceTest = request.selectedPressureTraceTest;
    const bool runGripperSealSuite = (selectedDiagnosticId == 2500u);
    const bool runGripperSealStressSuite = (selectedDiagnosticId == 2599u);
    const bool runXyMotionSuite = (selectedDiagnosticId == 2009u);
    const bool runMotionEnvelopeSuite = (selectedDiagnosticId == 2019u);
    const bool runMotionTimingSuite = (selectedDiagnosticId == 2029u);
    const bool runProfileLutBenchmark = (selectedDiagnosticId == 2039u);
    const bool runCoordinatedXyExecutorSuite = (selectedDiagnosticId == 2049u);
    const bool runNormalXyRouteSuite = (selectedDiagnosticId == 2059u);
    const bool runCoordinatedXyStatusSyncSuite =
        (selectedDiagnosticId == 2076u);
    const bool runCoordinatedXySingleIrqSuite =
        (selectedDiagnosticId == 2075u);
    const bool runCoordinatedXyMres3BaselineSuite =
        (selectedDiagnosticId == 2085u);
    const bool runCoordinatedXyMres3RearmSuite =
        (selectedDiagnosticId == 2084u);
    const bool runCoordinatedXyMres3ConditionalRearmSuite =
        (selectedDiagnosticId == 2086u);
    const bool runCoordinatedXyProductionMres3Suite =
        (selectedDiagnosticId == 2097u);
    const bool runDirectXyzLutSuite = (selectedDiagnosticId == 2096u);
    const bool runCoordinatedXyMres3Suite =
        runCoordinatedXyMres3BaselineSuite ||
        runCoordinatedXyMres3RearmSuite ||
        runCoordinatedXyMres3ConditionalRearmSuite;
    const bool collectCompletedMres3Evidence =
        runCoordinatedXyMres3BaselineSuite ||
        runCoordinatedXyMres3ConditionalRearmSuite ||
        runCoordinatedXyProductionMres3Suite;
    const bool runCoordinatedXyLogicalMres3Suite =
        runCoordinatedXyMres3Suite || runCoordinatedXyProductionMres3Suite;
    const bool runCoordinatedXy40KhzSuite =
        (selectedDiagnosticId == 2077u) || runCoordinatedXyStatusSyncSuite ||
        runCoordinatedXySingleIrqSuite;
    const bool runCoordinatedXyFocusedGeometrySuite =
        runCoordinatedXy40KhzSuite || runCoordinatedXyLogicalMres3Suite;
    const bool runCoordinatedXyDirectionSuite = (selectedDiagnosticId == 2079u);
    const bool runCoordinatedXyTransitionSuite = (selectedDiagnosticId == 2078u);
    const bool runCoordinatedXyPerformanceSuite =
        (selectedDiagnosticId == 2069u) || runCoordinatedXyFocusedGeometrySuite ||
        runCoordinatedXyDirectionSuite || runCoordinatedXyTransitionSuite;
    const bool runPressureRegulatorSuite = (selectedDiagnosticId == 2299u);
    const bool runRefuelVacuumSuite = (selectedDiagnosticId == 2298u);
    const bool runValveCharacterizationSuite = (selectedDiagnosticId == 2499u);
    const bool runValveGapSweepSuite = (selectedDiagnosticId == 2498u);
    const bool runSelfTestSchedulerNoYieldSuite = (selectedDiagnosticId == 1039u);
    const bool runSelfTestSchedulerCooperativeSuite = (selectedDiagnosticId == 1038u);
    const SelfTestResultSchedulingMode resultSchedulingMode = runSelfTestSchedulerNoYieldSuite
        ? SelfTestResultSchedulingMode::NoYield
        : SelfTestResultSchedulingMode::Cooperative;
    SelfTestSchedulingState schedulingState{};
    SelfTestScheduling_Init(schedulingState, resultSchedulingMode);
    if (PressureSensorWatchdog_BeginDiagnosticWindow() == 0u) {
      schedulingState.saturated = true;
    }
    const bool runPressureSweepCore = (selectedPressureTraceTest == 2301u);
    const bool runPressureSweepExtended = (selectedPressureTraceTest == 2302u);
    const bool runPressureSweepFocused = (selectedPressureTraceTest == 2303u);
    const bool runPressureSweepMicro = (selectedPressureTraceTest == 2304u);
    const bool runPressureDiagnosticsByFlag = request.runPressureDiagnostics;
    const bool runCustomPressureTraceSelection =
        (selectedPressureTraceTest == kPressureTraceCustomTestId);
    const bool runSinglePressureTraceSelection =
        (selectedPressureTraceTest >= 2101u) && (selectedPressureTraceTest <= 2104u);
                  auto shouldRunPressureTraceCase = [&](uint16_t testId) {
                    if (runPressureSweepCore || runPressureSweepExtended || runPressureSweepFocused || runPressureSweepMicro || runGripperSealSuite || runGripperSealStressSuite || runXyMotionSuite || runMotionEnvelopeSuite || runMotionTimingSuite || runDirectXyzLutSuite || runProfileLutBenchmark || runCoordinatedXyExecutorSuite || runNormalXyRouteSuite || runCoordinatedXyPerformanceSuite || runPressureRegulatorSuite || runRefuelVacuumSuite || runValveCharacterizationSuite || runValveGapSweepSuite) {
                      return false;
                    }
                    if (runSinglePressureTraceSelection) {
                      return selectedPressureTraceTest == testId;
                    }
                    if (selectedPressureTraceTest != 0u) {
                      return false;
                    }
                    // Keep default FULL gate lightweight; run pressure diagnostics only when explicitly requested.
                    return runPressureDiagnosticsByFlag;
                  };

                  bool resumeStatusAfterEmission = false;
                  auto sendResult = [&](uint16_t testId, const char* name, bool pass, const char* metrics) {
                    // Keep status spam suppressed for the whole self-test window.
                    comm->setStatusPaused(true);
                    uint8_t payload[256] = {0};
                    const size_t payloadLen = DiagnosticResultEmitter::buildResultPayload(
                        payload,
                        sizeof(payload),
                        outSeq8,
                        runId,
                        testId,
                        name,
                        pass,
                        metrics,
                        HAL_GetTick());
                    ScopedSelfTestEmissionPriority emissionPriority(resultSchedulingMode);
                    const uint32_t transmitStartMs = HAL_GetTick();
                    const bool frameSent = comm->sendFrameWithTimeout(
                        comm->handle(),
                        payload,
                        payloadLen,
                        SelfTestScheduling_SelectTransmitTimeoutMs(
                            resultSchedulingMode));
                    SelfTestScheduling_RecordTransmit(schedulingState,
                                                      HAL_GetTick() - transmitStartMs);
                    if (payloadLen == 0u || !frameSent) {
                      schedulingState.saturated = true;
                    }
                    if (SelfTestScheduling_ShouldDelay(schedulingState)) {
                      vTaskDelay(pdMS_TO_TICKS(1u));
                      SelfTestScheduling_RecordDelay(schedulingState);
                    }
                    if (resumeStatusAfterEmission) {
                      comm->setStatusPaused(false);
                    }
                  };
					  auto runOne = [&](uint16_t testId, const char* name, bool pass, const char* metrics) {
				    if (_selfTestAbortRequested) {
				      aborted = true;
				      return false;
				    }
				    total++;
				    if (pass) passed++; else failed++;
				    sendResult(testId, name, pass, metrics);
				    if (_selfTestAbortRequested) {
				      aborted = true;
				      return false;
				    }
				    return true;
				  };

                  auto finishSelfTestNow = [&]() -> DiagnosticsSummary {
                    comm->setStatusPaused(true);
                    uint8_t donePayload[64] = {0};
                    const size_t doneLen = DiagnosticResultEmitter::buildDonePayload(
                        donePayload,
                        sizeof(donePayload),
                        outSeq8,
                        runId,
                        total,
                        passed,
                        failed,
                        aborted,
                        HAL_GetTick());
                    comm->sendFrame(comm->handle(), donePayload, doneLen);
                    _selfTestAbortRequested = false;
                    summary.total = total;
                    summary.passed = passed;
                    summary.failed = failed;
                    summary.aborted = aborted;
                    return summary;
                  };

                  if (TMC2208Configuration::isMres3DiagnosticBuild() &&
                      request.fullProfile && !runCoordinatedXyMres3Suite) {
                    (void)runOne(
                        2083u,
                        "tmc2208_mres3_configuration",
                        false,
                        "gate=mres3_selector_required;mr=3;mf=0;dd=1;tx=0;tf=1;to=1");
                    return finishSelfTestNow();
                  }

                  auto maybeSendProgress = [&](const char* stage) {
                    const uint32_t nowMs = HAL_GetTick();
                    if ((nowMs - lastProgressEmitMs) < 1000u) {
                      return;
                    }
                    lastProgressEmitMs = nowMs;
                    unsigned long hwmWords = 0u;
#if (INCLUDE_uxTaskGetStackHighWaterMark == 1)
                    hwmWords = static_cast<unsigned long>(uxTaskGetStackHighWaterMark(nullptr));
#endif
                    char metrics[128];
                    snprintf(metrics, sizeof(metrics),
                             "kind=progress;stage=%s;elapsed_ms=%lu;stk_hwm_w=%lu",
                             stage,
                             static_cast<unsigned long>(nowMs - selftestStartMs),
                             hwmWords);
                    sendResult(0u, "selftest_progress", true, metrics);
                  };
                  auto sendProgressStage = [&](const char* stage) {
                    const uint32_t nowMs = HAL_GetTick();
                    lastProgressEmitMs = nowMs;
                    unsigned long hwmWords = 0u;
#if (INCLUDE_uxTaskGetStackHighWaterMark == 1)
                    hwmWords = static_cast<unsigned long>(uxTaskGetStackHighWaterMark(nullptr));
#endif
                    char metrics[128];
                    snprintf(metrics, sizeof(metrics),
                             "kind=progress;stage=%s;elapsed_ms=%lu;stk_hwm_w=%lu",
                             stage,
                             static_cast<unsigned long>(nowMs - selftestStartMs),
                             hwmWords);
                    sendResult(0u, "selftest_progress", true, metrics);
                  };

                  auto waitForOperatorResume = [&](const char* stage) -> bool {
                    _resumeRequested = false;
                    sendProgressStage(stage);
                    const TickType_t pollTicks = msToAtLeast1Tick(25u);
                    while (!_selfTestAbortRequested) {
                      Watchdog_CheckIn(CRASH_TASK_ORCH);
                      if (_resumeRequested) {
                        _resumeRequested = false;
                        sendProgressStage("evap_plate_confirmed");
                        return true;
                      }
                      maybeSendProgress(stage);
                      vTaskDelay(pollTicks);
                    }
                    aborted = true;
                    return false;
                  };

                  static constexpr uint8_t TRACE_KIND_SAMPLES = 1u;
                  static constexpr uint8_t TRACE_KIND_EVENTS = 2u;
                  static constexpr uint8_t TRACE_FORMAT_SAMPLE_V1 = 1u;
                  static constexpr uint8_t TRACE_FORMAT_EVENT_V1 = 2u;
                  const bool exportPressureTrace = request.exportPressureTrace;

                  auto sendTraceChunk = [&](uint16_t testId,
                                            const char* name,
                                            bool pass,
                                            uint8_t traceKind,
                                            uint8_t traceFormat,
                                            uint16_t chunkIndex,
                                            uint16_t chunkTotal,
                                            const uint8_t* payloadBytes,
                                            uint8_t payloadLen) {
                    // Reassert status suppression before each trace chunk burst.
                    comm->setStatusPaused(true);
                    static uint8_t payload[192];
                    memset(payload, 0, sizeof(payload));
                    const size_t framePayloadLen = DiagnosticResultEmitter::buildTracePayload(
                        payload,
                        sizeof(payload),
                        outSeq8,
                        runId,
                        testId,
                        name,
                        pass,
                        traceKind,
                        traceFormat,
                        chunkIndex,
                        chunkTotal,
                        payloadBytes,
                        payloadLen);
                    Watchdog_CheckIn(CRASH_TASK_ORCH);
                    comm->sendFrame(comm->handle(), payload, framePayloadLen);
                  };

                  auto exportTrace = [&](uint16_t testId, const char* name, bool pass) -> bool {
                    if (!exportPressureTrace) {
                      return true;
                    }
                    auto& recorder = PressureTraceRecorder::instance();
                    static constexpr uint8_t kSampleChunkBytes = 80u;
                    static constexpr uint8_t kEventChunkBytes = 80u;
                    static constexpr TickType_t kExportMaxTicks = pdMS_TO_TICKS(6000u);
                    const TickType_t exportStart = xTaskGetTickCount();
                    unsigned long exportHwmWords = 0u;
#if (INCLUDE_uxTaskGetStackHighWaterMark == 1)
                    exportHwmWords = static_cast<unsigned long>(uxTaskGetStackHighWaterMark(nullptr));
#endif
                    if (exportHwmWords > 0u && exportHwmWords < 64u) {
                      sendProgressStage("trace_stack_low");
                      return false;
                    }
                    const auto* samples = reinterpret_cast<const uint8_t*>(recorder.samples());
                    const uint16_t totalSampleBytes = static_cast<uint16_t>(recorder.sampleCount() * sizeof(PressureTraceSample));
                    const uint16_t sampleChunks = (totalSampleBytes == 0u) ? 0u : static_cast<uint16_t>((totalSampleBytes + kSampleChunkBytes - 1u) / kSampleChunkBytes);
                    if (sampleChunks > 1024u) {
                      sendProgressStage("trace_sample_chunk_oob");
                      return false;
                    }
                    const TickType_t exportYieldTicks = msToAtLeast1Tick(recorder.config().exportYieldMs);
                    for (uint16_t chunkIndex = 0; chunkIndex < sampleChunks; ++chunkIndex) {
                      if ((xTaskGetTickCount() - exportStart) > kExportMaxTicks) {
                        sendProgressStage("trace_export_to");
                        return false;
                      }
                      Watchdog_CheckIn(CRASH_TASK_ORCH);
                      maybeSendProgress("trace_export");
                      const uint16_t offset = static_cast<uint16_t>(chunkIndex * kSampleChunkBytes);
                      const uint16_t remain = static_cast<uint16_t>(totalSampleBytes - offset);
                      const uint8_t chunkLen = static_cast<uint8_t>((remain > kSampleChunkBytes) ? kSampleChunkBytes : remain);
                      sendTraceChunk(testId, name, pass, TRACE_KIND_SAMPLES, TRACE_FORMAT_SAMPLE_V1, chunkIndex, sampleChunks, samples + offset, chunkLen);
                      vTaskDelay(exportYieldTicks);
                    }
                    const auto* events = reinterpret_cast<const uint8_t*>(recorder.events());
                    const uint16_t totalEventBytes = static_cast<uint16_t>(recorder.eventCount() * sizeof(PressureTraceEvent));
                    const uint16_t eventChunks = (totalEventBytes == 0u) ? 0u : static_cast<uint16_t>((totalEventBytes + kEventChunkBytes - 1u) / kEventChunkBytes);
                    if (eventChunks > 1024u) {
                      sendProgressStage("trace_event_chunk_oob");
                      return false;
                    }
                    for (uint16_t chunkIndex = 0; chunkIndex < eventChunks; ++chunkIndex) {
                      if ((xTaskGetTickCount() - exportStart) > kExportMaxTicks) {
                        sendProgressStage("trace_export_to");
                        return false;
                      }
                      Watchdog_CheckIn(CRASH_TASK_ORCH);
                      maybeSendProgress("trace_export");
                      const uint16_t offset = static_cast<uint16_t>(chunkIndex * kEventChunkBytes);
                      const uint16_t remain = static_cast<uint16_t>(totalEventBytes - offset);
                      const uint8_t chunkLen = static_cast<uint8_t>((remain > kEventChunkBytes) ? kEventChunkBytes : remain);
                      sendTraceChunk(testId, name, pass, TRACE_KIND_EVENTS, TRACE_FORMAT_EVENT_V1, chunkIndex, eventChunks, events + offset, chunkLen);
                      vTaskDelay(exportYieldTicks);
                    }
                    return true;
                  };

				  auto runAckRoundtrip = [&](uint16_t testId, const char* name, uint8_t ackCmd, bool includeSeq32, bool doneLabel, const char* extraMetrics = nullptr, bool extraPass = true) {
				    uint8_t ackPayload[8] = {0};
				    const uint8_t ackLen = CommCodec::buildAckPayload(ackCmd, outSeq8, runId, includeSeq32, ackPayload, sizeof(ackPayload));
				    uint8_t frame[16] = {0};
				    const size_t frameLen = CommCodec::encodeFrame(ackPayload, ackLen, frame, sizeof(frame));

				    CommCodec::RxParser parser{};
				    uint8_t parsedLen = 0;
				    int readyCount = 0;
				    for (size_t i = 0; i < frameLen; ++i) {
				      if (CommCodec::feedRxByte(parser, frame[i], parsedLen) == CommCodec::FeedResult::FrameReady) {
				        readyCount++;
				      }
				    }

				    const auto decoded = CommCodec::decodeCommand(parser.rxBuf, parsedLen);
				    const bool seq8Match = (decoded.seq8 == outSeq8);
				    const bool seq32Match = includeSeq32 ? (decoded.hasSeq32 && decoded.seq32 == runId) : !decoded.hasSeq32;
				    const bool pass = extraPass &&
				                      (ackLen == (includeSeq32 ? 8u : 2u)) &&
				                      (frameLen == static_cast<size_t>(ackLen + 4u)) &&
				                      (readyCount == 1) &&
				                      (decoded.cmd == ackCmd) &&
				                      seq8Match &&
				                      seq32Match;

				    char metrics[128];
				    int written = 0;
				    if (doneLabel) {
				      written = snprintf(metrics, sizeof(metrics), "done_cmd=%u;seq8_match=%u;seq32_match=%u",
				                         static_cast<unsigned>(ackCmd),
				                         static_cast<unsigned>(seq8Match ? 1u : 0u),
				                         static_cast<unsigned>(seq32Match ? 1u : 0u));
				    } else {
				      written = snprintf(metrics, sizeof(metrics), "ack_cmd=%u;seq8_match=%u;seq32_match=%u",
				                         static_cast<unsigned>(ackCmd),
				                         static_cast<unsigned>(seq8Match ? 1u : 0u),
				                         static_cast<unsigned>(seq32Match ? 1u : 0u));
				    }
				    if (extraMetrics && extraMetrics[0] != '\0' && written > 0 && static_cast<size_t>(written) < sizeof(metrics) - 1u) {
				      snprintf(metrics + written, sizeof(metrics) - static_cast<size_t>(written), ";%s", extraMetrics);
				    }
				    return runOne(testId, name, pass, metrics);
				  };

				  auto sampleStatusWindow = [&](uint32_t sampleMs,
					                                uint32_t& chunk0Seen,
					                                uint32_t& chunk1Seen,
					                                uint32_t& alternationErrors,
					                                uint32_t& periodMsAvg,
					                                uint32_t& periodMsMaxJitter) {
					    Comm::resetStatusMetrics();
					    comm->setStatusPaused(false);
					    Watchdog_CheckIn(CRASH_TASK_ORCH);
					    vTaskDelay(pdMS_TO_TICKS(sampleMs));
					    chunk0Seen = Comm::getStatusChunk0Count();
				    chunk1Seen = Comm::getStatusChunk1Count();
				    alternationErrors = Comm::getStatusAlternationErrors();
				    periodMsAvg = Comm::getStatusPeriodAvgMs();
				    periodMsMaxJitter = Comm::getStatusPeriodMaxJitterMs();
                    comm->setStatusPaused(true);
				  };

				  uint32_t statusChunk0Seen = 0;
					  uint32_t statusChunk1Seen = 0;
					  uint32_t statusAlternationErrors = 0;
					  uint32_t statusPeriodMsAvg = 0;
					  uint32_t statusPeriodMsMaxJitter = 0;
					  const bool fullProfile = request.fullProfile;
                      const bool pressureSweepOnly = runPressureSweepCore || runPressureSweepExtended || runPressureSweepFocused || runPressureSweepMicro;
					  bool fullHomePass = pressureSweepOnly;
					  bool fullMotionBoundsPass = pressureSweepOnly;
                      bool selectedPressureHomePass = false;

					  auto absDiff32 = [](int32_t a, int32_t b) -> uint32_t {
					    const int64_t diff = static_cast<int64_t>(a) - static_cast<int64_t>(b);
					    return static_cast<uint32_t>((diff < 0) ? -diff : diff);
					  };

					  auto isHomedPosition = [](int32_t pos) -> bool {
					    return (pos >= 80) && (pos <= 140);
					  };

                      struct PressureWaitResult {
                        bool readySeen = false;
                        bool readyFinal = false;
                        bool accepted = false;
                        bool aborted = false;
                        bool motorGuarded = false;
                        uint32_t settleMs = 0u;
                        uint32_t overshoot = 0u;
                        uint32_t controlError = 0u;
                        uint32_t avgError = 0u;
                      };

                      struct PressurePositionSample {
                        int32_t pressureRaw = 0;
                        int32_t pressureAvg = 0;
                        int32_t motorPosition = 0;
                      };

					  auto waitPressureReady = [&](PressureRegulator& reg,
					                               uint8_t sensorPort,
					                               int32_t targetPressure,
					                               bool stepUp,
					                               uint32_t timeoutMs,
                                                   uint32_t acceptTolRaw = 0u) {
                        PressureWaitResult result{};
					    PressureSensor* sensor = PressureSensor::instance();
					    if (!sensor) {
                          result.settleMs = timeoutMs;
					      return result;
					    }

					    const uint32_t startMs = HAL_GetTick();
					    int32_t peakPressure = sensor->getPressure(sensorPort);
					    int32_t troughPressure = peakPressure;

						    while ((HAL_GetTick() - startMs) < timeoutMs) {
						      Watchdog_CheckIn(CRASH_TASK_ORCH);
                              maybeSendProgress("wait_pressure_ready");
						      const int32_t pressure = sensor->getPressure(sensorPort);
						      if (pressure > peakPressure) peakPressure = pressure;
					      if (pressure < troughPressure) troughPressure = pressure;
                          const auto controlSample = sensor->getControlSample(sensorPort);
                          const uint32_t readyTol = reg.getReadyConfig().readyTolRaw;
                          const uint32_t effectiveTol = (acceptTolRaw > readyTol) ? acceptTolRaw : readyTol;
					      if (reg.isPressureOk()) {
                            result.readySeen = true;
					        break;
					      }
                          if (!reg.isTargetRamping() &&
                              (absDiff32(static_cast<int32_t>(controlSample.raw), targetPressure) <= effectiveTol)) {
                            break;
                          }
					      if (_selfTestAbortRequested) {
                            result.aborted = true;
					        break;
					      }
					      vTaskDelay(pdMS_TO_TICKS(20));
					    }

					    const uint32_t elapsedMs = HAL_GetTick() - startMs;
					    result.settleMs = elapsedMs;
                        result.readyFinal = reg.isPressureOk();
					    const int32_t finalAvgPressure = sensor->getPressure(sensorPort);
                        const auto finalControlSample = sensor->getControlSample(sensorPort);
                        result.controlError = absDiff32(static_cast<int32_t>(finalControlSample.raw), targetPressure);
					    result.avgError = absDiff32(finalAvgPressure, targetPressure);
					    if (stepUp) {
					      result.overshoot = (peakPressure > targetPressure)
					                  ? static_cast<uint32_t>(peakPressure - targetPressure)
					                  : 0u;
					    } else {
					      result.overshoot = (troughPressure < targetPressure)
					                  ? static_cast<uint32_t>(targetPressure - troughPressure)
					                  : 0u;
					    }
                        const uint32_t readyTol = reg.getReadyConfig().readyTolRaw;
                        const uint32_t effectiveTol = (acceptTolRaw > readyTol) ? acceptTolRaw : readyTol;
                        result.accepted = !result.aborted &&
                            (result.readySeen || result.readyFinal ||
                             (!reg.isTargetRamping() && (result.controlError <= effectiveTol)));
						    return result;
						  };

                      auto readPrintPressurePositionSample = [&]() {
                        PressurePositionSample sample{};
                        PressureSensor* sensor = PressureSensor::instance();
                        if (sensor != nullptr) {
                          const auto controlSample = sensor->getControlSample(0u);
                          sample.pressureRaw = static_cast<int32_t>(controlSample.raw);
                          sample.pressureAvg = sensor->getPressure(0u);
                        }
                        sample.motorPosition = Stepper::stepperP()->getPosition();
                        return sample;
                      };

                      auto recordPressureWaitExecution = [](const PressureWaitResult& wait,
                                                            PressureQualificationMath::ExecutionSummary& summary) {
                        if (wait.motorGuarded) {
                          summary.motorGuardCount++;
                          return;
                        }
                        if (wait.accepted) {
                          return;
                        }
                        summary.readyMissCount++;
                        if (wait.aborted) {
                          summary.abortCount++;
                        } else {
                          summary.timeoutCount++;
                        }
                      };

						  auto waitBitsWithTimeout = [&](EventBits_t bits, uint32_t timeoutMs) {
                            sendProgressStage("wait_bits_enter");
						    const TickType_t pollTicks = msToAtLeast1Tick(10u);
                            const uint32_t startMs = HAL_GetTick();
							    while ((HAL_GetTick() - startMs) < timeoutMs) {
							      Watchdog_CheckIn(CRASH_TASK_ORCH);
                                  maybeSendProgress("wait_bits");
							      if (_selfTestAbortRequested) {
							        return false;
							      }
                                  const EventBits_t result = xEventGroupGetBits(_doneEvents);
						      if ((result & bits) == bits) {
                                sendProgressStage("wait_bits_set");
						        return true;
						      }
                              maybeSendProgress("wait_bits_tick");
                              vTaskDelay(pollTicks);
						    }
                            sendProgressStage("wait_bits_to");
						    return false;
						  };
                          auto cancelActiveHomesAndWait = [&](EventBits_t bits) {
                            orchestrator.cancelActiveHomesForPause();
                            const uint32_t cancelStartMs = HAL_GetTick();
                            const TickType_t pollTicks = msToAtLeast1Tick(2u);
                            while ((HAL_GetTick() - cancelStartMs) < 1000u) {
                              Watchdog_CheckIn(CRASH_TASK_ORCH);
                              if ((xEventGroupGetBits(_doneEvents) & bits) == bits) {
                                return true;
                              }
                              vTaskDelay(pollTicks);
                            }
                            return (xEventGroupGetBits(_doneEvents) & bits) == bits;
                          };
                          auto delayWithWatchdog = [&](uint32_t delayMs, const char* progressStage) {
                            const uint32_t startMs = HAL_GetTick();
                            while ((HAL_GetTick() - startMs) < delayMs) {
                              Watchdog_CheckIn(CRASH_TASK_ORCH);
                              maybeSendProgress(progressStage);
                              if (_selfTestAbortRequested) {
                                return false;
                              }
                              const uint32_t elapsedMs = HAL_GetTick() - startMs;
                              const uint32_t remainMs = (elapsedMs < delayMs) ? (delayMs - elapsedMs) : 0u;
                              const uint32_t sliceMs = (remainMs > 25u) ? 25u : remainMs;
                              if (sliceMs == 0u) {
                                break;
                              }
                              vTaskDelay(msToAtLeast1Tick(sliceMs));
                            }
                            return true;
                          };

                          auto runXyHomeDiagnosticAttempt = [&](MotionQualificationMath::AxisHomeSample& xSample,
                                                                MotionQualificationMath::AxisHomeSample& ySample,
                                                                uint32_t fastHz,
                                                                uint32_t slowHz,
                                                                uint32_t backoffSteps,
                                                                uint32_t timeoutMs) {
                            Stepper::stepperX()->enableMotor();
                            Stepper::stepperY()->enableMotor();
                            xEventGroupClearBits(_doneEvents, BIT_HOME_X_DONE | BIT_HOME_Y_DONE);
                            startHomeAsync(Stepper::stepperX(), fastHz, slowHz, backoffSteps, BIT_HOME_X_DONE);
                            startHomeAsync(Stepper::stepperY(), fastHz, slowHz, backoffSteps, BIT_HOME_Y_DONE);
                            const bool bothDone = waitBitsWithTimeout(BIT_HOME_X_DONE | BIT_HOME_Y_DONE, timeoutMs);
                            if (!bothDone) {
                              (void)cancelActiveHomesAndWait(BIT_HOME_X_DONE | BIT_HOME_Y_DONE);
                            }
                            const EventBits_t doneBits = xEventGroupGetBits(_doneEvents);
                            const bool xDone = (doneBits & BIT_HOME_X_DONE) != 0u;
                            const bool yDone = (doneBits & BIT_HOME_Y_DONE) != 0u;
                            const Stepper::HomeDiagnosticSnapshot xDiag =
                                Stepper::stepperX()->getLastHomeDiagnosticSnapshot();
                            const Stepper::HomeDiagnosticSnapshot yDiag =
                                Stepper::stepperY()->getLastHomeDiagnosticSnapshot();
                            xSample.success = xDone && xDiag.success;
                            xSample.limitTriggerSteps = xDiag.fineLimitPositionSteps;
                            xSample.finalBackoffSteps = xDiag.finalBackoffPositionSteps;
                            xSample.moveTimeoutCount = xDiag.moveTimeoutCount;
                            ySample.success = yDone && yDiag.success;
                            ySample.limitTriggerSteps = yDiag.fineLimitPositionSteps;
                            ySample.finalBackoffSteps = yDiag.finalBackoffPositionSteps;
                            ySample.moveTimeoutCount = yDiag.moveTimeoutCount;
                            return bothDone && xSample.success && ySample.success;
                          };

                          auto runAxisHomeDiagnosticAttempt = [&](Stepper* stepper,
                                                                  EventBits_t homeBit,
                                                                  MotionQualificationMath::AxisHomeSample& sample,
                                                                  uint32_t fastHz,
                                                                  uint32_t slowHz,
                                                                  uint32_t backoffSteps,
                                                                  uint32_t timeoutMs) -> bool {
                            stepper->enableMotor();
                            xEventGroupClearBits(_doneEvents, homeBit);
                            startHomeAsync(stepper, fastHz, slowHz, backoffSteps, homeBit);
                            const bool done = waitBitsWithTimeout(homeBit, timeoutMs);
                            if (!done) {
                              (void)cancelActiveHomesAndWait(homeBit);
                            }
                            const EventBits_t doneBits = xEventGroupGetBits(_doneEvents);
                            const bool axisDone = (doneBits & homeBit) != 0u;
                            const Stepper::HomeDiagnosticSnapshot diag = stepper->getLastHomeDiagnosticSnapshot();
                            sample.success = axisDone && diag.success;
                            sample.limitTriggerSteps = diag.fineLimitPositionSteps;
                            sample.finalBackoffSteps = diag.finalBackoffPositionSteps;
                            sample.moveTimeoutCount = diag.moveTimeoutCount;
                            return done && sample.success;
                          };

                          auto runZClearanceHomePreflight = [&](const char* stage,
                                                                uint32_t fastHz,
                                                                uint32_t slowHz,
                                                                uint32_t backoffSteps,
                                                                uint32_t timeoutMs) -> bool {
                            MotionQualificationMath::AxisHomeSample zSample{};
                            sendProgressStage(stage);
                            return runAxisHomeDiagnosticAttempt(Stepper::stepperZ(),
                                                                BIT_HOME_Z_DONE,
                                                                zSample,
                                                                fastHz,
                                                                slowHz,
                                                                backoffSteps,
                                                                timeoutMs);
                          };

                          auto moveGantryToWithTimeout = [&](int32_t x,
                                                            int32_t y,
                                                            uint32_t feedHz,
                                                            uint32_t timeoutMs) {
                            const GantryPosition pos = Gantry::instance()->getPosition();
                            if (pos.x == x && pos.y == y) {
                              return true;
                            }
                            xEventGroupClearBits(_doneEvents, BIT_STEPPER1_DONE | BIT_STEPPER2_DONE);
                            Gantry::instance()->moveTo(x, y, feedHz);
                            const bool reached = waitBitsWithTimeout(BIT_STEPPER1_DONE | BIT_STEPPER2_DONE, timeoutMs);
                            if (!reached) {
                              Gantry::cancelXYZMotors();
                            }
                            return reached;
                          };

                          auto moveAxisToWithTimeout = [&](Stepper* stepper,
                                                           EventBits_t doneBit,
                                                           int32_t target,
                                                           uint32_t feedHz,
                                                           uint32_t timeoutMs) -> bool {
                            const int32_t current = stepper->getPosition();
                            const int64_t delta64 = static_cast<int64_t>(target) - static_cast<int64_t>(current);
                            if (delta64 == 0) {
                              return true;
                            }
                            const bool direction = delta64 >= 0;
                            const uint32_t steps = static_cast<uint32_t>(direction ? delta64 : -delta64);
                            xEventGroupClearBits(_doneEvents, doneBit);
                            stepper->enableMotor();
                            stepper->move(direction, steps, feedHz, 0u);
                            const bool reached = waitBitsWithTimeout(doneBit, timeoutMs);
                            if (!reached) {
                              stepper->stop();
                            }
                            return reached;
                          };

                          auto waitPrinterIdleWithTimeout = [&](Printer* printer, uint32_t timeoutMs) {
                            if (printer == nullptr) {
                              return false;
                            }
                            sendProgressStage("wait_printer_idle_enter");
                            const TickType_t pollTicks = pdMS_TO_TICKS(10);
                            const TickType_t timeoutTicks = pdMS_TO_TICKS(timeoutMs);
                            TickType_t waitedTicks = 0;
                            while (waitedTicks < timeoutTicks) {
                              Watchdog_CheckIn(CRASH_TASK_ORCH);
                              maybeSendProgress("wait_printer_idle");
                              if (!printer->isBusy()) {
                                sendProgressStage("wait_printer_idle_ok");
                                return true;
                              }
                              if (_selfTestAbortRequested) {
                                return false;
                              }
                              const TickType_t waitTicks = (pollTicks == 0) ? 1 : pollTicks;
                              vTaskDelay(waitTicks);
                              waitedTicks += waitTicks;
                            }
                            sendProgressStage("wait_printer_idle_to");
                            return false;
                          };

                      auto computeTraceMetrics = [&](uint16_t nominalPeriodMs,
                                                     uint32_t& baselinePressure,
                                                     uint32_t& minPressure,
                                                     uint32_t& maxPressure,
                                                     uint32_t& maxUndershoot,
                                                     uint32_t& maxOvershoot,
                                                     uint32_t& worstRecoveryMs,
                                                     uint32_t& meanRecoveryMs,
                                                     uint32_t& readyMissCount,
                                                     uint32_t& maxDeadlineSlipMs,
                                                     uint32_t& meanDeadlineSlipMs,
                                                     uint32_t& zeroCrossCount,
                                                     uint32_t& sampleRejectCount) {
                        baselinePressure = 0u;
                        minPressure = 0u;
                        maxPressure = 0u;
                        maxUndershoot = 0u;
                        maxOvershoot = 0u;
                        worstRecoveryMs = 0u;
                        meanRecoveryMs = 0u;
                        readyMissCount = 0u;
                        maxDeadlineSlipMs = 0u;
                        meanDeadlineSlipMs = 0u;
                        zeroCrossCount = 0u;
                        sampleRejectCount = 0u;
                        auto& recorder = PressureTraceRecorder::instance();
                        if (recorder.sampleCount() == 0u) {
                          return;
                        }
                        const PressureTraceSample* samples = recorder.samples();
                        baselinePressure = samples[0].controlPressure;
                        minPressure = samples[0].controlPressure;
                        maxPressure = samples[0].controlPressure;
                        int32_t prevErr = samples[0].error;
                        uint32_t recoveryTotal = 0u;
                        uint32_t recoveryCount = 0u;
                        uint32_t firstPulseDt = 0u;
                        uint32_t pulseCount = 0u;
                        const PressureTraceEvent* events = recorder.events();
                        const uint16_t eventCount = recorder.eventCount();
                        for (uint16_t i = 0; i < eventCount; ++i) {
                          if (events[i].type == static_cast<uint8_t>(PressureTraceEventType::PulseEnd)) {
                            pulseCount++;
                            if (firstPulseDt == 0u) {
                              firstPulseDt = events[i].dtMs;
                            }
                            const uint32_t actualDt = events[i].dtMs;
                            const uint32_t expectedDt =
                                (pulseCount <= 1u)
                                    ? actualDt
                                    : (static_cast<uint32_t>(firstPulseDt) +
                                       static_cast<uint32_t>(pulseCount - 1u) * nominalPeriodMs);
                            const uint16_t slip = PressureRegulatorMath::computeDeadlineSlipMs(expectedDt, actualDt);
                            meanDeadlineSlipMs += slip;
                            if (slip > maxDeadlineSlipMs) maxDeadlineSlipMs = slip;
                          }
                        }
                        for (uint16_t i = 0; i < eventCount; ++i) {
                          if (events[i].type != static_cast<uint8_t>(PressureTraceEventType::PulseEnd)) {
                            continue;
                          }
                          const uint32_t pulseDt = events[i].dtMs;
                          uint32_t nextPulseDt = 0xFFFFFFFFu;
                          for (uint16_t j = i + 1u; j < eventCount; ++j) {
                            if (events[j].type == static_cast<uint8_t>(PressureTraceEventType::PulseEnd)) {
                              nextPulseDt = events[j].dtMs;
                              break;
                            }
                          }

                          bool sawReadyExit = false;
                          bool recovered = false;
                          for (uint16_t j = i + 1u; j < eventCount; ++j) {
                            const auto eventType = static_cast<PressureTraceEventType>(events[j].type);
                            if ((nextPulseDt != 0xFFFFFFFFu) && (events[j].dtMs >= nextPulseDt)) {
                              break;
                            }
                            if (eventType == PressureTraceEventType::ReadyExit) {
                              sawReadyExit = true;
                              continue;
                            }
                            if (sawReadyExit && (eventType == PressureTraceEventType::ReadyEnter)) {
                              const uint32_t recovery = events[j].dtMs - pulseDt;
                              recoveryTotal += recovery;
                              recoveryCount++;
                              if (recovery > worstRecoveryMs) worstRecoveryMs = recovery;
                              recovered = true;
                              break;
                            }
                          }

                          if (!sawReadyExit) {
                            recoveryCount++;
                            continue;
                          }
                          if (!recovered) {
                            readyMissCount++;
                          }
                        }
                        for (uint16_t i = 0; i < recorder.sampleCount(); ++i) {
                          const auto& sample = samples[i];
                          if (sample.controlPressure < minPressure) minPressure = sample.controlPressure;
                          if (sample.controlPressure > maxPressure) maxPressure = sample.controlPressure;
                          if (sample.target > sample.controlPressure) {
                            const uint32_t under = sample.target - sample.controlPressure;
                            if (under > maxUndershoot) maxUndershoot = under;
                          } else {
                            const uint32_t over = sample.controlPressure - sample.target;
                            if (over > maxOvershoot) maxOvershoot = over;
                          }
                          if ((sample.flags & 0x20u) != 0u) sampleRejectCount++;
                          if (((prevErr < 0) && (sample.error > 0)) || ((prevErr > 0) && (sample.error < 0))) {
                            zeroCrossCount++;
                          }
                          prevErr = sample.error;
                        }
                        if (pulseCount > 0u) {
                          meanDeadlineSlipMs /= pulseCount;
                        }
                        if (recoveryCount > 0u) {
                          meanRecoveryMs = recoveryTotal / recoveryCount;
                        }
                      };

					  auto areMotorsDisabled = [&]() -> bool {
					    const bool xDisabled = HAL_GPIO_ReadPin(Stepper::stepperX()->enPort(), Stepper::stepperX()->enPin()) == GPIO_PIN_SET;
					    const bool yDisabled = HAL_GPIO_ReadPin(Stepper::stepperY()->enPort(), Stepper::stepperY()->enPin()) == GPIO_PIN_SET;
					    const bool zDisabled = HAL_GPIO_ReadPin(Stepper::stepperZ()->enPort(), Stepper::stepperZ()->enPin()) == GPIO_PIN_SET;
					    const bool pDisabled = HAL_GPIO_ReadPin(Stepper::stepperP()->enPort(), Stepper::stepperP()->enPin()) == GPIO_PIN_SET;
					#if (LC_PRESSURE_PORTS > 1)
					    const bool rDisabled = HAL_GPIO_ReadPin(Stepper::stepperR()->enPort(), Stepper::stepperR()->enPin()) == GPIO_PIN_SET;
					    return xDisabled && yDisabled && zDisabled && pDisabled && rDisabled;
					#else
					    return xDisabled && yDisabled && zDisabled && pDisabled;
					#endif
					  };

					  auto areRegulatorsStopped = [&]() -> bool {
					    const bool pStopped = !PressureRegulator::regP().isActive();
					#if (LC_PRESSURE_PORTS > 1)
					    const bool rStopped = !PressureRegulator::regR().isActive();
					    return pStopped && rStopped;
					#else
					    return pStopped;
					#endif
					  };

					  auto areValvesClosed = [&]() -> bool {
					    const bool pClosed = !PressureRegulator::regP().isValveOpen();
					#if (LC_PRESSURE_PORTS > 1)
					    const bool rClosed = !PressureRegulator::regR().isValveOpen();
					    return pClosed && rClosed;
					#else
					    return pClosed;
					#endif
					  };

                      if (runGripperSealStressSuite) {
                        static constexpr uint32_t kStressPulseMs = 2000u;
                        static constexpr uint32_t kStressPulseTickUs = 100u;
                        static constexpr uint32_t kStressTracePreRollMs = 250u;
                        static constexpr uint32_t kStressTracePostRollMs = 250u;
                        static constexpr uint32_t kStressTraceSampleStride = 5u;
                        static constexpr uint32_t kStressTraceSampleMs = 25u;
                        static constexpr uint32_t kStressTraceExportYieldMs = 5u;
                        static constexpr uint32_t kStressReadyTimeoutMs = 9000u;
                        static constexpr uint32_t kStressFreshSampleTimeoutMs = 80u;
                        static constexpr uint32_t kStressRefreshMs = 30000u;
                        static constexpr uint32_t kStressPulseIntervalMs = 10000u;
                        static constexpr uint32_t kStressRefreshHoldMs = 90000u;
                        static constexpr uint32_t kStressRegHomeFastHz = 30000u;
                        static constexpr uint32_t kStressRegHomeSlowHz = 3000u;
                        static constexpr uint32_t kStressRegHomeBackoffSteps = 400u;
                        static constexpr uint32_t kStressRegHomeTimeoutMs = 20000u;
                        static constexpr uint32_t kStressXyHomeFastHz = 30000u;
                        static constexpr uint32_t kStressXyHomeSlowHz = 3000u;
                        static constexpr uint32_t kStressXyHomeBackoffSteps = 400u;
                        static constexpr uint32_t kStressXyHomeTimeoutMs = 20000u;
                        static constexpr int32_t kStressMaxX = 45000;
                        static constexpr int32_t kStressMaxY = 35000;
                        static constexpr int32_t kStressCableGuardMinY = 500;
                        static constexpr int32_t kStressPlateStartX = 43000;
                        static constexpr int32_t kStressPlateStartY = 13000;
                        static constexpr int32_t kStressPlateEndX = 33000;
                        static constexpr int32_t kStressPlateEndY = 30000;
                        static constexpr int32_t kStressEvapPlateZ = 91500;
                        static constexpr uint32_t kStressPlateRows = 16u;
                        static constexpr uint32_t kStressPlateCols = 24u;
                        static constexpr uint32_t kStressPlateFeedHz = 6000u;
                        static constexpr uint32_t kStressPlateMoveTimeoutMs = 12000u;
                        static constexpr uint32_t kStressZFeedHz = 30000u;
                        static constexpr uint32_t kStressZMoveTimeoutMs = 45000u;
                        static constexpr int32_t kStressParkX = 500;
                        static constexpr int32_t kStressParkY = 500;
                        static constexpr uint32_t kStressTargetRaw1Psi = 2512u;
                        static constexpr uint32_t kStressTargetRaw2Psi = 3386u;
                        static constexpr uint32_t kStressTargetRaw3Psi = 4259u;
                        const MotionQualificationMath::ZSafetyEnvelope stressEvapZEnvelope{0, kStressEvapPlateZ};

                        struct GripperStressRowSummary {
                          uint32_t pulses = 0u;
                          uint32_t ready = 0u;
                          uint32_t timeout = 0u;
                          uint32_t freshTo = 0u;
                          uint32_t sc = 0u;
                          uint32_t ec = 0u;
                          uint32_t traceFail = 0u;
                          bool pass = true;
                        };

                        auto closeStressPressurePath = [&]() {
                          if (Printer::instance() != nullptr) {
                            Printer::instance()->endDiagnosticLongPulse();
                          }
                          if (PressureSensor::instance() != nullptr) {
                            PressureSensor::instance()->endDiagnosticFocus();
                          }
                          PressureRegulator::regP().pause();
                          PressureRegulator::regP().closeValve();
#if (LC_PRESSURE_PORTS > 1)
                          PressureRegulator::regR().pause();
                          PressureRegulator::regR().closeValve();
#endif
                        };

                        auto waitStressRegulatorHome = [&](EventBits_t doneBits,
                                                           uint32_t timeoutMs) -> bool {
                          const uint32_t startMs = HAL_GetTick();
                          while ((HAL_GetTick() - startMs) < timeoutMs) {
                            Watchdog_CheckIn(CRASH_TASK_ORCH);
                            maybeSendProgress("gripper_stress_reg_home");
                            if (_selfTestAbortRequested) {
                              return false;
                            }
                            const EventBits_t observed = xEventGroupGetBits(_doneEvents);
                            if ((observed & doneBits) == doneBits) {
                              return true;
                            }
                            vTaskDelay(msToAtLeast1Tick(25u));
                          }
                          return false;
                        };

                        auto homeStressPressureRegulators = [&]() -> bool {
                          closeStressPressurePath();
                          sendProgressStage("gripper_stress_reg_home");
                          EventBits_t homeBits = BIT_HOME_P_DONE;
#if (LC_PRESSURE_PORTS > 1)
                          homeBits |= BIT_HOME_R_DONE;
#endif
                          xEventGroupClearBits(_doneEvents, homeBits);
                          startRegHomeAsync(&PressureRegulator::regP(),
                                            kStressRegHomeFastHz,
                                            kStressRegHomeSlowHz,
                                            kStressRegHomeBackoffSteps,
                                            BIT_HOME_P_DONE);
#if (LC_PRESSURE_PORTS > 1)
                          startRegHomeAsync(&PressureRegulator::regR(),
                                            kStressRegHomeFastHz,
                                            kStressRegHomeSlowHz,
                                            kStressRegHomeBackoffSteps,
                                            BIT_HOME_R_DONE);
#endif
                          const bool homesDone = waitStressRegulatorHome(homeBits, kStressRegHomeTimeoutMs);
                          bool homeOk = homesDone &&
                              (Stepper::stepperP() != nullptr) &&
                              Stepper::stepperP()->getLastHomeDiagnosticSnapshot().success;
#if (LC_PRESSURE_PORTS > 1)
                          homeOk = homeOk &&
                              (Stepper::stepperR() != nullptr) &&
                              Stepper::stepperR()->getLastHomeDiagnosticSnapshot().success;
#endif
                          closeStressPressurePath();
                          return homeOk && !_selfTestAbortRequested;
                        };

                        auto waitFreshStressSample = [&](uint8_t channel, uint32_t timeoutMs) -> bool {
                          PressureSensor* sensor = PressureSensor::instance();
                          if (sensor == nullptr) {
                            return false;
                          }
                          const uint32_t priorTick = sensor->getControlSample(channel).tickMs;
                          const uint32_t startTick = HAL_GetTick();
                          while (!_selfTestAbortRequested && ((HAL_GetTick() - startTick) < timeoutMs)) {
                            Watchdog_CheckIn(CRASH_TASK_ORCH);
                            const auto sample = sensor->getControlSample(channel);
                            if (sample.valid && sample.tickMs != priorTick) {
                              return true;
                            }
                            vTaskDelay(msToAtLeast1Tick(1u));
                          }
                          return false;
                        };

                        auto recordStressTraceEvent = [&](PressureTraceChannel traceChannel,
                                                          PressureTraceEventType type,
                                                          uint16_t value0,
                                                          uint16_t value1,
                                                          uint32_t traceStartTick) {
                          const uint32_t dt = HAL_GetTick() - traceStartTick;
                          PressureTraceEvent event{};
                          event.dtMs = static_cast<uint16_t>((dt > 0xFFFFu) ? 0xFFFFu : dt);
                          event.type = static_cast<uint8_t>(type);
                          event.value0 = value0;
                          event.value1 = value1;
                          PressureTraceRecorder::instance().recordEvent(traceChannel, event);
                        };

                        auto toTraceDeciseconds = [](uint32_t ms) -> uint16_t {
                          const uint32_t ds = (ms + 50u) / 100u;
                          return static_cast<uint16_t>((ds > 0xFFFFu) ? 0xFFFFu : ds);
                        };

                        auto toTraceU16 = [](uint32_t value) -> uint16_t {
                          return static_cast<uint16_t>((value > 0xFFFFu) ? 0xFFFFu : value);
                        };

                        auto recordStressGripperMetadata = [&](PressureTraceChannel traceChannel,
                                                               uint32_t traceStartTick) {
                          const Gripper& gripper = Gripper::instance();
                          const uint32_t nowMs = HAL_GetTick();
                          const uint32_t sinceCloseMs = gripper.hasClosePulseTelemetry()
                              ? (nowMs - gripper.getLastClosePulseTickMs())
                              : 0u;
                          const uint32_t sinceRefreshMs = gripper.hasPumpPulseTelemetry()
                              ? (nowMs - gripper.getLastPumpPulseTickMs())
                              : sinceCloseMs;
                          recordStressTraceEvent(traceChannel,
                                                 PressureTraceEventType::GripperTiming,
                                                 toTraceDeciseconds(sinceCloseMs),
                                                 toTraceDeciseconds(sinceRefreshMs),
                                                 traceStartTick);
                          recordStressTraceEvent(traceChannel,
                                                 PressureTraceEventType::GripperRefreshCount,
                                                 toTraceU16(gripper.getRefreshPulseCount()),
                                                 toTraceDeciseconds(MX_GRIPPER_GetRefreshPeriodMs()),
                                                 traceStartTick);
                        };

                        auto beginStressQuiet = [&]() {
                          PressureRegulator::regP().beginDispenseQuiet(0u);
#if (LC_PRESSURE_PORTS > 1)
                          PressureRegulator::regR().beginDispenseQuiet(0u);
#endif
                        };

                        auto endStressQuiet = [&](const char* stage) {
                          PressureRegulator::regP().endDispenseQuiet(2u);
#if (LC_PRESSURE_PORTS > 1)
                          PressureRegulator::regR().endDispenseQuiet(2u);
#endif
                          (void)delayWithWatchdog(10u, stage);
                        };

                        auto prepareStressPressure = [&](uint16_t targetRaw,
                                                         GripperStressRowSummary& row) -> bool {
                          PressureRegulator::regP().closeValve();
                          PressureRegulator::regP().start();
#if (LC_PRESSURE_PORTS > 1)
                          PressureRegulator::regR().closeValve();
                          PressureRegulator::regR().start();
#endif
                          xEventGroupClearBits(_doneEvents, BIT_PRESSURE_P_READY
#if (LC_PRESSURE_PORTS > 1)
                              | BIT_PRESSURE_R_READY
#endif
                          );
                          PressureRegulator::regP().setTargetSafe(targetRaw);
#if (LC_PRESSURE_PORTS > 1)
                          PressureRegulator::regR().setTargetSafe(targetRaw);
#endif
                          const PressureWaitResult pWait = waitPressureReady(PressureRegulator::regP(),
                                                                              0u,
                                                                              targetRaw,
                                                                              true,
                                                                              kStressReadyTimeoutMs);
                          bool readyOk = pWait.accepted;
#if (LC_PRESSURE_PORTS > 1)
                          const PressureWaitResult rWait = waitPressureReady(PressureRegulator::regR(),
                                                                              1u,
                                                                              targetRaw,
                                                                              true,
                                                                              kStressReadyTimeoutMs);
                          readyOk = readyOk && rWait.accepted;
#endif
                          if (!readyOk) {
                            row.ready++;
                            row.pass = false;
                          }
                          return readyOk;
                        };

                        auto configureStressTrace = [&](uint8_t channel) {
                          auto& recorder = PressureTraceRecorder::instance();
                          recorder.reset();
                          PressureTraceConfig traceCfg{};
                          traceCfg.channel = (channel == 0u) ? PressureTraceChannel::Print : PressureTraceChannel::Refuel;
                          traceCfg.maxSamples = PressureTraceRecorder::kMaxSamples;
                          traceCfg.maxEvents = PressureTraceRecorder::kMaxEvents;
                          traceCfg.preRollMs = static_cast<uint16_t>(kStressTracePreRollMs);
                          traceCfg.postRollMs = static_cast<uint16_t>(kStressTracePostRollMs);
                          traceCfg.sampleStride = static_cast<uint16_t>(kStressTraceSampleStride);
                          traceCfg.exportYieldMs = static_cast<uint16_t>(kStressTraceExportYieldMs);
                          recorder.configure(traceCfg);
                          return traceCfg;
                        };

                        auto finishStressTrace = [&](uint16_t testId,
                                                     const char* traceName,
                                                     bool traceOk,
                                                     GripperStressRowSummary& row) -> bool {
                          auto& recorder = PressureTraceRecorder::instance();
                          row.sc += recorder.sampleCount();
                          row.ec += recorder.eventCount();
                          if (!traceOk) {
                            row.traceFail++;
                            row.pass = false;
                          }
                          if (!exportTrace(testId, traceName, traceOk)) {
                            row.traceFail++;
                            row.pass = false;
                            return false;
                          }
                          return true;
                        };

                        auto runStressTracePulse = [&](uint16_t testId,
                                                       const char* traceName,
                                                       uint8_t channel,
                                                       uint16_t targetRaw,
                                                       GripperStressRowSummary& row,
                                                       const char* stage) -> bool {
                          Printer* printer = Printer::instance();
                          PressureSensor* sensor = PressureSensor::instance();
                          if (printer == nullptr || sensor == nullptr) {
                            row.ready++;
                            row.pass = false;
                            return true;
                          }
                          if (!prepareStressPressure(targetRaw, row)) {
                            return true;
                          }
                          beginStressQuiet();
                          const bool focusOk = sensor->beginDiagnosticFocus(channel);
                          if (!focusOk) {
                            endStressQuiet("gripper_stress_quiet_release");
                            row.ready++;
                            row.pass = false;
                            return true;
                          }
                          const PressureTraceConfig traceCfg = configureStressTrace(channel);
                          auto& recorder = PressureTraceRecorder::instance();
                          recorder.arm();
                          const uint32_t traceStartTick = HAL_GetTick();
                          recorder.start(traceStartTick);
                          recordStressGripperMetadata(traceCfg.channel, traceStartTick);
                          bool timeout = !delayWithWatchdog(traceCfg.preRollMs, stage);
                          bool freshOk = false;
                          if (!timeout && !_selfTestAbortRequested) {
                            freshOk = waitFreshStressSample(channel, kStressFreshSampleTimeoutMs);
                            if (!freshOk) {
                              row.freshTo++;
                            }
                          }
                          if (!timeout && freshOk && !_selfTestAbortRequested) {
                            const PressureTraceChannel traceChannel = traceCfg.channel;
                            recordStressTraceEvent(traceChannel,
                                                   PressureTraceEventType::PulseStart,
                                                   static_cast<uint16_t>(kStressPulseMs),
                                                   sensor->getLatestRaw(channel),
                                                   traceStartTick);
                            const bool started = printer->beginDiagnosticLongPulse(PulseMode::BOTH,
                                                                                   kStressPulseMs,
                                                                                   kStressPulseTickUs);
                            if (!started) {
                              timeout = true;
                            } else {
                              timeout = !delayWithWatchdog(kStressPulseMs, stage);
                            }
                            printer->endDiagnosticLongPulse();
                            recordStressTraceEvent(traceChannel,
                                                   PressureTraceEventType::PulseEnd,
                                                   static_cast<uint16_t>(kStressPulseMs),
                                                   sensor->getLatestRaw(channel),
                                                   traceStartTick);
                          }
                          if (!timeout && !_selfTestAbortRequested) {
                            timeout = !delayWithWatchdog(traceCfg.postRollMs, stage);
                          }
                          recorder.stop(HAL_GetTick());
                          sensor->endDiagnosticFocus();
                          endStressQuiet("gripper_stress_quiet_release");
                          row.pulses++;
                          if (timeout || _selfTestAbortRequested) {
                            row.timeout++;
                            row.pass = false;
                          }
                          const bool traceOk = !timeout && freshOk && (recorder.sampleCount() > 0u) && (recorder.eventCount() > 0u);
                          return finishStressTrace(testId, traceName, traceOk, row);
                        };

                        auto runStressConditioningPulse = [&](uint16_t targetRaw,
                                                              GripperStressRowSummary& row,
                                                              const char* stage) -> bool {
                          Printer* conditioningPrinter = Printer::instance();
                          if (conditioningPrinter == nullptr) {
                            row.ready++;
                            row.pass = false;
                            return false;
                          }
                          if (!prepareStressPressure(targetRaw, row)) {
                            return false;
                          }
                          beginStressQuiet();
                          bool timeout = false;
                          const bool started = conditioningPrinter->beginDiagnosticLongPulse(PulseMode::BOTH,
                                                                                            kStressPulseMs,
                                                                                            kStressPulseTickUs);
                          if (!started) {
                            timeout = true;
                          } else {
                            timeout = !delayWithWatchdog(kStressPulseMs, stage);
                          }
                          conditioningPrinter->endDiagnosticLongPulse();
                          endStressQuiet("gripper_static_condition_release");
                          if (timeout || _selfTestAbortRequested) {
                            row.timeout++;
                            row.pass = false;
                            return false;
                          }
                          return true;
                        };

                        auto emitStressSetupFailureRows = [&](const char* gate) -> bool {
                          char metrics[192];
                          snprintf(metrics,
                                   sizeof(metrics),
                                   "home_to=1;timeout=0;ready=1;trace=0;stride=%lu;sample_ms=%lu;gate=%s",
                                   static_cast<unsigned long>(kStressTraceSampleStride),
                                   static_cast<unsigned long>(kStressTraceSampleMs),
                                   gate);
                          if (!runOne(2510u, "gripper_static_pressure_matrix_factory", false, metrics)) return false;
                          if (!runOne(2511u, "gripper_refresh_hold_3psi_factory", false, metrics)) return false;
                          if (!runOne(2512u, "gripper_motion_raster_3psi_factory", false, metrics)) return false;
                          return runOne(2513u, "gripper_post_motion_seal_compare_factory", false, metrics);
                        };

                        Printer* printer = Printer::instance();
                        PressureSensor* sensor = PressureSensor::instance();
                        if (!homeStressPressureRegulators() || printer == nullptr || sensor == nullptr) {
                          closeStressPressurePath();
                          if (_selfTestAbortRequested) {
                            aborted = true;
                            return finishSelfTestNow();
                          }
                          (void)emitStressSetupFailureRows("home_reference");
                          return finishSelfTestNow();
                        }

                        const uint32_t originalRefreshMs = MX_GRIPPER_GetRefreshPeriodMs();
                        MX_GRIPPER_SetRefreshPeriodMs(kStressRefreshMs);
                        xEventGroupClearBits(_doneEvents, BIT_GRIPPER_DONE);
                        MX_GRIPPER_Close();
                        const bool gripperClosed = waitBitsWithTimeout(BIT_GRIPPER_DONE, 7000u);
                        MX_GRIPPER_StopRefresh();
                        if (!gripperClosed) {
                          MX_GRIPPER_SetRefreshPeriodMs(originalRefreshMs);
                          closeStressPressurePath();
                          (void)emitStressSetupFailureRows("gripper_close");
                          return finishSelfTestNow();
                        }

                        GripperStressRowSummary row2510{};
                        const uint16_t stressTargets[3] = {
                            static_cast<uint16_t>(kStressTargetRaw1Psi),
                            static_cast<uint16_t>(kStressTargetRaw2Psi),
                            static_cast<uint16_t>(kStressTargetRaw3Psi),
                        };
                        const uint16_t stressPsiMilli[3] = {1000u, 2000u, 3000u};
                        sendProgressStage("gripper_static_matrix");
                        uint32_t row2510Conditioning = 0u;
                        static constexpr uint16_t kStressStaticMeasuredReps = 5u;
                        for (uint16_t pIdx = 0u; pIdx < 3u && !_selfTestAbortRequested; ++pIdx) {
                          if (runStressConditioningPulse(stressTargets[pIdx],
                                                         row2510,
                                                         "gripper_static_condition")) {
                            row2510Conditioning++;
                          }
                          for (uint16_t rep = 1u; rep <= kStressStaticMeasuredReps && !_selfTestAbortRequested; ++rep) {
                            for (uint8_t channel = 0u; channel < 2u && !_selfTestAbortRequested; ++channel) {
                              char traceName[56];
                              snprintf(traceName,
                                       sizeof(traceName),
                                       "grip_static_ch%c_psi%u_rep%02u",
                                       (channel == 0u) ? 'p' : 'r',
                                       static_cast<unsigned>(stressPsiMilli[pIdx]),
                                       static_cast<unsigned>(rep));
                              if (!runStressTracePulse(2510u,
                                                       traceName,
                                                       channel,
                                                       stressTargets[pIdx],
                                                       row2510,
                                                       "gripper_static_pulse")) {
                                aborted = true;
                                return finishSelfTestNow();
                              }
                            }
                          }
                        }
                        char metrics2510[256];
                        snprintf(metrics2510,
                                 sizeof(metrics2510),
                                 "pulse_ms=%lu;tick_us=%lu;pulses=%lu;cond=%lu;reps=%lu;targets=1_2_3;ready=%lu;timeout=%lu;fresh_to=%lu;focus=1;trace=%u;sc=%lu;ec=%lu;stride=%lu;sample_ms=%lu",
                                 static_cast<unsigned long>(kStressPulseMs),
                                 static_cast<unsigned long>(kStressPulseTickUs),
                                 static_cast<unsigned long>(row2510.pulses),
                                 static_cast<unsigned long>(row2510Conditioning),
                                 static_cast<unsigned long>(kStressStaticMeasuredReps),
                                 static_cast<unsigned long>(row2510.ready),
                                 static_cast<unsigned long>(row2510.timeout),
                                 static_cast<unsigned long>(row2510.freshTo),
                                 static_cast<unsigned>((row2510.traceFail == 0u) ? 1u : 0u),
                                 static_cast<unsigned long>(row2510.sc),
                                 static_cast<unsigned long>(row2510.ec),
                                 static_cast<unsigned long>(kStressTraceSampleStride),
                                 static_cast<unsigned long>(kStressTraceSampleMs));
                        if (!runOne(2510u, "gripper_static_pressure_matrix_factory", row2510.pass, metrics2510)) {
                          return finishSelfTestNow();
                        }

                        GripperStressRowSummary row2511{};
                        MX_GRIPPER_SetRefreshPeriodMs(kStressRefreshMs);
                        MX_GRIPPER_StartRefresh();
                        sendProgressStage("gripper_refresh_hold");
                        const uint32_t refreshStartMs = HAL_GetTick();
                        uint16_t refreshSeq = 0u;
                        while (!_selfTestAbortRequested && ((HAL_GetTick() - refreshStartMs) < kStressRefreshHoldMs)) {
                          const uint32_t elapsedMs = HAL_GetTick() - refreshStartMs;
                          if (elapsedMs < static_cast<uint32_t>(refreshSeq) * kStressPulseIntervalMs) {
                            const uint32_t waitMs = (static_cast<uint32_t>(refreshSeq) * kStressPulseIntervalMs) - elapsedMs;
                            if (!delayWithWatchdog((waitMs > 100u) ? 100u : waitMs, "gripper_refresh_wait")) {
                              row2511.timeout++;
                              row2511.pass = false;
                              break;
                            }
                            continue;
                          }
                          refreshSeq++;
                          const uint8_t channel = (refreshSeq % 2u == 0u) ? 1u : 0u;
                          char traceName[56];
                          snprintf(traceName,
                                   sizeof(traceName),
                                   "grip_refresh_ch%c_psi3000_seq%02u",
                                   (channel == 0u) ? 'p' : 'r',
                                   static_cast<unsigned>(refreshSeq));
                          if (!runStressTracePulse(2511u,
                                                   traceName,
                                                   channel,
                                                   static_cast<uint16_t>(kStressTargetRaw3Psi),
                                                   row2511,
                                                   "gripper_refresh_pulse")) {
                            aborted = true;
                            return finishSelfTestNow();
                          }
                          if (refreshSeq >= 9u) {
                            break;
                          }
                        }
                        char metrics2511[256];
                        snprintf(metrics2511,
                                 sizeof(metrics2511),
                                 "psi=3000;pulse_ms=%lu;pulse_int=%lu;dur_ms=%lu;pulses=%lu;refresh_ms=%lu;refresh=%u;ready=%lu;timeout=%lu;fresh_to=%lu;focus=1;trace=%u;sc=%lu;ec=%lu;stride=%lu;sample_ms=%lu",
                                 static_cast<unsigned long>(kStressPulseMs),
                                 static_cast<unsigned long>(kStressPulseIntervalMs),
                                 static_cast<unsigned long>(kStressRefreshHoldMs),
                                 static_cast<unsigned long>(row2511.pulses),
                                 static_cast<unsigned long>(kStressRefreshMs),
                                 static_cast<unsigned>(Gripper::instance().isRefreshing() ? 1u : 0u),
                                 static_cast<unsigned long>(row2511.ready),
                                 static_cast<unsigned long>(row2511.timeout),
                                 static_cast<unsigned long>(row2511.freshTo),
                                 static_cast<unsigned>((row2511.traceFail == 0u) ? 1u : 0u),
                                 static_cast<unsigned long>(row2511.sc),
                                 static_cast<unsigned long>(row2511.ec),
                                 static_cast<unsigned long>(kStressTraceSampleStride),
                                 static_cast<unsigned long>(kStressTraceSampleMs));
                        if (!runOne(2511u, "gripper_refresh_hold_3psi_factory", row2511.pass, metrics2511)) {
                          return finishSelfTestNow();
                        }

                        GripperStressRowSummary comparePre{};
                        MX_GRIPPER_StopRefresh();
                        for (uint8_t channel = 0u; channel < 2u && !_selfTestAbortRequested; ++channel) {
                          char traceName[56];
                          snprintf(traceName,
                                   sizeof(traceName),
                                   "grip_compare_ch%c_pre_psi3000",
                                   (channel == 0u) ? 'p' : 'r');
                          if (!runStressTracePulse(2513u,
                                                   traceName,
                                                   channel,
                                                   static_cast<uint16_t>(kStressTargetRaw3Psi),
                                                   comparePre,
                                                   "gripper_compare_pre")) {
                            aborted = true;
                            return finishSelfTestNow();
                          }
                        }

                        GripperStressRowSummary row2512{};
                        uint32_t zHomeTimeout = 0u;
                        uint32_t xyHomeTimeout = 0u;
                        uint32_t moveTimeout = 0u;
                        uint32_t guardViolation = 0u;
                        uint32_t boundViolation = 0u;
                        uint32_t parkTimeout = 0u;
                        uint32_t moveCount = 0u;
                        uint32_t plateConfirmed = 0u;
                        uint32_t zPlateTimeout = 0u;
                        bool zPlateMoveStarted = false;
                        const char* row2512Gate = nullptr;
                        MotionQualificationMath::AxisHomeSample xStressHome{};
                        MotionQualificationMath::AxisHomeSample yStressHome{};
                        const bool zHomeOk = runZClearanceHomePreflight("gripper_motion_z_clearance_home",
                                                                        kStressXyHomeFastHz,
                                                                        kStressXyHomeSlowHz,
                                                                        kStressXyHomeBackoffSteps,
                                                                        kStressXyHomeTimeoutMs);
                        if (!zHomeOk) {
                          zHomeTimeout = 1u;
                          row2512Gate = "z_clearance_home";
                          row2512.pass = false;
                        } else {
                          sendProgressStage("gripper_motion_xy_home");
                          const bool xyHomeOk = runXyHomeDiagnosticAttempt(xStressHome,
                                                                           yStressHome,
                                                                           kStressXyHomeFastHz,
                                                                           kStressXyHomeSlowHz,
                                                                           kStressXyHomeBackoffSteps,
                                                                           kStressXyHomeTimeoutMs);
                          if (!xyHomeOk) {
                            xyHomeTimeout = 1u;
                            row2512Gate = "xy_home";
                            row2512.pass = false;
                          } else {
                          uint32_t routeIndex = 0u;
                          const uint32_t totalPoints = kStressPlateRows * kStressPlateCols;
                          uint16_t pulseSeq = 0u;
                          auto nextRasterPoint = [&](int32_t& x, int32_t& y) -> bool {
                            if (routeIndex >= totalPoints) {
                              return false;
                            }
                            const uint32_t row = routeIndex / kStressPlateCols;
                            const uint32_t colIdx = routeIndex % kStressPlateCols;
                            const uint32_t col = ((row % 2u) == 0u) ? colIdx : (kStressPlateCols - 1u - colIdx);
                            x = MotionQualificationMath::interpolateEndpoint(kStressPlateStartX,
                                                                             kStressPlateEndX,
                                                                             row,
                                                                             kStressPlateRows);
                            y = MotionQualificationMath::interpolateEndpoint(kStressPlateStartY,
                                                                             kStressPlateEndY,
                                                                             col,
                                                                             kStressPlateCols);
                            routeIndex++;
                            return true;
                          };
                          auto pointSafe = [&](int32_t x, int32_t y) -> bool {
                            if (x < 0 || y < 0 || x > kStressMaxX || y > kStressMaxY) {
                              boundViolation++;
                              return false;
                            }
                            if (x > 1000 && y < kStressCableGuardMinY) {
                              guardViolation++;
                              return false;
                            }
                            return true;
                          };
                          auto moveNextPoint = [&]() -> bool {
                            int32_t x = 0;
                            int32_t y = 0;
                            if (!nextRasterPoint(x, y)) {
                              return false;
                            }
                            if (!pointSafe(x, y)) {
                              row2512.pass = false;
                              return false;
                            }
                            if (!moveGantryToWithTimeout(x, y, kStressPlateFeedHz, kStressPlateMoveTimeoutMs)) {
                              moveTimeout++;
                              row2512.pass = false;
                              return false;
                            }
                            moveCount++;
                            return true;
                          };
                          bool evapSetupOk = true;
                          sendProgressStage("gripper_motion_plate_setup_anchor");
                          if (!pointSafe(kStressPlateStartX, kStressPlateStartY)) {
                            row2512Gate = "evap_plate_setup";
                            row2512.pass = false;
                            evapSetupOk = false;
                          } else if (!moveGantryToWithTimeout(kStressPlateStartX,
                                                             kStressPlateStartY,
                                                             kStressPlateFeedHz,
                                                             kStressPlateMoveTimeoutMs)) {
                            moveTimeout++;
                            row2512Gate = "evap_plate_setup";
                            row2512.pass = false;
                            evapSetupOk = false;
                          }
                          if (evapSetupOk && !waitForOperatorResume("evap_plate_confirm")) {
                            MX_GRIPPER_SetRefreshPeriodMs(originalRefreshMs);
                            closeStressPressurePath();
                            return finishSelfTestNow();
                          }
                          if (evapSetupOk) {
                            plateConfirmed = 1u;
                            if (!MotionQualificationMath::zPositionInBounds(kStressEvapPlateZ, stressEvapZEnvelope)) {
                              boundViolation++;
                              row2512Gate = "evap_plate_setup";
                              row2512.pass = false;
                              evapSetupOk = false;
                            } else {
                              zPlateMoveStarted = true;
                              if (!moveAxisToWithTimeout(Stepper::stepperZ(),
                                                         BIT_STEPPER3_DONE,
                                                         kStressEvapPlateZ,
                                                         kStressZFeedHz,
                                                         kStressZMoveTimeoutMs)) {
                                zPlateTimeout = 1u;
                                moveTimeout++;
                                row2512Gate = "evap_plate_setup";
                                row2512.pass = false;
                                evapSetupOk = false;
                              } else if (!MotionQualificationMath::zPositionInBounds(Stepper::stepperZ()->getPosition(), stressEvapZEnvelope)) {
                                boundViolation++;
                                row2512Gate = "evap_plate_setup";
                                row2512.pass = false;
                                evapSetupOk = false;
                              }
                            }
                          }
                          if (evapSetupOk) {
                          MX_GRIPPER_SetRefreshPeriodMs(kStressRefreshMs);
                          MX_GRIPPER_StartRefresh();

                          sendProgressStage("gripper_motion_raster");
                          const uint32_t rasterStartMs = HAL_GetTick();
                          uint32_t nextPulseDueMs = 0u;
                          while (!_selfTestAbortRequested && routeIndex < totalPoints) {
                            const uint32_t elapsedMs = HAL_GetTick() - rasterStartMs;
                            if (elapsedMs >= nextPulseDueMs) {
                              pulseSeq++;
                              const uint8_t channel = (pulseSeq % 2u == 0u) ? 1u : 0u;
                              if (!prepareStressPressure(static_cast<uint16_t>(kStressTargetRaw3Psi), row2512)) {
                                nextPulseDueMs += kStressPulseIntervalMs;
                                continue;
                              }
                              beginStressQuiet();
                              const bool focusOk = sensor->beginDiagnosticFocus(channel);
                              if (!focusOk) {
                                endStressQuiet("gripper_motion_quiet_release");
                                row2512.ready++;
                                row2512.pass = false;
                                nextPulseDueMs += kStressPulseIntervalMs;
                                continue;
                              }
                              const PressureTraceConfig traceCfg = configureStressTrace(channel);
                              auto& recorder = PressureTraceRecorder::instance();
                              recorder.arm();
                              const uint32_t traceStartTick = HAL_GetTick();
                              recorder.start(traceStartTick);
                              recordStressGripperMetadata(traceCfg.channel, traceStartTick);
                              bool timeout = !delayWithWatchdog(traceCfg.preRollMs, "gripper_motion_preroll");
                              bool freshOk = false;
                              if (!timeout && !_selfTestAbortRequested) {
                                freshOk = waitFreshStressSample(channel, kStressFreshSampleTimeoutMs);
                                if (!freshOk) {
                                  row2512.freshTo++;
                                }
                              }
                              int32_t pulseX = Stepper::stepperX()->getPosition();
                              int32_t pulseY = Stepper::stepperY()->getPosition();
                              if (!timeout && freshOk && !_selfTestAbortRequested) {
                                const PressureTraceChannel traceChannel = traceCfg.channel;
                                recordStressTraceEvent(traceChannel,
                                                       PressureTraceEventType::PulseStart,
                                                       static_cast<uint16_t>(kStressPulseMs),
                                                       sensor->getLatestRaw(channel),
                                                       traceStartTick);
                                const bool started = printer->beginDiagnosticLongPulse(PulseMode::BOTH,
                                                                                       kStressPulseMs,
                                                                                       kStressPulseTickUs);
                                if (!started) {
                                  timeout = true;
                                } else {
                                  const uint32_t pulseStartMs = HAL_GetTick();
                                  while (!_selfTestAbortRequested && ((HAL_GetTick() - pulseStartMs) < kStressPulseMs) && routeIndex < totalPoints) {
                                    if (!moveNextPoint()) {
                                      break;
                                    }
                                  }
                                  const uint32_t elapsedPulseMs = HAL_GetTick() - pulseStartMs;
                                  if (elapsedPulseMs < kStressPulseMs) {
                                    timeout = !delayWithWatchdog(kStressPulseMs - elapsedPulseMs, "gripper_motion_pulse_wait");
                                  }
                                }
                                printer->endDiagnosticLongPulse();
                                pulseX = Stepper::stepperX()->getPosition();
                                pulseY = Stepper::stepperY()->getPosition();
                                recordStressTraceEvent(traceChannel,
                                                       PressureTraceEventType::PulseEnd,
                                                       static_cast<uint16_t>(kStressPulseMs),
                                                       sensor->getLatestRaw(channel),
                                                       traceStartTick);
                              }
                              if (!timeout && !_selfTestAbortRequested) {
                                timeout = !delayWithWatchdog(traceCfg.postRollMs, "gripper_motion_postroll");
                              }
                              recorder.stop(HAL_GetTick());
                              sensor->endDiagnosticFocus();
                              endStressQuiet("gripper_motion_quiet_release");
                              row2512.pulses++;
                              if (timeout || _selfTestAbortRequested) {
                                row2512.timeout++;
                                row2512.pass = false;
                              }
                              char traceName[72];
                              snprintf(traceName,
                                       sizeof(traceName),
                                       "grip_motion_ch%c_psi3000_seq%02u_x%ld_y%ld",
                                       (channel == 0u) ? 'p' : 'r',
                                       static_cast<unsigned>(pulseSeq),
                                       static_cast<long>(pulseX),
                                       static_cast<long>(pulseY));
                              const bool traceOk = !timeout && freshOk && (recorder.sampleCount() > 0u) && (recorder.eventCount() > 0u);
                              if (!finishStressTrace(2512u, traceName, traceOk, row2512)) {
                                aborted = true;
                                return finishSelfTestNow();
                              }
                              nextPulseDueMs += kStressPulseIntervalMs;
                            } else if (!moveNextPoint()) {
                              break;
                            }
                          }
                          while (!_selfTestAbortRequested && routeIndex < totalPoints && moveTimeout == 0u && guardViolation == 0u && boundViolation == 0u) {
                            if (!moveNextPoint()) {
                              break;
                            }
                          }
                          if (!_selfTestAbortRequested && moveTimeout == 0u && guardViolation == 0u && boundViolation == 0u) {
                            sendProgressStage("gripper_motion_return_plate_start");
                            if (!pointSafe(kStressPlateStartX, kStressPlateStartY)) {
                              row2512Gate = "evap_plate_teardown";
                              row2512.pass = false;
                            } else if (!moveGantryToWithTimeout(kStressPlateStartX,
                                                               kStressPlateStartY,
                                                               kStressPlateFeedHz,
                                                               kStressPlateMoveTimeoutMs)) {
                              moveTimeout++;
                              row2512Gate = "evap_plate_teardown";
                              row2512.pass = false;
                            }
                          }
                          if (!_selfTestAbortRequested && zPlateMoveStarted) {
                            MotionQualificationMath::AxisHomeSample zPostRasterHome{};
                            sendProgressStage("gripper_motion_z_home_after_raster");
                            if (!runAxisHomeDiagnosticAttempt(Stepper::stepperZ(),
                                                              BIT_HOME_Z_DONE,
                                                              zPostRasterHome,
                                                              kStressXyHomeFastHz,
                                                              kStressXyHomeSlowHz,
                                                              kStressXyHomeBackoffSteps,
                                                              kStressXyHomeTimeoutMs)) {
                              zHomeTimeout++;
                              if (row2512Gate == nullptr) {
                                row2512Gate = "evap_plate_teardown";
                              }
                              row2512.pass = false;
                            }
                          }
                          if (!_selfTestAbortRequested && moveTimeout == 0u && guardViolation == 0u && boundViolation == 0u && zHomeTimeout == 0u) {
                            sendProgressStage("gripper_motion_park");
                            if (!pointSafe(kStressParkX, kStressParkY)) {
                              row2512.pass = false;
                            } else if (!moveGantryToWithTimeout(kStressParkX,
                                                                kStressParkY,
                                                                kStressPlateFeedHz,
                                                                kStressPlateMoveTimeoutMs)) {
                              parkTimeout++;
                              moveTimeout++;
                              row2512.pass = false;
                            }
                          }
                          } else if (row2512Gate == nullptr) {
                            row2512Gate = "evap_plate_setup";
                          }
                          }
                        }
                        if ((moveTimeout != 0u || guardViolation != 0u || boundViolation != 0u) &&
                            row2512Gate == nullptr &&
                            plateConfirmed == 1u) {
                          row2512Gate = "evap_plate_teardown";
                        }
                        row2512.pass = row2512.pass &&
                                       !_selfTestAbortRequested &&
                                       (zHomeTimeout == 0u) &&
                                       (xyHomeTimeout == 0u) &&
                                       (plateConfirmed == 1u) &&
                                       (zPlateTimeout == 0u) &&
                                       (moveTimeout == 0u) &&
                                       (guardViolation == 0u) &&
                                       (boundViolation == 0u) &&
                                       (parkTimeout == 0u) &&
                                       (row2512.ready == 0u) &&
                                       (row2512.timeout == 0u) &&
                                       (row2512.traceFail == 0u) &&
                                       (row2512.pulses > 0u);
                        // Keep this row under the self-test result metric budget for the
                        // 32-byte truncated test name; trace artifacts carry detailed data.
                        char metrics2512[224];
                        snprintf(metrics2512,
                                 sizeof(metrics2512),
                                 "psi=3000;pc=%lu;pz=%ld;z_to=%lu;z_home_to=%lu;pulses=%lu;moves=%lu;xy_home_to=%lu;move_to=%lu;guard=%lu;bound=%lu;park_to=%lu;ready=%lu;timeout=%lu;fresh_to=%lu;focus=1;trace=%u;sc=%lu;stride=%lu;sample_ms=%lu",
                                 static_cast<unsigned long>(plateConfirmed),
                                 static_cast<long>(kStressEvapPlateZ),
                                 static_cast<unsigned long>(zPlateTimeout),
                                 static_cast<unsigned long>(zHomeTimeout),
                                 static_cast<unsigned long>(row2512.pulses),
                                 static_cast<unsigned long>(moveCount),
                                 static_cast<unsigned long>(xyHomeTimeout),
                                 static_cast<unsigned long>(moveTimeout),
                                 static_cast<unsigned long>(guardViolation),
                                 static_cast<unsigned long>(boundViolation),
                                 static_cast<unsigned long>(parkTimeout),
                                 static_cast<unsigned long>(row2512.ready),
                                 static_cast<unsigned long>(row2512.timeout),
                                 static_cast<unsigned long>(row2512.freshTo),
                                 static_cast<unsigned>((row2512.traceFail == 0u) ? 1u : 0u),
                                 static_cast<unsigned long>(row2512.sc),
                                 static_cast<unsigned long>(kStressTraceSampleStride),
                                 static_cast<unsigned long>(kStressTraceSampleMs));
                        if (!runOne(2512u, "gripper_motion_raster_3psi_factory", row2512.pass, metrics2512)) {
                          return finishSelfTestNow();
                        }
                        if (row2512Gate != nullptr || _selfTestAbortRequested) {
                          const char* gate = (row2512Gate != nullptr) ? row2512Gate : "abort";
                          char skipMetrics[192];
                          snprintf(skipMetrics,
                                   sizeof(skipMetrics),
                                   "psi=3000;pulse_ms=%lu;pre=%lu;post=0;ready=0;timeout=0;fresh_to=0;focus=0;trace=0;sc=0;ec=0;stride=%lu;sample_ms=%lu;gate=%s",
                                   static_cast<unsigned long>(kStressPulseMs),
                                   static_cast<unsigned long>(comparePre.pulses),
                                   static_cast<unsigned long>(kStressTraceSampleStride),
                                   static_cast<unsigned long>(kStressTraceSampleMs),
                                   gate);
                          (void)runOne(2513u, "gripper_post_motion_seal_compare_factory", false, skipMetrics);
                          MX_GRIPPER_SetRefreshPeriodMs(originalRefreshMs);
                          closeStressPressurePath();
                          return finishSelfTestNow();
                        }

                        GripperStressRowSummary comparePost{};
                        MX_GRIPPER_StopRefresh();
                        for (uint8_t channel = 0u; channel < 2u && !_selfTestAbortRequested; ++channel) {
                          char traceName[56];
                          snprintf(traceName,
                                   sizeof(traceName),
                                   "grip_compare_ch%c_post_psi3000",
                                   (channel == 0u) ? 'p' : 'r');
                          if (!runStressTracePulse(2513u,
                                                   traceName,
                                                   channel,
                                                   static_cast<uint16_t>(kStressTargetRaw3Psi),
                                                   comparePost,
                                                   "gripper_compare_post")) {
                            aborted = true;
                            return finishSelfTestNow();
                          }
                        }
                        const bool comparePass = comparePre.pass &&
                                                 comparePost.pass &&
                                                 !_selfTestAbortRequested;
                        char metrics2513[256];
                        snprintf(metrics2513,
                                 sizeof(metrics2513),
                                 "psi=3000;pulse_ms=%lu;pre=%lu;post=%lu;ready=%lu;timeout=%lu;fresh_to=%lu;focus=1;trace=%u;sc=%lu;ec=%lu;stride=%lu;sample_ms=%lu",
                                 static_cast<unsigned long>(kStressPulseMs),
                                 static_cast<unsigned long>(comparePre.pulses),
                                 static_cast<unsigned long>(comparePost.pulses),
                                 static_cast<unsigned long>(comparePre.ready + comparePost.ready),
                                 static_cast<unsigned long>(comparePre.timeout + comparePost.timeout),
                                 static_cast<unsigned long>(comparePre.freshTo + comparePost.freshTo),
                                 static_cast<unsigned>(((comparePre.traceFail + comparePost.traceFail) == 0u) ? 1u : 0u),
                                 static_cast<unsigned long>(comparePre.sc + comparePost.sc),
                                 static_cast<unsigned long>(comparePre.ec + comparePost.ec),
                                 static_cast<unsigned long>(kStressTraceSampleStride),
                                 static_cast<unsigned long>(kStressTraceSampleMs));
                        if (!runOne(2513u, "gripper_post_motion_seal_compare_factory", comparePass, metrics2513)) {
                          return finishSelfTestNow();
                        }

                        MX_GRIPPER_SetRefreshPeriodMs(originalRefreshMs);
                        closeStressPressurePath();
                        return finishSelfTestNow();
                      }

                      if (runGripperSealSuite) {
                        static constexpr uint32_t kSetupTimeoutMs = 5000u;
                        static constexpr uint32_t kPulseMs = 2000u;
                        static constexpr uint32_t kPulseTickUs = 100u;
                        static constexpr uint32_t kConditioningBurstCount = 2u;
                        static constexpr uint32_t kConditioningBurstPeriodMs = 5000u;
                        static constexpr uint32_t kHoldBurstCount = 6u;
                        static constexpr uint32_t kHoldBurstPeriodMs = 10000u;
                        static constexpr uint32_t kRepeatBurstCount = 3u;
                        static constexpr uint32_t kRepeatBurstPeriodMs = 5000u;
                        static constexpr uint32_t kSealDropThresholdRaw = 100u;
                        static constexpr uint32_t kSealTargetPsiMilli = 1000u;
                        static constexpr int32_t kSealTargetRaw = static_cast<int32_t>(
                            1638u + ((kSealTargetPsiMilli * 13107u + 7500u) / 15000u));
                        uint32_t gripperCloseCount = 0u;
                        const char* headValveMode =
                        #if (LC_PRESSURE_PORTS > 1)
                            "both";
                        #else
                            "print";
                        #endif

                        struct SealRun {
                          bool setupOk = false;
                          bool timeout = false;
                          bool headValveActive = false;
                          bool regulatorPaused = false;
                          int32_t targetRaw = 0;
                          int32_t pStartRaw = 0;
                          int32_t pEndRaw = 0;
                          int32_t rStartRaw = 0;
                          int32_t rEndRaw = 0;
                          uint32_t pDropRaw = 0u;
                          uint32_t rDropRaw = 0u;
                          uint32_t dropRaw = 0u;
                          uint32_t pulseMs = 0u;
                          uint32_t readyMs = 0u;
                        };

                        PressureSensor* sensor = PressureSensor::instance();
                        Printer* printer = Printer::instance();

                        auto closePressurePath = [&]() {
                          if (printer != nullptr) {
                            printer->endDiagnosticLongPulse();
                          }
                          PressureRegulator::regP().pause();
                          PressureRegulator::regP().closeValve();
                        #if (LC_PRESSURE_PORTS > 1)
                          PressureRegulator::regR().pause();
                          PressureRegulator::regR().closeValve();
                        #endif
                        };

                        auto emitFailureRowsFrom = [&](uint16_t firstTestId,
                                                       const char* phase,
                                                       uint32_t conditioningCompleted,
                                                       bool gripperOk,
                                                       bool regulatorPaused,
                                                       uint32_t readyMs) -> bool {
                          char metrics[224];
                          snprintf(metrics, sizeof(metrics),
                                   "target_raw=%ld;valve_drive=diagnostic_one_pulse;pulse_ms=%lu;tick_us=%lu;bursts=0;phase=%s;cond_done=%lu;reg_pause=%u;grip=%lu;refresh=0;drop_raw=0;ready_ms=%lu;timeout=1;grip_ok=%u",
                                   static_cast<long>(kSealTargetRaw),
                                   static_cast<unsigned long>(kPulseMs),
                                   static_cast<unsigned long>(kPulseTickUs),
                                   phase,
                                   static_cast<unsigned long>(conditioningCompleted),
                                   static_cast<unsigned>(regulatorPaused ? 1u : 0u),
                                   static_cast<unsigned long>(gripperCloseCount),
                                   static_cast<unsigned long>(readyMs),
                                   static_cast<unsigned>(gripperOk ? 1u : 0u));
                          if ((firstTestId <= 2501u) &&
                              !runOne(2501, "gripper_seal_closed_decay_factory", false, metrics)) return false;
                          if ((firstTestId <= 2502u) &&
                              !runOne(2502, "gripper_seal_hold_duration_factory", false, metrics)) return false;
                          if ((firstTestId <= 2503u) &&
                              !runOne(2503, "gripper_seal_repeatability_factory", false, metrics)) return false;
                          return true;
                        };

                        auto runSealBurst = [&](uint32_t pulseMs) -> SealRun {
                          SealRun run{};
                          run.pulseMs = pulseMs;
                          run.targetRaw = kSealTargetRaw;
                          if (!sensor || !printer) {
                            run.timeout = true;
                            closePressurePath();
                            return run;
                          }

                          PressureRegulator& regP = PressureRegulator::regP();
                          const bool stepUpP = static_cast<int32_t>(sensor->getControlSample(0u).raw) <= kSealTargetRaw;
                          regP.closeValve();
                          regP.start();
                          xEventGroupClearBits(_doneEvents, BIT_PRESSURE_P_READY);
                          regP.setTargetSafe(kSealTargetRaw);
                          run.targetRaw = static_cast<int32_t>(regP.getTarget());
                          const PressureWaitResult readyP = waitPressureReady(regP,
                                                                              0u,
                                                                              run.targetRaw,
                                                                              stepUpP,
                                                                              kSetupTimeoutMs,
                                                                              kSealDropThresholdRaw);
                          run.readyMs = readyP.settleMs;
                          bool readyOk = readyP.accepted;
#if (LC_PRESSURE_PORTS > 1)
                          PressureRegulator& regR = PressureRegulator::regR();
                          const bool stepUpR = static_cast<int32_t>(sensor->getControlSample(1u).raw) <= kSealTargetRaw;
                          regR.closeValve();
                          regR.start();
                          xEventGroupClearBits(_doneEvents, BIT_PRESSURE_R_READY);
                          regR.setTargetSafe(kSealTargetRaw);
                          const PressureWaitResult readyR = waitPressureReady(regR,
                                                                              1u,
                                                                              static_cast<int32_t>(regR.getTarget()),
                                                                              stepUpR,
                                                                              kSetupTimeoutMs,
                                                                              kSealDropThresholdRaw);
                          if (readyR.settleMs > run.readyMs) {
                            run.readyMs = readyR.settleMs;
                          }
                          readyOk = readyOk && readyR.accepted;
#endif
                          if (!readyOk || _selfTestAbortRequested) {
                            run.timeout = true;
                            closePressurePath();
                            return run;
                          }

                          regP.pause();
#if (LC_PRESSURE_PORTS > 1)
                          regR.pause();
#endif
                          run.regulatorPaused = true;
                          run.pStartRaw = static_cast<int32_t>(sensor->getControlSample(0u).raw);
#if (LC_PRESSURE_PORTS > 1)
                          run.rStartRaw = static_cast<int32_t>(sensor->getControlSample(1u).raw);
#endif
                          run.headValveActive = printer->beginDiagnosticLongPulse(PulseMode::BOTH,
                                                                                  pulseMs,
                                                                                  kPulseTickUs);
                          if (!run.headValveActive) {
                            run.timeout = true;
                            closePressurePath();
                            return run;
                          }

                          int32_t currentP = run.pStartRaw;
                          int32_t currentR = run.rStartRaw;
                          const uint32_t startMs = HAL_GetTick();
                          while ((HAL_GetTick() - startMs) < pulseMs) {
                            Watchdog_CheckIn(CRASH_TASK_ORCH);
                            maybeSendProgress("gripper_seal_burst");
                            if (_selfTestAbortRequested) {
                              run.timeout = true;
                              break;
                            }
                            currentP = static_cast<int32_t>(sensor->getControlSample(0u).raw);
#if (LC_PRESSURE_PORTS > 1)
                            currentR = static_cast<int32_t>(sensor->getControlSample(1u).raw);
#endif
                            const uint32_t pDrop = GripperSealQualificationMath::absDiff(run.pStartRaw, currentP);
                            if (pDrop > run.pDropRaw) run.pDropRaw = pDrop;
#if (LC_PRESSURE_PORTS > 1)
                            const uint32_t rDrop = GripperSealQualificationMath::absDiff(run.rStartRaw, currentR);
                            if (rDrop > run.rDropRaw) run.rDropRaw = rDrop;
#endif
                            vTaskDelay(pdMS_TO_TICKS(100u));
                          }
                          currentP = static_cast<int32_t>(sensor->getControlSample(0u).raw);
#if (LC_PRESSURE_PORTS > 1)
                          currentR = static_cast<int32_t>(sensor->getControlSample(1u).raw);
#endif
                          run.pEndRaw = currentP;
#if (LC_PRESSURE_PORTS > 1)
                          run.rEndRaw = currentR;
#endif
                          const uint32_t pEndDrop = GripperSealQualificationMath::absDiff(run.pStartRaw, run.pEndRaw);
                          if (pEndDrop > run.pDropRaw) run.pDropRaw = pEndDrop;
#if (LC_PRESSURE_PORTS > 1)
                          const uint32_t rEndDrop = GripperSealQualificationMath::absDiff(run.rStartRaw, run.rEndRaw);
                          if (rEndDrop > run.rDropRaw) run.rDropRaw = rEndDrop;
#endif
                          run.dropRaw = (run.rDropRaw > run.pDropRaw) ? run.rDropRaw : run.pDropRaw;
                          run.setupOk = !run.timeout && !_selfTestAbortRequested;
                          printer->endDiagnosticLongPulse();
                          if (run.setupOk) {
                            regP.closeValve();
                            regP.start();
                            regP.setTargetSafe(kSealTargetRaw);
#if (LC_PRESSURE_PORTS > 1)
                            regR.closeValve();
                            regR.start();
                            regR.setTargetSafe(kSealTargetRaw);
#endif
                          }
                          return run;
                        };

                        auto waitForRegulatorHome = [&](EventBits_t doneBits,
                                                         uint32_t timeoutMs) -> bool {
                          const uint32_t startMs = HAL_GetTick();
                          while ((HAL_GetTick() - startMs) < timeoutMs) {
                            Watchdog_CheckIn(CRASH_TASK_ORCH);
                            maybeSendProgress("gripper_seal_reg_home");
                            if (_selfTestAbortRequested) {
                              return false;
                            }
                            const EventBits_t observed = xEventGroupGetBits(_doneEvents);
                            if ((observed & doneBits) == doneBits) {
                              return true;
                            }
                            vTaskDelay(msToAtLeast1Tick(25u));
                          }
                          return false;
                        };

                        auto homePressureRegulators = [&]() -> bool {
                          static constexpr uint32_t kRegHomeFastHz = 30000u;
                          static constexpr uint32_t kRegHomeSlowHz = 3000u;
                          static constexpr uint32_t kRegHomeBackoffSteps = 400u;
                          static constexpr uint32_t kRegHomeTimeoutMs = 20000u;

                          closePressurePath();
                          sendProgressStage("gripper_seal_reg_home");
                          EventBits_t homeBits = BIT_HOME_P_DONE;
#if (LC_PRESSURE_PORTS > 1)
                          homeBits |= BIT_HOME_R_DONE;
#endif
                          xEventGroupClearBits(_doneEvents, homeBits);
                          startRegHomeAsync(&PressureRegulator::regP(),
                                            kRegHomeFastHz,
                                            kRegHomeSlowHz,
                                            kRegHomeBackoffSteps,
                                            BIT_HOME_P_DONE);
#if (LC_PRESSURE_PORTS > 1)
                          startRegHomeAsync(&PressureRegulator::regR(),
                                            kRegHomeFastHz,
                                            kRegHomeSlowHz,
                                            kRegHomeBackoffSteps,
                                            BIT_HOME_R_DONE);
#endif
                          const bool homesDone = waitForRegulatorHome(homeBits, kRegHomeTimeoutMs);
                          bool homeOk = homesDone &&
                              (Stepper::stepperP() != nullptr) &&
                              Stepper::stepperP()->getLastHomeDiagnosticSnapshot().success;
#if (LC_PRESSURE_PORTS > 1)
                          homeOk = homeOk &&
                              (Stepper::stepperR() != nullptr) &&
                              Stepper::stepperR()->getLastHomeDiagnosticSnapshot().success;
#endif
                          closePressurePath();
                          return homeOk && !_selfTestAbortRequested;
                        };

                        if (!homePressureRegulators()) {
                          closePressurePath();
                          if (_selfTestAbortRequested) {
                            aborted = true;
                            return finishSelfTestNow();
                          }
                          (void)emitFailureRowsFrom(2501u, "home", 0u, false, false, 0u);
                          return finishSelfTestNow();
                        }

                        xEventGroupClearBits(_doneEvents, BIT_GRIPPER_DONE);
                        MX_GRIPPER_Close();
                        gripperCloseCount++;
                        const bool gripperCommandOk = waitForBit(BIT_GRIPPER_DONE);
                        MX_GRIPPER_StopRefresh();

                        if (!gripperCommandOk || !sensor || !printer) {
                          closePressurePath();
                          (void)emitFailureRowsFrom(2501u, "grip", 0u, gripperCommandOk, false, 0u);
                          return finishSelfTestNow();
                        }

                        uint32_t conditioningCompleted = 0u;
                        uint32_t conditioningReadyMs = 0u;
                        bool conditioningRegulatorPaused = true;
                        bool conditioningOk = true;
                        for (uint32_t idx = 0u; idx < kConditioningBurstCount; ++idx) {
                          sendProgressStage("gripper_seal_conditioning");
                          const SealRun conditioningRun = runSealBurst(kPulseMs);
                          conditioningReadyMs = conditioningRun.readyMs;
                          conditioningRegulatorPaused = conditioningRegulatorPaused && conditioningRun.regulatorPaused;
                          if (!conditioningRun.setupOk) {
                            conditioningOk = false;
                            break;
                          }
                          conditioningCompleted++;
                          if ((idx + 1u) < kConditioningBurstCount) {
                            const uint32_t waitMs = (kConditioningBurstPeriodMs > kPulseMs)
                                ? (kConditioningBurstPeriodMs - kPulseMs)
                                : 1u;
                            if (!delayWithWatchdog(waitMs, "gripper_seal_conditioning")) {
                              conditioningOk = false;
                              break;
                            }
                          }
                        }
                        if (!conditioningOk || (conditioningCompleted != kConditioningBurstCount)) {
                          closePressurePath();
                          (void)emitFailureRowsFrom(2501u,
                                                    "condition",
                                                    conditioningCompleted,
                                                    gripperCommandOk,
                                                    conditioningRegulatorPaused,
                                                    conditioningReadyMs);
                          return finishSelfTestNow();
                        }

                        const SealRun shortRun = runSealBurst(kPulseMs);
                        char metrics2501[224];
                        snprintf(metrics2501, sizeof(metrics2501),
                                 "target_raw=%ld;valve_drive=diagnostic_one_pulse;pulse_ms=%lu;tick_us=%lu;bursts=1;head_valve_mode=%s;reg_vent=0;reg_pause=%u;grip=%lu;refresh=0;p_drop=%lu;r_drop=%lu;drop_raw=%lu;timeout=%u",
                                 static_cast<long>(shortRun.targetRaw),
                                 static_cast<unsigned long>(kPulseMs),
                                 static_cast<unsigned long>(kPulseTickUs),
                                 headValveMode,
                                 static_cast<unsigned>(shortRun.regulatorPaused ? 1u : 0u),
                                 static_cast<unsigned long>(gripperCloseCount),
                                 static_cast<unsigned long>(shortRun.pDropRaw),
                                 static_cast<unsigned long>(shortRun.rDropRaw),
                                 static_cast<unsigned long>(shortRun.dropRaw),
                                 static_cast<unsigned>(shortRun.timeout ? 1u : 0u));
                        if (!runOne(2501, "gripper_seal_closed_decay_factory", shortRun.setupOk, metrics2501)) {
                          closePressurePath();
                          return finishSelfTestNow();
                        }
                        if (!shortRun.setupOk) {
                          closePressurePath();
                          (void)emitFailureRowsFrom(2502u,
                                                    "skipped",
                                                    conditioningCompleted,
                                                    gripperCommandOk,
                                                    shortRun.regulatorPaused,
                                                    shortRun.readyMs);
                          return finishSelfTestNow();
                        }

                        uint32_t holdDrops[kHoldBurstCount]{};
                        uint32_t holdCompleted = 0u;
                        bool holdSetupOk = true;
                        int32_t holdPStart = 0;
                        int32_t holdPEnd = 0;
                        int32_t holdRStart = 0;
                        int32_t holdREnd = 0;
                        uint32_t holdPDropMax = 0u;
                        uint32_t holdRDropMax = 0u;
                        bool holdRegulatorPaused = true;
                        for (uint32_t idx = 0u; idx < kHoldBurstCount; ++idx) {
                          const SealRun burstRun = runSealBurst(kPulseMs);
                          holdRegulatorPaused = holdRegulatorPaused && burstRun.regulatorPaused;
                          if (!burstRun.setupOk) {
                            holdSetupOk = false;
                            break;
                          }
                          if (holdCompleted == 0u) {
                            holdPStart = burstRun.pStartRaw;
                            holdRStart = burstRun.rStartRaw;
                          }
                          holdPEnd = burstRun.pEndRaw;
                          holdREnd = burstRun.rEndRaw;
                          if (burstRun.pDropRaw > holdPDropMax) holdPDropMax = burstRun.pDropRaw;
                          if (burstRun.rDropRaw > holdRDropMax) holdRDropMax = burstRun.rDropRaw;
                          holdDrops[holdCompleted] = burstRun.dropRaw;
                          holdCompleted++;
                          const uint32_t waitMs = (kHoldBurstPeriodMs > kPulseMs)
                              ? (kHoldBurstPeriodMs - kPulseMs)
                              : 1u;
                          if (!delayWithWatchdog(waitMs, "gripper_seal_between_bursts")) {
                            holdSetupOk = false;
                            break;
                          }
                        }
                        const auto holdSummary = GripperSealQualificationMath::summarizeBurstDrops(
                            holdDrops,
                            holdCompleted,
                            kHoldBurstPeriodMs,
                            kSealDropThresholdRaw);
                        char metrics2502[192];
                        snprintf(metrics2502, sizeof(metrics2502),
                                 "target_raw=%ld;valve_drive=diagnostic_one_pulse;pulse_ms=%lu;tick_us=%lu;bursts=%lu;head_valve_mode=%s;reg_vent=0;reg_pause=%u;p_drop=%lu;r_drop=%lu;drop_raw=%lu;seal_ms=%lu;timeout=%u",
                                 static_cast<long>(kSealTargetRaw),
                                 static_cast<unsigned long>(kPulseMs),
                                 static_cast<unsigned long>(kPulseTickUs),
                                 static_cast<unsigned long>(holdCompleted),
                                 headValveMode,
                                 static_cast<unsigned>(holdRegulatorPaused ? 1u : 0u),
                                 static_cast<unsigned long>(holdPDropMax),
                                 static_cast<unsigned long>(holdRDropMax),
                                 static_cast<unsigned long>(holdSummary.maxDropRaw),
                                 static_cast<unsigned long>(holdSummary.sealPassDurationMs),
                                 static_cast<unsigned>(holdSetupOk && (holdCompleted == kHoldBurstCount) ? 0u : 1u));
                        (void)holdPStart;
                        (void)holdPEnd;
                        (void)holdRStart;
                        (void)holdREnd;
                        if (!runOne(2502,
                                    "gripper_seal_hold_duration_factory",
                                    holdSetupOk && (holdCompleted == kHoldBurstCount),
                                    metrics2502)) {
                          closePressurePath();
                          return finishSelfTestNow();
                        }
                        if (!holdSetupOk || (holdCompleted != kHoldBurstCount)) {
                          closePressurePath();
                          (void)emitFailureRowsFrom(2503u,
                                                    "skipped",
                                                    conditioningCompleted,
                                                    gripperCommandOk,
                                                    holdRegulatorPaused,
                                                    0u);
                          return finishSelfTestNow();
                        }

                        uint32_t repeatDrops[kRepeatBurstCount]{};
                        uint32_t repeatSealMs[kRepeatBurstCount]{};
                        uint32_t repeatCompleted = 0u;
                        bool repeatSetupOk = true;
                        bool repeatRegulatorPaused = true;
                        for (uint32_t idx = 0u; idx < kRepeatBurstCount; ++idx) {
                          const SealRun repeatRun = runSealBurst(kPulseMs);
                          repeatRegulatorPaused = repeatRegulatorPaused && repeatRun.regulatorPaused;
                          if (!repeatRun.setupOk) {
                            repeatSetupOk = false;
                            break;
                          }
                          repeatDrops[repeatCompleted] = repeatRun.dropRaw;
                          repeatSealMs[repeatCompleted] = (repeatRun.dropRaw <= kSealDropThresholdRaw)
                              ? kRepeatBurstPeriodMs
                              : 0u;
                          repeatCompleted++;
                          const uint32_t waitMs = (kRepeatBurstPeriodMs > kPulseMs)
                              ? (kRepeatBurstPeriodMs - kPulseMs)
                              : 1u;
                          if (!delayWithWatchdog(waitMs, "gripper_seal_repeat_wait")) {
                            repeatSetupOk = false;
                            break;
                          }
                        }
                        const uint32_t repeatSpan = GripperSealQualificationMath::spanRaw(repeatDrops, repeatCompleted);
                        const uint32_t sealMsMin = GripperSealQualificationMath::minValue(repeatSealMs, repeatCompleted);
                        char metrics2503[224];
                        snprintf(metrics2503, sizeof(metrics2503),
                                 "target_raw=%ld;valve_drive=diagnostic_one_pulse;pulse_ms=%lu;tick_us=%lu;bursts=%lu;head_valve_mode=%s;reg_vent=0;reg_pause=%u;grip=%lu;refresh=0;repeat_span_raw=%lu;seal_ms_min=%lu;timeout=%u",
                                 static_cast<long>(kSealTargetRaw),
                                 static_cast<unsigned long>(kPulseMs),
                                 static_cast<unsigned long>(kPulseTickUs),
                                 static_cast<unsigned long>(repeatCompleted),
                                 headValveMode,
                                 static_cast<unsigned>(repeatRegulatorPaused ? 1u : 0u),
                                 static_cast<unsigned long>(gripperCloseCount),
                                 static_cast<unsigned long>(repeatSpan),
                                 static_cast<unsigned long>(sealMsMin),
                                 static_cast<unsigned>(repeatSetupOk ? 0u : 1u));
                        if (!runOne(2503,
                                    "gripper_seal_repeatability_factory",
                                    repeatSetupOk && (repeatCompleted == kRepeatBurstCount),
                                    metrics2503)) {
                          closePressurePath();
                          return finishSelfTestNow();
                        }

                        closePressurePath();
                        return finishSelfTestNow();
                      }

                      if (runProfileLutBenchmark) {
                        static constexpr uint32_t kRequiredCoreClockHz = 180000000u;
                        static constexpr uint32_t kLutCycleBudget = 225u;
                        static constexpr uint32_t kPrepareCycleBudget = 1800u;
                        static constexpr uint32_t kRequiredSpeedupX100 = 400u;
                        static constexpr uint32_t kMaximumArrError = 2u;
                        static constexpr size_t kMetricsFrameLimit = 198u;

                        struct BenchmarkVector {
                          uint32_t startArr;
                          uint32_t targetArr;
                          uint32_t intervals;
                        };
                        static constexpr BenchmarkVector kVectors[] = {
                            {37495u, 7499u, 258u},
                            {19010u, 3802u, 1000u},
                            {5620u, 1124u, 11430u},
                        };

                        CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
                        if ((DWT->CTRL & DWT_CTRL_CYCCNTENA_Msk) == 0u) {
                          DWT->CYCCNT = 0u;
                          DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
                        }

                        bool irqRestoreOk = true;
                        volatile uint32_t checksum = 0u;
                        auto measureCycles = [&](auto&& operation)
                            __attribute__((optimize("O0"), noinline))
                            -> uint32_t {
                          const uint32_t primaskBefore = __get_PRIMASK();
                          __disable_irq();
                          const uint32_t start = DWT->CYCCNT;
                          operation();
                          const uint32_t elapsed = DWT->CYCCNT - start;
                          __set_PRIMASK(primaskBefore);
                          if (__get_PRIMASK() != primaskBefore) {
                            irqRestoreOk = false;
                          }
                          return elapsed;
                        };

                        uint32_t emptyHarnessMax = 0u;
                        uint64_t emptyHarnessTotal = 0u;
                        for (uint32_t i = 0u; i < 16u; ++i) {
                          const uint32_t cycles = measureCycles([&]()
                              __attribute__((optimize("O0"), noipa)) {
                            checksum ^= 0x9E3779B9u;
                          });
                          if (cycles > emptyHarnessMax) emptyHarnessMax = cycles;
                          emptyHarnessTotal += cycles;
                        }

                        auto measurePrepareMax = [&](uint32_t intervals) -> uint32_t {
                          uint32_t maximum = 0u;
                          for (uint32_t repeat = 0u; repeat < 16u; ++repeat) {
                            NormalizedCosineProfile::RampCursor prepared{};
                            const uint32_t cycles = measureCycles([&]() {
                              const auto status = NormalizedCosineProfile::prepare(
                                  {5620u, 1124u, 179u, 0xFFFFFFFFu, intervals}, prepared);
                              checksum ^= prepared.phaseIncrementQ32 ^
                                          static_cast<uint32_t>(status);
                            });
                            if (cycles > maximum) maximum = cycles;
                          }
                          return maximum;
                        };

                        const uint32_t prepareShortMax = measurePrepareMax(1000u);
                        const uint32_t prepareLongMax = measurePrepareMax(11430u);
                        uint32_t lutMax = 0u;
                        uint32_t legacyMax = 0u;
                        uint32_t errorMax = 0u;
                        uint64_t lutTotal = 0u;
                        uint64_t legacyTotal = 0u;
                        uint32_t samples = 0u;

                        Watchdog_CheckIn(CRASH_TASK_ORCH);
                        for (const BenchmarkVector& vector : kVectors) {
                          for (uint32_t direction = 0u; direction < 2u; ++direction) {
                            const uint32_t fromArr =
                                (direction == 0u) ? vector.startArr : vector.targetArr;
                            const uint32_t toArr =
                                (direction == 0u) ? vector.targetArr : vector.startArr;
                            NormalizedCosineProfile::RampCursor cursor{};
                            const auto prepareStatus = NormalizedCosineProfile::prepare(
                                {fromArr, toArr, 179u, 0xFFFFFFFFu, vector.intervals}, cursor);
                            if (prepareStatus != NormalizedCosineProfile::PrepareStatus::Ready) {
                              irqRestoreOk = false;
                              continue;
                            }

                            for (uint32_t k = 0u; k < vector.intervals; ++k) {
                              uint32_t lutArr = 0u;
                              const uint32_t lutCycles = measureCycles([&]()
                                  __attribute__((optimize("O2"))) {
                                lutArr = NormalizedCosineProfile::currentArr(cursor);
                                (void)NormalizedCosineProfile::advance(cursor);
                                checksum = (checksum << 5u) ^ (checksum >> 2u) ^ lutArr;
                              });

                              uint32_t legacyArr = 0u;
                              const uint32_t legacyCycles = measureCycles([&]()
                                  __attribute__((optimize("O0"), noipa)) {
                                const float t = static_cast<float>(k) /
                                                static_cast<float>(vector.intervals);
                                const float ease = StepperProfileMath::ease01(
                                    StepperProfileMath::Profile::SCurveCosine, t);
                                const int32_t offset = static_cast<int32_t>(
                                    (static_cast<float>(toArr) - static_cast<float>(fromArr)) * ease);
                                legacyArr = static_cast<uint32_t>(
                                    static_cast<int64_t>(fromArr) + offset);
                                checksum = (checksum << 5u) ^ (checksum >> 2u) ^ legacyArr;
                              });

                              const uint32_t error = (lutArr >= legacyArr)
                                  ? (lutArr - legacyArr)
                                  : (legacyArr - lutArr);
                              if (error > errorMax) errorMax = error;
                              if (lutCycles > lutMax) lutMax = lutCycles;
                              if (legacyCycles > legacyMax) legacyMax = legacyCycles;
                              lutTotal += lutCycles;
                              legacyTotal += legacyCycles;
                              ++samples;
                            }
                          }
                          Watchdog_CheckIn(CRASH_TASK_ORCH);
                        }

                        const uint32_t lutMean = (samples == 0u)
                            ? 0u
                            : static_cast<uint32_t>(lutTotal / samples);
                        const uint32_t legacyMean = (samples == 0u)
                            ? 0u
                            : static_cast<uint32_t>(legacyTotal / samples);
                        const uint32_t emptyHarnessMean =
                            static_cast<uint32_t>(emptyHarnessTotal / 16u);
                        const uint32_t adjustedLutMean =
                            (lutMean > emptyHarnessMean) ? (lutMean - emptyHarnessMean) : 1u;
                        const uint32_t adjustedLegacyMean =
                            (legacyMean > emptyHarnessMean) ? (legacyMean - emptyHarnessMean) : 0u;
                        const uint32_t speedupX100 = (adjustedLutMean == 0u)
                            ? 0u
                            : static_cast<uint32_t>(
                                  (static_cast<uint64_t>(adjustedLegacyMean) * 100u) /
                                  adjustedLutMean);

                        char metrics[224] = {0};
                        const int metricsLength = snprintf(
                            metrics,
                            sizeof(metrics),
                            "clk=%lu;samples=%lu;lut_max=%lu;lut_mean=%lu;legacy_max=%lu;legacy_mean=%lu;speedup_x100=%lu;prep_short=%lu;prep_long=%lu;err_max=%lu;irq_restore=%u;checksum=%lu",
                            static_cast<unsigned long>(SystemCoreClock),
                            static_cast<unsigned long>(samples),
                            static_cast<unsigned long>(lutMax),
                            static_cast<unsigned long>(lutMean),
                            static_cast<unsigned long>(legacyMax),
                            static_cast<unsigned long>(legacyMean),
                            static_cast<unsigned long>(speedupX100),
                            static_cast<unsigned long>(prepareShortMax),
                            static_cast<unsigned long>(prepareLongMax),
                            static_cast<unsigned long>(errorMax),
                            static_cast<unsigned>(irqRestoreOk ? 1u : 0u),
                            static_cast<unsigned long>(checksum));
                        const bool metricsFit = metricsLength > 0 &&
                            static_cast<size_t>(metricsLength) < sizeof(metrics) &&
                            static_cast<size_t>(metricsLength) <= kMetricsFrameLimit;
                        const bool pass = metricsFit &&
                            SystemCoreClock == kRequiredCoreClockHz &&
                            samples == 25376u &&
                            lutMax <= kLutCycleBudget &&
                            speedupX100 >= kRequiredSpeedupX100 &&
                            prepareShortMax <= kPrepareCycleBudget &&
                            prepareLongMax <= kPrepareCycleBudget &&
                            errorMax <= kMaximumArrError &&
                            irqRestoreOk &&
                            emptyHarnessMax <= lutMax;

                        (void)runOne(2030u,
                                     "profile_lut_cycle_benchmark_safe",
                                     pass,
                                     metricsFit ? metrics : "gate=metrics_overflow");
                        Watchdog_CheckIn(CRASH_TASK_ORCH);
                        return finishSelfTestNow();
                      }

                      if (runCoordinatedXyExecutorSuite) {
#if defined(__GNUC__)
                        auto runCoordinatedExecutorDiagnostic = [&]()
                            __attribute__((optimize("Os"), noinline))
                            -> DiagnosticsSummary {
#else
                        auto runCoordinatedExecutorDiagnostic = [&]() -> DiagnosticsSummary {
#endif
                        static constexpr int32_t kAnchorX = 5000;
                        static constexpr int32_t kAnchorY = 5000;
                        static constexpr uint32_t kCoordinatedRateHz = 3000u;
                        static constexpr uint32_t kLegacySetupRateHz = 6000u;
                        static constexpr uint32_t kMoveTimeoutMs = 20000u;
                        static constexpr uint32_t kControlTimeoutMs = 3000u;
                        static constexpr uint32_t kZHomeFastHz = 30000u;
                        static constexpr uint32_t kZHomeSlowHz = 3000u;
                        static constexpr uint32_t kXyHomeFastHz = 3000u;
                        static constexpr uint32_t kXyHomeSlowHz = 1000u;
                        static constexpr uint32_t kHomeBackoffSteps = 400u;
                        static constexpr uint32_t kHomeTimeoutMs = 20000u;
                        static constexpr uint32_t kControlProgressSteps = 400u;
                        static constexpr uint32_t kPauseHoldMs = 50u;
                        static constexpr uint32_t kIsrCycleBudget = 2250u;
                        static constexpr uint32_t kHomeDriftLimitSteps = 25u;

                        struct ExecutorTestDescriptor {
                          uint16_t testId;
                          const char* name;
                        };
                        static constexpr ExecutorTestDescriptor kExecutorTests[] = {
                            {2040u, "coordinated_xy_x_only_low"},
                            {2041u, "coordinated_xy_y_only_low"},
                            {2042u, "coordinated_xy_equal_low"},
                            {2043u, "coordinated_xy_asymmetric_low"},
                            {2044u, "coordinated_xy_pause_resume"},
                            {2045u, "coordinated_xy_cancel"},
                            {2046u, "coordinated_xy_limit_abort"},
                        };

                        auto emitSkippedExecutor = [&](uint16_t firstTestId,
                                                       const char* gate) -> bool {
                          char metrics[128];
                          snprintf(metrics,
                                   sizeof(metrics),
                                   "gate=%s;hz=3000;to=1;low=0;done=0;i7=0;pu=0",
                                   gate);
                          for (const ExecutorTestDescriptor& test : kExecutorTests) {
                            if (test.testId >= firstTestId &&
                                !runOne(test.testId, test.name, false, metrics)) {
                              return false;
                            }
                          }
                          return true;
                        };

                        Stepper* stepperX = Stepper::stepperX();
                        Stepper* stepperY = Stepper::stepperY();
                        Gantry* gantry = Gantry::instance();
                        if (stepperX == nullptr || stepperY == nullptr || gantry == nullptr) {
                          (void)emitSkippedExecutor(2040u, "motion_unavailable");
                          return finishSelfTestNow();
                        }

                        const uint32_t savedXMaxRateHz = stepperX->maxSpeedHz();
                        const uint32_t savedYMaxRateHz = stepperY->maxSpeedHz();
                        auto restoreXyRates = [&]() {
                          stepperX->setMaxSpeedHz(savedXMaxRateHz);
                          stepperY->setMaxSpeedHz(savedYMaxRateHz);
                        };
                        auto moveLegacyToAnchor = [&]() -> bool {
                          stepperX->setMaxSpeedHz(kLegacySetupRateHz);
                          stepperY->setMaxSpeedHz(kLegacySetupRateHz);
                          const bool reached = moveGantryToWithTimeout(
                              kAnchorX, kAnchorY, kLegacySetupRateHz, kMoveTimeoutMs);
                          restoreXyRates();
                          const GantryPosition position = gantry->getPosition();
                          return reached && position.x == kAnchorX && position.y == kAnchorY;
                        };

                        auto stateTerminal = [](CoordinatedXyExecutor::State state) {
                          return state == CoordinatedXyExecutor::State::Completed ||
                                 state == CoordinatedXyExecutor::State::Canceled ||
                                 state == CoordinatedXyExecutor::State::LimitAborted ||
                                 state == CoordinatedXyExecutor::State::Faulted;
                        };
                        auto waitForTerminal = [&](uint32_t timeoutMs,
                                                   CoordinatedXySnapshot& snapshot) -> bool {
                          const uint32_t startedMs = HAL_GetTick();
                          const TickType_t pollTicks = msToAtLeast1Tick(2u);
                          while ((HAL_GetTick() - startedMs) < timeoutMs) {
                            Watchdog_CheckIn(CRASH_TASK_ORCH);
                            snapshot = gantry->coordinatedSnapshot();
                            if (stateTerminal(snapshot.state)) return true;
                            if (_selfTestAbortRequested) {
                              Gantry::cancelXYZMotors();
                              return false;
                            }
                            vTaskDelay(pollTicks);
                          }
                          Gantry::cancelXYZMotors();
                          snapshot = gantry->coordinatedSnapshot();
                          return false;
                        };
                        auto waitForProgress = [&](uint32_t completedSteps,
                                                   uint32_t timeoutMs,
                                                   CoordinatedXySnapshot& snapshot) -> bool {
                          const uint32_t startedMs = HAL_GetTick();
                          const TickType_t pollTicks = msToAtLeast1Tick(1u);
                          while ((HAL_GetTick() - startedMs) < timeoutMs) {
                            Watchdog_CheckIn(CRASH_TASK_ORCH);
                            snapshot = gantry->coordinatedSnapshot();
                            if (snapshot.fallingEdges >= completedSteps) return true;
                            if (stateTerminal(snapshot.state) || _selfTestAbortRequested) {
                              return false;
                            }
                            vTaskDelay(pollTicks);
                          }
                          return false;
                        };
                        auto waitForState = [&](CoordinatedXyExecutor::State expected,
                                                uint32_t timeoutMs,
                                                CoordinatedXySnapshot& snapshot) -> bool {
                          const uint32_t startedMs = HAL_GetTick();
                          const TickType_t pollTicks = msToAtLeast1Tick(1u);
                          while ((HAL_GetTick() - startedMs) < timeoutMs) {
                            Watchdog_CheckIn(CRASH_TASK_ORCH);
                            snapshot = gantry->coordinatedSnapshot();
                            if (snapshot.state == expected) return true;
                            if (stateTerminal(snapshot.state) || _selfTestAbortRequested) {
                              return false;
                            }
                            vTaskDelay(pollTicks);
                          }
                          return false;
                        };

                        auto completedSnapshotPasses = [&](const CoordinatedXySnapshot& snapshot,
                                                           int32_t expectedX,
                                                           int32_t expectedY) -> bool {
                          const uint32_t doneMask = BIT_STEPPER1_DONE | BIT_STEPPER2_DONE;
                          return snapshot.startStatus == CoordinatedStartStatus::Started &&
                                 snapshot.state == CoordinatedXyExecutor::State::Completed &&
                                 snapshot.terminalReason ==
                                     CoordinatedXyExecutor::TerminalReason::Completed &&
                                 snapshot.emittedXSteps == snapshot.requestedXSteps &&
                                 snapshot.emittedYSteps == snapshot.requestedYSteps &&
                                 snapshot.timer2Interrupts == snapshot.masterSteps * 2u &&
                                 snapshot.risingEdges == snapshot.masterSteps &&
                                 snapshot.fallingEdges == snapshot.masterSteps &&
                                 snapshot.timer7Interrupts == 0u &&
                                 snapshot.pendingUpdateCount == 0u &&
                                 snapshot.maxIsrCycles > 0u &&
                                 snapshot.maxIsrCycles <= kIsrCycleBudget &&
                                 snapshot.xStepLow && snapshot.yStepLow &&
                                 !snapshot.timerOwned &&
                                 snapshot.xPosition == expectedX &&
                                 snapshot.yPosition == expectedY &&
                                 snapshot.xTarget == expectedX &&
                                 snapshot.yTarget == expectedY &&
                                 (snapshot.doneBits & doneMask) == doneMask &&
                                 snapshot.arrMin >= 179u &&
                                 snapshot.arrMax >= snapshot.arrMin;
                        };

                        struct CompleteLegResult {
                          bool started = false;
                          bool terminal = false;
                          bool passed = false;
                          CoordinatedXySnapshot snapshot{};
                        };
                        auto runCompleteLeg = [&](int32_t dx, int32_t dy) -> CompleteLegResult {
                          CompleteLegResult result{};
                          const GantryPosition start = gantry->getPosition();
                          const CoordinatedStartStatus startStatus =
                              gantry->startCoordinatedXY(dx, dy, kCoordinatedRateHz);
                          result.started = startStatus == CoordinatedStartStatus::Started;
                          if (!result.started) {
                            result.snapshot = gantry->coordinatedSnapshot();
                            return result;
                          }
                          result.terminal = waitForTerminal(kMoveTimeoutMs, result.snapshot);
                          result.passed = result.terminal && completedSnapshotPasses(
                              result.snapshot, start.x + dx, start.y + dy);
                          return result;
                        };

                        auto runRoundTrip = [&](uint16_t testId,
                                                const char* name,
                                                int32_t dx,
                                                int32_t dy) -> bool {
                          const GantryPosition start = gantry->getPosition();
                          const CompleteLegResult forward = runCompleteLeg(dx, dy);
                          CompleteLegResult reverse{};
                          if (forward.passed) {
                            reverse = runCompleteLeg(-dx, -dy);
                          }
                          const GantryPosition end = gantry->getPosition();
                          const bool checksumMatch = forward.passed && reverse.passed &&
                              forward.snapshot.maskChecksum == reverse.snapshot.maskChecksum &&
                              forward.snapshot.arrChecksum == reverse.snapshot.arrChecksum;
                          const bool returned = end.x == start.x && end.y == start.y;
                          const bool pass = forward.passed && reverse.passed &&
                                            checksumMatch && returned;
                          const uint32_t maxCycles = std::max(
                              forward.snapshot.maxIsrCycles,
                              reverse.snapshot.maxIsrCycles);
                          char metrics[224];
                          const int metricsLength = snprintf(
                              metrics,
                              sizeof(metrics),
                              "dx=%ld;dy=%ld;hz=%lu;xe=%lu;ye=%lu;ms=%lu;i2=%lu;i7=%lu;edge=%u;ck=%u;low=%u;done=%u;pu=%lu;cy=%lu;ret=%u;to=%u",
                              (long)dx,
                              (long)dy,
                              (unsigned long)kCoordinatedRateHz,
                              (unsigned long)(forward.snapshot.emittedXSteps + reverse.snapshot.emittedXSteps),
                              (unsigned long)(forward.snapshot.emittedYSteps + reverse.snapshot.emittedYSteps),
                              (unsigned long)forward.snapshot.masterSteps,
                              (unsigned long)(forward.snapshot.timer2Interrupts + reverse.snapshot.timer2Interrupts),
                              (unsigned long)(forward.snapshot.timer7Interrupts + reverse.snapshot.timer7Interrupts),
                              (forward.passed && reverse.passed) ? 1u : 0u,
                              checksumMatch ? 1u : 0u,
                              (forward.snapshot.xStepLow && forward.snapshot.yStepLow &&
                               reverse.snapshot.xStepLow && reverse.snapshot.yStepLow) ? 1u : 0u,
                              ((forward.snapshot.doneBits &
                                (BIT_STEPPER1_DONE | BIT_STEPPER2_DONE)) ==
                                   (BIT_STEPPER1_DONE | BIT_STEPPER2_DONE) &&
                               (reverse.snapshot.doneBits &
                                (BIT_STEPPER1_DONE | BIT_STEPPER2_DONE)) ==
                                   (BIT_STEPPER1_DONE | BIT_STEPPER2_DONE)) ? 1u : 0u,
                              (unsigned long)(forward.snapshot.pendingUpdateCount + reverse.snapshot.pendingUpdateCount),
                              (unsigned long)maxCycles,
                              returned ? 1u : 0u,
                              (forward.terminal && reverse.terminal) ? 0u : 1u);
                          const bool metricsFit = metricsLength > 0 &&
                              static_cast<size_t>(metricsLength) < sizeof(metrics);
                          (void)runOne(testId,
                                       name,
                                       pass && metricsFit,
                                       metricsFit ? metrics : "gate=metrics_overflow;to=1");
                          return pass;
                        };

                        // This suite qualifies the coordinated executor, not
                        // simultaneous legacy homing. Home one XY axis at a
                        // time and at a deliberately low approach rate so the
                        // preflight cannot recreate the interrupt saturation
                        // that motivated the coordinated executor.
                        auto runSequentialXyHome = [&](MotionQualificationMath::AxisHomeSample& xSample,
                                                       MotionQualificationMath::AxisHomeSample& ySample) {
                          sendProgressStage("coord_x_home_low");
                          if (!runAxisHomeDiagnosticAttempt(stepperX,
                                                            BIT_HOME_X_DONE,
                                                            xSample,
                                                            kXyHomeFastHz,
                                                            kXyHomeSlowHz,
                                                            kHomeBackoffSteps,
                                                            kHomeTimeoutMs)) {
                            return false;
                          }
                          sendProgressStage("coord_y_home_low");
                          return runAxisHomeDiagnosticAttempt(stepperY,
                                                              BIT_HOME_Y_DONE,
                                                              ySample,
                                                              kXyHomeFastHz,
                                                              kXyHomeSlowHz,
                                                              kHomeBackoffSteps,
                                                              kHomeTimeoutMs);
                        };

                        // Fail closed before any motion in this suite. The
                        // operator must manually exercise both physical XY
                        // switches while the motors are disabled, and the MCU
                        // must observe both the asserted and released levels.
                        // This catches disconnected, stuck, inverted, or
                        // mechanically unreachable inputs without moving an
                        // axis toward a hard stop.
                        auto runXyLimitSwitchPreflight = [&]() -> bool {
                          if (stepperX->isBusy() || stepperY->isBusy()) return false;
                          stepperX->disableMotor();
                          stepperY->disableMotor();

                          if (!waitForOperatorResume("coord_x_limit_press") ||
                              !stepperX->isLimitAssertedForDiagnostics()) {
                            return false;
                          }
                          if (!waitForOperatorResume("coord_x_limit_release") ||
                              stepperX->isLimitAssertedForDiagnostics()) {
                            return false;
                          }
                          if (!waitForOperatorResume("coord_y_limit_press") ||
                              !stepperY->isLimitAssertedForDiagnostics()) {
                            return false;
                          }
                          if (!waitForOperatorResume("coord_y_limit_release") ||
                              stepperY->isLimitAssertedForDiagnostics()) {
                            return false;
                          }
                          return true;
                        };

                        if (!runXyLimitSwitchPreflight()) {
                          restoreXyRates();
                          (void)emitSkippedExecutor(2040u, "limit_switch_preflight");
                          return finishSelfTestNow();
                        }

                        if (!runZClearanceHomePreflight("coord_z_clearance_home",
                                                        kZHomeFastHz,
                                                        kZHomeSlowHz,
                                                        kHomeBackoffSteps,
                                                        kHomeTimeoutMs)) {
                          restoreXyRates();
                          (void)emitSkippedExecutor(2040u, "z_clearance_home");
                          return finishSelfTestNow();
                        }

                        MotionQualificationMath::AxisHomeSample xHomeBefore{};
                        MotionQualificationMath::AxisHomeSample yHomeBefore{};
                        if (!runSequentialXyHome(xHomeBefore, yHomeBefore)) {
                          restoreXyRates();
                          (void)emitSkippedExecutor(2040u, "xy_home");
                          return finishSelfTestNow();
                        }
                        if (savedXMaxRateHz != 40000u || savedYMaxRateHz != 40000u) {
                          restoreXyRates();
                          (void)emitSkippedExecutor(2040u, "max_rate_not_40000");
                          return finishSelfTestNow();
                        }
                        if (!moveLegacyToAnchor()) {
                          restoreXyRates();
                          (void)emitSkippedExecutor(2040u, "anchor");
                          return finishSelfTestNow();
                        }

                        bool safeToContinue = runRoundTrip(
                            2040u, "coordinated_xy_x_only_low", 1000, 0);
                        if (!safeToContinue) {
                          (void)emitSkippedExecutor(2041u, "x_only_failed");
                          restoreXyRates();
                          return finishSelfTestNow();
                        }
                        safeToContinue = runRoundTrip(
                            2041u, "coordinated_xy_y_only_low", 0, 1000);
                        if (!safeToContinue) {
                          (void)emitSkippedExecutor(2042u, "y_only_failed");
                          restoreXyRates();
                          return finishSelfTestNow();
                        }
                        safeToContinue = runRoundTrip(
                            2042u, "coordinated_xy_equal_low", 1000, 1000);
                        if (!safeToContinue) {
                          (void)emitSkippedExecutor(2043u, "equal_failed");
                          restoreXyRates();
                          return finishSelfTestNow();
                        }
                        safeToContinue = runRoundTrip(
                            2043u, "coordinated_xy_asymmetric_low", 500, 1500);
                        if (!safeToContinue) {
                          (void)emitSkippedExecutor(2044u, "asymmetric_failed");
                          restoreXyRates();
                          return finishSelfTestNow();
                        }

                        const GantryPosition pauseStart = gantry->getPosition();
                        CoordinatedXySnapshot pauseProgress{};
                        CoordinatedXySnapshot pauseFirst{};
                        CoordinatedXySnapshot pauseSecond{};
                        CoordinatedXySnapshot pauseForward{};
                        const bool pauseStarted = gantry->startCoordinatedXY(
                            2000, 1000, kCoordinatedRateHz) ==
                            CoordinatedStartStatus::Started;
                        const bool pauseProgressReached = pauseStarted && waitForProgress(
                            kControlProgressSteps, kControlTimeoutMs, pauseProgress);
                        if (pauseProgressReached) Gantry::pauseXYZMotors();
                        const bool paused = pauseProgressReached && waitForState(
                            CoordinatedXyExecutor::State::Paused,
                            kControlTimeoutMs,
                            pauseFirst);
                        const bool pauseDelayOk = paused &&
                            delayWithWatchdog(kPauseHoldMs, "coord_pause_hold");
                        if (pauseDelayOk) pauseSecond = gantry->coordinatedSnapshot();
                        const bool pauseStable = pauseDelayOk &&
                            pauseSecond.state == CoordinatedXyExecutor::State::Paused &&
                            pauseSecond.fallingEdges == pauseFirst.fallingEdges &&
                            pauseSecond.risingEdges == pauseFirst.risingEdges &&
                            pauseSecond.xPosition == pauseFirst.xPosition &&
                            pauseSecond.yPosition == pauseFirst.yPosition &&
                            pauseSecond.xStepLow && pauseSecond.yStepLow;
                        if (pauseStable) Gantry::resumeXYZMotors();
                        const bool pauseCompleted = pauseStable &&
                            waitForTerminal(kMoveTimeoutMs, pauseForward) &&
                            completedSnapshotPasses(
                                pauseForward, pauseStart.x + 2000, pauseStart.y + 1000);
                        CompleteLegResult pauseReverse{};
                        if (pauseCompleted) pauseReverse = runCompleteLeg(-2000, -1000);
                        const GantryPosition pauseEnd = gantry->getPosition();
                        const bool pausePass = pauseCompleted && pauseReverse.passed &&
                            pauseForward.maskChecksum == pauseReverse.snapshot.maskChecksum &&
                            pauseForward.arrChecksum == pauseReverse.snapshot.arrChecksum &&
                            pauseEnd.x == pauseStart.x && pauseEnd.y == pauseStart.y;
                        char pauseMetrics[224];
                        snprintf(pauseMetrics,
                                 sizeof(pauseMetrics),
                                 "dx=2000;dy=1000;hz=3000;pause=%u;stable=%u;resume=%u;low=%u;i7=%lu;pu=%lu;cy=%lu;ret=%u;to=%u",
                                 paused ? 1u : 0u,
                                 pauseStable ? 1u : 0u,
                                 pauseCompleted ? 1u : 0u,
                                 (pauseForward.xStepLow && pauseForward.yStepLow &&
                                  pauseReverse.snapshot.xStepLow && pauseReverse.snapshot.yStepLow) ? 1u : 0u,
                                 (unsigned long)(pauseForward.timer7Interrupts + pauseReverse.snapshot.timer7Interrupts),
                                 (unsigned long)(pauseForward.pendingUpdateCount + pauseReverse.snapshot.pendingUpdateCount),
                                 (unsigned long)std::max(pauseForward.maxIsrCycles,
                                                         pauseReverse.snapshot.maxIsrCycles),
                                 (pauseEnd.x == pauseStart.x && pauseEnd.y == pauseStart.y) ? 1u : 0u,
                                 (pauseCompleted && pauseReverse.terminal) ? 0u : 1u);
                        (void)runOne(2044u,
                                     "coordinated_xy_pause_resume",
                                     pausePass,
                                     pauseMetrics);
                        if (!pausePass) {
                          Gantry::cancelXYZMotors();
                          (void)emitSkippedExecutor(2045u, "pause_failed");
                          restoreXyRates();
                          return finishSelfTestNow();
                        }

                        const GantryPosition cancelStart = gantry->getPosition();
                        CoordinatedXySnapshot cancelBefore{};
                        CoordinatedXySnapshot cancelAfter{};
                        uint32_t cancelRisingAtRequest = 0u;
                        uint32_t cancelFallingAtRequest = 0u;
                        const bool cancelStarted = gantry->startCoordinatedXY(
                            2000, 1000, kCoordinatedRateHz) ==
                            CoordinatedStartStatus::Started;
                        const bool cancelProgress = cancelStarted && waitForProgress(
                            kControlProgressSteps, kControlTimeoutMs, cancelBefore);
                        const bool cancelRequested = cancelProgress &&
                            gantry->requestCoordinatedCancelForDiagnostics(
                                cancelRisingAtRequest,
                                cancelFallingAtRequest);
                        const bool cancelTerminal = cancelRequested && waitForTerminal(
                            kControlTimeoutMs, cancelAfter);
                        const bool cancelOutcome = cancelTerminal &&
                            cancelAfter.state == CoordinatedXyExecutor::State::Canceled &&
                            cancelAfter.terminalReason ==
                                CoordinatedXyExecutor::TerminalReason::Canceled;
                        const bool cancelLatency = cancelOutcome &&
                            cancelAfter.fallingEdges - cancelFallingAtRequest <= 1u &&
                            cancelAfter.risingEdges == cancelRisingAtRequest;
                        const bool cancelRebased = cancelOutcome &&
                            cancelAfter.xTarget == cancelAfter.xPosition &&
                            cancelAfter.yTarget == cancelAfter.yPosition;
                        const bool cancelPins = cancelAfter.xStepLow &&
                                                cancelAfter.yStepLow &&
                                                !cancelAfter.timerOwned;
                        const bool cancelRecovered = cancelOutcome && moveLegacyToAnchor();
                        const GantryPosition cancelEnd = gantry->getPosition();
                        const bool cancelPass = cancelOutcome && cancelLatency &&
                            cancelRebased && cancelPins && cancelRecovered &&
                            cancelAfter.timer7Interrupts == 0u &&
                            cancelAfter.pendingUpdateCount == 0u &&
                            cancelAfter.maxIsrCycles <= kIsrCycleBudget &&
                            cancelEnd.x == cancelStart.x && cancelEnd.y == cancelStart.y;
                        char cancelMetrics[224];
                        snprintf(cancelMetrics,
                                 sizeof(cancelMetrics),
                                 "dx=2000;dy=1000;hz=3000;cancel=%u;lat=%lu;rise=%lu;rebase=%u;low=%u;i7=%lu;pu=%lu;cy=%lu;recover=%u;to=%u",
                                 cancelOutcome ? 1u : 0u,
                                 (unsigned long)(cancelAfter.fallingEdges - cancelFallingAtRequest),
                                 (unsigned long)(cancelAfter.risingEdges - cancelRisingAtRequest),
                                 cancelRebased ? 1u : 0u,
                                 cancelPins ? 1u : 0u,
                                 (unsigned long)cancelAfter.timer7Interrupts,
                                 (unsigned long)cancelAfter.pendingUpdateCount,
                                 (unsigned long)cancelAfter.maxIsrCycles,
                                 cancelRecovered ? 1u : 0u,
                                 cancelTerminal ? 0u : 1u);
                        (void)runOne(2045u,
                                     "coordinated_xy_cancel",
                                     cancelPass,
                                     cancelMetrics);
                        if (!cancelPass) {
                          (void)emitSkippedExecutor(2046u, "cancel_failed");
                          restoreXyRates();
                          return finishSelfTestNow();
                        }

                        struct LimitResult {
                          bool passed = false;
                          uint32_t latency = 0u;
                          uint32_t riseDelta = 0u;
                          uint32_t maxCycles = 0u;
                        };
                        auto runInjectedLimit = [&](Stepper::Axis axis) -> LimitResult {
                          LimitResult result{};
                          CoordinatedXySnapshot before{};
                          CoordinatedXySnapshot after{};
                          uint32_t risingAtRequest = 0u;
                          uint32_t fallingAtRequest = 0u;
                          if (gantry->startCoordinatedXY(1000, 2000, kCoordinatedRateHz) !=
                              CoordinatedStartStatus::Started ||
                              !waitForProgress(kControlProgressSteps,
                                               kControlTimeoutMs,
                                               before) ||
                              !gantry->requestCoordinatedLimitAbortForDiagnostics(
                                  axis, risingAtRequest, fallingAtRequest) ||
                              !waitForTerminal(kControlTimeoutMs, after)) {
                            return result;
                          }
                          const CoordinatedXyExecutor::TerminalReason expectedReason =
                              axis == Stepper::X_AXIS
                                  ? CoordinatedXyExecutor::TerminalReason::XLimit
                                  : CoordinatedXyExecutor::TerminalReason::YLimit;
                          result.latency = after.fallingEdges - fallingAtRequest;
                          result.riseDelta = after.risingEdges - risingAtRequest;
                          result.maxCycles = after.maxIsrCycles;
                          const bool terminal =
                              after.state == CoordinatedXyExecutor::State::LimitAborted &&
                              after.terminalReason == expectedReason;
                          const bool rebased = after.xTarget == after.xPosition &&
                                               after.yTarget == after.yPosition;
                          const bool bounded = result.latency <= 1u &&
                                               result.riseDelta == 0u;
                          const bool safe = after.xStepLow && after.yStepLow &&
                                            !after.timerOwned &&
                                            after.timer7Interrupts == 0u &&
                                            after.pendingUpdateCount == 0u &&
                                            after.maxIsrCycles <= kIsrCycleBudget;
                          result.passed = terminal && rebased && bounded && safe &&
                                          moveLegacyToAnchor();
                          return result;
                        };

                        const LimitResult xLimit = runInjectedLimit(Stepper::X_AXIS);
                        const LimitResult yLimit = xLimit.passed
                            ? runInjectedLimit(Stepper::Y_AXIS)
                            : LimitResult{};

                        MotionQualificationMath::AxisHomeSample xHomeAfter{};
                        MotionQualificationMath::AxisHomeSample yHomeAfter{};
                        bool teardownHome = false;
                        if (xLimit.passed && yLimit.passed && !_selfTestAbortRequested) {
                          sendProgressStage("coord_xy_teardown_home");
                          teardownHome = runSequentialXyHome(xHomeAfter, yHomeAfter);
                        }
                        // The initial home establishes the fine-limit point as
                        // logical zero. Its recorded pre-zero position depends
                        // on the unknown coordinate retained across flashing,
                        // so repeatability is the teardown trigger's distance
                        // from that established zero reference.
                        const uint32_t xHomeDrift = teardownHome
                            ? MotionQualificationMath::absDiffSteps(
                                  xHomeAfter.limitTriggerSteps, 0)
                            : std::numeric_limits<uint32_t>::max();
                        const uint32_t yHomeDrift = teardownHome
                            ? MotionQualificationMath::absDiffSteps(
                                  yHomeAfter.limitTriggerSteps, 0)
                            : std::numeric_limits<uint32_t>::max();
                        const bool homeDriftPass = teardownHome &&
                            xHomeDrift <= kHomeDriftLimitSteps &&
                            yHomeDrift <= kHomeDriftLimitSteps;
                        const bool limitPass = xLimit.passed && yLimit.passed &&
                                               homeDriftPass;
                        char limitMetrics[224];
                        snprintf(limitMetrics,
                                 sizeof(limitMetrics),
                                 "dx=1000;dy=2000;hz=3000;xl=%u;yl=%u;xlat=%lu;ylat=%lu;xrise=%lu;yrise=%lu;rebase=%u;low=%u;i7=0;pu=0;cy=%lu;xd=%lu;yd=%lu;home=%u;to=%u",
                                 xLimit.passed ? 1u : 0u,
                                 yLimit.passed ? 1u : 0u,
                                 (unsigned long)xLimit.latency,
                                 (unsigned long)yLimit.latency,
                                 (unsigned long)xLimit.riseDelta,
                                 (unsigned long)yLimit.riseDelta,
                                 (xLimit.passed && yLimit.passed) ? 1u : 0u,
                                 (xLimit.passed && yLimit.passed) ? 1u : 0u,
                                 (unsigned long)std::max(xLimit.maxCycles, yLimit.maxCycles),
                                 (unsigned long)xHomeDrift,
                                 (unsigned long)yHomeDrift,
                                 teardownHome ? 1u : 0u,
                                 teardownHome ? 0u : 1u);
                        (void)runOne(2046u,
                                     "coordinated_xy_limit_abort",
                                     limitPass,
                                     limitMetrics);
                        restoreXyRates();
                        return finishSelfTestNow();
                        };
                        return runCoordinatedExecutorDiagnostic();
                      }

                      if (runNormalXyRouteSuite) {
#if defined(__GNUC__)
                        auto runNormalRouteDiagnostic = [&]()
                            __attribute__((optimize("Os"), noinline))
                            -> DiagnosticsSummary {
#else
                        auto runNormalRouteDiagnostic = [&]() -> DiagnosticsSummary {
#endif
                        static constexpr int32_t kAnchorX = 5000;
                        static constexpr int32_t kAnchorY = 5000;
                        static constexpr uint32_t kRouteRateHz = 3000u;
                        static constexpr uint32_t kMoveTimeoutMs = 20000u;
                        static constexpr uint32_t kControlTimeoutMs = 3000u;
                        static constexpr uint32_t kZHomeFastHz = 30000u;
                        static constexpr uint32_t kZHomeSlowHz = 3000u;
                        static constexpr uint32_t kXyHomeFastHz = 3000u;
                        static constexpr uint32_t kXyHomeSlowHz = 1000u;
                        static constexpr uint32_t kHomeBackoffSteps = 400u;
                        static constexpr uint32_t kHomeTimeoutMs = 20000u;
                        static constexpr uint32_t kControlProgressSteps = 400u;
                        static constexpr uint32_t kPauseHoldMs = 50u;
                        static constexpr uint32_t kIsrCycleBudget = 2250u;
                        static constexpr uint32_t kStatusGapLimitMs = 500u;
                        static constexpr uint32_t kHomeDriftLimitSteps = 25u;
                        static constexpr uint32_t kPhysicalLimitWindowSteps = 200u;

                        struct RouteTestDescriptor {
                          uint16_t testId;
                          const char* name;
                        };
                        static constexpr RouteTestDescriptor kRouteTests[] = {
                            {2050u, "normal_xy_route_x_only_low"},
                            {2051u, "normal_xy_route_y_only_low"},
                            {2052u, "normal_xy_route_equal_low"},
                            {2053u, "normal_xy_route_asymmetric_low"},
                            {2054u, "normal_xy_route_long_status"},
                            {2055u, "normal_xy_route_control_low"},
                            {2056u, "normal_xy_route_physical_limit"},
                            {2057u, "normal_xy_route_legacy_smoke"},
                        };

                        auto emitSkippedRoute = [&](uint16_t firstTestId,
                                                     const char* gate) -> bool {
                          char metrics[128];
                          snprintf(metrics,
                                   sizeof(metrics),
                                   "gate=%s;route=%u;hz=3000;to=1;low=0;i7=0;pu=0",
                                   gate,
                                   static_cast<unsigned>(
                                       LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE != 0));
                          for (const RouteTestDescriptor& test : kRouteTests) {
                            if (test.testId >= firstTestId &&
                                !runOne(test.testId, test.name, false, metrics)) {
                              return false;
                            }
                          }
                          return true;
                        };

                        Stepper* stepperX = Stepper::stepperX();
                        Stepper* stepperY = Stepper::stepperY();
                        Stepper* stepperZ = Stepper::stepperZ();
                        Gantry* gantry = Gantry::instance();
                        if (stepperX == nullptr || stepperY == nullptr ||
                            stepperZ == nullptr || gantry == nullptr || comm == nullptr) {
                          (void)emitSkippedRoute(2050u, "motion_unavailable");
                          return finishSelfTestNow();
                        }

                        const uint32_t savedXMaxRateHz = stepperX->maxSpeedHz();
                        const uint32_t savedYMaxRateHz = stepperY->maxSpeedHz();
                        auto restoreXyRates = [&]() {
                          stepperX->setMaxSpeedHz(savedXMaxRateHz);
                          stepperY->setMaxSpeedHz(savedYMaxRateHz);
                        };
                        auto failRemaining = [&](uint16_t firstTestId,
                                                 const char* gate) {
                          Gantry::cancelXYZMotors();
                          restoreXyRates();
                          (void)emitSkippedRoute(firstTestId, gate);
                        };

                        auto stateTerminal = [](CoordinatedXyExecutor::State state) {
                          return state == CoordinatedXyExecutor::State::Completed ||
                                 state == CoordinatedXyExecutor::State::Canceled ||
                                 state == CoordinatedXyExecutor::State::LimitAborted ||
                                 state == CoordinatedXyExecutor::State::Faulted;
                        };
                        auto waitForTerminal = [&](uint32_t timeoutMs,
                                                   CoordinatedXySnapshot& snapshot) -> bool {
                          const uint32_t startedMs = HAL_GetTick();
                          const TickType_t pollTicks = msToAtLeast1Tick(2u);
                          while ((HAL_GetTick() - startedMs) < timeoutMs) {
                            Watchdog_CheckIn(CRASH_TASK_ORCH);
                            snapshot = gantry->coordinatedSnapshot();
                            if (stateTerminal(snapshot.state)) return true;
                            if (_selfTestAbortRequested) {
                              Gantry::cancelXYZMotors();
                              return false;
                            }
                            vTaskDelay(pollTicks);
                          }
                          Gantry::cancelXYZMotors();
                          snapshot = gantry->coordinatedSnapshot();
                          return false;
                        };
                        auto waitForProgress = [&](uint32_t completedSteps,
                                                   uint32_t timeoutMs,
                                                   CoordinatedXySnapshot& snapshot) -> bool {
                          const uint32_t startedMs = HAL_GetTick();
                          const TickType_t pollTicks = msToAtLeast1Tick(1u);
                          while ((HAL_GetTick() - startedMs) < timeoutMs) {
                            Watchdog_CheckIn(CRASH_TASK_ORCH);
                            snapshot = gantry->coordinatedSnapshot();
                            if (snapshot.fallingEdges >= completedSteps) return true;
                            if (stateTerminal(snapshot.state) || _selfTestAbortRequested) {
                              return false;
                            }
                            vTaskDelay(pollTicks);
                          }
                          return false;
                        };
                        auto waitForState = [&](CoordinatedXyExecutor::State expected,
                                                uint32_t timeoutMs,
                                                CoordinatedXySnapshot& snapshot) -> bool {
                          const uint32_t startedMs = HAL_GetTick();
                          const TickType_t pollTicks = msToAtLeast1Tick(1u);
                          while ((HAL_GetTick() - startedMs) < timeoutMs) {
                            Watchdog_CheckIn(CRASH_TASK_ORCH);
                            snapshot = gantry->coordinatedSnapshot();
                            if (snapshot.state == expected) return true;
                            if (stateTerminal(snapshot.state) || _selfTestAbortRequested) {
                              return false;
                            }
                            vTaskDelay(pollTicks);
                          }
                          return false;
                        };

                        auto snapshotCompleted = [&](const CoordinatedXySnapshot& snapshot,
                                                     const Orchestrator::AbsoluteXyExecutionResult& execution,
                                                     int32_t expectedX,
                                                     int32_t expectedY) -> bool {
                          return execution.startStatus == CoordinatedStartStatus::Started &&
                              execution.disposition ==
                                  OrchestratorCompletionPolicy::AbsXyDisposition::Completed &&
                              execution.waitCompleted && execution.endpointMatches &&
                              execution.targetsMatch &&
                              snapshot.state == CoordinatedXyExecutor::State::Completed &&
                              snapshot.terminalReason ==
                                  CoordinatedXyExecutor::TerminalReason::Completed &&
                              snapshot.emittedXSteps == snapshot.requestedXSteps &&
                              snapshot.emittedYSteps == snapshot.requestedYSteps &&
                              snapshot.timer2Interrupts == snapshot.masterSteps * 2u &&
                              snapshot.risingEdges == snapshot.masterSteps &&
                              snapshot.fallingEdges == snapshot.masterSteps &&
                              snapshot.timer7Interrupts == 0u &&
                              snapshot.pendingUpdateCount == 0u &&
                              snapshot.maxIsrCycles > 0u &&
                              snapshot.maxIsrCycles <= kIsrCycleBudget &&
                              snapshot.xStepLow && snapshot.yStepLow &&
                              !snapshot.timerOwned &&
                              snapshot.xPosition == expectedX &&
                              snapshot.yPosition == expectedY &&
                              snapshot.xTarget == expectedX &&
                              snapshot.yTarget == expectedY &&
                              snapshot.arrMin >= 179u &&
                              snapshot.arrMax >= snapshot.arrMin;
                        };

                        struct RouteLegResult {
                          bool passed = false;
                          Orchestrator::AbsoluteXyExecutionResult execution{};
                          CoordinatedXySnapshot snapshot{};
                        };
                        auto runRouteLeg = [&](int32_t targetX,
                                               int32_t targetY) -> RouteLegResult {
                          RouteLegResult result{};
                          result.execution = orchestrator.executeAbsoluteXy(
                              targetX, targetY, 0u, false, kMoveTimeoutMs);
                          result.snapshot = gantry->coordinatedSnapshot();
                          result.passed = snapshotCompleted(
                              result.snapshot, result.execution, targetX, targetY);
                          return result;
                        };

                        auto runRouteRoundTrip = [&](uint16_t testId,
                                                     const char* name,
                                                     int32_t dx,
                                                     int32_t dy) -> bool {
                          const GantryPosition start = gantry->getPosition();
                          const RouteLegResult forward = runRouteLeg(
                              start.x + dx, start.y + dy);
                          RouteLegResult reverse{};
                          if (forward.passed) {
                            reverse = runRouteLeg(start.x, start.y);
                          }
                          const GantryPosition end = gantry->getPosition();
                          const bool checksumMatch = forward.passed && reverse.passed &&
                              forward.snapshot.maskChecksum == reverse.snapshot.maskChecksum &&
                              forward.snapshot.arrChecksum == reverse.snapshot.arrChecksum;
                          const bool returned = end.x == start.x && end.y == start.y;
                          const bool pass = forward.passed && reverse.passed &&
                                            checksumMatch && returned;
                          const uint32_t maxCycles = std::max(
                              forward.snapshot.maxIsrCycles,
                              reverse.snapshot.maxIsrCycles);
                          char metrics[198];
                          const int metricsLength = snprintf(
                              metrics,
                              sizeof(metrics),
                              "dx=%ld;dy=%ld;hz=3000;route=1;xe=%lu;ye=%lu;ms=%lu;i2=%lu;i7=%lu;edge=%u;ck=%u;low=%u;done=%u;pu=%lu;cy=%lu;ep=%u;ret=%u;to=%u",
                              (long)dx,
                              (long)dy,
                              (unsigned long)(forward.snapshot.emittedXSteps + reverse.snapshot.emittedXSteps),
                              (unsigned long)(forward.snapshot.emittedYSteps + reverse.snapshot.emittedYSteps),
                              (unsigned long)forward.snapshot.masterSteps,
                              (unsigned long)(forward.snapshot.timer2Interrupts + reverse.snapshot.timer2Interrupts),
                              (unsigned long)(forward.snapshot.timer7Interrupts + reverse.snapshot.timer7Interrupts),
                              (forward.passed && reverse.passed) ? 1u : 0u,
                              checksumMatch ? 1u : 0u,
                              (forward.snapshot.xStepLow && forward.snapshot.yStepLow &&
                               reverse.snapshot.xStepLow && reverse.snapshot.yStepLow) ? 1u : 0u,
                              (forward.execution.waitCompleted && reverse.execution.waitCompleted) ? 1u : 0u,
                              (unsigned long)(forward.snapshot.pendingUpdateCount + reverse.snapshot.pendingUpdateCount),
                              (unsigned long)maxCycles,
                              (forward.execution.endpointMatches && forward.execution.targetsMatch &&
                               reverse.execution.endpointMatches && reverse.execution.targetsMatch) ? 1u : 0u,
                              returned ? 1u : 0u,
                              (forward.execution.waitCompleted && reverse.execution.waitCompleted) ? 0u : 1u);
                          const bool metricsFit = metricsLength > 0 &&
                              static_cast<size_t>(metricsLength) < sizeof(metrics);
                          (void)runOne(testId,
                                       name,
                                       pass && metricsFit,
                                       metricsFit ? metrics : "gate=metrics_overflow;to=1");
                          return pass && metricsFit;
                        };

                        auto runSequentialXyHome = [&](MotionQualificationMath::AxisHomeSample& xSample,
                                                       MotionQualificationMath::AxisHomeSample& ySample) {
                          sendProgressStage("normal_route_x_home_low");
                          if (!runAxisHomeDiagnosticAttempt(stepperX,
                                                            BIT_HOME_X_DONE,
                                                            xSample,
                                                            kXyHomeFastHz,
                                                            kXyHomeSlowHz,
                                                            kHomeBackoffSteps,
                                                            kHomeTimeoutMs)) {
                            return false;
                          }
                          sendProgressStage("normal_route_y_home_low");
                          return runAxisHomeDiagnosticAttempt(stepperY,
                                                              BIT_HOME_Y_DONE,
                                                              ySample,
                                                              kXyHomeFastHz,
                                                              kXyHomeSlowHz,
                                                              kHomeBackoffSteps,
                                                              kHomeTimeoutMs);
                        };

                        auto runXyLimitSwitchPreflight = [&]() -> bool {
                          if (stepperX->isBusy() || stepperY->isBusy()) return false;
                          stepperX->disableMotor();
                          stepperY->disableMotor();
                          if (!waitForOperatorResume("coord_x_limit_press") ||
                              !stepperX->isLimitAssertedForDiagnostics()) return false;
                          if (!waitForOperatorResume("coord_x_limit_release") ||
                              stepperX->isLimitAssertedForDiagnostics()) return false;
                          if (!waitForOperatorResume("coord_y_limit_press") ||
                              !stepperY->isLimitAssertedForDiagnostics()) return false;
                          if (!waitForOperatorResume("coord_y_limit_release") ||
                              stepperY->isLimitAssertedForDiagnostics()) return false;
                          if (!waitForOperatorResume("normal_route_envelope_clear")) {
                            return false;
                          }
                          return true;
                        };

                        if (LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE == 0 ||
                            !runXyLimitSwitchPreflight()) {
                          failRemaining(2050u, "route_or_limit_preflight");
                          return finishSelfTestNow();
                        }
                        if (!runZClearanceHomePreflight("normal_route_z_clearance_home",
                                                        kZHomeFastHz,
                                                        kZHomeSlowHz,
                                                        kHomeBackoffSteps,
                                                        kHomeTimeoutMs)) {
                          failRemaining(2050u, "z_clearance_home");
                          return finishSelfTestNow();
                        }

                        MotionQualificationMath::AxisHomeSample xHomeBefore{};
                        MotionQualificationMath::AxisHomeSample yHomeBefore{};
                        if (!runSequentialXyHome(xHomeBefore, yHomeBefore)) {
                          failRemaining(2050u, "xy_home");
                          return finishSelfTestNow();
                        }
                        if (savedXMaxRateHz != 40000u || savedYMaxRateHz != 40000u) {
                          failRemaining(2050u, "max_rate_not_40000");
                          return finishSelfTestNow();
                        }
                        stepperX->setMaxSpeedHz(kRouteRateHz);
                        stepperY->setMaxSpeedHz(kRouteRateHz);
                        const RouteLegResult anchor = runRouteLeg(kAnchorX, kAnchorY);
                        if (!anchor.passed) {
                          char anchorMetrics[198];
                          const int anchorMetricsLength = snprintf(
                              anchorMetrics,
                              sizeof(anchorMetrics),
                              "gate=anchor;ss=%u;di=%u;w=%u;ep=%u;tg=%u;st=%u;tr=%u;xe=%lu/%lu;ye=%lu/%lu;ms=%lu;i2=%lu;i7=%lu;e=%lu/%lu;pu=%lu;cy=%lu;l=%u;o=%u;a=%lu/%lu;p=%ld/%ld;t=%ld/%ld",
                              static_cast<unsigned>(anchor.execution.startStatus),
                              static_cast<unsigned>(anchor.execution.disposition),
                              anchor.execution.waitCompleted ? 1u : 0u,
                              anchor.execution.endpointMatches ? 1u : 0u,
                              anchor.execution.targetsMatch ? 1u : 0u,
                              static_cast<unsigned>(anchor.snapshot.state),
                              static_cast<unsigned>(anchor.snapshot.terminalReason),
                              (unsigned long)anchor.snapshot.emittedXSteps,
                              (unsigned long)anchor.snapshot.requestedXSteps,
                              (unsigned long)anchor.snapshot.emittedYSteps,
                              (unsigned long)anchor.snapshot.requestedYSteps,
                              (unsigned long)anchor.snapshot.masterSteps,
                              (unsigned long)anchor.snapshot.timer2Interrupts,
                              (unsigned long)anchor.snapshot.timer7Interrupts,
                              (unsigned long)anchor.snapshot.risingEdges,
                              (unsigned long)anchor.snapshot.fallingEdges,
                              (unsigned long)anchor.snapshot.pendingUpdateCount,
                              (unsigned long)anchor.snapshot.maxIsrCycles,
                              (anchor.snapshot.xStepLow && anchor.snapshot.yStepLow) ? 1u : 0u,
                              anchor.snapshot.timerOwned ? 1u : 0u,
                              (unsigned long)anchor.snapshot.arrMin,
                              (unsigned long)anchor.snapshot.arrMax,
                              (long)anchor.snapshot.xPosition,
                              (long)anchor.snapshot.yPosition,
                              (long)anchor.snapshot.xTarget,
                              (long)anchor.snapshot.yTarget);
                          const bool anchorMetricsFit = anchorMetricsLength > 0 &&
                              static_cast<size_t>(anchorMetricsLength) <
                                  sizeof(anchorMetrics);
                          (void)runOne(2050u,
                                       "normal_xy_route_x_only_low",
                                       false,
                                       anchorMetricsFit
                                           ? anchorMetrics
                                           : "gate=anchor_metrics_overflow");
                          failRemaining(2051u, "anchor");
                          return finishSelfTestNow();
                        }

                        if (!runRouteRoundTrip(2050u,
                                               "normal_xy_route_x_only_low",
                                               1000,
                                               0)) {
                          failRemaining(2051u, "x_only_failed");
                          return finishSelfTestNow();
                        }
                        if (!runRouteRoundTrip(2051u,
                                               "normal_xy_route_y_only_low",
                                               0,
                                               1000)) {
                          failRemaining(2052u, "y_only_failed");
                          return finishSelfTestNow();
                        }
                        if (!runRouteRoundTrip(2052u,
                                               "normal_xy_route_equal_low",
                                               1000,
                                               1000)) {
                          failRemaining(2053u, "equal_failed");
                          return finishSelfTestNow();
                        }
                        if (!runRouteRoundTrip(2053u,
                                               "normal_xy_route_asymmetric_low",
                                               500,
                                               1500)) {
                          failRemaining(2054u, "asymmetric_failed");
                          return finishSelfTestNow();
                        }

                        Comm::resetStatusMetrics();
                        comm->setStatusPaused(false);
                        const RouteLegResult longForward = runRouteLeg(
                            kAnchorX + 6000, kAnchorY + 2000);
                        RouteLegResult longReverse{};
                        if (longForward.passed) {
                          longReverse = runRouteLeg(kAnchorX, kAnchorY);
                        }
                        uint32_t statusAgeMs = 999999u;
                        const bool statusAgeAvailable =
                            Watchdog_GetTaskLastSeenAgeMs(
                                CRASH_TASK_STATUS, &statusAgeMs) != 0u;
                        const uint32_t statusFrames =
                            Comm::getStatusChunk0Count() + Comm::getStatusChunk1Count();
                        const uint32_t statusGapMs = Comm::getStatusPeriodMaxMs();
                        const uint32_t statusAlternationErrors =
                            Comm::getStatusAlternationErrors();
                        comm->setStatusPaused(true);
                        const bool holdsReleased =
                            !PressureRegulator::regP().isMotionHoldActive()
#if LC_PRESSURE_PORTS > 1
                            && !PressureRegulator::regR().isMotionHoldActive()
#endif
                            ;
                        const bool longPass = longForward.passed && longReverse.passed &&
                            longForward.execution.holdRequested &&
                            longReverse.execution.holdRequested &&
                            holdsReleased && statusFrames >= 2u &&
                            statusGapMs < kStatusGapLimitMs && statusAgeAvailable &&
                            statusAgeMs < kStatusGapLimitMs &&
                            statusAlternationErrors == 0u;
                        char longMetrics[198];
                        const int longMetricsLength = snprintf(
                            longMetrics,
                            sizeof(longMetrics),
                            "dx=6000;dy=2000;hz=3000;route=1;hold=%u;acq=%u;clean=%u;sf=%lu;sg=%lu;sa=%lu;alt=%lu;i2=%lu;i7=%lu;low=%u;pu=%lu;cy=%lu;ep=%u;ret=%u;to=%u",
                            (longForward.execution.holdRequested &&
                             longReverse.execution.holdRequested) ? 1u : 0u,
                            (longForward.execution.printHoldAcquired ||
                             longForward.execution.refuelHoldAcquired ||
                             longReverse.execution.printHoldAcquired ||
                             longReverse.execution.refuelHoldAcquired) ? 1u : 0u,
                            holdsReleased ? 1u : 0u,
                            (unsigned long)statusFrames,
                            (unsigned long)statusGapMs,
                            (unsigned long)statusAgeMs,
                            (unsigned long)statusAlternationErrors,
                            (unsigned long)(longForward.snapshot.timer2Interrupts +
                                            longReverse.snapshot.timer2Interrupts),
                            (unsigned long)(longForward.snapshot.timer7Interrupts +
                                            longReverse.snapshot.timer7Interrupts),
                            (longForward.snapshot.xStepLow && longForward.snapshot.yStepLow &&
                             longReverse.snapshot.xStepLow && longReverse.snapshot.yStepLow) ? 1u : 0u,
                            (unsigned long)(longForward.snapshot.pendingUpdateCount +
                                            longReverse.snapshot.pendingUpdateCount),
                            (unsigned long)std::max(longForward.snapshot.maxIsrCycles,
                                                    longReverse.snapshot.maxIsrCycles),
                            (longForward.execution.endpointMatches &&
                             longReverse.execution.endpointMatches) ? 1u : 0u,
                            (gantry->getPosition().x == kAnchorX &&
                             gantry->getPosition().y == kAnchorY) ? 1u : 0u,
                            (longForward.execution.waitCompleted &&
                             longReverse.execution.waitCompleted) ? 0u : 1u);
                        const bool longMetricsFit = longMetricsLength > 0 &&
                            static_cast<size_t>(longMetricsLength) < sizeof(longMetrics);
                        (void)runOne(2054u,
                                     "normal_xy_route_long_status",
                                     longPass && longMetricsFit,
                                     longMetricsFit ? longMetrics
                                                    : "gate=metrics_overflow;to=1");
                        if (!longPass || !longMetricsFit) {
                          failRemaining(2055u, "long_status_failed");
                          return finishSelfTestNow();
                        }

                        const GantryPosition controlStart = gantry->getPosition();
                        CoordinatedXySnapshot pauseProgress{};
                        CoordinatedXySnapshot pauseFirst{};
                        CoordinatedXySnapshot pauseSecond{};
                        CoordinatedXySnapshot pauseCompleted{};
                        const bool pauseStarted = gantry->moveTo(
                            controlStart.x + 2000,
                            controlStart.y + 1000,
                            0u) == CoordinatedStartStatus::Started;
                        const bool pauseProgressReached = pauseStarted && waitForProgress(
                            kControlProgressSteps, kControlTimeoutMs, pauseProgress);
                        if (pauseProgressReached) Gantry::pauseXYZMotors();
                        const bool paused = pauseProgressReached && waitForState(
                            CoordinatedXyExecutor::State::Paused,
                            kControlTimeoutMs,
                            pauseFirst);
                        const bool pauseDelayOk = paused &&
                            delayWithWatchdog(kPauseHoldMs, "normal_route_pause_hold");
                        if (pauseDelayOk) pauseSecond = gantry->coordinatedSnapshot();
                        const bool pauseStable = pauseDelayOk &&
                            pauseSecond.state == CoordinatedXyExecutor::State::Paused &&
                            pauseSecond.fallingEdges == pauseFirst.fallingEdges &&
                            pauseSecond.risingEdges == pauseFirst.risingEdges &&
                            pauseSecond.xPosition == pauseFirst.xPosition &&
                            pauseSecond.yPosition == pauseFirst.yPosition &&
                            pauseSecond.xStepLow && pauseSecond.yStepLow;
                        if (pauseStable) Gantry::resumeXYZMotors();
                        const bool pauseTerminal = pauseStable && waitForTerminal(
                            kMoveTimeoutMs, pauseCompleted);
                        const bool pausePass = pauseTerminal &&
                            pauseCompleted.state == CoordinatedXyExecutor::State::Completed &&
                            pauseCompleted.terminalReason ==
                                CoordinatedXyExecutor::TerminalReason::Completed &&
                            pauseCompleted.xPosition == controlStart.x + 2000 &&
                            pauseCompleted.yPosition == controlStart.y + 1000 &&
                            pauseCompleted.xTarget == pauseCompleted.xPosition &&
                            pauseCompleted.yTarget == pauseCompleted.yPosition &&
                            pauseCompleted.xStepLow && pauseCompleted.yStepLow &&
                            !pauseCompleted.timerOwned &&
                            pauseCompleted.timer7Interrupts == 0u &&
                            pauseCompleted.pendingUpdateCount == 0u &&
                            pauseCompleted.maxIsrCycles <= kIsrCycleBudget;
                        const RouteLegResult pauseRecovery = pausePass
                            ? runRouteLeg(controlStart.x, controlStart.y)
                            : RouteLegResult{};

                        CoordinatedXySnapshot cancelProgress{};
                        CoordinatedXySnapshot cancelAfter{};
                        uint32_t cancelRisingAtRequest = 0u;
                        uint32_t cancelFallingAtRequest = 0u;
                        const bool cancelStarted = pauseRecovery.passed &&
                            gantry->moveTo(controlStart.x + 2000,
                                           controlStart.y + 1000,
                                           0u) == CoordinatedStartStatus::Started;
                        const bool cancelProgressReached = cancelStarted && waitForProgress(
                            kControlProgressSteps, kControlTimeoutMs, cancelProgress);
                        const bool cancelRequested = cancelProgressReached &&
                            gantry->requestCoordinatedCancelForDiagnostics(
                                cancelRisingAtRequest,
                                cancelFallingAtRequest);
                        const bool cancelTerminal = cancelRequested && waitForTerminal(
                            kControlTimeoutMs, cancelAfter);
                        const bool cancelLatency = cancelTerminal &&
                            cancelAfter.fallingEdges >= cancelFallingAtRequest &&
                            cancelAfter.fallingEdges - cancelFallingAtRequest <= 1u &&
                            cancelAfter.risingEdges == cancelRisingAtRequest;
                        const bool cancelPass = cancelTerminal && cancelLatency &&
                            cancelAfter.state == CoordinatedXyExecutor::State::Canceled &&
                            cancelAfter.terminalReason ==
                                CoordinatedXyExecutor::TerminalReason::Canceled &&
                            cancelAfter.xTarget == cancelAfter.xPosition &&
                            cancelAfter.yTarget == cancelAfter.yPosition &&
                            cancelAfter.xStepLow && cancelAfter.yStepLow &&
                            !cancelAfter.timerOwned &&
                            cancelAfter.timer7Interrupts == 0u &&
                            cancelAfter.pendingUpdateCount == 0u &&
                            cancelAfter.maxIsrCycles <= kIsrCycleBudget;
                        const RouteLegResult cancelRecovery = cancelPass
                            ? runRouteLeg(controlStart.x, controlStart.y)
                            : RouteLegResult{};
                        const bool controlPass = pausePass && pauseRecovery.passed &&
                                                 cancelPass && cancelRecovery.passed;
                        char controlMetrics[198];
                        const int controlMetricsLength = snprintf(
                                 controlMetrics,
                                 sizeof(controlMetrics),
                                 "dx=2000;dy=1000;hz=3000;route=1;pause=%u;stable=%u;resume=%u;cancel=%u;lat=%lu;rise=%lu;rebase=%u;low=%u;i7=%lu;pu=%lu;cy=%lu;recover=%u;to=%u",
                                 paused ? 1u : 0u,
                                 pauseStable ? 1u : 0u,
                                 pausePass ? 1u : 0u,
                                 cancelPass ? 1u : 0u,
                                 (unsigned long)(cancelAfter.fallingEdges >= cancelFallingAtRequest
                                     ? cancelAfter.fallingEdges - cancelFallingAtRequest
                                     : std::numeric_limits<uint32_t>::max()),
                                 (unsigned long)(cancelAfter.risingEdges >= cancelRisingAtRequest
                                     ? cancelAfter.risingEdges - cancelRisingAtRequest
                                     : std::numeric_limits<uint32_t>::max()),
                                 (cancelAfter.xTarget == cancelAfter.xPosition &&
                                  cancelAfter.yTarget == cancelAfter.yPosition) ? 1u : 0u,
                                 (pauseCompleted.xStepLow && pauseCompleted.yStepLow &&
                                  cancelAfter.xStepLow && cancelAfter.yStepLow) ? 1u : 0u,
                                 (unsigned long)(pauseCompleted.timer7Interrupts +
                                                 cancelAfter.timer7Interrupts),
                                 (unsigned long)(pauseCompleted.pendingUpdateCount +
                                                 cancelAfter.pendingUpdateCount),
                                 (unsigned long)std::max(pauseCompleted.maxIsrCycles,
                                                         cancelAfter.maxIsrCycles),
                                 (pauseRecovery.passed && cancelRecovery.passed) ? 1u : 0u,
                                 (pauseTerminal && cancelTerminal) ? 0u : 1u);
                        const bool controlMetricsFit = controlMetricsLength > 0 &&
                            static_cast<size_t>(controlMetricsLength) <
                                sizeof(controlMetrics);
                        (void)runOne(2055u,
                                     "normal_xy_route_control_low",
                                     controlPass && controlMetricsFit,
                                     controlMetricsFit ? controlMetrics
                                                       : "gate=metrics_overflow;to=1");
                        if (!controlPass || !controlMetricsFit) {
                          failRemaining(2056u, "control_failed");
                          return finishSelfTestNow();
                        }

                        struct PhysicalLimitResult {
                          bool passed = false;
                          uint32_t emitted = 0u;
                          uint32_t latency = std::numeric_limits<uint32_t>::max();
                          uint32_t riseDelta = std::numeric_limits<uint32_t>::max();
                          uint32_t requestCount = 0u;
                          uint32_t rawCount = 0u;
                          uint32_t maxCycles = 0u;
                          uint32_t drift = std::numeric_limits<uint32_t>::max();
                          int32_t rehomeLimitSteps = 0;
                        };
                        auto runPhysicalLimit = [&](Stepper* stepper,
                                                    EventBits_t homeBit,
                                                    Stepper::Axis axis) -> PhysicalLimitResult {
                          PhysicalLimitResult result{};
                          MotionQualificationMath::AxisHomeSample before{};
                          if (!runAxisHomeDiagnosticAttempt(stepper,
                                                            homeBit,
                                                            before,
                                                            kXyHomeFastHz,
                                                            kXyHomeSlowHz,
                                                            kHomeBackoffSteps,
                                                            kHomeTimeoutMs) ||
                              before.finalBackoffSteps != 100 ||
                              stepper->getPosition() != 100 ||
                              stepper->isLimitAssertedForDiagnostics()) {
                            return result;
                          }
                          const GantryPosition start = gantry->getPosition();
                          const int32_t targetX = axis == Stepper::X_AXIS ? -100 : start.x;
                          const int32_t targetY = axis == Stepper::Y_AXIS ? -100 : start.y;
                          const Orchestrator::AbsoluteXyExecutionResult execution =
                              orchestrator.executeAbsoluteXy(
                                  targetX, targetY, 0u, false, kMoveTimeoutMs);
                          const CoordinatedXySnapshot snapshot =
                              gantry->coordinatedSnapshot();
                          const CoordinatedXyExecutor::TerminalReason expectedReason =
                              axis == Stepper::X_AXIS
                                  ? CoordinatedXyExecutor::TerminalReason::XLimit
                                  : CoordinatedXyExecutor::TerminalReason::YLimit;
                          result.emitted = axis == Stepper::X_AXIS
                              ? snapshot.emittedXSteps
                              : snapshot.emittedYSteps;
                          result.requestCount = snapshot.limitAbortRequestCount;
                          result.rawCount = snapshot.rawLimitAbortCount;
                          result.maxCycles = snapshot.maxIsrCycles;
                          if (snapshot.fallingEdges >= snapshot.limitRequestFallingEdges) {
                            result.latency =
                                snapshot.fallingEdges - snapshot.limitRequestFallingEdges;
                          }
                          if (snapshot.risingEdges >= snapshot.limitRequestRisingEdges) {
                            result.riseDelta =
                                snapshot.risingEdges - snapshot.limitRequestRisingEdges;
                          }
                          const bool stationaryAxisDidNotMove = axis == Stepper::X_AXIS
                              ? snapshot.emittedYSteps == 0u
                              : snapshot.emittedXSteps == 0u;
                          const bool terminal =
                              execution.disposition ==
                                  OrchestratorCompletionPolicy::AbsXyDisposition::MotionFailure &&
                              snapshot.state == CoordinatedXyExecutor::State::LimitAborted &&
                              snapshot.terminalReason == expectedReason;
                          const bool safe = result.requestCount > 0u &&
                              result.emitted <= kPhysicalLimitWindowSteps &&
                              stationaryAxisDidNotMove &&
                              result.latency <= 1u && result.riseDelta == 0u &&
                              snapshot.xTarget == snapshot.xPosition &&
                              snapshot.yTarget == snapshot.yPosition &&
                              snapshot.xStepLow && snapshot.yStepLow &&
                              !snapshot.timerOwned &&
                              snapshot.timer7Interrupts == 0u &&
                              snapshot.pendingUpdateCount == 0u &&
                              snapshot.maxIsrCycles <= kIsrCycleBudget;
                          MotionQualificationMath::AxisHomeSample after{};
                          const bool rehome = terminal && safe &&
                              runAxisHomeDiagnosticAttempt(stepper,
                                                           homeBit,
                                                           after,
                                                           kXyHomeFastHz,
                                                           kXyHomeSlowHz,
                                                           kHomeBackoffSteps,
                                                           kHomeTimeoutMs);
                          result.drift = rehome
                              ? MotionQualificationMath::absDiffSteps(
                                    after.limitTriggerSteps,
                                    before.limitTriggerSteps)
                              : std::numeric_limits<uint32_t>::max();
                          if (rehome) {
                            result.rehomeLimitSteps = after.limitTriggerSteps;
                          }
                          result.passed = terminal && safe && rehome &&
                                          result.drift <= kHomeDriftLimitSteps;
                          return result;
                        };

                        sendProgressStage("normal_route_x_physical_limit");
                        const PhysicalLimitResult xLimit = runPhysicalLimit(
                            stepperX, BIT_HOME_X_DONE, Stepper::X_AXIS);
                        PhysicalLimitResult yLimit{};
                        if (xLimit.passed) {
                          sendProgressStage("normal_route_y_physical_limit");
                          yLimit = runPhysicalLimit(
                              stepperY, BIT_HOME_Y_DONE, Stepper::Y_AXIS);
                        }
                        const bool physicalPass = xLimit.passed && yLimit.passed;
                        char limitMetrics[198];
                        const int limitMetricsLength = snprintf(
                                 limitMetrics,
                                 sizeof(limitMetrics),
                                 "hz=3000;route=1;win=200;xl=%u;yl=%u;xe=%lu;ye=%lu;xlat=%lu;ylat=%lu;xrise=%lu;yrise=%lu;req=%lu;raw=%lu;rebase=%u;low=%u;i7=0;pu=0;cy=%lu;xd=%lu;yd=%lu;home=%u;to=%u",
                                 xLimit.passed ? 1u : 0u,
                                 yLimit.passed ? 1u : 0u,
                                 (unsigned long)xLimit.emitted,
                                 (unsigned long)yLimit.emitted,
                                 (unsigned long)xLimit.latency,
                                 (unsigned long)yLimit.latency,
                                 (unsigned long)xLimit.riseDelta,
                                 (unsigned long)yLimit.riseDelta,
                                 (unsigned long)(xLimit.requestCount + yLimit.requestCount),
                                 (unsigned long)(xLimit.rawCount + yLimit.rawCount),
                                 physicalPass ? 1u : 0u,
                                 physicalPass ? 1u : 0u,
                                 (unsigned long)std::max(xLimit.maxCycles, yLimit.maxCycles),
                                 (unsigned long)xLimit.drift,
                                 (unsigned long)yLimit.drift,
                                 physicalPass ? 1u : 0u,
                                 physicalPass ? 0u : 1u);
                        const bool limitMetricsFit = limitMetricsLength > 0 &&
                            static_cast<size_t>(limitMetricsLength) <
                                sizeof(limitMetrics);
                        (void)runOne(2056u,
                                     "normal_xy_route_physical_limit",
                                     physicalPass && limitMetricsFit,
                                     limitMetricsFit ? limitMetrics
                                                     : "gate=metrics_overflow;to=1");
                        if (!physicalPass || !limitMetricsFit) {
                          failRemaining(2057u, "physical_limit_failed");
                          return finishSelfTestNow();
                        }

                        const int32_t xLegacyStart = stepperX->getPosition();
                        const int32_t yLegacyStart = stepperY->getPosition();
                        const int32_t zLegacyStart = stepperZ->getPosition();
                        Stepper* stepperP = Stepper::stepperP();
                        Stepper* stepperR = Stepper::stepperR();
                        const int32_t pStart = stepperP != nullptr
                            ? stepperP->getPosition() : 0;
                        const int32_t rStart = stepperR != nullptr
                            ? stepperR->getPosition() : 0;
                        const bool directX =
                            moveAxisToWithTimeout(stepperX,
                                                  BIT_STEPPER1_DONE,
                                                  xLegacyStart + 200,
                                                  kRouteRateHz,
                                                  kMoveTimeoutMs) &&
                            moveAxisToWithTimeout(stepperX,
                                                  BIT_STEPPER1_DONE,
                                                  xLegacyStart,
                                                  kRouteRateHz,
                                                  kMoveTimeoutMs);
                        const bool directY = directX &&
                            moveAxisToWithTimeout(stepperY,
                                                  BIT_STEPPER2_DONE,
                                                  yLegacyStart + 200,
                                                  kRouteRateHz,
                                                  kMoveTimeoutMs) &&
                            moveAxisToWithTimeout(stepperY,
                                                  BIT_STEPPER2_DONE,
                                                  yLegacyStart,
                                                  kRouteRateHz,
                                                  kMoveTimeoutMs);
                        const bool directZ = directY &&
                            moveAxisToWithTimeout(stepperZ,
                                                  BIT_STEPPER3_DONE,
                                                  zLegacyStart + 200,
                                                  kRouteRateHz,
                                                  kMoveTimeoutMs) &&
                            moveAxisToWithTimeout(stepperZ,
                                                  BIT_STEPPER3_DONE,
                                                  zLegacyStart,
                                                  kRouteRateHz,
                                                  kMoveTimeoutMs);
                        const bool regulatorsUnchanged =
                            (stepperP == nullptr || stepperP->getPosition() == pStart) &&
                            (stepperR == nullptr || stepperR->getPosition() == rStart);
                        const CoordinatedXySnapshot legacySnapshot =
                            gantry->coordinatedSnapshot();
                        MotionQualificationMath::AxisHomeSample xHomeAfter{};
                        MotionQualificationMath::AxisHomeSample yHomeAfter{};
                        sendProgressStage("normal_route_xy_teardown_home");
                        const bool teardownHome = directZ && regulatorsUnchanged &&
                            runSequentialXyHome(xHomeAfter, yHomeAfter);
                        const uint32_t xTeardownDrift = teardownHome
                            ? MotionQualificationMath::absDiffSteps(
                                  xHomeAfter.limitTriggerSteps,
                                  xLimit.rehomeLimitSteps)
                            : std::numeric_limits<uint32_t>::max();
                        const uint32_t yTeardownDrift = teardownHome
                            ? MotionQualificationMath::absDiffSteps(
                                  yHomeAfter.limitTriggerSteps,
                                  yLimit.rehomeLimitSteps)
                            : std::numeric_limits<uint32_t>::max();
                        const bool legacyPass = directX && directY && directZ &&
                            regulatorsUnchanged && !legacySnapshot.timerOwned &&
                            legacySnapshot.xStepLow && legacySnapshot.yStepLow &&
                            teardownHome &&
                            xTeardownDrift <= kHomeDriftLimitSteps &&
                            yTeardownDrift <= kHomeDriftLimitSteps;
                        char legacyMetrics[198];
                        const int legacyMetricsLength = snprintf(
                                 legacyMetrics,
                                 sizeof(legacyMetrics),
                                 "hz=3000;route=1;x=%u;y=%u;z=%u;pr=%u;own=%u;low=%u;xret=%ld;yret=%ld;zret=%ld;xd=%lu;yd=%lu;home=%u;to=%u",
                                 directX ? 1u : 0u,
                                 directY ? 1u : 0u,
                                 directZ ? 1u : 0u,
                                 regulatorsUnchanged ? 1u : 0u,
                                 legacySnapshot.timerOwned ? 1u : 0u,
                                 (legacySnapshot.xStepLow && legacySnapshot.yStepLow) ? 1u : 0u,
                                 (long)(stepperX->getPosition() - (teardownHome ? 100 : xLegacyStart)),
                                 (long)(stepperY->getPosition() - (teardownHome ? 100 : yLegacyStart)),
                                 (long)(stepperZ->getPosition() - zLegacyStart),
                                 (unsigned long)xTeardownDrift,
                                 (unsigned long)yTeardownDrift,
                                 teardownHome ? 1u : 0u,
                                 (directX && directY && directZ && teardownHome) ? 0u : 1u);
                        const bool legacyMetricsFit = legacyMetricsLength > 0 &&
                            static_cast<size_t>(legacyMetricsLength) <
                                sizeof(legacyMetrics);
                        (void)runOne(2057u,
                                     "normal_xy_route_legacy_smoke",
                                     legacyPass && legacyMetricsFit,
                                     legacyMetricsFit ? legacyMetrics
                                                      : "gate=metrics_overflow;to=1");
                        restoreXyRates();
                        return finishSelfTestNow();
                        };
                        return runNormalRouteDiagnostic();
                      }

                      if (runCoordinatedXyPerformanceSuite) {
#if defined(__GNUC__)
                        auto runCoordinatedPerformanceDiagnostic = [&]()
                            __attribute__((optimize("Os"), noinline))
                            -> DiagnosticsSummary {
#else
                        auto runCoordinatedPerformanceDiagnostic = [&]() -> DiagnosticsSummary {
#endif
                        using CoordinatedXyPerformanceReport::Aggregate;
                        using CoordinatedXyPerformanceReport::Limits;
                        using CoordinatedXyPerformanceReport::MoveObservation;

                        static constexpr uint32_t kMoveTimeoutMs = 30000u;
                        static constexpr uint32_t kHomeTimeoutMs = 20000u;
                        static constexpr uint32_t kZMoveTimeoutMs = 45000u;
                        static constexpr uint32_t kBaselineXyHomeFastHz = 3000u;
                        static constexpr uint32_t kBaselineXyHomeSlowHz = 1000u;
                        static constexpr uint32_t kBoundedHomeTimeoutMs = 30000u;
                        static constexpr uint32_t kBaselineHomeGuardMarginSteps = 3000u;
                        static constexpr uint32_t kBaselineMinimumHomeGuardSteps = 3000u;
                        static constexpr uint32_t kBaselineXEnvelopeMaximumSteps = 45000u;
                        static constexpr uint32_t kBaselineYEnvelopeMaximumSteps = 35000u;
                        static constexpr uint32_t kBaselineZHomeFastHz = 30000u;
                        static constexpr uint32_t kBaselineZHomeSlowHz = 3000u;
                        static constexpr uint32_t kRegHomeFastHz = 30000u;
                        static constexpr uint32_t kRegHomeSlowHz = 3000u;
                        static constexpr uint32_t kBaselineHomeBackoffSteps = 400u;
                        static constexpr uint32_t kTimerClockHz = 90000000u;
                        static constexpr uint32_t kBaselineExpectedBackoffPosition = 100u;
                        static constexpr uint32_t kBaselineHomeDriftLimitSteps = 25u;
                        static constexpr uint32_t kBaselineReturnErrorLimitSteps = 10u;
                        static constexpr uint32_t kPressureSettleTimeoutMs = 8000u;
                        static constexpr uint16_t kPressure1Raw =
                            PressureQualificationMath::pressureRawFromPsiMilli(1000u);
                        static constexpr uint16_t kPressure2Raw =
                            PressureQualificationMath::pressureRawFromPsiMilli(2000u);
                        static constexpr uint32_t kPressureGuardAbsSteps = 80000u;
                        static constexpr uint32_t kPressureGuardDeltaSteps = 50000u;
                        static constexpr uint32_t kFocusedNormalAcceleration = 140000u;
                        static constexpr uint32_t kFocusedReducedAcceleration = 70000u;
                        static constexpr int32_t kFocusedHomePosition = 100;
                        static constexpr int32_t kFocusedAwayPosition = 20100;
                        static constexpr int32_t kFocusedReducedAwayPosition = 24100;
                        // Every self-test command remains in the historical
                        // MRES=2 logical coordinate system. MotionUnitScale
                        // performs the MRES=3 conversion at the motor boundary.
                        const uint32_t kXyHomeFastHz = kBaselineXyHomeFastHz;
                        const uint32_t kXyHomeSlowHz = kBaselineXyHomeSlowHz;
                        const uint32_t kHomeGuardMarginSteps =
                            kBaselineHomeGuardMarginSteps;
                        const uint32_t kMinimumHomeGuardSteps =
                            kBaselineMinimumHomeGuardSteps;
                        const uint32_t kXEnvelopeMaximumSteps =
                            kBaselineXEnvelopeMaximumSteps;
                        const uint32_t kYEnvelopeMaximumSteps =
                            kBaselineYEnvelopeMaximumSteps;
                        const uint32_t kZHomeFastHz = kBaselineZHomeFastHz;
                        const uint32_t kZHomeSlowHz = kBaselineZHomeSlowHz;
                        const uint32_t kHomeBackoffSteps =
                            kBaselineHomeBackoffSteps;
                        const uint32_t kExpectedBackoffPosition =
                            kBaselineExpectedBackoffPosition;
                        const uint32_t kHomeDriftLimitSteps =
                            kBaselineHomeDriftLimitSteps;
                        const uint32_t kReturnErrorLimitSteps =
                            kBaselineReturnErrorLimitSteps;
                        // The production two-edge path retains its established
                        // half-period cycle gates. CompleteStep has a 4,500-
                        // core-cycle full period at 40 kHz; its 3,500-cycle
                        // active gate preserves the independently reported
                        // 500-timer-tick (1,000-core-cycle) minimum slack.
                        Limits performanceLimits{};
                        if (runCoordinatedXySingleIrqSuite) {
                          performanceLimits.activeMaxCycles = 3500u;
                          performanceLimits.terminalMaxCycles = 4500u;
                        }
                        const Comm::StatusMetricsSyncMode requestedStatusSyncMode =
                            runCoordinatedXyStatusSyncSuite
                                ? Comm::StatusMetricsSyncMode::TaskMutex
                                : Comm::StatusMetricsSyncMode::CriticalSection;
                        ScopedStatusMetricsSyncMode statusSyncGuard(
                            requestedStatusSyncMode);

                        struct TestDescriptor {
                          uint16_t id;
                          const char* name;
                        };
                        static constexpr TestDescriptor kTests[] = {
                            {2060u, "coordinated_xy_performance_5khz"},
                            {2061u, "coordinated_xy_performance_10khz"},
                            {2062u, "coordinated_xy_performance_20khz"},
                            {2063u, "coordinated_xy_performance_30khz"},
                            {2064u, "coordinated_xy_performance_40khz"},
                            {2065u, "coord_xy_perf_m1_comparison"},
                            {2066u, "coord_xy_perf_raster"},
                            {2067u, "coord_xy_perf_camera_repeat"},
                            {2068u, "coord_xy_perf_pr"},
                        };
                        struct Point {
                          int32_t x;
                          int32_t y;
                        };
                        struct Pair {
                          Point start;
                          Point finish;
                        };
                        static constexpr Pair kGeometryPairs[] = {
                            {{5000, 5000}, {25000, 5000}},
                            {{5000, 5000}, {5000, 25000}},
                            {{5000, 5000}, {25000, 25000}},
                            {{5000, 5000}, {10000, 25000}},
                            {{8916, 30500}, {500, 500}},
                        };
                        static constexpr uint32_t kRatesHz[] = {
                            5000u, 10000u, 20000u, 30000u, 40000u};

                        Stepper* stepperX = Stepper::stepperX();
                        Stepper* stepperY = Stepper::stepperY();
                        Stepper* stepperZ = Stepper::stepperZ();
                        Stepper* stepperP = Stepper::stepperP();
                        Stepper* stepperR = Stepper::stepperR();
                        Gantry* gantry = Gantry::instance();
                        PressureSensor* pressureSensor = PressureSensor::instance();
                        const CoordinatedXyExecutor::ExecutionMode
                            requestedExecutionMode =
                                CoordinatedXyExecutor::ExecutionMode::TwoEdge;
                        ScopedCoordinatedXyExecutionMode executionModeGuard(
                            gantry, requestedExecutionMode);
                        const CoordinatedXyTimerSchedulePolicy::Mode
                            requestedTimerScheduleMode =
                                runCoordinatedXyMres3RearmSuite
                                    ? CoordinatedXyTimerSchedulePolicy::Mode::
                                          RearmFromActualEdge
                                    : (runCoordinatedXyMres3ConditionalRearmSuite ||
                                       runCoordinatedXyProductionMres3Suite)
                                    ? CoordinatedXyTimerSchedulePolicy::Mode::
                                          ConditionalLateRearm
                                    : CoordinatedXyTimerSchedulePolicy::Mode::
                                          FreeRunning;
                        ScopedCoordinatedXyTimerScheduleMode timerScheduleGuard(
                            gantry, requestedTimerScheduleMode);

                        const uint32_t savedXMaxRateHz =
                            stepperX != nullptr ? stepperX->maxSpeedHz() : 0u;
                        const uint32_t savedYMaxRateHz =
                            stepperY != nullptr ? stepperY->maxSpeedHz() : 0u;
                        const float savedXAcceleration =
                            stepperX != nullptr ? stepperX->accelStepsPerSec2() : 0.0f;
                        const float savedYAcceleration =
                            stepperY != nullptr ? stepperY->accelStepsPerSec2() : 0.0f;
                        auto restoreXyRates = [&]() {
                          if (stepperX != nullptr) stepperX->setMaxSpeedHz(savedXMaxRateHz);
                          if (stepperY != nullptr) stepperY->setMaxSpeedHz(savedYMaxRateHz);
                          if (stepperX != nullptr) stepperX->setAccelStepsPerSec2(savedXAcceleration);
                          if (stepperY != nullptr) stepperY->setAccelStepsPerSec2(savedYAcceleration);
                        };
                        auto closePressurePaths = [&]() {
                          PressureRegulator::regP().pause();
                          PressureRegulator::regP().closeValve();
#if (LC_PRESSURE_PORTS > 1)
                          PressureRegulator::regR().pause();
                          PressureRegulator::regR().closeValve();
#endif
                        };
                        bool focusedDirectionResultEmitted = false;
                        bool transitionResultEmitted = false;
                        auto emitMres3Configuration = [&]() {
                          const TMC2208InitializationSnapshot driver =
                              TMC2208Driver::initializationSnapshot();
                          const TMC2208Configuration::Values expected =
                              TMC2208Configuration::valuesForMres(3u);
                          const bool scheduleModeExpected = gantry != nullptr &&
                              gantry->coordinatedTimerScheduleMode() ==
                                  (runCoordinatedXyProductionMres3Suite
                                       ? CoordinatedXyTimerSchedulePolicy::Mode::
                                             ConditionalLateRearm
                                       : requestedTimerScheduleMode);
                          char configMetrics[160] = {};
                          const int written = snprintf(
                              configMetrics,
                              sizeof(configMetrics),
                              "mr=%u;mf=%u;dd=%u;gc=%lu;cc=%lu;tx=%lu;tf=%lu;"
                              "ve=%u;ae=%u;lu=%lu;ge=%u;sf=0;to=0",
                              static_cast<unsigned>(driver.mres),
                              driver.multistepFilter ? 1u : 0u,
                              driver.doubleEdge ? 1u : 0u,
                              (unsigned long)driver.gconf,
                              (unsigned long)driver.chopconf,
                              (unsigned long)driver.successfulWrites,
                              (unsigned long)driver.failedWrites,
                              TMC2208Configuration::preservesMres2PhysicalRate(
                                  40000u) ? 1u : 0u,
                              TMC2208Configuration::
                                      preservesMres2PhysicalAcceleration(140000u)
                                  ? 1u : 0u,
                              (unsigned long)
                                  MotionUnitScale::logicalUnitsPerNativeStep(),
                              scheduleModeExpected ? 1u : 0u);
                          const bool expectedBuild =
                              runCoordinatedXyProductionMres3Suite
                                  ? TMC2208Configuration::isProductionMres3Build()
                                  : TMC2208Configuration::isMres3DiagnosticBuild();
                          const bool passed =
                              expectedBuild &&
                              driver.initialized &&
                              driver.mres == expected.mres &&
                              driver.multistepFilter == expected.multistepFilter &&
                              driver.doubleEdge == expected.doubleEdge &&
                              driver.gconf == expected.gconf &&
                              driver.chopconf == expected.chopconf &&
                              driver.successfulWrites == 4u &&
                              driver.failedWrites == 0u &&
                              MotionUnitScale::logicalUnitsPerNativeStep() == 2u &&
                              scheduleModeExpected;
                          const bool metricsFit = written > 0 &&
                              static_cast<size_t>(written) < sizeof(configMetrics);
                          (void)runOne(
                                       runCoordinatedXyProductionMres3Suite
                                           ? 2090u : 2083u,
                                       runCoordinatedXyProductionMres3Suite
                                           ? "tmc2208_production_mres3_config"
                                           : "tmc2208_mres3_configuration",
                                       passed && metricsFit,
                                       metricsFit
                                           ? configMetrics
                                           : "gate=metrics_overflow;to=1");
                          return passed && metricsFit;
                        };
                        auto emitSkipped = [&](uint16_t firstId,
                                               const char* gate) {
                          char metrics[96];
                          snprintf(metrics,
                                   sizeof(metrics),
                                   "gate=%s;hz=0;n=0;i2=0;i7=0;pu=0;wl=0;to=1",
                                   gate);
                          if (runCoordinatedXyTransitionSuite) {
                            if (!transitionResultEmitted) {
                              (void)runOne(2071u,
                                           "coord_xy_camera_home_transition",
                                           false,
                                           metrics);
                              transitionResultEmitted = true;
                            }
                            return;
                          }
                          if (runCoordinatedXyLogicalMres3Suite) {
                            (void)runOne(
                                         runCoordinatedXyProductionMres3Suite
                                             ? 2087u : 2080u,
                                         runCoordinatedXyProductionMres3Suite
                                             ? "coord_xy_prod_mres3_motion"
                                             : "coord_xy_mres3_20khz_motion",
                                         false,
                                         metrics);
                            (void)runOne(
                                runCoordinatedXyProductionMres3Suite
                                    ? 2088u : 2081u,
                                runCoordinatedXyProductionMres3Suite
                                    ? "coord_xy_prod_mres3_irq_path"
                                    : "coord_xy_mres3_20khz_irq_path",
                                false,
                                "i2=0;s=0;mi=0;ph=0;pa=0;fm=0;fa=0;tf=0;pp=0;pf=0;pu=0;ps=0;sf=0;to=1");
                            (void)runOne(
                                runCoordinatedXyProductionMres3Suite
                                    ? 2089u : 2082u,
                                runCoordinatedXyProductionMres3Suite
                                    ? "coord_xy_prod_conditional_rearm"
                                    : "coord_xy_mres3_entry_margin",
                                false,
                                runCoordinatedXyMres3RearmSuite
                                    ? "i2=0;s=0;mi=0;cm=0;ca=0;pm=0;lc=0;dm=0;ds=0;di=0;md=0;sl=0;rm=1;rc=0;rp=0;rd=0;sf=0;to=1"
                                    : (runCoordinatedXyMres3ConditionalRearmSuite ||
                                       runCoordinatedXyProductionMres3Suite)
                                    ? "i2=0;s=0;mi=0;cm=0;ca=0;pm=0;lc=0;dm=0;ds=0;di=0;md=0;sl=0;rm=2;rc=0;rp=0;rd=0;sf=0;to=1"
                                    : "i2=0;s=0;mi=0;cm=0;ca=0;pm=0;lc=0;dm=0;ds=0;di=0;md=0;sl=0;rm=0;rc=0;rp=0;rd=0;sf=0;to=1");
                            if (runCoordinatedXyMres3ConditionalRearmSuite) {
                              (void)runOne(
                                  2086u,
                                  "coord_xy_conditional_rearm",
                                  false,
                                  "rm=2;rg=1125;it=900;dc=0;mi=0;rc=0;rp=0;rd=0;ic=0;ix=0;ir=0;im=0;ns=0;wm=0;sf=0;to=1");
                            }
                            (void)emitMres3Configuration();
                            return;
                          }
                          if (runCoordinatedXy40KhzSuite) {
                            char entryMetrics[224] = {};
                            const unsigned statusSyncMode = static_cast<unsigned>(
                                Comm::getStatusMetricsSyncMode());
                            const unsigned long lockFailures =
                                static_cast<unsigned long>(
                                    Comm::getStatusMetricsLockFailureCount());
                            (void)runOne(2064u,
                                         "coordinated_xy_performance_40khz",
                                         false,
                                         metrics);
                            (void)runOne(
                                2072u,
                                "coord_xy_40khz_irq_path",
                                false,
                                "i2=0;s=0;mi=0;ph=0;pa=0;fm=0;fa=0;tf=0;pp=0;pf=0;pu=0;ps=0;sf=0;to=1");
                            (void)runOne(
                                2073u,
                                "coord_xy_40khz_entry_lateness",
                                false,
                                (snprintf(entryMetrics,
                                          sizeof(entryMetrics),
                                          "i2=0;s=0;mi=0;cm=0;ca=0;pm=0;lc=0;"
                                          "dm=0;sm=%u;lf=%lu;sf=0;to=1;"
                                          "fv=0;tr=0;la=0;ra=0",
                                          statusSyncMode,
                                          lockFailures) > 0)
                                    ? entryMetrics
                                    : "gate=metrics_overflow;to=1");
                            if (runCoordinatedXySingleIrqSuite) {
                              (void)runOne(
                                  2074u,
                                  "coord_xy_single_irq_pulse",
                                  false,
                                  "em=1;ip=1;i2=0;pc=0;pn=0;px=0;pe=0;ds=0;mi=0;md=0;sl=0;pu=0;ok=0;sf=0;to=1");
                            }
                            return;
                          }
                          if (!runCoordinatedXyDirectionSuite) {
                            for (const TestDescriptor& test : kTests) {
                              if (test.id >= firstId) {
                                (void)runOne(test.id, test.name, false, metrics);
                              }
                            }
                          }
                          if (!focusedDirectionResultEmitted) {
                            (void)runOne(2070u,
                                         "coord_xy_perf_x_direction",
                                         false,
                                         metrics);
                          }
                        };
                        auto failRemaining = [&](uint16_t firstId,
                                                 const char* gate) {
                          Gantry::cancelXYZMotors();
                          closePressurePaths();
                          restoreXyRates();
                          comm->setStatusPaused(true);
                          emitSkipped(firstId, gate);
                        };

                        if (!statusSyncGuard.activated()) {
                          failRemaining(2060u, "status_sync_unavailable");
                          return finishSelfTestNow();
                        }
                        if (!executionModeGuard.activated()) {
                          failRemaining(2060u, "executor_mode_unavailable");
                          return finishSelfTestNow();
                        }
                        if (!timerScheduleGuard.activated()) {
                          failRemaining(2060u, "timer_schedule_unavailable");
                          return finishSelfTestNow();
                        }

                        if (runCoordinatedXySingleIrqSuite) {
                          failRemaining(2060u, "single_irq_superseded");
                          return finishSelfTestNow();
                        }

                        if (stepperX == nullptr || stepperY == nullptr ||
                            stepperZ == nullptr || gantry == nullptr || comm == nullptr ||
                            LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE == 0 ||
                            LC_COORDINATED_XY_ISR_INSTRUMENTATION_ENABLE == 0 ||
                            savedXMaxRateHz != 40000u || savedYMaxRateHz != 40000u) {
                          failRemaining(2060u, "configuration");
                          return finishSelfTestNow();
                        }
                        if (runCoordinatedXyMres3Suite &&
                            !TMC2208Configuration::isMres3DiagnosticBuild()) {
                          failRemaining(2080u, "mres3_build_required");
                          return finishSelfTestNow();
                        }
                        if (runCoordinatedXyProductionMres3Suite &&
                            !TMC2208Configuration::isProductionMres3Build()) {
                          failRemaining(2087u, "production_mres3_build_required");
                          return finishSelfTestNow();
                        }
                        if (runCoordinatedXyLogicalMres3Suite) {
                          const TMC2208InitializationSnapshot driver =
                              TMC2208Driver::initializationSnapshot();
                          if (!driver.initialized || driver.mres != 3u ||
                              driver.multistepFilter || !driver.doubleEdge ||
                              driver.successfulWrites != 4u ||
                              driver.failedWrites != 0u) {
                            failRemaining(
                                runCoordinatedXyProductionMres3Suite
                                    ? 2087u : 2080u,
                                "tmc_configuration");
                            return finishSelfTestNow();
                          }
                        }
                        const char* fixtureStage = runCoordinatedXyTransitionSuite
                            ? "coordinated_xy_camera_transition_envelope_clear"
                            : runCoordinatedXySingleIrqSuite
                                ? "coordinated_xy_single_irq_envelope_clear"
                            : runCoordinatedXyMres3ConditionalRearmSuite
                                ? "coordinated_xy_mres3_conditional_rearm_envelope_clear"
                            : runCoordinatedXyProductionMres3Suite
                                ? "coordinated_xy_production_mres3_envelope_clear"
                            : runCoordinatedXyMres3RearmSuite
                                ? "coordinated_xy_mres3_rearm_envelope_clear"
                            : runCoordinatedXyMres3Suite
                                ? "coordinated_xy_mres3_20khz_envelope_clear"
                            : runCoordinatedXy40KhzSuite
                                ? "coordinated_xy_40khz_envelope_clear"
                                : "coordinated_xy_performance_fixture_clear";
                        if (!waitForOperatorResume(fixtureStage)) {
                          failRemaining(2060u, "fixture");
                          return finishSelfTestNow();
                        }
                        // The manual switch preflight and low-rate homing
                        // regression passed after the bounded diagnostic-home
                        // change. No subsequent change affects limit sampling
                        // or homing, so the M6 selectors retain exactly one
                        // fixture/envelope confirmation above.
                        closePressurePaths();
                        if (!runZClearanceHomePreflight(
                                "coordinated_xy_performance_z_home",
                                kZHomeFastHz,
                                kZHomeSlowHz,
                                kHomeBackoffSteps,
                                kHomeTimeoutMs)) {
                          failRemaining(2060u, "z_home");
                          return finishSelfTestNow();
                        }

                        struct BoundedHomeResult {
                          bool passed = false;
                          bool outerTimedOut = false;
                          uint32_t guardSteps = 0u;
                          Stepper::HomeDiagnosticSnapshot snapshot{};
                        };
                        BoundedHomeResult lastXHome{};
                        BoundedHomeResult lastYHome{};
                        auto runBoundedAxisHome = [&](Stepper* stepper,
                                                      EventBits_t homeBit,
                                                      MotionQualificationMath::AxisHomeSample& sample,
                                                      uint32_t envelopeMaximum,
                                                      bool positionKnown) {
                          BoundedHomeResult result{};
                          result.guardSteps =
                              CoordinatedXyPerformanceReport::boundedHomeGuardSteps(
                                  stepper->getPosition(),
                                  envelopeMaximum,
                                  kHomeGuardMarginSteps,
                                  kMinimumHomeGuardSteps,
                                  positionKnown);
                          const uint32_t savedGuard = stepper->homeGuardSteps();
                          stepper->setHomeGuardSteps(result.guardSteps);
                          stepper->enableMotor();
                          xEventGroupClearBits(_doneEvents, homeBit);
                          startHomeAsync(stepper,
                                         kXyHomeFastHz,
                                         kXyHomeSlowHz,
                                         kHomeBackoffSteps,
                                         homeBit);
                          const bool done = waitBitsWithTimeout(
                              homeBit, kBoundedHomeTimeoutMs);
                          if (!done) {
                            result.outerTimedOut = true;
                            (void)cancelActiveHomesAndWait(homeBit);
                          }
                          const bool axisDone =
                              (xEventGroupGetBits(_doneEvents) & homeBit) != 0u;
                          result.snapshot = stepper->getLastHomeDiagnosticSnapshot();
                          stepper->setHomeGuardSteps(savedGuard);
                          sample.success = axisDone && result.snapshot.success;
                          sample.limitTriggerSteps =
                              result.snapshot.fineLimitPositionSteps;
                          sample.finalBackoffSteps =
                              result.snapshot.finalBackoffPositionSteps;
                          sample.moveTimeoutCount =
                              result.snapshot.moveTimeoutCount;
                          result.passed = done && sample.success;
                          return result;
                        };
                        auto runSequentialXyHome = [&](MotionQualificationMath::AxisHomeSample& x,
                                                       MotionQualificationMath::AxisHomeSample& y,
                                                       const char* xStage,
                                                       const char* yStage,
                                                       bool positionKnown) {
                          comm->setStatusPaused(false);
                          sendProgressStage(xStage);
                          lastXHome = runBoundedAxisHome(stepperX,
                                                        BIT_HOME_X_DONE,
                                                        x,
                                                        kXEnvelopeMaximumSteps,
                                                        positionKnown);
                          if (!lastXHome.passed) {
                            return false;
                          }
                          sendProgressStage(yStage);
                          lastYHome = runBoundedAxisHome(stepperY,
                                                        BIT_HOME_Y_DONE,
                                                        y,
                                                        kYEnvelopeMaximumSteps,
                                                        positionKnown);
                          return lastYHome.passed;
                        };
                        MotionQualificationMath::AxisHomeSample xReference{};
                        MotionQualificationMath::AxisHomeSample yReference{};
                        if (!runSequentialXyHome(
                                xReference,
                                yReference,
                                "coordinated_xy_performance_x_home",
                                "coordinated_xy_performance_y_home",
                                false) ||
                            stepperX->getPosition() !=
                                static_cast<int32_t>(kExpectedBackoffPosition) ||
                            stepperY->getPosition() !=
                                static_cast<int32_t>(kExpectedBackoffPosition)) {
                          failRemaining(2060u, "xy_home");
                          return finishSelfTestNow();
                        }

                        auto absoluteDelta = [](int32_t from, int32_t to) {
                          const int64_t delta =
                              static_cast<int64_t>(to) - static_cast<int64_t>(from);
                          return static_cast<uint32_t>(delta < 0 ? -delta : delta);
                        };
                        auto targetArrForRate = [](uint32_t rateHz) {
                          return rateHz == 0u
                              ? std::numeric_limits<uint32_t>::max()
                              : (kTimerClockHz / (2u * rateHz)) - 1u;
                        };
                        auto startArrForRate = [&](uint32_t rateHz) {
                          return targetArrForRate(rateHz) * 5u;
                        };

                        struct MoveResult {
                          bool passed = false;
                          bool canContinue = false;
                          uint32_t failureMask = 0u;
                          MoveObservation observation{};
                          CoordinatedXySnapshot snapshot{};
                        };
                        CoordinatedXyPerformanceReport::FailureTelemetry
                            firstMoveFailure{};
                        auto classifyMove = [&](MoveResult& result) {
                          result.failureMask =
                              CoordinatedXyPerformanceReport::moveFailureMask(
                                  result.observation, performanceLimits);
                          result.passed = result.failureMask == 0u;
                          result.canContinue =
                              CoordinatedXyPerformanceReport::
                                  moveCanContinueAfterCompletion(
                                      result.observation, performanceLimits);
                          CoordinatedXyPerformanceReport::captureFirstFailure(
                              firstMoveFailure,
                              result.canContinue,
                              result.snapshot.terminalReason,
                              result.snapshot.limitAbortRequestCount,
                              result.snapshot.rawLimitAbortCount,
                              result.failureMask);
                        };
                        auto observeCompletedMove = [&](Point start,
                                                        Point target,
                                                        uint32_t expectedRateHz,
                                                        bool direct,
                                                        bool* pMoved,
                                                        bool* rMoved,
                                                        bool* pressureGuard) -> MoveResult {
                          MoveResult result{};
                          const uint32_t expectedX =
                              MotionUnitScale::toNativeStepCycles(
                                  absoluteDelta(start.x, target.x));
                          const uint32_t expectedY =
                              MotionUnitScale::toNativeStepCycles(
                                  absoluteDelta(start.y, target.y));
                          const uint32_t expectedMaster =
                              expectedX > expectedY ? expectedX : expectedY;
                          const bool statusMetricsReset =
                              Comm::resetStatusMetrics();
                          comm->setStatusPaused(false);
                          bool completed = false;
                          bool endpoint = false;
                          bool targets = false;
                          bool timedOut = false;
                          const int32_t pStart =
                              stepperP != nullptr ? stepperP->getPosition() : 0;
                          const int32_t rStart =
                              stepperR != nullptr ? stepperR->getPosition() : 0;
                          const bool injectionReady =
                              !runCoordinatedXyMres3ConditionalRearmSuite ||
                              gantry->
                                  armCoordinatedLateServiceInjectionForDiagnostics();
                          if (!injectionReady) {
                            timedOut = true;
                            result.snapshot = gantry->coordinatedSnapshot();
                          } else if (direct) {
                            xEventGroupClearBits(
                                _doneEvents, BIT_STEPPER1_DONE | BIT_STEPPER2_DONE);
                            const CoordinatedStartStatus status =
                                gantry->moveTo(target.x, target.y, 0u);
                            if (status == CoordinatedStartStatus::Started) {
                              const uint32_t startedMs = HAL_GetTick();
                              const TickType_t pollTicks = msToAtLeast1Tick(2u);
                              while ((HAL_GetTick() - startedMs) < kMoveTimeoutMs) {
                                Watchdog_CheckIn(CRASH_TASK_ORCH);
                                maybeSendProgress("coordinated_xy_performance_move");
                                if (pMoved != nullptr && stepperP != nullptr &&
                                    stepperP->getPosition() != pStart) *pMoved = true;
                                if (rMoved != nullptr && stepperR != nullptr &&
                                    stepperR->getPosition() != rStart) *rMoved = true;
                                if (pressureGuard != nullptr &&
                                    stepperP != nullptr && stepperR != nullptr) {
                                  const int32_t pNow = stepperP->getPosition();
                                  const int32_t rNow = stepperR->getPosition();
                                  if (absDiff32(pNow, 0) > kPressureGuardAbsSteps ||
                                      absDiff32(rNow, 0) > kPressureGuardAbsSteps ||
                                      absDiff32(pNow, pStart) > kPressureGuardDeltaSteps ||
                                      absDiff32(rNow, rStart) > kPressureGuardDeltaSteps) {
                                    *pressureGuard = true;
                                    Gantry::cancelXYZMotors();
                                    break;
                                  }
                                }
                                const EventBits_t bits = xEventGroupGetBits(_doneEvents);
                                if ((bits & (BIT_STEPPER1_DONE | BIT_STEPPER2_DONE)) ==
                                    (BIT_STEPPER1_DONE | BIT_STEPPER2_DONE)) {
                                  completed = true;
                                  break;
                                }
                                if (_selfTestAbortRequested) break;
                                vTaskDelay(pollTicks);
                              }
                              if (!completed) {
                                timedOut = true;
                                Gantry::cancelXYZMotors();
                              }
                            } else {
                              timedOut = true;
                            }
                            result.snapshot = gantry->coordinatedSnapshot();
                            endpoint = completed &&
                                result.snapshot.state ==
                                    CoordinatedXyExecutor::State::Completed &&
                                result.snapshot.xPosition == target.x &&
                                result.snapshot.yPosition == target.y;
                            targets = result.snapshot.xTarget == target.x &&
                                      result.snapshot.yTarget == target.y;
                          } else {
                            const Orchestrator::AbsoluteXyExecutionResult execution =
                                orchestrator.executeAbsoluteXy(
                                    target.x, target.y, 0u, false, kMoveTimeoutMs);
                            result.snapshot = gantry->coordinatedSnapshot();
                            completed = execution.waitCompleted &&
                                execution.disposition ==
                                    OrchestratorCompletionPolicy::AbsXyDisposition::Completed;
                            endpoint = execution.endpointMatches &&
                                result.snapshot.xPosition == target.x &&
                                result.snapshot.yPosition == target.y;
                            targets = execution.targetsMatch &&
                                result.snapshot.xTarget == target.x &&
                                result.snapshot.yTarget == target.y;
                            timedOut = !execution.waitCompleted;
                          }
                          if (runCoordinatedXyMres3ConditionalRearmSuite) {
                            gantry->
                                clearCoordinatedLateServiceInjectionForDiagnostics();
                          }
                          uint32_t statusAgeMs =
                              std::numeric_limits<uint32_t>::max();
                          (void)Watchdog_GetTaskLastSeenAgeMs(
                              CRASH_TASK_STATUS, &statusAgeMs);
                          comm->setStatusPaused(true);
                          const Comm::StatusMetricsSnapshot statusMetrics =
                              Comm::getStatusMetricsSnapshot();
                          const bool statusMetricsValid =
                              statusMetricsReset && statusMetrics.valid &&
                              statusMetrics.lockFailures == 0u;
                          const uint32_t statusFrames = statusMetricsValid
                              ? statusMetrics.chunk0Count + statusMetrics.chunk1Count
                              : 0u;
                          const uint32_t statusGapMs = statusMetricsValid
                              ? statusMetrics.periodMaxMs
                              : std::numeric_limits<uint32_t>::max();
                          const uint32_t alternationErrors = statusMetricsValid
                              ? statusMetrics.alternationErrors
                              : 1u;

                          if (expectedRateHz == 0u) {
                            expectedRateHz = result.snapshot.selectedMasterRateHz;
                          } else {
                            expectedRateHz =
                                MotionUnitScale::toNativeRate(expectedRateHz);
                          }
                          MoveObservation& observation = result.observation;
                          observation.expectedXSteps = expectedX;
                          observation.expectedYSteps = expectedY;
                          observation.expectedMasterSteps = expectedMaster;
                          observation.expectedRateHz = expectedRateHz;
                          observation.executionMode =
                              result.snapshot.executionMode;
                          observation.timerScheduleMode =
                              result.snapshot.timerScheduleMode;
                          observation.interruptsPerMasterStep =
                              result.snapshot.executionMode ==
                                      CoordinatedXyExecutor::ExecutionMode::CompleteStep
                                  ? 1u
                                  : 2u;
                          observation.minimumPulseCoreCycles =
                              result.snapshot.minimumPulseCoreCycles;
                          observation.timerRearmCount =
                              result.snapshot.timerRearmCount;
                          observation.timerRearmPendingCount =
                              result.snapshot.timerRearmPendingCount;
                          observation.timerRearmDelayMaxCycles =
                              result.snapshot.timerRearmDelayMaxCycles;
                          observation.conditionalDecisionCount =
                              result.snapshot.conditionalDecisionCount;
                          observation.conditionalDecisionMissingCount =
                              result.snapshot.conditionalDecisionMissingCount;
                          observation.conditionalNonRearmSlackMinTicks =
                              result.snapshot.conditionalNonRearmSlackMinTicks;
                          observation.lateInjectionCount =
                              result.snapshot.lateInjectionCount;
                          observation.lateInjectionFailureCount =
                              result.snapshot.lateInjectionFailureCount;
                          observation.lateInjectionRearmCount =
                              result.snapshot.lateInjectionRearmCount;
                          observation.lateInjectionDecisionSlackMaxTicks =
                              result.snapshot.lateInjectionDecisionSlackMaxTicks;
                          observation.lateInjectionWaitMaxCycles =
                              result.snapshot.lateInjectionWaitMaxCycles;
                          observation.timerScheduleSaturationFlags =
                              result.snapshot.timerScheduleSaturationFlags;
                          observation.expectedTargetArr =
                              targetArrForRate(expectedRateHz);
                          observation.expectedStartArr =
                              startArrForRate(expectedRateHz);
                          observation.requestedXSteps =
                              result.snapshot.requestedXSteps;
                          observation.requestedYSteps =
                              result.snapshot.requestedYSteps;
                          observation.emittedXSteps = result.snapshot.emittedXSteps;
                          observation.emittedYSteps = result.snapshot.emittedYSteps;
                          observation.masterSteps = result.snapshot.masterSteps;
                          observation.selectedRateHz =
                              result.snapshot.selectedMasterRateHz;
                          observation.timer2Callbacks =
                              result.snapshot.timer2Interrupts;
                          observation.timer7Callbacks =
                              result.snapshot.timer7Interrupts;
                          observation.arrMin = result.snapshot.arrMin;
                          observation.arrMax = result.snapshot.arrMax;
                          observation.durationErrorBasisPoints =
                              result.snapshot.durationErrorBasisPoints;
                          observation.statusPeriodMaxMs = statusGapMs;
                          observation.statusWatchdogAgeMaxMs = statusAgeMs;
                          observation.statusFrameCount = statusFrames;
                          observation.statusAlternationErrors = alternationErrors;
                          observation.watchdogLateCount =
                              Watchdog_GetLateTask() == CRASH_TASK_NONE ? 0u : 1u;
                          observation.minimumDeadlineSlackTicks =
                               collectCompletedMres3Evidence ? 450u : 0u;
                          observation.requireLateInjectionEvidence =
                               !runCoordinatedXyProductionMres3Suite;
                          observation.requireTerminalCycleBudget =
                               !runCoordinatedXyProductionMres3Suite;
                          observation.requireNoLateEntries =
                               collectCompletedMres3Evidence &&
                               !runCoordinatedXyProductionMres3Suite;
                          observation.terminalReason =
                              result.snapshot.terminalReason;
                          observation.endpointMatches = endpoint;
                          observation.targetsMatch = targets;
                          // The normal Orchestrator wait requires both bits and
                          // clears them on exit. The direct diagnostic path also
                          // sets completed only after observing both bits.
                          observation.completionTogether = completed;
                          observation.pinsLow = result.snapshot.xStepLow &&
                                                result.snapshot.yStepLow;
                          observation.ownershipReleased =
                              !result.snapshot.timerOwned;
                          observation.checksumMatch = true;
                          observation.timedOut = timedOut || !completed;
                          observation.timing = result.snapshot.timing;
                          classifyMove(result);
                          return result;
                        };

                        auto positionTo = [&](Point target) {
                          const GantryPosition current = gantry->getPosition();
                          if (current.x == target.x && current.y == target.y) return true;
                          comm->setStatusPaused(false);
                          const Orchestrator::AbsoluteXyExecutionResult execution =
                              orchestrator.executeAbsoluteXy(
                                  target.x, target.y, 0u, false, kMoveTimeoutMs);
                          const CoordinatedXySnapshot snapshot =
                              gantry->coordinatedSnapshot();
                          // This is an unmeasured positioning leg. Require safe,
                          // exact completion here; the following measured leg
                          // records and gates ISR timing and pending observations.
                          const bool passed = execution.disposition ==
                                  OrchestratorCompletionPolicy::AbsXyDisposition::Completed &&
                              execution.waitCompleted && execution.endpointMatches &&
                              execution.targetsMatch &&
                              snapshot.pendingUpdateCount == 0u &&
                              snapshot.xStepLow && snapshot.yStepLow &&
                              !snapshot.timerOwned;
                          uint32_t failureMask = 0u;
                          if (execution.disposition !=
                                  OrchestratorCompletionPolicy::
                                      AbsXyDisposition::Completed ||
                              snapshot.terminalReason !=
                                  CoordinatedXyExecutor::TerminalReason::Completed) {
                            failureMask |= CoordinatedXyPerformanceReport::
                                kMoveFailureTerminalReason;
                          }
                          if (!execution.waitCompleted) {
                            failureMask |= CoordinatedXyPerformanceReport::
                                kMoveFailureTimedOut;
                          }
                          if (!execution.endpointMatches) {
                            failureMask |= CoordinatedXyPerformanceReport::
                                kMoveFailureEndpoint;
                          }
                          if (!execution.targetsMatch) {
                            failureMask |= CoordinatedXyPerformanceReport::
                                kMoveFailureTargets;
                          }
                          if (snapshot.pendingUpdateCount != 0u) {
                            failureMask |= CoordinatedXyPerformanceReport::
                                kMoveFailurePendingUpdate;
                          }
                          if (!snapshot.xStepLow || !snapshot.yStepLow) {
                            failureMask |= CoordinatedXyPerformanceReport::
                                kMoveFailurePins;
                          }
                          if (snapshot.timerOwned) {
                            failureMask |= CoordinatedXyPerformanceReport::
                                kMoveFailureOwnership;
                          }
                          CoordinatedXyPerformanceReport::captureFirstFailure(
                              firstMoveFailure,
                              passed,
                              snapshot.terminalReason,
                              snapshot.limitAbortRequestCount,
                              snapshot.rawLimitAbortCount,
                              failureMask);
                          return passed;
                        };

                        auto addPair = [&](Aggregate& aggregate,
                                           const Pair& pair,
                                           uint32_t rateHz) {
                          if (!positionTo(pair.start)) return false;
                          MoveResult forward = observeCompletedMove(
                              pair.start, pair.finish, rateHz, false, nullptr, nullptr, nullptr);
                          const bool forwardMayContinue =
                              collectCompletedMres3Evidence
                                  ? forward.canContinue
                                  : forward.passed;
                          if (!forwardMayContinue) {
                            CoordinatedXyPerformanceReport::addMove(
                                aggregate,
                                forward.observation,
                                performanceLimits);
                            return false;
                          }
                          MoveResult reverse = observeCompletedMove(
                              pair.finish, pair.start, rateHz, false, nullptr, nullptr, nullptr);
                          const bool checksumsMatch =
                              forward.canContinue && reverse.canContinue &&
                              forward.snapshot.maskChecksum ==
                                  reverse.snapshot.maskChecksum &&
                              forward.snapshot.arrChecksum ==
                                  reverse.snapshot.arrChecksum;
                          forward.observation.checksumMatch = checksumsMatch;
                          reverse.observation.checksumMatch = checksumsMatch;
                          classifyMove(forward);
                          classifyMove(reverse);
                          CoordinatedXyPerformanceReport::addMove(
                              aggregate, forward.observation, performanceLimits);
                          CoordinatedXyPerformanceReport::addMove(
                              aggregate, reverse.observation, performanceLimits);
                          const GantryPosition returned = gantry->getPosition();
                          const uint32_t returnError =
                              absoluteDelta(returned.x, pair.start.x) +
                              absoluteDelta(returned.y, pair.start.y);
                          if (returnError > kReturnErrorLimitSteps) {
                            CoordinatedXyPerformanceReport::captureFirstFailure(
                                firstMoveFailure,
                                false,
                                reverse.snapshot.terminalReason,
                                reverse.snapshot.limitAbortRequestCount,
                                reverse.snapshot.rawLimitAbortCount,
                                CoordinatedXyPerformanceReport::
                                    kMoveFailureEndpoint);
                          }
                          const bool movesMayContinue =
                              collectCompletedMres3Evidence
                                  ? forward.canContinue && reverse.canContinue
                                  : forward.passed && reverse.passed;
                          return movesMayContinue && checksumsMatch &&
                              returnError <= kReturnErrorLimitSteps;
                        };

                        auto homeAndMeasureDrift = [&](uint32_t& xDrift,
                                                       uint32_t& yDrift,
                                                       const char* xStage,
                                                       const char* yStage) {
                          MotionQualificationMath::AxisHomeSample xAfter{};
                          MotionQualificationMath::AxisHomeSample yAfter{};
                          const bool homed = runSequentialXyHome(
                              xAfter, yAfter, xStage, yStage, true);
                          // The first home establishes logical zero. Its
                          // pre-zero trigger coordinate depends on the unknown
                          // startup position, so later repeatability is the
                          // fine-limit trigger's distance from zero.
                          xDrift = homed
                              ? MotionQualificationMath::absDiffSteps(
                                    xAfter.limitTriggerSteps, 0)
                              : std::numeric_limits<uint32_t>::max();
                          yDrift = homed
                              ? MotionQualificationMath::absDiffSteps(
                                    yAfter.limitTriggerSteps, 0)
                              : std::numeric_limits<uint32_t>::max();
                          return homed && xDrift <= kHomeDriftLimitSteps &&
                              yDrift <= kHomeDriftLimitSteps;
                        };

                        auto emitAggregate = [&](const TestDescriptor& test,
                                                  uint32_t rateHz,
                                                  Aggregate& aggregate,
                                                  uint32_t expectedMoves,
                                                  uint32_t expectedX,
                                                  uint32_t expectedY,
                                                  uint32_t expectedMaster,
                                                  uint32_t xDrift,
                                                  uint32_t yDrift,
                                                  bool extraPass) {
                          char metrics[224] = {};
                          size_t length = 0u;
                          if (!extraPass &&
                              (lastXHome.guardSteps != 0u ||
                               lastYHome.guardSteps != 0u)) {
                            const BoundedHomeResult& failedHome =
                                lastXHome.passed ? lastYHome : lastXHome;
                            const int written = snprintf(
                                metrics,
                                sizeof(metrics),
                                "hz=%lu;n=%lu;xe=%lu;ye=%lu;ms=%lu;i2=%lu;i7=%lu;"
                                "hs=%ld;he=%ld;hg=%lu;hc=%lu;ha=%lu;hp=%u;ho=%u;"
                                "hl=%u;ht=%u;qf=%lu;qm=%lu;xd=%lu;yd=%lu;to=1",
                                (unsigned long)rateHz,
                                (unsigned long)aggregate.moveCount,
                                (unsigned long)aggregate.emittedXSteps,
                                (unsigned long)aggregate.emittedYSteps,
                                (unsigned long)aggregate.masterSteps,
                                (unsigned long)aggregate.timer2Callbacks,
                                (unsigned long)aggregate.timer7Callbacks,
                                (long)failedHome.snapshot.startPositionSteps,
                                (long)failedHome.snapshot.endPositionSteps,
                                (unsigned long)failedHome.guardSteps,
                                (unsigned long)failedHome.snapshot.coarseCommandSteps,
                                (unsigned long)failedHome.snapshot.coarseAccountedSteps,
                                static_cast<unsigned>(failedHome.snapshot.phase),
                                static_cast<unsigned>(failedHome.snapshot.outcome),
                                failedHome.snapshot.limitSeen ? 1u : 0u,
                                failedHome.outerTimedOut ? 1u : 0u,
                                (unsigned long)
                                    aggregate.qualificationFailureMoveCount,
                                (unsigned long)
                                    aggregate.qualificationFailureMask,
                                (unsigned long)xDrift,
                                (unsigned long)yDrift);
                            if (written > 0 &&
                                static_cast<size_t>(written) < sizeof(metrics)) {
                              length = static_cast<size_t>(written);
                            }
                          } else {
                            length = CoordinatedXyPerformanceReport::buildMetrics(
                                metrics,
                                sizeof(metrics),
                                rateHz,
                                aggregate,
                                xDrift,
                                yDrift);
                          }
                          const size_t nameLength =
                              std::min(std::strlen(test.name),
                                       DiagnosticResultEmitter::kMaxResultNameBytes);
                          const size_t metricBudget =
                              DiagnosticResultEmitter::kResultMetricsFrameBudget -
                              nameLength;
                          const bool aggregatePass =
                              CoordinatedXyPerformanceReport::aggregatePasses(
                                  aggregate,
                                  expectedMoves,
                                  expectedX,
                                  expectedY,
                                  expectedMaster,
                                  performanceLimits);
                          const bool metricsFit = length > 0u && length <= metricBudget;
                          comm->setStatusPaused(true);
                          (void)runOne(test.id,
                                       test.name,
                                       aggregatePass && extraPass && metricsFit,
                                       metricsFit ? metrics
                                                  : "gate=metrics_overflow;to=1");
                          return aggregatePass && extraPass && metricsFit;
                        };

                        auto runFocusedXDirectionQualification = [&]() {
                          struct FocusCase {
                            uint32_t rateHz;
                            uint32_t acceleration;
                            int32_t awayPosition;
                          };
                          static constexpr FocusCase kFocusCases[] = {
                              {30000u, kFocusedNormalAcceleration,
                               kFocusedAwayPosition},
                              {35000u, kFocusedNormalAcceleration,
                               kFocusedAwayPosition},
                              {40000u, kFocusedReducedAcceleration,
                               kFocusedReducedAwayPosition},
                              {40000u, kFocusedNormalAcceleration,
                               kFocusedAwayPosition},
                          };
                          const Point homePoint{
                              kFocusedHomePosition, kFocusedHomePosition};
                          uint32_t directionalDrift[8] = {
                              std::numeric_limits<uint32_t>::max(),
                              std::numeric_limits<uint32_t>::max(),
                              std::numeric_limits<uint32_t>::max(),
                              std::numeric_limits<uint32_t>::max(),
                              std::numeric_limits<uint32_t>::max(),
                              std::numeric_limits<uint32_t>::max(),
                              std::numeric_limits<uint32_t>::max(),
                              std::numeric_limits<uint32_t>::max(),
                          };
                          Aggregate aggregate{};
                          bool passed = true;
                          uint32_t failedCase = std::numeric_limits<uint32_t>::max();
                          uint32_t failedDirection = 0u;
                          uint32_t failureStage = 0u;
                          uint32_t moveFailureMask = 0u;
                          lastXHome = BoundedHomeResult{};
                          lastYHome = BoundedHomeResult{};

                          for (uint32_t caseIndex = 0u;
                               caseIndex < 4u && passed;
                               ++caseIndex) {
                              const FocusCase& focus = kFocusCases[caseIndex];
                              const Point awayPoint{
                                  focus.awayPosition, kFocusedHomePosition};
                            for (uint32_t direction = 0u;
                                 direction < 2u && passed;
                                 ++direction) {
                              const bool positive = direction == 0u;
                              const Point start = positive ? homePoint : awayPoint;
                              const Point target = positive ? awayPoint : homePoint;

                              // All positioning legs use the already qualified
                              // 5 kHz path. Only the measured leg uses the
                              // case's rate, acceleration, and distance. The
                              // reduced-acceleration case is 24,000 steps so it
                              // reaches a real 40 kHz cruise section.
                              stepperX->setMaxSpeedHz(5000u);
                              stepperY->setMaxSpeedHz(5000u);
                              stepperX->setAccelStepsPerSec2(
                                  static_cast<float>(kFocusedNormalAcceleration));
                              stepperY->setAccelStepsPerSec2(
                                  static_cast<float>(kFocusedNormalAcceleration));
                              passed = positionTo(start);
                              if (!passed) failureStage = 1u;
                              stepperX->setMaxSpeedHz(focus.rateHz);
                              stepperY->setMaxSpeedHz(focus.rateHz);
                              stepperX->setAccelStepsPerSec2(
                                  static_cast<float>(focus.acceleration));
                              stepperY->setAccelStepsPerSec2(
                                  static_cast<float>(focus.acceleration));

                              MoveResult measured{};
                              if (passed) {
                                measured = observeCompletedMove(
                                    start,
                                    target,
                                    focus.rateHz,
                                    false,
                                    nullptr,
                                    nullptr,
                                    nullptr);
                                CoordinatedXyPerformanceReport::addMove(
                                    aggregate,
                                    measured.observation,
                                    performanceLimits);
                                passed = measured.passed;
                                if (!passed) {
                                  failureStage = 2u;
                                  moveFailureMask =
                                      CoordinatedXyPerformanceReport::moveFailureMask(
                                          measured.observation,
                                          performanceLimits);
                                }
                              }

                              MotionQualificationMath::AxisHomeSample home{};
                              if (passed) {
                                sendProgressStage(
                                    positive
                                        ? "coordinated_xy_performance_x_positive_home"
                                        : "coordinated_xy_performance_x_negative_home");
                                lastXHome = runBoundedAxisHome(
                                    stepperX,
                                    BIT_HOME_X_DONE,
                                    home,
                                    kXEnvelopeMaximumSteps,
                                    true);
                                const uint32_t driftIndex =
                                    caseIndex * 2u + direction;
                                directionalDrift[driftIndex] = lastXHome.passed
                                    ? MotionQualificationMath::absDiffSteps(
                                          home.limitTriggerSteps, 0)
                                    : std::numeric_limits<uint32_t>::max();
                                passed = lastXHome.passed &&
                                    directionalDrift[driftIndex] <=
                                        kHomeDriftLimitSteps;
                                if (!passed) failureStage = 3u;
                              }
                              if (!passed) {
                                failedCase = caseIndex;
                                failedDirection = direction + 1u;
                              }
                            }
                          }

                          const bool aggregatePass =
                              CoordinatedXyPerformanceReport::aggregatePasses(
                                  aggregate,
                                  8u,
                                  168000u,
                                  0u,
                                  168000u,
                                  performanceLimits);
                          passed = passed && aggregatePass;
                          if (!passed && failureStage == 0u) failureStage = 4u;
                          uint32_t activeMax = 0u;
                          for (uint8_t phase = 0u; phase < 3u; ++phase) {
                            if (aggregate.phaseMaxCycles[phase] > activeMax) {
                              activeMax = aggregate.phaseMaxCycles[phase];
                            }
                          }
                          char metrics[224] = {};
                          int written = 0;
                          if (passed) {
                            written = snprintf(
                                metrics,
                                sizeof(metrics),
                                "n=%lu;xe=%lu;ye=%lu;ms=%lu;i2=%lu;i7=%lu;ok=1;"
                                "pu=%lu;am=%lu;tm=%lu;p30=%lu;n30=%lu;p35=%lu;"
                                "n35=%lu;p4l=%lu;n4l=%lu;p40=%lu;n40=%lu;"
                                "an=%lu;al=%lu;to=0",
                                (unsigned long)aggregate.moveCount,
                                (unsigned long)aggregate.emittedXSteps,
                                (unsigned long)aggregate.emittedYSteps,
                                (unsigned long)aggregate.masterSteps,
                                (unsigned long)aggregate.timer2Callbacks,
                                (unsigned long)aggregate.timer7Callbacks,
                                (unsigned long)aggregate.pendingObservations,
                                (unsigned long)activeMax,
                                (unsigned long)aggregate.terminalMaxCycles,
                                (unsigned long)directionalDrift[0],
                                (unsigned long)directionalDrift[1],
                                (unsigned long)directionalDrift[2],
                                (unsigned long)directionalDrift[3],
                                (unsigned long)directionalDrift[4],
                                (unsigned long)directionalDrift[5],
                                (unsigned long)directionalDrift[6],
                                (unsigned long)directionalDrift[7],
                                (unsigned long)kFocusedNormalAcceleration,
                                (unsigned long)kFocusedReducedAcceleration);
                          } else if (failureStage == 3u) {
                            written = snprintf(
                                metrics,
                                sizeof(metrics),
                                "case=%lu;dir=%lu;n=%lu;xe=%lu;ms=%lu;i2=%lu;"
                                "hs=%ld;he=%ld;hg=%lu;hc=%lu;ha=%lu;hp=%u;ho=%u;"
                                "hl=%u;ht=%u;pu=%lu;to=1",
                                (unsigned long)failedCase,
                                (unsigned long)failedDirection,
                                (unsigned long)aggregate.moveCount,
                                (unsigned long)aggregate.emittedXSteps,
                                (unsigned long)aggregate.masterSteps,
                                (unsigned long)aggregate.timer2Callbacks,
                                (long)lastXHome.snapshot.startPositionSteps,
                                (long)lastXHome.snapshot.endPositionSteps,
                                (unsigned long)lastXHome.guardSteps,
                                (unsigned long)lastXHome.snapshot.coarseCommandSteps,
                                (unsigned long)lastXHome.snapshot.coarseAccountedSteps,
                                static_cast<unsigned>(lastXHome.snapshot.phase),
                                static_cast<unsigned>(lastXHome.snapshot.outcome),
                                lastXHome.snapshot.limitSeen ? 1u : 0u,
                                lastXHome.outerTimedOut ? 1u : 0u,
                                (unsigned long)aggregate.pendingObservations);
                          } else {
                            written = snprintf(
                                metrics,
                                sizeof(metrics),
                                "case=%lu;dir=%lu;fs=%lu;fm=%lu;n=%lu;xe=%lu;"
                                "ms=%lu;i2=%lu;pu=%lu;ps=%lu;am=%lu;tm=%lu;"
                                "de=%lu;sg=%lu;wd=%lu;sa=%lu;wl=%lu;cw=%lu;"
                                "sf=%lu;to=1",
                                (unsigned long)failedCase,
                                (unsigned long)failedDirection,
                                (unsigned long)failureStage,
                                (unsigned long)moveFailureMask,
                                (unsigned long)aggregate.moveCount,
                                (unsigned long)aggregate.emittedXSteps,
                                (unsigned long)aggregate.masterSteps,
                                (unsigned long)aggregate.timer2Callbacks,
                                (unsigned long)aggregate.pendingObservations,
                                (unsigned long)aggregate.maxPendingStreak,
                                (unsigned long)activeMax,
                                (unsigned long)aggregate.terminalMaxCycles,
                                (unsigned long)aggregate.durationErrorMaxBasisPoints,
                                (unsigned long)aggregate.statusPeriodMaxMs,
                                (unsigned long)aggregate.statusWatchdogAgeMaxMs,
                                (unsigned long)aggregate.statusAlternationErrors,
                                (unsigned long)aggregate.watchdogLateCount,
                                (unsigned long)aggregate.cycleWraps,
                                (unsigned long)aggregate.saturationFlags);
                          }
                          restoreXyRates();
                          const size_t nameLength = std::min(
                              std::strlen("coord_xy_perf_x_direction"),
                              DiagnosticResultEmitter::kMaxResultNameBytes);
                          const size_t metricBudget =
                              DiagnosticResultEmitter::kResultMetricsFrameBudget -
                              nameLength;
                          const bool metricsFit = written > 0 &&
                              static_cast<size_t>(written) < sizeof(metrics) &&
                              static_cast<size_t>(written) <= metricBudget;
                          comm->setStatusPaused(true);
                          (void)runOne(2070u,
                                       "coord_xy_perf_x_direction",
                                       passed && metricsFit,
                                       metricsFit ? metrics
                                                  : "gate=metrics_overflow;to=1");
                          focusedDirectionResultEmitted = true;
                          return passed && metricsFit;
                        };

                        auto runCameraHomeTransitionQualification = [&]() {
                          static constexpr Pair kCameraPair = {
                              {8916, 30500}, {500, 500}};
                          Aggregate aggregate{};
                          bool passed = true;
                          uint32_t failureStage = 0u;

                          // Keep setup motion on the already-qualified 5 kHz
                          // path. Only the camera-ratio round trip is measured
                          // at 40 kHz, followed immediately by legacy X home.
                          stepperX->setMaxSpeedHz(5000u);
                          stepperY->setMaxSpeedHz(5000u);
                          stepperX->setAccelStepsPerSec2(savedXAcceleration);
                          stepperY->setAccelStepsPerSec2(savedYAcceleration);
                          passed = positionTo(kCameraPair.start);
                          if (!passed) failureStage = 1u;

                          stepperX->setMaxSpeedHz(40000u);
                          stepperY->setMaxSpeedHz(40000u);
                          if (passed) {
                            passed = addPair(aggregate, kCameraPair, 40000u);
                            if (!passed) failureStage = 2u;
                          }

                          const CoordinatedXySnapshot transitionSnapshot =
                              gantry->coordinatedSnapshot();
                          const bool enablesAsserted =
                              stepperX->enableOutputsAssertedForDiagnostics();
                          const bool transitionSafe = passed &&
                              transitionSnapshot.xStepLow &&
                              transitionSnapshot.yStepLow &&
                              !transitionSnapshot.timerOwned &&
                              transitionSnapshot.pendingUpdateCount == 0u &&
                              transitionSnapshot.timer7Interrupts == 0u &&
                              stepperX->getPosition() == kCameraPair.start.x &&
                              stepperY->getPosition() == kCameraPair.start.y;
                          if (passed && (!transitionSafe || !enablesAsserted)) {
                            passed = false;
                            failureStage = 3u;
                          }

                          const bool limitBefore =
                              stepperX->isLimitAssertedForDiagnostics();
                          MotionQualificationMath::AxisHomeSample home{};
                          if (failureStage == 0u) {
                            sendProgressStage(
                                "coordinated_xy_camera_transition_x_home");
                            lastXHome = runBoundedAxisHome(
                                stepperX,
                                BIT_HOME_X_DONE,
                                home,
                                kXEnvelopeMaximumSteps,
                                true);
                            passed = lastXHome.passed;
                            if (!passed) failureStage = 4u;
                          }

                          const StepperIsrInstrumentation::Snapshot homeIsr =
                              stepperX->getLastMoveInstrumentationSnapshot();
                          const bool limitAfter =
                              stepperX->isLimitAssertedForDiagnostics();
                          const bool enablesAfter =
                              stepperX->enableOutputsAssertedForDiagnostics();
                          const uint32_t homeDrift = passed
                              ? MotionQualificationMath::absDiffSteps(
                                    home.limitTriggerSteps, 0)
                              : std::numeric_limits<uint32_t>::max();
                          const bool aggregatePass =
                              CoordinatedXyPerformanceReport::aggregatePasses(
                                  aggregate,
                                  2u,
                                  16832u,
                                  60000u,
                                  60000u,
                                  performanceLimits);
                          const bool homeEvidence = passed &&
                              aggregatePass && !limitBefore && !limitAfter &&
                              enablesAfter && homeDrift <= kHomeDriftLimitSteps &&
                              lastXHome.snapshot.phase ==
                                  Stepper::HomeDiagnosticSnapshot::Phase::FinalBackoff &&
                              lastXHome.snapshot.outcome ==
                                  HomeInterruptionPolicy::Outcome::Succeeded &&
                              lastXHome.snapshot.limitSeen &&
                              lastXHome.snapshot.endPositionSteps ==
                                  static_cast<int32_t>(kExpectedBackoffPosition) &&
                              homeIsr.valid && !homeIsr.active && !homeIsr.aborted &&
                              homeIsr.totalEntries > 0u &&
                              homeIsr.completedPulses == 100u &&
                              homeIsr.pendingObservations == 0u;
                          if (!homeEvidence && failureStage == 0u) {
                            failureStage = 5u;
                          }

                          uint32_t activeMax = 0u;
                          for (uint8_t phase = 0u; phase < 3u; ++phase) {
                            if (aggregate.phaseMaxCycles[phase] > activeMax) {
                              activeMax = aggregate.phaseMaxCycles[phase];
                            }
                          }
                          char metrics[224] = {};
                          const int written = snprintf(
                              metrics,
                              sizeof(metrics),
                              "fs=%lu;n=%lu;xe=%lu;ye=%lu;i2=%lu;i7=%lu;"
                              "pu=%lu;am=%lu;tm=%lu;en=%u;sl=%u;ow=%u;lb=%u;"
                              "hs=%ld;he=%ld;hg=%lu;hc=%lu;ha=%lu;hp=%u;ho=%u;"
                              "hl=%u;la=%u;hi=%lu;hpc=%lu;hpu=%lu;hd=%lu;to=%u",
                              (unsigned long)failureStage,
                              (unsigned long)aggregate.moveCount,
                              (unsigned long)aggregate.emittedXSteps,
                              (unsigned long)aggregate.emittedYSteps,
                              (unsigned long)aggregate.timer2Callbacks,
                              (unsigned long)aggregate.timer7Callbacks,
                              (unsigned long)aggregate.pendingObservations,
                              (unsigned long)activeMax,
                              (unsigned long)aggregate.terminalMaxCycles,
                              (enablesAsserted && enablesAfter) ? 1u : 0u,
                              (transitionSnapshot.xStepLow &&
                               transitionSnapshot.yStepLow) ? 1u : 0u,
                              transitionSnapshot.timerOwned ? 1u : 0u,
                              limitBefore ? 1u : 0u,
                              (long)lastXHome.snapshot.startPositionSteps,
                              (long)lastXHome.snapshot.endPositionSteps,
                              (unsigned long)lastXHome.guardSteps,
                              (unsigned long)lastXHome.snapshot.coarseCommandSteps,
                              (unsigned long)lastXHome.snapshot.coarseAccountedSteps,
                              static_cast<unsigned>(lastXHome.snapshot.phase),
                              static_cast<unsigned>(lastXHome.snapshot.outcome),
                              lastXHome.snapshot.limitSeen ? 1u : 0u,
                              limitAfter ? 1u : 0u,
                              (unsigned long)homeIsr.totalEntries,
                              (unsigned long)homeIsr.completedPulses,
                              (unsigned long)homeIsr.pendingObservations,
                              (unsigned long)homeDrift,
                              homeEvidence ? 0u : 1u);
                          restoreXyRates();
                          const size_t nameLength = std::min(
                              std::strlen("coord_xy_camera_home_transition"),
                              DiagnosticResultEmitter::kMaxResultNameBytes);
                          const size_t metricBudget =
                              DiagnosticResultEmitter::kResultMetricsFrameBudget -
                              nameLength;
                          const bool metricsFit = written > 0 &&
                              static_cast<size_t>(written) < sizeof(metrics) &&
                              static_cast<size_t>(written) <= metricBudget;
                          const bool resultPass = homeEvidence && metricsFit;
                          comm->setStatusPaused(true);
                          (void)runOne(2071u,
                                       "coord_xy_camera_home_transition",
                                       resultPass,
                                       metricsFit ? metrics
                                                  : "gate=metrics_overflow;to=1");
                          transitionResultEmitted = true;
                          return resultPass;
                        };

                        auto emitIrqPathEvidence = [&](const Aggregate& aggregate,
                                                       uint16_t testId,
                                                       const char* name,
                                                       bool requireNoPending) {
                          char metrics[192] = {};
                          const int written = snprintf(
                              metrics,
                              sizeof(metrics),
                              "i2=%lu;s=%lu;mi=%lu;ph=%lu;pa=%lu;fm=%lu;fa=%lu;"
                              "ax=%lu;tf=%lu;pp=%lu;pf=%lu;pu=%lu;ps=%lu;sf=%lu;to=0",
                              (unsigned long)aggregate.timer2Callbacks,
                              (unsigned long)aggregate.irqPathSamples,
                              (unsigned long)aggregate.irqPathMissing,
                              (unsigned long)aggregate.preHandlerMaxCycles,
                              (unsigned long)CoordinatedXyPerformanceReport::preHandlerMeanCycles(aggregate),
                              (unsigned long)aggregate.fullIrqMaxCycles,
                              (unsigned long)CoordinatedXyPerformanceReport::fullIrqMeanCycles(aggregate),
                              (unsigned long)aggregate.activeFullIrqMaxCycles,
                              (unsigned long)aggregate.terminalFullIrqMaxCycles,
                              (unsigned long)aggregate.pendingPreHandlerMaxCycles,
                              (unsigned long)aggregate.pendingFullIrqMaxCycles,
                              (unsigned long)aggregate.pendingObservations,
                              (unsigned long)aggregate.maxPendingStreak,
                              (unsigned long)aggregate.saturationFlags);
                          const bool evidenceComplete =
                              aggregate.timer2Callbacks > 0u &&
                              aggregate.irqPathSamples == aggregate.timer2Callbacks &&
                              aggregate.irqPathMissing == 0u &&
                              aggregate.preHandlerMaxCycles > 0u &&
                              aggregate.fullIrqMaxCycles > 0u &&
                              aggregate.activeFullIrqMaxCycles > 0u &&
                              aggregate.terminalFullIrqMaxCycles > 0u &&
                              (!requireNoPending ||
                               (aggregate.pendingObservations == 0u &&
                                aggregate.maxPendingStreak == 0u)) &&
                              aggregate.saturationFlags == 0u;
                          const size_t nameLength = std::min(
                              std::strlen(name),
                              DiagnosticResultEmitter::kMaxResultNameBytes);
                          const size_t metricBudget =
                              DiagnosticResultEmitter::kResultMetricsFrameBudget -
                              nameLength;
                          const bool metricsFit = written > 0 &&
                              static_cast<size_t>(written) < sizeof(metrics) &&
                              static_cast<size_t>(written) <= metricBudget;
                          (void)runOne(testId,
                                       name,
                                       evidenceComplete && metricsFit,
                                       metricsFit ? metrics
                                                  : "gate=metrics_overflow;to=1");
                          return evidenceComplete && metricsFit;
                        };

                        auto emitEntryLatenessEvidence =
                            [&](const Aggregate& aggregate,
                                uint16_t testId,
                                const char* name,
                                bool requireDeadlineMargin) {
                          char metrics[224] = {};
                          const unsigned statusSyncMode = static_cast<unsigned>(
                              Comm::getStatusMetricsSyncMode());
                          const uint32_t lockFailures =
                              Comm::getStatusMetricsLockFailureCount();
                          int written = 0;
                          if (requireDeadlineMargin) {
                            written = snprintf(
                                metrics,
                                sizeof(metrics),
                                "i2=%lu;s=%lu;mi=%lu;cm=%lu;ca=%lu;pm=%lu;"
                                "lc=%lu;dm=%lu;ds=%lu;di=%lu;md=%lu;sl=%lu;"
                                "rm=%u;dc=%lu;ci=%lu;ns=%lu;rc=%lu;rp=%lu;rd=%lu;sm=%u;lf=%lu;"
                                "sf=%lu;to=%lu;fv=%u;tr=%u;"
                                "la=%lu;ra=%lu;hm=%lu",
                                (unsigned long)aggregate.timer2Callbacks,
                                (unsigned long)aggregate.entryTimerSamples,
                                (unsigned long)aggregate.entryTimerMissing,
                                (unsigned long)aggregate.entryTimerCountMax,
                                (unsigned long)CoordinatedXyPerformanceReport::entryTimerMeanTicks(aggregate),
                                (unsigned long)aggregate.pendingEntryTimerCountMax,
                                (unsigned long)aggregate.lateEntryCount,
                                (unsigned long)aggregate.entryScheduleOverrunMaxCycles,
                                (unsigned long)aggregate.deadlineSamples,
                                (unsigned long)aggregate.deadlineMissing,
                                (unsigned long)aggregate.deadlineMisses,
                                (unsigned long)aggregate.deadlineSlackMinTicks,
                                static_cast<unsigned>(
                                    aggregate.timerScheduleMode),
                                (unsigned long)
                                    aggregate.conditionalDecisionCount,
                                (unsigned long)
                                    aggregate.conditionalDecisionMissingCount,
                                (unsigned long)
                                    aggregate.conditionalNonRearmSlackMinTicks,
                                (unsigned long)aggregate.timerRearmCount,
                                (unsigned long)aggregate.timerRearmPendingCount,
                                (unsigned long)aggregate.timerRearmDelayMaxCycles,
                                statusSyncMode,
                                (unsigned long)lockFailures,
                                (unsigned long)aggregate.saturationFlags,
                                (unsigned long)aggregate.timeoutCount,
                                firstMoveFailure.valid ? 1u : 0u,
                                static_cast<unsigned>(
                                    firstMoveFailure.terminalReason),
                                (unsigned long)
                                    firstMoveFailure.limitAbortRequestCount,
                                (unsigned long)firstMoveFailure.rawLimitAbortCount,
                                (unsigned long)firstMoveFailure.failureMask);
                          } else {
                            written = snprintf(
                                metrics,
                                sizeof(metrics),
                                "i2=%lu;s=%lu;mi=%lu;cm=%lu;ca=%lu;pm=%lu;"
                                "lc=%lu;dm=%lu;sm=%u;lf=%lu;sf=%lu;to=%lu;"
                                "fv=%u;tr=%u;la=%lu;ra=%lu",
                                (unsigned long)aggregate.timer2Callbacks,
                                (unsigned long)aggregate.entryTimerSamples,
                                (unsigned long)aggregate.entryTimerMissing,
                                (unsigned long)aggregate.entryTimerCountMax,
                                (unsigned long)CoordinatedXyPerformanceReport::entryTimerMeanTicks(aggregate),
                                (unsigned long)aggregate.pendingEntryTimerCountMax,
                                (unsigned long)aggregate.lateEntryCount,
                                (unsigned long)aggregate.entryScheduleOverrunMaxCycles,
                                statusSyncMode,
                                (unsigned long)lockFailures,
                                (unsigned long)aggregate.saturationFlags,
                                (unsigned long)aggregate.timeoutCount,
                                firstMoveFailure.valid ? 1u : 0u,
                                static_cast<unsigned>(
                                    firstMoveFailure.terminalReason),
                                (unsigned long)
                                    firstMoveFailure.limitAbortRequestCount,
                                (unsigned long)firstMoveFailure.rawLimitAbortCount);
                          }
                          const bool rearmSchedule =
                              aggregate.timerScheduleMode ==
                                  CoordinatedXyTimerSchedulePolicy::Mode::
                                      RearmFromActualEdge;
                          const bool conditionalSchedule =
                              aggregate.timerScheduleMode ==
                                  CoordinatedXyTimerSchedulePolicy::Mode::
                                      ConditionalLateRearm;
                          const bool scheduleEvidenceComplete = rearmSchedule
                              ? (aggregate.interruptsPerMasterStep == 2u &&
                                 aggregate.timer2Callbacks >=
                                     aggregate.moveCount &&
                                 aggregate.timerRearmCount ==
                                     (aggregate.timer2Callbacks -
                                      aggregate.moveCount) &&
                                 aggregate.timerRearmPendingCount == 0u &&
                                 aggregate.timerRearmDelayMaxCycles > 0u)
                              : conditionalSchedule
                              ? (aggregate.interruptsPerMasterStep == 2u &&
                                 aggregate.timer2Callbacks >=
                                     aggregate.moveCount &&
                                 aggregate.conditionalDecisionCount ==
                                     (aggregate.timer2Callbacks -
                                      aggregate.moveCount) &&
                                 aggregate.conditionalDecisionMissingCount ==
                                     0u &&
                                 aggregate.timerRearmPendingCount == 0u &&
                                 ((aggregate.timerRearmCount == 0u &&
                                   aggregate.timerRearmDelayMaxCycles == 0u) ||
                                  (aggregate.timerRearmCount > 0u &&
                                   aggregate.timerRearmDelayMaxCycles > 0u)) &&
                                 aggregate.timerScheduleSaturationFlags == 0u)
                              : (aggregate.timerRearmCount == 0u &&
                                 aggregate.timerRearmPendingCount == 0u &&
                                 aggregate.timerRearmDelayMaxCycles == 0u);
                          const bool evidenceComplete =
                              aggregate.timer2Callbacks > 0u &&
                              aggregate.entryTimerSamples ==
                                  aggregate.timer2Callbacks &&
                              aggregate.entryTimerMissing == 0u &&
                              lockFailures == 0u &&
                              (!requireDeadlineMargin ||
                               (aggregate.pendingObservations == 0u &&
                                aggregate.maxPendingStreak == 0u &&
                                (rearmSchedule || conditionalSchedule ||
                                  aggregate.lateEntryCount == 0u) &&
                                aggregate.deadlineSamples ==
                                    (aggregate.timer2Callbacks -
                                     aggregate.moveCount) &&
                                aggregate.deadlineMissing == 0u &&
                                aggregate.deadlineMisses == 0u &&
                                aggregate.deadlineSlackMinTicks >= 450u &&
                                scheduleEvidenceComplete &&
                                aggregate.exactAndSafe &&
                                !firstMoveFailure.valid)) &&
                              aggregate.saturationFlags == 0u &&
                              aggregate.timeoutCount == 0u;
                          const size_t nameLength = std::min(
                              std::strlen(name),
                              DiagnosticResultEmitter::kMaxResultNameBytes);
                          const size_t metricBudget =
                              DiagnosticResultEmitter::kResultMetricsFrameBudget -
                              nameLength;
                          const bool metricsFit = written > 0 &&
                              static_cast<size_t>(written) < sizeof(metrics) &&
                              static_cast<size_t>(written) <= metricBudget;
                          (void)runOne(testId,
                                       name,
                                       evidenceComplete && metricsFit,
                                       metricsFit ? metrics
                                                  : "gate=metrics_overflow;to=1");
                          return evidenceComplete && metricsFit;
                        };

                        auto emitConditionalRearmEvidence =
                            [&](const Aggregate& aggregate) {
                          char metrics[192] = {};
                          const int written = snprintf(
                              metrics,
                              sizeof(metrics),
                              "rm=%u;rg=%lu;it=%lu;dc=%lu;mi=%lu;rc=%lu;"
                              "rp=%lu;rd=%lu;ic=%lu;ix=%lu;ir=%lu;im=%lu;"
                              "ns=%lu;wm=%lu;sf=%lu;to=%lu",
                              static_cast<unsigned>(aggregate.timerScheduleMode),
                              (unsigned long)CoordinatedXyTimerSchedulePolicy::
                                  kConditionalGuardTicks,
                              (unsigned long)CoordinatedXyTimerSchedulePolicy::
                                  kInjectionTargetSlackTicks,
                              (unsigned long)aggregate.conditionalDecisionCount,
                              (unsigned long)
                                  aggregate.conditionalDecisionMissingCount,
                              (unsigned long)aggregate.timerRearmCount,
                              (unsigned long)aggregate.timerRearmPendingCount,
                              (unsigned long)aggregate.timerRearmDelayMaxCycles,
                              (unsigned long)aggregate.lateInjectionCount,
                              (unsigned long)aggregate.lateInjectionFailureCount,
                              (unsigned long)aggregate.lateInjectionRearmCount,
                              (unsigned long)
                                  aggregate.lateInjectionDecisionSlackMaxTicks,
                              (unsigned long)
                                  aggregate.conditionalNonRearmSlackMinTicks,
                              (unsigned long)aggregate.lateInjectionWaitMaxCycles,
                              (unsigned long)aggregate.saturationFlags,
                              (unsigned long)aggregate.timeoutCount);
                          static constexpr uint32_t kExpectedDecisions = 219990u;
                          static constexpr uint32_t kExpectedInjections = 10u;
                          const bool evidenceComplete =
                              aggregate.timerScheduleMode ==
                                  CoordinatedXyTimerSchedulePolicy::Mode::
                                      ConditionalLateRearm &&
                              aggregate.conditionalDecisionCount ==
                                  kExpectedDecisions &&
                              aggregate.conditionalDecisionMissingCount == 0u &&
                              aggregate.timerRearmCount >=
                                  kExpectedInjections &&
                              aggregate.timerRearmPendingCount == 0u &&
                              aggregate.timerRearmDelayMaxCycles > 0u &&
                              aggregate.lateInjectionCount ==
                                  kExpectedInjections &&
                              aggregate.lateInjectionFailureCount == 0u &&
                              aggregate.lateInjectionRearmCount ==
                                  kExpectedInjections &&
                              aggregate.lateInjectionDecisionSlackMaxTicks <=
                                  CoordinatedXyTimerSchedulePolicy::
                                      kConditionalGuardTicks &&
                              aggregate.conditionalNonRearmSlackMinTicks >
                                  CoordinatedXyTimerSchedulePolicy::
                                      kConditionalGuardTicks &&
                              aggregate.lateInjectionWaitMaxCycles > 0u &&
                              aggregate.lateInjectionWaitMaxCycles <=
                                  CoordinatedXyTimerSchedulePolicy::
                                      kInjectionMaxCoreCycles &&
                              aggregate.saturationFlags == 0u &&
                              aggregate.timeoutCount == 0u &&
                              aggregate.exactAndSafe &&
                              !firstMoveFailure.valid;
                          const size_t nameLength = std::min(
                              std::strlen("coord_xy_conditional_rearm"),
                              DiagnosticResultEmitter::kMaxResultNameBytes);
                          const size_t metricBudget =
                              DiagnosticResultEmitter::kResultMetricsFrameBudget -
                              nameLength;
                          const bool metricsFit = written > 0 &&
                              static_cast<size_t>(written) < sizeof(metrics) &&
                              static_cast<size_t>(written) <= metricBudget;
                          (void)runOne(
                              2086u,
                              "coord_xy_conditional_rearm",
                              evidenceComplete && metricsFit,
                              metricsFit ? metrics
                                         : "gate=metrics_overflow;to=1");
                          return evidenceComplete && metricsFit;
                        };

                        auto emitCompleteStepEvidence =
                            [&](const Aggregate& aggregate) {
                          static constexpr uint32_t kExpectedCallbacks = 220000u;
                          static constexpr uint32_t kMinimumDeadlineSlackTicks =
                              500u;
                          char metrics[224] = {};
                          const unsigned mode =
                              static_cast<unsigned>(aggregate.executionMode);
                          const int written = snprintf(
                              metrics,
                              sizeof(metrics),
                              "em=%u;ip=%lu;i2=%lu;pc=%lu;pn=%lu;px=%lu;"
                              "pe=%lu;ds=%lu;mi=%lu;md=%lu;sl=%lu;pu=%lu;"
                              "ok=%u;sf=%lu;to=%lu",
                              mode,
                              (unsigned long)aggregate.interruptsPerMasterStep,
                              (unsigned long)aggregate.timer2Callbacks,
                              (unsigned long)aggregate.completeStepPulseSamples,
                              (unsigned long)aggregate.completeStepPulseMinCycles,
                              (unsigned long)aggregate.completeStepPulseMaxCycles,
                              (unsigned long)aggregate.minimumPulseCoreCycles,
                              (unsigned long)aggregate.deadlineSamples,
                              (unsigned long)aggregate.deadlineMissing,
                              (unsigned long)aggregate.deadlineMisses,
                              (unsigned long)aggregate.deadlineSlackMinTicks,
                              (unsigned long)aggregate.pendingObservations,
                              aggregate.exactAndSafe ? 1u : 0u,
                              (unsigned long)aggregate.saturationFlags,
                              (unsigned long)aggregate.timeoutCount);
                          const bool evidenceComplete =
                              aggregate.executionMode ==
                                  CoordinatedXyExecutor::ExecutionMode::CompleteStep &&
                              aggregate.interruptsPerMasterStep == 1u &&
                              aggregate.timer2Callbacks == kExpectedCallbacks &&
                              aggregate.completeStepPulseSamples ==
                                  kExpectedCallbacks &&
                              aggregate.minimumPulseCoreCycles == 360u &&
                              aggregate.completeStepPulseMinCycles >=
                                  aggregate.minimumPulseCoreCycles &&
                              aggregate.deadlineSamples == kExpectedCallbacks &&
                              aggregate.deadlineMissing == 0u &&
                              aggregate.deadlineMisses == 0u &&
                              aggregate.deadlineSlackMinTicks >=
                                  kMinimumDeadlineSlackTicks &&
                              aggregate.pendingObservations == 0u &&
                              aggregate.saturationFlags == 0u &&
                              aggregate.timeoutCount == 0u &&
                              aggregate.exactAndSafe;
                          const size_t nameLength = std::min(
                              std::strlen("coord_xy_single_irq_pulse"),
                              DiagnosticResultEmitter::kMaxResultNameBytes);
                          const size_t metricBudget =
                              DiagnosticResultEmitter::kResultMetricsFrameBudget -
                              nameLength;
                          const bool metricsFit = written > 0 &&
                              static_cast<size_t>(written) < sizeof(metrics) &&
                              static_cast<size_t>(written) <= metricBudget;
                          (void)runOne(2074u,
                                       "coord_xy_single_irq_pulse",
                                       evidenceComplete && metricsFit,
                                       metricsFit ? metrics
                                                  : "gate=metrics_overflow;to=1");
                          return evidenceComplete && metricsFit;
                        };

                        if (runCoordinatedXyTransitionSuite) {
                          const bool transitionPass =
                              runCameraHomeTransitionQualification();
                          if (!transitionPass) {
                            failRemaining(2072u, "camera_home_transition");
                          } else {
                            Gantry::cancelXYZMotors();
                            closePressurePaths();
                            restoreXyRates();
                          }
                          return finishSelfTestNow();
                        }

                        if (runCoordinatedXyDirectionSuite) {
                          const bool focusedPass =
                              runFocusedXDirectionQualification();
                          if (!focusedPass) {
                            failRemaining(2071u, "x_direction");
                          } else {
                            Gantry::cancelXYZMotors();
                            closePressurePaths();
                            restoreXyRates();
                          }
                          return finishSelfTestNow();
                        }

                        const uint32_t firstTier =
                            runCoordinatedXyFocusedGeometrySuite ? 4u : 0u;
                        for (uint32_t tier = firstTier; tier < 5u; ++tier) {
                          if (tier == 4u &&
                              !runCoordinatedXyFocusedGeometrySuite &&
                              !runFocusedXDirectionQualification()) {
                            failRemaining(2064u, "x_direction");
                            return finishSelfTestNow();
                          }
                          const uint32_t rateHz =
                              runCoordinatedXyLogicalMres3Suite
                                  ? 40000u : kRatesHz[tier];
                          const float rowAccelerationX =
                              runCoordinatedXyLogicalMres3Suite
                                  ? 140000.0f : savedXAcceleration;
                          const float rowAccelerationY =
                              runCoordinatedXyLogicalMres3Suite
                                  ? 140000.0f : savedYAcceleration;
                          stepperX->setMaxSpeedHz(rateHz);
                          stepperY->setMaxSpeedHz(rateHz);
                          stepperX->setAccelStepsPerSec2(rowAccelerationX);
                          stepperY->setAccelStepsPerSec2(rowAccelerationY);
                          lastXHome = BoundedHomeResult{};
                          lastYHome = BoundedHomeResult{};
                          const int32_t pPositionBefore = stepperP != nullptr
                              ? stepperP->getPosition() : 0;
                          const int32_t rPositionBefore = stepperR != nullptr
                              ? stepperR->getPosition() : 0;
                          Aggregate aggregate{};
                          bool rowPass = true;
                          const Pair* geometry = kGeometryPairs;
                          for (uint32_t pairIndex = 0u; pairIndex < 5u;
                               ++pairIndex) {
                            const Pair& pair = geometry[pairIndex];
                            if (!addPair(aggregate, pair, rateHz)) {
                              rowPass = false;
                              break;
                            }
                          }
                          uint32_t xDrift = std::numeric_limits<uint32_t>::max();
                          uint32_t yDrift = std::numeric_limits<uint32_t>::max();
                          if (rowPass) {
                            rowPass = homeAndMeasureDrift(
                                xDrift,
                                yDrift,
                                "coordinated_xy_performance_post_tier_x_home",
                                "coordinated_xy_performance_post_tier_y_home");
                            if (!rowPass) {
                              CoordinatedXyPerformanceReport::captureFirstFailure(
                                  firstMoveFailure,
                                  false,
                                  CoordinatedXyExecutor::TerminalReason::None,
                                  0u,
                                  0u,
                                  CoordinatedXyPerformanceReport::
                                      kMoveFailureTerminalReason);
                            }
                          }
                          if (runCoordinatedXyLogicalMres3Suite &&
                              ((stepperP != nullptr &&
                                stepperP->getPosition() != pPositionBefore) ||
                               (stepperR != nullptr &&
                                stepperR->getPosition() != rPositionBefore))) {
                            rowPass = false;
                            CoordinatedXyPerformanceReport::captureFirstFailure(
                                firstMoveFailure,
                                false,
                                CoordinatedXyExecutor::TerminalReason::None,
                                0u,
                                0u,
                                CoordinatedXyPerformanceReport::
                                    kMoveFailureEndpoint);
                          }
                          const TestDescriptor focusedTest =
                              runCoordinatedXyLogicalMres3Suite
                                  ? TestDescriptor{
                                        runCoordinatedXyProductionMres3Suite
                                            ? 2087u : 2080u,
                                        runCoordinatedXyProductionMres3Suite
                                            ? "coord_xy_prod_mres3_motion"
                                            : "coord_xy_mres3_20khz_motion"}
                                  : kTests[tier];
                          const uint32_t evidenceRateHz =
                              runCoordinatedXyLogicalMres3Suite
                                  ? MotionUnitScale::toNativeRate(rateHz)
                                  : rateHz;
                          const bool emitted = emitAggregate(
                              focusedTest,
                              evidenceRateHz,
                              aggregate,
                              10u,
                              runCoordinatedXyLogicalMres3Suite ? 53416u : 106832u,
                              runCoordinatedXyLogicalMres3Suite ? 90000u : 180000u,
                              runCoordinatedXyLogicalMres3Suite ? 110000u : 220000u,
                              xDrift,
                              yDrift,
                              rowPass);
                          if (runCoordinatedXyFocusedGeometrySuite) {
                            (void)emitIrqPathEvidence(
                                aggregate,
                                runCoordinatedXyLogicalMres3Suite
                                    ? (runCoordinatedXyProductionMres3Suite
                                           ? 2088u : 2081u)
                                    : 2072u,
                                runCoordinatedXyLogicalMres3Suite
                                    ? (runCoordinatedXyProductionMres3Suite
                                           ? "coord_xy_prod_mres3_irq_path"
                                           : "coord_xy_mres3_20khz_irq_path")
                                    : "coord_xy_40khz_irq_path",
                                runCoordinatedXyLogicalMres3Suite);
                            (void)emitEntryLatenessEvidence(
                                aggregate,
                                runCoordinatedXyLogicalMres3Suite
                                    ? (runCoordinatedXyProductionMres3Suite
                                           ? 2089u : 2082u)
                                    : 2073u,
                                runCoordinatedXyLogicalMres3Suite
                                    ? (runCoordinatedXyProductionMres3Suite
                                           ? "coord_xy_prod_conditional_rearm"
                                           : "coord_xy_mres3_entry_margin")
                                    : "coord_xy_40khz_entry_lateness",
                                runCoordinatedXyLogicalMres3Suite);
                            if (runCoordinatedXyMres3ConditionalRearmSuite) {
                              (void)emitConditionalRearmEvidence(aggregate);
                            }
                            if (runCoordinatedXySingleIrqSuite) {
                              (void)emitCompleteStepEvidence(aggregate);
                            }
                            if (runCoordinatedXyLogicalMres3Suite) {
                              (void)emitMres3Configuration();
                            }
                          }
                          if (!emitted) {
                            if (runCoordinatedXyFocusedGeometrySuite) {
                              Gantry::cancelXYZMotors();
                              closePressurePaths();
                              restoreXyRates();
                              return finishSelfTestNow();
                            }
                            failRemaining(static_cast<uint16_t>(2061u + tier),
                                          "rate_tier");
                            return finishSelfTestNow();
                          }
                        }

                        if (runCoordinatedXyFocusedGeometrySuite) {
                          Gantry::cancelXYZMotors();
                          closePressurePaths();
                          restoreXyRates();
                          return finishSelfTestNow();
                        }

                        stepperX->setMaxSpeedHz(40000u);
                        stepperY->setMaxSpeedHz(40000u);
                        Aggregate m1Aggregate{};
                        static constexpr struct {
                          Point start;
                          Point finish;
                          uint32_t selectedRateHz;
                        } kM1Moves[] = {
                            {{2000, 2000}, {12000, 2000}, 40000u},
                            {{12000, 2000}, {12000, 12000}, 40000u},
                            {{12000, 12000}, {22000, 22000}, 40000u},
                            {{8916, 30500}, {500, 500}, 40000u},
                            {{2000, 2000}, {3000, 2000}, 11832u},
                        };
                        bool m1Pass = true;
                        for (const auto& move : kM1Moves) {
                          if (!positionTo(move.start)) {
                            m1Pass = false;
                            break;
                          }
                          MoveResult result = observeCompletedMove(
                              move.start,
                              move.finish,
                              move.selectedRateHz,
                              false,
                              nullptr,
                              nullptr,
                              nullptr);
                          CoordinatedXyPerformanceReport::addMove(
                              m1Aggregate, result.observation, performanceLimits);
                          if (!result.passed) {
                            m1Pass = false;
                            break;
                          }
                        }
                        if (!emitAggregate(kTests[5],
                                           40000u,
                                           m1Aggregate,
                                           5u,
                                           29416u,
                                           50000u,
                                           61000u,
                                           0u,
                                           0u,
                                           m1Pass)) {
                          failRemaining(2066u, "m1_comparison");
                          return finishSelfTestNow();
                        }

                        Aggregate rasterAggregate{};
                        bool rasterPass = true;
                        static constexpr Pair kAsymmetricPairs[] = {
                            {{5000, 5000}, {15000, 25000}},
                            {{5000, 5000}, {10000, 25000}},
                            {{5000, 5000}, {25000, 10000}},
                        };
                        for (const Pair& pair : kAsymmetricPairs) {
                          if (!addPair(rasterAggregate, pair, 40000u)) {
                            rasterPass = false;
                            break;
                          }
                        }
                        const Point plateStart{43000, 13000};
                        if (rasterPass) rasterPass = positionTo(plateStart);
                        if (rasterPass) {
                          rasterPass = moveAxisToWithTimeout(stepperZ,
                                                             BIT_STEPPER3_DONE,
                                                             91500,
                                                             30000u,
                                                             kZMoveTimeoutMs);
                        }
                        Point rasterCurrent = plateStart;
                        if (rasterPass) {
                          sendProgressStage("coordinated_xy_performance_raster");
                          for (uint32_t row = 0u; row < 16u && rasterPass; ++row) {
                            const int32_t x = MotionQualificationMath::interpolateEndpoint(
                                43000, 33000, row, 16u);
                            for (uint32_t colIndex = 0u;
                                 colIndex < 24u && rasterPass;
                                 ++colIndex) {
                              const uint32_t col = (row & 1u) == 0u
                                  ? colIndex
                                  : 23u - colIndex;
                              const Point target{
                                  x,
                                  MotionQualificationMath::interpolateEndpoint(
                                      13000, 30000, col, 24u)};
                              if (target.x == rasterCurrent.x &&
                                  target.y == rasterCurrent.y) continue;
                              MoveResult move = observeCompletedMove(
                                  rasterCurrent,
                                  target,
                                  0u,
                                  false,
                                  nullptr,
                                  nullptr,
                                  nullptr);
                              CoordinatedXyPerformanceReport::addMove(
                                  rasterAggregate,
                                  move.observation,
                                  performanceLimits);
                              rasterPass = move.passed;
                              rasterCurrent = target;
                            }
                          }
                        }
                        if (rasterPass) {
                          MoveResult returned = observeCompletedMove(
                              rasterCurrent,
                              plateStart,
                              40000u,
                              false,
                              nullptr,
                              nullptr,
                              nullptr);
                          CoordinatedXyPerformanceReport::addMove(
                              rasterAggregate,
                              returned.observation,
                              performanceLimits);
                          rasterPass = returned.passed;
                        }
                        MotionQualificationMath::AxisHomeSample zAfterRaster{};
                        if (!_selfTestAbortRequested &&
                            !runAxisHomeDiagnosticAttempt(stepperZ,
                                                          BIT_HOME_Z_DONE,
                                                          zAfterRaster,
                                                          kZHomeFastHz,
                                                          kZHomeSlowHz,
                                                          kHomeBackoffSteps,
                                                          kHomeTimeoutMs)) {
                          rasterPass = false;
                        }
                        uint32_t rasterXDrift =
                            std::numeric_limits<uint32_t>::max();
                        uint32_t rasterYDrift =
                            std::numeric_limits<uint32_t>::max();
                        if (rasterPass) {
                          rasterPass = homeAndMeasureDrift(
                              rasterXDrift,
                              rasterYDrift,
                              "coordinated_xy_performance_post_raster_x_home",
                              "coordinated_xy_performance_post_raster_y_home");
                        }
                        if (!emitAggregate(kTests[6],
                                           40000u,
                                           rasterAggregate,
                                           390u,
                                           90000u,
                                           362000u,
                                           412000u,
                                           rasterXDrift,
                                           rasterYDrift,
                                           rasterPass)) {
                          failRemaining(2067u, "raster");
                          return finishSelfTestNow();
                        }

                        Aggregate cameraAggregate{};
                        bool cameraPass = positionTo(kGeometryPairs[4].start);
                        for (uint32_t cycle = 0u; cycle < 5u && cameraPass; ++cycle) {
                          cameraPass = addPair(
                              cameraAggregate, kGeometryPairs[4], 40000u);
                        }
                        if (!emitAggregate(kTests[7],
                                           40000u,
                                           cameraAggregate,
                                           10u,
                                           84160u,
                                           300000u,
                                           300000u,
                                           0u,
                                           0u,
                                           cameraPass)) {
                          failRemaining(2068u, "camera_repeat");
                          return finishSelfTestNow();
                        }

                        Aggregate pressureAggregate{};
                        bool pressurePass = pressureSensor != nullptr &&
                            pressureSensor->numPorts() > 1u &&
                            stepperP != nullptr && stepperR != nullptr;
                        auto homePressureRegulators = [&]() {
                          closePressurePaths();
                          xEventGroupClearBits(
                              _doneEvents, BIT_HOME_P_DONE | BIT_HOME_R_DONE);
                          startRegHomeAsync(&PressureRegulator::regP(),
                                            kRegHomeFastHz,
                                            kRegHomeSlowHz,
                                            kHomeBackoffSteps,
                                            BIT_HOME_P_DONE);
#if (LC_PRESSURE_PORTS > 1)
                          startRegHomeAsync(&PressureRegulator::regR(),
                                            kRegHomeFastHz,
                                            kRegHomeSlowHz,
                                            kHomeBackoffSteps,
                                            BIT_HOME_R_DONE);
#endif
                          const bool done = waitBitsWithTimeout(
                              BIT_HOME_P_DONE | BIT_HOME_R_DONE,
                              kHomeTimeoutMs);
                          return done && stepperP != nullptr && stepperR != nullptr &&
                              stepperP->getLastHomeDiagnosticSnapshot().success &&
                              stepperR->getLastHomeDiagnosticSnapshot().success;
                        };
                        if (pressurePass) {
                          sendProgressStage(
                              "coordinated_xy_performance_pressure_home");
                          pressurePass = homePressureRegulators();
                        }
                        PressureRegulator& regP = PressureRegulator::regP();
                        PressureRegulator& regR = PressureRegulator::regR();
                        PressureWaitResult pOne{};
                        PressureWaitResult rOne{};
                        PressureWaitResult pFinal{};
                        PressureWaitResult rFinal{};
                        uint32_t rejectStartP = 0u;
                        uint32_t rejectStartR = 0u;
                        int32_t pGuardOrigin = 0;
                        int32_t rGuardOrigin = 0;
                        bool guardTripped = false;
                        bool pForwardMoved = false;
                        bool rForwardMoved = false;
                        bool pReverseMoved = false;
                        bool rReverseMoved = false;
                        bool activeForward = false;
                        bool activeReverse = false;
                        bool pTwoAccepted = false;
                        bool rTwoAccepted = false;
                        MoveResult pressureForward{};
                        MoveResult pressureReverse{};
                        if (pressurePass) {
                          regP.closeValve();
                          regR.closeValve();
                          regP.start();
                          regR.start();
                          regP.setTargetSafe(kPressure1Raw);
                          regR.setTargetSafe(kPressure1Raw);
                          pOne = waitPressureReady(
                              regP, 0u, kPressure1Raw, true, kPressureSettleTimeoutMs);
                          rOne = waitPressureReady(
                              regR, 1u, kPressure1Raw, true, kPressureSettleTimeoutMs);
                          pressurePass = pOne.accepted && rOne.accepted &&
                              regP.getTarget() == kPressure1Raw &&
                              regR.getTarget() == kPressure1Raw;
                        }
                        const Point pressureStart = kGeometryPairs[4].start;
                        const Point pressureFinish = kGeometryPairs[4].finish;
                        if (pressurePass) pressurePass = positionTo(pressureStart);
                        PressureSensor::ControlSample pCounterStart{};
                        PressureSensor::ControlSample rCounterStart{};
                        if (pressurePass) {
                          pCounterStart = pressureSensor->getControlSample(0u);
                          rCounterStart = pressureSensor->getControlSample(1u);
                          rejectStartP = pCounterStart.rejectCount;
                          rejectStartR = rCounterStart.rejectCount;
                          pGuardOrigin = stepperP->getPosition();
                          rGuardOrigin = stepperR->getPosition();
                          regP.setTargetSafe(kPressure2Raw);
                          regR.setTargetSafe(kPressure2Raw);
                          pTwoAccepted = regP.getTarget() == kPressure2Raw;
                          rTwoAccepted = regR.getTarget() == kPressure2Raw;
                          activeForward = regP.isActive() && regR.isActive();
                          pressureForward = observeCompletedMove(
                              pressureStart,
                              pressureFinish,
                              40000u,
                              true,
                              &pForwardMoved,
                              &rForwardMoved,
                              &guardTripped);
                          const int32_t pNow = stepperP->getPosition();
                          const int32_t rNow = stepperR->getPosition();
                          guardTripped =
                              absDiff32(pNow, 0) > kPressureGuardAbsSteps ||
                              absDiff32(rNow, 0) > kPressureGuardAbsSteps ||
                              absDiff32(pNow, pGuardOrigin) > kPressureGuardDeltaSteps ||
                              absDiff32(rNow, rGuardOrigin) > kPressureGuardDeltaSteps;
                          pressurePass = pressureForward.passed && activeForward &&
                              pForwardMoved && rForwardMoved && !guardTripped &&
                              pTwoAccepted && rTwoAccepted;
                        }
                        if (pressurePass) {
                          pGuardOrigin = stepperP->getPosition();
                          rGuardOrigin = stepperR->getPosition();
                          regP.setTargetSafe(kPressure1Raw);
                          regR.setTargetSafe(kPressure1Raw);
                          activeReverse = regP.isActive() && regR.isActive();
                          pressureReverse = observeCompletedMove(
                              pressureFinish,
                              pressureStart,
                              40000u,
                              true,
                              &pReverseMoved,
                              &rReverseMoved,
                              &guardTripped);
                          const int32_t pNow = stepperP->getPosition();
                          const int32_t rNow = stepperR->getPosition();
                          guardTripped = guardTripped ||
                              absDiff32(pNow, 0) > kPressureGuardAbsSteps ||
                              absDiff32(rNow, 0) > kPressureGuardAbsSteps ||
                              absDiff32(pNow, pGuardOrigin) > kPressureGuardDeltaSteps ||
                              absDiff32(rNow, rGuardOrigin) > kPressureGuardDeltaSteps;
                          pressurePass = pressureReverse.passed && activeReverse &&
                              pReverseMoved && rReverseMoved && !guardTripped;
                        }
                        const bool pressureChecksumsMatch =
                            pressureForward.passed && pressureReverse.passed &&
                            pressureForward.snapshot.maskChecksum ==
                                pressureReverse.snapshot.maskChecksum &&
                            pressureForward.snapshot.arrChecksum ==
                                pressureReverse.snapshot.arrChecksum;
                        pressureForward.observation.checksumMatch =
                            pressureChecksumsMatch;
                        pressureReverse.observation.checksumMatch =
                            pressureChecksumsMatch;
                        CoordinatedXyPerformanceReport::addMove(
                            pressureAggregate,
                            pressureForward.observation,
                            performanceLimits);
                        CoordinatedXyPerformanceReport::addMove(
                            pressureAggregate,
                            pressureReverse.observation,
                            performanceLimits);
                        pressurePass = pressurePass && pressureChecksumsMatch;
                        if (pressurePass) {
                          pFinal = waitPressureReady(
                              regP, 0u, kPressure1Raw, false, kPressureSettleTimeoutMs);
                          rFinal = waitPressureReady(
                              regR, 1u, kPressure1Raw, false, kPressureSettleTimeoutMs);
                          pressurePass = pFinal.accepted && rFinal.accepted &&
                              regP.getTarget() == kPressure1Raw &&
                              regR.getTarget() == kPressure1Raw;
                        }
                        const PressureSensor::ControlSample pCounterEnd =
                            pressureSensor != nullptr && pressureSensor->numPorts() > 0u
                            ? pressureSensor->getControlSample(0u)
                            : PressureSensor::ControlSample{};
                        const PressureSensor::ControlSample rCounterEnd =
                            pressureSensor != nullptr && pressureSensor->numPorts() > 1u
                            ? pressureSensor->getControlSample(1u)
                            : PressureSensor::ControlSample{};
                        const uint32_t rejectDeltaP =
                            pCounterEnd.rejectCount >= rejectStartP
                            ? pCounterEnd.rejectCount - rejectStartP
                            : std::numeric_limits<uint32_t>::max();
                        const uint32_t rejectDeltaR =
                            rCounterEnd.rejectCount >= rejectStartR
                            ? rCounterEnd.rejectCount - rejectStartR
                            : std::numeric_limits<uint32_t>::max();
                        const bool pressureFault = pressureSensor == nullptr ||
                            pressureSensor->isSafetyFaultLatched(0u) ||
                            pressureSensor->isSafetyFaultLatched(1u);
                        pressurePass = pressurePass && rejectDeltaP == 0u &&
                            rejectDeltaR == 0u && !pressureFault &&
                            CoordinatedXyPerformanceReport::aggregatePasses(
                                pressureAggregate,
                                2u,
                                16832u,
                                60000u,
                                60000u,
                                performanceLimits);
                        closePressurePaths();
                        uint32_t finalXDrift =
                            std::numeric_limits<uint32_t>::max();
                        uint32_t finalYDrift =
                            std::numeric_limits<uint32_t>::max();
                        if (pressurePass) {
                          pressurePass = homeAndMeasureDrift(
                              finalXDrift,
                              finalYDrift,
                              "coordinated_xy_performance_final_x_home",
                              "coordinated_xy_performance_final_y_home");
                        }
                        char pressureMetrics[224] = {};
                        const int pressureLength = snprintf(
                            pressureMetrics,
                            sizeof(pressureMetrics),
                            "hz=40000;n=%lu;xe=%lu;ye=%lu;ms=%lu;i2=%lu;i7=%lu;pu=%lu;ps=%lu;am=%lu;cm=%lu;dm=%lu;tm=%lu;de=%lu;sg=%lu;wd=%lu;sa=%lu;wl=%lu;cw=%lu;sf=%lu;pa=%u;ra=%u;pm=%u;rm=%u;p2=%u;r2=%u;p1=%u;r1=%u;rej=%lu;flt=%u;g=%u;xd=%lu;yd=%lu;to=%lu",
                            (unsigned long)pressureAggregate.moveCount,
                            (unsigned long)pressureAggregate.emittedXSteps,
                            (unsigned long)pressureAggregate.emittedYSteps,
                            (unsigned long)pressureAggregate.masterSteps,
                            (unsigned long)pressureAggregate.timer2Callbacks,
                            (unsigned long)pressureAggregate.timer7Callbacks,
                            (unsigned long)pressureAggregate.pendingObservations,
                            (unsigned long)pressureAggregate.maxPendingStreak,
                            (unsigned long)pressureAggregate.phaseMaxCycles[0],
                            (unsigned long)pressureAggregate.phaseMaxCycles[1],
                            (unsigned long)pressureAggregate.phaseMaxCycles[2],
                            (unsigned long)pressureAggregate.terminalMaxCycles,
                            (unsigned long)pressureAggregate.durationErrorMaxBasisPoints,
                            (unsigned long)pressureAggregate.statusPeriodMaxMs,
                            (unsigned long)pressureAggregate.statusWatchdogAgeMaxMs,
                            (unsigned long)pressureAggregate.statusAlternationErrors,
                            (unsigned long)pressureAggregate.watchdogLateCount,
                            (unsigned long)pressureAggregate.cycleWraps,
                            (unsigned long)pressureAggregate.saturationFlags,
                            activeForward ? 1u : 0u,
                            activeReverse ? 1u : 0u,
                            (pForwardMoved && pReverseMoved) ? 1u : 0u,
                            (rForwardMoved && rReverseMoved) ? 1u : 0u,
                            pTwoAccepted ? 1u : 0u,
                            rTwoAccepted ? 1u : 0u,
                            pFinal.accepted ? 1u : 0u,
                            rFinal.accepted ? 1u : 0u,
                            (unsigned long)(rejectDeltaP + rejectDeltaR),
                            pressureFault ? 1u : 0u,
                            guardTripped ? 1u : 0u,
                            (unsigned long)finalXDrift,
                            (unsigned long)finalYDrift,
                            (unsigned long)pressureAggregate.timeoutCount);
                        const size_t pressureBudget =
                            DiagnosticResultEmitter::kResultMetricsFrameBudget -
                            std::min(std::strlen(kTests[8].name),
                                     DiagnosticResultEmitter::kMaxResultNameBytes);
                        const bool pressureMetricsFit = pressureLength > 0 &&
                            static_cast<size_t>(pressureLength) <= pressureBudget;
                        (void)runOne(kTests[8].id,
                                     kTests[8].name,
                                     pressurePass && pressureMetricsFit,
                                     pressureMetricsFit
                                         ? pressureMetrics
                                         : "gate=metrics_overflow;to=1");
                        restoreXyRates();
                        closePressurePaths();
                        return finishSelfTestNow();
                        };
                        return runCoordinatedPerformanceDiagnostic();
                      }

                      if (runDirectXyzLutSuite) {
                        static constexpr uint32_t kRateHz = 40000u;
                        static constexpr uint32_t kMoveTimeoutMs = 20000u;
                        static constexpr uint32_t kHomeFastHz = 30000u;
                        static constexpr uint32_t kHomeSlowHz = 3000u;
                        static constexpr uint32_t kHomeBackoffSteps = 400u;
                        static constexpr uint32_t kHomeTimeoutMs = 20000u;
                        static constexpr uint32_t kCruiseDistance = 14000u;
                        static constexpr uint32_t kTriangularDistance = 2000u;
                        static constexpr int32_t kSafeXMax = 45000;
                        static constexpr int32_t kSafeYMax = 35000;
                        static constexpr int32_t kSafeZMax = 80000;

                        struct DirectTestDescriptor {
                          uint16_t id;
                          const char* name;
                        };
                        static constexpr DirectTestDescriptor kTests[] = {
                            {2091u, "direct_lut_x_cruise"},
                            {2092u, "direct_lut_y_cruise"},
                            {2093u, "direct_lut_z_cruise"},
                            {2094u, "direct_lut_x_triangular"},
                            {2095u, "direct_lut_isolation"},
                        };

                        auto emitSkipped = [&](uint16_t firstId,
                                               const char* gate) -> bool {
                          char metrics[112];
                          snprintf(metrics,
                                   sizeof(metrics),
                                   "gate=%s;to=1;ep=0;nm=0;co=0;pf=1;rf=0;ab=0;sf=0",
                                   gate);
                          for (const auto& test : kTests) {
                            if (test.id >= firstId &&
                                !runOne(test.id, test.name, false, metrics)) {
                              return false;
                            }
                          }
                          return true;
                        };

                        Stepper* stepperX = Stepper::stepperX();
                        Stepper* stepperY = Stepper::stepperY();
                        Stepper* stepperZ = Stepper::stepperZ();
                        Stepper* stepperP = Stepper::stepperP();
                        Stepper* stepperR = Stepper::stepperR();
                        if (stepperX == nullptr || stepperY == nullptr ||
                            stepperZ == nullptr || stepperP == nullptr ||
                            Gantry::instance() == nullptr) {
                          (void)emitSkipped(2091u, "motion_unavailable");
                          return finishSelfTestNow();
                        }

                        struct ProfileRestoreGuard {
                          Stepper* x;
                          Stepper* y;
                          Stepper* z;
                          Stepper::AccelProfile xp;
                          Stepper::AccelProfile yp;
                          Stepper::AccelProfile zp;
                          uint32_t xMax;
                          uint32_t yMax;
                          uint32_t zMax;
                          float xAccel;
                          float yAccel;
                          float zAccel;
                          ~ProfileRestoreGuard() {
                            x->setAccelProfile(xp);
                            y->setAccelProfile(yp);
                            z->setAccelProfile(zp);
                            x->setMaxSpeedHz(xMax);
                            y->setMaxSpeedHz(yMax);
                            z->setMaxSpeedHz(zMax);
                            x->setAccelStepsPerSec2(xAccel);
                            y->setAccelStepsPerSec2(yAccel);
                            z->setAccelStepsPerSec2(zAccel);
                          }
                        } profileGuard{stepperX,
                                       stepperY,
                                       stepperZ,
                                       stepperX->accelProfile(),
                                       stepperY->accelProfile(),
                                       stepperZ->accelProfile(),
                                       stepperX->maxSpeedHz(),
                                       stepperY->maxSpeedHz(),
                                       stepperZ->maxSpeedHz(),
                                       stepperX->accelStepsPerSec2(),
                                       stepperY->accelStepsPerSec2(),
                                       stepperZ->accelStepsPerSec2()};
                        stepperX->setAccelProfile(Stepper::PROFILE_SCURVE_COSINE);
                        stepperY->setAccelProfile(Stepper::PROFILE_SCURVE_COSINE);
                        stepperZ->setAccelProfile(Stepper::PROFILE_SCURVE_COSINE);
                        stepperX->setMaxSpeedHz(kRateHz);
                        stepperY->setMaxSpeedHz(kRateHz);
                        stepperZ->setMaxSpeedHz(kRateHz);
                        stepperX->setAccelStepsPerSec2(140000.0f);
                        stepperY->setAccelStepsPerSec2(140000.0f);
                        stepperZ->setAccelStepsPerSec2(140000.0f);

                        const int32_t pStart = stepperP->getPosition();
                        const int32_t rStart =
                            (stepperR != nullptr) ? stepperR->getPosition() : 0;

                        // Each direct move is shorter than one status cadence
                        // interval. Keep one window open across the complete
                        // row so evidence does not depend on cadence phase.
                        const bool directStatusMetricsReset =
                            Comm::resetStatusMetrics();
                        struct DirectStatusWindowGuard {
                          DirectStatusWindowGuard(Comm* owner, bool& resume)
                              : comm(owner), resumeAfterEmission(&resume), active(true) {
                            *resumeAfterEmission = true;
                            comm->setStatusPaused(false);
                          }
                          void stop() {
                            if (active && comm != nullptr) {
                              *resumeAfterEmission = false;
                              comm->setStatusPaused(true);
                              active = false;
                            }
                          }
                          ~DirectStatusWindowGuard() { stop(); }
                          Comm* comm;
                          bool* resumeAfterEmission;
                          bool active;
                        } statusWindow{comm, resumeStatusAfterEmission};
                        bool directStatusEvidenceValid =
                            directStatusMetricsReset;
                        uint32_t directStatusAgeMaxMs = 0u;

                        sendProgressStage("direct_xyz_lut_envelope_clear");
                        if (!runZClearanceHomePreflight("direct_lut_z_home",
                                                        kHomeFastHz,
                                                        kHomeSlowHz,
                                                        kHomeBackoffSteps,
                                                        kHomeTimeoutMs)) {
                          (void)emitSkipped(2091u, "z_home");
                          return finishSelfTestNow();
                        }
                        MotionQualificationMath::AxisHomeSample xHome{};
                        MotionQualificationMath::AxisHomeSample yHome{};
                        sendProgressStage("direct_lut_xy_home");
                        if (!runXyHomeDiagnosticAttempt(xHome,
                                                        yHome,
                                                        kHomeFastHz,
                                                        kHomeSlowHz,
                                                        kHomeBackoffSteps,
                                                        kHomeTimeoutMs)) {
                          (void)emitSkipped(2091u, "xy_home");
                          return finishSelfTestNow();
                        }

                        const bool preHomesLegacy =
                            !stepperX->getLastDirectProfileSnapshot().selected &&
                            !stepperY->getLastDirectProfileSnapshot().selected &&
                            !stepperZ->getLastDirectProfileSnapshot().selected;

                        struct DirectMoveResult {
                          bool emitted = false;
                          bool safeToContinue = false;
                        };

                        auto runDirectMove = [&](uint16_t testId,
                                                 const char* name,
                                                 Stepper* stepper,
                                                 EventBits_t doneBit,
                                                 uint8_t axis,
                                                 int32_t target,
                                                 bool instrumented) -> DirectMoveResult {
                          DirectMoveResult result{};
                          const int32_t start = stepper->getPosition();
                          const int64_t deltaWide =
                              static_cast<int64_t>(target) - start;
                          const uint32_t distance = static_cast<uint32_t>(
                              deltaWide < 0 ? -deltaWide : deltaWide);

                          DirectStepperProfileReport::MoveObservation observation{};
                          observation.axis = axis;
                          observation.logicalDistance = distance;
                          observation.effectiveRateHz = kRateHz;
                          observation.expectedNativePulses =
                              MotionUnitScale::toNativeStepCycles(distance);
                          observation.instrumentationRequired = instrumented;

                          const bool completed = moveAxisToWithTimeout(
                              stepper, doneBit, target, kRateHz, kMoveTimeoutMs);
                          const Comm::StatusMetricsSnapshot statusMetrics =
                              Comm::getStatusMetricsSnapshot();
                          directStatusEvidenceValid =
                              directStatusEvidenceValid && statusMetrics.valid &&
                              statusMetrics.lockFailures == 0u;
                          observation.statusPeriodMaxMs = statusMetrics.valid
                              ? statusMetrics.periodMaxMs
                              : std::numeric_limits<uint32_t>::max();
                          observation.statusFrameCount = statusMetrics.valid
                              ? statusMetrics.chunk0Count + statusMetrics.chunk1Count
                              : 0u;
                          uint32_t statusAgeMs =
                              std::numeric_limits<uint32_t>::max();
                          if (Watchdog_GetTaskLastSeenAgeMs(
                                  CRASH_TASK_STATUS, &statusAgeMs) == 0u) {
                            directStatusEvidenceValid = false;
                          } else if (statusAgeMs > directStatusAgeMaxMs) {
                            directStatusAgeMaxMs = statusAgeMs;
                          }
                          observation.statusWatchdogAgeMaxMs = statusAgeMs;

                          observation.timedOut = !completed;
                          observation.endpointReached =
                              completed && stepper->getPosition() == target;
                          observation.profile =
                              stepper->getLastDirectProfileSnapshot();
                          if (instrumented) {
                            observation.instrumentation =
                                stepper->getLastMoveInstrumentationSnapshot();
                          }

                          char metrics[208] = {0};
                          const size_t metricsLength =
                              DirectStepperProfileReport::buildMetrics(
                                  metrics, sizeof(metrics), observation);
                          const size_t metricsBudget =
                              DiagnosticResultEmitter::kResultMetricsFrameBudget -
                              std::min(std::strlen(name),
                                       DiagnosticResultEmitter::kMaxResultNameBytes);
                          const bool metricsFit = metricsLength != 0u &&
                              metricsLength <= metricsBudget;
                          const bool passed = metricsFit &&
                              DirectStepperProfileReport::movePasses(observation);
                          result.safeToContinue = completed &&
                              observation.endpointReached &&
                              !observation.profile.prepareFailed &&
                              !observation.profile.runtimeFailed &&
                              !observation.profile.aborted;
                          result.emitted = runOne(
                              testId,
                              name,
                              passed,
                              metricsFit
                                  ? metrics
                                  : "gate=metrics_overflow;to=1;ep=0;nm=0;co=0;pf=1;rf=0;ab=0;sf=0");
                          return result;
                        };

                        const int32_t xStart = stepperX->getPosition();
                        const int32_t xTarget = xStart +
                            static_cast<int32_t>(kCruiseDistance);
                        if (xStart < 0 || xTarget > kSafeXMax) {
                          (void)emitSkipped(2091u, "x_envelope");
                          return finishSelfTestNow();
                        }
                        DirectMoveResult moveResult = runDirectMove(
                            2091u,
                            "direct_lut_x_cruise",
                            stepperX,
                            BIT_STEPPER1_DONE,
                            static_cast<uint8_t>(Stepper::X_AXIS),
                            xTarget,
                            true);
                        if (!moveResult.emitted) return finishSelfTestNow();
                        if (!moveResult.safeToContinue) {
                          (void)emitSkipped(2092u, "x_move");
                          return finishSelfTestNow();
                        }

                        const int32_t yStart = stepperY->getPosition();
                        const int32_t yTarget = yStart +
                            static_cast<int32_t>(kCruiseDistance);
                        if (yStart < 0 || yTarget > kSafeYMax) {
                          (void)emitSkipped(2092u, "y_envelope");
                          return finishSelfTestNow();
                        }
                        moveResult = runDirectMove(
                            2092u,
                            "direct_lut_y_cruise",
                            stepperY,
                            BIT_STEPPER2_DONE,
                            static_cast<uint8_t>(Stepper::Y_AXIS),
                            yTarget,
                            true);
                        if (!moveResult.emitted) return finishSelfTestNow();
                        if (!moveResult.safeToContinue) {
                          (void)emitSkipped(2093u, "y_move");
                          return finishSelfTestNow();
                        }

                        const int32_t zStart = stepperZ->getPosition();
                        const int32_t zTarget = zStart +
                            static_cast<int32_t>(kCruiseDistance);
                        if (zStart < 0 || zTarget > kSafeZMax) {
                          (void)emitSkipped(2093u, "z_envelope");
                          return finishSelfTestNow();
                        }
                        moveResult = runDirectMove(
                            2093u,
                            "direct_lut_z_cruise",
                            stepperZ,
                            BIT_STEPPER3_DONE,
                            static_cast<uint8_t>(Stepper::Z_AXIS),
                            zTarget,
                            false);
                        if (!moveResult.emitted) return finishSelfTestNow();
                        if (!moveResult.safeToContinue) {
                          (void)emitSkipped(2094u, "z_move");
                          return finishSelfTestNow();
                        }

                        const int32_t triangularTarget = stepperX->getPosition() +
                            static_cast<int32_t>(kTriangularDistance);
                        if (triangularTarget > kSafeXMax) {
                          (void)emitSkipped(2094u, "tri_envelope");
                          return finishSelfTestNow();
                        }
                        moveResult = runDirectMove(
                            2094u,
                            "direct_lut_x_triangular",
                            stepperX,
                            BIT_STEPPER1_DONE,
                            static_cast<uint8_t>(Stepper::X_AXIS),
                            triangularTarget,
                            true);
                        if (!moveResult.emitted) return finishSelfTestNow();
                        if (!moveResult.safeToContinue) {
                          (void)emitSkipped(2095u, "tri_move");
                          return finishSelfTestNow();
                        }

                        MotionQualificationMath::AxisHomeSample zTeardown{};
                        const bool zHomeOk = runAxisHomeDiagnosticAttempt(
                            stepperZ,
                            BIT_HOME_Z_DONE,
                            zTeardown,
                            kHomeFastHz,
                            kHomeSlowHz,
                            kHomeBackoffSteps,
                            kHomeTimeoutMs);
                        MotionQualificationMath::AxisHomeSample xTeardown{};
                        MotionQualificationMath::AxisHomeSample yTeardown{};
                        const bool xyHomeOk = runXyHomeDiagnosticAttempt(
                            xTeardown,
                            yTeardown,
                            kHomeFastHz,
                            kHomeSlowHz,
                            kHomeBackoffSteps,
                            kHomeTimeoutMs);
                        const bool postHomesLegacy =
                            !stepperX->getLastDirectProfileSnapshot().selected &&
                            !stepperY->getLastDirectProfileSnapshot().selected &&
                            !stepperZ->getLastDirectProfileSnapshot().selected;
                        const Comm::StatusMetricsSnapshot finalStatusMetrics =
                            Comm::getStatusMetricsSnapshot();
                        directStatusEvidenceValid =
                            directStatusEvidenceValid && finalStatusMetrics.valid &&
                            finalStatusMetrics.lockFailures == 0u;
                        uint32_t finalStatusAgeMs =
                            std::numeric_limits<uint32_t>::max();
                        if (Watchdog_GetTaskLastSeenAgeMs(
                                CRASH_TASK_STATUS, &finalStatusAgeMs) == 0u) {
                          directStatusEvidenceValid = false;
                        } else if (finalStatusAgeMs > directStatusAgeMaxMs) {
                          directStatusAgeMaxMs = finalStatusAgeMs;
                        }
                        statusWindow.stop();
                        const uint32_t directStatusFrames =
                            finalStatusMetrics.valid
                                ? finalStatusMetrics.chunk0Count +
                                      finalStatusMetrics.chunk1Count
                                : 0u;
                        const uint32_t directStatusGapMs =
                            finalStatusMetrics.valid
                                ? finalStatusMetrics.periodMaxMs
                                : std::numeric_limits<uint32_t>::max();
                        const uint32_t directStatusAlternationErrors =
                            finalStatusMetrics.valid
                                ? finalStatusMetrics.alternationErrors
                                : std::numeric_limits<uint32_t>::max();
                        const bool directStatusPass =
                            directStatusEvidenceValid &&
                            directStatusFrames >= 2u &&
                            directStatusGapMs <= 100u &&
                            directStatusAgeMaxMs <= 100u &&
                            directStatusAlternationErrors == 0u;
                        const int32_t pDelta = stepperP->getPosition() - pStart;
                        const int32_t rDelta = (stepperR != nullptr)
                            ? (stepperR->getPosition() - rStart)
                            : 0;
                        constexpr TMC2208Configuration::Values driverConfig =
                            TMC2208Configuration::buildValues();
                        const bool isolationPass = preHomesLegacy &&
                            postHomesLegacy && zHomeOk && xyHomeOk &&
                            pDelta == 0 && rDelta == 0 &&
                            LC_TMC2208_MRES == 3u &&
                            driverConfig.doubleEdge &&
                            !driverConfig.multistepFilter &&
                            directStatusPass;
                        char isolationMetrics[208];
                        const int isolationLength = snprintf(
                                 isolationMetrics,
                                 sizeof(isolationMetrics),
                                 "pre=%u;post=%u;zh=%u;xyh=%u;pd=%ld;rd=%ld;mres=%u;de=%u;mf=%u;sn=%lu;sg=%lu;wd=%lu;sa=%lu;sv=%u;sf=0;to=0",
                                 static_cast<unsigned>(preHomesLegacy ? 1u : 0u),
                                 static_cast<unsigned>(postHomesLegacy ? 1u : 0u),
                                 static_cast<unsigned>(zHomeOk ? 1u : 0u),
                                 static_cast<unsigned>(xyHomeOk ? 1u : 0u),
                                 static_cast<long>(pDelta),
                                 static_cast<long>(rDelta),
                                 static_cast<unsigned>(LC_TMC2208_MRES),
                                 static_cast<unsigned>(driverConfig.doubleEdge ? 1u : 0u),
                                 static_cast<unsigned>(driverConfig.multistepFilter ? 1u : 0u),
                                 static_cast<unsigned long>(directStatusFrames),
                                 static_cast<unsigned long>(directStatusGapMs),
                                 static_cast<unsigned long>(directStatusAgeMaxMs),
                                 static_cast<unsigned long>(directStatusAlternationErrors),
                                 static_cast<unsigned>(directStatusEvidenceValid ? 1u : 0u));
                        const size_t isolationBudget =
                            DiagnosticResultEmitter::kResultMetricsFrameBudget -
                            std::min(std::strlen("direct_lut_isolation"),
                                     DiagnosticResultEmitter::kMaxResultNameBytes);
                        const bool isolationMetricsFit = isolationLength > 0 &&
                            static_cast<size_t>(isolationLength) <= isolationBudget;
                        (void)runOne(2095u,
                                     "direct_lut_isolation",
                                     isolationPass && isolationMetricsFit,
                                     isolationMetricsFit
                                         ? isolationMetrics
                                         : "gate=metrics_overflow;sf=1;to=1");
                        return finishSelfTestNow();
                      }

                      if (runMotionTimingSuite) {
                        static constexpr int32_t kSafeXMax = 45000;
                        static constexpr int32_t kSafeYMax = 35000;
                        static constexpr int32_t kCableGuardX = 1000;
                        static constexpr int32_t kCableGuardMinY = 500;
                        static constexpr uint32_t kLowRateHz = 6000u;
                        static constexpr uint32_t kRequiredMaxRateHz = 40000u;
                        static constexpr uint32_t kMoveTimeoutMs = 20000u;
                        static constexpr uint32_t kHomeFastHz = 30000u;
                        static constexpr uint32_t kHomeSlowHz = 3000u;
                        static constexpr uint32_t kHomeBackoffSteps = 400u;
                        static constexpr uint32_t kHomeTimeoutMs = 20000u;
                        static constexpr size_t kMetricsCapacity = 192u;
                        const MotionQualificationMath::XySafetyEnvelope envelope{
                            0, kSafeXMax, 0, kSafeYMax, kCableGuardX, kCableGuardMinY};

                        struct TimingTestDescriptor {
                          uint16_t testId;
                          const char* name;
                        };
                        static constexpr TimingTestDescriptor kTimingTests[] = {
                            {2020u, "motion_timing_low_xy"},
                            {2021u, "motion_timing_x_only"},
                            {2022u, "motion_timing_y_only"},
                            {2023u, "motion_timing_equal_xy"},
                            {2024u, "motion_timing_camera_ratio"},
                            {2025u, "motion_timing_short_tri"},
                        };

                        auto emitSkippedMotionTiming = [&](uint16_t firstTestId,
                                                           const char* gate) -> bool {
                          char metrics[128];
                          snprintf(metrics,
                                   sizeof(metrics),
                                   "gate=%s;dx=0;dy=0;hz=0;to=1;ep=0;wd=0;sg=0;sn=0;sf=0",
                                   gate);
                          for (const TimingTestDescriptor& test : kTimingTests) {
                            if (test.testId >= firstTestId &&
                                !runOne(test.testId, test.name, false, metrics)) {
                              return false;
                            }
                          }
                          return true;
                        };

                        auto pointIsSafe = [&](int32_t x, int32_t y) -> bool {
                          return MotionQualificationMath::xyPointIsSafe({x, y}, envelope);
                        };

                        Stepper* stepperX = Stepper::stepperX();
                        Stepper* stepperY = Stepper::stepperY();
                        if (stepperX == nullptr || stepperY == nullptr || Gantry::instance() == nullptr) {
                          (void)emitSkippedMotionTiming(2020u, "motion_unavailable");
                          return finishSelfTestNow();
                        }

                        const uint32_t savedXMaxRateHz = stepperX->maxSpeedHz();
                        const uint32_t savedYMaxRateHz = stepperY->maxSpeedHz();
                        auto restoreXyMaxRates = [&]() {
                          stepperX->setMaxSpeedHz(savedXMaxRateHz);
                          stepperY->setMaxSpeedHz(savedYMaxRateHz);
                        };
                        auto setLowXyMaxRates = [&]() {
                          stepperX->setMaxSpeedHz(kLowRateHz);
                          stepperY->setMaxSpeedHz(kLowRateHz);
                        };

                        auto moveToAtLowRate = [&](int32_t x, int32_t y) -> bool {
                          if (!pointIsSafe(x, y)) {
                            return false;
                          }
                          setLowXyMaxRates();
                          const bool completed =
                              moveGantryToWithTimeout(x, y, kLowRateHz, kMoveTimeoutMs);
                          restoreXyMaxRates();
                          const GantryPosition position = Gantry::instance()->getPosition();
                          return completed && position.x == x && position.y == y;
                        };

                        struct TimingMoveResult {
                          bool resultEmitted = false;
                          bool passed = false;
                          bool safeToContinue = false;
                        };

                        auto runMeasuredMove = [&](uint16_t testId,
                                                   const char* name,
                                                   int32_t targetX,
                                                   int32_t targetY) -> TimingMoveResult {
                          TimingMoveResult result{};
                          const GantryPosition start = Gantry::instance()->getPosition();
                          if (!pointIsSafe(start.x, start.y) || !pointIsSafe(targetX, targetY)) {
                            result.resultEmitted = runOne(testId, name, false, "gate=unsafe_point;to=1;ep=0");
                            return result;
                          }

                          StepperInstrumentationReport::MoveObservation observation{};
                          observation.deltaXSteps = targetX - start.x;
                          observation.deltaYSteps = targetY - start.y;
                          const uint32_t xDistance = static_cast<uint32_t>(
                              observation.deltaXSteps < 0 ? -static_cast<int64_t>(observation.deltaXSteps)
                                                          : observation.deltaXSteps);
                          const uint32_t yDistance = static_cast<uint32_t>(
                              observation.deltaYSteps < 0 ? -static_cast<int64_t>(observation.deltaYSteps)
                                                          : observation.deltaYSteps);
                          observation.effectiveRateHz =
                              (xDistance >= yDistance) ? stepperX->maxSpeedHz() : stepperY->maxSpeedHz();

                          xEventGroupClearBits(_doneEvents, BIT_STEPPER1_DONE | BIT_STEPPER2_DONE);
                          Comm::resetStatusMetrics();
                          comm->setStatusPaused(false);
                          Gantry::instance()->moveTo(targetX, targetY, observation.effectiveRateHz);

                          const uint32_t waitStartMs = HAL_GetTick();
                          const TickType_t pollTicks = msToAtLeast1Tick(10u);
                          bool completed = false;
                          while ((HAL_GetTick() - waitStartMs) < kMoveTimeoutMs) {
                            Watchdog_CheckIn(CRASH_TASK_ORCH);
                            uint32_t statusAgeMs = 0u;
                            if (Watchdog_GetTaskLastSeenAgeMs(CRASH_TASK_STATUS, &statusAgeMs) != 0u &&
                                statusAgeMs > observation.statusWatchdogAgeMaxMs) {
                              observation.statusWatchdogAgeMaxMs = statusAgeMs;
                            }
                            if (_selfTestAbortRequested) {
                              break;
                            }
                            const EventBits_t doneBits = xEventGroupGetBits(_doneEvents);
                            if ((doneBits & (BIT_STEPPER1_DONE | BIT_STEPPER2_DONE)) ==
                                (BIT_STEPPER1_DONE | BIT_STEPPER2_DONE)) {
                              completed = true;
                              break;
                            }
                            vTaskDelay(pollTicks);
                          }

                          uint32_t finalStatusAgeMs = 0u;
                          if (Watchdog_GetTaskLastSeenAgeMs(CRASH_TASK_STATUS, &finalStatusAgeMs) != 0u &&
                              finalStatusAgeMs > observation.statusWatchdogAgeMaxMs) {
                            observation.statusWatchdogAgeMaxMs = finalStatusAgeMs;
                          }
                          observation.statusPeriodMaxMs = Comm::getStatusPeriodMaxMs();
                          observation.statusFrameCount =
                              Comm::getStatusChunk0Count() + Comm::getStatusChunk1Count();
                          comm->setStatusPaused(true);

                          if (!completed) {
                            Gantry::cancelXYZMotors();
                          }
                          const GantryPosition end = Gantry::instance()->getPosition();
                          observation.timedOut = !completed;
                          observation.endpointReached =
                              completed && end.x == targetX && end.y == targetY;
                          observation.x = stepperX->getLastMoveInstrumentationSnapshot();
                          observation.y = stepperY->getLastMoveInstrumentationSnapshot();

                          char metrics[kMetricsCapacity] = {0};
                          const size_t metricsLength =
                              StepperInstrumentationReport::buildMetrics(
                                  metrics, sizeof(metrics), observation);
                          result.passed = (metricsLength != 0u) &&
                                          StepperInstrumentationReport::movePasses(observation);
                          result.safeToContinue = completed && observation.endpointReached;
                          result.resultEmitted = runOne(
                              testId,
                              name,
                              result.passed,
                              (metricsLength != 0u) ? metrics : "gate=metrics_overflow;to=1;ep=0");
                          return result;
                        };

                        if (!runZClearanceHomePreflight("timing_z_clearance_home",
                                                        kHomeFastHz,
                                                        kHomeSlowHz,
                                                        kHomeBackoffSteps,
                                                        kHomeTimeoutMs)) {
                          restoreXyMaxRates();
                          (void)emitSkippedMotionTiming(2020u, "z_clearance_home");
                          return finishSelfTestNow();
                        }

                        MotionQualificationMath::AxisHomeSample xHome{};
                        MotionQualificationMath::AxisHomeSample yHome{};
                        sendProgressStage("timing_xy_home");
                        if (!runXyHomeDiagnosticAttempt(xHome,
                                                        yHome,
                                                        kHomeFastHz,
                                                        kHomeSlowHz,
                                                        kHomeBackoffSteps,
                                                        kHomeTimeoutMs)) {
                          restoreXyMaxRates();
                          (void)emitSkippedMotionTiming(2020u, "xy_home");
                          return finishSelfTestNow();
                        }

                        setLowXyMaxRates();
                        const bool lowAnchorCompleted =
                            moveGantryToWithTimeout(2000, 2000, kLowRateHz, kMoveTimeoutMs);
                        const GantryPosition lowAnchorPosition = Gantry::instance()->getPosition();
                        if (!lowAnchorCompleted ||
                            lowAnchorPosition.x != 2000 || lowAnchorPosition.y != 2000) {
                          restoreXyMaxRates();
                          (void)emitSkippedMotionTiming(2020u, "low_anchor");
                          return finishSelfTestNow();
                        }
                        const TimingMoveResult lowResult =
                            runMeasuredMove(2020u, "motion_timing_low_xy", 7000, 7000);
                        restoreXyMaxRates();
                        if (!lowResult.resultEmitted) {
                          return finishSelfTestNow();
                        }
                        if (!lowResult.passed) {
                          (void)emitSkippedMotionTiming(2021u, "low_probe_failed");
                          return finishSelfTestNow();
                        }
                        if (savedXMaxRateHz != kRequiredMaxRateHz ||
                            savedYMaxRateHz != kRequiredMaxRateHz) {
                          (void)emitSkippedMotionTiming(2021u, "max_rate_not_40000");
                          return finishSelfTestNow();
                        }

                        if (!moveToAtLowRate(2000, 2000)) {
                          (void)emitSkippedMotionTiming(2021u, "x_anchor");
                          return finishSelfTestNow();
                        }
                        TimingMoveResult moveResult =
                            runMeasuredMove(2021u, "motion_timing_x_only", 12000, 2000);
                        if (!moveResult.resultEmitted) return finishSelfTestNow();
                        if (!moveResult.safeToContinue) {
                          (void)emitSkippedMotionTiming(2022u, "x_move_failed");
                          return finishSelfTestNow();
                        }

                        moveResult = runMeasuredMove(
                            2022u, "motion_timing_y_only", 12000, 12000);
                        if (!moveResult.resultEmitted) return finishSelfTestNow();
                        if (!moveResult.safeToContinue) {
                          (void)emitSkippedMotionTiming(2023u, "y_move_failed");
                          return finishSelfTestNow();
                        }

                        moveResult = runMeasuredMove(
                            2023u, "motion_timing_equal_xy", 22000, 22000);
                        if (!moveResult.resultEmitted) return finishSelfTestNow();
                        if (!moveResult.safeToContinue) {
                          (void)emitSkippedMotionTiming(2024u, "equal_xy_failed");
                          return finishSelfTestNow();
                        }

                        if (!moveToAtLowRate(8916, 30500)) {
                          (void)emitSkippedMotionTiming(2024u, "camera_anchor");
                          return finishSelfTestNow();
                        }
                        moveResult = runMeasuredMove(
                            2024u, "motion_timing_camera_ratio", 500, 500);
                        if (!moveResult.resultEmitted) return finishSelfTestNow();
                        if (!moveResult.safeToContinue) {
                          (void)emitSkippedMotionTiming(2025u, "camera_ratio_failed");
                          return finishSelfTestNow();
                        }

                        if (!moveToAtLowRate(2000, 2000)) {
                          (void)emitSkippedMotionTiming(2025u, "short_anchor");
                          return finishSelfTestNow();
                        }
                        moveResult = runMeasuredMove(
                            2025u, "motion_timing_short_tri", 3000, 2000);
                        if (!moveResult.resultEmitted) return finishSelfTestNow();

                        restoreXyMaxRates();
                        if (moveResult.safeToContinue && !_selfTestAbortRequested) {
                          MotionQualificationMath::AxisHomeSample xTeardownHome{};
                          MotionQualificationMath::AxisHomeSample yTeardownHome{};
                          sendProgressStage("timing_xy_teardown_home");
                          (void)runXyHomeDiagnosticAttempt(xTeardownHome,
                                                          yTeardownHome,
                                                          kHomeFastHz,
                                                          kHomeSlowHz,
                                                          kHomeBackoffSteps,
                                                          kHomeTimeoutMs);
                        }
                        return finishSelfTestNow();
                      }

                      if (runXyMotionSuite) {
                        static constexpr int32_t kSafeXMax = 45000;
                        static constexpr int32_t kSafeYMax = 35000;
                        static constexpr int32_t kCableGuardX = 1000;
                        static constexpr int32_t kCableGuardMinY = 500;
                        static constexpr int32_t kLongXMax = 44000;
                        static constexpr int32_t kLongYMax = 34000;
                        static constexpr uint32_t kLongRepetitions = 3u;
                        static constexpr uint32_t kLongPointCount = 5u;
                        static constexpr uint32_t kLongFeedHz = 6000u;
                        static constexpr uint32_t kLongMoveTimeoutMs = 45000u;
                        static constexpr uint32_t kRasterRepetitions = 2u;
                        static constexpr uint32_t kRasterRows = 8u;
                        static constexpr uint32_t kRasterCols = 12u;
                        static constexpr int32_t kRasterAnchorX = 3000;
                        static constexpr int32_t kRasterAnchorY = 1000;
                        static constexpr int32_t kRasterStep = 400;
                        static constexpr uint32_t kRasterFeedHz = 6000u;
                        static constexpr uint32_t kRasterMoveTimeoutMs = 8000u;
                        static constexpr uint32_t kHomeFastHz = 30000u;
                        static constexpr uint32_t kHomeSlowHz = 3000u;
                        static constexpr uint32_t kHomeBackoffSteps = 400u;
                        static constexpr uint32_t kHomeTimeoutMs = 20000u;
                        static constexpr int32_t kExpectedBackoffSteps = 100;
                        const MotionQualificationMath::XySafetyEnvelope envelope{
                            0, kSafeXMax, 0, kSafeYMax, kCableGuardX, kCableGuardMinY};

                        auto emitSkippedXyMotion = [&](uint16_t firstTestId, const char* phase) -> bool {
                          char metrics[192];
                          snprintf(metrics, sizeof(metrics),
                                   "phase=%s;rep=0;pts=0;xmax=%ld;ymax=%ld;dx=0;dy=0;x_span=0;y_span=0;x_drift=0;y_drift=0;x_ret=0;y_ret=0;ret_err=0;move_to=0;home_to=1;guard=0;bound=0",
                                   phase,
                                   static_cast<long>(kSafeXMax),
                                   static_cast<long>(kSafeYMax));
                          if ((firstTestId <= 2010u) &&
                              !runOne(2010, "motion_xy_long_travel_factory", false, metrics)) return false;
                          if ((firstTestId <= 2011u) &&
                              !runOne(2011, "motion_xy_raster_repeatability_factory", false, metrics)) return false;
                          return true;
                        };

                        auto checkPointSafety = [&](const MotionQualificationMath::XyPoint& point,
                                                    MotionQualificationMath::XyMotionStats& stats,
                                                    bool& boundViolation,
                                                    bool& guardViolation) -> bool {
                          const bool inBounds = MotionQualificationMath::xyPointInBounds(point, envelope);
                          const bool guardOk = MotionQualificationMath::xyPointPassesCableGuard(point, envelope);
                          if (!inBounds) {
                            boundViolation = true;
                            stats.boundViolationCount++;
                          }
                          if (!guardOk) {
                            guardViolation = true;
                            stats.guardViolationCount++;
                          }
                          return inBounds && guardOk;
                        };

                        auto moveChecked = [&](const MotionQualificationMath::XyPoint& target,
                                               uint32_t feedHz,
                                               uint32_t timeoutMs,
                                               MotionQualificationMath::XyMotionStats& stats,
                                               bool& boundViolation,
                                               bool& guardViolation) -> bool {
                          if (!checkPointSafety(target, stats, boundViolation, guardViolation)) {
                            return false;
                          }
                          const bool reached = moveGantryToWithTimeout(target.x, target.y, feedHz, timeoutMs);
                          if (!reached) {
                            return false;
                          }
                          const GantryPosition pos = Gantry::instance()->getPosition();
                          const MotionQualificationMath::XyPoint actual{pos.x, pos.y};
                          return checkPointSafety(actual, stats, boundViolation, guardViolation);
                        };

                        auto runReferenceHomeSequence = [&](MotionQualificationMath::AxisHomeSample& xReference,
                                                            MotionQualificationMath::AxisHomeSample& yReference,
                                                            const char* settleStage,
                                                            const char* referenceStage,
                                                            const char*& failedStage) -> bool {
                          MotionQualificationMath::AxisHomeSample xSettle{};
                          MotionQualificationMath::AxisHomeSample ySettle{};
                          failedStage = settleStage;
                          sendProgressStage(settleStage);
                          if (!runXyHomeDiagnosticAttempt(xSettle,
                                                          ySettle,
                                                          kHomeFastHz,
                                                          kHomeSlowHz,
                                                          kHomeBackoffSteps,
                                                          kHomeTimeoutMs)) {
                            return false;
                          }
                          failedStage = referenceStage;
                          sendProgressStage(referenceStage);
                          if (!runXyHomeDiagnosticAttempt(xReference,
                                                          yReference,
                                                          kHomeFastHz,
                                                          kHomeSlowHz,
                                                          kHomeBackoffSteps,
                                                          kHomeTimeoutMs)) {
                            return false;
                          }
                          failedStage = nullptr;
                          return true;
                        };

                        MotionQualificationMath::AxisHomeSample xReference{};
                        MotionQualificationMath::AxisHomeSample yReference{};
                        const char* referenceHomeFailureStage = nullptr;
                        if (!runZClearanceHomePreflight("xy_z_clearance_home",
                                                        kHomeFastHz,
                                                        kHomeSlowHz,
                                                        kHomeBackoffSteps,
                                                        kHomeTimeoutMs)) {
                          (void)emitSkippedXyMotion(2010u, "z_clearance_home");
                          return finishSelfTestNow();
                        }
                        if (!runReferenceHomeSequence(xReference,
                                                      yReference,
                                                      "xy_long_settle_home",
                                                      "xy_long_reference_home",
                                                      referenceHomeFailureStage)) {
                          (void)emitSkippedXyMotion(2010u, referenceHomeFailureStage ? referenceHomeFailureStage : "reference_home");
                          return finishSelfTestNow();
                        }

                        const int32_t baseX = xReference.finalBackoffSteps;
                        const int32_t baseY = yReference.finalBackoffSteps;
                        const MotionQualificationMath::XyPoint longTargets[kLongPointCount] = {
                            {baseX, kCableGuardMinY},
                            {kLongXMax, kCableGuardMinY},
                            {kLongXMax, kLongYMax},
                            {baseX, kLongYMax},
                            {baseX, kCableGuardMinY},
                        };
                        MotionQualificationMath::AxisHomeSample xLongSamples[kLongRepetitions]{};
                        MotionQualificationMath::AxisHomeSample yLongSamples[kLongRepetitions]{};
                        MotionQualificationMath::XyMotionStats longStats{};
                        longStats.points = kLongPointCount;
                        uint32_t longCompleted = 0u;
                        bool longMoveOk = true;
                        for (uint32_t rep = 0u; rep < kLongRepetitions; ++rep) {
                          sendProgressStage("xy_long_travel");
                          bool repMovesCompleted = true;
                          bool repBoundViolation = false;
                          bool repGuardViolation = false;
                          for (uint32_t point = 0u; point < kLongPointCount; ++point) {
                            maybeSendProgress("xy_long_travel_move");
                            if (!moveChecked(longTargets[point],
                                             kLongFeedHz,
                                             kLongMoveTimeoutMs,
                                             longStats,
                                             repBoundViolation,
                                             repGuardViolation)) {
                              repMovesCompleted = false;
                              longMoveOk = false;
                              break;
                            }
                            if (_selfTestAbortRequested) {
                              break;
                            }
                          }
                          const bool homePassed = runXyHomeDiagnosticAttempt(xLongSamples[rep],
                                                                             yLongSamples[rep],
                                                                             kHomeFastHz,
                                                                             kHomeSlowHz,
                                                                             kHomeBackoffSteps,
                                                                             kHomeTimeoutMs);
                          MotionQualificationMath::recordXyMotionSample(longStats,
                                                                         baseX,
                                                                         baseY,
                                                                         Stepper::stepperX()->getPosition(),
                                                                         Stepper::stepperY()->getPosition(),
                                                                         xReference.limitTriggerSteps,
                                                                         yReference.limitTriggerSteps,
                                                                         xLongSamples[rep],
                                                                         yLongSamples[rep],
                                                                         repMovesCompleted && homePassed,
                                                                         repBoundViolation,
                                                                         repGuardViolation);
                          longCompleted++;
                          if (!repMovesCompleted || !homePassed || _selfTestAbortRequested) {
                            break;
                          }
                        }
                        longStats.repetitions = longCompleted;
                        const MotionQualificationMath::AxisHomeStats xLongHomeStats =
                            MotionQualificationMath::summarizeAxisHomeSamples(xLongSamples,
                                                                              longCompleted,
                                                                              kExpectedBackoffSteps);
                        const MotionQualificationMath::AxisHomeStats yLongHomeStats =
                            MotionQualificationMath::summarizeAxisHomeSamples(yLongSamples,
                                                                              longCompleted,
                                                                              kExpectedBackoffSteps);
                        uint32_t longReturnError = longStats.returnErrorMaxSteps;
                        if (xLongHomeStats.returnErrorMaxSteps > longReturnError) longReturnError = xLongHomeStats.returnErrorMaxSteps;
                        if (yLongHomeStats.returnErrorMaxSteps > longReturnError) longReturnError = yLongHomeStats.returnErrorMaxSteps;
                        const bool longPass = longMoveOk &&
                            (longCompleted == kLongRepetitions) &&
                            MotionQualificationMath::xyMotionStatsPass(longStats);
                        char metrics2010[224];
                        snprintf(metrics2010, sizeof(metrics2010),
                                 "rep=%lu;ref=2;pts=%lu;xmax=%ld;ymax=%ld;dx=%ld;dy=%ld;x_span=%lu;y_span=%lu;x_drift=%lu;y_drift=%lu;x_ret=%lu;y_ret=%lu;ret_err=%lu;move_to=%lu;home_to=%lu;guard=%lu;bound=%lu",
                                 static_cast<unsigned long>(longCompleted),
                                 static_cast<unsigned long>(kLongPointCount),
                                 static_cast<long>(kLongXMax),
                                 static_cast<long>(kLongYMax),
                                 static_cast<long>(kLongXMax - baseX),
                                 static_cast<long>(kLongYMax - kCableGuardMinY),
                                 static_cast<unsigned long>(xLongHomeStats.limitTriggerSpanSteps),
                                 static_cast<unsigned long>(yLongHomeStats.limitTriggerSpanSteps),
                                 static_cast<unsigned long>(longStats.xDriftMaxSteps),
                                 static_cast<unsigned long>(longStats.yDriftMaxSteps),
                                 static_cast<unsigned long>(longStats.xReturnErrorMaxSteps),
                                 static_cast<unsigned long>(longStats.yReturnErrorMaxSteps),
                                 static_cast<unsigned long>(longReturnError),
                                 static_cast<unsigned long>(longStats.moveTimeoutCount),
                                 static_cast<unsigned long>(longStats.homeTimeoutCount),
                                 static_cast<unsigned long>(longStats.guardViolationCount),
                                 static_cast<unsigned long>(longStats.boundViolationCount));
                        if (!runOne(2010, "motion_xy_long_travel_factory", longPass, metrics2010)) {
                          return finishSelfTestNow();
                        }
                        if (!longPass) {
                          (void)emitSkippedXyMotion(2011u, "long_travel_failed");
                          return finishSelfTestNow();
                        }

                        MotionQualificationMath::AxisHomeSample xRasterReference{};
                        MotionQualificationMath::AxisHomeSample yRasterReference{};
                        referenceHomeFailureStage = nullptr;
                        if (!runReferenceHomeSequence(xRasterReference,
                                                      yRasterReference,
                                                      "xy_raster_settle_home",
                                                      "xy_raster_reference_home",
                                                      referenceHomeFailureStage)) {
                          (void)emitSkippedXyMotion(2011u, referenceHomeFailureStage ? referenceHomeFailureStage : "raster_reference_home");
                          return finishSelfTestNow();
                        }

                        MotionQualificationMath::AxisHomeSample xRasterSamples[kRasterRepetitions]{};
                        MotionQualificationMath::AxisHomeSample yRasterSamples[kRasterRepetitions]{};
                        MotionQualificationMath::XyMotionStats rasterStats{};
                        rasterStats.points = (kRasterRows * kRasterCols) + 1u;
                        uint32_t rasterCompleted = 0u;
                        bool rasterMoveOk = true;
                        const MotionQualificationMath::XyPoint rasterAnchor{kRasterAnchorX, kRasterAnchorY};
                        for (uint32_t rep = 0u; rep < kRasterRepetitions; ++rep) {
                          sendProgressStage("xy_raster_repeatability");
                          bool repMovesCompleted = true;
                          bool repBoundViolation = false;
                          bool repGuardViolation = false;
                          for (uint32_t row = 0u; row < kRasterRows; ++row) {
                            for (uint32_t colIdx = 0u; colIdx < kRasterCols; ++colIdx) {
                              const uint32_t col = ((row & 1u) == 0u) ? colIdx : (kRasterCols - 1u - colIdx);
                              const MotionQualificationMath::XyPoint target{
                                  kRasterAnchorX + static_cast<int32_t>(col) * kRasterStep,
                                  kRasterAnchorY + static_cast<int32_t>(row) * kRasterStep};
                              maybeSendProgress("xy_raster_move");
                              if (!moveChecked(target,
                                               kRasterFeedHz,
                                               kRasterMoveTimeoutMs,
                                               rasterStats,
                                               repBoundViolation,
                                               repGuardViolation)) {
                                repMovesCompleted = false;
                                rasterMoveOk = false;
                                break;
                              }
                              if (_selfTestAbortRequested) {
                                break;
                              }
                            }
                            if (!repMovesCompleted || _selfTestAbortRequested) {
                              break;
                            }
                          }
                          if (repMovesCompleted) {
                            repMovesCompleted = moveChecked(rasterAnchor,
                                                            kRasterFeedHz,
                                                            kRasterMoveTimeoutMs,
                                                            rasterStats,
                                                            repBoundViolation,
                                                            repGuardViolation);
                          }
                          const bool homePassed = runXyHomeDiagnosticAttempt(xRasterSamples[rep],
                                                                             yRasterSamples[rep],
                                                                             kHomeFastHz,
                                                                             kHomeSlowHz,
                                                                             kHomeBackoffSteps,
                                                                             kHomeTimeoutMs);
                          MotionQualificationMath::recordXyMotionSample(rasterStats,
                                                                         xRasterReference.finalBackoffSteps,
                                                                         yRasterReference.finalBackoffSteps,
                                                                         Stepper::stepperX()->getPosition(),
                                                                         Stepper::stepperY()->getPosition(),
                                                                         xRasterReference.limitTriggerSteps,
                                                                         yRasterReference.limitTriggerSteps,
                                                                         xRasterSamples[rep],
                                                                         yRasterSamples[rep],
                                                                         repMovesCompleted && homePassed,
                                                                         repBoundViolation,
                                                                         repGuardViolation);
                          rasterCompleted++;
                          if (!repMovesCompleted || !homePassed || _selfTestAbortRequested) {
                            break;
                          }
                        }
                        rasterStats.repetitions = rasterCompleted;
                        const MotionQualificationMath::AxisHomeStats xRasterHomeStats =
                            MotionQualificationMath::summarizeAxisHomeSamples(xRasterSamples,
                                                                              rasterCompleted,
                                                                              kExpectedBackoffSteps);
                        const MotionQualificationMath::AxisHomeStats yRasterHomeStats =
                            MotionQualificationMath::summarizeAxisHomeSamples(yRasterSamples,
                                                                              rasterCompleted,
                                                                              kExpectedBackoffSteps);
                        uint32_t rasterReturnError = rasterStats.returnErrorMaxSteps;
                        if (xRasterHomeStats.returnErrorMaxSteps > rasterReturnError) rasterReturnError = xRasterHomeStats.returnErrorMaxSteps;
                        if (yRasterHomeStats.returnErrorMaxSteps > rasterReturnError) rasterReturnError = yRasterHomeStats.returnErrorMaxSteps;
                        const bool rasterPass = rasterMoveOk &&
                            (rasterCompleted == kRasterRepetitions) &&
                            MotionQualificationMath::xyMotionStatsPass(rasterStats);
                        char metrics2011[224];
                        snprintf(metrics2011, sizeof(metrics2011),
                                 "rep=%lu;ref=2;rows=%lu;cols=%lu;step=%ld;moves=%lu;xmax=%ld;ymax=%ld;dx=%ld;dy=%ld;x_span=%lu;y_span=%lu;x_drift=%lu;y_drift=%lu;x_ret=%lu;y_ret=%lu;ret_err=%lu;move_to=%lu;home_to=%lu;guard=%lu;bound=%lu",
                                 static_cast<unsigned long>(rasterCompleted),
                                 static_cast<unsigned long>(kRasterRows),
                                 static_cast<unsigned long>(kRasterCols),
                                 static_cast<long>(kRasterStep),
                                 static_cast<unsigned long>(rasterStats.points * rasterCompleted),
                                 static_cast<long>(kRasterAnchorX + static_cast<int32_t>(kRasterCols - 1u) * kRasterStep),
                                 static_cast<long>(kRasterAnchorY + static_cast<int32_t>(kRasterRows - 1u) * kRasterStep),
                                 static_cast<long>(static_cast<int32_t>(kRasterCols - 1u) * kRasterStep),
                                 static_cast<long>(static_cast<int32_t>(kRasterRows - 1u) * kRasterStep),
                                 static_cast<unsigned long>(xRasterHomeStats.limitTriggerSpanSteps),
                                 static_cast<unsigned long>(yRasterHomeStats.limitTriggerSpanSteps),
                                 static_cast<unsigned long>(rasterStats.xDriftMaxSteps),
                                 static_cast<unsigned long>(rasterStats.yDriftMaxSteps),
                                 static_cast<unsigned long>(rasterStats.xReturnErrorMaxSteps),
                                 static_cast<unsigned long>(rasterStats.yReturnErrorMaxSteps),
                                 static_cast<unsigned long>(rasterReturnError),
                                 static_cast<unsigned long>(rasterStats.moveTimeoutCount),
                                 static_cast<unsigned long>(rasterStats.homeTimeoutCount),
                                 static_cast<unsigned long>(rasterStats.guardViolationCount),
                                 static_cast<unsigned long>(rasterStats.boundViolationCount));
                        if (!runOne(2011, "motion_xy_raster_repeatability_factory", rasterPass, metrics2011)) {
                          return finishSelfTestNow();
                        }
                        return finishSelfTestNow();
                      }

                      if (runMotionEnvelopeSuite) {
                        static constexpr int32_t kSafeXMax = 45000;
                        static constexpr int32_t kSafeYMax = 35000;
                        static constexpr int32_t kCableGuardX = 1000;
                        static constexpr int32_t kCableGuardMinY = 500;
                        static constexpr int32_t kLongXMax = 44000;
                        static constexpr int32_t kLongYMax = 34000;
                        static constexpr int32_t kZLongMax = 80000;
                        static constexpr int32_t kZLongSafeMax = 80000;
                        static constexpr uint32_t kLongRepetitions = 3u;
                        static constexpr uint32_t kLongPointCount = 5u;
                        static constexpr uint32_t kDiagPointCount = 5u;
                        static constexpr uint32_t kLongFeedHz = 6000u;
                        static constexpr uint32_t kLongMoveTimeoutMs = 45000u;
                        static constexpr uint32_t kPlateRows = 16u;
                        static constexpr uint32_t kPlateCols = 24u;
                        static constexpr int32_t kPlateStartX = 43000;
                        static constexpr int32_t kPlateStartY = 13000;
                        static constexpr int32_t kPlateEndX = 33000;
                        static constexpr int32_t kPlateEndY = 30000;
                        static constexpr int32_t kEvapPlateZ = 91500;
                        static constexpr uint32_t kPlateFeedHz = 6000u;
                        static constexpr uint32_t kPlateMoveTimeoutMs = 12000u;
                        static constexpr uint32_t kZFeedHz = 30000u;
                        static constexpr uint32_t kZMoveTimeoutMs = 45000u;
                        static constexpr uint32_t kHomeFastHz = 30000u;
                        static constexpr uint32_t kHomeSlowHz = 3000u;
                        static constexpr uint32_t kHomeBackoffSteps = 400u;
                        static constexpr uint32_t kHomeTimeoutMs = 20000u;
                        static constexpr int32_t kExpectedBackoffSteps = 100;
                        static constexpr int32_t kTriggeredOffsetSteps = 200;
                        static constexpr uint32_t kTriggeredMoveHz = 3000u;
                        static constexpr uint32_t kTriggeredMoveTimeoutMs = 8000u;
                        const MotionQualificationMath::XySafetyEnvelope envelope{
                            0, kSafeXMax, 0, kSafeYMax, kCableGuardX, kCableGuardMinY};
                        const MotionQualificationMath::ZSafetyEnvelope zLongEnvelope{0, kZLongSafeMax};
                        const MotionQualificationMath::ZSafetyEnvelope evapZEnvelope{0, kEvapPlateZ};
                        const uint32_t zAxisMaxSpeedHz = Stepper::stepperZ()->maxSpeedHz();
                        const uint32_t zAxisAccelStepsPerSec2 =
                            static_cast<uint32_t>(Stepper::stepperZ()->accelStepsPerSec2());

                        auto emitSkippedMotionEnvelope = [&](uint16_t firstTestId, const char* phase) -> bool {
                          char xyMetrics[192];
                          snprintf(xyMetrics, sizeof(xyMetrics),
                                   "phase=%s;rep=0;ref=0;pts=0;xmax=%ld;ymax=%ld;dx=0;dy=0;x_span=0;y_span=0;x_drift=0;y_drift=0;x_ret=0;y_ret=0;ret_err=0;move_to=0;home_to=1;guard=0;bound=0",
                                   phase,
                                   static_cast<long>(kSafeXMax),
                                   static_cast<long>(kSafeYMax));
                          char zMetrics[192];
                          snprintf(zMetrics, sizeof(zMetrics),
                                   "phase=%s;rep=0;ref=0;xy_to=0;zhz=%lu;zcap=%lu;zacc=%lu;zmax=%ld;dz=0;z_span=0;z_drift=0;z_ret=0;ret_err=0;move_to=0;home_to=1;guard=0;bound=0",
                                   phase,
                                   static_cast<unsigned long>(kZFeedHz),
                                   static_cast<unsigned long>(zAxisMaxSpeedHz),
                                   static_cast<unsigned long>(zAxisAccelStepsPerSec2),
                                   static_cast<long>(kZLongMax));
                          char limitMetrics[176];
                          snprintf(limitMetrics, sizeof(limitMetrics),
                                   "phase=%s;axis=xyz;offset=%ld;x_span=0;y_span=0;z_span=0;x_drift=0;y_drift=0;z_drift=0;move_to=0;home_to=1;limit_start=1",
                                   phase,
                                   static_cast<long>(kTriggeredOffsetSteps));
                          if ((firstTestId <= 2012u) &&
                              !runOne(2012, "motion_xy_reverse_travel_factory", false, xyMetrics)) return false;
                          if ((firstTestId <= 2013u) &&
                              !runOne(2013, "motion_xy_diagonal_factory", false, xyMetrics)) return false;
                          if ((firstTestId <= 2014u) &&
                              !runOne(2014, "motion_384_plate_raster_factory", false, xyMetrics)) return false;
                          if ((firstTestId <= 2015u) &&
                              !runOne(2015, "motion_z_long_travel_factory", false, zMetrics)) return false;
                          if ((firstTestId <= 2016u) &&
                              !runOne(2016, "motion_limit_triggered_home_fact", false, limitMetrics)) return false;
                          return true;
                        };

                        auto checkPointSafety = [&](const MotionQualificationMath::XyPoint& point,
                                                    MotionQualificationMath::XyMotionStats& stats,
                                                    bool& boundViolation,
                                                    bool& guardViolation) -> bool {
                          const bool inBounds = MotionQualificationMath::xyPointInBounds(point, envelope);
                          const bool guardOk = MotionQualificationMath::xyPointPassesCableGuard(point, envelope);
                          if (!inBounds) {
                            boundViolation = true;
                            stats.boundViolationCount++;
                          }
                          if (!guardOk) {
                            guardViolation = true;
                            stats.guardViolationCount++;
                          }
                          return inBounds && guardOk;
                        };

                        auto moveChecked = [&](const MotionQualificationMath::XyPoint& target,
                                               uint32_t feedHz,
                                               uint32_t timeoutMs,
                                               MotionQualificationMath::XyMotionStats& stats,
                                               bool& boundViolation,
                                               bool& guardViolation) -> bool {
                          if (!checkPointSafety(target, stats, boundViolation, guardViolation)) {
                            return false;
                          }
                          const bool reached = moveGantryToWithTimeout(target.x, target.y, feedHz, timeoutMs);
                          if (!reached) {
                            return false;
                          }
                          const GantryPosition pos = Gantry::instance()->getPosition();
                          return checkPointSafety({pos.x, pos.y}, stats, boundViolation, guardViolation);
                        };

                        auto moveAxisToWithTimeout = [&](Stepper* stepper,
                                                         EventBits_t doneBit,
                                                         int32_t target,
                                                         uint32_t feedHz,
                                                         uint32_t timeoutMs) -> bool {
                          const int32_t current = stepper->getPosition();
                          const int64_t delta64 = static_cast<int64_t>(target) - static_cast<int64_t>(current);
                          if (delta64 == 0) {
                            return true;
                          }
                          const bool direction = delta64 >= 0;
                          const uint32_t steps = static_cast<uint32_t>(direction ? delta64 : -delta64);
                          xEventGroupClearBits(_doneEvents, doneBit);
                          stepper->enableMotor();
                          stepper->move(direction, steps, feedHz, 0u);
                          const bool reached = waitBitsWithTimeout(doneBit, timeoutMs);
                          if (!reached) {
                            stepper->stop();
                          }
                          return reached;
                        };

                        auto runXyReferenceHomeSequence = [&](MotionQualificationMath::AxisHomeSample& xReference,
                                                              MotionQualificationMath::AxisHomeSample& yReference,
                                                              const char* settleStage,
                                                              const char* referenceStage,
                                                              const char*& failedStage) -> bool {
                          MotionQualificationMath::AxisHomeSample xSettle{};
                          MotionQualificationMath::AxisHomeSample ySettle{};
                          failedStage = settleStage;
                          sendProgressStage(settleStage);
                          if (!runXyHomeDiagnosticAttempt(xSettle,
                                                          ySettle,
                                                          kHomeFastHz,
                                                          kHomeSlowHz,
                                                          kHomeBackoffSteps,
                                                          kHomeTimeoutMs)) {
                            return false;
                          }
                          failedStage = referenceStage;
                          sendProgressStage(referenceStage);
                          if (!runXyHomeDiagnosticAttempt(xReference,
                                                          yReference,
                                                          kHomeFastHz,
                                                          kHomeSlowHz,
                                                          kHomeBackoffSteps,
                                                          kHomeTimeoutMs)) {
                            return false;
                          }
                          failedStage = nullptr;
                          return true;
                        };

                        auto runZReferenceHomeSequence = [&](MotionQualificationMath::AxisHomeSample& zReference,
                                                             const char* settleStage,
                                                             const char* referenceStage,
                                                             const char*& failedStage) -> bool {
                          MotionQualificationMath::AxisHomeSample zSettle{};
                          failedStage = settleStage;
                          sendProgressStage(settleStage);
                          if (!runAxisHomeDiagnosticAttempt(Stepper::stepperZ(),
                                                            BIT_HOME_Z_DONE,
                                                            zSettle,
                                                            kHomeFastHz,
                                                            kHomeSlowHz,
                                                            kHomeBackoffSteps,
                                                            kHomeTimeoutMs)) {
                            return false;
                          }
                          failedStage = referenceStage;
                          sendProgressStage(referenceStage);
                          if (!runAxisHomeDiagnosticAttempt(Stepper::stepperZ(),
                                                            BIT_HOME_Z_DONE,
                                                            zReference,
                                                            kHomeFastHz,
                                                            kHomeSlowHz,
                                                            kHomeBackoffSteps,
                                                            kHomeTimeoutMs)) {
                            return false;
                          }
                          failedStage = nullptr;
                          return true;
                        };

                        auto worstOf = [](uint32_t a, uint32_t b) -> uint32_t {
                          return (a > b) ? a : b;
                        };

                        auto emitXyPathResult = [&](uint16_t testId,
                                                    const char* name,
                                                    const MotionQualificationMath::XyMotionStats& stats,
                                                    const MotionQualificationMath::AxisHomeStats& xHomeStats,
                                                    const MotionQualificationMath::AxisHomeStats& yHomeStats,
                                                    uint32_t completed,
                                                    uint32_t expectedRepetitions,
                                                    uint32_t pointCount,
                                                    int32_t xmax,
                                                    int32_t ymax,
                                                    int32_t dx,
                                                    int32_t dy,
                                                    bool movesOk) -> bool {
                          uint32_t returnError = stats.returnErrorMaxSteps;
                          returnError = worstOf(returnError, xHomeStats.returnErrorMaxSteps);
                          returnError = worstOf(returnError, yHomeStats.returnErrorMaxSteps);
                          const bool pass = movesOk &&
                              (completed == expectedRepetitions) &&
                              MotionQualificationMath::xyMotionStatsPass(stats);
                          char metrics[224];
                          snprintf(metrics, sizeof(metrics),
                                   "rep=%lu;ref=2;pts=%lu;xmax=%ld;ymax=%ld;dx=%ld;dy=%ld;x_span=%lu;y_span=%lu;x_drift=%lu;y_drift=%lu;x_ret=%lu;y_ret=%lu;ret_err=%lu;move_to=%lu;home_to=%lu;guard=%lu;bound=%lu",
                                   static_cast<unsigned long>(completed),
                                   static_cast<unsigned long>(pointCount),
                                   static_cast<long>(xmax),
                                   static_cast<long>(ymax),
                                   static_cast<long>(dx),
                                   static_cast<long>(dy),
                                   static_cast<unsigned long>(xHomeStats.limitTriggerSpanSteps),
                                   static_cast<unsigned long>(yHomeStats.limitTriggerSpanSteps),
                                   static_cast<unsigned long>(stats.xDriftMaxSteps),
                                   static_cast<unsigned long>(stats.yDriftMaxSteps),
                                   static_cast<unsigned long>(stats.xReturnErrorMaxSteps),
                                   static_cast<unsigned long>(stats.yReturnErrorMaxSteps),
                                   static_cast<unsigned long>(returnError),
                                   static_cast<unsigned long>(stats.moveTimeoutCount),
                                   static_cast<unsigned long>(stats.homeTimeoutCount),
                                   static_cast<unsigned long>(stats.guardViolationCount),
                                   static_cast<unsigned long>(stats.boundViolationCount));
                          return runOne(testId, name, pass, metrics) && pass;
                        };

                        MotionQualificationMath::AxisHomeSample xReference{};
                        MotionQualificationMath::AxisHomeSample yReference{};
                        const char* referenceHomeFailureStage = nullptr;
                        if (!runZClearanceHomePreflight("envelope_z_clearance_home",
                                                        kHomeFastHz,
                                                        kHomeSlowHz,
                                                        kHomeBackoffSteps,
                                                        kHomeTimeoutMs)) {
                          (void)emitSkippedMotionEnvelope(2012u, "z_clearance_home");
                          return finishSelfTestNow();
                        }
                        if (!runXyReferenceHomeSequence(xReference,
                                                        yReference,
                                                        "xy_reverse_settle_home",
                                                        "xy_reverse_reference_home",
                                                        referenceHomeFailureStage)) {
                          (void)emitSkippedMotionEnvelope(2012u, referenceHomeFailureStage ? referenceHomeFailureStage : "reference_home");
                          return finishSelfTestNow();
                        }
                        const int32_t baseX = xReference.finalBackoffSteps;
                        const int32_t baseY = yReference.finalBackoffSteps;
                        const MotionQualificationMath::XyPoint reverseTargets[kLongPointCount] = {
                            {baseX, kCableGuardMinY},
                            {baseX, kLongYMax},
                            {kLongXMax, kLongYMax},
                            {kLongXMax, kCableGuardMinY},
                            {baseX, kCableGuardMinY},
                        };
                        MotionQualificationMath::AxisHomeSample xReverseSamples[kLongRepetitions]{};
                        MotionQualificationMath::AxisHomeSample yReverseSamples[kLongRepetitions]{};
                        MotionQualificationMath::XyMotionStats reverseStats{};
                        reverseStats.points = kLongPointCount;
                        uint32_t reverseCompleted = 0u;
                        bool reverseMovesOk = true;
                        for (uint32_t rep = 0u; rep < kLongRepetitions; ++rep) {
                          sendProgressStage("xy_reverse_travel");
                          bool repMovesCompleted = true;
                          bool repBoundViolation = false;
                          bool repGuardViolation = false;
                          for (uint32_t point = 0u; point < kLongPointCount; ++point) {
                            maybeSendProgress("xy_reverse_move");
                            if (!moveChecked(reverseTargets[point],
                                             kLongFeedHz,
                                             kLongMoveTimeoutMs,
                                             reverseStats,
                                             repBoundViolation,
                                             repGuardViolation)) {
                              repMovesCompleted = false;
                              reverseMovesOk = false;
                              break;
                            }
                            if (_selfTestAbortRequested) {
                              break;
                            }
                          }
                          const bool homePassed = runXyHomeDiagnosticAttempt(xReverseSamples[rep],
                                                                             yReverseSamples[rep],
                                                                             kHomeFastHz,
                                                                             kHomeSlowHz,
                                                                             kHomeBackoffSteps,
                                                                             kHomeTimeoutMs);
                          MotionQualificationMath::recordXyMotionSample(reverseStats,
                                                                         baseX,
                                                                         baseY,
                                                                         Stepper::stepperX()->getPosition(),
                                                                         Stepper::stepperY()->getPosition(),
                                                                         xReference.limitTriggerSteps,
                                                                         yReference.limitTriggerSteps,
                                                                         xReverseSamples[rep],
                                                                         yReverseSamples[rep],
                                                                         repMovesCompleted && homePassed,
                                                                         repBoundViolation,
                                                                         repGuardViolation);
                          reverseCompleted++;
                          if (!repMovesCompleted || !homePassed || _selfTestAbortRequested) {
                            break;
                          }
                        }
                        reverseStats.repetitions = reverseCompleted;
                        const MotionQualificationMath::AxisHomeStats xReverseHomeStats =
                            MotionQualificationMath::summarizeAxisHomeSamples(xReverseSamples,
                                                                              reverseCompleted,
                                                                              kExpectedBackoffSteps);
                        const MotionQualificationMath::AxisHomeStats yReverseHomeStats =
                            MotionQualificationMath::summarizeAxisHomeSamples(yReverseSamples,
                                                                              reverseCompleted,
                                                                              kExpectedBackoffSteps);
                        if (!emitXyPathResult(2012,
                                              "motion_xy_reverse_travel_factory",
                                              reverseStats,
                                              xReverseHomeStats,
                                              yReverseHomeStats,
                                              reverseCompleted,
                                              kLongRepetitions,
                                              kLongPointCount,
                                              kLongXMax,
                                              kLongYMax,
                                              kLongXMax - baseX,
                                              kLongYMax - kCableGuardMinY,
                                              reverseMovesOk)) {
                          (void)emitSkippedMotionEnvelope(2013u, "xy_reverse_failed");
                          return finishSelfTestNow();
                        }

                        MotionQualificationMath::AxisHomeSample xDiagReference{};
                        MotionQualificationMath::AxisHomeSample yDiagReference{};
                        referenceHomeFailureStage = nullptr;
                        if (!runXyReferenceHomeSequence(xDiagReference,
                                                        yDiagReference,
                                                        "xy_diagonal_settle_home",
                                                        "xy_diagonal_reference_home",
                                                        referenceHomeFailureStage)) {
                          (void)emitSkippedMotionEnvelope(2013u, referenceHomeFailureStage ? referenceHomeFailureStage : "diagonal_reference_home");
                          return finishSelfTestNow();
                        }
                        const MotionQualificationMath::XyPoint diagTargets[kDiagPointCount] = {
                            {xDiagReference.finalBackoffSteps, kCableGuardMinY},
                            {kLongXMax, kLongYMax},
                            {xDiagReference.finalBackoffSteps, kLongYMax},
                            {kLongXMax, kCableGuardMinY},
                            {xDiagReference.finalBackoffSteps, kCableGuardMinY},
                        };
                        MotionQualificationMath::AxisHomeSample xDiagSamples[kLongRepetitions]{};
                        MotionQualificationMath::AxisHomeSample yDiagSamples[kLongRepetitions]{};
                        MotionQualificationMath::XyMotionStats diagStats{};
                        diagStats.points = kDiagPointCount;
                        uint32_t diagCompleted = 0u;
                        bool diagMovesOk = true;
                        for (uint32_t rep = 0u; rep < kLongRepetitions; ++rep) {
                          sendProgressStage("xy_diagonal_travel");
                          bool repMovesCompleted = true;
                          bool repBoundViolation = false;
                          bool repGuardViolation = false;
                          for (uint32_t point = 0u; point < kDiagPointCount; ++point) {
                            maybeSendProgress("xy_diagonal_move");
                            if (!moveChecked(diagTargets[point],
                                             kLongFeedHz,
                                             kLongMoveTimeoutMs,
                                             diagStats,
                                             repBoundViolation,
                                             repGuardViolation)) {
                              repMovesCompleted = false;
                              diagMovesOk = false;
                              break;
                            }
                            if (_selfTestAbortRequested) {
                              break;
                            }
                          }
                          const bool homePassed = runXyHomeDiagnosticAttempt(xDiagSamples[rep],
                                                                             yDiagSamples[rep],
                                                                             kHomeFastHz,
                                                                             kHomeSlowHz,
                                                                             kHomeBackoffSteps,
                                                                             kHomeTimeoutMs);
                          MotionQualificationMath::recordXyMotionSample(diagStats,
                                                                         xDiagReference.finalBackoffSteps,
                                                                         yDiagReference.finalBackoffSteps,
                                                                         Stepper::stepperX()->getPosition(),
                                                                         Stepper::stepperY()->getPosition(),
                                                                         xDiagReference.limitTriggerSteps,
                                                                         yDiagReference.limitTriggerSteps,
                                                                         xDiagSamples[rep],
                                                                         yDiagSamples[rep],
                                                                         repMovesCompleted && homePassed,
                                                                         repBoundViolation,
                                                                         repGuardViolation);
                          diagCompleted++;
                          if (!repMovesCompleted || !homePassed || _selfTestAbortRequested) {
                            break;
                          }
                        }
                        diagStats.repetitions = diagCompleted;
                        const MotionQualificationMath::AxisHomeStats xDiagHomeStats =
                            MotionQualificationMath::summarizeAxisHomeSamples(xDiagSamples,
                                                                              diagCompleted,
                                                                              kExpectedBackoffSteps);
                        const MotionQualificationMath::AxisHomeStats yDiagHomeStats =
                            MotionQualificationMath::summarizeAxisHomeSamples(yDiagSamples,
                                                                              diagCompleted,
                                                                              kExpectedBackoffSteps);
                        if (!emitXyPathResult(2013,
                                              "motion_xy_diagonal_factory",
                                              diagStats,
                                              xDiagHomeStats,
                                              yDiagHomeStats,
                                              diagCompleted,
                                              kLongRepetitions,
                                              kDiagPointCount,
                                              kLongXMax,
                                              kLongYMax,
                                              kLongXMax - xDiagReference.finalBackoffSteps,
                                              kLongYMax - kCableGuardMinY,
                                              diagMovesOk)) {
                          (void)emitSkippedMotionEnvelope(2014u, "xy_diagonal_failed");
                          return finishSelfTestNow();
                        }

                        MotionQualificationMath::AxisHomeSample xPlateReference{};
                        MotionQualificationMath::AxisHomeSample yPlateReference{};
                        referenceHomeFailureStage = nullptr;
                        if (!runXyReferenceHomeSequence(xPlateReference,
                                                        yPlateReference,
                                                        "xy_plate_settle_home",
                                                        "xy_plate_reference_home",
                                                        referenceHomeFailureStage)) {
                          (void)emitSkippedMotionEnvelope(2014u, referenceHomeFailureStage ? referenceHomeFailureStage : "plate_reference_home");
                          return finishSelfTestNow();
                        }
                        MotionQualificationMath::AxisHomeSample xPlateSample{};
                        MotionQualificationMath::AxisHomeSample yPlateSample{};
                        MotionQualificationMath::XyMotionStats plateStats{};
                        plateStats.points = (kPlateRows * kPlateCols) + 3u;
                        bool plateMovesCompleted = true;
                        bool plateBoundViolation = false;
                        bool plateGuardViolation = false;
                        uint32_t plateConfirmed = 0u;
                        uint32_t plateZMoveTimeout = 0u;
                        uint32_t plateZHomeTimeout = 0u;
                        uint32_t plateReturnFailed = 0u;
                        bool plateZMoveStarted = false;
                        const MotionQualificationMath::XyPoint plateStart{kPlateStartX, kPlateStartY};
                        sendProgressStage("xy_plate_setup_anchor");
                        plateMovesCompleted = moveChecked(plateStart,
                                                          kPlateFeedHz,
                                                          kPlateMoveTimeoutMs,
                                                          plateStats,
                                                          plateBoundViolation,
                                                          plateGuardViolation);
                        if (plateMovesCompleted && !waitForOperatorResume("evap_plate_confirm")) {
                          return finishSelfTestNow();
                        }
                        if (plateMovesCompleted) {
                          plateConfirmed = 1u;
                          if (!MotionQualificationMath::zPositionInBounds(kEvapPlateZ, evapZEnvelope)) {
                            plateBoundViolation = true;
                            plateStats.boundViolationCount++;
                            plateMovesCompleted = false;
                          } else {
                            plateZMoveStarted = true;
                            if (!moveAxisToWithTimeout(Stepper::stepperZ(),
                                                       BIT_STEPPER3_DONE,
                                                       kEvapPlateZ,
                                                       kZFeedHz,
                                                       kZMoveTimeoutMs)) {
                              plateZMoveTimeout = 1u;
                              plateStats.moveTimeoutCount++;
                              plateMovesCompleted = false;
                            } else if (!MotionQualificationMath::zPositionInBounds(Stepper::stepperZ()->getPosition(), evapZEnvelope)) {
                              plateBoundViolation = true;
                              plateStats.boundViolationCount++;
                              plateMovesCompleted = false;
                            }
                          }
                        }
                        if (plateMovesCompleted) {
                          sendProgressStage("xy_plate_raster");
                          for (uint32_t row = 0u; row < kPlateRows; ++row) {
                            const int32_t x = MotionQualificationMath::interpolateEndpoint(
                                kPlateStartX, kPlateEndX, row, kPlateRows);
                            for (uint32_t colIdx = 0u; colIdx < kPlateCols; ++colIdx) {
                              const uint32_t col = ((row & 1u) == 0u) ? colIdx : (kPlateCols - 1u - colIdx);
                              const int32_t y = MotionQualificationMath::interpolateEndpoint(
                                  kPlateStartY, kPlateEndY, col, kPlateCols);
                              maybeSendProgress("xy_plate_raster_move");
                              if (!moveChecked({x, y},
                                               kPlateFeedHz,
                                               kPlateMoveTimeoutMs,
                                               plateStats,
                                               plateBoundViolation,
                                               plateGuardViolation)) {
                                plateMovesCompleted = false;
                                break;
                              }
                              if (_selfTestAbortRequested) {
                                break;
                              }
                            }
                            if (!plateMovesCompleted || _selfTestAbortRequested) {
                              break;
                            }
                          }
                        }
                        if (plateMovesCompleted) {
                          sendProgressStage("xy_plate_return_start");
                          const bool returnedToStart = moveChecked(plateStart,
                                                                   kPlateFeedHz,
                                                                   kPlateMoveTimeoutMs,
                                                                   plateStats,
                                                                   plateBoundViolation,
                                                                   plateGuardViolation);
                          if (!returnedToStart) {
                            plateReturnFailed = 1u;
                            plateMovesCompleted = false;
                          }
                        }
                        if (!_selfTestAbortRequested && plateZMoveStarted) {
                          MotionQualificationMath::AxisHomeSample zPlateHome{};
                          sendProgressStage("xy_plate_z_home_after_raster");
                          if (!runAxisHomeDiagnosticAttempt(Stepper::stepperZ(),
                                                            BIT_HOME_Z_DONE,
                                                            zPlateHome,
                                                            kHomeFastHz,
                                                            kHomeSlowHz,
                                                            kHomeBackoffSteps,
                                                            kHomeTimeoutMs)) {
                            plateZHomeTimeout = 1u;
                            plateMovesCompleted = false;
                          }
                        }
                        const MotionQualificationMath::XyPoint plateHomeAnchor{
                            xPlateReference.finalBackoffSteps,
                            kCableGuardMinY};
                        if (plateMovesCompleted) {
                          sendProgressStage("xy_plate_home_anchor");
                          plateMovesCompleted = moveChecked(plateHomeAnchor,
                                                            kPlateFeedHz,
                                                            kPlateMoveTimeoutMs,
                                                            plateStats,
                                                            plateBoundViolation,
                                                            plateGuardViolation);
                        }
                        const bool plateHomePassed = plateMovesCompleted &&
                            runXyHomeDiagnosticAttempt(xPlateSample,
                                                       yPlateSample,
                                                       kHomeFastHz,
                                                       kHomeSlowHz,
                                                       kHomeBackoffSteps,
                                                       kHomeTimeoutMs);
                        MotionQualificationMath::recordXyMotionSample(plateStats,
                                                                       xPlateReference.finalBackoffSteps,
                                                                       yPlateReference.finalBackoffSteps,
                                                                       Stepper::stepperX()->getPosition(),
                                                                       Stepper::stepperY()->getPosition(),
                                                                       xPlateReference.limitTriggerSteps,
                                                                       yPlateReference.limitTriggerSteps,
                                                                       xPlateSample,
                                                                       yPlateSample,
                                                                       plateMovesCompleted && plateHomePassed,
                                                                       plateBoundViolation,
                                                                       plateGuardViolation);
                        plateStats.repetitions = (plateMovesCompleted && plateHomePassed) ? 1u : 0u;
                        const MotionQualificationMath::AxisHomeStats xPlateHomeStats =
                            MotionQualificationMath::summarizeAxisHomeSamples(&xPlateSample,
                                                                              1u,
                                                                              kExpectedBackoffSteps);
                        const MotionQualificationMath::AxisHomeStats yPlateHomeStats =
                            MotionQualificationMath::summarizeAxisHomeSamples(&yPlateSample,
                                                                              1u,
                                                                              kExpectedBackoffSteps);
                        uint32_t plateReturnError = plateStats.returnErrorMaxSteps;
                        plateReturnError = worstOf(plateReturnError, xPlateHomeStats.returnErrorMaxSteps);
                        plateReturnError = worstOf(plateReturnError, yPlateHomeStats.returnErrorMaxSteps);
                        const bool platePass = plateMovesCompleted &&
                            plateHomePassed &&
                            (plateConfirmed == 1u) &&
                            (plateZMoveTimeout == 0u) &&
                            (plateZHomeTimeout == 0u) &&
                            MotionQualificationMath::xyMotionStatsPass(plateStats);
                        char metrics2014[224];
                        snprintf(metrics2014, sizeof(metrics2014),
                                 "pc=%lu;pz=%ld;z_to=%lu;z_home_to=%lu;rep=%lu;ref=2;rows=%lu;cols=%lu;moves=%lu;x_span=%lu;y_span=%lu;x_drift=%lu;y_drift=%lu;x_ret=%lu;y_ret=%lu;ret_err=%lu;move_to=%lu;home_to=%lu;guard=%lu;bound=%lu",
                                 static_cast<unsigned long>(plateConfirmed),
                                 static_cast<long>(kEvapPlateZ),
                                 static_cast<unsigned long>(plateZMoveTimeout),
                                 static_cast<unsigned long>(plateZHomeTimeout),
                                 static_cast<unsigned long>(plateStats.repetitions),
                                 static_cast<unsigned long>(kPlateRows),
                                 static_cast<unsigned long>(kPlateCols),
                                 static_cast<unsigned long>(plateStats.points),
                                 static_cast<unsigned long>(xPlateHomeStats.limitTriggerSpanSteps),
                                 static_cast<unsigned long>(yPlateHomeStats.limitTriggerSpanSteps),
                                 static_cast<unsigned long>(plateStats.xDriftMaxSteps),
                                 static_cast<unsigned long>(plateStats.yDriftMaxSteps),
                                 static_cast<unsigned long>(plateStats.xReturnErrorMaxSteps),
                                 static_cast<unsigned long>(plateStats.yReturnErrorMaxSteps),
                                 static_cast<unsigned long>(plateReturnError),
                                 static_cast<unsigned long>(plateStats.moveTimeoutCount),
                                 static_cast<unsigned long>(plateStats.homeTimeoutCount),
                                 static_cast<unsigned long>(plateStats.guardViolationCount),
                                 static_cast<unsigned long>(plateStats.boundViolationCount));
                        if (!runOne(2014, "motion_384_plate_raster_factory", platePass, metrics2014)) {
                          return finishSelfTestNow();
                        }
                        if (!platePass) {
                          const char* plateFailurePhase = "xy_plate_failed";
                          if (plateConfirmed == 0u || plateZMoveTimeout != 0u) {
                            plateFailurePhase = "evap_plate_setup";
                          } else if (plateReturnFailed != 0u || plateZHomeTimeout != 0u) {
                            plateFailurePhase = "evap_plate_teardown";
                          }
                          (void)emitSkippedMotionEnvelope(2015u, plateFailurePhase);
                          return finishSelfTestNow();
                        }

                        const MotionQualificationMath::XyPoint zLongAnchor{kPlateStartX, kPlateStartY};
                        MotionQualificationMath::XyMotionStats zAnchorStats{};
                        bool zAnchorBoundViolation = false;
                        bool zAnchorGuardViolation = false;
                        uint32_t zAnchorMoveTimeouts = 0u;
                        sendProgressStage("z_long_xy_anchor");
                        const bool zAnchorMoved = moveChecked(zLongAnchor,
                                                              kPlateFeedHz,
                                                              kPlateMoveTimeoutMs,
                                                              zAnchorStats,
                                                              zAnchorBoundViolation,
                                                              zAnchorGuardViolation);
                        if (!zAnchorMoved) {
                          if (!zAnchorBoundViolation && !zAnchorGuardViolation) {
                            zAnchorMoveTimeouts = 1u;
                          }
                          char metrics2015[224];
                          snprintf(metrics2015, sizeof(metrics2015),
                                   "phase=z_xy_anchor;rep=0;ref=0;anchor_x=%ld;anchor_y=%ld;xy_to=%lu;zhz=%lu;zcap=%lu;zacc=%lu;zmax=%ld;dz=0;z_span=0;z_drift=0;z_ret=0;ret_err=0;move_to=%lu;home_to=0;guard=%lu;bound=%lu",
                                   static_cast<long>(zLongAnchor.x),
                                   static_cast<long>(zLongAnchor.y),
                                   static_cast<unsigned long>(zAnchorMoveTimeouts),
                                   static_cast<unsigned long>(kZFeedHz),
                                   static_cast<unsigned long>(zAxisMaxSpeedHz),
                                   static_cast<unsigned long>(zAxisAccelStepsPerSec2),
                                   static_cast<long>(kZLongMax),
                                   static_cast<unsigned long>(zAnchorMoveTimeouts),
                                   static_cast<unsigned long>(zAnchorGuardViolation ? 1u : 0u),
                                   static_cast<unsigned long>(zAnchorBoundViolation ? 1u : 0u));
                          if (!runOne(2015, "motion_z_long_travel_factory", false, metrics2015)) {
                            return finishSelfTestNow();
                          }
                          (void)emitSkippedMotionEnvelope(2016u, "z_xy_anchor_failed");
                          return finishSelfTestNow();
                        }

                        MotionQualificationMath::AxisHomeSample zReference{};
                        referenceHomeFailureStage = nullptr;
                        if (!runZReferenceHomeSequence(zReference,
                                                       "z_long_settle_home",
                                                       "z_long_reference_home",
                                                       referenceHomeFailureStage)) {
                          (void)emitSkippedMotionEnvelope(2015u, referenceHomeFailureStage ? referenceHomeFailureStage : "z_reference_home");
                          return finishSelfTestNow();
                        }
                        MotionQualificationMath::AxisHomeSample zSamples[kLongRepetitions]{};
                        uint32_t zCompleted = 0u;
                        uint32_t zMoveTimeouts = 0u;
                        uint32_t zBoundViolations = 0u;
                        uint32_t zReturnErrorMax = 0u;
                        uint32_t zDriftMax = 0u;
                        bool zMovesOk = true;
                        for (uint32_t rep = 0u; rep < kLongRepetitions; ++rep) {
                          sendProgressStage("z_long_travel");
                          bool repMoveOk = true;
                          if (!MotionQualificationMath::zPositionInBounds(kZLongMax, zLongEnvelope)) {
                            zBoundViolations++;
                            repMoveOk = false;
                          }
                          if (repMoveOk &&
                              !moveAxisToWithTimeout(Stepper::stepperZ(),
                                                     BIT_STEPPER3_DONE,
                                                     kZLongMax,
                                                     kZFeedHz,
                                                     kZMoveTimeoutMs)) {
                            zMoveTimeouts++;
                            repMoveOk = false;
                          }
                          if (!MotionQualificationMath::zPositionInBounds(Stepper::stepperZ()->getPosition(), zLongEnvelope)) {
                            zBoundViolations++;
                            repMoveOk = false;
                          }
                          if (repMoveOk &&
                              !moveAxisToWithTimeout(Stepper::stepperZ(),
                                                     BIT_STEPPER3_DONE,
                                                     zReference.finalBackoffSteps,
                                                     kZFeedHz,
                                                     kZMoveTimeoutMs)) {
                            zMoveTimeouts++;
                            repMoveOk = false;
                          }
                          const uint32_t zRet = MotionQualificationMath::absDiffSteps(
                              Stepper::stepperZ()->getPosition(), zReference.finalBackoffSteps);
                          zReturnErrorMax = worstOf(zReturnErrorMax, zRet);
                          const bool homePassed = runAxisHomeDiagnosticAttempt(Stepper::stepperZ(),
                                                                               BIT_HOME_Z_DONE,
                                                                               zSamples[rep],
                                                                               kHomeFastHz,
                                                                               kHomeSlowHz,
                                                                               kHomeBackoffSteps,
                                                                               kHomeTimeoutMs);
                          zDriftMax = worstOf(zDriftMax,
                                              MotionQualificationMath::absDiffSteps(zSamples[rep].limitTriggerSteps,
                                                                                    zReference.limitTriggerSteps));
                          zCompleted++;
                          if (!repMoveOk || !homePassed || _selfTestAbortRequested) {
                            zMovesOk = false;
                            break;
                          }
                        }
                        const MotionQualificationMath::AxisHomeStats zHomeStats =
                            MotionQualificationMath::summarizeAxisHomeSamples(zSamples,
                                                                              zCompleted,
                                                                              kExpectedBackoffSteps);
                        uint32_t zReturnError = worstOf(zReturnErrorMax, zHomeStats.returnErrorMaxSteps);
                        const bool zPass = zMovesOk &&
                            (zCompleted == kLongRepetitions) &&
                            (zMoveTimeouts == 0u) &&
                            (zHomeStats.homeTimeoutCount == 0u) &&
                            (zHomeStats.moveTimeoutCount == 0u) &&
                            (zBoundViolations == 0u);
                        char metrics2015[224];
                        snprintf(metrics2015, sizeof(metrics2015),
                                 "rep=%lu;ref=2;anchor_x=%ld;anchor_y=%ld;xy_to=%lu;zhz=%lu;zcap=%lu;zacc=%lu;zmax=%ld;dz=%ld;z_span=%lu;z_drift=%lu;z_ret=%lu;ret_err=%lu;move_to=%lu;home_to=%lu;guard=%lu;bound=%lu",
                                 static_cast<unsigned long>(zCompleted),
                                 static_cast<long>(zLongAnchor.x),
                                 static_cast<long>(zLongAnchor.y),
                                 static_cast<unsigned long>(zAnchorMoveTimeouts),
                                 static_cast<unsigned long>(kZFeedHz),
                                 static_cast<unsigned long>(zAxisMaxSpeedHz),
                                 static_cast<unsigned long>(zAxisAccelStepsPerSec2),
                                 static_cast<long>(kZLongMax),
                                 static_cast<long>(kZLongMax - zReference.finalBackoffSteps),
                                 static_cast<unsigned long>(zHomeStats.limitTriggerSpanSteps),
                                 static_cast<unsigned long>(zDriftMax),
                                 static_cast<unsigned long>(zReturnErrorMax),
                                 static_cast<unsigned long>(zReturnError),
                                 static_cast<unsigned long>(zAnchorMoveTimeouts + zMoveTimeouts + zHomeStats.moveTimeoutCount),
                                 static_cast<unsigned long>(zHomeStats.homeTimeoutCount),
                                 static_cast<unsigned long>(zAnchorGuardViolation ? 1u : 0u),
                                 static_cast<unsigned long>(zBoundViolations));
                        if (!runOne(2015, "motion_z_long_travel_factory", zPass, metrics2015)) {
                          return finishSelfTestNow();
                        }
                        if (!zPass) {
                          (void)emitSkippedMotionEnvelope(2016u, "z_long_failed");
                          return finishSelfTestNow();
                        }

                        sendProgressStage("triggered_limit_home");
                        uint32_t triggeredMoveTimeouts = 0u;
                        uint32_t triggeredHomeTimeouts = 0u;
                        uint32_t limitStartFailures = 0u;
                        MotionQualificationMath::AxisHomeSample xTriggeredRef{};
                        MotionQualificationMath::AxisHomeSample yTriggeredRef{};
                        MotionQualificationMath::AxisHomeSample zTriggeredRef{};
                        MotionQualificationMath::AxisHomeSample xTriggeredHome{};
                        MotionQualificationMath::AxisHomeSample yTriggeredHome{};
                        MotionQualificationMath::AxisHomeSample zTriggeredHome{};

                        auto runTriggeredAxis = [&](Stepper* stepper,
                                                    EventBits_t homeBit,
                                                    EventBits_t moveBit,
                                                    const char* stage,
                                                    MotionQualificationMath::AxisHomeSample& reference,
                                                    MotionQualificationMath::AxisHomeSample& measured) -> bool {
                          sendProgressStage(stage);
                          if (!runAxisHomeDiagnosticAttempt(stepper,
                                                            homeBit,
                                                            reference,
                                                            kHomeFastHz,
                                                            kHomeSlowHz,
                                                            kHomeBackoffSteps,
                                                            kHomeTimeoutMs)) {
                            triggeredHomeTimeouts++;
                            return false;
                          }
                          const int32_t triggeredTarget = reference.finalBackoffSteps - kTriggeredOffsetSteps;
                          if (!moveAxisToWithTimeout(stepper,
                                                     moveBit,
                                                     triggeredTarget,
                                                     kTriggeredMoveHz,
                                                     kTriggeredMoveTimeoutMs)) {
                            triggeredMoveTimeouts++;
                            return false;
                          }
                          if (!stepper->isLimitAssertedForDiagnostics()) {
                            limitStartFailures++;
                          }
                          if (!runAxisHomeDiagnosticAttempt(stepper,
                                                            homeBit,
                                                            measured,
                                                            kHomeFastHz,
                                                            kHomeSlowHz,
                                                            kHomeBackoffSteps,
                                                            kHomeTimeoutMs)) {
                            triggeredHomeTimeouts++;
                            return false;
                          }
                          return true;
                        };

                        const bool xTriggeredPass = runTriggeredAxis(Stepper::stepperX(),
                                                                     BIT_HOME_X_DONE,
                                                                     BIT_STEPPER1_DONE,
                                                                     "triggered_home_x",
                                                                     xTriggeredRef,
                                                                     xTriggeredHome);
                        const bool yTriggeredPass = xTriggeredPass &&
                            runTriggeredAxis(Stepper::stepperY(),
                                             BIT_HOME_Y_DONE,
                                             BIT_STEPPER2_DONE,
                                             "triggered_home_y",
                                             yTriggeredRef,
                                             yTriggeredHome);
                        const bool zTriggeredPass = yTriggeredPass &&
                            runTriggeredAxis(Stepper::stepperZ(),
                                             BIT_HOME_Z_DONE,
                                             BIT_STEPPER3_DONE,
                                             "triggered_home_z",
                                             zTriggeredRef,
                                             zTriggeredHome);
                        const MotionQualificationMath::AxisHomeStats xTriggeredStats =
                            MotionQualificationMath::summarizeAxisHomeSamples(&xTriggeredHome,
                                                                              1u,
                                                                              kExpectedBackoffSteps);
                        const MotionQualificationMath::AxisHomeStats yTriggeredStats =
                            MotionQualificationMath::summarizeAxisHomeSamples(&yTriggeredHome,
                                                                              1u,
                                                                              kExpectedBackoffSteps);
                        const MotionQualificationMath::AxisHomeStats zTriggeredStats =
                            MotionQualificationMath::summarizeAxisHomeSamples(&zTriggeredHome,
                                                                              1u,
                                                                              kExpectedBackoffSteps);
                        triggeredMoveTimeouts += xTriggeredStats.moveTimeoutCount +
                                                 yTriggeredStats.moveTimeoutCount +
                                                 zTriggeredStats.moveTimeoutCount;
                        triggeredHomeTimeouts += xTriggeredStats.homeTimeoutCount +
                                                 yTriggeredStats.homeTimeoutCount +
                                                 zTriggeredStats.homeTimeoutCount;
                        const uint32_t xTriggeredDrift =
                            MotionQualificationMath::absDiffSteps(xTriggeredHome.limitTriggerSteps,
                                                                  xTriggeredRef.limitTriggerSteps);
                        const uint32_t yTriggeredDrift =
                            MotionQualificationMath::absDiffSteps(yTriggeredHome.limitTriggerSteps,
                                                                  yTriggeredRef.limitTriggerSteps);
                        const uint32_t zTriggeredDrift =
                            MotionQualificationMath::absDiffSteps(zTriggeredHome.limitTriggerSteps,
                                                                  zTriggeredRef.limitTriggerSteps);
                        const bool triggeredPass = xTriggeredPass &&
                            yTriggeredPass &&
                            zTriggeredPass &&
                            (triggeredMoveTimeouts == 0u) &&
                            (triggeredHomeTimeouts == 0u) &&
                            (limitStartFailures == 0u);
                        char metrics2016[192];
                        snprintf(metrics2016, sizeof(metrics2016),
                                 "axis=xyz;offset=%ld;x_span=%lu;y_span=%lu;z_span=%lu;x_drift=%lu;y_drift=%lu;z_drift=%lu;move_to=%lu;home_to=%lu;limit_start=%lu",
                                 static_cast<long>(kTriggeredOffsetSteps),
                                 static_cast<unsigned long>(xTriggeredStats.limitTriggerSpanSteps),
                                 static_cast<unsigned long>(yTriggeredStats.limitTriggerSpanSteps),
                                 static_cast<unsigned long>(zTriggeredStats.limitTriggerSpanSteps),
                                 static_cast<unsigned long>(xTriggeredDrift),
                                 static_cast<unsigned long>(yTriggeredDrift),
                                 static_cast<unsigned long>(zTriggeredDrift),
                                 static_cast<unsigned long>(triggeredMoveTimeouts),
                                 static_cast<unsigned long>(triggeredHomeTimeouts),
                                 static_cast<unsigned long>(limitStartFailures));
                        (void)runOne(2016, "motion_limit_triggered_home_fact", triggeredPass, metrics2016);
                        return finishSelfTestNow();
                      }

                      auto psiToRaw = [](uint32_t psiMilli) -> uint16_t {
                        return PressureQualificationMath::pressureRawFromPsiMilli(psiMilli);
                      };

                      if (runRefuelVacuumSuite) {
                        static constexpr uint8_t kRefuelChannel = 1u;
                        static constexpr int32_t kVacuumRaw =
                            PressureQualificationMath::pressureRawFromSignedPsiMilli(-1000);
                        static constexpr int32_t kAtmosphereRaw =
                            PressureQualificationMath::pressureRawFromSignedPsiMilli(0);
                        static constexpr uint16_t kVacuumValidationMinRaw =
                            static_cast<uint16_t>(PressureQualificationMath::pressureRawFromSignedPsiMilli(-1600));
                        static constexpr uint16_t kVacuumValidationMaxStepRaw = 1400u;
                        static constexpr uint32_t kVacuumPrepPositionSteps = 20000u;
                        static constexpr uint32_t kVacuumPrepMoveHz = 5000u;
                        static constexpr uint32_t kAtmosphereSettleMs = 500u;
                        static constexpr uint32_t kAtmosphereSampleMs = 1500u;
                        static constexpr uint32_t kAtmosphereSamplePeriodMs = 25u;
                        static constexpr uint32_t kVacuumCycleCount = 20u;
                        static constexpr uint32_t kVacuumSettleTimeoutMs = 3000u;
                        static constexpr uint32_t kVacuumAcceptTolRaw = 120u;
                        static constexpr uint32_t kVacuumAtmosphereShiftMaxRaw = 120u;
                        static constexpr uint32_t kVacuumMotorGuardAbsSteps = 80000u;
                        static constexpr uint32_t kVacuumMotorGuardDeltaSteps = 50000u;

#if (LC_PRESSURE_PORTS <= 1)
                        if (!runOne(2220,
                                    "refuel_vacuum_sensor_shift_factory",
                                    false,
                                    "gate=no_refuel_port;pre=0;post=0;shift=0;pre_sp=0;post_sp=0;pre_n=0;post_n=0;rej=0;rail=0;spike=0;fault=1;to=0;trace=0")) {
                          return finishSelfTestNow();
                        }
                        if (!runOne(2221,
                                    "refuel_vacuum_cycle_repeatability_factory",
                                    false,
                                    "gate=no_refuel_port;cyc=0;neg_n=0;zero_n=0;n_span=0;z_span=0;nps=0;zps=0;err=0;settle=0;guard=0;ma=0;md=0;rej=0;to=0;trace=0")) {
                          return finishSelfTestNow();
                        }
                        return finishSelfTestNow();
#else
                        PressureSensor* sensor = PressureSensor::instance();
                        Stepper* stepper = Stepper::stepperR();
                        if ((sensor == nullptr) || (sensor->numPorts() <= kRefuelChannel) || (stepper == nullptr)) {
                          if (!runOne(2220,
                                      "refuel_vacuum_sensor_shift_factory",
                                      false,
                                      "gate=no_refuel_channel;pre=0;post=0;shift=0;pre_sp=0;post_sp=0;pre_n=0;post_n=0;rej=0;rail=0;spike=0;fault=1;to=0;trace=0")) {
                            return finishSelfTestNow();
                          }
                          if (!runOne(2221,
                                      "refuel_vacuum_cycle_repeatability_factory",
                                      false,
                                      "gate=no_refuel_channel;cyc=0;neg_n=0;zero_n=0;n_span=0;z_span=0;nps=0;zps=0;err=0;settle=0;guard=0;ma=0;md=0;rej=0;to=0;trace=0")) {
                            return finishSelfTestNow();
                          }
                          return finishSelfTestNow();
                        }

                        struct VacuumSampleStats {
                          uint32_t count = 0u;
                          int64_t sum = 0;
                          int32_t first = 0;
                          int32_t last = 0;
                          int32_t minValue = 0;
                          int32_t maxValue = 0;
                        };

                        auto updateVacuumStats = [](VacuumSampleStats& stats, int32_t value) {
                          if (stats.count == 0u) {
                            stats.first = value;
                            stats.minValue = value;
                            stats.maxValue = value;
                          }
                          stats.last = value;
                          if (value < stats.minValue) stats.minValue = value;
                          if (value > stats.maxValue) stats.maxValue = value;
                          stats.sum += static_cast<int64_t>(value);
                          stats.count++;
                        };

                        auto meanVacuumStats = [](const VacuumSampleStats& stats) -> int32_t {
                          return (stats.count == 0u)
                              ? 0
                              : static_cast<int32_t>(stats.sum / static_cast<int64_t>(stats.count));
                        };

                        auto spanVacuumStats = [](const VacuumSampleStats& stats) -> uint32_t {
                          return (stats.count == 0u)
                              ? 0u
                              : PressureQualificationMath::absDiff(stats.maxValue, stats.minValue);
                        };

                        auto deltaCounter32 = [](uint32_t start, uint32_t finish) -> uint32_t {
                          return (finish >= start) ? (finish - start) : 0u;
                        };

                        auto readRefuelPressurePositionSample = [&]() {
                          PressurePositionSample sample{};
                          const auto controlSample = sensor->getControlSample(kRefuelChannel);
                          sample.pressureRaw = static_cast<int32_t>(controlSample.raw);
                          sample.pressureAvg = static_cast<int32_t>(controlSample.avg);
                          sample.motorPosition = stepper->getPosition();
                          return sample;
                        };

                        PressureRegulator& reg = PressureRegulator::regR();
                        const int32_t savedTargetRaw =
                            (static_cast<int32_t>(reg.getTarget()) < kAtmosphereRaw)
                                ? kAtmosphereRaw
                                : static_cast<int32_t>(reg.getTarget());
                        const PressureSensor::ValidationConfig savedValidation =
                            sensor->getValidationConfig(kRefuelChannel);
                        bool validationChanged = false;
                        bool focusActive = false;
                        bool vacuumEntered = false;
                        bool traceStarted = false;
                        bool traceExportOk = true;
                        uint32_t traceStartTick = 0u;

                        auto cleanupVacuumSuite = [&]() {
                          if (traceStarted) {
                            PressureTraceRecorder::instance().stop(HAL_GetTick());
                            traceStarted = false;
                          }
                          if (focusActive) {
                            sensor->endDiagnosticFocus();
                            focusActive = false;
                          }
                          if (vacuumEntered) {
                            (void)reg.exitVacuumMode(savedTargetRaw, CRASH_TASK_ORCH);
                            vacuumEntered = false;
                          } else {
                            reg.pause();
                            reg.closeValve();
                          }
                          if (validationChanged) {
                            sensor->setValidationConfig(kRefuelChannel, savedValidation);
                            validationChanged = false;
                          }
                        };

                        auto recordVacuumMotorEvent = [&](int32_t motorPosition) {
                          if (!traceStarted) {
                            return;
                          }
                          const uint32_t dt = HAL_GetTick() - traceStartTick;
                          const uint32_t encoded = static_cast<uint32_t>(motorPosition);
                          PressureTraceEvent event{};
                          event.dtMs = static_cast<uint16_t>((dt > 0xFFFFu) ? 0xFFFFu : dt);
                          event.type = static_cast<uint8_t>(PressureTraceEventType::MotorPosition);
                          event.value0 = static_cast<uint16_t>(encoded & 0xFFFFu);
                          event.value1 = static_cast<uint16_t>((encoded >> 16) & 0xFFFFu);
                          PressureTraceRecorder::instance().recordEvent(PressureTraceChannel::Refuel, event);
                        };

                        auto collectAtmosphereStats = [&](VacuumSampleStats& stats,
                                                          const char* stage) -> bool {
                          reg.pause();
                          reg.openValve();
                          if (!delayWithWatchdog(kAtmosphereSettleMs, stage)) {
                            reg.closeValve();
                            return false;
                          }
                          const uint32_t startMs = HAL_GetTick();
                          while ((HAL_GetTick() - startMs) < kAtmosphereSampleMs) {
                            Watchdog_CheckIn(CRASH_TASK_ORCH);
                            maybeSendProgress(stage);
                            if (_selfTestAbortRequested) {
                              reg.closeValve();
                              return false;
                            }
                            const auto sample = sensor->getControlSample(kRefuelChannel);
                            updateVacuumStats(stats, static_cast<int32_t>(sample.raw));
                            vTaskDelay(msToAtLeast1Tick(kAtmosphereSamplePeriodMs));
                          }
                          reg.closeValve();
                          return stats.count > 0u;
                        };

                        const PressureQualificationMath::MotorTravelGuardLimits motorGuardLimits{
                            kVacuumMotorGuardAbsSteps,
                            kVacuumMotorGuardDeltaSteps,
                        };
                        PressureQualificationMath::MotorTravelGuardState guardState{};
                        uint32_t guardCount = 0u;

                        auto waitVacuumTarget = [&](int32_t targetRaw,
                                                    const char* stage) -> PressureWaitResult {
                          PressureWaitResult result{};
                          const auto startSample = sensor->getControlSample(kRefuelChannel);
                          const bool stepUp = static_cast<int32_t>(startSample.raw) <= targetRaw;
                          const int32_t transitionStartPosition = stepper->getPosition();
                          (void)PressureQualificationMath::updateMotorTravelGuard(
                              transitionStartPosition,
                              transitionStartPosition,
                              motorGuardLimits,
                              guardState);
                          if (!reg.setVacuumTargetSafe(targetRaw)) {
                            return result;
                          }
                          const uint32_t startMs = HAL_GetTick();
                          int32_t peakPressure = sensor->getPressure(kRefuelChannel);
                          int32_t troughPressure = peakPressure;
                          while ((HAL_GetTick() - startMs) < kVacuumSettleTimeoutMs) {
                            Watchdog_CheckIn(CRASH_TASK_ORCH);
                            maybeSendProgress(stage);
                            const int32_t pos = stepper->getPosition();
                            if (PressureQualificationMath::updateMotorTravelGuard(
                                    pos,
                                    transitionStartPosition,
                                    motorGuardLimits,
                                    guardState)) {
                              result.motorGuarded = true;
                              guardCount++;
                              reg.pause();
                              reg.closeValve();
                              break;
                            }
                            const int32_t pressure = sensor->getPressure(kRefuelChannel);
                            if (pressure > peakPressure) peakPressure = pressure;
                            if (pressure < troughPressure) troughPressure = pressure;
                            const auto sample = sensor->getControlSample(kRefuelChannel);
                            const uint32_t err =
                                PressureQualificationMath::absDiff(static_cast<int32_t>(sample.raw), targetRaw);
                            if (reg.isPressureOk() ||
                                (!reg.isTargetRamping() && (err <= kVacuumAcceptTolRaw))) {
                              result.readySeen = true;
                              break;
                            }
                            if (_selfTestAbortRequested) {
                              result.aborted = true;
                              break;
                            }
                            vTaskDelay(pdMS_TO_TICKS(20));
                          }
                          result.settleMs = HAL_GetTick() - startMs;
                          result.readyFinal = reg.isPressureOk();
                          const int32_t finalAvgPressure = sensor->getPressure(kRefuelChannel);
                          const auto finalSample = sensor->getControlSample(kRefuelChannel);
                          result.controlError =
                              PressureQualificationMath::absDiff(static_cast<int32_t>(finalSample.raw), targetRaw);
                          result.avgError = PressureQualificationMath::absDiff(finalAvgPressure, targetRaw);
                          if (stepUp) {
                            result.overshoot = (peakPressure > targetRaw)
                                ? static_cast<uint32_t>(peakPressure - targetRaw)
                                : 0u;
                          } else {
                            result.overshoot = (troughPressure < targetRaw)
                                ? static_cast<uint32_t>(targetRaw - troughPressure)
                                : 0u;
                          }
                          result.accepted = !result.aborted &&
                              !result.motorGuarded &&
                              (result.readySeen || result.readyFinal ||
                               (!reg.isTargetRamping() && (result.controlError <= kVacuumAcceptTolRaw)));
                          return result;
                        };

                        PressureSensor::ValidationConfig vacuumValidation = savedValidation;
                        vacuumValidation.minRaw = kVacuumValidationMinRaw;
                        vacuumValidation.maxStepPerSample = kVacuumValidationMaxStepRaw;
                        sensor->setValidationConfig(kRefuelChannel, vacuumValidation);
                        validationChanged = true;

                        focusActive = sensor->beginDiagnosticFocus(kRefuelChannel);
                        const auto startCounters = sensor->getControlSample(kRefuelChannel);
                        VacuumSampleStats preAtmosphere{};
                        VacuumSampleStats postAtmosphere{};
                        int32_t negPressures[kVacuumCycleCount]{};
                        int32_t zeroPressures[kVacuumCycleCount]{};
                        int32_t negPositions[kVacuumCycleCount]{};
                        int32_t zeroPositions[kVacuumCycleCount]{};
                        size_t negCount = 0u;
                        size_t zeroCount = 0u;
                        uint32_t cyclesCompleted = 0u;
                        uint32_t settleMaxMs = 0u;
                        uint32_t errMax = 0u;
                        uint32_t timeoutCount = 0u;
                        bool enterOk = false;
                        bool preAtmosphereOk = false;
                        bool postAtmosphereOk = false;

                        if (exportPressureTrace) {
                          PressureTraceRecorder::instance().reset();
                        }

                        if (focusActive) {
                          sendProgressStage("refuel_vacuum_pre_atm");
                          preAtmosphereOk = collectAtmosphereStats(preAtmosphere, "refuel_vacuum_pre_atm");
                          if (!preAtmosphereOk) timeoutCount++;
                        } else {
                          timeoutCount++;
                        }

                        if (preAtmosphereOk && !_selfTestAbortRequested) {
                          sendProgressStage("refuel_vacuum_enter");
                          enterOk = orchestrator.enterRefuelVacuumModeWithAsyncHome(
                              kVacuumRaw,
                              kVacuumPrepPositionSteps,
                              kVacuumPrepMoveHz);
                          vacuumEntered = enterOk;
                        }

                        if (enterOk && exportPressureTrace) {
                          auto& recorder = PressureTraceRecorder::instance();
                          recorder.reset();
                          PressureTraceConfig traceCfg{};
                          traceCfg.channel = PressureTraceChannel::Refuel;
                          traceCfg.maxSamples = PressureTraceRecorder::kMaxSamples;
                          traceCfg.maxEvents = PressureTraceRecorder::kMaxEvents;
                          traceCfg.sampleStride = 10u;
                          recorder.configure(traceCfg);
                          recorder.arm();
                          traceStartTick = HAL_GetTick();
                          recorder.start(traceStartTick);
                          traceStarted = true;
                        }

                        if (enterOk && !_selfTestAbortRequested) {
                          for (uint32_t cycle = 0u; cycle < kVacuumCycleCount; ++cycle) {
                            sendProgressStage("refuel_vacuum_cycle");
                            const PressureWaitResult negWait =
                                waitVacuumTarget(kVacuumRaw, "refuel_vacuum_neg");
                            if (negWait.settleMs > settleMaxMs) settleMaxMs = negWait.settleMs;
                            if (negWait.controlError > errMax) errMax = negWait.controlError;
                            if (!negWait.accepted || _selfTestAbortRequested) {
                              timeoutCount++;
                              break;
                            }
                            const PressurePositionSample negSample = readRefuelPressurePositionSample();
                            if (negCount < kVacuumCycleCount) {
                              negPressures[negCount] = negSample.pressureRaw;
                              negPositions[negCount] = negSample.motorPosition;
                              negCount++;
                            }
                            recordVacuumMotorEvent(negSample.motorPosition);

                            const PressureWaitResult zeroWait =
                                waitVacuumTarget(kAtmosphereRaw, "refuel_vacuum_zero");
                            if (zeroWait.settleMs > settleMaxMs) settleMaxMs = zeroWait.settleMs;
                            if (zeroWait.controlError > errMax) errMax = zeroWait.controlError;
                            if (!zeroWait.accepted || _selfTestAbortRequested) {
                              timeoutCount++;
                              break;
                            }
                            const PressurePositionSample zeroSample = readRefuelPressurePositionSample();
                            if (zeroCount < kVacuumCycleCount) {
                              zeroPressures[zeroCount] = zeroSample.pressureRaw;
                              zeroPositions[zeroCount] = zeroSample.motorPosition;
                              zeroCount++;
                            }
                            recordVacuumMotorEvent(zeroSample.motorPosition);
                            cyclesCompleted++;
                          }
                        }

                        if (enterOk && !_selfTestAbortRequested && !guardState.guardAbs && !guardState.guardDelta) {
                          const PressureWaitResult zeroWait =
                              waitVacuumTarget(kAtmosphereRaw, "refuel_vacuum_post_zero");
                          if (zeroWait.settleMs > settleMaxMs) settleMaxMs = zeroWait.settleMs;
                          if (zeroWait.controlError > errMax) errMax = zeroWait.controlError;
                          if (!zeroWait.accepted) timeoutCount++;
                          postAtmosphereOk = collectAtmosphereStats(postAtmosphere, "refuel_vacuum_post_atm");
                          if (!postAtmosphereOk) timeoutCount++;
                        }

                        if (traceStarted) {
                          PressureTraceRecorder::instance().stop(HAL_GetTick());
                          traceStarted = false;
                        }
                        const bool traceCaptured =
                            !exportPressureTrace ||
                            ((PressureTraceRecorder::instance().sampleCount() > 0u) &&
                             (PressureTraceRecorder::instance().eventCount() > 0u));
                        traceExportOk = exportTrace(
                            2221,
                            "refuel_vacuum_cycle_repeatability_factory",
                            traceCaptured);

                        const auto endCounters = sensor->getControlSample(kRefuelChannel);
                        const uint32_t rejectDelta =
                            deltaCounter32(startCounters.rejectCount, endCounters.rejectCount);
                        const uint32_t railRejectDelta =
                            deltaCounter32(startCounters.railRejectCount, endCounters.railRejectCount);
                        const uint32_t spikeRejectDelta =
                            deltaCounter32(startCounters.spikeRejectCount, endCounters.spikeRejectCount);
                        const uint32_t refuelFault =
                            sensor->isSafetyFaultLatched(kRefuelChannel) ? 1u : 0u;
                        const int32_t preMean = meanVacuumStats(preAtmosphere);
                        const int32_t postMean = meanVacuumStats(postAtmosphere);
                        const uint32_t atmosphereShift =
                            PressureQualificationMath::absDiff(preMean, postMean);
                        const auto negPressureStats =
                            PressureQualificationMath::summarizeInt32Span(negPressures, negCount);
                        const auto zeroPressureStats =
                            PressureQualificationMath::summarizeInt32Span(zeroPressures, zeroCount);
                        const auto negPositionStats =
                            PressureQualificationMath::summarizeInt32Span(negPositions, negCount);
                        const auto zeroPositionStats =
                            PressureQualificationMath::summarizeInt32Span(zeroPositions, zeroCount);

                        cleanupVacuumSuite();

                        const bool traceEmitted = exportPressureTrace && traceCaptured && traceExportOk;
                        const bool shiftPass = enterOk &&
                            preAtmosphereOk &&
                            postAtmosphereOk &&
                            (cyclesCompleted == kVacuumCycleCount) &&
                            (atmosphereShift <= kVacuumAtmosphereShiftMaxRaw) &&
                            (rejectDelta == 0u) &&
                            (refuelFault == 0u) &&
                            (timeoutCount == 0u);
                        char shiftMetrics[224];
                        snprintf(shiftMetrics,
                                 sizeof(shiftMetrics),
                                 "pre=%ld;post=%ld;shift=%lu;pre_sp=%lu;post_sp=%lu;pre_n=%lu;post_n=%lu;rej=%lu;rail=%lu;spike=%lu;fault=%lu;to=%lu;trace=%u",
                                 static_cast<long>(preMean),
                                 static_cast<long>(postMean),
                                 static_cast<unsigned long>(atmosphereShift),
                                 static_cast<unsigned long>(spanVacuumStats(preAtmosphere)),
                                 static_cast<unsigned long>(spanVacuumStats(postAtmosphere)),
                                 static_cast<unsigned long>(preAtmosphere.count),
                                 static_cast<unsigned long>(postAtmosphere.count),
                                 static_cast<unsigned long>(rejectDelta),
                                 static_cast<unsigned long>(railRejectDelta),
                                 static_cast<unsigned long>(spikeRejectDelta),
                                 static_cast<unsigned long>(refuelFault),
                                 static_cast<unsigned long>(timeoutCount),
                                 static_cast<unsigned>(traceEmitted ? 1u : 0u));
                        if (!runOne(2220,
                                    "refuel_vacuum_sensor_shift_factory",
                                    shiftPass,
                                    shiftMetrics)) {
                          return finishSelfTestNow();
                        }

                        const bool cyclePass = enterOk &&
                            (cyclesCompleted == kVacuumCycleCount) &&
                            (negCount == kVacuumCycleCount) &&
                            (zeroCount == kVacuumCycleCount) &&
                            (errMax <= kVacuumAcceptTolRaw) &&
                            (rejectDelta == 0u) &&
                            (refuelFault == 0u) &&
                            (guardCount == 0u) &&
                            !guardState.guardAbs &&
                            !guardState.guardDelta &&
                            (timeoutCount == 0u) &&
                            traceCaptured &&
                            traceExportOk;
                        char cycleMetrics[256];
                        snprintf(cycleMetrics,
                                 sizeof(cycleMetrics),
                                 "cyc=%lu;neg_n=%lu;zero_n=%lu;n_span=%lu;z_span=%lu;nps=%lu;zps=%lu;err=%lu;settle=%lu;guard=%lu;ma=%lu;md=%lu;rej=%lu;to=%lu;trace=%u",
                                 static_cast<unsigned long>(cyclesCompleted),
                                 static_cast<unsigned long>(negPressureStats.sampleCount),
                                 static_cast<unsigned long>(zeroPressureStats.sampleCount),
                                 static_cast<unsigned long>(negPressureStats.span),
                                 static_cast<unsigned long>(zeroPressureStats.span),
                                 static_cast<unsigned long>(negPositionStats.span),
                                 static_cast<unsigned long>(zeroPositionStats.span),
                                 static_cast<unsigned long>(errMax),
                                 static_cast<unsigned long>(settleMaxMs),
                                 static_cast<unsigned long>(guardCount),
                                 static_cast<unsigned long>(guardState.motorAbsMax),
                                 static_cast<unsigned long>(guardState.motorDeltaMax),
                                 static_cast<unsigned long>(rejectDelta),
                                 static_cast<unsigned long>(timeoutCount),
                                 static_cast<unsigned>(traceEmitted ? 1u : 0u));
                        if (!runOne(2221,
                                    "refuel_vacuum_cycle_repeatability_factory",
                                    cyclePass,
                                    cycleMetrics)) {
                          return finishSelfTestNow();
                        }
                        return finishSelfTestNow();
#endif
                      }

                      if (runPressureRegulatorSuite) {
                        static constexpr uint32_t kPressureIdleMs = 10000u;
                        static constexpr uint32_t kPressureIdleSampleMs = 50u;
                        static constexpr uint32_t kPressureHoldMs = 15000u;
                        static constexpr uint32_t kPressureSettleTimeoutMs = 5000u;
                        static constexpr uint32_t kRegHomeFastHz = 30000u;
                        static constexpr uint32_t kRegHomeSlowHz = 3000u;
                        static constexpr uint32_t kRegHomeBackoffSteps = 400u;
                        static constexpr uint32_t kRegHomeTimeoutMs = 20000u;
                        static constexpr uint32_t kRegHomeReps = 3u;
                        static constexpr uint32_t kCycleCount = 3u;
                        static constexpr uint32_t kHysteresisReps = 2u;
                        static constexpr uint32_t kLadderPointCount = 5u;
                        static constexpr uint16_t kPressure0Raw =
                            PressureQualificationMath::pressureRawFromPsiMilli(0u);
                        static constexpr uint16_t kPressure1Raw =
                            PressureQualificationMath::pressureRawFromPsiMilli(1000u);
                        static constexpr uint16_t kPressure2Raw =
                            PressureQualificationMath::pressureRawFromPsiMilli(2000u);
                        static constexpr uint16_t kPressure3Raw =
                            PressureQualificationMath::pressureRawFromPsiMilli(3000u);
                        static constexpr uint32_t kMaxPressureJumpRaw =
                            static_cast<uint32_t>(kPressure1Raw - kPressure0Raw);
                        static constexpr uint32_t kMotorGuardAbsSteps = 80000u;
                        static constexpr uint32_t kMotorGuardDeltaSteps = 50000u;
                        static constexpr size_t kPressureTargetSequenceCapacity = 8u;

                        bool pressureMotorGuardTripped = false;
                        const PressureQualificationMath::MotorTravelGuardLimits motorGuardLimits{
                            kMotorGuardAbsSteps,
                            kMotorGuardDeltaSteps,
                        };

                        PressureSensor* sensor = PressureSensor::instance();

                        auto regulatorFor = [&](uint8_t channel) -> PressureRegulator& {
#if (LC_PRESSURE_PORTS > 1)
                          return (channel == 0u) ? PressureRegulator::regP() : PressureRegulator::regR();
#else
                          (void)channel;
                          return PressureRegulator::regP();
#endif
                        };

                        auto stepperFor = [&](uint8_t channel) -> Stepper* {
                          if (channel == 0u) {
                            return Stepper::stepperP();
                          }
#if (LC_PRESSURE_PORTS > 1)
                          return Stepper::stepperR();
#else
                          (void)channel;
                          return nullptr;
#endif
                        };

                        auto readyBitFor = [&](uint8_t channel) -> EventBits_t {
#if (LC_PRESSURE_PORTS > 1)
                          return (channel == 0u) ? BIT_PRESSURE_P_READY : BIT_PRESSURE_R_READY;
#else
                          (void)channel;
                          return BIT_PRESSURE_P_READY;
#endif
                        };

                        auto homeBitFor = [&](uint8_t channel) -> EventBits_t {
#if (LC_PRESSURE_PORTS > 1)
                          return (channel == 0u) ? BIT_HOME_P_DONE : BIT_HOME_R_DONE;
#else
                          (void)channel;
                          return BIT_HOME_P_DONE;
#endif
                        };

                        auto channelAvailable = [&](uint8_t channel) -> bool {
                          if ((sensor == nullptr) || (sensor->numPorts() <= channel)) {
                            return false;
                          }
                          return stepperFor(channel) != nullptr;
                        };

                        auto channelCode = [](uint8_t channel) -> char {
                          return (channel == 0u) ? 'p' : 'r';
                        };

                        auto closePressureSuitePaths = [&]() {
                          PressureRegulator::regP().pause();
                          PressureRegulator::regP().closeValve();
#if (LC_PRESSURE_PORTS > 1)
                          PressureRegulator::regR().pause();
                          PressureRegulator::regR().closeValve();
#endif
                        };

                        auto deltaCounter = [](uint32_t start, uint32_t finish) -> uint32_t {
                          return (finish >= start) ? (finish - start) : 0u;
                        };

                        auto updateMax = [](uint32_t& current, uint32_t candidate) {
                          if (candidate > current) {
                            current = candidate;
                          }
                        };

                        auto readPressurePositionSample = [&](uint8_t channel) {
                          PressurePositionSample sample{};
                          if ((sensor != nullptr) && (sensor->numPorts() > channel)) {
                            const auto controlSample = sensor->getControlSample(channel);
                            sample.pressureRaw = static_cast<int32_t>(controlSample.raw);
                            sample.pressureAvg = static_cast<int32_t>(controlSample.avg);
                          }
                          Stepper* stepper = stepperFor(channel);
                          if (stepper != nullptr) {
                            sample.motorPosition = stepper->getPosition();
                          }
                          return sample;
                        };

                        auto emitUnavailableChannel = [&](uint16_t testId,
                                                          const char* name,
                                                          uint8_t channel,
                                                          const char* metricsTail) -> bool {
                          char metrics[224];
                          snprintf(metrics, sizeof(metrics),
                                   "ch=%c;gate=no_refuel_port;%s",
                                   channelCode(channel),
                                   metricsTail);
                          return runOne(testId, name, false, metrics);
                        };

                        struct PressureHomeReference {
                          bool ok = false;
                          uint32_t moveTo = 0u;
                          uint32_t homeTo = 0u;
                          int32_t fineLimitSteps = 0;
                        };

                        auto homePressureReference = [&](uint8_t channel,
                                                         const char* stage) -> PressureHomeReference {
                          PressureHomeReference ref{};
                          if (!channelAvailable(channel)) {
                            ref.homeTo = 1u;
                            return ref;
                          }
                          closePressureSuitePaths();
                          sendProgressStage(stage);
                          const EventBits_t homeBit = homeBitFor(channel);
                          xEventGroupClearBits(_doneEvents, homeBit);
                          if (channel == 0u) {
                            startRegHomeAsync(&PressureRegulator::regP(),
                                              kRegHomeFastHz,
                                              kRegHomeSlowHz,
                                              kRegHomeBackoffSteps,
                                              BIT_HOME_P_DONE);
                          }
#if (LC_PRESSURE_PORTS > 1)
                          else {
                            startRegHomeAsync(&PressureRegulator::regR(),
                                              kRegHomeFastHz,
                                              kRegHomeSlowHz,
                                              kRegHomeBackoffSteps,
                                              BIT_HOME_R_DONE);
                          }
#endif
                          const bool homeDone = waitBitsWithTimeout(homeBit, kRegHomeTimeoutMs);
                          const EventBits_t doneBits = xEventGroupGetBits(_doneEvents);
                          Stepper* stepper = stepperFor(channel);
                          if (stepper == nullptr) {
                            ref.homeTo = 1u;
                            return ref;
                          }
                          const Stepper::HomeDiagnosticSnapshot diag =
                              stepper->getLastHomeDiagnosticSnapshot();
                          ref.moveTo = diag.moveTimeoutCount;
                          ref.fineLimitSteps = diag.fineLimitPositionSteps;
                          ref.ok = homeDone && ((doneBits & homeBit) != 0u) && diag.success;
                          if (!ref.ok) {
                            ref.homeTo = 1u;
                          }
                          regulatorFor(channel).pause();
                          regulatorFor(channel).closeValve();
                          return ref;
                        };

                        auto waitForPressureTarget = [&](uint8_t channel,
                                                         int32_t targetRaw,
                                                         PressureQualificationMath::ExecutionSummary& exec,
                                                         uint32_t& settleMaxMs,
                                                         uint32_t& errMax,
                                                         uint32_t* overMax,
                                                         uint32_t* underMax,
                                                         PressureQualificationMath::MotorTravelGuardState& guardState) -> PressureWaitResult {
                          PressureRegulator& reg = regulatorFor(channel);
                          Stepper* stepper = stepperFor(channel);
                          const auto startSample = sensor->getControlSample(channel);
                          const bool stepUp = static_cast<int32_t>(startSample.raw) <= targetRaw;
                          const int32_t transitionStartPosition =
                              (stepper != nullptr) ? stepper->getPosition() : 0;
                          (void)PressureQualificationMath::updateMotorTravelGuard(
                              transitionStartPosition,
                              transitionStartPosition,
                              motorGuardLimits,
                              guardState);
                          xEventGroupClearBits(_doneEvents, readyBitFor(channel));
                          reg.setTargetSafe(targetRaw);
                          const int32_t acceptedTarget = static_cast<int32_t>(reg.getTarget());
                          PressureWaitResult wait{};
                          const uint32_t startMs = HAL_GetTick();
                          int32_t peakPressure = sensor->getPressure(channel);
                          int32_t troughPressure = peakPressure;
                          while ((HAL_GetTick() - startMs) < kPressureSettleTimeoutMs) {
                            Watchdog_CheckIn(CRASH_TASK_ORCH);
                            maybeSendProgress("wait_pressure_ready");
                            if (stepper != nullptr) {
                              const int32_t pos = stepper->getPosition();
                              if (PressureQualificationMath::updateMotorTravelGuard(
                                      pos,
                                      transitionStartPosition,
                                      motorGuardLimits,
                                      guardState)) {
                                wait.motorGuarded = true;
                                pressureMotorGuardTripped = true;
                                reg.pause();
                                reg.closeValve();
                                break;
                              }
                            }
                            const int32_t pressure = sensor->getPressure(channel);
                            if (pressure > peakPressure) peakPressure = pressure;
                            if (pressure < troughPressure) troughPressure = pressure;
                            if (reg.isPressureOk()) {
                              wait.readySeen = true;
                              break;
                            }
                            if (_selfTestAbortRequested) {
                              wait.aborted = true;
                              break;
                            }
                            vTaskDelay(pdMS_TO_TICKS(20));
                          }
                          wait.settleMs = HAL_GetTick() - startMs;
                          wait.readyFinal = reg.isPressureOk();
                          const int32_t finalAvgPressure = sensor->getPressure(channel);
                          const auto finalControlSample = sensor->getControlSample(channel);
                          wait.controlError = absDiff32(static_cast<int32_t>(finalControlSample.raw), acceptedTarget);
                          wait.avgError = absDiff32(finalAvgPressure, acceptedTarget);
                          if (stepUp) {
                            wait.overshoot = (peakPressure > acceptedTarget)
                                ? static_cast<uint32_t>(peakPressure - acceptedTarget)
                                : 0u;
                          } else {
                            wait.overshoot = (troughPressure < acceptedTarget)
                                ? static_cast<uint32_t>(acceptedTarget - troughPressure)
                                : 0u;
                          }
                          wait.accepted = !wait.aborted &&
                              !wait.motorGuarded &&
                              (wait.readySeen || wait.readyFinal);
                          recordPressureWaitExecution(wait, exec);
                          updateMax(settleMaxMs, wait.settleMs);
                          updateMax(errMax, wait.controlError);
                          if (stepUp && (overMax != nullptr)) {
                            updateMax(*overMax, wait.overshoot);
                          }
                          if (!stepUp && (underMax != nullptr)) {
                            updateMax(*underMax, wait.overshoot);
                          }
                          return wait;
                        };

                        auto waitForAdjacentPressureTarget = [&](uint8_t channel,
                                                                 int32_t targetRaw,
                                                                 PressureQualificationMath::ExecutionSummary& exec,
                                                                 uint32_t& settleMaxMs,
                                                                 uint32_t& errMax,
                                                                 uint32_t* overMax,
                                                                 uint32_t* underMax,
                                                                 PressureQualificationMath::MotorTravelGuardState& guardState,
                                                                 uint32_t& maxJumpRaw) -> PressureWaitResult {
                          PressureWaitResult lastWait{};
                          int32_t targets[kPressureTargetSequenceCapacity]{};
                          const int32_t currentTarget = static_cast<int32_t>(regulatorFor(channel).getTarget());
                          const size_t count = PressureQualificationMath::buildAdjacentTargetSequence(
                              currentTarget,
                              targetRaw,
                              kMaxPressureJumpRaw,
                              targets,
                              kPressureTargetSequenceCapacity);
                          if (count == 0u) {
                            return waitForPressureTarget(channel,
                                                         targetRaw,
                                                         exec,
                                                         settleMaxMs,
                                                         errMax,
                                                         overMax,
                                                         underMax,
                                                         guardState);
                          }
                          int32_t previousTarget = currentTarget;
                          for (size_t idx = 0u; idx < count; ++idx) {
                            const int32_t nextTarget = targets[idx];
                            updateMax(maxJumpRaw, PressureQualificationMath::absDiff(previousTarget, nextTarget));
                            lastWait = waitForPressureTarget(channel,
                                                             nextTarget,
                                                             exec,
                                                             settleMaxMs,
                                                             errMax,
                                                             overMax,
                                                             underMax,
                                                             guardState);
                            previousTarget = static_cast<int32_t>(regulatorFor(channel).getTarget());
                            if (!lastWait.accepted || lastWait.motorGuarded || pressureMotorGuardTripped || _selfTestAbortRequested) {
                              break;
                            }
                          }
                          return lastWait;
                        };

                        auto restorePressureChannel = [&](uint8_t channel,
                                                          int32_t baselineTarget,
                                                          PressureQualificationMath::ExecutionSummary& exec,
                                                          uint32_t& settleMaxMs,
                                                          uint32_t& errMax,
                                                          PressureQualificationMath::MotorTravelGuardState& guardState,
                                                          uint32_t& maxJumpRaw) {
                          if (!channelAvailable(channel)) {
                            return;
                          }
                          if (!pressureMotorGuardTripped) {
                            (void)waitForAdjacentPressureTarget(channel,
                                                               baselineTarget,
                                                               exec,
                                                               settleMaxMs,
                                                               errMax,
                                                               nullptr,
                                                               nullptr,
                                                               guardState,
                                                               maxJumpRaw);
                          }
                          regulatorFor(channel).pause();
                          regulatorFor(channel).closeValve();
                        };

                        struct IdleStats {
                          uint32_t count = 0u;
                          int64_t sum = 0;
                          int32_t first = 0;
                          int32_t last = 0;
                          int32_t minValue = 0;
                          int32_t maxValue = 0;
                        };

                        auto updateIdleStats = [&](IdleStats& stats, uint8_t channel) {
                          if ((sensor == nullptr) || (sensor->numPorts() <= channel)) {
                            return;
                          }
                          const auto sample = sensor->getControlSample(channel);
                          const int32_t raw = static_cast<int32_t>(sample.raw);
                          if (stats.count == 0u) {
                            stats.first = raw;
                            stats.minValue = raw;
                            stats.maxValue = raw;
                          }
                          stats.last = raw;
                          if (raw < stats.minValue) stats.minValue = raw;
                          if (raw > stats.maxValue) stats.maxValue = raw;
                          stats.sum += static_cast<int64_t>(raw);
                          stats.count++;
                        };

                        auto meanIdle = [](const IdleStats& stats) -> int32_t {
                          return (stats.count == 0u)
                              ? 0
                              : static_cast<int32_t>(stats.sum / static_cast<int64_t>(stats.count));
                        };

                        auto spanIdle = [](const IdleStats& stats) -> uint32_t {
                          return (stats.count == 0u)
                              ? 0u
                              : PressureQualificationMath::absDiff(stats.maxValue, stats.minValue);
                        };

                        closePressureSuitePaths();

                        {
                          sendProgressStage("pressure_idle_stability");
                          IdleStats pIdle{};
                          IdleStats rIdle{};
                          const bool hasP = channelAvailable(0u);
                          const bool hasR = channelAvailable(1u);
                          const auto pStart = hasP ? sensor->getControlSample(0u) : PressureSensor::ControlSample{};
                          const auto rStart = hasR ? sensor->getControlSample(1u) : PressureSensor::ControlSample{};
                          bool timeout = false;
                          if (sensor != nullptr) {
                            const uint32_t startMs = HAL_GetTick();
                            while ((HAL_GetTick() - startMs) < kPressureIdleMs) {
                              Watchdog_CheckIn(CRASH_TASK_ORCH);
                              maybeSendProgress("pressure_idle_stability");
                              if (_selfTestAbortRequested) {
                                timeout = true;
                                break;
                              }
                              if (hasP) updateIdleStats(pIdle, 0u);
                              if (hasR) updateIdleStats(rIdle, 1u);
                              vTaskDelay(msToAtLeast1Tick(kPressureIdleSampleMs));
                            }
                          } else {
                            timeout = true;
                          }
                          const auto pEnd = hasP ? sensor->getControlSample(0u) : PressureSensor::ControlSample{};
                          const auto rEnd = hasR ? sensor->getControlSample(1u) : PressureSensor::ControlSample{};
                          const uint32_t pRejects = hasP ? deltaCounter(pStart.rejectCount, pEnd.rejectCount) : 0u;
                          const uint32_t rRejects = hasR ? deltaCounter(rStart.rejectCount, rEnd.rejectCount) : 0u;
                          const uint32_t pFault = hasP && sensor->isSafetyFaultLatched(0u) ? 1u : (hasP ? 0u : 1u);
                          const uint32_t rFault = hasR && sensor->isSafetyFaultLatched(1u) ? 1u : (hasR ? 0u : 1u);
                          const uint32_t pDrift = PressureQualificationMath::absDiff(pIdle.first, pIdle.last);
                          const uint32_t rDrift = PressureQualificationMath::absDiff(rIdle.first, rIdle.last);
                          const bool idlePass = sensor && hasP && hasR &&
                                                !timeout &&
                                                (pFault == 0u) &&
                                                (rFault == 0u);
                          char metrics[192];
                          snprintf(metrics, sizeof(metrics),
                                   "dur_ms=%lu;p_mean=%ld;r_mean=%ld;p_span=%lu;r_span=%lu;p_drift=%lu;r_drift=%lu;p_rej=%lu;r_rej=%lu;p_fault=%lu;r_fault=%lu;timeout=%u",
                                   static_cast<unsigned long>(kPressureIdleMs),
                                   static_cast<long>(meanIdle(pIdle)),
                                   static_cast<long>(meanIdle(rIdle)),
                                   static_cast<unsigned long>(spanIdle(pIdle)),
                                   static_cast<unsigned long>(spanIdle(rIdle)),
                                   static_cast<unsigned long>(pDrift),
                                   static_cast<unsigned long>(rDrift),
                                   static_cast<unsigned long>(pRejects),
                                   static_cast<unsigned long>(rRejects),
                                   static_cast<unsigned long>(pFault),
                                   static_cast<unsigned long>(rFault),
                                   static_cast<unsigned>(timeout ? 1u : 0u));
                          if (!runOne(2210, "pressure_sensor_idle_stability_factory", idlePass, metrics)) {
                            closePressureSuitePaths();
                            return finishSelfTestNow();
                          }
                        }

                        {
                          sendProgressStage("pressure_reg_home_repeat");
                          const bool hasP = channelAvailable(0u);
                          const bool hasR = channelAvailable(1u);
                          int32_t pHomes[kRegHomeReps]{};
                          int32_t rHomes[kRegHomeReps]{};
                          size_t pCount = 0u;
                          size_t rCount = 0u;
                          uint32_t pMoveTo = 0u;
                          uint32_t rMoveTo = 0u;
                          uint32_t pHomeTo = hasP ? 0u : 1u;
                          uint32_t rHomeTo = hasR ? 0u : 1u;
                          bool pSetupOk = hasP;
                          bool rSetupOk = hasR;
                          if (hasP) {
                            const PressureHomeReference setup = homePressureReference(0u, "pressure_reg_home_setup_p");
                            pMoveTo += setup.moveTo;
                            pHomeTo += setup.homeTo;
                            pSetupOk = setup.ok;
                          }
                          if (hasR) {
                            const PressureHomeReference setup = homePressureReference(1u, "pressure_reg_home_setup_r");
                            rMoveTo += setup.moveTo;
                            rHomeTo += setup.homeTo;
                            rSetupOk = setup.ok;
                          }
                          for (uint32_t rep = 0u; rep < kRegHomeReps; ++rep) {
                            closePressureSuitePaths();
                            EventBits_t homeBits = 0u;
                            if (hasP && pSetupOk) homeBits |= homeBitFor(0u);
                            if (hasR && rSetupOk) homeBits |= homeBitFor(1u);
                            if (homeBits == 0u) {
                              break;
                            }
                            xEventGroupClearBits(_doneEvents, homeBits);
                            if (hasP && pSetupOk) {
                              startRegHomeAsync(&PressureRegulator::regP(),
                                                kRegHomeFastHz,
                                                kRegHomeSlowHz,
                                                kRegHomeBackoffSteps,
                                                BIT_HOME_P_DONE);
                            }
#if (LC_PRESSURE_PORTS > 1)
                            if (hasR && rSetupOk) {
                              startRegHomeAsync(&PressureRegulator::regR(),
                                                kRegHomeFastHz,
                                                kRegHomeSlowHz,
                                                kRegHomeBackoffSteps,
                                                BIT_HOME_R_DONE);
                            }
#endif
                            const bool homesDone = waitBitsWithTimeout(homeBits, kRegHomeTimeoutMs);
                            const EventBits_t doneBits = xEventGroupGetBits(_doneEvents);
                            if (hasP && pSetupOk) {
                              const Stepper::HomeDiagnosticSnapshot pDiag =
                                  Stepper::stepperP()->getLastHomeDiagnosticSnapshot();
                              pMoveTo += pDiag.moveTimeoutCount;
                              if (homesDone && ((doneBits & BIT_HOME_P_DONE) != 0u) && pDiag.success) {
                                pHomes[pCount++] = pDiag.fineLimitPositionSteps;
                              } else {
                                pHomeTo++;
                              }
                            }
#if (LC_PRESSURE_PORTS > 1)
                            if (hasR && rSetupOk) {
                              const Stepper::HomeDiagnosticSnapshot rDiag =
                                  Stepper::stepperR()->getLastHomeDiagnosticSnapshot();
                              rMoveTo += rDiag.moveTimeoutCount;
                              if (homesDone && ((doneBits & BIT_HOME_R_DONE) != 0u) && rDiag.success) {
                                rHomes[rCount++] = rDiag.fineLimitPositionSteps;
                              } else {
                                rHomeTo++;
                              }
                            }
#endif
                            if (_selfTestAbortRequested) {
                              break;
                            }
                          }
                          closePressureSuitePaths();
                          const auto pSummary = PressureQualificationMath::summarizeHomeRepeatability(
                              pHomes,
                              pCount,
                              kRegHomeReps,
                              pMoveTo,
                              pHomeTo);
                          const auto rSummary = PressureQualificationMath::summarizeHomeRepeatability(
                              rHomes,
                              rCount,
                              kRegHomeReps,
                              rMoveTo,
                              rHomeTo);
                          const bool homePass = hasP && hasR && pSummary.pass && rSummary.pass;
                          char metrics[160];
                          snprintf(metrics, sizeof(metrics),
                                   "rep=%lu;p_n=%lu;r_n=%lu;p_span=%lu;r_span=%lu;p_drift=%lu;r_drift=%lu;p_move_to=%lu;r_move_to=%lu;p_home_to=%lu;r_home_to=%lu",
                                   static_cast<unsigned long>(kRegHomeReps),
                                   static_cast<unsigned long>(pSummary.sampleCount),
                                   static_cast<unsigned long>(rSummary.sampleCount),
                                   static_cast<unsigned long>(pSummary.span),
                                   static_cast<unsigned long>(rSummary.span),
                                   static_cast<unsigned long>(pSummary.drift),
                                   static_cast<unsigned long>(rSummary.drift),
                                   static_cast<unsigned long>(pMoveTo),
                                   static_cast<unsigned long>(rMoveTo),
                                   static_cast<unsigned long>(pHomeTo),
                                   static_cast<unsigned long>(rHomeTo));
                          if (!runOne(2211, "pressure_regulator_home_repeatability_factory", homePass, metrics)) {
                            return finishSelfTestNow();
                          }
                        }

                        auto runPressureHold = [&](uint16_t testId, const char* name, uint8_t channel) -> bool {
                          if (!channelAvailable(channel)) {
                            return emitUnavailableChannel(
                                testId,
                                name,
                                channel,
                                "target_raw=3386;hold_ms=15000;slope_raw_min=0;corr_steps=0;home_to=1;ready_miss=0;timeout=0;guard=0;motor_abs_max=0;motor_delta_max=0;max_jump=874;slew=1;cap_hz=16000");
                          }
                          sendProgressStage((channel == 0u) ? "pressure_hold_print" : "pressure_hold_refuel");
                          const PressureHomeReference homeRef = homePressureReference(
                              channel,
                              (channel == 0u) ? "pressure_hold_home_print" : "pressure_hold_home_refuel");
                          if (!homeRef.ok) {
                            char metrics[224];
                            snprintf(metrics, sizeof(metrics),
                                     "ch=%c;gate=home_reference;target_raw=%lu;hold_ms=%lu;slope_raw_min=0;corr_steps=0;home_to=%lu;ready_miss=0;timeout=0;guard=0;motor_abs_max=0;motor_delta_max=0;max_jump=0;slew=1;cap_hz=%lu",
                                     channelCode(channel),
                                     static_cast<unsigned long>(kPressure2Raw),
                                     static_cast<unsigned long>(kPressureHoldMs),
                                     static_cast<unsigned long>((homeRef.homeTo > 0u) ? homeRef.homeTo : 1u),
                                     static_cast<unsigned long>(PressureRegulator::kSetpointSlewSpeedCapHz));
                            return runOne(testId, name, false, metrics);
                          }
                          PressureQualificationMath::ExecutionSummary exec{};
                          PressureQualificationMath::MotorTravelGuardState guardState{};
                          PressureRegulator& reg = regulatorFor(channel);
                          const int32_t baselineTarget = static_cast<int32_t>(reg.getTarget());
                          uint32_t settleMaxMs = 0u;
                          uint32_t errMax = 0u;
                          uint32_t maxJumpRaw = 0u;
                          int32_t pressureStart = 0;
                          int32_t pressureEnd = 0;
                          int32_t motorStart = 0;
                          int32_t motorEnd = 0;
                          reg.closeValve();
                          reg.start();
                          const PressureWaitResult ready = waitForAdjacentPressureTarget(channel,
                                                                                         kPressure2Raw,
                                                                                         exec,
                                                                                         settleMaxMs,
                                                                                         errMax,
                                                                                         nullptr,
                                                                                         nullptr,
                                                                                         guardState,
                                                                                         maxJumpRaw);
                          const int32_t targetRaw = static_cast<int32_t>(reg.getTarget());
                          if (ready.accepted && !_selfTestAbortRequested) {
                            const PressurePositionSample startSample = readPressurePositionSample(channel);
                            pressureStart = startSample.pressureRaw;
                            motorStart = startSample.motorPosition;
                            if (!delayWithWatchdog(kPressureHoldMs, "pressure_reg_hold")) {
                              exec.abortCount++;
                            }
                            const PressurePositionSample endSample = readPressurePositionSample(channel);
                            pressureEnd = endSample.pressureRaw;
                            motorEnd = endSample.motorPosition;
                          }
                          restorePressureChannel(channel, baselineTarget, exec, settleMaxMs, errMax, guardState, maxJumpRaw);
                          const int32_t slopeRawPerMin =
                              PressureQualificationMath::slopeRawPerMin(pressureStart, pressureEnd, kPressureHoldMs);
                          const uint32_t correctionSteps =
                              PressureQualificationMath::absDiff(motorStart, motorEnd);
                          const bool pass = PressureQualificationMath::executionPass(exec);
                          char metrics[256];
                          snprintf(metrics, sizeof(metrics),
                                   "ch=%c;target_raw=%ld;hold_ms=%lu;slope_raw_min=%ld;corr_steps=%lu;home_to=%lu;ready_miss=%lu;timeout=%lu;guard=%lu;motor_abs_max=%lu;motor_delta_max=%lu;max_jump=%lu;slew=1;cap_hz=%lu",
                                   channelCode(channel),
                                   static_cast<long>(targetRaw),
                                   static_cast<unsigned long>(kPressureHoldMs),
                                   static_cast<long>(slopeRawPerMin),
                                   static_cast<unsigned long>(correctionSteps),
                                   static_cast<unsigned long>(homeRef.homeTo),
                                   static_cast<unsigned long>(exec.readyMissCount),
                                   static_cast<unsigned long>(exec.timeoutCount + exec.abortCount),
                                   static_cast<unsigned long>(exec.motorGuardCount),
                                   static_cast<unsigned long>(guardState.motorAbsMax),
                                   static_cast<unsigned long>(guardState.motorDeltaMax),
                                   static_cast<unsigned long>(maxJumpRaw),
                                   static_cast<unsigned long>(PressureRegulator::kSetpointSlewSpeedCapHz));
                          return runOne(testId, name, pass, metrics);
                        };

                        auto runPressureCycle = [&](uint16_t testId, const char* name, uint8_t channel) -> bool {
                          if (!channelAvailable(channel)) {
                            return emitUnavailableChannel(
                                testId,
                                name,
                                channel,
                                "settle_max_ms=0;err_max=0;low_dn_span=0;high_up_span=0;over=0;under=0;home_to=1;ready_miss=0;timeout=0;guard=0;motor_abs_max=0;motor_delta_max=0;max_jump=874;slew=1;cap_hz=16000");
                          }
                          sendProgressStage((channel == 0u) ? "pressure_cycle_print" : "pressure_cycle_refuel");
                          const PressureHomeReference homeRef = homePressureReference(
                              channel,
                              (channel == 0u) ? "pressure_cycle_home_print" : "pressure_cycle_home_refuel");
                          if (!homeRef.ok) {
                            char metrics[224];
                            snprintf(metrics, sizeof(metrics),
                                     "ch=%c;gate=home_reference;settle_max_ms=0;err_max=0;low_dn_span=0;high_up_span=0;over=0;under=0;home_to=%lu;ready_miss=0;timeout=0;guard=0;motor_abs_max=0;motor_delta_max=0;max_jump=0;slew=1;cap_hz=%lu",
                                     channelCode(channel),
                                     static_cast<unsigned long>((homeRef.homeTo > 0u) ? homeRef.homeTo : 1u),
                                     static_cast<unsigned long>(PressureRegulator::kSetpointSlewSpeedCapHz));
                            return runOne(testId, name, false, metrics);
                          }
                          PressureQualificationMath::ExecutionSummary exec{};
                          PressureQualificationMath::MotorTravelGuardState guardState{};
                          PressureRegulator& reg = regulatorFor(channel);
                          const int32_t baselineTarget = static_cast<int32_t>(reg.getTarget());
                          int32_t lowPositions[kCycleCount]{};
                          int32_t highPositions[kCycleCount]{};
                          size_t lowCount = 0u;
                          size_t highCount = 0u;
                          uint32_t settleMaxMs = 0u;
                          uint32_t errMax = 0u;
                          uint32_t overMax = 0u;
                          uint32_t underMax = 0u;
                          uint32_t maxJumpRaw = 0u;
                          reg.closeValve();
                          reg.start();
                          const PressureWaitResult setupWait = waitForAdjacentPressureTarget(channel,
                                                                                             kPressure2Raw,
                                                                                             exec,
                                                                                             settleMaxMs,
                                                                                             errMax,
                                                                                             &overMax,
                                                                                             &underMax,
                                                                                             guardState,
                                                                                             maxJumpRaw);
                          for (uint32_t cycle = 0u; cycle < kCycleCount; ++cycle) {
                            if (!setupWait.accepted || pressureMotorGuardTripped || _selfTestAbortRequested) break;
                            const PressureWaitResult lowWait = waitForAdjacentPressureTarget(channel,
                                                                                             kPressure1Raw,
                                                                                             exec,
                                                                                             settleMaxMs,
                                                                                             errMax,
                                                                                             &overMax,
                                                                                             &underMax,
                                                                                             guardState,
                                                                                             maxJumpRaw);
                            if (!lowWait.accepted || pressureMotorGuardTripped || _selfTestAbortRequested) break;
                            const PressurePositionSample lowSample = readPressurePositionSample(channel);
                            if (lowCount < kCycleCount) lowPositions[lowCount++] = lowSample.motorPosition;
                            const PressureWaitResult midWait = waitForAdjacentPressureTarget(channel,
                                                                                             kPressure2Raw,
                                                                                             exec,
                                                                                             settleMaxMs,
                                                                                             errMax,
                                                                                             &overMax,
                                                                                             &underMax,
                                                                                             guardState,
                                                                                             maxJumpRaw);
                            if (!midWait.accepted || pressureMotorGuardTripped || _selfTestAbortRequested) break;
                            const PressureWaitResult highWait = waitForAdjacentPressureTarget(channel,
                                                                                              kPressure3Raw,
                                                                                              exec,
                                                                                              settleMaxMs,
                                                                                              errMax,
                                                                                              &overMax,
                                                                                              &underMax,
                                                                                              guardState,
                                                                                              maxJumpRaw);
                            if (!highWait.accepted || pressureMotorGuardTripped || _selfTestAbortRequested) break;
                            const PressurePositionSample highSample = readPressurePositionSample(channel);
                            if (highCount < kCycleCount) highPositions[highCount++] = highSample.motorPosition;
                            const PressureWaitResult returnMidWait = waitForAdjacentPressureTarget(channel,
                                                                                                   kPressure2Raw,
                                                                                                   exec,
                                                                                                   settleMaxMs,
                                                                                                   errMax,
                                                                                                   &overMax,
                                                                                                   &underMax,
                                                                                                   guardState,
                                                                                                   maxJumpRaw);
                            if (!returnMidWait.accepted || pressureMotorGuardTripped || _selfTestAbortRequested) break;
                          }
                          restorePressureChannel(channel, baselineTarget, exec, settleMaxMs, errMax, guardState, maxJumpRaw);
                          const auto lowStats = PressureQualificationMath::summarizeInt32Span(lowPositions, lowCount);
                          const auto highStats = PressureQualificationMath::summarizeInt32Span(highPositions, highCount);
                          const bool pass = (lowCount == kCycleCount) &&
                                            (highCount == kCycleCount) &&
                                            PressureQualificationMath::executionPass(exec);
                          char metrics[256];
                          snprintf(metrics, sizeof(metrics),
                                   "ch=%c;settle_max_ms=%lu;err_max=%lu;low_dn_span=%lu;high_up_span=%lu;over=%lu;under=%lu;home_to=%lu;ready_miss=%lu;timeout=%lu;guard=%lu;motor_abs_max=%lu;motor_delta_max=%lu;max_jump=%lu;slew=1;cap_hz=%lu",
                                   channelCode(channel),
                                   static_cast<unsigned long>(settleMaxMs),
                                   static_cast<unsigned long>(errMax),
                                   static_cast<unsigned long>(lowStats.span),
                                   static_cast<unsigned long>(highStats.span),
                                   static_cast<unsigned long>(overMax),
                                   static_cast<unsigned long>(underMax),
                                   static_cast<unsigned long>(homeRef.homeTo),
                                   static_cast<unsigned long>(exec.readyMissCount),
                                   static_cast<unsigned long>(exec.timeoutCount + exec.abortCount),
                                   static_cast<unsigned long>(exec.motorGuardCount),
                                   static_cast<unsigned long>(guardState.motorAbsMax),
                                   static_cast<unsigned long>(guardState.motorDeltaMax),
                                   static_cast<unsigned long>(maxJumpRaw),
                                   static_cast<unsigned long>(PressureRegulator::kSetpointSlewSpeedCapHz));
                          return runOne(testId, name, pass, metrics);
                        };

                        auto runPressureHysteresis = [&](uint16_t testId, const char* name, uint8_t channel) -> bool {
                          if (!channelAvailable(channel)) {
                            return emitUnavailableChannel(
                                testId,
                                name,
                                channel,
                                "target_raw=3386;below_span=0;above_span=0;hyst_span=0;err_max=0;home_to=1;ready_miss=0;timeout=0;guard=0;motor_abs_max=0;motor_delta_max=0;max_jump=874;slew=1;cap_hz=16000");
                          }
                          sendProgressStage((channel == 0u) ? "pressure_hyst_print" : "pressure_hyst_refuel");
                          const PressureHomeReference homeRef = homePressureReference(
                              channel,
                              (channel == 0u) ? "pressure_hyst_home_print" : "pressure_hyst_home_refuel");
                          if (!homeRef.ok) {
                            char metrics[224];
                            snprintf(metrics, sizeof(metrics),
                                     "ch=%c;gate=home_reference;target_raw=%lu;below_span=0;above_span=0;hyst_span=0;err_max=0;home_to=%lu;ready_miss=0;timeout=0;guard=0;motor_abs_max=0;motor_delta_max=0;max_jump=0;slew=1;cap_hz=%lu",
                                     channelCode(channel),
                                     static_cast<unsigned long>(kPressure2Raw),
                                     static_cast<unsigned long>((homeRef.homeTo > 0u) ? homeRef.homeTo : 1u),
                                     static_cast<unsigned long>(PressureRegulator::kSetpointSlewSpeedCapHz));
                            return runOne(testId, name, false, metrics);
                          }
                          PressureQualificationMath::ExecutionSummary exec{};
                          PressureQualificationMath::MotorTravelGuardState guardState{};
                          PressureRegulator& reg = regulatorFor(channel);
                          const int32_t baselineTarget = static_cast<int32_t>(reg.getTarget());
                          int32_t belowPositions[kHysteresisReps]{};
                          int32_t abovePositions[kHysteresisReps]{};
                          size_t belowCount = 0u;
                          size_t aboveCount = 0u;
                          uint32_t settleMaxMs = 0u;
                          uint32_t errMax = 0u;
                          uint32_t maxJumpRaw = 0u;
                          reg.closeValve();
                          reg.start();
                          for (uint32_t rep = 0u; rep < kHysteresisReps; ++rep) {
                            const PressureWaitResult lowWait = waitForAdjacentPressureTarget(channel,
                                                                                             kPressure1Raw,
                                                                                             exec,
                                                                                             settleMaxMs,
                                                                                             errMax,
                                                                                             nullptr,
                                                                                             nullptr,
                                                                                             guardState,
                                                                                             maxJumpRaw);
                            if (!lowWait.accepted || pressureMotorGuardTripped || _selfTestAbortRequested) break;
                            const PressureWaitResult fromBelow = waitForAdjacentPressureTarget(channel,
                                                                                               kPressure2Raw,
                                                                                               exec,
                                                                                               settleMaxMs,
                                                                                               errMax,
                                                                                               nullptr,
                                                                                               nullptr,
                                                                                               guardState,
                                                                                               maxJumpRaw);
                            if (!fromBelow.accepted || pressureMotorGuardTripped || _selfTestAbortRequested) break;
                            const PressurePositionSample belowSample = readPressurePositionSample(channel);
                            if (belowCount < kHysteresisReps) belowPositions[belowCount++] = belowSample.motorPosition;

                            const PressureWaitResult highWait = waitForAdjacentPressureTarget(channel,
                                                                                              kPressure3Raw,
                                                                                              exec,
                                                                                              settleMaxMs,
                                                                                              errMax,
                                                                                              nullptr,
                                                                                              nullptr,
                                                                                              guardState,
                                                                                              maxJumpRaw);
                            if (!highWait.accepted || pressureMotorGuardTripped || _selfTestAbortRequested) break;
                            const PressureWaitResult fromAbove = waitForAdjacentPressureTarget(channel,
                                                                                               kPressure2Raw,
                                                                                               exec,
                                                                                               settleMaxMs,
                                                                                               errMax,
                                                                                               nullptr,
                                                                                               nullptr,
                                                                                               guardState,
                                                                                               maxJumpRaw);
                            if (!fromAbove.accepted || pressureMotorGuardTripped || _selfTestAbortRequested) break;
                            const PressurePositionSample aboveSample = readPressurePositionSample(channel);
                            if (aboveCount < kHysteresisReps) abovePositions[aboveCount++] = aboveSample.motorPosition;
                          }
                          restorePressureChannel(channel, baselineTarget, exec, settleMaxMs, errMax, guardState, maxJumpRaw);
                          const auto belowStats = PressureQualificationMath::summarizeInt32Span(belowPositions, belowCount);
                          const auto aboveStats = PressureQualificationMath::summarizeInt32Span(abovePositions, aboveCount);
                          const uint32_t hystSpan =
                              PressureQualificationMath::meanDifferenceAbs(belowPositions,
                                                                           belowCount,
                                                                           abovePositions,
                                                                           aboveCount);
                          const bool pass = (belowCount == kHysteresisReps) &&
                                            (aboveCount == kHysteresisReps) &&
                                            PressureQualificationMath::executionPass(exec);
                          char metrics[256];
                          snprintf(metrics, sizeof(metrics),
                                   "ch=%c;target_raw=%lu;below_span=%lu;above_span=%lu;hyst_span=%lu;err_max=%lu;home_to=%lu;ready_miss=%lu;timeout=%lu;guard=%lu;motor_abs_max=%lu;motor_delta_max=%lu;max_jump=%lu;slew=1;cap_hz=%lu",
                                   channelCode(channel),
                                   static_cast<unsigned long>(kPressure2Raw),
                                   static_cast<unsigned long>(belowStats.span),
                                   static_cast<unsigned long>(aboveStats.span),
                                   static_cast<unsigned long>(hystSpan),
                                   static_cast<unsigned long>(errMax),
                                   static_cast<unsigned long>(homeRef.homeTo),
                                   static_cast<unsigned long>(exec.readyMissCount),
                                   static_cast<unsigned long>(exec.timeoutCount + exec.abortCount),
                                   static_cast<unsigned long>(exec.motorGuardCount),
                                   static_cast<unsigned long>(guardState.motorAbsMax),
                                   static_cast<unsigned long>(guardState.motorDeltaMax),
                                   static_cast<unsigned long>(maxJumpRaw),
                                   static_cast<unsigned long>(PressureRegulator::kSetpointSlewSpeedCapHz));
                          return runOne(testId, name, pass, metrics);
                        };

                        auto runPressureStepLadder = [&](uint16_t testId, const char* name, uint8_t channel) -> bool {
                          if (!channelAvailable(channel)) {
                            return emitUnavailableChannel(
                                testId,
                                name,
                                channel,
                                "raw1=2512;raw2=3386;raw3=4259;settle_max_ms=0;err_max=0;over=0;under=0;home_to=1;ready_miss=0;timeout=0;guard=0;motor_abs_max=0;motor_delta_max=0;max_jump=874;slew=1;cap_hz=16000");
                          }
                          sendProgressStage((channel == 0u) ? "pressure_ladder_print" : "pressure_ladder_refuel");
                          const PressureHomeReference homeRef = homePressureReference(
                              channel,
                              (channel == 0u) ? "pressure_ladder_home_print" : "pressure_ladder_home_refuel");
                          if (!homeRef.ok) {
                            char metrics[224];
                            snprintf(metrics, sizeof(metrics),
                                     "ch=%c;gate=home_reference;raw1=%lu;raw2=%lu;raw3=%lu;settle_max_ms=0;err_max=0;over=0;under=0;home_to=%lu;ready_miss=0;timeout=0;guard=0;motor_abs_max=0;motor_delta_max=0;max_jump=0;slew=1;cap_hz=%lu",
                                     channelCode(channel),
                                     static_cast<unsigned long>(kPressure1Raw),
                                     static_cast<unsigned long>(kPressure2Raw),
                                     static_cast<unsigned long>(kPressure3Raw),
                                     static_cast<unsigned long>((homeRef.homeTo > 0u) ? homeRef.homeTo : 1u),
                                     static_cast<unsigned long>(PressureRegulator::kSetpointSlewSpeedCapHz));
                            return runOne(testId, name, false, metrics);
                          }
                          const uint16_t targets[kLadderPointCount] = {
                              kPressure1Raw,
                              kPressure2Raw,
                              kPressure3Raw,
                              kPressure2Raw,
                              kPressure1Raw,
                          };
                          PressureQualificationMath::ExecutionSummary exec{};
                          PressureQualificationMath::MotorTravelGuardState guardState{};
                          PressureRegulator& reg = regulatorFor(channel);
                          const int32_t baselineTarget = static_cast<int32_t>(reg.getTarget());
                          size_t allCount = 0u;
                          uint32_t settleMaxMs = 0u;
                          uint32_t errMax = 0u;
                          uint32_t overMax = 0u;
                          uint32_t underMax = 0u;
                          uint32_t maxJumpRaw = 0u;
                          reg.closeValve();
                          reg.start();
                          for (uint32_t idx = 0u; idx < kLadderPointCount; ++idx) {
                            const uint16_t target = targets[idx];
                            const PressureWaitResult wait = waitForAdjacentPressureTarget(channel,
                                                                                          target,
                                                                                          exec,
                                                                                          settleMaxMs,
                                                                                          errMax,
                                                                                          &overMax,
                                                                                          &underMax,
                                                                                          guardState,
                                                                                          maxJumpRaw);
                            if (!wait.accepted || pressureMotorGuardTripped || _selfTestAbortRequested) break;
                            if (allCount < kLadderPointCount) allCount++;
                          }
                          restorePressureChannel(channel, baselineTarget, exec, settleMaxMs, errMax, guardState, maxJumpRaw);
                          const bool pass = (allCount == kLadderPointCount) &&
                                            PressureQualificationMath::executionPass(exec);
                          char metrics[256];
                          snprintf(metrics, sizeof(metrics),
                                   "ch=%c;raw1=%lu;raw2=%lu;raw3=%lu;settle_max_ms=%lu;err_max=%lu;over=%lu;under=%lu;home_to=%lu;ready_miss=%lu;timeout=%lu;guard=%lu;motor_abs_max=%lu;motor_delta_max=%lu;max_jump=%lu;slew=1;cap_hz=%lu",
                                   channelCode(channel),
                                   static_cast<unsigned long>(kPressure1Raw),
                                   static_cast<unsigned long>(kPressure2Raw),
                                   static_cast<unsigned long>(kPressure3Raw),
                                   static_cast<unsigned long>(settleMaxMs),
                                   static_cast<unsigned long>(errMax),
                                   static_cast<unsigned long>(overMax),
                                   static_cast<unsigned long>(underMax),
                                   static_cast<unsigned long>(homeRef.homeTo),
                                   static_cast<unsigned long>(exec.readyMissCount),
                                   static_cast<unsigned long>(exec.timeoutCount + exec.abortCount),
                                   static_cast<unsigned long>(exec.motorGuardCount),
                                   static_cast<unsigned long>(guardState.motorAbsMax),
                                   static_cast<unsigned long>(guardState.motorDeltaMax),
                                   static_cast<unsigned long>(maxJumpRaw),
                                   static_cast<unsigned long>(PressureRegulator::kSetpointSlewSpeedCapHz));
                          return runOne(testId, name, pass, metrics);
                        };

                        auto emitPressureMotorGuardRows = [&](uint16_t firstTestId) -> bool {
                          auto emitHold = [&](uint16_t testId, const char* name, uint8_t channel) -> bool {
                            char metrics[256];
                            snprintf(metrics, sizeof(metrics),
                                     "ch=%c;gate=motor_guard;target_raw=%lu;hold_ms=%lu;slope_raw_min=0;corr_steps=0;home_to=0;ready_miss=0;timeout=0;guard=1;motor_abs_max=0;motor_delta_max=0;max_jump=%lu;slew=1;cap_hz=%lu",
                                     channelCode(channel),
                                     static_cast<unsigned long>(kPressure2Raw),
                                     static_cast<unsigned long>(kPressureHoldMs),
                                     static_cast<unsigned long>(kMaxPressureJumpRaw),
                                     static_cast<unsigned long>(PressureRegulator::kSetpointSlewSpeedCapHz));
                            return runOne(testId, name, false, metrics);
                          };
                          auto emitCycle = [&](uint16_t testId, const char* name, uint8_t channel) -> bool {
                            char metrics[256];
                            snprintf(metrics, sizeof(metrics),
                                     "ch=%c;gate=motor_guard;settle_max_ms=0;err_max=0;low_dn_span=0;high_up_span=0;over=0;under=0;home_to=0;ready_miss=0;timeout=0;guard=1;motor_abs_max=0;motor_delta_max=0;max_jump=%lu;slew=1;cap_hz=%lu",
                                     channelCode(channel),
                                     static_cast<unsigned long>(kMaxPressureJumpRaw),
                                     static_cast<unsigned long>(PressureRegulator::kSetpointSlewSpeedCapHz));
                            return runOne(testId, name, false, metrics);
                          };
                          auto emitHysteresis = [&](uint16_t testId, const char* name, uint8_t channel) -> bool {
                            char metrics[256];
                            snprintf(metrics, sizeof(metrics),
                                     "ch=%c;gate=motor_guard;target_raw=%lu;below_span=0;above_span=0;hyst_span=0;err_max=0;home_to=0;ready_miss=0;timeout=0;guard=1;motor_abs_max=0;motor_delta_max=0;max_jump=%lu;slew=1;cap_hz=%lu",
                                     channelCode(channel),
                                     static_cast<unsigned long>(kPressure2Raw),
                                     static_cast<unsigned long>(kMaxPressureJumpRaw),
                                     static_cast<unsigned long>(PressureRegulator::kSetpointSlewSpeedCapHz));
                            return runOne(testId, name, false, metrics);
                          };
                          auto emitLadder = [&](uint16_t testId, const char* name, uint8_t channel) -> bool {
                            char metrics[256];
                            snprintf(metrics, sizeof(metrics),
                                     "ch=%c;gate=motor_guard;raw1=%lu;raw2=%lu;raw3=%lu;settle_max_ms=0;err_max=0;over=0;under=0;home_to=0;ready_miss=0;timeout=0;guard=1;motor_abs_max=0;motor_delta_max=0;max_jump=%lu;slew=1;cap_hz=%lu",
                                     channelCode(channel),
                                     static_cast<unsigned long>(kPressure1Raw),
                                     static_cast<unsigned long>(kPressure2Raw),
                                     static_cast<unsigned long>(kPressure3Raw),
                                     static_cast<unsigned long>(kMaxPressureJumpRaw),
                                     static_cast<unsigned long>(PressureRegulator::kSetpointSlewSpeedCapHz));
                            return runOne(testId, name, false, metrics);
                          };
                          if ((firstTestId <= 2212u) && !emitHold(2212, "pressure_hold_leak_print_factory", 0u)) return false;
                          if ((firstTestId <= 2213u) && !emitHold(2213, "pressure_hold_leak_refuel_factory", 1u)) return false;
                          if ((firstTestId <= 2214u) && !emitCycle(2214, "pressure_target_cycle_print_factory", 0u)) return false;
                          if ((firstTestId <= 2215u) && !emitCycle(2215, "pressure_target_cycle_refuel_factory", 1u)) return false;
                          if ((firstTestId <= 2216u) && !emitHysteresis(2216, "pressure_motor_hysteresis_print_factory", 0u)) return false;
                          if ((firstTestId <= 2217u) && !emitHysteresis(2217, "pressure_motor_hysteresis_refuel_factory", 1u)) return false;
                          if ((firstTestId <= 2218u) && !emitLadder(2218, "pressure_step_ladder_print_factory", 0u)) return false;
                          if ((firstTestId <= 2219u) && !emitLadder(2219, "pressure_step_ladder_refuel_factory", 1u)) return false;
                          return true;
                        };

                        if (!runPressureHold(2212, "pressure_hold_leak_print_factory", 0u)) {
                          closePressureSuitePaths();
                          return finishSelfTestNow();
                        }
                        if (pressureMotorGuardTripped) {
                          (void)emitPressureMotorGuardRows(2213u);
                          closePressureSuitePaths();
                          return finishSelfTestNow();
                        }
                        if (!runPressureHold(2213, "pressure_hold_leak_refuel_factory", 1u)) {
                          closePressureSuitePaths();
                          return finishSelfTestNow();
                        }
                        if (pressureMotorGuardTripped) {
                          (void)emitPressureMotorGuardRows(2214u);
                          closePressureSuitePaths();
                          return finishSelfTestNow();
                        }
                        if (!runPressureCycle(2214, "pressure_target_cycle_print_factory", 0u)) {
                          closePressureSuitePaths();
                          return finishSelfTestNow();
                        }
                        if (pressureMotorGuardTripped) {
                          (void)emitPressureMotorGuardRows(2215u);
                          closePressureSuitePaths();
                          return finishSelfTestNow();
                        }
                        if (!runPressureCycle(2215, "pressure_target_cycle_refuel_factory", 1u)) {
                          closePressureSuitePaths();
                          return finishSelfTestNow();
                        }
                        if (pressureMotorGuardTripped) {
                          (void)emitPressureMotorGuardRows(2216u);
                          closePressureSuitePaths();
                          return finishSelfTestNow();
                        }
                        if (!runPressureHysteresis(2216, "pressure_motor_hysteresis_print_factory", 0u)) {
                          closePressureSuitePaths();
                          return finishSelfTestNow();
                        }
                        if (pressureMotorGuardTripped) {
                          (void)emitPressureMotorGuardRows(2217u);
                          closePressureSuitePaths();
                          return finishSelfTestNow();
                        }
                        if (!runPressureHysteresis(2217, "pressure_motor_hysteresis_refuel_factory", 1u)) {
                          closePressureSuitePaths();
                          return finishSelfTestNow();
                        }
                        if (pressureMotorGuardTripped) {
                          (void)emitPressureMotorGuardRows(2218u);
                          closePressureSuitePaths();
                          return finishSelfTestNow();
                        }
                        if (!runPressureStepLadder(2218, "pressure_step_ladder_print_factory", 0u)) {
                          closePressureSuitePaths();
                          return finishSelfTestNow();
                        }
                        if (pressureMotorGuardTripped) {
                          (void)emitPressureMotorGuardRows(2219u);
                          closePressureSuitePaths();
                          return finishSelfTestNow();
                        }
                        if (!runPressureStepLadder(2219, "pressure_step_ladder_refuel_factory", 1u)) {
                          closePressureSuitePaths();
                          return finishSelfTestNow();
                        }
                        if (pressureMotorGuardTripped) {
                          closePressureSuitePaths();
                          return finishSelfTestNow();
                        }

                        closePressureSuitePaths();
                        return finishSelfTestNow();
                      }

                      struct PressureTraceCaseMetrics {
                        uint32_t baselinePressure = 0u;
                        uint32_t minPressure = 0u;
                        uint32_t maxPressure = 0u;
                        uint32_t maxUndershoot = 0u;
                        uint32_t maxOvershoot = 0u;
                        uint32_t worstRecoveryMs = 0u;
                        uint32_t meanRecoveryMs = 0u;
                        uint32_t readyMissCount = 0u;
                        uint32_t maxDeadlineSlipMs = 0u;
                        uint32_t meanDeadlineSlipMs = 0u;
                        uint32_t zeroCrossCount = 0u;
                        uint32_t sampleRejectCount = 0u;
                        uint32_t traceSampleCount = 0u;
                        uint32_t traceEventCount = 0u;
                        ValvePulseQualificationMath::PulseDropSummary pulseDrop{};
                        ValvePulseQualificationMath::WindowedPulseResponseSummary pulseResponse{};
                        bool pass = false;
                      };

                      auto maybeExportTrace = [&](bool shouldExport,
                                                  uint16_t testId,
                                                  const char* name,
                                                  bool pass) -> bool {
                        if (!shouldExport) {
                          return true;
                        }
                        return exportTrace(testId, name, pass);
                      };

                      auto runPressureTraceCase = [&](uint16_t testId,
                                                      const char* name,
                                                      uint8_t channel,
                                                      uint16_t targetRaw,
                                                      uint16_t pulseWidthUs,
                                                      uint16_t dropletCount,
                                                      uint16_t rateHz,
                                                      PulseMode mode,
                                                      bool requireBothReady,
                                                      uint16_t secondaryTargetRaw,
                                                      uint16_t secondaryPulseWidthUs,
                                                      PressureTraceCaseMetrics* outMetrics,
                                                      bool emitResult,
                                                      bool shouldExportTrace) {
                        static constexpr uint32_t kPressureStabilizationMs = 1000u;
                        sendProgressStage("trace_case_enter");
                        PressureTraceCaseMetrics computed{};
                        if (!fullProfile) {
                          if (emitResult) {
                            return runOne(testId, name, true, "profile=SAFE;executed=0;fixture_required=1;pressure_trace=0;gate=safe_only");
                          }
                          computed.pass = true;
                          if (outMetrics) *outMetrics = computed;
                          return true;
                        }
                        if (!fullHomePass && !pressureSweepOnly && !selectedPressureHomePass) {
                          if (emitResult) {
                            return runOne(testId, name, false, "base=0;min=0;max=0;under=0;over=0;rec_w=0;rec_m=0;ready_miss=1;slip_w=0;slip_m=0;zero=0;rejects=0;sc=0;ec=0");
                          }
                          if (outMetrics) *outMetrics = computed;
                          return false;
                        }

                        auto& recorder = PressureTraceRecorder::instance();
                        recorder.reset();
                        PressureTraceConfig traceCfg{};
                        traceCfg.channel = (channel == 0u) ? PressureTraceChannel::Print : PressureTraceChannel::Refuel;
                        traceCfg.maxSamples = PressureTraceRecorder::kMaxSamples;
                        traceCfg.maxEvents = PressureTraceRecorder::kMaxEvents;
                        recorder.configure(traceCfg);

                        Printer* printer = Printer::instance();
                        if ((printer == nullptr) || (PressureSensor::instance() == nullptr)) {
                          if (emitResult) {
                            return runOne(testId, name, false, "base=0;min=0;max=0;under=0;over=0;rec_w=0;rec_m=0;ready_miss=1;slip_w=0;slip_m=0;zero=0;rejects=0;sc=0;ec=0");
                          }
                          if (outMetrics) *outMetrics = computed;
                          return false;
                        }

                        PressureRegulator& reg = (channel == 0u) ? PressureRegulator::regP() : PressureRegulator::regR();
                        PressureRegulator* secondaryReg = nullptr;
                        bool secondaryReadyOk = true;
                        const uint32_t originalPrintPulse = printer->getPrintPulse();
                        const uint32_t originalRefuelPulse = printer->getRefuelPulse();
                        const uint16_t baselineTarget = static_cast<uint16_t>(reg.getTarget());
                        uint16_t secondaryBaselineTarget = 0u;
                        reg.start();
                        printer->setDiagnosticReadyTimeout(true, 4500u);
                        if (requireBothReady) {
#if (LC_PRESSURE_PORTS > 1)
                          secondaryReg = (channel == 0u) ? &PressureRegulator::regR() : &PressureRegulator::regP();
                          secondaryBaselineTarget = static_cast<uint16_t>(secondaryReg->getTarget());
                          secondaryReg->start();
                          xEventGroupClearBits(_doneEvents, (channel == 0u) ? BIT_PRESSURE_R_READY : BIT_PRESSURE_P_READY);
                          const uint16_t secTarget = (secondaryTargetRaw == 0u)
                                                       ? ((channel == 0u) ? psiToRaw(500u) : psiToRaw(1000u))
                                                       : secondaryTargetRaw;
                          secondaryReg->setTargetSafe(secTarget);
                          secondaryReadyOk = waitBitsWithTimeout((channel == 0u) ? BIT_PRESSURE_R_READY : BIT_PRESSURE_P_READY, 5000u);
#endif
                        }
                        if (channel == 0u) {
                          printer->setPrintPulse(pulseWidthUs);
                        } else {
                          printer->setRefuelPulse(pulseWidthUs);
                        }
                        if (requireBothReady && (secondaryPulseWidthUs > 0u)) {
                          if (channel == 0u) {
#if (LC_PRESSURE_PORTS > 1)
                            printer->setRefuelPulse(secondaryPulseWidthUs);
#endif
                          } else {
                            printer->setPrintPulse(secondaryPulseWidthUs);
                          }
                        }
                        xEventGroupClearBits(_doneEvents, BIT_PRINTING_DONE | BIT_FLASH_PRINT_DONE | ((channel == 0u) ? BIT_PRESSURE_P_READY : BIT_PRESSURE_R_READY));
                        reg.setTargetSafe(targetRaw);
                        sendProgressStage("trace_wait_ready");
                        const bool readyOk = waitBitsWithTimeout((channel == 0u) ? BIT_PRESSURE_P_READY : BIT_PRESSURE_R_READY, 5000u);
                        bool printDone = false;
                        bool queued = false;
                        if (secondaryReadyOk && readyOk) {
                          sendProgressStage("trace_stabilize");
                          if (!delayWithWatchdog(kPressureStabilizationMs, "trace_stabilize")) {
                            sendProgressStage("trace_abort_pre_enqueue");
                          } else if (_selfTestAbortRequested) {
                            sendProgressStage("trace_abort_pre_enqueue");
                          } else {
                            recorder.arm();
                            recorder.start(HAL_GetTick());
                            if (!delayWithWatchdog(traceCfg.preRollMs, "trace_preroll")) {
                              sendProgressStage("trace_abort_pre_enqueue");
                            } else {
                              sendProgressStage("trace_enqueue");
                              queued = printer->enqueueWithTimeout(
                                  dropletCount,
                                  rateHz,
                                  mode,
                                  pdMS_TO_TICKS(250),
                                  BIT_PRINTING_DONE);
                              if (queued) {
                                sendProgressStage("trace_wait_done");
                                printDone = waitBitsWithTimeout(BIT_PRINTING_DONE, 5000u);
                              } else {
                                sendProgressStage("trace_enqueue_to");
                                printDone = false;
                              }
                              if (printDone) {
                                (void)delayWithWatchdog(traceCfg.postRollMs, "trace_postroll");
                              }
                              recorder.stop(HAL_GetTick());
                            }
                          }
                        }
                        if (queued && !printDone) {
                          // Prevent a timed-out run from leaking into the next sweep combo.
                          sendProgressStage("trace_cancel");
                          printer->cancelDispense();
                          (void)waitPrinterIdleWithTimeout(printer, 500u);
                        }
                        sendProgressStage("trace_restore");
                        reg.setTargetSafe(baselineTarget);
#if (LC_PRESSURE_PORTS > 1)
                        if (secondaryReg != nullptr) {
                          secondaryReg->setTargetSafe(secondaryBaselineTarget);
                        }
#endif
                        vTaskDelay(pdMS_TO_TICKS(50));
                        sendProgressStage("trace_restore_pulses");
                        printer->setPrintPulse(originalPrintPulse);
                        printer->setRefuelPulse(originalRefuelPulse);
                        printer->setDiagnosticReadyTimeout(false, 0u);
                        sendProgressStage("trace_pause_regs");
                        reg.pause();
#if (LC_PRESSURE_PORTS > 1)
                        if (secondaryReg != nullptr) {
                          secondaryReg->pause();
                        }
#endif

                        computed.traceSampleCount = recorder.sampleCount();
                        computed.traceEventCount = recorder.eventCount();
                        sendProgressStage("trace_metrics_start");
                        Watchdog_CheckIn(CRASH_TASK_ORCH);
                        computeTraceMetrics(rateHz == 0u ? 0u : static_cast<uint16_t>(1000u / rateHz),
                                            computed.baselinePressure,
                                            computed.minPressure,
                                            computed.maxPressure,
                                            computed.maxUndershoot,
                                            computed.maxOvershoot,
                                            computed.worstRecoveryMs,
                                            computed.meanRecoveryMs,
                                            computed.readyMissCount,
                                            computed.maxDeadlineSlipMs,
                                            computed.meanDeadlineSlipMs,
                                            computed.zeroCrossCount,
                                            computed.sampleRejectCount);
                        computed.pulseDrop = ValvePulseQualificationMath::summarizePulseDrops(
                            recorder.samples(),
                            recorder.sampleCount(),
                            recorder.events(),
                            recorder.eventCount(),
                            rateHz == 0u ? 0u : static_cast<uint16_t>(1000u / rateHz));
                        computed.pulseResponse = ValvePulseQualificationMath::summarizeWindowedPulseResponses(
                            recorder.samples(),
                            recorder.sampleCount(),
                            recorder.events(),
                            recorder.eventCount(),
                            10u,
                            30u);
                        Watchdog_CheckIn(CRASH_TASK_ORCH);
                        sendProgressStage("trace_metrics_done");
                        computed.pass = secondaryReadyOk &&
                                        readyOk &&
                                        printDone &&
                                        (computed.maxDeadlineSlipMs <= 250u) &&
                                        (computed.readyMissCount == 0u);

                        if (outMetrics) *outMetrics = computed;

                        if (emitResult) {
                          char metrics[224];
                          snprintf(metrics, sizeof(metrics),
                                   "base=%lu;min=%lu;max=%lu;under=%lu;over=%lu;rec_w=%lu;rec_m=%lu;ready_miss=%lu;slip_w=%lu;slip_m=%lu;zero=%lu;rejects=%lu;sc=%lu;ec=%lu",
                                   static_cast<unsigned long>(computed.baselinePressure),
                                   static_cast<unsigned long>(computed.minPressure),
                                   static_cast<unsigned long>(computed.maxPressure),
                                   static_cast<unsigned long>(computed.maxUndershoot),
                                   static_cast<unsigned long>(computed.maxOvershoot),
                                   static_cast<unsigned long>(computed.worstRecoveryMs),
                                   static_cast<unsigned long>(computed.meanRecoveryMs),
                                   static_cast<unsigned long>(computed.readyMissCount),
                                   static_cast<unsigned long>(computed.maxDeadlineSlipMs),
                                   static_cast<unsigned long>(computed.meanDeadlineSlipMs),
                                   static_cast<unsigned long>(computed.zeroCrossCount),
                                   static_cast<unsigned long>(computed.sampleRejectCount),
                                   static_cast<unsigned long>(computed.traceSampleCount),
                                   static_cast<unsigned long>(computed.traceEventCount));
                          sendProgressStage("trace_result_emit");
                          Watchdog_CheckIn(CRASH_TASK_ORCH);
                          const bool reported = runOne(testId, name, computed.pass, metrics);
                          sendProgressStage("trace_result_done");
                          if (!reported) {
                            return false;
                          }
                          if (!maybeExportTrace(shouldExportTrace, testId, name, computed.pass)) {
                            sendProgressStage("trace_export_abort");
                            aborted = true;
                            _selfTestAbortRequested = true;
                            return false;
                          }
                          return true;
                        }

                        return true;
                      };

                      if (runValveCharacterizationSuite || runValveGapSweepSuite) {
                        static constexpr uint16_t kValveCharWidthsUs[3] = {1500u, 3000u, 4500u};
                        static constexpr uint16_t kValveCharReplicates = 10u;
                        static constexpr uint16_t kValveCharWidthCount = 3u;
                        static constexpr uint16_t kValveCharMeasuredPulses =
                            kValveCharReplicates * kValveCharWidthCount;
                        static constexpr uint16_t kValveGapDetailedReplicates = 8u;
                        static constexpr uint16_t kValveGapDetailedGapCount = 5u;
                        static constexpr uint16_t kValveGapControlReplicates = 4u;
                        static constexpr uint16_t kValveGapControlConditionCount = 4u;
                        static constexpr uint32_t kValveCharStabilizeMs = 500u;
                        static constexpr uint32_t kValveCharRegHomeFastHz = 30000u;
                        static constexpr uint32_t kValveCharRegHomeSlowHz = 3000u;
                        static constexpr uint32_t kValveCharRegHomeBackoffSteps = 400u;
                        static constexpr uint32_t kValveCharRegHomeTimeoutMs = 20000u;
                        static constexpr uint16_t kValveCharPsiMilli = 2000u;
                        static constexpr uint32_t kValveCharFocusedSampleMs = 5u;
                        static constexpr uint32_t kValveCharFreshSampleTimeoutMs = 60u;

                        struct ValveCharRowSummary {
                          uint32_t ready = 0u;
                          uint32_t freshTo = 0u;
                          uint32_t sc = 0u;
                          uint32_t ec = 0u;
                          uint32_t timeout = 0u;
                          uint32_t pulses = 0u;
                          bool pass = true;
                        };

                        auto pressureBitForChannel = [&](uint8_t channel) -> EventBits_t {
                          return (channel == 0u) ? BIT_PRESSURE_P_READY : BIT_PRESSURE_R_READY;
                        };

                        auto regulatorForValveChannel = [&](uint8_t channel) -> PressureRegulator& {
                          return (channel == 0u) ? PressureRegulator::regP() : PressureRegulator::regR();
                        };

                        auto closeValveCharPressurePaths = [&]() {
                          PressureRegulator::regP().pause();
                          PressureRegulator::regP().closeValve();
#if (LC_PRESSURE_PORTS > 1)
                          PressureRegulator::regR().pause();
                          PressureRegulator::regR().closeValve();
#endif
                        };

                        auto homeValveCharPressureRegulators = [&]() -> bool {
                          closeValveCharPressurePaths();
                          sendProgressStage("valve_char_reg_home");
                          EventBits_t homeBits = BIT_HOME_P_DONE;
#if (LC_PRESSURE_PORTS > 1)
                          homeBits |= BIT_HOME_R_DONE;
#endif
                          xEventGroupClearBits(_doneEvents, homeBits);
                          startRegHomeAsync(&PressureRegulator::regP(),
                                            kValveCharRegHomeFastHz,
                                            kValveCharRegHomeSlowHz,
                                            kValveCharRegHomeBackoffSteps,
                                            BIT_HOME_P_DONE);
#if (LC_PRESSURE_PORTS > 1)
                          startRegHomeAsync(&PressureRegulator::regR(),
                                            kValveCharRegHomeFastHz,
                                            kValveCharRegHomeSlowHz,
                                            kValveCharRegHomeBackoffSteps,
                                            BIT_HOME_R_DONE);
#endif
                          const bool homesDone = waitBitsWithTimeout(homeBits, kValveCharRegHomeTimeoutMs);
                          const EventBits_t doneBits = xEventGroupGetBits(_doneEvents);
                          bool homeOk = homesDone &&
                              ((doneBits & BIT_HOME_P_DONE) != 0u) &&
                              (Stepper::stepperP() != nullptr) &&
                              Stepper::stepperP()->getLastHomeDiagnosticSnapshot().success;
#if (LC_PRESSURE_PORTS > 1)
                          homeOk = homeOk &&
                              ((doneBits & BIT_HOME_R_DONE) != 0u) &&
                              (Stepper::stepperR() != nullptr) &&
                              Stepper::stepperR()->getLastHomeDiagnosticSnapshot().success;
#endif
                          closeValveCharPressurePaths();
                          return homeOk && !_selfTestAbortRequested;
                        };

                        auto waitFreshValveCharSample = [&](uint8_t channel, uint32_t timeoutMs) -> bool {
                          PressureSensor* sensor = PressureSensor::instance();
                          if (sensor == nullptr) {
                            return false;
                          }
                          const uint32_t priorTick = sensor->getControlSample(channel).tickMs;
                          const uint32_t startTick = HAL_GetTick();
                          while (!_selfTestAbortRequested && ((HAL_GetTick() - startTick) < timeoutMs)) {
                            Watchdog_CheckIn(CRASH_TASK_ORCH);
                            const auto sample = sensor->getControlSample(channel);
                            if (sample.valid && sample.tickMs != priorTick) {
                              return true;
                            }
                            vTaskDelay(msToAtLeast1Tick(1u));
                          }
                          return false;
                        };

                        auto runIsolatedValveSequence = [&](uint16_t testId,
                                                            uint8_t channel,
                                                            uint16_t targetRaw) -> ValveCharRowSummary {
                          ValveCharRowSummary row{};
#if (LC_PRESSURE_PORTS <= 1)
                          if (channel != 0u) {
                            row.ready = 1u;
                            row.pass = false;
                            return row;
                          }
#endif
                          Printer* printer = Printer::instance();
                          PressureSensor* sensor = PressureSensor::instance();
                          if (printer == nullptr || sensor == nullptr) {
                            row.ready = 1u;
                            row.pass = false;
                            return row;
                          }
                          struct ScopedPressureFocus {
                            PressureSensor* sensor = nullptr;
                            bool active = false;
                            ~ScopedPressureFocus() {
                              if (active && sensor != nullptr) {
                                sensor->endDiagnosticFocus();
                              }
                            }
                          } focusScope;
                          focusScope.sensor = sensor;
                          focusScope.active = sensor->beginDiagnosticFocus(channel);
                          if (!focusScope.active) {
                            row.ready = 1u;
                            row.pass = false;
                            return row;
                          }

                          PressureRegulator& reg = regulatorForValveChannel(channel);
                          Stepper* stepper = (channel == 0u) ? Stepper::stepperP() : Stepper::stepperR();
                          const uint32_t originalPrintPulse = printer->getPrintPulse();
                          const uint32_t originalRefuelPulse = printer->getRefuelPulse();

                          auto recordValveCharEvent = [&](PressureTraceChannel traceChannel,
                                                          PressureTraceEventType type,
                                                          uint16_t value0,
                                                          uint16_t value1,
                                                          uint32_t traceStartTick) {
                            const uint32_t dt = HAL_GetTick() - traceStartTick;
                            PressureTraceEvent event{};
                            event.dtMs = static_cast<uint16_t>((dt > 0xFFFFu) ? 0xFFFFu : dt);
                            event.type = static_cast<uint8_t>(type);
                            event.value0 = value0;
                            event.value1 = value1;
                            PressureTraceRecorder::instance().recordEvent(traceChannel, event);
                          };

                          auto runOnePulse = [&](uint16_t pulseWidthUs,
                                                 uint16_t sequenceIndex,
                                                 uint16_t replicateForWidth,
                                                 bool measured) -> bool {
                            if (channel == 0u) {
                              printer->setPrintPulse(pulseWidthUs);
                            } else {
                              printer->setRefuelPulse(pulseWidthUs);
                            }
                            reg.start();
                            xEventGroupClearBits(_doneEvents, pressureBitForChannel(channel));
                            reg.setTargetSafe(targetRaw);
                            const bool readyOk = waitBitsWithTimeout(pressureBitForChannel(channel), 7000u);
                            if (!readyOk) {
                              row.ready++;
                              return true;
                            }
                            if (!delayWithWatchdog(kValveCharStabilizeMs, "valve_char_stabilize")) {
                              row.timeout++;
                              return false;
                            }
                            const int32_t motorPosition = (stepper != nullptr) ? stepper->getPosition() : 0;

                            auto& recorder = PressureTraceRecorder::instance();
                            recorder.reset();
                            PressureTraceConfig traceCfg{};
                            traceCfg.channel = (channel == 0u) ? PressureTraceChannel::Print : PressureTraceChannel::Refuel;
                            traceCfg.maxSamples = PressureTraceRecorder::kMaxSamples;
                            traceCfg.maxEvents = PressureTraceRecorder::kMaxEvents;
                            recorder.configure(traceCfg);

                            reg.beginDispenseQuiet(0u);
                            recorder.arm();
                            const uint32_t traceStartTick = HAL_GetTick();
                            recorder.start(traceStartTick);
                            if (measured) {
                              recordValveCharEvent(traceCfg.channel,
                                                   PressureTraceEventType::ValveSequence,
                                                   sequenceIndex,
                                                   pulseWidthUs,
                                                   traceStartTick);
                              const uint32_t encodedMotorPosition = static_cast<uint32_t>(motorPosition);
                              recordValveCharEvent(traceCfg.channel,
                                                   PressureTraceEventType::MotorPosition,
                                                   static_cast<uint16_t>(encodedMotorPosition & 0xFFFFu),
                                                   static_cast<uint16_t>((encodedMotorPosition >> 16) & 0xFFFFu),
                                                   traceStartTick);
                            }
                            bool timeout = !delayWithWatchdog(traceCfg.preRollMs, "valve_char_pause_preroll");
                            bool freshOk = false;
                            if (!timeout && !_selfTestAbortRequested) {
                              freshOk = waitFreshValveCharSample(channel, kValveCharFreshSampleTimeoutMs);
                              if (!freshOk) {
                                row.freshTo++;
                              }
                            }
                            if (!timeout && freshOk && !_selfTestAbortRequested) {
                              PressureRegulator::DisturbanceEvent ev{};
                              ev.type = (channel == 0u) ? PressureRegulator::PulseType::Print : PressureRegulator::PulseType::Refuel;
                              ev.pulseWidthUs = pulseWidthUs;
                              ev.pressureAtTrigger = sensor->getLatestRaw(channel);
                              ev.tickMs = HAL_GetTick();
                              reg.notifyPulseStart(ev);
                              if (channel == 0u) {
                                printer->pulsePrint();
                              } else {
                                printer->pulseRefuel();
                              }
                              const uint32_t pulseHoldMs = (static_cast<uint32_t>(pulseWidthUs) + 999u) / 1000u + 2u;
                              timeout = !delayWithWatchdog(pulseHoldMs, "valve_char_pause_pulse");
                              ev.tickMs = HAL_GetTick();
                              ev.pressureAtTrigger = sensor->getLatestRaw(channel);
                              reg.notifyPulseEnd(ev);
                            }
                            if (!timeout && !_selfTestAbortRequested) {
                              timeout = !delayWithWatchdog(traceCfg.postRollMs, "valve_char_pause_postroll");
                            }
                            recorder.stop(HAL_GetTick());
                            reg.endDispenseQuiet(2u);
                            (void)delayWithWatchdog(10u, "valve_char_pause_release");

                            if (!measured) {
                              if (timeout) {
                                row.timeout++;
                              }
                              return !timeout;
                            }

                            char traceName[48];
                            snprintf(traceName,
                                     sizeof(traceName),
                                     "valve_char_%c_w%u_rep%02u",
                                     (channel == 0u) ? 'p' : 'r',
                                     static_cast<unsigned>(pulseWidthUs),
                                     static_cast<unsigned>(replicateForWidth));
                            const bool traceOk = !timeout && freshOk && (recorder.sampleCount() > 0u) && (recorder.eventCount() > 0u);
                            (void)exportTrace(testId, traceName, traceOk);
                            row.sc += recorder.sampleCount();
                            row.ec += recorder.eventCount();
                            row.pulses++;
                            if (timeout) {
                              row.timeout++;
                            }
                            return !timeout;
                          };

                          bool valveSequenceOk = true;
                          for (uint16_t widthIndex = 0u; widthIndex < kValveCharWidthCount && valveSequenceOk && !_selfTestAbortRequested; ++widthIndex) {
                            const uint16_t widthUs = kValveCharWidthsUs[widthIndex];
                            if (!runOnePulse(widthUs, 0u, 0u, false)) {
                              valveSequenceOk = false;
                            }
                            for (uint16_t rep = 1u; rep <= kValveCharReplicates && valveSequenceOk && !_selfTestAbortRequested; ++rep) {
                              const uint16_t seq = static_cast<uint16_t>((widthIndex * kValveCharReplicates) + rep);
                              if (!runOnePulse(widthUs, seq, rep, true)) {
                                valveSequenceOk = false;
                              }
                            }
                          }

                          row.pass = row.pass &&
                                     !_selfTestAbortRequested &&
                                     (row.ready == 0u) &&
                                     (row.freshTo == 0u) &&
                                     (row.timeout == 0u) &&
                                     (row.pulses == kValveCharMeasuredPulses) &&
                                     (row.sc > 0u) &&
                                     (row.ec > 0u);
                          reg.pause();
                          printer->setPrintPulse(originalPrintPulse);
                          printer->setRefuelPulse(originalRefuelPulse);
                          return row;
                        };

                        auto emitValveChannelRow = [&](uint16_t testId,
                                                       const char* name,
                                                       char ch,
                                                       const ValveCharRowSummary& row) -> bool {
                          char metrics[192];
                          snprintf(metrics, sizeof(metrics),
                                   "ch=%c;psi=2000;rep=10;pulses=%lu;cond=3;home_to=0;timeout=%lu;ready=%lu;fresh_to=%lu;focus=1;sm=%lu;sc=%lu;ec=%lu",
                                   ch,
                                   static_cast<unsigned long>(row.pulses),
                                   static_cast<unsigned long>(row.timeout),
                                   static_cast<unsigned long>(row.ready),
                                   static_cast<unsigned long>(row.freshTo),
                                   static_cast<unsigned long>(kValveCharFocusedSampleMs),
                                   static_cast<unsigned long>(row.sc),
                                   static_cast<unsigned long>(row.ec));
                          return runOne(testId, name, row.pass, metrics);
                        };

                        auto emitValveHomeFailureChannelRow = [&](uint16_t testId,
                                                                  const char* name,
                                                                  char ch) -> bool {
                          char metrics[160];
                          snprintf(metrics, sizeof(metrics),
                                   "ch=%c;psi=2000;rep=10;pulses=0;cond=3;home_to=1;timeout=0;ready=0;fresh_to=0;focus=0;sm=%lu;sc=0;ec=0;gate=home_reference",
                                   ch,
                                   static_cast<unsigned long>(kValveCharFocusedSampleMs));
                          return runOne(testId, name, false, metrics);
                        };

                        auto runValveChannelRow = [&](uint16_t testId,
                                                      const char* name,
                                                      uint8_t channel,
                                                      uint16_t targetRaw,
                                                      ValveCharRowSummary* outRow) -> bool {
                          ValveCharRowSummary row = runIsolatedValveSequence(testId, channel, targetRaw);
                          if (outRow != nullptr) {
                            *outRow = row;
                          }
                          return emitValveChannelRow(testId,
                                                     name,
                                                     (channel == 0u) ? 'p' : 'r',
                                                     row);
                        };

                        auto emitValveBalanceRow = [&](const ValveCharRowSummary& printRow,
                                                       const ValveCharRowSummary& refuelRow) -> bool {
                          static constexpr uint16_t kTestId = 2475u;
                          static constexpr const char* kName = "valve_char_channel_balance_2psi";
#if (LC_PRESSURE_PORTS <= 1)
                          return runOne(kTestId,
                                        kName,
                                        false,
                                        "psi=2000;rep=10;pulses=0;home_to=0;timeout=0;ready=1;fresh_to=0;sc=0;ec=0;gate=no_refuel_port");
#else
                          char metrics[192];
                          snprintf(metrics, sizeof(metrics),
                                   "psi=2000;rep=10;pulses=%lu;home_to=0;timeout=%lu;ready=%lu;fresh_to=%lu;sc=%lu;ec=%lu",
                                   static_cast<unsigned long>(printRow.pulses + refuelRow.pulses),
                                   static_cast<unsigned long>(printRow.timeout + refuelRow.timeout),
                                   static_cast<unsigned long>(printRow.ready + refuelRow.ready),
                                   static_cast<unsigned long>(printRow.freshTo + refuelRow.freshTo),
                                   static_cast<unsigned long>(printRow.sc + refuelRow.sc),
                                   static_cast<unsigned long>(printRow.ec + refuelRow.ec));
                          return runOne(kTestId, kName, printRow.pass && refuelRow.pass, metrics);
#endif
                        };

                        auto emitValveHomeFailureRows = [&]() -> bool {
                          if (!emitValveHomeFailureChannelRow(2473u, "valve_char_print_2psi_repeat_linearity", 'p')) return false;
                          if (!emitValveHomeFailureChannelRow(2474u, "valve_char_refuel_2psi_repeat_linearity", 'r')) return false;
                          return runOne(2475u,
                                        "valve_char_channel_balance_2psi",
                                        false,
                                        "psi=2000;rep=10;pulses=0;home_to=1;timeout=0;ready=0;fresh_to=0;sc=0;ec=0;gate=home_reference");
                        };

                        struct ValveGapRowSummary {
                          uint32_t ready = 0u;
                          uint32_t freshTo = 0u;
                          uint32_t sc = 0u;
                          uint32_t ec = 0u;
                          uint32_t timeout = 0u;
                          uint32_t pulses = 0u;
                          bool pass = true;
                        };

                        auto runValveGapSequence = [&](uint8_t channel,
                                                       uint16_t targetRaw,
                                                       bool controlMode) -> ValveGapRowSummary {
                          ValveGapRowSummary row{};
                          const uint16_t conditionCount = controlMode ? kValveGapControlConditionCount : kValveGapDetailedGapCount;
                          const uint16_t replicateCount = controlMode ? kValveGapControlReplicates : kValveGapDetailedReplicates;
                          const uint16_t expectedPulseCount = conditionCount * replicateCount;
#if (LC_PRESSURE_PORTS <= 1)
                          if (channel != 0u) {
                            row.ready = 1u;
                            row.pass = false;
                            return row;
                          }
#endif
                          Printer* printer = Printer::instance();
                          PressureSensor* sensor = PressureSensor::instance();
                          if (printer == nullptr || sensor == nullptr) {
                            row.ready = 1u;
                            row.pass = false;
                            return row;
                          }
                          struct ScopedPressureFocus {
                            PressureSensor* sensor = nullptr;
                            bool active = false;
                            ~ScopedPressureFocus() {
                              if (active && sensor != nullptr) {
                                sensor->endDiagnosticFocus();
                              }
                            }
                          } focusScope;
                          focusScope.sensor = sensor;
                          focusScope.active = sensor->beginDiagnosticFocus(channel);
                          if (!focusScope.active) {
                            row.ready = 1u;
                            row.pass = false;
                            return row;
                          }

                          PressureRegulator& reg = regulatorForValveChannel(channel);
                          Stepper* stepper = (channel == 0u) ? Stepper::stepperP() : Stepper::stepperR();
                          const uint32_t originalPrintPulse = printer->getPrintPulse();
                          const uint32_t originalRefuelPulse = printer->getRefuelPulse();

                          uint16_t previousWidthUs = 0u;
                          uint32_t previousPulseStartTick = 0u;

                          auto recordGapEvent = [&](PressureTraceChannel traceChannel,
                                                    PressureTraceEventType type,
                                                    uint16_t value0,
                                                    uint16_t value1,
                                                    uint32_t traceStartTick) {
                            const uint32_t dt = HAL_GetTick() - traceStartTick;
                            PressureTraceEvent event{};
                            event.dtMs = static_cast<uint16_t>((dt > 0xFFFFu) ? 0xFFFFu : dt);
                            event.type = static_cast<uint8_t>(type);
                            event.value0 = value0;
                            event.value1 = value1;
                            PressureTraceRecorder::instance().recordEvent(traceChannel, event);
                          };

                          auto runOneGapPulse = [&](uint16_t pulseWidthUs,
                                                    uint32_t gapMs,
                                                    uint16_t conditionIndex,
                                                    uint16_t replicate) -> bool {
                            (void)conditionIndex;
                            if (channel == 0u) {
                              printer->setPrintPulse(pulseWidthUs);
                            } else {
                              printer->setRefuelPulse(pulseWidthUs);
                            }
                            reg.start();
                            xEventGroupClearBits(_doneEvents, pressureBitForChannel(channel));
                            reg.setTargetSafe(targetRaw);
                            const bool readyOk = waitBitsWithTimeout(pressureBitForChannel(channel), 7000u);
                            if (!readyOk) {
                              row.ready++;
                              return true;
                            }
                            if (!delayWithWatchdog(gapMs, "valve_gap_settle")) {
                              row.timeout++;
                              return false;
                            }
                            const int32_t motorPosition = (stepper != nullptr) ? stepper->getPosition() : 0;

                            auto& recorder = PressureTraceRecorder::instance();
                            recorder.reset();
                            PressureTraceConfig traceCfg{};
                            traceCfg.channel = (channel == 0u) ? PressureTraceChannel::Print : PressureTraceChannel::Refuel;
                            traceCfg.maxSamples = PressureTraceRecorder::kMaxSamples;
                            traceCfg.maxEvents = PressureTraceRecorder::kMaxEvents;
                            recorder.configure(traceCfg);

                            reg.beginDispenseQuiet(0u);
                            recorder.arm();
                            const uint32_t traceStartTick = HAL_GetTick();
                            recorder.start(traceStartTick);
                            recordGapEvent(traceCfg.channel,
                                           PressureTraceEventType::ValveGap,
                                           static_cast<uint16_t>((gapMs > 0xFFFFu) ? 0xFFFFu : gapMs),
                                           0u,
                                           traceStartTick);
                            recordGapEvent(traceCfg.channel,
                                           PressureTraceEventType::ValvePreviousWidth,
                                           previousWidthUs,
                                           pulseWidthUs,
                                           traceStartTick);
                            const uint32_t encodedMotorPosition = static_cast<uint32_t>(motorPosition);
                            recordGapEvent(traceCfg.channel,
                                           PressureTraceEventType::MotorPosition,
                                           static_cast<uint16_t>(encodedMotorPosition & 0xFFFFu),
                                           static_cast<uint16_t>((encodedMotorPosition >> 16) & 0xFFFFu),
                                           traceStartTick);

                            bool timeout = !delayWithWatchdog(traceCfg.preRollMs, "valve_gap_pause_preroll");
                            bool freshOk = false;
                            if (!timeout && !_selfTestAbortRequested) {
                              freshOk = waitFreshValveCharSample(channel, kValveCharFreshSampleTimeoutMs);
                              if (!freshOk) {
                                row.freshTo++;
                              }
                            }
                            uint32_t pulseStartTick = 0u;
                            if (!timeout && freshOk && !_selfTestAbortRequested) {
                              PressureRegulator::DisturbanceEvent ev{};
                              ev.type = (channel == 0u) ? PressureRegulator::PulseType::Print : PressureRegulator::PulseType::Refuel;
                              ev.pulseWidthUs = pulseWidthUs;
                              ev.pressureAtTrigger = sensor->getLatestRaw(channel);
                              pulseStartTick = HAL_GetTick();
                              const uint32_t intervalMs = (previousPulseStartTick == 0u) ? 0u : (pulseStartTick - previousPulseStartTick);
                              recordGapEvent(traceCfg.channel,
                                             PressureTraceEventType::ValveInterval,
                                             static_cast<uint16_t>((intervalMs > 0xFFFFu) ? 0xFFFFu : intervalMs),
                                             0u,
                                             traceStartTick);
                              ev.tickMs = pulseStartTick;
                              reg.notifyPulseStart(ev);
                              if (channel == 0u) {
                                printer->pulsePrint();
                              } else {
                                printer->pulseRefuel();
                              }
                              const uint32_t pulseHoldMs = (static_cast<uint32_t>(pulseWidthUs) + 999u) / 1000u + 2u;
                              timeout = !delayWithWatchdog(pulseHoldMs, "valve_gap_pause_pulse");
                              ev.tickMs = HAL_GetTick();
                              ev.pressureAtTrigger = sensor->getLatestRaw(channel);
                              reg.notifyPulseEnd(ev);
                            }
                            if (!timeout && !_selfTestAbortRequested) {
                              timeout = !delayWithWatchdog(traceCfg.postRollMs, "valve_gap_pause_postroll");
                            }
                            recorder.stop(HAL_GetTick());
                            reg.endDispenseQuiet(2u);
                            (void)delayWithWatchdog(10u, "valve_gap_pause_release");

                            char traceName[48];
                            snprintf(traceName,
                                     sizeof(traceName),
                                     "valve_gap_%c_w%u_g%04lu_rep%02u",
                                     (channel == 0u) ? 'p' : 'r',
                                     static_cast<unsigned>(pulseWidthUs),
                                     static_cast<unsigned long>(gapMs),
                                     static_cast<unsigned>(replicate));
                            const uint16_t testId = (channel == 0u)
                                ? (controlMode ? 2478u : 2476u)
                                : (controlMode ? 2479u : 2477u);
                            const bool traceOk = !timeout && freshOk && (recorder.sampleCount() > 0u) && (recorder.eventCount() > 0u);
                            (void)exportTrace(testId, traceName, traceOk);
                            row.sc += recorder.sampleCount();
                            row.ec += recorder.eventCount();
                            row.pulses++;
                            if (timeout) {
                              row.timeout++;
                            }
                            if (pulseStartTick != 0u) {
                              previousPulseStartTick = pulseStartTick;
                              previousWidthUs = pulseWidthUs;
                            }
                            return !timeout;
                          };

                          bool valveSequenceOk = true;
                          for (uint16_t condition = 0u; condition < conditionCount && valveSequenceOk && !_selfTestAbortRequested; ++condition) {
                            const uint16_t widthUs = controlMode
                                ? ValvePulseQualificationMath::valveGapSweepControlWidthUs(condition)
                                : 1500u;
                            const uint32_t gapMs = controlMode
                                ? ValvePulseQualificationMath::valveGapSweepControlGapMs(condition)
                                : ValvePulseQualificationMath::valveGapSweepDetailedGapMs(condition);
                            for (uint16_t rep = 1u; rep <= replicateCount && valveSequenceOk && !_selfTestAbortRequested; ++rep) {
                              if (!runOneGapPulse(widthUs, gapMs, condition, rep)) {
                                valveSequenceOk = false;
                              }
                            }
                          }

                          row.pass = row.pass &&
                                     !_selfTestAbortRequested &&
                                     (row.ready == 0u) &&
                                     (row.freshTo == 0u) &&
                                     (row.timeout == 0u) &&
                                     (row.pulses == expectedPulseCount) &&
                                     (row.sc > 0u) &&
                                     (row.ec > 0u);
                          reg.pause();
                          printer->setPrintPulse(originalPrintPulse);
                          printer->setRefuelPulse(originalRefuelPulse);
                          return row;
                        };

                        auto emitValveGapDetailedRow = [&](uint16_t testId,
                                                           const char* name,
                                                          char ch,
                                                          const ValveGapRowSummary& row) -> bool {
                          char metrics[192];
                          snprintf(metrics, sizeof(metrics),
                                   "ch=%c;pw=1500;rep=8;pulses=%lu;gaps=5;home_to=0;timeout=%lu;ready=%lu;fresh_to=%lu;focus=1;sc=%lu;ec=%lu",
                                   ch,
                                   static_cast<unsigned long>(row.pulses),
                                   static_cast<unsigned long>(row.timeout),
                                   static_cast<unsigned long>(row.ready),
                                   static_cast<unsigned long>(row.freshTo),
                                   static_cast<unsigned long>(row.sc),
                                   static_cast<unsigned long>(row.ec));
                          return runOne(testId, name, row.pass, metrics);
                        };

                        auto emitValveGapControlRow = [&](uint16_t testId,
                                                          const char* name,
                                                          char ch,
                                                          const ValveGapRowSummary& row) -> bool {
                          char metrics[192];
                          snprintf(metrics, sizeof(metrics),
                                   "ch=%c;rep=4;pulses=%lu;cond=4;home_to=0;timeout=%lu;ready=%lu;fresh_to=%lu;focus=1;sc=%lu;ec=%lu",
                                   ch,
                                   static_cast<unsigned long>(row.pulses),
                                   static_cast<unsigned long>(row.timeout),
                                   static_cast<unsigned long>(row.ready),
                                   static_cast<unsigned long>(row.freshTo),
                                   static_cast<unsigned long>(row.sc),
                                   static_cast<unsigned long>(row.ec));
                          return runOne(testId, name, row.pass, metrics);
                        };

                        auto emitValveGapHomeFailureRows = [&]() -> bool {
                          if (!runOne(2476u, "valve_gap_print_1500us_2psi", false, "ch=p;pw=1500;rep=8;pulses=0;gaps=5;home_to=1;timeout=0;ready=0;fresh_to=0;focus=0;sc=0;ec=0;gate=home_reference")) return false;
                          if (!runOne(2477u, "valve_gap_refuel_1500us_2psi", false, "ch=r;pw=1500;rep=8;pulses=0;gaps=5;home_to=1;timeout=0;ready=0;fresh_to=0;focus=0;sc=0;ec=0;gate=home_reference")) return false;
                          if (!runOne(2478u, "valve_gap_print_control_2psi", false, "ch=p;rep=4;pulses=0;cond=4;home_to=1;timeout=0;ready=0;fresh_to=0;focus=0;sc=0;ec=0;gate=home_reference")) return false;
                          return runOne(2479u, "valve_gap_refuel_control_2psi", false, "ch=r;rep=4;pulses=0;cond=4;home_to=1;timeout=0;ready=0;fresh_to=0;focus=0;sc=0;ec=0;gate=home_reference");
                        };

                        const uint16_t raw2 = psiToRaw(kValveCharPsiMilli);

                        selectedPressureHomePass = homeValveCharPressureRegulators();
                        if (!selectedPressureHomePass) {
                          closeValveCharPressurePaths();
                          if (_selfTestAbortRequested) {
                            aborted = true;
                            return finishSelfTestNow();
                          }
                          if (runValveGapSweepSuite) {
                            (void)emitValveGapHomeFailureRows();
                          } else {
                            (void)emitValveHomeFailureRows();
                          }
                          return finishSelfTestNow();
                        }

                        if (runValveGapSweepSuite) {
                          ValveGapRowSummary printDetailed{};
                          ValveGapRowSummary refuelDetailed{};
                          ValveGapRowSummary printControl{};
                          ValveGapRowSummary refuelControl{};
                          printDetailed = runValveGapSequence(0u, raw2, false);
                          if (!emitValveGapDetailedRow(2476u, "valve_gap_print_1500us_2psi", 'p', printDetailed)) return finishSelfTestNow();
                          refuelDetailed = runValveGapSequence(1u, raw2, false);
                          if (!emitValveGapDetailedRow(2477u, "valve_gap_refuel_1500us_2psi", 'r', refuelDetailed)) return finishSelfTestNow();
                          printControl = runValveGapSequence(0u, raw2, true);
                          if (!emitValveGapControlRow(2478u, "valve_gap_print_control_2psi", 'p', printControl)) return finishSelfTestNow();
                          refuelControl = runValveGapSequence(1u, raw2, true);
                          if (!emitValveGapControlRow(2479u, "valve_gap_refuel_control_2psi", 'r', refuelControl)) return finishSelfTestNow();
                          closeValveCharPressurePaths();
                          return finishSelfTestNow();
                        }

                        ValveCharRowSummary printRow{};
                        ValveCharRowSummary refuelRow{};
                        if (!runValveChannelRow(2473u, "valve_char_print_2psi_repeat_linearity", 0u, raw2, &printRow)) return finishSelfTestNow();
                        if (!runValveChannelRow(2474u, "valve_char_refuel_2psi_repeat_linearity", 1u, raw2, &refuelRow)) return finishSelfTestNow();
                        if (!emitValveBalanceRow(printRow, refuelRow)) return finishSelfTestNow();
                        closeValveCharPressurePaths();
                        return finishSelfTestNow();
                      }

				  {
				    static const uint8_t known[] = {'1','2','3','4','5','6','7','8','9'};
				    const uint16_t crc = CommCodec::crc16(known, sizeof(known));
				    char metrics[48];
				    snprintf(metrics, sizeof(metrics), "crc=%u", static_cast<unsigned>(crc));
				    if (!runOne(1001, "comm_crc_known_vector", (crc == 0x4B37u), metrics)) goto selftest_done;
				  }

				  {
				    uint8_t ackPayload[8] = {0};
				    const uint8_t ackLen = CommCodec::buildAckPayload(0xF4, 0x22, runId, true, ackPayload, sizeof(ackPayload));
				    uint8_t frame[16] = {0};
				    const size_t frameLen = CommCodec::encodeFrame(ackPayload, ackLen, frame, sizeof(frame));
				    CommCodec::RxParser parser{};
				    uint8_t parsedLen = 0;
				    int readyCount = 0;
				    for (size_t i = 0; i < frameLen; ++i) {
				      if (CommCodec::feedRxByte(parser, frame[i], parsedLen) == CommCodec::FeedResult::FrameReady) {
				        readyCount++;
				      }
				    }
				    const auto decoded = CommCodec::decodeCommand(parser.rxBuf, parsedLen);
				    const bool pass = (ackLen == 8u) && (frameLen == 12u) && (readyCount == 1) &&
				                      (decoded.cmd == 0xF4u) && (decoded.seq8 == 0x22u) && decoded.hasSeq32;
				    char metrics[48];
				    snprintf(metrics, sizeof(metrics), "frame_len=%u", static_cast<unsigned>(frameLen));
				    if (!runOne(1002, "comm_frame_roundtrip", pass, metrics)) goto selftest_done;
				  }

				  if (!runAckRoundtrip(1010, "session_hello_ack", CMD_HELLO_ACK, true, false)) goto selftest_done;
				  if (!runAckRoundtrip(1011, "session_goodbye_ack", CMD_BYE_ACK, true, false)) goto selftest_done;
				  if (!runAckRoundtrip(1012, "session_goodbye_done", CMD_BYE_DONE, true, true)) goto selftest_done;

				  sampleStatusWindow(260u,
				                    statusChunk0Seen,
				                    statusChunk1Seen,
				                    statusAlternationErrors,
				                    statusPeriodMsAvg,
				                    statusPeriodMsMaxJitter);

				  {
				    static constexpr unsigned kStatusTagCount = 18u;
				    const bool pass = (statusChunk0Seen > 0u) && (statusChunk1Seen > 0u);
				    char metrics[96];
				    snprintf(metrics, sizeof(metrics), "tag_count=%u;has_seq32=0;chunk0_seen=%lu;chunk1_seen=%lu",
				             kStatusTagCount,
				             static_cast<unsigned long>(statusChunk0Seen),
				             static_cast<unsigned long>(statusChunk1Seen));
				    if (!runOne(1003, "status_frame_shape", pass, metrics)) goto selftest_done;
				  }

				  {
				    xQueueReset(_cmdQueue);
				    const UBaseType_t queueDepthAfterClear = uxQueueMessagesWaiting(_cmdQueue);
				    char extra[48];
				    snprintf(extra, sizeof(extra), "queue_depth_after_clear=%u", static_cast<unsigned>(queueDepthAfterClear));
				    if (!runAckRoundtrip(1013, "clear_queue_ack", CMD_CLEAR_ACK, true, false, extra, (queueDepthAfterClear == 0u))) goto selftest_done;
				  }

				  {
				    const bool pass = (statusChunk0Seen >= 2u) && (statusChunk1Seen >= 2u) && (statusAlternationErrors == 0u);
				    char metrics[96];
				    snprintf(metrics, sizeof(metrics), "chunk0_seen=%lu;chunk1_seen=%lu;alternation_errors=%lu",
				             static_cast<unsigned long>(statusChunk0Seen),
				             static_cast<unsigned long>(statusChunk1Seen),
				             static_cast<unsigned long>(statusAlternationErrors));
				    if (!runOne(1020, "status_chunk_alternation_safe", pass, metrics)) goto selftest_done;
				  }

				  {
				    const bool pass = (statusPeriodMsAvg >= 35u) && (statusPeriodMsAvg <= 90u) && (statusPeriodMsMaxJitter <= 40u);
				    char metrics[96];
				    snprintf(metrics, sizeof(metrics), "period_ms_avg=%lu;period_ms_max_jitter=%lu",
				             static_cast<unsigned long>(statusPeriodMsAvg),
				             static_cast<unsigned long>(statusPeriodMsMaxJitter));
				    if (!runOne(1021, "status_cadence_safe", pass, metrics)) goto selftest_done;
				  }

					  {
					    const uint32_t t0 = HAL_GetTick();
					    vTaskDelay(pdMS_TO_TICKS(10));
					    const uint32_t dt = HAL_GetTick() - t0;
					    char metrics[48];
					    snprintf(metrics, sizeof(metrics), "delta_ms=%lu", static_cast<unsigned long>(dt));
					    if (!runOne(1004, "uptime_counter_read", dt >= 1u, metrics)) goto selftest_done;
					  }
	
					  {
					    const uint32_t flashDelay = Orchestrator::getFlashDelay();
                        const uint32_t extCount = Orchestrator::getExtCount();
                        const uint32_t flashAckCount = Orchestrator::getFlashAckCount();
                        const uint32_t flashTaskWakeCount = Orchestrator::getFlashTaskWakeCount();
                        const uint32_t flashTaskDoneCount = Orchestrator::getFlashTaskDoneCount();
					    const uint32_t flashInitCmdCount = Orchestrator::getFlashInitCmdCount();
					    const uint32_t flashInitOkCount = Orchestrator::getFlashInitOkCount();
					    const uint32_t flashInitTaskCreateFailCount = Orchestrator::getFlashInitTaskCreateFailCount();
					    const uint32_t flashInitTimerCreateFailCount = Orchestrator::getFlashInitTimerCreateFailCount();
					    const uint32_t flashTriggerAcceptedCount = Orchestrator::getFlashTriggerAcceptedCount();
					    const uint32_t flashTriggerIgnoredDisarmedCount = Orchestrator::getFlashTriggerIgnoredDisarmedCount();
					    const uint32_t flashTriggerIgnoredFaultCount = Orchestrator::getFlashTriggerIgnoredFaultCount();
					    const uint32_t flashTriggerIgnoredBusyCount = Orchestrator::getFlashTriggerIgnoredBusyCount();
					    const uint32_t flashTriggerIgnoredLineLowCount = Orchestrator::getFlashTriggerIgnoredLineLowCount();
					    const uint32_t flashTriggerReleaseTimeoutCount = Orchestrator::getFlashTriggerReleaseTimeoutCount();
					    const uint32_t flashAckTimeoutCount = Orchestrator::getFlashAckTimeoutCount();
					    const uint32_t flashPrintCompletionTimeoutCount = Orchestrator::getFlashPrintCompletionTimeoutCount();
					    const uint32_t flashSessionArmed = Orchestrator::isFlashSessionArmed() ? 1u : 0u;
					    const uint32_t flashFaultLatched = Orchestrator::isFlashFaultLatched() ? 1u : 0u;
					    const char* flashFaultReason = Orchestrator::getFlashFaultReason();
                        const uint32_t flashOutputArmed = static_cast<uint32_t>(MX_FLASH_IsOutputArmed());
                        const char* flashOutputMode = MX_FLASH_OutputModeToken();
                        uint32_t flashWidthNs = 0;
                        uint32_t flashWidthMinNs = 0;
                        uint32_t flashWidthMaxNs = 0;
	#if LC_HAS_IMAGING == 1
					    if (auto* flash = Flash::instance()) {
					      flashWidthNs = flash->getPulseDuration();
					    }
                        flashWidthMinNs = static_cast<uint32_t>(Flash::kMinPulseNs);
                        flashWidthMaxNs = static_cast<uint32_t>(Flash::kMaxPulseNs);
	#endif
					    char metrics[768];
					    snprintf(metrics, sizeof(metrics),
                                "flash_delay_us=%lu;flash_width_ns=%lu;flash_width_min_ns=%lu;flash_width_max_ns=%lu;"
                                 "ft_acc=%lu;ft_ign_dis=%lu;ft_ign_fault=%lu;ft_ign_busy=%lu;ft_ign_low=%lu;ft_rel_to=%lu;ft_ack_to=%lu;ft_print_to=%lu;"
                                 "ext_count=%lu;flash_ack_count=%lu;flash_task_wake_count=%lu;flash_task_done_count=%lu;"
                                 "flash_init_cmd_count=%lu;flash_init_ok_count=%lu;flash_init_task_create_fail_count=%lu;flash_init_timer_create_fail_count=%lu;"
                                 "flash_session_armed=%lu;flash_fault_latched=%lu;flash_fault_reason=%s;flash_output_armed=%lu;flash_output_mode=%s",
					             static_cast<unsigned long>(flashDelay),
					             static_cast<unsigned long>(flashWidthNs),
                                 static_cast<unsigned long>(flashWidthMinNs),
                                 static_cast<unsigned long>(flashWidthMaxNs),
                                 static_cast<unsigned long>(flashTriggerAcceptedCount),
                                 static_cast<unsigned long>(flashTriggerIgnoredDisarmedCount),
                                 static_cast<unsigned long>(flashTriggerIgnoredFaultCount),
                                 static_cast<unsigned long>(flashTriggerIgnoredBusyCount),
                                 static_cast<unsigned long>(flashTriggerIgnoredLineLowCount),
                                 static_cast<unsigned long>(flashTriggerReleaseTimeoutCount),
                                 static_cast<unsigned long>(flashAckTimeoutCount),
                                 static_cast<unsigned long>(flashPrintCompletionTimeoutCount),
                                 static_cast<unsigned long>(extCount),
                                 static_cast<unsigned long>(flashAckCount),
                                 static_cast<unsigned long>(flashTaskWakeCount),
                                 static_cast<unsigned long>(flashTaskDoneCount),
                                 static_cast<unsigned long>(flashInitCmdCount),
                                 static_cast<unsigned long>(flashInitOkCount),
                                 static_cast<unsigned long>(flashInitTaskCreateFailCount),
                                 static_cast<unsigned long>(flashInitTimerCreateFailCount),
                                 static_cast<unsigned long>(flashSessionArmed),
                                 static_cast<unsigned long>(flashFaultLatched),
                                 flashFaultReason,
                                 static_cast<unsigned long>(flashOutputArmed),
                                 flashOutputMode);
					    if (!runOne(1005, "flash_config_readonly", true, metrics)) goto selftest_done;
					  }

                      {
                        const uint16_t priorDrops = _imagingDroplets;
                        setImagingDroplets(0);
                        const uint32_t extPre = Orchestrator::getExtCount();
                        const uint32_t ackPre = Orchestrator::getFlashAckCount();
                        const uint32_t wakePre = Orchestrator::getFlashTaskWakeCount();
                        const uint32_t donePre = Orchestrator::getFlashTaskDoneCount();
                        const uint32_t acceptedPre = Orchestrator::getFlashTriggerAcceptedCount();
                        const uint32_t ignoredDisarmedPre = Orchestrator::getFlashTriggerIgnoredDisarmedCount();
                        const uint32_t ignoredFaultPre = Orchestrator::getFlashTriggerIgnoredFaultCount();
                        const uint32_t ignoredBusyPre = Orchestrator::getFlashTriggerIgnoredBusyCount();
                        const uint32_t ignoredLineLowPre = Orchestrator::getFlashTriggerIgnoredLineLowCount();
                        const uint32_t releaseTimeoutPre = Orchestrator::getFlashTriggerReleaseTimeoutCount();
                        const uint32_t ackTimeoutPre = Orchestrator::getFlashAckTimeoutCount();
                        const uint32_t printTimeoutPre = Orchestrator::getFlashPrintCompletionTimeoutCount();
                        static constexpr uint32_t kBurstCycles = 5u;
                        uint32_t started = 0u;
                        uint32_t timedOut = 0u;
                        for (uint32_t i = 0; i < kBurstCycles; ++i) {
                            if (_flashTaskHandle == nullptr) {
                                break;
                            }
                            xEventGroupClearBits(_doneEvents, BIT_FLASH_DONE);
                            const BaseType_t noteRc = xTaskNotify(_flashTaskHandle, 0x1u, eSetBits);
                            if (noteRc != pdPASS) {
                                continue;
                            }
                            started++;
                            if (!waitBitsWithTimeout(BIT_FLASH_DONE, 250u)) {
                                timedOut++;
                            }
                            vTaskDelay(msToAtLeast1Tick(3u));
                        }
                        const uint32_t extPost = Orchestrator::getExtCount();
                        const uint32_t ackPost = Orchestrator::getFlashAckCount();
                        const uint32_t wakePost = Orchestrator::getFlashTaskWakeCount();
                        const uint32_t donePost = Orchestrator::getFlashTaskDoneCount();
                        const uint32_t acceptedPost = Orchestrator::getFlashTriggerAcceptedCount();
                        const uint32_t ignoredDisarmedPost = Orchestrator::getFlashTriggerIgnoredDisarmedCount();
                        const uint32_t ignoredFaultPost = Orchestrator::getFlashTriggerIgnoredFaultCount();
                        const uint32_t ignoredBusyPost = Orchestrator::getFlashTriggerIgnoredBusyCount();
                        const uint32_t ignoredLineLowPost = Orchestrator::getFlashTriggerIgnoredLineLowCount();
                        const uint32_t releaseTimeoutPost = Orchestrator::getFlashTriggerReleaseTimeoutCount();
                        const uint32_t ackTimeoutPost = Orchestrator::getFlashAckTimeoutCount();
                        const uint32_t printTimeoutPost = Orchestrator::getFlashPrintCompletionTimeoutCount();
                        setImagingDroplets(priorDrops);

                        const uint32_t dExt = extPost - extPre;
                        const uint32_t dAck = ackPost - ackPre;
                        const uint32_t dWake = wakePost - wakePre;
                        const uint32_t dDone = donePost - donePre;
                        const uint32_t dAccepted = acceptedPost - acceptedPre;
                        const uint32_t dIgnoredDisarmed = ignoredDisarmedPost - ignoredDisarmedPre;
                        const uint32_t dIgnoredFault = ignoredFaultPost - ignoredFaultPre;
                        const uint32_t dIgnoredBusy = ignoredBusyPost - ignoredBusyPre;
                        const uint32_t dIgnoredLineLow = ignoredLineLowPost - ignoredLineLowPre;
                        const uint32_t dReleaseTimeout = releaseTimeoutPost - releaseTimeoutPre;
                        const uint32_t dAckTimeout = ackTimeoutPost - ackTimeoutPre;
                        const uint32_t dPrintTimeout = printTimeoutPost - printTimeoutPre;
                        const bool taskPresent = (_flashTaskHandle != nullptr);
                        const uint32_t flashSessionArmed = Orchestrator::isFlashSessionArmed() ? 1u : 0u;
                        const uint32_t flashFaultLatched = Orchestrator::isFlashFaultLatched() ? 1u : 0u;
                        const char* flashFaultReason = Orchestrator::getFlashFaultReason();
                        const uint32_t flashOutputArmed = static_cast<uint32_t>(MX_FLASH_IsOutputArmed());
                        const char* flashOutputMode = MX_FLASH_OutputModeToken();
                        const bool pass = (!taskPresent) ||
                                          ((started > 0u) &&
                                           (timedOut == 0u) &&
                                           (dWake >= started) &&
                                           (dDone >= started) &&
                                           (dAck >= started) &&
                                           (dReleaseTimeout == 0u) &&
                                           (dAckTimeout == 0u) &&
                                           (dPrintTimeout == 0u) &&
                                           (flashFaultLatched == 0u));
                        char metrics[640];
                        snprintf(metrics, sizeof(metrics),
                                 "skipped_no_flash_task=%lu;cycles_req=%lu;cycles_started=%lu;cycles_timeout=%lu;ext_delta=%lu;flash_ack_delta=%lu;flash_task_wake_delta=%lu;flash_task_done_delta=%lu;"
                                 "ft_acc_delta=%lu;ft_ign_dis_delta=%lu;ft_ign_fault_delta=%lu;ft_ign_busy_delta=%lu;ft_ign_low_delta=%lu;ft_rel_to_delta=%lu;ft_ack_to_delta=%lu;ft_print_to_delta=%lu;"
                                 "flash_session_armed=%lu;flash_fault_latched=%lu;flash_fault_reason=%s;flash_output_armed=%lu;flash_output_mode=%s",
                                 static_cast<unsigned long>(taskPresent ? 0u : 1u),
                                 static_cast<unsigned long>(kBurstCycles),
                                 static_cast<unsigned long>(started),
                                 static_cast<unsigned long>(timedOut),
                                 static_cast<unsigned long>(dExt),
                                 static_cast<unsigned long>(dAck),
                                 static_cast<unsigned long>(dWake),
                                 static_cast<unsigned long>(dDone),
                                 static_cast<unsigned long>(dAccepted),
                                 static_cast<unsigned long>(dIgnoredDisarmed),
                                 static_cast<unsigned long>(dIgnoredFault),
                                 static_cast<unsigned long>(dIgnoredBusy),
                                 static_cast<unsigned long>(dIgnoredLineLow),
                                 static_cast<unsigned long>(dReleaseTimeout),
                                 static_cast<unsigned long>(dAckTimeout),
                                 static_cast<unsigned long>(dPrintTimeout),
                                 static_cast<unsigned long>(flashSessionArmed),
                                 static_cast<unsigned long>(flashFaultLatched),
                                 flashFaultReason,
                                 static_cast<unsigned long>(flashOutputArmed),
                                 flashOutputMode);
                        if (!runOne(1007, "flash_imaging_burst_diag_safe", pass, metrics)) goto selftest_done;
                      }
	
					  {
					    static const char kBuildInfo[] = __DATE__ " " __TIME__;
					    char metrics[96];
					    snprintf(metrics, sizeof(metrics), "version_len=%u;build_epoch=%s",
					             static_cast<unsigned>(strlen(kBuildInfo)),
					             kBuildInfo);
					    if (!runOne(1006, "fw_build_info", strlen(kBuildInfo) > 0u, metrics)) goto selftest_done;
					  }

						  {
						    static const uint8_t recoveryStream[] = {
					      0x00, 0x7E, 0x55, 0xAB,
					      0xAA, 0x02, 0xF3, 0x01, 0x84, 0x80,
					      0xAA, 0x3F,
					      0xAA, 0x03, 0x10, 0x20, 0x30, 0x40, 0x50,
					      0xAA, 0x02, 0xF3, 0x01, 0x84, 0x80
					    };
					    CommCodec::RxParser parser{};
					    uint8_t parsedLen = 0;
					    uint16_t framesRecovered = 0;
					    uint16_t crcMismatchCount = 0;
					    uint16_t lengthRejectCount = 0;
					    for (size_t i = 0; i < sizeof(recoveryStream); ++i) {
					      const auto result = CommCodec::feedRxByte(parser, recoveryStream[i], parsedLen);
					      if (result == CommCodec::FeedResult::FrameReady) {
					        framesRecovered++;
					      } else if (result == CommCodec::FeedResult::CrcMismatch) {
					        crcMismatchCount++;
					      } else if (result == CommCodec::FeedResult::LengthRejected) {
					        lengthRejectCount++;
					      }
					    }
					    const bool pass = (framesRecovered == 2u) &&
					                      (crcMismatchCount == 1u) &&
					                      (lengthRejectCount == 1u) &&
					                      (parser.state == CommCodec::RxParser::WAIT_START);
					    char metrics[112];
						    snprintf(metrics, sizeof(metrics),
						             "noise_bytes_injected=%u;frames_recovered=%u;crc_mismatch_count=%u;length_reject_count=%u",
						             4u,
						             static_cast<unsigned>(framesRecovered),
						             static_cast<unsigned>(crcMismatchCount),
						             static_cast<unsigned>(lengthRejectCount));
							    if (!runOne(1030, "uart_recovery_after_noise_safe", pass, metrics)) goto selftest_done;
							  }

						  {
						    static constexpr size_t kSelfTestTaskSnapshotCap = 32u;
						    static constexpr uint32_t kSelfTestHeapNowMinBytes = 4096u;
						    static constexpr uint32_t kSelfTestHeapMinMinBytes = 3072u;
						    static constexpr uint16_t kSelfTestStackMinWords = 32u;
						    static TaskStatus_t taskStats[kSelfTestTaskSnapshotCap];
						    const UBaseType_t taskCount = uxTaskGetNumberOfTasks();
						    const UBaseType_t captured = uxTaskGetSystemState(taskStats, kSelfTestTaskSnapshotCap, nullptr);
						    const bool trunc = (taskCount > kSelfTestTaskSnapshotCap) || ((captured == 0u) && (taskCount > 0u));
						    bool hasOrch = false;
						    bool hasStatus = false;
						    bool hasPrinter = false;
						    bool hasPressure = false;
						    bool hasFlashMon = false;
						    uint32_t pregCount = 0u;
						    uint16_t stackMinWords = 0xFFFFu;
						    uint16_t printerHwmWords = 0u;
						    uint16_t flashMonHwmWords = 0u;
						    char stackMinTask[12] = "none";
						    for (UBaseType_t i = 0; i < captured; ++i) {
						      const char* taskName = taskStats[i].pcTaskName;
						      if (taskName == nullptr) {
						        continue;
						      }
						      bool trackForMin = false;
						      if (strcmp(taskName, "Orch") == 0) {
						        hasOrch = true;
						        trackForMin = true;
						      } else if (strcmp(taskName, "Status") == 0) {
						        hasStatus = true;
						        trackForMin = true;
						      } else if (strcmp(taskName, "PRNT") == 0) {
						        hasPrinter = true;
						        printerHwmWords = taskStats[i].usStackHighWaterMark;
						        trackForMin = true;
						      } else if (strcmp(taskName, "Pressure") == 0) {
						        hasPressure = true;
						        trackForMin = true;
						      } else if (strcmp(taskName, "FlashMon") == 0) {
						        hasFlashMon = true;
						        flashMonHwmWords = taskStats[i].usStackHighWaterMark;
						        trackForMin = true;
						      } else if (strcmp(taskName, "PReg") == 0) {
						        pregCount++;
						        trackForMin = true;
						      }
						      if (trackForMin && (taskStats[i].usStackHighWaterMark < stackMinWords)) {
						        stackMinWords = taskStats[i].usStackHighWaterMark;
						        snprintf(stackMinTask, sizeof(stackMinTask), "%s", taskName);
						      }
						    }
						    const uint32_t heapNow = xPortGetFreeHeapSize();
						    const uint32_t heapMin = xPortGetMinimumEverFreeHeapSize();
						    const uint32_t stackOverflowFired = RTOS_StackOverflowHookFired();
						    const uint32_t coreMissing = (hasOrch ? 0u : 1u) +
						                                 (hasStatus ? 0u : 1u) +
						                                 (hasPrinter ? 0u : 1u) +
						                                 (hasPressure ? 0u : 1u);
						    const bool pass = (heapNow >= kSelfTestHeapNowMinBytes) &&
						                      (heapMin >= kSelfTestHeapMinMinBytes) &&
						                      (stackMinWords >= kSelfTestStackMinWords) &&
						                      (coreMissing == 0u) &&
						                      !trunc &&
						                      (pregCount == static_cast<uint32_t>(LC_PRESSURE_PORTS)) &&
						                      (stackOverflowFired == 0u);
						    char metrics[256];
						    snprintf(metrics,
						             sizeof(metrics),
						             "heap_now=%lu;heap_min=%lu;stk_min=%u;stk_task=%s;task_n=%u;task_total=%u;task_cap=%u;core_miss=%lu;preg_n=%lu;trunc=%u;stk_ovf=%lu;prnt_hwm_words=%u;flashmon_hwm_words=%u;flashmon_present=%u",
						             static_cast<unsigned long>(heapNow),
						             static_cast<unsigned long>(heapMin),
						             static_cast<unsigned>(stackMinWords),
						             stackMinTask,
						             static_cast<unsigned>(captured),
						             static_cast<unsigned>(taskCount),
						             static_cast<unsigned>(kSelfTestTaskSnapshotCap),
						             static_cast<unsigned long>(coreMissing),
						             static_cast<unsigned long>(pregCount),
						             trunc ? 1u : 0u,
						             static_cast<unsigned long>(stackOverflowFired),
						             static_cast<unsigned>(printerHwmWords),
						             static_cast<unsigned>(flashMonHwmWords),
						             hasFlashMon ? 1u : 0u);
						    if (!runOne(1040, "rtos_memory_headroom_safe", pass, metrics)) goto selftest_done;
						  }

						#if (LC_CRASHLOG_SELFTEST_ENABLE != 0)
						  {
						    CrashLogSnapshot snap{};
						    CrashLog_GetSnapshot(&snap);
						    char metrics[224];
						    const bool pass = BuildCrashRecordSelfTestResult(snap, metrics, sizeof(metrics));
						    if (!runOne(1041, "crash_record_retained_safe", pass, metrics)) goto selftest_done;
						  }
						#endif

						#if (LC_WATCHDOG_SELFTEST_ENABLE != 0)
						  {
						    WatchdogSelfTestSnapshot snap{};
						    snap.armResult = Watchdog_GetArmResult();
						    snap.enabled = Watchdog_IsEnabled();
						    snap.requiredTaskCount = Watchdog_GetRequiredTaskCount();
						    snap.liveTaskCount = Watchdog_GetLiveTaskCount();
						    snap.lateTask = Watchdog_GetLateTask();
						    snap.recoveryBoot = CrashLog_IsWatchdogRecoveryBoot();
						    snap.timeoutMs = Watchdog_GetTimeoutMs();
						    snap.initTimeoutMs = Watchdog_GetInitTimeoutMs();
						    snap.rawStatus = Watchdog_GetRawStatus();
						    snap.stickyStatusCount = Watchdog_GetStickyStatusCount();
						    char metrics[192];
						    const bool pass = BuildWatchdogSupervisorSelfTestResult(snap, metrics, sizeof(metrics));
						    if (!runOne(1042, "watchdog_supervisor_safe", pass, metrics)) goto selftest_done;
						  }
						#endif

						  {
						    if (!fullProfile || pressureSweepOnly) {
						      if (!runOne(2001,
						                  "motion_home_cycle_full",
						                  true,
						                  pressureSweepOnly ? "profile=FULL;executed=0;fixture_required=1;motion=0;gate=sweep_only" : "profile=SAFE;executed=0;fixture_required=1;motion=0;gate=safe_only")) {
						        goto selftest_done;
						      }
						    } else {
						      static constexpr uint32_t kHomeFastHz = 30000u;
						      static constexpr uint32_t kHomeSlowHz = 3000u;
						      static constexpr uint32_t kHomeBackoffSteps = 400u;
						      static constexpr uint32_t kHomeTimeoutMs = 20000u;
						      uint32_t homeSuccessAxes = 0u;
						      const uint32_t expectedAxes = 2u + static_cast<uint32_t>(LC_PRESSURE_PORTS);
						      const uint32_t homeStartMs = HAL_GetTick();
						      EventBits_t homeBits = BIT_HOME_X_DONE | BIT_HOME_Y_DONE | BIT_HOME_P_DONE;

						      Stepper::stepperX()->enableMotor();
						      Stepper::stepperY()->enableMotor();
						      Stepper::stepperP()->enableMotor();
						#if (LC_PRESSURE_PORTS > 1)
						      Stepper::stepperR()->enableMotor();
						      homeBits |= BIT_HOME_R_DONE;
						#endif

						      xEventGroupClearBits(_doneEvents, homeBits);
						      startHomeAsync(Stepper::stepperX(), kHomeFastHz, kHomeSlowHz, kHomeBackoffSteps, BIT_HOME_X_DONE);
						      startHomeAsync(Stepper::stepperY(), kHomeFastHz, kHomeSlowHz, kHomeBackoffSteps, BIT_HOME_Y_DONE);
						      startRegHomeAsync(&PressureRegulator::regP(), kHomeFastHz, kHomeSlowHz, kHomeBackoffSteps, BIT_HOME_P_DONE);
						#if (LC_PRESSURE_PORTS > 1)
						      startRegHomeAsync(&PressureRegulator::regR(), kHomeFastHz, kHomeSlowHz, kHomeBackoffSteps, BIT_HOME_R_DONE);
						#endif
						      const bool homeCompleted = waitBitsWithTimeout(homeBits, kHomeTimeoutMs);

						      if (isHomedPosition(Stepper::stepperX()->getPosition())) homeSuccessAxes++;
						      if (isHomedPosition(Stepper::stepperY()->getPosition())) homeSuccessAxes++;
						      if (isHomedPosition(Stepper::stepperP()->getPosition())) homeSuccessAxes++;
						#if (LC_PRESSURE_PORTS > 1)
						      if (isHomedPosition(Stepper::stepperR()->getPosition())) homeSuccessAxes++;
						#endif

						      const uint32_t homeTimeMs = HAL_GetTick() - homeStartMs;
						      const uint32_t limitHits = homeSuccessAxes;
						      const bool homePass = homeCompleted && (homeSuccessAxes == expectedAxes);
						      fullHomePass = homePass;
						      char metrics[96];
						      snprintf(metrics, sizeof(metrics),
						               "home_time_ms=%lu;home_success_axes=%lu;limit_hits=%lu",
						               static_cast<unsigned long>(homeTimeMs),
						               static_cast<unsigned long>(homeSuccessAxes),
						               static_cast<unsigned long>(limitHits));
						      if (!runOne(2001, "motion_home_cycle_full", homePass, metrics)) goto selftest_done;
						      if (!homePass) goto selftest_done;
						    }
						  }

						  {
						    if (!fullProfile || pressureSweepOnly) {
						      if (!runOne(2002,
						                  "motion_absolute_move_bounds_full",
						                  true,
						                  pressureSweepOnly ? "profile=FULL;executed=0;fixture_required=1;motion=0;gate=sweep_only" : "profile=SAFE;executed=0;fixture_required=1;motion=0;gate=safe_only")) {
						        goto selftest_done;
						      }
						    } else if (!fullHomePass) {
						      if (!runOne(2002,
						                  "motion_absolute_move_bounds_full",
						                  false,
						                  "target_x=400;target_y=400;target_z=0;final_error_steps=0;bound_violation=1")) {
						        goto selftest_done;
						      }
						    } else {
						      static constexpr int32_t kTargetX = 400;
						      static constexpr int32_t kTargetY = 400;
						      static constexpr int32_t kTargetZ = 0;
						      static constexpr uint32_t kMoveFeedHz = 4000u;
						      const int32_t homeX = Stepper::stepperX()->getPosition();
						      const int32_t homeY = Stepper::stepperY()->getPosition();
						      bool boundViolation = false;
						      uint32_t finalErrorSteps = 0u;

						      xEventGroupClearBits(_doneEvents, BIT_STEPPER1_DONE | BIT_STEPPER2_DONE);
						      Gantry::instance()->moveTo(kTargetX, kTargetY, kMoveFeedHz);
						      const bool reachedTarget = waitForBit(BIT_STEPPER1_DONE) && waitForBit(BIT_STEPPER2_DONE);
						      const GantryPosition targetPos = Gantry::instance()->getPosition();
						      const uint32_t targetErrorX = absDiff32(targetPos.x, kTargetX);
						      const uint32_t targetErrorY = absDiff32(targetPos.y, kTargetY);
						      finalErrorSteps = (targetErrorX > targetErrorY) ? targetErrorX : targetErrorY;
						      boundViolation = (targetPos.x < 0) || (targetPos.y < 0) ||
						                       (targetPos.x > (kTargetX + 50)) || (targetPos.y > (kTargetY + 50));

						      xEventGroupClearBits(_doneEvents, BIT_STEPPER1_DONE | BIT_STEPPER2_DONE);
						      Gantry::instance()->moveTo(homeX, homeY, kMoveFeedHz);
						      const bool returnedHome = waitForBit(BIT_STEPPER1_DONE) && waitForBit(BIT_STEPPER2_DONE);
						      const GantryPosition returnPos = Gantry::instance()->getPosition();
						      const uint32_t returnErrorX = absDiff32(returnPos.x, homeX);
						      const uint32_t returnErrorY = absDiff32(returnPos.y, homeY);
						      const uint32_t returnError = (returnErrorX > returnErrorY) ? returnErrorX : returnErrorY;
						      if (returnError > finalErrorSteps) finalErrorSteps = returnError;
						      boundViolation = boundViolation ||
						                       (returnPos.x < 0) || (returnPos.y < 0) ||
						                       (returnPos.x > (kTargetX + 50)) || (returnPos.y > (kTargetY + 50));

						      const bool movePass = reachedTarget && returnedHome && !boundViolation && (finalErrorSteps <= 4u);
						      fullMotionBoundsPass = movePass;
						      char metrics[96];
						      snprintf(metrics, sizeof(metrics),
						               "target_x=%ld;target_y=%ld;target_z=%ld;final_error_steps=%lu;bound_violation=%u",
						               static_cast<long>(kTargetX),
						               static_cast<long>(kTargetY),
						               static_cast<long>(kTargetZ),
						               static_cast<unsigned long>(finalErrorSteps),
						               static_cast<unsigned>(boundViolation ? 1u : 0u));
						      if (!runOne(2002, "motion_absolute_move_bounds_full", movePass, metrics)) goto selftest_done;
						    }
						  }

                          {
                            if (!fullProfile || pressureSweepOnly) {
                              if (!runOne(2007,
                                          "motion_home_repeatability_factory",
                                          true,
                                          pressureSweepOnly ? "profile=FULL;executed=0;fixture_required=1;motion=0;gate=sweep_only" : "profile=SAFE;executed=0;fixture_required=1;motion=0;gate=safe_only")) {
                                goto selftest_done;
                              }
                            } else if (!fullHomePass) {
                              if (!runOne(2007,
                                          "motion_home_repeatability_factory",
                                          false,
                                          "axis=xy;rep=0;x_min=0;x_max=0;x_span=0;y_min=0;y_max=0;y_span=0;ret_err=0;move_to=0;home_to=1")) {
                                goto selftest_done;
                              }
                            } else {
                              static constexpr uint32_t kRepeatCount = 3u;
                              static constexpr uint32_t kHomeFastHz = 30000u;
                              static constexpr uint32_t kHomeSlowHz = 3000u;
                              static constexpr uint32_t kHomeBackoffSteps = 400u;
                              static constexpr uint32_t kHomeTimeoutMs = 20000u;
                              static constexpr int32_t kExpectedBackoffSteps = 100;
                              MotionQualificationMath::AxisHomeSample xSamples[kRepeatCount]{};
                              MotionQualificationMath::AxisHomeSample ySamples[kRepeatCount]{};
                              bool allHomesPassed = true;
                              for (uint32_t rep = 0; rep < kRepeatCount; ++rep) {
                                sendProgressStage("motion_home_repeatability");
                                const bool homesPassed = runXyHomeDiagnosticAttempt(xSamples[rep],
                                                                                     ySamples[rep],
                                                                                     kHomeFastHz,
                                                                                     kHomeSlowHz,
                                                                                     kHomeBackoffSteps,
                                                                                     kHomeTimeoutMs);
                                allHomesPassed = allHomesPassed && homesPassed;
                                if (_selfTestAbortRequested) {
                                  break;
                                }
                              }
                              const MotionQualificationMath::AxisHomeStats xStats =
                                  MotionQualificationMath::summarizeAxisHomeSamples(xSamples,
                                                                                   kRepeatCount,
                                                                                   kExpectedBackoffSteps);
                              const MotionQualificationMath::AxisHomeStats yStats =
                                  MotionQualificationMath::summarizeAxisHomeSamples(ySamples,
                                                                                   kRepeatCount,
                                                                                   kExpectedBackoffSteps);
                              const uint32_t moveTimeoutCount = xStats.moveTimeoutCount + yStats.moveTimeoutCount;
                              const uint32_t homeTimeoutCount = xStats.homeTimeoutCount + yStats.homeTimeoutCount;
                              const uint32_t returnErrorMax = (xStats.returnErrorMaxSteps > yStats.returnErrorMaxSteps)
                                  ? xStats.returnErrorMaxSteps
                                  : yStats.returnErrorMaxSteps;
                              const bool repeatPass = allHomesPassed &&
                                  MotionQualificationMath::axisHomeStatsPass(xStats, kRepeatCount) &&
                                  MotionQualificationMath::axisHomeStatsPass(yStats, kRepeatCount);
                              char metrics[192];
                              snprintf(metrics, sizeof(metrics),
                                       "axis=xy;rep=%lu;x_min=%ld;x_max=%ld;x_span=%lu;y_min=%ld;y_max=%ld;y_span=%lu;ret_err=%lu;move_to=%lu;home_to=%lu",
                                       static_cast<unsigned long>(kRepeatCount),
                                       static_cast<long>(xStats.limitTriggerMinSteps),
                                       static_cast<long>(xStats.limitTriggerMaxSteps),
                                       static_cast<unsigned long>(xStats.limitTriggerSpanSteps),
                                       static_cast<long>(yStats.limitTriggerMinSteps),
                                       static_cast<long>(yStats.limitTriggerMaxSteps),
                                       static_cast<unsigned long>(yStats.limitTriggerSpanSteps),
                                       static_cast<unsigned long>(returnErrorMax),
                                       static_cast<unsigned long>(moveTimeoutCount),
                                       static_cast<unsigned long>(homeTimeoutCount));
                              if (!runOne(2007, "motion_home_repeatability_factory", repeatPass, metrics)) goto selftest_done;
                            }
                          }

                          {
                            if (!fullProfile || pressureSweepOnly) {
                              if (!runOne(2008,
                                          "motion_pattern_return_factory",
                                          true,
                                          pressureSweepOnly ? "profile=FULL;executed=0;fixture_required=1;motion=0;gate=sweep_only" : "profile=SAFE;executed=0;fixture_required=1;motion=0;gate=safe_only")) {
                                goto selftest_done;
                              }
                            } else if (!fullHomePass || !fullMotionBoundsPass) {
                              if (!runOne(2008,
                                          "motion_pattern_return_factory",
                                          false,
                                          "axis=xy;rep=0;pts=0;ret_err=0;x_ret=0;y_ret=0;move_to=0;home_to=0;bound=1;executed=0;base_motion_bounds=0")) {
                                goto selftest_done;
                              }
                            } else {
                              static constexpr uint32_t kPatternRepetitions = 2u;
                              static constexpr uint32_t kPatternPoints = 4u;
                              static constexpr uint32_t kPatternFeedHz = 4000u;
                              static constexpr uint32_t kPatternMoveTimeoutMs = 5000u;
                              static constexpr uint32_t kHomeFastHz = 30000u;
                              static constexpr uint32_t kHomeSlowHz = 3000u;
                              static constexpr uint32_t kHomeBackoffSteps = 400u;
                              static constexpr uint32_t kHomeTimeoutMs = 20000u;
                              static constexpr int32_t kPatternStep = 200;
                              static constexpr int32_t kAllowedMin = 0;
                              static constexpr int32_t kAllowedMax = 450;
                              const int32_t homeX = Stepper::stepperX()->getPosition();
                              const int32_t homeY = Stepper::stepperY()->getPosition();
                              const int32_t targets[kPatternPoints][2] = {
                                  {homeX + kPatternStep, homeY},
                                  {homeX + kPatternStep, homeY + kPatternStep},
                                  {homeX, homeY + kPatternStep},
                                  {homeX, homeY},
                              };
                              MotionQualificationMath::PatternReturnStats patternStats{};
                              patternStats.repetitions = kPatternRepetitions;
                              patternStats.patternPoints = kPatternPoints;

                              bool allMovesCompleted = true;
                              for (uint32_t rep = 0; rep < kPatternRepetitions; ++rep) {
                                sendProgressStage("motion_pattern_return");
                                bool repMovesCompleted = true;
                                bool repBoundViolation = false;
                                for (uint32_t point = 0; point < kPatternPoints; ++point) {
                                  const bool reached = moveGantryToWithTimeout(targets[point][0],
                                                                               targets[point][1],
                                                                               kPatternFeedHz,
                                                                               kPatternMoveTimeoutMs);
                                  repMovesCompleted = repMovesCompleted && reached;
                                  allMovesCompleted = allMovesCompleted && reached;
                                  const GantryPosition pos = Gantry::instance()->getPosition();
                                  repBoundViolation = repBoundViolation ||
                                      (pos.x < kAllowedMin) || (pos.y < kAllowedMin) ||
                                      (pos.x > kAllowedMax) || (pos.y > kAllowedMax);
                                  if (!reached || _selfTestAbortRequested) {
                                    break;
                                  }
                                }

                                MotionQualificationMath::AxisHomeSample xHome{};
                                MotionQualificationMath::AxisHomeSample yHome{};
                                const bool homePassed = runXyHomeDiagnosticAttempt(xHome,
                                                                                   yHome,
                                                                                   kHomeFastHz,
                                                                                   kHomeSlowHz,
                                                                                   kHomeBackoffSteps,
                                                                                   kHomeTimeoutMs);
                                MotionQualificationMath::recordPatternReturn(patternStats,
                                                                             homeX,
                                                                             homeY,
                                                                             Stepper::stepperX()->getPosition(),
                                                                             Stepper::stepperY()->getPosition(),
                                                                             repMovesCompleted,
                                                                             homePassed,
                                                                             repBoundViolation);
                                patternStats.moveTimeoutCount += xHome.moveTimeoutCount + yHome.moveTimeoutCount;
                                if (!allMovesCompleted || !homePassed || _selfTestAbortRequested) {
                                  break;
                                }
                              }

                              const bool patternPass = allMovesCompleted && MotionQualificationMath::patternReturnStatsPass(patternStats);
                              char metrics[160];
                              snprintf(metrics, sizeof(metrics),
                                       "axis=xy;rep=%lu;pts=%lu;ret_err=%lu;x_ret=%lu;y_ret=%lu;move_to=%lu;home_to=%lu;bound=%lu",
                                       static_cast<unsigned long>(patternStats.repetitions),
                                       static_cast<unsigned long>(patternStats.patternPoints),
                                       static_cast<unsigned long>(patternStats.returnErrorMaxSteps),
                                       static_cast<unsigned long>(patternStats.xReturnErrorMaxSteps),
                                       static_cast<unsigned long>(patternStats.yReturnErrorMaxSteps),
                                       static_cast<unsigned long>(patternStats.moveTimeoutCount),
                                       static_cast<unsigned long>(patternStats.homeTimeoutCount),
                                       static_cast<unsigned long>(patternStats.boundViolationCount));
                              if (!runOne(2008, "motion_pattern_return_factory", patternPass, metrics)) goto selftest_done;
                            }
                          }

						  {
						    if (!fullProfile || pressureSweepOnly) {
						      if (!runOne(2003,
						                  "pressure_regulator_step_response_full",
						                  true,
						                  pressureSweepOnly ? "profile=FULL;executed=0;fixture_required=1;pressure=0;gate=sweep_only" : "profile=SAFE;executed=0;fixture_required=1;pressure=0;gate=safe_only")) {
						        goto selftest_done;
						      }
						    } else if (!fullHomePass) {
						      if (!runOne(2003,
						                  "pressure_regulator_step_response_full",
						                  false,
						                  "target_pressure=0;settle_time_ms=0;overshoot=0;steady_state_error=0")) {
						        goto selftest_done;
						      }
						    } else {
						      static constexpr uint32_t kBaselineTimeoutMs = 3000u;
						      static constexpr uint32_t kSettleTimeoutMs = 4000u;
						      static constexpr int32_t kPressureDelta = 200;
						      PressureSensor* sensor = PressureSensor::instance();
						      PressureRegulator& reg = PressureRegulator::regP();
						      const int32_t baselineTarget = static_cast<int32_t>(reg.getTarget());
						      int32_t targetPressure = baselineTarget + kPressureDelta;
						      bool stepUp = true;
						      if (targetPressure > 5600) {
						        targetPressure = baselineTarget - kPressureDelta;
						        stepUp = false;
						      }
						      uint32_t settleTimeMs = kSettleTimeoutMs;
						      uint32_t overshoot = 0u;
						      uint32_t steadyStateError = 0u;
                              uint32_t avgError = 0u;
                              bool baseReady = false;
                              uint32_t baselineSettleMs = 0u;
                              uint32_t baselineError = 0u;
                              bool targetRun = false;
                              bool targetReady = false;
						      bool pressurePass = false;
                              const uint32_t readyTol = reg.getReadyConfig().readyTolRaw;

						      if (sensor && targetPressure != baselineTarget) {
						        reg.start();
						        xEventGroupClearBits(_doneEvents, BIT_PRESSURE_P_READY);
						        const PressureWaitResult baselineWait = waitPressureReady(reg,
						                                                                  0u,
						                                                                  baselineTarget,
						                                                                  true,
						                                                                  kBaselineTimeoutMs);
                                baseReady = baselineWait.accepted;
                                baselineSettleMs = baselineWait.settleMs;
                                baselineError = baselineWait.controlError;
                                if (baseReady && !_selfTestAbortRequested) {
                                  xEventGroupClearBits(_doneEvents, BIT_PRESSURE_P_READY);
                                  reg.setTargetSafe(targetPressure);
                                  targetPressure = static_cast<int32_t>(reg.getTarget());
                                  targetRun = true;
                                  const PressureWaitResult targetWait = waitPressureReady(reg,
                                                                                          0u,
                                                                                          targetPressure,
                                                                                          stepUp,
                                                                                          kSettleTimeoutMs);
                                  targetReady = targetWait.accepted;
                                  settleTimeMs = targetWait.settleMs;
                                  overshoot = targetWait.overshoot;
                                  steadyStateError = targetWait.controlError;
                                  avgError = targetWait.avgError;
                                  pressurePass = targetReady &&
                                                 (steadyStateError <= 120u) &&
                                                 (overshoot <= 300u);
                                } else {
                                  settleTimeMs = 0u;
                                  overshoot = 0u;
                                  steadyStateError = 0u;
                                  avgError = 0u;
                                  pressurePass = false;
                                }
						        xEventGroupClearBits(_doneEvents, BIT_PRESSURE_P_READY);
						        reg.setTargetSafe(baselineTarget);
						        (void)waitPressureReady(reg,
						                                0u,
						                                baselineTarget,
						                                !stepUp,
						                                kSettleTimeoutMs);
						        reg.pause();
						      }

						      char metrics[224];
						      snprintf(metrics, sizeof(metrics),
						               "target_pressure=%ld;settle_time_ms=%lu;overshoot=%lu;steady_state_error=%lu;base_ready=%u;base_ms=%lu;base_err=%lu;target_run=%u;target_ready=%u;control_error=%lu;avg_error=%lu;ready_tol=%lu",
						               static_cast<long>(targetPressure),
						               static_cast<unsigned long>(settleTimeMs),
						               static_cast<unsigned long>(overshoot),
						               static_cast<unsigned long>(steadyStateError),
                                       static_cast<unsigned>(baseReady ? 1u : 0u),
                                       static_cast<unsigned long>(baselineSettleMs),
                                       static_cast<unsigned long>(baselineError),
                                       static_cast<unsigned>(targetRun ? 1u : 0u),
                                       static_cast<unsigned>(targetReady ? 1u : 0u),
						               static_cast<unsigned long>(steadyStateError),
                                       static_cast<unsigned long>(avgError),
                                       static_cast<unsigned long>(readyTol));
						      if (!runOne(2003, "pressure_regulator_step_response_full", pressurePass, metrics)) goto selftest_done;
						    }
						  }

                          {
                            if (!fullProfile || pressureSweepOnly) {
                              if (!runOne(2201,
                                          "pressure_hold_leak_factory",
                                          true,
                                          pressureSweepOnly ? "profile=FULL;executed=0;fixture_required=1;pressure=0;gate=sweep_only" : "profile=SAFE;executed=0;fixture_required=1;pressure=0;gate=safe_only")) {
                                goto selftest_done;
                              }
                            } else if (!fullHomePass) {
                              if (!runOne(2201,
                                          "pressure_hold_leak_factory",
                                          false,
                                          "channel=p;target_raw=0;hold_ms=0;p_start=0;p_end=0;slope_raw_min=0;corr_steps=0;motor_start=0;motor_end=0;ready_miss=1;timeout=0")) {
                                goto selftest_done;
                              }
                            } else {
                              static constexpr uint32_t kHoldSettleTimeoutMs = 5000u;
                              static constexpr uint32_t kHoldMs = 5000u;
                              static constexpr int32_t kPressureDelta = 200;
                              static constexpr uint32_t kQualificationPressureErrorTolRaw = 100u;
                              PressureQualificationMath::ExecutionSummary exec{};
                              PressureSensor* sensor = PressureSensor::instance();
                              PressureRegulator& reg = PressureRegulator::regP();
                              const int32_t baselineTarget = static_cast<int32_t>(reg.getTarget());
                              int32_t holdTarget = baselineTarget + kPressureDelta;
                              bool stepUp = true;
                              if (holdTarget > 5600) {
                                holdTarget = baselineTarget - kPressureDelta;
                                stepUp = false;
                              }
                              int32_t pressureStart = 0;
                              int32_t pressureEnd = 0;
                              int32_t motorStart = 0;
                              int32_t motorEnd = 0;

                              if (sensor && holdTarget != baselineTarget) {
                                reg.start();
                                xEventGroupClearBits(_doneEvents, BIT_PRESSURE_P_READY);
                                reg.setTargetSafe(holdTarget);
                                holdTarget = static_cast<int32_t>(reg.getTarget());
                                const PressureWaitResult ready = waitPressureReady(reg,
                                                                                   0u,
                                                                                   holdTarget,
                                                                                   stepUp,
                                                                                   kHoldSettleTimeoutMs,
                                                                                   kQualificationPressureErrorTolRaw);
                                recordPressureWaitExecution(ready, exec);
                                if (ready.accepted && !_selfTestAbortRequested) {
                                  const PressurePositionSample startSample = readPrintPressurePositionSample();
                                  pressureStart = startSample.pressureRaw;
                                  motorStart = startSample.motorPosition;
                                  if (!delayWithWatchdog(kHoldMs, "pressure_hold_leak")) {
                                    exec.abortCount++;
                                  }
                                  const PressurePositionSample endSample = readPrintPressurePositionSample();
                                  pressureEnd = endSample.pressureRaw;
                                  motorEnd = endSample.motorPosition;
                                }
                                xEventGroupClearBits(_doneEvents, BIT_PRESSURE_P_READY);
                                reg.setTargetSafe(baselineTarget);
                                (void)waitPressureReady(reg,
                                                        0u,
                                                        baselineTarget,
                                                        !stepUp,
                                                        kHoldSettleTimeoutMs,
                                                        kQualificationPressureErrorTolRaw);
                                reg.pause();
                              } else {
                                exec.readyMissCount++;
                              }

                              const int32_t slopeRawPerMin =
                                  PressureQualificationMath::slopeRawPerMin(pressureStart, pressureEnd, kHoldMs);
                              const uint32_t correctionSteps =
                                  PressureQualificationMath::absDiff(motorStart, motorEnd);
                              const bool holdPass = sensor &&
                                                    (holdTarget != baselineTarget) &&
                                                    PressureQualificationMath::executionPass(exec);
                              char metrics[192];
                              snprintf(metrics, sizeof(metrics),
                                       "channel=p;target_raw=%ld;hold_ms=%lu;p_start=%ld;p_end=%ld;slope_raw_min=%ld;corr_steps=%lu;motor_start=%ld;motor_end=%ld;ready_miss=%lu;timeout=%lu",
                                       static_cast<long>(holdTarget),
                                       static_cast<unsigned long>(kHoldMs),
                                       static_cast<long>(pressureStart),
                                       static_cast<long>(pressureEnd),
                                       static_cast<long>(slopeRawPerMin),
                                       static_cast<unsigned long>(correctionSteps),
                                       static_cast<long>(motorStart),
                                       static_cast<long>(motorEnd),
                                       static_cast<unsigned long>(exec.readyMissCount),
                                       static_cast<unsigned long>(exec.timeoutCount));
                              if (!runOne(2201, "pressure_hold_leak_factory", holdPass, metrics)) goto selftest_done;
                            }
                          }

                          {
                            if (!fullProfile || pressureSweepOnly) {
                              if (!runOne(2202,
                                          "pressure_target_cycle_repeatability_factory",
                                          true,
                                          pressureSweepOnly ? "profile=FULL;executed=0;fixture_required=1;pressure=0;gate=sweep_only" : "profile=SAFE;executed=0;fixture_required=1;pressure=0;gate=safe_only")) {
                                goto selftest_done;
                              }
                            } else if (!fullHomePass) {
                              if (!runOne(2202,
                                          "pressure_target_cycle_repeatability_factory",
                                          false,
                                          "channel=p;cycles=0;low_raw=0;high_raw=0;settle_max_ms=0;err_max=0;low_span=0;high_span=0;ready_miss=1;timeout=0")) {
                                goto selftest_done;
                              }
                            } else {
                              static constexpr uint32_t kCycleCount = 3u;
                              static constexpr uint32_t kCycleSettleTimeoutMs = 5000u;
                              static constexpr int32_t kPressureDelta = 200;
                              static constexpr uint32_t kQualificationPressureErrorTolRaw = 100u;
                              PressureQualificationMath::ExecutionSummary exec{};
                              PressureSensor* sensor = PressureSensor::instance();
                              PressureRegulator& reg = PressureRegulator::regP();
                              const int32_t baselineTarget = static_cast<int32_t>(reg.getTarget());
                              int32_t targetA = baselineTarget;
                              int32_t targetB = baselineTarget + kPressureDelta;
                              bool bIsStepUp = true;
                              if (targetB > 5600) {
                                targetB = baselineTarget - kPressureDelta;
                                bIsStepUp = false;
                              }
                              int32_t lowPositions[kCycleCount]{};
                              int32_t highPositions[kCycleCount]{};
                              size_t lowCount = 0u;
                              size_t highCount = 0u;
                              uint32_t settleMaxMs = 0u;
                              uint32_t errMax = 0u;

                              if (sensor && targetB != targetA) {
                                reg.start();
                                for (uint32_t cycle = 0; cycle < kCycleCount; ++cycle) {
                                  sendProgressStage("pressure_cycle_repeat");
                                  xEventGroupClearBits(_doneEvents, BIT_PRESSURE_P_READY);
                                  reg.setTargetSafe(targetA);
                                  targetA = static_cast<int32_t>(reg.getTarget());
                                  const PressureWaitResult waitA = waitPressureReady(reg,
                                                                                     0u,
                                                                                     targetA,
                                                                                     !bIsStepUp,
                                                                                     kCycleSettleTimeoutMs,
                                                                                     kQualificationPressureErrorTolRaw);
                                  recordPressureWaitExecution(waitA, exec);
                                  if (waitA.settleMs > settleMaxMs) settleMaxMs = waitA.settleMs;
                                  if (waitA.controlError > errMax) errMax = waitA.controlError;
                                  if (!waitA.accepted || _selfTestAbortRequested) {
                                    break;
                                  }
                                  const PressurePositionSample sampleA = readPrintPressurePositionSample();
                                  if (targetA <= targetB) {
                                    if (lowCount < kCycleCount) lowPositions[lowCount++] = sampleA.motorPosition;
                                  } else {
                                    if (highCount < kCycleCount) highPositions[highCount++] = sampleA.motorPosition;
                                  }

                                  xEventGroupClearBits(_doneEvents, BIT_PRESSURE_P_READY);
                                  reg.setTargetSafe(targetB);
                                  targetB = static_cast<int32_t>(reg.getTarget());
                                  const PressureWaitResult waitB = waitPressureReady(reg,
                                                                                     0u,
                                                                                     targetB,
                                                                                     bIsStepUp,
                                                                                     kCycleSettleTimeoutMs,
                                                                                     kQualificationPressureErrorTolRaw);
                                  recordPressureWaitExecution(waitB, exec);
                                  if (waitB.settleMs > settleMaxMs) settleMaxMs = waitB.settleMs;
                                  if (waitB.controlError > errMax) errMax = waitB.controlError;
                                  if (!waitB.accepted || _selfTestAbortRequested) {
                                    break;
                                  }
                                  const PressurePositionSample sampleB = readPrintPressurePositionSample();
                                  if (targetB <= targetA) {
                                    if (lowCount < kCycleCount) lowPositions[lowCount++] = sampleB.motorPosition;
                                  } else {
                                    if (highCount < kCycleCount) highPositions[highCount++] = sampleB.motorPosition;
                                  }
                                  if (_selfTestAbortRequested) {
                                    exec.abortCount++;
                                    break;
                                  }
                                }
                                xEventGroupClearBits(_doneEvents, BIT_PRESSURE_P_READY);
                                reg.setTargetSafe(baselineTarget);
                                (void)waitPressureReady(reg,
                                                        0u,
                                                        baselineTarget,
                                                        !bIsStepUp,
                                                        kCycleSettleTimeoutMs,
                                                        kQualificationPressureErrorTolRaw);
                                reg.pause();
                              } else {
                                exec.readyMissCount++;
                              }

                              const PressureQualificationMath::Int32Span lowStats =
                                  PressureQualificationMath::summarizeInt32Span(lowPositions, lowCount);
                              const PressureQualificationMath::Int32Span highStats =
                                  PressureQualificationMath::summarizeInt32Span(highPositions, highCount);
                              const int32_t lowRaw = (targetA < targetB) ? targetA : targetB;
                              const int32_t highRaw = (targetA > targetB) ? targetA : targetB;
                              const bool cyclePass = sensor &&
                                                     (targetA != targetB) &&
                                                     PressureQualificationMath::executionPass(exec);
                              char metrics[192];
                              snprintf(metrics, sizeof(metrics),
                                       "channel=p;cycles=%lu;low_raw=%ld;high_raw=%ld;settle_max_ms=%lu;err_max=%lu;low_span=%lu;high_span=%lu;ready_miss=%lu;timeout=%lu",
                                       static_cast<unsigned long>(kCycleCount),
                                       static_cast<long>(lowRaw),
                                       static_cast<long>(highRaw),
                                       static_cast<unsigned long>(settleMaxMs),
                                       static_cast<unsigned long>(errMax),
                                       static_cast<unsigned long>(lowStats.span),
                                       static_cast<unsigned long>(highStats.span),
                                       static_cast<unsigned long>(exec.readyMissCount),
                                       static_cast<unsigned long>(exec.timeoutCount));
                              if (!runOne(2202, "pressure_target_cycle_repeatability_factory", cyclePass, metrics)) goto selftest_done;
                            }
                          }

                          {
                            if (!fullProfile || pressureSweepOnly) {
                              if (!runOne(2203,
                                          "pressure_motor_position_hysteresis_factory",
                                          true,
                                          pressureSweepOnly ? "profile=FULL;executed=0;fixture_required=1;pressure=0;gate=sweep_only" : "profile=SAFE;executed=0;fixture_required=1;pressure=0;gate=safe_only")) {
                                goto selftest_done;
                              }
                            } else if (!fullHomePass) {
                              if (!runOne(2203,
                                          "pressure_motor_position_hysteresis_factory",
                                          false,
                                          "channel=p;target_raw=0;visits=0;pos_min=0;pos_max=0;repeat_span=0;hyst_span=0;err_max=0;ready_miss=1;timeout=0")) {
                                goto selftest_done;
                              }
                            } else {
                              static constexpr uint32_t kHysteresisReps = 2u;
                              static constexpr uint32_t kHysteresisSettleTimeoutMs = 5000u;
                              static constexpr uint32_t kQualificationPressureErrorTolRaw = 100u;
                              PressureQualificationMath::ExecutionSummary exec{};
                              PressureSensor* sensor = PressureSensor::instance();
                              PressureRegulator& reg = PressureRegulator::regP();
                              const int32_t baselineTarget = static_cast<int32_t>(reg.getTarget());
                              int32_t lowTarget = baselineTarget;
                              int32_t targetRaw = baselineTarget + 100;
                              int32_t highTarget = baselineTarget + 200;
                              if (highTarget > 5600) {
                                highTarget = baselineTarget;
                                targetRaw = baselineTarget - 100;
                                lowTarget = baselineTarget - 200;
                              }
                              int32_t belowPositions[kHysteresisReps]{};
                              int32_t abovePositions[kHysteresisReps]{};
                              int32_t allPositions[kHysteresisReps * 2u]{};
                              size_t belowCount = 0u;
                              size_t aboveCount = 0u;
                              size_t allCount = 0u;
                              uint32_t errMax = 0u;

                              if (sensor && (lowTarget != highTarget) && (targetRaw != baselineTarget)) {
                                reg.start();
                                for (uint32_t rep = 0; rep < kHysteresisReps; ++rep) {
                                  sendProgressStage("pressure_hysteresis");
                                  xEventGroupClearBits(_doneEvents, BIT_PRESSURE_P_READY);
                                  reg.setTargetSafe(lowTarget);
                                  lowTarget = static_cast<int32_t>(reg.getTarget());
                                  const PressureWaitResult lowWait = waitPressureReady(reg,
                                                                                       0u,
                                                                                       lowTarget,
                                                                                       false,
                                                                                       kHysteresisSettleTimeoutMs,
                                                                                       kQualificationPressureErrorTolRaw);
                                  recordPressureWaitExecution(lowWait, exec);
                                  if (lowWait.controlError > errMax) errMax = lowWait.controlError;
                                  if (!lowWait.accepted || _selfTestAbortRequested) {
                                    break;
                                  }

                                  xEventGroupClearBits(_doneEvents, BIT_PRESSURE_P_READY);
                                  reg.setTargetSafe(targetRaw);
                                  targetRaw = static_cast<int32_t>(reg.getTarget());
                                  const PressureWaitResult fromBelow = waitPressureReady(reg,
                                                                                         0u,
                                                                                         targetRaw,
                                                                                         true,
                                                                                         kHysteresisSettleTimeoutMs,
                                                                                         kQualificationPressureErrorTolRaw);
                                  recordPressureWaitExecution(fromBelow, exec);
                                  if (fromBelow.controlError > errMax) errMax = fromBelow.controlError;
                                  if (!fromBelow.accepted || _selfTestAbortRequested) {
                                    break;
                                  }
                                  const PressurePositionSample belowSample = readPrintPressurePositionSample();
                                  if (belowCount < kHysteresisReps) belowPositions[belowCount++] = belowSample.motorPosition;
                                  if (allCount < (kHysteresisReps * 2u)) allPositions[allCount++] = belowSample.motorPosition;

                                  xEventGroupClearBits(_doneEvents, BIT_PRESSURE_P_READY);
                                  reg.setTargetSafe(highTarget);
                                  highTarget = static_cast<int32_t>(reg.getTarget());
                                  const PressureWaitResult highWait = waitPressureReady(reg,
                                                                                        0u,
                                                                                        highTarget,
                                                                                        true,
                                                                                        kHysteresisSettleTimeoutMs,
                                                                                        kQualificationPressureErrorTolRaw);
                                  recordPressureWaitExecution(highWait, exec);
                                  if (highWait.controlError > errMax) errMax = highWait.controlError;
                                  if (!highWait.accepted || _selfTestAbortRequested) {
                                    break;
                                  }

                                  xEventGroupClearBits(_doneEvents, BIT_PRESSURE_P_READY);
                                  reg.setTargetSafe(targetRaw);
                                  targetRaw = static_cast<int32_t>(reg.getTarget());
                                  const PressureWaitResult fromAbove = waitPressureReady(reg,
                                                                                         0u,
                                                                                         targetRaw,
                                                                                         false,
                                                                                         kHysteresisSettleTimeoutMs,
                                                                                         kQualificationPressureErrorTolRaw);
                                  recordPressureWaitExecution(fromAbove, exec);
                                  if (fromAbove.controlError > errMax) errMax = fromAbove.controlError;
                                  if (!fromAbove.accepted || _selfTestAbortRequested) {
                                    break;
                                  }
                                  const PressurePositionSample aboveSample = readPrintPressurePositionSample();
                                  if (aboveCount < kHysteresisReps) abovePositions[aboveCount++] = aboveSample.motorPosition;
                                  if (allCount < (kHysteresisReps * 2u)) allPositions[allCount++] = aboveSample.motorPosition;

                                  if (_selfTestAbortRequested) {
                                    exec.abortCount++;
                                    break;
                                  }
                                }
                                xEventGroupClearBits(_doneEvents, BIT_PRESSURE_P_READY);
                                reg.setTargetSafe(baselineTarget);
                                const bool restoreStepUp = baselineTarget >= targetRaw;
                                (void)waitPressureReady(reg,
                                                        0u,
                                                        baselineTarget,
                                                        restoreStepUp,
                                                        kHysteresisSettleTimeoutMs,
                                                        kQualificationPressureErrorTolRaw);
                                reg.pause();
                              } else {
                                exec.readyMissCount++;
                              }

                              const PressureQualificationMath::Int32Span repeatStats =
                                  PressureQualificationMath::summarizeInt32Span(allPositions, allCount);
                              const uint32_t hystSpan =
                                  PressureQualificationMath::meanDifferenceAbs(belowPositions,
                                                                               belowCount,
                                                                               abovePositions,
                                                                               aboveCount);
                              const bool hysteresisPass = sensor &&
                                                          (targetRaw != baselineTarget) &&
                                                          PressureQualificationMath::executionPass(exec);
                              char metrics[192];
                              snprintf(metrics, sizeof(metrics),
                                       "channel=p;target_raw=%ld;visits=%lu;pos_min=%ld;pos_max=%ld;repeat_span=%lu;hyst_span=%lu;err_max=%lu;ready_miss=%lu;timeout=%lu",
                                       static_cast<long>(targetRaw),
                                       static_cast<unsigned long>(allCount),
                                       static_cast<long>(repeatStats.minValue),
                                       static_cast<long>(repeatStats.maxValue),
                                       static_cast<unsigned long>(repeatStats.span),
                                       static_cast<unsigned long>(hystSpan),
                                       static_cast<unsigned long>(errMax),
                                       static_cast<unsigned long>(exec.readyMissCount),
                                       static_cast<unsigned long>(exec.timeoutCount));
                              if (!runOne(2203, "pressure_motor_position_hysteresis_factory", hysteresisPass, metrics)) goto selftest_done;
                            }
                          }

						  {
						    if (!fullProfile || pressureSweepOnly) {
						      if (!runOne(2004,
						                  "valve_actuation_sequence_full",
						                  true,
						                  pressureSweepOnly ? "profile=FULL;executed=0;fixture_required=1;valves=0;gate=sweep_only" : "profile=SAFE;executed=0;fixture_required=1;valves=0;gate=safe_only")) {
						        goto selftest_done;
						      }
						    } else if (!fullHomePass) {
						      if (!runOne(2004,
						                  "valve_actuation_sequence_full",
						                  false,
						                  "valve_open_count=0;valve_close_count=0;sequence_order_ok=0")) {
						        goto selftest_done;
						      }
						    } else {
						      uint32_t openCount = 0u;
						      uint32_t closeCount = 0u;
						      bool sequenceOrderOk = true;

						      PressureRegulator::regP().openValve();
						      openCount++;
						      sequenceOrderOk = sequenceOrderOk && PressureRegulator::regP().isValveOpen();
						      vTaskDelay(pdMS_TO_TICKS(10));
						      PressureRegulator::regP().closeValve();
						      closeCount++;
						      sequenceOrderOk = sequenceOrderOk && !PressureRegulator::regP().isValveOpen();

						#if (LC_PRESSURE_PORTS > 1)
						      PressureRegulator::regR().openValve();
						      openCount++;
						      sequenceOrderOk = sequenceOrderOk && PressureRegulator::regR().isValveOpen();
						      vTaskDelay(pdMS_TO_TICKS(10));
						      PressureRegulator::regR().closeValve();
						      closeCount++;
						      sequenceOrderOk = sequenceOrderOk && !PressureRegulator::regR().isValveOpen();
						#endif

						      const bool valvePass = sequenceOrderOk && (openCount == closeCount);
						      char metrics[96];
						      snprintf(metrics, sizeof(metrics),
						               "valve_open_count=%lu;valve_close_count=%lu;sequence_order_ok=%u",
						               static_cast<unsigned long>(openCount),
						               static_cast<unsigned long>(closeCount),
						               static_cast<unsigned>(sequenceOrderOk ? 1u : 0u));
						      if (!runOne(2004, "valve_actuation_sequence_full", valvePass, metrics)) goto selftest_done;
						    }
						  }

						  {
						    if (!fullProfile || pressureSweepOnly) {
						      if (!runOne(2005,
						                  "print_refuel_pulse_integrity_full",
						                  true,
						                  pressureSweepOnly ? "profile=FULL;executed=0;fixture_required=1;pulses=0;gate=sweep_only" : "profile=SAFE;executed=0;fixture_required=1;pulses=0;gate=safe_only")) {
						        goto selftest_done;
						      }
						    } else if (!fullHomePass) {
						      if (!runOne(2005,
						                  "print_refuel_pulse_integrity_full",
						                  false,
						                  "pulse_count=0;pulse_width_min_ns=0;pulse_width_max_ns=0")) {
						        goto selftest_done;
						      }
						    } else {
						      Printer* printer = Printer::instance();
						      uint32_t pulseCount = 0u;
						      uint32_t pulseWidthMinNs = 0u;
						      uint32_t pulseWidthMaxNs = 0u;
						      bool pulsePass = false;

						      if (printer != nullptr) {
						        const uint32_t printPulseNs = printer->getPrintPulse() * 1000u;
						#if (LC_PRESSURE_PORTS > 1)
						        const uint32_t refuelPulseNs = printer->getRefuelPulse() * 1000u;
						#else
						        const uint32_t refuelPulseNs = printPulseNs;
						#endif
						        pulseWidthMinNs = (printPulseNs < refuelPulseNs) ? printPulseNs : refuelPulseNs;
						        pulseWidthMaxNs = (printPulseNs > refuelPulseNs) ? printPulseNs : refuelPulseNs;

						        printer->pulsePrint();
						        pulseCount++;
						        vTaskDelay(pdMS_TO_TICKS(5));
						#if (LC_PRESSURE_PORTS > 1)
						        printer->pulseRefuel();
						        pulseCount++;
						        vTaskDelay(pdMS_TO_TICKS(5));
						#endif
						        pulsePass = (pulseCount >= 1u) && (pulseWidthMinNs > 0u) && (pulseWidthMaxNs >= pulseWidthMinNs);
						      }

						      char metrics[96];
						      snprintf(metrics, sizeof(metrics),
						               "pulse_count=%lu;pulse_width_min_ns=%lu;pulse_width_max_ns=%lu",
						               static_cast<unsigned long>(pulseCount),
						               static_cast<unsigned long>(pulseWidthMinNs),
						               static_cast<unsigned long>(pulseWidthMaxNs));
						      if (!runOne(2005, "print_refuel_pulse_integrity_full", pulsePass, metrics)) goto selftest_done;
						    }
						  }

						  {
						    if (!fullProfile || pressureSweepOnly) {
						      if (!runOne(2006,
						                  "emergency_abort_and_safe_stop_full",
						                  true,
						                  pressureSweepOnly ? "profile=FULL;executed=0;fixture_required=1;abort=0;gate=sweep_only" : "profile=SAFE;executed=0;fixture_required=1;abort=0;gate=safe_only")) {
						        goto selftest_done;
						      }
						    } else if (!fullHomePass) {
						      if (!runOne(2006,
						                  "emergency_abort_and_safe_stop_full",
						                  false,
						                  "abort_latency_ms=0;motors_disabled=0;regulators_stopped=0;valves_safe_state=0")) {
						        goto selftest_done;
						      }
						    } else {
						      static constexpr uint32_t kAbortMoveSteps = 200u;
						      static constexpr uint32_t kAbortMoveHz = 4000u;
						      static constexpr uint32_t kAbortLatencyLimitMs = 1000u;
						      PressureRegulator::regP().start();
						      Stepper::stepperX()->enableMotor();
						      Stepper::stepperX()->move(true, kAbortMoveSteps, kAbortMoveHz, 0u);
						      const uint32_t abortStartMs = HAL_GetTick();
						      performShutdown(outSeq8, runId, true);
						      const uint32_t abortLatencyMs = HAL_GetTick() - abortStartMs;
						      const bool motorsDisabled = areMotorsDisabled();
						      const bool regulatorsStopped = areRegulatorsStopped();
						      const bool valvesSafeState = areValvesClosed();
						      const bool abortPass = (abortLatencyMs <= kAbortLatencyLimitMs) &&
						                             motorsDisabled &&
						                             regulatorsStopped &&
						                             valvesSafeState;
						      char metrics[96];
						      snprintf(metrics, sizeof(metrics),
						               "abort_latency_ms=%lu;motors_disabled=%u;regulators_stopped=%u;valves_safe_state=%u",
						               static_cast<unsigned long>(abortLatencyMs),
						               static_cast<unsigned>(motorsDisabled ? 1u : 0u),
						               static_cast<unsigned>(regulatorsStopped ? 1u : 0u),
						               static_cast<unsigned>(valvesSafeState ? 1u : 0u));
						      if (!runOne(2006, "emergency_abort_and_safe_stop_full", abortPass, metrics)) goto selftest_done;
						    }
						  }

                          {
                          struct SweepParamSet {
                            uint8_t paramId;
                            PressureRegulator::RecoveryConfig printRecovery;
                            PressureRegulator::SlewConfig printSlew;
                            PressureRegulator::RecoveryConfig refuelRecovery;
                            PressureRegulator::SlewConfig refuelSlew;
                          };

                          struct SweepScenario {
                            uint8_t scenarioId;
                            uint8_t channel;
                            uint16_t targetRaw;
                            uint16_t secondaryTargetRaw;
                            uint16_t pulseUs;
                            uint16_t secondaryPulseUs;
                            uint16_t droplets;
                            uint16_t hz;
                            PulseMode mode;
                            bool requireBothReady;
                            uint8_t modeCode;
                          };

                          auto computeSweepScore = [&](const PressureTraceCaseMetrics& m) -> uint32_t {
                            return (1000u * m.readyMissCount) +
                                   (4u * m.maxDeadlineSlipMs) +
                                   (2u * m.worstRecoveryMs) +
                                   m.maxOvershoot +
                                   m.maxUndershoot +
                                   m.zeroCrossCount;
                          };

                          auto shouldExportSweepTrace = [&](const PressureTraceCaseMetrics& m) -> bool {
                            return (m.readyMissCount > 0u) ||
                                   (m.maxDeadlineSlipMs > 120u) ||
                                   (m.maxOvershoot > 20u) ||
                                   (m.maxUndershoot > 40u);
                          };

                          auto runPressureSweepSuite = [&](uint16_t suiteId) -> bool {
                            const bool isCoreSuite = (suiteId == 2301u);
                            const bool isExtendedSuite = (suiteId == 2302u);
                            const bool isFocusedSuite = (suiteId == 2303u);
                            const bool isMicroSuite = (suiteId == 2304u);
                            const uint16_t suiteSummaryTestId = isCoreSuite ? 2391u : (isExtendedSuite ? 2491u : (isFocusedSuite ? 2591u : 2691u));
                            const char* suiteSummaryName = isCoreSuite ? "pressure_sweep_summary_s2301"
                                                                       : (isExtendedSuite ? "pressure_sweep_summary_s2302"
                                                                                          : (isFocusedSuite ? "pressure_sweep_summary_s2303"
                                                                                                           : "pressure_sweep_summary_s2304"));
                            if (!fullProfile) {
                              return runOne(suiteSummaryTestId,
                                            suiteSummaryName,
                                            true,
                                            "suite=0;combos=0;pass_combo_count=0;best_param=0;best_score=0;worst_score=0;trace_exported_count=0");
                            }
                            if (!fullHomePass) {
                              return runOne(suiteSummaryTestId,
                                            suiteSummaryName,
                                            false,
                                            "suite=0;combos=0;pass_combo_count=0;best_param=0;best_score=0;worst_score=0;trace_exported_count=0");
                            }

                            PressureRegulator& regP = PressureRegulator::regP();
#if (LC_PRESSURE_PORTS > 1)
                            PressureRegulator& regR = PressureRegulator::regR();
#endif
                            const PressureRegulator::RecoveryConfig baselinePrintRecovery = regP.getRecoveryConfig();
                            const PressureRegulator::SlewConfig baselinePrintSlew = regP.getSlewConfig();
#if (LC_PRESSURE_PORTS > 1)
                            const PressureRegulator::RecoveryConfig baselineRefuelRecovery = regR.getRecoveryConfig();
                            const PressureRegulator::SlewConfig baselineRefuelSlew = regR.getSlewConfig();
#else
                            const PressureRegulator::RecoveryConfig baselineRefuelRecovery = baselinePrintRecovery;
                            const PressureRegulator::SlewConfig baselineRefuelSlew = baselinePrintSlew;
#endif

                            auto applyParamSet = [&](const SweepParamSet& set) {
                              regP.setRecoveryConfig(set.printRecovery);
                              regP.setSlewConfig(set.printSlew);
#if (LC_PRESSURE_PORTS > 1)
                              regR.setRecoveryConfig(set.refuelRecovery);
                              regR.setSlewConfig(set.refuelSlew);
#endif
                            };

                            auto restoreBaseline = [&]() {
                              regP.setRecoveryConfig(baselinePrintRecovery);
                              regP.setSlewConfig(baselinePrintSlew);
#if (LC_PRESSURE_PORTS > 1)
                              regR.setRecoveryConfig(baselineRefuelRecovery);
                              regR.setSlewConfig(baselineRefuelSlew);
#endif
                            };

                            SweepParamSet params[10]{};
                            uint16_t paramCount = 0u;

                            if (!(isFocusedSuite || isMicroSuite)) {
                              params[paramCount++] = SweepParamSet{
                                  0u, baselinePrintRecovery, baselinePrintSlew, baselineRefuelRecovery, baselineRefuelSlew};
                            }

                            auto p2PrintRecovery = baselinePrintRecovery;
                            p2PrintRecovery.activeTicks = 4u;
                            p2PrintRecovery.baseBoostHz = 500u;
                            p2PrintRecovery.maxBoostHz = 2500u;
                            p2PrintRecovery.maxExtendTicks = 2u;
                            p2PrintRecovery.allowExtendWhileUndershoot = true;
                            auto p2PrintSlew = baselinePrintSlew;
                            p2PrintSlew.maxHzDeltaUpPerLoop = 900u;
                            p2PrintSlew.maxHzDeltaDownPerLoop = 900u;
                            p2PrintSlew.recoveryBypassSlewTicks = 1u;
                            if (!(isFocusedSuite || isMicroSuite)) {
                              params[paramCount++] = SweepParamSet{
                                  2u, p2PrintRecovery, p2PrintSlew, baselineRefuelRecovery, baselineRefuelSlew};
                            }

                            if (isExtendedSuite || isFocusedSuite || isMicroSuite) {
                              auto p1PrintRecovery = baselinePrintRecovery;
                              p1PrintRecovery.activeTicks = 2u;
                              p1PrintRecovery.baseBoostHz = 250u;
                              p1PrintRecovery.pulseCoeffHzPerUs = 1u;
                              p1PrintRecovery.maxBoostHz = 1200u;
                              p1PrintRecovery.maxExtendTicks = 0u;
                              p1PrintRecovery.allowExtendWhileUndershoot = false;
                              auto p1PrintSlew = baselinePrintSlew;
                              p1PrintSlew.maxHzDeltaUpPerLoop = 500u;
                              p1PrintSlew.maxHzDeltaDownPerLoop = 1100u;
                              p1PrintSlew.recoveryBypassSlewTicks = 0u;
                              params[paramCount++] = SweepParamSet{
                                  1u, p1PrintRecovery, p1PrintSlew, baselineRefuelRecovery, baselineRefuelSlew};

                              if (isExtendedSuite) {
                                auto p3PrintRecovery = baselinePrintRecovery;
                                p3PrintRecovery.activeTicks = 0u;
                                p3PrintRecovery.baseBoostHz = 0u;
                                p3PrintRecovery.pulseCoeffHzPerUs = 0u;
                                p3PrintRecovery.pressureCoeffHzPerRaw = 0u;
                                p3PrintRecovery.maxBoostHz = 0u;
                                auto p3PrintSlew = baselinePrintSlew;
                                params[paramCount++] = SweepParamSet{
                                    3u, p3PrintRecovery, p3PrintSlew, baselineRefuelRecovery, baselineRefuelSlew};

                                // Promote micro-sweep winner (param 11) into full 2302 coverage.
                                auto p11PrintRecovery = baselinePrintRecovery;
                                p11PrintRecovery.activeTicks = 2u;
                                p11PrintRecovery.baseBoostHz = 350u;
                                p11PrintRecovery.maxBoostHz = 1700u;
                                auto p11RefuelRecovery = baselineRefuelRecovery;
                                p11RefuelRecovery.activeTicks = 6u;
                                p11RefuelRecovery.baseBoostHz = baselineRefuelRecovery.baseBoostHz + 350u;
                                p11RefuelRecovery.maxBoostHz = baselineRefuelRecovery.maxBoostHz + 900u;
                                p11RefuelRecovery.maxExtendTicks = 1u;
                                auto p11PrintSlew = baselinePrintSlew;
                                p11PrintSlew.maxHzDeltaUpPerLoop = 650u;
                                p11PrintSlew.maxHzDeltaDownPerLoop = 950u;
                                auto p11RefuelSlew = baselineRefuelSlew;
                                p11RefuelSlew.maxHzDeltaUpPerLoop = baselineRefuelSlew.maxHzDeltaUpPerLoop + 300u;
                                p11RefuelSlew.maxHzDeltaDownPerLoop = baselineRefuelSlew.maxHzDeltaDownPerLoop + 200u;
                                params[paramCount++] = SweepParamSet{
                                    11u, p11PrintRecovery, p11PrintSlew, p11RefuelRecovery, p11RefuelSlew};
                              }

                              auto p5PrintRecovery = baselinePrintRecovery;
                              p5PrintRecovery.activeTicks = 2u;
                              p5PrintRecovery.baseBoostHz = 350u;
                              p5PrintRecovery.maxBoostHz = 1700u;
                              auto p5RefuelRecovery = baselineRefuelRecovery;
                              p5RefuelRecovery.activeTicks = 6u;
                              p5RefuelRecovery.baseBoostHz = baselineRefuelRecovery.baseBoostHz;
                              p5RefuelRecovery.maxBoostHz = baselineRefuelRecovery.maxBoostHz;
                              p5RefuelRecovery.maxExtendTicks = 1u;
                              auto p5PrintSlew = baselinePrintSlew;
                              p5PrintSlew.maxHzDeltaUpPerLoop = 650u;
                              p5PrintSlew.maxHzDeltaDownPerLoop = 950u;
                              auto p5RefuelSlew = baselineRefuelSlew;
                              p5RefuelSlew.maxHzDeltaUpPerLoop = baselineRefuelSlew.maxHzDeltaUpPerLoop;
                              p5RefuelSlew.maxHzDeltaDownPerLoop = baselineRefuelSlew.maxHzDeltaDownPerLoop + 200u;
                              params[paramCount++] = SweepParamSet{
                                  5u, p5PrintRecovery, p5PrintSlew, p5RefuelRecovery, p5RefuelSlew};

                              if (isFocusedSuite) {
                                // Focused variants around the best-performing param 1 for scenarios 2/6/8.
                                auto p6PrintRecovery = p1PrintRecovery;
                                auto p6PrintSlew = p1PrintSlew;
                                auto p6RefuelRecovery = baselineRefuelRecovery;
                                p6RefuelRecovery.activeTicks = baselineRefuelRecovery.activeTicks + 2u;
                                p6RefuelRecovery.baseBoostHz = baselineRefuelRecovery.baseBoostHz + 600u;
                                p6RefuelRecovery.maxBoostHz = baselineRefuelRecovery.maxBoostHz + 1500u;
                                p6RefuelRecovery.maxExtendTicks = baselineRefuelRecovery.maxExtendTicks + 1u;
                                auto p6RefuelSlew = baselineRefuelSlew;
                                p6RefuelSlew.maxHzDeltaUpPerLoop = baselineRefuelSlew.maxHzDeltaUpPerLoop + 500u;
                                p6RefuelSlew.maxHzDeltaDownPerLoop = baselineRefuelSlew.maxHzDeltaDownPerLoop;
                                params[paramCount++] = SweepParamSet{
                                    6u, p6PrintRecovery, p6PrintSlew, p6RefuelRecovery, p6RefuelSlew};

                                auto p7PrintRecovery = p1PrintRecovery;
                                p7PrintRecovery.activeTicks = 3u;
                                p7PrintRecovery.baseBoostHz = 350u;
                                p7PrintRecovery.maxBoostHz = 1600u;
                                auto p7PrintSlew = p1PrintSlew;
                                p7PrintSlew.maxHzDeltaUpPerLoop = 700u;
                                p7PrintSlew.maxHzDeltaDownPerLoop = 900u;
                                auto p7RefuelRecovery = p6RefuelRecovery;
                                p7RefuelRecovery.activeTicks = p6RefuelRecovery.activeTicks + 1u;
                                p7RefuelRecovery.baseBoostHz = p6RefuelRecovery.baseBoostHz + 300u;
                                p7RefuelRecovery.maxBoostHz = p6RefuelRecovery.maxBoostHz + 1000u;
                                auto p7RefuelSlew = p6RefuelSlew;
                                p7RefuelSlew.maxHzDeltaUpPerLoop = p6RefuelSlew.maxHzDeltaUpPerLoop + 300u;
                                params[paramCount++] = SweepParamSet{
                                    7u, p7PrintRecovery, p7PrintSlew, p7RefuelRecovery, p7RefuelSlew};
                              }

                              if (isMicroSuite) {
                                // Micro-variants around p1/p5 with small refuel-only deltas.
                                auto p8PrintRecovery = p1PrintRecovery;
                                auto p8PrintSlew = p1PrintSlew;
                                auto p8RefuelRecovery = baselineRefuelRecovery;
                                p8RefuelRecovery.baseBoostHz = baselineRefuelRecovery.baseBoostHz + 250u;
                                p8RefuelRecovery.maxBoostHz = baselineRefuelRecovery.maxBoostHz + 600u;
                                auto p8RefuelSlew = baselineRefuelSlew;
                                p8RefuelSlew.maxHzDeltaUpPerLoop = baselineRefuelSlew.maxHzDeltaUpPerLoop + 200u;
                                params[paramCount++] = SweepParamSet{
                                    8u, p8PrintRecovery, p8PrintSlew, p8RefuelRecovery, p8RefuelSlew};

                                auto p9PrintRecovery = p1PrintRecovery;
                                auto p9PrintSlew = p1PrintSlew;
                                auto p9RefuelRecovery = baselineRefuelRecovery;
                                p9RefuelRecovery.baseBoostHz = baselineRefuelRecovery.baseBoostHz + 450u;
                                p9RefuelRecovery.maxBoostHz = baselineRefuelRecovery.maxBoostHz + 1000u;
                                auto p9RefuelSlew = baselineRefuelSlew;
                                p9RefuelSlew.maxHzDeltaUpPerLoop = baselineRefuelSlew.maxHzDeltaUpPerLoop + 350u;
                                params[paramCount++] = SweepParamSet{
                                    9u, p9PrintRecovery, p9PrintSlew, p9RefuelRecovery, p9RefuelSlew};

                                auto p10PrintRecovery = p5PrintRecovery;
                                auto p10PrintSlew = p5PrintSlew;
                                auto p10RefuelRecovery = p5RefuelRecovery;
                                p10RefuelRecovery.baseBoostHz = p5RefuelRecovery.baseBoostHz + 200u;
                                p10RefuelRecovery.maxBoostHz = p5RefuelRecovery.maxBoostHz + 500u;
                                auto p10RefuelSlew = p5RefuelSlew;
                                p10RefuelSlew.maxHzDeltaUpPerLoop = p5RefuelSlew.maxHzDeltaUpPerLoop + 150u;
                                params[paramCount++] = SweepParamSet{
                                    10u, p10PrintRecovery, p10PrintSlew, p10RefuelRecovery, p10RefuelSlew};

                                auto p11PrintRecovery = p5PrintRecovery;
                                auto p11PrintSlew = p5PrintSlew;
                                auto p11RefuelRecovery = p5RefuelRecovery;
                                p11RefuelRecovery.baseBoostHz = p5RefuelRecovery.baseBoostHz + 350u;
                                p11RefuelRecovery.maxBoostHz = p5RefuelRecovery.maxBoostHz + 900u;
                                auto p11RefuelSlew = p5RefuelSlew;
                                p11RefuelSlew.maxHzDeltaUpPerLoop = p5RefuelSlew.maxHzDeltaUpPerLoop + 300u;
                                params[paramCount++] = SweepParamSet{
                                    11u, p11PrintRecovery, p11PrintSlew, p11RefuelRecovery, p11RefuelSlew};
                              }
                            }

                            SweepScenario scenarios[8]{};
                            uint16_t scenarioCount = 0u;
                            if (isExtendedSuite) {
                              scenarios[scenarioCount++] = SweepScenario{2u, 0u, psiToRaw(1000u), 0u, 1300u, 0u, 10u, 20u, PulseMode::PRINT_ONLY, false, 0u};
                              scenarios[scenarioCount++] = SweepScenario{3u, 0u, psiToRaw(1200u), 0u, 1800u, 0u, 10u, 20u, PulseMode::PRINT_ONLY, false, 0u};
                              scenarios[scenarioCount++] = SweepScenario{4u, 1u, psiToRaw(500u), 0u, 3000u, 0u, 10u, 20u, PulseMode::REFUEL_ONLY, false, 1u};
                              scenarios[scenarioCount++] = SweepScenario{6u, 0u, psiToRaw(1000u), psiToRaw(500u), 1300u, 3000u, 10u, 20u, PulseMode::BOTH, true, 2u};
                              scenarios[scenarioCount++] = SweepScenario{1u, 0u, psiToRaw(600u), 0u, 1300u, 0u, 10u, 20u, PulseMode::PRINT_ONLY, false, 0u};
                              scenarios[scenarioCount++] = SweepScenario{5u, 1u, psiToRaw(600u), 0u, 3000u, 0u, 10u, 20u, PulseMode::REFUEL_ONLY, false, 1u};
                              scenarios[scenarioCount++] = SweepScenario{7u, 0u, psiToRaw(800u), 0u, 1500u, 0u, 12u, 25u, PulseMode::PRINT_ONLY, false, 0u};
                              scenarios[scenarioCount++] = SweepScenario{8u, 1u, psiToRaw(450u), 0u, 3200u, 0u, 12u, 25u, PulseMode::REFUEL_ONLY, false, 1u};
                            } else if (isFocusedSuite || isMicroSuite) {
                              // Focused high-value scenarios: print guard, dual coupling, and refuel high-slip.
                              scenarios[scenarioCount++] = SweepScenario{2u, 0u, psiToRaw(1000u), 0u, 1300u, 0u, 10u, 20u, PulseMode::PRINT_ONLY, false, 0u};
                              scenarios[scenarioCount++] = SweepScenario{6u, 0u, psiToRaw(1000u), psiToRaw(500u), 1300u, 3000u, 10u, 20u, PulseMode::BOTH, true, 2u};
                              scenarios[scenarioCount++] = SweepScenario{8u, 1u, psiToRaw(450u), 0u, 3200u, 0u, 12u, 25u, PulseMode::REFUEL_ONLY, false, 1u};
                            } else {
                              // 120s rapid suite: one high-stress print case, compare params directly.
                              scenarios[scenarioCount++] = SweepScenario{3u, 0u, psiToRaw(1200u), 0u, 1800u, 0u, 10u, 20u, PulseMode::PRINT_ONLY, false, 0u};
                            }

                            const uint16_t comboBaseTestId = isCoreSuite ? 2310u : (isExtendedSuite ? 2410u : (isFocusedSuite ? 2510u : 2610u));
                            uint16_t comboIndex = 0u;
                            uint16_t passComboCount = 0u;
                            uint16_t traceExportedCount = 0u;
                            // Extended 2302 is metrics-first under tight runtime budgets; raw trace export
                            // is disabled here to avoid transport instability during large chunk bursts.
                            const uint16_t traceExportBudget = isExtendedSuite ? 0u : ((isFocusedSuite || isMicroSuite) ? 3u : 0xFFFFu);
                            const uint32_t comboSoftTimeoutMs = isExtendedSuite ? 16000u : ((isFocusedSuite || isMicroSuite) ? 14000u : 12000u);
                            const uint32_t suiteBudgetMs = isExtendedSuite ? 110000u : 0u;
                            const uint32_t suiteStartMs = HAL_GetTick();
                            bool suiteTimedOut = false;
                            uint32_t bestScore = 0xFFFFFFFFu;
                            uint32_t worstScore = 0u;
                            uint8_t bestParam = 0u;

                            for (uint16_t p = 0u; p < paramCount; ++p) {
                              char paramStage[32];
                              snprintf(paramStage, sizeof(paramStage), "sw_param_p%u",
                                       static_cast<unsigned>(params[p].paramId));
                              sendProgressStage(paramStage);
                              applyParamSet(params[p]);
                              for (uint16_t s = 0u; s < scenarioCount; ++s) {
                                if ((suiteBudgetMs > 0u) && ((HAL_GetTick() - suiteStartMs) >= suiteBudgetMs)) {
                                  suiteTimedOut = true;
                                  sendProgressStage("sw_suite_budget_to");
                                  break;
                                }
                                maybeSendProgress("sweep_combo");
                                PressureTraceCaseMetrics caseMetrics{};
                                const uint16_t comboTestId = static_cast<uint16_t>(comboBaseTestId + comboIndex);
                                char comboName[40];
                                snprintf(comboName, sizeof(comboName), "pressure_sweep_s%u_p%u_c%u",
                                         static_cast<unsigned>(suiteId),
                                         static_cast<unsigned>(params[p].paramId),
                                         static_cast<unsigned>(scenarios[s].scenarioId));
                                char comboStage[32];
                                snprintf(comboStage, sizeof(comboStage), "sw_cstart_p%u_c%u",
                                         static_cast<unsigned>(params[p].paramId),
                                         static_cast<unsigned>(scenarios[s].scenarioId));
                                sendProgressStage(comboStage);
                                const uint32_t comboStartMs = HAL_GetTick();
                                const bool executed = runPressureTraceCase(comboTestId,
                                                                           comboName,
                                                                           scenarios[s].channel,
                                                                           scenarios[s].targetRaw,
                                                                           scenarios[s].pulseUs,
                                                                           scenarios[s].droplets,
                                                                           scenarios[s].hz,
                                                                           scenarios[s].mode,
                                                                           scenarios[s].requireBothReady,
                                                                           scenarios[s].secondaryTargetRaw,
                                                                           scenarios[s].secondaryPulseUs,
                                                                           &caseMetrics,
                                                                           false,
                                                                           false);
                                if (!executed) {
                                  sendProgressStage("sw_combo_exec_fail");
                                  restoreBaseline();
                                  return false;
                                }
                                const uint32_t comboElapsedMs = HAL_GetTick() - comboStartMs;
                                const bool comboTimedOut = comboElapsedMs > comboSoftTimeoutMs;
                                if (comboTimedOut) {
                                  sendProgressStage("sw_combo_soft_to");
                                }

                                const bool comboPass = caseMetrics.pass && !comboTimedOut;
                                if (comboPass) {
                                  passComboCount++;
                                }
                                const uint32_t score = computeSweepScore(caseMetrics);
                                if (score < bestScore) {
                                  bestScore = score;
                                  bestParam = params[p].paramId;
                                }
                                if (score > worstScore) {
                                  worstScore = score;
                                }
                                const bool exportThisTrace = exportPressureTrace &&
                                                             (traceExportedCount < traceExportBudget) &&
                                                             shouldExportSweepTrace(caseMetrics);
                                if (exportThisTrace) {
                                  traceExportedCount++;
                                }

                                char metrics[240];
                                snprintf(metrics, sizeof(metrics),
                                         "suite=%u;param=%u;scenario=%u;mode=%u;under=%lu;over=%lu;rec_w=%lu;rec_m=%lu;ready_miss=%lu;slip_w=%lu;slip_m=%lu;zero=%lu;rejects=%lu;sc=%lu;ec=%lu;trace=%u;score=%lu;combo_ms=%lu;combo_to=%u",
                                         static_cast<unsigned>(suiteId),
                                         static_cast<unsigned>(params[p].paramId),
                                         static_cast<unsigned>(scenarios[s].scenarioId),
                                         static_cast<unsigned>(scenarios[s].modeCode),
                                         static_cast<unsigned long>(caseMetrics.maxUndershoot),
                                         static_cast<unsigned long>(caseMetrics.maxOvershoot),
                                         static_cast<unsigned long>(caseMetrics.worstRecoveryMs),
                                         static_cast<unsigned long>(caseMetrics.meanRecoveryMs),
                                         static_cast<unsigned long>(caseMetrics.readyMissCount),
                                         static_cast<unsigned long>(caseMetrics.maxDeadlineSlipMs),
                                         static_cast<unsigned long>(caseMetrics.meanDeadlineSlipMs),
                                         static_cast<unsigned long>(caseMetrics.zeroCrossCount),
                                         static_cast<unsigned long>(caseMetrics.sampleRejectCount),
                                         static_cast<unsigned long>(caseMetrics.traceSampleCount),
                                         static_cast<unsigned long>(caseMetrics.traceEventCount),
                                         static_cast<unsigned>(exportThisTrace ? 1u : 0u),
                                         static_cast<unsigned long>(score),
                                         static_cast<unsigned long>(comboElapsedMs),
                                         static_cast<unsigned>(comboTimedOut ? 1u : 0u));
                                sendProgressStage("sw_combo_emit");
                                if (!runOne(comboTestId, comboName, comboPass, metrics)) {
                                  restoreBaseline();
                                  return false;
                                }
                                sendProgressStage("sw_combo_emit_ok");
                                if (!maybeExportTrace(exportThisTrace, comboTestId, comboName, comboPass)) {
                                  sendProgressStage("trace_export_fail");
                                } else if (exportThisTrace) {
                                  sendProgressStage("sw_combo_export_ok");
                                }
                                comboIndex++;
                              }
                              if (suiteTimedOut) {
                                break;
                              }
                            }

                            restoreBaseline();
                            if (bestScore == 0xFFFFFFFFu) {
                              bestScore = 0u;
                              bestParam = 0u;
                            }
                            const uint16_t combosPlanned = static_cast<uint16_t>(paramCount * scenarioCount);
                            const uint16_t combosRun = comboIndex;
                            char summaryMetrics[192];
                            snprintf(summaryMetrics, sizeof(summaryMetrics),
                                     "suite=%u;combos=%u;combos_run=%u;pass_combo_count=%u;best_param=%u;best_score=%lu;worst_score=%lu;trace_exported_count=%u;suite_timeout=%u",
                                     static_cast<unsigned>(suiteId),
                                     static_cast<unsigned>(combosPlanned),
                                     static_cast<unsigned>(combosRun),
                                     static_cast<unsigned>(passComboCount),
                                     static_cast<unsigned>(bestParam),
                                     static_cast<unsigned long>(bestScore),
                                     static_cast<unsigned long>(worstScore),
                                     static_cast<unsigned>(traceExportedCount),
                                     static_cast<unsigned>(suiteTimedOut ? 1u : 0u));
                            return runOne(suiteSummaryTestId,
                                          suiteSummaryName,
                                          (!suiteTimedOut) && (passComboCount == combosPlanned),
                                          summaryMetrics);
                          };

                          if (runPressureSweepCore) {
                            if (!runPressureSweepSuite(2301u)) goto selftest_done;
                          }
                          if (runPressureSweepExtended) {
                            if (!runPressureSweepSuite(2302u)) goto selftest_done;
                          }
                          if (runPressureSweepFocused) {
                            if (!runPressureSweepSuite(2303u)) goto selftest_done;
                          }
                          if (runPressureSweepMicro) {
                            if (!runPressureSweepSuite(2304u)) goto selftest_done;
                          }

                          if (runCustomPressureTraceSelection) {
                            const PressureTraceCustomConfig& custom = request.customPressureTrace;
                            const char* invalid = nullptr;
                            if (!custom.enabled ||
                                !custom.hasChannel ||
                                !custom.hasPressureMilliPsi ||
                                !custom.hasPulseUs ||
                                !custom.hasPulseCount ||
                                !custom.hasFrequencyHz) {
                              invalid = "missing_config";
                            } else if (custom.channel > 1u) {
                              invalid = "channel";
#if (LC_PRESSURE_PORTS <= 1)
                            } else if (custom.channel == 1u) {
                              invalid = "refuel_unavailable";
#endif
                            } else if ((custom.pressureMilliPsi < kTracePressureMilliPsiMin) ||
                                       (custom.pressureMilliPsi > kTracePressureMilliPsiMax)) {
                              invalid = "pressure";
                            } else if ((custom.pulseUs < kTracePulseUsMin) ||
                                       (custom.pulseUs > kTracePulseUsMax)) {
                              invalid = "pulse_us";
                            } else if ((custom.pulseCount < kTracePulseCountMin) ||
                                       (custom.pulseCount > kTracePulseCountMax)) {
                              invalid = "pulse_count";
                            } else if ((custom.frequencyHz < kTraceFrequencyHzMin) ||
                                       (custom.frequencyHz > kTraceFrequencyHzMax)) {
                              invalid = "frequency";
                            } else if (static_cast<uint32_t>(custom.pulseUs) >=
                                       (1000000u / static_cast<uint32_t>(custom.frequencyHz))) {
                              invalid = "pulse_period";
                            } else if (((static_cast<uint32_t>(custom.pulseCount) * 1000u) +
                                        static_cast<uint32_t>(custom.frequencyHz) - 1u) /
                                       static_cast<uint32_t>(custom.frequencyHz) > kTraceMaxPulseWindowMs) {
                              invalid = "duration";
                            }

                            if (invalid != nullptr) {
                              char metrics[160];
                              snprintf(metrics,
                                       sizeof(metrics),
                                       "custom=1;executed=0;invalid=%s;ch=%u;pressure_mpsi=%u;pulse_us=%u;pulses=%u;hz=%u",
                                       invalid,
                                       static_cast<unsigned>(custom.channel),
                                       static_cast<unsigned>(custom.pressureMilliPsi),
                                       static_cast<unsigned>(custom.pulseUs),
                                       static_cast<unsigned>(custom.pulseCount),
                                       static_cast<unsigned>(custom.frequencyHz));
                              if (!runOne(kPressureTraceCustomTestId,
                                          "pressure_recovery_trace_custom",
                                          false,
                                          metrics)) goto selftest_done;
                            } else {
                              if (!runPressureTraceCase(kPressureTraceCustomTestId,
                                                        "pressure_recovery_trace_custom",
                                                        custom.channel,
                                                        psiToRaw(custom.pressureMilliPsi),
                                                        custom.pulseUs,
                                                        custom.pulseCount,
                                                        custom.frequencyHz,
                                                        (custom.channel == 0u) ? PulseMode::PRINT_ONLY : PulseMode::REFUEL_ONLY,
                                                        false,
                                                        0u,
                                                        0u,
                                                        nullptr,
                                                        true,
                                                        exportPressureTrace)) goto selftest_done;
                            }
                          }

                          if (shouldRunPressureTraceCase(2101)) {
                            if (!runPressureTraceCase(2101,
                                                      "pressure_recovery_trace_print_single",
                                                      0u,
                                                      psiToRaw(1000u),
                                                      1300u,
                                                      1u,
                                                      20u,
                                                      PulseMode::PRINT_ONLY,
                                                      false,
                                                      0u,
                                                      0u,
                                                      nullptr,
                                                      true,
                                                      exportPressureTrace)) goto selftest_done;
                          }

                          if (shouldRunPressureTraceCase(2102)) {
                            if (!runPressureTraceCase(2102,
                                                      "pressure_recovery_trace_print_repeated",
                                                      0u,
                                                      psiToRaw(1000u),
                                                      1300u,
                                                      10u,
                                                      20u,
                                                      PulseMode::PRINT_ONLY,
                                                      false,
                                                      0u,
                                                      0u,
                                                      nullptr,
                                                      true,
                                                      exportPressureTrace)) goto selftest_done;
                          }

#if (LC_PRESSURE_PORTS > 1)
                          if (shouldRunPressureTraceCase(2103)) {
                            if (!runPressureTraceCase(2103,
                                                      "pressure_recovery_trace_refuel_repeated",
                                                      1u,
                                                      psiToRaw(500u),
                                                      3000u,
                                                      10u,
                                                      20u,
                                                      PulseMode::REFUEL_ONLY,
                                                      false,
                                                      0u,
                                                      0u,
                                                      nullptr,
                                                      true,
                                                      exportPressureTrace)) goto selftest_done;
                          }

                          if (shouldRunPressureTraceCase(2104)) {
                            if (!runPressureTraceCase(2104,
                                                      "pressure_recovery_trace_dual_interleaved",
                                                      0u,
                                                      psiToRaw(1000u),
                                                      1300u,
                                                      10u,
                                                      20u,
                                                      PulseMode::BOTH,
                                                      true,
                                                      psiToRaw(500u),
                                                      3000u,
                                                      nullptr,
                                                      true,
                                                      exportPressureTrace)) goto selftest_done;
                          }
#else
                          if (!runOne(2103,
                                      "pressure_recovery_trace_refuel_repeated",
                                      false,
                                      "baseline_pressure_raw=0;min_pressure_raw=0;max_pressure_raw=0;max_undershoot_raw=0;max_overshoot_raw=0;worst_recovery_ms=0;mean_recovery_ms=0;ready_miss_count=1;max_deadline_slip_ms=0;mean_deadline_slip_ms=0;zero_cross_count=0;sample_reject_count=0")) goto selftest_done;
                          if (!runOne(2104,
                                      "pressure_recovery_trace_dual_interleaved",
                                      false,
                                      "baseline_pressure_raw=0;min_pressure_raw=0;max_pressure_raw=0;max_undershoot_raw=0;max_overshoot_raw=0;worst_recovery_ms=0;mean_recovery_ms=0;ready_miss_count=1;max_deadline_slip_ms=0;mean_deadline_slip_ms=0;zero_cross_count=0;sample_reject_count=0")) goto selftest_done;
#endif
                          }
			

                              selftest_done:
    if (!request.fullProfile &&
        (selectedDiagnosticId == 0u ||
         runSelfTestSchedulerNoYieldSuite ||
         runSelfTestSchedulerCooperativeSuite)) {
      CrashLogSnapshot crashSnapshot{};
      CrashLog_GetSnapshot(&crashSnapshot);
      const bool pressureContextExpected =
          ((crashSnapshot.flags & CRASHLOG_FLAG_PENDING) != 0u) &&
          (crashSnapshot.lastFault == CRASH_FAULT_WDT_STARVE) &&
          (crashSnapshot.watchdogLateTask == CRASH_TASK_PRESSURE) &&
          (crashSnapshot.resetCause != CRASH_RESET_POWER) &&
          (crashSnapshot.resetCause != CRASH_RESET_LOW_POWER);
      char contextMetrics[208];
      const bool contextPass = BuildPressureSensorWatchdogContextResult(
          pressureContextExpected,
          crashSnapshot.pressureSensorContextValid != 0u,
          crashSnapshot.pressureSensorContext,
          contextMetrics,
          sizeof(contextMetrics));
      ++total;
      if (contextPass) ++passed; else ++failed;
      sendResult(1044u, "pressure_wdg_context_safe", contextPass, contextMetrics);

      PressureSensorWatchdogSnapshot pressureSnapshot{};
      pressureSnapshot.phaseAgeMs = PRESSURE_SENSOR_WDG_AGE_UNKNOWN;
      pressureSnapshot.lastLoopAgeMs = PRESSURE_SENSOR_WDG_AGE_UNKNOWN;
      pressureSnapshot.stackHighWaterWords = PRESSURE_SENSOR_WDG_AGE_UNKNOWN;
      (void)PressureSensorWatchdog_GetSnapshot(&pressureSnapshot);
      uint32_t pressureWatchdogAgeMs = PRESSURE_SENSOR_WDG_AGE_UNKNOWN;
      (void)Watchdog_GetTaskLastSeenAgeMs(CRASH_TASK_PRESSURE, &pressureWatchdogAgeMs);
      char schedulerMetrics[208];
      const bool schedulerPass = BuildSelfTestSchedulerResult(
          schedulingState,
          pressureSnapshot,
          pressureWatchdogAgeMs,
          schedulerMetrics,
          sizeof(schedulerMetrics));
      ++total;
      if (schedulerPass) ++passed; else ++failed;
      sendResult(1043u, "selftest_scheduler_safe", schedulerPass, schedulerMetrics);
    }
    comm->setStatusPaused(true);
    uint8_t donePayload[64] = {0};
    const size_t doneLen = DiagnosticResultEmitter::buildDonePayload(
        donePayload,
        sizeof(donePayload),
        outSeq8,
        runId,
        total,
        passed,
        failed,
        aborted,
        HAL_GetTick());
    comm->sendFrame(comm->handle(), donePayload, doneLen);
    _selfTestAbortRequested = false;
    summary.total = total;
    summary.passed = passed;
    summary.failed = failed;
    summary.aborted = aborted;
    return summary;
}

#if defined(__GNUC__)
#pragma GCC pop_options
#endif
