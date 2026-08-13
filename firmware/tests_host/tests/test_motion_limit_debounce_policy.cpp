#include "CppUTest/TestHarness.h"

#include "MotionLimitDebouncePolicy.h"

#include <limits>

TEST_GROUP(MotionLimitDebouncePolicyTests)
{
};

TEST(MotionLimitDebouncePolicyTests, ProductionIntervalIsFixedAtFifteenMilliseconds)
{
    UNSIGNED_LONGS_EQUAL(15u, MotionLimitDebouncePolicy::kDebounceMs);
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
