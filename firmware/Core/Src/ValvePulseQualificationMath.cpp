#include "ValvePulseQualificationMath.h"

namespace ValvePulseQualificationMath {

namespace {

static constexpr size_t kMaxAnalyzedPulses = 64u;

uint32_t integerSqrt(uint64_t value) {
  uint64_t result = 0;
  uint64_t bit = uint64_t{1} << 62;
  while (bit > value) {
    bit >>= 2;
  }
  while (bit != 0) {
    if (value >= result + bit) {
      value -= result + bit;
      result = (result >> 1) + bit;
    } else {
      result >>= 1;
    }
    bit >>= 2;
  }
  return static_cast<uint32_t>(result);
}

uint16_t eventType(PressureTraceEventType type) {
  return static_cast<uint16_t>(static_cast<uint8_t>(type));
}

}  // namespace

uint32_t absDiff(uint32_t a, uint32_t b) {
  return (a >= b) ? (a - b) : (b - a);
}

PulseDropSummary summarizePulseDrops(const PressureTraceSample* samples,
                                      size_t sampleCount,
                                      const PressureTraceEvent* events,
                                      size_t eventCount,
                                      uint32_t nominalPeriodMs) {
  (void)samples;
  (void)sampleCount;

  PulseDropSummary summary{};
  if (events == nullptr || eventCount == 0u) {
    return summary;
  }

  uint32_t drops[kMaxAnalyzedPulses]{};
  bool haveStart = false;
  uint32_t startPressure = 0u;
  uint32_t pulseEndCount = 0u;
  uint32_t firstPulseEndDt = 0u;

  for (size_t i = 0; i < eventCount; ++i) {
    const PressureTraceEvent& ev = events[i];
    if (ev.type == eventType(PressureTraceEventType::PulseStart)) {
      startPressure = ev.value1;
      haveStart = true;
      continue;
    }

    if (ev.type != eventType(PressureTraceEventType::PulseEnd)) {
      continue;
    }

    pulseEndCount++;
    if (firstPulseEndDt == 0u) {
      firstPulseEndDt = ev.dtMs;
    }
    if (nominalPeriodMs > 0u) {
      const uint32_t expectedDt = (pulseEndCount <= 1u)
                                      ? ev.dtMs
                                      : firstPulseEndDt + ((pulseEndCount - 1u) * nominalPeriodMs);
      const uint32_t slip = absDiff(expectedDt, ev.dtMs);
      if (slip > summary.maxDeadlineSlipMs) {
        summary.maxDeadlineSlipMs = slip;
      }
    }

    const uint32_t nextPulseDt = [&]() {
      for (size_t j = i + 1u; j < eventCount; ++j) {
        if (events[j].type == eventType(PressureTraceEventType::PulseEnd)) {
          return static_cast<uint32_t>(events[j].dtMs);
        }
      }
      return uint32_t{0xFFFFFFFFu};
    }();

    bool sawReadyExit = false;
    for (size_t j = i + 1u; j < eventCount; ++j) {
      if ((nextPulseDt != 0xFFFFFFFFu) && (events[j].dtMs >= nextPulseDt)) {
        break;
      }
      if (events[j].type == eventType(PressureTraceEventType::ReadyExit)) {
        sawReadyExit = true;
        continue;
      }
      if (sawReadyExit && events[j].type == eventType(PressureTraceEventType::ReadyEnter)) {
        const uint32_t recovery = static_cast<uint32_t>(events[j].dtMs) - static_cast<uint32_t>(ev.dtMs);
        if (recovery > summary.maxRecoveryMs) {
          summary.maxRecoveryMs = recovery;
        }
        break;
      }
    }

    if (!haveStart || summary.pulseCount >= kMaxAnalyzedPulses) {
      haveStart = false;
      continue;
    }
    const uint32_t endPressure = ev.value1;
    drops[summary.pulseCount++] = absDiff(startPressure, endPressure);
    haveStart = false;
  }

  if (summary.pulseCount == 0u) {
    return summary;
  }

  uint64_t sum = 0u;
  summary.minDropRaw = drops[0];
  summary.maxDropRaw = drops[0];
  for (uint32_t i = 0; i < summary.pulseCount; ++i) {
    const uint32_t drop = drops[i];
    sum += drop;
    if (drop < summary.minDropRaw) summary.minDropRaw = drop;
    if (drop > summary.maxDropRaw) summary.maxDropRaw = drop;
  }
  summary.meanDropRaw = static_cast<uint32_t>((sum + (summary.pulseCount / 2u)) / summary.pulseCount);

  if (summary.pulseCount > 1u) {
    summary.dropSlopeRawPerPulse =
        (static_cast<int32_t>(drops[summary.pulseCount - 1u]) - static_cast<int32_t>(drops[0])) /
        static_cast<int32_t>(summary.pulseCount - 1u);
  }

  uint64_t squaredDiffSum = 0u;
  uint64_t absDiffSum = 0u;
  for (uint32_t i = 0; i < summary.pulseCount; ++i) {
    const uint32_t diff = absDiff(drops[i], summary.meanDropRaw);
    squaredDiffSum += static_cast<uint64_t>(diff) * static_cast<uint64_t>(diff);
    absDiffSum += diff;
  }
  const uint32_t stdDev = integerSqrt(squaredDiffSum / summary.pulseCount);
  if (summary.meanDropRaw > 0u) {
    summary.dropCvPct = static_cast<uint32_t>(
        ((static_cast<uint64_t>(stdDev) * 100u) + (summary.meanDropRaw / 2u)) / summary.meanDropRaw);
  }

  const uint32_t meanAbsDiff = static_cast<uint32_t>((absDiffSum + (summary.pulseCount / 2u)) / summary.pulseCount);
  uint32_t outlierThreshold = meanAbsDiff;
  const uint32_t halfMean = summary.meanDropRaw / 2u;
  if (outlierThreshold < halfMean) {
    outlierThreshold = halfMean;
  }
  for (uint32_t i = 0; i < summary.pulseCount; ++i) {
    if (absDiff(drops[i], summary.meanDropRaw) > outlierThreshold) {
      summary.outlierCount++;
    }
  }

  return summary;
}

}  // namespace ValvePulseQualificationMath
