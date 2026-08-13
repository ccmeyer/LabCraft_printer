#include "CppUTest/TestHarness.h"

#include "DiagnosticResultEmitter.h"
#include "SelfTestSchedulingPolicy.h"

#include <climits>
#include <cstring>

TEST_GROUP(SelfTestSchedulingPolicy)
{
};

TEST(SelfTestSchedulingPolicy, CooperativeModeRequiresOneDelayPerFrame)
{
    SelfTestSchedulingState state{};
    SelfTestScheduling_Init(state, SelfTestResultSchedulingMode::Cooperative);
    SelfTestScheduling_RecordTransmit(state, 20u);
    CHECK_TRUE(SelfTestScheduling_ShouldDelay(state));
    SelfTestScheduling_RecordDelay(state);

    PressureSensorWatchdogSnapshot pressure{};
    pressure.valid = 1u;
    pressure.stackHighWaterWords = 100u;
    pressure.readFailureCount = 1u;
    pressure.lastReadHalStatus = 2u;
    pressure.lastReadHalError = 0x20u;
    pressure.lastFailedReadDurationMs = 1u;
    pressure.readRecoveryDurationMs = 24u;
    char metrics[208];
    CHECK_TRUE(BuildSelfTestSchedulerResult(state, pressure, 5u, metrics, sizeof(metrics)));
    CHECK_TRUE(std::strstr(metrics, "sm=1;rf=1;yc=1") != nullptr);
    CHECK_TRUE(std::strstr(metrics, ";h=2;r=1;x=24;e=32;") != nullptr);
}

TEST(SelfTestSchedulingPolicy, NoYieldModeRejectsUnexpectedDelay)
{
    SelfTestSchedulingState state{};
    SelfTestScheduling_Init(state, SelfTestResultSchedulingMode::NoYield);
    SelfTestScheduling_RecordTransmit(state, 1u);
    CHECK_FALSE(SelfTestScheduling_ShouldDelay(state));
    SelfTestScheduling_RecordDelay(state);
    PressureSensorWatchdogSnapshot pressure{};
    pressure.valid = 1u;
    pressure.stackHighWaterWords = 100u;
    CHECK_FALSE(BuildSelfTestSchedulerResult(state, pressure, 1u, nullptr, 0u));
}

TEST(SelfTestSchedulingPolicy, TransmitTotalsSaturateClosed)
{
    SelfTestSchedulingState state{};
    SelfTestScheduling_Init(state, SelfTestResultSchedulingMode::Cooperative);
    state.totalTransmitMs = UINT32_MAX - 2u;
    SelfTestScheduling_RecordTransmit(state, 3u);
    UNSIGNED_LONGS_EQUAL(UINT32_MAX, state.totalTransmitMs);
    CHECK_TRUE(state.saturated);
}

TEST(SelfTestSchedulingPolicy, PressureContextIsRequiredOnlyForPendingPressureFault)
{
    PressureSensorWatchdogResetContext context{};
    context.watchdogAgeMs = PRESSURE_SENSOR_WDG_AGE_UNKNOWN;
    char metrics[208];
    CHECK_TRUE(BuildPressureSensorWatchdogContextResult(false, false, context,
                                                        metrics, sizeof(metrics)));
    CHECK_FALSE(BuildPressureSensorWatchdogContextResult(true, false, context,
                                                         metrics, sizeof(metrics)));
    context.valid = 1u;
    context.watchdogAgeMs = 300u;
    context.stackHighWaterWords = 100u;
    context.readFailureCount = 1u;
    context.lastReadHalStatus = 3u;
    context.lastReadHalError = 4u;
    context.lastFailedReadDurationMs = 20u;
    context.readRecoveryDurationMs = 270u;
    CHECK_TRUE(BuildPressureSensorWatchdogContextResult(true, true, context,
                                                        metrics, sizeof(metrics)));
    CHECK_TRUE(std::strstr(metrics, ";h=3;r=20;x=270;e=4;") != nullptr);
}

TEST(SelfTestSchedulingPolicy, UnknownStackHeadroomFailsEvidenceClosed)
{
    SelfTestSchedulingState state{};
    SelfTestScheduling_Init(state, SelfTestResultSchedulingMode::Cooperative);
    PressureSensorWatchdogSnapshot pressure{};
    pressure.valid = 1u;
    pressure.stackHighWaterWords = PRESSURE_SENSOR_WDG_AGE_UNKNOWN;
    char metrics[208];
    CHECK_FALSE(BuildSelfTestSchedulerResult(state, pressure, 5u, metrics, sizeof(metrics)));
    CHECK_TRUE(std::strstr(metrics, "sf=1") != nullptr);

    PressureSensorWatchdogResetContext context{};
    context.valid = 1u;
    context.stackHighWaterWords = PRESSURE_SENSOR_WDG_AGE_UNKNOWN;
    CHECK_FALSE(BuildPressureSensorWatchdogContextResult(true, true, context,
                                                         metrics, sizeof(metrics)));
}

TEST(SelfTestSchedulingPolicy, InvalidHalFailureDetailFailsEvidenceClosed)
{
    SelfTestSchedulingState state{};
    SelfTestScheduling_Init(state, SelfTestResultSchedulingMode::Cooperative);
    PressureSensorWatchdogSnapshot pressure{};
    pressure.valid = 1u;
    pressure.stackHighWaterWords = 100u;
    pressure.readFailureCount = 1u;
    pressure.lastReadHalStatus = 0u;
    char metrics[208];
    CHECK_FALSE(BuildSelfTestSchedulerResult(state, pressure, 5u, metrics, sizeof(metrics)));
    CHECK_TRUE(std::strstr(metrics, "sf=1") != nullptr);
}

TEST(SelfTestSchedulingPolicy, UnknownHalErrorBitsFailEvidenceClosed)
{
    SelfTestSchedulingState state{};
    SelfTestScheduling_Init(state, SelfTestResultSchedulingMode::Cooperative);
    PressureSensorWatchdogSnapshot pressure{};
    pressure.valid = 1u;
    pressure.stackHighWaterWords = 100u;
    pressure.readFailureCount = 1u;
    pressure.lastReadHalStatus = 1u;
    pressure.lastReadHalError = PRESSURE_SENSOR_WDG_HAL_ERROR_VALID_MASK + 1u;
    char metrics[208];
    CHECK_FALSE(BuildSelfTestSchedulerResult(state, pressure, 5u, metrics, sizeof(metrics)));
    CHECK_TRUE(std::strstr(metrics, "sf=1") != nullptr);
}

TEST(SelfTestSchedulingPolicy, DiagnosticMetricsFitResultFrameBudget)
{
    SelfTestSchedulingState state{};
    SelfTestScheduling_Init(state, SelfTestResultSchedulingMode::Cooperative);
    state.resultFrameCount = UINT32_MAX;
    state.cooperativeDelayCount = UINT32_MAX;
    state.maxTransmitMs = UINT32_MAX;
    state.totalTransmitMs = UINT32_MAX;
    PressureSensorWatchdogSnapshot pressure{};
    pressure.valid = 1u;
    pressure.phase = PRESSURE_SENSOR_WDG_PHASE_RECOVER_READ;
    pressure.phaseAgeMs = UINT32_MAX;
    pressure.lastLoopAgeMs = UINT32_MAX;
    pressure.maxCheckInGapMs = UINT32_MAX;
    pressure.selectFailureCount = UINT32_MAX;
    pressure.readFailureCount = UINT32_MAX;
    pressure.recoveryCount = UINT32_MAX;
    pressure.lastReadHalStatus = 3u;
    pressure.lastReadHalError = PRESSURE_SENSOR_WDG_HAL_ERROR_VALID_MASK;
    pressure.lastFailedReadDurationMs = PRESSURE_SENSOR_WDG_DURATION_MAX_MS;
    pressure.readRecoveryDurationMs = PRESSURE_SENSOR_WDG_DURATION_MAX_MS;
    pressure.stackHighWaterWords = UINT32_MAX - 1u;
    char metrics[208];
    CHECK_TRUE(BuildSelfTestSchedulerResult(state, pressure, UINT32_MAX, metrics, sizeof(metrics)));
    uint8_t payload[256] = {0u};
    const size_t len = DiagnosticResultEmitter::buildResultPayload(
        payload, sizeof(payload), 1u, 2u, 1043u, "selftest_scheduler_safe", true, metrics, 3u);
    CHECK_TRUE(len > 0u);
    CHECK_TRUE(len <= sizeof(payload));
}
