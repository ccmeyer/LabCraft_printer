#include "CppUTest/TestHarness.h"
#include "PressureTargetPolicy.h"

TEST_GROUP(PressureTargetPolicyHelpers)
{
};

TEST(PressureTargetPolicyHelpers, InactiveRegulatorDoesNotWaitAfterTargetChange) {
    CHECK_FALSE(PressureTargetPolicy::shouldWaitForReadyAfterTargetChange(false));
}

TEST(PressureTargetPolicyHelpers, ActiveRegulatorWaitsAfterTargetChange) {
    CHECK_TRUE(PressureTargetPolicy::shouldWaitForReadyAfterTargetChange(true));
}
