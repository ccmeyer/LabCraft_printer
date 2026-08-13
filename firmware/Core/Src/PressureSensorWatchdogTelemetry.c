#include "PressureSensorWatchdogTelemetry.h"

#include <limits.h>
#include <string.h>
#if defined(_MSC_VER)
#include <intrin.h>
#endif

static void memoryBarrier(void)
{
#if defined(_MSC_VER)
  _ReadWriteBarrier();
#elif defined(__GNUC__)
  __sync_synchronize();
#endif
}

static void beginUpdate(PressureSensorWatchdogState* state)
{
  ++state->generation;
  memoryBarrier();
}

static void endUpdate(PressureSensorWatchdogState* state)
{
  memoryBarrier();
  ++state->generation;
}

static void incrementSaturating(uint32_t* value, uint8_t* saturated)
{
  if (*value == UINT32_MAX) {
    *saturated = 1u;
    return;
  }
  ++(*value);
}

static uint32_t ageFrom(uint32_t nowMs, uint32_t thenMs)
{
  return nowMs - thenMs;
}

static uint32_t boundedDuration(uint32_t elapsedMs, uint8_t* saturated)
{
  if (elapsedMs > PRESSURE_SENSOR_WDG_DURATION_MAX_MS) {
    if (saturated != 0) *saturated = 1u;
    return PRESSURE_SENSOR_WDG_DURATION_MAX_MS;
  }
  return elapsedMs;
}

void PressureSensorWatchdogTelemetry_Init(PressureSensorWatchdogState* state,
                                          uint32_t nowMs)
{
  if (state == 0) return;
  memset(state, 0, sizeof(*state));
  state->valid = 1u;
  state->phase = (uint8_t)PRESSURE_SENSOR_WDG_PHASE_UNINITIALIZED;
  state->phaseStartMs = nowMs;
  state->stackHighWaterWords = UINT32_MAX;
}

uint32_t PressureSensorWatchdogTelemetry_BeginWindow(PressureSensorWatchdogState* state)
{
  if (state == 0 || (state->generation & 1u) != 0u) return 0u;
  beginUpdate(state);
  state->diagnosticWindowActive = 1u;
  state->diagnosticMaxCheckInGapMs = 0u;
  state->diagnosticLoopStart = state->loopCount;
  state->diagnosticSelectFailureStart = state->selectFailureCount;
  state->diagnosticReadFailureStart = state->readFailureCount;
  state->diagnosticRecoveryStart = state->recoveryCount;
  state->diagnosticLastReadHalStatus = 0u;
  state->diagnosticLastFailedReadDurationMs = 0u;
  state->diagnosticLastReadRecoveryDurationMs = 0u;
  endUpdate(state);
  return 1u;
}

void PressureSensorWatchdogTelemetry_SetPhase(PressureSensorWatchdogState* state,
                                              PressureSensorWatchdogPhase phase,
                                              uint32_t nowMs)
{
  if (state == 0) return;
  beginUpdate(state);
  state->phase = (uint8_t)phase;
  state->phaseStartMs = nowMs;
  endUpdate(state);
}

void PressureSensorWatchdogTelemetry_NoteLoopStart(PressureSensorWatchdogState* state,
                                                  uint32_t nowMs)
{
  if (state == 0) return;
  beginUpdate(state);
  if (state->hasLoopStart != 0u) {
    const uint32_t gap = nowMs - state->lastLoopStartMs;
    if (gap > state->maxCheckInGapMs) state->maxCheckInGapMs = gap;
    if (state->diagnosticWindowActive != 0u && gap > state->diagnosticMaxCheckInGapMs) {
      state->diagnosticMaxCheckInGapMs = gap;
    }
  }
  state->hasLoopStart = 1u;
  state->lastLoopStartMs = nowMs;
  incrementSaturating(&state->loopCount, &state->saturated);
  endUpdate(state);
}

void PressureSensorWatchdogTelemetry_NoteLoopComplete(PressureSensorWatchdogState* state,
                                                     uint32_t nowMs)
{
  if (state == 0) return;
  beginUpdate(state);
  state->hasLoopComplete = 1u;
  state->lastLoopCompleteMs = nowMs;
  endUpdate(state);
}

void PressureSensorWatchdogTelemetry_NoteSelectFailure(PressureSensorWatchdogState* state)
{
  if (state == 0) return;
  beginUpdate(state);
  incrementSaturating(&state->selectFailureCount, &state->saturated);
  endUpdate(state);
}

void PressureSensorWatchdogTelemetry_NoteReadFailure(PressureSensorWatchdogState* state,
                                                     uint8_t halStatus,
                                                     uint32_t elapsedMs)
{
  if (state == 0) return;
  beginUpdate(state);
  incrementSaturating(&state->readFailureCount, &state->saturated);
  state->lastReadHalStatus = halStatus;
  state->lastFailedReadDurationMs = boundedDuration(elapsedMs, &state->saturated);
  if (state->diagnosticWindowActive != 0u) {
    state->diagnosticLastReadHalStatus = halStatus;
    state->diagnosticLastFailedReadDurationMs = state->lastFailedReadDurationMs;
  }
  endUpdate(state);
}

void PressureSensorWatchdogTelemetry_NoteRecovery(PressureSensorWatchdogState* state)
{
  if (state == 0) return;
  beginUpdate(state);
  incrementSaturating(&state->recoveryCount, &state->saturated);
  endUpdate(state);
}

void PressureSensorWatchdogTelemetry_NoteReadRecoveryStart(PressureSensorWatchdogState* state,
                                                           uint32_t nowMs)
{
  if (state == 0) return;
  beginUpdate(state);
  state->readRecoveryActive = 1u;
  state->readRecoveryStartedInDiagnostic = state->diagnosticWindowActive;
  state->readRecoveryStartMs = nowMs;
  endUpdate(state);
}

void PressureSensorWatchdogTelemetry_NoteReadRecoveryComplete(PressureSensorWatchdogState* state,
                                                              uint32_t nowMs)
{
  if (state == 0) return;
  beginUpdate(state);
  if (state->readRecoveryActive != 0u) {
    state->lastReadRecoveryDurationMs = boundedDuration(
        ageFrom(nowMs, state->readRecoveryStartMs), &state->saturated);
    if (state->readRecoveryStartedInDiagnostic != 0u) {
      state->diagnosticLastReadRecoveryDurationMs = state->lastReadRecoveryDurationMs;
    }
  }
  state->readRecoveryActive = 0u;
  state->readRecoveryStartedInDiagnostic = 0u;
  endUpdate(state);
}

void PressureSensorWatchdogTelemetry_SetStackHighWater(PressureSensorWatchdogState* state,
                                                      uint32_t words)
{
  if (state == 0) return;
  beginUpdate(state);
  state->stackHighWaterWords = words;
  endUpdate(state);
}

void PressureSensorWatchdogTelemetry_GetSnapshot(const PressureSensorWatchdogState* state,
                                                 uint32_t nowMs,
                                                 PressureSensorWatchdogSnapshot* out)
{
  if (out == 0) return;
  memset(out, 0, sizeof(*out));
  out->phaseAgeMs = PRESSURE_SENSOR_WDG_AGE_UNKNOWN;
  out->lastLoopAgeMs = PRESSURE_SENSOR_WDG_AGE_UNKNOWN;
  out->stackHighWaterWords = UINT32_MAX;
  out->snapshotTickMs = nowMs;
  if (state == 0 || state->valid == 0u) return;
  const uint32_t generationBefore = state->generation;
  if ((generationBefore & 1u) != 0u) return;
  memoryBarrier();

  out->valid = 1u;
  out->phase = state->phase;
  out->saturated = state->saturated;
  out->diagnosticWindowActive = state->diagnosticWindowActive;
  out->phaseAgeMs = ageFrom(nowMs, state->phaseStartMs);
  if (state->hasLoopComplete != 0u) {
    out->lastLoopAgeMs = ageFrom(nowMs, state->lastLoopCompleteMs);
  }
  out->stackHighWaterWords = state->stackHighWaterWords;
  if (state->diagnosticWindowActive != 0u) {
    out->maxCheckInGapMs = state->diagnosticMaxCheckInGapMs;
    out->loopCount = state->loopCount - state->diagnosticLoopStart;
    out->selectFailureCount = state->selectFailureCount - state->diagnosticSelectFailureStart;
    out->readFailureCount = state->readFailureCount - state->diagnosticReadFailureStart;
    out->recoveryCount = state->recoveryCount - state->diagnosticRecoveryStart;
    out->lastReadHalStatus = state->diagnosticLastReadHalStatus;
    out->lastFailedReadDurationMs = state->diagnosticLastFailedReadDurationMs;
    out->readRecoveryDurationMs = state->diagnosticLastReadRecoveryDurationMs;
  } else {
    out->maxCheckInGapMs = state->maxCheckInGapMs;
    out->loopCount = state->loopCount;
    out->selectFailureCount = state->selectFailureCount;
    out->readFailureCount = state->readFailureCount;
    out->recoveryCount = state->recoveryCount;
    out->lastReadHalStatus = state->lastReadHalStatus;
    out->lastFailedReadDurationMs = state->lastFailedReadDurationMs;
    out->readRecoveryDurationMs = state->lastReadRecoveryDurationMs;
  }
  if (state->readRecoveryActive != 0u &&
      (state->diagnosticWindowActive == 0u ||
       state->readRecoveryStartedInDiagnostic != 0u)) {
    const uint32_t activeDuration = boundedDuration(
        ageFrom(nowMs, state->readRecoveryStartMs), &out->saturated);
    if (activeDuration > out->readRecoveryDurationMs) {
      out->readRecoveryDurationMs = activeDuration;
    }
  }
  memoryBarrier();
  const uint32_t generationAfter = state->generation;
  if (generationBefore != generationAfter || (generationAfter & 1u) != 0u) {
    memset(out, 0, sizeof(*out));
    out->phaseAgeMs = PRESSURE_SENSOR_WDG_AGE_UNKNOWN;
    out->lastLoopAgeMs = PRESSURE_SENSOR_WDG_AGE_UNKNOWN;
    out->stackHighWaterWords = UINT32_MAX;
    out->snapshotTickMs = nowMs;
  }
}

static uint32_t hashByte(uint32_t hash, uint8_t value)
{
  hash ^= value;
  return hash * 16777619u;
}

static uint32_t hashU32(uint32_t hash, uint32_t value)
{
  hash = hashByte(hash, (uint8_t)value);
  hash = hashByte(hash, (uint8_t)(value >> 8));
  hash = hashByte(hash, (uint8_t)(value >> 16));
  return hashByte(hash, (uint8_t)(value >> 24));
}

uint32_t PressureSensorWatchdogTelemetry_ChecksumResetContext(
    const PressureSensorWatchdogResetContext* context)
{
  if (context == 0) return 0u;
  uint32_t hash = 2166136261u;
  hash = hashByte(hash, context->valid);
  hash = hashByte(hash, context->phase);
  hash = hashByte(hash, context->saturated);
  hash = hashU32(hash, context->watchdogAgeMs);
  hash = hashU32(hash, context->phaseAgeMs);
  hash = hashU32(hash, context->lastLoopAgeMs);
  hash = hashU32(hash, context->maxCheckInGapMs);
  hash = hashU32(hash, context->selectFailureCount);
  hash = hashU32(hash, context->readFailureCount);
  hash = hashU32(hash, context->recoveryCount);
  hash = hashU32(hash, context->loopCount);
  hash = hashU32(hash, context->stackHighWaterWords);
  hash = hashU32(hash, context->snapshotTickMs);
  hash = hashByte(hash, context->lastReadHalStatus);
  hash = hashU32(hash, context->lastFailedReadDurationMs);
  return hashU32(hash, context->readRecoveryDurationMs);
}

void PressureSensorWatchdogTelemetry_WriteRetainedContext(
    PressureSensorWatchdogRetainedContext* retained,
    const PressureSensorWatchdogResetContext* context)
{
  if (retained == 0 || context == 0) return;
  retained->magic = PRESSURE_SENSOR_WDG_RETAINED_MAGIC;
  retained->version = PRESSURE_SENSOR_WDG_RETAINED_VERSION;
  retained->size = (uint16_t)sizeof(*retained);
  retained->context = *context;
  retained->checksum = PressureSensorWatchdogTelemetry_ChecksumResetContext(context);
}

uint32_t PressureSensorWatchdogTelemetry_ReadRetainedContext(
    const PressureSensorWatchdogRetainedContext* retained,
    PressureSensorWatchdogResetContext* context)
{
  if (retained == 0 || context == 0) return 0u;
  if (retained->magic != PRESSURE_SENSOR_WDG_RETAINED_MAGIC ||
      retained->version != PRESSURE_SENSOR_WDG_RETAINED_VERSION ||
      retained->size != (uint16_t)sizeof(*retained)) return 0u;
  const uint32_t checksum = PressureSensorWatchdogTelemetry_ChecksumResetContext(&retained->context);
  if (checksum == 0u || checksum != retained->checksum) return 0u;
  *context = retained->context;
  return context->valid != 0u ? 1u : 0u;
}

void PressureSensorWatchdogTelemetry_ClearRetainedContext(
    PressureSensorWatchdogRetainedContext* retained)
{
  if (retained != 0) memset(retained, 0, sizeof(*retained));
}
