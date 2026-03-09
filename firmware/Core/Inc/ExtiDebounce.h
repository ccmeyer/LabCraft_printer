#ifndef INC_EXTIDEBounce_H_
#define INC_EXTIDEBounce_H_

#include <stdint.h>

namespace ExtiDebounce {

enum class ArmAction : uint8_t {
  Ignore = 0,
  Armed,
  ImmediateFallback
};

constexpr uint32_t lineMask(uint8_t line)
{
  return (line < 16u) ? (1u << line) : 0u;
}

constexpr bool isAsserted(bool pinHigh, bool activeHigh)
{
  return pinHigh == activeHigh;
}

constexpr ArmAction decideArmAction(bool schedulerRunning,
                                    bool timerReady,
                                    bool timerArmSucceeded)
{
  if (!schedulerRunning) {
    return ArmAction::Ignore;
  }
  if (!timerReady || !timerArmSucceeded) {
    return ArmAction::ImmediateFallback;
  }
  return ArmAction::Armed;
}

}  // namespace ExtiDebounce

#endif /* INC_EXTIDEBounce_H_ */
