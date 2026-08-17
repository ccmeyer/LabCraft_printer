#ifndef INC_COORDINATEDXYEXECUTOR_H_
#define INC_COORDINATEDXYEXECUTOR_H_

#include "CoordinatedXyPlanner.h"

#include <cstdint>

namespace CoordinatedXyExecutor {

enum class State : uint8_t {
  Idle = 0u,
  Armed = 1u,
  Running = 2u,
  Paused = 3u,
  Completed = 4u,
  Canceled = 5u,
  LimitAborted = 6u,
  Faulted = 7u,
};

enum class TerminalReason : uint8_t {
  None = 0u,
  Completed = 1u,
  Canceled = 2u,
  XLimit = 3u,
  YLimit = 4u,
  PlannerFault = 5u,
};

enum class LimitAxis : uint8_t {
  X = 0u,
  Y = 1u,
};

enum class ArmStatus : uint8_t {
  Ready = 0u,
  Immediate = 1u,
  Busy = 2u,
  InvalidPlan = 3u,
};

enum class ControlDisposition : uint8_t {
  Deferred = 0u,
  StopNow = 1u,
  AlreadySatisfied = 2u,
  InvalidState = 3u,
};

enum class TickStatus : uint8_t {
  EdgeEmitted = 0u,
  CleanupPending = 1u,
  Paused = 2u,
  Completed = 3u,
  Canceled = 4u,
  LimitAborted = 5u,
  Faulted = 6u,
  InvalidState = 7u,
};

enum class ReservationStatus : uint8_t {
  Ready = 0u,
  XBusy = 1u,
  YBusy = 2u,
};

struct AxisReservationState {
  bool legacyBusy = false;
  bool homingActive = false;
  bool coordinatedReserved = false;
};

enum class PendingControl : uint8_t {
  None = 0u,
  Pause = 1u,
  Cancel = 2u,
  XLimit = 3u,
  YLimit = 4u,
  PlannerFault = 5u,
};

struct TickResult {
  TickStatus status = TickStatus::InvalidState;
  CoordinatedXyPlanner::EdgeMask edgeMask =
      CoordinatedXyPlanner::EdgeMask::None;
  CoordinatedXyPlanner::EdgeMask highMask =
      CoordinatedXyPlanner::EdgeMask::None;
  CoordinatedXyPlanner::EdgeMask lowMask =
      CoordinatedXyPlanner::EdgeMask::None;
  CoordinatedXyPlanner::EdgeMask accountEdgeMask =
      CoordinatedXyPlanner::EdgeMask::None;
  CoordinatedXyPlanner::EdgeMask cleanupEdgeMask =
      CoordinatedXyPlanner::EdgeMask::None;
  uint32_t arr = 0u;
  uint32_t nextArr = 0u;
  bool updateArr = false;
  bool stopTimer = false;
  bool signalDone = false;
};

struct Cursor {
  CoordinatedXyPlanner::Cursor planner{};
  CoordinatedXyPlanner::EdgeEvent cachedEvent{};
  State state = State::Idle;
  TerminalReason terminalReason = TerminalReason::None;
  PendingControl pendingControl = PendingControl::None;
  bool xStepHigh = false;
  bool yStepHigh = false;
  uint32_t timerInterrupts = 0u;
  uint32_t plannedEdgeEvents = 0u;
  uint32_t cleanupEdgeEvents = 0u;
  uint32_t xActiveEdges = 0u;
  uint32_t yActiveEdges = 0u;
  uint32_t xCleanupEdges = 0u;
  uint32_t yCleanupEdges = 0u;
  uint32_t xSpacingViolations = 0u;
  uint32_t ySpacingViolations = 0u;
  uint32_t xLastMasterEdgeIndex = 0u;
  uint32_t yLastMasterEdgeIndex = 0u;
  bool xHasPreviousEdge = false;
  bool yHasPreviousEdge = false;
  uint32_t maskChecksum = 2166136261u;
  uint32_t arrChecksum = 2166136261u;
};

ArmStatus arm(const CoordinatedXyPlanner::CoordinatedXyPlan& plan,
              Cursor& cursor,
              bool initialXStepHigh = false,
              bool initialYStepHigh = false);
ControlDisposition start(Cursor& cursor);
ControlDisposition requestPause(Cursor& cursor);
ControlDisposition resume(Cursor& cursor);
ControlDisposition requestCancel(Cursor& cursor);
ControlDisposition requestLimitAbort(Cursor& cursor, LimitAxis axis);
TickStatus onTimerUpdate(const CoordinatedXyPlanner::CoordinatedXyPlan& plan,
                         Cursor& cursor,
                         TickResult& result);
TickStatus forcePlannerFault(Cursor& cursor, TickResult& result);
inline constexpr uint32_t elapsedCoreCycles(uint32_t startCycle,
                                            uint32_t endCycle) {
  return endCycle - startCycle;
}
bool isActive(const Cursor& cursor);
bool isTerminal(const Cursor& cursor);
ReservationStatus evaluateReservation(const AxisReservationState& x,
                                      const AxisReservationState& y);

}  // namespace CoordinatedXyExecutor

#endif /* INC_COORDINATEDXYEXECUTOR_H_ */
