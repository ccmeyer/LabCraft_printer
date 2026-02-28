#include "CppUTest/TestHarness.h"

extern "C" {
#include "CrashLogCodec.h"
}

TEST_GROUP(CrashLogCodec)
{
};

TEST(CrashLogCodec, IwdgResetFlagClassifiesAsIwdg)
{
    LONGS_EQUAL((int)CRASH_RESET_IWDG, (int)CrashLog_ClassifyResetFlags(CRASHLOG_RCC_CSR_IWDGRSTF));
}

TEST(CrashLogCodec, PowerResetFlagsClassifyAsPower)
{
    const uint32_t flags = CRASHLOG_RCC_CSR_PORRSTF | CRASHLOG_RCC_CSR_BORRSTF;
    LONGS_EQUAL((int)CRASH_RESET_POWER, (int)CrashLog_ClassifyResetFlags(flags));
}

TEST(CrashLogCodec, FaultKindToMetricStringIsStable)
{
    STRCMP_EQUAL("hard", CrashLog_FaultKindName(CRASH_FAULT_HARD));
    STRCMP_EQUAL("stkovf", CrashLog_FaultKindName(CRASH_FAULT_STACK_OVF));
    STRCMP_EQUAL("wdt", CrashLog_FaultKindName(CRASH_FAULT_WDT_STARVE));
}

TEST(CrashLogCodec, TaskIdToMetricStringIsStable)
{
    STRCMP_EQUAL("boot", CrashLog_TaskIdName(CRASH_TASK_BOOT));
    STRCMP_EQUAL("status", CrashLog_TaskIdName(CRASH_TASK_STATUS));
    STRCMP_EQUAL("pregr", CrashLog_TaskIdName(CRASH_TASK_PREG_R));
}
