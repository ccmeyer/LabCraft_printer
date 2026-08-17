#include "CoordinatedXyPlanner.h"

#include <algorithm>
#include <limits>

namespace CoordinatedXyPlanner {

namespace {

#if defined(__GNUC__) && !defined(UNIT_TEST)
#define LC_COORDINATED_EDGE_OPTIMIZED __attribute__((optimize("O2"), hot))
#else
#define LC_COORDINATED_EDGE_OPTIMIZED
#endif

constexpr uint64_t kNanosecondsPerSecond = 1000000000ULL;
// The ideal velocity-squared cosine period LUT has a worst piecewise-linear
// acceleration coefficient below 0.800 for every start/target period ratio
// in the planner's supported [1, 5] range. Use 7/8 (0.875) so phase sampling
// and integer ARR rounding retain explicit margin below the axis acceleration
// cap on the real timer sequence.
constexpr uint64_t kProfileAccelerationNumerator = 7u;
constexpr uint64_t kProfileAccelerationDenominator = 8u;

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

uint64_t requiredProfileRampEdges(uint32_t rateHz,
                                  uint32_t accelerationEdgesPerSec2) {
  const uint64_t rateSquared = static_cast<uint64_t>(rateHz) * rateHz;
  const uint64_t numerator =
      rateSquared * kProfileAccelerationNumerator;
  const uint64_t denominator =
      static_cast<uint64_t>(accelerationEdgesPerSec2) *
      kProfileAccelerationDenominator;
  return ceilDivide(numerator, denominator);
}

uint32_t maximumTriangularRate(uint32_t requestedRateHz,
                               uint32_t accelerationEdgesPerSec2,
                               uint32_t rampEdges) {
  uint32_t accepted = 0u;
  uint32_t low = 1u;
  uint32_t high = requestedRateHz;
  while (low <= high) {
    const uint32_t middle = low + ((high - low) / 2u);
    if (requiredProfileRampEdges(middle, accelerationEdgesPerSec2) <=
        rampEdges) {
      accepted = middle;
      if (middle == std::numeric_limits<uint32_t>::max()) break;
      low = middle + 1u;
    } else {
      if (middle == 0u) break;
      high = middle - 1u;
    }
  }
  return accepted;
}

uint64_t scaledMasterLimit(uint32_t axisLimit,
                           uint32_t masterEdges,
                           uint32_t axisEdges) {
  return (static_cast<uint64_t>(axisLimit) * masterEdges) / axisEdges;
}

uint32_t scaledComponent(uint32_t masterValue,
                         uint32_t axisEdges,
                         uint32_t masterEdges) {
  if (axisEdges == 0u) return 0u;
  return static_cast<uint32_t>(
      (static_cast<uint64_t>(masterValue) * axisEdges) / masterEdges);
}

LC_COORDINATED_EDGE_OPTIMIZED
bool planMatchesCursor(const CoordinatedXyPlan& plan, const Cursor& cursor) {
  return plan.status == PlanStatus::Ready &&
         cursor.expectedMasterEdges == plan.masterEdges &&
         cursor.expectedXEdges == plan.xEdges &&
         cursor.expectedYEdges == plan.yEdges;
}

LC_COORDINATED_EDGE_OPTIMIZED
EdgeMask nextMask(const CoordinatedXyPlan& plan, Cursor& cursor) {
  EdgeMask mask = EdgeMask::None;
  if (plan.xEdges != 0u) {
    cursor.xAccumulator += plan.ddaIncrementX;
    if (cursor.xAccumulator >= plan.ddaThreshold) {
      cursor.xAccumulator -= plan.ddaThreshold;
      mask = mask | EdgeMask::X;
    }
  }
  if (plan.yEdges != 0u) {
    cursor.yAccumulator += plan.ddaIncrementY;
    if (cursor.yAccumulator >= plan.ddaThreshold) {
      cursor.yAccumulator -= plan.ddaThreshold;
      mask = mask | EdgeMask::Y;
    }
  }
  return mask;
}

LC_COORDINATED_EDGE_OPTIMIZED
void primeEvent(const CoordinatedXyPlan& plan, Cursor& cursor) {
  EdgeEvent event{};
  event.masterEdgeIndex = cursor.completedMasterEdges;
  event.mask = nextMask(plan, cursor);

  if (event.masterEdgeIndex < plan.accelerationEdges) {
    event.phase = ProfilePhase::Acceleration;
    event.arr = NormalizedCosineProfile::currentArr(cursor.accelerationCursor);
  } else if (event.masterEdgeIndex <
             (plan.accelerationEdges + plan.cruiseEdges)) {
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
  if (!magnitudeOf(request.deltaX, plan.xEdges) ||
      !magnitudeOf(request.deltaY, plan.yEdges)) {
    plan.status = PlanStatus::OutOfRange;
    return plan.status;
  }

  plan.masterEdges = std::max(plan.xEdges, plan.yEdges);
  plan.ddaIncrementX = plan.xEdges;
  plan.ddaIncrementY = plan.yEdges;
  plan.ddaThreshold = plan.masterEdges;
  if (plan.masterEdges == 0u) {
    plan.status = PlanStatus::Immediate;
    return plan.status;
  }

  if ((plan.xEdges != 0u &&
       (request.xLimits.maxRateHz == 0u ||
        request.xLimits.accelerationEdgesPerSec2 == 0u)) ||
      (plan.yEdges != 0u &&
       (request.yLimits.maxRateHz == 0u ||
        request.yLimits.accelerationEdgesPerSec2 == 0u)) ||
      request.timer.inputClockHz == 0u ||
      request.timer.minEdgeIntervalNs == 0u) {
    plan.status = PlanStatus::InvalidLimits;
    return plan.status;
  }

  uint64_t rateCap = std::numeric_limits<uint64_t>::max();
  uint64_t accelerationCap = std::numeric_limits<uint64_t>::max();
  if (plan.xEdges != 0u) {
    rateCap = std::min(rateCap, scaledMasterLimit(
        request.xLimits.maxRateHz, plan.masterEdges, plan.xEdges));
    accelerationCap = std::min(accelerationCap, scaledMasterLimit(
        request.xLimits.accelerationEdgesPerSec2,
        plan.masterEdges,
        plan.xEdges));
  }
  if (plan.yEdges != 0u) {
    rateCap = std::min(rateCap, scaledMasterLimit(
        request.yLimits.maxRateHz, plan.masterEdges, plan.yEdges));
    accelerationCap = std::min(accelerationCap, scaledMasterLimit(
        request.yLimits.accelerationEdgesPerSec2,
        plan.masterEdges,
        plan.yEdges));
  }

  uint64_t minimumTicks = ceilDivide(
      static_cast<uint64_t>(request.timer.minEdgeIntervalNs) *
          request.timer.inputClockHz,
      kNanosecondsPerSecond);
  if (minimumTicks < 2u) minimumTicks = 2u;
  if (minimumTicks > static_cast<uint64_t>(request.timer.maxArr) + 1u) {
    plan.status = PlanStatus::InvalidLimits;
    return plan.status;
  }
  plan.minArr = static_cast<uint32_t>(minimumTicks - 1u);

  const uint64_t timerRateCap = request.timer.inputClockHz / minimumTicks;
  rateCap = std::min(rateCap, timerRateCap);
  if (rateCap == 0u || accelerationCap == 0u ||
      rateCap > std::numeric_limits<uint32_t>::max() ||
      accelerationCap > std::numeric_limits<uint32_t>::max()) {
    plan.status = PlanStatus::InvalidLimits;
    return plan.status;
  }

  plan.masterRateCapHz = static_cast<uint32_t>(rateCap);
  plan.masterAccelerationCapEdgesPerSec2 =
      static_cast<uint32_t>(accelerationCap);
  plan.masterAccelerationEdgesPerSec2 =
      plan.masterAccelerationCapEdgesPerSec2;
  plan.masterRateHz = request.requestedMasterRateHz == 0u
      ? plan.masterRateCapHz
      : std::min(request.requestedMasterRateHz, plan.masterRateCapHz);
  if (plan.masterRateHz == 0u) {
    plan.status = PlanStatus::InvalidLimits;
    return plan.status;
  }

  const uint64_t requestedAccelerationEdges =
      requiredProfileRampEdges(plan.masterRateHz,
                               plan.masterAccelerationEdgesPerSec2);

  if ((requestedAccelerationEdges * 2u) <= plan.masterEdges) {
    plan.accelerationEdges = static_cast<uint32_t>(requestedAccelerationEdges);
    plan.decelerationEdges = plan.accelerationEdges;
    plan.cruiseEdges = plan.masterEdges - plan.accelerationEdges -
                       plan.decelerationEdges;
  } else {
    plan.accelerationEdges = plan.masterEdges / 2u;
    plan.decelerationEdges = plan.accelerationEdges;
    plan.cruiseEdges = plan.masterEdges - plan.accelerationEdges -
                       plan.decelerationEdges;
    uint32_t peakRate = plan.accelerationEdges == 0u
        ? integerSquareRoot(plan.masterAccelerationEdgesPerSec2)
        : maximumTriangularRate(plan.masterRateHz,
                                plan.masterAccelerationEdgesPerSec2,
                                plan.accelerationEdges);
    if (peakRate == 0u) peakRate = 1u;
    plan.masterRateHz = std::min(peakRate, plan.masterRateCapHz);
    plan.triangular = true;
  }

  const uint64_t arrDenominator = static_cast<uint64_t>(plan.masterRateHz);
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
      plan.masterRateHz, plan.xEdges, plan.masterEdges);
  plan.yRateHz = scaledComponent(
      plan.masterRateHz, plan.yEdges, plan.masterEdges);
  plan.xAccelerationEdgesPerSec2 = scaledComponent(
      plan.masterAccelerationEdgesPerSec2, plan.xEdges, plan.masterEdges);
  plan.yAccelerationEdgesPerSec2 = scaledComponent(
      plan.masterAccelerationEdgesPerSec2, plan.yEdges, plan.masterEdges);

  plan.accelerationRamp = {
      plan.startArr,
      plan.targetArr,
      plan.minArr,
      request.timer.maxArr,
      plan.accelerationEdges,
  };
  plan.decelerationRamp = {
      plan.targetArr,
      plan.startArr,
      plan.minArr,
      request.timer.maxArr,
      plan.decelerationEdges,
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
  if (plan.status != PlanStatus::Ready || plan.masterEdges == 0u) {
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

  cursor.expectedMasterEdges = plan.masterEdges;
  cursor.expectedXEdges = plan.xEdges;
  cursor.expectedYEdges = plan.yEdges;
  cursor.xAccumulator = plan.masterEdges / 2u;
  cursor.yAccumulator = plan.masterEdges / 2u;
  cursor.active = true;
  primeEvent(plan, cursor);
  return TraceStatus::Ready;
}

LC_COORDINATED_EDGE_OPTIMIZED
TraceStatus currentEvent(const Cursor& cursor, EdgeEvent& event) {
  if (cursor.complete) return TraceStatus::Complete;
  if (!cursor.active) return TraceStatus::InvalidState;
  event = cursor.cachedEvent;
  return TraceStatus::Ready;
}

LC_COORDINATED_EDGE_OPTIMIZED
TraceStatus completeCurrentEdge(const CoordinatedXyPlan& plan, Cursor& cursor) {
  if (!cursor.active || cursor.complete || !planMatchesCursor(plan, cursor) ||
      cursor.cachedEvent.masterEdgeIndex != cursor.completedMasterEdges) {
    return TraceStatus::InvalidState;
  }

  const uint8_t eventMask = static_cast<uint8_t>(cursor.cachedEvent.mask);
  if ((eventMask & static_cast<uint8_t>(EdgeMask::X)) != 0u) {
    ++cursor.xEmittedEdges;
  }
  if ((eventMask & static_cast<uint8_t>(EdgeMask::Y)) != 0u) {
    ++cursor.yEmittedEdges;
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

  ++cursor.completedMasterEdges;
  if (cursor.completedMasterEdges >= plan.masterEdges) {
    if (cursor.xEmittedEdges != plan.xEdges ||
        cursor.yEmittedEdges != plan.yEdges ||
        (plan.accelerationEdges != 0u &&
         !NormalizedCosineProfile::atEndpoint(cursor.accelerationCursor)) ||
        (plan.decelerationEdges != 0u &&
         !NormalizedCosineProfile::atEndpoint(cursor.decelerationCursor))) {
      return TraceStatus::InvalidState;
    }
    cursor.cachedEvent = EdgeEvent{};
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

#undef LC_COORDINATED_EDGE_OPTIMIZED

}  // namespace CoordinatedXyPlanner
