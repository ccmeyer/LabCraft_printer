#ifndef INC_COORDINATEDXYEXECUTOR_H_
#define INC_COORDINATEDXYEXECUTOR_H_

#include "CoordinatedXyPlanner.h"

#include <cstdint>

#ifndef LC_COORDINATED_XY_EXECUTOR_ENABLE
#define LC_COORDINATED_XY_EXECUTOR_ENABLE 1
#endif

#ifndef LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE
#define LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE 1
#endif

#if (LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE != 0) && \
    (LC_COORDINATED_XY_EXECUTOR_ENABLE == 0)
#error "Coordinated XY normal routing requires the coordinated XY executor"
#endif

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
  Raised = 0u,
  Lowered = 1u,
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
};

struct TickResult {
  TickStatus status = TickStatus::InvalidState;
  CoordinatedXyPlanner::StepMask mask = CoordinatedXyPlanner::StepMask::None;
  uint32_t arr = 0u;
  uint32_t nextArr = 0u;
  bool updateArr = false;
  bool accountCompletePulse = false;
  bool stopTimer = false;
  bool signalDone = false;
};

struct Cursor {
  CoordinatedXyPlanner::Cursor planner{};
  CoordinatedXyPlanner::StepEvent cachedEvent{};
  State state = State::Idle;
  TerminalReason terminalReason = TerminalReason::None;
  PendingControl pendingControl = PendingControl::None;
  bool stepHigh = false;
  uint32_t timerInterrupts = 0u;
  uint32_t risingEdges = 0u;
  uint32_t fallingEdges = 0u;
  uint32_t xEmittedSteps = 0u;
  uint32_t yEmittedSteps = 0u;
  uint32_t maskChecksum = 2166136261u;
  uint32_t arrChecksum = 2166136261u;
};

ArmStatus arm(const CoordinatedXyPlanner::CoordinatedXyPlan& plan,
              Cursor& cursor);
ControlDisposition start(Cursor& cursor);
ControlDisposition requestPause(Cursor& cursor);
ControlDisposition resume(Cursor& cursor);
ControlDisposition requestCancel(Cursor& cursor);
ControlDisposition requestLimitAbort(Cursor& cursor, LimitAxis axis);
TickStatus onTimerUpdate(const CoordinatedXyPlanner::CoordinatedXyPlan& plan,
                         Cursor& cursor,
                         TickResult& result);
bool isActive(const Cursor& cursor);
bool isTerminal(const Cursor& cursor);
ReservationStatus evaluateReservation(const AxisReservationState& x,
                                      const AxisReservationState& y);

}  // namespace CoordinatedXyExecutor

#endif /* INC_COORDINATEDXYEXECUTOR_H_ */
