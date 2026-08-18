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

TEST(OrchestratorCompletionPolicyTests, FailedAbsXyRetiresAcceptedWindowWithoutCompletingIt) {
    uint32_t current = 8u;
    uint32_t lastExecuted = 7u;
    uint32_t lastRetired = 7u;

    OrchestratorCompletionPolicy::retireFailedAcceptedCommands(
        11u, current, lastRetired);

    UNSIGNED_LONGS_EQUAL(7u, lastExecuted);
    UNSIGNED_LONGS_EQUAL(11u, lastRetired);
    UNSIGNED_LONGS_EQUAL(11u, current);
}

TEST(OrchestratorCompletionPolicyTests, FailedAbsXyNeverMovesRetiredFrontierBackward) {
    uint32_t current = 12u;
    uint32_t lastRetired = 12u;

    OrchestratorCompletionPolicy::retireFailedAcceptedCommands(
        11u, current, lastRetired);

    UNSIGNED_LONGS_EQUAL(12u, lastRetired);
    UNSIGNED_LONGS_EQUAL(12u, current);
}

TEST(OrchestratorCompletionPolicyTests, WaitCommandOnlyRetiresWhenDelayCompletes) {
    CHECK_FALSE(OrchestratorCompletionPolicy::didPauseAwareDelayComplete(false, 4u));
    CHECK_FALSE(OrchestratorCompletionPolicy::didPauseAwareDelayComplete(true, 2u));
    CHECK_TRUE(OrchestratorCompletionPolicy::didPauseAwareDelayComplete(true, 0u));
}

TEST(OrchestratorCompletionPolicyTests, AbsXyMotionHoldIgnoresSmallMoves) {
    CHECK_FALSE(OrchestratorCompletionPolicy::shouldHoldRegulatorsForAbsXy(4999, 1200, 5000u, false));
    CHECK_FALSE(OrchestratorCompletionPolicy::shouldHoldRegulatorsForAbsXy(-1200, -4999, 5000u, false));
}

TEST(OrchestratorCompletionPolicyTests, AbsXyMotionHoldTriggersAtThreshold) {
    CHECK_TRUE(OrchestratorCompletionPolicy::shouldHoldRegulatorsForAbsXy(5000, 0, 5000u, false));
    CHECK_TRUE(OrchestratorCompletionPolicy::shouldHoldRegulatorsForAbsXy(0, -5000, 5000u, false));
}

TEST(OrchestratorCompletionPolicyTests, AbsXyMotionHoldUsesLongestAxis) {
    CHECK_TRUE(OrchestratorCompletionPolicy::shouldHoldRegulatorsForAbsXy(3000, -9000, 5000u, false));
    CHECK_TRUE(OrchestratorCompletionPolicy::shouldHoldRegulatorsForAbsXy(-9000, 3000, 5000u, false));
}

TEST(OrchestratorCompletionPolicyTests, AbsXyMotionHoldDoesNotTriggerWhilePrinting) {
    CHECK_FALSE(OrchestratorCompletionPolicy::shouldHoldRegulatorsForAbsXy(20000, 20000, 5000u, true));
}

TEST(OrchestratorCompletionPolicyTests, AbsXyCompletionRequiresEveryGate) {
    OrchestratorCompletionPolicy::AbsXyCompletionInput input{
        true, true, false, true, false, true, true};
    LONGS_EQUAL(
        static_cast<long>(OrchestratorCompletionPolicy::AbsXyDisposition::Completed),
        static_cast<long>(OrchestratorCompletionPolicy::evaluateAbsXyCompletion(input)));

    input.startAccepted = false;
    LONGS_EQUAL(
        static_cast<long>(OrchestratorCompletionPolicy::AbsXyDisposition::MotionFailure),
        static_cast<long>(OrchestratorCompletionPolicy::evaluateAbsXyCompletion(input)));
    input.startAccepted = true;
    input.waitCompleted = false;
    LONGS_EQUAL(
        static_cast<long>(OrchestratorCompletionPolicy::AbsXyDisposition::MotionFailure),
        static_cast<long>(OrchestratorCompletionPolicy::evaluateAbsXyCompletion(input)));
    input.waitCompleted = true;
    input.terminalCompleted = false;
    LONGS_EQUAL(
        static_cast<long>(OrchestratorCompletionPolicy::AbsXyDisposition::MotionFailure),
        static_cast<long>(OrchestratorCompletionPolicy::evaluateAbsXyCompletion(input)));
    input.terminalCompleted = true;
    input.endpointMatches = false;
    LONGS_EQUAL(
        static_cast<long>(OrchestratorCompletionPolicy::AbsXyDisposition::MotionFailure),
        static_cast<long>(OrchestratorCompletionPolicy::evaluateAbsXyCompletion(input)));
    input.endpointMatches = true;
    input.targetsMatch = false;
    LONGS_EQUAL(
        static_cast<long>(OrchestratorCompletionPolicy::AbsXyDisposition::MotionFailure),
        static_cast<long>(OrchestratorCompletionPolicy::evaluateAbsXyCompletion(input)));
}

TEST(OrchestratorCompletionPolicyTests, AbsXyControlInterruptionIsResumableNotFailure) {
    const OrchestratorCompletionPolicy::AbsXyCompletionInput input{
        true, false, true, false, false, false, false};
    LONGS_EQUAL(
        static_cast<long>(OrchestratorCompletionPolicy::AbsXyDisposition::Interrupted),
        static_cast<long>(OrchestratorCompletionPolicy::evaluateAbsXyCompletion(input)));
}

TEST(OrchestratorCompletionPolicyTests, AbsXyRejectedStartIsNotMaskedByControlInterruption) {
    const OrchestratorCompletionPolicy::AbsXyCompletionInput input{
        false, false, true, false, false, false, false};
    LONGS_EQUAL(
        static_cast<long>(OrchestratorCompletionPolicy::AbsXyDisposition::MotionFailure),
        static_cast<long>(OrchestratorCompletionPolicy::evaluateAbsXyCompletion(input)));
}

TEST(OrchestratorCompletionPolicyTests, AbsXyLimitOrPlannerFailureWinsOverControlInterruption) {
    const OrchestratorCompletionPolicy::AbsXyCompletionInput input{
        true, false, true, false, true, false, false};
    LONGS_EQUAL(
        static_cast<long>(OrchestratorCompletionPolicy::AbsXyDisposition::MotionFailure),
        static_cast<long>(OrchestratorCompletionPolicy::evaluateAbsXyCompletion(input)));
}

TEST(OrchestratorCompletionPolicyTests, DirectMoveCompletionRequiresEveryGate) {
    OrchestratorCompletionPolicy::DirectMoveCompletionInput input{
        true, true, false, true, false, true, true};
    LONGS_EQUAL(
        static_cast<long>(OrchestratorCompletionPolicy::DirectMoveDisposition::Completed),
        static_cast<long>(OrchestratorCompletionPolicy::evaluateDirectMoveCompletion(input)));

    input.endpointMatches = false;
    LONGS_EQUAL(
        static_cast<long>(OrchestratorCompletionPolicy::DirectMoveDisposition::MotionFailure),
        static_cast<long>(OrchestratorCompletionPolicy::evaluateDirectMoveCompletion(input)));
    input.endpointMatches = true;
    input.targetsMatch = false;
    LONGS_EQUAL(
        static_cast<long>(OrchestratorCompletionPolicy::DirectMoveDisposition::MotionFailure),
        static_cast<long>(OrchestratorCompletionPolicy::evaluateDirectMoveCompletion(input)));
}

TEST(OrchestratorCompletionPolicyTests, DirectMovePauseIsResumable) {
    const OrchestratorCompletionPolicy::DirectMoveCompletionInput input{
        true, false, true, false, false, false, false};
    LONGS_EQUAL(
        static_cast<long>(OrchestratorCompletionPolicy::DirectMoveDisposition::Interrupted),
        static_cast<long>(OrchestratorCompletionPolicy::evaluateDirectMoveCompletion(input)));
}

TEST(OrchestratorCompletionPolicyTests, DirectMoveFailureWinsOverPause) {
    const OrchestratorCompletionPolicy::DirectMoveCompletionInput input{
        true, false, true, false, true, false, false};
    LONGS_EQUAL(
        static_cast<long>(OrchestratorCompletionPolicy::DirectMoveDisposition::MotionFailure),
        static_cast<long>(OrchestratorCompletionPolicy::evaluateDirectMoveCompletion(input)));
}

TEST(OrchestratorCompletionPolicyTests, DirectMoveRejectedStartIsTerminal) {
    const OrchestratorCompletionPolicy::DirectMoveCompletionInput input{
        false, false, false, false, false, false, false};
    LONGS_EQUAL(
        static_cast<long>(OrchestratorCompletionPolicy::DirectMoveDisposition::MotionFailure),
        static_cast<long>(OrchestratorCompletionPolicy::evaluateDirectMoveCompletion(input)));
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
