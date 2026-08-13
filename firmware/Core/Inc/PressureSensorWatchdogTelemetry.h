#ifndef INC_PRESSURESENSORWATCHDOGTELEMETRY_H_
#define INC_PRESSURESENSORWATCHDOGTELEMETRY_H_

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PRESSURE_SENSOR_WDG_AGE_UNKNOWN 0xFFFFFFFFu
#define PRESSURE_SENSOR_WDG_DURATION_MAX_MS 65535u
#define PRESSURE_SENSOR_WDG_RECOVERY_DELAY_TICKS 20u
#define PRESSURE_SENSOR_WDG_RETAINED_MAGIC 0x50535744u
#define PRESSURE_SENSOR_WDG_RETAINED_VERSION 2u

typedef enum {
  PRESSURE_SENSOR_WDG_PHASE_UNINITIALIZED = 0,
  PRESSURE_SENSOR_WDG_PHASE_DELAY = 1,
  PRESSURE_SENSOR_WDG_PHASE_SELECT_PORT = 2,
  PRESSURE_SENSOR_WDG_PHASE_READ_SENSOR = 3,
  PRESSURE_SENSOR_WDG_PHASE_RECOVER_SELECT = 4,
  PRESSURE_SENSOR_WDG_PHASE_RECOVER_READ = 5,
  PRESSURE_SENSOR_WDG_PHASE_PROCESS_SAMPLE = 6
} PressureSensorWatchdogPhase;

typedef struct {
  volatile uint32_t generation;
  uint8_t valid;
  uint8_t phase;
  uint8_t saturated;
  uint8_t diagnosticWindowActive;
  uint8_t hasLoopStart;
  uint8_t hasLoopComplete;
  uint8_t readRecoveryActive;
  uint8_t readRecoveryStartedInDiagnostic;
  uint8_t lastReadHalStatus;
  uint8_t diagnosticLastReadHalStatus;
  uint8_t reserved[2];
  uint32_t phaseStartMs;
  uint32_t lastLoopStartMs;
  uint32_t lastLoopCompleteMs;
  uint32_t maxCheckInGapMs;
  uint32_t diagnosticMaxCheckInGapMs;
  uint32_t loopCount;
  uint32_t selectFailureCount;
  uint32_t readFailureCount;
  uint32_t recoveryCount;
  uint32_t diagnosticLoopStart;
  uint32_t diagnosticSelectFailureStart;
  uint32_t diagnosticReadFailureStart;
  uint32_t diagnosticRecoveryStart;
  uint32_t stackHighWaterWords;
  uint32_t lastFailedReadDurationMs;
  uint32_t lastReadRecoveryDurationMs;
  uint32_t diagnosticLastFailedReadDurationMs;
  uint32_t diagnosticLastReadRecoveryDurationMs;
  uint32_t readRecoveryStartMs;
} PressureSensorWatchdogState;

typedef struct {
  uint8_t valid;
  uint8_t phase;
  uint8_t saturated;
  uint8_t diagnosticWindowActive;
  uint32_t phaseAgeMs;
  uint32_t lastLoopAgeMs;
  uint32_t maxCheckInGapMs;
  uint32_t loopCount;
  uint32_t selectFailureCount;
  uint32_t readFailureCount;
  uint32_t recoveryCount;
  uint32_t stackHighWaterWords;
  uint32_t snapshotTickMs;
  uint8_t lastReadHalStatus;
  uint8_t reserved[3];
  uint32_t lastFailedReadDurationMs;
  uint32_t readRecoveryDurationMs;
} PressureSensorWatchdogSnapshot;

typedef struct {
  uint8_t valid;
  uint8_t phase;
  uint8_t saturated;
  uint8_t reserved;
  uint32_t watchdogAgeMs;
  uint32_t phaseAgeMs;
  uint32_t lastLoopAgeMs;
  uint32_t maxCheckInGapMs;
  uint32_t selectFailureCount;
  uint32_t readFailureCount;
  uint32_t recoveryCount;
  uint32_t loopCount;
  uint32_t stackHighWaterWords;
  uint32_t snapshotTickMs;
  uint8_t lastReadHalStatus;
  uint8_t reserved2[3];
  uint32_t lastFailedReadDurationMs;
  uint32_t readRecoveryDurationMs;
} PressureSensorWatchdogResetContext;

typedef struct {
  uint32_t magic;
  uint16_t version;
  uint16_t size;
  uint32_t checksum;
  PressureSensorWatchdogResetContext context;
} PressureSensorWatchdogRetainedContext;

void PressureSensorWatchdogTelemetry_Init(PressureSensorWatchdogState* state,
                                          uint32_t nowMs);
uint32_t PressureSensorWatchdogTelemetry_BeginWindow(PressureSensorWatchdogState* state);
void PressureSensorWatchdogTelemetry_SetPhase(PressureSensorWatchdogState* state,
                                              PressureSensorWatchdogPhase phase,
                                              uint32_t nowMs);
void PressureSensorWatchdogTelemetry_NoteLoopStart(PressureSensorWatchdogState* state,
                                                  uint32_t nowMs);
void PressureSensorWatchdogTelemetry_NoteLoopComplete(PressureSensorWatchdogState* state,
                                                     uint32_t nowMs);
void PressureSensorWatchdogTelemetry_NoteSelectFailure(PressureSensorWatchdogState* state);
void PressureSensorWatchdogTelemetry_NoteReadFailure(PressureSensorWatchdogState* state,
                                                     uint8_t halStatus,
                                                     uint32_t elapsedMs);
void PressureSensorWatchdogTelemetry_NoteRecovery(PressureSensorWatchdogState* state);
void PressureSensorWatchdogTelemetry_NoteReadRecoveryStart(PressureSensorWatchdogState* state,
                                                           uint32_t nowMs);
void PressureSensorWatchdogTelemetry_NoteReadRecoveryComplete(PressureSensorWatchdogState* state,
                                                              uint32_t nowMs);
void PressureSensorWatchdogTelemetry_SetStackHighWater(PressureSensorWatchdogState* state,
                                                      uint32_t words);
void PressureSensorWatchdogTelemetry_GetSnapshot(const PressureSensorWatchdogState* state,
                                                 uint32_t nowMs,
                                                 PressureSensorWatchdogSnapshot* out);

uint32_t PressureSensorWatchdogTelemetry_ChecksumResetContext(
    const PressureSensorWatchdogResetContext* context);
void PressureSensorWatchdogTelemetry_WriteRetainedContext(
    PressureSensorWatchdogRetainedContext* retained,
    const PressureSensorWatchdogResetContext* context);
uint32_t PressureSensorWatchdogTelemetry_ReadRetainedContext(
    const PressureSensorWatchdogRetainedContext* retained,
    PressureSensorWatchdogResetContext* context);
void PressureSensorWatchdogTelemetry_ClearRetainedContext(
    PressureSensorWatchdogRetainedContext* retained);

/* Task-context runtime bridge implemented by PressureSensor.cpp. */
uint32_t PressureSensorWatchdog_BeginDiagnosticWindow(void);
uint32_t PressureSensorWatchdog_GetSnapshot(PressureSensorWatchdogSnapshot* out);

#ifdef __cplusplus
}
#endif

#endif /* INC_PRESSURESENSORWATCHDOGTELEMETRY_H_ */
