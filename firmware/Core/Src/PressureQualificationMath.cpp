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
         (summary.abortCount == 0u);
}

}  // namespace PressureQualificationMath
