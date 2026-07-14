#include "CppUTest/TestHarness.h"

#include <cstring>

extern "C" {
#include "CrashFaultContext.h"
}

TEST_GROUP(CrashFaultContext)
{
};

TEST(CrashFaultContext, WirePackingMatchesGoldenLittleEndianVector)
{
    CrashFaultContextV1 context{};
    context.version = 1u;
    context.flags = 2u;
    context.faultKind = 3u;
    context.taskId = 4u;
    context.activeCommand = 5u;
    context.homePhaseX = 6u;
    context.homePhaseY = 7u;
    context.homePhaseZ = 8u;
    context.homePhaseP = 9u;
    context.homePhaseR = 10u;
    context.ipsr = 0x0B0Au;
    uint32_t* values = &context.excReturn;
    for (uint32_t i = 0u; i < 25u; ++i) {
        const uint32_t byte = 12u + (i * 4u);
        values[i] = byte | ((byte + 1u) << 8) | ((byte + 2u) << 16) | ((byte + 3u) << 24);
    }

    uint8_t actual[CRASH_FAULT_CONTEXT_WIRE_SIZE]{};
    uint8_t expected[CRASH_FAULT_CONTEXT_WIRE_SIZE]{};
    for (uint32_t i = 0u; i < CRASH_FAULT_CONTEXT_WIRE_SIZE; ++i) {
        expected[i] = static_cast<uint8_t>(i);
    }
    expected[0] = 1u;
    for (uint32_t i = 1u; i < 10u; ++i) {
        expected[i] = static_cast<uint8_t>(i + 1u);
    }

    CHECK_TRUE(CrashFaultContext_Pack(&context, actual, sizeof(actual)) != 0u);
    MEMCMP_EQUAL(expected, actual, sizeof(expected));
}

TEST(CrashFaultContext, SelectsBasicAndExtendedFloatingPointCoreFrames)
{
    uint32_t frame = 0u;
    CHECK_TRUE(CrashFaultContext_SelectCoreFrame(0x20000100u, 0xFFFFFFFDu,
                                                 0x20000000u, 0x20001000u, &frame) != 0u);
    UNSIGNED_LONGS_EQUAL(0x20000100u, frame);

    CHECK_TRUE(CrashFaultContext_SelectCoreFrame(0x20000100u, 0xFFFFFFEDu,
                                                 0x20000000u, 0x20001000u, &frame) != 0u);
    UNSIGNED_LONGS_EQUAL(0x20000148u, frame);
}

TEST(CrashFaultContext, RejectsMisalignedAndOutOfRangeStackPointers)
{
    uint32_t frame = 0u;
    CHECK_FALSE(CrashFaultContext_SelectCoreFrame(0x20000102u, 0xFFFFFFFDu,
                                                  0x20000000u, 0x20001000u, &frame) != 0u);
    CHECK_FALSE(CrashFaultContext_SelectCoreFrame(0x10000100u, 0xFFFFFFFDu,
                                                  0x20000000u, 0x20001000u, &frame) != 0u);
    CHECK_FALSE(CrashFaultContext_SelectCoreFrame(0x20000FF0u, 0xFFFFFFFDu,
                                                  0x20000000u, 0x20001000u, &frame) != 0u);
}

TEST(CrashFaultContext, MatchesStackRangeAndReturnsBounds)
{
    const CrashFaultStackRange ranges[] = {
        {7u, 0x20001000u, 0x20001400u},
        {8u, 0x20001400u, 0x20001800u},
    };
    uint32_t low = 0u;
    uint32_t high = 0u;
    UNSIGNED_LONGS_EQUAL(8u, CrashFaultContext_MatchStack(
        0x200017FCu, ranges, 2u, &low, &high));
    UNSIGNED_LONGS_EQUAL(0x20001400u, low);
    UNSIGNED_LONGS_EQUAL(0x20001800u, high);
    UNSIGNED_LONGS_EQUAL(0u, CrashFaultContext_MatchStack(
        0x20001800u, ranges, 2u, &low, &high));
}

TEST(CrashFaultContext, RetainedValidationRejectsChecksumFailureAndPartialWrite)
{
    CrashFaultContextRetained retained{};
    retained.version = CRASH_FAULT_CONTEXT_VERSION;
    retained.size = sizeof(retained);
    retained.context.version = CRASH_FAULT_CONTEXT_VERSION;
    retained.context.pc = 0x08001234u;
    retained.checksum = CrashFaultContext_Checksum(&retained.context);

    retained.magic = 0u;
    CHECK_FALSE(CrashFaultContext_ValidateRetained(&retained, nullptr) != 0u);
    retained.magic = CRASH_FAULT_CONTEXT_RETAINED_MAGIC;
    CHECK_TRUE(CrashFaultContext_ValidateRetained(&retained, nullptr) != 0u);
    retained.context.pc ^= 1u;
    CHECK_FALSE(CrashFaultContext_ValidateRetained(&retained, nullptr) != 0u);
}

TEST(CrashFaultContext, RetainedValidationRejectsUnknownVersion)
{
    CrashFaultContextRetained retained{};
    retained.magic = CRASH_FAULT_CONTEXT_RETAINED_MAGIC;
    retained.version = CRASH_FAULT_CONTEXT_VERSION + 1u;
    retained.size = sizeof(retained);
    retained.context.version = CRASH_FAULT_CONTEXT_VERSION;
    retained.checksum = CrashFaultContext_Checksum(&retained.context);
    CHECK_FALSE(CrashFaultContext_ValidateRetained(&retained, nullptr) != 0u);
}
