#ifndef INC_VALVEPULSEQUALIFICATIONMATH_H_
#define INC_VALVEPULSEQUALIFICATIONMATH_H_

#include "PressureTraceRecorder.h"

#include <cstddef>
#include <cstdint>

namespace ValvePulseQualificationMath {

struct PulseDropSummary {
  uint32_t pulseCount = 0;
  uint32_t meanDropRaw = 0;
  uint32_t dropCvPct = 0;
  int32_t dropSlopeRawPerPulse = 0;
  uint32_t outlierCount = 0;
  uint32_t maxRecoveryMs = 0;
  uint32_t maxDeadlineSlipMs = 0;
  uint32_t minDropRaw = 0;
  uint32_t maxDropRaw = 0;
};

struct WindowedPulseResponseSummary {
  uint32_t pulseCount = 0;
  uint32_t meanResponseRaw = 0;
  uint32_t responseCvPct = 0;
  int32_t responseSlopeRawPerPulse = 0;
  uint32_t outlierCount = 0;
  uint32_t rejectCount = 0;
  uint32_t minResponseRaw = 0;
  uint32_t maxResponseRaw = 0;
};

uint32_t absDiff(uint32_t a, uint32_t b);
PulseDropSummary summarizePulseDrops(const PressureTraceSample* samples,
                                      size_t sampleCount,
                                      const PressureTraceEvent* events,
                                      size_t eventCount,
                                      uint32_t nominalPeriodMs);
WindowedPulseResponseSummary summarizeWindowedPulseResponses(const PressureTraceSample* samples,
                                                             size_t sampleCount,
                                                             const PressureTraceEvent* events,
                                                             size_t eventCount,
                                                             uint32_t baselineWindowMs,
                                                             uint32_t responseWindowMs);

}  // namespace ValvePulseQualificationMath

#endif  // INC_VALVEPULSEQUALIFICATIONMATH_H_
