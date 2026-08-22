#include "CppUTest/TestHarness.h"

#include "MotionLimitDebouncePolicy.h"

#include <limits>

TEST_GROUP(MotionLimitDebouncePolicyTests)
{
};

TEST(MotionLimitDebouncePolicyTests, ProductionIntervalIsFixedAtFifteenMilliseconds)
{
    UNSIGNED_LONGS_EQUAL(15u, MotionLimitDebouncePolicy::kDebounceMs);
    UNSIGNED_LONGS_EQUAL(15000u,
                         MotionLimitDebouncePolicy::kHardwareDebounceUs);
}

TEST(MotionLimitDebouncePolicyTests, HardwareCandidateConfirmsOnlyAtDeadline)
{
    MotionLimitDebouncePolicy::HardwareState state{};
    LONGS_EQUAL(
        static_cast<long>(MotionLimitDebouncePolicy::HardwareDecision::Started),
        static_cast<long>(MotionLimitDebouncePolicy::beginHardwareCandidate(
            state, 100u, 15000u, true)));
    LONGS_EQUAL(
        static_cast<long>(MotionLimitDebouncePolicy::HardwareDecision::Pending),
        static_cast<long>(MotionLimitDebouncePolicy::evaluateHardwareExpiry(
            state, true, false, 15099u, 15000u, true)));
    LONGS_EQUAL(
        static_cast<long>(MotionLimitDebouncePolicy::HardwareDecision::Confirmed),
        static_cast<long>(MotionLimitDebouncePolicy::evaluateHardwareExpiry(
            state, true, false, 15100u, 15000u, true)));
}

TEST(MotionLimitDebouncePolicyTests, InterveningEdgeRestartsTheEntireHardwareWindow)
{
    MotionLimitDebouncePolicy::HardwareState state{};
    (void)MotionLimitDebouncePolicy::beginHardwareCandidate(
        state, 100u, 15000u, true);
    MotionLimitDebouncePolicy::noteHardwareTransition(state);
    LONGS_EQUAL(
        static_cast<long>(MotionLimitDebouncePolicy::HardwareDecision::Restarted),
        static_cast<long>(MotionLimitDebouncePolicy::evaluateHardwareExpiry(
            state, true, false, 15100u, 15000u, true)));
    UNSIGNED_LONGS_EQUAL(30100u, state.deadlineCount);
    LONGS_EQUAL(
        static_cast<long>(MotionLimitDebouncePolicy::HardwareDecision::Pending),
        static_cast<long>(MotionLimitDebouncePolicy::evaluateHardwareExpiry(
            state, true, false, 30099u, 15000u, true)));
    LONGS_EQUAL(
        static_cast<long>(MotionLimitDebouncePolicy::HardwareDecision::Confirmed),
        static_cast<long>(MotionLimitDebouncePolicy::evaluateHardwareExpiry(
            state, true, false, 30100u, 15000u, true)));
    const auto snapshot = MotionLimitDebouncePolicy::makeSnapshot(state);
    UNSIGNED_LONGS_EQUAL(2u, snapshot.candidateCount);
    UNSIGNED_LONGS_EQUAL(1u, snapshot.rejectionCount);
    UNSIGNED_LONGS_EQUAL(1u, snapshot.transitionCount);
    UNSIGNED_LONGS_EQUAL(1u, snapshot.restartCount);
}

TEST(MotionLimitDebouncePolicyTests, TransitionEndingReleasedRejectsHardwareCandidate)
{
    MotionLimitDebouncePolicy::HardwareState state{};
    (void)MotionLimitDebouncePolicy::beginHardwareCandidate(
        state, 10u, 20u, true);
    LONGS_EQUAL(
        static_cast<long>(MotionLimitDebouncePolicy::HardwareDecision::Rejected),
        static_cast<long>(MotionLimitDebouncePolicy::evaluateHardwareExpiry(
            state, false, true, 30u, 20u, true)));
    CHECK_FALSE(MotionLimitDebouncePolicy::makeSnapshot(state).pending);
}

TEST(MotionLimitDebouncePolicyTests, HardwareDeadlineArithmeticIsWrapSafe)
{
    MotionLimitDebouncePolicy::HardwareState state{};
    (void)MotionLimitDebouncePolicy::beginHardwareCandidate(
        state, 0xFFFFFFF0u, 32u, true);
    LONGS_EQUAL(
        static_cast<long>(MotionLimitDebouncePolicy::HardwareDecision::Pending),
        static_cast<long>(MotionLimitDebouncePolicy::evaluateHardwareExpiry(
            state, true, false, 0x0000000Fu, 32u, true)));
    LONGS_EQUAL(
        static_cast<long>(MotionLimitDebouncePolicy::HardwareDecision::Confirmed),
        static_cast<long>(MotionLimitDebouncePolicy::evaluateHardwareExpiry(
            state, true, false, 0x00000010u, 32u, true)));
}

TEST(MotionLimitDebouncePolicyTests, MissingHardwareTimerConfirmsExactlyOnceFailSafe)
{
    MotionLimitDebouncePolicy::HardwareState state{};
    LONGS_EQUAL(
        static_cast<long>(MotionLimitDebouncePolicy::HardwareDecision::Confirmed),
        static_cast<long>(MotionLimitDebouncePolicy::beginHardwareCandidate(
            state, 0u, 15000u, false)));
    LONGS_EQUAL(
        static_cast<long>(MotionLimitDebouncePolicy::HardwareDecision::AlreadyConfirmed),
        static_cast<long>(MotionLimitDebouncePolicy::forceHardwareConfirmation(state)));
    const auto snapshot = MotionLimitDebouncePolicy::makeSnapshot(state);
    UNSIGNED_LONGS_EQUAL(1u, snapshot.confirmationCount);
    UNSIGNED_LONGS_EQUAL(1u, snapshot.infrastructureFailureCount);
}

TEST(MotionLimitDebouncePolicyTests, SimultaneousHardwareAxesRemainIndependent)
{
    MotionLimitDebouncePolicy::HardwareState x{};
    MotionLimitDebouncePolicy::HardwareState y{};
    (void)MotionLimitDebouncePolicy::beginHardwareCandidate(
        x, 10u, 100u, true);
    (void)MotionLimitDebouncePolicy::beginHardwareCandidate(
        y, 20u, 100u, true);
    MotionLimitDebouncePolicy::noteHardwareTransition(x);
    LONGS_EQUAL(
        static_cast<long>(MotionLimitDebouncePolicy::HardwareDecision::Restarted),
        static_cast<long>(MotionLimitDebouncePolicy::evaluateHardwareExpiry(
            x, true, false, 110u, 100u, true)));
    LONGS_EQUAL(
        static_cast<long>(MotionLimitDebouncePolicy::HardwareDecision::Confirmed),
        static_cast<long>(MotionLimitDebouncePolicy::evaluateHardwareExpiry(
            y, true, false, 120u, 100u, true)));
    CHECK_TRUE(MotionLimitDebouncePolicy::makeSnapshot(x).pending);
    CHECK_TRUE(MotionLimitDebouncePolicy::makeSnapshot(y).confirmed);
}

TEST(MotionLimitDebouncePolicyTests, CancelInvalidatesPendingWindowAndRearmUsesFullDelay)
{
    MotionLimitDebouncePolicy::HardwareState state{};
    (void)MotionLimitDebouncePolicy::beginHardwareCandidate(
        state, 50u, 100u, true);
    MotionLimitDebouncePolicy::cancelHardware(state, true);
    LONGS_EQUAL(
        static_cast<long>(MotionLimitDebouncePolicy::HardwareDecision::None),
        static_cast<long>(MotionLimitDebouncePolicy::evaluateHardwareExpiry(
            state, true, false, 150u, 100u, true)));
    (void)MotionLimitDebouncePolicy::beginHardwareCandidate(
        state, 160u, 100u, true);
    LONGS_EQUAL(
        static_cast<long>(MotionLimitDebouncePolicy::HardwareDecision::Pending),
        static_cast<long>(MotionLimitDebouncePolicy::evaluateHardwareExpiry(
            state, true, false, 259u, 100u, true)));
    UNSIGNED_LONGS_EQUAL(1u,
        MotionLimitDebouncePolicy::makeSnapshot(state).rejectionCount);
}

TEST(MotionLimitDebouncePolicyTests, StickySharedVectorEvidenceRestartsWindow)
{
    MotionLimitDebouncePolicy::HardwareState state{};
    (void)MotionLimitDebouncePolicy::beginHardwareCandidate(
        state, 1u, 20u, true);
    LONGS_EQUAL(
        static_cast<long>(MotionLimitDebouncePolicy::HardwareDecision::Restarted),
        static_cast<long>(MotionLimitDebouncePolicy::evaluateHardwareExpiry(
            state, true, true, 21u, 20u, true)));
    UNSIGNED_LONGS_EQUAL(1u,
        MotionLimitDebouncePolicy::makeSnapshot(state).transitionCount);
}

TEST(MotionLimitDebouncePolicyTests, BoundaryAssertionAfterRejectStartsFreshWindow)
{
    MotionLimitDebouncePolicy::HardwareState state{};
    (void)MotionLimitDebouncePolicy::beginHardwareCandidate(
        state, 10u, 30u, true);
    (void)MotionLimitDebouncePolicy::evaluateHardwareExpiry(
        state, false, true, 40u, 30u, true);
    (void)MotionLimitDebouncePolicy::beginHardwareCandidate(
        state, 41u, 30u, true);
    LONGS_EQUAL(
        static_cast<long>(MotionLimitDebouncePolicy::HardwareDecision::Pending),
        static_cast<long>(MotionLimitDebouncePolicy::evaluateHardwareExpiry(
            state, true, false, 70u, 30u, true)));
    LONGS_EQUAL(
        static_cast<long>(MotionLimitDebouncePolicy::HardwareDecision::Confirmed),
        static_cast<long>(MotionLimitDebouncePolicy::evaluateHardwareExpiry(
            state, true, false, 71u, 30u, true)));
}

TEST(MotionLimitDebouncePolicyTests, ZeroAndStaleGenerationsCannotConsumeConfirmation)
{
    CHECK_FALSE(MotionLimitDebouncePolicy::hardwareGenerationMatches(0u, 0u));
    CHECK_FALSE(MotionLimitDebouncePolicy::hardwareGenerationMatches(7u, 8u));
    CHECK_TRUE(MotionLimitDebouncePolicy::hardwareGenerationMatches(8u, 8u));
}

TEST(MotionLimitDebouncePolicyTests, ConfirmsAtExactBoundaryButNotBefore)
{
    MotionLimitDebouncePolicy::State state{};
    LONGS_EQUAL(static_cast<long>(MotionLimitDebouncePolicy::Decision::Started),
                static_cast<long>(MotionLimitDebouncePolicy::observe(
                    state, true, 100u, 150u, true)));
    LONGS_EQUAL(static_cast<long>(MotionLimitDebouncePolicy::Decision::Pending),
                static_cast<long>(MotionLimitDebouncePolicy::observe(
                    state, true, 249u, 150u, true)));
    LONGS_EQUAL(static_cast<long>(MotionLimitDebouncePolicy::Decision::Confirmed),
                static_cast<long>(MotionLimitDebouncePolicy::observe(
                    state, true, 250u, 150u, true)));
}

TEST(MotionLimitDebouncePolicyTests, ReleasedTransientRestartsTheFullWindow)
{
    MotionLimitDebouncePolicy::State state{};
    (void)MotionLimitDebouncePolicy::observe(state, true, 10u, 100u, true);
    LONGS_EQUAL(static_cast<long>(MotionLimitDebouncePolicy::Decision::Rejected),
                static_cast<long>(MotionLimitDebouncePolicy::observe(
                    state, false, 90u, 100u, true)));
    (void)MotionLimitDebouncePolicy::observe(state, true, 95u, 100u, true);
    LONGS_EQUAL(static_cast<long>(MotionLimitDebouncePolicy::Decision::Pending),
                static_cast<long>(MotionLimitDebouncePolicy::observe(
                    state, true, 194u, 100u, true)));
    LONGS_EQUAL(static_cast<long>(MotionLimitDebouncePolicy::Decision::Confirmed),
                static_cast<long>(MotionLimitDebouncePolicy::observe(
                    state, true, 195u, 100u, true)));
    const auto snapshot = MotionLimitDebouncePolicy::makeSnapshot(state);
    UNSIGNED_LONGS_EQUAL(2u, snapshot.candidateCount);
    UNSIGNED_LONGS_EQUAL(1u, snapshot.rejectionCount);
    UNSIGNED_LONGS_EQUAL(1u, snapshot.confirmationCount);
}

TEST(MotionLimitDebouncePolicyTests, CycleArithmeticIsWrapSafe)
{
    MotionLimitDebouncePolicy::State state{};
    (void)MotionLimitDebouncePolicy::observe(
        state, true, 0xFFFFFFF0u, 32u, true);
    LONGS_EQUAL(static_cast<long>(MotionLimitDebouncePolicy::Decision::Pending),
                static_cast<long>(MotionLimitDebouncePolicy::observe(
                    state, true, 0x0000000Fu, 32u, true)));
    LONGS_EQUAL(static_cast<long>(MotionLimitDebouncePolicy::Decision::Confirmed),
                static_cast<long>(MotionLimitDebouncePolicy::observe(
                    state, true, 0x00000010u, 32u, true)));
}

TEST(MotionLimitDebouncePolicyTests, MissingTimebaseConfirmsAssertedInputFailSafe)
{
    MotionLimitDebouncePolicy::State state{};
    LONGS_EQUAL(static_cast<long>(MotionLimitDebouncePolicy::Decision::Confirmed),
                static_cast<long>(MotionLimitDebouncePolicy::observe(
                    state, true, 0u, 0u, false)));
    const auto snapshot = MotionLimitDebouncePolicy::makeSnapshot(state);
    CHECK_TRUE(snapshot.confirmed);
    UNSIGNED_LONGS_EQUAL(1u, snapshot.timebaseFailureCount);
}

TEST(MotionLimitDebouncePolicyTests, ConfirmedInputIsNotCountedTwice)
{
    MotionLimitDebouncePolicy::State state{};
    (void)MotionLimitDebouncePolicy::observe(state, true, 1u, 1u, true);
    (void)MotionLimitDebouncePolicy::observe(state, true, 2u, 1u, true);
    LONGS_EQUAL(static_cast<long>(MotionLimitDebouncePolicy::Decision::AlreadyConfirmed),
                static_cast<long>(MotionLimitDebouncePolicy::observe(
                    state, true, 3u, 1u, true)));
    UNSIGNED_LONGS_EQUAL(
        1u, MotionLimitDebouncePolicy::makeSnapshot(state).confirmationCount);
}

TEST(MotionLimitDebouncePolicyTests, SaturatingCountersSetAttributionFlags)
{
    MotionLimitDebouncePolicy::State state{};
    state.candidateCount = std::numeric_limits<uint32_t>::max();
    (void)MotionLimitDebouncePolicy::observe(state, true, 0u, 10u, true);
    const auto snapshot = MotionLimitDebouncePolicy::makeSnapshot(state);
    UNSIGNED_LONGS_EQUAL(std::numeric_limits<uint32_t>::max(),
                         snapshot.candidateCount);
    CHECK_TRUE((snapshot.saturationFlags &
                MotionLimitDebouncePolicy::CandidateCountSaturated) != 0u);
}
