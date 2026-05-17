#include "BoardConfig.h"
#include "Diagnostics.h"
#include "DiagnosticResultEmitter.h"
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
#include "PressureRegulatorMath.h"
#include "PressureQualificationMath.h"
#include "GripperSealQualificationMath.h"
#include "PressureTargetPolicy.h"
#include "ValvePulseQualificationMath.h"
#include "PressureSensor.h"
#include "Logger.h"
#include "Gantry.h"
#include "Comm.h"
#include "CommCodec.h"
#include "CrashLog.h"
#include "CrashLogCodec.h"
#include "WatchdogSupervisor.h"
#include "PressureTraceRecorder.h"
#include "cmsis_os.h"
#include "task.h"

#include <cstdio>
#include <cstring>

#if LC_HAS_IMAGING > 0
  #include "Flash.h"
  #include "Flash.hpp"
#endif

#if LC_HAS_LED_STRIP > 0
  #include "LEDStrip.h"
#endif

extern "C" uint32_t RTOS_StackOverflowHookFired(void);

namespace {

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
    {2004u, "valve_actuation_sequence_full", "pressure", "FULL", "safe_gate_or_full"},
    {2005u, "print_refuel_pulse_integrity_full", "pulse", "FULL", "safe_gate_or_full"},
    {2401u, "print_valve_pulse_drop_repeatability_factory", "pulse", "FULL", "safe_gate_or_full"},
    {2402u, "refuel_valve_pulse_drop_repeatability_factory", "pulse", "FULL", "safe_gate_or_full"},
    {2403u, "dual_valve_interaction_factory", "pulse", "FULL", "safe_gate_or_full"},
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
    {2006u, "emergency_abort_and_safe_stop_full", "safety", "FULL", "safe_gate_or_full"},
    {2101u, "pressure_recovery_trace_print_single", "pressure_trace", "FULL", "explicit_flag"},
    {2102u, "pressure_recovery_trace_print_repeated", "pressure_trace", "FULL", "explicit_flag"},
    {2103u, "pressure_recovery_trace_refuel_repeated", "pressure_trace", "FULL", "explicit_flag"},
    {2104u, "pressure_recovery_trace_dual_interleaved", "pressure_trace", "FULL", "explicit_flag"},
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
    const bool runXyMotionSuite = (selectedDiagnosticId == 2009u);
    const bool runMotionEnvelopeSuite = (selectedDiagnosticId == 2019u);
    const bool runPressureRegulatorSuite = (selectedDiagnosticId == 2299u);
    const bool runValveCharacterizationSuite = (selectedDiagnosticId == 2499u);
    const bool runValveGapSweepSuite = (selectedDiagnosticId == 2498u);
    const bool runPressureSweepCore = (selectedPressureTraceTest == 2301u);
    const bool runPressureSweepExtended = (selectedPressureTraceTest == 2302u);
    const bool runPressureSweepFocused = (selectedPressureTraceTest == 2303u);
    const bool runPressureSweepMicro = (selectedPressureTraceTest == 2304u);
    const bool runPressureDiagnosticsByFlag = request.runPressureDiagnostics;
    const bool runSinglePressureTraceSelection =
        (selectedPressureTraceTest >= 2101u) && (selectedPressureTraceTest <= 2104u);
                  auto shouldRunPressureTraceCase = [&](uint16_t testId) {
                    if (runPressureSweepCore || runPressureSweepExtended || runPressureSweepFocused || runPressureSweepMicro || runGripperSealSuite || runXyMotionSuite || runMotionEnvelopeSuite || runPressureRegulatorSuite || runValveCharacterizationSuite || runValveGapSweepSuite) {
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
                    comm->sendFrame(comm->handle(), payload, payloadLen);
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
                      vTaskDelay(1);
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
                      vTaskDelay(1);
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

                          auto moveGantryToWithTimeout = [&](int32_t x,
                                                            int32_t y,
                                                            uint32_t feedHz,
                                                            uint32_t timeoutMs) {
                            xEventGroupClearBits(_doneEvents, BIT_STEPPER1_DONE | BIT_STEPPER2_DONE);
                            Gantry::instance()->moveTo(x, y, feedHz);
                            const bool reached = waitBitsWithTimeout(BIT_STEPPER1_DONE | BIT_STEPPER2_DONE, timeoutMs);
                            if (!reached) {
                              Gantry::cancelXYZMotors();
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
                        static constexpr int32_t kSafeZMax = 40000;
                        static constexpr int32_t kCableGuardX = 1000;
                        static constexpr int32_t kCableGuardMinY = 500;
                        static constexpr int32_t kLongXMax = 44000;
                        static constexpr int32_t kLongYMax = 34000;
                        static constexpr int32_t kZLongMax = 39000;
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
                        const MotionQualificationMath::ZSafetyEnvelope zEnvelope{0, kSafeZMax};
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
                                   "phase=%s;rep=0;ref=0;zhz=%lu;zcap=%lu;zacc=%lu;zmax=%ld;dz=0;z_span=0;z_drift=0;z_ret=0;ret_err=0;move_to=0;home_to=1;bound=0",
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
                          const EventBits_t doneBits = xEventGroupGetBits(_doneEvents);
                          const bool axisDone = (doneBits & homeBit) != 0u;
                          const Stepper::HomeDiagnosticSnapshot diag = stepper->getLastHomeDiagnosticSnapshot();
                          sample.success = axisDone && diag.success;
                          sample.limitTriggerSteps = diag.fineLimitPositionSteps;
                          sample.finalBackoffSteps = diag.finalBackoffPositionSteps;
                          sample.moveTimeoutCount = diag.moveTimeoutCount;
                          return done && sample.success;
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
                        plateStats.points = (kPlateRows * kPlateCols) + 2u;
                        bool plateMovesCompleted = true;
                        bool plateBoundViolation = false;
                        bool plateGuardViolation = false;
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
                        if (plateMovesCompleted) {
                          plateMovesCompleted = moveChecked({kPlateEndX, kPlateEndY},
                                                            kPlateFeedHz,
                                                            kPlateMoveTimeoutMs,
                                                            plateStats,
                                                            plateBoundViolation,
                                                            plateGuardViolation);
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
                            MotionQualificationMath::xyMotionStatsPass(plateStats);
                        char metrics2014[224];
                        snprintf(metrics2014, sizeof(metrics2014),
                                 "rep=%lu;ref=2;rows=%lu;cols=%lu;moves=%lu;xmax=%ld;ymax=%ld;dx=%ld;dy=%ld;home_y=%ld;x_span=%lu;y_span=%lu;x_drift=%lu;y_drift=%lu;x_ret=%lu;y_ret=%lu;ret_err=%lu;move_to=%lu;home_to=%lu;guard=%lu;bound=%lu",
                                 static_cast<unsigned long>(plateStats.repetitions),
                                 static_cast<unsigned long>(kPlateRows),
                                 static_cast<unsigned long>(kPlateCols),
                                 static_cast<unsigned long>(plateStats.points),
                                 static_cast<long>(kPlateStartX),
                                 static_cast<long>(kPlateEndY),
                                 static_cast<long>(kPlateStartX - kPlateEndX),
                                 static_cast<long>(kPlateEndY - kPlateStartY),
                                 static_cast<long>(plateHomeAnchor.y),
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
                          (void)emitSkippedMotionEnvelope(2015u, "xy_plate_failed");
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
                          if (!MotionQualificationMath::zPositionInBounds(kZLongMax, zEnvelope)) {
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
                          if (!MotionQualificationMath::zPositionInBounds(Stepper::stepperZ()->getPosition(), zEnvelope)) {
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
                                 "rep=%lu;ref=2;zhz=%lu;zcap=%lu;zacc=%lu;zmax=%ld;dz=%ld;z_span=%lu;z_drift=%lu;z_ret=%lu;ret_err=%lu;move_to=%lu;home_to=%lu;bound=%lu",
                                 static_cast<unsigned long>(zCompleted),
                                 static_cast<unsigned long>(kZFeedHz),
                                 static_cast<unsigned long>(zAxisMaxSpeedHz),
                                 static_cast<unsigned long>(zAxisAccelStepsPerSec2),
                                 static_cast<long>(kZLongMax),
                                 static_cast<long>(kZLongMax - zReference.finalBackoffSteps),
                                 static_cast<unsigned long>(zHomeStats.limitTriggerSpanSteps),
                                 static_cast<unsigned long>(zDriftMax),
                                 static_cast<unsigned long>(zReturnErrorMax),
                                 static_cast<unsigned long>(zReturnError),
                                 static_cast<unsigned long>(zMoveTimeouts + zHomeStats.moveTimeoutCount),
                                 static_cast<unsigned long>(zHomeStats.homeTimeoutCount),
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
                        static constexpr uint16_t kValveCharPulseCount = kValveCharMeasuredPulses;
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
                        static constexpr uint32_t kValveCharBaselineWindowMs = 10u;
                        static constexpr uint32_t kValveCharRingWindowMs = 60u;
                        static constexpr uint32_t kValveCharSettledStartMs = 80u;
                        static constexpr uint32_t kValveCharSettledEndMs = 150u;

                        struct ValveCharRowSummary {
                          uint32_t mean[3] = {0u, 0u, 0u};
                          uint32_t cv[3] = {0u, 0u, 0u};
                          uint32_t span[3] = {0u, 0u, 0u};
                          uint32_t ring[3] = {0u, 0u, 0u};
                          uint32_t latency[3] = {0u, 0u, 0u};
                          uint32_t out = 0u;
                          uint32_t rej = 0u;
                          uint32_t ready = 0u;
                          uint32_t freshTo = 0u;
                          uint32_t sc = 0u;
                          uint32_t ec = 0u;
                          uint32_t timeout = 0u;
                          uint32_t mono = 0u;
                          uint32_t gain = 0u;
                          uint32_t lin = 0u;
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

                        auto finalizeValveRowLinearity = [&](ValveCharRowSummary& row) {
                          const auto lin = ValvePulseQualificationMath::summarizeThreeWidthLinearity(
                              row.mean[0],
                              row.mean[1],
                              row.mean[2]);
                          row.mono = lin.monotonic;
                          row.gain = lin.gainRaw;
                          row.lin = lin.midpointLinearityErrorPct;
                        };

                        auto valveWidthIndex = [&](uint16_t widthUs) -> uint8_t {
                          for (uint8_t i = 0u; i < kValveCharWidthCount; ++i) {
                            if (kValveCharWidthsUs[i] == widthUs) {
                              return i;
                            }
                          }
                          return 0u;
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
                            row.rej = kValveCharPulseCount;
                            row.ready = 1u;
                            row.pass = false;
                            return row;
                          }
#endif
                          Printer* printer = Printer::instance();
                          PressureSensor* sensor = PressureSensor::instance();
                          if (printer == nullptr || sensor == nullptr) {
                            row.rej = kValveCharPulseCount;
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
                            row.rej = kValveCharPulseCount;
                            row.ready = 1u;
                            row.pass = false;
                            return row;
                          }

                          PressureRegulator& reg = regulatorForValveChannel(channel);
                          Stepper* stepper = (channel == 0u) ? Stepper::stepperP() : Stepper::stepperR();
                          const uint32_t originalPrintPulse = printer->getPrintPulse();
                          const uint32_t originalRefuelPulse = printer->getRefuelPulse();

                          uint32_t responses[kValveCharWidthCount][kValveCharReplicates]{};
                          uint32_t rings[kValveCharWidthCount][kValveCharReplicates]{};
                          uint32_t latencies[kValveCharWidthCount][kValveCharReplicates]{};
                          uint32_t responseCount[kValveCharWidthCount]{};
                          uint32_t scheduledCount[kValveCharWidthCount]{};

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
                              row.rej++;
                              return true;
                            }
                            if (!delayWithWatchdog(kValveCharStabilizeMs, "valve_char_stabilize")) {
                              row.timeout++;
                              row.rej++;
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
                                row.rej++;
                              } else if (!freshOk) {
                                row.rej++;
                              }
                              return !timeout;
                            }

                            const auto response = ValvePulseQualificationMath::summarizeWindowedValveCharacterization(
                                recorder.samples(),
                                recorder.sampleCount(),
                                recorder.events(),
                                recorder.eventCount(),
                                kValveCharBaselineWindowMs,
                                kValveCharRingWindowMs,
                                kValveCharSettledStartMs,
                                kValveCharSettledEndMs);
                            const uint8_t widthIndex = valveWidthIndex(pulseWidthUs);
                            char traceName[48];
                            snprintf(traceName,
                                     sizeof(traceName),
                                     "valve_char_%c_w%u_rep%02u",
                                     (channel == 0u) ? 'p' : 'r',
                                     static_cast<unsigned>(pulseWidthUs),
                                     static_cast<unsigned>(replicateForWidth));
                            (void)exportTrace(testId, traceName, !timeout && (response.pulseCount >= 1u));
                            row.rej += response.rejectCount;
                            if (response.pulseCount < 1u) {
                              row.rej++;
                            } else if (responseCount[widthIndex] < kValveCharReplicates) {
                              const uint32_t idx = responseCount[widthIndex]++;
                              responses[widthIndex][idx] = response.meanSettledDropRaw;
                              rings[widthIndex][idx] = response.meanRingRaw;
                              latencies[widthIndex][idx] = response.meanLatencyMs;
                            }
                            row.out += response.outlierCount;
                            row.sc += recorder.sampleCount();
                            row.ec += recorder.eventCount();
                            if (timeout) {
                              row.timeout++;
                              row.rej++;
                            }
                            return !timeout;
                          };

                          bool valveSequenceOk = true;
                          for (uint16_t widthIndex = 0u; widthIndex < kValveCharWidthCount && valveSequenceOk && !_selfTestAbortRequested; ++widthIndex) {
                            const uint16_t widthUs = kValveCharWidthsUs[widthIndex];
                            if (!runOnePulse(widthUs, 0u, 0u, false)) {
                              valveSequenceOk = false;
                            }
                          }

                          for (uint16_t seq = 0u; seq < kValveCharMeasuredPulses && valveSequenceOk && !_selfTestAbortRequested; ++seq) {
                            const uint16_t widthUs = ValvePulseQualificationMath::groupedValvePulseWidthUs(seq, kValveCharReplicates);
                            const uint8_t widthIndex = valveWidthIndex(widthUs);
                            const uint16_t repForWidth = static_cast<uint16_t>(++scheduledCount[widthIndex]);
                            if (!runOnePulse(widthUs, static_cast<uint16_t>(seq + 1u), repForWidth, true)) {
                              valveSequenceOk = false;
                            }
                          }

                          for (uint8_t i = 0u; i < kValveCharWidthCount; ++i) {
                            const auto aggregate = ValvePulseQualificationMath::summarizeResponseValues(
                                responses[i],
                                responseCount[i]);
                            row.mean[i] = aggregate.meanRaw;
                            row.cv[i] = aggregate.cvPct;
                            row.span[i] = aggregate.spanRaw;
                            row.out += aggregate.outlierCount;
                            const auto ringAggregate = ValvePulseQualificationMath::summarizeResponseValues(
                                rings[i],
                                responseCount[i]);
                            row.ring[i] = ringAggregate.meanRaw;
                            const auto latencyAggregate = ValvePulseQualificationMath::summarizeResponseValues(
                                latencies[i],
                                responseCount[i]);
                            row.latency[i] = latencyAggregate.meanRaw;
                            row.pass = row.pass && (responseCount[i] == kValveCharReplicates);
                          }
                          row.pass = row.pass &&
                                     !_selfTestAbortRequested &&
                                     (row.ready == 0u) &&
                                     (row.rej == 0u) &&
                                     (row.freshTo == 0u) &&
                                     (row.timeout == 0u) &&
                                     (row.sc > 0u) &&
                                     (row.ec > 0u);
                          reg.pause();
                          printer->setPrintPulse(originalPrintPulse);
                          printer->setRefuelPulse(originalRefuelPulse);
                          finalizeValveRowLinearity(row);
                          return row;
                        };

                        auto emitValveChannelRow = [&](uint16_t testId,
                                                       const char* name,
                                                       char ch,
                                                       const ValveCharRowSummary& row) -> bool {
                          char metrics[256];
                          snprintf(metrics, sizeof(metrics),
                                   "ch=%c;home_to=0;timeout=%lu;ready=%lu;rej=%lu;sc=%lu;ec=%lu;focus=1;sm=%lu;fresh_to=%lu;rw=%lu;sw=%lu;m15=%lu;m30=%lu;m45=%lu;cv15=%lu;cv30=%lu;cv45=%lu;rg15=%lu;rg30=%lu;rg45=%lu;lt15=%lu;lt30=%lu;lt45=%lu;mono=%lu",
                                   ch,
                                   static_cast<unsigned long>(row.timeout),
                                   static_cast<unsigned long>(row.ready),
                                   static_cast<unsigned long>(row.rej),
                                   static_cast<unsigned long>(row.sc),
                                   static_cast<unsigned long>(row.ec),
                                   static_cast<unsigned long>(kValveCharFocusedSampleMs),
                                   static_cast<unsigned long>(row.freshTo),
                                   static_cast<unsigned long>(kValveCharRingWindowMs),
                                   static_cast<unsigned long>(kValveCharSettledStartMs),
                                   static_cast<unsigned long>(row.mean[0]),
                                   static_cast<unsigned long>(row.mean[1]),
                                   static_cast<unsigned long>(row.mean[2]),
                                   static_cast<unsigned long>(row.cv[0]),
                                   static_cast<unsigned long>(row.cv[1]),
                                   static_cast<unsigned long>(row.cv[2]),
                                   static_cast<unsigned long>(row.ring[0]),
                                   static_cast<unsigned long>(row.ring[1]),
                                   static_cast<unsigned long>(row.ring[2]),
                                   static_cast<unsigned long>(row.latency[0]),
                                   static_cast<unsigned long>(row.latency[1]),
                                   static_cast<unsigned long>(row.latency[2]),
                                   static_cast<unsigned long>(row.mono));
                          return runOne(testId, name, row.pass, metrics);
                        };

                        auto emitValveHomeFailureChannelRow = [&](uint16_t testId,
                                                                  const char* name,
                                                                  char ch) -> bool {
                          char metrics[256];
                          snprintf(metrics, sizeof(metrics),
                                   "ch=%c;home_to=1;timeout=0;ready=0;rej=30;sc=0;ec=0;focus=0;sm=%lu;fresh_to=0;rw=%lu;sw=%lu;m15=0;m30=0;m45=0;cv15=0;cv30=0;cv45=0;rg15=0;rg30=0;rg45=0;lt15=0;lt30=0;lt45=0;mono=0;gate=home_reference",
                                   ch,
                                   static_cast<unsigned long>(kValveCharFocusedSampleMs),
                                   static_cast<unsigned long>(kValveCharRingWindowMs),
                                   static_cast<unsigned long>(kValveCharSettledStartMs));
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
                                        "psi=2000;rep=10;pulses=0;home_to=0;timeout=0;ready=1;rej=30;sc=0;ec=0;m15p=0;m15r=0;m30p=0;m30r=0;m45p=0;m45r=0;r15=0;r30=0;r45=0;d15=0;d30=0;d45=0;gate=no_refuel_port");
#else
                          const uint32_t r15 = (refuelRow.mean[0] > 0u) ? static_cast<uint32_t>((static_cast<uint64_t>(printRow.mean[0]) * 100u) / refuelRow.mean[0]) : 0u;
                          const uint32_t r30 = (refuelRow.mean[1] > 0u) ? static_cast<uint32_t>((static_cast<uint64_t>(printRow.mean[1]) * 100u) / refuelRow.mean[1]) : 0u;
                          const uint32_t r45 = (refuelRow.mean[2] > 0u) ? static_cast<uint32_t>((static_cast<uint64_t>(printRow.mean[2]) * 100u) / refuelRow.mean[2]) : 0u;
                          const uint32_t d15 = ValvePulseQualificationMath::absDiff(printRow.mean[0], refuelRow.mean[0]);
                          const uint32_t d30 = ValvePulseQualificationMath::absDiff(printRow.mean[1], refuelRow.mean[1]);
                          const uint32_t d45 = ValvePulseQualificationMath::absDiff(printRow.mean[2], refuelRow.mean[2]);
                          char metrics[256];
                          snprintf(metrics, sizeof(metrics),
                                   "psi=2000;rep=10;pulses=60;home_to=0;timeout=%lu;ready=%lu;rej=%lu;sc=%lu;ec=%lu;m15p=%lu;m15r=%lu;m30p=%lu;m30r=%lu;m45p=%lu;m45r=%lu;r15=%lu;r30=%lu;r45=%lu;d15=%lu;d30=%lu;d45=%lu",
                                   static_cast<unsigned long>(printRow.timeout + refuelRow.timeout),
                                   static_cast<unsigned long>(printRow.ready + refuelRow.ready),
                                   static_cast<unsigned long>(printRow.rej + refuelRow.rej),
                                   static_cast<unsigned long>(printRow.sc + refuelRow.sc),
                                   static_cast<unsigned long>(printRow.ec + refuelRow.ec),
                                   static_cast<unsigned long>(printRow.mean[0]),
                                   static_cast<unsigned long>(refuelRow.mean[0]),
                                   static_cast<unsigned long>(printRow.mean[1]),
                                   static_cast<unsigned long>(refuelRow.mean[1]),
                                   static_cast<unsigned long>(printRow.mean[2]),
                                   static_cast<unsigned long>(refuelRow.mean[2]),
                                   static_cast<unsigned long>(r15),
                                   static_cast<unsigned long>(r30),
                                   static_cast<unsigned long>(r45),
                                   static_cast<unsigned long>(d15),
                                   static_cast<unsigned long>(d30),
                                   static_cast<unsigned long>(d45));
                          return runOne(kTestId, kName, printRow.pass && refuelRow.pass, metrics);
#endif
                        };

                        auto emitValveHomeFailureRows = [&]() -> bool {
                          if (!emitValveHomeFailureChannelRow(2473u, "valve_char_print_2psi_repeat_linearity", 'p')) return false;
                          if (!emitValveHomeFailureChannelRow(2474u, "valve_char_refuel_2psi_repeat_linearity", 'r')) return false;
                          return runOne(2475u,
                                        "valve_char_channel_balance_2psi",
                                        false,
                                        "psi=2000;rep=10;pulses=60;home_to=1;timeout=0;ready=0;rej=60;sc=0;ec=0;m15p=0;m15r=0;m30p=0;m30r=0;m45p=0;m45r=0;r15=0;r30=0;r45=0;d15=0;d30=0;d45=0;gate=home_reference");
                        };

                        struct ValveGapRowSummary {
                          uint32_t mean[5] = {0u, 0u, 0u, 0u, 0u};
                          uint32_t rej = 0u;
                          uint32_t ready = 0u;
                          uint32_t freshTo = 0u;
                          uint32_t sc = 0u;
                          uint32_t ec = 0u;
                          uint32_t timeout = 0u;
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
                            row.rej = expectedPulseCount;
                            row.ready = 1u;
                            row.pass = false;
                            return row;
                          }
#endif
                          Printer* printer = Printer::instance();
                          PressureSensor* sensor = PressureSensor::instance();
                          if (printer == nullptr || sensor == nullptr) {
                            row.rej = expectedPulseCount;
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
                            row.rej = expectedPulseCount;
                            row.ready = 1u;
                            row.pass = false;
                            return row;
                          }

                          PressureRegulator& reg = regulatorForValveChannel(channel);
                          Stepper* stepper = (channel == 0u) ? Stepper::stepperP() : Stepper::stepperR();
                          const uint32_t originalPrintPulse = printer->getPrintPulse();
                          const uint32_t originalRefuelPulse = printer->getRefuelPulse();

                          uint32_t responses[5][8]{};
                          uint32_t responseCount[5]{};
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
                              row.rej++;
                              return true;
                            }
                            if (!delayWithWatchdog(gapMs, "valve_gap_settle")) {
                              row.timeout++;
                              row.rej++;
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

                            const auto response = ValvePulseQualificationMath::summarizeWindowedValveCharacterization(
                                recorder.samples(),
                                recorder.sampleCount(),
                                recorder.events(),
                                recorder.eventCount(),
                                kValveCharBaselineWindowMs,
                                kValveCharRingWindowMs,
                                kValveCharSettledStartMs,
                                kValveCharSettledEndMs);
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
                            (void)exportTrace(testId, traceName, !timeout && (response.pulseCount >= 1u));
                            row.rej += response.rejectCount;
                            if (response.pulseCount < 1u) {
                              row.rej++;
                            } else if (conditionIndex < 5u && responseCount[conditionIndex] < 8u) {
                              responses[conditionIndex][responseCount[conditionIndex]++] = response.meanSettledDropRaw;
                            }
                            row.sc += recorder.sampleCount();
                            row.ec += recorder.eventCount();
                            if (timeout) {
                              row.timeout++;
                              row.rej++;
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

                          for (uint16_t condition = 0u; condition < conditionCount; ++condition) {
                            const auto aggregate = ValvePulseQualificationMath::summarizeResponseValues(
                                responses[condition],
                                responseCount[condition]);
                            row.mean[condition] = aggregate.meanRaw;
                            row.pass = row.pass && (responseCount[condition] == replicateCount);
                          }
                          row.pass = row.pass &&
                                     !_selfTestAbortRequested &&
                                     (row.ready == 0u) &&
                                     (row.rej == 0u) &&
                                     (row.freshTo == 0u) &&
                                     (row.timeout == 0u) &&
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
                          char metrics[256];
                          snprintf(metrics, sizeof(metrics),
                                   "ch=%c;pw=1500;rep=8;home_to=0;timeout=%lu;ready=%lu;rej=%lu;fresh_to=%lu;focus=1;sc=%lu;ec=%lu;g250=%lu;g500=%lu;g1000=%lu;g2000=%lu;g5000=%lu",
                                   ch,
                                   static_cast<unsigned long>(row.timeout),
                                   static_cast<unsigned long>(row.ready),
                                   static_cast<unsigned long>(row.rej),
                                   static_cast<unsigned long>(row.freshTo),
                                   static_cast<unsigned long>(row.sc),
                                   static_cast<unsigned long>(row.ec),
                                   static_cast<unsigned long>(row.mean[0]),
                                   static_cast<unsigned long>(row.mean[1]),
                                   static_cast<unsigned long>(row.mean[2]),
                                   static_cast<unsigned long>(row.mean[3]),
                                   static_cast<unsigned long>(row.mean[4]));
                          return runOne(testId, name, row.pass, metrics);
                        };

                        auto emitValveGapControlRow = [&](uint16_t testId,
                                                          const char* name,
                                                          char ch,
                                                          const ValveGapRowSummary& row) -> bool {
                          char metrics[256];
                          snprintf(metrics, sizeof(metrics),
                                   "ch=%c;rep=4;home_to=0;timeout=%lu;ready=%lu;rej=%lu;fresh_to=%lu;focus=1;sc=%lu;ec=%lu;m30g500=%lu;m30g2000=%lu;m45g500=%lu;m45g2000=%lu",
                                   ch,
                                   static_cast<unsigned long>(row.timeout),
                                   static_cast<unsigned long>(row.ready),
                                   static_cast<unsigned long>(row.rej),
                                   static_cast<unsigned long>(row.freshTo),
                                   static_cast<unsigned long>(row.sc),
                                   static_cast<unsigned long>(row.ec),
                                   static_cast<unsigned long>(row.mean[0]),
                                   static_cast<unsigned long>(row.mean[1]),
                                   static_cast<unsigned long>(row.mean[2]),
                                   static_cast<unsigned long>(row.mean[3]));
                          return runOne(testId, name, row.pass, metrics);
                        };

                        auto emitValveGapHomeFailureRows = [&]() -> bool {
                          if (!runOne(2476u, "valve_gap_print_1500us_2psi", false, "ch=p;pw=1500;rep=8;home_to=1;timeout=0;ready=0;rej=40;fresh_to=0;focus=0;sc=0;ec=0;g250=0;g500=0;g1000=0;g2000=0;g5000=0;gate=home_reference")) return false;
                          if (!runOne(2477u, "valve_gap_refuel_1500us_2psi", false, "ch=r;pw=1500;rep=8;home_to=1;timeout=0;ready=0;rej=40;fresh_to=0;focus=0;sc=0;ec=0;g250=0;g500=0;g1000=0;g2000=0;g5000=0;gate=home_reference")) return false;
                          if (!runOne(2478u, "valve_gap_print_control_2psi", false, "ch=p;rep=4;home_to=1;timeout=0;ready=0;rej=16;fresh_to=0;focus=0;sc=0;ec=0;m30g500=0;m30g2000=0;m45g500=0;m45g2000=0;gate=home_reference")) return false;
                          return runOne(2479u, "valve_gap_refuel_control_2psi", false, "ch=r;rep=4;home_to=1;timeout=0;ready=0;rej=16;fresh_to=0;focus=0;sc=0;ec=0;m30g500=0;m30g2000=0;m45g500=0;m45g2000=0;gate=home_reference");
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
					    char metrics[384];
					    snprintf(metrics, sizeof(metrics),
                                "flash_delay_us=%lu;flash_width_ns=%lu;flash_width_min_ns=%lu;flash_width_max_ns=%lu;"
                                 "ext_count=%lu;flash_ack_count=%lu;flash_task_wake_count=%lu;flash_task_done_count=%lu;"
                                 "flash_init_cmd_count=%lu;flash_init_ok_count=%lu;flash_init_task_create_fail_count=%lu;flash_init_timer_create_fail_count=%lu;"
                                 "flash_session_armed=%lu;flash_fault_latched=%lu;flash_fault_reason=%s;flash_output_armed=%lu;flash_output_mode=%s",
					             static_cast<unsigned long>(flashDelay),
					             static_cast<unsigned long>(flashWidthNs),
                                 static_cast<unsigned long>(flashWidthMinNs),
                                 static_cast<unsigned long>(flashWidthMaxNs),
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
                        setImagingDroplets(priorDrops);

                        const uint32_t dExt = extPost - extPre;
                        const uint32_t dAck = ackPost - ackPre;
                        const uint32_t dWake = wakePost - wakePre;
                        const uint32_t dDone = donePost - donePre;
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
                                           (dAck >= started));
                        char metrics[320];
                        snprintf(metrics, sizeof(metrics),
                                 "skipped_no_flash_task=%lu;cycles_req=%lu;cycles_started=%lu;cycles_timeout=%lu;ext_delta=%lu;flash_ack_delta=%lu;flash_task_wake_delta=%lu;flash_task_done_delta=%lu;"
                                 "flash_session_armed=%lu;flash_fault_latched=%lu;flash_fault_reason=%s;flash_output_armed=%lu;flash_output_mode=%s",
                                 static_cast<unsigned long>(taskPresent ? 0u : 1u),
                                 static_cast<unsigned long>(kBurstCycles),
                                 static_cast<unsigned long>(started),
                                 static_cast<unsigned long>(timedOut),
                                 static_cast<unsigned long>(dExt),
                                 static_cast<unsigned long>(dAck),
                                 static_cast<unsigned long>(dWake),
                                 static_cast<unsigned long>(dDone),
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
						    static constexpr size_t kSelfTestTaskSnapshotCap = 16u;
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
						    bool hasLogStats = false;
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
						      } else if (strcmp(taskName, "LogStats") == 0) {
						        hasLogStats = true;
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
						                                 (hasPressure ? 0u : 1u) +
						                                 (hasLogStats ? 0u : 1u);
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
						             "heap_now=%lu;heap_min=%lu;stk_min=%u;stk_task=%s;task_n=%u;core_miss=%lu;preg_n=%lu;trunc=%u;stk_ovf=%lu;prnt_hwm_words=%u;flashmon_hwm_words=%u;flashmon_present=%u",
						             static_cast<unsigned long>(heapNow),
						             static_cast<unsigned long>(heapMin),
						             static_cast<unsigned>(stackMinWords),
						             stackMinTask,
						             static_cast<unsigned>(captured),
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
						    const bool pending = (snap.flags & CRASHLOG_FLAG_PENDING) != 0u;
						    const bool sticky = (snap.flags & CRASHLOG_FLAG_WDT_ARM_STICKY) != 0u;
						    const bool staleWatchdogHistory =
						        pending &&
						        sticky &&
						        (snap.lastFault == CRASH_FAULT_WDT_STARVE) &&
						        (snap.resetCause != CRASH_RESET_IWDG);
						    const bool pass = (!pending && (snap.lastFault == CRASH_FAULT_NONE)) || staleWatchdogHistory;
						    char metrics[224];
						    snprintf(metrics,
						             sizeof(metrics),
						             "pending=%u;sticky=%u;fault=%s;task=%s;reset=%s;boot=%lu;fault_ct=%lu;wdg_ct=%lu;sticky_ct=%lu;raw_sr=%lu;boot_stage=%s;wdg_late=%s",
						             pending ? 1u : 0u,
						             sticky ? 1u : 0u,
						             CrashLog_FaultKindName(snap.lastFault),
						             CrashLog_TaskIdName(snap.lastTask),
						             CrashLog_ResetCauseName(snap.resetCause),
						             static_cast<unsigned long>(snap.bootCount),
						             static_cast<unsigned long>(snap.faultCountTotal),
						             static_cast<unsigned long>(snap.watchdogResetCount),
						             static_cast<unsigned long>(snap.watchdogStickyCount),
						             static_cast<unsigned long>(snap.watchdogRawStatus),
						             CrashLog_BootStageName(snap.bootStage),
						             CrashLog_TaskIdName(snap.watchdogLateTask));
						    if (!runOne(1041, "crash_record_retained_safe", pass, metrics)) goto selftest_done;
						  }
						#endif

						#if (LC_WATCHDOG_SELFTEST_ENABLE != 0)
						  {
						    const WatchdogArmResult armResult = Watchdog_GetArmResult();
						    const uint32_t enabled = Watchdog_IsEnabled();
						    const uint32_t reqN = Watchdog_GetRequiredTaskCount();
						    const uint32_t liveN = Watchdog_GetLiveTaskCount();
						    const CrashTaskId lateTask = Watchdog_GetLateTask();
						    const uint32_t recoveryBoot = CrashLog_IsWatchdogRecoveryBoot();
						    const bool passArmed = (armResult == WATCHDOG_ARM_RESULT_ARMED) &&
						        (enabled == 1u) &&
						        (lateTask == CRASH_TASK_NONE) &&
						        (reqN > 0u) &&
						        (liveN == reqN);
						    const bool passStickySkip = (armResult == WATCHDOG_ARM_RESULT_SKIPPED_STICKY_STATUS) &&
						        (enabled == 0u) &&
						        (lateTask == CRASH_TASK_NONE) &&
						        (reqN == 0u) &&
						        (liveN == 0u);
						    const bool pass = passArmed || passStickySkip;
						    char metrics[192];
						    snprintf(metrics,
						             sizeof(metrics),
						             "enabled=%lu;arm_result=%s;timeout_ms=%lu;init_timeout_ms=%lu;req_n=%lu;live_n=%lu;late_task=%s;raw_sr=%lu;sticky_ct=%lu;recovery_boot=%lu",
						             static_cast<unsigned long>(enabled),
						             Watchdog_ArmResultName(armResult),
						             static_cast<unsigned long>(Watchdog_GetTimeoutMs()),
						             static_cast<unsigned long>(Watchdog_GetInitTimeoutMs()),
						             static_cast<unsigned long>(reqN),
						             static_cast<unsigned long>(liveN),
						             CrashLog_TaskIdName(lateTask),
						             static_cast<unsigned long>(Watchdog_GetRawStatus()),
						             static_cast<unsigned long>(Watchdog_GetStickyStatusCount()),
						             static_cast<unsigned long>(recoveryBoot));
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
                            static constexpr uint16_t kValvePulseCount = 8u;
                            static constexpr uint16_t kDualValvePulseCount = 6u;
                            static constexpr uint16_t kValvePulseRateHz = 20u;

                            auto clampPulseWidthU16 = [](uint32_t pulseUs) -> uint16_t {
                              return static_cast<uint16_t>((pulseUs > 0xFFFFu) ? 0xFFFFu : pulseUs);
                            };

                            auto runSingleValvePulseDiagnostic = [&](uint16_t testId,
                                                                     const char* name,
                                                                     uint8_t channel,
                                                                     PulseMode mode,
                                                                     uint16_t targetRaw) -> bool {
                              if (!fullProfile || pressureSweepOnly) {
                                return runOne(testId,
                                              name,
                                              true,
                                              pressureSweepOnly ? "profile=FULL;executed=0;fixture_required=1;pulses=0;gate=sweep_only" : "profile=SAFE;executed=0;fixture_required=1;pulses=0;gate=safe_only");
                              }
#if (LC_PRESSURE_PORTS <= 1)
                              if (channel != 0u) {
                                return runOne(testId,
                                              name,
                                              true,
                                              "profile=FULL;executed=0;fixture_required=1;pulses=0;gate=no_refuel_port");
                              }
#endif
                              if (!fullHomePass) {
                                return runOne(testId,
                                              name,
                                              false,
                                              "ch=x;pulses=0;pw_us=0;hz=0;mean=0;cv_pct=0;slope=0;out=0;rec_w=0;slip_w=0;ready=1;sc=0;ec=0");
                              }
                              Printer* printer = Printer::instance();
                              if (printer == nullptr) {
                                return runOne(testId,
                                              name,
                                              false,
                                              "ch=x;pulses=0;pw_us=0;hz=0;mean=0;cv_pct=0;slope=0;out=0;rec_w=0;slip_w=0;ready=1;sc=0;ec=0");
                              }

                              const uint16_t pulseWidthUs = clampPulseWidthU16(
                                  (channel == 0u) ? printer->getPrintPulse() : printer->getRefuelPulse());
                              PressureTraceCaseMetrics metrics{};
                              bool traceRan = false;
                              if (pulseWidthUs > 0u) {
                                traceRan = runPressureTraceCase(testId,
                                                                name,
                                                                channel,
                                                                targetRaw,
                                                                pulseWidthUs,
                                                                kValvePulseCount,
                                                                kValvePulseRateHz,
                                                                mode,
                                                                false,
                                                                0u,
                                                                0u,
                                                                &metrics,
                                                                false,
                                                                false);
                              }
                              const auto& drops = metrics.pulseDrop;
                              const bool pass = traceRan &&
                                                (pulseWidthUs > 0u) &&
                                                (drops.pulseCount >= kValvePulseCount) &&
                                                (metrics.traceSampleCount > 0u) &&
                                                (metrics.traceEventCount > 0u);
                              char resultMetrics[192];
                              snprintf(resultMetrics, sizeof(resultMetrics),
                                       "ch=%c;pulses=%lu;pw_us=%u;hz=%u;mean=%lu;cv_pct=%lu;slope=%ld;out=%lu;rec_w=%lu;slip_w=%lu;ready=%lu;sc=%lu;ec=%lu",
                                       (channel == 0u) ? 'p' : 'r',
                                       static_cast<unsigned long>(drops.pulseCount),
                                       static_cast<unsigned>(pulseWidthUs),
                                       static_cast<unsigned>(kValvePulseRateHz),
                                       static_cast<unsigned long>(drops.meanDropRaw),
                                       static_cast<unsigned long>(drops.dropCvPct),
                                       static_cast<long>(drops.dropSlopeRawPerPulse),
                                       static_cast<unsigned long>(drops.outlierCount),
                                       static_cast<unsigned long>(drops.maxRecoveryMs),
                                       static_cast<unsigned long>(drops.maxDeadlineSlipMs),
                                       static_cast<unsigned long>(metrics.readyMissCount),
                                       static_cast<unsigned long>(metrics.traceSampleCount),
                                       static_cast<unsigned long>(metrics.traceEventCount));
                              return runOne(testId, name, pass, resultMetrics);
                            };

                            auto runDualValveInteractionDiagnostic = [&]() -> bool {
                              static constexpr uint16_t kTestId = 2403u;
                              static constexpr const char* kName = "dual_valve_interaction_factory";
                              if (!fullProfile || pressureSweepOnly) {
                                return runOne(kTestId,
                                              kName,
                                              true,
                                              pressureSweepOnly ? "profile=FULL;executed=0;fixture_required=1;pulses=0;gate=sweep_only" : "profile=SAFE;executed=0;fixture_required=1;pulses=0;gate=safe_only");
                              }
#if (LC_PRESSURE_PORTS <= 1)
                              return runOne(kTestId,
                                            kName,
                                            true,
                                            "profile=FULL;executed=0;fixture_required=1;pulses=0;gate=no_refuel_port");
#else
                              if (!fullHomePass) {
                                return runOne(kTestId,
                                              kName,
                                              false,
                                              "mode=both;pulses=0;p_pw=0;r_pw=0;p_mean=0;r_mean=0;ratio=0;delta=0;p_out=0;r_out=0;slip_w=0;ready=1");
                              }
                              Printer* printer = Printer::instance();
                              if (printer == nullptr) {
                                return runOne(kTestId,
                                              kName,
                                              false,
                                              "mode=both;pulses=0;p_pw=0;r_pw=0;p_mean=0;r_mean=0;ratio=0;delta=0;p_out=0;r_out=0;slip_w=0;ready=1");
                              }
                              const uint16_t printPulseUs = clampPulseWidthU16(printer->getPrintPulse());
                              const uint16_t refuelPulseUs = clampPulseWidthU16(printer->getRefuelPulse());
                              PressureTraceCaseMetrics printMetrics{};
                              PressureTraceCaseMetrics refuelMetrics{};
                              bool printRan = false;
                              bool refuelRan = false;
                              if (printPulseUs > 0u && refuelPulseUs > 0u) {
                                printRan = runPressureTraceCase(kTestId,
                                                                kName,
                                                                0u,
                                                                psiToRaw(1000u),
                                                                printPulseUs,
                                                                kDualValvePulseCount,
                                                                kValvePulseRateHz,
                                                                PulseMode::BOTH,
                                                                true,
                                                                psiToRaw(500u),
                                                                refuelPulseUs,
                                                                &printMetrics,
                                                                false,
                                                                false);
                                if (printRan) {
                                  refuelRan = runPressureTraceCase(kTestId,
                                                                   kName,
                                                                   1u,
                                                                   psiToRaw(500u),
                                                                   refuelPulseUs,
                                                                   kDualValvePulseCount,
                                                                   kValvePulseRateHz,
                                                                   PulseMode::BOTH,
                                                                   true,
                                                                   psiToRaw(1000u),
                                                                   printPulseUs,
                                                                   &refuelMetrics,
                                                                   false,
                                                                   false);
                                }
                              }
                              const auto& p = printMetrics.pulseDrop;
                              const auto& r = refuelMetrics.pulseDrop;
                              const uint32_t ratio = (r.meanDropRaw > 0u)
                                                         ? static_cast<uint32_t>((static_cast<uint64_t>(p.meanDropRaw) * 100u) / r.meanDropRaw)
                                                         : 0u;
                              const uint32_t delta = ValvePulseQualificationMath::absDiff(p.meanDropRaw, r.meanDropRaw);
                              const uint32_t slipWorst = (p.maxDeadlineSlipMs > r.maxDeadlineSlipMs) ? p.maxDeadlineSlipMs : r.maxDeadlineSlipMs;
                              const uint32_t readyMiss = printMetrics.readyMissCount + refuelMetrics.readyMissCount;
                              const bool pass = printRan &&
                                                refuelRan &&
                                                (p.pulseCount >= kDualValvePulseCount) &&
                                                (r.pulseCount >= kDualValvePulseCount);
                              char resultMetrics[192];
                              snprintf(resultMetrics, sizeof(resultMetrics),
                                       "mode=both;pulses=%u;p_pw=%u;r_pw=%u;p_mean=%lu;r_mean=%lu;ratio=%lu;delta=%lu;p_out=%lu;r_out=%lu;slip_w=%lu;ready=%lu",
                                       static_cast<unsigned>(kDualValvePulseCount),
                                       static_cast<unsigned>(printPulseUs),
                                       static_cast<unsigned>(refuelPulseUs),
                                       static_cast<unsigned long>(p.meanDropRaw),
                                       static_cast<unsigned long>(r.meanDropRaw),
                                       static_cast<unsigned long>(ratio),
                                       static_cast<unsigned long>(delta),
                                       static_cast<unsigned long>(p.outlierCount),
                                       static_cast<unsigned long>(r.outlierCount),
                                       static_cast<unsigned long>(slipWorst),
                                       static_cast<unsigned long>(readyMiss));
                              return runOne(kTestId, kName, pass, resultMetrics);
#endif
                            };

                            if (!runSingleValvePulseDiagnostic(2401u,
                                                               "print_valve_pulse_drop_repeatability_factory",
                                                               0u,
                                                               PulseMode::PRINT_ONLY,
                                                               psiToRaw(1000u))) {
                              goto selftest_done;
                            }
                            if (!runSingleValvePulseDiagnostic(2402u,
                                                               "refuel_valve_pulse_drop_repeatability_factory",
                                                               1u,
                                                               PulseMode::REFUEL_ONLY,
                                                               psiToRaw(500u))) {
                              goto selftest_done;
                            }
                            if (!runDualValveInteractionDiagnostic()) {
                              goto selftest_done;
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
