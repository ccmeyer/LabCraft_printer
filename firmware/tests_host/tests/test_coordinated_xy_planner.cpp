#include "CoordinatedXyPlanner.h"
#include "CppUTest/TestHarness.h"

#include <algorithm>
#include <cstdint>
#include <limits>
#include <utility>
#include <vector>

namespace {

using namespace CoordinatedXyPlanner;

PlanRequest normalRequest(int64_t dx, int64_t dy) {
  PlanRequest request{};
  request.deltaX = dx;
  request.deltaY = dy;
  request.xLimits = {40000u, 140000u};
  request.yLimits = {40000u, 140000u};
  request.timer = {
      90000000u,
      std::numeric_limits<uint32_t>::max(),
      2000u,
  };
  return request;
}

CoordinatedXyPlan readyPlan(const PlanRequest& request) {
  CoordinatedXyPlan plan{};
  CHECK_EQUAL(static_cast<int>(PlanStatus::Ready),
              static_cast<int>(prepare(request, plan)));
  return plan;
}

uint64_t absoluteDifference(uint64_t lhs, uint64_t rhs) {
  return lhs >= rhs ? lhs - rhs : rhs - lhs;
}

uint64_t pathErrorNumerator(uint32_t emitted,
                            uint32_t completedMasterSteps,
                            uint32_t axisSteps,
                            uint32_t masterSteps) {
  return absoluteDifference(
      static_cast<uint64_t>(emitted) * masterSteps,
      static_cast<uint64_t>(completedMasterSteps) * axisSteps);
}

std::vector<StepEvent> runTrace(const CoordinatedXyPlan& plan,
                                Cursor* finishedCursor = nullptr) {
  std::vector<StepEvent> events;
  Cursor cursor{};
  const TraceStatus beginStatus = begin(plan, cursor);
  if (plan.status == PlanStatus::Immediate) {
    CHECK_EQUAL(static_cast<int>(TraceStatus::Complete),
                static_cast<int>(beginStatus));
    CHECK_TRUE(isComplete(cursor));
    if (finishedCursor != nullptr) *finishedCursor = cursor;
    return events;
  }

  CHECK_EQUAL(static_cast<int>(TraceStatus::Ready),
              static_cast<int>(beginStatus));
  while (!isComplete(cursor)) {
    StepEvent event{};
    CHECK_EQUAL(static_cast<int>(TraceStatus::Ready),
                static_cast<int>(currentEvent(cursor, event)));
    events.push_back(event);
    const TraceStatus status = completeCurrentStep(plan, cursor);
    if (events.size() == plan.masterSteps) {
      CHECK_EQUAL(static_cast<int>(TraceStatus::Complete),
                  static_cast<int>(status));
    } else {
      CHECK_EQUAL(static_cast<int>(TraceStatus::Ready),
                  static_cast<int>(status));
    }
  }

  UNSIGNED_LONGS_EQUAL(plan.masterSteps,
                       static_cast<uint32_t>(events.size()));
  UNSIGNED_LONGS_EQUAL(plan.xSteps, cursor.xEmittedSteps);
  UNSIGNED_LONGS_EQUAL(plan.ySteps, cursor.yEmittedSteps);
  if (finishedCursor != nullptr) *finishedCursor = cursor;
  return events;
}

void checkPathAtEveryPrefix(const CoordinatedXyPlan& plan) {
  Cursor cursor{};
  CHECK_EQUAL(static_cast<int>(TraceStatus::Ready),
              static_cast<int>(begin(plan, cursor)));
  while (!isComplete(cursor)) {
    const TraceStatus status = completeCurrentStep(plan, cursor);
    const uint64_t bound = plan.masterSteps / 2u;
    CHECK_TRUE(pathErrorNumerator(cursor.xEmittedSteps,
                                  cursor.completedMasterSteps,
                                  plan.xSteps,
                                  plan.masterSteps) <= bound);
    CHECK_TRUE(pathErrorNumerator(cursor.yEmittedSteps,
                                  cursor.completedMasterSteps,
                                  plan.ySteps,
                                  plan.masterSteps) <= bound);
    CHECK_TRUE(cursor.xAccumulator < plan.masterSteps);
    CHECK_TRUE(cursor.yAccumulator < plan.masterSteps);
    CHECK_TRUE(status == TraceStatus::Ready ||
               status == TraceStatus::Complete);
  }
  UNSIGNED_LONGS_EQUAL(plan.xSteps, cursor.xEmittedSteps);
  UNSIGNED_LONGS_EQUAL(plan.ySteps, cursor.yEmittedSteps);
}

void checkSameEvent(const StepEvent& lhs, const StepEvent& rhs) {
  UNSIGNED_LONGS_EQUAL(lhs.masterStepIndex, rhs.masterStepIndex);
  CHECK_EQUAL(static_cast<int>(lhs.mask), static_cast<int>(rhs.mask));
  UNSIGNED_LONGS_EQUAL(lhs.arr, rhs.arr);
  CHECK_EQUAL(static_cast<int>(lhs.phase), static_cast<int>(rhs.phase));
}

int32_t interpolateEndpoint(int32_t start,
                            int32_t end,
                            uint32_t index,
                            uint32_t count) {
  if (count <= 1u || index == 0u) return start;
  if (index >= count - 1u) return end;
  const int64_t delta = static_cast<int64_t>(end) - start;
  const int64_t denominator = static_cast<int64_t>(count - 1u);
  const int64_t numerator = delta * index;
  const int64_t rounded = numerator >= 0
      ? (numerator + denominator / 2) / denominator
      : (numerator - denominator / 2) / denominator;
  return static_cast<int32_t>(static_cast<int64_t>(start) + rounded);
}

}  // namespace

TEST_GROUP(CoordinatedXyPlanner) {
};

TEST(CoordinatedXyPlanner, ZeroMoveAndInvalidRequestsHaveExplicitResults) {
  CoordinatedXyPlan plan{};
  PlanRequest request{};
  CHECK_EQUAL(static_cast<int>(PlanStatus::Immediate),
              static_cast<int>(prepare(request, plan)));
  CHECK_EQUAL(static_cast<int>(Direction::Stationary),
              static_cast<int>(plan.xDirection));
  CHECK_EQUAL(static_cast<int>(Direction::Stationary),
              static_cast<int>(plan.yDirection));
  Cursor immediateCursor{};
  CHECK_EQUAL(static_cast<int>(TraceStatus::Complete),
              static_cast<int>(begin(plan, immediateCursor)));
  CHECK_TRUE(isComplete(immediateCursor));

  request = normalRequest(std::numeric_limits<int64_t>::min(), 1);
  CHECK_EQUAL(static_cast<int>(PlanStatus::ArithmeticOverflow),
              static_cast<int>(prepare(request, plan)));

  request = normalRequest(
      static_cast<int64_t>(std::numeric_limits<uint32_t>::max()) + 1, 1);
  CHECK_EQUAL(static_cast<int>(PlanStatus::OutOfRange),
              static_cast<int>(prepare(request, plan)));

  request = normalRequest(1000, 0);
  request.xLimits.maxRateHz = 0u;
  CHECK_EQUAL(static_cast<int>(PlanStatus::InvalidLimits),
              static_cast<int>(prepare(request, plan)));

  request = normalRequest(1000, 0);
  request.yLimits = {};
  CHECK_EQUAL(static_cast<int>(PlanStatus::Ready),
              static_cast<int>(prepare(request, plan)));

  request.timer.inputClockHz = 0u;
  CHECK_EQUAL(static_cast<int>(PlanStatus::InvalidLimits),
              static_cast<int>(prepare(request, plan)));

  request = normalRequest(1000, 0);
  request.timer.maxArr = 0u;
  CHECK_EQUAL(static_cast<int>(PlanStatus::InvalidLimits),
              static_cast<int>(prepare(request, plan)));
}

TEST(CoordinatedXyPlanner, CenteredDdaHasExactCountsAndHalfStepBoundExhaustively) {
  for (uint32_t x = 0u; x <= 64u; ++x) {
    for (uint32_t y = 0u; y <= 64u; ++y) {
      if (x == 0u && y == 0u) continue;
      const CoordinatedXyPlan plan = readyPlan(normalRequest(x, y));
      checkPathAtEveryPrefix(plan);
    }
  }
}

TEST(CoordinatedXyPlanner, CenteredTieRuleProducesKnownMasks) {
  const CoordinatedXyPlan plan = readyPlan(normalRequest(5, 2));
  const std::vector<StepEvent> events = runTrace(plan);
  const StepMask expected[] = {
      StepMask::X,
      StepMask::X | StepMask::Y,
      StepMask::X,
      StepMask::X | StepMask::Y,
      StepMask::X,
  };
  for (uint32_t index = 0u; index < 5u; ++index) {
    CHECK_EQUAL(static_cast<int>(expected[index]),
                static_cast<int>(events[index].mask));
  }
}

TEST(CoordinatedXyPlanner, DirectionsAndReverseMovesOnlyChangeDirectionFields) {
  const int64_t signedX[] = {8416, -8416, 8416, -8416};
  const int64_t signedY[] = {30000, 30000, -30000, -30000};
  for (uint32_t index = 0u; index < 4u; ++index) {
    const CoordinatedXyPlan plan = readyPlan(
        normalRequest(signedX[index], signedY[index]));
    CHECK_EQUAL(static_cast<int>(signedX[index] < 0
                                     ? Direction::Negative
                                     : Direction::Positive),
                static_cast<int>(plan.xDirection));
    CHECK_EQUAL(static_cast<int>(signedY[index] < 0
                                     ? Direction::Negative
                                     : Direction::Positive),
                static_cast<int>(plan.yDirection));
  }

  const CoordinatedXyPlan forward = readyPlan(normalRequest(8416, 30000));
  const CoordinatedXyPlan reverse = readyPlan(normalRequest(-8416, -30000));
  const std::vector<StepEvent> forwardEvents = runTrace(forward);
  const std::vector<StepEvent> reverseEvents = runTrace(reverse);
  UNSIGNED_LONGS_EQUAL(static_cast<uint32_t>(forwardEvents.size()),
                       static_cast<uint32_t>(reverseEvents.size()));
  for (uint32_t index = 0u; index < forwardEvents.size(); ++index) {
    checkSameEvent(forwardEvents[index], reverseEvents[index]);
  }

  const CoordinatedXyPlan xOnly = readyPlan(normalRequest(-1000, 0));
  CHECK_EQUAL(static_cast<int>(Direction::Negative),
              static_cast<int>(xOnly.xDirection));
  CHECK_EQUAL(static_cast<int>(Direction::Stationary),
              static_cast<int>(xOnly.yDirection));
  const std::vector<StepEvent> xOnlyEvents = runTrace(xOnly);
  for (const StepEvent& event : xOnlyEvents) {
    CHECK_TRUE(contains(event.mask, StepMask::X));
    CHECK_FALSE(contains(event.mask, StepMask::Y));
  }
}

TEST(CoordinatedXyPlanner, CameraAndEnvelopeVectorsRemainWithinCenteredBound) {
  const int64_t vectors[][2] = {
      {-8416, -30000},
      {8416, 30000},
      {-10850, -38676},
      {10850, 38676},
      {43000, 33500},
      {-43000, -33500},
      {1, 40000},
      {40000, 1},
  };
  for (const auto& vector : vectors) {
    const CoordinatedXyPlan plan = readyPlan(
        normalRequest(vector[0], vector[1]));
    checkPathAtEveryPrefix(plan);
  }
}

TEST(CoordinatedXyPlanner, QualificationAnd384WellRastersHaveExactMoveTraces) {
  int32_t currentX = 3000;
  int32_t currentY = 1000;
  for (uint32_t row = 0u; row < 8u; ++row) {
    for (uint32_t columnIndex = 0u; columnIndex < 12u; ++columnIndex) {
      const uint32_t column = (row & 1u) == 0u
          ? columnIndex
          : 11u - columnIndex;
      const int32_t targetX = 3000 + static_cast<int32_t>(column) * 400;
      const int32_t targetY = 1000 + static_cast<int32_t>(row) * 400;
      const int64_t dx = static_cast<int64_t>(targetX) - currentX;
      const int64_t dy = static_cast<int64_t>(targetY) - currentY;
      CoordinatedXyPlan plan{};
      const PlanStatus status = prepare(normalRequest(dx, dy), plan);
      if (dx == 0 && dy == 0) {
        CHECK_EQUAL(static_cast<int>(PlanStatus::Immediate),
                    static_cast<int>(status));
      } else {
        CHECK_EQUAL(static_cast<int>(PlanStatus::Ready),
                    static_cast<int>(status));
        checkPathAtEveryPrefix(plan);
      }
      currentX = targetX;
      currentY = targetY;
    }
  }

  currentX = 43000;
  currentY = 13000;
  uint32_t plannedMoves = 0u;
  for (uint32_t row = 0u; row < 16u; ++row) {
    const int32_t targetX = interpolateEndpoint(43000, 33000, row, 16u);
    for (uint32_t columnIndex = 0u; columnIndex < 24u; ++columnIndex) {
      const uint32_t column = (row & 1u) == 0u
          ? columnIndex
          : 23u - columnIndex;
      const int32_t targetY = interpolateEndpoint(
          13000, 30000, column, 24u);
      const int64_t dx = static_cast<int64_t>(targetX) - currentX;
      const int64_t dy = static_cast<int64_t>(targetY) - currentY;
      CoordinatedXyPlan plan{};
      const PlanStatus status = prepare(normalRequest(dx, dy), plan);
      if (dx == 0 && dy == 0) {
        CHECK_EQUAL(static_cast<int>(PlanStatus::Immediate),
                    static_cast<int>(status));
      } else {
        CHECK_EQUAL(static_cast<int>(PlanStatus::Ready),
                    static_cast<int>(status));
        checkPathAtEveryPrefix(plan);
        ++plannedMoves;
      }
      currentX = targetX;
      currentY = targetY;
    }
  }
  UNSIGNED_LONGS_EQUAL(383u, plannedMoves);
  const CoordinatedXyPlan returnPlan = readyPlan(normalRequest(
      static_cast<int64_t>(43000) - currentX,
      static_cast<int64_t>(13000) - currentY));
  checkPathAtEveryPrefix(returnPlan);
}

TEST(CoordinatedXyPlanner, Milestone6VectorGroupsHaveFrozenPulseAndCallbackTotals) {
  struct Totals {
    uint32_t moves = 0u;
    uint32_t x = 0u;
    uint32_t y = 0u;
    uint32_t master = 0u;
  };
  auto add = [](Totals& totals, int64_t dx, int64_t dy, uint32_t rateHz) {
    PlanRequest request = normalRequest(dx, dy);
    request.requestedMasterRateHz = rateHz;
    const CoordinatedXyPlan plan = readyPlan(request);
    totals.moves++;
    totals.x += plan.xSteps;
    totals.y += plan.ySteps;
    totals.master += plan.masterSteps;
  };

  const int32_t geometry[][4] = {
      {5000, 5000, 25000, 5000},
      {5000, 5000, 5000, 25000},
      {5000, 5000, 25000, 25000},
      {5000, 5000, 10000, 25000},
      {8916, 30500, 500, 500},
  };
  for (uint32_t rate : {5000u, 10000u, 20000u, 30000u, 40000u}) {
    Totals tier{};
    for (const auto& pair : geometry) {
      const int64_t dx = static_cast<int64_t>(pair[2]) - pair[0];
      const int64_t dy = static_cast<int64_t>(pair[3]) - pair[1];
      add(tier, dx, dy, rate);
      add(tier, -dx, -dy, rate);
    }
    UNSIGNED_LONGS_EQUAL(10u, tier.moves);
    UNSIGNED_LONGS_EQUAL(106832u, tier.x);
    UNSIGNED_LONGS_EQUAL(180000u, tier.y);
    UNSIGNED_LONGS_EQUAL(220000u, tier.master);
    UNSIGNED_LONGS_EQUAL(440000u, tier.master * 2u);
  }

  Totals milestone1{};
  add(milestone1, 10000, 0, 40000u);
  add(milestone1, 0, 10000, 40000u);
  add(milestone1, 10000, 10000, 40000u);
  add(milestone1, -8416, -30000, 40000u);
  add(milestone1, 1000, 0, 40000u);
  UNSIGNED_LONGS_EQUAL(5u, milestone1.moves);
  UNSIGNED_LONGS_EQUAL(29416u, milestone1.x);
  UNSIGNED_LONGS_EQUAL(50000u, milestone1.y);
  UNSIGNED_LONGS_EQUAL(61000u, milestone1.master);
  UNSIGNED_LONGS_EQUAL(122000u, milestone1.master * 2u);

  Totals repeatedCamera{};
  for (uint32_t cycle = 0u; cycle < 5u; ++cycle) {
    add(repeatedCamera, -8416, -30000, 40000u);
    add(repeatedCamera, 8416, 30000, 40000u);
  }
  UNSIGNED_LONGS_EQUAL(10u, repeatedCamera.moves);
  UNSIGNED_LONGS_EQUAL(84160u, repeatedCamera.x);
  UNSIGNED_LONGS_EQUAL(300000u, repeatedCamera.y);
  UNSIGNED_LONGS_EQUAL(300000u, repeatedCamera.master);
  UNSIGNED_LONGS_EQUAL(600000u, repeatedCamera.master * 2u);

  Totals asymRaster{};
  for (const auto& delta : {std::pair<int32_t, int32_t>{10000, 20000},
                            {5000, 20000}, {20000, 5000}}) {
    add(asymRaster, delta.first, delta.second, 40000u);
    add(asymRaster, -delta.first, -delta.second, 40000u);
  }
  int32_t x = 43000;
  int32_t y = 13000;
  for (uint32_t row = 0u; row < 16u; ++row) {
    const int32_t targetX = interpolateEndpoint(43000, 33000, row, 16u);
    for (uint32_t columnIndex = 0u; columnIndex < 24u; ++columnIndex) {
      const uint32_t column = (row & 1u) == 0u ? columnIndex : 23u - columnIndex;
      const int32_t targetY = interpolateEndpoint(13000, 30000, column, 24u);
      if (targetX != x || targetY != y) {
        add(asymRaster,
            static_cast<int64_t>(targetX) - x,
            static_cast<int64_t>(targetY) - y,
            40000u);
      }
      x = targetX;
      y = targetY;
    }
  }
  add(asymRaster, static_cast<int64_t>(43000) - x,
      static_cast<int64_t>(13000) - y, 40000u);
  UNSIGNED_LONGS_EQUAL(390u, asymRaster.moves);
  UNSIGNED_LONGS_EQUAL(90000u, asymRaster.x);
  UNSIGNED_LONGS_EQUAL(362000u, asymRaster.y);
  UNSIGNED_LONGS_EQUAL(412000u, asymRaster.master);
  UNSIGNED_LONGS_EQUAL(824000u, asymRaster.master * 2u);
}

TEST(CoordinatedXyPlanner, LongAndTriangularProfilesHaveExactSegmentsAndEndpoints) {
  CoordinatedXyPlan longPlan = readyPlan(normalRequest(8416, 30000));
  UNSIGNED_LONGS_EQUAL(40000u, longPlan.masterRateHz);
  UNSIGNED_LONGS_EQUAL(5715u, longPlan.accelerationSteps);
  UNSIGNED_LONGS_EQUAL(18570u, longPlan.cruiseSteps);
  UNSIGNED_LONGS_EQUAL(5715u, longPlan.decelerationSteps);
  UNSIGNED_LONGS_EQUAL(1124u, longPlan.targetArr);
  UNSIGNED_LONGS_EQUAL(5620u, longPlan.startArr);
  CHECK_FALSE(longPlan.triangular);

  Cursor longCursor{};
  const std::vector<StepEvent> longEvents = runTrace(longPlan, &longCursor);
  CHECK_EQUAL(static_cast<int>(ProfilePhase::Acceleration),
              static_cast<int>(longEvents.front().phase));
  UNSIGNED_LONGS_EQUAL(longPlan.startArr, longEvents.front().arr);
  CHECK_EQUAL(static_cast<int>(ProfilePhase::Cruise),
              static_cast<int>(longEvents[longPlan.accelerationSteps].phase));
  UNSIGNED_LONGS_EQUAL(longPlan.targetArr,
                       longEvents[longPlan.accelerationSteps].arr);
  CHECK_EQUAL(static_cast<int>(ProfilePhase::Deceleration),
              static_cast<int>(longEvents[
                  longPlan.accelerationSteps + longPlan.cruiseSteps].phase));
  UNSIGNED_LONGS_EQUAL(longPlan.targetArr,
                       longEvents[
                           longPlan.accelerationSteps + longPlan.cruiseSteps].arr);
  CHECK_TRUE(NormalizedCosineProfile::atEndpoint(
      longCursor.accelerationCursor));
  CHECK_TRUE(NormalizedCosineProfile::atEndpoint(
      longCursor.decelerationCursor));
  UNSIGNED_LONGS_EQUAL(longPlan.startArr,
                       NormalizedCosineProfile::currentArr(
                           longCursor.decelerationCursor));

  CoordinatedXyPlan shortPlan = readyPlan(normalRequest(1000, 0));
  UNSIGNED_LONGS_EQUAL(11832u, shortPlan.masterRateHz);
  UNSIGNED_LONGS_EQUAL(500u, shortPlan.accelerationSteps);
  UNSIGNED_LONGS_EQUAL(0u, shortPlan.cruiseSteps);
  UNSIGNED_LONGS_EQUAL(500u, shortPlan.decelerationSteps);
  UNSIGNED_LONGS_EQUAL(3802u, shortPlan.targetArr);
  UNSIGNED_LONGS_EQUAL(19010u, shortPlan.startArr);
  CHECK_TRUE(shortPlan.triangular);
  Cursor shortCursor{};
  const std::vector<StepEvent> shortEvents = runTrace(shortPlan, &shortCursor);
  CHECK_EQUAL(static_cast<int>(ProfilePhase::Acceleration),
              static_cast<int>(shortEvents[499u].phase));
  CHECK_EQUAL(static_cast<int>(ProfilePhase::Deceleration),
              static_cast<int>(shortEvents[500u].phase));
  UNSIGNED_LONGS_EQUAL(shortPlan.targetArr, shortEvents[500u].arr);
  UNSIGNED_LONGS_EQUAL(shortPlan.startArr,
                       NormalizedCosineProfile::currentArr(
                           shortCursor.decelerationCursor));
}

TEST(CoordinatedXyPlanner, TinyMovesHaveDefinedTriangularPhaseJoins) {
  for (uint32_t steps = 1u; steps <= 3u; ++steps) {
    const CoordinatedXyPlan plan = readyPlan(normalRequest(steps, steps));
    const std::vector<StepEvent> events = runTrace(plan);
    UNSIGNED_LONGS_EQUAL(steps, static_cast<uint32_t>(events.size()));
    if (steps == 1u) {
      UNSIGNED_LONGS_EQUAL(0u, plan.accelerationSteps);
      UNSIGNED_LONGS_EQUAL(1u, plan.cruiseSteps);
      UNSIGNED_LONGS_EQUAL(0u, plan.decelerationSteps);
      CHECK_EQUAL(static_cast<int>(ProfilePhase::Cruise),
                  static_cast<int>(events[0].phase));
      UNSIGNED_LONGS_EQUAL(plan.targetArr, events[0].arr);
    } else {
      CHECK_EQUAL(static_cast<int>(ProfilePhase::Acceleration),
                  static_cast<int>(events.front().phase));
      CHECK_EQUAL(static_cast<int>(ProfilePhase::Deceleration),
                  static_cast<int>(events.back().phase));
    }
  }
}

TEST(CoordinatedXyPlanner, ComponentScalingHonorsUnequalAxisLimitsExactly) {
  PlanRequest request = normalRequest(10000, 5000);
  request.requestedMasterRateHz = 50000u;
  request.yLimits = {10000u, 30000u};
  const CoordinatedXyPlan plan = readyPlan(request);
  UNSIGNED_LONGS_EQUAL(20000u, plan.masterRateCapHz);
  UNSIGNED_LONGS_EQUAL(20000u, plan.masterRateHz);
  UNSIGNED_LONGS_EQUAL(20000u, plan.xRateHz);
  UNSIGNED_LONGS_EQUAL(10000u, plan.yRateHz);
  UNSIGNED_LONGS_EQUAL(60000u,
                       plan.masterAccelerationCapStepsPerSec2);
  UNSIGNED_LONGS_EQUAL(60000u,
                       plan.xAccelerationStepsPerSec2);
  UNSIGNED_LONGS_EQUAL(30000u,
                       plan.yAccelerationStepsPerSec2);
  CHECK_TRUE(static_cast<uint64_t>(plan.masterRateHz) * plan.xSteps <=
             static_cast<uint64_t>(request.xLimits.maxRateHz) *
                 plan.masterSteps);
  CHECK_TRUE(static_cast<uint64_t>(plan.masterRateHz) * plan.ySteps <=
             static_cast<uint64_t>(request.yLimits.maxRateHz) *
                 plan.masterSteps);
  CHECK_TRUE(static_cast<uint64_t>(
                 plan.masterAccelerationStepsPerSec2) * plan.xSteps <=
             static_cast<uint64_t>(
                 request.xLimits.accelerationStepsPerSec2) * plan.masterSteps);
  CHECK_TRUE(static_cast<uint64_t>(
                 plan.masterAccelerationStepsPerSec2) * plan.ySteps <=
             static_cast<uint64_t>(
                 request.yLimits.accelerationStepsPerSec2) * plan.masterSteps);

  request.requestedMasterRateHz = 15000u;
  const CoordinatedXyPlan requestedPlan = readyPlan(request);
  UNSIGNED_LONGS_EQUAL(15000u, requestedPlan.masterRateHz);
  UNSIGNED_LONGS_EQUAL(15000u, requestedPlan.xRateHz);
  UNSIGNED_LONGS_EQUAL(7500u, requestedPlan.yRateHz);
}

TEST(CoordinatedXyPlanner, TimerBoundsCoverNormalRatesAndSlowOutOfRangePlans) {
  const uint32_t rates[] = {3000u, 6000u, 10000u, 20000u, 40000u};
  for (uint32_t rate : rates) {
    PlanRequest request = normalRequest(60000, 30000);
    request.requestedMasterRateHz = rate;
    const CoordinatedXyPlan plan = readyPlan(request);
    UNSIGNED_LONGS_EQUAL(179u, plan.minArr);
    UNSIGNED_LONGS_EQUAL(90000000u / (2u * rate) - 1u,
                         plan.targetArr);
    UNSIGNED_LONGS_EQUAL(
        static_cast<uint32_t>(std::min<uint64_t>(
            static_cast<uint64_t>(plan.targetArr) * 5u,
            std::numeric_limits<uint32_t>::max())),
        plan.startArr);
  }

  PlanRequest sixteenBit = normalRequest(60000, 30000);
  sixteenBit.timer.maxArr = 65535u;
  sixteenBit.requestedMasterRateHz = 3000u;
  const CoordinatedXyPlan sixteenBitPlan = readyPlan(sixteenBit);
  UNSIGNED_LONGS_EQUAL(14999u, sixteenBitPlan.targetArr);
  UNSIGNED_LONGS_EQUAL(65535u, sixteenBitPlan.startArr);

  sixteenBit.requestedMasterRateHz = 100u;
  CoordinatedXyPlan tooSlow{};
  CHECK_EQUAL(static_cast<int>(PlanStatus::OutOfRange),
              static_cast<int>(prepare(sixteenBit, tooSlow)));
}

TEST(CoordinatedXyPlanner, FullWidthPlansKeepCenteredAccumulatorsInUint64Range) {
  constexpr uint32_t maximum = std::numeric_limits<uint32_t>::max();
  const CoordinatedXyPlan plan = readyPlan(normalRequest(maximum, maximum - 1u));
  UNSIGNED_LONGS_EQUAL(maximum, plan.masterSteps);
  CHECK_TRUE((static_cast<uint64_t>(plan.masterSteps) * 2u - 1u) <
             std::numeric_limits<uint64_t>::max());

  Cursor cursor{};
  CHECK_EQUAL(static_cast<int>(TraceStatus::Ready),
              static_cast<int>(begin(plan, cursor)));
  for (uint32_t index = 0u; index < 4096u; ++index) {
    CHECK_EQUAL(static_cast<int>(TraceStatus::Ready),
                static_cast<int>(completeCurrentStep(plan, cursor)));
    CHECK_TRUE(cursor.xAccumulator < plan.masterSteps);
    CHECK_TRUE(cursor.yAccumulator < plan.masterSteps);
    CHECK_TRUE(pathErrorNumerator(cursor.xEmittedSteps,
                                  cursor.completedMasterSteps,
                                  plan.xSteps,
                                  plan.masterSteps) <= plan.masterSteps / 2u);
    CHECK_TRUE(pathErrorNumerator(cursor.yEmittedSteps,
                                  cursor.completedMasterSteps,
                                  plan.ySteps,
                                  plan.masterSteps) <= plan.masterSteps / 2u);
  }
}

TEST(CoordinatedXyPlanner, TraceIsDeterministicAndCursorBusyStateIsExplicit) {
  const CoordinatedXyPlan plan = readyPlan(normalRequest(1234, 4321));
  const std::vector<StepEvent> first = runTrace(plan);
  const std::vector<StepEvent> second = runTrace(plan);
  UNSIGNED_LONGS_EQUAL(static_cast<uint32_t>(first.size()),
                       static_cast<uint32_t>(second.size()));
  for (uint32_t index = 0u; index < first.size(); ++index) {
    checkSameEvent(first[index], second[index]);
  }

  Cursor cursor{};
  CHECK_EQUAL(static_cast<int>(TraceStatus::Ready),
              static_cast<int>(begin(plan, cursor)));
  CHECK_EQUAL(static_cast<int>(TraceStatus::Busy),
              static_cast<int>(begin(plan, cursor)));

  StepEvent event{};
  Cursor idle{};
  CHECK_EQUAL(static_cast<int>(TraceStatus::InvalidState),
              static_cast<int>(currentEvent(idle, event)));
  CHECK_EQUAL(static_cast<int>(TraceStatus::InvalidState),
              static_cast<int>(completeCurrentStep(plan, idle)));

  CoordinatedXyPlan invalid{};
  CHECK_EQUAL(static_cast<int>(TraceStatus::InvalidPlan),
              static_cast<int>(begin(invalid, idle)));

  const CoordinatedXyPlan otherPlan = readyPlan(normalRequest(1235, 4321));
  CHECK_EQUAL(static_cast<int>(TraceStatus::InvalidState),
              static_cast<int>(completeCurrentStep(otherPlan, cursor)));
}
