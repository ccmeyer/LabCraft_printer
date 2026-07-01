#include "CppUTest/TestHarness.h"
#include "FlashCyclePolicy.h"

TEST_GROUP(FlashCyclePolicyTests)
{
};

TEST(FlashCyclePolicyTests, BeginCycleCreatesNonzeroActiveId)
{
    FlashCyclePolicy::State state{};

    const uint32_t cycleId = FlashCyclePolicy::beginCycle(state);

    CHECK_TRUE(cycleId != 0u);
    UNSIGNED_LONGS_EQUAL(cycleId, state.activeCycleId);
    CHECK_TRUE(FlashCyclePolicy::isActive(state));
    CHECK_FALSE(FlashCyclePolicy::isScheduled(state));
    CHECK_FALSE(FlashCyclePolicy::isAckExpected(state));
}

TEST(FlashCyclePolicyTests, ScheduleSucceedsOnlyForActiveCycle)
{
    FlashCyclePolicy::State state{};
    const uint32_t cycleId = FlashCyclePolicy::beginCycle(state);

    CHECK_FALSE(FlashCyclePolicy::schedule(state, cycleId + 1u));
    CHECK_TRUE(FlashCyclePolicy::schedule(state, cycleId));
    CHECK_FALSE(FlashCyclePolicy::schedule(state, cycleId));
    CHECK_TRUE(FlashCyclePolicy::isScheduled(state));
}

TEST(FlashCyclePolicyTests, StaleScheduledCycleCannotFire)
{
    FlashCyclePolicy::State state{};

    CHECK_FALSE(FlashCyclePolicy::consumeScheduledFire(state));

    const uint32_t cycleId = FlashCyclePolicy::beginCycle(state);
    CHECK_TRUE(FlashCyclePolicy::schedule(state, cycleId));
    FlashCyclePolicy::finish(state);

    CHECK_FALSE(FlashCyclePolicy::consumeScheduledFire(state));
    CHECK_FALSE(FlashCyclePolicy::isAckExpected(state));
}

TEST(FlashCyclePolicyTests, AckAcceptedOnlyAfterValidScheduledFire)
{
    FlashCyclePolicy::State state{};
    const uint32_t cycleId = FlashCyclePolicy::beginCycle(state);

    CHECK_FALSE(FlashCyclePolicy::noteAck(state));
    CHECK_TRUE(FlashCyclePolicy::schedule(state, cycleId));
    CHECK_TRUE(FlashCyclePolicy::consumeScheduledFire(state));
    CHECK_TRUE(FlashCyclePolicy::isAckExpected(state));
    CHECK_TRUE(FlashCyclePolicy::noteAck(state));
    CHECK_FALSE(FlashCyclePolicy::isAckExpected(state));
    CHECK_TRUE(state.ackObserved);
    CHECK_FALSE(FlashCyclePolicy::noteAck(state));
}

TEST(FlashCyclePolicyTests, FinishClearsActiveScheduledAndAckState)
{
    FlashCyclePolicy::State state{};
    const uint32_t cycleId = FlashCyclePolicy::beginCycle(state);
    CHECK_TRUE(FlashCyclePolicy::schedule(state, cycleId));
    CHECK_TRUE(FlashCyclePolicy::consumeScheduledFire(state));

    FlashCyclePolicy::finish(state);

    UNSIGNED_LONGS_EQUAL(FlashCyclePolicy::kNoCycleId, state.activeCycleId);
    UNSIGNED_LONGS_EQUAL(FlashCyclePolicy::kNoCycleId, state.scheduledCycleId);
    CHECK_FALSE(state.inProgress);
    CHECK_FALSE(state.ackExpected);
    CHECK_FALSE(state.ackObserved);
}

TEST(FlashCyclePolicyTests, RepeatedStaleTimerCallbacksAreIgnored)
{
    FlashCyclePolicy::State state{};
    const uint32_t cycleId = FlashCyclePolicy::beginCycle(state);
    CHECK_TRUE(FlashCyclePolicy::schedule(state, cycleId));

    CHECK_TRUE(FlashCyclePolicy::consumeScheduledFire(state));
    CHECK_FALSE(FlashCyclePolicy::consumeScheduledFire(state));
    CHECK_FALSE(FlashCyclePolicy::consumeScheduledFire(state));
    CHECK_TRUE(FlashCyclePolicy::isAckExpected(state));
}
