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

TEST(PressureRegulatorMath, ValidatePressureSampleRejectsRailsAndSpikes) {
    PressureRegulatorMath::ValidationConfig cfg{};
    cfg.minRaw = 1200;
    cfg.maxRaw = 7000;
    cfg.maxStepPerSample = 250;

    const auto low = PressureRegulatorMath::validatePressureSample(2000, 1100, 0, cfg);
    CHECK_FALSE(low.accept);
    LONGS_EQUAL(static_cast<long>(PressureRegulatorMath::PressureRejectReason::RailLow),
                static_cast<long>(low.reason));
    UNSIGNED_LONGS_EQUAL(2000u, low.committedRaw);

    const auto high = PressureRegulatorMath::validatePressureSample(2000, 7100, 0, cfg);
    CHECK_FALSE(high.accept);
    LONGS_EQUAL(static_cast<long>(PressureRegulatorMath::PressureRejectReason::RailHigh),
                static_cast<long>(high.reason));

    const auto spike = PressureRegulatorMath::validatePressureSample(2000, 2400, 0, cfg);
    CHECK_FALSE(spike.accept);
    LONGS_EQUAL(static_cast<long>(PressureRegulatorMath::PressureRejectReason::Spike),
                static_cast<long>(spike.reason));
}

TEST(PressureRegulatorMath, ValidatePressureSampleForcesAcceptanceAfterTooManyRejects) {
    PressureRegulatorMath::ValidationConfig cfg{};
    cfg.maxStepPerSample = 100;
    cfg.maxConsecutiveRejects = 3;

    const auto result = PressureRegulatorMath::validatePressureSample(2000, 2400, 3, cfg);
    CHECK_TRUE(result.accept);
    UNSIGNED_LONGS_EQUAL(2400u, result.committedRaw);
}

TEST(PressureRegulatorMath, RecoveryBoostScalesAndClamps) {
    PressureRegulatorMath::RecoveryConfig cfg{};
    cfg.baseBoostHz = 1500;
    cfg.pressureCoeffHzPerRaw = 2;
    cfg.pulseCoeffHzPerUs = 1;
    cfg.maxBoostHz = 5000;

    const auto boost = PressureRegulatorMath::computeRecoveryBoostHz(2000, 1300, cfg, 1638);
    UNSIGNED_LONGS_EQUAL(3524u, boost);

    const auto clamped = PressureRegulatorMath::computeRecoveryBoostHz(4000, 3000, cfg, 1638);
    UNSIGNED_LONGS_EQUAL(5000u, clamped);
}

TEST(PressureRegulatorMath, RecoveryBoostDecayIsLinearAndDeadlineSlipIsNonNegative) {
    UNSIGNED_LONGS_EQUAL(500u, PressureRegulatorMath::decayRecoveryBoostHz(1000u, 2u, 4u, true));
    UNSIGNED_LONGS_EQUAL(0u, PressureRegulatorMath::decayRecoveryBoostHz(1000u, 0u, 4u, true));
    UNSIGNED_LONGS_EQUAL(1000u, PressureRegulatorMath::decayRecoveryBoostHz(1000u, 2u, 4u, false));

    UNSIGNED_LONGS_EQUAL(0u, PressureRegulatorMath::computeDeadlineSlipMs(100u, 95u));
    UNSIGNED_LONGS_EQUAL(23u, PressureRegulatorMath::computeDeadlineSlipMs(100u, 123u));
}

TEST(PressureRegulatorMath, DefaultReadyToleranceIsChannelSpecific) {
    UNSIGNED_LONGS_EQUAL(4u, PressureRegulatorMath::defaultReadyTolRaw(0u));
    UNSIGNED_LONGS_EQUAL(8u, PressureRegulatorMath::defaultReadyTolRaw(1u));
    UNSIGNED_LONGS_EQUAL(8u, PressureRegulatorMath::defaultReadyTolRaw(2u));
}

TEST(PressureRegulatorMath, RecoveryRequestedHzAppliesDirectionalBoostAndBounds) {
    PressureRegulatorMath::RecoveryState s{};
    s.baseRequestedHz = 1200;
    s.decayedBoostHz = 800;
    s.recoveryActive = true;
    s.errorRaw = -10;
    s.boostOnlyWhenUndershoot = true;
    s.maxRequestedHz = 4000;
    s.minRequestedHz = 500;
    s.recoveryFloorHz = 0;
    UNSIGNED_LONGS_EQUAL(2000u, PressureRegulatorMath::computeRecoveryRequestedHz(s));

    s.errorRaw = 8;
    UNSIGNED_LONGS_EQUAL(1200u, PressureRegulatorMath::computeRecoveryRequestedHz(s));

    s.boostOnlyWhenUndershoot = false;
    s.maxRequestedHz = 1500;
    UNSIGNED_LONGS_EQUAL(1500u, PressureRegulatorMath::computeRecoveryRequestedHz(s));
}

TEST(PressureRegulatorMath, AsymmetricSlewAndRecoveryExtensionBehaveAsExpected) {
    PressureRegulatorMath::SlewConfig slew{};
    slew.maxHzDeltaUpPerLoop = 600;
    slew.maxHzDeltaDownPerLoop = 200;

    UNSIGNED_LONGS_EQUAL(1600u, PressureRegulatorMath::applyAsymmetricSlew(2200u, 1000u, slew));
    UNSIGNED_LONGS_EQUAL(1800u, PressureRegulatorMath::applyAsymmetricSlew(1800u, 1900u, slew));
    UNSIGNED_LONGS_EQUAL(1500u, PressureRegulatorMath::applyAsymmetricSlew(1400u, 1700u, slew));

    CHECK_TRUE(PressureRegulatorMath::shouldExtendRecovery(-12, 3, 1, 4, true, 3));
    CHECK_FALSE(PressureRegulatorMath::shouldExtendRecovery(6, 3, 1, 4, true, 3));
    CHECK_FALSE(PressureRegulatorMath::shouldExtendRecovery(-12, 3, 4, 4, true, 3));
    CHECK_FALSE(PressureRegulatorMath::shouldExtendRecovery(-2, 3, 0, 4, true, 3));
}
