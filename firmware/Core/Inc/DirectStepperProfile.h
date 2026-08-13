#ifndef INC_DIRECTSTEPPERPROFILE_H_
#define INC_DIRECTSTEPPERPROFILE_H_

#include "NormalizedCosineProfile.h"

#include <cstdint>

// Pure state machine used by the independent X/Y/Z timer callbacks. It keeps
// the historical toggle-phase boundaries while replacing per-callback float
// cosine evaluation with the already-qualified fixed-point normalized LUT.
namespace DirectStepperProfile {

enum class Phase : uint8_t {
  Acceleration = 0,
  Cruise = 1,
  Deceleration = 2,
};

struct Sample {
  uint32_t arr = 0u;
  Phase phase = Phase::Cruise;
};

struct State {
  NormalizedCosineProfile::RampCursor acceleration{};
  NormalizedCosineProfile::RampCursor deceleration{};
  uint32_t totalToggles = 0u;
  uint32_t accelToggles = 0u;
  uint32_t decelToggles = 0u;
  uint32_t targetArr = 0u;
  bool selected = false;
  bool active = false;
  bool completed = false;
  bool prepareFailed = false;
  bool runtimeFailed = false;
  bool aborted = false;
};

struct Snapshot {
  uint32_t totalToggles = 0u;
  uint32_t accelIntervals = 0u;
  uint32_t accelConsumed = 0u;
  uint32_t decelIntervals = 0u;
  uint32_t decelConsumed = 0u;
  uint32_t startArr = 0u;
  uint32_t targetArr = 0u;
  bool selected = false;
  bool active = false;
  bool completed = false;
  bool prepareFailed = false;
  bool runtimeFailed = false;
  bool aborted = false;
};

void reset(State& state);
bool prepare(State& state,
             uint32_t totalToggles,
             uint32_t accelToggles,
             uint32_t decelToggles,
             uint32_t startArr,
             uint32_t targetArr,
             uint32_t minArr,
             uint32_t maxArr);
bool nextSample(State& state,
                uint32_t completedToggles,
                uint32_t remainingToggles,
                Sample& sample);
bool finish(State& state);
void abort(State& state);
Snapshot snapshot(const State& state);
uint32_t expectedDecelSamples(uint32_t totalToggles,
                              uint32_t accelToggles,
                              uint32_t decelToggles);

}  // namespace DirectStepperProfile

#endif /* INC_DIRECTSTEPPERPROFILE_H_ */
