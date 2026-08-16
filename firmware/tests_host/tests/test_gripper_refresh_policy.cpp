#include "CppUTest/TestHarness.h"

#include "GripperRefreshPolicy.h"

namespace {

unsigned int directiveValue(GripperRefreshPolicy::PeriodicTimerDirective directive)
{
    return static_cast<unsigned int>(directive);
}

}  // namespace

TEST_GROUP(GripperRefreshPolicyTests)
{
};

TEST(GripperRefreshPolicyTests, InitializeClearsAllState)
{
    GripperRefreshPolicy::State state{};
    state.mode = GripperRefreshPolicy::Mode::DeferredUntilDispense;
    state.refreshPending = true;
    state.hasPulseCompletion = true;
    state.lastPulseCompletionMs = 123u;

    GripperRefreshPolicy::initialize(state);

    CHECK_FALSE(GripperRefreshPolicy::isDeferred(state));
    CHECK_FALSE(GripperRefreshPolicy::hasPending(state));
    CHECK_FALSE(state.hasPulseCompletion);
    UNSIGNED_LONGS_EQUAL(0u, state.lastPulseCompletionMs);
    UNSIGNED_LONGS_EQUAL(
        0u,
        GripperRefreshPolicy::remainingDispenseCooldownMs(state, 10u, 50u));
}

TEST(GripperRefreshPolicyTests, EnableDeferredStartsFreshIntervalAndClearsPending)
{
    GripperRefreshPolicy::State state{};
    state.refreshPending = true;

    const auto directive = GripperRefreshPolicy::enableDeferred(state);

    CHECK_TRUE(GripperRefreshPolicy::isDeferred(state));
    CHECK_FALSE(GripperRefreshPolicy::hasPending(state));
    UNSIGNED_LONGS_EQUAL(
        directiveValue(GripperRefreshPolicy::PeriodicTimerDirective::StartOrReset),
        directiveValue(directive));
}

TEST(GripperRefreshPolicyTests, ReenableClearsStalePendingAndRestartsInterval)
{
    GripperRefreshPolicy::State state{};
    GripperRefreshPolicy::enableDeferred(state);
    CHECK_TRUE(GripperRefreshPolicy::markRefreshDue(state));

    const auto directive = GripperRefreshPolicy::enableDeferred(state);

    CHECK_FALSE(GripperRefreshPolicy::hasPending(state));
    UNSIGNED_LONGS_EQUAL(
        directiveValue(GripperRefreshPolicy::PeriodicTimerDirective::StartOrReset),
        directiveValue(directive));
}

TEST(GripperRefreshPolicyTests, RefreshDueIsIgnoredWhileDisabled)
{
    GripperRefreshPolicy::State state{};

    CHECK_FALSE(GripperRefreshPolicy::markRefreshDue(state));
    CHECK_FALSE(GripperRefreshPolicy::hasPending(state));
}

TEST(GripperRefreshPolicyTests, RepeatedRefreshDueEventsCoalesce)
{
    GripperRefreshPolicy::State state{};
    GripperRefreshPolicy::enableDeferred(state);

    CHECK_TRUE(GripperRefreshPolicy::markRefreshDue(state));
    CHECK_FALSE(GripperRefreshPolicy::markRefreshDue(state));
    CHECK_FALSE(GripperRefreshPolicy::markRefreshDue(state));
    CHECK_TRUE(GripperRefreshPolicy::hasPending(state));
}

TEST(GripperRefreshPolicyTests, PendingRefreshCanBeClaimedExactlyOnce)
{
    GripperRefreshPolicy::State state{};
    GripperRefreshPolicy::enableDeferred(state);
    GripperRefreshPolicy::markRefreshDue(state);

    CHECK_TRUE(GripperRefreshPolicy::claimPendingAfterDispense(state));
    CHECK_FALSE(GripperRefreshPolicy::claimPendingAfterDispense(state));
    CHECK_FALSE(GripperRefreshPolicy::hasPending(state));
}

TEST(GripperRefreshPolicyTests, ClaimRequiresDeferredModeAndPendingRefresh)
{
    GripperRefreshPolicy::State state{};

    CHECK_FALSE(GripperRefreshPolicy::claimPendingAfterDispense(state));
    GripperRefreshPolicy::enableDeferred(state);
    CHECK_FALSE(GripperRefreshPolicy::claimPendingAfterDispense(state));
    GripperRefreshPolicy::markRefreshDue(state);
    GripperRefreshPolicy::disable(state);
    CHECK_FALSE(GripperRefreshPolicy::claimPendingAfterDispense(state));
}

TEST(GripperRefreshPolicyTests, DisableStopsTimerAndClearsPending)
{
    GripperRefreshPolicy::State state{};
    GripperRefreshPolicy::enableDeferred(state);
    GripperRefreshPolicy::markRefreshDue(state);

    const auto directive = GripperRefreshPolicy::disable(state);

    CHECK_FALSE(GripperRefreshPolicy::isDeferred(state));
    CHECK_FALSE(GripperRefreshPolicy::hasPending(state));
    UNSIGNED_LONGS_EQUAL(
        directiveValue(GripperRefreshPolicy::PeriodicTimerDirective::Stop),
        directiveValue(directive));
}

TEST(GripperRefreshPolicyTests, PulseCompletionRestartsTimerOnlyWhenDeferred)
{
    GripperRefreshPolicy::State state{};

    auto directive = GripperRefreshPolicy::recordPulseCompleted(state, 10u);
    UNSIGNED_LONGS_EQUAL(
        directiveValue(GripperRefreshPolicy::PeriodicTimerDirective::None),
        directiveValue(directive));

    GripperRefreshPolicy::enableDeferred(state);
    directive = GripperRefreshPolicy::recordPulseCompleted(state, 20u);
    UNSIGNED_LONGS_EQUAL(
        directiveValue(GripperRefreshPolicy::PeriodicTimerDirective::StartOrReset),
        directiveValue(directive));
}

TEST(GripperRefreshPolicyTests, PulseCompletionClearsPendingAndAnchorsCooldown)
{
    GripperRefreshPolicy::State state{};
    GripperRefreshPolicy::enableDeferred(state);
    GripperRefreshPolicy::markRefreshDue(state);

    GripperRefreshPolicy::recordPulseCompleted(state, 100u);

    CHECK_FALSE(GripperRefreshPolicy::hasPending(state));
    CHECK_TRUE(state.hasPulseCompletion);
    UNSIGNED_LONGS_EQUAL(100u, state.lastPulseCompletionMs);
    UNSIGNED_LONGS_EQUAL(
        40u,
        GripperRefreshPolicy::remainingDispenseCooldownMs(state, 110u, 50u));
}

TEST(GripperRefreshPolicyTests, DisablePreservesActiveCooldown)
{
    GripperRefreshPolicy::State state{};
    GripperRefreshPolicy::enableDeferred(state);
    GripperRefreshPolicy::recordPulseCompleted(state, 100u);

    GripperRefreshPolicy::disable(state);

    UNSIGNED_LONGS_EQUAL(
        25u,
        GripperRefreshPolicy::remainingDispenseCooldownMs(state, 125u, 50u));
}

TEST(GripperRefreshPolicyTests, CooldownHandlesZeroAndBoundaryTimes)
{
    GripperRefreshPolicy::State state{};
    GripperRefreshPolicy::recordPulseCompleted(state, 100u);

    UNSIGNED_LONGS_EQUAL(
        0u,
        GripperRefreshPolicy::remainingDispenseCooldownMs(state, 100u, 0u));
    UNSIGNED_LONGS_EQUAL(
        1u,
        GripperRefreshPolicy::remainingDispenseCooldownMs(state, 149u, 50u));
    UNSIGNED_LONGS_EQUAL(
        0u,
        GripperRefreshPolicy::remainingDispenseCooldownMs(state, 150u, 50u));
    UNSIGNED_LONGS_EQUAL(
        0u,
        GripperRefreshPolicy::remainingDispenseCooldownMs(state, 151u, 50u));
}

TEST(GripperRefreshPolicyTests, CooldownCalculationHandlesTickRollover)
{
    GripperRefreshPolicy::State state{};
    GripperRefreshPolicy::recordPulseCompleted(state, 0xFFFFFFF8u);

    UNSIGNED_LONGS_EQUAL(
        5u,
        GripperRefreshPolicy::remainingDispenseCooldownMs(state, 7u, 20u));
    UNSIGNED_LONGS_EQUAL(
        0u,
        GripperRefreshPolicy::remainingDispenseCooldownMs(state, 12u, 20u));
}
