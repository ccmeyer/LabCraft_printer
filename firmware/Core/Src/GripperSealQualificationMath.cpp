#include "GripperSealQualificationMath.h"

namespace GripperSealQualificationMath {

uint32_t absDiff(int32_t a, int32_t b) {
  const int64_t diff = static_cast<int64_t>(a) - static_cast<int64_t>(b);
  return static_cast<uint32_t>((diff < 0) ? -diff : diff);
}

int32_t slopeRawPerMin(int32_t startRaw, int32_t endRaw, uint32_t durationMs) {
  if (durationMs == 0u) {
    return 0;
  }
  const int64_t delta = static_cast<int64_t>(endRaw) - static_cast<int64_t>(startRaw);
  return static_cast<int32_t>((delta * 60000LL) / static_cast<int64_t>(durationMs));
}

DecaySummary summarizeDecay(int32_t startRaw,
                            int32_t endRaw,
                            uint32_t holdMs,
                            uint32_t thresholdCrossMs,
                            uint32_t thresholdRaw) {
  DecaySummary summary{};
  summary.dropRaw = absDiff(startRaw, endRaw);
  summary.slopeRawPerMin = slopeRawPerMin(startRaw, endRaw, holdMs);
  summary.timeToThresholdMs = thresholdCrossMs;
  if (thresholdCrossMs != 0u) {
    summary.sealPassDurationMs = thresholdCrossMs;
  } else if (summary.dropRaw <= thresholdRaw) {
    summary.sealPassDurationMs = holdMs;
  } else {
    summary.sealPassDurationMs = 0u;
  }
  return summary;
}

uint32_t spanRaw(const uint32_t* values, size_t count) {
  if (values == nullptr || count == 0u) {
    return 0u;
  }
  uint32_t minRaw = values[0];
  uint32_t maxRaw = values[0];
  for (size_t i = 1u; i < count; ++i) {
    if (values[i] < minRaw) minRaw = values[i];
    if (values[i] > maxRaw) maxRaw = values[i];
  }
  return maxRaw - minRaw;
}

uint32_t minValue(const uint32_t* values, size_t count) {
  if (values == nullptr || count == 0u) {
    return 0u;
  }
  uint32_t minRaw = values[0];
  for (size_t i = 1u; i < count; ++i) {
    if (values[i] < minRaw) minRaw = values[i];
  }
  return minRaw;
}

uint32_t maxValue(const uint32_t* values, size_t count) {
  if (values == nullptr || count == 0u) {
    return 0u;
  }
  uint32_t maxRaw = values[0];
  for (size_t i = 1u; i < count; ++i) {
    if (values[i] > maxRaw) maxRaw = values[i];
  }
  return maxRaw;
}

uint32_t worstDropRaw(int32_t primaryStart,
                      int32_t primaryEnd,
                      bool hasSecondary,
                      int32_t secondaryStart,
                      int32_t secondaryEnd) {
  const uint32_t primaryDrop = absDiff(primaryStart, primaryEnd);
  if (!hasSecondary) {
    return primaryDrop;
  }
  const uint32_t secondaryDrop = absDiff(secondaryStart, secondaryEnd);
  return (secondaryDrop > primaryDrop) ? secondaryDrop : primaryDrop;
}

BurstSummary summarizeBurstDrops(const uint32_t* drops,
                                 size_t count,
                                 uint32_t burstPeriodMs,
                                 uint32_t thresholdRaw) {
  BurstSummary summary{};
  if (drops == nullptr || count == 0u || burstPeriodMs == 0u) {
    return summary;
  }

  summary.maxDropRaw = maxValue(drops, count);
  summary.spanRaw = spanRaw(drops, count);
  summary.sealPassDurationMs = static_cast<uint32_t>(count) * burstPeriodMs;
  for (size_t i = 0u; i < count; ++i) {
    if (drops[i] > thresholdRaw) {
      summary.sealPassDurationMs = static_cast<uint32_t>(i) * burstPeriodMs;
      break;
    }
  }
  return summary;
}

}  // namespace GripperSealQualificationMath
