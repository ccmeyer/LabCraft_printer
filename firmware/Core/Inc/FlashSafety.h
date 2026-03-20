#ifndef INC_FLASHSAFETY_H_
#define INC_FLASHSAFETY_H_

#include <stdint.h>

namespace FlashSafety {

enum class FaultReason : uint8_t {
  None = 0u,
  LineHighOnArm,
  RetriggerWhileHigh,
  LineStuckHigh
};

enum class ArmAction : uint8_t {
  Armed = 0u,
  FaultLatched
};

enum class TriggerAction : uint8_t {
  IgnoredDisarmed = 0u,
  IgnoredFaultLatched,
  Accepted,
  FaultLatched
};

enum class ReleaseAction : uint8_t {
  Released = 0u,
  WaitingForLow,
  FaultLatched
};

struct State {
  bool sessionArmed = false;
  bool faultLatched = false;
  bool awaitingRelease = false;
  FaultReason faultReason = FaultReason::None;
};

constexpr void clear(State& state)
{
  state.sessionArmed = false;
  state.faultLatched = false;
  state.awaitingRelease = false;
  state.faultReason = FaultReason::None;
}

constexpr ArmAction arm(State& state, bool lineHigh)
{
  clear(state);
  if (lineHigh) {
    state.faultLatched = true;
    state.faultReason = FaultReason::LineHighOnArm;
    return ArmAction::FaultLatched;
  }
  state.sessionArmed = true;
  return ArmAction::Armed;
}

constexpr TriggerAction onTrigger(State& state)
{
  if (state.faultLatched) {
    return TriggerAction::IgnoredFaultLatched;
  }
  if (!state.sessionArmed) {
    return TriggerAction::IgnoredDisarmed;
  }
  if (state.awaitingRelease) {
    state.sessionArmed = false;
    state.faultLatched = true;
    state.awaitingRelease = false;
    state.faultReason = FaultReason::RetriggerWhileHigh;
    return TriggerAction::FaultLatched;
  }
  state.awaitingRelease = true;
  return TriggerAction::Accepted;
}

constexpr ReleaseAction onReleasePoll(State& state,
                                      bool lineHigh,
                                      uint32_t elapsedMs,
                                      uint32_t timeoutMs)
{
  if (!state.awaitingRelease) {
    return ReleaseAction::Released;
  }
  if (!lineHigh) {
    state.awaitingRelease = false;
    return ReleaseAction::Released;
  }
  if (elapsedMs < timeoutMs) {
    return ReleaseAction::WaitingForLow;
  }
  state.sessionArmed = false;
  state.faultLatched = true;
  state.awaitingRelease = false;
  state.faultReason = FaultReason::LineStuckHigh;
  return ReleaseAction::FaultLatched;
}

constexpr bool isSessionArmed(const State& state)
{
  return state.sessionArmed;
}

constexpr bool isFaultLatched(const State& state)
{
  return state.faultLatched;
}

const char* faultReasonToken(FaultReason reason);

}  // namespace FlashSafety

#endif /* INC_FLASHSAFETY_H_ */
