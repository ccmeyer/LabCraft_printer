#include "RegulatorTelemetry.h"

#include <string.h>

static void writeU16(uint8_t* out, size_t* idx, uint16_t value)
{
  out[(*idx)++] = (uint8_t)(value & 0xFFu);
  out[(*idx)++] = (uint8_t)((value >> 8) & 0xFFu);
}

static void writeU32(uint8_t* out, size_t* idx, uint32_t value)
{
  out[(*idx)++] = (uint8_t)(value & 0xFFu);
  out[(*idx)++] = (uint8_t)((value >> 8) & 0xFFu);
  out[(*idx)++] = (uint8_t)((value >> 16) & 0xFFu);
  out[(*idx)++] = (uint8_t)((value >> 24) & 0xFFu);
}

static uint16_t readU16(const uint8_t* payload, size_t* idx)
{
  const uint16_t value = (uint16_t)payload[*idx] |
                         (uint16_t)((uint16_t)payload[*idx + 1u] << 8);
  *idx += 2u;
  return value;
}

static uint32_t readU32(const uint8_t* payload, size_t* idx)
{
  const uint32_t value = (uint32_t)payload[*idx] |
                         ((uint32_t)payload[*idx + 1u] << 8) |
                         ((uint32_t)payload[*idx + 2u] << 16) |
                         ((uint32_t)payload[*idx + 3u] << 24);
  *idx += 4u;
  return value;
}

static uint32_t checksumBytes(const uint8_t* data, size_t len)
{
  uint32_t hash = 2166136261u;
  for (size_t i = 0u; i < len; ++i) {
    hash ^= data[i];
    hash *= 16777619u;
  }
  return hash;
}

uint16_t RegulatorTelemetry_BuildFlags(uint32_t active,
                                       uint32_t homing,
                                       uint32_t resetting,
                                       uint32_t motionHold,
                                       uint32_t quiet,
                                       uint32_t stepping,
                                       uint32_t watchdogInactiveHold,
                                       uint32_t watchdogMotionHold,
                                       uint32_t watchdogRecoveryHold)
{
  uint16_t flags = 0u;
  if (active != 0u) flags |= REG_TEL_FLAG_ACTIVE;
  if (homing != 0u) flags |= REG_TEL_FLAG_HOMING;
  if (resetting != 0u) flags |= REG_TEL_FLAG_RESETTING;
  if (motionHold != 0u) flags |= REG_TEL_FLAG_MOTION_HOLD;
  if (quiet != 0u) flags |= REG_TEL_FLAG_QUIET;
  if (stepping != 0u) flags |= REG_TEL_FLAG_STEPPING;
  if (watchdogInactiveHold != 0u) flags |= REG_TEL_FLAG_WDG_INACTIVE_HOLD;
  if (watchdogMotionHold != 0u) flags |= REG_TEL_FLAG_WDG_MOTION_HOLD;
  if (watchdogRecoveryHold != 0u) flags |= REG_TEL_FLAG_WDG_RECOVERY_HOLD;
  return flags;
}

const char* RegulatorTelemetry_EventName(uint8_t event)
{
  switch ((RegulatorTelemetryEvent)event) {
    case REG_TEL_EVENT_NONE: return "none";
    case REG_TEL_EVENT_START: return "start";
    case REG_TEL_EVENT_PAUSE: return "pause";
    case REG_TEL_EVENT_MOTION_HOLD_ENTER: return "motion_hold_enter";
    case REG_TEL_EVENT_MOTION_HOLD_EXIT: return "motion_hold_exit";
    case REG_TEL_EVENT_HOME_BEGIN: return "home_begin";
    case REG_TEL_EVENT_HOME_END_OK: return "home_end_ok";
    case REG_TEL_EVENT_HOME_END_FAIL: return "home_end_fail";
    case REG_TEL_EVENT_RESET_BEGIN: return "reset_begin";
    case REG_TEL_EVENT_RESET_END_OK: return "reset_end_ok";
    case REG_TEL_EVENT_RESET_END_FAIL: return "reset_end_fail";
    case REG_TEL_EVENT_QUIET_BEGIN: return "quiet_begin";
    case REG_TEL_EVENT_QUIET_END: return "quiet_end";
    case REG_TEL_EVENT_INNER_LIMIT: return "inner_limit";
    case REG_TEL_EVENT_STEP_LIMIT: return "step_limit";
    case REG_TEL_EVENT_SAFETY_HOME: return "safety_home";
    default: return "unknown";
  }
}

uint32_t RegulatorTelemetry_IsRecoveryTriggerEvent(uint8_t event)
{
  return ((event == (uint8_t)REG_TEL_EVENT_INNER_LIMIT) ||
          (event == (uint8_t)REG_TEL_EVENT_STEP_LIMIT) ||
          (event == (uint8_t)REG_TEL_EVENT_SAFETY_HOME)) ? 1u : 0u;
}

uint8_t RegulatorTelemetry_SelectLastEvent(uint8_t currentEvent, uint8_t nextEvent)
{
  if ((nextEvent == (uint8_t)REG_TEL_EVENT_HOME_BEGIN) &&
      (RegulatorTelemetry_IsRecoveryTriggerEvent(currentEvent) != 0u)) {
    return currentEvent;
  }
  return nextEvent;
}

void RegulatorTelemetry_InitResetContext(RegulatorTelemetryResetContext* context)
{
  if (context == 0) {
    return;
  }
  memset(context, 0, sizeof(*context));
  context->version = REG_TEL_RESET_CONTEXT_VERSION;
  context->pWatchdogAgeMs = REG_TEL_AGE_UNKNOWN;
  context->rWatchdogAgeMs = REG_TEL_AGE_UNKNOWN;
  context->pLastEventAgeMs = REG_TEL_AGE_UNKNOWN;
  context->rLastEventAgeMs = REG_TEL_AGE_UNKNOWN;
}

uint32_t RegulatorTelemetry_PackResetContext(const RegulatorTelemetryResetContext* context,
                                             uint8_t* out,
                                             size_t outLen)
{
  if ((context == 0) || (out == 0) || (outLen < REG_TEL_RESET_CONTEXT_WIRE_SIZE)) {
    return 0u;
  }
  size_t idx = 0u;
  out[idx++] = context->version;
  out[idx++] = context->valid;
  writeU16(out, &idx, context->pFlags);
  writeU16(out, &idx, context->rFlags);
  out[idx++] = context->pWatchdogEnabled;
  out[idx++] = context->rWatchdogEnabled;
  writeU32(out, &idx, context->pWatchdogAgeMs);
  writeU32(out, &idx, context->rWatchdogAgeMs);
  out[idx++] = context->pLastEvent;
  out[idx++] = context->rLastEvent;
  writeU32(out, &idx, context->pLastEventAgeMs);
  writeU32(out, &idx, context->rLastEventAgeMs);
  writeU32(out, &idx, context->snapshotTickMs);
  return (idx == REG_TEL_RESET_CONTEXT_WIRE_SIZE) ? 1u : 0u;
}

uint32_t RegulatorTelemetry_UnpackResetContext(RegulatorTelemetryResetContext* context,
                                               const uint8_t* payload,
                                               size_t payloadLen)
{
  if ((context == 0) || (payload == 0) || (payloadLen != REG_TEL_RESET_CONTEXT_WIRE_SIZE)) {
    return 0u;
  }
  size_t idx = 0u;
  context->version = payload[idx++];
  context->valid = payload[idx++];
  context->pFlags = readU16(payload, &idx);
  context->rFlags = readU16(payload, &idx);
  context->pWatchdogEnabled = payload[idx++];
  context->rWatchdogEnabled = payload[idx++];
  context->pWatchdogAgeMs = readU32(payload, &idx);
  context->rWatchdogAgeMs = readU32(payload, &idx);
  context->pLastEvent = payload[idx++];
  context->rLastEvent = payload[idx++];
  context->pLastEventAgeMs = readU32(payload, &idx);
  context->rLastEventAgeMs = readU32(payload, &idx);
  context->snapshotTickMs = readU32(payload, &idx);
  return (idx == REG_TEL_RESET_CONTEXT_WIRE_SIZE) ? 1u : 0u;
}

uint32_t RegulatorTelemetry_ChecksumResetContext(const RegulatorTelemetryResetContext* context)
{
  uint8_t packed[REG_TEL_RESET_CONTEXT_WIRE_SIZE] = {0u};
  if (RegulatorTelemetry_PackResetContext(context, packed, sizeof(packed)) == 0u) {
    return 0u;
  }
  return checksumBytes(packed, sizeof(packed));
}

void RegulatorTelemetry_WriteRetainedContext(RegulatorTelemetryRetainedContext* retained,
                                             const RegulatorTelemetryResetContext* context)
{
  if ((retained == 0) || (context == 0)) {
    return;
  }
  retained->magic = REG_TEL_RETAINED_MAGIC;
  retained->version = REG_TEL_RETAINED_VERSION;
  retained->size = (uint16_t)sizeof(*retained);
  retained->context = *context;
  retained->checksum = RegulatorTelemetry_ChecksumResetContext(context);
}

uint32_t RegulatorTelemetry_ReadRetainedContext(const RegulatorTelemetryRetainedContext* retained,
                                                RegulatorTelemetryResetContext* context)
{
  if ((retained == 0) || (context == 0)) {
    return 0u;
  }
  if ((retained->magic != REG_TEL_RETAINED_MAGIC) ||
      (retained->version != REG_TEL_RETAINED_VERSION) ||
      (retained->size != (uint16_t)sizeof(*retained))) {
    return 0u;
  }
  const uint32_t checksum = RegulatorTelemetry_ChecksumResetContext(&retained->context);
  if ((checksum == 0u) || (checksum != retained->checksum)) {
    return 0u;
  }
  *context = retained->context;
  return (context->valid != 0u) ? 1u : 0u;
}

void RegulatorTelemetry_ClearRetainedContext(RegulatorTelemetryRetainedContext* retained)
{
  if (retained == 0) {
    return;
  }
  memset(retained, 0, sizeof(*retained));
}
