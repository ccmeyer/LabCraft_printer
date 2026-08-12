#ifndef INC_COORDINATEDXYISRINSTRUMENTATION_H_
#define INC_COORDINATEDXYISRINSTRUMENTATION_H_

#include <cstdint>

#ifndef LC_COORDINATED_XY_ISR_INSTRUMENTATION_ENABLE
#define LC_COORDINATED_XY_ISR_INSTRUMENTATION_ENABLE 1
#endif

namespace CoordinatedXyIsrInstrumentation {

static constexpr uint32_t kLateEntryTimerTicks = 128u;
static constexpr uint32_t kCoreCyclesPerTimerTick = 2u;

enum class Phase : uint8_t {
  Acceleration = 0u,
  Cruise = 1u,
  Deceleration = 2u,
  Count = 3u,
};

enum SaturationFlag : uint32_t {
  SaturatedNone = 0u,
  SaturatedCallbacks = 1u << 0u,
  SaturatedPhaseCallbacks = 1u << 1u,
  SaturatedCompletedPulses = 1u << 2u,
  SaturatedPendingObservations = 1u << 3u,
  SaturatedPendingStreak = 1u << 4u,
  SaturatedCycleWraps = 1u << 5u,
  SaturatedCycleSums = 1u << 6u,
  SaturatedScheduledTicks = 1u << 7u,
  SaturatedTerminalCallbacks = 1u << 8u,
  SaturatedIrqPathSamples = 1u << 9u,
  SaturatedIrqPathMissing = 1u << 10u,
  SaturatedEntryTimerSamples = 1u << 11u,
  SaturatedEntryTimerMissing = 1u << 12u,
  SaturatedEntryTimerCountSum = 1u << 13u,
  SaturatedLateEntryCount = 1u << 14u,
  SaturatedCompleteStepPulseSamples = 1u << 15u,
  SaturatedDeadlineSamples = 1u << 16u,
  SaturatedDeadlineMissing = 1u << 17u,
  SaturatedDeadlineMisses = 1u << 18u,
};

struct State {
  bool valid = false;
  bool active = false;
  bool aborted = false;
  uint32_t startCycle = 0u;
  uint32_t endCycle = 0u;
  uint32_t lastObservedCycle = 0u;
  uint32_t cycleWraps = 0u;
  uint32_t totalCallbacks = 0u;
  uint32_t completedPulses = 0u;
  uint32_t phaseCallbacks[static_cast<uint8_t>(Phase::Count)] = {};
  uint32_t phaseCycleSums[static_cast<uint8_t>(Phase::Count)] = {};
  uint32_t phaseMaxCycles[static_cast<uint8_t>(Phase::Count)] = {};
  uint32_t terminalCallbacks = 0u;
  uint32_t terminalCycleSum = 0u;
  uint32_t terminalMaxCycles = 0u;
  uint32_t maxCycles = 0u;
  uint32_t pendingObservations = 0u;
  uint32_t currentPendingStreak = 0u;
  uint32_t maxPendingStreak = 0u;
  uint32_t scheduledTimerTicks = 0u;
  uint32_t irqPathSamples = 0u;
  uint32_t irqPathMissing = 0u;
  uint32_t preHandlerCycleSum = 0u;
  uint32_t preHandlerMaxCycles = 0u;
  uint32_t fullIrqCycleSum = 0u;
  uint32_t fullIrqMaxCycles = 0u;
  uint32_t activeFullIrqMaxCycles = 0u;
  uint32_t terminalFullIrqMaxCycles = 0u;
  uint32_t pendingPreHandlerMaxCycles = 0u;
  uint32_t pendingFullIrqMaxCycles = 0u;
  uint32_t entryTimerSamples = 0u;
  uint32_t entryTimerMissing = 0u;
  uint32_t entryTimerCountSum = 0u;
  uint32_t entryTimerCountMax = 0u;
  uint32_t pendingEntryTimerCountMax = 0u;
  uint32_t lateEntryCount = 0u;
  uint32_t entryScheduleOverrunMaxCycles = 0u;
  uint32_t completeStepPulseSamples = 0u;
  uint32_t completeStepPulseMinCycles = 0u;
  uint32_t completeStepPulseMaxCycles = 0u;
  uint32_t deadlineSamples = 0u;
  uint32_t deadlineMissing = 0u;
  uint32_t deadlineMisses = 0u;
  uint32_t deadlineSlackMinTicks = 0u;
  bool entryScheduleReferenceValid = false;
  uint32_t previousIrqEntryCycle = 0u;
  bool irqPathSampleOpen = false;
  bool irqPathSamplePending = false;
  bool irqPathSampleTerminal = false;
  uint32_t irqPathEntryCycle = 0u;
  uint32_t saturationFlags = SaturatedNone;
};

struct Snapshot {
  bool valid = false;
  bool active = false;
  bool aborted = false;
  uint32_t startCycle = 0u;
  uint32_t endCycle = 0u;
  uint32_t cycleWraps = 0u;
  uint32_t durationCycles = 0u;
  uint32_t totalCallbacks = 0u;
  uint32_t completedPulses = 0u;
  uint32_t phaseCallbacks[static_cast<uint8_t>(Phase::Count)] = {};
  uint32_t phaseCycleSums[static_cast<uint8_t>(Phase::Count)] = {};
  uint32_t phaseMaxCycles[static_cast<uint8_t>(Phase::Count)] = {};
  uint32_t terminalCallbacks = 0u;
  uint32_t terminalCycleSum = 0u;
  uint32_t terminalMaxCycles = 0u;
  uint32_t maxCycles = 0u;
  uint32_t pendingObservations = 0u;
  uint32_t maxPendingStreak = 0u;
  uint32_t scheduledTimerTicks = 0u;
  uint32_t irqPathSamples = 0u;
  uint32_t irqPathMissing = 0u;
  uint32_t preHandlerCycleSum = 0u;
  uint32_t preHandlerMaxCycles = 0u;
  uint32_t fullIrqCycleSum = 0u;
  uint32_t fullIrqMaxCycles = 0u;
  uint32_t activeFullIrqMaxCycles = 0u;
  uint32_t terminalFullIrqMaxCycles = 0u;
  uint32_t pendingPreHandlerMaxCycles = 0u;
  uint32_t pendingFullIrqMaxCycles = 0u;
  uint32_t entryTimerSamples = 0u;
  uint32_t entryTimerMissing = 0u;
  uint32_t entryTimerCountSum = 0u;
  uint32_t entryTimerCountMax = 0u;
  uint32_t pendingEntryTimerCountMax = 0u;
  uint32_t lateEntryCount = 0u;
  uint32_t entryScheduleOverrunMaxCycles = 0u;
  uint32_t completeStepPulseSamples = 0u;
  uint32_t completeStepPulseMinCycles = 0u;
  uint32_t completeStepPulseMaxCycles = 0u;
  uint32_t deadlineSamples = 0u;
  uint32_t deadlineMissing = 0u;
  uint32_t deadlineMisses = 0u;
  uint32_t deadlineSlackMinTicks = 0u;
  uint32_t saturationFlags = SaturatedNone;
};

void reset(State& state, uint32_t startCycle);
void markAborted(State& state);
void finishWithoutSample(State& state, uint32_t endCycle, bool aborted);
void recordSample(State& state,
                  Phase phase,
                  uint32_t entryCycle,
                  uint32_t exitCycle,
                  uint32_t arr,
                  bool updatePending,
                  bool completedPulse,
                  bool terminal);
void completeSampleTiming(State& state,
                          Phase phase,
                          uint32_t entryCycle,
                          uint32_t recordedExitCycle,
                          uint32_t finalExitCycle,
                          bool terminal);
void beginIrqPathSample(State& state,
                        bool irqEntryValid,
                        uint32_t irqEntryCycle,
                        bool entryTimerValid,
                        uint32_t entryTimerCount,
                        uint32_t entryTimerArr,
                        uint32_t handlerEntryCycle,
                        bool updatePending,
                        bool terminal);
void completeIrqPath(State& state, uint32_t irqExitCycle);
void recordCompleteStepPulse(State& state, uint32_t pulseHighCycles);
void recordCompleteStepDeadline(State& state,
                                bool timerSampleValid,
                                uint32_t timerCount,
                                uint32_t timerArr,
                                bool timerUpdatePending);
Snapshot makeSnapshot(const State& state);
uint32_t phaseMeanCycles(const Snapshot& snapshot, Phase phase);
uint32_t terminalMeanCycles(const Snapshot& snapshot);
uint32_t preHandlerMeanCycles(const Snapshot& snapshot);
uint32_t fullIrqMeanCycles(const Snapshot& snapshot);
uint32_t entryTimerMeanTicks(const Snapshot& snapshot);
uint32_t durationErrorBasisPoints(const Snapshot& snapshot,
                                  uint32_t coreClockHz,
                                  uint32_t timerClockHz);

}  // namespace CoordinatedXyIsrInstrumentation

#endif /* INC_COORDINATEDXYISRINSTRUMENTATION_H_ */
