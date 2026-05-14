#include "CppUTest/TestHarness.h"
#include "GripperSealQualificationMath.h"

TEST_GROUP(GripperSealQualificationMath)
{
};

TEST(GripperSealQualificationMath, ComputesDropAndSlope) {
    const auto summary = GripperSealQualificationMath::summarizeDecay(1800, 1740, 30000, 0, 100);

    UNSIGNED_LONGS_EQUAL(60u, summary.dropRaw);
    LONGS_EQUAL(-120, summary.slopeRawPerMin);
    UNSIGNED_LONGS_EQUAL(30000u, summary.sealPassDurationMs);
}

TEST(GripperSealQualificationMath, RecordsThresholdCrossingAsPassDuration) {
    const auto summary = GripperSealQualificationMath::summarizeDecay(1800, 1660, 300000, 45000, 100);

    UNSIGNED_LONGS_EQUAL(140u, summary.dropRaw);
    UNSIGNED_LONGS_EQUAL(45000u, summary.timeToThresholdMs);
    UNSIGNED_LONGS_EQUAL(45000u, summary.sealPassDurationMs);
}

TEST(GripperSealQualificationMath, FailsPassDurationWhenDropExceedsThresholdWithoutCrossTime) {
    const auto summary = GripperSealQualificationMath::summarizeDecay(1800, 1660, 300000, 0, 100);

    UNSIGNED_LONGS_EQUAL(0u, summary.timeToThresholdMs);
    UNSIGNED_LONGS_EQUAL(0u, summary.sealPassDurationMs);
}

TEST(GripperSealQualificationMath, ComputesRepeatSpanAndMinimum) {
    const uint32_t values[] = {40u, 55u, 42u};

    UNSIGNED_LONGS_EQUAL(15u, GripperSealQualificationMath::spanRaw(values, 3));
    UNSIGNED_LONGS_EQUAL(40u, GripperSealQualificationMath::minValue(values, 3));
    UNSIGNED_LONGS_EQUAL(55u, GripperSealQualificationMath::maxValue(values, 3));
}

TEST(GripperSealQualificationMath, EmptyAggregatesAreZero) {
    UNSIGNED_LONGS_EQUAL(0u, GripperSealQualificationMath::spanRaw(nullptr, 0));
    UNSIGNED_LONGS_EQUAL(0u, GripperSealQualificationMath::minValue(nullptr, 0));
    UNSIGNED_LONGS_EQUAL(0u, GripperSealQualificationMath::maxValue(nullptr, 0));
}

TEST(GripperSealQualificationMath, ComputesWorstChannelDrop) {
    UNSIGNED_LONGS_EQUAL(35u, GripperSealQualificationMath::worstDropRaw(2500, 2475, true, 2510, 2475));
    UNSIGNED_LONGS_EQUAL(25u, GripperSealQualificationMath::worstDropRaw(2500, 2475, false, 2510, 2400));
}

TEST(GripperSealQualificationMath, SummarizesBurstDropsAcrossFullSealWindow) {
    const uint32_t drops[] = {15u, 25u, 20u, 30u, 22u, 28u};

    const auto summary = GripperSealQualificationMath::summarizeBurstDrops(drops, 6, 10000, 100);

    UNSIGNED_LONGS_EQUAL(30u, summary.maxDropRaw);
    UNSIGNED_LONGS_EQUAL(15u, summary.spanRaw);
    UNSIGNED_LONGS_EQUAL(60000u, summary.sealPassDurationMs);
}

TEST(GripperSealQualificationMath, BurstSummaryStopsSealDurationAtFirstThresholdCrossing) {
    const uint32_t drops[] = {15u, 25u, 120u, 30u};

    const auto summary = GripperSealQualificationMath::summarizeBurstDrops(drops, 4, 10000, 100);

    UNSIGNED_LONGS_EQUAL(120u, summary.maxDropRaw);
    UNSIGNED_LONGS_EQUAL(105u, summary.spanRaw);
    UNSIGNED_LONGS_EQUAL(20000u, summary.sealPassDurationMs);
}
