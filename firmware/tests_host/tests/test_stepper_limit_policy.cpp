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

TEST(StepperLimitPolicyHelpers, ReleaseSearchGuardScalesFromBackoffSteps)
{
    LONGS_EQUAL(1024L, static_cast<long>(StepperLimitPolicy::releaseSearchGuardSteps(0u)));
    LONGS_EQUAL(1024L, static_cast<long>(StepperLimitPolicy::releaseSearchGuardSteps(32u)));
    LONGS_EQUAL(16000L, static_cast<long>(StepperLimitPolicy::releaseSearchGuardSteps(1000u)));
}

TEST(StepperLimitPolicyHelpers, FinalHomeBackoffPreservesConfiguredPhysicalScale)
{
    LONGS_EQUAL(100L, static_cast<long>(StepperLimitPolicy::finalHomeBackoffSteps(400u)));
    LONGS_EQUAL(50L, static_cast<long>(StepperLimitPolicy::finalHomeBackoffSteps(200u)));
    LONGS_EQUAL(1L, static_cast<long>(StepperLimitPolicy::finalHomeBackoffSteps(0u)));
    LONGS_EQUAL(1L, static_cast<long>(StepperLimitPolicy::finalHomeBackoffSteps(3u)));
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

TEST(StepperLimitPolicyHelpers, DirectMoveMayEscapeAnAlreadyAssertedLimit)
{
    LONGS_EQUAL(
        static_cast<long>(StepperLimitPolicy::DirectStartDecision::EscapeAssertedLimit),
        static_cast<long>(StepperLimitPolicy::classifyDirectStart(
            true, true, false, false)));
}

TEST(StepperLimitPolicyHelpers, DirectMoveRejectsTowardAnAssertedLimit)
{
    LONGS_EQUAL(
        static_cast<long>(StepperLimitPolicy::DirectStartDecision::RejectAssertedTowardLimit),
        static_cast<long>(StepperLimitPolicy::classifyDirectStart(
            true, false, false, false)));
}

TEST(StepperLimitPolicyHelpers, DirectApproachRequiresConfirmedRelease)
{
    LONGS_EQUAL(
        static_cast<long>(StepperLimitPolicy::DirectStartDecision::RejectUntilReleased),
        static_cast<long>(StepperLimitPolicy::classifyDirectStart(
            false, false, false, false)));
    LONGS_EQUAL(
        static_cast<long>(StepperLimitPolicy::DirectStartDecision::Proceed),
        static_cast<long>(StepperLimitPolicy::classifyDirectStart(
            false, false, false, true)));
}
