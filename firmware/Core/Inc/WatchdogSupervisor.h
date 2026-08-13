#ifndef INC_WATCHDOGSUPERVISOR_H_
#define INC_WATCHDOGSUPERVISOR_H_

#include <stdint.h>

#include "CrashLog.h"

#ifdef __cplusplus
extern "C" {
#endif

#ifndef LC_WATCHDOG_ENABLE
#define LC_WATCHDOG_ENABLE 1
#endif

#ifndef LC_WATCHDOG_TASK_ENABLE
#define LC_WATCHDOG_TASK_ENABLE 1
#endif

#ifndef LC_WATCHDOG_CHECKINS_ENABLE
#define LC_WATCHDOG_CHECKINS_ENABLE 1
#endif

#ifndef LC_WATCHDOG_SELFTEST_ENABLE
#define LC_WATCHDOG_SELFTEST_ENABLE 1
#endif

#ifndef LC_WATCHDOG_ARM_ENABLE
#define LC_WATCHDOG_ARM_ENABLE 1
#endif

#define WATCHDOG_ARM_IMMEDIATE 0
#define WATCHDOG_ARM_AFTER_HELLO_ACK 1
#define WATCHDOG_PRESSURE_TASK_DEADLINE_MS 500u

typedef enum {
  WATCHDOG_ARM_RESULT_NOT_ATTEMPTED = 0,
  WATCHDOG_ARM_RESULT_ARMED,
  WATCHDOG_ARM_RESULT_SKIPPED_STICKY_STATUS,
  WATCHDOG_ARM_RESULT_RECOVERY_RESET_REQUIRED,
  WATCHDOG_ARM_RESULT_TIMEOUT_LSI,
  WATCHDOG_ARM_RESULT_TIMEOUT_STATUS
} WatchdogArmResult;

#ifndef LC_WATCHDOG_ARM_MODE
#define LC_WATCHDOG_ARM_MODE WATCHDOG_ARM_AFTER_HELLO_ACK
#endif

#if (LC_WATCHDOG_ARM_MODE != WATCHDOG_ARM_IMMEDIATE) && \
    (LC_WATCHDOG_ARM_MODE != WATCHDOG_ARM_AFTER_HELLO_ACK)
#error "LC_WATCHDOG_ARM_MODE must select a supported watchdog arm mode"
#endif

void Watchdog_EarlyInit(void);
uint32_t Watchdog_ShouldRunRecoveryReset(void);
void Watchdog_StartTask(void);
void Watchdog_Arm(void);
void Watchdog_EnableTask(CrashTaskId taskId);
void Watchdog_DisableTask(CrashTaskId taskId);
void Watchdog_CheckIn(CrashTaskId taskId);
uint32_t Watchdog_IsArmed(void);
uint32_t Watchdog_IsEnabled(void);
WatchdogArmResult Watchdog_GetArmResult(void);
const char* Watchdog_ArmResultName(WatchdogArmResult result);
uint32_t Watchdog_GetRawStatus(void);
uint32_t Watchdog_GetInitTimeoutMs(void);
uint32_t Watchdog_GetStickyStatusCount(void);
uint32_t Watchdog_GetTimeoutMs(void);
uint32_t Watchdog_GetRequiredTaskCount(void);
uint32_t Watchdog_GetLiveTaskCount(void);
CrashTaskId Watchdog_GetLateTask(void);
uint32_t Watchdog_IsTaskEnabled(CrashTaskId taskId);
uint32_t Watchdog_GetTaskLastSeenAgeMs(CrashTaskId taskId, uint32_t* ageMs);

#ifdef __cplusplus
}
#endif

#endif /* INC_WATCHDOGSUPERVISOR_H_ */
