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

struct WindowedValveDropSummary {
  uint32_t pulseCount = 0;
  uint32_t meanDropRaw = 0;
  uint32_t dropCvPct = 0;
  int32_t dropSlopeRawPerPulse = 0;
  uint32_t outlierCount = 0;
  uint32_t rejectCount = 0;
  uint32_t minDropRaw = 0;
  uint32_t maxDropRaw = 0;
  uint32_t spanDropRaw = 0;
  uint32_t meanSpikeRaw = 0;
  uint32_t minSpikeRaw = 0;
  uint32_t maxSpikeRaw = 0;
};

struct WindowedValveCharacterizationSummary {
  uint32_t pulseCount = 0;
  uint32_t ringCount = 0;
  uint32_t latencyCount = 0;
  uint32_t meanSettledDropRaw = 0;
  uint32_t settledDropCvPct = 0;
  int32_t settledDropSlopeRawPerPulse = 0;
  uint32_t outlierCount = 0;
  uint32_t rejectCount = 0;
  uint32_t ringMissingCount = 0;
  uint32_t latencyMissingCount = 0;
  uint32_t minSettledDropRaw = 0;
  uint32_t maxSettledDropRaw = 0;
  uint32_t spanSettledDropRaw = 0;
  uint32_t meanRingRaw = 0;
  uint32_t minRingRaw = 0;
  uint32_t maxRingRaw = 0;
  uint32_t meanLatencyMs = 0;
  uint32_t minLatencyMs = 0;
  uint32_t maxLatencyMs = 0;
};

struct ThreeWidthLinearitySummary {
  uint32_t monotonic = 0;
  uint32_t gainRaw = 0;
  uint32_t midpointLinearityErrorPct = 0;
};

struct ResponseValueSummary {
  uint32_t count = 0;
  uint32_t meanRaw = 0;
  uint32_t cvPct = 0;
  uint32_t outlierCount = 0;
  uint32_t minRaw = 0;
  uint32_t maxRaw = 0;
  uint32_t spanRaw = 0;
};

uint32_t absDiff(uint32_t a, uint32_t b);
uint16_t interleavedValvePulseWidthUs(size_t sequenceIndexZeroBased);
uint16_t groupedValvePulseWidthUs(size_t sequenceIndexZeroBased, size_t replicatesPerWidth);
bool isSteadyValveCharacterizationReplicate(uint16_t replicateForWidth);
uint32_t valveGapSweepDetailedGapMs(size_t gapIndexZeroBased);
uint16_t valveGapSweepControlWidthUs(size_t conditionIndexZeroBased);
uint32_t valveGapSweepControlGapMs(size_t conditionIndexZeroBased);
ResponseValueSummary summarizeResponseValues(const uint32_t* responses, size_t responseCount);
ThreeWidthLinearitySummary summarizeThreeWidthLinearity(uint32_t response15,
                                                        uint32_t response30,
                                                        uint32_t response45);
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
WindowedValveDropSummary summarizeWindowedValveDrops(const PressureTraceSample* samples,
                                                     size_t sampleCount,
                                                     const PressureTraceEvent* events,
                                                     size_t eventCount,
                                                     uint32_t baselineWindowMs,
                                                     uint32_t dropWindowAfterPulseEndMs);
WindowedValveCharacterizationSummary summarizeWindowedValveCharacterization(
    const PressureTraceSample* samples,
    size_t sampleCount,
    const PressureTraceEvent* events,
    size_t eventCount,
    uint32_t baselineWindowMs,
    uint32_t ringWindowAfterPulseEndMs,
    uint32_t settledStartAfterPulseEndMs,
    uint32_t settledEndAfterPulseEndMs);

}  // namespace ValvePulseQualificationMath

#endif  // INC_VALVEPULSEQUALIFICATIONMATH_H_
