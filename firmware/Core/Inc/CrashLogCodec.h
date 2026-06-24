#ifndef INC_CRASHLOGCODEC_H_
#define INC_CRASHLOGCODEC_H_

#include "CrashLog.h"

#ifdef __cplusplus
extern "C" {
#endif

#define CRASHLOG_RCC_CSR_LPWRRSTF  0x80000000u
#define CRASHLOG_RCC_CSR_WWDGRSTF  0x40000000u
#define CRASHLOG_RCC_CSR_IWDGRSTF  0x20000000u
#define CRASHLOG_RCC_CSR_SFTRSTF   0x10000000u
#define CRASHLOG_RCC_CSR_PORRSTF   0x08000000u
#define CRASHLOG_RCC_CSR_PINRSTF   0x04000000u
#define CRASHLOG_RCC_CSR_BORRSTF   0x02000000u

CrashResetCause CrashLog_ClassifyResetFlags(uint32_t resetFlagsRaw);
const char* CrashLog_FaultKindName(CrashFaultKind kind);
const char* CrashLog_ResetCauseName(CrashResetCause cause);
const char* CrashLog_TaskIdName(CrashTaskId taskId);
CrashTaskId CrashLog_TaskIdFromTaskName(const char* taskName);
CrashTaskId CrashLog_SelectStackOverflowTaskId(CrashTaskId hookTaskId, CrashTaskId activeTaskId);
uint32_t CrashLog_PackTaskName4(const char* taskName);

#ifdef __cplusplus
}
#endif

#endif /* INC_CRASHLOGCODEC_H_ */
