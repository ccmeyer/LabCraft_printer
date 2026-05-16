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

PressureTraceSample sampleAt(uint16_t dtMs, uint16_t raw) {
    PressureTraceSample sample{};
    sample.dtMs = dtMs;
    sample.rawPressure = raw;
    sample.controlPressure = raw;
    sample.avgPressure = raw;
    sample.target = raw;
    return sample;
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

TEST(ValvePulseQualificationMath, ThreeWidthLinearityReportsMonotonicProportionalResponses) {
    auto summary = ValvePulseQualificationMath::summarizeThreeWidthLinearity(30, 60, 90);

    UNSIGNED_LONGS_EQUAL(1u, summary.monotonic);
    UNSIGNED_LONGS_EQUAL(60u, summary.gainRaw);
    UNSIGNED_LONGS_EQUAL(0u, summary.midpointLinearityErrorPct);
}

TEST(ValvePulseQualificationMath, ThreeWidthLinearityReportsNonMonotonicResponses) {
    auto summary = ValvePulseQualificationMath::summarizeThreeWidthLinearity(30, 20, 90);

    UNSIGNED_LONGS_EQUAL(0u, summary.monotonic);
    UNSIGNED_LONGS_EQUAL(60u, summary.gainRaw);
    CHECK(summary.midpointLinearityErrorPct > 0u);
}

TEST(ValvePulseQualificationMath, ResponseValueSummaryReportsMeanCvSpanAndOutliers) {
    uint32_t responses[] = {30, 31, 29, 80};

    auto summary = ValvePulseQualificationMath::summarizeResponseValues(
        responses,
        sizeof(responses) / sizeof(responses[0]));

    UNSIGNED_LONGS_EQUAL(4u, summary.count);
    UNSIGNED_LONGS_EQUAL(43u, summary.meanRaw);
    UNSIGNED_LONGS_EQUAL(29u, summary.minRaw);
    UNSIGNED_LONGS_EQUAL(80u, summary.maxRaw);
    UNSIGNED_LONGS_EQUAL(51u, summary.spanRaw);
    CHECK(summary.cvPct > 40u);
    UNSIGNED_LONGS_EQUAL(1u, summary.outlierCount);
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

TEST(ValvePulseQualificationMath, WindowedResponseUsesSamplesAfterPulseStart) {
    PressureTraceSample samples[] = {
        sampleAt(8, 2500),
        sampleAt(10, 2500),
        sampleAt(12, 2499),
        sampleAt(16, 2470),
        sampleAt(24, 2488),
        sampleAt(58, 2502),
        sampleAt(60, 2502),
        sampleAt(63, 2495),
        sampleAt(70, 2460),
        sampleAt(78, 2490),
    };
    PressureTraceEvent events[] = {
        eventAt(10, PressureTraceEventType::PulseStart, 1500, 2500),
        eventAt(11, PressureTraceEventType::PulseEnd, 1500, 2500),
        eventAt(60, PressureTraceEventType::PulseStart, 1500, 2502),
        eventAt(61, PressureTraceEventType::PulseEnd, 1500, 2502),
    };

    auto summary = ValvePulseQualificationMath::summarizeWindowedPulseResponses(
        samples,
        sizeof(samples) / sizeof(samples[0]),
        events,
        sizeof(events) / sizeof(events[0]),
        5,
        20);

    UNSIGNED_LONGS_EQUAL(2u, summary.pulseCount);
    UNSIGNED_LONGS_EQUAL(36u, summary.meanResponseRaw);
    UNSIGNED_LONGS_EQUAL(30u, summary.minResponseRaw);
    UNSIGNED_LONGS_EQUAL(42u, summary.maxResponseRaw);
    UNSIGNED_LONGS_EQUAL(0u, summary.rejectCount);
}

TEST(ValvePulseQualificationMath, WindowedResponseRejectsPulseWithoutSamples) {
    PressureTraceSample samples[] = {
        sampleAt(5, 2500),
        sampleAt(90, 2500),
    };
    PressureTraceEvent events[] = {
        eventAt(20, PressureTraceEventType::PulseStart, 3000, 2500),
    };

    auto summary = ValvePulseQualificationMath::summarizeWindowedPulseResponses(
        samples,
        sizeof(samples) / sizeof(samples[0]),
        events,
        sizeof(events) / sizeof(events[0]),
        5,
        20);

    UNSIGNED_LONGS_EQUAL(0u, summary.pulseCount);
    UNSIGNED_LONGS_EQUAL(1u, summary.rejectCount);
    UNSIGNED_LONGS_EQUAL(0u, summary.meanResponseRaw);
}
