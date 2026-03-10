#ifndef INC_STEPPERLIMITPOLICY_H_
#define INC_STEPPERLIMITPOLICY_H_

#include <stdint.h>

namespace StepperLimitPolicy {

enum class PullMode : uint32_t {
  None = 0u,
  Up = 1u,
  Down = 2u,
  Auto = 0xFFFFFFFFu
};

enum class LatchedLimitAction : uint8_t {
  ConfirmLater = 0,
  HardStopNow
};

constexpr PullMode resolvePullMode(PullMode requested, bool activeHigh)
{
  if (requested != PullMode::Auto) {
    return requested;
  }
  return activeHigh ? PullMode::Down : PullMode::Up;
}

constexpr bool homeLimitDetected(bool limitSeenLatched, bool limitCurrentlyAsserted)
{
  return limitSeenLatched || limitCurrentlyAsserted;
}

constexpr LatchedLimitAction decideLatchedLimitAction(bool moveActive,
                                                      bool homeSoftStopEnabled,
                                                      bool hardStopOnHomeHit)
{
  if (!moveActive || !homeSoftStopEnabled || !hardStopOnHomeHit) {
    return LatchedLimitAction::ConfirmLater;
  }
  return LatchedLimitAction::HardStopNow;
}

}  // namespace StepperLimitPolicy

#endif /* INC_STEPPERLIMITPOLICY_H_ */
