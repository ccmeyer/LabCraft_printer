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

TEST(ResetReportPolicy, DeliveryWaitsForHostHello)
{
    const CrashLogSnapshot snap = makeSnapshot(CRASH_RESET_IWDG);
    CHECK_FALSE(ResetReport_ShouldAttemptDelivery(&snap, false, false));
}

TEST(ResetReportPolicy, FirstHostHelloAttemptsDelivery)
{
    const CrashLogSnapshot snap = makeSnapshot(CRASH_RESET_IWDG);
    CHECK_TRUE(ResetReport_ShouldAttemptDelivery(&snap, true, false));
}

TEST(ResetReportPolicy, SuccessfulDeliveryIsNotRepeated)
{
    const CrashLogSnapshot snap = makeSnapshot(CRASH_RESET_IWDG);
    CHECK_FALSE(ResetReport_ShouldAttemptDelivery(&snap, true, true));
}

TEST(ResetReportPolicy, NullSnapshotIsNeverDelivered)
{
    CHECK_FALSE(ResetReport_ShouldAttemptDelivery(nullptr, true, false));
}

TEST(ResetReportPolicy, InvalidRegulatorContextIsNotIncluded)
{
    CrashLogSnapshot snap = makeSnapshot(CRASH_RESET_IWDG);
    snap.lastFault = CRASH_FAULT_WDT_STARVE;
    snap.regulatorContext.valid = 0u;

    CHECK_FALSE(ResetReport_ShouldIncludeRegulatorContext(&snap));
}

TEST(ResetReportPolicy, ValidRegulatorContextIsIncludedForWatchdogResets)
{
    CrashLogSnapshot iwdg = makeSnapshot(CRASH_RESET_IWDG);
    CrashLogSnapshot wwdg = makeSnapshot(CRASH_RESET_WWDG);
    iwdg.regulatorContext.valid = 1u;
    wwdg.regulatorContext.valid = 1u;

    CHECK_TRUE(ResetReport_ShouldIncludeRegulatorContext(&iwdg));
    CHECK_TRUE(ResetReport_ShouldIncludeRegulatorContext(&wwdg));
}

TEST(ResetReportPolicy, ValidRegulatorContextIsIncludedForWatchdogFaultRecord)
{
    CrashLogSnapshot snap = makeSnapshot(CRASH_RESET_SOFTWARE);
    snap.lastFault = CRASH_FAULT_WDT_STARVE;
    snap.regulatorContext.valid = 1u;

    CHECK_TRUE(ResetReport_ShouldIncludeRegulatorContext(&snap));
}

TEST(ResetReportPolicy, ValidRegulatorContextIsNotIncludedForUnrelatedReset)
{
    CrashLogSnapshot snap = makeSnapshot(CRASH_RESET_PIN);
    snap.lastFault = CRASH_FAULT_NONE;
    snap.regulatorContext.valid = 1u;

    CHECK_FALSE(ResetReport_ShouldIncludeRegulatorContext(&snap));
}

TEST(ResetReportPolicy, NullSnapshotDoesNotIncludeRegulatorContext)
{
    CHECK_FALSE(ResetReport_ShouldIncludeRegulatorContext(nullptr));
}

TEST(ResetReportPolicy, XyContextIsIncludedWhenNoCpuFaultContextExists)
{
    CrashLogSnapshot snap = makeSnapshot(CRASH_RESET_SOFTWARE);
    snap.xyMotionContextValid = 1u;

    const ResetReportContextSelection selection = ResetReport_SelectContexts(&snap);

    CHECK_TRUE(selection.includeXyMotionContext);
    CHECK_FALSE(selection.includeFaultContext);
}

TEST(ResetReportPolicy, PendingCpuFaultContextTakesPriorityOverXyContext)
{
    CrashLogSnapshot snap = makeSnapshot(CRASH_RESET_IWDG, CRASHLOG_FLAG_PENDING);
    snap.faultContextValid = 1u;
    snap.xyMotionContextValid = 1u;

    const ResetReportContextSelection selection = ResetReport_SelectContexts(&snap);

    CHECK_TRUE(selection.includeFaultContext);
    CHECK_FALSE(selection.includeXyMotionContext);
}

TEST(ResetReportPolicy, XyContextTakesPriorityOverStaleCpuFaultContext)
{
    CrashLogSnapshot snap = makeSnapshot(CRASH_RESET_SOFTWARE);
    snap.faultContextValid = 1u;
    snap.xyMotionContextValid = 1u;

    const ResetReportContextSelection selection = ResetReport_SelectContexts(&snap);

    CHECK_FALSE(selection.includeFaultContext);
    CHECK_TRUE(selection.includeXyMotionContext);
}

TEST(ResetReportPolicy, CpuFaultContextIsIncludedWhenItIsTheOnlyExtendedContext)
{
    CrashLogSnapshot snap = makeSnapshot(CRASH_RESET_SOFTWARE);
    snap.faultContextValid = 1u;

    const ResetReportContextSelection selection = ResetReport_SelectContexts(&snap);

    CHECK_TRUE(selection.includeFaultContext);
    CHECK_FALSE(selection.includeXyMotionContext);
}

TEST(ResetReportPolicy, RegulatorContextCanAccompanyXyContext)
{
    CrashLogSnapshot snap = makeSnapshot(CRASH_RESET_IWDG);
    snap.regulatorContext.valid = 1u;
    snap.xyMotionContextValid = 1u;

    const ResetReportContextSelection selection = ResetReport_SelectContexts(&snap);

    CHECK_TRUE(selection.includeRegulatorContext);
    CHECK_TRUE(selection.includeXyMotionContext);
}

TEST(ResetReportPolicy, NullSnapshotSelectsNoContexts)
{
    const ResetReportContextSelection selection = ResetReport_SelectContexts(nullptr);
    CHECK_FALSE(selection.includeRegulatorContext);
    CHECK_FALSE(selection.includeFaultContext);
    CHECK_FALSE(selection.includeXyMotionContext);
}
