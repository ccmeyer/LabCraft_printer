#include "PressureQualificationMath.h"

namespace PressureQualificationMath {

uint32_t absDiff(int32_t a, int32_t b)
{
  const int64_t diff = static_cast<int64_t>(a) - static_cast<int64_t>(b);
  return static_cast<uint32_t>((diff < 0) ? -diff : diff);
}

int32_t slopeRawPerMin(int32_t startRaw, int32_t endRaw, uint32_t durationMs)
{
  if (durationMs == 0u) {
    return 0;
  }
  const int64_t delta = static_cast<int64_t>(endRaw) - static_cast<int64_t>(startRaw);
  return static_cast<int32_t>((delta * 60000LL) / static_cast<int64_t>(durationMs));
}

size_t buildAdjacentTargetSequence(int32_t currentRaw,
                                   int32_t targetRaw,
                                   uint32_t maxDeltaRaw,
                                   int32_t* outTargets,
                                   size_t capacity)
{
  if ((outTargets == nullptr) || (capacity == 0u) || (currentRaw == targetRaw)) {
    return 0u;
  }

  if (maxDeltaRaw == 0u) {
    outTargets[0] = targetRaw;
    return 1u;
  }

  size_t count = 0u;
  int32_t current = currentRaw;
  while ((current != targetRaw) && (count < capacity)) {
    const int64_t remaining = static_cast<int64_t>(targetRaw) - static_cast<int64_t>(current);
    const int64_t absRemaining = (remaining < 0) ? -remaining : remaining;
    if (absRemaining <= static_cast<int64_t>(maxDeltaRaw)) {
      current = targetRaw;
    } else if (remaining > 0) {
      current += static_cast<int32_t>(maxDeltaRaw);
    } else {
      current -= static_cast<int32_t>(maxDeltaRaw);
    }
    outTargets[count++] = current;
  }
  return count;
}

bool updateMotorTravelGuard(int32_t position,
                            int32_t transitionStartPosition,
                            const MotorTravelGuardLimits& limits,
                            MotorTravelGuardState& state)
{
  const uint32_t absPosition = absDiff(position, 0);
  const uint32_t transitionDelta = absDiff(position, transitionStartPosition);
  if (absPosition > state.motorAbsMax) {
    state.motorAbsMax = absPosition;
  }
  if (transitionDelta > state.motorDeltaMax) {
    state.motorDeltaMax = transitionDelta;
  }
  if ((limits.absoluteLimitSteps > 0u) && (absPosition >= limits.absoluteLimitSteps)) {
    state.guardAbs = true;
  }
  if ((limits.transitionLimitSteps > 0u) && (transitionDelta >= limits.transitionLimitSteps)) {
    state.guardDelta = true;
  }
  return state.guardAbs || state.guardDelta;
}

Int32Span summarizeInt32Span(const int32_t* values, size_t count)
{
  Int32Span span{};
  if ((values == nullptr) || (count == 0u)) {
    return span;
  }

  span.sampleCount = static_cast<uint32_t>(count);
  span.minValue = values[0];
  span.maxValue = values[0];
  for (size_t idx = 1; idx < count; ++idx) {
    if (values[idx] < span.minValue) {
      span.minValue = values[idx];
    }
    if (values[idx] > span.maxValue) {
      span.maxValue = values[idx];
    }
  }
  span.span = absDiff(span.maxValue, span.minValue);
  return span;
}

uint32_t driftFromInt32Samples(const int32_t* values, size_t count)
{
  if ((values == nullptr) || (count == 0u)) {
    return 0u;
  }
  return absDiff(values[0], values[count - 1u]);
}

HomeRepeatabilitySummary summarizeHomeRepeatability(const int32_t* successfulPositions,
                                                    size_t successfulCount,
                                                    uint32_t expectedCount,
                                                    uint32_t moveTimeoutCount,
                                                    uint32_t homeTimeoutCount)
{
  HomeRepeatabilitySummary summary{};
  summary.expectedCount = expectedCount;
  summary.sampleCount = static_cast<uint32_t>(successfulCount);
  summary.missingCount = (expectedCount > summary.sampleCount) ? (expectedCount - summary.sampleCount) : 0u;
  summary.moveTimeoutCount = moveTimeoutCount;
  summary.homeTimeoutCount = homeTimeoutCount;

  const Int32Span span = summarizeInt32Span(successfulPositions, successfulCount);
  summary.span = span.span;
  summary.drift = driftFromInt32Samples(successfulPositions, successfulCount);
  summary.pass = (summary.sampleCount == expectedCount) &&
                 (summary.moveTimeoutCount == 0u) &&
                 (summary.homeTimeoutCount == 0u);
  return summary;
}

uint32_t meanDifferenceAbs(const int32_t* a, size_t aCount, const int32_t* b, size_t bCount)
{
  if ((a == nullptr) || (b == nullptr) || (aCount == 0u) || (bCount == 0u)) {
    return 0u;
  }

  int64_t sumA = 0;
  for (size_t idx = 0; idx < aCount; ++idx) {
    sumA += static_cast<int64_t>(a[idx]);
  }
  int64_t sumB = 0;
  for (size_t idx = 0; idx < bCount; ++idx) {
    sumB += static_cast<int64_t>(b[idx]);
  }

  const int64_t meanA = sumA / static_cast<int64_t>(aCount);
  const int64_t meanB = sumB / static_cast<int64_t>(bCount);
  const int64_t diff = meanA - meanB;
  return static_cast<uint32_t>((diff < 0) ? -diff : diff);
}

bool executionPass(const ExecutionSummary& summary)
{
  return (summary.readyMissCount == 0u) &&
         (summary.timeoutCount == 0u) &&
         (summary.abortCount == 0u) &&
         (summary.motorGuardCount == 0u);
}

}  // namespace PressureQualificationMath
