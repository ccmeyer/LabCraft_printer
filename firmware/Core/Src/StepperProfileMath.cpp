#include "StepperProfileMath.h"

#include <cmath>

namespace StepperProfileMath {

namespace {
constexpr float kPiF = 3.14159265f;
}

uint32_t arrForFreq(uint32_t timerClockHz, uint32_t freqHz) {
  if (freqHz < 1u) freqHz = 1u;
  uint64_t arrp1 = static_cast<uint64_t>(timerClockHz) / static_cast<uint64_t>(freqHz * 2u);
  if (arrp1 < 2u) arrp1 = 2u;
  return static_cast<uint32_t>(arrp1 - 1u);
}

float ease01(Profile profile, float t) {
  if (t <= 0.f) return 0.f;
  if (t >= 1.f) return 1.f;

  switch (profile) {
    case Profile::TrapezoidalLinear:
      return t;
    case Profile::SCurveMinJerk: {
      float t2 = t * t;
      float t3 = t2 * t;
      float t4 = t3 * t;
      float t5 = t4 * t;
      return 10.f * t3 - 15.f * t4 + 6.f * t5;
    }
    case Profile::SCurveCosine:
    default:
      return 0.5f * (1.f - std::cos(t * kPiF));
  }
}

MovePlan planMove(const MovePlanInput& input) {
  MovePlan plan{};

  uint32_t cruiseHz = (input.requestedHz == 0u) ? input.maxSpeedHz : input.requestedHz;
  if (cruiseHz > input.maxSpeedHz) cruiseHz = input.maxSpeedHz;
  if (cruiseHz < 1u) cruiseHz = 1u;

  const float accel = (input.accelStepsPerSec2 > 1.f) ? input.accelStepsPerSec2 : 1.f;
  uint32_t accelSteps = static_cast<uint32_t>(std::ceil((double)cruiseHz * (double)cruiseHz / (2.0 * (double)accel)));
  if (accelSteps < 1u) accelSteps = 1u;

  if ((2u * accelSteps) > input.steps) {
    double vPeakD = std::sqrt((double)input.steps * (double)accel);
    uint32_t vPeak = static_cast<uint32_t>(std::floor(vPeakD));
    if (vPeak < 1u) vPeak = 1u;
    cruiseHz = vPeak;
    accelSteps = input.steps / 2u;
    if (accelSteps < 1u) accelSteps = 1u;
    plan.triangular = true;
  }

  uint32_t minTicks = static_cast<uint32_t>(
      ((static_cast<uint64_t>(input.minPulseNs) * input.timerClockHz) + 999999999ULL) / 1000000000ULL);
  if (minTicks < 2u) minTicks = 2u;
  const uint32_t minArr = minTicks - 1u;

  uint32_t targetArr = arrForFreq(input.timerClockHz, cruiseHz);
  if (targetArr < minArr) targetArr = minArr;
  if (targetArr > input.timerMaxArr) targetArr = input.timerMaxArr;

  uint64_t start64 = static_cast<uint64_t>(targetArr) * 5u;
  if (start64 > static_cast<uint64_t>(input.timerMaxArr)) start64 = input.timerMaxArr;
  uint32_t startArr = static_cast<uint32_t>(start64);
  if (startArr < minArr) startArr = minArr;

  plan.cruiseHz = cruiseHz;
  plan.accelSteps = accelSteps;
  plan.accelToggles = accelSteps * 2u;
  plan.decelToggles = plan.accelToggles;
  plan.minArr = minArr;
  plan.targetArr = targetArr;
  plan.startArr = startArr;
  return plan;
}

}  // namespace StepperProfileMath
