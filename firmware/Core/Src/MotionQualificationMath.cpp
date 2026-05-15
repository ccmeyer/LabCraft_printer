#include "MotionQualificationMath.h"

namespace MotionQualificationMath {

uint32_t absDiffSteps(int32_t a, int32_t b)
{
  const int64_t diff = static_cast<int64_t>(a) - static_cast<int64_t>(b);
  return static_cast<uint32_t>((diff < 0) ? -diff : diff);
}

AxisHomeStats summarizeAxisHomeSamples(const AxisHomeSample* samples,
                                       size_t sampleCount,
                                       int32_t expectedBackoffSteps)
{
  AxisHomeStats stats{};
  if ((samples == nullptr) || (sampleCount == 0u)) {
    stats.homeTimeoutCount = static_cast<uint32_t>(sampleCount);
    return stats;
  }

  bool haveLimit = false;
  for (size_t idx = 0; idx < sampleCount; ++idx) {
    const AxisHomeSample& sample = samples[idx];
    stats.sampleCount++;
    stats.moveTimeoutCount += sample.moveTimeoutCount;
    if (!sample.success) {
      stats.homeTimeoutCount++;
    }
    if (!haveLimit) {
      stats.limitTriggerMinSteps = sample.limitTriggerSteps;
      stats.limitTriggerMaxSteps = sample.limitTriggerSteps;
      haveLimit = true;
    } else {
      if (sample.limitTriggerSteps < stats.limitTriggerMinSteps) {
        stats.limitTriggerMinSteps = sample.limitTriggerSteps;
      }
      if (sample.limitTriggerSteps > stats.limitTriggerMaxSteps) {
        stats.limitTriggerMaxSteps = sample.limitTriggerSteps;
      }
    }
    const uint32_t returnError = absDiffSteps(sample.finalBackoffSteps, expectedBackoffSteps);
    if (returnError > stats.returnErrorMaxSteps) {
      stats.returnErrorMaxSteps = returnError;
    }
  }
  stats.limitTriggerSpanSteps = absDiffSteps(stats.limitTriggerMaxSteps, stats.limitTriggerMinSteps);
  return stats;
}

void recordPatternReturn(PatternReturnStats& stats,
                         int32_t startX,
                         int32_t startY,
                         int32_t returnX,
                         int32_t returnY,
                         bool moveCompleted,
                         bool homeCompleted,
                         bool boundViolation)
{
  const uint32_t xError = absDiffSteps(returnX, startX);
  const uint32_t yError = absDiffSteps(returnY, startY);
  if (xError > stats.xReturnErrorMaxSteps) {
    stats.xReturnErrorMaxSteps = xError;
  }
  if (yError > stats.yReturnErrorMaxSteps) {
    stats.yReturnErrorMaxSteps = yError;
  }
  const uint32_t worst = (xError > yError) ? xError : yError;
  if (worst > stats.returnErrorMaxSteps) {
    stats.returnErrorMaxSteps = worst;
  }
  if (!moveCompleted) {
    stats.moveTimeoutCount++;
  }
  if (!homeCompleted) {
    stats.homeTimeoutCount++;
  }
  if (boundViolation) {
    stats.boundViolationCount++;
  }
}

bool axisHomeStatsPass(const AxisHomeStats& stats, uint32_t expectedSamples)
{
  return (stats.sampleCount == expectedSamples) &&
         (stats.moveTimeoutCount == 0u) &&
         (stats.homeTimeoutCount == 0u);
}

bool patternReturnStatsPass(const PatternReturnStats& stats)
{
  return (stats.moveTimeoutCount == 0u) &&
         (stats.homeTimeoutCount == 0u) &&
         (stats.boundViolationCount == 0u);
}

bool xyPointInBounds(const XyPoint& point, const XySafetyEnvelope& envelope)
{
  return (point.x >= envelope.minX) &&
         (point.x <= envelope.maxX) &&
         (point.y >= envelope.minY) &&
         (point.y <= envelope.maxY);
}

bool xyPointPassesCableGuard(const XyPoint& point, const XySafetyEnvelope& envelope)
{
  return (point.x <= envelope.cableGuardX) || (point.y >= envelope.cableGuardMinY);
}

bool xyPointIsSafe(const XyPoint& point, const XySafetyEnvelope& envelope)
{
  return xyPointInBounds(point, envelope) && xyPointPassesCableGuard(point, envelope);
}

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
                          bool guardViolation)
{
  const uint32_t xReturnError = absDiffSteps(returnX, startX);
  const uint32_t yReturnError = absDiffSteps(returnY, startY);
  if (xReturnError > stats.xReturnErrorMaxSteps) {
    stats.xReturnErrorMaxSteps = xReturnError;
  }
  if (yReturnError > stats.yReturnErrorMaxSteps) {
    stats.yReturnErrorMaxSteps = yReturnError;
  }
  const uint32_t worstReturn = (xReturnError > yReturnError) ? xReturnError : yReturnError;
  if (worstReturn > stats.returnErrorMaxSteps) {
    stats.returnErrorMaxSteps = worstReturn;
  }

  const uint32_t xDrift = absDiffSteps(xHome.limitTriggerSteps, referenceXLimit);
  const uint32_t yDrift = absDiffSteps(yHome.limitTriggerSteps, referenceYLimit);
  if (xDrift > stats.xDriftMaxSteps) {
    stats.xDriftMaxSteps = xDrift;
  }
  if (yDrift > stats.yDriftMaxSteps) {
    stats.yDriftMaxSteps = yDrift;
  }

  if (!moveCompleted) {
    stats.moveTimeoutCount++;
  }
  stats.moveTimeoutCount += xHome.moveTimeoutCount + yHome.moveTimeoutCount;
  if (!xHome.success || !yHome.success) {
    stats.homeTimeoutCount++;
  }
  if (boundViolation) {
    stats.boundViolationCount++;
  }
  if (guardViolation) {
    stats.guardViolationCount++;
  }
}

bool xyMotionStatsPass(const XyMotionStats& stats)
{
  return (stats.moveTimeoutCount == 0u) &&
         (stats.homeTimeoutCount == 0u) &&
         (stats.guardViolationCount == 0u) &&
         (stats.boundViolationCount == 0u);
}

}  // namespace MotionQualificationMath
