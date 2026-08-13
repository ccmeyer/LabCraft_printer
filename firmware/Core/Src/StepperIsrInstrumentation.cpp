#include "StepperIsrInstrumentation.h"

#include <cstdint>
#include <limits>

namespace StepperIsrInstrumentation {
namespace {

constexpr uint8_t phaseIndex(Phase phase)
{
  return static_cast<uint8_t>(phase);
}

void saturatingIncrement(uint32_t& value, uint32_t& flags, uint32_t flag)
{
  if (value == std::numeric_limits<uint32_t>::max()) {
    flags |= flag;
    return;
  }
  ++value;
}

void observeCycle(State& state, uint32_t cycle)
{
  if (cycle < state.lastObservedCycle) {
    saturatingIncrement(state.cycleWraps, state.saturationFlags, SaturatedCycleWraps);
  }
  state.lastObservedCycle = cycle;
}

uint64_t durationCycles(const State& state)
{
  const uint64_t extendedEnd =
      (static_cast<uint64_t>(state.cycleWraps) << 32) + state.endCycle;
  if (extendedEnd < state.startCycle) {
    return 0u;
  }
  return extendedEnd - state.startCycle;
}

} // namespace

Phase classifyPhase(uint32_t togglesDone,
                    uint32_t togglesRemaining,
                    uint32_t totalToggles,
                    uint32_t accelToggles,
                    uint32_t decelToggles)
{
  if (togglesRemaining == 0u) {
    return Phase::Completion;
  }
  if (togglesDone < accelToggles) {
    return Phase::Acceleration;
  }
  if ((decelToggles != 0u) &&
      (togglesDone > (totalToggles - decelToggles))) {
    return Phase::Deceleration;
  }
  return Phase::Cruise;
}

void reset(State& state, uint32_t startCycle)
{
  state = State{};
  state.valid = true;
  state.active = true;
  state.startCycle = startCycle;
  state.endCycle = startCycle;
  state.lastObservedCycle = startCycle;
}

void markAborted(State& state)
{
  if (state.valid) {
    state.aborted = true;
  }
}

void finishWithoutSample(State& state, uint32_t endCycle, bool aborted)
{
  if (!state.valid) {
    return;
  }
  observeCycle(state, endCycle);
  state.endCycle = endCycle;
  state.active = false;
  state.aborted = state.aborted || aborted;
}

void recordSample(State& state,
                  Phase phase,
                  uint32_t entryCycle,
                  uint32_t exitCycle,
                  bool updatePending,
                  bool completedPulse,
                  bool moveComplete)
{
  if (!state.valid || !state.active) {
    return;
  }

  observeCycle(state, entryCycle);
  observeCycle(state, exitCycle);

  saturatingIncrement(
      state.totalEntries, state.saturationFlags, SaturatedTotalEntries);

  const uint8_t index = phaseIndex(phase);
  if (index < phaseIndex(Phase::Count)) {
    saturatingIncrement(
        state.phaseEntries[index], state.saturationFlags, SaturatedPhaseEntries);
    const uint32_t elapsedCycles = exitCycle - entryCycle;
    if (elapsedCycles > state.phaseMaxCycles[index]) {
      state.phaseMaxCycles[index] = elapsedCycles;
    }
    if (elapsedCycles > state.maxCycles) {
      state.maxCycles = elapsedCycles;
    }
  }

  if (completedPulse) {
    saturatingIncrement(
        state.completedPulses, state.saturationFlags, SaturatedCompletedPulses);
  }

  if (updatePending) {
    saturatingIncrement(state.pendingObservations,
                        state.saturationFlags,
                        SaturatedPendingObservations);
    saturatingIncrement(state.currentPendingStreak,
                        state.saturationFlags,
                        SaturatedPendingStreak);
    if (state.currentPendingStreak > state.maxPendingStreak) {
      state.maxPendingStreak = state.currentPendingStreak;
    }
  } else {
    state.currentPendingStreak = 0u;
  }

  if (moveComplete) {
    state.endCycle = exitCycle;
    state.active = false;
  }
}

void recordFullIrqSample(State& state,
                         bool entryValid,
                         uint32_t entryCycle,
                         uint32_t exitCycle,
                         bool timerSampleValid,
                         uint32_t entryTimerCount,
                         uint32_t entryTimerArr,
                         bool postTimerSampleValid,
                         uint32_t postTimerCount,
                         uint32_t postTimerArr,
                         bool updatePendingAfter,
                         bool terminalCallback)
{
  if (!state.valid) {
    return;
  }
  if (!entryValid) {
    saturatingIncrement(state.missingFullIrqSamples,
                        state.saturationFlags,
                        SaturatedMissingFullIrqSamples);
    return;
  }

  saturatingIncrement(state.fullIrqSamples,
                      state.saturationFlags,
                      SaturatedFullIrqSamples);
  const uint32_t elapsedCycles = exitCycle - entryCycle;
  uint32_t& maximum = terminalCallback
      ? state.fullIrqTerminalMaxCycles
      : state.fullIrqActiveMaxCycles;
  if (elapsedCycles > maximum) {
    maximum = elapsedCycles;
  }

  if (!timerSampleValid || entryTimerCount > entryTimerArr) {
    saturatingIncrement(state.missingFullIrqSamples,
                        state.saturationFlags,
                        SaturatedMissingFullIrqSamples);
    return;
  }
  if (entryTimerCount > state.entryTimerCountMax) {
    state.entryTimerCountMax = entryTimerCount;
  }

  // A terminal callback stops TIM10 in the handler, so its post-handler CNT
  // is not a following-deadline sample.
  if (terminalCallback) {
    return;
  }
  if (!postTimerSampleValid || postTimerCount > postTimerArr) {
    saturatingIncrement(state.deadlineMisses,
                        state.saturationFlags,
                        SaturatedDeadlineMisses);
    return;
  }
  saturatingIncrement(state.deadlineSamples,
                      state.saturationFlags,
                      SaturatedDeadlineSamples);

  // TIM10 is clocked at 180 MHz with PSC=1, so each timer tick is two
  // 180 MHz DWT core cycles.
  const uint64_t remainingCoreCycles =
      (static_cast<uint64_t>(postTimerArr - postTimerCount) + 1u) * 2u;
  if (updatePendingAfter) {
    saturatingIncrement(state.deadlineMisses,
                        state.saturationFlags,
                        SaturatedDeadlineMisses);
    return;
  }
  const uint32_t slack = static_cast<uint32_t>(remainingCoreCycles);
  if (slack < state.minimumDeadlineSlackCycles) {
    state.minimumDeadlineSlackCycles = slack;
  }
}

Snapshot makeSnapshot(const State& state)
{
  Snapshot snapshot{};
  snapshot.valid = state.valid;
  snapshot.active = state.active;
  snapshot.aborted = state.aborted;
  snapshot.startCycle = state.startCycle;
  snapshot.endCycle = state.endCycle;
  snapshot.cycleWraps = state.cycleWraps;
  snapshot.durationCycles = durationCycles(state);
  snapshot.totalEntries = state.totalEntries;
  for (uint8_t i = 0u; i < phaseIndex(Phase::Count); ++i) {
    snapshot.phaseEntries[i] = state.phaseEntries[i];
    snapshot.phaseMaxCycles[i] = state.phaseMaxCycles[i];
  }
  snapshot.maxCycles = state.maxCycles;
  snapshot.completedPulses = state.completedPulses;
  snapshot.pendingObservations = state.pendingObservations;
  snapshot.maxPendingStreak = state.maxPendingStreak;
  snapshot.fullIrqSamples = state.fullIrqSamples;
  snapshot.missingFullIrqSamples = state.missingFullIrqSamples;
  snapshot.fullIrqActiveMaxCycles = state.fullIrqActiveMaxCycles;
  snapshot.fullIrqTerminalMaxCycles = state.fullIrqTerminalMaxCycles;
  snapshot.entryTimerCountMax = state.entryTimerCountMax;
  snapshot.deadlineSamples = state.deadlineSamples;
  snapshot.deadlineMisses = state.deadlineMisses;
  snapshot.minimumDeadlineSlackCycles = state.minimumDeadlineSlackCycles;
  snapshot.saturationFlags = state.saturationFlags;
  return snapshot;
}

} // namespace StepperIsrInstrumentation
