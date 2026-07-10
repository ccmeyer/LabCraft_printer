#ifndef INC_REGULATORTELEMETRY_H_
#define INC_REGULATORTELEMETRY_H_

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define REG_TEL_FLAG_ACTIVE            (1u << 0)
#define REG_TEL_FLAG_HOMING            (1u << 1)
#define REG_TEL_FLAG_RESETTING         (1u << 2)
#define REG_TEL_FLAG_MOTION_HOLD       (1u << 3)
#define REG_TEL_FLAG_QUIET             (1u << 4)
#define REG_TEL_FLAG_STEPPING          (1u << 5)
#define REG_TEL_FLAG_WDG_INACTIVE_HOLD (1u << 6)
#define REG_TEL_FLAG_WDG_MOTION_HOLD   (1u << 7)
#define REG_TEL_FLAG_WDG_RECOVERY_HOLD (1u << 8)

#define REG_TEL_AGE_UNKNOWN 0xFFFFFFFFu
#define REG_TEL_RESET_CONTEXT_VERSION 1u
#define REG_TEL_RESET_CONTEXT_WIRE_SIZE 30u
#define REG_TEL_RETAINED_MAGIC 0x5247544Cu
#define REG_TEL_RETAINED_VERSION 1u

typedef enum {
  REG_TEL_EVENT_NONE = 0,
  REG_TEL_EVENT_START = 1,
  REG_TEL_EVENT_PAUSE = 2,
  REG_TEL_EVENT_MOTION_HOLD_ENTER = 3,
  REG_TEL_EVENT_MOTION_HOLD_EXIT = 4,
  REG_TEL_EVENT_HOME_BEGIN = 5,
  REG_TEL_EVENT_HOME_END_OK = 6,
  REG_TEL_EVENT_HOME_END_FAIL = 7,
  REG_TEL_EVENT_RESET_BEGIN = 8,
  REG_TEL_EVENT_RESET_END_OK = 9,
  REG_TEL_EVENT_RESET_END_FAIL = 10,
  REG_TEL_EVENT_QUIET_BEGIN = 11,
  REG_TEL_EVENT_QUIET_END = 12,
  REG_TEL_EVENT_INNER_LIMIT = 13,
  REG_TEL_EVENT_STEP_LIMIT = 14,
  REG_TEL_EVENT_SAFETY_HOME = 15,
} RegulatorTelemetryEvent;

typedef struct {
  uint16_t flags;
  uint8_t watchdogEnabled;
  uint32_t watchdogAgeMs;
  uint8_t lastEvent;
  uint32_t lastEventAgeMs;
} RegulatorTelemetrySnapshot;

typedef struct {
  uint8_t version;
  uint8_t valid;
  uint16_t pFlags;
  uint16_t rFlags;
  uint8_t pWatchdogEnabled;
  uint8_t rWatchdogEnabled;
  uint32_t pWatchdogAgeMs;
  uint32_t rWatchdogAgeMs;
  uint8_t pLastEvent;
  uint8_t rLastEvent;
  uint32_t pLastEventAgeMs;
  uint32_t rLastEventAgeMs;
  uint32_t snapshotTickMs;
} RegulatorTelemetryResetContext;

typedef struct {
  uint32_t magic;
  uint16_t version;
  uint16_t size;
  uint32_t checksum;
  RegulatorTelemetryResetContext context;
} RegulatorTelemetryRetainedContext;

uint16_t RegulatorTelemetry_BuildFlags(uint32_t active,
                                       uint32_t homing,
                                       uint32_t resetting,
                                       uint32_t motionHold,
                                       uint32_t quiet,
                                       uint32_t stepping,
                                       uint32_t watchdogInactiveHold,
                                       uint32_t watchdogMotionHold,
                                       uint32_t watchdogRecoveryHold);

const char* RegulatorTelemetry_EventName(uint8_t event);
uint32_t RegulatorTelemetry_IsRecoveryTriggerEvent(uint8_t event);
uint8_t RegulatorTelemetry_SelectLastEvent(uint8_t currentEvent, uint8_t nextEvent);

void RegulatorTelemetry_InitResetContext(RegulatorTelemetryResetContext* context);
uint32_t RegulatorTelemetry_PackResetContext(const RegulatorTelemetryResetContext* context,
                                             uint8_t* out,
                                             size_t outLen);
uint32_t RegulatorTelemetry_UnpackResetContext(RegulatorTelemetryResetContext* context,
                                               const uint8_t* payload,
                                               size_t payloadLen);
uint32_t RegulatorTelemetry_ChecksumResetContext(const RegulatorTelemetryResetContext* context);
void RegulatorTelemetry_WriteRetainedContext(RegulatorTelemetryRetainedContext* retained,
                                             const RegulatorTelemetryResetContext* context);
uint32_t RegulatorTelemetry_ReadRetainedContext(const RegulatorTelemetryRetainedContext* retained,
                                                RegulatorTelemetryResetContext* context);
void RegulatorTelemetry_ClearRetainedContext(RegulatorTelemetryRetainedContext* retained);

#ifdef __cplusplus
}
#endif

#endif /* INC_REGULATORTELEMETRY_H_ */
