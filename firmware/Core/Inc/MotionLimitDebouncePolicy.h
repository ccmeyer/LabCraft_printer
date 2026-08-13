#ifndef INC_MOTIONLIMITDEBOUNCEPOLICY_H_
#define INC_MOTIONLIMITDEBOUNCEPOLICY_H_

#include <cstdint>
#include <limits>

namespace MotionLimitDebouncePolicy {

constexpr uint32_t kDebounceMs = 15u;

enum class Phase : uint8_t {
  Idle = 0u,
  Pending = 1u,
  Confirmed = 2u,
};

enum class Decision : uint8_t {
  None = 0u,
  Started = 1u,
  Pending = 2u,
  Rejected = 3u,
  Confirmed = 4u,
  AlreadyConfirmed = 5u,
  Released = 6u,
};

enum SaturationFlag : uint32_t {
  CandidateCountSaturated = 1u << 0,
  RejectionCountSaturated = 1u << 1,
  ConfirmationCountSaturated = 1u << 2,
  TimebaseFailureCountSaturated = 1u << 3,
};

struct State {
  volatile Phase phase = Phase::Idle;
  volatile uint32_t startCycle = 0u;
  volatile uint32_t candidateCount = 0u;
  volatile uint32_t rejectionCount = 0u;
  volatile uint32_t confirmationCount = 0u;
  volatile uint32_t timebaseFailureCount = 0u;
  volatile uint32_t saturationFlags = 0u;
};

struct Snapshot {
  Phase phase = Phase::Idle;
  uint32_t candidateCount = 0u;
  uint32_t rejectionCount = 0u;
  uint32_t confirmationCount = 0u;
  uint32_t timebaseFailureCount = 0u;
  uint32_t saturationFlags = 0u;
  bool pending = false;
  bool confirmed = false;
};

inline void incrementSaturating(volatile uint32_t& value,
                                volatile uint32_t& saturationFlags,
                                uint32_t flag) {
  if (value == std::numeric_limits<uint32_t>::max()) {
    saturationFlags |= flag;
    return;
  }
  ++value;
}

inline void resetTransient(State& state, bool rejectPending = false) {
  if (rejectPending && state.phase == Phase::Pending) {
    incrementSaturating(state.rejectionCount,
                        state.saturationFlags,
                        RejectionCountSaturated);
  }
  state.phase = Phase::Idle;
  state.startCycle = 0u;
}

inline Decision observe(State& state,
                        bool asserted,
                        uint32_t nowCycle,
                        uint32_t requiredCycles,
                        bool timebaseValid) {
  if (!asserted) {
    if (state.phase == Phase::Pending) {
      incrementSaturating(state.rejectionCount,
                          state.saturationFlags,
                          RejectionCountSaturated);
      state.phase = Phase::Idle;
      state.startCycle = 0u;
      return Decision::Rejected;
    }
    if (state.phase == Phase::Confirmed) {
      state.phase = Phase::Idle;
      state.startCycle = 0u;
      return Decision::Released;
    }
    return Decision::None;
  }

  if (state.phase == Phase::Confirmed) {
    return Decision::AlreadyConfirmed;
  }

  if (state.phase == Phase::Idle) {
    incrementSaturating(state.candidateCount,
                        state.saturationFlags,
                        CandidateCountSaturated);
    state.startCycle = nowCycle;
    state.phase = Phase::Pending;
    if (!timebaseValid || requiredCycles == 0u) {
      incrementSaturating(state.timebaseFailureCount,
                          state.saturationFlags,
                          TimebaseFailureCountSaturated);
      incrementSaturating(state.confirmationCount,
                          state.saturationFlags,
                          ConfirmationCountSaturated);
      state.phase = Phase::Confirmed;
      return Decision::Confirmed;
    }
    return Decision::Started;
  }

  if (!timebaseValid || requiredCycles == 0u) {
    incrementSaturating(state.timebaseFailureCount,
                        state.saturationFlags,
                        TimebaseFailureCountSaturated);
    incrementSaturating(state.confirmationCount,
                        state.saturationFlags,
                        ConfirmationCountSaturated);
    state.phase = Phase::Confirmed;
    return Decision::Confirmed;
  }

  if (static_cast<uint32_t>(nowCycle - state.startCycle) >= requiredCycles) {
    incrementSaturating(state.confirmationCount,
                        state.saturationFlags,
                        ConfirmationCountSaturated);
    state.phase = Phase::Confirmed;
    return Decision::Confirmed;
  }
  return Decision::Pending;
}

inline Snapshot makeSnapshot(const State& state) {
  Snapshot snapshot{};
  snapshot.phase = state.phase;
  snapshot.candidateCount = state.candidateCount;
  snapshot.rejectionCount = state.rejectionCount;
  snapshot.confirmationCount = state.confirmationCount;
  snapshot.timebaseFailureCount = state.timebaseFailureCount;
  snapshot.saturationFlags = state.saturationFlags;
  snapshot.pending = state.phase == Phase::Pending;
  snapshot.confirmed = state.phase == Phase::Confirmed;
  return snapshot;
}

inline uint32_t counterDelta(uint32_t before, uint32_t after) {
  return after >= before
      ? after - before
      : std::numeric_limits<uint32_t>::max();
}

}  // namespace MotionLimitDebouncePolicy

#endif  // INC_MOTIONLIMITDEBOUNCEPOLICY_H_
