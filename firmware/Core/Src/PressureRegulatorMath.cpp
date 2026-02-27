#include "PressureRegulatorMath.h"

namespace PressureRegulatorMath {

int32_t clampTarget(const TargetLimits& limits, int32_t requested) {
  int32_t clamped = requested;
  if (clamped < limits.minTarget) clamped = limits.minTarget;
  if (clamped > limits.maxTarget) clamped = limits.maxTarget;

  int32_t delta = clamped - limits.currentTarget;
  if (delta > limits.maxCmdStep) clamped = limits.currentTarget + limits.maxCmdStep;
  if (delta < -limits.maxCmdStep) clamped = limits.currentTarget - limits.maxCmdStep;

  return clamped;
}

int32_t clampRelativeTarget(const TargetLimits& limits, bool sign, int32_t delta) {
  if (delta < 0) delta = -delta;
  if (delta > limits.maxRelStep) delta = limits.maxRelStep;

  int32_t next = limits.currentTarget + (sign ? delta : -delta);
  if (next < limits.minTarget) next = limits.minTarget;
  if (next > limits.maxTarget) next = limits.maxTarget;
  return next;
}

ProfileState applyPrintProfile(const ProfileState& state, bool enabled) {
  ProfileState next = state;
  const int64_t prevIContrib = static_cast<int64_t>(state.kiCurrent) * state.integral;

  next.kpCurrent = enabled ? state.kpPrint : state.kpTrack;
  next.kiCurrent = enabled ? state.kiPrint : state.kiTrack;
  next.kdCurrent = enabled ? state.kdPrint : state.kdTrack;
  next.maxHzDeltaPerLoop = enabled ? state.maxHzDeltaPrint : state.maxHzDeltaTrack;

  if (next.kiCurrent == 0) {
    next.iContrib = prevIContrib;
    return next;
  }

  const int64_t desired = (prevIContrib != 0) ? prevIContrib : state.iContrib;
  int64_t newIntegral = desired / static_cast<int64_t>(next.kiCurrent);
  if (newIntegral > state.iCap) newIntegral = state.iCap;
  if (newIntegral < -state.iCap) newIntegral = -state.iCap;

  next.integral = newIntegral;
  next.iContrib = static_cast<int64_t>(next.kiCurrent) * next.integral;
  return next;
}

}  // namespace PressureRegulatorMath
