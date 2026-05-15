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

TEST(MotionQualificationMath, XySafetyRejectsBoundsAndCableGuardViolations)
{
    const MotionQualificationMath::XySafetyEnvelope envelope{};

    CHECK_TRUE(MotionQualificationMath::xyPointInBounds({0, 0}, envelope));
    CHECK_TRUE(MotionQualificationMath::xyPointInBounds({45000, 35000}, envelope));
    CHECK_FALSE(MotionQualificationMath::xyPointInBounds({45001, 0}, envelope));
    CHECK_FALSE(MotionQualificationMath::xyPointInBounds({0, 35001}, envelope));
    CHECK_FALSE(MotionQualificationMath::xyPointInBounds({-1, 0}, envelope));
    CHECK_FALSE(MotionQualificationMath::xyPointInBounds({0, -1}, envelope));

    CHECK_TRUE(MotionQualificationMath::xyPointPassesCableGuard({1000, 0}, envelope));
    CHECK_TRUE(MotionQualificationMath::xyPointPassesCableGuard({1001, 500}, envelope));
    CHECK_FALSE(MotionQualificationMath::xyPointPassesCableGuard({1001, 499}, envelope));
    CHECK_FALSE(MotionQualificationMath::xyPointIsSafe({1001, 499}, envelope));
}

TEST(MotionQualificationMath, XyMotionStatsTrackDriftReturnAndSafetyFailures)
{
    MotionQualificationMath::XyMotionStats stats{};
    const MotionQualificationMath::AxisHomeSample xHome{true, -7, 102, 1};
    const MotionQualificationMath::AxisHomeSample yHome{true, 4, 98, 2};

    MotionQualificationMath::recordXyMotionSample(stats,
                                                  100,
                                                  100,
                                                  103,
                                                  96,
                                                  -5,
                                                  1,
                                                  xHome,
                                                  yHome,
                                                  false,
                                                  true,
                                                  true);

    UNSIGNED_LONGS_EQUAL(3u, stats.xReturnErrorMaxSteps);
    UNSIGNED_LONGS_EQUAL(4u, stats.yReturnErrorMaxSteps);
    UNSIGNED_LONGS_EQUAL(4u, stats.returnErrorMaxSteps);
    UNSIGNED_LONGS_EQUAL(2u, stats.xDriftMaxSteps);
    UNSIGNED_LONGS_EQUAL(3u, stats.yDriftMaxSteps);
    UNSIGNED_LONGS_EQUAL(4u, stats.moveTimeoutCount);
    UNSIGNED_LONGS_EQUAL(0u, stats.homeTimeoutCount);
    UNSIGNED_LONGS_EQUAL(1u, stats.guardViolationCount);
    UNSIGNED_LONGS_EQUAL(1u, stats.boundViolationCount);
    CHECK_FALSE(MotionQualificationMath::xyMotionStatsPass(stats));
}

TEST(MotionQualificationMath, XyMotionStatsPassOnlyWhenSafetyCountersAreZero)
{
    MotionQualificationMath::XyMotionStats stats{};

    CHECK_TRUE(MotionQualificationMath::xyMotionStatsPass(stats));

    stats.moveTimeoutCount = 1u;
    CHECK_FALSE(MotionQualificationMath::xyMotionStatsPass(stats));

    stats.moveTimeoutCount = 0u;
    stats.homeTimeoutCount = 1u;
    CHECK_FALSE(MotionQualificationMath::xyMotionStatsPass(stats));

    stats.homeTimeoutCount = 0u;
    stats.guardViolationCount = 1u;
    CHECK_FALSE(MotionQualificationMath::xyMotionStatsPass(stats));

    stats.guardViolationCount = 0u;
    stats.boundViolationCount = 1u;
    CHECK_FALSE(MotionQualificationMath::xyMotionStatsPass(stats));
}

TEST(MotionQualificationMath, ZSafetyRejectsOutOfEnvelopePositions)
{
    const MotionQualificationMath::ZSafetyEnvelope envelope{};

    CHECK_TRUE(MotionQualificationMath::zPositionInBounds(0, envelope));
    CHECK_TRUE(MotionQualificationMath::zPositionInBounds(40000, envelope));
    CHECK_FALSE(MotionQualificationMath::zPositionInBounds(-1, envelope));
    CHECK_FALSE(MotionQualificationMath::zPositionInBounds(40001, envelope));
}

TEST(MotionQualificationMath, EndpointInterpolationHitsPlateRasterCorners)
{
    LONGS_EQUAL(43000, MotionQualificationMath::interpolateEndpoint(43000, 33000, 0, 16));
    LONGS_EQUAL(33000, MotionQualificationMath::interpolateEndpoint(43000, 33000, 15, 16));
    LONGS_EQUAL(13000, MotionQualificationMath::interpolateEndpoint(13000, 30000, 0, 24));
    LONGS_EQUAL(30000, MotionQualificationMath::interpolateEndpoint(13000, 30000, 23, 24));

    const int32_t firstInteriorY = MotionQualificationMath::interpolateEndpoint(13000, 30000, 1, 24);
    const int32_t nextInteriorY = MotionQualificationMath::interpolateEndpoint(13000, 30000, 2, 24);
    CHECK_TRUE(firstInteriorY > 13000);
    CHECK_TRUE(nextInteriorY > firstInteriorY);
}
