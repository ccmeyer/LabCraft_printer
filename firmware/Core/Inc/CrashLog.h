#ifndef INC_CRASHLOG_H_
#define INC_CRASHLOG_H_

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#ifndef LC_CRASHLOG_ENABLE
#define LC_CRASHLOG_ENABLE 1
#endif

#ifndef LC_CRASHLOG_EARLY_BOOT_ENABLE
#define LC_CRASHLOG_EARLY_BOOT_ENABLE 1
#endif

#ifndef LC_CRASHLOG_BOOT_BREADCRUMBS_ENABLE
#define LC_CRASHLOG_BOOT_BREADCRUMBS_ENABLE 1
#endif

#ifndef LC_CRASHLOG_BOOT_SUMMARY_ENABLE
#define LC_CRASHLOG_BOOT_SUMMARY_ENABLE 1
#endif

#ifndef LC_CRASHLOG_SELFTEST_ENABLE
#define LC_CRASHLOG_SELFTEST_ENABLE 1
#endif

#ifndef LC_CRASHLOG_FAULT_HOOKS_ENABLE
#define LC_CRASHLOG_FAULT_HOOKS_ENABLE 1
#endif

typedef enum {
  CRASH_FAULT_NONE = 0,
  CRASH_FAULT_HARD,
  CRASH_FAULT_MEM,
  CRASH_FAULT_BUS,
  CRASH_FAULT_USAGE,
  CRASH_FAULT_NMI,
  CRASH_FAULT_STACK_OVF,
  CRASH_FAULT_ASSERT,
  CRASH_FAULT_ERROR,
  CRASH_FAULT_WDT_STARVE
} CrashFaultKind;

typedef enum {
  CRASH_RESET_UNKNOWN = 0,
  CRASH_RESET_POWER,
  CRASH_RESET_PIN,
  CRASH_RESET_SOFTWARE,
  CRASH_RESET_IWDG,
  CRASH_RESET_WWDG,
  CRASH_RESET_LOW_POWER
} CrashResetCause;

typedef enum {
  CRASH_TASK_NONE = 0,
  CRASH_TASK_BOOT,
  CRASH_TASK_ORCH,
  CRASH_TASK_STATUS,
  CRASH_TASK_PRESSURE,
  CRASH_TASK_PREG_P,
  CRASH_TASK_PREG_R,
  CRASH_TASK_COUNT
} CrashTaskId;

typedef enum {
  CRASH_BOOT_STAGE_RESET = 0,
  CRASH_BOOT_STAGE_HAL_INIT,
  CRASH_BOOT_STAGE_CRASHLOG_READY,
  CRASH_BOOT_STAGE_ORCH_READY,
  CRASH_BOOT_STAGE_LOGGER_READY,
  CRASH_BOOT_STAGE_COMM_INIT,
  CRASH_BOOT_STAGE_COMM_RX_ARMED,
  CRASH_BOOT_STAGE_COMM_RX_REARMED,
  CRASH_BOOT_STAGE_COMM_READY,
  CRASH_BOOT_STAGE_WATCHDOG_TASK_READY,
  CRASH_BOOT_STAGE_HELLO_RX,
  CRASH_BOOT_STAGE_HELLO_ACK
} CrashBootStage;

typedef struct {
  uint32_t magic;
  uint32_t flags;
  uint32_t bootCount;
  uint32_t faultCountTotal;
  uint32_t watchdogResetCount;
  uint32_t watchdogStickyCount;
  uint32_t resetFlagsRaw;
  CrashFaultKind lastFault;
  CrashResetCause resetCause;
  CrashTaskId lastTask;
  uint32_t uptimeMs;
  uint32_t cfsr;
  uint32_t hfsr;
  uint32_t mmfar;
  uint32_t bfar;
  uint32_t watchdogRawStatus;
  CrashBootStage bootStage;
} CrashLogSnapshot;

#define CRASHLOG_FLAG_VALID            0x00000001u
#define CRASHLOG_FLAG_PENDING          0x00000002u
#define CRASHLOG_FLAG_WDT_ARM_STICKY   0x00000004u
#define CRASHLOG_FLAG_WDT_RECOVERY_PENDING 0x00000008u

void CrashLog_EarlyBootInit(void);
void CrashLog_RecordFault(CrashFaultKind kind, CrashTaskId taskIdHint);
void CrashLog_RecordFaultFromHandler(CrashFaultKind kind, CrashTaskId taskIdHint);
void CrashLog_RecordAndHalt(CrashFaultKind kind, CrashTaskId taskIdHint);
void CrashLog_RecordAndHaltFromHandler(CrashFaultKind kind, CrashTaskId taskIdHint);
void CrashLog_RecordWatchdogSticky(uint32_t rawStatus);
void CrashLog_RequestWatchdogRecoveryReset(uint32_t rawStatus);
void CrashLog_ClearWatchdogRecoveryReset(void);
uint32_t CrashLog_IsWatchdogRecoveryBoot(void);
void CrashLog_MarkBootHealthy(void);
void CrashLog_GetSnapshot(CrashLogSnapshot* out);
void CrashLog_LogBootSummary(void);
void CrashLog_SetBootStage(CrashBootStage stage);
CrashBootStage CrashLog_GetBootStage(void);
const char* CrashLog_BootStageName(CrashBootStage stage);

#ifdef __cplusplus
}
#endif

#endif /* INC_CRASHLOG_H_ */
