#include "CppUTest/TestHarness.h"

#include "CrashWatchdogSelfTestPolicy.h"
#include "DiagnosticResultEmitter.h"

#include <cstring>

namespace {

CrashLogSnapshot makeCleanCrashSnapshot()
{
    CrashLogSnapshot snap{};
    snap.resetCause = CRASH_RESET_POWER;
    snap.lastFault = CRASH_FAULT_NONE;
    snap.lastTask = CRASH_TASK_NONE;
    snap.bootCount = 42u;
    snap.faultCountTotal = 3u;
    snap.watchdogResetCount = 2u;
    snap.watchdogStickyCount = 4u;
    snap.watchdogRawStatus = 3u;
    snap.bootStage = CRASH_BOOT_STAGE_HELLO_ACK;
    snap.watchdogLateTask = CRASH_TASK_NONE;
    return snap;
}

WatchdogSelfTestSnapshot makeWatchdogSnapshot()
{
    WatchdogSelfTestSnapshot snap{};
    snap.armResult = WATCHDOG_ARM_RESULT_ARMED;
    snap.enabled = 1u;
    snap.requiredTaskCount = 3u;
    snap.liveTaskCount = 3u;
    snap.lateTask = CRASH_TASK_NONE;
    snap.timeoutMs = 4000u;
    snap.initTimeoutMs = 20u;
    snap.rawStatus = 0u;
    snap.stickyStatusCount = 0u;
    snap.recoveryBoot = 0u;
    return snap;
}

void checkContains(const char* text, const char* needle)
{
    CHECK_TRUE(std::strstr(text, needle) != nullptr);
}

size_t findTag(const uint8_t* payload, size_t len, uint8_t tag)
{
    size_t idx = 2u;
    while ((idx + 2u) <= len) {
        const uint8_t currentTag = payload[idx++];
        const uint8_t valueLen = payload[idx++];
        if (currentTag == tag) {
            return idx - 2u;
        }
        idx += valueLen;
    }
    return len;
}

void checkMetricsPreservedByEmitter(uint16_t testId, const char* name, const char* metrics)
{
    uint8_t payload[256] = {0};
    const size_t len = DiagnosticResultEmitter::buildResultPayload(
        payload,
        sizeof(payload),
        0x01u,
        0x02u,
        testId,
        name,
        true,
        metrics,
        0x04u);

    const size_t metricsTag = findTag(payload, len, DiagnosticResultEmitter::kTagMetrics);
    CHECK_TRUE(metricsTag < len);
    UNSIGNED_LONGS_EQUAL(std::strlen(metrics), payload[metricsTag + 1]);
    MEMCMP_EQUAL(metrics, &payload[metricsTag + 2], std::strlen(metrics));
}

} // namespace

TEST_GROUP(CrashWatchdogSelfTestPolicy)
{
};

TEST(CrashWatchdogSelfTestPolicy, CleanCrashSnapshotPassesWithCompleteMetrics)
{
    const CrashLogSnapshot snap = makeCleanCrashSnapshot();
    char metrics[224] = {0};

    CHECK_TRUE(BuildCrashRecordSelfTestResult(snap, metrics, sizeof(metrics)));

    STRCMP_EQUAL(
        "pending=0;sticky=0;fault=none;task=none;reset=power;boot=42;fault_ct=3;wdg_ct=2;sticky_ct=4;raw_sr=3;boot_stage=hello_ack;wdg_late=none",
        metrics);
}

TEST(CrashWatchdogSelfTestPolicy, RetainedPendingCrashFailsWithDiagnosticMetrics)
{
    CrashLogSnapshot snap = makeCleanCrashSnapshot();
    snap.flags = CRASHLOG_FLAG_PENDING;
    snap.lastFault = CRASH_FAULT_HARD;
    snap.lastTask = CRASH_TASK_ORCH;
    snap.resetCause = CRASH_RESET_SOFTWARE;
    snap.bootStage = CRASH_BOOT_STAGE_COMM_READY;
    snap.watchdogLateTask = CRASH_TASK_PREG_P;
    char metrics[224] = {0};

    CHECK_FALSE(BuildCrashRecordSelfTestResult(snap, metrics, sizeof(metrics)));

    checkContains(metrics, "pending=1");
    checkContains(metrics, "fault=hard");
    checkContains(metrics, "task=orch");
    checkContains(metrics, "reset=soft");
    checkContains(metrics, "boot_stage=comm");
    checkContains(metrics, "wdg_late=pregp");
}

TEST(CrashWatchdogSelfTestPolicy, StickyWatchdogHistoryExceptionIsPreserved)
{
    CrashLogSnapshot snap = makeCleanCrashSnapshot();
    snap.flags = CRASHLOG_FLAG_PENDING | CRASHLOG_FLAG_WDT_ARM_STICKY;
    snap.lastFault = CRASH_FAULT_WDT_STARVE;
    snap.resetCause = CRASH_RESET_WWDG;
    snap.watchdogLateTask = CRASH_TASK_STATUS;
    char metrics[224] = {0};

    CHECK_TRUE(BuildCrashRecordSelfTestResult(snap, metrics, sizeof(metrics)));
    checkContains(metrics, "pending=1;sticky=1;fault=wdt");
    checkContains(metrics, "reset=wwdg");
    checkContains(metrics, "wdg_late=status");
}

TEST(CrashWatchdogSelfTestPolicy, IwdgStickyWatchdogRecordStillFails)
{
    CrashLogSnapshot snap = makeCleanCrashSnapshot();
    snap.flags = CRASHLOG_FLAG_PENDING | CRASHLOG_FLAG_WDT_ARM_STICKY;
    snap.lastFault = CRASH_FAULT_WDT_STARVE;
    snap.resetCause = CRASH_RESET_IWDG;
    char metrics[224] = {0};

    CHECK_FALSE(BuildCrashRecordSelfTestResult(snap, metrics, sizeof(metrics)));
    checkContains(metrics, "reset=iwdg");
}

TEST(CrashWatchdogSelfTestPolicy, ArmedWatchdogSupervisorPassesWhenAllTasksAreLive)
{
    const WatchdogSelfTestSnapshot snap = makeWatchdogSnapshot();
    char metrics[192] = {0};

    CHECK_TRUE(BuildWatchdogSupervisorSelfTestResult(snap, metrics, sizeof(metrics)));

    STRCMP_EQUAL(
        "enabled=1;arm_result=armed;timeout_ms=4000;init_timeout_ms=20;req_n=3;live_n=3;late_task=none;raw_sr=0;sticky_ct=0;recovery_boot=0",
        metrics);
}

TEST(CrashWatchdogSelfTestPolicy, StickyStatusWatchdogSkipPassesOnlyInCleanSkippedState)
{
    WatchdogSelfTestSnapshot snap = makeWatchdogSnapshot();
    snap.armResult = WATCHDOG_ARM_RESULT_SKIPPED_STICKY_STATUS;
    snap.enabled = 0u;
    snap.requiredTaskCount = 0u;
    snap.liveTaskCount = 0u;
    snap.stickyStatusCount = 2u;
    snap.rawStatus = 3u;
    snap.recoveryBoot = 1u;
    char metrics[192] = {0};

    CHECK_TRUE(BuildWatchdogSupervisorSelfTestResult(snap, metrics, sizeof(metrics)));
    checkContains(metrics, "arm_result=sticky_status_skip");
    checkContains(metrics, "req_n=0;live_n=0");

    snap.liveTaskCount = 1u;
    CHECK_FALSE(BuildWatchdogSupervisorSelfTestResult(snap, metrics, sizeof(metrics)));
}

TEST(CrashWatchdogSelfTestPolicy, TimeoutRecoveryRequiredAndLateTaskWatchdogStatesFail)
{
    WatchdogSelfTestSnapshot snap = makeWatchdogSnapshot();
    char metrics[192] = {0};

    snap.armResult = WATCHDOG_ARM_RESULT_TIMEOUT_LSI;
    snap.enabled = 0u;
    snap.requiredTaskCount = 2u;
    snap.liveTaskCount = 1u;
    snap.lateTask = CRASH_TASK_STATUS;
    CHECK_FALSE(BuildWatchdogSupervisorSelfTestResult(snap, metrics, sizeof(metrics)));
    checkContains(metrics, "arm_result=timeout_lsi");
    checkContains(metrics, "req_n=2;live_n=1");
    checkContains(metrics, "late_task=status");

    snap = makeWatchdogSnapshot();
    snap.armResult = WATCHDOG_ARM_RESULT_RECOVERY_RESET_REQUIRED;
    CHECK_FALSE(BuildWatchdogSupervisorSelfTestResult(snap, metrics, sizeof(metrics)));
    checkContains(metrics, "arm_result=recovery_reset");

    snap = makeWatchdogSnapshot();
    snap.lateTask = CRASH_TASK_ORCH;
    CHECK_FALSE(BuildWatchdogSupervisorSelfTestResult(snap, metrics, sizeof(metrics)));
    checkContains(metrics, "late_task=orch");
}

TEST(CrashWatchdogSelfTestPolicy, MetricsFitThroughSelfTestResultEmitter)
{
    CrashLogSnapshot crash = makeCleanCrashSnapshot();
    crash.flags = CRASHLOG_FLAG_PENDING | CRASHLOG_FLAG_WDT_ARM_STICKY;
    crash.lastFault = CRASH_FAULT_WDT_STARVE;
    crash.lastTask = CRASH_TASK_PRESSURE;
    crash.resetCause = CRASH_RESET_WWDG;
    crash.bootCount = 123456u;
    crash.faultCountTotal = 234567u;
    crash.watchdogResetCount = 345678u;
    crash.watchdogStickyCount = 456789u;
    crash.watchdogRawStatus = 0xFFFFFFFFu;
    crash.bootStage = CRASH_BOOT_STAGE_COMM_RX_REARMED;
    crash.watchdogLateTask = CRASH_TASK_HOME_R;
    char crashMetrics[224] = {0};
    CHECK_TRUE(BuildCrashRecordSelfTestResult(crash, crashMetrics, sizeof(crashMetrics)));
    checkMetricsPreservedByEmitter(1041u, "crash_record_retained_safe", crashMetrics);

    WatchdogSelfTestSnapshot watchdog = makeWatchdogSnapshot();
    watchdog.armResult = WATCHDOG_ARM_RESULT_TIMEOUT_STATUS;
    watchdog.enabled = 1u;
    watchdog.requiredTaskCount = 12u;
    watchdog.liveTaskCount = 11u;
    watchdog.lateTask = CRASH_TASK_HOME_R;
    watchdog.rawStatus = 0xFFFFFFFFu;
    watchdog.stickyStatusCount = 987654u;
    watchdog.recoveryBoot = 1u;
    char watchdogMetrics[192] = {0};
    CHECK_FALSE(BuildWatchdogSupervisorSelfTestResult(watchdog, watchdogMetrics, sizeof(watchdogMetrics)));
    checkMetricsPreservedByEmitter(1042u, "watchdog_supervisor_safe", watchdogMetrics);
}
