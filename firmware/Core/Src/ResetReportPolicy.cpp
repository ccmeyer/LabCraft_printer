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
