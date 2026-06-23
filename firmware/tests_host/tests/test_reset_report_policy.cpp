#include "CppUTest/TestHarness.h"

#include "ResetReportPolicy.h"

namespace {
CrashLogSnapshot makeSnapshot(CrashResetCause resetCause, uint32_t flags = 0u)
{
    CrashLogSnapshot snap{};
    snap.flags = flags;
    snap.resetCause = resetCause;
    return snap;
}
}

TEST_GROUP(ResetReportPolicy)
{
};

TEST(ResetReportPolicy, PendingCrashSendsReportForUnknownReset)
{
    const CrashLogSnapshot snap = makeSnapshot(CRASH_RESET_UNKNOWN, CRASHLOG_FLAG_PENDING);
    CHECK_TRUE(ResetReport_ShouldSend(&snap));
}

TEST(ResetReportPolicy, WatchdogResetsSendReport)
{
    const CrashLogSnapshot iwdg = makeSnapshot(CRASH_RESET_IWDG);
    const CrashLogSnapshot wwdg = makeSnapshot(CRASH_RESET_WWDG);
    CHECK_TRUE(ResetReport_ShouldSend(&iwdg));
    CHECK_TRUE(ResetReport_ShouldSend(&wwdg));
}

TEST(ResetReportPolicy, PowerResetSendsReport)
{
    const CrashLogSnapshot snap = makeSnapshot(CRASH_RESET_POWER);
    CHECK_TRUE(ResetReport_ShouldSend(&snap));
}

TEST(ResetReportPolicy, PinResetSendsReport)
{
    const CrashLogSnapshot snap = makeSnapshot(CRASH_RESET_PIN);
    CHECK_TRUE(ResetReport_ShouldSend(&snap));
}

TEST(ResetReportPolicy, SoftwareResetSendsReport)
{
    const CrashLogSnapshot snap = makeSnapshot(CRASH_RESET_SOFTWARE);
    CHECK_TRUE(ResetReport_ShouldSend(&snap));
}

TEST(ResetReportPolicy, LowPowerResetSendsReport)
{
    const CrashLogSnapshot snap = makeSnapshot(CRASH_RESET_LOW_POWER);
    CHECK_TRUE(ResetReport_ShouldSend(&snap));
}

TEST(ResetReportPolicy, UnknownResetWithoutPendingCrashSendsReport)
{
    const CrashLogSnapshot snap = makeSnapshot(CRASH_RESET_UNKNOWN);
    CHECK_TRUE(ResetReport_ShouldSend(&snap));
}

TEST(ResetReportPolicy, UnexpectedResetEnumStillSendsReport)
{
    const CrashLogSnapshot snap = makeSnapshot(static_cast<CrashResetCause>(99));
    CHECK_TRUE(ResetReport_ShouldSend(&snap));
}

TEST(ResetReportPolicy, NullSnapshotDoesNotSendReport)
{
    CHECK_FALSE(ResetReport_ShouldSend(nullptr));
}
