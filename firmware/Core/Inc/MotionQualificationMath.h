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

struct XyPoint {
  int32_t x = 0;
  int32_t y = 0;
};

struct XySafetyEnvelope {
  int32_t minX = 0;
  int32_t maxX = 45000;
  int32_t minY = 0;
  int32_t maxY = 35000;
  int32_t cableGuardX = 1000;
  int32_t cableGuardMinY = 500;
};

struct XyMotionStats {
  uint32_t repetitions = 0;
  uint32_t points = 0;
  uint32_t xReturnErrorMaxSteps = 0;
  uint32_t yReturnErrorMaxSteps = 0;
  uint32_t returnErrorMaxSteps = 0;
  uint32_t xDriftMaxSteps = 0;
  uint32_t yDriftMaxSteps = 0;
  uint32_t moveTimeoutCount = 0;
  uint32_t homeTimeoutCount = 0;
  uint32_t guardViolationCount = 0;
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

bool xyPointInBounds(const XyPoint& point, const XySafetyEnvelope& envelope);
bool xyPointPassesCableGuard(const XyPoint& point, const XySafetyEnvelope& envelope);
bool xyPointIsSafe(const XyPoint& point, const XySafetyEnvelope& envelope);
void recordXyMotionSample(XyMotionStats& stats,
                          int32_t startX,
                          int32_t startY,
                          int32_t returnX,
                          int32_t returnY,
                          int32_t referenceXLimit,
                          int32_t referenceYLimit,
                          const AxisHomeSample& xHome,
                          const AxisHomeSample& yHome,
                          bool moveCompleted,
                          bool boundViolation,
                          bool guardViolation);
bool xyMotionStatsPass(const XyMotionStats& stats);

}  // namespace MotionQualificationMath

#endif  // INC_MOTIONQUALIFICATIONMATH_H_
