#include "CppUTest/TestHarness.h"
#include "PressureTraceRecorder.h"

TEST_GROUP(PressureTraceMath)
{
    void setup() {
        PressureTraceRecorder::instance().reset();
        PressureTraceConfig cfg{};
        PressureTraceRecorder::instance().configure(cfg);
    }

    void teardown() {
        PressureTraceRecorder::instance().reset();
    }

    PressureTraceSample sample(uint16_t dtMs, uint16_t rawPressure = 2000u) {
        PressureTraceSample s{};
        s.dtMs = dtMs;
        s.rawPressure = rawPressure;
        return s;
    }

    void start(PressureTraceConfig cfg) {
        PressureTraceRecorder::instance().configure(cfg);
        PressureTraceRecorder::instance().arm();
        PressureTraceRecorder::instance().start(100u);
    }
};

TEST(PressureTraceMath, TraceRecordLayoutsRemainStable) {
    UNSIGNED_LONGS_EQUAL(20u, sizeof(PressureTraceSample));
    UNSIGNED_LONGS_EQUAL(8u, sizeof(PressureTraceEvent));
}

TEST(PressureTraceMath, GripperMetadataEventTypesRemainCompact) {
    UNSIGNED_LONGS_EQUAL(15u, static_cast<uint8_t>(PressureTraceEventType::GripperTiming));
    UNSIGNED_LONGS_EQUAL(16u, static_cast<uint8_t>(PressureTraceEventType::GripperRefreshCount));
    const uint16_t gripperEventsPerTrace =
        1u + 2u + 2u + 1u; // trace start, metadata, pulse start/end, trace stop
    CHECK_TRUE(gripperEventsPerTrace < PressureTraceRecorder::kMaxEvents);
    UNSIGNED_LONGS_EQUAL(16u, 2u * sizeof(PressureTraceEvent));
}

TEST(PressureTraceMath, DefaultStrideRecordsEveryAcceptedSample) {
    PressureTraceConfig cfg{};
    cfg.channel = PressureTraceChannel::Print;
    start(cfg);

    auto& recorder = PressureTraceRecorder::instance();
    recorder.recordSample(PressureTraceChannel::Print, sample(0u));
    recorder.recordSample(PressureTraceChannel::Print, sample(5u));
    recorder.recordSample(PressureTraceChannel::Print, sample(10u));

    UNSIGNED_LONGS_EQUAL(3u, recorder.sampleCount());
    UNSIGNED_LONGS_EQUAL(0u, recorder.samples()[0].dtMs);
    UNSIGNED_LONGS_EQUAL(5u, recorder.samples()[1].dtMs);
    UNSIGNED_LONGS_EQUAL(10u, recorder.samples()[2].dtMs);
}

TEST(PressureTraceMath, StrideFiveRecordsFirstAndEveryFifthAcceptedSample) {
    PressureTraceConfig cfg{};
    cfg.channel = PressureTraceChannel::Print;
    cfg.sampleStride = 5u;
    start(cfg);

    auto& recorder = PressureTraceRecorder::instance();
    for (uint16_t idx = 0u; idx < 12u; ++idx) {
        recorder.recordSample(PressureTraceChannel::Print, sample(idx));
    }

    UNSIGNED_LONGS_EQUAL(3u, recorder.sampleCount());
    UNSIGNED_LONGS_EQUAL(0u, recorder.samples()[0].dtMs);
    UNSIGNED_LONGS_EQUAL(5u, recorder.samples()[1].dtMs);
    UNSIGNED_LONGS_EQUAL(10u, recorder.samples()[2].dtMs);
}

TEST(PressureTraceMath, ChannelFilteringDoesNotAdvanceStride) {
    PressureTraceConfig cfg{};
    cfg.channel = PressureTraceChannel::Print;
    cfg.sampleStride = 5u;
    start(cfg);

    auto& recorder = PressureTraceRecorder::instance();
    for (uint16_t idx = 0u; idx < 4u; ++idx) {
        recorder.recordSample(PressureTraceChannel::Refuel, sample(idx));
    }
    recorder.recordSample(PressureTraceChannel::Print, sample(10u));

    UNSIGNED_LONGS_EQUAL(1u, recorder.sampleCount());
    UNSIGNED_LONGS_EQUAL(10u, recorder.samples()[0].dtMs);
}

TEST(PressureTraceMath, ResetClearsStrideState) {
    PressureTraceConfig cfg{};
    cfg.channel = PressureTraceChannel::Print;
    cfg.sampleStride = 5u;
    start(cfg);

    auto& recorder = PressureTraceRecorder::instance();
    recorder.recordSample(PressureTraceChannel::Print, sample(0u));
    recorder.recordSample(PressureTraceChannel::Print, sample(1u));
    recorder.reset();

    start(cfg);
    recorder.recordSample(PressureTraceChannel::Print, sample(20u));

    UNSIGNED_LONGS_EQUAL(1u, recorder.sampleCount());
    UNSIGNED_LONGS_EQUAL(20u, recorder.samples()[0].dtMs);
}

TEST(PressureTraceMath, ConfigureNormalizesZeroStrideAndYield) {
    PressureTraceConfig cfg{};
    cfg.sampleStride = 0u;
    cfg.exportYieldMs = 0u;
    PressureTraceRecorder::instance().configure(cfg);

    const auto& normalized = PressureTraceRecorder::instance().config();
    UNSIGNED_LONGS_EQUAL(1u, normalized.sampleStride);
    UNSIGNED_LONGS_EQUAL(1u, normalized.exportYieldMs);
}
