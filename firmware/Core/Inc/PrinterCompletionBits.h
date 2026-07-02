#ifndef INC_PRINTERCOMPLETIONBITS_H_
#define INC_PRINTERCOMPLETIONBITS_H_

#include <cstdint>

static constexpr uint32_t PRINTER_COMPLETION_HOST_DONE_BIT = (1u << 6);
static constexpr uint32_t PRINTER_COMPLETION_FLASH_DONE_BIT = (1u << 16);

enum class PrinterDispenseResult : uint8_t {
  Idle = 0,
  Completed,
  Cancelled,
  GateTimeout,
  FlashScheduleFailed
};

constexpr bool printerDispenseResultIsRecoverableNoAck(PrinterDispenseResult result)
{
  return result == PrinterDispenseResult::Cancelled ||
         result == PrinterDispenseResult::GateTimeout ||
         result == PrinterDispenseResult::FlashScheduleFailed;
}

#endif // INC_PRINTERCOMPLETIONBITS_H_
