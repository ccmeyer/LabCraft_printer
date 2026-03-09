#include "CppUTest/TestHarness.h"
#include "ExtiDebounce.h"

TEST_GROUP(ExtiDebounceHelpers)
{
};

TEST(ExtiDebounceHelpers, LineMaskUsesExpectedBitForValidLines)
{
    UNSIGNED_LONGS_EQUAL(1u, ExtiDebounce::lineMask(0u));
    UNSIGNED_LONGS_EQUAL(1u << 10, ExtiDebounce::lineMask(10u));
    UNSIGNED_LONGS_EQUAL(1u << 15, ExtiDebounce::lineMask(15u));
}

TEST(ExtiDebounceHelpers, LineMaskGuardsInvalidLineNumbers)
{
    UNSIGNED_LONGS_EQUAL(0u, ExtiDebounce::lineMask(16u));
    UNSIGNED_LONGS_EQUAL(0u, ExtiDebounce::lineMask(31u));
}

TEST(ExtiDebounceHelpers, ArmDecisionIgnoresEventsBeforeSchedulerStarts)
{
    LONGS_EQUAL(static_cast<long>(ExtiDebounce::ArmAction::Ignore),
                static_cast<long>(ExtiDebounce::decideArmAction(false, true, true)));
}

TEST(ExtiDebounceHelpers, ArmDecisionFallsBackWhenTimerIsUnavailableOrArmFails)
{
    LONGS_EQUAL(static_cast<long>(ExtiDebounce::ArmAction::ImmediateFallback),
                static_cast<long>(ExtiDebounce::decideArmAction(true, false, false)));
    LONGS_EQUAL(static_cast<long>(ExtiDebounce::ArmAction::ImmediateFallback),
                static_cast<long>(ExtiDebounce::decideArmAction(true, true, false)));
}

TEST(ExtiDebounceHelpers, ArmDecisionReportsArmedWhenTimerPostSucceeds)
{
    LONGS_EQUAL(static_cast<long>(ExtiDebounce::ArmAction::Armed),
                static_cast<long>(ExtiDebounce::decideArmAction(true, true, true)));
}

TEST(ExtiDebounceHelpers, AssertedLevelMatchesConfiguredPolarity)
{
    CHECK_TRUE(ExtiDebounce::isAsserted(true, true));
    CHECK_TRUE(ExtiDebounce::isAsserted(false, false));
    CHECK_FALSE(ExtiDebounce::isAsserted(false, true));
    CHECK_FALSE(ExtiDebounce::isAsserted(true, false));
}
