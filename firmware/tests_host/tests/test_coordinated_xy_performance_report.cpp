#include "CppUTest/TestHarness.h"
#include "CoordinatedXyPerformanceReport.h"

#include <cstring>

namespace {

CoordinatedXyPerformanceReport::MoveObservation acceptedMove(
    uint32_t x,
    uint32_t y,
    uint32_t master,
    uint32_t rate,
    uint32_t targetArr,
    uint32_t startArr) {
  CoordinatedXyPerformanceReport::MoveObservation observation{};
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
  observation.timer2Callbacks = master * 2u;
  observation.arrMin = targetArr;
  observation.arrMax = startArr;
  observation.durationErrorBasisPoints = 10u;
  observation.statusPeriodMaxMs = 65u;
  observation.statusWatchdogAgeMaxMs = 70u;
  observation.statusFrameCount = 3u;
  observation.terminalReason =
      CoordinatedXyExecutor::TerminalReason::Completed;
  observation.endpointMatches = true;
  observation.targetsMatch = true;
  observation.completionTogether = true;
  observation.pinsLow = true;
  observation.ownershipReleased = true;
  observation.checksumMatch = true;
  observation.timing.valid = true;
  observation.timing.totalCallbacks = master * 2u;
  observation.timing.completedPulses = master;
  observation.timing.phaseCallbacks[0] = 2u;
  observation.timing.phaseCallbacks[1] = master * 2u - 5u;
  observation.timing.phaseCallbacks[2] = 2u;
  observation.timing.phaseCycleSums[0] = 1000u;
  observation.timing.phaseCycleSums[1] =
      observation.timing.phaseCallbacks[1] * 300u;
  observation.timing.phaseCycleSums[2] = 1200u;
  observation.timing.phaseMaxCycles[0] = 600u;
  observation.timing.phaseMaxCycles[1] = 400u;
  observation.timing.phaseMaxCycles[2] = 700u;
  observation.timing.terminalCallbacks = 1u;
  observation.timing.terminalMaxCycles = 1800u;
  observation.timing.irqPathSamples = master * 2u;
  observation.timing.preHandlerCycleSum = master * 20u;
  observation.timing.preHandlerMaxCycles = 15u;
  observation.timing.fullIrqCycleSum = master * 40u;
  observation.timing.fullIrqMaxCycles = 900u;
  observation.timing.activeFullIrqMaxCycles = 850u;
  observation.timing.terminalFullIrqMaxCycles = 1900u;
  observation.timing.entryTimerSamples = master * 2u;
  observation.timing.entryTimerCountSum = master * 40u;
  observation.timing.entryTimerCountMax = 50u;
  observation.timing.pendingEntryTimerCountMax = 40u;
  observation.timing.lateEntryCount = 2u;
  observation.timing.entryScheduleOverrunMaxCycles = 60u;
  return observation;
}

CoordinatedXyPerformanceReport::MoveObservation acceptedCompleteStepMove(
    uint32_t x,
    uint32_t y,
    uint32_t master,
    uint32_t rate,
    uint32_t targetArr,
    uint32_t startArr) {
  auto observation = acceptedMove(x, y, master, rate, targetArr, startArr);
  observation.interruptsPerMasterStep = 1u;
  observation.executionMode =
      CoordinatedXyExecutor::ExecutionMode::CompleteStep;
  observation.minimumPulseCoreCycles = 360u;
  observation.timer2Callbacks = master;
  observation.timing.totalCallbacks = master;
  observation.timing.phaseCallbacks[1] = master - 5u;
  observation.timing.irqPathSamples = master;
  observation.timing.entryTimerSamples = master;
  observation.timing.completeStepPulseSamples = master;
  observation.timing.completeStepPulseMinCycles = 360u;
  observation.timing.completeStepPulseMaxCycles = 420u;
  observation.timing.deadlineSamples = master;
  observation.timing.deadlineSlackMinTicks = 700u;
  return observation;
}

}  // namespace

TEST_GROUP(CoordinatedXyPerformanceReport) {
};

TEST(CoordinatedXyPerformanceReport, BoundsHomeGuardFromKnownPositionOrEnvelope) {
  UNSIGNED_LONGS_EQUAL(
      11916u,
      CoordinatedXyPerformanceReport::boundedHomeGuardSteps(
          8916, 45000u, 3000u, 3000u, true));
  UNSIGNED_LONGS_EQUAL(
      48000u,
      CoordinatedXyPerformanceReport::boundedHomeGuardSteps(
          0, 45000u, 3000u, 3000u, false));
  UNSIGNED_LONGS_EQUAL(
      38000u,
      CoordinatedXyPerformanceReport::boundedHomeGuardSteps(
          -1, 35000u, 3000u, 3000u, true));
  UNSIGNED_LONGS_EQUAL(
      3000u,
      CoordinatedXyPerformanceReport::boundedHomeGuardSteps(
          100, 45000u, 100u, 3000u, true));
  UNSIGNED_LONGS_EQUAL(
      0xFFFFFFFFu,
      CoordinatedXyPerformanceReport::boundedHomeGuardSteps(
          0, 0xFFFFFFFFu, 1u, 1u, false));
}

TEST(CoordinatedXyPerformanceReport, AcceptsExactSafeMoveWithinBudgets) {
  const auto observation = acceptedMove(500u, 1500u, 1500u, 3000u, 14999u, 74995u);
  UNSIGNED_LONGS_EQUAL(
      0u,
      CoordinatedXyPerformanceReport::moveFailureMask(
          observation, CoordinatedXyPerformanceReport::Limits{}));
  CHECK_TRUE(CoordinatedXyPerformanceReport::movePasses(
      observation, CoordinatedXyPerformanceReport::Limits{}));
}

TEST(CoordinatedXyPerformanceReport, AcceptsCompleteStepMoveWithOneInterrupt) {
  const auto observation = acceptedCompleteStepMove(
      20000u, 5000u, 20000u, 40000u, 1124u, 5620u);
  UNSIGNED_LONGS_EQUAL(
      0u,
      CoordinatedXyPerformanceReport::moveFailureMask(
          observation, CoordinatedXyPerformanceReport::Limits{}));
}

TEST(CoordinatedXyPerformanceReport, RearmModeRequiresEveryNonterminalCallback) {
  auto observation =
      acceptedMove(500u, 1500u, 1500u, 20000u, 2249u, 11245u);
  observation.timerScheduleMode =
      CoordinatedXyTimerSchedulePolicy::Mode::RearmFromActualEdge;
  observation.timerRearmCount = observation.timer2Callbacks - 1u;
  observation.timerRearmDelayMaxCycles = 24u;
  CHECK_TRUE(CoordinatedXyPerformanceReport::movePasses(
      observation, CoordinatedXyPerformanceReport::Limits{}));

  --observation.timerRearmCount;
  CHECK_TRUE((CoordinatedXyPerformanceReport::moveFailureMask(
                  observation, CoordinatedXyPerformanceReport::Limits{}) &
              CoordinatedXyPerformanceReport::kMoveFailureTimerRearm) != 0u);

  ++observation.timerRearmCount;
  observation.timerRearmPendingCount = 1u;
  CHECK_TRUE((CoordinatedXyPerformanceReport::moveFailureMask(
                  observation, CoordinatedXyPerformanceReport::Limits{}) &
              CoordinatedXyPerformanceReport::kMoveFailureTimerRearm) != 0u);
}

TEST(CoordinatedXyPerformanceReport, ConditionalModeRequiresLateInjectionEvidence) {
  auto observation =
      acceptedMove(500u, 1500u, 1500u, 20000u, 2249u, 11245u);
  observation.timerScheduleMode =
      CoordinatedXyTimerSchedulePolicy::Mode::ConditionalLateRearm;
  observation.conditionalDecisionCount = observation.timer2Callbacks - 1u;
  observation.timerRearmCount = 1u;
  observation.timerRearmDelayMaxCycles = 24u;
  observation.conditionalNonRearmSlackMinTicks = 1126u;
  observation.lateInjectionCount = 1u;
  observation.lateInjectionRearmCount = 1u;
  observation.lateInjectionDecisionSlackMaxTicks = 905u;
  observation.lateInjectionWaitMaxCycles = 2800u;
  observation.timing.intentionalWaitCycleSum = 2800u;
  observation.timing.intentionalWaitMaxCycles = 2800u;
  CHECK_TRUE(CoordinatedXyPerformanceReport::movePasses(
      observation, CoordinatedXyPerformanceReport::Limits{}));

  observation.lateInjectionRearmCount = 0u;
  CHECK_TRUE((CoordinatedXyPerformanceReport::moveFailureMask(
                  observation, CoordinatedXyPerformanceReport::Limits{}) &
              CoordinatedXyPerformanceReport::kMoveFailureTimerRearm) != 0u);
  observation.lateInjectionRearmCount = 1u;
  observation.conditionalNonRearmSlackMinTicks = 1125u;
  CHECK_TRUE((CoordinatedXyPerformanceReport::moveFailureMask(
                  observation, CoordinatedXyPerformanceReport::Limits{}) &
              CoordinatedXyPerformanceReport::kMoveFailureTimerRearm) != 0u);
}

TEST(CoordinatedXyPerformanceReport, CompleteStepMoveFailsClosedOnPulseOrDeadline) {
  auto observation = acceptedCompleteStepMove(
      20000u, 5000u, 20000u, 40000u, 1124u, 5620u);
  observation.timing.completeStepPulseMinCycles = 359u;
  CHECK_TRUE((CoordinatedXyPerformanceReport::moveFailureMask(
                  observation, CoordinatedXyPerformanceReport::Limits{}) &
              CoordinatedXyPerformanceReport::kMoveFailurePulseTiming) != 0u);

  observation = acceptedCompleteStepMove(
      20000u, 5000u, 20000u, 40000u, 1124u, 5620u);
  observation.timing.deadlineMissing = 1u;
  CHECK_TRUE((CoordinatedXyPerformanceReport::moveFailureMask(
                  observation, CoordinatedXyPerformanceReport::Limits{}) &
              CoordinatedXyPerformanceReport::kMoveFailureDeadlineSlack) != 0u);

  observation = acceptedCompleteStepMove(
      20000u, 5000u, 20000u, 40000u, 1124u, 5620u);
  observation.executionMode = CoordinatedXyExecutor::ExecutionMode::TwoEdge;
  CHECK_TRUE((CoordinatedXyPerformanceReport::moveFailureMask(
                  observation, CoordinatedXyPerformanceReport::Limits{}) &
              CoordinatedXyPerformanceReport::kMoveFailureExecutionMode) != 0u);
}

TEST(CoordinatedXyPerformanceReport, ClassifiesFailedMoveGatesCompactly) {
  auto observation =
      acceptedMove(20000u, 0u, 20000u, 40000u, 1124u, 5620u);
  observation.timing.phaseMaxCycles[1] = 2026u;
  observation.durationErrorBasisPoints = 101u;
  observation.statusPeriodMaxMs = 101u;

  const uint32_t failures =
      CoordinatedXyPerformanceReport::moveFailureMask(
          observation, CoordinatedXyPerformanceReport::Limits{});

  UNSIGNED_LONGS_EQUAL(
      CoordinatedXyPerformanceReport::kMoveFailureActiveCycles |
          CoordinatedXyPerformanceReport::kMoveFailureDuration |
          CoordinatedXyPerformanceReport::kMoveFailureStatusPeriod,
      failures);
  CHECK_FALSE(CoordinatedXyPerformanceReport::movePasses(
      observation, CoordinatedXyPerformanceReport::Limits{}));
}

TEST(CoordinatedXyPerformanceReport, CompletedTimingFailuresRemainCollectible) {
  const CoordinatedXyPerformanceReport::Limits limits{};
  auto observation =
      acceptedMove(20000u, 0u, 20000u, 20000u, 2249u, 11245u);
  observation.timing.pendingObservations = 1u;
  observation.timing.maxPendingStreak = 1u;
  observation.timing.cycleWraps = 2u;
  observation.timing.phaseMaxCycles[1] = 2026u;
  observation.timing.terminalMaxCycles = 2251u;
  observation.durationErrorBasisPoints = 101u;
  observation.statusPeriodMaxMs = 101u;
  observation.statusWatchdogAgeMaxMs = 101u;
  observation.statusAlternationErrors = 1u;
  observation.minimumDeadlineSlackTicks = 450u;
  observation.timing.deadlineSamples = observation.timer2Callbacks - 1u;
  observation.timing.deadlineSlackMinTicks = 449u;
  observation.requireNoLateEntries = true;
  observation.timing.lateEntryCount = 1u;

  CHECK_FALSE(CoordinatedXyPerformanceReport::movePasses(
      observation, limits));
  CHECK_TRUE(CoordinatedXyPerformanceReport::moveCanContinueAfterCompletion(
      observation, limits));
  UNSIGNED_LONGS_EQUAL(
      CoordinatedXyPerformanceReport::kMoveCollectionSoftFailureMask &
          ~CoordinatedXyPerformanceReport::kMoveFailureTimerRearm,
      CoordinatedXyPerformanceReport::moveFailureMask(observation, limits));

  observation.timerRearmCount = 1u;
  CHECK_TRUE(CoordinatedXyPerformanceReport::moveCanContinueAfterCompletion(
      observation, limits));
  CHECK_TRUE((CoordinatedXyPerformanceReport::moveFailureMask(
                  observation, limits) &
              CoordinatedXyPerformanceReport::kMoveFailureTimerRearm) != 0u);
}

TEST(CoordinatedXyPerformanceReport, IntegrityAndSafetyFailuresStopCollection) {
  const CoordinatedXyPerformanceReport::Limits limits{};
  auto observation =
      acceptedMove(20000u, 0u, 20000u, 20000u, 2249u, 11245u);
  observation.endpointMatches = false;
  CHECK_FALSE(CoordinatedXyPerformanceReport::moveCanContinueAfterCompletion(
      observation, limits));

  observation =
      acceptedMove(20000u, 0u, 20000u, 20000u, 2249u, 11245u);
  observation.terminalReason =
      CoordinatedXyExecutor::TerminalReason::PlannerFault;
  CHECK_FALSE(CoordinatedXyPerformanceReport::moveCanContinueAfterCompletion(
      observation, limits));

  observation =
      acceptedMove(20000u, 0u, 20000u, 20000u, 2249u, 11245u);
  observation.timerScheduleSaturationFlags = 1u;
  CHECK_FALSE(CoordinatedXyPerformanceReport::moveCanContinueAfterCompletion(
      observation, limits));

  observation =
      acceptedMove(20000u, 0u, 20000u, 20000u, 2249u, 11245u);
  observation.watchdogLateCount = 1u;
  CHECK_FALSE(CoordinatedXyPerformanceReport::moveCanContinueAfterCompletion(
      observation, limits));
}

TEST(CoordinatedXyPerformanceReport, FailureTelemetryIgnoresPassingMove) {
  CoordinatedXyPerformanceReport::FailureTelemetry telemetry{};

  CoordinatedXyPerformanceReport::captureFirstFailure(
      telemetry,
      true,
      CoordinatedXyExecutor::TerminalReason::Completed,
      0u,
      0u);

  CHECK_FALSE(telemetry.valid);
  CHECK_EQUAL(
      static_cast<int>(CoordinatedXyExecutor::TerminalReason::None),
      static_cast<int>(telemetry.terminalReason));
  UNSIGNED_LONGS_EQUAL(0u, telemetry.limitAbortRequestCount);
  UNSIGNED_LONGS_EQUAL(0u, telemetry.rawLimitAbortCount);
  UNSIGNED_LONGS_EQUAL(0u, telemetry.failureMask);
}

TEST(CoordinatedXyPerformanceReport, FailureTelemetryCapturesFirstLimitAbort) {
  CoordinatedXyPerformanceReport::FailureTelemetry telemetry{};

  CoordinatedXyPerformanceReport::captureFirstFailure(
      telemetry,
      false,
      CoordinatedXyExecutor::TerminalReason::XLimit,
      1u,
      2u,
      CoordinatedXyPerformanceReport::kMoveFailureTerminalReason);
  CoordinatedXyPerformanceReport::captureFirstFailure(
      telemetry,
      false,
      CoordinatedXyExecutor::TerminalReason::PlannerFault,
      3u,
      4u,
      CoordinatedXyPerformanceReport::kMoveFailureTimingState);

  CHECK_TRUE(telemetry.valid);
  CHECK_EQUAL(
      static_cast<int>(CoordinatedXyExecutor::TerminalReason::XLimit),
      static_cast<int>(telemetry.terminalReason));
  UNSIGNED_LONGS_EQUAL(1u, telemetry.limitAbortRequestCount);
  UNSIGNED_LONGS_EQUAL(2u, telemetry.rawLimitAbortCount);
  UNSIGNED_LONGS_EQUAL(
      CoordinatedXyPerformanceReport::kMoveFailureTerminalReason,
      telemetry.failureMask);
}

TEST(CoordinatedXyPerformanceReport, RejectsEverySafetyAndTimingMismatch) {
  auto observation = acceptedMove(1000u, 1000u, 1000u, 40000u, 3802u, 19010u);
  observation.timer2Callbacks++;
  CHECK_FALSE(CoordinatedXyPerformanceReport::movePasses(
      observation, CoordinatedXyPerformanceReport::Limits{}));
  observation = acceptedMove(1000u, 1000u, 1000u, 40000u, 3802u, 19010u);
  observation.timing.pendingObservations = 1u;
  CHECK_FALSE(CoordinatedXyPerformanceReport::movePasses(
      observation, CoordinatedXyPerformanceReport::Limits{}));
  observation = acceptedMove(1000u, 1000u, 1000u, 40000u, 3802u, 19010u);
  observation.timing.phaseMaxCycles[0] = 2026u;
  CHECK_FALSE(CoordinatedXyPerformanceReport::movePasses(
      observation, CoordinatedXyPerformanceReport::Limits{}));
  observation = acceptedMove(1000u, 1000u, 1000u, 40000u, 3802u, 19010u);
  observation.timing.terminalMaxCycles = 2251u;
  CHECK_FALSE(CoordinatedXyPerformanceReport::movePasses(
      observation, CoordinatedXyPerformanceReport::Limits{}));
  observation = acceptedMove(1000u, 1000u, 1000u, 40000u, 3802u, 19010u);
  observation.watchdogLateCount = 1u;
  CHECK_FALSE(CoordinatedXyPerformanceReport::movePasses(
      observation, CoordinatedXyPerformanceReport::Limits{}));
  observation = acceptedMove(1000u, 1000u, 1000u, 40000u, 3802u, 19010u);
  observation.timing.cycleWraps = 2u;
  CHECK_FALSE(CoordinatedXyPerformanceReport::movePasses(
      observation, CoordinatedXyPerformanceReport::Limits{}));
}

TEST(CoordinatedXyPerformanceReport, AcceptsOneHandledCycleWrapPerMove) {
  auto observation =
      acceptedMove(20000u, 0u, 20000u, 5000u, 8999u, 44995u);
  observation.timing.cycleWraps = 1u;

  CHECK_TRUE(CoordinatedXyPerformanceReport::movePasses(
      observation, CoordinatedXyPerformanceReport::Limits{}));

  CoordinatedXyPerformanceReport::Aggregate aggregate{};
  const CoordinatedXyPerformanceReport::Limits limits{};
  CoordinatedXyPerformanceReport::addMove(aggregate, observation, limits);
  UNSIGNED_LONGS_EQUAL(1u, aggregate.cycleWraps);
  CHECK_TRUE(CoordinatedXyPerformanceReport::aggregatePasses(
      aggregate, 1u, 20000u, 0u, 20000u, limits));
}

TEST(CoordinatedXyPerformanceReport, AggregatesMovesAndPhaseMeans) {
  CoordinatedXyPerformanceReport::Aggregate aggregate{};
  const CoordinatedXyPerformanceReport::Limits limits{};
  const auto first = acceptedMove(20000u, 0u, 20000u, 40000u, 1124u, 5620u);
  const auto second = acceptedMove(0u, 20000u, 20000u, 40000u, 1124u, 5620u);
  CoordinatedXyPerformanceReport::addMove(aggregate, first, limits);
  CoordinatedXyPerformanceReport::addMove(aggregate, second, limits);

  CHECK_TRUE(CoordinatedXyPerformanceReport::aggregatePasses(
      aggregate, 2u, 20000u, 20000u, 40000u, limits));
  UNSIGNED_LONGS_EQUAL(80000u, aggregate.timer2Callbacks);
  UNSIGNED_LONGS_EQUAL(80000u, aggregate.irqPathSamples);
  UNSIGNED_LONGS_EQUAL(10u,
      CoordinatedXyPerformanceReport::preHandlerMeanCycles(aggregate));
  UNSIGNED_LONGS_EQUAL(20u,
      CoordinatedXyPerformanceReport::fullIrqMeanCycles(aggregate));
  UNSIGNED_LONGS_EQUAL(1900u, aggregate.terminalFullIrqMaxCycles);
  UNSIGNED_LONGS_EQUAL(850u, aggregate.activeFullIrqMaxCycles);
  UNSIGNED_LONGS_EQUAL(80000u, aggregate.entryTimerSamples);
  UNSIGNED_LONGS_EQUAL(20u,
      CoordinatedXyPerformanceReport::entryTimerMeanTicks(aggregate));
  UNSIGNED_LONGS_EQUAL(50u, aggregate.entryTimerCountMax);
  UNSIGNED_LONGS_EQUAL(40u, aggregate.pendingEntryTimerCountMax);
  UNSIGNED_LONGS_EQUAL(4u, aggregate.lateEntryCount);
  UNSIGNED_LONGS_EQUAL(60u, aggregate.entryScheduleOverrunMaxCycles);
  UNSIGNED_LONGS_EQUAL(
      500u,
      CoordinatedXyPerformanceReport::phaseMeanCycles(
          aggregate, CoordinatedXyIsrInstrumentation::Phase::Acceleration));
}

TEST(CoordinatedXyPerformanceReport, AggregatesCompleteStepPulseEvidence) {
  CoordinatedXyPerformanceReport::Aggregate aggregate{};
  const CoordinatedXyPerformanceReport::Limits limits{};
  CoordinatedXyPerformanceReport::addMove(
      aggregate,
      acceptedCompleteStepMove(
          20000u, 0u, 20000u, 40000u, 1124u, 5620u),
      limits);
  CoordinatedXyPerformanceReport::addMove(
      aggregate,
      acceptedCompleteStepMove(
          0u, 20000u, 20000u, 40000u, 1124u, 5620u),
      limits);

  CHECK_TRUE(CoordinatedXyPerformanceReport::aggregatePasses(
      aggregate, 2u, 20000u, 20000u, 40000u, limits));
  UNSIGNED_LONGS_EQUAL(1u, aggregate.interruptsPerMasterStep);
  UNSIGNED_LONGS_EQUAL(40000u, aggregate.timer2Callbacks);
  UNSIGNED_LONGS_EQUAL(40000u, aggregate.completeStepPulseSamples);
  UNSIGNED_LONGS_EQUAL(360u, aggregate.completeStepPulseMinCycles);
  UNSIGNED_LONGS_EQUAL(420u, aggregate.completeStepPulseMaxCycles);
  UNSIGNED_LONGS_EQUAL(40000u, aggregate.deadlineSamples);
  UNSIGNED_LONGS_EQUAL(700u, aggregate.deadlineSlackMinTicks);
}

TEST(CoordinatedXyPerformanceReport, BuildsCompactDeterministicMetrics) {
  CoordinatedXyPerformanceReport::Aggregate aggregate{};
  const CoordinatedXyPerformanceReport::Limits limits{};
  CoordinatedXyPerformanceReport::addMove(
      aggregate,
      acceptedMove(20000u, 5000u, 20000u, 40000u, 1124u, 5620u),
      limits);
  char metrics[256] = {};
  const size_t length = CoordinatedXyPerformanceReport::buildMetrics(
      metrics, sizeof(metrics), 40000u, aggregate, 3u, 4u);

  CHECK_TRUE(length > 0u);
  STRCMP_CONTAINS("hz=40000;n=1;xe=20000;ye=5000;ms=20000;i2=40000;i7=0;ok=1", metrics);
  STRCMP_CONTAINS("pu=0;ps=0", metrics);
  STRCMP_CONTAINS("cw=0;qf=0;qm=0;sf=0", metrics);
  STRCMP_CONTAINS("xd=3;yd=4;to=0", metrics);
  CHECK_TRUE(length <= 198u);
}

TEST(CoordinatedXyPerformanceReport, AggregatesStrictFailuresWithoutLosingMove) {
  CoordinatedXyPerformanceReport::Aggregate aggregate{};
  const CoordinatedXyPerformanceReport::Limits limits{};
  auto observation =
      acceptedMove(20000u, 0u, 20000u, 20000u, 2249u, 11245u);
  observation.timing.terminalMaxCycles = 2251u;

  CoordinatedXyPerformanceReport::addMove(aggregate, observation, limits);

  UNSIGNED_LONGS_EQUAL(1u, aggregate.moveCount);
  UNSIGNED_LONGS_EQUAL(1u, aggregate.qualificationFailureMoveCount);
  UNSIGNED_LONGS_EQUAL(
      CoordinatedXyPerformanceReport::kMoveFailureTerminalCycles,
      aggregate.qualificationFailureMask);
  CHECK_FALSE(aggregate.exactAndSafe);
}

TEST(CoordinatedXyPerformanceReport, LargestPlannedAggregateFitsResultFrameBudget) {
  CoordinatedXyPerformanceReport::Aggregate aggregate{};
  aggregate.moveCount = 390u;
  aggregate.emittedXSteps = 90000u;
  aggregate.emittedYSteps = 362000u;
  aggregate.masterSteps = 412000u;
  aggregate.timer2Callbacks = 824000u;
  aggregate.phaseCallbacks[0] = 200000u;
  aggregate.phaseCallbacks[1] = 300000u;
  aggregate.phaseCallbacks[2] = 323999u;
  aggregate.phaseCycleSums[0] = 180000000u;
  aggregate.phaseCycleSums[1] = 150000000u;
  aggregate.phaseCycleSums[2] = 259199200u;
  aggregate.phaseMaxCycles[0] = 1800u;
  aggregate.phaseMaxCycles[1] = 1500u;
  aggregate.phaseMaxCycles[2] = 1900u;
  aggregate.terminalMaxCycles = 2200u;
  aggregate.durationErrorMaxBasisPoints = 99u;
  aggregate.statusPeriodMaxMs = 99u;
  aggregate.statusWatchdogAgeMaxMs = 99u;
  aggregate.qualificationFailureMoveCount = 10u;
  aggregate.qualificationFailureMask = 0xFFFFFFFFu;
  char metrics[224] = {};

  const size_t length = CoordinatedXyPerformanceReport::buildMetrics(
      metrics, sizeof(metrics), 40000u, aggregate, 25u, 25u);

  CHECK_TRUE(length > 0u);
  CHECK_TRUE(length <= 203u);
}

TEST(CoordinatedXyPerformanceReport, RejectsAggregateExpectedCountMismatch) {
  CoordinatedXyPerformanceReport::Aggregate aggregate{};
  const CoordinatedXyPerformanceReport::Limits limits{};
  CoordinatedXyPerformanceReport::addMove(
      aggregate,
      acceptedMove(100u, 0u, 100u, 5000u, 8999u, 44995u),
      limits);
  CHECK_FALSE(CoordinatedXyPerformanceReport::aggregatePasses(
      aggregate, 2u, 100u, 0u, 100u, limits));
}
