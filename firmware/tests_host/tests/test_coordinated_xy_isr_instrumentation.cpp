#include "CppUTest/TestHarness.h"
#include "CoordinatedXyIsrInstrumentation.h"

#include <cstdint>
#include <limits>

using CoordinatedXyIsrInstrumentation::Phase;
using CoordinatedXyIsrInstrumentation::State;

TEST_GROUP(CoordinatedXyIsrInstrumentation) {
};

TEST(CoordinatedXyIsrInstrumentation, ResetCreatesFreshActiveState) {
  State state{};
  state.totalCallbacks = 99u;
  CoordinatedXyIsrInstrumentation::reset(state, 123u);

  const auto snapshot = CoordinatedXyIsrInstrumentation::makeSnapshot(state);
  CHECK_TRUE(snapshot.valid);
  CHECK_TRUE(snapshot.active);
  CHECK_FALSE(snapshot.aborted);
  UNSIGNED_LONGS_EQUAL(123u, snapshot.startCycle);
  UNSIGNED_LONGS_EQUAL(0u, snapshot.totalCallbacks);
}

TEST(CoordinatedXyIsrInstrumentation, TracksActivePhasesAndSeparatesTerminalCost) {
  State state{};
  CoordinatedXyIsrInstrumentation::reset(state, 100u);
  CoordinatedXyIsrInstrumentation::recordSample(
      state, Phase::Acceleration, 110u, 150u, 99u, false, false, false);
  CoordinatedXyIsrInstrumentation::recordSample(
      state, Phase::Acceleration, 200u, 260u, 89u, true, true, false);
  CoordinatedXyIsrInstrumentation::recordSample(
      state, Phase::Cruise, 300u, 330u, 79u, true, false, false);
  CoordinatedXyIsrInstrumentation::recordSample(
      state, Phase::Deceleration, 400u, 450u, 99u, false, true, false);
  CoordinatedXyIsrInstrumentation::recordSample(
      state, Phase::Deceleration, 500u, 700u, 99u, false, true, true);

  const auto snapshot = CoordinatedXyIsrInstrumentation::makeSnapshot(state);
  CHECK_FALSE(snapshot.active);
  UNSIGNED_LONGS_EQUAL(5u, snapshot.totalCallbacks);
  UNSIGNED_LONGS_EQUAL(3u, snapshot.completedPulses);
  UNSIGNED_LONGS_EQUAL(2u, snapshot.phaseCallbacks[0]);
  UNSIGNED_LONGS_EQUAL(1u, snapshot.phaseCallbacks[1]);
  UNSIGNED_LONGS_EQUAL(1u, snapshot.phaseCallbacks[2]);
  UNSIGNED_LONGS_EQUAL(100u, snapshot.phaseCycleSums[0]);
  UNSIGNED_LONGS_EQUAL(30u, snapshot.phaseCycleSums[1]);
  UNSIGNED_LONGS_EQUAL(50u, snapshot.phaseCycleSums[2]);
  UNSIGNED_LONGS_EQUAL(60u, snapshot.phaseMaxCycles[0]);
  UNSIGNED_LONGS_EQUAL(30u, snapshot.phaseMaxCycles[1]);
  UNSIGNED_LONGS_EQUAL(50u, snapshot.phaseMaxCycles[2]);
  UNSIGNED_LONGS_EQUAL(1u, snapshot.terminalCallbacks);
  UNSIGNED_LONGS_EQUAL(200u, snapshot.terminalCycleSum);
  UNSIGNED_LONGS_EQUAL(200u, snapshot.terminalMaxCycles);
  UNSIGNED_LONGS_EQUAL(2u, snapshot.pendingObservations);
  UNSIGNED_LONGS_EQUAL(2u, snapshot.maxPendingStreak);
  UNSIGNED_LONGS_EQUAL(470u, snapshot.scheduledTimerTicks);
  UNSIGNED_LONGS_EQUAL(50u,
      CoordinatedXyIsrInstrumentation::phaseMeanCycles(
          snapshot, Phase::Acceleration));
  UNSIGNED_LONGS_EQUAL(200u,
      CoordinatedXyIsrInstrumentation::terminalMeanCycles(snapshot));
}

TEST(CoordinatedXyIsrInstrumentation, PendingStreakResetsAfterClearSample) {
  State state{};
  CoordinatedXyIsrInstrumentation::reset(state, 0u);
  CoordinatedXyIsrInstrumentation::recordSample(
      state, Phase::Cruise, 1u, 2u, 0u, true, false, false);
  CoordinatedXyIsrInstrumentation::recordSample(
      state, Phase::Cruise, 3u, 4u, 0u, true, false, false);
  CoordinatedXyIsrInstrumentation::recordSample(
      state, Phase::Cruise, 5u, 6u, 0u, false, false, false);
  CoordinatedXyIsrInstrumentation::recordSample(
      state, Phase::Cruise, 7u, 8u, 0u, true, false, true);

  const auto snapshot = CoordinatedXyIsrInstrumentation::makeSnapshot(state);
  UNSIGNED_LONGS_EQUAL(3u, snapshot.pendingObservations);
  UNSIGNED_LONGS_EQUAL(2u, snapshot.maxPendingStreak);
}

TEST(CoordinatedXyIsrInstrumentation, CompletionIncludesRecorderCostInPhaseAndTerminalTiming) {
  State state{};
  CoordinatedXyIsrInstrumentation::reset(state, 100u);
  CoordinatedXyIsrInstrumentation::recordSample(
      state, Phase::Acceleration, 110u, 150u, 99u, false, false, false);
  CoordinatedXyIsrInstrumentation::completeSampleTiming(
      state, Phase::Acceleration, 110u, 150u, 175u, false);
  CoordinatedXyIsrInstrumentation::recordSample(
      state, Phase::Deceleration, 200u, 260u, 99u, false, true, true);
  CoordinatedXyIsrInstrumentation::completeSampleTiming(
      state, Phase::Deceleration, 200u, 260u, 300u, true);

  const auto snapshot = CoordinatedXyIsrInstrumentation::makeSnapshot(state);
  UNSIGNED_LONGS_EQUAL(65u, snapshot.phaseCycleSums[0]);
  UNSIGNED_LONGS_EQUAL(65u, snapshot.phaseMaxCycles[0]);
  UNSIGNED_LONGS_EQUAL(100u, snapshot.terminalCycleSum);
  UNSIGNED_LONGS_EQUAL(100u, snapshot.terminalMaxCycles);
  UNSIGNED_LONGS_EQUAL(100u, snapshot.maxCycles);
  UNSIGNED_LONGS_EQUAL(200u, snapshot.durationCycles);
}

TEST(CoordinatedXyIsrInstrumentation, TracksOuterIrqPathAndCorrelatesPendingSample) {
  State state{};
  CoordinatedXyIsrInstrumentation::reset(state, 100u);
  CoordinatedXyIsrInstrumentation::recordSample(
      state, Phase::Acceleration, 110u, 150u, 99u, true, false, false);
  CoordinatedXyIsrInstrumentation::completeSampleTiming(
      state, Phase::Acceleration, 110u, 150u, 175u, false);
  CoordinatedXyIsrInstrumentation::beginIrqPathSample(
      state, true, 105u, true, 130u, 99u, 110u, true, false);
  CoordinatedXyIsrInstrumentation::completeIrqPath(state, 175u);
  CoordinatedXyIsrInstrumentation::recordSample(
      state, Phase::Deceleration, 200u, 260u, 99u, false, true, true);
  CoordinatedXyIsrInstrumentation::completeSampleTiming(
      state, Phase::Deceleration, 200u, 260u, 300u, true);
  CoordinatedXyIsrInstrumentation::beginIrqPathSample(
      state, true, 190u, true, 20u, 99u, 200u, false, true);
  CoordinatedXyIsrInstrumentation::completeIrqPath(state, 300u);

  const auto snapshot = CoordinatedXyIsrInstrumentation::makeSnapshot(state);
  UNSIGNED_LONGS_EQUAL(2u, snapshot.irqPathSamples);
  UNSIGNED_LONGS_EQUAL(0u, snapshot.irqPathMissing);
  UNSIGNED_LONGS_EQUAL(15u, snapshot.preHandlerCycleSum);
  UNSIGNED_LONGS_EQUAL(10u, snapshot.preHandlerMaxCycles);
  UNSIGNED_LONGS_EQUAL(180u, snapshot.fullIrqCycleSum);
  UNSIGNED_LONGS_EQUAL(110u, snapshot.fullIrqMaxCycles);
  UNSIGNED_LONGS_EQUAL(70u, snapshot.activeFullIrqMaxCycles);
  UNSIGNED_LONGS_EQUAL(110u, snapshot.terminalFullIrqMaxCycles);
  UNSIGNED_LONGS_EQUAL(5u, snapshot.pendingPreHandlerMaxCycles);
  UNSIGNED_LONGS_EQUAL(70u, snapshot.pendingFullIrqMaxCycles);
  UNSIGNED_LONGS_EQUAL(2u, snapshot.entryTimerSamples);
  UNSIGNED_LONGS_EQUAL(0u, snapshot.entryTimerMissing);
  UNSIGNED_LONGS_EQUAL(150u, snapshot.entryTimerCountSum);
  UNSIGNED_LONGS_EQUAL(130u, snapshot.entryTimerCountMax);
  UNSIGNED_LONGS_EQUAL(130u, snapshot.pendingEntryTimerCountMax);
  UNSIGNED_LONGS_EQUAL(1u, snapshot.lateEntryCount);
  UNSIGNED_LONGS_EQUAL(0u, snapshot.entryScheduleOverrunMaxCycles);
  UNSIGNED_LONGS_EQUAL(
      75u, CoordinatedXyIsrInstrumentation::entryTimerMeanTicks(snapshot));
  UNSIGNED_LONGS_EQUAL(
      7u, CoordinatedXyIsrInstrumentation::preHandlerMeanCycles(snapshot));
  UNSIGNED_LONGS_EQUAL(
      90u, CoordinatedXyIsrInstrumentation::fullIrqMeanCycles(snapshot));
}

TEST(CoordinatedXyIsrInstrumentation, CountsMissingOuterIrqEntrySample) {
  State state{};
  CoordinatedXyIsrInstrumentation::reset(state, 0u);
  CoordinatedXyIsrInstrumentation::recordSample(
      state, Phase::Cruise, 1u, 2u, 0u, false, false, true);
  CoordinatedXyIsrInstrumentation::beginIrqPathSample(
      state, false, 0u, false, 0u, 0u, 1u, false, true);

  const auto snapshot = CoordinatedXyIsrInstrumentation::makeSnapshot(state);
  UNSIGNED_LONGS_EQUAL(0u, snapshot.irqPathSamples);
  UNSIGNED_LONGS_EQUAL(1u, snapshot.irqPathMissing);
  UNSIGNED_LONGS_EQUAL(0u, snapshot.entryTimerSamples);
  UNSIGNED_LONGS_EQUAL(1u, snapshot.entryTimerMissing);
  UNSIGNED_LONGS_EQUAL(
      0u, CoordinatedXyIsrInstrumentation::preHandlerMeanCycles(snapshot));
  UNSIGNED_LONGS_EQUAL(
      0u, CoordinatedXyIsrInstrumentation::fullIrqMeanCycles(snapshot));
}

TEST(CoordinatedXyIsrInstrumentation, OuterIrqPathUsesUnsignedWrapArithmetic) {
  State state{};
  CoordinatedXyIsrInstrumentation::reset(state, 0xFFFFFFE0u);
  CoordinatedXyIsrInstrumentation::recordSample(
      state, Phase::Cruise, 0xFFFFFFF5u, 0x00000010u, 0u,
      false, true, true);
  CoordinatedXyIsrInstrumentation::completeSampleTiming(
      state, Phase::Cruise, 0xFFFFFFF5u, 0x00000010u, 0x00000020u,
      true);
  CoordinatedXyIsrInstrumentation::beginIrqPathSample(
      state, true, 0xFFFFFFF0u, true, 7u, 15u,
      0xFFFFFFF5u, false, true);
  CoordinatedXyIsrInstrumentation::completeIrqPath(state, 0x00000020u);

  const auto snapshot = CoordinatedXyIsrInstrumentation::makeSnapshot(state);
  UNSIGNED_LONGS_EQUAL(5u, snapshot.preHandlerMaxCycles);
  UNSIGNED_LONGS_EQUAL(48u, snapshot.fullIrqMaxCycles);
  UNSIGNED_LONGS_EQUAL(48u, snapshot.terminalFullIrqMaxCycles);
}

TEST(CoordinatedXyIsrInstrumentation, CalculatesDurationAcrossCycleWrap) {
  State state{};
  CoordinatedXyIsrInstrumentation::reset(state, 0xFFFFFFF0u);
  CoordinatedXyIsrInstrumentation::recordSample(
      state, Phase::Cruise, 0xFFFFFFF5u, 0x00000010u, 15u,
      false, true, true);

  const auto snapshot = CoordinatedXyIsrInstrumentation::makeSnapshot(state);
  UNSIGNED_LONGS_EQUAL(1u, snapshot.cycleWraps);
  UNSIGNED_LONGS_EQUAL(32u, snapshot.durationCycles);
}

TEST(CoordinatedXyIsrInstrumentation, ComputesDurationErrorInTaskContext) {
  CoordinatedXyIsrInstrumentation::Snapshot snapshot{};
  snapshot.valid = true;
  snapshot.durationCycles = 180000u;
  snapshot.scheduledTimerTicks = 90000u;
  UNSIGNED_LONGS_EQUAL(
      0u,
      CoordinatedXyIsrInstrumentation::durationErrorBasisPoints(
          snapshot, 180000000u, 90000000u));

  snapshot.durationCycles = 181800u;
  UNSIGNED_LONGS_EQUAL(
      100u,
      CoordinatedXyIsrInstrumentation::durationErrorBasisPoints(
          snapshot, 180000000u, 90000000u));

  snapshot.scheduledTimerTicks = 0u;
  UNSIGNED_LONGS_EQUAL(
      std::numeric_limits<uint32_t>::max(),
      CoordinatedXyIsrInstrumentation::durationErrorBasisPoints(
          snapshot, 180000000u, 90000000u));
}

TEST(CoordinatedXyIsrInstrumentation, SaturatesInsteadOfWrapping) {
  State state{};
  CoordinatedXyIsrInstrumentation::reset(state, 0u);
  state.totalCallbacks = std::numeric_limits<uint32_t>::max();
  state.completedPulses = std::numeric_limits<uint32_t>::max();
  state.phaseCallbacks[0] = std::numeric_limits<uint32_t>::max();
  state.phaseCycleSums[0] = std::numeric_limits<uint32_t>::max();
  state.pendingObservations = std::numeric_limits<uint32_t>::max();
  state.currentPendingStreak = std::numeric_limits<uint32_t>::max();
  state.scheduledTimerTicks = std::numeric_limits<uint32_t>::max();
  state.irqPathSamples = std::numeric_limits<uint32_t>::max();
  state.preHandlerCycleSum = std::numeric_limits<uint32_t>::max();
  state.fullIrqCycleSum = std::numeric_limits<uint32_t>::max();
  state.entryTimerSamples = std::numeric_limits<uint32_t>::max();
  state.entryTimerCountSum = std::numeric_limits<uint32_t>::max();
  state.lateEntryCount = std::numeric_limits<uint32_t>::max();
  state.completeStepPulseSamples = std::numeric_limits<uint32_t>::max();
  state.deadlineSamples = std::numeric_limits<uint32_t>::max();
  state.deadlineMissing = std::numeric_limits<uint32_t>::max();
  state.deadlineMisses = std::numeric_limits<uint32_t>::max();

  CoordinatedXyIsrInstrumentation::recordSample(
      state, Phase::Acceleration, 1u, 2u, 1u, true, true, false);
  CoordinatedXyIsrInstrumentation::beginIrqPathSample(
      state, true, 0u, true, 128u, 1u, 1u, true, false);
  CoordinatedXyIsrInstrumentation::completeIrqPath(state, 2u);
  CoordinatedXyIsrInstrumentation::recordCompleteStepPulse(state, 360u);
  CoordinatedXyIsrInstrumentation::beginIrqPathSample(
      state, true, 3u, true, 128u, 2249u, 4u, true, false);
  CoordinatedXyIsrInstrumentation::recordCompleteStepDeadline(
      state, true, 128u, 2249u, false);
  CoordinatedXyIsrInstrumentation::recordCompleteStepDeadline(
      state, false, 0u, 0u, false);
  CoordinatedXyIsrInstrumentation::completeIrqPath(state, 5u);
  state.irqPathMissing = std::numeric_limits<uint32_t>::max();
  state.entryTimerMissing = std::numeric_limits<uint32_t>::max();
  CoordinatedXyIsrInstrumentation::recordSample(
      state, Phase::Acceleration, 3u, 4u, 1u, false, false, false);
  CoordinatedXyIsrInstrumentation::beginIrqPathSample(
      state, false, 0u, false, 0u, 0u, 3u, false, false);
  const auto snapshot = CoordinatedXyIsrInstrumentation::makeSnapshot(state);

  CHECK_TRUE((snapshot.saturationFlags &
              CoordinatedXyIsrInstrumentation::SaturatedCallbacks) != 0u);
  CHECK_TRUE((snapshot.saturationFlags &
              CoordinatedXyIsrInstrumentation::SaturatedPhaseCallbacks) != 0u);
  CHECK_TRUE((snapshot.saturationFlags &
              CoordinatedXyIsrInstrumentation::SaturatedCompletedPulses) != 0u);
  CHECK_TRUE((snapshot.saturationFlags &
              CoordinatedXyIsrInstrumentation::SaturatedPendingObservations) != 0u);
  CHECK_TRUE((snapshot.saturationFlags &
              CoordinatedXyIsrInstrumentation::SaturatedPendingStreak) != 0u);
  CHECK_TRUE((snapshot.saturationFlags &
              CoordinatedXyIsrInstrumentation::SaturatedCycleSums) != 0u);
  CHECK_TRUE((snapshot.saturationFlags &
              CoordinatedXyIsrInstrumentation::SaturatedScheduledTicks) != 0u);
  CHECK_TRUE((snapshot.saturationFlags &
              CoordinatedXyIsrInstrumentation::SaturatedIrqPathSamples) != 0u);
  CHECK_TRUE((snapshot.saturationFlags &
              CoordinatedXyIsrInstrumentation::SaturatedIrqPathMissing) != 0u);
  CHECK_TRUE((snapshot.saturationFlags &
              CoordinatedXyIsrInstrumentation::SaturatedEntryTimerSamples) != 0u);
  CHECK_TRUE((snapshot.saturationFlags &
              CoordinatedXyIsrInstrumentation::SaturatedEntryTimerMissing) != 0u);
  CHECK_TRUE((snapshot.saturationFlags &
              CoordinatedXyIsrInstrumentation::SaturatedEntryTimerCountSum) != 0u);
  CHECK_TRUE((snapshot.saturationFlags &
              CoordinatedXyIsrInstrumentation::SaturatedLateEntryCount) != 0u);
  CHECK_TRUE((snapshot.saturationFlags &
              CoordinatedXyIsrInstrumentation::SaturatedCompleteStepPulseSamples) != 0u);
  CHECK_TRUE((snapshot.saturationFlags &
              CoordinatedXyIsrInstrumentation::SaturatedDeadlineSamples) != 0u);
  CHECK_TRUE((snapshot.saturationFlags &
              CoordinatedXyIsrInstrumentation::SaturatedDeadlineMissing) != 0u);
  CHECK_TRUE((snapshot.saturationFlags &
              CoordinatedXyIsrInstrumentation::SaturatedDeadlineMisses) != 0u);
}

TEST(CoordinatedXyIsrInstrumentation, TracksEntryScheduleOverrunAcrossDwtWrap) {
  State state{};
  CoordinatedXyIsrInstrumentation::reset(state, 0u);
  CoordinatedXyIsrInstrumentation::beginIrqPathSample(
      state, true, 0xFFFFFFF0u, true, 10u, 49u,
      0xFFFFFFF5u, false, false);
  CoordinatedXyIsrInstrumentation::completeIrqPath(state, 0xFFFFFFFAu);
  CoordinatedXyIsrInstrumentation::beginIrqPathSample(
      state, true, 0x00000072u, true, 140u, 49u,
      0x00000077u, true, true);
  CoordinatedXyIsrInstrumentation::completeIrqPath(state, 0x0000007Cu);

  const auto snapshot = CoordinatedXyIsrInstrumentation::makeSnapshot(state);
  // Unsigned subtraction yields 130 actual cycles across wrap; ARR 49 is a
  // 100-cycle schedule at the fixed 2:1 core/timer clock ratio.
  UNSIGNED_LONGS_EQUAL(30u, snapshot.entryScheduleOverrunMaxCycles);
  UNSIGNED_LONGS_EQUAL(140u, snapshot.pendingEntryTimerCountMax);
  UNSIGNED_LONGS_EQUAL(1u, snapshot.lateEntryCount);
}

TEST(CoordinatedXyIsrInstrumentation, MarkAbortAndFinishWithoutSample) {
  State state{};
  CoordinatedXyIsrInstrumentation::reset(state, 100u);
  CoordinatedXyIsrInstrumentation::markAborted(state);
  CoordinatedXyIsrInstrumentation::finishWithoutSample(state, 175u, false);

  const auto snapshot = CoordinatedXyIsrInstrumentation::makeSnapshot(state);
  CHECK_TRUE(snapshot.aborted);
  CHECK_FALSE(snapshot.active);
  UNSIGNED_LONGS_EQUAL(75u, snapshot.durationCycles);
  UNSIGNED_LONGS_EQUAL(0u, snapshot.totalCallbacks);
}

TEST(CoordinatedXyIsrInstrumentation, TracksCompleteStepPulseBounds) {
  State state{};
  CoordinatedXyIsrInstrumentation::reset(state, 100u);
  CoordinatedXyIsrInstrumentation::recordCompleteStepPulse(state, 365u);
  CoordinatedXyIsrInstrumentation::recordCompleteStepPulse(state, 360u);
  CoordinatedXyIsrInstrumentation::recordCompleteStepPulse(state, 912u);

  const auto snapshot = CoordinatedXyIsrInstrumentation::makeSnapshot(state);
  UNSIGNED_LONGS_EQUAL(3u, snapshot.completeStepPulseSamples);
  UNSIGNED_LONGS_EQUAL(360u, snapshot.completeStepPulseMinCycles);
  UNSIGNED_LONGS_EQUAL(912u, snapshot.completeStepPulseMaxCycles);
}

TEST(CoordinatedXyIsrInstrumentation, TracksFullIrqDeadlineSlackAndPendingMiss) {
  State state{};
  CoordinatedXyIsrInstrumentation::reset(state, 100u);
  CoordinatedXyIsrInstrumentation::beginIrqPathSample(
      state, true, 110u, true, 4u, 2249u, 120u, false, false);
  CoordinatedXyIsrInstrumentation::recordCompleteStepDeadline(
      state, true, 249u, 2249u, false);
  CoordinatedXyIsrInstrumentation::completeIrqPath(state, 150u);

  CoordinatedXyIsrInstrumentation::beginIrqPathSample(
      state, true, 200u, true, 5u, 2249u, 210u, true, false);
  CoordinatedXyIsrInstrumentation::recordCompleteStepDeadline(
      state, true, 20u, 2249u, false);
  CoordinatedXyIsrInstrumentation::completeIrqPath(state, 230u);

  const auto snapshot = CoordinatedXyIsrInstrumentation::makeSnapshot(state);
  UNSIGNED_LONGS_EQUAL(2u, snapshot.deadlineSamples);
  UNSIGNED_LONGS_EQUAL(0u, snapshot.deadlineMissing);
  UNSIGNED_LONGS_EQUAL(1u, snapshot.deadlineMisses);
  UNSIGNED_LONGS_EQUAL(0u, snapshot.deadlineSlackMinTicks);
}

TEST(CoordinatedXyIsrInstrumentation, MissingDeadlineSampleFailsClosed) {
  State state{};
  CoordinatedXyIsrInstrumentation::reset(state, 100u);
  CoordinatedXyIsrInstrumentation::beginIrqPathSample(
      state, true, 110u, true, 4u, 2249u, 120u, false, false);
  CoordinatedXyIsrInstrumentation::recordCompleteStepDeadline(
      state, false, 0u, 0u, false);
  CoordinatedXyIsrInstrumentation::completeIrqPath(state, 150u);

  const auto snapshot = CoordinatedXyIsrInstrumentation::makeSnapshot(state);
  UNSIGNED_LONGS_EQUAL(0u, snapshot.deadlineSamples);
  UNSIGNED_LONGS_EQUAL(1u, snapshot.deadlineMissing);
}

TEST(CoordinatedXyIsrInstrumentation, FinalTimerUpdateFlagIsADeadlineMiss) {
  State state{};
  CoordinatedXyIsrInstrumentation::reset(state, 100u);
  CoordinatedXyIsrInstrumentation::beginIrqPathSample(
      state, true, 110u, true, 4u, 2249u, 120u, false, false);
  CoordinatedXyIsrInstrumentation::recordCompleteStepDeadline(
      state, true, 20u, 2249u, true);
  CoordinatedXyIsrInstrumentation::completeIrqPath(state, 150u);

  const auto snapshot = CoordinatedXyIsrInstrumentation::makeSnapshot(state);
  UNSIGNED_LONGS_EQUAL(1u, snapshot.deadlineSamples);
  UNSIGNED_LONGS_EQUAL(1u, snapshot.deadlineMisses);
  UNSIGNED_LONGS_EQUAL(0u, snapshot.deadlineSlackMinTicks);
}
