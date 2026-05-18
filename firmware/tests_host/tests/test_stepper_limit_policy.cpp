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

TEST(StepperLimitPolicyHelpers, StableLimitAssertedUsesConfiguredMajority)
{
    CHECK_FALSE(StepperLimitPolicy::stableLimitAsserted(0u, 5u, 3u));
    CHECK_FALSE(StepperLimitPolicy::stableLimitAsserted(1u, 5u, 3u));
    CHECK_FALSE(StepperLimitPolicy::stableLimitAsserted(2u, 5u, 3u));
    CHECK_TRUE(StepperLimitPolicy::stableLimitAsserted(3u, 5u, 3u));
    CHECK_TRUE(StepperLimitPolicy::stableLimitAsserted(4u, 5u, 3u));
    CHECK_TRUE(StepperLimitPolicy::stableLimitAsserted(5u, 5u, 3u));
}

TEST(StepperLimitPolicyHelpers, StableLimitAssertedRejectsInvalidSampleConfig)
{
    CHECK_FALSE(StepperLimitPolicy::stableLimitAsserted(5u, 0u, 3u));
    CHECK_FALSE(StepperLimitPolicy::stableLimitAsserted(5u, 5u, 0u));
}

TEST(StepperLimitPolicyHelpers, HomeLevelPollingOnlyAppliesTowardLimit)
{
    CHECK_TRUE(StepperLimitPolicy::shouldPollHomeLimitLevel(true, true));
    CHECK_TRUE(StepperLimitPolicy::shouldPollHomeLimitLevel(false, false));
    CHECK_FALSE(StepperLimitPolicy::shouldPollHomeLimitLevel(true, false));
    CHECK_FALSE(StepperLimitPolicy::shouldPollHomeLimitLevel(false, true));
}

TEST(StepperLimitPolicyHelpers, HomeLevelPollRequiresConfiguredConsecutiveSamples)
{
    CHECK_FALSE(StepperLimitPolicy::homeLevelPollConfirmed(0u, 2u));
    CHECK_FALSE(StepperLimitPolicy::homeLevelPollConfirmed(1u, 2u));
    CHECK_TRUE(StepperLimitPolicy::homeLevelPollConfirmed(2u, 2u));
    CHECK_TRUE(StepperLimitPolicy::homeLevelPollConfirmed(3u, 2u));
    CHECK_FALSE(StepperLimitPolicy::homeLevelPollConfirmed(3u, 0u));
}

TEST(StepperLimitPolicyHelpers, ReleaseSearchGuardScalesFromBackoffSteps)
{
    LONGS_EQUAL(1024L, static_cast<long>(StepperLimitPolicy::releaseSearchGuardSteps(0u)));
    LONGS_EQUAL(1024L, static_cast<long>(StepperLimitPolicy::releaseSearchGuardSteps(32u)));
    LONGS_EQUAL(16000L, static_cast<long>(StepperLimitPolicy::releaseSearchGuardSteps(1000u)));
}

TEST(StepperLimitPolicyHelpers, MoveGenerationWrapsWithoutUsingZero)
{
    LONGS_EQUAL(1L, static_cast<long>(StepperLimitPolicy::nextMoveGeneration(0u)));
    LONGS_EQUAL(2L, static_cast<long>(StepperLimitPolicy::nextMoveGeneration(1u)));
    LONGS_EQUAL(1L, static_cast<long>(StepperLimitPolicy::nextMoveGeneration(0xFFFFFFFFu)));
}

TEST(StepperLimitPolicyHelpers, FineHomeLimitDetectedRequiresFreshHitAfterRelease)
{
    CHECK_TRUE(StepperLimitPolicy::fineHomeLimitDetected(true, true, false));
    CHECK_FALSE(StepperLimitPolicy::fineHomeLimitDetected(true, false, true));
    CHECK_TRUE(StepperLimitPolicy::fineHomeLimitDetected(false, false, true));
}

TEST(StepperLimitPolicyHelpers, StaleDebounceCallbackDoesNotApplyToNewMove)
{
    CHECK_TRUE(StepperLimitPolicy::shouldApplyDebounceCallback(7u, 7u));
    CHECK_FALSE(StepperLimitPolicy::shouldApplyDebounceCallback(0u, 7u));
    CHECK_FALSE(StepperLimitPolicy::shouldApplyDebounceCallback(7u, 8u));
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
