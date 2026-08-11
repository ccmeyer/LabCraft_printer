#include "CoordinatedXyPlanner.h"

#include <algorithm>
#include <limits>

namespace CoordinatedXyPlanner {

namespace {

#if defined(__GNUC__) && !defined(UNIT_TEST)
#define LC_COORDINATED_STEP_OPTIMIZED __attribute__((optimize("O2"), hot))
#else
#define LC_COORDINATED_STEP_OPTIMIZED
#endif

constexpr uint64_t kNanosecondsPerSecond = 1000000000ULL;

bool magnitudeOf(int64_t value, uint32_t& magnitude) {
  if (value == std::numeric_limits<int64_t>::min()) {
    return false;
  }
  const uint64_t unsignedMagnitude = value < 0
      ? static_cast<uint64_t>(-value)
      : static_cast<uint64_t>(value);
  if (unsignedMagnitude > std::numeric_limits<uint32_t>::max()) {
    return false;
  }
  magnitude = static_cast<uint32_t>(unsignedMagnitude);
  return true;
}

Direction directionOf(int64_t value) {
  if (value < 0) return Direction::Negative;
  if (value > 0) return Direction::Positive;
  return Direction::Stationary;
}

uint64_t ceilDivide(uint64_t numerator, uint64_t denominator) {
  return (numerator / denominator) + ((numerator % denominator) != 0u ? 1u : 0u);
}

uint32_t integerSquareRoot(uint64_t value) {
  uint64_t remainder = value;
  uint64_t root = 0u;
  uint64_t bit = uint64_t{1u} << 62u;
  while (bit > remainder) {
    bit >>= 2u;
  }
  while (bit != 0u) {
    if (remainder >= root + bit) {
      remainder -= root + bit;
      root = (root >> 1u) + bit;
    } else {
      root >>= 1u;
    }
    bit >>= 2u;
  }
  return static_cast<uint32_t>(root);
}

uint64_t scaledMasterLimit(uint32_t axisLimit,
                           uint32_t masterSteps,
                           uint32_t axisSteps) {
  return (static_cast<uint64_t>(axisLimit) * masterSteps) / axisSteps;
}

uint32_t scaledComponent(uint32_t masterValue,
                         uint32_t axisSteps,
                         uint32_t masterSteps) {
  if (axisSteps == 0u) return 0u;
  return static_cast<uint32_t>(
      (static_cast<uint64_t>(masterValue) * axisSteps) / masterSteps);
}

LC_COORDINATED_STEP_OPTIMIZED
bool planMatchesCursor(const CoordinatedXyPlan& plan, const Cursor& cursor) {
  return plan.status == PlanStatus::Ready &&
         cursor.expectedMasterSteps == plan.masterSteps &&
         cursor.expectedXSteps == plan.xSteps &&
         cursor.expectedYSteps == plan.ySteps;
}

LC_COORDINATED_STEP_OPTIMIZED
StepMask nextMask(const CoordinatedXyPlan& plan, Cursor& cursor) {
  StepMask mask = StepMask::None;
  if (plan.xSteps != 0u) {
    cursor.xAccumulator += plan.ddaIncrementX;
    if (cursor.xAccumulator >= plan.ddaThreshold) {
      cursor.xAccumulator -= plan.ddaThreshold;
      mask = mask | StepMask::X;
    }
  }
  if (plan.ySteps != 0u) {
    cursor.yAccumulator += plan.ddaIncrementY;
    if (cursor.yAccumulator >= plan.ddaThreshold) {
      cursor.yAccumulator -= plan.ddaThreshold;
      mask = mask | StepMask::Y;
    }
  }
  return mask;
}

LC_COORDINATED_STEP_OPTIMIZED
void primeEvent(const CoordinatedXyPlan& plan, Cursor& cursor) {
  StepEvent event{};
  event.masterStepIndex = cursor.completedMasterSteps;
  event.mask = nextMask(plan, cursor);

  if (event.masterStepIndex < plan.accelerationSteps) {
    event.phase = ProfilePhase::Acceleration;
    event.arr = NormalizedCosineProfile::currentArr(cursor.accelerationCursor);
  } else if (event.masterStepIndex <
             (plan.accelerationSteps + plan.cruiseSteps)) {
    event.phase = ProfilePhase::Cruise;
    event.arr = plan.targetArr;
  } else {
    event.phase = ProfilePhase::Deceleration;
    event.arr = NormalizedCosineProfile::currentArr(cursor.decelerationCursor);
  }
  cursor.cachedEvent = event;
}

}  // namespace

PlanStatus prepare(const PlanRequest& request, CoordinatedXyPlan& plan) {
  plan = CoordinatedXyPlan{};
  plan.xDirection = directionOf(request.deltaX);
  plan.yDirection = directionOf(request.deltaY);

  if (request.deltaX == std::numeric_limits<int64_t>::min() ||
      request.deltaY == std::numeric_limits<int64_t>::min()) {
    plan.status = PlanStatus::ArithmeticOverflow;
    return plan.status;
  }
  if (!magnitudeOf(request.deltaX, plan.xSteps) ||
      !magnitudeOf(request.deltaY, plan.ySteps)) {
    plan.status = PlanStatus::OutOfRange;
    return plan.status;
  }

  plan.masterSteps = std::max(plan.xSteps, plan.ySteps);
  plan.ddaIncrementX = plan.xSteps;
  plan.ddaIncrementY = plan.ySteps;
  plan.ddaThreshold = plan.masterSteps;
  if (plan.masterSteps == 0u) {
    plan.status = PlanStatus::Immediate;
    return plan.status;
  }

  if ((plan.xSteps != 0u &&
       (request.xLimits.maxRateHz == 0u ||
        request.xLimits.accelerationStepsPerSec2 == 0u)) ||
      (plan.ySteps != 0u &&
       (request.yLimits.maxRateHz == 0u ||
        request.yLimits.accelerationStepsPerSec2 == 0u)) ||
      request.timer.inputClockHz == 0u ||
      request.timer.minPulseNs == 0u) {
    plan.status = PlanStatus::InvalidLimits;
    return plan.status;
  }

  uint64_t rateCap = std::numeric_limits<uint64_t>::max();
  uint64_t accelerationCap = std::numeric_limits<uint64_t>::max();
  if (plan.xSteps != 0u) {
    rateCap = std::min(rateCap, scaledMasterLimit(
        request.xLimits.maxRateHz, plan.masterSteps, plan.xSteps));
    accelerationCap = std::min(accelerationCap, scaledMasterLimit(
        request.xLimits.accelerationStepsPerSec2,
        plan.masterSteps,
        plan.xSteps));
  }
  if (plan.ySteps != 0u) {
    rateCap = std::min(rateCap, scaledMasterLimit(
        request.yLimits.maxRateHz, plan.masterSteps, plan.ySteps));
    accelerationCap = std::min(accelerationCap, scaledMasterLimit(
        request.yLimits.accelerationStepsPerSec2,
        plan.masterSteps,
        plan.ySteps));
  }

  uint64_t minimumTicks = ceilDivide(
      static_cast<uint64_t>(request.timer.minPulseNs) *
          request.timer.inputClockHz,
      kNanosecondsPerSecond);
  if (minimumTicks < 2u) minimumTicks = 2u;
  if (minimumTicks > static_cast<uint64_t>(request.timer.maxArr) + 1u) {
    plan.status = PlanStatus::InvalidLimits;
    return plan.status;
  }
  plan.minArr = static_cast<uint32_t>(minimumTicks - 1u);

  const uint64_t timerDenominator = 2u * minimumTicks;
  const uint64_t timerRateCap = request.timer.inputClockHz / timerDenominator;
  rateCap = std::min(rateCap, timerRateCap);
  if (rateCap == 0u || accelerationCap == 0u ||
      rateCap > std::numeric_limits<uint32_t>::max() ||
      accelerationCap > std::numeric_limits<uint32_t>::max()) {
    plan.status = PlanStatus::InvalidLimits;
    return plan.status;
  }

  plan.masterRateCapHz = static_cast<uint32_t>(rateCap);
  plan.masterAccelerationCapStepsPerSec2 =
      static_cast<uint32_t>(accelerationCap);
  plan.masterAccelerationStepsPerSec2 =
      plan.masterAccelerationCapStepsPerSec2;
  plan.masterRateHz = request.requestedMasterRateHz == 0u
      ? plan.masterRateCapHz
      : std::min(request.requestedMasterRateHz, plan.masterRateCapHz);
  if (plan.masterRateHz == 0u) {
    plan.status = PlanStatus::InvalidLimits;
    return plan.status;
  }

  const uint64_t rateSquared =
      static_cast<uint64_t>(plan.masterRateHz) * plan.masterRateHz;
  const uint64_t twiceAcceleration =
      static_cast<uint64_t>(plan.masterAccelerationStepsPerSec2) * 2u;
  const uint64_t requestedAccelerationSteps =
      ceilDivide(rateSquared, twiceAcceleration);

  if ((requestedAccelerationSteps * 2u) <= plan.masterSteps) {
    plan.accelerationSteps = static_cast<uint32_t>(requestedAccelerationSteps);
    plan.decelerationSteps = plan.accelerationSteps;
    plan.cruiseSteps = plan.masterSteps - plan.accelerationSteps -
                       plan.decelerationSteps;
  } else {
    const uint64_t peakProduct =
        static_cast<uint64_t>(plan.masterSteps) *
        plan.masterAccelerationStepsPerSec2;
    uint32_t peakRate = integerSquareRoot(peakProduct);
    if (peakRate == 0u) peakRate = 1u;
    plan.masterRateHz = std::min(peakRate, plan.masterRateCapHz);
    plan.accelerationSteps = plan.masterSteps / 2u;
    plan.decelerationSteps = plan.accelerationSteps;
    plan.cruiseSteps = plan.masterSteps - plan.accelerationSteps -
                       plan.decelerationSteps;
    plan.triangular = true;
  }

  const uint64_t arrDenominator =
      static_cast<uint64_t>(plan.masterRateHz) * 2u;
  const uint64_t arrPlusOne = request.timer.inputClockHz / arrDenominator;
  if (arrPlusOne < 2u) {
    plan.status = PlanStatus::InvalidLimits;
    return plan.status;
  }
  const uint64_t targetArr = arrPlusOne - 1u;
  if (targetArr < plan.minArr) {
    plan.status = PlanStatus::InvalidLimits;
    return plan.status;
  }
  if (targetArr > request.timer.maxArr) {
    plan.status = PlanStatus::OutOfRange;
    return plan.status;
  }

  plan.timer = request.timer;
  plan.targetArr = static_cast<uint32_t>(targetArr);
  plan.startArr = static_cast<uint32_t>(std::min<uint64_t>(
      static_cast<uint64_t>(plan.targetArr) * 5u,
      request.timer.maxArr));
  if (plan.startArr < plan.minArr) plan.startArr = plan.minArr;

  plan.xRateHz = scaledComponent(
      plan.masterRateHz, plan.xSteps, plan.masterSteps);
  plan.yRateHz = scaledComponent(
      plan.masterRateHz, plan.ySteps, plan.masterSteps);
  plan.xAccelerationStepsPerSec2 = scaledComponent(
      plan.masterAccelerationStepsPerSec2, plan.xSteps, plan.masterSteps);
  plan.yAccelerationStepsPerSec2 = scaledComponent(
      plan.masterAccelerationStepsPerSec2, plan.ySteps, plan.masterSteps);

  plan.accelerationRamp = {
      plan.startArr,
      plan.targetArr,
      plan.minArr,
      request.timer.maxArr,
      plan.accelerationSteps,
  };
  plan.decelerationRamp = {
      plan.targetArr,
      plan.startArr,
      plan.minArr,
      request.timer.maxArr,
      plan.decelerationSteps,
  };
  plan.status = PlanStatus::Ready;
  return plan.status;
}

TraceStatus begin(const CoordinatedXyPlan& plan, Cursor& cursor) {
  if (cursor.active) return TraceStatus::Busy;
  cursor = Cursor{};
  if (plan.status == PlanStatus::Immediate) {
    cursor.complete = true;
    return TraceStatus::Complete;
  }
  if (plan.status != PlanStatus::Ready || plan.masterSteps == 0u) {
    return TraceStatus::InvalidPlan;
  }

  const NormalizedCosineProfile::PrepareStatus accelerationStatus =
      NormalizedCosineProfile::prepare(
          plan.accelerationRamp, cursor.accelerationCursor);
  const NormalizedCosineProfile::PrepareStatus decelerationStatus =
      NormalizedCosineProfile::prepare(
          plan.decelerationRamp, cursor.decelerationCursor);
  if (accelerationStatus == NormalizedCosineProfile::PrepareStatus::InvalidBounds ||
      decelerationStatus == NormalizedCosineProfile::PrepareStatus::InvalidBounds) {
    cursor = Cursor{};
    return TraceStatus::InvalidPlan;
  }

  cursor.expectedMasterSteps = plan.masterSteps;
  cursor.expectedXSteps = plan.xSteps;
  cursor.expectedYSteps = plan.ySteps;
  cursor.xAccumulator = plan.masterSteps / 2u;
  cursor.yAccumulator = plan.masterSteps / 2u;
  cursor.active = true;
  primeEvent(plan, cursor);
  return TraceStatus::Ready;
}

LC_COORDINATED_STEP_OPTIMIZED
TraceStatus currentEvent(const Cursor& cursor, StepEvent& event) {
  if (cursor.complete) return TraceStatus::Complete;
  if (!cursor.active) return TraceStatus::InvalidState;
  event = cursor.cachedEvent;
  return TraceStatus::Ready;
}

LC_COORDINATED_STEP_OPTIMIZED
TraceStatus completeCurrentStep(const CoordinatedXyPlan& plan, Cursor& cursor) {
  if (!cursor.active || cursor.complete || !planMatchesCursor(plan, cursor) ||
      cursor.cachedEvent.masterStepIndex != cursor.completedMasterSteps) {
    return TraceStatus::InvalidState;
  }

  const uint8_t eventMask = static_cast<uint8_t>(cursor.cachedEvent.mask);
  if ((eventMask & static_cast<uint8_t>(StepMask::X)) != 0u) {
    ++cursor.xEmittedSteps;
  }
  if ((eventMask & static_cast<uint8_t>(StepMask::Y)) != 0u) {
    ++cursor.yEmittedSteps;
  }

  if (cursor.cachedEvent.phase == ProfilePhase::Acceleration) {
    if (!NormalizedCosineProfile::advance(cursor.accelerationCursor)) {
      return TraceStatus::InvalidState;
    }
  } else if (cursor.cachedEvent.phase == ProfilePhase::Deceleration) {
    if (!NormalizedCosineProfile::advance(cursor.decelerationCursor)) {
      return TraceStatus::InvalidState;
    }
  }

  ++cursor.completedMasterSteps;
  if (cursor.completedMasterSteps >= plan.masterSteps) {
    if (cursor.xEmittedSteps != plan.xSteps ||
        cursor.yEmittedSteps != plan.ySteps ||
        (plan.accelerationSteps != 0u &&
         !NormalizedCosineProfile::atEndpoint(cursor.accelerationCursor)) ||
        (plan.decelerationSteps != 0u &&
         !NormalizedCosineProfile::atEndpoint(cursor.decelerationCursor))) {
      return TraceStatus::InvalidState;
    }
    cursor.cachedEvent = StepEvent{};
    cursor.active = false;
    cursor.complete = true;
    return TraceStatus::Complete;
  }

  primeEvent(plan, cursor);
  return TraceStatus::Ready;
}

bool isComplete(const Cursor& cursor) {
  return cursor.complete;
}

#undef LC_COORDINATED_STEP_OPTIMIZED

}  // namespace CoordinatedXyPlanner
