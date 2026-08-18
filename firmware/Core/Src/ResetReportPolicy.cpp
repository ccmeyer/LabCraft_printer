#include "ResetReportPolicy.h"

bool ResetReport_ShouldSend(const CrashLogSnapshot* snap) {
  if (snap == nullptr) {
    return false;
  }

  return true;
}

bool ResetReport_ShouldAttemptDelivery(const CrashLogSnapshot* snap,
                                       bool hostReady,
                                       bool alreadySent) {
  return hostReady && !alreadySent && ResetReport_ShouldSend(snap);
}

bool ResetReport_ShouldIncludeRegulatorContext(const CrashLogSnapshot* snap) {
  if (snap == nullptr || snap->regulatorContext.valid == 0u) {
    return false;
  }

  return (snap->resetCause == CRASH_RESET_IWDG) ||
         (snap->resetCause == CRASH_RESET_WWDG) ||
         (snap->lastFault == CRASH_FAULT_WDT_STARVE);
}

ResetReportContextSelection ResetReport_SelectContexts(const CrashLogSnapshot* snap) {
  ResetReportContextSelection selection{};
  if (snap == nullptr) {
    return selection;
  }

  selection.includeRegulatorContext = ResetReport_ShouldIncludeRegulatorContext(snap);
  const bool pendingFaultContext =
      ((snap->flags & CRASHLOG_FLAG_PENDING) != 0u) && (snap->faultContextValid != 0u);
  selection.includeFaultContext =
      (snap->faultContextValid != 0u) &&
      (pendingFaultContext || snap->xyMotionContextValid == 0u);
  selection.includeXyMotionContext =
      (snap->xyMotionContextValid != 0u) && !pendingFaultContext;
  return selection;
}
