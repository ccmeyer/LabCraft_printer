#include "CoordinatedXyPlanner.h"
#include "CppUTest/TestHarness.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
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

std::vector<EdgeEvent> runTrace(const CoordinatedXyPlan& plan,
                                Cursor* finished = nullptr) {
  std::vector<EdgeEvent> events;
  Cursor cursor{};
  const TraceStatus started = begin(plan, cursor);
  if (plan.status == PlanStatus::Immediate) {
    CHECK_EQUAL(static_cast<int>(TraceStatus::Complete),
                static_cast<int>(started));
    if (finished != nullptr) *finished = cursor;
    return events;
  }
  CHECK_EQUAL(static_cast<int>(TraceStatus::Ready),
              static_cast<int>(started));
  while (!isComplete(cursor)) {
    EdgeEvent event{};
    CHECK_EQUAL(static_cast<int>(TraceStatus::Ready),
                static_cast<int>(currentEvent(cursor, event)));
    events.push_back(event);
    const TraceStatus status = completeCurrentEdge(plan, cursor);
    CHECK_TRUE(status == TraceStatus::Ready ||
               status == TraceStatus::Complete);
  }
  UNSIGNED_LONGS_EQUAL(plan.masterEdges,
                       static_cast<uint32_t>(events.size()));
  UNSIGNED_LONGS_EQUAL(plan.xEdges, cursor.xEmittedEdges);
  UNSIGNED_LONGS_EQUAL(plan.yEdges, cursor.yEmittedEdges);
  if (finished != nullptr) *finished = cursor;
  return events;
}

uint64_t absoluteDifference(uint64_t lhs, uint64_t rhs) {
  return lhs >= rhs ? lhs - rhs : rhs - lhs;
}

void checkCenteredPath(const CoordinatedXyPlan& plan) {
  Cursor cursor{};
  CHECK_EQUAL(static_cast<int>(TraceStatus::Ready),
              static_cast<int>(begin(plan, cursor)));
  while (!isComplete(cursor)) {
    const TraceStatus status = completeCurrentEdge(plan, cursor);
    const uint64_t xError = absoluteDifference(
        static_cast<uint64_t>(cursor.xEmittedEdges) * plan.masterEdges,
        static_cast<uint64_t>(cursor.completedMasterEdges) * plan.xEdges);
    const uint64_t yError = absoluteDifference(
        static_cast<uint64_t>(cursor.yEmittedEdges) * plan.masterEdges,
        static_cast<uint64_t>(cursor.completedMasterEdges) * plan.yEdges);
    CHECK_TRUE(xError <= plan.masterEdges / 2u);
    CHECK_TRUE(yError <= plan.masterEdges / 2u);
    CHECK_TRUE(cursor.xAccumulator < plan.masterEdges);
    CHECK_TRUE(cursor.yAccumulator < plan.masterEdges);
    CHECK_TRUE(status == TraceStatus::Ready ||
               status == TraceStatus::Complete);
  }
}

void checkUniformAxisSpacing(const CoordinatedXyPlan& plan,
                             const std::vector<EdgeEvent>& events,
                             EdgeMask axis,
                             uint32_t axisEdges) {
  if (axisEdges < 2u) return;
  const uint32_t minimumGap = plan.masterEdges / axisEdges;
  const uint32_t maximumGap = minimumGap +
      ((plan.masterEdges % axisEdges) != 0u ? 1u : 0u);
  uint32_t previous = 0u;
  bool found = false;
  uint32_t count = 0u;
  for (const EdgeEvent& event : events) {
    if (!contains(event.mask, axis)) continue;
    if (found) {
      const uint32_t gap = event.masterEdgeIndex - previous;
      CHECK_TRUE(gap == minimumGap || gap == maximumGap);
    }
    previous = event.masterEdgeIndex;
    found = true;
    ++count;
  }
  UNSIGNED_LONGS_EQUAL(axisEdges, count);
}

void checkIncidentVector(int64_t dx,
                         int64_t dy,
                         uint32_t expectedMinimumMinorGap,
                         uint32_t expectedMaximumMinorGap) {
  const CoordinatedXyPlan plan = readyPlan(normalRequest(dx, dy));
  const std::vector<EdgeEvent> events = runTrace(plan);
  const bool xMinor = plan.xEdges < plan.yEdges;
  const uint32_t minorEdges = xMinor ? plan.xEdges : plan.yEdges;
  const EdgeMask minorAxis = xMinor ? EdgeMask::X : EdgeMask::Y;
  const uint32_t minimumGap = plan.masterEdges / minorEdges;
  const uint32_t maximumGap = minimumGap +
      ((plan.masterEdges % minorEdges) != 0u ? 1u : 0u);
  UNSIGNED_LONGS_EQUAL(expectedMinimumMinorGap, minimumGap);
  UNSIGNED_LONGS_EQUAL(expectedMaximumMinorGap, maximumGap);
  checkUniformAxisSpacing(plan, events, minorAxis, minorEdges);
  checkCenteredPath(plan);
}

double squaredRateForArr(const CoordinatedXyPlan& plan, uint32_t arr) {
  const double rate = static_cast<double>(plan.timer.inputClockHz) /
      (static_cast<double>(arr) + 1.0);
  return rate * rate;
}

void checkAccelerationBound(const CoordinatedXyPlan& plan) {
  const std::vector<EdgeEvent> events = runTrace(plan);
  auto checkRamp = [&](uint32_t first, uint32_t count, uint32_t endpointArr) {
    if (count == 0u) return;
    const uint32_t window = std::max(
        1u, (count + NormalizedCosineProfile::kLutIntervals - 1u) /
                NormalizedCosineProfile::kLutIntervals);
    for (uint32_t offset = 0u; offset + window <= count; ++offset) {
      const uint32_t end = offset + window;
      const uint32_t firstArr = events[first + offset].arr;
      const uint32_t lastArr =
          end == count ? endpointArr : events[first + end].arr;
      const double acceleration = std::abs(
          squaredRateForArr(plan, lastArr) -
          squaredRateForArr(plan, firstArr)) /
          (2.0 * static_cast<double>(window));
      CHECK_COMPARE(
          acceleration, <=,
          static_cast<double>(plan.masterAccelerationCapEdgesPerSec2));
    }
  };
  checkRamp(0u, plan.accelerationEdges, plan.targetArr);
  checkRamp(plan.accelerationEdges + plan.cruiseEdges,
            plan.decelerationEdges,
            plan.startArr);
}

}  // namespace

TEST_GROUP(CoordinatedXyPlanner) {
};

TEST(CoordinatedXyPlanner, ZeroMoveAndInvalidRequestsHaveExplicitResults) {
  CoordinatedXyPlan plan{};
  PlanRequest request{};
  CHECK_EQUAL(static_cast<int>(PlanStatus::Immediate),
              static_cast<int>(prepare(request, plan)));
  Cursor cursor{};
  CHECK_EQUAL(static_cast<int>(TraceStatus::Complete),
              static_cast<int>(begin(plan, cursor)));

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
  request.timer.minEdgeIntervalNs = 0u;
  CHECK_EQUAL(static_cast<int>(PlanStatus::InvalidLimits),
              static_cast<int>(prepare(request, plan)));
}

TEST(CoordinatedXyPlanner, CenteredDdaIsExactAndUniformExhaustively) {
  for (uint32_t x = 0u; x <= 64u; ++x) {
    for (uint32_t y = 0u; y <= 64u; ++y) {
      if (x == 0u && y == 0u) continue;
      const CoordinatedXyPlan plan = readyPlan(normalRequest(x, y));
      const std::vector<EdgeEvent> events = runTrace(plan);
      checkCenteredPath(plan);
      checkUniformAxisSpacing(plan, events, EdgeMask::X, plan.xEdges);
      checkUniformAxisSpacing(plan, events, EdgeMask::Y, plan.yEdges);
    }
  }
}

TEST(CoordinatedXyPlanner, ShallowIncidentVectorsHaveRequiredEdgeGaps) {
  for (int signX : {-1, 1}) {
    for (int signY : {-1, 1}) {
      checkIncidentVector(signX * 17100, signY * 4470, 3u, 4u);
      checkIncidentVector(signX * 4470, signY * 17100, 3u, 4u);
      checkIncidentVector(signX * 17100, signY * 2054, 8u, 9u);
      checkIncidentVector(signX * 2054, signY * 17100, 8u, 9u);
      checkIncidentVector(signX * 100, signY * 19574, 195u, 196u);
      checkIncidentVector(signX * 19574, signY * 100, 195u, 196u);
    }
  }
}

TEST(CoordinatedXyPlanner, DirectionChangesDoNotChangeEdgeTrace) {
  const CoordinatedXyPlan forward = readyPlan(normalRequest(4470, 17100));
  const CoordinatedXyPlan reverse = readyPlan(normalRequest(-4470, -17100));
  const std::vector<EdgeEvent> forwardEvents = runTrace(forward);
  const std::vector<EdgeEvent> reverseEvents = runTrace(reverse);
  UNSIGNED_LONGS_EQUAL(
      static_cast<uint32_t>(forwardEvents.size()),
      static_cast<uint32_t>(reverseEvents.size()));
  for (uint32_t index = 0u; index < forwardEvents.size(); ++index) {
    UNSIGNED_LONGS_EQUAL(
        forwardEvents[index].masterEdgeIndex,
        reverseEvents[index].masterEdgeIndex);
    CHECK_EQUAL(static_cast<int>(forwardEvents[index].mask),
                static_cast<int>(reverseEvents[index].mask));
    UNSIGNED_LONGS_EQUAL(forwardEvents[index].arr,
                         reverseEvents[index].arr);
  }
}

TEST(CoordinatedXyPlanner, ProductionGeometryHasFrozenActiveEdgeTotals) {
  struct Totals {
    uint32_t moves = 0u;
    uint32_t xEdges = 0u;
    uint32_t yEdges = 0u;
    uint32_t masterEdges = 0u;
  };
  const int32_t vectors[][2] = {
      {20000, 0},
      {0, 20000},
      {20000, 20000},
      {5000, 20000},
      {-8416, -30000},
  };
  for (uint32_t rate : {10000u, 40000u}) {
    Totals totals{};
    for (const auto& vector : vectors) {
      for (int direction : {1, -1}) {
        PlanRequest request =
            normalRequest(direction * vector[0], direction * vector[1]);
        request.requestedMasterRateHz = rate;
        const CoordinatedXyPlan plan = readyPlan(request);
        ++totals.moves;
        totals.xEdges += plan.xEdges;
        totals.yEdges += plan.yEdges;
        totals.masterEdges += plan.masterEdges;
      }
    }
    UNSIGNED_LONGS_EQUAL(10u, totals.moves);
    UNSIGNED_LONGS_EQUAL(106832u, totals.xEdges);
    UNSIGNED_LONGS_EQUAL(180000u, totals.yEdges);
    UNSIGNED_LONGS_EQUAL(220000u, totals.masterEdges);
  }
}

TEST(CoordinatedXyPlanner, ShallowSuiteTotalsAreFrozenAtBothRates) {
  const int32_t vectors[][2] = {
      {17100, 4470},
      {17100, 2054},
      {100, 19574},
      {4470, 17100},
      {2054, 17100},
      {19574, 100},
  };
  for (uint32_t rate : {10000u, 40000u}) {
    uint32_t xEdges = 0u;
    uint32_t yEdges = 0u;
    uint32_t masterEdges = 0u;
    for (const auto& vector : vectors) {
      for (int direction : {1, -1}) {
        PlanRequest request =
            normalRequest(direction * vector[0], direction * vector[1]);
        request.requestedMasterRateHz = rate;
        const CoordinatedXyPlan plan = readyPlan(request);
        xEdges += plan.xEdges;
        yEdges += plan.yEdges;
        masterEdges += plan.masterEdges;
      }
    }
    UNSIGNED_LONGS_EQUAL(120796u, xEdges);
    UNSIGNED_LONGS_EQUAL(120796u, yEdges);
    UNSIGNED_LONGS_EQUAL(215096u, masterEdges);
  }
}

TEST(CoordinatedXyPlanner, TimerUsesOneCallbackPerActiveEdge) {
  PlanRequest request = normalRequest(30000, 8416);
  request.requestedMasterRateHz = 40000u;
  const CoordinatedXyPlan plan = readyPlan(request);
  UNSIGNED_LONGS_EQUAL(40000u, plan.masterRateHz);
  UNSIGNED_LONGS_EQUAL(2249u, plan.targetArr);
  UNSIGNED_LONGS_EQUAL(11245u, plan.startArr);
  UNSIGNED_LONGS_EQUAL(10000u, plan.accelerationEdges);
  UNSIGNED_LONGS_EQUAL(10000u, plan.cruiseEdges);
  UNSIGNED_LONGS_EQUAL(10000u, plan.decelerationEdges);
  checkAccelerationBound(plan);

  request.requestedMasterRateHz = 10000u;
  const CoordinatedXyPlan slow = readyPlan(request);
  UNSIGNED_LONGS_EQUAL(8999u, slow.targetArr);
}

TEST(CoordinatedXyPlanner, UnequalAxisLimitsScaleEdgeRatesAndAcceleration) {
  PlanRequest request = normalRequest(20000, 5000);
  request.requestedMasterRateHz = 40000u;
  request.xLimits = {30000u, 120000u};
  request.yLimits = {40000u, 140000u};
  const CoordinatedXyPlan plan = readyPlan(request);
  UNSIGNED_LONGS_EQUAL(30000u, plan.masterRateHz);
  UNSIGNED_LONGS_EQUAL(30000u, plan.xRateHz);
  UNSIGNED_LONGS_EQUAL(7500u, plan.yRateHz);
  UNSIGNED_LONGS_EQUAL(120000u, plan.masterAccelerationEdgesPerSec2);
  UNSIGNED_LONGS_EQUAL(30000u, plan.yAccelerationEdgesPerSec2);
  checkAccelerationBound(plan);
}

TEST(CoordinatedXyPlanner, CursorCachingAndBusyStateAreDeterministic) {
  const CoordinatedXyPlan plan = readyPlan(normalRequest(100, 19574));
  Cursor first{};
  Cursor second{};
  CHECK_EQUAL(static_cast<int>(TraceStatus::Ready),
              static_cast<int>(begin(plan, first)));
  CHECK_EQUAL(static_cast<int>(TraceStatus::Busy),
              static_cast<int>(begin(plan, first)));
  CHECK_EQUAL(static_cast<int>(TraceStatus::Ready),
              static_cast<int>(begin(plan, second)));
  while (!isComplete(first)) {
    EdgeEvent lhs{};
    EdgeEvent rhs{};
    CHECK_EQUAL(static_cast<int>(TraceStatus::Ready),
                static_cast<int>(currentEvent(first, lhs)));
    CHECK_EQUAL(static_cast<int>(TraceStatus::Ready),
                static_cast<int>(currentEvent(second, rhs)));
    CHECK_EQUAL(static_cast<int>(lhs.mask), static_cast<int>(rhs.mask));
    UNSIGNED_LONGS_EQUAL(lhs.arr, rhs.arr);
    CHECK_EQUAL(static_cast<int>(completeCurrentEdge(plan, first)),
                static_cast<int>(completeCurrentEdge(plan, second)));
  }
}

TEST(CoordinatedXyPlanner, ExplicitResumeRateStartsAtThreeKilohertz) {
  PlanRequest request = normalRequest(20000, 20000);
  request.requestedMasterRateHz = 40000u;
  request.initialMasterRateHz = 3000u;
  CoordinatedXyPlan plan{};
  CHECK_EQUAL(static_cast<int>(PlanStatus::Ready),
              static_cast<int>(prepare(request, plan)));
  UNSIGNED_LONGS_EQUAL(3000u, plan.initialMasterRateHz);
  UNSIGNED_LONGS_EQUAL(29999u, plan.startArr);
  CHECK_TRUE(plan.startArr > plan.targetArr);
  CHECK_TRUE(plan.accelerationEdges < plan.masterEdges / 2u);
}

TEST(CoordinatedXyPlanner, ResumeRateClampsToShortMovePeak) {
  PlanRequest request = normalRequest(10, 10);
  request.requestedMasterRateHz = 2000u;
  request.initialMasterRateHz = 3000u;
  CoordinatedXyPlan plan{};
  CHECK_EQUAL(static_cast<int>(PlanStatus::Ready),
              static_cast<int>(prepare(request, plan)));
  UNSIGNED_LONGS_EQUAL(plan.masterRateHz, plan.initialMasterRateHz);
  UNSIGNED_LONGS_EQUAL(0u, plan.accelerationEdges);
  UNSIGNED_LONGS_EQUAL(plan.targetArr, plan.startArr);
}
