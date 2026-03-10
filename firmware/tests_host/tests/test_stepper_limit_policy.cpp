#include "CppUTest/TestHarness.h"
#include "StepperLimitPolicy.h"

TEST_GROUP(StepperLimitPolicyHelpers)
{
};

TEST(StepperLimitPolicyHelpers, ResolvePullModeUsesExplicitSettingWhenProvided)
{
    LONGS_EQUAL(static_cast<long>(StepperLimitPolicy::PullMode::None),
                static_cast<long>(StepperLimitPolicy::resolvePullMode(
                    StepperLimitPolicy::PullMode::None, true)));
    LONGS_EQUAL(static_cast<long>(StepperLimitPolicy::PullMode::Up),
                static_cast<long>(StepperLimitPolicy::resolvePullMode(
                    StepperLimitPolicy::PullMode::Up, false)));
}

TEST(StepperLimitPolicyHelpers, ResolvePullModeFallsBackToPolarityDefaultsForAuto)
{
    LONGS_EQUAL(static_cast<long>(StepperLimitPolicy::PullMode::Down),
                static_cast<long>(StepperLimitPolicy::resolvePullMode(
                    StepperLimitPolicy::PullMode::Auto, true)));
    LONGS_EQUAL(static_cast<long>(StepperLimitPolicy::PullMode::Up),
                static_cast<long>(StepperLimitPolicy::resolvePullMode(
                    StepperLimitPolicy::PullMode::Auto, false)));
}

TEST(StepperLimitPolicyHelpers, HomeLimitDetectedAcceptsLatchedOrCurrentAssertion)
{
    CHECK_TRUE(StepperLimitPolicy::homeLimitDetected(true, false));
    CHECK_TRUE(StepperLimitPolicy::homeLimitDetected(false, true));
    CHECK_FALSE(StepperLimitPolicy::homeLimitDetected(false, false));
}

TEST(StepperLimitPolicyHelpers, LatchedLimitActionHardStopsOnlyForConfiguredHomeAxis)
{
    LONGS_EQUAL(static_cast<long>(StepperLimitPolicy::LatchedLimitAction::ConfirmLater),
                static_cast<long>(StepperLimitPolicy::decideLatchedLimitAction(false, true, true)));
    LONGS_EQUAL(static_cast<long>(StepperLimitPolicy::LatchedLimitAction::ConfirmLater),
                static_cast<long>(StepperLimitPolicy::decideLatchedLimitAction(true, false, true)));
    LONGS_EQUAL(static_cast<long>(StepperLimitPolicy::LatchedLimitAction::ConfirmLater),
                static_cast<long>(StepperLimitPolicy::decideLatchedLimitAction(true, true, false)));
    LONGS_EQUAL(static_cast<long>(StepperLimitPolicy::LatchedLimitAction::HardStopNow),
                static_cast<long>(StepperLimitPolicy::decideLatchedLimitAction(true, true, true)));
}
