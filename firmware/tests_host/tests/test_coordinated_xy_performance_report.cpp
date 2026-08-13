#include "CppUTest/TestHarness.h"
#include "CoordinatedXyPerformanceReport.h"

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
  const uint32_t callbacks = master * 2u;
  observation.expectedXSteps = x;
  observation.expectedYSteps = y;
  observation.expectedMasterSteps = master;
  observation.expectedRateHz = rate;
  observation.expectedTargetArr = targetArr;
  observation.expectedStartArr = startArr;
  observation.requestedXSteps = x;
  observation.requestedYSteps = y;
  observation.emittedXSteps = x;
  observation.emittedYSteps = y;
  observation.masterSteps = master;
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
  observation.timing.completedPulses = master;
  observation.timing.phaseCallbacks[0] = 2u;
  observation.timing.phaseCallbacks[1] = callbacks - 5u;
  observation.timing.phaseCallbacks[2] = 2u;
  observation.timing.phaseMaxCycles[0] = 600u;
  observation.timing.phaseMaxCycles[1] = 400u;
  observation.timing.phaseMaxCycles[2] = 700u;
  observation.timing.terminalCallbacks = 1u;
  observation.timing.terminalMaxCycles = 1800u;
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

TEST(CoordinatedXyPerformanceReport, AcceptsFixedTwoEdgeConditionalMove) {
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

TEST(CoordinatedXyPerformanceReport, AggregateSaturatesWithoutWrapping) {
  CoordinatedXyPerformanceReport::Aggregate aggregate{};
  aggregate.emittedXSteps = std::numeric_limits<uint32_t>::max();
  const auto observation =
      acceptedMove(1u, 0u, 1u, 20000u, 2249u, 11245u);
  CoordinatedXyPerformanceReport::addMove(
      aggregate, observation, CoordinatedXyPerformanceReport::Limits{});
  UNSIGNED_LONGS_EQUAL(std::numeric_limits<uint32_t>::max(),
                       aggregate.emittedXSteps);
  CHECK_TRUE(aggregate.saturationFlags != 0u);
}

TEST(CoordinatedXyPerformanceReport, MetricsFitGenericResultBudget) {
  CoordinatedXyPerformanceReport::Aggregate aggregate{};
  const auto observation =
      acceptedMove(53416u, 90000u, 110000u, 20000u, 2249u, 11245u);
  CoordinatedXyPerformanceReport::addMove(
      aggregate, observation, CoordinatedXyPerformanceReport::Limits{});
  char metrics[224] = {};
  const size_t length = CoordinatedXyPerformanceReport::buildMetrics(
      metrics, sizeof(metrics), 20000u, aggregate, 13u, 13u);
  CHECK_TRUE(length > 0u);
  CHECK_TRUE(std::strstr(metrics, "hz=20000") != nullptr);
  CHECK_TRUE(std::strstr(metrics, ";ok=1;") != nullptr);
  CHECK_TRUE(length <= 224u);
}
