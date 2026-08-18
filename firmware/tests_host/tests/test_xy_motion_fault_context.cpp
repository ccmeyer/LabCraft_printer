#include "CppUTest/TestHarness.h"

#include <cstring>

extern "C" {
#include "XyMotionFaultContext.h"
}

TEST_GROUP(XyMotionFaultContext)
{
};

TEST(XyMotionFaultContext, ReasonWireValuesAndNamesRemainStable)
{
    STRCMP_EQUAL("none", XyMotionFaultContext_ReasonName(XY_MOTION_FAULT_NONE));
    STRCMP_EQUAL("start_rejected", XyMotionFaultContext_ReasonName(XY_MOTION_FAULT_START_REJECTED));
    STRCMP_EQUAL("x_limit", XyMotionFaultContext_ReasonName(XY_MOTION_FAULT_X_LIMIT));
    STRCMP_EQUAL("y_limit", XyMotionFaultContext_ReasonName(XY_MOTION_FAULT_Y_LIMIT));
    STRCMP_EQUAL("planner_fault", XyMotionFaultContext_ReasonName(XY_MOTION_FAULT_PLANNER));
    STRCMP_EQUAL("endpoint_mismatch", XyMotionFaultContext_ReasonName(XY_MOTION_FAULT_ENDPOINT_MISMATCH));
    STRCMP_EQUAL("resume_terminal_mismatch",
                 XyMotionFaultContext_ReasonName(XY_MOTION_FAULT_RESUME_TERMINAL_MISMATCH));
    STRCMP_EQUAL("unknown", XyMotionFaultContext_ReasonName(0xFFu));
}

TEST(XyMotionFaultContext, InitializesVersionAndClearsAllOtherFields)
{
    XyMotionFaultContext context;
    memset(&context, 0xA5, sizeof(context));

    XyMotionFaultContext_Init(&context);

    UNSIGNED_LONGS_EQUAL(XY_MOTION_FAULT_CONTEXT_VERSION, context.version);
    UNSIGNED_LONGS_EQUAL(0u, context.valid);
    UNSIGNED_LONGS_EQUAL(0u, context.commandSeq32);
    LONGS_EQUAL(0, context.startX);
    UNSIGNED_LONGS_EQUAL(0u, context.doneBits);
}

TEST(XyMotionFaultContext, WirePackingMatchesGoldenLittleEndianVector)
{
    XyMotionFaultContext context{};
    context.version = 1u;
    context.valid = 2u;
    context.reason = 3u;
    context.startStatus = 4u;
    context.executorState = 5u;
    context.terminalReason = 6u;
    context.flags = 7u;
    context.reserved = 8u;
    context.commandSeq32 = 0x0C0B0A09u;
    context.captureUptimeMs = 0x100F0E0Du;
    context.startX = static_cast<int32_t>(0x14131211u);
    context.startY = static_cast<int32_t>(0x18171615u);
    context.targetX = static_cast<int32_t>(0x1C1B1A19u);
    context.targetY = static_cast<int32_t>(0x201F1E1Du);
    context.endX = static_cast<int32_t>(0x24232221u);
    context.endY = static_cast<int32_t>(0x28272625u);
    context.requestedXEdges = 0x2C2B2A29u;
    context.requestedYEdges = 0x302F2E2Du;
    context.emittedXEdges = 0x34333231u;
    context.emittedYEdges = 0x38373635u;
    context.doneBits = 0x3C3B3A39u;

    uint8_t actual[XY_MOTION_FAULT_CONTEXT_WIRE_SIZE]{};
    uint8_t expected[XY_MOTION_FAULT_CONTEXT_WIRE_SIZE]{};
    for (uint32_t i = 0u; i < sizeof(expected); ++i) {
        expected[i] = static_cast<uint8_t>(i + 1u);
    }

    CHECK_TRUE(XyMotionFaultContext_Pack(&context, actual, sizeof(actual)) != 0u);
    MEMCMP_EQUAL(expected, actual, sizeof(expected));
}

TEST(XyMotionFaultContext, WireRoundTripPreservesSignedPositions)
{
    XyMotionFaultContext expected{};
    XyMotionFaultContext_Init(&expected);
    expected.valid = 1u;
    expected.reason = XY_MOTION_FAULT_ENDPOINT_MISMATCH;
    expected.startX = -123456;
    expected.startY = 654321;
    expected.targetX = -1;
    expected.targetY = INT32_MIN;
    expected.endX = INT32_MAX;
    expected.endY = -42;
    expected.doneBits = 3u;
    uint8_t payload[XY_MOTION_FAULT_CONTEXT_WIRE_SIZE]{};
    XyMotionFaultContext actual{};

    CHECK_TRUE(XyMotionFaultContext_Pack(&expected, payload, sizeof(payload)) != 0u);
    CHECK_TRUE(XyMotionFaultContext_Unpack(&actual, payload, sizeof(payload)) != 0u);
    MEMCMP_EQUAL(&expected, &actual, sizeof(expected));
}

TEST(XyMotionFaultContext, RejectsWrongWireLengths)
{
    XyMotionFaultContext context{};
    uint8_t payload[XY_MOTION_FAULT_CONTEXT_WIRE_SIZE]{};

    CHECK_FALSE(XyMotionFaultContext_Pack(&context, payload, sizeof(payload) - 1u) != 0u);
    CHECK_FALSE(XyMotionFaultContext_Unpack(&context, payload, sizeof(payload) - 1u) != 0u);
    CHECK_FALSE(XyMotionFaultContext_Unpack(&context, payload, sizeof(payload) + 1u) != 0u);
}

TEST(XyMotionFaultContext, RetainedContextValidatesChecksumAndMetadata)
{
    XyMotionFaultContext context{};
    XyMotionFaultContext_Init(&context);
    context.valid = 1u;
    context.reason = XY_MOTION_FAULT_X_LIMIT;
    context.commandSeq32 = 1234u;
    XyMotionFaultRetainedContext retained{};
    XyMotionFaultContext restored{};

    XyMotionFaultContext_WriteRetained(&retained, &context);
    CHECK_TRUE(XyMotionFaultContext_ReadRetained(&retained, &restored) != 0u);
    MEMCMP_EQUAL(&context, &restored, sizeof(context));

    retained.context.commandSeq32 ^= 1u;
    CHECK_FALSE(XyMotionFaultContext_ReadRetained(&retained, &restored) != 0u);
    retained.context.commandSeq32 ^= 1u;
    retained.version += 1u;
    CHECK_FALSE(XyMotionFaultContext_ReadRetained(&retained, &restored) != 0u);
}

TEST(XyMotionFaultContext, NewFaultOverwritesOldAndClearInvalidatesIt)
{
    XyMotionFaultContext first{};
    XyMotionFaultContext second{};
    XyMotionFaultContext restored{};
    XyMotionFaultRetainedContext retained{};
    XyMotionFaultContext_Init(&first);
    XyMotionFaultContext_Init(&second);
    first.valid = 1u;
    first.reason = XY_MOTION_FAULT_X_LIMIT;
    second.valid = 1u;
    second.reason = XY_MOTION_FAULT_Y_LIMIT;

    XyMotionFaultContext_WriteRetained(&retained, &first);
    XyMotionFaultContext_WriteRetained(&retained, &second);
    CHECK_TRUE(XyMotionFaultContext_ReadRetained(&retained, &restored) != 0u);
    UNSIGNED_LONGS_EQUAL(XY_MOTION_FAULT_Y_LIMIT, restored.reason);

    XyMotionFaultContext_ClearRetained(&retained);
    CHECK_FALSE(XyMotionFaultContext_ReadRetained(&retained, &restored) != 0u);
}
