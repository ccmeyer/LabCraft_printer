#include "CppUTest/TestHarness.h"
#include "MotionQualificationMath.h"

TEST_GROUP(MotionQualificationMath)
{
};

TEST(MotionQualificationMath, SummarizesHomeLimitSpanAndReturnError)
{
    const MotionQualificationMath::AxisHomeSample samples[] = {
        {true, -6, 100, 0},
        {true, -3, 102, 0},
        {true, -9, 99, 0},
    };

    const auto stats = MotionQualificationMath::summarizeAxisHomeSamples(samples, 3, 100);

    UNSIGNED_LONGS_EQUAL(3u, stats.sampleCount);
    LONGS_EQUAL(-9, stats.limitTriggerMinSteps);
    LONGS_EQUAL(-3, stats.limitTriggerMaxSteps);
    UNSIGNED_LONGS_EQUAL(6u, stats.limitTriggerSpanSteps);
    UNSIGNED_LONGS_EQUAL(2u, stats.returnErrorMaxSteps);
    CHECK_TRUE(MotionQualificationMath::axisHomeStatsPass(stats, 3));
}

TEST(MotionQualificationMath, HomeSummaryCountsTimeouts)
{
    const MotionQualificationMath::AxisHomeSample samples[] = {
        {true, 4, 100, 0},
        {false, 8, 93, 2},
    };

    const auto stats = MotionQualificationMath::summarizeAxisHomeSamples(samples, 2, 100);

    UNSIGNED_LONGS_EQUAL(2u, stats.moveTimeoutCount);
    UNSIGNED_LONGS_EQUAL(1u, stats.homeTimeoutCount);
    CHECK_FALSE(MotionQualificationMath::axisHomeStatsPass(stats, 2));
}

TEST(MotionQualificationMath, PatternReturnTracksWorstAxisErrorAndTimeouts)
{
    MotionQualificationMath::PatternReturnStats stats{};
    MotionQualificationMath::recordPatternReturn(stats, 100, 100, 102, 96, true, true, false);
    MotionQualificationMath::recordPatternReturn(stats, 100, 100, 99, 101, false, false, true);

    UNSIGNED_LONGS_EQUAL(2u, stats.xReturnErrorMaxSteps);
    UNSIGNED_LONGS_EQUAL(4u, stats.yReturnErrorMaxSteps);
    UNSIGNED_LONGS_EQUAL(4u, stats.returnErrorMaxSteps);
    UNSIGNED_LONGS_EQUAL(1u, stats.moveTimeoutCount);
    UNSIGNED_LONGS_EQUAL(1u, stats.homeTimeoutCount);
    UNSIGNED_LONGS_EQUAL(1u, stats.boundViolationCount);
    CHECK_FALSE(MotionQualificationMath::patternReturnStatsPass(stats));
}
