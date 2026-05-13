#ifndef INC_DIAGNOSTICRESULTEMITTER_H_
#define INC_DIAGNOSTICRESULTEMITTER_H_

#include <cstddef>
#include <cstdint>

namespace DiagnosticResultEmitter {

static constexpr uint8_t kCmdSelfTestResult = 0xFB;
static constexpr uint8_t kCmdSelfTestDone = 0xFC;

static constexpr uint8_t kTagRunId = 0x21;
static constexpr uint8_t kTagTestId = 0x30;
static constexpr uint8_t kTagName = 0x31;
static constexpr uint8_t kTagPass = 0x32;
static constexpr uint8_t kTagMetrics = 0x33;
static constexpr uint8_t kTagTimestamp = 0x34;
static constexpr uint8_t kTagTotal = 0x35;
static constexpr uint8_t kTagPassed = 0x36;
static constexpr uint8_t kTagFailed = 0x37;
static constexpr uint8_t kTagAborted = 0x38;
static constexpr uint8_t kTagTraceKind = 0x39;
static constexpr uint8_t kTagTraceChunkIndex = 0x3A;
static constexpr uint8_t kTagTraceChunkTotal = 0x3B;
static constexpr uint8_t kTagTraceFormat = 0x3C;
static constexpr uint8_t kTagTracePayload = 0x3D;

static constexpr size_t kMaxResultNameBytes = 32u;
static constexpr size_t kMaxTraceNameBytes = 48u;
static constexpr size_t kResultMetricsFrameBudget = 230u;

size_t buildResultPayload(uint8_t* out,
                          size_t outCapacity,
                          uint8_t seq8,
                          uint32_t runId,
                          uint16_t testId,
                          const char* name,
                          bool pass,
                          const char* metrics,
                          uint32_t timestampMs);

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
                         uint8_t payloadLen);

size_t buildDonePayload(uint8_t* out,
                        size_t outCapacity,
                        uint8_t seq8,
                        uint32_t runId,
                        uint16_t total,
                        uint16_t passed,
                        uint16_t failed,
                        bool aborted,
                        uint32_t timestampMs);

} // namespace DiagnosticResultEmitter

#endif // INC_DIAGNOSTICRESULTEMITTER_H_
