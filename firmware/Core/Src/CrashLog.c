#include "CrashLog.h"

#include "CrashLogCodec.h"
#include "WatchdogSupervisor.h"
#include "BoardConfig.h"
#include "FreeRTOS.h"
#include "task.h"
#include "main.h"

#include <stdio.h>
#include <string.h>

extern void MX_LOGGER_Log_entry(const char* fmt);

static volatile CrashBootStage g_bootStage = CRASH_BOOT_STAGE_RESET;
static volatile uint32_t g_bootSummaryLogged = 0u;
static volatile uint32_t g_watchdogRecoveryBoot = 0u;
static volatile CrashTaskId g_activeTask = CRASH_TASK_NONE;
static volatile uint8_t g_activeCommand = 0u;

static const uint32_t kCrashLogMagic = 0x43524153u;
static const uint32_t kCrashLogVersion = 3u;
static const uint32_t kCrashLogVersionShift = 16u;
static const uint32_t kCrashLogRegCount = 20u;

enum {
  CRASHLOG_BKP_MAGIC = 0,
  CRASHLOG_BKP_FLAGS = 1,
  CRASHLOG_BKP_BOOT_COUNT = 2,
  CRASHLOG_BKP_FAULT_COUNT = 3,
  CRASHLOG_BKP_WATCHDOG_COUNT = 4,
  CRASHLOG_BKP_RESET_FLAGS = 5,
  CRASHLOG_BKP_LAST_FAULT = 6,
  CRASHLOG_BKP_RESET_CAUSE = 7,
  CRASHLOG_BKP_LAST_TASK = 8,
  CRASHLOG_BKP_UPTIME_MS = 9,
  CRASHLOG_BKP_CFSR = 10,
  CRASHLOG_BKP_HFSR = 11,
  CRASHLOG_BKP_MMFAR = 12,
  CRASHLOG_BKP_BFAR = 13,
  CRASHLOG_BKP_WATCHDOG_STICKY_COUNT = 14,
  CRASHLOG_BKP_WATCHDOG_RAW_STATUS = 15,
  CRASHLOG_BKP_FAULT_STAGE = 16,
  CRASHLOG_BKP_WATCHDOG_LATE_TASK = 17,
  CRASHLOG_BKP_ACTIVE_COMMAND = 18,
  CRASHLOG_BKP_FAULT_TASK_NAME4 = 19
};

static void CrashLog_EnableBackupAccess(void)
{
#if (LC_CRASHLOG_ENABLE == 0)
  return;
#endif
  RCC->APB1ENR |= RCC_APB1ENR_PWREN;
  (void)RCC->APB1ENR;
  PWR->CR |= PWR_CR_DBP;
  while ((PWR->CR & PWR_CR_DBP) == 0u) {
  }

  RCC->CSR |= RCC_CSR_LSION;
  while ((RCC->CSR & RCC_CSR_LSIRDY) == 0u) {
  }

  if ((RCC->BDCR & RCC_BDCR_RTCSEL) == 0u) {
    RCC->BDCR = (RCC->BDCR & ~RCC_BDCR_RTCSEL) | RCC_BDCR_RTCSEL_1;
  }
  RCC->BDCR |= RCC_BDCR_RTCEN;
}

static volatile uint32_t* CrashLog_BkpReg(uint32_t index)
{
  return ((volatile uint32_t*)&RTC->BKP0R) + index;
}

static uint32_t CrashLog_Read(uint32_t index)
{
  return *CrashLog_BkpReg(index);
}

static void CrashLog_Write(uint32_t index, uint32_t value)
{
  *CrashLog_BkpReg(index) = value;
}

static uint32_t CrashLog_FlagsWithVersion(uint32_t flags)
{
  return (kCrashLogVersion << kCrashLogVersionShift) | flags;
}

static uint32_t CrashLog_FlagsOnly(uint32_t flagsReg)
{
  return (flagsReg & 0xFFFFu);
}

static void CrashLog_ResetStorage(void)
{
  for (uint32_t i = 0u; i < kCrashLogRegCount; ++i) {
    CrashLog_Write(i, 0u);
  }
  CrashLog_Write(CRASHLOG_BKP_MAGIC, kCrashLogMagic);
  CrashLog_Write(CRASHLOG_BKP_FLAGS, CrashLog_FlagsWithVersion(CRASHLOG_FLAG_VALID));
  CrashLog_Write(CRASHLOG_BKP_LAST_FAULT, (uint32_t)CRASH_FAULT_NONE);
  CrashLog_Write(CRASHLOG_BKP_RESET_CAUSE, (uint32_t)CRASH_RESET_UNKNOWN);
  CrashLog_Write(CRASHLOG_BKP_LAST_TASK, (uint32_t)CRASH_TASK_NONE);
  CrashLog_Write(CRASHLOG_BKP_FAULT_STAGE, (uint32_t)CRASH_BOOT_STAGE_RESET);
  CrashLog_Write(CRASHLOG_BKP_WATCHDOG_LATE_TASK, (uint32_t)CRASH_TASK_NONE);
  CrashLog_Write(CRASHLOG_BKP_ACTIVE_COMMAND, 0u);
}

static uint32_t CrashLog_IsStorageValid(void)
{
  if (CrashLog_Read(CRASHLOG_BKP_MAGIC) != kCrashLogMagic) return 0u;
  const uint32_t flagsReg = CrashLog_Read(CRASHLOG_BKP_FLAGS);
  const uint32_t version = flagsReg >> kCrashLogVersionShift;
  const uint32_t flags = CrashLog_FlagsOnly(flagsReg);
  return (version == kCrashLogVersion) && ((flags & CRASHLOG_FLAG_VALID) != 0u);
}

static CrashTaskId CrashLog_CurrentTaskId(void)
{
  if (xTaskGetSchedulerState() == taskSCHEDULER_NOT_STARTED) {
    return CRASH_TASK_BOOT;
  }
  TaskHandle_t current = xTaskGetCurrentTaskHandle();
  if (current == NULL) {
    return CRASH_TASK_NONE;
  }
  return CrashLog_TaskIdFromTaskName(pcTaskGetName(current));
}

static void CrashLog_FillSnapshot(CrashLogSnapshot* out)
{
  memset(out, 0, sizeof(*out));
  out->magic = CrashLog_Read(CRASHLOG_BKP_MAGIC);
  out->flags = CrashLog_FlagsOnly(CrashLog_Read(CRASHLOG_BKP_FLAGS));
  out->bootCount = CrashLog_Read(CRASHLOG_BKP_BOOT_COUNT);
  out->faultCountTotal = CrashLog_Read(CRASHLOG_BKP_FAULT_COUNT);
  out->watchdogResetCount = CrashLog_Read(CRASHLOG_BKP_WATCHDOG_COUNT);
  out->watchdogStickyCount = CrashLog_Read(CRASHLOG_BKP_WATCHDOG_STICKY_COUNT);
  out->resetFlagsRaw = CrashLog_Read(CRASHLOG_BKP_RESET_FLAGS);
  out->lastFault = (CrashFaultKind)CrashLog_Read(CRASHLOG_BKP_LAST_FAULT);
  out->resetCause = (CrashResetCause)CrashLog_Read(CRASHLOG_BKP_RESET_CAUSE);
  out->lastTask = (CrashTaskId)CrashLog_Read(CRASHLOG_BKP_LAST_TASK);
  out->uptimeMs = CrashLog_Read(CRASHLOG_BKP_UPTIME_MS);
  out->cfsr = CrashLog_Read(CRASHLOG_BKP_CFSR);
  out->hfsr = CrashLog_Read(CRASHLOG_BKP_HFSR);
  out->mmfar = CrashLog_Read(CRASHLOG_BKP_MMFAR);
  out->bfar = CrashLog_Read(CRASHLOG_BKP_BFAR);
  out->watchdogRawStatus = CrashLog_Read(CRASHLOG_BKP_WATCHDOG_RAW_STATUS);
  out->bootStage = g_bootStage;
  out->faultStage = (CrashBootStage)CrashLog_Read(CRASHLOG_BKP_FAULT_STAGE);
  out->watchdogLateTask = (CrashTaskId)CrashLog_Read(CRASHLOG_BKP_WATCHDOG_LATE_TASK);
  out->activeCommand = (uint8_t)CrashLog_Read(CRASHLOG_BKP_ACTIVE_COMMAND);
  out->faultTaskName4 = CrashLog_Read(CRASHLOG_BKP_FAULT_TASK_NAME4);
}

static void CrashLog_WriteFaultRecord(CrashFaultKind kind,
                                      CrashTaskId taskId,
                                      CrashTaskId watchdogLateTask,
                                      uint32_t uptimeMs,
                                      uint32_t cfsr,
                                      uint32_t hfsr,
                                      uint32_t mmfar,
                                      uint32_t bfar,
                                      uint32_t taskName4)
{
  const uint32_t flags = CrashLog_FlagsOnly(CrashLog_Read(CRASHLOG_BKP_FLAGS));
  CrashLog_Write(CRASHLOG_BKP_FLAGS, CrashLog_FlagsWithVersion(flags | CRASHLOG_FLAG_PENDING | CRASHLOG_FLAG_VALID));
  CrashLog_Write(CRASHLOG_BKP_FAULT_COUNT, CrashLog_Read(CRASHLOG_BKP_FAULT_COUNT) + 1u);
  CrashLog_Write(CRASHLOG_BKP_LAST_FAULT, (uint32_t)kind);
  CrashLog_Write(CRASHLOG_BKP_LAST_TASK, (uint32_t)taskId);
  CrashLog_Write(CRASHLOG_BKP_UPTIME_MS, uptimeMs);
  CrashLog_Write(CRASHLOG_BKP_CFSR, cfsr);
  CrashLog_Write(CRASHLOG_BKP_HFSR, hfsr);
  CrashLog_Write(CRASHLOG_BKP_MMFAR, mmfar);
  CrashLog_Write(CRASHLOG_BKP_BFAR, bfar);
  CrashLog_Write(CRASHLOG_BKP_FAULT_STAGE, (uint32_t)g_bootStage);
  CrashLog_Write(CRASHLOG_BKP_WATCHDOG_LATE_TASK, (uint32_t)watchdogLateTask);
  CrashLog_Write(CRASHLOG_BKP_ACTIVE_COMMAND, (uint32_t)g_activeCommand);
  CrashLog_Write(CRASHLOG_BKP_FAULT_TASK_NAME4, taskName4);
  __DSB();
  __ISB();
}

void CrashLog_EarlyBootInit(void)
{
#if (LC_CRASHLOG_ENABLE == 0) || (LC_CRASHLOG_EARLY_BOOT_ENABLE == 0)
  return;
#endif
  CrashLog_EnableBackupAccess();
  if (CrashLog_IsStorageValid() == 0u) {
    CrashLog_ResetStorage();
  }

  const uint32_t resetFlags = RCC->CSR;
  const CrashResetCause resetCause = CrashLog_ClassifyResetFlags(resetFlags);
  const uint32_t flags = CrashLog_FlagsOnly(CrashLog_Read(CRASHLOG_BKP_FLAGS));
  const uint32_t bootCount = CrashLog_Read(CRASHLOG_BKP_BOOT_COUNT) + 1u;
  CrashLog_Write(CRASHLOG_BKP_BOOT_COUNT, bootCount);
  CrashLog_Write(CRASHLOG_BKP_RESET_FLAGS, resetFlags);
  CrashLog_Write(CRASHLOG_BKP_RESET_CAUSE, (uint32_t)resetCause);
  g_watchdogRecoveryBoot = (((flags & CRASHLOG_FLAG_WDT_RECOVERY_PENDING) != 0u) &&
      (resetCause == CRASH_RESET_SOFTWARE)) ? 1u : 0u;
  if (resetCause == CRASH_RESET_IWDG) {
    CrashLog_Write(CRASHLOG_BKP_WATCHDOG_COUNT, CrashLog_Read(CRASHLOG_BKP_WATCHDOG_COUNT) + 1u);
  }
  RCC->CSR |= RCC_CSR_RMVF;
  g_bootStage = CRASH_BOOT_STAGE_CRASHLOG_READY;
}

void CrashLog_RecordFault(CrashFaultKind kind, CrashTaskId taskIdHint)
{
#if (LC_CRASHLOG_ENABLE == 0)
  (void)kind;
  (void)taskIdHint;
  return;
#endif
  CrashLog_EnableBackupAccess();
  if (CrashLog_IsStorageValid() == 0u) {
    CrashLog_ResetStorage();
  }

  CrashTaskId taskId = taskIdHint;
  if (taskId == CRASH_TASK_NONE) {
    taskId = g_activeTask;
    if (taskId == CRASH_TASK_NONE) {
      taskId = CrashLog_CurrentTaskId();
#if (LC_PRESSURE_PORTS > 1)
      if (taskId == CRASH_TASK_PREG_P) {
        taskId = CRASH_TASK_NONE;
      }
#endif
    }
  }

  CrashLog_WriteFaultRecord(kind,
                            taskId,
                            CRASH_TASK_NONE,
                            HAL_GetTick(),
                            SCB->CFSR,
                            SCB->HFSR,
                            SCB->MMFAR,
                            SCB->BFAR,
                            0u);
}

void CrashLog_RecordWatchdogFault(CrashTaskId lateTask)
{
#if (LC_CRASHLOG_ENABLE == 0)
  (void)lateTask;
  return;
#endif
  CrashLog_EnableBackupAccess();
  if (CrashLog_IsStorageValid() == 0u) {
    CrashLog_ResetStorage();
  }

  CrashTaskId taskId = g_activeTask;
  if (taskId == CRASH_TASK_NONE) {
    taskId = lateTask;
  }

  CrashLog_WriteFaultRecord(CRASH_FAULT_WDT_STARVE,
                            taskId,
                            lateTask,
                            HAL_GetTick(),
                            SCB->CFSR,
                            SCB->HFSR,
                            SCB->MMFAR,
                            SCB->BFAR,
                            0u);
}

void CrashLog_RecordFaultFromHandler(CrashFaultKind kind, CrashTaskId taskIdHint)
{
#if (LC_CRASHLOG_ENABLE == 0) || (LC_CRASHLOG_FAULT_HOOKS_ENABLE == 0)
  (void)kind;
  (void)taskIdHint;
  return;
#endif
  CrashLog_EnableBackupAccess();
  if (CrashLog_IsStorageValid() == 0u) {
    CrashLog_ResetStorage();
  }
  CrashLog_WriteFaultRecord(kind,
                            taskIdHint,
                            CRASH_TASK_NONE,
                            HAL_GetTick(),
                            SCB->CFSR,
                            SCB->HFSR,
                            SCB->MMFAR,
                            SCB->BFAR,
                            0u);
}

void CrashLog_RecordStackOverflowFromHook(CrashTaskId taskIdHint, const char* taskName)
{
#if (LC_CRASHLOG_ENABLE == 0) || (LC_CRASHLOG_FAULT_HOOKS_ENABLE == 0)
  (void)taskIdHint;
  (void)taskName;
  return;
#endif
  CrashLog_EnableBackupAccess();
  if (CrashLog_IsStorageValid() == 0u) {
    CrashLog_ResetStorage();
  }
  const CrashTaskId taskId = CrashLog_SelectStackOverflowTaskId(taskIdHint, g_activeTask);
  CrashLog_WriteFaultRecord(CRASH_FAULT_STACK_OVF,
                            taskId,
                            CRASH_TASK_NONE,
                            HAL_GetTick(),
                            SCB->CFSR,
                            SCB->HFSR,
                            SCB->MMFAR,
                            SCB->BFAR,
                            CrashLog_PackTaskName4(taskName));
}

void CrashLog_RecordAndHalt(CrashFaultKind kind, CrashTaskId taskIdHint)
{
  CrashLog_RecordFault(kind, taskIdHint);
  __disable_irq();
  if (Watchdog_IsArmed() != 0u) {
    for (;;) {
    }
  }
  NVIC_SystemReset();
  for (;;) {
  }
}

void CrashLog_RecordAndHaltFromHandler(CrashFaultKind kind, CrashTaskId taskIdHint)
{
#if (LC_CRASHLOG_FAULT_HOOKS_ENABLE != 0)
  CrashLog_RecordFaultFromHandler(kind, taskIdHint);
#else
  (void)kind;
  (void)taskIdHint;
#endif
  __disable_irq();
  if (Watchdog_IsArmed() != 0u) {
    for (;;) {
    }
  }
  NVIC_SystemReset();
  for (;;) {
  }
}

void CrashLog_RecordWatchdogSticky(uint32_t rawStatus)
{
#if (LC_CRASHLOG_ENABLE == 0)
  (void)rawStatus;
  return;
#endif
  CrashLog_EnableBackupAccess();
  if (CrashLog_IsStorageValid() == 0u) {
    CrashLog_ResetStorage();
  }
  const uint32_t flags = CrashLog_FlagsOnly(CrashLog_Read(CRASHLOG_BKP_FLAGS));
  CrashLog_Write(CRASHLOG_BKP_FLAGS, CrashLog_FlagsWithVersion(flags | CRASHLOG_FLAG_VALID | CRASHLOG_FLAG_WDT_ARM_STICKY));
  CrashLog_Write(CRASHLOG_BKP_WATCHDOG_STICKY_COUNT, CrashLog_Read(CRASHLOG_BKP_WATCHDOG_STICKY_COUNT) + 1u);
  CrashLog_Write(CRASHLOG_BKP_WATCHDOG_RAW_STATUS, rawStatus);
}

void CrashLog_RequestWatchdogRecoveryReset(uint32_t rawStatus)
{
#if (LC_CRASHLOG_ENABLE == 0)
  (void)rawStatus;
  return;
#endif
  CrashLog_EnableBackupAccess();
  if (CrashLog_IsStorageValid() == 0u) {
    CrashLog_ResetStorage();
  }
  const uint32_t flags = CrashLog_FlagsOnly(CrashLog_Read(CRASHLOG_BKP_FLAGS));
  CrashLog_Write(CRASHLOG_BKP_FLAGS, CrashLog_FlagsWithVersion(flags |
      CRASHLOG_FLAG_VALID |
      CRASHLOG_FLAG_WDT_ARM_STICKY |
      CRASHLOG_FLAG_WDT_RECOVERY_PENDING));
  CrashLog_Write(CRASHLOG_BKP_WATCHDOG_RAW_STATUS, rawStatus);
}

void CrashLog_ClearWatchdogRecoveryReset(void)
{
#if (LC_CRASHLOG_ENABLE == 0)
  return;
#endif
  CrashLog_EnableBackupAccess();
  if (CrashLog_IsStorageValid() == 0u) {
    CrashLog_ResetStorage();
  }
  const uint32_t flags = CrashLog_FlagsOnly(CrashLog_Read(CRASHLOG_BKP_FLAGS));
  CrashLog_Write(CRASHLOG_BKP_FLAGS, CrashLog_FlagsWithVersion((flags & ~CRASHLOG_FLAG_WDT_RECOVERY_PENDING) | CRASHLOG_FLAG_VALID));
}

uint32_t CrashLog_IsWatchdogRecoveryBoot(void)
{
  return g_watchdogRecoveryBoot;
}

void CrashLog_MarkBootHealthy(void)
{
#if (LC_CRASHLOG_ENABLE == 0)
  return;
#endif
  const uint32_t flags = CrashLog_FlagsOnly(CrashLog_Read(CRASHLOG_BKP_FLAGS));
  CrashLog_Write(CRASHLOG_BKP_FLAGS, CrashLog_FlagsWithVersion((flags & ~CRASHLOG_FLAG_PENDING) | CRASHLOG_FLAG_VALID));
  CrashLog_Write(CRASHLOG_BKP_LAST_FAULT, (uint32_t)CRASH_FAULT_NONE);
  CrashLog_Write(CRASHLOG_BKP_LAST_TASK, (uint32_t)CRASH_TASK_NONE);
  CrashLog_Write(CRASHLOG_BKP_CFSR, 0u);
  CrashLog_Write(CRASHLOG_BKP_HFSR, 0u);
  CrashLog_Write(CRASHLOG_BKP_MMFAR, 0u);
  CrashLog_Write(CRASHLOG_BKP_BFAR, 0u);
  CrashLog_Write(CRASHLOG_BKP_WATCHDOG_RAW_STATUS, 0u);
  CrashLog_Write(CRASHLOG_BKP_FAULT_STAGE, (uint32_t)CRASH_BOOT_STAGE_RESET);
  CrashLog_Write(CRASHLOG_BKP_WATCHDOG_LATE_TASK, (uint32_t)CRASH_TASK_NONE);
  CrashLog_Write(CRASHLOG_BKP_ACTIVE_COMMAND, 0u);
  CrashLog_Write(CRASHLOG_BKP_FAULT_TASK_NAME4, 0u);
}

void CrashLog_GetSnapshot(CrashLogSnapshot* out)
{
  if (out == NULL) return;
#if (LC_CRASHLOG_ENABLE == 0)
  memset(out, 0, sizeof(*out));
  out->bootStage = g_bootStage;
  return;
#endif
  CrashLog_EnableBackupAccess();
  if (CrashLog_IsStorageValid() == 0u) {
    CrashLog_ResetStorage();
  }
  CrashLog_FillSnapshot(out);
}

void CrashLog_LogBootSummary(void)
{
#if (LC_CRASHLOG_ENABLE == 0) || (LC_CRASHLOG_BOOT_SUMMARY_ENABLE == 0)
  return;
#endif
  if (g_bootSummaryLogged != 0u) {
    return;
  }
  CrashLogSnapshot snap;
  CrashLog_GetSnapshot(&snap);
  static char line[256];
  snprintf(line,
           sizeof(line),
           "[BOOT] stage=%s reset=%s pending=%lu sticky=%lu fault=%s task=%s late=%s cmd=0x%02lx fault_stage=%s boot=%lu sticky_ct=%lu raw_sr=%lu cfsr=%lu hfsr=%lu mmfar=%lu bfar=%lu\r\n",
           CrashLog_BootStageName(snap.bootStage),
           CrashLog_ResetCauseName(snap.resetCause),
           (unsigned long)((snap.flags & CRASHLOG_FLAG_PENDING) ? 1u : 0u),
           (unsigned long)((snap.flags & CRASHLOG_FLAG_WDT_ARM_STICKY) ? 1u : 0u),
           CrashLog_FaultKindName(snap.lastFault),
           CrashLog_TaskIdName(snap.lastTask),
           CrashLog_TaskIdName(snap.watchdogLateTask),
           (unsigned long)snap.activeCommand,
           CrashLog_BootStageName(snap.faultStage),
           (unsigned long)snap.bootCount,
           (unsigned long)snap.watchdogStickyCount,
           (unsigned long)snap.watchdogRawStatus,
           (unsigned long)snap.cfsr,
           (unsigned long)snap.hfsr,
           (unsigned long)snap.mmfar,
           (unsigned long)snap.bfar);
  MX_LOGGER_Log_entry(line);
  g_bootSummaryLogged = 1u;
}

void CrashLog_SetBootStage(CrashBootStage stage)
{
#if (LC_CRASHLOG_BOOT_BREADCRUMBS_ENABLE == 0)
  (void)stage;
  return;
#endif
  g_bootStage = stage;
}

CrashBootStage CrashLog_GetBootStage(void)
{
  return g_bootStage;
}

void CrashLog_SetActiveContext(CrashTaskId taskId, uint8_t activeCommand)
{
  g_activeTask = taskId;
  g_activeCommand = activeCommand;
}

void CrashLog_ClearActiveContext(void)
{
  g_activeTask = CRASH_TASK_NONE;
  g_activeCommand = 0u;
}

const char* CrashLog_BootStageName(CrashBootStage stage)
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
