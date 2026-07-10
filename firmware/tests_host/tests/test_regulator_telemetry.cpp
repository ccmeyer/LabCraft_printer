#include "CppUTest/TestHarness.h"

#include "RegulatorTelemetry.h"

TEST_GROUP(RegulatorTelemetry)
{
};

TEST(RegulatorTelemetry, BuildFlagsPacksRuntimeAndWatchdogBits)
{
    const uint16_t flags = RegulatorTelemetry_BuildFlags(
        1u, 1u, 0u, 1u, 0u, 1u, 1u, 0u, 1u);

    CHECK_TRUE((flags & REG_TEL_FLAG_ACTIVE) != 0u);
    CHECK_TRUE((flags & REG_TEL_FLAG_HOMING) != 0u);
    CHECK_FALSE((flags & REG_TEL_FLAG_RESETTING) != 0u);
    CHECK_TRUE((flags & REG_TEL_FLAG_MOTION_HOLD) != 0u);
    CHECK_FALSE((flags & REG_TEL_FLAG_QUIET) != 0u);
    CHECK_TRUE((flags & REG_TEL_FLAG_STEPPING) != 0u);
    CHECK_TRUE((flags & REG_TEL_FLAG_WDG_INACTIVE_HOLD) != 0u);
    CHECK_FALSE((flags & REG_TEL_FLAG_WDG_MOTION_HOLD) != 0u);
    CHECK_TRUE((flags & REG_TEL_FLAG_WDG_RECOVERY_HOLD) != 0u);
}

TEST(RegulatorTelemetry, EventNamesAreStable)
{
    STRCMP_EQUAL("none", RegulatorTelemetry_EventName(REG_TEL_EVENT_NONE));
    STRCMP_EQUAL("motion_hold_enter", RegulatorTelemetry_EventName(REG_TEL_EVENT_MOTION_HOLD_ENTER));
    STRCMP_EQUAL("home_end_fail", RegulatorTelemetry_EventName(REG_TEL_EVENT_HOME_END_FAIL));
    STRCMP_EQUAL("step_limit", RegulatorTelemetry_EventName(REG_TEL_EVENT_STEP_LIMIT));
    STRCMP_EQUAL("unknown", RegulatorTelemetry_EventName(99u));
}

TEST(RegulatorTelemetry, RecoveryTriggersSurviveImmediateHomeBegin)
{
    UNSIGNED_LONGS_EQUAL(
        REG_TEL_EVENT_STEP_LIMIT,
        RegulatorTelemetry_SelectLastEvent(REG_TEL_EVENT_STEP_LIMIT, REG_TEL_EVENT_HOME_BEGIN));
    UNSIGNED_LONGS_EQUAL(
        REG_TEL_EVENT_INNER_LIMIT,
        RegulatorTelemetry_SelectLastEvent(REG_TEL_EVENT_INNER_LIMIT, REG_TEL_EVENT_HOME_BEGIN));
    UNSIGNED_LONGS_EQUAL(
        REG_TEL_EVENT_SAFETY_HOME,
        RegulatorTelemetry_SelectLastEvent(REG_TEL_EVENT_SAFETY_HOME, REG_TEL_EVENT_HOME_BEGIN));
}

TEST(RegulatorTelemetry, RecoveryCompletionOverwritesTrigger)
{
    UNSIGNED_LONGS_EQUAL(
        REG_TEL_EVENT_HOME_END_OK,
        RegulatorTelemetry_SelectLastEvent(REG_TEL_EVENT_STEP_LIMIT, REG_TEL_EVENT_HOME_END_OK));
    UNSIGNED_LONGS_EQUAL(
        REG_TEL_EVENT_HOME_END_FAIL,
        RegulatorTelemetry_SelectLastEvent(REG_TEL_EVENT_INNER_LIMIT, REG_TEL_EVENT_HOME_END_FAIL));
}

TEST(RegulatorTelemetry, CommandedHomeBeginRecordsWhenNoTriggerIsPending)
{
    UNSIGNED_LONGS_EQUAL(
        REG_TEL_EVENT_HOME_BEGIN,
        RegulatorTelemetry_SelectLastEvent(REG_TEL_EVENT_NONE, REG_TEL_EVENT_HOME_BEGIN));
    UNSIGNED_LONGS_EQUAL(
        REG_TEL_EVENT_HOME_BEGIN,
        RegulatorTelemetry_SelectLastEvent(REG_TEL_EVENT_MOTION_HOLD_EXIT, REG_TEL_EVENT_HOME_BEGIN));
}

TEST(RegulatorTelemetry, InitUsesUnknownAgeSentinels)
{
    RegulatorTelemetryResetContext context{};

    RegulatorTelemetry_InitResetContext(&context);

    UNSIGNED_LONGS_EQUAL(REG_TEL_RESET_CONTEXT_VERSION, context.version);
    UNSIGNED_LONGS_EQUAL(0u, context.valid);
    UNSIGNED_LONGS_EQUAL(REG_TEL_AGE_UNKNOWN, context.pWatchdogAgeMs);
    UNSIGNED_LONGS_EQUAL(REG_TEL_AGE_UNKNOWN, context.rWatchdogAgeMs);
    UNSIGNED_LONGS_EQUAL(REG_TEL_AGE_UNKNOWN, context.pLastEventAgeMs);
    UNSIGNED_LONGS_EQUAL(REG_TEL_AGE_UNKNOWN, context.rLastEventAgeMs);
}

TEST(RegulatorTelemetry, PackAndUnpackResetContextUsesFixedWireSize)
{
    RegulatorTelemetryResetContext context{};
    RegulatorTelemetry_InitResetContext(&context);
    context.valid = 1u;
    context.pFlags = REG_TEL_FLAG_ACTIVE | REG_TEL_FLAG_STEPPING;
    context.rFlags = REG_TEL_FLAG_HOMING;
    context.pWatchdogEnabled = 1u;
    context.rWatchdogEnabled = 0u;
    context.pWatchdogAgeMs = 123u;
    context.rWatchdogAgeMs = REG_TEL_AGE_UNKNOWN;
    context.pLastEvent = REG_TEL_EVENT_STEP_LIMIT;
    context.rLastEvent = REG_TEL_EVENT_HOME_BEGIN;
    context.pLastEventAgeMs = 456u;
    context.rLastEventAgeMs = 789u;
    context.snapshotTickMs = 1000u;

    uint8_t packed[REG_TEL_RESET_CONTEXT_WIRE_SIZE] = {0u};
    CHECK_TRUE(RegulatorTelemetry_PackResetContext(&context, packed, sizeof(packed)) != 0u);

    RegulatorTelemetryResetContext decoded{};
    CHECK_TRUE(RegulatorTelemetry_UnpackResetContext(&decoded, packed, sizeof(packed)) != 0u);

    UNSIGNED_LONGS_EQUAL(REG_TEL_RESET_CONTEXT_WIRE_SIZE, sizeof(packed));
    UNSIGNED_LONGS_EQUAL(context.version, decoded.version);
    UNSIGNED_LONGS_EQUAL(context.valid, decoded.valid);
    UNSIGNED_LONGS_EQUAL(context.pFlags, decoded.pFlags);
    UNSIGNED_LONGS_EQUAL(context.rFlags, decoded.rFlags);
    UNSIGNED_LONGS_EQUAL(context.pWatchdogEnabled, decoded.pWatchdogEnabled);
    UNSIGNED_LONGS_EQUAL(context.rWatchdogEnabled, decoded.rWatchdogEnabled);
    UNSIGNED_LONGS_EQUAL(context.pWatchdogAgeMs, decoded.pWatchdogAgeMs);
    UNSIGNED_LONGS_EQUAL(context.rWatchdogAgeMs, decoded.rWatchdogAgeMs);
    UNSIGNED_LONGS_EQUAL(context.pLastEvent, decoded.pLastEvent);
    UNSIGNED_LONGS_EQUAL(context.rLastEvent, decoded.rLastEvent);
    UNSIGNED_LONGS_EQUAL(context.pLastEventAgeMs, decoded.pLastEventAgeMs);
    UNSIGNED_LONGS_EQUAL(context.rLastEventAgeMs, decoded.rLastEventAgeMs);
    UNSIGNED_LONGS_EQUAL(context.snapshotTickMs, decoded.snapshotTickMs);
}

TEST(RegulatorTelemetry, UnpackRejectsBadLength)
{
    RegulatorTelemetryResetContext decoded{};
    const uint8_t payload[REG_TEL_RESET_CONTEXT_WIRE_SIZE - 1u] = {};

    CHECK_FALSE(RegulatorTelemetry_UnpackResetContext(&decoded, payload, sizeof(payload)) != 0u);
}

TEST(RegulatorTelemetry, RetainedContextRejectsChecksumMismatch)
{
    RegulatorTelemetryResetContext context{};
    RegulatorTelemetry_InitResetContext(&context);
    context.valid = 1u;
    context.pFlags = REG_TEL_FLAG_ACTIVE;

    RegulatorTelemetryRetainedContext retained{};
    RegulatorTelemetry_WriteRetainedContext(&retained, &context);

    RegulatorTelemetryResetContext decoded{};
    CHECK_TRUE(RegulatorTelemetry_ReadRetainedContext(&retained, &decoded) != 0u);

    retained.context.pFlags ^= REG_TEL_FLAG_STEPPING;
    CHECK_FALSE(RegulatorTelemetry_ReadRetainedContext(&retained, &decoded) != 0u);
}
