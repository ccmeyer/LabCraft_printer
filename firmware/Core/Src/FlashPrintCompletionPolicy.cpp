#include "FlashPrintCompletionPolicy.h"

namespace FlashPrintCompletionPolicy {

namespace {

uint32_t clampBaseTimeout(uint64_t value) {
  if (value < MIN_BASE_TIMEOUT_MS) {
    return MIN_BASE_TIMEOUT_MS;
  }
  if (value > MAX_BASE_TIMEOUT_MS) {
    return MAX_BASE_TIMEOUT_MS;
  }
  return static_cast<uint32_t>(value);
}

}  // namespace

uint32_t timeoutMs(uint16_t droplets,
                   uint16_t rateHz,
                   uint32_t startupDelayBudgetMs) {
  const uint32_t safeRateHz = (rateHz == 0u) ? 1u : static_cast<uint32_t>(rateHz);
  const uint64_t pulseMs =
      ((static_cast<uint64_t>(droplets) * 1000ULL) + safeRateHz - 1ULL) /
      safeRateHz;
  const uint32_t baseTimeout = clampBaseTimeout(pulseMs + GRACE_MS);
  const uint64_t total =
      static_cast<uint64_t>(baseTimeout) + startupDelayBudgetMs;
  return (total > 0xFFFFFFFFULL)
      ? 0xFFFFFFFFu
      : static_cast<uint32_t>(total);
}

}  // namespace FlashPrintCompletionPolicy
