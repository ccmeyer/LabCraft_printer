#include "CppUTest/TestHarness.h"

#include "WatchdogParticipationPolicy.h"

TEST_GROUP(WatchdogParticipationPolicy)
{
};

TEST(WatchdogParticipationPolicy, EnableAndDisablePreserveUnrelatedParticipants)
{
    constexpr uint32_t boot = 1u << 1;
    constexpr uint32_t pressure = 1u << 2;
    constexpr uint32_t status = 1u << 3;

    uint32_t mask = WatchdogParticipation_Enable(boot, pressure);
    mask = WatchdogParticipation_Enable(mask, status);
    mask = WatchdogParticipation_Disable(mask, pressure);

    UNSIGNED_LONGS_EQUAL(boot | status, mask);
}

TEST(WatchdogParticipationPolicy, RepeatedTransitionsAreIdempotent)
{
    constexpr uint32_t orchestrator = 1u << 4;

    uint32_t mask = WatchdogParticipation_Enable(0u, orchestrator);
    mask = WatchdogParticipation_Enable(mask, orchestrator);
    UNSIGNED_LONGS_EQUAL(orchestrator, mask);

    mask = WatchdogParticipation_Disable(mask, orchestrator);
    mask = WatchdogParticipation_Disable(mask, orchestrator);
    UNSIGNED_LONGS_EQUAL(0u, mask);
}
