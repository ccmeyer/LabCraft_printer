#include "CppUTest/TestHarness.h"
#include "PrinterCompletionBits.h"

namespace {

bool isSingleBit(uint32_t value) {
    return value != 0u && (value & (value - 1u)) == 0u;
}

} // namespace

TEST_GROUP(PrinterCompletionBitsTests)
{
};

TEST(PrinterCompletionBitsTests, HostAndFlashCompletionBitsAreDistinctSingleBits) {
    CHECK_TRUE(isSingleBit(PRINTER_COMPLETION_HOST_DONE_BIT));
    CHECK_TRUE(isSingleBit(PRINTER_COMPLETION_FLASH_DONE_BIT));
    CHECK_FALSE(PRINTER_COMPLETION_HOST_DONE_BIT == PRINTER_COMPLETION_FLASH_DONE_BIT);
}

TEST(PrinterCompletionBitsTests, HostCompletionBitPreservesLegacyPrintingDoneSlot) {
    UNSIGNED_LONGS_EQUAL(1u << 6, PRINTER_COMPLETION_HOST_DONE_BIT);
}

TEST(PrinterCompletionBitsTests, FlashCompletionBitUsesDedicatedHighOrderSlot) {
    UNSIGNED_LONGS_EQUAL(1u << 16, PRINTER_COMPLETION_FLASH_DONE_BIT);
}

TEST(PrinterCompletionBitsTests, RecoverableNoAckResultsAreClassified) {
    CHECK_FALSE(printerDispenseResultIsRecoverableNoAck(PrinterDispenseResult::Idle));
    CHECK_FALSE(printerDispenseResultIsRecoverableNoAck(PrinterDispenseResult::Completed));
    CHECK_TRUE(printerDispenseResultIsRecoverableNoAck(PrinterDispenseResult::Cancelled));
    CHECK_TRUE(printerDispenseResultIsRecoverableNoAck(PrinterDispenseResult::GateTimeout));
    CHECK_TRUE(printerDispenseResultIsRecoverableNoAck(PrinterDispenseResult::FlashScheduleFailed));
}

TEST(PrinterCompletionBitsTests, OnlyCompletedDispenseCanClaimDeferredRefresh) {
    CHECK_FALSE(printerDispenseResultCanClaimDeferredRefresh(PrinterDispenseResult::Idle));
    CHECK_TRUE(printerDispenseResultCanClaimDeferredRefresh(PrinterDispenseResult::Completed));
    CHECK_FALSE(printerDispenseResultCanClaimDeferredRefresh(PrinterDispenseResult::Cancelled));
    CHECK_FALSE(printerDispenseResultCanClaimDeferredRefresh(PrinterDispenseResult::GateTimeout));
    CHECK_FALSE(printerDispenseResultCanClaimDeferredRefresh(PrinterDispenseResult::FlashScheduleFailed));
}
