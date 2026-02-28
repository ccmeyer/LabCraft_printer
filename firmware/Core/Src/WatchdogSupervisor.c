#include "WatchdogSupervisor.h"

#include "main.h"
#include "FreeRTOS.h"
#include "task.h"

static const uint32_t kWatchdogTimeoutMs = 4000u;
static const uint32_t kWatchdogServicePeriodMs = 100u;
static const uint32_t kHealthyBootGraceMs = 10000u;
static const uint32_t kLsiHz = 32000u;
static const uint32_t kPrescalerDiv = 64u;
static const uint32_t kPrescalerReg = 4u;
static const uint32_t kReloadValue = ((kWatchdogTimeoutMs * kLsiHz) / (kPrescalerDiv * 1000u)) - 1u;
static const uint32_t kWatchdogInitTimeoutMs = 20u;

static volatile uint32_t g_watchdogArmed = 0u;
static volatile uint32_t g_enabledMask = 0u;
static volatile uint32_t g_lastSeen[CRASH_TASK_COUNT] = {0u};
static volatile CrashTaskId g_lateTask = CRASH_TASK_NONE;
static volatile uint32_t g_starved = 0u;
static volatile uint32_t g_healthyStartMs = 0u;
static volatile uint32_t g_bootMarkedHealthy = 0u;
static volatile WatchdogArmResult g_armResult = WATCHDOG_ARM_RESULT_NOT_ATTEMPTED;
static volatile uint32_t g_lastRawSr = 0u;
static volatile uint32_t g_stickyStatusCount = 0u;
static TaskHandle_t g_watchdogTaskHandle = NULL;

static uint32_t Watchdog_TaskBit(CrashTaskId taskId)
{
  if (taskId <= CRASH_TASK_NONE || taskId >= CRASH_TASK_COUNT) return 0u;
  return (1u << (uint32_t)taskId);
}

static uint32_t Watchdog_DeadlineMs(CrashTaskId taskId)
{
  switch (taskId) {
    case CRASH_TASK_BOOT: return 1000u;
    case CRASH_TASK_ORCH: return 500u;
    case CRASH_TASK_STATUS: return 500u;
    case CRASH_TASK_PRESSURE: return 250u;
    case CRASH_TASK_PREG_P: return 250u;
    case CRASH_TASK_PREG_R: return 250u;
    default: return 0u;
  }
}

static void Watchdog_Refresh(void)
{
  IWDG->KR = 0xAAAAu;
}

static uint32_t Watchdog_WaitMask(uint32_t (*read_reg)(void), uint32_t mask, uint32_t desired)
{
  const uint32_t startMs = HAL_GetTick();
  for (;;) {
    const uint32_t value = read_reg();
    if ((value & mask) == desired) {
      return 1u;
    }
    if ((HAL_GetTick() - startMs) >= kWatchdogInitTimeoutMs) {
      return 0u;
    }
  }
}

static uint32_t Watchdog_ReadRccCsr(void)
{
  return RCC->CSR;
}

static uint32_t Watchdog_ReadIwdgSr(void)
{
  return IWDG->SR;
}

static WatchdogArmResult Watchdog_ConfigureIwdg(uint32_t recordSticky)
{
  RCC->CSR |= RCC_CSR_LSION;
  if (Watchdog_WaitMask(Watchdog_ReadRccCsr, RCC_CSR_LSIRDY, RCC_CSR_LSIRDY) == 0u) {
    g_lastRawSr = RCC->CSR;
    return WATCHDOG_ARM_RESULT_TIMEOUT_LSI;
  }

  IWDG->KR = 0x5555u;
  IWDG->PR = kPrescalerReg;
  IWDG->RLR = kReloadValue;

  if (Watchdog_WaitMask(Watchdog_ReadIwdgSr, IWDG_SR_PVU | IWDG_SR_RVU, 0u) == 0u) {
    g_lastRawSr = IWDG->SR;
    if (recordSticky != 0u) {
      g_stickyStatusCount++;
      CrashLog_RecordWatchdogSticky(g_lastRawSr);
    }
    return WATCHDOG_ARM_RESULT_SKIPPED_STICKY_STATUS;
  }

  g_lastRawSr = IWDG->SR;
  return WATCHDOG_ARM_RESULT_NOT_ATTEMPTED;
}

static WatchdogArmResult Watchdog_InitIwdg(void)
{
  const WatchdogArmResult configResult = Watchdog_ConfigureIwdg(1u);
  if (configResult == WATCHDOG_ARM_RESULT_SKIPPED_STICKY_STATUS &&
      (CrashLog_IsWatchdogRecoveryBoot() != 0u)) {
    IWDG->KR = 0xCCCCu;
    Watchdog_Refresh();
    g_lastRawSr = IWDG->SR;
    return WATCHDOG_ARM_RESULT_ARMED;
  }
  if (configResult != WATCHDOG_ARM_RESULT_NOT_ATTEMPTED) {
    return configResult;
  }
  IWDG->KR = 0xCCCCu;
  Watchdog_Refresh();
  g_lastRawSr = IWDG->SR;
  return WATCHDOG_ARM_RESULT_ARMED;
}

static uint32_t Watchdog_Evaluate(uint32_t nowMs, uint32_t* requiredCount, uint32_t* liveCount, CrashTaskId* lateTask)
{
  uint32_t req = 0u;
  uint32_t live = 0u;
  CrashTaskId late = CRASH_TASK_NONE;
  const uint32_t enabledMask = g_enabledMask;

  for (uint32_t id = (uint32_t)CRASH_TASK_BOOT; id < (uint32_t)CRASH_TASK_COUNT; ++id) {
    const uint32_t bit = Watchdog_TaskBit((CrashTaskId)id);
    if ((enabledMask & bit) == 0u) continue;
    req++;
    const uint32_t deadline = Watchdog_DeadlineMs((CrashTaskId)id);
    const uint32_t lastSeen = g_lastSeen[id];
    if ((lastSeen != 0u) && ((nowMs - lastSeen) <= deadline)) {
      live++;
      continue;
    }
    if (late == CRASH_TASK_NONE) {
      late = (CrashTaskId)id;
    }
  }

  if (requiredCount) *requiredCount = req;
  if (liveCount) *liveCount = live;
  if (lateTask) *lateTask = late;
  return (req == live) ? 1u : 0u;
}

static void Watchdog_Task(void* argument)
{
  (void)argument;
  for (;;) {
    vTaskDelay(pdMS_TO_TICKS(kWatchdogServicePeriodMs));

#if (LC_WATCHDOG_ENABLE == 0)
    continue;
#endif

    if (g_watchdogArmed == 0u) {
      g_lateTask = CRASH_TASK_NONE;
      g_healthyStartMs = 0u;
      continue;
    }

    if (g_starved != 0u) {
      continue;
    }

    const uint32_t nowMs = HAL_GetTick();
    uint32_t req = 0u;
    uint32_t live = 0u;
    CrashTaskId late = CRASH_TASK_NONE;
    const uint32_t healthy = Watchdog_Evaluate(nowMs, &req, &live, &late);

    if (healthy != 0u) {
      Watchdog_Refresh();
      g_lateTask = CRASH_TASK_NONE;
      if (req > 0u) {
        if (g_healthyStartMs == 0u) {
          g_healthyStartMs = nowMs;
        } else if ((g_bootMarkedHealthy == 0u) && ((nowMs - g_healthyStartMs) >= kHealthyBootGraceMs)) {
          CrashLog_MarkBootHealthy();
          g_bootMarkedHealthy = 1u;
        }
      }
      continue;
    }

    g_lateTask = late;
    g_starved = 1u;
    g_healthyStartMs = 0u;
    CrashLog_RecordWatchdogFault(late);
  }
}

void Watchdog_EarlyInit(void)
{
  g_enabledMask = 0u;
  g_lateTask = CRASH_TASK_NONE;
  g_starved = 0u;
  g_healthyStartMs = 0u;
  g_bootMarkedHealthy = 0u;
  g_armResult = WATCHDOG_ARM_RESULT_NOT_ATTEMPTED;
  g_lastRawSr = 0u;
  g_stickyStatusCount = 0u;
  for (uint32_t i = 0u; i < (uint32_t)CRASH_TASK_COUNT; ++i) {
    g_lastSeen[i] = 0u;
  }
  g_watchdogArmed = 0u;
}

uint32_t Watchdog_ShouldRunRecoveryReset(void)
{
#if (LC_WATCHDOG_ENABLE == 0) || (LC_WATCHDOG_ARM_ENABLE == 0)
  return 0u;
#endif
  if (CrashLog_IsWatchdogRecoveryBoot() != 0u) {
    return 0u;
  }
  const WatchdogArmResult result = Watchdog_ConfigureIwdg(1u);
  if (result != WATCHDOG_ARM_RESULT_SKIPPED_STICKY_STATUS) {
    return 0u;
  }
  CrashLog_RequestWatchdogRecoveryReset(g_lastRawSr);
  g_armResult = WATCHDOG_ARM_RESULT_RECOVERY_RESET_REQUIRED;
  return 1u;
}

void Watchdog_StartTask(void)
{
#if (LC_WATCHDOG_TASK_ENABLE == 0)
  return;
#endif
  if (g_watchdogTaskHandle != NULL) {
    return;
  }
  (void)xTaskCreate(Watchdog_Task, "Wdog", 384, NULL, tskIDLE_PRIORITY + 2, &g_watchdogTaskHandle);
#if (LC_WATCHDOG_ENABLE != 0) && (LC_WATCHDOG_ARM_ENABLE != 0) && (LC_WATCHDOG_ARM_MODE == WATCHDOG_ARM_IMMEDIATE)
  Watchdog_Arm();
#endif
}

void Watchdog_Arm(void)
{
#if (LC_WATCHDOG_ENABLE == 0) || (LC_WATCHDOG_TASK_ENABLE == 0) || (LC_WATCHDOG_ARM_ENABLE == 0)
  return;
#endif
  if (g_watchdogArmed != 0u) {
    return;
  }
  g_armResult = Watchdog_InitIwdg();
  if (g_armResult != WATCHDOG_ARM_RESULT_ARMED) {
    if (CrashLog_IsWatchdogRecoveryBoot() != 0u) {
      CrashLog_ClearWatchdogRecoveryReset();
    }
    g_watchdogArmed = 0u;
    g_lateTask = CRASH_TASK_NONE;
    g_healthyStartMs = 0u;
    return;
  }
  const uint32_t nowMs = HAL_GetTick();
  for (uint32_t id = (uint32_t)CRASH_TASK_BOOT; id < (uint32_t)CRASH_TASK_COUNT; ++id) {
    if ((g_enabledMask & Watchdog_TaskBit((CrashTaskId)id)) != 0u) {
      g_lastSeen[id] = nowMs;
    }
  }
  CrashLog_ClearWatchdogRecoveryReset();
  g_watchdogArmed = 1u;
  g_starved = 0u;
  g_lateTask = CRASH_TASK_NONE;
  g_healthyStartMs = 0u;
}

void Watchdog_EnableTask(CrashTaskId taskId)
{
#if (LC_WATCHDOG_CHECKINS_ENABLE == 0)
  (void)taskId;
  return;
#endif
  const uint32_t bit = Watchdog_TaskBit(taskId);
  if (bit == 0u) return;
  g_enabledMask |= bit;
  g_lastSeen[(uint32_t)taskId] = HAL_GetTick();
}

void Watchdog_DisableTask(CrashTaskId taskId)
{
#if (LC_WATCHDOG_CHECKINS_ENABLE == 0)
  (void)taskId;
  return;
#endif
  const uint32_t bit = Watchdog_TaskBit(taskId);
  if (bit == 0u) return;
  g_enabledMask &= ~bit;
  g_lastSeen[(uint32_t)taskId] = 0u;
  if (g_lateTask == taskId) {
    g_lateTask = CRASH_TASK_NONE;
  }
}

void Watchdog_CheckIn(CrashTaskId taskId)
{
#if (LC_WATCHDOG_CHECKINS_ENABLE == 0)
  (void)taskId;
  return;
#endif
  const uint32_t bit = Watchdog_TaskBit(taskId);
  if (bit == 0u) return;
  g_enabledMask |= bit;
  g_lastSeen[(uint32_t)taskId] = HAL_GetTick();
}

uint32_t Watchdog_IsArmed(void)
{
#if (LC_WATCHDOG_ENABLE == 0)
  return 0u;
#endif
  return g_watchdogArmed;
}

uint32_t Watchdog_IsEnabled(void)
{
#if (LC_WATCHDOG_ENABLE == 0) || (LC_WATCHDOG_SELFTEST_ENABLE == 0)
  return 0u;
#endif
  return Watchdog_IsArmed();
}

WatchdogArmResult Watchdog_GetArmResult(void)
{
#if (LC_WATCHDOG_ENABLE == 0) || (LC_WATCHDOG_SELFTEST_ENABLE == 0)
  return WATCHDOG_ARM_RESULT_NOT_ATTEMPTED;
#endif
  return g_armResult;
}

const char* Watchdog_ArmResultName(WatchdogArmResult result)
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

uint32_t Watchdog_GetRawStatus(void)
{
#if (LC_WATCHDOG_ENABLE == 0) || (LC_WATCHDOG_SELFTEST_ENABLE == 0)
  return 0u;
#endif
  return g_lastRawSr;
}

uint32_t Watchdog_GetInitTimeoutMs(void)
{
  return kWatchdogInitTimeoutMs;
}

uint32_t Watchdog_GetStickyStatusCount(void)
{
#if (LC_WATCHDOG_ENABLE == 0) || (LC_WATCHDOG_SELFTEST_ENABLE == 0)
  return 0u;
#endif
  return g_stickyStatusCount;
}

uint32_t Watchdog_GetTimeoutMs(void)
{
  return kWatchdogTimeoutMs;
}

uint32_t Watchdog_GetRequiredTaskCount(void)
{
#if (LC_WATCHDOG_SELFTEST_ENABLE == 0)
  return 0u;
#endif
  if (g_watchdogArmed == 0u) {
    return 0u;
  }
  uint32_t req = 0u;
  (void)Watchdog_Evaluate(HAL_GetTick(), &req, NULL, NULL);
  return req;
}

uint32_t Watchdog_GetLiveTaskCount(void)
{
#if (LC_WATCHDOG_SELFTEST_ENABLE == 0)
  return 0u;
#endif
  if (g_watchdogArmed == 0u) {
    return 0u;
  }
  uint32_t live = 0u;
  (void)Watchdog_Evaluate(HAL_GetTick(), NULL, &live, NULL);
  return live;
}

CrashTaskId Watchdog_GetLateTask(void)
{
#if (LC_WATCHDOG_SELFTEST_ENABLE == 0)
  return CRASH_TASK_NONE;
#endif
  if (g_watchdogArmed == 0u) {
    return CRASH_TASK_NONE;
  }
  if (g_starved != 0u) {
    return g_lateTask;
  }
  CrashTaskId late = CRASH_TASK_NONE;
  (void)Watchdog_Evaluate(HAL_GetTick(), NULL, NULL, &late);
  return late;
}
