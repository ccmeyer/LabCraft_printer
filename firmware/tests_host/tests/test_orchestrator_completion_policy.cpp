#include "CppUTest/TestHarness.h"
#include "OrchestratorCompletionPolicy.h"

TEST_GROUP(OrchestratorCompletionPolicyTests)
{
};

TEST(OrchestratorCompletionPolicyTests, InterruptedSingleBitWaitDoesNotRetireFrontiers) {
    uint32_t lastExecuted = 7u;
    uint32_t lastRetired = 7u;

    const bool completed = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(false);
    CHECK_FALSE(completed);
    if (completed) {
        OrchestratorCompletionPolicy::retireCurrentCommand(8u, lastExecuted, lastRetired);
    }

    UNSIGNED_LONGS_EQUAL(7u, lastExecuted);
    UNSIGNED_LONGS_EQUAL(7u, lastRetired);
}

TEST(OrchestratorCompletionPolicyTests, InterruptedMultiBitWaitDoesNotRetireFrontiers) {
    uint32_t lastExecuted = 11u;
    uint32_t lastRetired = 11u;

    const bool completed = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(false);
    CHECK_FALSE(completed);
    if (completed) {
        OrchestratorCompletionPolicy::retireCurrentCommand(12u, lastExecuted, lastRetired);
    }

    UNSIGNED_LONGS_EQUAL(11u, lastExecuted);
    UNSIGNED_LONGS_EQUAL(11u, lastRetired);
}

TEST(OrchestratorCompletionPolicyTests, SuccessfulWaitRetiresBothFrontiers) {
    uint32_t lastExecuted = 2u;
    uint32_t lastRetired = 2u;

    CHECK_TRUE(OrchestratorCompletionPolicy::didInterruptibleWaitComplete(true));
    OrchestratorCompletionPolicy::retireCurrentCommand(12u, lastExecuted, lastRetired);

    UNSIGNED_LONGS_EQUAL(12u, lastExecuted);
    UNSIGNED_LONGS_EQUAL(12u, lastRetired);
}

TEST(OrchestratorCompletionPolicyTests, WaitCommandOnlyRetiresWhenDelayCompletes) {
    CHECK_FALSE(OrchestratorCompletionPolicy::didPauseAwareDelayComplete(false, 4u));
    CHECK_FALSE(OrchestratorCompletionPolicy::didPauseAwareDelayComplete(true, 2u));
    CHECK_TRUE(OrchestratorCompletionPolicy::didPauseAwareDelayComplete(true, 0u));
}

TEST(OrchestratorCompletionPolicyTests, DispenseLikeInterruptedWaitDoesNotRetire) {
    uint32_t lastExecuted = 20u;
    uint32_t lastRetired = 20u;

    const bool completed = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(false);
    CHECK_FALSE(completed);
    if (completed) {
        OrchestratorCompletionPolicy::retireCurrentCommand(21u, lastExecuted, lastRetired);
    }

    UNSIGNED_LONGS_EQUAL(20u, lastExecuted);
    UNSIGNED_LONGS_EQUAL(20u, lastRetired);
}

TEST(OrchestratorCompletionPolicyTests, MoveLikeInterruptedWaitDoesNotRetire) {
    uint32_t lastExecuted = 30u;
    uint32_t lastRetired = 30u;

    const bool completed = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(false);
    CHECK_FALSE(completed);
    if (completed) {
        OrchestratorCompletionPolicy::retireCurrentCommand(31u, lastExecuted, lastRetired);
    }

    UNSIGNED_LONGS_EQUAL(30u, lastExecuted);
    UNSIGNED_LONGS_EQUAL(30u, lastRetired);
}
