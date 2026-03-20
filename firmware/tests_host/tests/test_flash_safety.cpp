#include "CppUTest/TestHarness.h"
#include "FlashSafety.h"

TEST_GROUP(FlashSafetyHelpers)
{
};

TEST(FlashSafetyHelpers, ArmSessionSucceedsWhenTriggerLineIsLow)
{
    FlashSafety::State state{};

    const auto action = FlashSafety::arm(state, false);

    LONGS_EQUAL(static_cast<long>(FlashSafety::ArmAction::Armed),
                static_cast<long>(action));
    CHECK_TRUE(FlashSafety::isSessionArmed(state));
    CHECK_FALSE(FlashSafety::isFaultLatched(state));
    CHECK_FALSE(state.awaitingRelease);
    STRCMP_EQUAL("none", FlashSafety::faultReasonToken(state.faultReason));
}

TEST(FlashSafetyHelpers, ArmSessionFaultsWhenTriggerLineIsAlreadyHigh)
{
    FlashSafety::State state{};

    const auto action = FlashSafety::arm(state, true);

    LONGS_EQUAL(static_cast<long>(FlashSafety::ArmAction::FaultLatched),
                static_cast<long>(action));
    CHECK_FALSE(FlashSafety::isSessionArmed(state));
    CHECK_TRUE(FlashSafety::isFaultLatched(state));
    STRCMP_EQUAL("line_high_on_arm", FlashSafety::faultReasonToken(state.faultReason));
}

TEST(FlashSafetyHelpers, FirstTriggerIsAcceptedWhileArmed)
{
    FlashSafety::State state{};
    FlashSafety::arm(state, false);

    const auto action = FlashSafety::onTrigger(state);

    LONGS_EQUAL(static_cast<long>(FlashSafety::TriggerAction::Accepted),
                static_cast<long>(action));
    CHECK_TRUE(state.awaitingRelease);
    CHECK_TRUE(FlashSafety::isSessionArmed(state));
    CHECK_FALSE(FlashSafety::isFaultLatched(state));
}

TEST(FlashSafetyHelpers, RetriggerWhileAwaitingReleaseFaultsAndDisarms)
{
    FlashSafety::State state{};
    FlashSafety::arm(state, false);
    FlashSafety::onTrigger(state);

    const auto action = FlashSafety::onTrigger(state);

    LONGS_EQUAL(static_cast<long>(FlashSafety::TriggerAction::FaultLatched),
                static_cast<long>(action));
    CHECK_FALSE(FlashSafety::isSessionArmed(state));
    CHECK_TRUE(FlashSafety::isFaultLatched(state));
    CHECK_FALSE(state.awaitingRelease);
    STRCMP_EQUAL("retrigger_while_high", FlashSafety::faultReasonToken(state.faultReason));
}

TEST(FlashSafetyHelpers, ReleasePollingFaultsIfLineStaysHighPastTimeout)
{
    FlashSafety::State state{};
    FlashSafety::arm(state, false);
    FlashSafety::onTrigger(state);

    const auto action = FlashSafety::onReleasePoll(state, true, 20u, 20u);

    LONGS_EQUAL(static_cast<long>(FlashSafety::ReleaseAction::FaultLatched),
                static_cast<long>(action));
    CHECK_FALSE(FlashSafety::isSessionArmed(state));
    CHECK_TRUE(FlashSafety::isFaultLatched(state));
    CHECK_FALSE(state.awaitingRelease);
    STRCMP_EQUAL("line_stuck_high", FlashSafety::faultReasonToken(state.faultReason));
}

TEST(FlashSafetyHelpers, StopClearsFaultAndReturnsToDisarmedState)
{
    FlashSafety::State state{};
    FlashSafety::arm(state, true);

    FlashSafety::clear(state);

    CHECK_FALSE(FlashSafety::isSessionArmed(state));
    CHECK_FALSE(FlashSafety::isFaultLatched(state));
    CHECK_FALSE(state.awaitingRelease);
    STRCMP_EQUAL("none", FlashSafety::faultReasonToken(state.faultReason));
}
