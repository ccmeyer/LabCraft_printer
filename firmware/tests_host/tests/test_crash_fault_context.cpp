#include "CppUTest/TestHarness.h"

#include <cstring>

extern "C" {
#include "CrashFaultContext.h"
}

TEST_GROUP(CrashFaultContext)
{
};

TEST(CrashFaultContext, V2WirePackingMatchesGoldenLittleEndianVector)
{
    CrashFaultContextV2 context{};
    context.version = 2u;
    context.faultKind = 1u;
    context.taskId = 2u;
    context.activeCommand = 3u;
    context.flags = 0x0504u;
    uint8_t* header = &context.homePhaseX;
    for (uint8_t i = 0u; i < 14u; ++i) {
        header[i] = static_cast<uint8_t>(6u + i);
    }
    uint32_t* values = &context.excReturn;
    for (uint32_t i = 0u; i < 28u; ++i) {
        const uint32_t byte = 20u + (i * 4u);
        values[i] = byte | ((byte + 1u) << 8) | ((byte + 2u) << 16) | ((byte + 3u) << 24);
    }

    uint8_t actual[CRASH_FAULT_CONTEXT_WIRE_SIZE]{};
    uint8_t expected[CRASH_FAULT_CONTEXT_WIRE_SIZE]{};
    for (uint32_t i = 0u; i < CRASH_FAULT_CONTEXT_WIRE_SIZE; ++i) {
        expected[i] = static_cast<uint8_t>(i);
    }
    expected[0] = 2u;

    CHECK_TRUE(CrashFaultContext_Pack(&context, actual, sizeof(actual)) != 0u);
    MEMCMP_EQUAL(expected, actual, sizeof(expected));
}

TEST(CrashFaultContext, BasicAndExtendedFramesBothStartAtRawSp)
{
    uint32_t frame = 0u;
    uint32_t words = 0u;
    CHECK_TRUE(CrashFaultContext_SelectCoreFrame(0x20000100u, 0xFFFFFFFDu,
                                                 0x20000000u, 0x20001000u,
                                                 &frame, &words) != 0u);
    UNSIGNED_LONGS_EQUAL(0x20000100u, frame);
    UNSIGNED_LONGS_EQUAL(8u, words);

    CHECK_TRUE(CrashFaultContext_SelectCoreFrame(0x20000100u, 0xFFFFFFEDu,
                                                 0x20000000u, 0x20001000u,
                                                 &frame, &words) != 0u);
    UNSIGNED_LONGS_EQUAL(0x20000100u, frame);
    UNSIGNED_LONGS_EQUAL(26u, words);
}

TEST(CrashFaultContext, ValidatesTheCompleteBasicOrExtendedAllocation)
{
    CHECK_TRUE(CrashFaultContext_SelectCoreFrame(0x20000FE0u, 0xFFFFFFFDu,
                                                 0x20000000u, 0x20001000u,
                                                 nullptr, nullptr) != 0u);
    CHECK_FALSE(CrashFaultContext_SelectCoreFrame(0x20000FE4u, 0xFFFFFFFDu,
                                                  0x20000000u, 0x20001000u,
                                                  nullptr, nullptr) != 0u);
    CHECK_TRUE(CrashFaultContext_SelectCoreFrame(0x20000F98u, 0xFFFFFFEDu,
                                                 0x20000000u, 0x20001000u,
                                                 nullptr, nullptr) != 0u);
    CHECK_FALSE(CrashFaultContext_SelectCoreFrame(0x20000F9Cu, 0xFFFFFFEDu,
                                                  0x20000000u, 0x20001000u,
                                                  nullptr, nullptr) != 0u);
}

TEST(CrashFaultContext, RejectsMisalignedAndOutOfRangeStackPointers)
{
    CHECK_FALSE(CrashFaultContext_SelectCoreFrame(0x20000102u, 0xFFFFFFFDu,
                                                  0x20000000u, 0x20001000u,
                                                  nullptr, nullptr) != 0u);
    CHECK_FALSE(CrashFaultContext_SelectCoreFrame(0x10000100u, 0xFFFFFFFDu,
                                                  0x20000000u, 0x20001000u,
                                                  nullptr, nullptr) != 0u);
}

TEST(CrashFaultContext, ExecutablePcAcceptsFlashAndRamFunctionRanges)
{
    CHECK_TRUE(CrashFaultContext_IsExecutablePc(0x08001234u,
                                                0x08000000u, 0x08060000u,
                                                0x20001000u, 0x20001100u) != 0u);
    CHECK_TRUE(CrashFaultContext_IsExecutablePc(0x20001021u,
                                                0x08000000u, 0x08060000u,
                                                0x20001000u, 0x20001100u) != 0u);
    CHECK_FALSE(CrashFaultContext_IsExecutablePc(0x05000000u,
                                                 0x08000000u, 0x08060000u,
                                                 0x20001000u, 0x20001100u) != 0u);
}

TEST(CrashFaultContext, ThumbStateRequiresTheStackedTBit)
{
    CHECK_TRUE(CrashFaultContext_HasThumbState(0x21000000u) != 0u);
    CHECK_FALSE(CrashFaultContext_HasThumbState(0x20000000u) != 0u);
}

TEST(CrashFaultContext, HomeCheckpointWireValuesRemainStable)
{
    UNSIGNED_LONGS_EQUAL(0u, CRASH_HOME_CHECKPOINT_IDLE);
    UNSIGNED_LONGS_EQUAL(1u, CRASH_HOME_CHECKPOINT_PHASE_ENTRY);
    UNSIGNED_LONGS_EQUAL(2u, CRASH_HOME_CHECKPOINT_BEFORE_EVENT_CLEAR);
    UNSIGNED_LONGS_EQUAL(3u, CRASH_HOME_CHECKPOINT_BEFORE_MOVE);
    UNSIGNED_LONGS_EQUAL(4u, CRASH_HOME_CHECKPOINT_WAITING_FOR_MOVE);
    UNSIGNED_LONGS_EQUAL(5u, CRASH_HOME_CHECKPOINT_AFTER_MOVE);
    UNSIGNED_LONGS_EQUAL(6u, CRASH_HOME_CHECKPOINT_BEFORE_LIMIT_SAMPLE);
    UNSIGNED_LONGS_EQUAL(7u, CRASH_HOME_CHECKPOINT_AFTER_LIMIT_SAMPLE);
    UNSIGNED_LONGS_EQUAL(8u, CRASH_HOME_CHECKPOINT_FINISHING);
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
