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
static RegulatorTelemetryRetainedContext g_regulatorContext __attribute__((section(".noinit")));
static CrashFaultContextRetained g_faultContext __attribute__((section(".noinit")));
volatile uint32_t g_crashFaultEntryCallee[8] __attribute__((section(".noinit")));
static CrashFaultStackRange g_taskStackRanges[CRASH_HOME_AXIS_COUNT];
static volatile uint8_t g_homePhases[CRASH_HOME_AXIS_COUNT];
static volatile uint8_t g_homeCheckpoints[CRASH_HOME_AXIS_COUNT];

extern uint32_t _sdata;
extern uint32_t _estack;
extern uint32_t __flash_exec_start__;
extern uint32_t __flash_exec_end__;
extern uint32_t __ram_exec_start__;
extern uint32_t __ram_exec_end__;
extern __IO uint32_t uwTick;

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

static uint32_t CrashLog_ShouldKeepRegulatorContext(CrashResetCause resetCause)
{
  return (resetCause != CRASH_RESET_POWER) &&
         (resetCause != CRASH_RESET_LOW_POWER);
}

static void CrashLog_ClearFaultContext(void)
{
  g_faultContext.magic = 0u;
  g_faultContext.version = 0u;
  g_faultContext.size = 0u;
  g_faultContext.checksum = 0u;
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
  RegulatorTelemetry_ClearRetainedContext(&g_regulatorContext);
  CrashLog_ClearFaultContext();
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
  out->faultContextValid = (uint8_t)CrashFaultContext_ValidateRetained(
      &g_faultContext, &out->faultContext);
  RegulatorTelemetry_InitResetContext(&out->regulatorContext);
  if (CrashLog_ShouldKeepRegulatorContext(out->resetCause) != 0u) {
    (void)RegulatorTelemetry_ReadRetainedContext(&g_regulatorContext,
                                                 &out->regulatorContext);
  }
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
  if (CrashLog_ShouldKeepRegulatorContext(resetCause) == 0u) {
    RegulatorTelemetry_ClearRetainedContext(&g_regulatorContext);
    CrashLog_ClearFaultContext();
  }
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

  CrashLog_ClearFaultContext();

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

  CrashLog_ClearFaultContext();

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
  CrashLog_ClearFaultContext();
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
  CrashLog_ClearFaultContext();
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

static void CrashLog_RecordExceptionCommon(CrashFaultKind kind,
                                           uint32_t rawSp,
                                           uint32_t excReturn,
                                           uint32_t msp,
                                           uint32_t psp) __attribute__((noreturn));

static void CrashLog_RecordExceptionCommon(CrashFaultKind kind,
                                           uint32_t rawSp,
                                           uint32_t excReturn,
                                           uint32_t msp,
                                           uint32_t psp)
{
  const uint8_t faultControl = (uint8_t)__get_CONTROL();
  const uint8_t faultBasepri = (uint8_t)__get_BASEPRI();
  const uint8_t faultPrimask = (uint8_t)__get_PRIMASK();
  const uint8_t faultFaultmask = (uint8_t)__get_FAULTMASK();
  __disable_irq();

#if (LC_CRASHLOG_FAULT_HOOKS_ENABLE != 0)
  CrashLog_EnableBackupAccess();
  if (CrashLog_IsStorageValid() == 0u) {
    CrashLog_ResetStorage();
  }
#endif

  g_faultContext.magic = 0u;
  __DMB();

  CrashFaultContextV2* context = &g_faultContext.context;
  uint32_t* words = (uint32_t*)context;
  for (uint32_t i = 0u; i < (sizeof(*context) / sizeof(uint32_t)); ++i) {
    words[i] = 0u;
  }

  context->version = CRASH_FAULT_CONTEXT_VERSION;
  context->faultKind = (uint8_t)kind;
  context->activeCommand = g_activeCommand;
  context->homePhaseX = g_homePhases[CRASH_HOME_AXIS_X];
  context->homePhaseY = g_homePhases[CRASH_HOME_AXIS_Y];
  context->homePhaseZ = g_homePhases[CRASH_HOME_AXIS_Z];
  context->homePhaseP = g_homePhases[CRASH_HOME_AXIS_P];
  context->homePhaseR = g_homePhases[CRASH_HOME_AXIS_R];
  context->homeCheckpointX = g_homeCheckpoints[CRASH_HOME_AXIS_X];
  context->homeCheckpointY = g_homeCheckpoints[CRASH_HOME_AXIS_Y];
  context->homeCheckpointZ = g_homeCheckpoints[CRASH_HOME_AXIS_Z];
  context->homeCheckpointP = g_homeCheckpoints[CRASH_HOME_AXIS_P];
  context->homeCheckpointR = g_homeCheckpoints[CRASH_HOME_AXIS_R];
  context->flags |= CRASH_FAULT_CONTEXT_FLAG_CHECKPOINTS_VALID;
  context->excReturn = excReturn;
  context->activeSp = rawSp;
  context->msp = msp;
  context->psp = psp;
  context->control = faultControl;
  context->basepri = faultBasepri;
  context->primask = faultPrimask;
  context->faultmask = faultFaultmask;
  context->cfsr = SCB->CFSR;
  context->hfsr = SCB->HFSR;
  context->mmfar = SCB->MMFAR;
  context->bfar = SCB->BFAR;
  context->fpccr = FPU->FPCCR;
  context->fpcar = FPU->FPCAR;
  context->flags |= CRASH_FAULT_CONTEXT_FLAG_FP_STATUS_VALID;
  if ((excReturn & (1u << 4)) == 0u) {
    context->flags |= CRASH_FAULT_CONTEXT_FLAG_FP_EXTENDED_FRAME;
  }
  if ((excReturn & (1u << 3)) == 0u) {
    context->flags |= CRASH_FAULT_CONTEXT_FLAG_HANDLER_MODE;
  }
  if ((context->cfsr & SCB_CFSR_MMARVALID_Msk) != 0u) {
    context->flags |= CRASH_FAULT_CONTEXT_FLAG_MMFAR_VALID;
  }
  if ((context->cfsr & SCB_CFSR_BFARVALID_Msk) != 0u) {
    context->flags |= CRASH_FAULT_CONTEXT_FLAG_BFAR_VALID;
  }

  context->r4 = g_crashFaultEntryCallee[0];
  context->r5 = g_crashFaultEntryCallee[1];
  context->r6 = g_crashFaultEntryCallee[2];
  context->r7 = g_crashFaultEntryCallee[3];
  context->r8 = g_crashFaultEntryCallee[4];
  context->r9 = g_crashFaultEntryCallee[5];
  context->r10 = g_crashFaultEntryCallee[6];
  context->r11 = g_crashFaultEntryCallee[7];
  context->flags |= CRASH_FAULT_CONTEXT_FLAG_CALLEE_SAVED_VALID;

  uint32_t stackLow = 0u;
  uint32_t stackHigh = 0u;
  const uint8_t matchedTask = CrashFaultContext_MatchStack(
      rawSp, g_taskStackRanges, CRASH_HOME_AXIS_COUNT, &stackLow, &stackHigh);
  if (matchedTask != 0u) {
    context->flags |= CRASH_FAULT_CONTEXT_FLAG_TASK_STACK_MATCHED;
    context->taskId = matchedTask;
    context->taskStackLow = stackLow;
    context->taskStackHigh = stackHigh;
  } else {
    context->taskId = (uint8_t)g_activeTask;
    stackLow = (uint32_t)(uintptr_t)&_sdata;
    stackHigh = (uint32_t)(uintptr_t)&_estack;
  }

  uint32_t coreFrame = 0u;
  uint32_t frameWords = 0u;
  if (CrashFaultContext_SelectCoreFrame(rawSp, excReturn, stackLow, stackHigh,
                                        &coreFrame, &frameWords) != 0u) {
    (void)frameWords;
    const uint32_t* frame = (const uint32_t*)(uintptr_t)coreFrame;
    context->flags |= CRASH_FAULT_CONTEXT_FLAG_STACK_POINTER_VALID;
    context->r0 = frame[0];
    context->r1 = frame[1];
    context->r2 = frame[2];
    context->r3 = frame[3];
    context->r12 = frame[4];
    context->lr = frame[5];
    context->pc = frame[6];
    context->xpsr = frame[7];
    if (CrashFaultContext_IsExecutablePc(
            context->pc,
            (uint32_t)(uintptr_t)&__flash_exec_start__,
            (uint32_t)(uintptr_t)&__flash_exec_end__,
            (uint32_t)(uintptr_t)&__ram_exec_start__,
            (uint32_t)(uintptr_t)&__ram_exec_end__) != 0u) {
      context->flags |= CRASH_FAULT_CONTEXT_FLAG_PC_EXECUTABLE;
    }
    if (CrashFaultContext_HasThumbState(context->xpsr) != 0u) {
      context->flags |= CRASH_FAULT_CONTEXT_FLAG_XPSR_THUMB;
    }
    if ((context->flags & (CRASH_FAULT_CONTEXT_FLAG_PC_EXECUTABLE |
                           CRASH_FAULT_CONTEXT_FLAG_XPSR_THUMB)) ==
        (CRASH_FAULT_CONTEXT_FLAG_PC_EXECUTABLE |
         CRASH_FAULT_CONTEXT_FLAG_XPSR_THUMB)) {
      context->flags |= CRASH_FAULT_CONTEXT_FLAG_CORE_FRAME_VALID;
    }
  }

  g_faultContext.version = CRASH_FAULT_CONTEXT_VERSION;
  g_faultContext.size = (uint16_t)sizeof(g_faultContext);
  g_faultContext.checksum = CrashFaultContext_Checksum(context);
  __DMB();
  g_faultContext.magic = CRASH_FAULT_CONTEXT_RETAINED_MAGIC;
  __DSB();
  __ISB();

#if (LC_CRASHLOG_FAULT_HOOKS_ENABLE != 0)
  CrashLog_WriteFaultRecord(kind,
                            (CrashTaskId)context->taskId,
                            CRASH_TASK_NONE,
                            (uint32_t)uwTick,
                            context->cfsr,
                            context->hfsr,
                            context->mmfar,
                            context->bfar,
                            0u);
#endif
  if (Watchdog_IsArmed() != 0u) {
    for (;;) {
    }
  }
  NVIC_SystemReset();
  for (;;) {
  }
}

void CrashLog_RecordHardFaultAndHalt(uint32_t rawSp, uint32_t excReturn,
                                    uint32_t msp, uint32_t psp)
    __attribute__((section(".text.CrashLog_HardFaultEntry")));

void CrashLog_RecordHardFaultAndHalt(uint32_t rawSp, uint32_t excReturn,
                                    uint32_t msp, uint32_t psp)
{
  CrashLog_RecordExceptionCommon(CRASH_FAULT_HARD, rawSp, excReturn, msp, psp);
}

void CrashLog_RecordMemFaultAndHalt(uint32_t rawSp, uint32_t excReturn,
                                   uint32_t msp, uint32_t psp)
{
  CrashLog_RecordExceptionCommon(CRASH_FAULT_MEM, rawSp, excReturn, msp, psp);
}

void CrashLog_RecordBusFaultAndHalt(uint32_t rawSp, uint32_t excReturn,
                                   uint32_t msp, uint32_t psp)
{
  CrashLog_RecordExceptionCommon(CRASH_FAULT_BUS, rawSp, excReturn, msp, psp);
}

void CrashLog_RecordUsageFaultAndHalt(uint32_t rawSp, uint32_t excReturn,
                                     uint32_t msp, uint32_t psp)
{
  CrashLog_RecordExceptionCommon(CRASH_FAULT_USAGE, rawSp, excReturn, msp, psp);
}

void CrashLog_TriggerHardFaultForTest(void)
    __attribute__((used, noinline, section(".text.CrashLog_HardFaultEntry")));

void CrashLog_TriggerHardFaultForTest(void)
{
  __asm volatile ("udf #0");
}

void CrashLog_TriggerExtendedFrameHardFaultForTest(void)
    __attribute__((used, noinline, section(".text.CrashLog_HardFaultEntry")));

void CrashLog_TriggerExtendedFrameHardFaultForTest(void)
{
  __asm volatile (
      "vmov s0, s0\n"
      "udf #0\n");
}

void CrashLog_CaptureRegulatorContext(const RegulatorTelemetryResetContext* context)
{
#if (LC_CRASHLOG_ENABLE == 0)
  (void)context;
  return;
#endif
  if (context == NULL) {
    RegulatorTelemetry_ClearRetainedContext(&g_regulatorContext);
    return;
  }
  RegulatorTelemetry_WriteRetainedContext(&g_regulatorContext, context);
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

void CrashLog_RegisterTaskStack(CrashTaskId taskId, const void* stackBase, uint32_t stackBytes)
{
  if (stackBase == NULL || stackBytes == 0u) {
    return;
  }
  uint32_t slot = CRASH_HOME_AXIS_COUNT;
  switch (taskId) {
    case CRASH_TASK_HOME_X: slot = CRASH_HOME_AXIS_X; break;
    case CRASH_TASK_HOME_Y: slot = CRASH_HOME_AXIS_Y; break;
    case CRASH_TASK_HOME_Z: slot = CRASH_HOME_AXIS_Z; break;
    case CRASH_TASK_HOME_P: slot = CRASH_HOME_AXIS_P; break;
    case CRASH_TASK_HOME_R: slot = CRASH_HOME_AXIS_R; break;
    default: return;
  }
  const uint32_t low = (uint32_t)(uintptr_t)stackBase;
  if (low > (UINT32_MAX - stackBytes)) {
    return;
  }
  g_taskStackRanges[slot].taskId = (uint8_t)taskId;
  g_taskStackRanges[slot].low = low;
  g_taskStackRanges[slot].high = low + stackBytes;
}

void CrashLog_SetHomePhase(CrashHomeAxis axis, CrashHomePhase phase)
{
  if ((uint32_t)axis < CRASH_HOME_AXIS_COUNT) {
    g_homePhases[(uint32_t)axis] = (uint8_t)phase;
    g_homeCheckpoints[(uint32_t)axis] = (uint8_t)CRASH_HOME_CHECKPOINT_PHASE_ENTRY;
  }
}

void CrashLog_SetHomeCheckpoint(CrashHomeAxis axis, CrashHomeCheckpoint checkpoint)
{
  if ((uint32_t)axis < CRASH_HOME_AXIS_COUNT) {
    g_homeCheckpoints[(uint32_t)axis] = (uint8_t)checkpoint;
  }
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
