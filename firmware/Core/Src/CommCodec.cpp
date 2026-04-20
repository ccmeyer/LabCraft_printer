#include "CommCodec.h"

namespace CommCodec {

uint16_t crc16(const uint8_t* data, uint16_t len) {
    uint16_t crc = 0xFFFF;
    while (len--) {
        crc ^= *data++;
        for (int i = 0; i < 8; ++i) {
            crc = (crc & 1u) ? static_cast<uint16_t>((crc >> 1) ^ 0xA001u) : static_cast<uint16_t>(crc >> 1);
        }
    }
    return crc;
}

size_t encodeFrame(const uint8_t* payload, uint8_t len, uint8_t* outFrame, size_t outCap) {
    const size_t frameLen = static_cast<size_t>(len) + 4u;
    if (!payload || !outFrame || outCap < frameLen) {
        return 0;
    }

    outFrame[0] = START_BYTE;
    outFrame[1] = len;
    for (uint8_t i = 0; i < len; ++i) {
        outFrame[2u + i] = payload[i];
    }

    const uint16_t crc = crc16(payload, len);
    outFrame[2u + len] = static_cast<uint8_t>(crc & 0xFFu);
    outFrame[3u + len] = static_cast<uint8_t>((crc >> 8) & 0xFFu);
    return frameLen;
}

uint8_t buildAckPayload(
    uint8_t ackCmd,
    uint8_t seq8,
    uint32_t seq32,
    bool includeSeq32,
    uint8_t* outPayload,
    size_t outCap,
    bool includeAckResult,
    uint8_t ackResult,
    bool includeExpectedSeq32,
    uint32_t expectedSeq32,
    bool includeCapabilities,
    uint32_t capabilities
) {
    uint8_t needed = 2u;
    if (includeSeq32) {
        needed = static_cast<uint8_t>(needed + 6u);
    }
    if (includeAckResult) {
        needed = static_cast<uint8_t>(needed + 3u);
    }
    if (includeExpectedSeq32) {
        needed = static_cast<uint8_t>(needed + 6u);
    }
    if (includeCapabilities) {
        needed = static_cast<uint8_t>(needed + 6u);
    }
    if (!outPayload || outCap < needed) {
        return 0;
    }

    uint8_t idx = 0;
    outPayload[idx++] = ackCmd;
    outPayload[idx++] = seq8;

    if (includeSeq32) {
        outPayload[idx++] = TAG_SEQ32;
        outPayload[idx++] = 4;
        outPayload[idx++] = static_cast<uint8_t>(seq32 & 0xFFu);
        outPayload[idx++] = static_cast<uint8_t>((seq32 >> 8) & 0xFFu);
        outPayload[idx++] = static_cast<uint8_t>((seq32 >> 16) & 0xFFu);
        outPayload[idx++] = static_cast<uint8_t>((seq32 >> 24) & 0xFFu);
    }

    if (includeAckResult) {
        outPayload[idx++] = TAG_ACK_RESULT;
        outPayload[idx++] = 1u;
        outPayload[idx++] = ackResult;
    }

    if (includeExpectedSeq32) {
        outPayload[idx++] = TAG_EXPECTED_SEQ32;
        outPayload[idx++] = 4u;
        outPayload[idx++] = static_cast<uint8_t>(expectedSeq32 & 0xFFu);
        outPayload[idx++] = static_cast<uint8_t>((expectedSeq32 >> 8) & 0xFFu);
        outPayload[idx++] = static_cast<uint8_t>((expectedSeq32 >> 16) & 0xFFu);
        outPayload[idx++] = static_cast<uint8_t>((expectedSeq32 >> 24) & 0xFFu);
    }

    if (includeCapabilities) {
        outPayload[idx++] = TAG_CAPABILITIES;
        outPayload[idx++] = 4u;
        outPayload[idx++] = static_cast<uint8_t>(capabilities & 0xFFu);
        outPayload[idx++] = static_cast<uint8_t>((capabilities >> 8) & 0xFFu);
        outPayload[idx++] = static_cast<uint8_t>((capabilities >> 16) & 0xFFu);
        outPayload[idx++] = static_cast<uint8_t>((capabilities >> 24) & 0xFFu);
    }

    return idx;
}

FeedResult feedRxByte(RxParser& parser, uint8_t b, uint8_t& outPayloadLen) {
    outPayloadLen = 0;
    switch (parser.state) {
        case RxParser::WAIT_START:
            if (b == START_BYTE) {
                parser.state = RxParser::WAIT_LEN;
            }
            return FeedResult::None;

        case RxParser::WAIT_LEN:
            parser.rxLen = b;
            if (static_cast<size_t>(parser.rxLen) + 2u <= RX_BUF_SIZE) {
                parser.rxIdx = 0;
                parser.state = RxParser::WAIT_DATA;
                return FeedResult::None;
            }
            parser.state = RxParser::WAIT_START;
            return FeedResult::LengthRejected;

        case RxParser::WAIT_DATA:
            parser.rxBuf[parser.rxIdx++] = b;
            if (parser.rxIdx < static_cast<uint8_t>(parser.rxLen + 2u)) {
                return FeedResult::None;
            }

            parser.state = RxParser::WAIT_START;
            outPayloadLen = parser.rxLen;
            {
                const uint16_t recCrc = static_cast<uint16_t>(parser.rxBuf[parser.rxLen]) |
                                        static_cast<uint16_t>(parser.rxBuf[parser.rxLen + 1u] << 8);
                if (recCrc == crc16(parser.rxBuf, parser.rxLen)) {
                    return FeedResult::FrameReady;
                }
            }
            return FeedResult::CrcMismatch;
    }

    parser.state = RxParser::WAIT_START;
    return FeedResult::None;
}

DecodedCommand decodeCommand(const uint8_t* buf, uint8_t len) {
    DecodedCommand dc{};
    if (!buf || len < 2) {
        return dc;
    }

    dc.cmd = buf[0];
    dc.seq8 = buf[1];

    uint8_t idx = 2;
    while (static_cast<uint8_t>(idx + 1u) < len) {
        const uint8_t tag = buf[idx++];
        const uint8_t l = buf[idx++];
        if (static_cast<uint8_t>(idx + l) > len) {
            break;
        }

        uint32_t v = 0;
        for (uint8_t i = 0; i < l; ++i) {
            v |= static_cast<uint32_t>(buf[idx++]) << (8u * i);
        }

        switch (tag) {
            case TAG_P1:
                dc.p1 = v;
                dc.p1Len = l;
                break;
            case TAG_P2:
                dc.p2 = v;
                dc.p2Len = l;
                break;
            case TAG_P3:
                dc.p3 = v;
                dc.p3Len = l;
                break;
            case TAG_SEQ32:
                dc.seq32 = v;
                dc.hasSeq32 = (l == 4);
                break;
            default:
                break;
        }
    }

    return dc;
}

} // namespace CommCodec
