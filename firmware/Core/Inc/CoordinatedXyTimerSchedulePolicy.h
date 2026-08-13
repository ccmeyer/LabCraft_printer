#ifndef INC_COORDINATEDXYTIMERSCHEDULEPOLICY_H_
#define INC_COORDINATEDXYTIMERSCHEDULEPOLICY_H_

#include <cstdint>

namespace CoordinatedXyTimerSchedulePolicy {

constexpr uint32_t kConditionalGuardTicks = 1125u;

struct Decision {
  bool applicable = false;
  bool sampleValid = true;
  bool rearm = false;
  uint32_t remainingTicks = 0u;
};

constexpr Decision decide(bool physicalEdgeEmitted,
                          bool stopTimer,
                          bool timerSampleValid,
                          uint32_t timerCount,
                          uint32_t timerArr,
                          bool updatePending) {
  if (!physicalEdgeEmitted || stopTimer) {
    return {};
  }
  if (!timerSampleValid) {
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

}  // namespace CoordinatedXyTimerSchedulePolicy

#endif /* INC_COORDINATEDXYTIMERSCHEDULEPOLICY_H_ */
