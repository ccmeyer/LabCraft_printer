#include "CppUTest/TestHarness.h"
#include "CoordinatedXyIsrInstrumentation.h"

#include <limits>

using namespace CoordinatedXyIsrInstrumentation;

TEST_GROUP(CoordinatedXyIsrInstrumentation) {};

TEST(CoordinatedXyIsrInstrumentation, ResetCreatesFreshActiveState) {
  State state{};
  reset(state, 100u);
  CHECK_TRUE(state.valid);
  CHECK_TRUE(state.active);
  CHECK_FALSE(state.aborted);
  UNSIGNED_LONGS_EQUAL(100u, state.startCycle);
  UNSIGNED_LONGS_EQUAL(0u, state.saturationFlags);
}

TEST(CoordinatedXyIsrInstrumentation, TracksPhaseAndTerminalMaxima) {
  State state{};
  reset(state, 10u);
  recordSample(state, Phase::Acceleration, 20u, 120u, 9u, false, false, false);
  completeSampleTiming(state, Phase::Acceleration, 20u, 120u, 150u, false);
  recordSample(state, Phase::Cruise, 160u, 190u, 9u, false, true, false);
  recordSample(state, Phase::Deceleration, 200u, 250u, 9u, false, true, false);
  recordSample(state, Phase::Deceleration, 260u, 340u, 9u, false, false, true);
  const Snapshot snapshot = makeSnapshot(state);
  UNSIGNED_LONGS_EQUAL(4u, snapshot.totalCallbacks);
  UNSIGNED_LONGS_EQUAL(2u, snapshot.completedPulses);
  UNSIGNED_LONGS_EQUAL(130u, snapshot.phaseMaxCycles[0]);
  UNSIGNED_LONGS_EQUAL(30u, snapshot.phaseMaxCycles[1]);
  UNSIGNED_LONGS_EQUAL(50u, snapshot.phaseMaxCycles[2]);
  UNSIGNED_LONGS_EQUAL(1u, snapshot.terminalCallbacks);
  UNSIGNED_LONGS_EQUAL(80u, snapshot.terminalMaxCycles);
  CHECK_FALSE(snapshot.active);
}

TEST(CoordinatedXyIsrInstrumentation, PendingStreakResetsAfterClearSample) {
  State state{};
  reset(state, 0u);
  recordSample(state, Phase::Cruise, 1u, 2u, 9u, true, false, false);
  recordSample(state, Phase::Cruise, 3u, 4u, 9u, true, false, false);
  recordSample(state, Phase::Cruise, 5u, 6u, 9u, false, false, false);
  recordSample(state, Phase::Cruise, 7u, 8u, 9u, true, false, false);
  const Snapshot snapshot = makeSnapshot(state);
  UNSIGNED_LONGS_EQUAL(3u, snapshot.pendingObservations);
  UNSIGNED_LONGS_EQUAL(2u, snapshot.maxPendingStreak);
}

TEST(CoordinatedXyIsrInstrumentation, TracksEntryAndFullIrqMaxima) {
  State state{};
  reset(state, 0u);
  beginIrqPathSample(
      state, true, 100u, true, 50u, 2249u, 110u, false, false);
  completeIrqPath(state, 180u);
  beginIrqPathSample(
      state, true, 200u, true, 100u, 2249u, 220u, true, true);
  completeIrqPath(state, 390u);
  const Snapshot snapshot = makeSnapshot(state);
  UNSIGNED_LONGS_EQUAL(2u, snapshot.irqPathSamples);
  UNSIGNED_LONGS_EQUAL(0u, snapshot.irqPathMissing);
  UNSIGNED_LONGS_EQUAL(20u, snapshot.preHandlerMaxCycles);
  UNSIGNED_LONGS_EQUAL(190u, snapshot.fullIrqMaxCycles);
  UNSIGNED_LONGS_EQUAL(80u, snapshot.activeFullIrqMaxCycles);
  UNSIGNED_LONGS_EQUAL(190u, snapshot.terminalFullIrqMaxCycles);
  UNSIGNED_LONGS_EQUAL(20u, snapshot.pendingPreHandlerMaxCycles);
  UNSIGNED_LONGS_EQUAL(190u, snapshot.pendingFullIrqMaxCycles);
  UNSIGNED_LONGS_EQUAL(2u, snapshot.entryTimerSamples);
  UNSIGNED_LONGS_EQUAL(100u, snapshot.entryTimerCountMax);
  UNSIGNED_LONGS_EQUAL(100u, snapshot.pendingEntryTimerCountMax);
}

TEST(CoordinatedXyIsrInstrumentation, MissingEntrySamplesFailClosed) {
  State state{};
  reset(state, 0u);
  beginIrqPathSample(
      state, false, 0u, false, 0u, 0u, 20u, false, false);
  const Snapshot snapshot = makeSnapshot(state);
  UNSIGNED_LONGS_EQUAL(1u, snapshot.entryTimerMissing);
  UNSIGNED_LONGS_EQUAL(1u, snapshot.irqPathMissing);
}

TEST(CoordinatedXyIsrInstrumentation, EntryThresholdAndPendingCorrelation) {
  State state{};
  reset(state, 0u);
  beginIrqPathSample(
      state, true, 10u, true, 127u, 2249u, 20u, false, false);
  completeIrqPath(state, 30u);
  beginIrqPathSample(
      state, true, 4510u, true, 128u, 2249u, 4520u, true, false);
  completeIrqPath(state, 4530u);
  const Snapshot snapshot = makeSnapshot(state);
  UNSIGNED_LONGS_EQUAL(1u, snapshot.lateEntryCount);
  UNSIGNED_LONGS_EQUAL(128u, snapshot.entryTimerCountMax);
  UNSIGNED_LONGS_EQUAL(128u, snapshot.pendingEntryTimerCountMax);
}

TEST(CoordinatedXyIsrInstrumentation, FirstEntryHasNoScheduleOverrun) {
  State state{};
  reset(state, 0u);
  beginIrqPathSample(
      state, true, 1000u, true, 10u, 99u, 1010u, false, false);
  completeIrqPath(state, 1020u);
  UNSIGNED_LONGS_EQUAL(0u, makeSnapshot(state).entryScheduleOverrunMaxCycles);
}

TEST(CoordinatedXyIsrInstrumentation, ScheduleOverrunUsesWrapSafeDwtDelta) {
  State state{};
  reset(state, 0xFFFFFF00u);
  beginIrqPathSample(state,
                     true,
                     0xFFFFFF80u,
                     true,
                     10u,
                     99u,
                     0xFFFFFF90u,
                     false,
                     false);
  completeIrqPath(state, 0xFFFFFFA0u);
  beginIrqPathSample(state,
                     true,
                     0x00000080u,
                     true,
                     10u,
                     99u,
                     0x00000090u,
                     false,
                     false);
  completeIrqPath(state, 0x000000A0u);
  UNSIGNED_LONGS_EQUAL(
      56u, makeSnapshot(state).entryScheduleOverrunMaxCycles);
}

TEST(CoordinatedXyIsrInstrumentation, DurationAndErrorHandleCycleWrap) {
  State state{};
  reset(state, 0xFFFFFFF0u);
  recordSample(state,
               Phase::Acceleration,
               0xFFFFFFF8u,
               0x00000020u,
               9u,
               false,
               false,
               true);
  const Snapshot snapshot = makeSnapshot(state);
  UNSIGNED_LONGS_EQUAL(48u, snapshot.durationCycles);
  UNSIGNED_LONGS_EQUAL(1u, snapshot.cycleWraps);

  Snapshot exact{};
  exact.valid = true;
  exact.durationCycles = 2000u;
  exact.scheduledTimerTicks = 1000u;
  UNSIGNED_LONGS_EQUAL(
      0u, durationErrorBasisPoints(exact, 180000000u, 90000000u));
}

TEST(CoordinatedXyIsrInstrumentation, SaturatesCountersWithoutWrapping) {
  State state{};
  reset(state, 0u);
  state.totalCallbacks = std::numeric_limits<uint32_t>::max();
  state.pendingObservations = std::numeric_limits<uint32_t>::max();
  state.scheduledTimerTicks = std::numeric_limits<uint32_t>::max();
  recordSample(state, Phase::Cruise, 1u, 2u, 9u, true, false, false);
  const Snapshot snapshot = makeSnapshot(state);
  UNSIGNED_LONGS_EQUAL(std::numeric_limits<uint32_t>::max(),
                       snapshot.totalCallbacks);
  UNSIGNED_LONGS_EQUAL(std::numeric_limits<uint32_t>::max(),
                       snapshot.pendingObservations);
  CHECK_TRUE(snapshot.saturationFlags != 0u);
}

TEST(CoordinatedXyIsrInstrumentation, DeadlineTracksSlackAndMisses) {
  State state{};
  reset(state, 0u);
  beginIrqPathSample(
      state, true, 10u, true, 0u, 2249u, 20u, false, false);
  recordTim2Deadline(state, true, 100u, 2249u, false);
  completeIrqPath(state, 30u);
  beginIrqPathSample(
      state, true, 40u, true, 0u, 2249u, 50u, false, false);
  recordTim2Deadline(state, true, 1800u, 2249u, false);
  completeIrqPath(state, 60u);
  beginIrqPathSample(
      state, true, 70u, true, 0u, 2249u, 80u, false, false);
  recordTim2Deadline(state, true, 2200u, 2249u, true);
  const Snapshot snapshot = makeSnapshot(state);
  UNSIGNED_LONGS_EQUAL(3u, snapshot.deadlineSamples);
  UNSIGNED_LONGS_EQUAL(1u, snapshot.deadlineMisses);
  UNSIGNED_LONGS_EQUAL(0u, snapshot.deadlineSlackMinTicks);
}

TEST(CoordinatedXyIsrInstrumentation, MissingDeadlineSampleIsCounted) {
  State state{};
  reset(state, 0u);
  beginIrqPathSample(
      state, true, 10u, true, 0u, 2249u, 20u, false, false);
  recordTim2Deadline(state, false, 0u, 0u, false);
  const Snapshot snapshot = makeSnapshot(state);
  UNSIGNED_LONGS_EQUAL(1u, snapshot.deadlineMissing);
  UNSIGNED_LONGS_EQUAL(0u, snapshot.deadlineSamples);
}

TEST(CoordinatedXyIsrInstrumentation, TerminalCallbackIsNotDeadlineSample) {
  State state{};
  reset(state, 0u);
  finishWithoutSample(state, 10u, false);
  recordTim2Deadline(state, true, 0u, 10u, false);
  UNSIGNED_LONGS_EQUAL(0u, makeSnapshot(state).deadlineSamples);
}

TEST(CoordinatedXyIsrInstrumentation, MarkAbortAndFinishWithoutSample) {
  State state{};
  reset(state, 10u);
  markAborted(state);
  finishWithoutSample(state, 20u, true);
  const Snapshot snapshot = makeSnapshot(state);
  CHECK_TRUE(snapshot.aborted);
  CHECK_FALSE(snapshot.active);
  UNSIGNED_LONGS_EQUAL(10u, snapshot.durationCycles);
}
