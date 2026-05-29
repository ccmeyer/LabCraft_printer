#include "CppUTest/TestHarness.h"
#include "CommCodec.h"

#include <cstring>

static CommCodec::FeedResult feedAll(CommCodec::RxParser& parser, const uint8_t* data, size_t len, uint8_t& outPayloadLen) {
    CommCodec::FeedResult last = CommCodec::FeedResult::None;
    outPayloadLen = 0;
    for (size_t i = 0; i < len; ++i) {
        last = CommCodec::feedRxByte(parser, data[i], outPayloadLen);
    }
    return last;
}

static void assertAckRoundtrip(uint8_t ackCmd, uint8_t seq8, uint32_t seq32) {
    uint8_t payload[8] = {0};
    const uint8_t payloadLen = CommCodec::buildAckPayload(ackCmd, seq8, seq32, true, payload, sizeof(payload));
    UNSIGNED_LONGS_EQUAL(8u, payloadLen);

    uint8_t frame[16] = {0};
    const size_t frameLen = CommCodec::encodeFrame(payload, payloadLen, frame, sizeof(frame));
    UNSIGNED_LONGS_EQUAL(12u, frameLen);

    CommCodec::RxParser parser{};
    uint8_t parsedLen = 0;
    const auto result = feedAll(parser, frame, frameLen, parsedLen);
    LONGS_EQUAL((int)CommCodec::FeedResult::FrameReady, (int)result);
    const auto decoded = CommCodec::decodeCommand(parser.rxBuf, parsedLen);
    UNSIGNED_LONGS_EQUAL(ackCmd, decoded.cmd);
    UNSIGNED_LONGS_EQUAL(seq8, decoded.seq8);
    CHECK_TRUE(decoded.hasSeq32);
    UNSIGNED_LONGS_EQUAL(seq32, decoded.seq32);
}

TEST_GROUP(CommCodec)
{
};

TEST(CommCodec, Crc16MatchesKnownVector123456789) {
    static const uint8_t msg[] = {'1','2','3','4','5','6','7','8','9'};
    const uint16_t crc = CommCodec::crc16(msg, sizeof(msg));
    UNSIGNED_LONGS_EQUAL(0x4B37u, crc);
}

TEST(CommCodec, AckEncodeWithoutSeq32MatchesGoldenBytes) {
    uint8_t payload[8] = {0};
    const uint8_t payloadLen = CommCodec::buildAckPayload(0xF3, 0x01, 0, false, payload, sizeof(payload));
    UNSIGNED_LONGS_EQUAL(2u, payloadLen);

    uint8_t frame[16] = {0};
    const size_t frameLen = CommCodec::encodeFrame(payload, payloadLen, frame, sizeof(frame));
    UNSIGNED_LONGS_EQUAL(6u, frameLen);

    static const uint8_t expected[] = {0xAA, 0x02, 0xF3, 0x01, 0x84, 0x80};
    MEMCMP_EQUAL(expected, frame, sizeof(expected));
}

TEST(CommCodec, AckEncodeWithSeq32MatchesGoldenBytes) {
    uint8_t payload[8] = {0};
    const uint8_t payloadLen = CommCodec::buildAckPayload(0xF4, 0x22, 0x12345678u, true, payload, sizeof(payload));
    UNSIGNED_LONGS_EQUAL(8u, payloadLen);

    uint8_t frame[16] = {0};
    const size_t frameLen = CommCodec::encodeFrame(payload, payloadLen, frame, sizeof(frame));
    UNSIGNED_LONGS_EQUAL(12u, frameLen);

    static const uint8_t expected[] = {0xAA, 0x08, 0xF4, 0x22, 0x10, 0x04, 0x78, 0x56, 0x34, 0x12, 0xD1, 0x93};
    MEMCMP_EQUAL(expected, frame, sizeof(expected));
}

TEST(CommCodec, ValidHelloFrameParses) {
    static const uint8_t frame[] = {0xAA, 0x02, 0xF3, 0x01, 0x84, 0x80};
    CommCodec::RxParser parser{};
    uint8_t payloadLen = 0;

    const auto result = feedAll(parser, frame, sizeof(frame), payloadLen);
    LONGS_EQUAL((int)CommCodec::FeedResult::FrameReady, (int)result);
    UNSIGNED_LONGS_EQUAL(2u, payloadLen);

    const auto decoded = CommCodec::decodeCommand(parser.rxBuf, payloadLen);
    UNSIGNED_LONGS_EQUAL(0xF3u, decoded.cmd);
    UNSIGNED_LONGS_EQUAL(0x01u, decoded.seq8);
}

TEST(CommCodec, ValidMoveXWithTlvsAndSeq32Parses) {
    static const uint8_t payload[] = {
        0x02, 0x05,
        CommCodec::TAG_P1, 0x01, 0x01,
        CommCodec::TAG_P2, 0x04, 0x34, 0x12, 0x00, 0x00,
        CommCodec::TAG_P3, 0x02, 0x88, 0x13,
        CommCodec::TAG_SEQ32, 0x04, 0x78, 0x56, 0x34, 0x12
    };
    uint8_t frame[32] = {0};
    const size_t frameLen = CommCodec::encodeFrame(payload, sizeof(payload), frame, sizeof(frame));
    CHECK_TRUE(frameLen > 0);

    CommCodec::RxParser parser{};
    uint8_t payloadLen = 0;
    const auto result = feedAll(parser, frame, frameLen, payloadLen);
    LONGS_EQUAL((int)CommCodec::FeedResult::FrameReady, (int)result);

    const auto decoded = CommCodec::decodeCommand(parser.rxBuf, payloadLen);
    UNSIGNED_LONGS_EQUAL(0x02u, decoded.cmd);
    UNSIGNED_LONGS_EQUAL(0x05u, decoded.seq8);
    UNSIGNED_LONGS_EQUAL(0x01u, decoded.p1);
    UNSIGNED_LONGS_EQUAL(1u, decoded.p1Len);
    UNSIGNED_LONGS_EQUAL(0x1234u, decoded.p2);
    UNSIGNED_LONGS_EQUAL(4u, decoded.p2Len);
    UNSIGNED_LONGS_EQUAL(0x1388u, decoded.p3);
    UNSIGNED_LONGS_EQUAL(2u, decoded.p3Len);
    UNSIGNED_LONGS_EQUAL(0x12345678u, decoded.seq32);
    CHECK_TRUE(decoded.hasSeq32);
}

TEST(CommCodec, CorruptCrcFrameIsRejected) {
    static const uint8_t payload[] = {0xF3, 0x01};
    uint8_t frame[16] = {0};
    const size_t frameLen = CommCodec::encodeFrame(payload, sizeof(payload), frame, sizeof(frame));
    CHECK_TRUE(frameLen > 0);
    frame[frameLen - 1] ^= 0xFF; // flip CRC high byte

    CommCodec::RxParser parser{};
    uint8_t payloadLen = 0;
    const auto result = feedAll(parser, frame, frameLen, payloadLen);
    LONGS_EQUAL((int)CommCodec::FeedResult::CrcMismatch, (int)result);
}

TEST(CommCodec, OversizeLenIsRejected) {
    static const uint8_t bytes[] = {0xAA, 0x3F}; // LEN=63, parser supports <=62 payload
    CommCodec::RxParser parser{};
    uint8_t payloadLen = 0;

    const auto result = feedAll(parser, bytes, sizeof(bytes), payloadLen);
    LONGS_EQUAL((int)CommCodec::FeedResult::LengthRejected, (int)result);
}

TEST(CommCodec, EncodeFrameZeroLenPayloadMatchesGolden) {
    static const uint8_t dummyPayload[] = {0x00};
    uint8_t frame[8] = {0};
    const size_t frameLen = CommCodec::encodeFrame(dummyPayload, 0, frame, sizeof(frame));
    UNSIGNED_LONGS_EQUAL(4u, frameLen);
    static const uint8_t expected[] = {0xAA, 0x00, 0xFF, 0xFF};
    MEMCMP_EQUAL(expected, frame, sizeof(expected));
}

TEST(CommCodec, EncodeFrameReturnsZeroWhenOutCapTooSmall) {
    static const uint8_t payload[] = {0xF3, 0x01};
    uint8_t frame[5] = {0}; // needs 6 bytes
    const size_t frameLen = CommCodec::encodeFrame(payload, sizeof(payload), frame, sizeof(frame));
    UNSIGNED_LONGS_EQUAL(0u, frameLen);
}

TEST(CommCodec, MaxPayloadLen62AcceptedByParser) {
    uint8_t payload[62] = {0};
    for (size_t i = 0; i < sizeof(payload); ++i) {
        payload[i] = static_cast<uint8_t>(i);
    }
    uint8_t frame[80] = {0};
    const size_t frameLen = CommCodec::encodeFrame(payload, sizeof(payload), frame, sizeof(frame));
    CHECK_TRUE(frameLen > 0);

    CommCodec::RxParser parser{};
    uint8_t parsedLen = 0;
    const auto result = feedAll(parser, frame, frameLen, parsedLen);
    LONGS_EQUAL((int)CommCodec::FeedResult::FrameReady, (int)result);
    UNSIGNED_LONGS_EQUAL(62u, parsedLen);
}

TEST(CommCodec, TruncatedTlvStopsParsingSafely) {
    static const uint8_t payload[] = {0x02, 0x09, CommCodec::TAG_P1, 0x04, 0xAA, 0xBB};
    uint8_t frame[32] = {0};
    const size_t frameLen = CommCodec::encodeFrame(payload, sizeof(payload), frame, sizeof(frame));
    CHECK_TRUE(frameLen > 0);

    CommCodec::RxParser parser{};
    uint8_t payloadLen = 0;
    const auto result = feedAll(parser, frame, frameLen, payloadLen);
    LONGS_EQUAL((int)CommCodec::FeedResult::FrameReady, (int)result);

    const auto decoded = CommCodec::decodeCommand(parser.rxBuf, payloadLen);
    UNSIGNED_LONGS_EQUAL(0u, decoded.p1Len);
    UNSIGNED_LONGS_EQUAL(0u, decoded.p2Len);
    UNSIGNED_LONGS_EQUAL(0u, decoded.p3Len);
    CHECK_FALSE(decoded.hasSeq32);
}

TEST(CommCodec, DecodeDuplicateP1UsesLastWriteWins) {
    static const uint8_t payload[] = {
        0xFA, 0x10,
        CommCodec::TAG_P1, 0x01, 0x11,
        CommCodec::TAG_P1, 0x01, 0x22
    };
    uint8_t frame[24] = {0};
    const size_t frameLen = CommCodec::encodeFrame(payload, sizeof(payload), frame, sizeof(frame));
    CHECK_TRUE(frameLen > 0);

    CommCodec::RxParser parser{};
    uint8_t parsedLen = 0;
    LONGS_EQUAL((int)CommCodec::FeedResult::FrameReady, (int)feedAll(parser, frame, frameLen, parsedLen));

    const auto decoded = CommCodec::decodeCommand(parser.rxBuf, parsedLen);
    UNSIGNED_LONGS_EQUAL(0x22u, decoded.p1);
    UNSIGNED_LONGS_EQUAL(1u, decoded.p1Len);
}

TEST(CommCodec, DecodeUnknownTagIgnoredAndKnownTagsPreserved) {
    static const uint8_t payload[] = {
        0xFA, 0x10,
        CommCodec::TAG_P1, 0x01, 0x11,
        0x99, 0x02, 0xAA, 0xBB,
        CommCodec::TAG_P2, 0x02, 0x34, 0x12
    };
    uint8_t frame[32] = {0};
    const size_t frameLen = CommCodec::encodeFrame(payload, sizeof(payload), frame, sizeof(frame));
    CHECK_TRUE(frameLen > 0);

    CommCodec::RxParser parser{};
    uint8_t parsedLen = 0;
    LONGS_EQUAL((int)CommCodec::FeedResult::FrameReady, (int)feedAll(parser, frame, frameLen, parsedLen));

    const auto decoded = CommCodec::decodeCommand(parser.rxBuf, parsedLen);
    UNSIGNED_LONGS_EQUAL(0x11u, decoded.p1);
    UNSIGNED_LONGS_EQUAL(1u, decoded.p1Len);
    UNSIGNED_LONGS_EQUAL(0x1234u, decoded.p2);
    UNSIGNED_LONGS_EQUAL(2u, decoded.p2Len);
}

TEST(CommCodec, DecodeSeq32WrongLenDoesNotSetHasSeq32) {
    static const uint8_t payload[] = {
        0xFA, 0x10,
        CommCodec::TAG_SEQ32, 0x02, 0xAA, 0xBB
    };
    uint8_t frame[24] = {0};
    const size_t frameLen = CommCodec::encodeFrame(payload, sizeof(payload), frame, sizeof(frame));
    CHECK_TRUE(frameLen > 0);

    CommCodec::RxParser parser{};
    uint8_t parsedLen = 0;
    LONGS_EQUAL((int)CommCodec::FeedResult::FrameReady, (int)feedAll(parser, frame, frameLen, parsedLen));

    const auto decoded = CommCodec::decodeCommand(parser.rxBuf, parsedLen);
    CHECK_FALSE(decoded.hasSeq32);
}

TEST(CommCodec, HelloAckWithSeq32Roundtrips) {
    assertAckRoundtrip(0xF4, 0x10, 0x12345678u);
}

TEST(CommCodec, ByeAckWithSeq32Roundtrips) {
    assertAckRoundtrip(0xF6, 0x10, 0x12345678u);
}

TEST(CommCodec, ByeDoneWithSeq32Roundtrips) {
    assertAckRoundtrip(0xF8, 0x10, 0x12345678u);
}

TEST(CommCodec, ClearAckWithSeq32Roundtrips) {
    assertAckRoundtrip(0xF7, 0x10, 0x12345678u);
}

TEST(CommCodec, QueueAckWithResultExpectedAndCapabilitiesMatchesGoldenBytes) {
    uint8_t payload[32] = {0};
    const uint8_t payloadLen = CommCodec::buildAckPayload(
        0xFE,
        0x05,
        0x00000009u,
        true,
        payload,
        sizeof(payload),
        true,
        0x03,
        true,
        0x00000007u,
        true,
        0x0000000Fu
    );
    UNSIGNED_LONGS_EQUAL(23u, payloadLen);

    static const uint8_t expected[] = {
        0xFE, 0x05,
        CommCodec::TAG_SEQ32, 0x04, 0x09, 0x00, 0x00, 0x00,
        CommCodec::TAG_ACK_RESULT, 0x01, 0x03,
        CommCodec::TAG_EXPECTED_SEQ32, 0x04, 0x07, 0x00, 0x00, 0x00,
        CommCodec::TAG_CAPABILITIES, 0x04, 0x0F, 0x00, 0x00, 0x00
    };
    MEMCMP_EQUAL(expected, payload, sizeof(expected));
}

TEST(CommCodec, PauseAfterSeq32CommandParsesP1AndSeq32) {
    static const uint8_t payload[] = {
        0xFF, 0x55,
        CommCodec::TAG_P1, 0x04, 0x2A, 0x00, 0x00, 0x00,
        CommCodec::TAG_SEQ32, 0x04, 0x78, 0x56, 0x34, 0x12
    };
    uint8_t frame[32] = {0};
    const size_t frameLen = CommCodec::encodeFrame(payload, sizeof(payload), frame, sizeof(frame));
    CHECK_TRUE(frameLen > 0);

    CommCodec::RxParser parser{};
    uint8_t parsedLen = 0;
    LONGS_EQUAL((int)CommCodec::FeedResult::FrameReady, (int)feedAll(parser, frame, frameLen, parsedLen));

    const auto decoded = CommCodec::decodeCommand(parser.rxBuf, parsedLen);
    UNSIGNED_LONGS_EQUAL(0xFFu, decoded.cmd);
    UNSIGNED_LONGS_EQUAL(0x2Au, decoded.p1);
    UNSIGNED_LONGS_EQUAL(4u, decoded.p1Len);
    UNSIGNED_LONGS_EQUAL(0x12345678u, decoded.seq32);
    CHECK_TRUE(decoded.hasSeq32);
}

TEST(CommCodec, SelftestResultCrashRecordMetricsFrameEncodesWithoutTruncation) {
    static const char name[] = "crash_record";
    static const char metrics[] = "pending=1;fault=hard;task=status;reset=iwdg;boot=42;fault_ct=3;wdg_ct=2;boot_stage=hello_ack";
    uint8_t payload[256] = {0};
    size_t idx = 0;
    payload[idx++] = 0xFB;
    payload[idx++] = 0x33;
    payload[idx++] = 0x30; payload[idx++] = 2; payload[idx++] = 0x11; payload[idx++] = 0x04;
    payload[idx++] = 0x31; payload[idx++] = sizeof(name) - 1; memcpy(&payload[idx], name, sizeof(name) - 1); idx += sizeof(name) - 1;
    payload[idx++] = 0x32; payload[idx++] = 1; payload[idx++] = 1;
    payload[idx++] = 0x33; payload[idx++] = sizeof(metrics) - 1; memcpy(&payload[idx], metrics, sizeof(metrics) - 1); idx += sizeof(metrics) - 1;
    payload[idx++] = 0x34; payload[idx++] = 4; payload[idx++] = 1; payload[idx++] = 0; payload[idx++] = 0; payload[idx++] = 0;
    payload[idx++] = 0x21; payload[idx++] = 4; payload[idx++] = 1; payload[idx++] = 0; payload[idx++] = 0; payload[idx++] = 0;

    uint8_t frame[320] = {0};
    const size_t frameLen = CommCodec::encodeFrame(payload, static_cast<uint8_t>(idx), frame, sizeof(frame));
    CHECK_TRUE(frameLen == idx + 4u);
    UNSIGNED_LONGS_EQUAL(0xAAu, frame[0]);
    UNSIGNED_LONGS_EQUAL(idx, frame[1]);
}

TEST(CommCodec, SelftestResultWatchdogMetricsFrameEncodesWithoutTruncation) {
    static const char name[] = "watchdog";
    static const char metrics[] = "enabled=1;timeout_ms=4000;req_n=5;live_n=5;late_task=none";
    uint8_t payload[256] = {0};
    size_t idx = 0;
    payload[idx++] = 0xFB;
    payload[idx++] = 0x33;
    payload[idx++] = 0x30; payload[idx++] = 2; payload[idx++] = 0x12; payload[idx++] = 0x04;
    payload[idx++] = 0x31; payload[idx++] = sizeof(name) - 1; memcpy(&payload[idx], name, sizeof(name) - 1); idx += sizeof(name) - 1;
    payload[idx++] = 0x32; payload[idx++] = 1; payload[idx++] = 1;
    payload[idx++] = 0x33; payload[idx++] = sizeof(metrics) - 1; memcpy(&payload[idx], metrics, sizeof(metrics) - 1); idx += sizeof(metrics) - 1;
    payload[idx++] = 0x34; payload[idx++] = 4; payload[idx++] = 2; payload[idx++] = 0; payload[idx++] = 0; payload[idx++] = 0;
    payload[idx++] = 0x21; payload[idx++] = 4; payload[idx++] = 1; payload[idx++] = 0; payload[idx++] = 0; payload[idx++] = 0;

    uint8_t frame[320] = {0};
    const size_t frameLen = CommCodec::encodeFrame(payload, static_cast<uint8_t>(idx), frame, sizeof(frame));
    CHECK_TRUE(frameLen == idx + 4u);
    UNSIGNED_LONGS_EQUAL(0xAAu, frame[0]);
    UNSIGNED_LONGS_EQUAL(idx, frame[1]);
}

TEST(CommCodec, SelftestStartWithFullProfileMirroredIntoP1ParsesProfileField) {
    static const uint8_t payload[] = {
        0xFA, 0x10,
        CommCodec::TAG_SEQ32, 0x04, 0x78, 0x56, 0x34, 0x12,
        CommCodec::TAG_P1, 0x01, 0x01,       // mirrored FULL profile for firmware decode
        CommCodec::TAG_PROFILE, 0x01, 0x01,
        CommCodec::TAG_RUN_ID, 0x04, 0x78, 0x56, 0x34, 0x12,
        CommCodec::TAG_TIMEOUT_MS, 0x04, 0x30, 0x75, 0x00, 0x00
    };
    uint8_t frame[48] = {0};
    const size_t frameLen = CommCodec::encodeFrame(payload, sizeof(payload), frame, sizeof(frame));
    CHECK_TRUE(frameLen > 0);

    CommCodec::RxParser parser{};
    uint8_t parsedLen = 0;
    LONGS_EQUAL((int)CommCodec::FeedResult::FrameReady, (int)feedAll(parser, frame, frameLen, parsedLen));

    const auto decoded = CommCodec::decodeCommand(parser.rxBuf, parsedLen);
    UNSIGNED_LONGS_EQUAL(0xFAu, decoded.cmd);
    UNSIGNED_LONGS_EQUAL(0x10u, decoded.seq8);
    UNSIGNED_LONGS_EQUAL(0x01u, decoded.p1);
    UNSIGNED_LONGS_EQUAL(1u, decoded.p1Len);
    CHECK_TRUE(decoded.hasSeq32);
    UNSIGNED_LONGS_EQUAL(0x12345678u, decoded.seq32);
    CHECK_TRUE(decoded.hasRunId);
    UNSIGNED_LONGS_EQUAL(0x12345678u, decoded.runId);
    CHECK_TRUE(decoded.hasTimeoutMs);
    UNSIGNED_LONGS_EQUAL(30000u, decoded.timeoutMs);
}

TEST(CommCodec, SelftestStartCustomPressureTraceTlvsParse) {
    static const uint8_t payload[] = {
        0xFA, 0x10,
        CommCodec::TAG_P1, 0x01, 0x01,
        CommCodec::TAG_P2, 0x01, 0x01,
        CommCodec::TAG_P3, 0x02, 0x3E, 0x08, // 2110
        CommCodec::TAG_TRACE_CHANNEL, 0x01, 0x00,
        CommCodec::TAG_TRACE_PRESSURE_MPSI, 0x02, 0xE2, 0x04, // 1250
        CommCodec::TAG_TRACE_PULSE_US, 0x02, 0xAA, 0x05, // 1450
        CommCodec::TAG_TRACE_PULSE_COUNT, 0x02, 0x14, 0x00,
        CommCodec::TAG_TRACE_FREQUENCY_HZ, 0x02, 0x14, 0x00
    };

    const auto decoded = CommCodec::decodeCommand(payload, sizeof(payload));

    UNSIGNED_LONGS_EQUAL(0xFAu, decoded.cmd);
    UNSIGNED_LONGS_EQUAL(2110u, decoded.p3);
    UNSIGNED_LONGS_EQUAL(2u, decoded.p3Len);
    UNSIGNED_LONGS_EQUAL(0u, decoded.traceChannel);
    UNSIGNED_LONGS_EQUAL(1u, decoded.traceChannelLen);
    UNSIGNED_LONGS_EQUAL(1250u, decoded.tracePressureMilliPsi);
    UNSIGNED_LONGS_EQUAL(2u, decoded.tracePressureMilliPsiLen);
    UNSIGNED_LONGS_EQUAL(1450u, decoded.tracePulseUs);
    UNSIGNED_LONGS_EQUAL(2u, decoded.tracePulseUsLen);
    UNSIGNED_LONGS_EQUAL(20u, decoded.tracePulseCount);
    UNSIGNED_LONGS_EQUAL(2u, decoded.tracePulseCountLen);
    UNSIGNED_LONGS_EQUAL(20u, decoded.traceFrequencyHz);
    UNSIGNED_LONGS_EQUAL(2u, decoded.traceFrequencyHzLen);
}

TEST(CommCodec, SelftestDoneSummaryTlvsDoNotBreakDecoding) {
    static const uint8_t payload[] = {
        0xFC, 0x10,
        CommCodec::TAG_SEQ32, 0x04, 0x78, 0x56, 0x34, 0x12,
        0x35, 0x02, 0x09, 0x00, // TAG_TOTAL
        0x36, 0x02, 0x09, 0x00, // TAG_PASSED
        0x37, 0x02, 0x00, 0x00, // TAG_FAILED
        0x38, 0x01, 0x00        // TAG_ABORTED
    };
    uint8_t frame[48] = {0};
    const size_t frameLen = CommCodec::encodeFrame(payload, sizeof(payload), frame, sizeof(frame));
    CHECK_TRUE(frameLen > 0);

    CommCodec::RxParser parser{};
    uint8_t parsedLen = 0;
    LONGS_EQUAL((int)CommCodec::FeedResult::FrameReady, (int)feedAll(parser, frame, frameLen, parsedLen));

    const auto decoded = CommCodec::decodeCommand(parser.rxBuf, parsedLen);
    UNSIGNED_LONGS_EQUAL(0xFCu, decoded.cmd);
    UNSIGNED_LONGS_EQUAL(0x10u, decoded.seq8);
    CHECK_TRUE(decoded.hasSeq32);
    UNSIGNED_LONGS_EQUAL(0x12345678u, decoded.seq32);
}

TEST(CommCodec, SelftestResultWithMilestone5SafeGateMetricsRoundtrips) {
    static const char name[] = "m5_gate";
    static const char metrics[] = "profile=SAFE";
    uint8_t payload[96] = {0};
    size_t idx = 0;
    payload[idx++] = 0xFB;
    payload[idx++] = 0x10;
    payload[idx++] = CommCodec::TAG_SEQ32;
    payload[idx++] = 0x04;
    payload[idx++] = 0x78;
    payload[idx++] = 0x56;
    payload[idx++] = 0x34;
    payload[idx++] = 0x12;
    payload[idx++] = 0x30;
    payload[idx++] = 0x02;
    payload[idx++] = 0xD1;
    payload[idx++] = 0x07;
    payload[idx++] = 0x31;
    payload[idx++] = static_cast<uint8_t>(strlen(name));
    memcpy(&payload[idx], name, strlen(name));
    idx += strlen(name);
    payload[idx++] = 0x32;
    payload[idx++] = 0x01;
    payload[idx++] = 0x01;
    payload[idx++] = 0x33;
    payload[idx++] = static_cast<uint8_t>(strlen(metrics));
    memcpy(&payload[idx], metrics, strlen(metrics));
    idx += strlen(metrics);

    uint8_t frame[96] = {0};
    const size_t frameLen = CommCodec::encodeFrame(payload, idx, frame, sizeof(frame));
    CHECK_TRUE(frameLen > 0);

    CommCodec::RxParser parser{};
    uint8_t parsedLen = 0;
    LONGS_EQUAL((int)CommCodec::FeedResult::FrameReady, (int)feedAll(parser, frame, frameLen, parsedLen));

    const auto decoded = CommCodec::decodeCommand(parser.rxBuf, parsedLen);
    UNSIGNED_LONGS_EQUAL(0xFBu, decoded.cmd);
    UNSIGNED_LONGS_EQUAL(0x10u, decoded.seq8);
    CHECK_TRUE(decoded.hasSeq32);
    UNSIGNED_LONGS_EQUAL(0x12345678u, decoded.seq32);
}

TEST(CommCodec, SelftestResultWithMilestone6MetricsRoundtrips) {
    static const char name[] = "m6_abort";
    static const char metrics[] = "lat=512;mot=1;reg=1;val=1";
    uint8_t payload[96] = {0};
    size_t idx = 0;
    payload[idx++] = 0xFB;
    payload[idx++] = 0x10;
    payload[idx++] = CommCodec::TAG_SEQ32;
    payload[idx++] = 0x04;
    payload[idx++] = 0x78;
    payload[idx++] = 0x56;
    payload[idx++] = 0x34;
    payload[idx++] = 0x12;
    payload[idx++] = 0x30;
    payload[idx++] = 0x02;
    payload[idx++] = 0xD6;
    payload[idx++] = 0x07;
    payload[idx++] = 0x31;
    payload[idx++] = static_cast<uint8_t>(strlen(name));
    memcpy(&payload[idx], name, strlen(name));
    idx += strlen(name);
    payload[idx++] = 0x32;
    payload[idx++] = 0x01;
    payload[idx++] = 0x01;
    payload[idx++] = 0x33;
    payload[idx++] = static_cast<uint8_t>(strlen(metrics));
    memcpy(&payload[idx], metrics, strlen(metrics));
    idx += strlen(metrics);

    uint8_t frame[128] = {0};
    const size_t frameLen = CommCodec::encodeFrame(payload, static_cast<uint8_t>(idx), frame, sizeof(frame));
    CHECK_TRUE(frameLen > 0);

    CommCodec::RxParser parser{};
    uint8_t parsedLen = 0;
    LONGS_EQUAL((int)CommCodec::FeedResult::FrameReady, (int)feedAll(parser, frame, frameLen, parsedLen));

    const auto decoded = CommCodec::decodeCommand(parser.rxBuf, parsedLen);
    UNSIGNED_LONGS_EQUAL(0xFBu, decoded.cmd);
    UNSIGNED_LONGS_EQUAL(0x10u, decoded.seq8);
    CHECK_TRUE(decoded.hasSeq32);
    UNSIGNED_LONGS_EQUAL(0x12345678u, decoded.seq32);
}

TEST(CommCodec, SelftestResultWithRtosMemoryHeadroomMetricsEncodesLongHostFrame) {
    static const char name[] = "rtos_mem";
    static const char metrics[] = "heap_now=8192;heap_min=6144;stk_min=96;stk_task=Status;task_n=9;core_miss=0;preg_n=2;trunc=0;stk_ovf=0";
    uint8_t payload[160] = {0};
    size_t idx = 0;
    payload[idx++] = 0xFB;
    payload[idx++] = 0x10;
    payload[idx++] = CommCodec::TAG_SEQ32;
    payload[idx++] = 0x04;
    payload[idx++] = 0x78;
    payload[idx++] = 0x56;
    payload[idx++] = 0x34;
    payload[idx++] = 0x12;
    payload[idx++] = 0x30;
    payload[idx++] = 0x02;
    payload[idx++] = 0x10;
    payload[idx++] = 0x04;
    payload[idx++] = 0x31;
    payload[idx++] = static_cast<uint8_t>(strlen(name));
    memcpy(&payload[idx], name, strlen(name));
    idx += strlen(name);
    payload[idx++] = 0x32;
    payload[idx++] = 0x01;
    payload[idx++] = 0x01;
    payload[idx++] = 0x33;
    payload[idx++] = static_cast<uint8_t>(strlen(metrics));
    memcpy(&payload[idx], metrics, strlen(metrics));
    idx += strlen(metrics);
    payload[idx++] = 0x34;
    payload[idx++] = 0x04;
    payload[idx++] = 0x78;
    payload[idx++] = 0x56;
    payload[idx++] = 0x34;
    payload[idx++] = 0x12;

    uint8_t frame[192] = {0};
    const size_t frameLen = CommCodec::encodeFrame(payload, static_cast<uint8_t>(idx), frame, sizeof(frame));
    UNSIGNED_LONGS_EQUAL(idx + 4u, frameLen);
    BYTES_EQUAL(0xAA, frame[0]);
    BYTES_EQUAL(static_cast<uint8_t>(idx), frame[1]);
    const uint16_t crc = CommCodec::crc16(payload, static_cast<uint16_t>(idx));
    BYTES_EQUAL(static_cast<uint8_t>(crc & 0xFFu), frame[2u + idx]);
    BYTES_EQUAL(static_cast<uint8_t>((crc >> 8) & 0xFFu), frame[3u + idx]);

    const auto decoded = CommCodec::decodeCommand(payload, static_cast<uint8_t>(idx));
    UNSIGNED_LONGS_EQUAL(0xFBu, decoded.cmd);
    UNSIGNED_LONGS_EQUAL(0x10u, decoded.seq8);
    CHECK_TRUE(decoded.hasSeq32);
    UNSIGNED_LONGS_EQUAL(0x12345678u, decoded.seq32);
}

TEST_GROUP(CommCodecRecovery)
{
};

TEST(CommCodecRecovery, NoiseBeforeStartIgnored) {
    static const uint8_t stream[] = {0x00, 0x7E, 0x55, 0xAB, 0xAA, 0x02, 0xF3, 0x01, 0x84, 0x80};
    CommCodec::RxParser parser{};
    uint8_t payloadLen = 0;
    int frameReadyCount = 0;

    for (size_t i = 0; i < sizeof(stream); ++i) {
        const auto result = CommCodec::feedRxByte(parser, stream[i], payloadLen);
        if (i < 9) {
            LONGS_EQUAL((int)CommCodec::FeedResult::None, (int)result);
        }
        if (result == CommCodec::FeedResult::FrameReady) {
            frameReadyCount++;
        }
    }

    LONGS_EQUAL(1, frameReadyCount);
    const auto decoded = CommCodec::decodeCommand(parser.rxBuf, payloadLen);
    UNSIGNED_LONGS_EQUAL(0xF3u, decoded.cmd);
    UNSIGNED_LONGS_EQUAL(0x01u, decoded.seq8);
}

TEST(CommCodecRecovery, TwoValidFramesBackToBackBothRecognized) {
    static const uint8_t stream[] = {
        0xAA, 0x02, 0xF3, 0x01, 0x84, 0x80,
        0xAA, 0x02, 0xF5, 0x02, 0xC7, 0x21
    };
    CommCodec::RxParser parser{};
    uint8_t payloadLen = 0;
    int frameReadyCount = 0;
    int crcMismatchCount = 0;
    int lengthRejectedCount = 0;
    CommCodec::DecodedCommand decodedFrames[2]{};

    for (size_t i = 0; i < sizeof(stream); ++i) {
        const auto result = CommCodec::feedRxByte(parser, stream[i], payloadLen);
        if (result == CommCodec::FeedResult::FrameReady) {
            if (frameReadyCount < 2) {
                decodedFrames[frameReadyCount] = CommCodec::decodeCommand(parser.rxBuf, payloadLen);
            }
            frameReadyCount++;
        } else if (result == CommCodec::FeedResult::CrcMismatch) {
            crcMismatchCount++;
        } else if (result == CommCodec::FeedResult::LengthRejected) {
            lengthRejectedCount++;
        }
    }

    LONGS_EQUAL(2, frameReadyCount);
    LONGS_EQUAL(0, crcMismatchCount);
    LONGS_EQUAL(0, lengthRejectedCount);
    UNSIGNED_LONGS_EQUAL(0xF3u, decodedFrames[0].cmd);
    UNSIGNED_LONGS_EQUAL(0x01u, decodedFrames[0].seq8);
    UNSIGNED_LONGS_EQUAL(0xF5u, decodedFrames[1].cmd);
    UNSIGNED_LONGS_EQUAL(0x02u, decodedFrames[1].seq8);
}

TEST(CommCodecRecovery, TruncatedThenCorruptFrameFollowedByValidFrameRecovers) {
    static const uint8_t stream[] = {
        0xAA, 0x03, 0x10, 0x20, 0x30, 0x40, 0x50,
        0xAA, 0x02, 0xF3, 0x01, 0x84, 0x80
    };
    CommCodec::RxParser parser{};
    uint8_t payloadLen = 0;
    int frameReadyCount = 0;
    int crcMismatchCount = 0;
    CommCodec::DecodedCommand recovered{};

    for (size_t i = 0; i < sizeof(stream); ++i) {
        const auto result = CommCodec::feedRxByte(parser, stream[i], payloadLen);
        if (result == CommCodec::FeedResult::CrcMismatch) {
            crcMismatchCount++;
            LONGS_EQUAL((int)CommCodec::RxParser::WAIT_START, (int)parser.state);
        } else if (result == CommCodec::FeedResult::FrameReady) {
            frameReadyCount++;
            recovered = CommCodec::decodeCommand(parser.rxBuf, payloadLen);
        }
    }

    LONGS_EQUAL(1, crcMismatchCount);
    LONGS_EQUAL(1, frameReadyCount);
    UNSIGNED_LONGS_EQUAL(0xF3u, recovered.cmd);
    UNSIGNED_LONGS_EQUAL(0x01u, recovered.seq8);
}

TEST(CommCodecRecovery, OversizeLenRejectedAndReturnsToWaitStart) {
    static const uint8_t stream[] = {0xAA, 0x3F, 0xAA, 0x02, 0xF3, 0x01, 0x84, 0x80};
    CommCodec::RxParser parser{};
    uint8_t payloadLen = 0;
    int lengthRejectedCount = 0;
    int frameReadyCount = 0;
    CommCodec::DecodedCommand recovered{};

    for (size_t i = 0; i < sizeof(stream); ++i) {
        const auto result = CommCodec::feedRxByte(parser, stream[i], payloadLen);
        if (result == CommCodec::FeedResult::LengthRejected) {
            lengthRejectedCount++;
            LONGS_EQUAL((int)CommCodec::RxParser::WAIT_START, (int)parser.state);
        } else if (result == CommCodec::FeedResult::FrameReady) {
            frameReadyCount++;
            recovered = CommCodec::decodeCommand(parser.rxBuf, payloadLen);
        }
    }

    LONGS_EQUAL(1, lengthRejectedCount);
    LONGS_EQUAL(1, frameReadyCount);
    UNSIGNED_LONGS_EQUAL(0xF3u, recovered.cmd);
    UNSIGNED_LONGS_EQUAL(0x01u, recovered.seq8);
}
