#include "CppUTest/TestHarness.h"

#include "PressureSensorWatchdogTelemetry.h"

#include <climits>

TEST_GROUP(PressureSensorWatchdogTelemetry)
{
};

TEST(PressureSensorWatchdogTelemetry, TracksPhaseAgesLoopGapAndCompletion)
{
    PressureSensorWatchdogState state{};
    PressureSensorWatchdogTelemetry_Init(&state, 100u);
    PressureSensorWatchdogTelemetry_SetPhase(&state, PRESSURE_SENSOR_WDG_PHASE_SELECT_PORT, 110u);
    PressureSensorWatchdogTelemetry_NoteLoopStart(&state, 115u);
    PressureSensorWatchdogTelemetry_NoteLoopComplete(&state, 120u);
    PressureSensorWatchdogTelemetry_NoteLoopStart(&state, 135u);

    PressureSensorWatchdogSnapshot snap{};
    PressureSensorWatchdogTelemetry_GetSnapshot(&state, 140u, &snap);

    UNSIGNED_LONGS_EQUAL(1u, snap.valid);
    UNSIGNED_LONGS_EQUAL(PRESSURE_SENSOR_WDG_PHASE_SELECT_PORT, snap.phase);
    UNSIGNED_LONGS_EQUAL(30u, snap.phaseAgeMs);
    UNSIGNED_LONGS_EQUAL(20u, snap.lastLoopAgeMs);
    UNSIGNED_LONGS_EQUAL(20u, snap.maxCheckInGapMs);
    UNSIGNED_LONGS_EQUAL(2u, snap.loopCount);
}

TEST(PressureSensorWatchdogTelemetry, TickArithmeticIsWrapSafe)
{
    PressureSensorWatchdogState state{};
    PressureSensorWatchdogTelemetry_Init(&state, 0xFFFFFFE0u);
    PressureSensorWatchdogTelemetry_SetPhase(&state, PRESSURE_SENSOR_WDG_PHASE_READ_SENSOR, 0xFFFFFFF0u);
    PressureSensorWatchdogTelemetry_NoteLoopStart(&state, 0xFFFFFFF0u);
    PressureSensorWatchdogTelemetry_NoteLoopStart(&state, 0x00000010u);

    PressureSensorWatchdogSnapshot snap{};
    PressureSensorWatchdogTelemetry_GetSnapshot(&state, 0x00000020u, &snap);
    UNSIGNED_LONGS_EQUAL(48u, snap.phaseAgeMs);
    UNSIGNED_LONGS_EQUAL(32u, snap.maxCheckInGapMs);
}

TEST(PressureSensorWatchdogTelemetry, TickZeroIsAValidTimestamp)
{
    PressureSensorWatchdogState state{};
    PressureSensorWatchdogTelemetry_Init(&state, 0u);
    PressureSensorWatchdogTelemetry_NoteLoopStart(&state, 0u);
    PressureSensorWatchdogTelemetry_NoteLoopComplete(&state, 0u);
    PressureSensorWatchdogTelemetry_NoteLoopStart(&state, 25u);

    PressureSensorWatchdogSnapshot snap{};
    PressureSensorWatchdogTelemetry_GetSnapshot(&state, 40u, &snap);
    UNSIGNED_LONGS_EQUAL(40u, snap.phaseAgeMs);
    UNSIGNED_LONGS_EQUAL(40u, snap.lastLoopAgeMs);
    UNSIGNED_LONGS_EQUAL(25u, snap.maxCheckInGapMs);
}

TEST(PressureSensorWatchdogTelemetry, DiagnosticWindowReportsOnlyWindowDeltas)
{
    PressureSensorWatchdogState state{};
    PressureSensorWatchdogTelemetry_Init(&state, 1u);
    PressureSensorWatchdogTelemetry_NoteLoopStart(&state, 10u);
    PressureSensorWatchdogTelemetry_NoteSelectFailure(&state);
    PressureSensorWatchdogTelemetry_NoteRecovery(&state);
    PressureSensorWatchdogTelemetry_BeginWindow(&state);
    PressureSensorWatchdogTelemetry_NoteLoopStart(&state, 20u);
    PressureSensorWatchdogTelemetry_NoteLoopStart(&state, 55u);
    PressureSensorWatchdogTelemetry_NoteReadFailure(&state);

    PressureSensorWatchdogSnapshot snap{};
    PressureSensorWatchdogTelemetry_GetSnapshot(&state, 60u, &snap);
    UNSIGNED_LONGS_EQUAL(2u, snap.loopCount);
    UNSIGNED_LONGS_EQUAL(0u, snap.selectFailureCount);
    UNSIGNED_LONGS_EQUAL(1u, snap.readFailureCount);
    UNSIGNED_LONGS_EQUAL(0u, snap.recoveryCount);
    UNSIGNED_LONGS_EQUAL(35u, snap.maxCheckInGapMs);
}

TEST(PressureSensorWatchdogTelemetry, InProgressUpdateFailsSnapshotAndWindowClosed)
{
    PressureSensorWatchdogState state{};
    PressureSensorWatchdogTelemetry_Init(&state, 1u);
    state.generation = 1u;
    PressureSensorWatchdogSnapshot snap{};
    PressureSensorWatchdogTelemetry_GetSnapshot(&state, 2u, &snap);
    UNSIGNED_LONGS_EQUAL(0u, snap.valid);
    UNSIGNED_LONGS_EQUAL(0u, PressureSensorWatchdogTelemetry_BeginWindow(&state));
}

TEST(PressureSensorWatchdogTelemetry, SaturatingCounterSetsEvidenceFlag)
{
    PressureSensorWatchdogState state{};
    PressureSensorWatchdogTelemetry_Init(&state, 1u);
    state.readFailureCount = UINT32_MAX;
    PressureSensorWatchdogTelemetry_NoteReadFailure(&state);
    UNSIGNED_LONGS_EQUAL(UINT32_MAX, state.readFailureCount);
    UNSIGNED_LONGS_EQUAL(1u, state.saturated);
}

TEST(PressureSensorWatchdogTelemetry, RetainedContextRejectsCorruption)
{
    PressureSensorWatchdogResetContext input{};
    input.valid = 1u;
    input.phase = PRESSURE_SENSOR_WDG_PHASE_RECOVER_READ;
    input.watchdogAgeMs = 301u;
    input.phaseAgeMs = 290u;
    input.loopCount = 100u;
    PressureSensorWatchdogRetainedContext retained{};
    PressureSensorWatchdogTelemetry_WriteRetainedContext(&retained, &input);

    PressureSensorWatchdogResetContext output{};
    CHECK_TRUE(PressureSensorWatchdogTelemetry_ReadRetainedContext(&retained, &output) != 0u);
    UNSIGNED_LONGS_EQUAL(301u, output.watchdogAgeMs);
    retained.context.loopCount++;
    CHECK_FALSE(PressureSensorWatchdogTelemetry_ReadRetainedContext(&retained, &output) != 0u);
}

TEST(PressureSensorWatchdogTelemetry, ClearInvalidatesRetainedContext)
{
    PressureSensorWatchdogResetContext input{};
    input.valid = 1u;
    PressureSensorWatchdogRetainedContext retained{};
    PressureSensorWatchdogTelemetry_WriteRetainedContext(&retained, &input);
    PressureSensorWatchdogTelemetry_ClearRetainedContext(&retained);
    PressureSensorWatchdogResetContext output{};
    CHECK_FALSE(PressureSensorWatchdogTelemetry_ReadRetainedContext(&retained, &output) != 0u);
}
