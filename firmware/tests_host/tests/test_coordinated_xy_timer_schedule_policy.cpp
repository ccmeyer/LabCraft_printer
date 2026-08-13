#include "CppUTest/TestHarness.h"
#include "CoordinatedXyTimerSchedulePolicy.h"

TEST_GROUP(CoordinatedXyTimerSchedulePolicy) {};

TEST(CoordinatedXyTimerSchedulePolicy, GuardThresholdIsInclusive) {
  auto decision = CoordinatedXyTimerSchedulePolicy::decide(
      true, false, true, 1125u, 2249u, false);
  CHECK_TRUE(decision.applicable);
  CHECK_TRUE(decision.sampleValid);
  CHECK_TRUE(decision.rearm);
  UNSIGNED_LONGS_EQUAL(1125u, decision.remainingTicks);

  decision = CoordinatedXyTimerSchedulePolicy::decide(
      true, false, true, 1124u, 2249u, false);
  CHECK_FALSE(decision.rearm);
  UNSIGNED_LONGS_EQUAL(1126u, decision.remainingTicks);
}

TEST(CoordinatedXyTimerSchedulePolicy, PendingAndCounterOverrunRearm) {
  CHECK_TRUE(CoordinatedXyTimerSchedulePolicy::decide(
      true, false, true, 10u, 2249u, true).rearm);
  CHECK_TRUE(CoordinatedXyTimerSchedulePolicy::decide(
      true, false, true, 2250u, 2249u, false).rearm);
}

TEST(CoordinatedXyTimerSchedulePolicy, InvalidSampleFailsClosed) {
  const auto missing = CoordinatedXyTimerSchedulePolicy::decide(
      true, false, false, 0u, 0u, false);
  CHECK_TRUE(missing.applicable);
  CHECK_FALSE(missing.sampleValid);
  CHECK_FALSE(missing.rearm);
}

TEST(CoordinatedXyTimerSchedulePolicy, TerminalAndNoEdgeCallbacksNeedNoSample) {
  CHECK_FALSE(CoordinatedXyTimerSchedulePolicy::decide(
      false, false, false, 0u, 0u, false).applicable);
  CHECK_FALSE(CoordinatedXyTimerSchedulePolicy::decide(
      true, true, false, 0u, 0u, false).applicable);
}

TEST(CoordinatedXyTimerSchedulePolicy, CounterPastArrIsAnImmediateRearm) {
  const auto decision = CoordinatedXyTimerSchedulePolicy::decide(
      true, false, true, 0xFFFFFFFEu, 1u, false);
  CHECK_TRUE(decision.sampleValid);
  CHECK_TRUE(decision.rearm);
  UNSIGNED_LONGS_EQUAL(0u, decision.remainingTicks);
}
