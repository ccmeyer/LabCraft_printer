#ifndef INC_COMMCODEC_H_
#define INC_COMMCODEC_H_

#include <cstddef>
#include <cstdint>

namespace CommCodec {

static constexpr uint8_t START_BYTE = 0xAA;
static constexpr uint8_t TAG_P1 = 0x01;
static constexpr uint8_t TAG_P2 = 0x02;
static constexpr uint8_t TAG_P3 = 0x03;
static constexpr uint8_t TAG_SEQ32 = 0x10;
static constexpr uint8_t TAG_ACK_RESULT = 0x11;
static constexpr uint8_t TAG_EXPECTED_SEQ32 = 0x12;
static constexpr uint8_t TAG_CAPABILITIES = 0x13;
static constexpr size_t RX_BUF_SIZE = 64;

struct DecodedCommand {
    uint8_t cmd = 0;
    uint8_t seq8 = 0;
    uint32_t p1 = 0;
    uint32_t p2 = 0;
    uint32_t p3 = 0;
    uint32_t seq32 = 0;
    uint8_t p1Len = 0;
    uint8_t p2Len = 0;
    uint8_t p3Len = 0;
    bool hasSeq32 = false;
};

struct RxParser {
    enum State : uint8_t { WAIT_START = 0, WAIT_LEN = 1, WAIT_DATA = 2 };

    State state = WAIT_START;
    uint8_t rxLen = 0;
    uint8_t rxIdx = 0;
    uint8_t rxBuf[RX_BUF_SIZE] = {0};
};

enum class FeedResult : uint8_t {
    None = 0,
    FrameReady,
    LengthRejected,
    CrcMismatch
};

uint16_t crc16(const uint8_t* data, uint16_t len);

size_t encodeFrame(const uint8_t* payload, uint8_t len, uint8_t* outFrame, size_t outCap);

uint8_t buildAckPayload(
    uint8_t ackCmd,
    uint8_t seq8,
    uint32_t seq32,
    bool includeSeq32,
    uint8_t* outPayload,
    size_t outCap,
    bool includeAckResult = false,
    uint8_t ackResult = 0,
    bool includeExpectedSeq32 = false,
    uint32_t expectedSeq32 = 0,
    bool includeCapabilities = false,
    uint32_t capabilities = 0
);

FeedResult feedRxByte(RxParser& parser, uint8_t b, uint8_t& outPayloadLen);

DecodedCommand decodeCommand(const uint8_t* buf, uint8_t len);

} // namespace CommCodec

#endif // INC_COMMCODEC_H_
