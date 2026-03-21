#ifndef INC_FLASHOUTPUTSTATE_H_
#define INC_FLASHOUTPUTSTATE_H_

#include <stdint.h>

namespace FlashOutputState {

enum class Mode : uint8_t {
  SafeIdle = 0u,
  ArmedOutput
};

enum class Transition : uint8_t {
  NoChange = 0u,
  SafeIdleApplied,
  ArmedOutputApplied
};

struct State {
  Mode mode = Mode::SafeIdle;
};

constexpr Transition setSafeIdle(State& state)
{
  if (state.mode == Mode::SafeIdle) {
    return Transition::NoChange;
  }
  state.mode = Mode::SafeIdle;
  return Transition::SafeIdleApplied;
}

constexpr Transition armOutput(State& state)
{
  if (state.mode == Mode::ArmedOutput) {
    return Transition::NoChange;
  }
  state.mode = Mode::ArmedOutput;
  return Transition::ArmedOutputApplied;
}

constexpr bool isSafeIdle(const State& state)
{
  return state.mode == Mode::SafeIdle;
}

constexpr bool isArmedOutput(const State& state)
{
  return state.mode == Mode::ArmedOutput;
}

constexpr const char* modeToken(Mode mode)
{
  switch (mode) {
    case Mode::ArmedOutput:
      return "armed_output";
    case Mode::SafeIdle:
    default:
      return "safe_idle";
  }
}

}  // namespace FlashOutputState

#endif /* INC_FLASHOUTPUTSTATE_H_ */
