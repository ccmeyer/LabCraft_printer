#include "DiagnosticResultEmitter.h"

#include <cstring>

namespace DiagnosticResultEmitter {

namespace {

void appendU16(uint8_t* out, size_t& idx, uint16_t value)
{
    out[idx++] = static_cast<uint8_t>(value & 0xFFu);
    out[idx++] = static_cast<uint8_t>((value >> 8) & 0xFFu);
}

void appendU32(uint8_t* out, size_t& idx, uint32_t value)
{
    out[idx++] = static_cast<uint8_t>(value & 0xFFu);
    out[idx++] = static_cast<uint8_t>((value >> 8) & 0xFFu);
    out[idx++] = static_cast<uint8_t>((value >> 16) & 0xFFu);
    out[idx++] = static_cast<uint8_t>((value >> 24) & 0xFFu);
}

uint8_t boundedLen(const char* text, size_t maxLen)
{
    if (!text) {
        return 0u;
    }
    const size_t rawLen = std::strlen(text);
    return static_cast<uint8_t>((rawLen > maxLen) ? maxLen : rawLen);
}

void appendBytes(uint8_t* out, size_t& idx, const void* src, size_t len)
{
    if (len == 0u || !src) {
        return;
    }
    std::memcpy(&out[idx], src, len);
    idx += len;
}

} // namespace

size_t buildResultPayload(uint8_t* out,
                          size_t outCapacity,
                          uint8_t seq8,
                          uint32_t runId,
                          uint16_t testId,
                          const char* name,
                          bool pass,
                          const char* metrics,
                          uint32_t timestampMs)
{
    if (!out) {
        return 0u;
    }

    const uint8_t nameLen = boundedLen(name, kMaxResultNameBytes);
    const size_t maxMetricsByFrame = (kResultMetricsFrameBudget > static_cast<size_t>(nameLen))
        ? (kResultMetricsFrameBudget - static_cast<size_t>(nameLen))
        : 0u;
    const uint8_t metricsLen = boundedLen(metrics, maxMetricsByFrame);
    const size_t required = 25u + static_cast<size_t>(nameLen) + static_cast<size_t>(metricsLen);
    if (outCapacity < required) {
        return 0u;
    }

    size_t idx = 0;
    out[idx++] = kCmdSelfTestResult;
    out[idx++] = seq8;

    out[idx++] = kTagTestId; out[idx++] = 2;
    appendU16(out, idx, testId);

    out[idx++] = kTagName; out[idx++] = nameLen;
    appendBytes(out, idx, name, nameLen);

    out[idx++] = kTagPass; out[idx++] = 1;
    out[idx++] = pass ? 1u : 0u;

    out[idx++] = kTagMetrics; out[idx++] = metricsLen;
    appendBytes(out, idx, metrics, metricsLen);

    out[idx++] = kTagTimestamp; out[idx++] = 4;
    appendU32(out, idx, timestampMs);

    out[idx++] = kTagRunId; out[idx++] = 4;
    appendU32(out, idx, runId);

    return idx;
}

size_t buildTracePayload(uint8_t* out,
                         size_t outCapacity,
                         uint8_t seq8,
                         uint32_t runId,
                         uint16_t testId,
                         const char* name,
                         bool pass,
                         uint8_t traceKind,
                         uint8_t traceFormat,
                         uint16_t chunkIndex,
                         uint16_t chunkTotal,
                         const uint8_t* payloadBytes,
                         uint8_t payloadLen)
{
    if (!out || outCapacity < 32u) {
        return 0u;
    }

    size_t idx = 0;
    out[idx++] = kCmdSelfTestResult;
    out[idx++] = seq8;

    out[idx++] = kTagTestId; out[idx++] = 2;
    appendU16(out, idx, testId);

    const uint8_t nameLen = boundedLen(name, kMaxTraceNameBytes);
    const size_t required = 33u + static_cast<size_t>(nameLen) + static_cast<size_t>(payloadLen);
    if (outCapacity < required) {
        return 0u;
    }

    out[idx++] = kTagName; out[idx++] = nameLen;
    appendBytes(out, idx, name, nameLen);

    out[idx++] = kTagPass; out[idx++] = 1;
    out[idx++] = pass ? 1u : 0u;

    out[idx++] = kTagTraceKind; out[idx++] = 1; out[idx++] = traceKind;
    out[idx++] = kTagTraceFormat; out[idx++] = 1; out[idx++] = traceFormat;
    out[idx++] = kTagTraceChunkIndex; out[idx++] = 2;
    appendU16(out, idx, chunkIndex);
    out[idx++] = kTagTraceChunkTotal; out[idx++] = 2;
    appendU16(out, idx, chunkTotal);
    out[idx++] = kTagTracePayload; out[idx++] = payloadLen;
    appendBytes(out, idx, payloadBytes, payloadLen);

    out[idx++] = kTagRunId; out[idx++] = 4;
    appendU32(out, idx, runId);

    return idx;
}

size_t buildDonePayload(uint8_t* out,
                        size_t outCapacity,
                        uint8_t seq8,
                        uint32_t runId,
                        uint16_t total,
                        uint16_t passed,
                        uint16_t failed,
                        bool aborted,
                        uint32_t timestampMs)
{
    if (!out || outCapacity < 29u) {
        return 0u;
    }

    size_t idx = 0;
    out[idx++] = kCmdSelfTestDone;
    out[idx++] = seq8;

    out[idx++] = kTagRunId; out[idx++] = 4;
    appendU32(out, idx, runId);

    out[idx++] = kTagTotal; out[idx++] = 2;
    appendU16(out, idx, total);

    out[idx++] = kTagPassed; out[idx++] = 2;
    appendU16(out, idx, passed);

    out[idx++] = kTagFailed; out[idx++] = 2;
    appendU16(out, idx, failed);

    out[idx++] = kTagAborted; out[idx++] = 1;
    out[idx++] = aborted ? 1u : 0u;

    out[idx++] = kTagTimestamp; out[idx++] = 4;
    appendU32(out, idx, timestampMs);

    return idx;
}

} // namespace DiagnosticResultEmitter
