#include "CppUTest/TestHarness.h"
#include "CoordinatedXyPerformanceReport.h"

#include <cstdio>
#include <cstring>
#include <limits>

namespace {

CoordinatedXyPerformanceReport::MoveObservation acceptedMove(
    uint32_t x,
    uint32_t y,
    uint32_t master,
    uint32_t rate,
    uint32_t targetArr,
    uint32_t startArr) {
  CoordinatedXyPerformanceReport::MoveObservation observation{};
  const uint32_t callbacks = master;
  observation.expectedXEdges = x;
  observation.expectedYEdges = y;
  observation.expectedMasterEdges = master;
  observation.expectedRateHz = rate;
  observation.expectedTargetArr = targetArr;
  observation.expectedStartArr = startArr;
  observation.requestedXEdges = x;
  observation.requestedYEdges = y;
  observation.emittedXEdges = x;
  observation.emittedYEdges = y;
  observation.masterEdges = master;
  observation.selectedRateHz = rate;
  observation.timer2Callbacks = callbacks;
  observation.arrMin = targetArr;
  observation.arrMax = startArr;
  observation.conditionalDecisionCount = callbacks - 1u;
  observation.conditionalNonRearmSlackMinTicks = 1126u;
  observation.terminalReason =
      CoordinatedXyExecutor::TerminalReason::Completed;
  observation.durationErrorBasisPoints = 10u;
  observation.statusPeriodMaxMs = 65u;
  observation.statusWatchdogAgeMaxMs = 70u;
  observation.statusFrameCount = 3u;
  observation.minimumDeadlineSlackTicks = 450u;
  observation.endpointMatches = true;
  observation.targetsMatch = true;
  observation.completionTogether = true;
  observation.pinsLow = true;
  observation.ownershipReleased = true;
  observation.checksumMatch = true;
  observation.timing.valid = true;
  observation.timing.totalCallbacks = callbacks;
  observation.timing.activeEdgeEvents = master;
  observation.timing.phaseCallbacks[0] = 2u;
  observation.timing.phaseCallbacks[1] = callbacks - 5u;
  observation.timing.phaseCallbacks[2] = 2u;
  observation.timing.phaseMaxCycles[0] = 600u;
  observation.timing.phaseMaxCycles[1] = 400u;
  observation.timing.phaseMaxCycles[2] = 700u;
  observation.timing.terminalCallbacks = 1u;
  observation.timing.terminalMaxCycles = 1800u;
  observation.timing.terminalStageSamples = 1u;
  observation.timing.terminalMinCycles = 1800u;
  observation.timing.terminalTotalCycles = 1800u;
  observation.timing.worstTerminalCommonCycles = 900u;
  observation.timing.worstTerminalShutdownCycles = 600u;
  observation.timing.worstTerminalInstrumentationCycles = 300u;
  observation.timing.worstTerminalPreHandlerCycles = 15u;
  observation.timing.worstTerminalFullIrqCycles = 1900u;
  observation.timing.irqPathSamples = callbacks;
  observation.timing.preHandlerMaxCycles = 15u;
  observation.timing.fullIrqMaxCycles = 1900u;
  observation.timing.activeFullIrqMaxCycles = 850u;
  observation.timing.terminalFullIrqMaxCycles = 1900u;
  observation.timing.entryTimerSamples = callbacks;
  observation.timing.entryTimerCountMax = 50u;
  observation.timing.entryScheduleOverrunMaxCycles = 60u;
  observation.timing.deadlineSamples = callbacks - 1u;
  observation.timing.deadlineSlackMinTicks = 500u;
  return observation;
}

}  // namespace

TEST_GROUP(CoordinatedXyPerformanceReport) {};

TEST(CoordinatedXyPerformanceReport, BoundsHomeGuardFromPositionOrEnvelope) {
  UNSIGNED_LONGS_EQUAL(
      11916u,
      CoordinatedXyPerformanceReport::boundedHomeGuardSteps(
          8916, 45000u, 3000u, 3000u, true));
  UNSIGNED_LONGS_EQUAL(
      48000u,
      CoordinatedXyPerformanceReport::boundedHomeGuardSteps(
          0, 45000u, 3000u, 3000u, false));
  UNSIGNED_LONGS_EQUAL(
      3000u,
      CoordinatedXyPerformanceReport::boundedHomeGuardSteps(
          100, 45000u, 100u, 3000u, true));
  UNSIGNED_LONGS_EQUAL(
      std::numeric_limits<uint32_t>::max(),
      CoordinatedXyPerformanceReport::boundedHomeGuardSteps(
          0, std::numeric_limits<uint32_t>::max(), 1u, 1u, false));
}

TEST(CoordinatedXyPerformanceReport, ShallowTimingExpectationsAreExact) {
  CoordinatedXyPerformanceReport::ShallowMoveTimingExpectation expectation{};

  CHECK_TRUE(CoordinatedXyPerformanceReport::shallowMoveTimingExpectation(
      10000u, 17100u, expectation));
  UNSIGNED_LONGS_EQUAL(10000u, expectation.selectedRateHz);
  UNSIGNED_LONGS_EQUAL(8999u, expectation.targetArr);
  UNSIGNED_LONGS_EQUAL(44995u, expectation.startArr);

  CHECK_TRUE(CoordinatedXyPerformanceReport::shallowMoveTimingExpectation(
      10000u, 19574u, expectation));
  UNSIGNED_LONGS_EQUAL(10000u, expectation.selectedRateHz);
  UNSIGNED_LONGS_EQUAL(8999u, expectation.targetArr);
  UNSIGNED_LONGS_EQUAL(44995u, expectation.startArr);

  CHECK_TRUE(CoordinatedXyPerformanceReport::shallowMoveTimingExpectation(
      40000u, 17100u, expectation));
  UNSIGNED_LONGS_EQUAL(36986u, expectation.selectedRateHz);
  UNSIGNED_LONGS_EQUAL(2432u, expectation.targetArr);
  UNSIGNED_LONGS_EQUAL(12160u, expectation.startArr);

  CHECK_TRUE(CoordinatedXyPerformanceReport::shallowMoveTimingExpectation(
      40000u, 19574u, expectation));
  UNSIGNED_LONGS_EQUAL(39571u, expectation.selectedRateHz);
  UNSIGNED_LONGS_EQUAL(2273u, expectation.targetArr);
  UNSIGNED_LONGS_EQUAL(11365u, expectation.startArr);
}

TEST(CoordinatedXyPerformanceReport, ShallowTimingExpectationsFailClosed) {
  CoordinatedXyPerformanceReport::ShallowMoveTimingExpectation expectation{
      1u, 2u, 3u};
  CHECK_FALSE(CoordinatedXyPerformanceReport::shallowMoveTimingExpectation(
      40000u, 17101u, expectation));
  UNSIGNED_LONGS_EQUAL(0u, expectation.selectedRateHz);
  UNSIGNED_LONGS_EQUAL(0u, expectation.targetArr);
  UNSIGNED_LONGS_EQUAL(0u, expectation.startArr);
  CHECK_FALSE(CoordinatedXyPerformanceReport::shallowMoveTimingExpectation(
      20000u, 17100u, expectation));
}

TEST(CoordinatedXyPerformanceReport, AcceptsOneCallbackPerActiveEdgeMove) {
  const auto observation =
      acceptedMove(500u, 1500u, 1500u, 20000u, 2249u, 11245u);
  UNSIGNED_LONGS_EQUAL(
      0u,
      CoordinatedXyPerformanceReport::moveFailureMask(
          observation, CoordinatedXyPerformanceReport::Limits{}));
}

TEST(CoordinatedXyPerformanceReport, RearmGuardBoundaryAndPendingFailStrictly) {
  auto observation =
      acceptedMove(500u, 1500u, 1500u, 20000u, 2249u, 11245u);
  observation.conditionalNonRearmSlackMinTicks = 1125u;
  CHECK_TRUE((CoordinatedXyPerformanceReport::moveFailureMask(
                  observation, CoordinatedXyPerformanceReport::Limits{}) &
              CoordinatedXyPerformanceReport::kMoveFailureTimerRearm) != 0u);

  observation.conditionalNonRearmSlackMinTicks = 1126u;
  observation.timerRearmCount = 1u;
  observation.timerRearmDelayMaxCycles = 40u;
  CHECK_TRUE(CoordinatedXyPerformanceReport::movePasses(
      observation, CoordinatedXyPerformanceReport::Limits{}));

  observation.timerRearmPendingCount = 1u;
  CHECK_FALSE(CoordinatedXyPerformanceReport::movePasses(
      observation, CoordinatedXyPerformanceReport::Limits{}));
}

TEST(CoordinatedXyPerformanceReport, MissingDecisionAndScheduleSaturationFail) {
  auto observation =
      acceptedMove(500u, 1500u, 1500u, 20000u, 2249u, 11245u);
  observation.conditionalDecisionMissingCount = 1u;
  CHECK_TRUE((CoordinatedXyPerformanceReport::moveFailureMask(
                  observation, CoordinatedXyPerformanceReport::Limits{}) &
              CoordinatedXyPerformanceReport::kMoveFailureTimerRearm) != 0u);
  observation.conditionalDecisionMissingCount = 0u;
  observation.timerScheduleSaturationFlags = 1u;
  CHECK_TRUE((CoordinatedXyPerformanceReport::moveFailureMask(
                  observation, CoordinatedXyPerformanceReport::Limits{}) &
              CoordinatedXyPerformanceReport::kMoveFailureScheduleSaturation) !=
             0u);
}

TEST(CoordinatedXyPerformanceReport, TerminalAndTimingCoverageFailClosed) {
  auto observation =
      acceptedMove(500u, 1500u, 1500u, 20000u, 2249u, 11245u);
  observation.terminalReason =
      CoordinatedXyExecutor::TerminalReason::YLimit;
  CHECK_TRUE((CoordinatedXyPerformanceReport::moveFailureMask(
                  observation, CoordinatedXyPerformanceReport::Limits{}) &
              CoordinatedXyPerformanceReport::kMoveFailureTerminalReason) != 0u);
  observation.terminalReason =
      CoordinatedXyExecutor::TerminalReason::Completed;
  observation.timing.irqPathSamples--;
  observation.timing.irqPathMissing = 1u;
  observation.timing.entryTimerSamples--;
  observation.timing.entryTimerMissing = 1u;
  CHECK_FALSE(CoordinatedXyPerformanceReport::movePasses(
      observation, CoordinatedXyPerformanceReport::Limits{}));
}

TEST(CoordinatedXyPerformanceReport, LateEntryGateIsExplicit) {
  auto observation =
      acceptedMove(500u, 1500u, 1500u, 20000u, 2249u, 11245u);
  observation.timing.lateEntryCount = 1u;
  observation.requireNoLateEntries = false;
  CHECK_TRUE(CoordinatedXyPerformanceReport::movePasses(
      observation, CoordinatedXyPerformanceReport::Limits{}));
  observation.requireNoLateEntries = true;
  CHECK_TRUE((CoordinatedXyPerformanceReport::moveFailureMask(
                  observation, CoordinatedXyPerformanceReport::Limits{}) &
              CoordinatedXyPerformanceReport::kMoveFailureEntryLateness) != 0u);
}

TEST(CoordinatedXyPerformanceReport, TerminalCleanupUsesSharedProductionBound) {
  auto observation =
      acceptedMove(500u, 1500u, 1500u, 20000u, 2249u, 11245u);
  observation.requireTerminalCycleBudget = true;
  UNSIGNED_LONGS_EQUAL(
      3500u,
      CoordinatedXyPerformanceReport::kCoordinatedTerminalHandlerBudgetCycles);
  observation.timing.terminalMaxCycles = 3499u;
  CHECK_TRUE(CoordinatedXyPerformanceReport::movePasses(
      observation, CoordinatedXyPerformanceReport::Limits{}));

  observation.timing.terminalMaxCycles = 3500u;
  CHECK_TRUE(CoordinatedXyPerformanceReport::movePasses(
      observation, CoordinatedXyPerformanceReport::Limits{}));

  observation.timing.terminalMaxCycles = 3501u;
  CHECK_TRUE((CoordinatedXyPerformanceReport::moveFailureMask(
                  observation, CoordinatedXyPerformanceReport::Limits{}) &
              CoordinatedXyPerformanceReport::kMoveFailureTerminalCycles) !=
             0u);
}

TEST(CoordinatedXyPerformanceReport, ActiveHandlerUsesSharedRegressionBound) {
  auto observation =
      acceptedMove(500u, 1500u, 1500u, 40000u, 2249u, 11245u);
  UNSIGNED_LONGS_EQUAL(
      2600u,
      CoordinatedXyPerformanceReport::
          kCoordinatedActiveHandlerRegressionBudgetCycles);

  observation.timing.phaseMaxCycles[1] = 2599u;
  CHECK_TRUE(CoordinatedXyPerformanceReport::movePasses(
      observation, CoordinatedXyPerformanceReport::Limits{}));

  observation.timing.phaseMaxCycles[1] = 2600u;
  CHECK_TRUE(CoordinatedXyPerformanceReport::movePasses(
      observation, CoordinatedXyPerformanceReport::Limits{}));

  observation.timing.phaseMaxCycles[1] = 2601u;
  UNSIGNED_LONGS_EQUAL(
      CoordinatedXyPerformanceReport::kMoveFailureActiveCycles,
      CoordinatedXyPerformanceReport::moveFailureMask(
          observation, CoordinatedXyPerformanceReport::Limits{}));
}

TEST(CoordinatedXyPerformanceReport, TerminalOnlyFailureCanContinueDiagnostic) {
  CHECK_TRUE(CoordinatedXyPerformanceReport::
      canContinueAfterTerminalBudgetOnlyFailure(0u));
  CHECK_TRUE(CoordinatedXyPerformanceReport::
      canContinueAfterTerminalBudgetOnlyFailure(
          CoordinatedXyPerformanceReport::kMoveFailureTerminalCycles));
  CHECK_FALSE(CoordinatedXyPerformanceReport::
      canContinueAfterTerminalBudgetOnlyFailure(
          CoordinatedXyPerformanceReport::kMoveFailureTerminalCycles |
          CoordinatedXyPerformanceReport::kMoveFailureEndpoint));
}

TEST(CoordinatedXyPerformanceReport, AggregatesTerminalDistributionAndWorstStages) {
  CoordinatedXyPerformanceReport::Aggregate aggregate{};
  auto first = acceptedMove(100u, 50u, 100u, 10000u, 8999u, 44995u);
  first.timing.terminalMinCycles = 2500u;
  first.timing.terminalTotalCycles = 2500u;
  first.timing.terminalMaxCycles = 2500u;
  first.timing.worstTerminalCommonCycles = 1200u;
  first.timing.worstTerminalShutdownCycles = 800u;
  first.timing.worstTerminalInstrumentationCycles = 500u;
  first.timing.worstTerminalPreHandlerCycles = 20u;
  first.timing.worstTerminalFullIrqCycles = 2700u;
  auto second = acceptedMove(50u, 100u, 100u, 10000u, 8999u, 44995u);
  second.timing.terminalMinCycles = 3501u;
  second.timing.terminalTotalCycles = 3501u;
  second.timing.terminalMaxCycles = 3501u;
  second.timing.worstTerminalCommonCycles = 1300u;
  second.timing.worstTerminalShutdownCycles = 1500u;
  second.timing.worstTerminalInstrumentationCycles = 701u;
  second.timing.worstTerminalPreHandlerCycles = 25u;
  second.timing.worstTerminalFullIrqCycles = 3800u;

  CoordinatedXyPerformanceReport::addMove(
      aggregate, first, CoordinatedXyPerformanceReport::Limits{});
  CoordinatedXyPerformanceReport::addMove(
      aggregate, second, CoordinatedXyPerformanceReport::Limits{});

  UNSIGNED_LONGS_EQUAL(2u, aggregate.terminalSampleCount);
  UNSIGNED_LONGS_EQUAL(2500u, aggregate.terminalMinCycles);
  UNSIGNED_LONGS_EQUAL(6001u, aggregate.terminalTotalCycles);
  UNSIGNED_LONGS_EQUAL(
      3000u, CoordinatedXyPerformanceReport::terminalAverageCycles(aggregate));
  UNSIGNED_LONGS_EQUAL(3501u, aggregate.terminalMaxCycles);
  UNSIGNED_LONGS_EQUAL(1u, aggregate.terminalOverBudgetCount);
  UNSIGNED_LONGS_EQUAL(1300u, aggregate.worstTerminalCommonCycles);
  UNSIGNED_LONGS_EQUAL(1500u, aggregate.worstTerminalShutdownCycles);
  UNSIGNED_LONGS_EQUAL(701u, aggregate.worstTerminalInstrumentationCycles);
  UNSIGNED_LONGS_EQUAL(25u, aggregate.worstTerminalPreHandlerCycles);
  UNSIGNED_LONGS_EQUAL(3800u, aggregate.worstTerminalFullIrqCycles);
}

TEST(CoordinatedXyPerformanceReport, MissingOrInvalidTerminalStagesFailClosed) {
  auto observation =
      acceptedMove(100u, 50u, 100u, 10000u, 8999u, 44995u);
  observation.timing.terminalStageSamples = 0u;
  CHECK_TRUE((CoordinatedXyPerformanceReport::moveFailureMask(
                  observation, CoordinatedXyPerformanceReport::Limits{}) &
              CoordinatedXyPerformanceReport::kMoveFailureTimingCounts) != 0u);
  observation.timing.terminalStageSamples = 1u;
  observation.timing.terminalStageAccountingViolations = 1u;
  CHECK_TRUE((CoordinatedXyPerformanceReport::moveFailureMask(
                  observation, CoordinatedXyPerformanceReport::Limits{}) &
              CoordinatedXyPerformanceReport::kMoveFailureTimingCounts) != 0u);
}

TEST(CoordinatedXyPerformanceReport, CleanupAndSpacingTelemetryFailClosed) {
  auto observation =
      acceptedMove(500u, 1500u, 1500u, 40000u, 2249u, 11245u);
  observation.cleanupEdgeEvents = 1u;
  CHECK_TRUE((CoordinatedXyPerformanceReport::moveFailureMask(
                  observation, CoordinatedXyPerformanceReport::Limits{}) &
              CoordinatedXyPerformanceReport::kMoveFailureCleanupEdges) != 0u);
  observation.cleanupEdgeEvents = 0u;
  observation.edgeSpacingViolations = 1u;
  CHECK_TRUE((CoordinatedXyPerformanceReport::moveFailureMask(
                  observation, CoordinatedXyPerformanceReport::Limits{}) &
              CoordinatedXyPerformanceReport::kMoveFailureEdgeSpacing) != 0u);
}

TEST(CoordinatedXyPerformanceReport, AggregateRequiresExactCompleteRow) {
  CoordinatedXyPerformanceReport::Aggregate aggregate{};
  const auto first =
      acceptedMove(100u, 50u, 100u, 20000u, 2249u, 11245u);
  const auto second =
      acceptedMove(50u, 100u, 100u, 20000u, 2249u, 11245u);
  CoordinatedXyPerformanceReport::addMove(
      aggregate, first, CoordinatedXyPerformanceReport::Limits{});
  CoordinatedXyPerformanceReport::addMove(
      aggregate, second, CoordinatedXyPerformanceReport::Limits{});
  CHECK_TRUE(CoordinatedXyPerformanceReport::aggregatePasses(
      aggregate,
      2u,
      150u,
      150u,
      200u,
      CoordinatedXyPerformanceReport::Limits{}));
  CHECK_FALSE(CoordinatedXyPerformanceReport::aggregatePasses(
      aggregate,
      3u,
      150u,
      150u,
      200u,
      CoordinatedXyPerformanceReport::Limits{}));
}

TEST(CoordinatedXyPerformanceReport, AggregatePreservesExactMoveFailureMask) {
  CoordinatedXyPerformanceReport::Aggregate aggregate{};
  auto endpointFailure =
      acceptedMove(100u, 50u, 100u, 10000u, 8999u, 44995u);
  endpointFailure.endpointMatches = false;
  auto timingFailure =
      acceptedMove(50u, 100u, 100u, 10000u, 8999u, 44995u);
  timingFailure.timing.phaseMaxCycles[1] = 2601u;

  CoordinatedXyPerformanceReport::addMove(
      aggregate, endpointFailure, CoordinatedXyPerformanceReport::Limits{});
  CoordinatedXyPerformanceReport::addMove(
      aggregate, timingFailure, CoordinatedXyPerformanceReport::Limits{});

  const uint32_t expected =
      CoordinatedXyPerformanceReport::kMoveFailureEndpoint |
      CoordinatedXyPerformanceReport::kMoveFailureActiveCycles;
  UNSIGNED_LONGS_EQUAL(expected, aggregate.moveFailureMask);
}

TEST(CoordinatedXyPerformanceReport, AggregateSaturatesWithoutWrapping) {
  CoordinatedXyPerformanceReport::Aggregate aggregate{};
  aggregate.emittedXEdges = std::numeric_limits<uint32_t>::max();
  const auto observation =
      acceptedMove(1u, 0u, 1u, 20000u, 2249u, 11245u);
  CoordinatedXyPerformanceReport::addMove(
      aggregate, observation, CoordinatedXyPerformanceReport::Limits{});
  UNSIGNED_LONGS_EQUAL(std::numeric_limits<uint32_t>::max(),
                       aggregate.emittedXEdges);
  CHECK_TRUE(aggregate.saturationFlags != 0u);
}

TEST(CoordinatedXyPerformanceReport, MetricsFitGenericResultBudget) {
  CoordinatedXyPerformanceReport::Aggregate aggregate{};
  const auto observation =
      acceptedMove(106832u, 180000u, 220000u, 40000u, 2249u, 11245u);
  CoordinatedXyPerformanceReport::addMove(
      aggregate, observation, CoordinatedXyPerformanceReport::Limits{});
  char metrics[224] = {};
  const size_t length = CoordinatedXyPerformanceReport::buildMetrics(
      metrics, sizeof(metrics), 40000u, aggregate, 13u, 13u);
  CHECK_TRUE(length > 0u);
  CHECK_TRUE(std::strstr(metrics, "hz=40000") != nullptr);
  CHECK_TRUE(std::strstr(metrics, ";me=220000;") != nullptr);
  CHECK_TRUE(std::strstr(metrics, ";ce=0;sv=0;") != nullptr);
  CHECK_TRUE(std::strstr(metrics, ";ok=1;") != nullptr);
  CHECK_TRUE(length <= 224u);
}

TEST(CoordinatedXyPerformanceReport, CameraTransitionMetricsReportExactTiming) {
  CoordinatedXyPerformanceReport::Aggregate aggregate{};
  auto forward =
      acceptedMove(8416u, 30000u, 30000u, 40000u, 2249u, 11245u);
  forward.timing.phaseMaxCycles[1] = 2122u;
  forward.timing.terminalMaxCycles = 3053u;
  CoordinatedXyPerformanceReport::addMove(
      aggregate, forward, CoordinatedXyPerformanceReport::Limits{});

  CoordinatedXyPerformanceReport::CameraTransitionEvidence evidence{};
  evidence.failureStage = 2u;
  evidence.stepsLow = true;
  evidence.homeStartPositionSteps = 25000;
  evidence.homeEndPositionSteps = 100;
  evidence.homeGuardSteps = 48000u;
  evidence.homeIsrEntries = 101u;
  evidence.homeCompletedPulses = 50u;
  evidence.homeDriftSteps = std::numeric_limits<uint32_t>::max();

  char metrics[224] = {};
  const size_t length =
      CoordinatedXyPerformanceReport::buildCameraTransitionMetrics(
          metrics, sizeof(metrics), aggregate, evidence);
  CHECK_TRUE(length > 0u);
  CHECK_TRUE(std::strstr(metrics, "fs=2;n=1;xe=8416;ye=30000;") != nullptr);
  CHECK_TRUE(std::strstr(metrics, ";mf=0;ab=2600;am=2122;tm=3053;") !=
             nullptr);
  CHECK_TRUE(std::strstr(metrics, ";hd=4294967295;") != nullptr);
  CHECK_TRUE(length <= 199u);
}

TEST(CoordinatedXyPerformanceReport, CameraTransitionMetricsExposeFailureMasks) {
  CoordinatedXyPerformanceReport::Aggregate aggregate{};
  auto activeFailure =
      acceptedMove(8416u, 30000u, 30000u, 40000u, 2249u, 11245u);
  activeFailure.endpointMatches = false;
  activeFailure.timing.phaseMaxCycles[1] = 2601u;
  CoordinatedXyPerformanceReport::addMove(
      aggregate, activeFailure, CoordinatedXyPerformanceReport::Limits{});

  CoordinatedXyPerformanceReport::CameraTransitionEvidence evidence{};
  evidence.failureStage = 2u;
  char metrics[224] = {};
  CHECK_TRUE(CoordinatedXyPerformanceReport::buildCameraTransitionMetrics(
                 metrics, sizeof(metrics), aggregate, evidence) > 0u);
  const uint32_t combinedMask =
      CoordinatedXyPerformanceReport::kMoveFailureEndpoint |
      CoordinatedXyPerformanceReport::kMoveFailureActiveCycles;
  char expectedMask[32] = {};
  std::snprintf(expectedMask,
                sizeof(expectedMask),
                ";mf=%lu;",
                static_cast<unsigned long>(combinedMask));
  CHECK_TRUE(std::strstr(metrics, expectedMask) != nullptr);

  aggregate = {};
  auto terminalFailure =
      acceptedMove(8416u, 30000u, 30000u, 40000u, 2249u, 11245u);
  terminalFailure.timing.terminalMaxCycles = 3501u;
  CoordinatedXyPerformanceReport::addMove(
      aggregate, terminalFailure, CoordinatedXyPerformanceReport::Limits{});
  CHECK_TRUE(CoordinatedXyPerformanceReport::buildCameraTransitionMetrics(
                 metrics, sizeof(metrics), aggregate, evidence) > 0u);
  CHECK_TRUE(std::strstr(metrics, ";mf=524288;") != nullptr);
  CHECK_TRUE(std::strstr(metrics, ";tm=3501;") != nullptr);
}

TEST(CoordinatedXyPerformanceReport, CameraTransitionMetricsFitFailureFrame) {
  CoordinatedXyPerformanceReport::Aggregate aggregate{};
  aggregate.moveCount = 1u;
  aggregate.emittedXEdges = 8416u;
  aggregate.emittedYEdges = 30000u;
  aggregate.timer2Callbacks = 30000u;
  aggregate.moveFailureMask = std::numeric_limits<uint32_t>::max();
  aggregate.phaseMaxCycles[0] = std::numeric_limits<uint32_t>::max();
  aggregate.terminalMaxCycles = std::numeric_limits<uint32_t>::max();

  CoordinatedXyPerformanceReport::CameraTransitionEvidence evidence{};
  evidence.failureStage = 2u;
  evidence.stepsLow = true;
  evidence.homeStartPositionSteps = 25000;
  evidence.homeEndPositionSteps = 100;
  evidence.homeGuardSteps = 48000u;
  evidence.homeIsrEntries = 101u;
  evidence.homeCompletedPulses = 50u;
  evidence.homeDriftSteps = std::numeric_limits<uint32_t>::max();

  char metrics[224] = {};
  const size_t length =
      CoordinatedXyPerformanceReport::buildCameraTransitionMetrics(
          metrics, sizeof(metrics), aggregate, evidence);
  CHECK_TRUE(length > 0u);
  CHECK_TRUE(length <= 199u);
  CHECK_TRUE(std::strstr(metrics, ";mf=4294967295;") != nullptr);
  CHECK_TRUE(std::strstr(metrics, ";am=4294967295;tm=4294967295;") != nullptr);
}
