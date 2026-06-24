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

TEST(CrashLogCodec, SoftwareFlagCurrentlyTakesPriorityOverPinFlag)
{
    const uint32_t flags = CRASHLOG_RCC_CSR_SFTRSTF | CRASHLOG_RCC_CSR_PINRSTF;
    LONGS_EQUAL((int)CRASH_RESET_SOFTWARE, (int)CrashLog_ClassifyResetFlags(flags));
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
    STRCMP_EQUAL("homex", CrashLog_TaskIdName(CRASH_TASK_HOME_X));
    STRCMP_EQUAL("homer", CrashLog_TaskIdName(CRASH_TASK_HOME_R));
    STRCMP_EQUAL("prnt", CrashLog_TaskIdName(CRASH_TASK_PRINTER));
    STRCMP_EQUAL("wdog", CrashLog_TaskIdName(CRASH_TASK_WATCHDOG));
}

TEST(CrashLogCodec, TaskNameMapsHomeWorkers)
{
    LONGS_EQUAL((int)CRASH_TASK_HOME_X, (int)CrashLog_TaskIdFromTaskName("HomeX"));
    LONGS_EQUAL((int)CRASH_TASK_HOME_R, (int)CrashLog_TaskIdFromTaskName("HomePR_R"));
}

TEST(CrashLogCodec, TaskNameMapsRuntimeWorkers)
{
    LONGS_EQUAL((int)CRASH_TASK_ORCH, (int)CrashLog_TaskIdFromTaskName("Orch"));
    LONGS_EQUAL((int)CRASH_TASK_STATUS, (int)CrashLog_TaskIdFromTaskName("Status"));
    LONGS_EQUAL((int)CRASH_TASK_PRINTER, (int)CrashLog_TaskIdFromTaskName("PRNT"));
    LONGS_EQUAL((int)CRASH_TASK_GRIPPER, (int)CrashLog_TaskIdFromTaskName("GRP_REFR"));
    LONGS_EQUAL((int)CRASH_TASK_LED, (int)CrashLog_TaskIdFromTaskName("LED"));
    LONGS_EQUAL((int)CRASH_TASK_LED_FADE, (int)CrashLog_TaskIdFromTaskName("LEDFade"));
    LONGS_EQUAL((int)CRASH_TASK_LOG_STATS, (int)CrashLog_TaskIdFromTaskName("LogStats"));
    LONGS_EQUAL((int)CRASH_TASK_HEARTBEAT, (int)CrashLog_TaskIdFromTaskName("Heartbeat"));
    LONGS_EQUAL((int)CRASH_TASK_WATCHDOG, (int)CrashLog_TaskIdFromTaskName("Wdog"));
    LONGS_EQUAL((int)CRASH_TASK_IDLE, (int)CrashLog_TaskIdFromTaskName("IDLE"));
    LONGS_EQUAL((int)CRASH_TASK_TIMER, (int)CrashLog_TaskIdFromTaskName("Tmr Svc"));
}

TEST(CrashLogCodec, SelectStackOverflowTaskPrefersHookTaskThenActiveTask)
{
    LONGS_EQUAL((int)CRASH_TASK_STATUS,
                (int)CrashLog_SelectStackOverflowTaskId(CRASH_TASK_STATUS, CRASH_TASK_ORCH));
    LONGS_EQUAL((int)CRASH_TASK_ORCH,
                (int)CrashLog_SelectStackOverflowTaskId(CRASH_TASK_NONE, CRASH_TASK_ORCH));
    LONGS_EQUAL((int)CRASH_TASK_NONE,
                (int)CrashLog_SelectStackOverflowTaskId(CRASH_TASK_NONE, CRASH_TASK_NONE));
}

TEST(CrashLogCodec, PackTaskName4UsesLittleEndianPrefix)
{
    UNSIGNED_LONGS_EQUAL(0u, CrashLog_PackTaskName4(nullptr));
    UNSIGNED_LONGS_EQUAL(0u, CrashLog_PackTaskName4(""));
    UNSIGNED_LONGS_EQUAL(0x00000050u, CrashLog_PackTaskName4("P"));
    UNSIGNED_LONGS_EQUAL(0x6863724Fu, CrashLog_PackTaskName4("Orch"));
    UNSIGNED_LONGS_EQUAL(0x544E5250u, CrashLog_PackTaskName4("PRNT_task"));
}

TEST(CrashLogCodec, UnknownTaskNameMapsToNone)
{
    LONGS_EQUAL((int)CRASH_TASK_NONE, (int)CrashLog_TaskIdFromTaskName("UnknownTask"));
}
