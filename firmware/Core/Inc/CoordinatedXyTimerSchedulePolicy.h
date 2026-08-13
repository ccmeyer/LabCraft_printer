#ifndef INC_COORDINATEDXYTIMERSCHEDULEPOLICY_H_
#define INC_COORDINATEDXYTIMERSCHEDULEPOLICY_H_

#include <cstdint>

namespace CoordinatedXyTimerSchedulePolicy {

// FreeRunning preserves the production timer behavior. RearmFromActualEdge is
// diagnostic-only until its MRES=3 HIL evidence has been reviewed.
enum class Mode : uint8_t {
  FreeRunning = 0u,
  RearmFromActualEdge = 1u,
};

constexpr bool isValid(Mode mode) {
  return mode == Mode::FreeRunning || mode == Mode::RearmFromActualEdge;
}

constexpr bool shouldRearm(Mode mode,
                           bool physicalEdgeEmitted,
                           bool stopTimer) {
  return mode == Mode::RearmFromActualEdge && physicalEdgeEmitted &&
      !stopTimer;
}

}  // namespace CoordinatedXyTimerSchedulePolicy

#endif /* INC_COORDINATEDXYTIMERSCHEDULEPOLICY_H_ */
