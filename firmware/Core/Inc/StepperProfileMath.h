#ifndef INC_STEPPERPROFILEMATH_H_
#define INC_STEPPERPROFILEMATH_H_

#include <cstdint>

namespace StepperProfileMath {

enum class Profile : uint8_t {
  TrapezoidalLinear = 0,
  SCurveCosine = 1,
  SCurveMinJerk = 2
};

struct MovePlanInput {
  uint32_t steps = 0;
  uint32_t requestedHz = 0;
  uint32_t maxSpeedHz = 0;
  float accelStepsPerSec2 = 1.0f;
  uint32_t timerClockHz = 0;
  uint32_t timerMaxArr = 0;
  uint32_t minPulseNs = 2000u;
};

struct MovePlan {
  uint32_t cruiseHz = 0;
  uint32_t accelSteps = 0;
  uint32_t accelToggles = 0;
  uint32_t decelToggles = 0;
  uint32_t minArr = 0;
  uint32_t targetArr = 0;
  uint32_t startArr = 0;
  bool triangular = false;
};

uint32_t arrForFreq(uint32_t timerClockHz, uint32_t freqHz);
float ease01(Profile profile, float t);
MovePlan planMove(const MovePlanInput& input);

}  // namespace StepperProfileMath

#endif /* INC_STEPPERPROFILEMATH_H_ */
