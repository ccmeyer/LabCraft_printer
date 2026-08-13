#include "CoordinatedXyExecutor.h"
#include "CppUTest/TestHarness.h"

#include <cstdint>
#include <limits>

namespace {

using namespace CoordinatedXyExecutor;
using namespace CoordinatedXyPlanner;
using ExecutorCursor = CoordinatedXyExecutor::Cursor;

PlanRequest normalRequest(int64_t dx, int64_t dy, uint32_t rateHz = 0u) {
  PlanRequest request{};
  request.deltaX = dx;
  request.deltaY = dy;
  request.requestedMasterRateHz = rateHz;
  request.xLimits = {40000u, 140000u};
  request.yLimits = {40000u, 140000u};
  request.timer = {
      90000000u,
      std::numeric_limits<uint32_t>::max(),
      2000u,
  };
  return request;
}

CoordinatedXyPlan readyPlan(int64_t dx, int64_t dy, uint32_t rateHz = 0u) {
  CoordinatedXyPlan plan{};
  const PlanRequest request = normalRequest(dx, dy, rateHz);
  CHECK_EQUAL(static_cast<int>(PlanStatus::Ready),
              static_cast<int>(prepare(request, plan)));
  return plan;
}

ExecutorCursor runningCursor(const CoordinatedXyPlan& plan) {
  ExecutorCursor cursor{};
  CHECK_EQUAL(static_cast<int>(ArmStatus::Ready),
              static_cast<int>(arm(plan, cursor)));
  CHECK_EQUAL(static_cast<int>(ControlDisposition::Deferred),
              static_cast<int>(start(cursor)));
  return cursor;
}

void runToCompletion(const CoordinatedXyPlan& plan, ExecutorCursor& cursor) {
  TickResult result{};
  while (cursor.state == State::Running) {
    const TickStatus status = onTimerUpdate(plan, cursor, result);
    CHECK_TRUE(status != TickStatus::InvalidState);
    CHECK_TRUE(status != TickStatus::Faulted);
  }
  CHECK_EQUAL(static_cast<int>(State::Completed),
              static_cast<int>(cursor.state));
}

}  // namespace

TEST_GROUP(CoordinatedXyExecutor) {
};

TEST(CoordinatedXyExecutor, ImmediateInvalidAndBusyPlansAreExplicit) {
  CoordinatedXyPlan immediate{};
  PlanRequest request{};
  CHECK_EQUAL(static_cast<int>(PlanStatus::Immediate),
              static_cast<int>(prepare(request, immediate)));
  ExecutorCursor cursor{};
  CHECK_EQUAL(static_cast<int>(ArmStatus::Immediate),
              static_cast<int>(arm(immediate, cursor)));
  CHECK_EQUAL(static_cast<int>(State::Completed),
              static_cast<int>(cursor.state));

  CoordinatedXyPlan invalid{};
  CHECK_EQUAL(static_cast<int>(ArmStatus::InvalidPlan),
              static_cast<int>(arm(invalid, cursor)));

  const CoordinatedXyPlan plan = readyPlan(10, 4);
  cursor = runningCursor(plan);
  CHECK_EQUAL(static_cast<int>(ArmStatus::Busy),
              static_cast<int>(arm(plan, cursor)));
  CHECK_EQUAL(static_cast<int>(ControlDisposition::AlreadySatisfied),
              static_cast<int>(start(cursor)));
}

TEST(CoordinatedXyExecutor, EveryMagnitudePairUsesTwoEdgesPerMasterStep) {
  for (int32_t x = 0; x <= 64; ++x) {
    for (int32_t y = 0; y <= 64; ++y) {
      if (x == 0 && y == 0) continue;
      const CoordinatedXyPlan plan = readyPlan(x, y, 3000u);
      ExecutorCursor cursor = runningCursor(plan);
      uint32_t expectedX = 0u;
      uint32_t expectedY = 0u;
      StepMask raisedMask = StepMask::None;
      uint32_t raisedArr = 0u;
      TickResult result{};
      while (cursor.state == State::Running) {
        const TickStatus status = onTimerUpdate(plan, cursor, result);
        if (status == TickStatus::Raised) {
          raisedMask = result.mask;
          raisedArr = result.arr;
          CHECK_FALSE(result.accountCompletePulse);
        } else {
          CHECK_TRUE(status == TickStatus::Lowered ||
                     status == TickStatus::Completed);
          CHECK_EQUAL(static_cast<int>(raisedMask),
                      static_cast<int>(result.mask));
          UNSIGNED_LONGS_EQUAL(raisedArr, result.arr);
          CHECK_TRUE(result.accountCompletePulse);
          if (contains(result.mask, StepMask::X)) ++expectedX;
          if (contains(result.mask, StepMask::Y)) ++expectedY;
        }
      }
      UNSIGNED_LONGS_EQUAL(plan.masterSteps * 2u, cursor.timerInterrupts);
      UNSIGNED_LONGS_EQUAL(plan.masterSteps, cursor.risingEdges);
      UNSIGNED_LONGS_EQUAL(plan.masterSteps, cursor.fallingEdges);
      UNSIGNED_LONGS_EQUAL(plan.xSteps, expectedX);
      UNSIGNED_LONGS_EQUAL(plan.ySteps, expectedY);
      UNSIGNED_LONGS_EQUAL(plan.xSteps, cursor.xEmittedSteps);
      UNSIGNED_LONGS_EQUAL(plan.ySteps, cursor.yEmittedSteps);
      CHECK_FALSE(cursor.stepHigh);
    }
  }
}

TEST(CoordinatedXyExecutor, ReverseDirectionsDoNotChangeEdgeTrace) {
  const CoordinatedXyPlan forward = readyPlan(8416, 30000, 3000u);
  const CoordinatedXyPlan reverse = readyPlan(-8416, -30000, 3000u);
  ExecutorCursor forwardCursor = runningCursor(forward);
  ExecutorCursor reverseCursor = runningCursor(reverse);
  TickResult forwardResult{};
  TickResult reverseResult{};
  while (forwardCursor.state == State::Running) {
    const TickStatus forwardStatus =
        onTimerUpdate(forward, forwardCursor, forwardResult);
    const TickStatus reverseStatus =
        onTimerUpdate(reverse, reverseCursor, reverseResult);
    CHECK_EQUAL(static_cast<int>(forwardStatus),
                static_cast<int>(reverseStatus));
    CHECK_EQUAL(static_cast<int>(forwardResult.mask),
                static_cast<int>(reverseResult.mask));
    UNSIGNED_LONGS_EQUAL(forwardResult.arr, reverseResult.arr);
  }
  UNSIGNED_LONGS_EQUAL(forwardCursor.maskChecksum,
                       reverseCursor.maskChecksum);
  UNSIGNED_LONGS_EQUAL(forwardCursor.arrChecksum,
                       reverseCursor.arrChecksum);
  CHECK_EQUAL(static_cast<int>(Direction::Positive),
              static_cast<int>(forward.xDirection));
  CHECK_EQUAL(static_cast<int>(Direction::Negative),
              static_cast<int>(reverse.xDirection));
}

TEST(CoordinatedXyExecutor, PauseWhileLowStopsImmediatelyAndResumesCachedEvent) {
  const CoordinatedXyPlan plan = readyPlan(20, 7, 3000u);
  ExecutorCursor cursor = runningCursor(plan);
  const StepEvent cached = cursor.cachedEvent;
  CHECK_EQUAL(static_cast<int>(ControlDisposition::StopNow),
              static_cast<int>(requestPause(cursor)));
  CHECK_EQUAL(static_cast<int>(State::Paused), static_cast<int>(cursor.state));
  CHECK_FALSE(cursor.stepHigh);
  CHECK_EQUAL(static_cast<int>(ControlDisposition::AlreadySatisfied),
              static_cast<int>(requestPause(cursor)));
  CHECK_EQUAL(static_cast<int>(ControlDisposition::Deferred),
              static_cast<int>(resume(cursor)));
  CHECK_EQUAL(static_cast<int>(cached.mask),
              static_cast<int>(cursor.cachedEvent.mask));
  UNSIGNED_LONGS_EQUAL(cached.arr, cursor.cachedEvent.arr);
  runToCompletion(plan, cursor);
}

TEST(CoordinatedXyExecutor, PauseWhileHighFinishesPulseThenResumesNextEvent) {
  const CoordinatedXyPlan plan = readyPlan(20, 7, 3000u);
  ExecutorCursor cursor = runningCursor(plan);
  ExecutorCursor uninterrupted = runningCursor(plan);
  TickResult result{};
  TickResult uninterruptedResult{};
  CHECK_EQUAL(static_cast<int>(TickStatus::Raised),
              static_cast<int>(onTimerUpdate(plan, cursor, result)));
  CHECK_EQUAL(static_cast<int>(TickStatus::Raised),
              static_cast<int>(onTimerUpdate(
                  plan, uninterrupted, uninterruptedResult)));
  CHECK_EQUAL(static_cast<int>(uninterruptedResult.mask),
              static_cast<int>(result.mask));
  UNSIGNED_LONGS_EQUAL(uninterruptedResult.arr, result.arr);
  CHECK_EQUAL(static_cast<int>(ControlDisposition::Deferred),
              static_cast<int>(requestPause(cursor)));
  CHECK_EQUAL(static_cast<int>(TickStatus::Paused),
              static_cast<int>(onTimerUpdate(plan, cursor, result)));
  CHECK_EQUAL(static_cast<int>(TickStatus::Lowered),
              static_cast<int>(onTimerUpdate(
                  plan, uninterrupted, uninterruptedResult)));
  CHECK_TRUE(result.accountCompletePulse);
  CHECK_TRUE(result.stopTimer);
  UNSIGNED_LONGS_EQUAL(1u, cursor.fallingEdges);
  CHECK_FALSE(cursor.stepHigh);
  CHECK_EQUAL(static_cast<int>(uninterrupted.cachedEvent.mask),
              static_cast<int>(cursor.cachedEvent.mask));
  UNSIGNED_LONGS_EQUAL(uninterrupted.cachedEvent.arr,
                       cursor.cachedEvent.arr);
  CHECK_EQUAL(static_cast<int>(ControlDisposition::Deferred),
              static_cast<int>(resume(cursor)));

  uint32_t physicalX = contains(result.mask, StepMask::X) ? 1u : 0u;
  uint32_t physicalY = contains(result.mask, StepMask::Y) ? 1u : 0u;
  while (cursor.state == State::Running) {
    const TickStatus status = onTimerUpdate(plan, cursor, result);
    const TickStatus uninterruptedStatus =
        onTimerUpdate(plan, uninterrupted, uninterruptedResult);
    CHECK_EQUAL(static_cast<int>(uninterruptedStatus),
                static_cast<int>(status));
    CHECK_EQUAL(static_cast<int>(uninterruptedResult.mask),
                static_cast<int>(result.mask));
    UNSIGNED_LONGS_EQUAL(uninterruptedResult.arr, result.arr);
    if (result.accountCompletePulse) {
      if (contains(result.mask, StepMask::X)) ++physicalX;
      if (contains(result.mask, StepMask::Y)) ++physicalY;
    }
  }
  CHECK_EQUAL(static_cast<int>(State::Completed),
              static_cast<int>(cursor.state));
  CHECK_EQUAL(static_cast<int>(State::Completed),
              static_cast<int>(uninterrupted.state));
  UNSIGNED_LONGS_EQUAL(plan.xSteps, physicalX);
  UNSIGNED_LONGS_EQUAL(plan.ySteps, physicalY);
  UNSIGNED_LONGS_EQUAL(uninterrupted.maskChecksum, cursor.maskChecksum);
  UNSIGNED_LONGS_EQUAL(uninterrupted.arrChecksum, cursor.arrChecksum);
}

TEST(CoordinatedXyExecutor, PauseDuringFinalHighPulseCompletesWithoutExtraRise) {
  const CoordinatedXyPlan plan = readyPlan(1, 1, 3000u);
  ExecutorCursor cursor = runningCursor(plan);
  TickResult result{};
  CHECK_EQUAL(static_cast<int>(TickStatus::Raised),
              static_cast<int>(onTimerUpdate(plan, cursor, result)));
  CHECK_EQUAL(static_cast<int>(ControlDisposition::Deferred),
              static_cast<int>(requestPause(cursor)));
  CHECK_EQUAL(static_cast<int>(TickStatus::Completed),
              static_cast<int>(onTimerUpdate(plan, cursor, result)));
  CHECK_TRUE(result.accountCompletePulse);
  CHECK_TRUE(result.stopTimer);
  CHECK_TRUE(result.signalDone);
  UNSIGNED_LONGS_EQUAL(1u, cursor.risingEdges);
  UNSIGNED_LONGS_EQUAL(1u, cursor.fallingEdges);
  CHECK_EQUAL(static_cast<int>(State::Completed),
              static_cast<int>(cursor.state));
  CHECK_EQUAL(static_cast<int>(TerminalReason::Completed),
              static_cast<int>(cursor.terminalReason));
  CHECK_EQUAL(static_cast<int>(ControlDisposition::AlreadySatisfied),
              static_cast<int>(requestPause(cursor)));
}

TEST(CoordinatedXyExecutor, CancelLowStopsWithoutAnotherEdge) {
  const CoordinatedXyPlan plan = readyPlan(20, 7, 3000u);
  ExecutorCursor cursor = runningCursor(plan);
  CHECK_EQUAL(static_cast<int>(ControlDisposition::StopNow),
              static_cast<int>(requestCancel(cursor)));
  CHECK_EQUAL(static_cast<int>(State::Canceled), static_cast<int>(cursor.state));
  UNSIGNED_LONGS_EQUAL(0u, cursor.risingEdges);
  UNSIGNED_LONGS_EQUAL(0u, cursor.fallingEdges);
  CHECK_FALSE(cursor.stepHigh);
}

TEST(CoordinatedXyExecutor, CancelHighAccountsOnlyTheInFlightPulse) {
  const CoordinatedXyPlan plan = readyPlan(20, 7, 3000u);
  ExecutorCursor cursor = runningCursor(plan);
  TickResult result{};
  CHECK_EQUAL(static_cast<int>(TickStatus::Raised),
              static_cast<int>(onTimerUpdate(plan, cursor, result)));
  const StepMask inFlightMask = result.mask;
  CHECK_EQUAL(static_cast<int>(ControlDisposition::Deferred),
              static_cast<int>(requestCancel(cursor)));
  CHECK_EQUAL(static_cast<int>(TickStatus::Canceled),
              static_cast<int>(onTimerUpdate(plan, cursor, result)));
  CHECK_EQUAL(static_cast<int>(inFlightMask), static_cast<int>(result.mask));
  CHECK_TRUE(result.accountCompletePulse);
  CHECK_TRUE(result.signalDone);
  UNSIGNED_LONGS_EQUAL(1u, cursor.risingEdges);
  UNSIGNED_LONGS_EQUAL(1u, cursor.fallingEdges);
  CHECK_FALSE(cursor.stepHigh);
}

TEST(CoordinatedXyExecutor, LimitOverridesCancelAndPause) {
  const CoordinatedXyPlan plan = readyPlan(20, 7, 3000u);
  ExecutorCursor cursor = runningCursor(plan);
  TickResult result{};
  (void)onTimerUpdate(plan, cursor, result);
  CHECK_EQUAL(static_cast<int>(ControlDisposition::Deferred),
              static_cast<int>(requestPause(cursor)));
  CHECK_EQUAL(static_cast<int>(ControlDisposition::Deferred),
              static_cast<int>(requestCancel(cursor)));
  CHECK_EQUAL(static_cast<int>(ControlDisposition::Deferred),
              static_cast<int>(requestLimitAbort(cursor, LimitAxis::Y)));
  CHECK_EQUAL(static_cast<int>(ControlDisposition::AlreadySatisfied),
              static_cast<int>(requestCancel(cursor)));
  CHECK_EQUAL(static_cast<int>(TickStatus::LimitAborted),
              static_cast<int>(onTimerUpdate(plan, cursor, result)));
  CHECK_EQUAL(static_cast<int>(State::LimitAborted),
              static_cast<int>(cursor.state));
  CHECK_EQUAL(static_cast<int>(TerminalReason::YLimit),
              static_cast<int>(cursor.terminalReason));
  CHECK_FALSE(cursor.stepHigh);
}

TEST(CoordinatedXyExecutor, LimitWhilePausedTerminatesImmediately) {
  const CoordinatedXyPlan plan = readyPlan(20, 7, 3000u);
  ExecutorCursor cursor = runningCursor(plan);
  CHECK_EQUAL(static_cast<int>(ControlDisposition::StopNow),
              static_cast<int>(requestPause(cursor)));
  CHECK_EQUAL(static_cast<int>(ControlDisposition::StopNow),
              static_cast<int>(requestLimitAbort(cursor, LimitAxis::X)));
  CHECK_EQUAL(static_cast<int>(State::LimitAborted),
              static_cast<int>(cursor.state));
  CHECK_EQUAL(static_cast<int>(TerminalReason::XLimit),
              static_cast<int>(cursor.terminalReason));
}

TEST(CoordinatedXyExecutor, FinalPulseControlRequestRetainsRequestedOutcome) {
  const CoordinatedXyPlan plan = readyPlan(1, 1, 3000u);
  ExecutorCursor cursor = runningCursor(plan);
  TickResult result{};
  CHECK_EQUAL(static_cast<int>(TickStatus::Raised),
              static_cast<int>(onTimerUpdate(plan, cursor, result)));
  (void)requestCancel(cursor);
  CHECK_EQUAL(static_cast<int>(TickStatus::Canceled),
              static_cast<int>(onTimerUpdate(plan, cursor, result)));
  UNSIGNED_LONGS_EQUAL(1u, cursor.xEmittedSteps);
  UNSIGNED_LONGS_EQUAL(1u, cursor.yEmittedSteps);
  CHECK_EQUAL(static_cast<int>(State::Canceled), static_cast<int>(cursor.state));
}

TEST(CoordinatedXyExecutor, InvalidControlsDoNotMutateIdleOrTerminalState) {
  ExecutorCursor cursor{};
  CHECK_EQUAL(static_cast<int>(ControlDisposition::InvalidState),
              static_cast<int>(requestPause(cursor)));
  CHECK_EQUAL(static_cast<int>(ControlDisposition::InvalidState),
              static_cast<int>(resume(cursor)));
  CHECK_EQUAL(static_cast<int>(ControlDisposition::InvalidState),
              static_cast<int>(requestCancel(cursor)));

  const CoordinatedXyPlan plan = readyPlan(2, 1, 3000u);
  cursor = runningCursor(plan);
  runToCompletion(plan, cursor);
  CHECK_EQUAL(static_cast<int>(ControlDisposition::AlreadySatisfied),
              static_cast<int>(requestCancel(cursor)));
  TickResult result{};
  CHECK_EQUAL(static_cast<int>(TickStatus::InvalidState),
              static_cast<int>(onTimerUpdate(plan, cursor, result)));
}

TEST(CoordinatedXyExecutor, PlannerMismatchFaultsAfterAccountingTheHighPulse) {
  CoordinatedXyPlan plan = readyPlan(20, 7, 3000u);
  ExecutorCursor cursor = runningCursor(plan);
  TickResult result{};
  CHECK_EQUAL(static_cast<int>(TickStatus::Raised),
              static_cast<int>(onTimerUpdate(plan, cursor, result)));
  ++plan.masterSteps;
  CHECK_EQUAL(static_cast<int>(TickStatus::Faulted),
              static_cast<int>(onTimerUpdate(plan, cursor, result)));
  CHECK_TRUE(result.accountCompletePulse);
  CHECK_TRUE(result.stopTimer);
  CHECK_TRUE(result.signalDone);
  CHECK_EQUAL(static_cast<int>(State::Faulted), static_cast<int>(cursor.state));
  CHECK_EQUAL(static_cast<int>(TerminalReason::PlannerFault),
              static_cast<int>(cursor.terminalReason));
  CHECK_FALSE(cursor.stepHigh);
}

TEST(CoordinatedXyExecutor, TerminalCursorCanBeRearmedDeterministically) {
  const CoordinatedXyPlan plan = readyPlan(3, 2, 3000u);
  ExecutorCursor cursor = runningCursor(plan);
  runToCompletion(plan, cursor);
  CHECK_EQUAL(static_cast<int>(ArmStatus::Ready),
              static_cast<int>(arm(plan, cursor)));
  CHECK_EQUAL(static_cast<int>(State::Armed), static_cast<int>(cursor.state));
  UNSIGNED_LONGS_EQUAL(0u, cursor.timerInterrupts);
  UNSIGNED_LONGS_EQUAL(0u, cursor.xEmittedSteps);
  UNSIGNED_LONGS_EQUAL(0u, cursor.yEmittedSteps);
}

TEST(CoordinatedXyExecutor, ReservationPolicyRejectsEveryConflictingAxisState) {
  AxisReservationState idle{};
  CHECK_EQUAL(static_cast<int>(ReservationStatus::Ready),
              static_cast<int>(evaluateReservation(idle, idle)));

  AxisReservationState busy{};
  busy.legacyBusy = true;
  CHECK_EQUAL(static_cast<int>(ReservationStatus::XBusy),
              static_cast<int>(evaluateReservation(busy, idle)));
  CHECK_EQUAL(static_cast<int>(ReservationStatus::YBusy),
              static_cast<int>(evaluateReservation(idle, busy)));
  busy = AxisReservationState{};
  busy.homingActive = true;
  CHECK_EQUAL(static_cast<int>(ReservationStatus::XBusy),
              static_cast<int>(evaluateReservation(busy, idle)));
  busy = AxisReservationState{};
  busy.coordinatedReserved = true;
  CHECK_EQUAL(static_cast<int>(ReservationStatus::YBusy),
              static_cast<int>(evaluateReservation(idle, busy)));
}
