#include "CppUTest/TestHarness.h"
#include "FlashOutputState.h"

TEST_GROUP(FlashOutputStateHelpers)
{
};

TEST(FlashOutputStateHelpers, DefaultsToSafeIdle)
{
    FlashOutputState::State state{};

    CHECK_TRUE(FlashOutputState::isSafeIdle(state));
    CHECK_FALSE(FlashOutputState::isArmedOutput(state));
    STRCMP_EQUAL("safe_idle", FlashOutputState::modeToken(state.mode));
}

TEST(FlashOutputStateHelpers, ArmOutputTransitionsFromSafeIdle)
{
    FlashOutputState::State state{};

    const auto transition = FlashOutputState::armOutput(state);

    LONGS_EQUAL(static_cast<long>(FlashOutputState::Transition::ArmedOutputApplied),
                static_cast<long>(transition));
    CHECK_TRUE(FlashOutputState::isArmedOutput(state));
    STRCMP_EQUAL("armed_output", FlashOutputState::modeToken(state.mode));
}

TEST(FlashOutputStateHelpers, ArmOutputIsIdempotentWhenAlreadyArmed)
{
    FlashOutputState::State state{};
    FlashOutputState::armOutput(state);

    const auto transition = FlashOutputState::armOutput(state);

    LONGS_EQUAL(static_cast<long>(FlashOutputState::Transition::NoChange),
                static_cast<long>(transition));
    CHECK_TRUE(FlashOutputState::isArmedOutput(state));
}

TEST(FlashOutputStateHelpers, SafeIdleTransitionsBackFromArmedOutput)
{
    FlashOutputState::State state{};
    FlashOutputState::armOutput(state);

    const auto transition = FlashOutputState::setSafeIdle(state);

    LONGS_EQUAL(static_cast<long>(FlashOutputState::Transition::SafeIdleApplied),
                static_cast<long>(transition));
    CHECK_TRUE(FlashOutputState::isSafeIdle(state));
    CHECK_FALSE(FlashOutputState::isArmedOutput(state));
    STRCMP_EQUAL("safe_idle", FlashOutputState::modeToken(state.mode));
}

TEST(FlashOutputStateHelpers, SafeIdleIsIdempotentWhenAlreadyIdle)
{
    FlashOutputState::State state{};

    const auto transition = FlashOutputState::setSafeIdle(state);

    LONGS_EQUAL(static_cast<long>(FlashOutputState::Transition::NoChange),
                static_cast<long>(transition));
    CHECK_TRUE(FlashOutputState::isSafeIdle(state));
}
