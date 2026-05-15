#ifndef INC_PRESSUREQUALIFICATIONMATH_H_
#define INC_PRESSUREQUALIFICATIONMATH_H_

#include <cstddef>
#include <cstdint>

namespace PressureQualificationMath {

struct Int32Span {
  uint32_t sampleCount = 0;
  int32_t minValue = 0;
  int32_t maxValue = 0;
  uint32_t span = 0;
};

struct ExecutionSummary {
  uint32_t readyMissCount = 0;
  uint32_t timeoutCount = 0;
  uint32_t abortCount = 0;
};

uint32_t absDiff(int32_t a, int32_t b);
constexpr uint16_t pressureRawFromPsiMilli(uint32_t psiMilli)
{
  return static_cast<uint16_t>(1638u + ((psiMilli * 13107u + 7500u) / 15000u));
}
int32_t slopeRawPerMin(int32_t startRaw, int32_t endRaw, uint32_t durationMs);
Int32Span summarizeInt32Span(const int32_t* values, size_t count);
uint32_t meanDifferenceAbs(const int32_t* a, size_t aCount, const int32_t* b, size_t bCount);
bool executionPass(const ExecutionSummary& summary);

}  // namespace PressureQualificationMath

#endif  // INC_PRESSUREQUALIFICATIONMATH_H_
