#include "CppUTest/TestHarness.h"
#include "HomeInterruptionPolicy.h"

using namespace HomeInterruptionPolicy;

TEST_GROUP(HomeInterruptionPolicyTests) {};

TEST(HomeInterruptionPolicyTests, CanceledAttemptCanRestartWithNewGeneration) {
  Lifecycle lifecycle{};
  const uint32_t first = begin(lifecycle);
  requestCancel(lifecycle);
  noteOutcome(lifecycle, Outcome::Canceled, first);

  CHECK_TRUE(canRestart(lifecycle));
  const uint32_t second = begin(lifecycle, true);
  CHECK_TRUE(second != first);
  LONGS_EQUAL((int)State::Restarting, (int)lifecycle.state);
}

TEST(HomeInterruptionPolicyTests, StaleOutcomeCannotCompleteRestart) {
  Lifecycle lifecycle{};
  const uint32_t first = begin(lifecycle);
  requestCancel(lifecycle);
  noteOutcome(lifecycle, Outcome::Canceled, first);
  const uint32_t second = begin(lifecycle, true);

  noteOutcome(lifecycle, Outcome::Succeeded, first);
  LONGS_EQUAL((int)State::Restarting, (int)lifecycle.state);
  noteOutcome(lifecycle, Outcome::Succeeded, second);
  LONGS_EQUAL((int)State::Idle, (int)lifecycle.state);
}

TEST(HomeInterruptionPolicyTests, FailureLatchesAndCannotRestart) {
  Lifecycle lifecycle{};
  const uint32_t generation = begin(lifecycle);
  noteOutcome(lifecycle, Outcome::Failed, generation);

  CHECK_TRUE(isFailureLatched(lifecycle));
  CHECK_FALSE(canRestart(lifecycle));
  clear(lifecycle);
  LONGS_EQUAL((int)State::Idle, (int)lifecycle.state);
}

TEST(HomeInterruptionPolicyTests, CompositeRequiresEveryParticipantToSucceed) {
  const Outcome partial[] = {Outcome::Succeeded, Outcome::Canceled};
  const Outcome success[] = {Outcome::Succeeded, Outcome::Succeeded};

  CHECK_FALSE(allSucceeded(partial, 2u));
  CHECK_TRUE(anyCanceled(partial, 2u));
  CHECK_TRUE(allSucceeded(success, 2u));
  CHECK_FALSE(anyFailed(success, 2u));
}

TEST(HomeInterruptionPolicyTests, CompositeFailureIsDetected) {
  const Outcome outcomes[] = {Outcome::Succeeded, Outcome::Failed};
  CHECK_TRUE(anyFailed(outcomes, 2u));
  CHECK_FALSE(allSucceeded(outcomes, 2u));
}
