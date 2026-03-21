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

TEST(FlashSafetyHelpers, RetriggerWhileAwaitingReleaseIsIgnoredAndSessionStaysArmed)
{
    FlashSafety::State state{};
    FlashSafety::arm(state, false);
    FlashSafety::onTrigger(state);

    const auto action = FlashSafety::onTrigger(state);

    LONGS_EQUAL(static_cast<long>(FlashSafety::TriggerAction::IgnoredBusy),
                static_cast<long>(action));
    CHECK_TRUE(FlashSafety::isSessionArmed(state));
    CHECK_FALSE(FlashSafety::isFaultLatched(state));
    CHECK_TRUE(state.awaitingRelease);
    STRCMP_EQUAL("none", FlashSafety::faultReasonToken(state.faultReason));
}

TEST(FlashSafetyHelpers, ReleasePollingKeepsWaitingIfLineStaysHigh)
{
    FlashSafety::State state{};
    FlashSafety::arm(state, false);
    FlashSafety::onTrigger(state);

    const auto action = FlashSafety::onReleasePoll(state, true);

    LONGS_EQUAL(static_cast<long>(FlashSafety::ReleaseAction::WaitingForLow),
                static_cast<long>(action));
    CHECK_TRUE(FlashSafety::isSessionArmed(state));
    CHECK_FALSE(FlashSafety::isFaultLatched(state));
    CHECK_TRUE(state.awaitingRelease);
    STRCMP_EQUAL("none", FlashSafety::faultReasonToken(state.faultReason));
}

TEST(FlashSafetyHelpers, ReleasePollingClearsBusyStateWhenLineReturnsLow)
{
    FlashSafety::State state{};
    FlashSafety::arm(state, false);
    FlashSafety::onTrigger(state);

    const auto action = FlashSafety::onReleasePoll(state, false);

    LONGS_EQUAL(static_cast<long>(FlashSafety::ReleaseAction::Released),
                static_cast<long>(action));
    CHECK_TRUE(FlashSafety::isSessionArmed(state));
    CHECK_FALSE(FlashSafety::isFaultLatched(state));
    CHECK_FALSE(state.awaitingRelease);
    STRCMP_EQUAL("none", FlashSafety::faultReasonToken(state.faultReason));
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
