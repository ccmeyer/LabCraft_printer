#include "CrashLogCodec.h"

#include <string.h>

CrashResetCause CrashLog_ClassifyResetFlags(uint32_t resetFlagsRaw)
{
  if ((resetFlagsRaw & CRASHLOG_RCC_CSR_IWDGRSTF) != 0u) return CRASH_RESET_IWDG;
  if ((resetFlagsRaw & CRASHLOG_RCC_CSR_WWDGRSTF) != 0u) return CRASH_RESET_WWDG;
  if ((resetFlagsRaw & CRASHLOG_RCC_CSR_SFTRSTF) != 0u) return CRASH_RESET_SOFTWARE;
  if ((resetFlagsRaw & CRASHLOG_RCC_CSR_LPWRRSTF) != 0u) return CRASH_RESET_LOW_POWER;
  if ((resetFlagsRaw & CRASHLOG_RCC_CSR_PINRSTF) != 0u) return CRASH_RESET_PIN;
  if ((resetFlagsRaw & (CRASHLOG_RCC_CSR_PORRSTF | CRASHLOG_RCC_CSR_BORRSTF)) != 0u) return CRASH_RESET_POWER;
  return CRASH_RESET_UNKNOWN;
}

const char* CrashLog_FaultKindName(CrashFaultKind kind)
{
  switch (kind) {
    case CRASH_FAULT_NONE: return "none";
    case CRASH_FAULT_HARD: return "hard";
    case CRASH_FAULT_MEM: return "mem";
    case CRASH_FAULT_BUS: return "bus";
    case CRASH_FAULT_USAGE: return "usage";
    case CRASH_FAULT_NMI: return "nmi";
    case CRASH_FAULT_STACK_OVF: return "stkovf";
    case CRASH_FAULT_ASSERT: return "assert";
    case CRASH_FAULT_ERROR: return "error";
    case CRASH_FAULT_WDT_STARVE: return "wdt";
    default: return "unk";
  }
}

const char* CrashLog_ResetCauseName(CrashResetCause cause)
{
  switch (cause) {
    case CRASH_RESET_POWER: return "power";
    case CRASH_RESET_PIN: return "pin";
    case CRASH_RESET_SOFTWARE: return "soft";
    case CRASH_RESET_IWDG: return "iwdg";
    case CRASH_RESET_WWDG: return "wwdg";
    case CRASH_RESET_LOW_POWER: return "lpwr";
    case CRASH_RESET_UNKNOWN:
    default: return "unk";
  }
}

const char* CrashLog_TaskIdName(CrashTaskId taskId)
{
  switch (taskId) {
    case CRASH_TASK_NONE: return "none";
    case CRASH_TASK_BOOT: return "boot";
    case CRASH_TASK_ORCH: return "orch";
    case CRASH_TASK_STATUS: return "status";
    case CRASH_TASK_PRESSURE: return "press";
    case CRASH_TASK_PREG_P: return "pregp";
    case CRASH_TASK_PREG_R: return "pregr";
    case CRASH_TASK_HOME_X: return "homex";
    case CRASH_TASK_HOME_Y: return "homey";
    case CRASH_TASK_HOME_Z: return "homez";
    case CRASH_TASK_HOME_P: return "homep";
    case CRASH_TASK_HOME_R: return "homer";
    default: return "none";
  }
}

CrashTaskId CrashLog_TaskIdFromTaskName(const char* taskName)
{
  if (taskName == NULL || taskName[0] == '\0') return CRASH_TASK_NONE;
  if (strcmp(taskName, "Orch") == 0) return CRASH_TASK_ORCH;
  if (strcmp(taskName, "Status") == 0) return CRASH_TASK_STATUS;
  if (strcmp(taskName, "Pressure") == 0) return CRASH_TASK_PRESSURE;
  if (strcmp(taskName, "StartDefaultTask") == 0 || strcmp(taskName, "MotorInit") == 0) return CRASH_TASK_BOOT;
  if (strcmp(taskName, "PReg") == 0) return CRASH_TASK_PREG_P;
  if (strcmp(taskName, "HomeX") == 0) return CRASH_TASK_HOME_X;
  if (strcmp(taskName, "HomeY") == 0) return CRASH_TASK_HOME_Y;
  if (strcmp(taskName, "HomeZ") == 0) return CRASH_TASK_HOME_Z;
  if (strcmp(taskName, "HomePR_P") == 0) return CRASH_TASK_HOME_P;
  if (strcmp(taskName, "HomePR_R") == 0) return CRASH_TASK_HOME_R;
  return CRASH_TASK_NONE;
}
