#ifndef INC_PRESSUREREGULATORWATCHDOGPOLICY_H_
#define INC_PRESSUREREGULATORWATCHDOGPOLICY_H_

#include <stdint.h>

namespace PressureRegulatorWatchdogPolicy {

enum class Hold : uint8_t {
  Inactive = 1u << 0,
  MotionHold = 1u << 1,
  Recovery = 1u << 2,
};

constexpr uint8_t holdBit(Hold hold) {
  return static_cast<uint8_t>(hold);
}

constexpr uint8_t withHold(uint8_t mask, Hold hold) {
  return static_cast<uint8_t>(mask | holdBit(hold));
}

constexpr uint8_t withoutHold(uint8_t mask, Hold hold) {
  return static_cast<uint8_t>(mask & static_cast<uint8_t>(~holdBit(hold)));
}

constexpr bool hasHold(uint8_t mask, Hold hold) {
  return (mask & holdBit(hold)) != 0u;
}

constexpr bool shouldEnableWatchdog(uint8_t mask) {
  return mask == 0u;
}

constexpr bool recoveryBusy(bool homing, bool resetting, uint8_t mask) {
  return homing || resetting || hasHold(mask, Hold::Recovery);
}

constexpr bool canEnterMotionHold(bool active,
                                  bool taskPresent,
                                  bool homing,
                                  bool resetting,
                                  uint8_t mask) {
  return active && taskPresent && !recoveryBusy(homing, resetting, mask);
}

} // namespace PressureRegulatorWatchdogPolicy

#endif /* INC_PRESSUREREGULATORWATCHDOGPOLICY_H_ */
