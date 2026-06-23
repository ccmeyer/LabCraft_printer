#include "ResetReportPolicy.h"

bool ResetReport_ShouldSend(const CrashLogSnapshot* snap) {
  if (snap == nullptr) {
    return false;
  }

  return true;
}
