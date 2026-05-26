#include "CppUTest/TestHarness.h"
#include "PressureQualificationMath.h"

TEST_GROUP(PressureQualificationMath)
{
};

TEST(PressureQualificationMath, ComputesSignedPressureSlopePerMinute)
{
    LONGS_EQUAL(-1200, PressureQualificationMath::slopeRawPerMin(1900, 1800, 5000));
    LONGS_EQUAL(600, PressureQualificationMath::slopeRawPerMin(1800, 1850, 5000));
    LONGS_EQUAL(0, PressureQualificationMath::slopeRawPerMin(1800, 1900, 0));
}

TEST(PressureQualificationMath, ConvertsPsiMilliToPressureRaw)
{
    UNSIGNED_LONGS_EQUAL(1638u, PressureQualificationMath::pressureRawFromPsiMilli(0u));
    UNSIGNED_LONGS_EQUAL(2512u, PressureQualificationMath::pressureRawFromPsiMilli(1000u));
    UNSIGNED_LONGS_EQUAL(3386u, PressureQualificationMath::pressureRawFromPsiMilli(2000u));
    UNSIGNED_LONGS_EQUAL(4259u, PressureQualificationMath::pressureRawFromPsiMilli(3000u));
}

TEST(PressureQualificationMath, ConvertsSignedPsiMilliToVacuumPressureRaw)
{
    LONGS_EQUAL(1638, PressureQualificationMath::pressureRawFromSignedPsiMilli(0));
    LONGS_EQUAL(764, PressureQualificationMath::pressureRawFromSignedPsiMilli(-1000));
    LONGS_EQUAL(327, PressureQualificationMath::pressureRawFromSignedPsiMilli(-1500));
    LONGS_EQUAL(2512, PressureQualificationMath::pressureRawFromSignedPsiMilli(1000));
}

TEST(PressureQualificationMath, SplitsPressureTargetsIntoAdjacentOnePsiSteps)
{
    const uint32_t onePsiRaw =
        PressureQualificationMath::pressureRawFromPsiMilli(1000u) -
        PressureQualificationMath::pressureRawFromPsiMilli(0u);
    int32_t targets[4] = {};

    size_t count = PressureQualificationMath::buildAdjacentTargetSequence(1638, 3386, onePsiRaw, targets, 4);
    UNSIGNED_LONGS_EQUAL(2u, count);
    LONGS_EQUAL(2512, targets[0]);
    LONGS_EQUAL(3386, targets[1]);

    count = PressureQualificationMath::buildAdjacentTargetSequence(2512, 4259, onePsiRaw, targets, 4);
    UNSIGNED_LONGS_EQUAL(2u, count);
    LONGS_EQUAL(3386, targets[0]);
    LONGS_EQUAL(4259, targets[1]);

    count = PressureQualificationMath::buildAdjacentTargetSequence(4259, 1638, onePsiRaw, targets, 4);
    UNSIGNED_LONGS_EQUAL(3u, count);
    LONGS_EQUAL(3385, targets[0]);
    LONGS_EQUAL(2511, targets[1]);
    LONGS_EQUAL(1638, targets[2]);
}

TEST(PressureQualificationMath, ExactOnePsiTransitionIsNotSubdivided)
{
    const uint32_t onePsiRaw =
        PressureQualificationMath::pressureRawFromPsiMilli(1000u) -
        PressureQualificationMath::pressureRawFromPsiMilli(0u);
    int32_t targets[2] = {};

    const size_t count = PressureQualificationMath::buildAdjacentTargetSequence(1638, 2512, onePsiRaw, targets, 2);

    UNSIGNED_LONGS_EQUAL(1u, count);
    LONGS_EQUAL(2512, targets[0]);
}

TEST(PressureQualificationMath, MotorTravelGuardTracksAbsoluteAndTransitionLimits)
{
    PressureQualificationMath::MotorTravelGuardLimits limits{};
    limits.absoluteLimitSteps = 80000;
    limits.transitionLimitSteps = 50000;
    PressureQualificationMath::MotorTravelGuardState state{};

    CHECK_FALSE(PressureQualificationMath::updateMotorTravelGuard(49999, 10000, limits, state));
    UNSIGNED_LONGS_EQUAL(49999u, state.motorAbsMax);
    UNSIGNED_LONGS_EQUAL(39999u, state.motorDeltaMax);

    CHECK_TRUE(PressureQualificationMath::updateMotorTravelGuard(60000, 10000, limits, state));
    CHECK_FALSE(state.guardAbs);
    CHECK_TRUE(state.guardDelta);

    CHECK_TRUE(PressureQualificationMath::updateMotorTravelGuard(-80000, 10000, limits, state));
    CHECK_TRUE(state.guardAbs);
    CHECK_TRUE(state.guardDelta);
    UNSIGNED_LONGS_EQUAL(80000u, state.motorAbsMax);
    UNSIGNED_LONGS_EQUAL(90000u, state.motorDeltaMax);
}

TEST(PressureQualificationMath, SummarizesMotorPositionSpan)
{
    const int32_t positions[] = {105, 100, 111, 103};

    const auto stats = PressureQualificationMath::summarizeInt32Span(positions, 4);

    UNSIGNED_LONGS_EQUAL(4u, stats.sampleCount);
    LONGS_EQUAL(100, stats.minValue);
    LONGS_EQUAL(111, stats.maxValue);
    UNSIGNED_LONGS_EQUAL(11u, stats.span);
}

TEST(PressureQualificationMath, EmptySpanIsZero)
{
    const auto stats = PressureQualificationMath::summarizeInt32Span(nullptr, 3);

    UNSIGNED_LONGS_EQUAL(0u, stats.sampleCount);
    LONGS_EQUAL(0, stats.minValue);
    LONGS_EQUAL(0, stats.maxValue);
    UNSIGNED_LONGS_EQUAL(0u, stats.span);
}

TEST(PressureQualificationMath, HomeRepeatabilitySummaryUsesOnlySuccessfulHomes)
{
    const int32_t successfulHomes[] = {100, 103};

    const auto summary = PressureQualificationMath::summarizeHomeRepeatability(
        successfulHomes,
        2,
        3,
        0,
        1);

    UNSIGNED_LONGS_EQUAL(3u, summary.expectedCount);
    UNSIGNED_LONGS_EQUAL(2u, summary.sampleCount);
    UNSIGNED_LONGS_EQUAL(1u, summary.missingCount);
    UNSIGNED_LONGS_EQUAL(3u, summary.span);
    UNSIGNED_LONGS_EQUAL(3u, summary.drift);
    UNSIGNED_LONGS_EQUAL(0u, summary.moveTimeoutCount);
    UNSIGNED_LONGS_EQUAL(1u, summary.homeTimeoutCount);
    CHECK_FALSE(summary.pass);
}

TEST(PressureQualificationMath, HomeRepeatabilitySummaryPassesCleanMeasuredHomes)
{
    const int32_t successfulHomes[] = {100, 101, 99};

    const auto summary = PressureQualificationMath::summarizeHomeRepeatability(
        successfulHomes,
        3,
        3,
        0,
        0);

    UNSIGNED_LONGS_EQUAL(3u, summary.sampleCount);
    UNSIGNED_LONGS_EQUAL(0u, summary.missingCount);
    UNSIGNED_LONGS_EQUAL(2u, summary.span);
    UNSIGNED_LONGS_EQUAL(1u, summary.drift);
    CHECK_TRUE(summary.pass);
}

TEST(PressureQualificationMath, ComputesMeanDifferenceBetweenPositionGroups)
{
    const int32_t fromBelow[] = {100, 104};
    const int32_t fromAbove[] = {116, 120};

    UNSIGNED_LONGS_EQUAL(16u, PressureQualificationMath::meanDifferenceAbs(fromBelow, 2, fromAbove, 2));
    UNSIGNED_LONGS_EQUAL(0u, PressureQualificationMath::meanDifferenceAbs(nullptr, 0, fromAbove, 2));
}

TEST(PressureQualificationMath, ExecutionPassRequiresNoMissesOrTimeouts)
{
    PressureQualificationMath::ExecutionSummary summary{};
    CHECK_TRUE(PressureQualificationMath::executionPass(summary));

    summary.readyMissCount = 1;
    CHECK_FALSE(PressureQualificationMath::executionPass(summary));

    summary.readyMissCount = 0;
    summary.timeoutCount = 1;
    CHECK_FALSE(PressureQualificationMath::executionPass(summary));

    summary.timeoutCount = 0;
    summary.abortCount = 1;
    CHECK_FALSE(PressureQualificationMath::executionPass(summary));

    summary.abortCount = 0;
    summary.motorGuardCount = 1;
    CHECK_FALSE(PressureQualificationMath::executionPass(summary));
}
