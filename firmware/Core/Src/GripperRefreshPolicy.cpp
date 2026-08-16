#include "GripperRefreshPolicy.h"

namespace GripperRefreshPolicy {

void initialize(State& state)
{
  state = State{};
}

PeriodicTimerDirective enableDeferred(State& state)
{
  state.mode = Mode::DeferredUntilDispense;
  state.refreshPending = false;
  return PeriodicTimerDirective::StartOrReset;
}

PeriodicTimerDirective disable(State& state)
{
  state.mode = Mode::Disabled;
  state.refreshPending = false;
  return PeriodicTimerDirective::Stop;
}

bool markRefreshDue(State& state)
{
  if (state.mode != Mode::DeferredUntilDispense || state.refreshPending) {
    return false;
  }

  state.refreshPending = true;
  return true;
}

bool claimPendingAfterDispense(State& state)
{
  if (state.mode != Mode::DeferredUntilDispense || !state.refreshPending) {
    return false;
  }

  state.refreshPending = false;
  return true;
}

PeriodicTimerDirective recordPulseCompleted(State& state, uint32_t nowMs)
{
  state.refreshPending = false;
  state.hasPulseCompletion = true;
  state.lastPulseCompletionMs = nowMs;

  if (state.mode == Mode::DeferredUntilDispense) {
    return PeriodicTimerDirective::StartOrReset;
  }
  return PeriodicTimerDirective::None;
}

uint32_t remainingDispenseCooldownMs(const State& state,
                                    uint32_t nowMs,
                                    uint32_t cooldownMs)
{
  if (!state.hasPulseCompletion || cooldownMs == 0u) {
    return 0u;
  }

  const uint32_t elapsedMs = nowMs - state.lastPulseCompletionMs;
  if (elapsedMs >= cooldownMs) {
    return 0u;
  }
  return cooldownMs - elapsedMs;
}

bool isDeferred(const State& state)
{
  return state.mode == Mode::DeferredUntilDispense;
}

bool hasPending(const State& state)
{
  return state.refreshPending;
}

}  // namespace GripperRefreshPolicy
