#ifndef INC_COORDINATEDXYTIMERSCHEDULEPOLICY_H_
#define INC_COORDINATEDXYTIMERSCHEDULEPOLICY_H_

#include <cstdint>

namespace CoordinatedXyTimerSchedulePolicy {

// FreeRunning preserves the production timer behavior. The other modes are
// diagnostic-only until their MRES=3 HIL evidence has been reviewed.
enum class Mode : uint8_t {
  FreeRunning = 0u,
  RearmFromActualEdge = 1u,
  ConditionalLateRearm = 2u,
};

constexpr uint32_t kConditionalGuardTicks = 1125u;
constexpr uint32_t kInjectionTargetSlackTicks = 900u;
constexpr uint32_t kInjectionMaxCoreCycles = 4500u;

struct Decision {
  bool applicable = false;
  bool sampleValid = true;
  bool rearm = false;
  uint32_t remainingTicks = 0u;
};

constexpr bool isValid(Mode mode) {
  return mode == Mode::FreeRunning || mode == Mode::RearmFromActualEdge ||
      mode == Mode::ConditionalLateRearm;
}

constexpr bool shouldRearm(Mode mode,
                           bool physicalEdgeEmitted,
                           bool stopTimer) {
  return mode == Mode::RearmFromActualEdge && physicalEdgeEmitted &&
      !stopTimer;
}

constexpr Decision decide(Mode mode,
                          bool physicalEdgeEmitted,
                          bool stopTimer,
                          bool timerSampleValid,
                          uint32_t timerCount,
                          uint32_t timerArr,
                          bool updatePending) {
  if (!physicalEdgeEmitted || stopTimer || mode == Mode::FreeRunning) {
    return {};
  }
  if (mode == Mode::RearmFromActualEdge) {
    return {true, true, true, 0u};
  }
  if (mode != Mode::ConditionalLateRearm || !timerSampleValid) {
    return {true, false, false, 0u};
  }
  if (updatePending || timerCount > timerArr) {
    return {true, true, true, 0u};
  }
  const uint32_t remainingTicks = (timerArr - timerCount) + 1u;
  return {true,
          true,
          remainingTicks <= kConditionalGuardTicks,
          remainingTicks};
}

constexpr bool shouldAttemptInjection(Mode mode,
                                      bool armed,
                                      bool nonterminal,
                                      bool eligiblePhase,
                                      bool risingEdge,
                                      bool stepLow) {
  return mode == Mode::ConditionalLateRearm && armed && nonterminal &&
      eligiblePhase && risingEdge && stepLow;
}

// Prefer the first cruise event when a plateau exists. A zero-cruise profile
// transitions directly from acceleration to deceleration, so its first
// deceleration event is the only equivalent peak-rate injection point.
constexpr bool isInjectionPhaseEligible(bool cruisePhase,
                                        bool decelerationPhase,
                                        uint32_t cruiseSteps,
                                        uint32_t masterStepIndex,
                                        uint32_t accelerationSteps) {
  if (cruiseSteps != 0u) {
    return cruisePhase;
  }
  return decelerationPhase && masterStepIndex == accelerationSteps;
}

constexpr uint32_t elapsedCoreCycles(uint32_t startCycle,
                                     uint32_t currentCycle) {
  return currentCycle - startCycle;
}

constexpr bool injectionWaitExpired(uint32_t startCycle,
                                    uint32_t currentCycle) {
  return elapsedCoreCycles(startCycle, currentCycle) >=
      kInjectionMaxCoreCycles;
}

}  // namespace CoordinatedXyTimerSchedulePolicy

#endif /* INC_COORDINATEDXYTIMERSCHEDULEPOLICY_H_ */
