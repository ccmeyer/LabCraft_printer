#include "CppUTest/TestHarness.h"
#include "CoordinatedXyTimerSchedulePolicy.h"

TEST_GROUP(CoordinatedXyTimerSchedulePolicy) {
};

TEST(CoordinatedXyTimerSchedulePolicy, ModesHaveStableDiagnosticValues) {
  using CoordinatedXyTimerSchedulePolicy::Mode;
  UNSIGNED_LONGS_EQUAL(0u, static_cast<uint8_t>(Mode::FreeRunning));
  UNSIGNED_LONGS_EQUAL(1u, static_cast<uint8_t>(Mode::RearmFromActualEdge));
  CHECK_TRUE(CoordinatedXyTimerSchedulePolicy::isValid(Mode::FreeRunning));
  CHECK_TRUE(CoordinatedXyTimerSchedulePolicy::isValid(
      Mode::RearmFromActualEdge));
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
