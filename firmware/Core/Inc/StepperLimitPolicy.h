#ifndef INC_STEPPERLIMITPOLICY_H_
#define INC_STEPPERLIMITPOLICY_H_

#include <stdint.h>

namespace StepperLimitPolicy {

enum class DirectStartDecision : uint8_t {
  Proceed = 0u,
  EscapeAssertedLimit = 1u,
  RejectAssertedTowardLimit = 2u,
  RejectUntilReleased = 3u,
};

enum class PullMode : uint32_t {
  None = 0u,
  Up = 1u,
  Down = 2u,
  Auto = 0xFFFFFFFFu
};

constexpr uint32_t nextMoveGeneration(uint32_t currentGeneration)
{
  return (currentGeneration == 0xFFFFFFFFu) ? 1u : (currentGeneration + 1u);
}

constexpr uint32_t normalizeBackoffSteps(uint32_t backoffSteps)
{
  return (backoffSteps == 0u) ? 1u : backoffSteps;
}

constexpr uint32_t finalHomeBackoffSteps(uint32_t backoffSteps)
{
  const uint32_t scaled = normalizeBackoffSteps(backoffSteps) / 4u;
  return (scaled == 0u) ? 1u : scaled;
}

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

constexpr uint32_t releaseSearchGuardSteps(uint32_t backoffSteps)
{
  const uint32_t chunk = normalizeBackoffSteps(backoffSteps);
  const uint64_t scaled = static_cast<uint64_t>(chunk) * 16u;
  return (scaled < 1024u) ? 1024u
                          : ((scaled > 100000u) ? 100000u : static_cast<uint32_t>(scaled));
}

constexpr bool fineHomeLimitDetected(bool releasedBeforeFine,
                                     bool limitSeenLatched,
                                     bool limitCurrentlyAsserted)
{
  return releasedBeforeFine ? limitSeenLatched
                            : homeLimitDetected(limitSeenLatched, limitCurrentlyAsserted);
}

constexpr bool shouldApplyDebounceCallback(uint32_t armedGeneration,
                                           uint32_t currentGeneration)
{
  return (armedGeneration != 0u) && (armedGeneration == currentGeneration);
}

constexpr DirectStartDecision classifyDirectStart(bool limitAsserted,
                                                   bool direction,
                                                   bool homeTowardLimitDirection,
                                                   bool releaseConfirmed)
{
  const bool movingTowardLimit = direction == homeTowardLimitDirection;
  if (limitAsserted) {
    return movingTowardLimit
        ? DirectStartDecision::RejectAssertedTowardLimit
        : DirectStartDecision::EscapeAssertedLimit;
  }
  if (movingTowardLimit && !releaseConfirmed) {
    return DirectStartDecision::RejectUntilReleased;
  }
  return DirectStartDecision::Proceed;
}

}  // namespace StepperLimitPolicy

#endif /* INC_STEPPERLIMITPOLICY_H_ */
