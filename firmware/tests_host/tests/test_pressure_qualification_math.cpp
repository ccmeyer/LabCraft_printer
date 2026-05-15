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
    UNSIGNED_LONGS_EQUAL(2512u, PressureQualificationMath::pressureRawFromPsiMilli(1000u));
    UNSIGNED_LONGS_EQUAL(3386u, PressureQualificationMath::pressureRawFromPsiMilli(2000u));
    UNSIGNED_LONGS_EQUAL(4259u, PressureQualificationMath::pressureRawFromPsiMilli(3000u));
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
}
