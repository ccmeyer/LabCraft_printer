#include "CppUTest/TestHarness.h"
#include "NormalizedCosineProfile.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>

namespace {

uint32_t velocitySquaredCosineArr(uint32_t intervalIndex,
                                  uint32_t intervalCount,
                                  uint32_t fromArr,
                                  uint32_t toArr)
{
    if (intervalCount == 0u || intervalIndex >= intervalCount) {
        return toArr;
    }
    const bool descending = fromArr > toArr;
    double phase = static_cast<double>(intervalIndex) /
                   static_cast<double>(intervalCount);
    if (!descending) phase = 1.0 - phase;
    const double ease = 0.5 * (1.0 - std::cos(3.14159265358979323846 * phase));
    const double slowPeriod = static_cast<double>(std::max(fromArr, toArr)) + 1.0;
    const double fastPeriod = static_cast<double>(std::min(fromArr, toArr)) + 1.0;
    const double inversePeriodSquared =
        (1.0 - ease) / (slowPeriod * slowPeriod) +
        ease / (fastPeriod * fastPeriod);
    const uint32_t period = static_cast<uint32_t>(
        std::llround(1.0 / std::sqrt(inversePeriodSquared)));
    return period - 1u;
}

uint32_t absDifference(uint32_t lhs, uint32_t rhs)
{
    return (lhs >= rhs) ? (lhs - rhs) : (rhs - lhs);
}

}  // namespace

TEST_GROUP(NormalizedCosineProfile)
{
};

TEST(NormalizedCosineProfile, HandlesInvalidImmediateAndClampedPreparation)
{
    using namespace NormalizedCosineProfile;
    RampCursor cursor{};

    CHECK_EQUAL(static_cast<int>(PrepareStatus::InvalidBounds),
                static_cast<int>(prepare({10u, 20u, 30u, 29u, 5u}, cursor)));
    CHECK_FALSE(advance(cursor));
    UNSIGNED_LONGS_EQUAL(0u, currentArr(cursor));

    CHECK_EQUAL(static_cast<int>(PrepareStatus::Immediate),
                static_cast<int>(prepare({5u, 900u, 100u, 800u, 0u}, cursor)));
    CHECK_TRUE(atEndpoint(cursor));
    UNSIGNED_LONGS_EQUAL(800u, currentArr(cursor));
    CHECK_FALSE(advance(cursor));

    CHECK_EQUAL(static_cast<int>(PrepareStatus::Ready),
                static_cast<int>(prepare({5u, 900u, 100u, 800u, 2u}, cursor)));
    CHECK_FALSE(atEndpoint(cursor));
    UNSIGNED_LONGS_EQUAL(100u, currentArr(cursor));
    CHECK_TRUE(advance(cursor));
    CHECK_TRUE(advance(cursor));
    CHECK_TRUE(atEndpoint(cursor));
    UNSIGNED_LONGS_EQUAL(800u, currentArr(cursor));
    CHECK_FALSE(advance(cursor));
}

TEST(NormalizedCosineProfile, LutIsExactMonotonicAndTimeReversible)
{
    using namespace NormalizedCosineProfile;
    uint32_t acceleration[kLutIntervals + 1u] = {};
    uint32_t deceleration[kLutIntervals + 1u] = {};
    RampCursor accelerationCursor{};
    RampCursor decelerationCursor{};
    CHECK_EQUAL(static_cast<int>(PrepareStatus::Ready),
                static_cast<int>(prepare(
                    {kEaseOne, 0u, 0u, kEaseOne, kLutIntervals},
                    accelerationCursor)));
    CHECK_EQUAL(static_cast<int>(PrepareStatus::Ready),
                static_cast<int>(prepare(
                    {0u, kEaseOne, 0u, kEaseOne, kLutIntervals},
                    decelerationCursor)));

    for (uint32_t i = 0u; i <= kLutIntervals; ++i) {
        acceleration[i] = currentArr(accelerationCursor);
        deceleration[i] = currentArr(decelerationCursor);
        if (i != 0u) {
            CHECK_TRUE(acceleration[i] <= acceleration[i - 1u]);
            CHECK_TRUE(deceleration[i] >= deceleration[i - 1u]);
        }
        if (i != kLutIntervals) {
            CHECK_TRUE(advance(accelerationCursor));
            CHECK_TRUE(advance(decelerationCursor));
        }
    }

    UNSIGNED_LONGS_EQUAL(kEaseOne, acceleration[0]);
    UNSIGNED_LONGS_EQUAL(0u, acceleration[kLutIntervals]);
    UNSIGNED_LONGS_EQUAL(0u, deceleration[0]);
    UNSIGNED_LONGS_EQUAL(kEaseOne, deceleration[kLutIntervals]);
    for (uint32_t i = 0u; i <= kLutIntervals; ++i) {
        CHECK_TRUE(absDifference(
            acceleration[i], deceleration[kLutIntervals - i]) <= 1u);
    }
}

TEST(NormalizedCosineProfile, PhaseAccumulatorMatchesExactQ32Fractions)
{
    using namespace NormalizedCosineProfile;
    const uint32_t intervalCounts[] = {1u, 2u, 3u, 10u, 258u, 1000u, 11430u, 60000u};

    for (uint32_t intervalCount : intervalCounts) {
        RampCursor cursor{};
        CHECK_EQUAL(static_cast<int>(PrepareStatus::Ready),
                    static_cast<int>(prepare(
                        {50000u, 1000u, 0u, 65535u, intervalCount}, cursor)));
        for (uint32_t k = 0u; k < intervalCount; ++k) {
            const uint32_t expected = static_cast<uint32_t>(
                (static_cast<uint64_t>(k) << 32u) / intervalCount);
            UNSIGNED_LONGS_EQUAL(expected, cursor.phaseQ32);
            CHECK_TRUE(advance(cursor));
        }
        CHECK_TRUE(atEndpoint(cursor));
        UNSIGNED_LONGS_EQUAL(1000u, currentArr(cursor));
    }
}

TEST(NormalizedCosineProfile, MatchesVelocitySquaredCosineAtNominalPeriodRatio)
{
    using namespace NormalizedCosineProfile;
    const uint32_t intervalCounts[] = {1u, 2u, 3u, 10u, 258u, 1000u, 10000u, 11430u, 60000u};
    constexpr uint32_t kSlowArr = 4999u;
    constexpr uint32_t kFastArr = 999u;

    uint32_t maximumError = 0u;
    double squaredError = 0.0;
    uint64_t sampleCount = 0u;

    for (uint32_t intervalCount : intervalCounts) {
        for (uint32_t direction = 0u; direction < 2u; ++direction) {
            const uint32_t from = direction == 0u ? kSlowArr : kFastArr;
            const uint32_t to = direction == 0u ? kFastArr : kSlowArr;
            RampCursor cursor{};
            CHECK_EQUAL(static_cast<int>(PrepareStatus::Ready),
                        static_cast<int>(prepare(
                            {from, to, 0u, 65535u, intervalCount}, cursor)));
            for (uint32_t k = 0u; k <= intervalCount; ++k) {
                const uint32_t actual = currentArr(cursor);
                const uint32_t expected = velocitySquaredCosineArr(
                    k, intervalCount, from, to);
                const uint32_t error = absDifference(actual, expected);
                maximumError = std::max(maximumError, error);
                squaredError += static_cast<double>(error) * error;
                ++sampleCount;
                if (k != intervalCount) {
                    CHECK_TRUE(advance(cursor));
                }
            }
        }
    }

    const double rmsError = std::sqrt(squaredError / static_cast<double>(sampleCount));
    CHECK_TRUE(maximumError <= 3u);
    CHECK_TRUE(rmsError <= 1.0);
}

TEST(NormalizedCosineProfile, PiecewiseAccelerationCoefficientStaysBelowPlannerBound)
{
    using namespace NormalizedCosineProfile;
    constexpr uint32_t kFastPeriod = 100000u;
    double maximumCoefficient = 0.0;

    // Cover period ratios 1.01 through 5.00. The coordinated planner always
    // stays in this range because start ARR is target ARR times five, capped
    // by the timer maximum.
    for (uint32_t ratioHundredths = 101u;
         ratioHundredths <= 500u;
         ++ratioHundredths) {
        const uint32_t slowPeriod =
            (kFastPeriod * ratioHundredths) / 100u;
        RampCursor cursor{};
        CHECK_EQUAL(static_cast<int>(PrepareStatus::Ready),
                    static_cast<int>(prepare(
                        {slowPeriod - 1u,
                         kFastPeriod - 1u,
                         0u,
                         std::numeric_limits<uint32_t>::max(),
                         kLutIntervals},
                        cursor)));
        double previousNormalizedRate =
            static_cast<double>(kFastPeriod) / slowPeriod;
        for (uint32_t cell = 0u; cell < kLutIntervals; ++cell) {
            CHECK_TRUE(advance(cursor));
            const double normalizedRate =
                static_cast<double>(kFastPeriod) /
                (static_cast<double>(currentArr(cursor)) + 1.0);
            const double coefficient =
                (normalizedRate * normalizedRate -
                 previousNormalizedRate * previousNormalizedRate) *
                (static_cast<double>(kLutIntervals) / 2.0);
            maximumCoefficient = std::max(maximumCoefficient, coefficient);
            previousNormalizedRate = normalizedRate;
        }
    }

    CHECK_COMPARE(maximumCoefficient, <, 0.8005);
    CHECK_COMPARE(maximumCoefficient, <, 7.0 / 8.0);
}

TEST(NormalizedCosineProfile, ReverseRampIsMonotonicAndDeterministic)
{
    using namespace NormalizedCosineProfile;
    RampCursor first{};
    RampCursor second{};
    const RampSpec spec{3802u, 19010u, 179u, 65535u, 1000u};
    CHECK_EQUAL(static_cast<int>(PrepareStatus::Ready),
                static_cast<int>(prepare(spec, first)));
    CHECK_EQUAL(static_cast<int>(PrepareStatus::Ready),
                static_cast<int>(prepare(spec, second)));

    uint32_t previous = currentArr(first);
    for (uint32_t k = 0u; k <= spec.intervalCount; ++k) {
        const uint32_t firstArr = currentArr(first);
        const uint32_t secondArr = currentArr(second);
        UNSIGNED_LONGS_EQUAL(firstArr, secondArr);
        CHECK_TRUE(firstArr >= previous);
        CHECK_TRUE(firstArr >= spec.fromArr);
        CHECK_TRUE(firstArr <= spec.toArr);
        previous = firstArr;
        if (k != spec.intervalCount) {
            CHECK_TRUE(advance(first));
            CHECK_TRUE(advance(second));
        }
    }
    UNSIGNED_LONGS_EQUAL(spec.toArr, previous);
}

TEST(NormalizedCosineProfile, LongCruiseAndShortTriangularAssembliesJoinExactly)
{
    using namespace NormalizedCosineProfile;

    auto runRamp = [](uint32_t from, uint32_t to, uint32_t intervals) {
        RampCursor cursor{};
        CHECK_EQUAL(static_cast<int>(PrepareStatus::Ready),
                    static_cast<int>(prepare(
                        {from, to, 179u, 65535u, intervals}, cursor)));
        UNSIGNED_LONGS_EQUAL(from, currentArr(cursor));
        for (uint32_t k = 0u; k < intervals; ++k) {
            CHECK_TRUE(advance(cursor));
        }
        CHECK_TRUE(atEndpoint(cursor));
        UNSIGNED_LONGS_EQUAL(to, currentArr(cursor));
    };

    runRamp(5620u, 1124u, 11430u);
    // A cruise segment is represented by retaining the exact acceleration
    // endpoint until the reversed deceleration cursor begins.
    runRamp(1124u, 5620u, 11430u);

    // Two short halves join at the same peak ARR for a triangular move.
    runRamp(37495u, 7499u, 258u);
    runRamp(7499u, 37495u, 258u);
}

TEST(NormalizedCosineProfile, ZeroDistanceAndAbsentAxisPreparationStayConstant)
{
    using namespace NormalizedCosineProfile;
    RampCursor zeroDistance{};
    CHECK_EQUAL(static_cast<int>(PrepareStatus::Ready),
                static_cast<int>(prepare(
                    {3802u, 3802u, 179u, 65535u, 1000u}, zeroDistance)));
    for (uint32_t k = 0u; k < 1000u; ++k) {
        UNSIGNED_LONGS_EQUAL(3802u, currentArr(zeroDistance));
        CHECK_TRUE(advance(zeroDistance));
    }
    UNSIGNED_LONGS_EQUAL(3802u, currentArr(zeroDistance));

    RampCursor absentAxis{};
    CHECK_EQUAL(static_cast<int>(PrepareStatus::Immediate),
                static_cast<int>(prepare(
                    {65535u, 0u, 0u, 65535u, 0u}, absentAxis)));
    CHECK_TRUE(atEndpoint(absentAxis));
    UNSIGNED_LONGS_EQUAL(0u, currentArr(absentAxis));
    CHECK_FALSE(advance(absentAxis));
}

TEST(NormalizedCosineProfile, FullWidthInputsRemainBoundedWithoutOverflow)
{
    using namespace NormalizedCosineProfile;
    constexpr uint32_t kMaximum = std::numeric_limits<uint32_t>::max();
    RampCursor cursor{};
    CHECK_EQUAL(static_cast<int>(PrepareStatus::Ready),
                static_cast<int>(prepare({kMaximum, 0u, 0u, kMaximum, 2u}, cursor)));
    UNSIGNED_LONGS_EQUAL(kMaximum, currentArr(cursor));
    CHECK_TRUE(advance(cursor));
    const uint32_t midpoint = currentArr(cursor);
    CHECK_TRUE(midpoint > 0u);
    CHECK_TRUE(midpoint < kMaximum);
    CHECK_TRUE(advance(cursor));
    UNSIGNED_LONGS_EQUAL(0u, currentArr(cursor));

    CHECK_EQUAL(static_cast<int>(PrepareStatus::Ready),
                static_cast<int>(prepare(
                    {kMaximum, 0u, 0u, kMaximum, kMaximum}, cursor)));
    UNSIGNED_LONGS_EQUAL(1u, cursor.phaseIncrementQ32);
    CHECK_TRUE(advance(cursor));
    UNSIGNED_LONGS_EQUAL(1u, cursor.phaseQ32);
}
