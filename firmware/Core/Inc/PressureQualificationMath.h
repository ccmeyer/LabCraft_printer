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
  uint32_t motorGuardCount = 0;
};

struct MotorTravelGuardLimits {
  uint32_t absoluteLimitSteps = 0;
  uint32_t transitionLimitSteps = 0;
};

struct MotorTravelGuardState {
  uint32_t motorAbsMax = 0;
  uint32_t motorDeltaMax = 0;
  bool guardAbs = false;
  bool guardDelta = false;
};

uint32_t absDiff(int32_t a, int32_t b);
constexpr uint16_t pressureRawFromPsiMilli(uint32_t psiMilli)
{
  return static_cast<uint16_t>(1638u + ((psiMilli * 13107u + 7500u) / 15000u));
}
int32_t slopeRawPerMin(int32_t startRaw, int32_t endRaw, uint32_t durationMs);
size_t buildAdjacentTargetSequence(int32_t currentRaw,
                                   int32_t targetRaw,
                                   uint32_t maxDeltaRaw,
                                   int32_t* outTargets,
                                   size_t capacity);
bool updateMotorTravelGuard(int32_t position,
                            int32_t transitionStartPosition,
                            const MotorTravelGuardLimits& limits,
                            MotorTravelGuardState& state);
Int32Span summarizeInt32Span(const int32_t* values, size_t count);
uint32_t meanDifferenceAbs(const int32_t* a, size_t aCount, const int32_t* b, size_t bCount);
bool executionPass(const ExecutionSummary& summary);

}  // namespace PressureQualificationMath

#endif  // INC_PRESSUREQUALIFICATIONMATH_H_
