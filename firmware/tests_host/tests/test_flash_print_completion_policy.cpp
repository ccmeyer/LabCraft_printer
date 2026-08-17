#include "CppUTest/TestHarness.h"
#include "FlashPrintCompletionPolicy.h"

TEST_GROUP(FlashPrintCompletionPolicyTests)
{
};

TEST(FlashPrintCompletionPolicyTests, OneDropletAtTwentyHertzIncludesCooldownBudget)
{
    UNSIGNED_LONGS_EQUAL(
        4050u,
        FlashPrintCompletionPolicy::timeoutMs(1u, 20u, 3000u));
}

TEST(FlashPrintCompletionPolicyTests, ZeroRateFallsBackToOneHertz)
{
    UNSIGNED_LONGS_EQUAL(
        5000u,
        FlashPrintCompletionPolicy::timeoutMs(1u, 0u, 3000u));
}

TEST(FlashPrintCompletionPolicyTests, BaseTimeoutRetainsMinimumAndMaximumBounds)
{
    UNSIGNED_LONGS_EQUAL(
        1000u,
        FlashPrintCompletionPolicy::timeoutMs(0u, 20u, 0u));
    UNSIGNED_LONGS_EQUAL(
        30000u,
        FlashPrintCompletionPolicy::timeoutMs(65535u, 1u, 0u));
}

TEST(FlashPrintCompletionPolicyTests, StartupBudgetIsAddedAfterBaseCalculation)
{
    UNSIGNED_LONGS_EQUAL(
        2734u,
        FlashPrintCompletionPolicy::timeoutMs(10u, 20u, 1234u));
}

TEST(FlashPrintCompletionPolicyTests, StartupBudgetAdditionSaturates)
{
    UNSIGNED_LONGS_EQUAL(
        0xFFFFFFFFu,
        FlashPrintCompletionPolicy::timeoutMs(0u, 20u, 0xFFFFFFFFu));
}
