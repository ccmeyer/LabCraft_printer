#include "CppUTest/TestHarness.h"
#include "OrchestratorDecode.h"

TEST_GROUP(OrchestratorDecode)
{
};

TEST(OrchestratorDecode, SetAxisMaxSpeedMapsToIntent) {
    const auto intent = OrchestratorDecode::decodeIntent({0x40u, 0x02u, 25000u, 0u});
    LONGS_EQUAL((int)OrchestratorDecode::Action::SetAxisMaxSpeed, (int)intent.action);
    UNSIGNED_LONGS_EQUAL(0x02u, intent.axis);
    UNSIGNED_LONGS_EQUAL(25000u, intent.value);
    UNSIGNED_LONGS_EQUAL(0u, intent.waitMs);
}

TEST(OrchestratorDecode, WaitUsesP1AsMilliseconds) {
    const auto intent = OrchestratorDecode::decodeIntent({0x50u, 125u, 0u, 0u});
    LONGS_EQUAL((int)OrchestratorDecode::Action::Wait, (int)intent.action);
    UNSIGNED_LONGS_EQUAL(125u, intent.waitMs);
}

TEST(OrchestratorDecode, UnknownOpcodeFallsBackToNoOp) {
    const auto intent = OrchestratorDecode::decodeIntent({0xFFu, 1u, 2u, 3u});
    LONGS_EQUAL((int)OrchestratorDecode::Action::NoOp, (int)intent.action);
    UNSIGNED_LONGS_EQUAL(0u, intent.axis);
    UNSIGNED_LONGS_EQUAL(0u, intent.value);
    UNSIGNED_LONGS_EQUAL(0u, intent.waitMs);
}
