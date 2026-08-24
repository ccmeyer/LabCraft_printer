#include "CppUTest/TestHarness.h"
#include "MotionResumePolicy.h"

TEST_GROUP(MotionResumePolicy) {};

TEST(MotionResumePolicy, StartRateIsCappedAndHonorsSlowerCommands) {
  UNSIGNED_LONGS_EQUAL(
      3000u, MotionResumePolicy::selectStartRateHz(40000u));
  UNSIGNED_LONGS_EQUAL(
      3000u, MotionResumePolicy::selectStartRateHz(30000u));
  UNSIGNED_LONGS_EQUAL(
      1200u, MotionResumePolicy::selectStartRateHz(1200u));
  UNSIGNED_LONGS_EQUAL(
      3000u, MotionResumePolicy::selectStartRateHz(0u));
}

TEST(MotionResumePolicy, DriverRearmUsesBoundedDisableAndPoweredSettle) {
  UNSIGNED_LONGS_EQUAL(2u, MotionResumePolicy::kDriverDisablePulseMs);
  UNSIGNED_LONGS_EQUAL(130u, MotionResumePolicy::kDriverPoweredSettleMs);
}

TEST(MotionResumePolicy, RemainingMoveUsesWideArithmetic) {
  const auto positive = MotionResumePolicy::remainingMove(-100, 500);
  CHECK_TRUE(positive.valid);
  CHECK_TRUE(positive.positive);
  UNSIGNED_LONGS_EQUAL(600u, positive.magnitude);

  const auto negative = MotionResumePolicy::remainingMove(500, -100);
  CHECK_TRUE(negative.valid);
  CHECK_FALSE(negative.positive);
  UNSIGNED_LONGS_EQUAL(600u, negative.magnitude);

  const auto immediate = MotionResumePolicy::remainingMove(25, 25);
  CHECK_TRUE(immediate.valid);
  CHECK_TRUE(immediate.immediate);
}
