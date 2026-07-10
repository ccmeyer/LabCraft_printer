#include "CppUTest/TestHarness.h"
#include "PressureRegulatorWatchdogPolicy.h"

TEST_GROUP(PressureRegulatorWatchdogPolicyHelpers)
{
};

TEST(PressureRegulatorWatchdogPolicyHelpers, MotionHoldCannotEnableWhileRecoveryHeld) {
    uint8_t mask = 0u;
    mask = PressureRegulatorWatchdogPolicy::withHold(
        mask,
        PressureRegulatorWatchdogPolicy::Hold::Recovery);
    mask = PressureRegulatorWatchdogPolicy::withHold(
        mask,
        PressureRegulatorWatchdogPolicy::Hold::MotionHold);

    mask = PressureRegulatorWatchdogPolicy::withoutHold(
        mask,
        PressureRegulatorWatchdogPolicy::Hold::MotionHold);

    CHECK_TRUE(PressureRegulatorWatchdogPolicy::hasHold(
        mask,
        PressureRegulatorWatchdogPolicy::Hold::Recovery));
    CHECK_FALSE(PressureRegulatorWatchdogPolicy::shouldEnableWatchdog(mask));
}

TEST(PressureRegulatorWatchdogPolicyHelpers, ReleasingRecoveryEnablesWhenNoHoldsRemain) {
    uint8_t mask = PressureRegulatorWatchdogPolicy::withHold(
        0u,
        PressureRegulatorWatchdogPolicy::Hold::Recovery);

    mask = PressureRegulatorWatchdogPolicy::withoutHold(
        mask,
        PressureRegulatorWatchdogPolicy::Hold::Recovery);

    CHECK_TRUE(PressureRegulatorWatchdogPolicy::shouldEnableWatchdog(mask));
}

TEST(PressureRegulatorWatchdogPolicyHelpers, InactiveHoldKeepsWatchdogDisabled) {
    uint8_t mask = 0u;
    mask = PressureRegulatorWatchdogPolicy::withHold(
        mask,
        PressureRegulatorWatchdogPolicy::Hold::Inactive);
    mask = PressureRegulatorWatchdogPolicy::withHold(
        mask,
        PressureRegulatorWatchdogPolicy::Hold::MotionHold);
    mask = PressureRegulatorWatchdogPolicy::withHold(
        mask,
        PressureRegulatorWatchdogPolicy::Hold::Recovery);

    mask = PressureRegulatorWatchdogPolicy::withoutHold(
        mask,
        PressureRegulatorWatchdogPolicy::Hold::MotionHold);
    mask = PressureRegulatorWatchdogPolicy::withoutHold(
        mask,
        PressureRegulatorWatchdogPolicy::Hold::Recovery);

    CHECK_TRUE(PressureRegulatorWatchdogPolicy::hasHold(
        mask,
        PressureRegulatorWatchdogPolicy::Hold::Inactive));
    CHECK_FALSE(PressureRegulatorWatchdogPolicy::shouldEnableWatchdog(mask));
}

TEST(PressureRegulatorWatchdogPolicyHelpers, MotionHoldEligibilityRejectsRecoveryStates) {
    CHECK_FALSE(PressureRegulatorWatchdogPolicy::canEnterMotionHold(
        true, true, true, false, 0u));
    CHECK_FALSE(PressureRegulatorWatchdogPolicy::canEnterMotionHold(
        true, true, false, true, 0u));
    CHECK_FALSE(PressureRegulatorWatchdogPolicy::canEnterMotionHold(
        true,
        true,
        false,
        false,
        PressureRegulatorWatchdogPolicy::holdBit(
            PressureRegulatorWatchdogPolicy::Hold::Recovery)));
}

TEST(PressureRegulatorWatchdogPolicyHelpers, MotionHoldEligibilityAcceptsNormalActiveRegulation) {
    CHECK_TRUE(PressureRegulatorWatchdogPolicy::canEnterMotionHold(
        true, true, false, false, 0u));
}
