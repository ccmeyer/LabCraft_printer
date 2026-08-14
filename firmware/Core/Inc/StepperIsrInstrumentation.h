#ifndef INC_STEPPERISRINSTRUMENTATION_H_
#define INC_STEPPERISRINSTRUMENTATION_H_

#include <cstdint>

#ifndef LC_STEPPER_ISR_INSTRUMENTATION_ENABLE
#define LC_STEPPER_ISR_INSTRUMENTATION_ENABLE 1
#endif

namespace StepperIsrInstrumentation {

enum class Phase : uint8_t {
  Acceleration = 0,
  Cruise = 1,
  Deceleration = 2,
  Completion = 3,
  Count = 4
};

enum SaturationFlag : uint32_t {
  SaturatedNone = 0u,
  SaturatedTotalEntries = (1u << 0),
  SaturatedPhaseEntries = (1u << 1),
  SaturatedCompletedPulses = (1u << 2),
  SaturatedPendingObservations = (1u << 3),
  SaturatedPendingStreak = (1u << 4),
  SaturatedCycleWraps = (1u << 5)
};

struct State {
  bool valid = false;
  bool active = false;
  bool aborted = false;
  uint32_t startCycle = 0u;
  uint32_t endCycle = 0u;
  uint32_t lastObservedCycle = 0u;
  uint32_t cycleWraps = 0u;
  uint32_t totalEntries = 0u;
  uint32_t phaseEntries[static_cast<uint8_t>(Phase::Count)] = {};
  uint32_t phaseMaxCycles[static_cast<uint8_t>(Phase::Count)] = {};
  uint32_t maxCycles = 0u;
  uint32_t completedPulses = 0u;
  uint32_t pendingObservations = 0u;
  uint32_t currentPendingStreak = 0u;
  uint32_t maxPendingStreak = 0u;
  uint32_t saturationFlags = SaturatedNone;
};

struct Snapshot {
  bool valid = false;
  bool active = false;
  bool aborted = false;
  uint32_t startCycle = 0u;
  uint32_t endCycle = 0u;
  uint32_t cycleWraps = 0u;
  uint64_t durationCycles = 0u;
  uint32_t totalEntries = 0u;
  uint32_t phaseEntries[static_cast<uint8_t>(Phase::Count)] = {};
  uint32_t phaseMaxCycles[static_cast<uint8_t>(Phase::Count)] = {};
  uint32_t maxCycles = 0u;
  uint32_t completedPulses = 0u;
  uint32_t pendingObservations = 0u;
  uint32_t maxPendingStreak = 0u;
  uint32_t saturationFlags = SaturatedNone;
};

Phase classifyPhase(uint32_t togglesDone,
                    uint32_t togglesRemaining,
                    uint32_t totalToggles,
                    uint32_t accelToggles,
                    uint32_t decelToggles);

void reset(State& state, uint32_t startCycle);
void markAborted(State& state);
void finishWithoutSample(State& state, uint32_t endCycle, bool aborted);
void recordSample(State& state,
                  Phase phase,
                  uint32_t entryCycle,
                  uint32_t exitCycle,
                  bool updatePending,
                  bool completedPulse,
                  bool moveComplete);
Snapshot makeSnapshot(const State& state);

} // namespace StepperIsrInstrumentation

#endif /* INC_STEPPERISRINSTRUMENTATION_H_ */
