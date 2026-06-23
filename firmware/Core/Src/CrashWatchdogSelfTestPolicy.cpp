#include "CrashWatchdogSelfTestPolicy.h"

#include "CrashLogCodec.h"

#include <cstdio>

namespace {

const char* bootStageName(CrashBootStage stage)
{
  switch (stage) {
    case CRASH_BOOT_STAGE_RESET: return "reset";
    case CRASH_BOOT_STAGE_HAL_INIT: return "hal";
    case CRASH_BOOT_STAGE_CRASHLOG_READY: return "crashlog";
    case CRASH_BOOT_STAGE_ORCH_READY: return "orch";
    case CRASH_BOOT_STAGE_LOGGER_READY: return "logger";
    case CRASH_BOOT_STAGE_COMM_INIT: return "comm_init";
    case CRASH_BOOT_STAGE_COMM_RX_ARMED: return "comm_rx";
    case CRASH_BOOT_STAGE_COMM_RX_REARMED: return "comm_rearm";
    case CRASH_BOOT_STAGE_COMM_READY: return "comm";
    case CRASH_BOOT_STAGE_WATCHDOG_TASK_READY: return "wdog_task";
    case CRASH_BOOT_STAGE_HELLO_RX: return "hello_rx";
    case CRASH_BOOT_STAGE_HELLO_ACK: return "hello_ack";
    default: return "unknown";
  }
}

const char* watchdogArmResultName(WatchdogArmResult result)
{
  switch (result) {
    case WATCHDOG_ARM_RESULT_NOT_ATTEMPTED: return "not_attempted";
    case WATCHDOG_ARM_RESULT_ARMED: return "armed";
    case WATCHDOG_ARM_RESULT_SKIPPED_STICKY_STATUS: return "sticky_status_skip";
    case WATCHDOG_ARM_RESULT_RECOVERY_RESET_REQUIRED: return "recovery_reset";
    case WATCHDOG_ARM_RESULT_TIMEOUT_LSI: return "timeout_lsi";
    case WATCHDOG_ARM_RESULT_TIMEOUT_STATUS: return "timeout_status";
    default: return "unknown";
  }
}

} // namespace

bool BuildCrashRecordSelfTestResult(const CrashLogSnapshot& snap,
                                    char* metrics,
                                    size_t metricsLen)
{
  const bool pending = (snap.flags & CRASHLOG_FLAG_PENDING) != 0u;
  const bool sticky = (snap.flags & CRASHLOG_FLAG_WDT_ARM_STICKY) != 0u;
  const bool staleWatchdogHistory =
      pending &&
      sticky &&
      (snap.lastFault == CRASH_FAULT_WDT_STARVE) &&
      (snap.resetCause != CRASH_RESET_IWDG);
  const bool pass = (!pending && (snap.lastFault == CRASH_FAULT_NONE)) || staleWatchdogHistory;

  if (metrics != nullptr && metricsLen > 0u) {
    std::snprintf(metrics,
                  metricsLen,
                  "pending=%u;sticky=%u;fault=%s;task=%s;reset=%s;boot=%lu;fault_ct=%lu;wdg_ct=%lu;sticky_ct=%lu;raw_sr=%lu;boot_stage=%s;wdg_late=%s",
                  pending ? 1u : 0u,
                  sticky ? 1u : 0u,
                  CrashLog_FaultKindName(snap.lastFault),
                  CrashLog_TaskIdName(snap.lastTask),
                  CrashLog_ResetCauseName(snap.resetCause),
                  static_cast<unsigned long>(snap.bootCount),
                  static_cast<unsigned long>(snap.faultCountTotal),
                  static_cast<unsigned long>(snap.watchdogResetCount),
                  static_cast<unsigned long>(snap.watchdogStickyCount),
                  static_cast<unsigned long>(snap.watchdogRawStatus),
                  bootStageName(snap.bootStage),
                  CrashLog_TaskIdName(snap.watchdogLateTask));
  }

  return pass;
}

bool BuildWatchdogSupervisorSelfTestResult(const WatchdogSelfTestSnapshot& snap,
                                           char* metrics,
                                           size_t metricsLen)
{
  const bool passArmed = (snap.armResult == WATCHDOG_ARM_RESULT_ARMED) &&
      (snap.enabled == 1u) &&
      (snap.lateTask == CRASH_TASK_NONE) &&
      (snap.requiredTaskCount > 0u) &&
      (snap.liveTaskCount == snap.requiredTaskCount);
  const bool passStickySkip = (snap.armResult == WATCHDOG_ARM_RESULT_SKIPPED_STICKY_STATUS) &&
      (snap.enabled == 0u) &&
      (snap.lateTask == CRASH_TASK_NONE) &&
      (snap.requiredTaskCount == 0u) &&
      (snap.liveTaskCount == 0u);
  const bool pass = passArmed || passStickySkip;

  if (metrics != nullptr && metricsLen > 0u) {
    std::snprintf(metrics,
                  metricsLen,
                  "enabled=%lu;arm_result=%s;timeout_ms=%lu;init_timeout_ms=%lu;req_n=%lu;live_n=%lu;late_task=%s;raw_sr=%lu;sticky_ct=%lu;recovery_boot=%lu",
                  static_cast<unsigned long>(snap.enabled),
                  watchdogArmResultName(snap.armResult),
                  static_cast<unsigned long>(snap.timeoutMs),
                  static_cast<unsigned long>(snap.initTimeoutMs),
                  static_cast<unsigned long>(snap.requiredTaskCount),
                  static_cast<unsigned long>(snap.liveTaskCount),
                  CrashLog_TaskIdName(snap.lateTask),
                  static_cast<unsigned long>(snap.rawStatus),
                  static_cast<unsigned long>(snap.stickyStatusCount),
                  static_cast<unsigned long>(snap.recoveryBoot));
  }

  return pass;
}
