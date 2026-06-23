#include "ResetReportPolicy.h"

bool ResetReport_ShouldSend(const CrashLogSnapshot* snap) {
  if (snap == nullptr) {
    return false;
  }

  if ((snap->flags & CRASHLOG_FLAG_PENDING) != 0u) {
    return true;
  }

  switch (snap->resetCause) {
    case CRASH_RESET_POWER:
    case CRASH_RESET_PIN:
    case CRASH_RESET_SOFTWARE:
    case CRASH_RESET_IWDG:
    case CRASH_RESET_WWDG:
    case CRASH_RESET_LOW_POWER:
      return true;
    case CRASH_RESET_UNKNOWN:
    default:
      return false;
  }
}
