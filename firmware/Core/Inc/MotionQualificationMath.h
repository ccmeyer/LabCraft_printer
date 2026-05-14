#ifndef INC_MOTIONQUALIFICATIONMATH_H_
#define INC_MOTIONQUALIFICATIONMATH_H_

#include <cstddef>
#include <cstdint>

namespace MotionQualificationMath {

struct AxisHomeSample {
  bool success = false;
  int32_t limitTriggerSteps = 0;
  int32_t finalBackoffSteps = 0;
  uint32_t moveTimeoutCount = 0;
};

struct AxisHomeStats {
  uint32_t sampleCount = 0;
  int32_t limitTriggerMinSteps = 0;
  int32_t limitTriggerMaxSteps = 0;
  uint32_t limitTriggerSpanSteps = 0;
  uint32_t returnErrorMaxSteps = 0;
  uint32_t moveTimeoutCount = 0;
  uint32_t homeTimeoutCount = 0;
};

struct PatternReturnStats {
  uint32_t repetitions = 0;
  uint32_t patternPoints = 0;
  uint32_t returnErrorMaxSteps = 0;
  uint32_t xReturnErrorMaxSteps = 0;
  uint32_t yReturnErrorMaxSteps = 0;
  uint32_t moveTimeoutCount = 0;
  uint32_t homeTimeoutCount = 0;
  uint32_t boundViolationCount = 0;
};

uint32_t absDiffSteps(int32_t a, int32_t b);

AxisHomeStats summarizeAxisHomeSamples(const AxisHomeSample* samples,
                                       size_t sampleCount,
                                       int32_t expectedBackoffSteps);

void recordPatternReturn(PatternReturnStats& stats,
                         int32_t startX,
                         int32_t startY,
                         int32_t returnX,
                         int32_t returnY,
                         bool moveCompleted,
                         bool homeCompleted,
                         bool boundViolation);

bool axisHomeStatsPass(const AxisHomeStats& stats, uint32_t expectedSamples);
bool patternReturnStatsPass(const PatternReturnStats& stats);

}  // namespace MotionQualificationMath

#endif  // INC_MOTIONQUALIFICATIONMATH_H_
