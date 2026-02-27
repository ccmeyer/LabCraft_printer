#include "CppUTest/TestHarness.h"
#include "CommCodec.h"

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

TEST(CommCodec, SelftestStartWithProfileRunIdTimeoutParsesCoreFields) {
    static const uint8_t payload[] = {
        0xFA, 0x10,
        CommCodec::TAG_SEQ32, 0x04, 0x78, 0x56, 0x34, 0x12,
        0x20, 0x01, 0x00,             // TAG_PROFILE
        0x21, 0x04, 0x78, 0x56, 0x34, 0x12, // TAG_RUN_ID
        0x22, 0x04, 0x30, 0x75, 0x00, 0x00  // TAG_TIMEOUT_MS = 30000
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
    CHECK_TRUE(decoded.hasSeq32);
    UNSIGNED_LONGS_EQUAL(0x12345678u, decoded.seq32);
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
