#include "CoordinatedXyIsrInstrumentation.h"

#include <limits>

#if defined(__GNUC__) && !defined(UNIT_TEST)
#pragma GCC push_options
#pragma GCC optimize("O2")
#define LC_XY_ISR_INSTRUMENTATION_ALWAYS_INLINE \
  __attribute__((always_inline)) inline
#else
#define LC_XY_ISR_INSTRUMENTATION_ALWAYS_INLINE inline
#endif

namespace CoordinatedXyIsrInstrumentation {
namespace {

constexpr uint32_t kUint32Max = static_cast<uint32_t>(-1);

LC_XY_ISR_INSTRUMENTATION_ALWAYS_INLINE constexpr uint8_t phaseIndex(
    Phase phase) {
  return static_cast<uint8_t>(phase);
}

LC_XY_ISR_INSTRUMENTATION_ALWAYS_INLINE void saturatingIncrement(
    uint32_t& value,
    uint32_t& flags,
    uint32_t flag) {
  if (value == kUint32Max) {
    flags |= flag;
    return;
  }
  ++value;
}

LC_XY_ISR_INSTRUMENTATION_ALWAYS_INLINE void saturatingAdd(
    uint32_t& value,
    uint32_t increment,
    uint32_t& flags,
    uint32_t flag) {
  if (increment > (kUint32Max - value)) {
    value = kUint32Max;
    flags |= flag;
    return;
  }
  value += increment;
}

LC_XY_ISR_INSTRUMENTATION_ALWAYS_INLINE void observeCycle(
    State& state,
    uint32_t cycle) {
  if (cycle < state.lastObservedCycle) {
    saturatingIncrement(
        state.cycleWraps, state.saturationFlags, SaturatedCycleWraps);
  }
  state.lastObservedCycle = cycle;
}

uint32_t durationCycles(const State& state) {
  return state.endCycle - state.startCycle;
}

uint32_t boundedMean(uint32_t sum, uint32_t count) {
  if (count == 0u) return 0u;
  return sum / count;
}

}  // namespace

void reset(State& state, uint32_t startCycle) {
  state = State{};
  state.valid = true;
  state.active = true;
  state.startCycle = startCycle;
  state.endCycle = startCycle;
  state.lastObservedCycle = startCycle;
}

void markAborted(State& state) {
  if (state.valid) state.aborted = true;
}

void finishWithoutSample(State& state, uint32_t endCycle, bool aborted) {
  if (!state.valid) return;
  observeCycle(state, endCycle);
  state.endCycle = endCycle;
  state.active = false;
  state.aborted = state.aborted || aborted;
}

void recordSample(State& state,
                  Phase phase,
                  uint32_t entryCycle,
                  uint32_t exitCycle,
                  uint32_t arr,
                  bool updatePending,
                  bool completedPulse,
                  bool terminal) {
  if (!state.valid || !state.active) return;

  observeCycle(state, entryCycle);
  observeCycle(state, exitCycle);
  state.endCycle = exitCycle;

  saturatingIncrement(
      state.totalCallbacks, state.saturationFlags, SaturatedCallbacks);
  if (completedPulse) {
    saturatingIncrement(state.completedPulses,
                        state.saturationFlags,
                        SaturatedCompletedPulses);
  }

  const uint32_t elapsed = exitCycle - entryCycle;
  if (elapsed > state.maxCycles) state.maxCycles = elapsed;

  if (terminal) {
    saturatingIncrement(state.terminalCallbacks,
                        state.saturationFlags,
                        SaturatedTerminalCallbacks);
    saturatingAdd(state.terminalCycleSum,
                  elapsed,
                  state.saturationFlags,
                  SaturatedCycleSums);
    if (elapsed > state.terminalMaxCycles) state.terminalMaxCycles = elapsed;
  } else {
    const uint8_t index = phaseIndex(phase);
    if (index < phaseIndex(Phase::Count)) {
      saturatingIncrement(state.phaseCallbacks[index],
                          state.saturationFlags,
                          SaturatedPhaseCallbacks);
      saturatingAdd(state.phaseCycleSums[index],
                    elapsed,
                    state.saturationFlags,
                    SaturatedCycleSums);
      if (elapsed > state.phaseMaxCycles[index]) {
        state.phaseMaxCycles[index] = elapsed;
      }
    }
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

  if (arr == kUint32Max) {
    state.scheduledTimerTicks = kUint32Max;
    state.saturationFlags |= SaturatedScheduledTicks;
  } else {
    saturatingAdd(state.scheduledTimerTicks,
                  arr + 1u,
                  state.saturationFlags,
                  SaturatedScheduledTicks);
  }

  if (terminal) state.active = false;
}

void completeSampleTiming(State& state,
                          Phase phase,
                          uint32_t entryCycle,
                          uint32_t recordedExitCycle,
                          uint32_t finalExitCycle,
                          bool terminal) {
  if (!state.valid) return;
  observeCycle(state, finalExitCycle);
  state.endCycle = finalExitCycle;
  const uint32_t recorded = recordedExitCycle - entryCycle;
  const uint32_t completed = finalExitCycle - entryCycle;
  if (completed <= recorded) return;
  const uint32_t additional = completed - recorded;
  if (completed > state.maxCycles) state.maxCycles = completed;
  if (terminal) {
    saturatingAdd(state.terminalCycleSum,
                  additional,
                  state.saturationFlags,
                  SaturatedCycleSums);
    if (completed > state.terminalMaxCycles) {
      state.terminalMaxCycles = completed;
    }
    return;
  }
  const uint8_t index = phaseIndex(phase);
  if (index >= phaseIndex(Phase::Count)) return;
  saturatingAdd(state.phaseCycleSums[index],
                additional,
                state.saturationFlags,
                SaturatedCycleSums);
  if (completed > state.phaseMaxCycles[index]) {
    state.phaseMaxCycles[index] = completed;
  }
}

void beginIrqPathSample(State& state,
                        bool irqEntryValid,
                        uint32_t irqEntryCycle,
                        uint32_t handlerEntryCycle,
                        bool updatePending,
                        bool terminal) {
  if (!state.valid) return;
  if (!irqEntryValid) {
    saturatingIncrement(state.irqPathMissing,
                        state.saturationFlags,
                        SaturatedIrqPathMissing);
    return;
  }
  if (state.irqPathSampleOpen) {
    saturatingIncrement(state.irqPathMissing,
                        state.saturationFlags,
                        SaturatedIrqPathMissing);
  }
  saturatingIncrement(state.irqPathSamples,
                      state.saturationFlags,
                      SaturatedIrqPathSamples);
  const uint32_t preHandlerCycles = handlerEntryCycle - irqEntryCycle;
  saturatingAdd(state.preHandlerCycleSum,
                preHandlerCycles,
                state.saturationFlags,
                SaturatedCycleSums);
  if (preHandlerCycles > state.preHandlerMaxCycles) {
    state.preHandlerMaxCycles = preHandlerCycles;
  }
  if (updatePending &&
      preHandlerCycles > state.pendingPreHandlerMaxCycles) {
    state.pendingPreHandlerMaxCycles = preHandlerCycles;
  }
  state.irqPathSampleOpen = true;
  state.irqPathSamplePending = updatePending;
  state.irqPathSampleTerminal = terminal;
  state.irqPathEntryCycle = irqEntryCycle;
}

void completeIrqPath(State& state, uint32_t irqExitCycle) {
  if (!state.valid || !state.irqPathSampleOpen) return;
  const uint32_t fullIrqCycles = irqExitCycle - state.irqPathEntryCycle;
  saturatingAdd(state.fullIrqCycleSum,
                fullIrqCycles,
                state.saturationFlags,
                SaturatedCycleSums);
  if (fullIrqCycles > state.fullIrqMaxCycles) {
    state.fullIrqMaxCycles = fullIrqCycles;
  }
  if (!state.irqPathSampleTerminal &&
      fullIrqCycles > state.activeFullIrqMaxCycles) {
    state.activeFullIrqMaxCycles = fullIrqCycles;
  }
  if (state.irqPathSampleTerminal &&
      fullIrqCycles > state.terminalFullIrqMaxCycles) {
    state.terminalFullIrqMaxCycles = fullIrqCycles;
  }
  if (state.irqPathSamplePending &&
      fullIrqCycles > state.pendingFullIrqMaxCycles) {
    state.pendingFullIrqMaxCycles = fullIrqCycles;
  }
  state.irqPathSampleOpen = false;
  state.irqPathSamplePending = false;
  state.irqPathSampleTerminal = false;
}

Snapshot makeSnapshot(const State& state) {
  Snapshot snapshot{};
  snapshot.valid = state.valid;
  snapshot.active = state.active;
  snapshot.aborted = state.aborted;
  snapshot.startCycle = state.startCycle;
  snapshot.endCycle = state.endCycle;
  snapshot.cycleWraps = state.cycleWraps;
  snapshot.durationCycles = durationCycles(state);
  snapshot.totalCallbacks = state.totalCallbacks;
  snapshot.completedPulses = state.completedPulses;
  for (uint8_t i = 0u; i < phaseIndex(Phase::Count); ++i) {
    snapshot.phaseCallbacks[i] = state.phaseCallbacks[i];
    snapshot.phaseCycleSums[i] = state.phaseCycleSums[i];
    snapshot.phaseMaxCycles[i] = state.phaseMaxCycles[i];
  }
  snapshot.terminalCallbacks = state.terminalCallbacks;
  snapshot.terminalCycleSum = state.terminalCycleSum;
  snapshot.terminalMaxCycles = state.terminalMaxCycles;
  snapshot.maxCycles = state.maxCycles;
  snapshot.pendingObservations = state.pendingObservations;
  snapshot.maxPendingStreak = state.maxPendingStreak;
  snapshot.scheduledTimerTicks = state.scheduledTimerTicks;
  snapshot.irqPathSamples = state.irqPathSamples;
  snapshot.irqPathMissing = state.irqPathMissing;
  snapshot.preHandlerCycleSum = state.preHandlerCycleSum;
  snapshot.preHandlerMaxCycles = state.preHandlerMaxCycles;
  snapshot.fullIrqCycleSum = state.fullIrqCycleSum;
  snapshot.fullIrqMaxCycles = state.fullIrqMaxCycles;
  snapshot.activeFullIrqMaxCycles = state.activeFullIrqMaxCycles;
  snapshot.terminalFullIrqMaxCycles = state.terminalFullIrqMaxCycles;
  snapshot.pendingPreHandlerMaxCycles = state.pendingPreHandlerMaxCycles;
  snapshot.pendingFullIrqMaxCycles = state.pendingFullIrqMaxCycles;
  snapshot.saturationFlags = state.saturationFlags;
  return snapshot;
}

uint32_t phaseMeanCycles(const Snapshot& snapshot, Phase phase) {
  const uint8_t index = phaseIndex(phase);
  if (index >= phaseIndex(Phase::Count)) return 0u;
  return boundedMean(snapshot.phaseCycleSums[index],
                     snapshot.phaseCallbacks[index]);
}

uint32_t terminalMeanCycles(const Snapshot& snapshot) {
  return boundedMean(snapshot.terminalCycleSum, snapshot.terminalCallbacks);
}

uint32_t preHandlerMeanCycles(const Snapshot& snapshot) {
  return boundedMean(snapshot.preHandlerCycleSum, snapshot.irqPathSamples);
}

uint32_t fullIrqMeanCycles(const Snapshot& snapshot) {
  return boundedMean(snapshot.fullIrqCycleSum, snapshot.irqPathSamples);
}

uint32_t durationErrorBasisPoints(const Snapshot& snapshot,
                                  uint32_t coreClockHz,
                                  uint32_t timerClockHz) {
  if (!snapshot.valid || snapshot.scheduledTimerTicks == 0u ||
      coreClockHz == 0u || timerClockHz == 0u) {
    return std::numeric_limits<uint32_t>::max();
  }

  if ((coreClockHz % timerClockHz) != 0u) {
    return std::numeric_limits<uint32_t>::max();
  }
  const uint32_t clockRatio = coreClockHz / timerClockHz;
  if (clockRatio == 0u) {
    return std::numeric_limits<uint32_t>::max();
  }
  const uint32_t measuredTimerTicks = snapshot.durationCycles / clockRatio;
  const uint32_t difference =
      (measuredTimerTicks >= snapshot.scheduledTimerTicks)
      ? (measuredTimerTicks - snapshot.scheduledTimerTicks)
      : (snapshot.scheduledTimerTicks - measuredTimerTicks);
  if (snapshot.scheduledTimerTicks >= 10000u) {
    const uint32_t oneBasisPoint = snapshot.scheduledTimerTicks / 10000u;
    return (oneBasisPoint == 0u)
        ? std::numeric_limits<uint32_t>::max()
        : difference / oneBasisPoint;
  }
  if (difference > (std::numeric_limits<uint32_t>::max() / 10000u)) {
    return std::numeric_limits<uint32_t>::max();
  }
  return (difference * 10000u) / snapshot.scheduledTimerTicks;
}

}  // namespace CoordinatedXyIsrInstrumentation

#if defined(__GNUC__) && !defined(UNIT_TEST)
#pragma GCC pop_options
#endif

#undef LC_XY_ISR_INSTRUMENTATION_ALWAYS_INLINE
