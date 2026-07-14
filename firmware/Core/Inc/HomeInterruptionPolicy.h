#ifndef HOME_INTERRUPTION_POLICY_H
#define HOME_INTERRUPTION_POLICY_H

#include <cstddef>
#include <cstdint>

namespace HomeInterruptionPolicy {

enum class Outcome : uint8_t {
  NotStarted = 0,
  Running,
  Succeeded,
  Failed,
  Canceled,
};

enum class Origin : uint8_t {
  None = 0,
  Commanded,
  InnerLimit,
  Safety,
  StepLimit,
};

enum class State : uint8_t {
  Idle = 0,
  Running,
  CancelRequested,
  AwaitingResume,
  Restarting,
  FailureLatched,
};

struct CancellationToken {
  volatile bool requested = false;
  uint32_t generation = 0u;
};

struct Lifecycle {
  State state = State::Idle;
  uint32_t generation = 0u;
};

uint32_t begin(Lifecycle& lifecycle, bool restarting = false);
void requestCancel(Lifecycle& lifecycle);
void noteOutcome(Lifecycle& lifecycle, Outcome outcome, uint32_t generation);
bool canRestart(const Lifecycle& lifecycle);
bool isFailureLatched(const Lifecycle& lifecycle);
void clear(Lifecycle& lifecycle);

bool allSucceeded(const Outcome* outcomes, std::size_t count);
bool anyFailed(const Outcome* outcomes, std::size_t count);
bool anyCanceled(const Outcome* outcomes, std::size_t count);

inline bool cancellationRequested(const CancellationToken* token) {
  return token != nullptr && token->requested;
}

}  // namespace HomeInterruptionPolicy

#endif  // HOME_INTERRUPTION_POLICY_H
