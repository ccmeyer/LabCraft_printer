#ifndef INC_GRIPPERSEALQUALIFICATIONMATH_H_
#define INC_GRIPPERSEALQUALIFICATIONMATH_H_

#include <cstddef>
#include <cstdint>

namespace GripperSealQualificationMath {

struct DecaySummary {
  uint32_t dropRaw = 0;
  int32_t slopeRawPerMin = 0;
  uint32_t timeToThresholdMs = 0;
  uint32_t sealPassDurationMs = 0;
};

struct BurstSummary {
  uint32_t maxDropRaw = 0;
  uint32_t spanRaw = 0;
  uint32_t sealPassDurationMs = 0;
};

uint32_t absDiff(int32_t a, int32_t b);
int32_t slopeRawPerMin(int32_t startRaw, int32_t endRaw, uint32_t durationMs);
DecaySummary summarizeDecay(int32_t startRaw,
                            int32_t endRaw,
                            uint32_t holdMs,
                            uint32_t thresholdCrossMs,
                            uint32_t thresholdRaw);
uint32_t spanRaw(const uint32_t* values, size_t count);
uint32_t minValue(const uint32_t* values, size_t count);
uint32_t maxValue(const uint32_t* values, size_t count);
uint32_t worstDropRaw(int32_t primaryStart,
                      int32_t primaryEnd,
                      bool hasSecondary,
                      int32_t secondaryStart,
                      int32_t secondaryEnd);
BurstSummary summarizeBurstDrops(const uint32_t* drops,
                                 size_t count,
                                 uint32_t burstPeriodMs,
                                 uint32_t thresholdRaw);

}  // namespace GripperSealQualificationMath

#endif  // INC_GRIPPERSEALQUALIFICATIONMATH_H_
