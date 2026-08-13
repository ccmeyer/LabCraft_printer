#ifndef INC_SELFTESTSCHEDULINGPOLICY_H_
#define INC_SELFTESTSCHEDULINGPOLICY_H_

#include "PressureSensorWatchdogTelemetry.h"

#include <cstddef>
#include <cstdint>

enum class SelfTestResultSchedulingMode : uint8_t {
  NoYield = 0,
  Cooperative = 1
};

static constexpr uint32_t SELFTEST_COOPERATIVE_EMISSION_PRIORITY = 1u;
static constexpr uint32_t SELFTEST_NO_YIELD_TX_TIMEOUT_MS = 25u;
static constexpr uint32_t SELFTEST_COOPERATIVE_TX_TIMEOUT_MS = 50u;

struct SelfTestSchedulingState {
  SelfTestResultSchedulingMode mode = SelfTestResultSchedulingMode::Cooperative;
  uint32_t resultFrameCount = 0u;
  uint32_t cooperativeDelayCount = 0u;
  uint32_t maxTransmitMs = 0u;
  uint32_t totalTransmitMs = 0u;
  bool saturated = false;
};

void SelfTestScheduling_Init(SelfTestSchedulingState& state,
                             SelfTestResultSchedulingMode mode);
void SelfTestScheduling_RecordTransmit(SelfTestSchedulingState& state,
                                       uint32_t elapsedMs);
void SelfTestScheduling_RecordDelay(SelfTestSchedulingState& state);
bool SelfTestScheduling_ShouldDelay(const SelfTestSchedulingState& state);
uint32_t SelfTestScheduling_SelectEmissionPriority(
    SelfTestResultSchedulingMode mode,
    uint32_t currentPriority);
uint32_t SelfTestScheduling_SelectTransmitTimeoutMs(
    SelfTestResultSchedulingMode mode);

bool BuildSelfTestSchedulerResult(const SelfTestSchedulingState& state,
                                  const PressureSensorWatchdogSnapshot& pressure,
                                  uint32_t pressureWatchdogAgeMs,
                                  char* metrics,
                                  size_t metricsLen);

bool BuildPressureSensorWatchdogContextResult(bool contextExpected,
                                              bool contextValid,
                                              const PressureSensorWatchdogResetContext& context,
                                              char* metrics,
                                              size_t metricsLen);

#endif /* INC_SELFTESTSCHEDULINGPOLICY_H_ */
