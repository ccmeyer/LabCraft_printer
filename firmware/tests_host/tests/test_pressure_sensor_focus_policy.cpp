#include "CppUTest/TestHarness.h"
#include "PressureSensorFocusPolicy.h"

TEST_GROUP(PressureSensorFocusPolicy)
{
};

TEST(PressureSensorFocusPolicy, NormalModeAdvancesRoundRobinPorts) {
    UNSIGNED_LONGS_EQUAL(0u, PressureSensorFocusPolicy::portForRead(0u, 2u, false, 1u));
    UNSIGNED_LONGS_EQUAL(1u, PressureSensorFocusPolicy::nextPortAfterRead(0u, 2u, false, 1u));
    UNSIGNED_LONGS_EQUAL(0u, PressureSensorFocusPolicy::nextPortAfterRead(1u, 2u, false, 1u));
}

TEST(PressureSensorFocusPolicy, FocusModeHoldsRequestedPort) {
    UNSIGNED_LONGS_EQUAL(1u, PressureSensorFocusPolicy::portForRead(0u, 2u, true, 1u));
    UNSIGNED_LONGS_EQUAL(1u, PressureSensorFocusPolicy::nextPortAfterRead(1u, 2u, true, 1u));
    UNSIGNED_LONGS_EQUAL(1u, PressureSensorFocusPolicy::nextPortAfterRead(0u, 2u, true, 1u));
}

TEST(PressureSensorFocusPolicy, InvalidPortsClampToZero) {
    UNSIGNED_LONGS_EQUAL(0u, PressureSensorFocusPolicy::portForRead(9u, 2u, false, 0u));
    UNSIGNED_LONGS_EQUAL(0u, PressureSensorFocusPolicy::portForRead(0u, 2u, true, 9u));
    UNSIGNED_LONGS_EQUAL(0u, PressureSensorFocusPolicy::nextPortAfterRead(0u, 0u, false, 0u));
}
