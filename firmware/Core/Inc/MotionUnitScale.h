#pragma once

#include "TMC2208Configuration.h"

#include <cstdint>
#include <limits>

// The application and wire protocol continue to use the historical MRES=2
// coordinate system. This boundary converts those logical units to the
// complete STEP cycles required by the configured TMC2208 microstep setting.
namespace MotionUnitScale {

struct QuantizedDisplacement {
  bool valid = false;
  bool positive = true;
  uint32_t logicalMagnitude = 0u;
  uint32_t nativeStepCycles = 0u;
  int32_t target = 0;
};

inline constexpr uint32_t logicalUnitsPerNativeStepForMres(uint8_t mres) {
  return mres == 3u ? 2u : 1u;
}

inline constexpr uint32_t logicalUnitsPerNativeStep() {
  return logicalUnitsPerNativeStepForMres(
      TMC2208Configuration::kMres);
}

inline constexpr uint32_t toNativeStepCycles(uint32_t logicalMagnitude,
                                              uint32_t scale) {
  return scale == 0u ? 0u : logicalMagnitude / scale;
}

inline constexpr uint32_t toLogicalMagnitude(uint32_t nativeStepCycles,
                                              uint32_t scale) {
  return scale == 0u
      ? 0u
      : nativeStepCycles >
          std::numeric_limits<uint32_t>::max() / scale
      ? std::numeric_limits<uint32_t>::max()
      : nativeStepCycles * scale;
}

inline constexpr uint32_t toNativeRate(uint32_t logicalRateHz,
                                        uint32_t scale) {
  return logicalRateHz == 0u || scale == 0u
      ? 0u
      : ((logicalRateHz / scale) == 0u ? 1u : logicalRateHz / scale);
}

inline constexpr uint32_t toNativeAcceleration(
    uint32_t logicalStepsPerSec2,
    uint32_t scale) {
  return logicalStepsPerSec2 == 0u || scale == 0u
      ? 0u
      : ((logicalStepsPerSec2 / scale) == 0u
             ? 1u
             : logicalStepsPerSec2 / scale);
}

inline float toNativeAcceleration(float logicalStepsPerSec2,
                                  uint32_t scale) {
  return scale == 0u ? 0.0f
                     : logicalStepsPerSec2 / static_cast<float>(scale);
}

inline constexpr uint32_t toNativeStepCycles(uint32_t logicalMagnitude) {
  return toNativeStepCycles(logicalMagnitude,
                            logicalUnitsPerNativeStep());
}

inline constexpr uint32_t toLogicalMagnitude(uint32_t nativeStepCycles) {
  return toLogicalMagnitude(nativeStepCycles,
                            logicalUnitsPerNativeStep());
}

inline constexpr uint32_t toNativeRate(uint32_t logicalRateHz) {
  return toNativeRate(logicalRateHz, logicalUnitsPerNativeStep());
}

inline constexpr uint32_t toNativeAcceleration(
    uint32_t logicalStepsPerSec2) {
  return toNativeAcceleration(logicalStepsPerSec2,
                              logicalUnitsPerNativeStep());
}

inline float toNativeAcceleration(float logicalStepsPerSec2) {
  return toNativeAcceleration(logicalStepsPerSec2,
                              logicalUnitsPerNativeStep());
}

inline QuantizedDisplacement quantizeDisplacement(int32_t current,
                                                   int64_t requestedDelta,
                                                   uint32_t scale) {
  QuantizedDisplacement result{};
  if (scale == 0u) return result;

  result.positive = requestedDelta >= 0;
  const uint64_t magnitude = result.positive
      ? static_cast<uint64_t>(requestedDelta)
      : static_cast<uint64_t>(-(requestedDelta + 1)) + 1u;
  const uint64_t nativeSteps = magnitude / scale;
  if (nativeSteps > std::numeric_limits<uint32_t>::max()) return result;

  const uint64_t logicalMagnitude = nativeSteps * scale;
  if (logicalMagnitude > std::numeric_limits<uint32_t>::max()) return result;
  const int64_t target = result.positive
      ? static_cast<int64_t>(current) + static_cast<int64_t>(logicalMagnitude)
      : static_cast<int64_t>(current) - static_cast<int64_t>(logicalMagnitude);
  if (target < std::numeric_limits<int32_t>::min() ||
      target > std::numeric_limits<int32_t>::max()) {
    return result;
  }

  result.valid = true;
  result.nativeStepCycles = static_cast<uint32_t>(nativeSteps);
  result.logicalMagnitude = static_cast<uint32_t>(logicalMagnitude);
  result.target = static_cast<int32_t>(target);
  return result;
}

inline QuantizedDisplacement quantizeDisplacement(int32_t current,
                                                   int64_t requestedDelta) {
  return quantizeDisplacement(current,
                              requestedDelta,
                              logicalUnitsPerNativeStep());
}

inline bool canonicalizeAbsoluteTarget(int32_t current,
                                       int32_t requested,
                                       int32_t& canonical) {
  const QuantizedDisplacement move = quantizeDisplacement(
      current,
      static_cast<int64_t>(requested) - static_cast<int64_t>(current));
  if (!move.valid) return false;
  canonical = move.target;
  return true;
}

}  // namespace MotionUnitScale
