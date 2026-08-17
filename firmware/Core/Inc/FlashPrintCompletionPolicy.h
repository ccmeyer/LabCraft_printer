#ifndef FLASH_PRINT_COMPLETION_POLICY_H
#define FLASH_PRINT_COMPLETION_POLICY_H

#include <cstdint>

namespace FlashPrintCompletionPolicy {

constexpr uint32_t GRACE_MS = 1000u;
constexpr uint32_t MIN_BASE_TIMEOUT_MS = 1000u;
constexpr uint32_t MAX_BASE_TIMEOUT_MS = 30000u;

uint32_t timeoutMs(uint16_t droplets,
                   uint16_t rateHz,
                   uint32_t startupDelayBudgetMs);

}  // namespace FlashPrintCompletionPolicy

#endif  // FLASH_PRINT_COMPLETION_POLICY_H
