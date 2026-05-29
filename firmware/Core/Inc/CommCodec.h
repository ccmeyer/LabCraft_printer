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
static constexpr uint8_t TAG_PROFILE = 0x20;
static constexpr uint8_t TAG_RUN_ID = 0x21;
static constexpr uint8_t TAG_TIMEOUT_MS = 0x22;
static constexpr uint8_t TAG_TRACE_CHANNEL = 0x40;
static constexpr uint8_t TAG_TRACE_PRESSURE_MPSI = 0x41;
static constexpr uint8_t TAG_TRACE_PULSE_US = 0x42;
static constexpr uint8_t TAG_TRACE_PULSE_COUNT = 0x43;
static constexpr uint8_t TAG_TRACE_FREQUENCY_HZ = 0x44;
static constexpr size_t RX_BUF_SIZE = 64;

struct DecodedCommand {
    uint8_t cmd = 0;
    uint8_t seq8 = 0;
    uint32_t p1 = 0;
    uint32_t p2 = 0;
    uint32_t p3 = 0;
    uint32_t seq32 = 0;
    uint32_t runId = 0;
    uint32_t timeoutMs = 0;
    uint32_t traceChannel = 0;
    uint32_t tracePressureMilliPsi = 0;
    uint32_t tracePulseUs = 0;
    uint32_t tracePulseCount = 0;
    uint32_t traceFrequencyHz = 0;
    uint8_t p1Len = 0;
    uint8_t p2Len = 0;
    uint8_t p3Len = 0;
    uint8_t traceChannelLen = 0;
    uint8_t tracePressureMilliPsiLen = 0;
    uint8_t tracePulseUsLen = 0;
    uint8_t tracePulseCountLen = 0;
    uint8_t traceFrequencyHzLen = 0;
    bool hasSeq32 = false;
    bool hasRunId = false;
    bool hasTimeoutMs = false;
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
