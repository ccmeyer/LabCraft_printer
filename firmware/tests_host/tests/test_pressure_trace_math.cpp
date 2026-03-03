#include "CppUTest/TestHarness.h"
#include "PressureTraceRecorder.h"

TEST_GROUP(PressureTraceMath)
{
};

TEST(PressureTraceMath, TraceRecordLayoutsRemainStable) {
    UNSIGNED_LONGS_EQUAL(20u, sizeof(PressureTraceSample));
    UNSIGNED_LONGS_EQUAL(8u, sizeof(PressureTraceEvent));
}
