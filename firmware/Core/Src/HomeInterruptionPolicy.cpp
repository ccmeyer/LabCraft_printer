#include "HomeInterruptionPolicy.h"

namespace HomeInterruptionPolicy {

uint32_t begin(Lifecycle& lifecycle, bool restarting) {
  ++lifecycle.generation;
  if (lifecycle.generation == 0u) {
    lifecycle.generation = 1u;
  }
  lifecycle.state = restarting ? State::Restarting : State::Running;
  return lifecycle.generation;
}

void requestCancel(Lifecycle& lifecycle) {
  if (lifecycle.state == State::Running || lifecycle.state == State::Restarting) {
    lifecycle.state = State::CancelRequested;
  }
}

void noteOutcome(Lifecycle& lifecycle, Outcome outcome, uint32_t generation) {
  if (generation != lifecycle.generation) {
    return;
  }
  switch (outcome) {
    case Outcome::Succeeded:
      lifecycle.state = State::Idle;
      break;
    case Outcome::Canceled:
      lifecycle.state = State::AwaitingResume;
      break;
    case Outcome::Failed:
      lifecycle.state = State::FailureLatched;
      break;
    case Outcome::NotStarted:
    case Outcome::Running:
      break;
  }
}

bool canRestart(const Lifecycle& lifecycle) {
  return lifecycle.state == State::AwaitingResume;
}

bool isFailureLatched(const Lifecycle& lifecycle) {
  return lifecycle.state == State::FailureLatched;
}

void clear(Lifecycle& lifecycle) {
  lifecycle.state = State::Idle;
}

bool allSucceeded(const Outcome* outcomes, std::size_t count) {
  if (outcomes == nullptr || count == 0u) {
    return false;
  }
  for (std::size_t i = 0; i < count; ++i) {
    if (outcomes[i] != Outcome::Succeeded) {
      return false;
    }
  }
  return true;
}

bool anyFailed(const Outcome* outcomes, std::size_t count) {
  if (outcomes == nullptr) {
    return false;
  }
  for (std::size_t i = 0; i < count; ++i) {
    if (outcomes[i] == Outcome::Failed) {
      return true;
    }
  }
  return false;
}

bool anyCanceled(const Outcome* outcomes, std::size_t count) {
  if (outcomes == nullptr) {
    return false;
  }
  for (std::size_t i = 0; i < count; ++i) {
    if (outcomes[i] == Outcome::Canceled) {
      return true;
    }
  }
  return false;
}

}  // namespace HomeInterruptionPolicy
