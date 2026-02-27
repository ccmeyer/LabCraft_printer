#include "CppUTest/TestHarness.h"
#include "PressureRegulatorMath.h"

TEST_GROUP(PressureRegulatorMath)
{
};

TEST(PressureRegulatorMath, ClampTargetAppliesBoundsAndRateLimit) {
    PressureRegulatorMath::TargetLimits limits{};
    limits.currentTarget = 3000;
    limits.minTarget = 1638;
    limits.maxTarget = 6007;
    limits.maxCmdStep = 3000;

    LONGS_EQUAL(6000, PressureRegulatorMath::clampTarget(limits, 7000));
    LONGS_EQUAL(1638, PressureRegulatorMath::clampTarget(limits, 1000));
}

TEST(PressureRegulatorMath, RelativeTargetUsesMagnitudeClampAndBounds) {
    PressureRegulatorMath::TargetLimits limits{};
    limits.currentTarget = 5900;
    limits.minTarget = 1638;
    limits.maxTarget = 6007;
    limits.maxRelStep = 880;

    LONGS_EQUAL(6007, PressureRegulatorMath::clampRelativeTarget(limits, true, -2000));

    limits.currentTarget = 1700;
    LONGS_EQUAL(1638, PressureRegulatorMath::clampRelativeTarget(limits, false, 1000));
}

TEST(PressureRegulatorMath, PrintProfilePreservesIContributionAcrossGainChange) {
    PressureRegulatorMath::ProfileState state{};
    state.kpCurrent = 100;
    state.kiCurrent = 4;
    state.kdCurrent = 50;
    state.kpPrint = 60;
    state.kiPrint = 0;
    state.kdPrint = 25;
    state.kpTrack = 100;
    state.kiTrack = 2;
    state.kdTrack = 50;
    state.integral = 300;
    state.iContrib = 0;
    state.iCap = 20000;
    state.maxHzDeltaPerLoop = 2000;
    state.maxHzDeltaPrint = 500;
    state.maxHzDeltaTrack = 2000;

    const auto printState = PressureRegulatorMath::applyPrintProfile(state, true);
    LONGS_EQUAL(0, printState.kiCurrent);
    LONGS_EQUAL(1200, printState.iContrib);
    UNSIGNED_LONGS_EQUAL(500u, printState.maxHzDeltaPerLoop);

    const auto trackState = PressureRegulatorMath::applyPrintProfile(printState, false);
    LONGS_EQUAL(2, trackState.kiCurrent);
    LONGS_EQUAL(600, trackState.integral);
    LONGS_EQUAL(1200, trackState.iContrib);
    UNSIGNED_LONGS_EQUAL(2000u, trackState.maxHzDeltaPerLoop);
}
