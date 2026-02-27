#ifndef INC_PRESSUREREGULATORMATH_H_
#define INC_PRESSUREREGULATORMATH_H_

#include <cstdint>

namespace PressureRegulatorMath {

struct TargetLimits {
  int32_t currentTarget = 0;
  int32_t minTarget = 0;
  int32_t maxTarget = 0;
  int32_t maxCmdStep = 0;
  int32_t maxRelStep = 0;
};

struct ProfileState {
  int32_t kpCurrent = 0;
  int32_t kiCurrent = 0;
  int32_t kdCurrent = 0;
  int32_t kpPrint = 0;
  int32_t kiPrint = 0;
  int32_t kdPrint = 0;
  int32_t kpTrack = 0;
  int32_t kiTrack = 0;
  int32_t kdTrack = 0;
  int64_t integral = 0;
  int64_t iContrib = 0;
  int64_t iCap = 0;
  uint32_t maxHzDeltaPerLoop = 0;
  uint32_t maxHzDeltaPrint = 0;
  uint32_t maxHzDeltaTrack = 0;
};

int32_t clampTarget(const TargetLimits& limits, int32_t requested);
int32_t clampRelativeTarget(const TargetLimits& limits, bool sign, int32_t delta);
ProfileState applyPrintProfile(const ProfileState& state, bool enabled);

}  // namespace PressureRegulatorMath

#endif /* INC_PRESSUREREGULATORMATH_H_ */
