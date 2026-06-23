#ifndef INC_CRASHWATCHDOGSELFTESTPOLICY_H_
#define INC_CRASHWATCHDOGSELFTESTPOLICY_H_

#include "CrashLog.h"
#include "WatchdogSupervisor.h"

#include <cstddef>
#include <cstdint>

struct WatchdogSelfTestSnapshot {
  WatchdogArmResult armResult;
  uint32_t enabled;
  uint32_t requiredTaskCount;
  uint32_t liveTaskCount;
  CrashTaskId lateTask;
  uint32_t recoveryBoot;
  uint32_t timeoutMs;
  uint32_t initTimeoutMs;
  uint32_t rawStatus;
  uint32_t stickyStatusCount;
};

bool BuildCrashRecordSelfTestResult(const CrashLogSnapshot& snap,
                                    char* metrics,
                                    size_t metricsLen);

bool BuildWatchdogSupervisorSelfTestResult(const WatchdogSelfTestSnapshot& snap,
                                           char* metrics,
                                           size_t metricsLen);

#endif /* INC_CRASHWATCHDOGSELFTESTPOLICY_H_ */
