#include "CppUTest/TestHarness.h"
#include "ValvePulseQualificationMath.h"

TEST_GROUP(ValvePulseQualificationMath)
{
};

namespace {

PressureTraceEvent eventAt(uint16_t dtMs, PressureTraceEventType type, uint16_t value0 = 0, uint16_t value1 = 0) {
    PressureTraceEvent ev{};
    ev.dtMs = dtMs;
    ev.type = static_cast<uint8_t>(type);
    ev.value0 = value0;
    ev.value1 = value1;
    return ev;
}

}  // namespace

TEST(ValvePulseQualificationMath, EmptyTraceProducesZeroSummary) {
    auto summary = ValvePulseQualificationMath::summarizePulseDrops(nullptr, 0, nullptr, 0, 50);

    UNSIGNED_LONGS_EQUAL(0u, summary.pulseCount);
    UNSIGNED_LONGS_EQUAL(0u, summary.meanDropRaw);
    UNSIGNED_LONGS_EQUAL(0u, summary.maxDeadlineSlipMs);
}

TEST(ValvePulseQualificationMath, PairsPulseStartAndEndPressuresIntoDrops) {
    PressureTraceEvent events[] = {
        eventAt(10, PressureTraceEventType::PulseStart, 1300, 2500),
        eventAt(12, PressureTraceEventType::PulseEnd, 1300, 2488),
        eventAt(60, PressureTraceEventType::PulseStart, 1300, 2501),
        eventAt(62, PressureTraceEventType::PulseEnd, 1300, 2487),
        eventAt(110, PressureTraceEventType::PulseStart, 1300, 2500),
        eventAt(112, PressureTraceEventType::PulseEnd, 1300, 2483),
    };

    auto summary = ValvePulseQualificationMath::summarizePulseDrops(nullptr, 0, events, 6, 50);

    UNSIGNED_LONGS_EQUAL(3u, summary.pulseCount);
    UNSIGNED_LONGS_EQUAL(14u, summary.meanDropRaw);
    UNSIGNED_LONGS_EQUAL(12u, summary.minDropRaw);
    UNSIGNED_LONGS_EQUAL(17u, summary.maxDropRaw);
    LONGS_EQUAL(2, summary.dropSlopeRawPerPulse);
    UNSIGNED_LONGS_EQUAL(0u, summary.maxDeadlineSlipMs);
}

TEST(ValvePulseQualificationMath, UsesPressureChangeMagnitudeWhenPulsePressureRises) {
    PressureTraceEvent events[] = {
        eventAt(10, PressureTraceEventType::PulseStart, 1300, 2500),
        eventAt(12, PressureTraceEventType::PulseEnd, 1300, 2512),
    };

    auto summary = ValvePulseQualificationMath::summarizePulseDrops(nullptr, 0, events, 2, 50);

    UNSIGNED_LONGS_EQUAL(1u, summary.pulseCount);
    UNSIGNED_LONGS_EQUAL(12u, summary.meanDropRaw);
    UNSIGNED_LONGS_EQUAL(12u, summary.minDropRaw);
    UNSIGNED_LONGS_EQUAL(12u, summary.maxDropRaw);
}

TEST(ValvePulseQualificationMath, ComputesDeadlineSlipAndRecoveryWindow) {
    PressureTraceEvent events[] = {
        eventAt(10, PressureTraceEventType::PulseStart, 1300, 2500),
        eventAt(12, PressureTraceEventType::PulseEnd, 1300, 2488),
        eventAt(15, PressureTraceEventType::ReadyExit),
        eventAt(42, PressureTraceEventType::ReadyEnter),
        eventAt(69, PressureTraceEventType::PulseStart, 1300, 2502),
        eventAt(71, PressureTraceEventType::PulseEnd, 1300, 2488),
        eventAt(74, PressureTraceEventType::ReadyExit),
        eventAt(121, PressureTraceEventType::ReadyEnter),
    };

    auto summary = ValvePulseQualificationMath::summarizePulseDrops(nullptr, 0, events, 8, 50);

    UNSIGNED_LONGS_EQUAL(2u, summary.pulseCount);
    UNSIGNED_LONGS_EQUAL(9u, summary.maxDeadlineSlipMs);
    UNSIGNED_LONGS_EQUAL(50u, summary.maxRecoveryMs);
}

TEST(ValvePulseQualificationMath, ReportsCvAndOutlierCountForUnevenDrops) {
    PressureTraceEvent events[] = {
        eventAt(10, PressureTraceEventType::PulseStart, 1300, 2500),
        eventAt(12, PressureTraceEventType::PulseEnd, 1300, 2490),
        eventAt(60, PressureTraceEventType::PulseStart, 1300, 2500),
        eventAt(62, PressureTraceEventType::PulseEnd, 1300, 2490),
        eventAt(110, PressureTraceEventType::PulseStart, 1300, 2500),
        eventAt(112, PressureTraceEventType::PulseEnd, 1300, 2450),
    };

    auto summary = ValvePulseQualificationMath::summarizePulseDrops(nullptr, 0, events, 6, 50);

    UNSIGNED_LONGS_EQUAL(3u, summary.pulseCount);
    CHECK(summary.dropCvPct > 50u);
    UNSIGNED_LONGS_EQUAL(1u, summary.outlierCount);
}
