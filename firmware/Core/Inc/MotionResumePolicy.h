#pragma once

#include <cstdint>
#include <limits>

namespace MotionResumePolicy {

// Resume is intentionally gentler than the legacy fresh-move start, which is
// one fifth of cruise. Values are expressed in the application's historical
// logical motion units per second.
constexpr uint32_t kResumeStartRateHz = 3000u;

// TMC2208 short-protection flags are cleared by disabling the power stage
// through ENN. Keep the pulse visible across multiple task/timer intervals,
// then allow the re-enabled driver the datasheet's bounded StealthChop
// standstill-tuning interval before issuing the first resumed STEP edge.
constexpr uint32_t kDriverDisablePulseMs = 2u;
constexpr uint32_t kDriverPoweredSettleMs = 130u;

inline constexpr uint32_t selectStartRateHz(uint32_t requestedRateHz) {
  if (requestedRateHz == 0u) return kResumeStartRateHz;
  return requestedRateHz < kResumeStartRateHz
      ? requestedRateHz
      : kResumeStartRateHz;
}

struct RemainingMove {
  bool valid = false;
  bool immediate = false;
  bool positive = true;
  uint32_t magnitude = 0u;
};

inline constexpr RemainingMove remainingMove(int32_t current,
                                             int32_t target) {
  RemainingMove result{};
  const int64_t delta = static_cast<int64_t>(target) - current;
  result.positive = delta >= 0;
  const uint64_t magnitude = result.positive
      ? static_cast<uint64_t>(delta)
      : static_cast<uint64_t>(-(delta + 1)) + 1u;
  if (magnitude > std::numeric_limits<uint32_t>::max()) return result;
  result.valid = true;
  result.immediate = magnitude == 0u;
  result.magnitude = static_cast<uint32_t>(magnitude);
  return result;
}

}  // namespace MotionResumePolicy
