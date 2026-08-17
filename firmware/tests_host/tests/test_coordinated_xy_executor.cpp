#include "CoordinatedXyExecutor.h"
#include "CppUTest/TestHarness.h"

#include <cstdint>
#include <limits>
#include <vector>

namespace {

using namespace CoordinatedXyExecutor;
using CoordinatedXyPlanner::CoordinatedXyPlan;
using CoordinatedXyPlanner::EdgeEvent;
using CoordinatedXyPlanner::EdgeMask;
using CoordinatedXyPlanner::PlanRequest;
using CoordinatedXyPlanner::PlanStatus;
using CoordinatedXyPlanner::contains;
using CoordinatedXyPlanner::prepare;

CoordinatedXyPlan readyPlan(int64_t dx, int64_t dy) {
  PlanRequest request{};
  request.deltaX = dx;
  request.deltaY = dy;
  request.requestedMasterRateHz = 40000u;
  request.xLimits = {40000u, 140000u};
  request.yLimits = {40000u, 140000u};
  request.timer = {
      90000000u,
      std::numeric_limits<uint32_t>::max(),
      2000u,
  };
  CoordinatedXyPlan plan{};
  CHECK_EQUAL(static_cast<int>(PlanStatus::Ready),
              static_cast<int>(prepare(request, plan)));
  return plan;
}

Cursor runningCursor(const CoordinatedXyPlan& plan,
                     bool initialXHigh = false,
                     bool initialYHigh = false) {
  Cursor cursor{};
  CHECK_EQUAL(static_cast<int>(ArmStatus::Ready),
              static_cast<int>(
                  arm(plan, cursor, initialXHigh, initialYHigh)));
  CHECK_EQUAL(static_cast<int>(ControlDisposition::Deferred),
              static_cast<int>(start(cursor)));
  return cursor;
}

std::vector<TickResult> finish(const CoordinatedXyPlan& plan,
                               Cursor& cursor) {
  std::vector<TickResult> trace;
  while (!isTerminal(cursor)) {
    TickResult tick{};
    const TickStatus status = onTimerUpdate(plan, cursor, tick);
    CHECK_TRUE(status != TickStatus::InvalidState);
    trace.push_back(tick);
  }
  return trace;
}

bool has(EdgeMask mask, EdgeMask axis) {
  return contains(mask, axis);
}

}  // namespace

TEST_GROUP(CoordinatedXyExecutor) {
};

TEST(CoordinatedXyExecutor, ImmediateInvalidAndBusyPlansAreExplicit) {
  CoordinatedXyPlan immediate{};
  PlanRequest request{};
  CHECK_EQUAL(static_cast<int>(PlanStatus::Immediate),
              static_cast<int>(prepare(request, immediate)));
  Cursor cursor{};
  CHECK_EQUAL(static_cast<int>(ArmStatus::Immediate),
              static_cast<int>(arm(immediate, cursor)));
  CHECK_TRUE(isTerminal(cursor));

  CoordinatedXyPlan invalid{};
  CHECK_EQUAL(static_cast<int>(ArmStatus::InvalidPlan),
              static_cast<int>(arm(invalid, cursor)));

  const CoordinatedXyPlan plan = readyPlan(4, 2);
  cursor = runningCursor(plan);
  CHECK_EQUAL(static_cast<int>(ArmStatus::Busy),
              static_cast<int>(arm(plan, cursor)));
}

TEST(CoordinatedXyExecutor, EachMasterEventEmitsOneActiveEdgeMask) {
  const CoordinatedXyPlan plan = readyPlan(64, 18);
  Cursor cursor = runningCursor(plan);
  const std::vector<TickResult> trace = finish(plan, cursor);

  UNSIGNED_LONGS_EQUAL(plan.masterEdges,
                       static_cast<uint32_t>(trace.size()));
  for (const TickResult& tick : trace) {
    CHECK_TRUE(tick.edgeMask != EdgeMask::None);
    CHECK_EQUAL(static_cast<int>(tick.edgeMask),
                static_cast<int>(tick.accountEdgeMask));
    CHECK_TRUE(tick.cleanupEdgeMask == EdgeMask::None);
  }
  UNSIGNED_LONGS_EQUAL(plan.masterEdges, cursor.timerInterrupts);
  UNSIGNED_LONGS_EQUAL(plan.masterEdges, cursor.plannedEdgeEvents);
  UNSIGNED_LONGS_EQUAL(0u, cursor.cleanupEdgeEvents);
  UNSIGNED_LONGS_EQUAL(plan.xEdges, cursor.xActiveEdges);
  UNSIGNED_LONGS_EQUAL(plan.yEdges, cursor.yActiveEdges);
  UNSIGNED_LONGS_EQUAL(0u, cursor.xSpacingViolations);
  UNSIGNED_LONGS_EQUAL(0u, cursor.ySpacingViolations);
  CHECK_FALSE(cursor.xStepHigh);
  CHECK_FALSE(cursor.yStepHigh);
}

TEST(CoordinatedXyExecutor, IndependentPhasesReturnToEveryInitialState) {
  const CoordinatedXyPlan plan = readyPlan(8, 2);
  for (bool initialX : {false, true}) {
    for (bool initialY : {false, true}) {
      Cursor cursor = runningCursor(plan, initialX, initialY);
      bool xPhase = initialX;
      bool yPhase = initialY;
      while (!isTerminal(cursor)) {
        TickResult tick{};
        (void)onTimerUpdate(plan, cursor, tick);
        if (has(tick.edgeMask, EdgeMask::X)) {
          xPhase = !xPhase;
          CHECK_EQUAL(xPhase, has(tick.highMask, EdgeMask::X));
          CHECK_EQUAL(!xPhase, has(tick.lowMask, EdgeMask::X));
        }
        if (has(tick.edgeMask, EdgeMask::Y)) {
          yPhase = !yPhase;
          CHECK_EQUAL(yPhase, has(tick.highMask, EdgeMask::Y));
          CHECK_EQUAL(!yPhase, has(tick.lowMask, EdgeMask::Y));
        }
      }
      CHECK_EQUAL(initialX, cursor.xStepHigh);
      CHECK_EQUAL(initialY, cursor.yStepHigh);
    }
  }
}

TEST(CoordinatedXyExecutor, ReverseDirectionsDoNotChangeEdgeTrace) {
  const CoordinatedXyPlan forward = readyPlan(4470, 17100);
  const CoordinatedXyPlan reverse = readyPlan(-4470, -17100);
  Cursor forwardCursor = runningCursor(forward);
  Cursor reverseCursor = runningCursor(reverse);
  const std::vector<TickResult> forwardTrace =
      finish(forward, forwardCursor);
  const std::vector<TickResult> reverseTrace =
      finish(reverse, reverseCursor);
  UNSIGNED_LONGS_EQUAL(
      static_cast<uint32_t>(forwardTrace.size()),
      static_cast<uint32_t>(reverseTrace.size()));
  for (uint32_t index = 0u; index < forwardTrace.size(); ++index) {
    CHECK_EQUAL(static_cast<int>(forwardTrace[index].edgeMask),
                static_cast<int>(reverseTrace[index].edgeMask));
    UNSIGNED_LONGS_EQUAL(forwardTrace[index].arr,
                         reverseTrace[index].arr);
  }
  UNSIGNED_LONGS_EQUAL(forwardCursor.maskChecksum,
                       reverseCursor.maskChecksum);
  UNSIGNED_LONGS_EQUAL(forwardCursor.arrChecksum,
                       reverseCursor.arrChecksum);
}

TEST(CoordinatedXyExecutor, PauseStopsAtBoundaryAndPreservesCachedTrace) {
  const CoordinatedXyPlan plan = readyPlan(8, 4);
  Cursor uninterrupted = runningCursor(plan);
  Cursor paused = runningCursor(plan);

  TickResult firstA{};
  TickResult firstB{};
  (void)onTimerUpdate(plan, uninterrupted, firstA);
  (void)onTimerUpdate(plan, paused, firstB);
  CHECK_EQUAL(static_cast<int>(firstA.edgeMask),
              static_cast<int>(firstB.edgeMask));
  const EdgeEvent cached = paused.cachedEvent;
  const bool xPhase = paused.xStepHigh;
  const bool yPhase = paused.yStepHigh;

  CHECK_EQUAL(static_cast<int>(ControlDisposition::StopNow),
              static_cast<int>(requestPause(paused)));
  CHECK_EQUAL(static_cast<int>(State::Paused),
              static_cast<int>(paused.state));
  CHECK_EQUAL(xPhase, paused.xStepHigh);
  CHECK_EQUAL(yPhase, paused.yStepHigh);
  UNSIGNED_LONGS_EQUAL(cached.masterEdgeIndex,
                       paused.cachedEvent.masterEdgeIndex);
  CHECK_EQUAL(static_cast<int>(ControlDisposition::Deferred),
              static_cast<int>(resume(paused)));

  while (!isTerminal(uninterrupted)) {
    TickResult lhs{};
    TickResult rhs{};
    (void)onTimerUpdate(plan, uninterrupted, lhs);
    (void)onTimerUpdate(plan, paused, rhs);
    CHECK_EQUAL(static_cast<int>(lhs.edgeMask),
                static_cast<int>(rhs.edgeMask));
    CHECK_EQUAL(static_cast<int>(lhs.highMask),
                static_cast<int>(rhs.highMask));
    CHECK_EQUAL(static_cast<int>(lhs.lowMask),
                static_cast<int>(rhs.lowMask));
  }
  CHECK_TRUE(isTerminal(paused));
  UNSIGNED_LONGS_EQUAL(uninterrupted.maskChecksum, paused.maskChecksum);
  UNSIGNED_LONGS_EQUAL(uninterrupted.arrChecksum, paused.arrChecksum);
}

TEST(CoordinatedXyExecutor, CancelLowStopsWithoutPhysicalEdge) {
  const CoordinatedXyPlan plan = readyPlan(8, 4);
  Cursor cursor = runningCursor(plan);
  CHECK_EQUAL(static_cast<int>(ControlDisposition::StopNow),
              static_cast<int>(requestCancel(cursor)));
  CHECK_EQUAL(static_cast<int>(State::Canceled),
              static_cast<int>(cursor.state));
  UNSIGNED_LONGS_EQUAL(0u, cursor.timerInterrupts);
  UNSIGNED_LONGS_EQUAL(0u, cursor.xActiveEdges);
  UNSIGNED_LONGS_EQUAL(0u, cursor.yActiveEdges);
}

TEST(CoordinatedXyExecutor, CancelHighEmitsOneAccountedCleanupFall) {
  const CoordinatedXyPlan plan = readyPlan(8, 0);
  Cursor cursor = runningCursor(plan);
  TickResult first{};
  (void)onTimerUpdate(plan, cursor, first);
  CHECK_TRUE(cursor.xStepHigh);
  CHECK_EQUAL(static_cast<int>(ControlDisposition::Deferred),
              static_cast<int>(requestCancel(cursor)));

  TickResult cleanup{};
  CHECK_EQUAL(static_cast<int>(TickStatus::Canceled),
              static_cast<int>(onTimerUpdate(plan, cursor, cleanup)));
  CHECK_TRUE(has(cleanup.lowMask, EdgeMask::X));
  CHECK_TRUE(has(cleanup.accountEdgeMask, EdgeMask::X));
  CHECK_TRUE(has(cleanup.cleanupEdgeMask, EdgeMask::X));
  CHECK_FALSE(cursor.xStepHigh);
  UNSIGNED_LONGS_EQUAL(2u, cursor.xActiveEdges);
  UNSIGNED_LONGS_EQUAL(1u, cursor.xCleanupEdges);
  UNSIGNED_LONGS_EQUAL(1u, cursor.cleanupEdgeEvents);
  UNSIGNED_LONGS_EQUAL(1u, cursor.planner.completedMasterEdges);
}

TEST(CoordinatedXyExecutor, CleanupFallsOnlyAxesThatAreHigh) {
  const CoordinatedXyPlan plan = readyPlan(8, 2);
  Cursor cursor = runningCursor(plan);
  TickResult tick{};
  (void)onTimerUpdate(plan, cursor, tick);
  CHECK_TRUE(cursor.xStepHigh);
  CHECK_FALSE(cursor.yStepHigh);
  CHECK_EQUAL(static_cast<int>(ControlDisposition::Deferred),
              static_cast<int>(requestCancel(cursor)));
  (void)onTimerUpdate(plan, cursor, tick);
  CHECK_TRUE(has(tick.cleanupEdgeMask, EdgeMask::X));
  CHECK_FALSE(has(tick.cleanupEdgeMask, EdgeMask::Y));
  UNSIGNED_LONGS_EQUAL(1u, cursor.xCleanupEdges);
  UNSIGNED_LONGS_EQUAL(0u, cursor.yCleanupEdges);
}

TEST(CoordinatedXyExecutor, LimitOverridesCancelBeforeCleanup) {
  const CoordinatedXyPlan plan = readyPlan(8, 0);
  Cursor cursor = runningCursor(plan);
  TickResult tick{};
  (void)onTimerUpdate(plan, cursor, tick);
  CHECK_EQUAL(static_cast<int>(ControlDisposition::Deferred),
              static_cast<int>(requestCancel(cursor)));
  CHECK_EQUAL(static_cast<int>(ControlDisposition::Deferred),
              static_cast<int>(
                  requestLimitAbort(cursor, LimitAxis::X)));
  CHECK_EQUAL(static_cast<int>(TickStatus::LimitAborted),
              static_cast<int>(onTimerUpdate(plan, cursor, tick)));
  CHECK_EQUAL(static_cast<int>(TerminalReason::XLimit),
              static_cast<int>(cursor.terminalReason));
  UNSIGNED_LONGS_EQUAL(1u, cursor.xCleanupEdges);
}

TEST(CoordinatedXyExecutor, CancelWhilePausedHighRestartsCleanupState) {
  const CoordinatedXyPlan plan = readyPlan(8, 0);
  Cursor cursor = runningCursor(plan);
  TickResult tick{};
  (void)onTimerUpdate(plan, cursor, tick);
  CHECK_EQUAL(static_cast<int>(ControlDisposition::StopNow),
              static_cast<int>(requestPause(cursor)));
  CHECK_EQUAL(static_cast<int>(State::Paused),
              static_cast<int>(cursor.state));
  CHECK_EQUAL(static_cast<int>(ControlDisposition::Deferred),
              static_cast<int>(requestCancel(cursor)));
  CHECK_EQUAL(static_cast<int>(State::Running),
              static_cast<int>(cursor.state));
  CHECK_EQUAL(static_cast<int>(TickStatus::Canceled),
              static_cast<int>(onTimerUpdate(plan, cursor, tick)));
  CHECK_TRUE(has(tick.cleanupEdgeMask, EdgeMask::X));
}

TEST(CoordinatedXyExecutor, PlannerFaultUsesSameBoundedCleanup) {
  const CoordinatedXyPlan plan = readyPlan(8, 0);
  Cursor low = runningCursor(plan);
  TickResult tick{};
  CHECK_EQUAL(static_cast<int>(TickStatus::Faulted),
              static_cast<int>(forcePlannerFault(low, tick)));
  CHECK_TRUE(tick.stopTimer);

  Cursor high = runningCursor(plan);
  (void)onTimerUpdate(plan, high, tick);
  CHECK_EQUAL(static_cast<int>(TickStatus::CleanupPending),
              static_cast<int>(forcePlannerFault(high, tick)));
  CHECK_FALSE(tick.stopTimer);
  CHECK_EQUAL(static_cast<int>(TickStatus::Faulted),
              static_cast<int>(onTimerUpdate(plan, high, tick)));
  CHECK_TRUE(has(tick.cleanupEdgeMask, EdgeMask::X));
  CHECK_EQUAL(static_cast<int>(TerminalReason::PlannerFault),
              static_cast<int>(high.terminalReason));
}

TEST(CoordinatedXyExecutor, PostEdgePlannerMismatchAccountsThenCleansUp) {
  const CoordinatedXyPlan plan = readyPlan(8, 0);
  CoordinatedXyPlan mismatched = plan;
  ++mismatched.masterEdges;
  Cursor cursor = runningCursor(plan);
  TickResult tick{};
  CHECK_EQUAL(static_cast<int>(TickStatus::CleanupPending),
              static_cast<int>(onTimerUpdate(mismatched, cursor, tick)));
  CHECK_TRUE(has(tick.accountEdgeMask, EdgeMask::X));
  UNSIGNED_LONGS_EQUAL(1u, cursor.xActiveEdges);
  CHECK_EQUAL(static_cast<int>(TickStatus::Faulted),
              static_cast<int>(onTimerUpdate(plan, cursor, tick)));
  UNSIGNED_LONGS_EQUAL(2u, cursor.xActiveEdges);
  UNSIGNED_LONGS_EQUAL(1u, cursor.xCleanupEdges);
}

TEST(CoordinatedXyExecutor, ShallowVectorsHaveNoRuntimeSpacingViolations) {
  const int64_t vectors[][2] = {
      {17100, 4470},
      {17100, 2054},
      {100, 19574},
      {4470, 17100},
      {2054, 17100},
      {19574, 100},
  };
  for (const auto& vector : vectors) {
    for (int sign : {1, -1}) {
      const CoordinatedXyPlan plan =
          readyPlan(sign * vector[0], sign * vector[1]);
      Cursor cursor = runningCursor(plan);
      (void)finish(plan, cursor);
      UNSIGNED_LONGS_EQUAL(0u, cursor.xSpacingViolations);
      UNSIGNED_LONGS_EQUAL(0u, cursor.ySpacingViolations);
      UNSIGNED_LONGS_EQUAL(0u, cursor.cleanupEdgeEvents);
    }
  }
}

TEST(CoordinatedXyExecutor, TerminalCursorCanBeRearmedDeterministically) {
  const CoordinatedXyPlan plan = readyPlan(8, 4);
  Cursor cursor = runningCursor(plan);
  (void)finish(plan, cursor);
  CHECK_EQUAL(static_cast<int>(ArmStatus::Ready),
              static_cast<int>(arm(plan, cursor)));
  CHECK_EQUAL(static_cast<int>(State::Armed),
              static_cast<int>(cursor.state));
}

TEST(CoordinatedXyExecutor, ReservationPolicyRejectsConflictingAxes) {
  AxisReservationState clear{};
  CHECK_EQUAL(static_cast<int>(ReservationStatus::Ready),
              static_cast<int>(evaluateReservation(clear, clear)));
  for (uint32_t field = 0u; field < 3u; ++field) {
    AxisReservationState busy{};
    if (field == 0u) busy.legacyBusy = true;
    if (field == 1u) busy.homingActive = true;
    if (field == 2u) busy.coordinatedReserved = true;
    CHECK_EQUAL(static_cast<int>(ReservationStatus::XBusy),
                static_cast<int>(evaluateReservation(busy, clear)));
    CHECK_EQUAL(static_cast<int>(ReservationStatus::YBusy),
                static_cast<int>(evaluateReservation(clear, busy)));
  }
}
