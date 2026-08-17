#include "CoordinatedXyExecutor.h"

#include <limits>

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

using CoordinatedXyPlanner::EdgeMask;
using CoordinatedXyPlanner::TraceStatus;

LC_COORDINATED_EDGE_ALWAYS_INLINE
bool anyStepHigh(const Cursor& cursor) {
  return cursor.xStepHigh || cursor.yStepHigh;
}

LC_COORDINATED_EDGE_OPTIMIZED
uint32_t hashWord(uint32_t checksum, uint32_t value) {
  for (uint32_t shift = 0u; shift < 32u; shift += 8u) {
    checksum ^= (value >> shift) & 0xFFu;
    checksum *= 16777619u;
  }
  return checksum;
}

LC_COORDINATED_EDGE_ALWAYS_INLINE
void saturatingIncrement(uint32_t& value) {
  if (value != std::numeric_limits<uint32_t>::max()) ++value;
}

LC_COORDINATED_EDGE_ALWAYS_INLINE
uint8_t controlPriority(PendingControl control) {
  switch (control) {
    case PendingControl::PlannerFault:
      return 4u;
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
TickStatus terminalStatus(PendingControl control) {
  switch (control) {
    case PendingControl::Cancel:
      return TickStatus::Canceled;
    case PendingControl::XLimit:
    case PendingControl::YLimit:
      return TickStatus::LimitAborted;
    case PendingControl::PlannerFault:
    default:
      return TickStatus::Faulted;
  }
}

LC_COORDINATED_EDGE_ALWAYS_INLINE
void setTerminal(Cursor& cursor, PendingControl control) {
  cursor.pendingControl = PendingControl::None;
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
    case PendingControl::PlannerFault:
    default:
      cursor.state = State::Faulted;
      cursor.terminalReason = TerminalReason::PlannerFault;
      break;
  }
}

LC_COORDINATED_EDGE_ALWAYS_INLINE
void finishTerminal(Cursor& cursor,
                    PendingControl control,
                    TickResult& result) {
  setTerminal(cursor, control);
  result.status = terminalStatus(control);
  result.stopTimer = true;
  result.signalDone = true;
}

LC_COORDINATED_EDGE_ALWAYS_INLINE
void recordSpacing(uint32_t masterEdgeIndex,
                   uint32_t axisEdges,
                   uint32_t masterEdges,
                   bool& hasPrevious,
                   uint32_t& previousIndex,
                   uint32_t& violations) {
  if (axisEdges == 0u) return;
  if (hasPrevious) {
    const uint32_t gap = masterEdgeIndex - previousIndex;
    const uint32_t minimumGap = masterEdges / axisEdges;
    const uint32_t maximumGap = minimumGap +
        ((masterEdges % axisEdges) != 0u ? 1u : 0u);
    if (gap < minimumGap || gap > maximumGap) {
      saturatingIncrement(violations);
    }
  }
  previousIndex = masterEdgeIndex;
  hasPrevious = true;
}

LC_COORDINATED_EDGE_ALWAYS_INLINE
void applyEdgePhases(Cursor& cursor,
                     EdgeMask mask,
                     TickResult& result) {
  result.edgeMask = mask;
  result.accountEdgeMask = mask;
  if (CoordinatedXyPlanner::contains(mask, EdgeMask::X)) {
    cursor.xStepHigh = !cursor.xStepHigh;
    if (cursor.xStepHigh) {
      result.highMask = result.highMask | EdgeMask::X;
    } else {
      result.lowMask = result.lowMask | EdgeMask::X;
    }
    saturatingIncrement(cursor.xActiveEdges);
  }
  if (CoordinatedXyPlanner::contains(mask, EdgeMask::Y)) {
    cursor.yStepHigh = !cursor.yStepHigh;
    if (cursor.yStepHigh) {
      result.highMask = result.highMask | EdgeMask::Y;
    } else {
      result.lowMask = result.lowMask | EdgeMask::Y;
    }
    saturatingIncrement(cursor.yActiveEdges);
  }
}

LC_COORDINATED_EDGE_OPTIMIZED
TickStatus emitCleanupEdge(Cursor& cursor, TickResult& result) {
  const PendingControl terminalControl = cursor.pendingControl;
  EdgeMask cleanupMask = EdgeMask::None;
  if (cursor.xStepHigh) cleanupMask = cleanupMask | EdgeMask::X;
  if (cursor.yStepHigh) cleanupMask = cleanupMask | EdgeMask::Y;
  if (cleanupMask == EdgeMask::None) {
    finishTerminal(cursor, terminalControl, result);
    return result.status;
  }

  result.arr = cursor.cachedEvent.arr;
  result.cleanupEdgeMask = cleanupMask;
  applyEdgePhases(cursor, cleanupMask, result);
  saturatingIncrement(cursor.cleanupEdgeEvents);
  if (CoordinatedXyPlanner::contains(cleanupMask, EdgeMask::X)) {
    saturatingIncrement(cursor.xCleanupEdges);
  }
  if (CoordinatedXyPlanner::contains(cleanupMask, EdgeMask::Y)) {
    saturatingIncrement(cursor.yCleanupEdges);
  }
  finishTerminal(cursor, terminalControl, result);
  return result.status;
}

LC_COORDINATED_EDGE_ALWAYS_INLINE
void deferOrFinishPlannerFault(Cursor& cursor, TickResult& result) {
  cursor.pendingControl = PendingControl::PlannerFault;
  if (anyStepHigh(cursor)) {
    cursor.state = State::Running;
    result.status = TickStatus::CleanupPending;
    result.stopTimer = false;
    result.signalDone = false;
    return;
  }
  finishTerminal(cursor, PendingControl::PlannerFault, result);
}

LC_COORDINATED_EDGE_ALWAYS_INLINE
ControlDisposition requestControl(Cursor& cursor, PendingControl requested) {
  if (isTerminal(cursor)) return ControlDisposition::AlreadySatisfied;
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

  if (requested == PendingControl::Pause) {
    if (cursor.state == State::Paused) {
      return ControlDisposition::AlreadySatisfied;
    }
    cursor.pendingControl = PendingControl::None;
    cursor.state = State::Paused;
    return ControlDisposition::StopNow;
  }

  cursor.pendingControl = requested;
  if (anyStepHigh(cursor)) {
    // A paused move has no running timer. Re-enter Running so the caller can
    // start exactly one interval that emits the accounted cleanup fall.
    if (cursor.state == State::Paused || cursor.state == State::Armed) {
      cursor.state = State::Running;
    }
    return ControlDisposition::Deferred;
  }

  TickResult unused{};
  finishTerminal(cursor, requested, unused);
  return ControlDisposition::StopNow;
}

}  // namespace

ArmStatus arm(const CoordinatedXyPlanner::CoordinatedXyPlan& plan,
              Cursor& cursor,
              bool initialXStepHigh,
              bool initialYStepHigh) {
  if (isActive(cursor)) return ArmStatus::Busy;

  cursor = Cursor{};
  cursor.xStepHigh = initialXStepHigh;
  cursor.yStepHigh = initialYStepHigh;
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
  if (cursor.state != State::Paused) {
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

  saturatingIncrement(cursor.timerInterrupts);
  if (cursor.pendingControl != PendingControl::None) {
    return emitCleanupEdge(cursor, result);
  }

  result.status = TickStatus::EdgeEmitted;
  result.arr = cursor.cachedEvent.arr;
  const EdgeMask mask = cursor.cachedEvent.mask;
  const uint32_t masterEdgeIndex = cursor.cachedEvent.masterEdgeIndex;
  applyEdgePhases(cursor, mask, result);
  saturatingIncrement(cursor.plannedEdgeEvents);
  if (CoordinatedXyPlanner::contains(mask, EdgeMask::X)) {
    recordSpacing(masterEdgeIndex,
                  plan.xEdges,
                  plan.masterEdges,
                  cursor.xHasPreviousEdge,
                  cursor.xLastMasterEdgeIndex,
                  cursor.xSpacingViolations);
  }
  if (CoordinatedXyPlanner::contains(mask, EdgeMask::Y)) {
    recordSpacing(masterEdgeIndex,
                  plan.yEdges,
                  plan.masterEdges,
                  cursor.yHasPreviousEdge,
                  cursor.yLastMasterEdgeIndex,
                  cursor.ySpacingViolations);
  }
  cursor.maskChecksum = hashWord(
      cursor.maskChecksum, static_cast<uint32_t>(mask));
  cursor.arrChecksum = hashWord(cursor.arrChecksum, cursor.cachedEvent.arr);

  const TraceStatus advanceStatus =
      CoordinatedXyPlanner::completeCurrentEdge(plan, cursor.planner);
  if (advanceStatus != TraceStatus::Ready &&
      advanceStatus != TraceStatus::Complete) {
    deferOrFinishPlannerFault(cursor, result);
    return result.status;
  }

  if (advanceStatus == TraceStatus::Complete) {
    cursor.pendingControl = PendingControl::None;
    cursor.state = State::Completed;
    cursor.terminalReason = TerminalReason::Completed;
    result.status = TickStatus::Completed;
    result.stopTimer = true;
    result.signalDone = true;
    return result.status;
  }

  if (CoordinatedXyPlanner::currentEvent(cursor.planner,
                                         cursor.cachedEvent) !=
      TraceStatus::Ready) {
    deferOrFinishPlannerFault(cursor, result);
    return result.status;
  }
  result.nextArr = cursor.cachedEvent.arr;
  result.updateArr = true;
  return result.status;
}

LC_COORDINATED_EDGE_OPTIMIZED
TickStatus forcePlannerFault(Cursor& cursor, TickResult& result) {
  result = TickResult{};
  if (!isActive(cursor)) return result.status;
  deferOrFinishPlannerFault(cursor, result);
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
