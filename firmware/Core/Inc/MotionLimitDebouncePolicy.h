#ifndef INC_MOTIONLIMITDEBOUNCEPOLICY_H_
#define INC_MOTIONLIMITDEBOUNCEPOLICY_H_

#include <cstdint>
#include <limits>

namespace MotionLimitDebouncePolicy {

constexpr uint32_t kDebounceMs = 15u;
constexpr uint32_t kHardwareDebounceUs = kDebounceMs * 1000u;

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
  TransitionCountSaturated = 1u << 4,
  RestartCountSaturated = 1u << 5,
  InfrastructureFailureCountSaturated = 1u << 6,
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
  uint32_t transitionCount = 0u;
  uint32_t restartCount = 0u;
  uint32_t infrastructureFailureCount = 0u;
  uint32_t saturationFlags = 0u;
  bool pending = false;
  bool confirmed = false;
};

// Edge-aware policy used by the X/Y TIM5 service. HardwareState deliberately
// contains no STM32 types so the deadline, wrap, bounce, and stale-window
// behavior can be qualified by the host test lane.
struct HardwareState {
  volatile Phase phase = Phase::Idle;
  volatile uint32_t candidateCount = 0u;
  volatile uint32_t rejectionCount = 0u;
  volatile uint32_t confirmationCount = 0u;
  volatile uint32_t transitionCount = 0u;
  volatile uint32_t restartCount = 0u;
  volatile uint32_t infrastructureFailureCount = 0u;
  volatile uint32_t saturationFlags = 0u;
  volatile uint32_t startCount = 0u;
  volatile uint32_t deadlineCount = 0u;
  volatile bool transitionSeen = false;
};

enum class HardwareDecision : uint8_t {
  None = 0u,
  Started = 1u,
  Pending = 2u,
  Rejected = 3u,
  Restarted = 4u,
  Confirmed = 5u,
  AlreadyConfirmed = 6u,
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

inline bool deadlineReached(uint32_t nowCount, uint32_t deadlineCount) {
  return static_cast<int32_t>(nowCount - deadlineCount) >= 0;
}

inline bool hardwareGenerationMatches(uint32_t candidateGeneration,
                                      uint32_t activeGeneration) {
  return candidateGeneration != 0u &&
      candidateGeneration == activeGeneration;
}

inline HardwareDecision forceHardwareConfirmation(HardwareState& state) {
  if (state.phase == Phase::Confirmed) {
    return HardwareDecision::AlreadyConfirmed;
  }
  incrementSaturating(state.infrastructureFailureCount,
                      state.saturationFlags,
                      InfrastructureFailureCountSaturated);
  incrementSaturating(state.confirmationCount,
                      state.saturationFlags,
                      ConfirmationCountSaturated);
  state.phase = Phase::Confirmed;
  state.transitionSeen = false;
  return HardwareDecision::Confirmed;
}

inline HardwareDecision beginHardwareCandidate(HardwareState& state,
                                               uint32_t nowCount,
                                               uint32_t intervalCounts,
                                               bool infrastructureValid) {
  if (state.phase == Phase::Confirmed) {
    return HardwareDecision::AlreadyConfirmed;
  }
  if (state.phase == Phase::Pending) {
    return HardwareDecision::Pending;
  }
  incrementSaturating(state.candidateCount,
                      state.saturationFlags,
                      CandidateCountSaturated);
  state.startCount = nowCount;
  state.deadlineCount = nowCount + intervalCounts;
  state.transitionSeen = false;
  state.phase = Phase::Pending;
  if (!infrastructureValid || intervalCounts == 0u) {
    return forceHardwareConfirmation(state);
  }
  return HardwareDecision::Started;
}

inline void noteHardwareTransition(HardwareState& state) {
  if (state.phase != Phase::Pending || state.transitionSeen) {
    return;
  }
  state.transitionSeen = true;
  incrementSaturating(state.transitionCount,
                      state.saturationFlags,
                      TransitionCountSaturated);
}

inline HardwareDecision evaluateHardwareExpiry(HardwareState& state,
                                                bool asserted,
                                                bool stickyTransition,
                                                uint32_t nowCount,
                                                uint32_t intervalCounts,
                                                bool infrastructureValid) {
  if (state.phase == Phase::Confirmed) {
    return HardwareDecision::AlreadyConfirmed;
  }
  if (state.phase != Phase::Pending) {
    return HardwareDecision::None;
  }
  if (!infrastructureValid || intervalCounts == 0u) {
    return forceHardwareConfirmation(state);
  }
  if (!deadlineReached(nowCount, state.deadlineCount)) {
    return HardwareDecision::Pending;
  }

  if (stickyTransition) {
    noteHardwareTransition(state);
  }
  if (!asserted) {
    incrementSaturating(state.rejectionCount,
                        state.saturationFlags,
                        RejectionCountSaturated);
    state.phase = Phase::Idle;
    state.startCount = 0u;
    state.deadlineCount = 0u;
    state.transitionSeen = false;
    return HardwareDecision::Rejected;
  }
  if (state.transitionSeen) {
    incrementSaturating(state.rejectionCount,
                        state.saturationFlags,
                        RejectionCountSaturated);
    incrementSaturating(state.restartCount,
                        state.saturationFlags,
                        RestartCountSaturated);
    incrementSaturating(state.candidateCount,
                        state.saturationFlags,
                        CandidateCountSaturated);
    state.startCount = nowCount;
    state.deadlineCount = nowCount + intervalCounts;
    state.transitionSeen = false;
    return HardwareDecision::Restarted;
  }

  incrementSaturating(state.confirmationCount,
                      state.saturationFlags,
                      ConfirmationCountSaturated);
  state.phase = Phase::Confirmed;
  return HardwareDecision::Confirmed;
}

inline void cancelHardware(HardwareState& state, bool rejectPending = false) {
  if (rejectPending && state.phase == Phase::Pending) {
    incrementSaturating(state.rejectionCount,
                        state.saturationFlags,
                        RejectionCountSaturated);
  }
  state.phase = Phase::Idle;
  state.startCount = 0u;
  state.deadlineCount = 0u;
  state.transitionSeen = false;
}

inline Snapshot makeSnapshot(const HardwareState& state) {
  Snapshot snapshot{};
  snapshot.phase = state.phase;
  snapshot.candidateCount = state.candidateCount;
  snapshot.rejectionCount = state.rejectionCount;
  snapshot.confirmationCount = state.confirmationCount;
  snapshot.transitionCount = state.transitionCount;
  snapshot.restartCount = state.restartCount;
  snapshot.infrastructureFailureCount = state.infrastructureFailureCount;
  snapshot.saturationFlags = state.saturationFlags;
  snapshot.pending = state.phase == Phase::Pending;
  snapshot.confirmed = state.phase == Phase::Confirmed;
  return snapshot;
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
