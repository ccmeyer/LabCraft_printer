#include "SelfTestSchedulingPolicy.h"

#include <climits>
#include <cstdio>

namespace {

void incrementSaturating(uint32_t& value, bool& saturated)
{
  if (value == UINT32_MAX) {
    saturated = true;
    return;
  }
  ++value;
}

} // namespace

void SelfTestScheduling_Init(SelfTestSchedulingState& state,
                             SelfTestResultSchedulingMode mode)
{
  state = SelfTestSchedulingState{};
  state.mode = mode;
}

void SelfTestScheduling_RecordTransmit(SelfTestSchedulingState& state,
                                       uint32_t elapsedMs)
{
  incrementSaturating(state.resultFrameCount, state.saturated);
  if (elapsedMs > state.maxTransmitMs) state.maxTransmitMs = elapsedMs;
  if (UINT32_MAX - state.totalTransmitMs < elapsedMs) {
    state.totalTransmitMs = UINT32_MAX;
    state.saturated = true;
  } else {
    state.totalTransmitMs += elapsedMs;
  }
}

void SelfTestScheduling_RecordDelay(SelfTestSchedulingState& state)
{
  incrementSaturating(state.cooperativeDelayCount, state.saturated);
}

bool SelfTestScheduling_ShouldDelay(const SelfTestSchedulingState& state)
{
  return state.mode == SelfTestResultSchedulingMode::Cooperative;
}

bool BuildSelfTestSchedulerResult(const SelfTestSchedulingState& state,
                                  const PressureSensorWatchdogSnapshot& pressure,
                                  uint32_t pressureWatchdogAgeMs,
                                  char* metrics,
                                  size_t metricsLen)
{
  const bool knownMode = state.mode == SelfTestResultSchedulingMode::NoYield ||
                         state.mode == SelfTestResultSchedulingMode::Cooperative;
  const bool delayCountValid = state.mode == SelfTestResultSchedulingMode::NoYield
      ? state.cooperativeDelayCount == 0u
      : state.cooperativeDelayCount == state.resultFrameCount;
  const bool saturated = state.saturated || pressure.saturated != 0u;
  const bool stackEvidenceComplete =
      pressure.stackHighWaterWords != PRESSURE_SENSOR_WDG_AGE_UNKNOWN;
  const bool i2cErrorMaskValid =
      (pressure.lastReadHalError & ~PRESSURE_SENSOR_WDG_HAL_ERROR_VALID_MASK) == 0u;
  const bool i2cDetailComplete = pressure.readFailureCount == 0u
      ? pressure.lastReadHalStatus == 0u && pressure.lastReadHalError == 0u
      : pressure.lastReadHalStatus >= 1u && pressure.lastReadHalStatus <= 3u &&
            i2cErrorMaskValid;
  const bool pass = knownMode && delayCountValid && pressure.valid != 0u &&
                    stackEvidenceComplete && i2cDetailComplete && !saturated;
  if (metrics != nullptr && metricsLen > 0u) {
    std::snprintf(metrics,
                  metricsLen,
                  "sm=%u;rf=%lu;yc=%lu;txm=%lu;txt=%lu;pg=%lu;pa=%lu;ph=%u;pha=%lu;la=%lu;se=%lu;re=%lu;bc=%lu;h=%u;r=%lu;x=%lu;e=%lu;hw=%lu;sf=%u",
                  static_cast<unsigned>(state.mode),
                  static_cast<unsigned long>(state.resultFrameCount),
                  static_cast<unsigned long>(state.cooperativeDelayCount),
                  static_cast<unsigned long>(state.maxTransmitMs),
                  static_cast<unsigned long>(state.totalTransmitMs),
                  static_cast<unsigned long>(pressure.maxCheckInGapMs),
                  static_cast<unsigned long>(pressureWatchdogAgeMs),
                  static_cast<unsigned>(pressure.phase),
                  static_cast<unsigned long>(pressure.phaseAgeMs),
                  static_cast<unsigned long>(pressure.lastLoopAgeMs),
                  static_cast<unsigned long>(pressure.selectFailureCount),
                  static_cast<unsigned long>(pressure.readFailureCount),
                  static_cast<unsigned long>(pressure.recoveryCount),
                  static_cast<unsigned>(pressure.lastReadHalStatus),
                  static_cast<unsigned long>(pressure.lastFailedReadDurationMs),
                  static_cast<unsigned long>(pressure.readRecoveryDurationMs),
                  static_cast<unsigned long>(pressure.lastReadHalError),
                  static_cast<unsigned long>(pressure.stackHighWaterWords),
                  saturated || pressure.valid == 0u || !stackEvidenceComplete ||
                      !i2cDetailComplete ? 1u : 0u);
  }
  return pass;
}

bool BuildPressureSensorWatchdogContextResult(bool contextExpected,
                                              bool contextValid,
                                              const PressureSensorWatchdogResetContext& context,
                                              char* metrics,
                                              size_t metricsLen)
{
  const bool stackEvidenceComplete =
      !contextValid || context.stackHighWaterWords != PRESSURE_SENSOR_WDG_AGE_UNKNOWN;
  const bool i2cErrorMaskValid =
      (context.lastReadHalError & ~PRESSURE_SENSOR_WDG_HAL_ERROR_VALID_MASK) == 0u;
  const bool i2cDetailComplete = !contextValid || (context.readFailureCount == 0u
      ? context.lastReadHalStatus == 0u && context.lastReadHalError == 0u
      : context.lastReadHalStatus >= 1u && context.lastReadHalStatus <= 3u &&
            i2cErrorMaskValid);
  const bool pass = (!contextExpected || contextValid) && stackEvidenceComplete &&
                    i2cDetailComplete && (!contextValid || context.saturated == 0u);
  if (metrics != nullptr && metricsLen > 0u) {
    std::snprintf(metrics,
                  metricsLen,
                  "v=%u;ex=%u;pa=%lu;ph=%u;pha=%lu;la=%lu;pg=%lu;se=%lu;re=%lu;bc=%lu;lp=%lu;h=%u;r=%lu;x=%lu;e=%lu;hw=%lu;tk=%lu;sf=%u",
                  contextValid ? 1u : 0u,
                  contextExpected ? 1u : 0u,
                  static_cast<unsigned long>(context.watchdogAgeMs),
                  static_cast<unsigned>(context.phase),
                  static_cast<unsigned long>(context.phaseAgeMs),
                  static_cast<unsigned long>(context.lastLoopAgeMs),
                  static_cast<unsigned long>(context.maxCheckInGapMs),
                  static_cast<unsigned long>(context.selectFailureCount),
                  static_cast<unsigned long>(context.readFailureCount),
                  static_cast<unsigned long>(context.recoveryCount),
                  static_cast<unsigned long>(context.loopCount),
                  static_cast<unsigned>(context.lastReadHalStatus),
                  static_cast<unsigned long>(context.lastFailedReadDurationMs),
                  static_cast<unsigned long>(context.readRecoveryDurationMs),
                  static_cast<unsigned long>(context.lastReadHalError),
                  static_cast<unsigned long>(context.stackHighWaterWords),
                  static_cast<unsigned long>(context.snapshotTickMs),
                  contextValid &&
                      (context.saturated != 0u || !stackEvidenceComplete ||
                       !i2cDetailComplete) ? 1u : 0u);
  }
  return pass;
}
