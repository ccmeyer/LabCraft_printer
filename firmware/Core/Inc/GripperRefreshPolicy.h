#ifndef INC_GRIPPERREFRESHPOLICY_H_
#define INC_GRIPPERREFRESHPOLICY_H_

#include <cstdint>

namespace GripperRefreshPolicy {

enum class Mode : uint8_t {
  Disabled = 0u,
  DeferredUntilDispense = 1u,
};

enum class PeriodicTimerDirective : uint8_t {
  None = 0u,
  StartOrReset = 1u,
  Stop = 2u,
};

struct State {
  Mode mode = Mode::Disabled;
  bool refreshPending = false;
  bool hasPulseCompletion = false;
  uint32_t lastPulseCompletionMs = 0u;
};

// This policy is deliberately hardware- and RTOS-independent. Callers are
// responsible for serializing access to State and applying timer directives.
void initialize(State& state);
PeriodicTimerDirective enableDeferred(State& state);
PeriodicTimerDirective disable(State& state);
bool markRefreshDue(State& state);
// A successful claim authorizes one pulse. Before starting it, the caller must
// stop the periodic timer; recordPulseCompleted() supplies the restart action.
bool claimPendingAfterDispense(State& state);
PeriodicTimerDirective recordPulseCompleted(State& state, uint32_t nowMs);
// nowMs and the completion tick must use the same wrapping millisecond clock.
// The elapsed time must not span more than one complete uint32_t rollover.
uint32_t remainingDispenseCooldownMs(const State& state,
                                    uint32_t nowMs,
                                    uint32_t cooldownMs);
bool isDeferred(const State& state);
bool hasPending(const State& state);

}  // namespace GripperRefreshPolicy

#endif  // INC_GRIPPERREFRESHPOLICY_H_
