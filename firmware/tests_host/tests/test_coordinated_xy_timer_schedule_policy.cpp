#include "CppUTest/TestHarness.h"
#include "CoordinatedXyTimerSchedulePolicy.h"

TEST_GROUP(CoordinatedXyTimerSchedulePolicy) {
};

TEST(CoordinatedXyTimerSchedulePolicy, ModesHaveStableDiagnosticValues) {
  using CoordinatedXyTimerSchedulePolicy::Mode;
  UNSIGNED_LONGS_EQUAL(0u, static_cast<uint8_t>(Mode::FreeRunning));
  UNSIGNED_LONGS_EQUAL(1u, static_cast<uint8_t>(Mode::RearmFromActualEdge));
  UNSIGNED_LONGS_EQUAL(2u, static_cast<uint8_t>(Mode::ConditionalLateRearm));
  CHECK_TRUE(CoordinatedXyTimerSchedulePolicy::isValid(Mode::FreeRunning));
  CHECK_TRUE(CoordinatedXyTimerSchedulePolicy::isValid(
      Mode::RearmFromActualEdge));
  CHECK_TRUE(CoordinatedXyTimerSchedulePolicy::isValid(
      Mode::ConditionalLateRearm));
}

TEST(CoordinatedXyTimerSchedulePolicy, ConditionalThresholdIsInclusive) {
  using CoordinatedXyTimerSchedulePolicy::Mode;
  auto decision = CoordinatedXyTimerSchedulePolicy::decide(
      Mode::ConditionalLateRearm, true, false, true, 1125u, 2249u, false);
  CHECK_TRUE(decision.applicable);
  CHECK_TRUE(decision.sampleValid);
  CHECK_TRUE(decision.rearm);
  UNSIGNED_LONGS_EQUAL(1125u, decision.remainingTicks);

  decision = CoordinatedXyTimerSchedulePolicy::decide(
      Mode::ConditionalLateRearm, true, false, true, 1124u, 2249u, false);
  CHECK_FALSE(decision.rearm);
  UNSIGNED_LONGS_EQUAL(1126u, decision.remainingTicks);
}

TEST(CoordinatedXyTimerSchedulePolicy, PendingAndOverrunRearmButMissingFailsClosed) {
  using CoordinatedXyTimerSchedulePolicy::Mode;
  CHECK_TRUE(CoordinatedXyTimerSchedulePolicy::decide(
      Mode::ConditionalLateRearm, true, false, true, 10u, 2249u, true).rearm);
  CHECK_TRUE(CoordinatedXyTimerSchedulePolicy::decide(
      Mode::ConditionalLateRearm, true, false, true, 2250u, 2249u, false).rearm);
  const auto missing = CoordinatedXyTimerSchedulePolicy::decide(
      Mode::ConditionalLateRearm, true, false, false, 0u, 0u, false);
  CHECK_TRUE(missing.applicable);
  CHECK_FALSE(missing.sampleValid);
  CHECK_FALSE(missing.rearm);
}

TEST(CoordinatedXyTimerSchedulePolicy, TerminalAndNoEdgeCallbacksNeedNoSample) {
  using CoordinatedXyTimerSchedulePolicy::Mode;
  CHECK_FALSE(CoordinatedXyTimerSchedulePolicy::decide(
      Mode::ConditionalLateRearm, false, false, false, 0u, 0u, false).applicable);
  CHECK_FALSE(CoordinatedXyTimerSchedulePolicy::decide(
      Mode::ConditionalLateRearm, true, true, false, 0u, 0u, false).applicable);
}

TEST(CoordinatedXyTimerSchedulePolicy, InjectionUsesWrapSafeBound) {
  using CoordinatedXyTimerSchedulePolicy::Mode;
  CHECK_TRUE(CoordinatedXyTimerSchedulePolicy::shouldAttemptInjection(
      Mode::ConditionalLateRearm, true, true, true, true, true));
  CHECK_FALSE(CoordinatedXyTimerSchedulePolicy::shouldAttemptInjection(
      Mode::ConditionalLateRearm, true, true, true, true, false));
  CHECK_FALSE(CoordinatedXyTimerSchedulePolicy::injectionWaitExpired(
      0xFFFFFF00u, 0x00001000u));
  CHECK_TRUE(CoordinatedXyTimerSchedulePolicy::injectionWaitExpired(
      0xFFFFFF00u, 0x00001100u));
}

TEST(CoordinatedXyTimerSchedulePolicy, RearmsOnlyAfterNonterminalPhysicalEdge) {
  using CoordinatedXyTimerSchedulePolicy::Mode;
  CHECK_FALSE(CoordinatedXyTimerSchedulePolicy::shouldRearm(
      Mode::FreeRunning, true, false));
  CHECK_FALSE(CoordinatedXyTimerSchedulePolicy::shouldRearm(
      Mode::RearmFromActualEdge, false, false));
  CHECK_FALSE(CoordinatedXyTimerSchedulePolicy::shouldRearm(
      Mode::RearmFromActualEdge, true, true));
  CHECK_TRUE(CoordinatedXyTimerSchedulePolicy::shouldRearm(
      Mode::RearmFromActualEdge, true, false));
}
