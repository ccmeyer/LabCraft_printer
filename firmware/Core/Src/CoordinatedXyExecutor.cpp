#include "CoordinatedXyExecutor.h"

namespace CoordinatedXyExecutor {

namespace {

#if defined(__GNUC__) && !defined(UNIT_TEST)
#define LC_COORDINATED_EDGE_OPTIMIZED __attribute__((optimize("O2"), hot))
#define LC_COORDINATED_EDGE_ALWAYS_INLINE \
  inline __attribute__((always_inline, optimize("O2")))
#else
#define LC_COORDINATED_EDGE_OPTIMIZED
#define LC_COORDINATED_EDGE_ALWAYS_INLINE inline
#endif

using CoordinatedXyPlanner::TraceStatus;

LC_COORDINATED_EDGE_OPTIMIZED
uint32_t hashWord(uint32_t checksum, uint32_t value) {
  for (uint32_t shift = 0u; shift < 32u; shift += 8u) {
    checksum ^= (value >> shift) & 0xFFu;
    checksum *= 16777619u;
  }
  return checksum;
}

LC_COORDINATED_EDGE_ALWAYS_INLINE
uint8_t controlPriority(PendingControl control) {
  switch (control) {
    case PendingControl::XLimit:
    case PendingControl::YLimit:
      return 3u;
    case PendingControl::Cancel:
      return 2u;
    case PendingControl::Pause:
      return 1u;
    case PendingControl::None:
    default:
      return 0u;
  }
}

LC_COORDINATED_EDGE_ALWAYS_INLINE
void setTerminal(Cursor& cursor, PendingControl control) {
  cursor.pendingControl = PendingControl::None;
  cursor.stepHigh = false;
  switch (control) {
    case PendingControl::Cancel:
      cursor.state = State::Canceled;
      cursor.terminalReason = TerminalReason::Canceled;
      break;
    case PendingControl::XLimit:
      cursor.state = State::LimitAborted;
      cursor.terminalReason = TerminalReason::XLimit;
      break;
    case PendingControl::YLimit:
      cursor.state = State::LimitAborted;
      cursor.terminalReason = TerminalReason::YLimit;
      break;
    default:
      cursor.state = State::Faulted;
      cursor.terminalReason = TerminalReason::PlannerFault;
      break;
  }
}

LC_COORDINATED_EDGE_OPTIMIZED
void setPlannerFault(Cursor& cursor, TickResult& result) {
  cursor.pendingControl = PendingControl::None;
  cursor.stepHigh = false;
  cursor.state = State::Faulted;
  cursor.terminalReason = TerminalReason::PlannerFault;
  result.status = TickStatus::Faulted;
  result.stopTimer = true;
  result.signalDone = true;
}

LC_COORDINATED_EDGE_ALWAYS_INLINE
ControlDisposition requestControl(Cursor& cursor, PendingControl requested) {
  if (cursor.state == State::Completed || cursor.state == State::Canceled ||
      cursor.state == State::LimitAborted || cursor.state == State::Faulted) {
    return ControlDisposition::AlreadySatisfied;
  }
  if (cursor.state != State::Running && cursor.state != State::Armed &&
      cursor.state != State::Paused) {
    return ControlDisposition::InvalidState;
  }

  if (cursor.pendingControl != PendingControl::None) {
    const uint8_t pendingPriority = controlPriority(cursor.pendingControl);
    const uint8_t requestedPriority = controlPriority(requested);
    if (pendingPriority > requestedPriority ||
        (pendingPriority == requestedPriority &&
         cursor.pendingControl != PendingControl::Pause)) {
      return ControlDisposition::AlreadySatisfied;
    }
  }

  if (requested == PendingControl::Pause && cursor.state == State::Paused) {
    return ControlDisposition::AlreadySatisfied;
  }

  cursor.pendingControl = requested;
  if (cursor.stepHigh) return ControlDisposition::Deferred;

  if (requested == PendingControl::Pause) {
    cursor.pendingControl = PendingControl::None;
    cursor.state = State::Paused;
  } else {
    setTerminal(cursor, requested);
  }
  return ControlDisposition::StopNow;
}

LC_COORDINATED_EDGE_OPTIMIZED
TickStatus applyDeferredControl(Cursor& cursor, TickResult& result) {
  const PendingControl pending = cursor.pendingControl;
  cursor.pendingControl = PendingControl::None;
  result.stopTimer = true;
  if (pending == PendingControl::Pause) {
    cursor.state = State::Paused;
    result.status = TickStatus::Paused;
    return result.status;
  }

  setTerminal(cursor, pending);
  result.signalDone = true;
  result.status = cursor.state == State::Canceled
      ? TickStatus::Canceled
      : TickStatus::LimitAborted;
  return result.status;
}

}  // namespace

ArmStatus arm(const CoordinatedXyPlanner::CoordinatedXyPlan& plan,
              Cursor& cursor) {
  if (isActive(cursor)) return ArmStatus::Busy;

  cursor = Cursor{};
  const TraceStatus status = CoordinatedXyPlanner::begin(plan, cursor.planner);
  if (status == TraceStatus::Complete &&
      plan.status == CoordinatedXyPlanner::PlanStatus::Immediate) {
    cursor.state = State::Completed;
    cursor.terminalReason = TerminalReason::Completed;
    return ArmStatus::Immediate;
  }
  if (status != TraceStatus::Ready ||
      CoordinatedXyPlanner::currentEvent(cursor.planner, cursor.cachedEvent) !=
          TraceStatus::Ready) {
    cursor = Cursor{};
    return ArmStatus::InvalidPlan;
  }

  cursor.state = State::Armed;
  return ArmStatus::Ready;
}

ControlDisposition start(Cursor& cursor) {
  if (cursor.state == State::Running) {
    return ControlDisposition::AlreadySatisfied;
  }
  if (cursor.state != State::Armed) return ControlDisposition::InvalidState;
  cursor.state = State::Running;
  return ControlDisposition::Deferred;
}

ControlDisposition requestPause(Cursor& cursor) {
  return requestControl(cursor, PendingControl::Pause);
}

ControlDisposition resume(Cursor& cursor) {
  if (cursor.state == State::Running) {
    return ControlDisposition::AlreadySatisfied;
  }
  if (cursor.state != State::Paused || cursor.stepHigh) {
    return ControlDisposition::InvalidState;
  }
  cursor.state = State::Running;
  return ControlDisposition::Deferred;
}

ControlDisposition requestCancel(Cursor& cursor) {
  return requestControl(cursor, PendingControl::Cancel);
}

LC_COORDINATED_EDGE_OPTIMIZED
ControlDisposition requestLimitAbort(Cursor& cursor, LimitAxis axis) {
  return requestControl(cursor,
                        axis == LimitAxis::X ? PendingControl::XLimit
                                             : PendingControl::YLimit);
}

LC_COORDINATED_EDGE_OPTIMIZED
TickStatus onTimerUpdate(const CoordinatedXyPlanner::CoordinatedXyPlan& plan,
                         Cursor& cursor,
                         TickResult& result) {
  result = TickResult{};
  if (cursor.state != State::Running) return result.status;

  ++cursor.timerInterrupts;
  if (!cursor.stepHigh) {
    if (cursor.pendingControl != PendingControl::None) {
      return applyDeferredControl(cursor, result);
    }
    result.status = TickStatus::Raised;
    result.mask = cursor.cachedEvent.mask;
    result.arr = cursor.cachedEvent.arr;
    cursor.stepHigh = true;
    ++cursor.risingEdges;
    return result.status;
  }

  result.status = TickStatus::Lowered;
  result.mask = cursor.cachedEvent.mask;
  result.arr = cursor.cachedEvent.arr;
  result.accountCompletePulse = true;
  cursor.stepHigh = false;
  ++cursor.fallingEdges;
  cursor.maskChecksum = hashWord(
      cursor.maskChecksum, static_cast<uint32_t>(cursor.cachedEvent.mask));
  cursor.arrChecksum = hashWord(cursor.arrChecksum, cursor.cachedEvent.arr);

  const TraceStatus advanceStatus =
      CoordinatedXyPlanner::completeCurrentStep(plan, cursor.planner);
  cursor.xEmittedSteps = cursor.planner.xEmittedSteps;
  cursor.yEmittedSteps = cursor.planner.yEmittedSteps;
  if (advanceStatus != TraceStatus::Ready &&
      advanceStatus != TraceStatus::Complete) {
    setPlannerFault(cursor, result);
    return result.status;
  }

  if (advanceStatus == TraceStatus::Complete) {
    // Cancel and limit requests retain their terminal reason even when they
    // arrive during the final high phase. A pause at the same point has no
    // remaining event to preserve, so completing is the only resumable-safe
    // outcome and guarantees that no extra rising edge can be emitted.
    if (cursor.pendingControl != PendingControl::None &&
        cursor.pendingControl != PendingControl::Pause) {
      return applyDeferredControl(cursor, result);
    }
    cursor.pendingControl = PendingControl::None;
    cursor.state = State::Completed;
    cursor.terminalReason = TerminalReason::Completed;
    result.status = TickStatus::Completed;
    result.stopTimer = true;
    result.signalDone = true;
    return result.status;
  }

  // Cancel/limit requests do not need another event. Apply them before the
  // next-event lookup to keep their terminal ISR path bounded.
  if (cursor.pendingControl != PendingControl::None &&
      cursor.pendingControl != PendingControl::Pause) {
    return applyDeferredControl(cursor, result);
  }

  // The falling edge advanced the planner, so refresh the cache before
  // entering Paused. Resume must raise this next event, never repeat the event
  // whose falling edge was just accounted.
  if (CoordinatedXyPlanner::currentEvent(cursor.planner,
                                         cursor.cachedEvent) !=
      TraceStatus::Ready) {
    setPlannerFault(cursor, result);
    return result.status;
  }
  result.nextArr = cursor.cachedEvent.arr;
  result.updateArr = true;
  if (cursor.pendingControl == PendingControl::Pause) {
    return applyDeferredControl(cursor, result);
  }
  return result.status;
}

bool isActive(const Cursor& cursor) {
  return cursor.state == State::Armed || cursor.state == State::Running ||
         cursor.state == State::Paused;
}

bool isTerminal(const Cursor& cursor) {
  return cursor.state == State::Completed || cursor.state == State::Canceled ||
         cursor.state == State::LimitAborted || cursor.state == State::Faulted;
}

ReservationStatus evaluateReservation(const AxisReservationState& x,
                                      const AxisReservationState& y) {
  if (x.legacyBusy || x.homingActive || x.coordinatedReserved) {
    return ReservationStatus::XBusy;
  }
  if (y.legacyBusy || y.homingActive || y.coordinatedReserved) {
    return ReservationStatus::YBusy;
  }
  return ReservationStatus::Ready;
}

#undef LC_COORDINATED_EDGE_OPTIMIZED
#undef LC_COORDINATED_EDGE_ALWAYS_INLINE

}  // namespace CoordinatedXyExecutor
