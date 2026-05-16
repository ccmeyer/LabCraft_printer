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

ResponseValueSummary summarizeResponseValues(const uint32_t* responses, size_t responseCount) {
  ResponseValueSummary summary{};
  if (responses == nullptr || responseCount == 0u) {
    return summary;
  }

  const size_t count = (responseCount > kMaxAnalyzedPulses) ? kMaxAnalyzedPulses : responseCount;
  summary.count = static_cast<uint32_t>(count);
  uint64_t sum = 0u;
  summary.minRaw = responses[0];
  summary.maxRaw = responses[0];
  for (size_t i = 0; i < count; ++i) {
    const uint32_t response = responses[i];
    sum += response;
    if (response < summary.minRaw) summary.minRaw = response;
    if (response > summary.maxRaw) summary.maxRaw = response;
  }
  summary.meanRaw = static_cast<uint32_t>((sum + (count / 2u)) / count);
  summary.spanRaw = summary.maxRaw - summary.minRaw;

  uint64_t squaredDiffSum = 0u;
  uint64_t absDiffSum = 0u;
  for (size_t i = 0; i < count; ++i) {
    const uint32_t diff = absDiff(responses[i], summary.meanRaw);
    squaredDiffSum += static_cast<uint64_t>(diff) * static_cast<uint64_t>(diff);
    absDiffSum += diff;
  }
  const uint32_t stdDev = integerSqrt(squaredDiffSum / count);
  if (summary.meanRaw > 0u) {
    summary.cvPct = static_cast<uint32_t>(
        ((static_cast<uint64_t>(stdDev) * 100u) + (summary.meanRaw / 2u)) / summary.meanRaw);
  }

  const uint32_t meanAbsDiff = static_cast<uint32_t>((absDiffSum + (count / 2u)) / count);
  uint32_t outlierThreshold = meanAbsDiff;
  const uint32_t halfMean = summary.meanRaw / 2u;
  if (outlierThreshold < halfMean) {
    outlierThreshold = halfMean;
  }
  for (size_t i = 0; i < count; ++i) {
    if (absDiff(responses[i], summary.meanRaw) > outlierThreshold) {
      summary.outlierCount++;
    }
  }

  return summary;
}

ThreeWidthLinearitySummary summarizeThreeWidthLinearity(uint32_t response15,
                                                        uint32_t response30,
                                                        uint32_t response45) {
  ThreeWidthLinearitySummary summary{};
  summary.monotonic = (response15 <= response30 && response30 <= response45) ? 1u : 0u;
  summary.gainRaw = summary.monotonic ? (response45 - response15) : absDiff(response45, response15);

  if (summary.gainRaw == 0u) {
    summary.midpointLinearityErrorPct = (response30 == response15) ? 0u : 100u;
    return summary;
  }

  const uint64_t doubledMid = static_cast<uint64_t>(response30) * 2u;
  const uint64_t endpointSum = static_cast<uint64_t>(response15) + static_cast<uint64_t>(response45);
  const uint64_t doubledError = (doubledMid >= endpointSum) ? (doubledMid - endpointSum) : (endpointSum - doubledMid);
  summary.midpointLinearityErrorPct = static_cast<uint32_t>(
      ((doubledError * 100u) + summary.gainRaw) / (2u * static_cast<uint64_t>(summary.gainRaw)));
  return summary;
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

WindowedPulseResponseSummary summarizeWindowedPulseResponses(const PressureTraceSample* samples,
                                                             size_t sampleCount,
                                                             const PressureTraceEvent* events,
                                                             size_t eventCount,
                                                             uint32_t baselineWindowMs,
                                                             uint32_t responseWindowMs) {
  WindowedPulseResponseSummary summary{};
  if (samples == nullptr || sampleCount == 0u || events == nullptr || eventCount == 0u || responseWindowMs == 0u) {
    return summary;
  }

  uint32_t responses[kMaxAnalyzedPulses]{};
  for (size_t i = 0; i < eventCount; ++i) {
    const PressureTraceEvent& ev = events[i];
    if (ev.type != eventType(PressureTraceEventType::PulseStart)) {
      continue;
    }

    const uint32_t startDt = ev.dtMs;
    uint64_t baselineSum = 0u;
    uint32_t baselineCount = 0u;
    const uint32_t baselineStart = (startDt > baselineWindowMs) ? (startDt - baselineWindowMs) : 0u;
    for (size_t s = 0; s < sampleCount; ++s) {
      const uint32_t sampleDt = samples[s].dtMs;
      if (sampleDt >= baselineStart && sampleDt <= startDt) {
        baselineSum += samples[s].rawPressure;
        baselineCount++;
      }
    }
    const uint32_t baseline = (baselineCount > 0u)
                                  ? static_cast<uint32_t>((baselineSum + (baselineCount / 2u)) / baselineCount)
                                  : static_cast<uint32_t>(ev.value1);

    bool haveResponseSample = false;
    uint32_t minPressure = baseline;
    uint32_t maxPressure = baseline;
    const uint32_t responseEnd = startDt + responseWindowMs;
    for (size_t s = 0; s < sampleCount; ++s) {
      const uint32_t sampleDt = samples[s].dtMs;
      if (sampleDt < startDt || sampleDt > responseEnd) {
        continue;
      }
      const uint32_t pressure = samples[s].rawPressure;
      if (!haveResponseSample) {
        minPressure = pressure;
        maxPressure = pressure;
        haveResponseSample = true;
      } else {
        if (pressure < minPressure) minPressure = pressure;
        if (pressure > maxPressure) maxPressure = pressure;
      }
    }

    if (!haveResponseSample || summary.pulseCount >= kMaxAnalyzedPulses) {
      summary.rejectCount++;
      continue;
    }

    const uint32_t downResponse = (baseline >= minPressure) ? (baseline - minPressure) : (minPressure - baseline);
    const uint32_t upResponse = (maxPressure >= baseline) ? (maxPressure - baseline) : (baseline - maxPressure);
    responses[summary.pulseCount++] = (downResponse >= upResponse) ? downResponse : upResponse;
  }

  if (summary.pulseCount == 0u) {
    return summary;
  }

  uint64_t sum = 0u;
  summary.minResponseRaw = responses[0];
  summary.maxResponseRaw = responses[0];
  for (uint32_t i = 0; i < summary.pulseCount; ++i) {
    const uint32_t response = responses[i];
    sum += response;
    if (response < summary.minResponseRaw) summary.minResponseRaw = response;
    if (response > summary.maxResponseRaw) summary.maxResponseRaw = response;
  }
  summary.meanResponseRaw = static_cast<uint32_t>((sum + (summary.pulseCount / 2u)) / summary.pulseCount);

  if (summary.pulseCount > 1u) {
    summary.responseSlopeRawPerPulse =
        (static_cast<int32_t>(responses[summary.pulseCount - 1u]) - static_cast<int32_t>(responses[0])) /
        static_cast<int32_t>(summary.pulseCount - 1u);
  }

  uint64_t squaredDiffSum = 0u;
  uint64_t absDiffSum = 0u;
  for (uint32_t i = 0; i < summary.pulseCount; ++i) {
    const uint32_t diff = absDiff(responses[i], summary.meanResponseRaw);
    squaredDiffSum += static_cast<uint64_t>(diff) * static_cast<uint64_t>(diff);
    absDiffSum += diff;
  }
  const uint32_t stdDev = integerSqrt(squaredDiffSum / summary.pulseCount);
  if (summary.meanResponseRaw > 0u) {
    summary.responseCvPct = static_cast<uint32_t>(
        ((static_cast<uint64_t>(stdDev) * 100u) + (summary.meanResponseRaw / 2u)) / summary.meanResponseRaw);
  }

  const uint32_t meanAbsDiff = static_cast<uint32_t>((absDiffSum + (summary.pulseCount / 2u)) / summary.pulseCount);
  uint32_t outlierThreshold = meanAbsDiff;
  const uint32_t halfMean = summary.meanResponseRaw / 2u;
  if (outlierThreshold < halfMean) {
    outlierThreshold = halfMean;
  }
  for (uint32_t i = 0; i < summary.pulseCount; ++i) {
    if (absDiff(responses[i], summary.meanResponseRaw) > outlierThreshold) {
      summary.outlierCount++;
    }
  }

  return summary;
}

WindowedValveDropSummary summarizeWindowedValveDrops(const PressureTraceSample* samples,
                                                     size_t sampleCount,
                                                     const PressureTraceEvent* events,
                                                     size_t eventCount,
                                                     uint32_t baselineWindowMs,
                                                     uint32_t dropWindowAfterPulseEndMs) {
  WindowedValveDropSummary summary{};
  if (samples == nullptr || sampleCount == 0u || events == nullptr || eventCount == 0u ||
      dropWindowAfterPulseEndMs == 0u) {
    return summary;
  }

  uint32_t drops[kMaxAnalyzedPulses]{};
  uint32_t spikes[kMaxAnalyzedPulses]{};
  for (size_t i = 0; i < eventCount; ++i) {
    const PressureTraceEvent& startEv = events[i];
    if (startEv.type != eventType(PressureTraceEventType::PulseStart)) {
      continue;
    }

    const PressureTraceEvent* endEv = nullptr;
    for (size_t j = i + 1u; j < eventCount; ++j) {
      if (events[j].type == eventType(PressureTraceEventType::PulseEnd)) {
        endEv = &events[j];
        break;
      }
    }
    if (endEv == nullptr) {
      summary.rejectCount++;
      continue;
    }

    const uint32_t startDt = startEv.dtMs;
    const uint32_t endDt = endEv->dtMs;
    uint64_t baselineSum = 0u;
    uint32_t baselineCount = 0u;
    const uint32_t baselineStart = (startDt > baselineWindowMs) ? (startDt - baselineWindowMs) : 0u;
    for (size_t s = 0; s < sampleCount; ++s) {
      const uint32_t sampleDt = samples[s].dtMs;
      if (sampleDt >= baselineStart && sampleDt <= startDt) {
        baselineSum += samples[s].rawPressure;
        baselineCount++;
      }
    }
    const uint32_t baseline = (baselineCount > 0u)
                                  ? static_cast<uint32_t>((baselineSum + (baselineCount / 2u)) / baselineCount)
                                  : static_cast<uint32_t>(startEv.value1);

    bool haveDropSample = false;
    bool haveSpikeSample = false;
    uint32_t minPressure = baseline;
    uint32_t maxPressure = baseline;
    const uint32_t windowEnd = endDt + dropWindowAfterPulseEndMs;
    for (size_t s = 0; s < sampleCount; ++s) {
      const uint32_t sampleDt = samples[s].dtMs;
      const uint32_t pressure = samples[s].rawPressure;
      if (sampleDt >= endDt && sampleDt <= windowEnd) {
        if (!haveDropSample || pressure < minPressure) {
          minPressure = pressure;
        }
        haveDropSample = true;
      }
      if (sampleDt >= startDt && sampleDt <= windowEnd) {
        if (!haveSpikeSample || pressure > maxPressure) {
          maxPressure = pressure;
        }
        haveSpikeSample = true;
      }
    }

    if (!haveDropSample || summary.pulseCount >= kMaxAnalyzedPulses) {
      summary.rejectCount++;
      continue;
    }

    drops[summary.pulseCount] = (baseline > minPressure) ? (baseline - minPressure) : 0u;
    spikes[summary.pulseCount] = (haveSpikeSample && maxPressure > baseline) ? (maxPressure - baseline) : 0u;
    summary.pulseCount++;
  }

  if (summary.pulseCount == 0u) {
    return summary;
  }

  const auto dropSummary = summarizeResponseValues(drops, summary.pulseCount);
  const auto spikeSummary = summarizeResponseValues(spikes, summary.pulseCount);
  summary.meanDropRaw = dropSummary.meanRaw;
  summary.dropCvPct = dropSummary.cvPct;
  summary.outlierCount = dropSummary.outlierCount;
  summary.minDropRaw = dropSummary.minRaw;
  summary.maxDropRaw = dropSummary.maxRaw;
  summary.spanDropRaw = dropSummary.spanRaw;
  summary.meanSpikeRaw = spikeSummary.meanRaw;
  summary.minSpikeRaw = spikeSummary.minRaw;
  summary.maxSpikeRaw = spikeSummary.maxRaw;

  if (summary.pulseCount > 1u) {
    summary.dropSlopeRawPerPulse =
        (static_cast<int32_t>(drops[summary.pulseCount - 1u]) - static_cast<int32_t>(drops[0])) /
        static_cast<int32_t>(summary.pulseCount - 1u);
  }

  return summary;
}

}  // namespace ValvePulseQualificationMath
