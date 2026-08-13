#include "DirectStepperProfile.h"

#include <algorithm>

namespace DirectStepperProfile {

#if defined(__GNUC__) && !defined(UNIT_TEST)
#define LC_DIRECT_PROFILE_OPTIMIZED __attribute__((optimize("O2"), hot))
#else
#define LC_DIRECT_PROFILE_OPTIMIZED
#endif

void reset(State& state) {
  state = State{};
}

bool prepare(State& state,
             uint32_t totalToggles,
             uint32_t accelToggles,
             uint32_t decelToggles,
             uint32_t startArr,
             uint32_t targetArr,
             uint32_t minArr,
             uint32_t maxArr) {
  reset(state);
  state.selected = true;
  state.totalToggles = totalToggles;
  state.accelToggles = accelToggles;
  state.decelToggles = decelToggles;
  state.targetArr = targetArr;

  if (totalToggles == 0u || accelToggles > totalToggles ||
      decelToggles > totalToggles || minArr > maxArr ||
      startArr < minArr || startArr > maxArr ||
      targetArr < minArr || targetArr > maxArr) {
    state.prepareFailed = true;
    return false;
  }

  const auto accelStatus = NormalizedCosineProfile::prepare(
      {startArr, targetArr, minArr, maxArr, accelToggles},
      state.acceleration);
  const auto decelStatus = NormalizedCosineProfile::prepare(
      {targetArr, startArr, minArr, maxArr, decelToggles},
      state.deceleration);
  if (accelStatus == NormalizedCosineProfile::PrepareStatus::InvalidBounds ||
      decelStatus == NormalizedCosineProfile::PrepareStatus::InvalidBounds) {
    state.prepareFailed = true;
    return false;
  }

  state.active = true;
  return true;
}

uint32_t expectedDecelSamples(uint32_t totalToggles,
                              uint32_t accelToggles,
                              uint32_t decelToggles) {
  if (totalToggles == 0u || accelToggles > totalToggles ||
      decelToggles > totalToggles) {
    return 0u;
  }

  // Preserve Stepper's historical strict '>' deceleration boundary and the
  // acceleration branch's precedence if the two ramps overlap.
  const uint32_t decelBoundary = totalToggles - decelToggles;
  const uint32_t firstDecel = std::max(accelToggles, decelBoundary + 1u);
  return (firstDecel < totalToggles) ? (totalToggles - firstDecel) : 0u;
}

LC_DIRECT_PROFILE_OPTIMIZED
bool nextSample(State& state,
                uint32_t completedToggles,
                uint32_t remainingToggles,
                Sample& sample) {
  sample = Sample{};
  if (!state.selected || !state.active || state.completed ||
      state.prepareFailed || state.runtimeFailed || state.aborted ||
      completedToggles >= state.totalToggles ||
      remainingToggles == 0u ||
      remainingToggles != (state.totalToggles - completedToggles)) {
    state.runtimeFailed = true;
    state.active = false;
    return false;
  }

  if (completedToggles < state.accelToggles) {
    sample.phase = Phase::Acceleration;
    sample.arr = NormalizedCosineProfile::currentArr(state.acceleration);
    if (!NormalizedCosineProfile::advance(state.acceleration)) {
      state.runtimeFailed = true;
      state.active = false;
      return false;
    }
    return true;
  }

  if (completedToggles > (state.totalToggles - state.decelToggles)) {
    sample.phase = Phase::Deceleration;
    if (!NormalizedCosineProfile::advance(state.deceleration)) {
      state.runtimeFailed = true;
      state.active = false;
      return false;
    }
    sample.arr = NormalizedCosineProfile::currentArr(state.deceleration);
    return true;
  }

  sample.phase = Phase::Cruise;
  sample.arr = state.targetArr;
  return true;
}

bool finish(State& state) {
  if (!state.selected || !state.active || state.prepareFailed ||
      state.runtimeFailed || state.aborted ||
      state.acceleration.intervalIndex != state.accelToggles ||
      state.deceleration.intervalIndex != expectedDecelSamples(
          state.totalToggles, state.accelToggles, state.decelToggles)) {
    state.runtimeFailed = state.selected && !state.aborted;
    state.active = false;
    return false;
  }
  state.active = false;
  state.completed = true;
  return true;
}

void abort(State& state) {
  if (state.selected && state.active) {
    state.aborted = true;
    state.active = false;
  }
}

Snapshot snapshot(const State& state) {
  Snapshot result{};
  result.totalToggles = state.totalToggles;
  result.accelIntervals = state.accelToggles;
  result.accelConsumed = state.acceleration.intervalIndex;
  result.decelIntervals = state.decelToggles;
  result.decelConsumed = state.deceleration.intervalIndex;
  result.startArr = state.acceleration.fromArr;
  result.targetArr = state.targetArr;
  result.selected = state.selected;
  result.active = state.active;
  result.completed = state.completed;
  result.prepareFailed = state.prepareFailed;
  result.runtimeFailed = state.runtimeFailed;
  result.aborted = state.aborted;
  return result;
}

#undef LC_DIRECT_PROFILE_OPTIMIZED

}  // namespace DirectStepperProfile
