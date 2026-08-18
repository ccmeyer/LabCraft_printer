#include "XyMotionFaultContext.h"

#include <string.h>

static void writeU32(uint8_t* out, size_t* idx, uint32_t value)
{
  out[(*idx)++] = (uint8_t)(value & 0xFFu);
  out[(*idx)++] = (uint8_t)((value >> 8) & 0xFFu);
  out[(*idx)++] = (uint8_t)((value >> 16) & 0xFFu);
  out[(*idx)++] = (uint8_t)((value >> 24) & 0xFFu);
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

const char* XyMotionFaultContext_ReasonName(uint8_t reason)
{
  switch ((XyMotionFaultReason)reason) {
    case XY_MOTION_FAULT_NONE: return "none";
    case XY_MOTION_FAULT_START_REJECTED: return "start_rejected";
    case XY_MOTION_FAULT_X_LIMIT: return "x_limit";
    case XY_MOTION_FAULT_Y_LIMIT: return "y_limit";
    case XY_MOTION_FAULT_PLANNER: return "planner_fault";
    case XY_MOTION_FAULT_ENDPOINT_MISMATCH: return "endpoint_mismatch";
    case XY_MOTION_FAULT_RESUME_TERMINAL_MISMATCH: return "resume_terminal_mismatch";
    default: return "unknown";
  }
}

void XyMotionFaultContext_Init(XyMotionFaultContext* context)
{
  if (context == 0) return;
  memset(context, 0, sizeof(*context));
  context->version = XY_MOTION_FAULT_CONTEXT_VERSION;
}

uint32_t XyMotionFaultContext_Pack(const XyMotionFaultContext* context,
                                   uint8_t* out,
                                   size_t outLen)
{
  if (context == 0 || out == 0 || outLen < XY_MOTION_FAULT_CONTEXT_WIRE_SIZE) return 0u;
  size_t idx = 0u;
  out[idx++] = context->version;
  out[idx++] = context->valid;
  out[idx++] = context->reason;
  out[idx++] = context->startStatus;
  out[idx++] = context->executorState;
  out[idx++] = context->terminalReason;
  out[idx++] = context->flags;
  out[idx++] = context->reserved;
  writeU32(out, &idx, context->commandSeq32);
  writeU32(out, &idx, context->captureUptimeMs);
  writeU32(out, &idx, (uint32_t)context->startX);
  writeU32(out, &idx, (uint32_t)context->startY);
  writeU32(out, &idx, (uint32_t)context->targetX);
  writeU32(out, &idx, (uint32_t)context->targetY);
  writeU32(out, &idx, (uint32_t)context->endX);
  writeU32(out, &idx, (uint32_t)context->endY);
  writeU32(out, &idx, context->requestedXEdges);
  writeU32(out, &idx, context->requestedYEdges);
  writeU32(out, &idx, context->emittedXEdges);
  writeU32(out, &idx, context->emittedYEdges);
  writeU32(out, &idx, context->doneBits);
  return idx == XY_MOTION_FAULT_CONTEXT_WIRE_SIZE ? 1u : 0u;
}

uint32_t XyMotionFaultContext_Unpack(XyMotionFaultContext* context,
                                     const uint8_t* payload,
                                     size_t payloadLen)
{
  if (context == 0 || payload == 0 || payloadLen != XY_MOTION_FAULT_CONTEXT_WIRE_SIZE) return 0u;
  size_t idx = 0u;
  context->version = payload[idx++];
  context->valid = payload[idx++];
  context->reason = payload[idx++];
  context->startStatus = payload[idx++];
  context->executorState = payload[idx++];
  context->terminalReason = payload[idx++];
  context->flags = payload[idx++];
  context->reserved = payload[idx++];
  context->commandSeq32 = readU32(payload, &idx);
  context->captureUptimeMs = readU32(payload, &idx);
  context->startX = (int32_t)readU32(payload, &idx);
  context->startY = (int32_t)readU32(payload, &idx);
  context->targetX = (int32_t)readU32(payload, &idx);
  context->targetY = (int32_t)readU32(payload, &idx);
  context->endX = (int32_t)readU32(payload, &idx);
  context->endY = (int32_t)readU32(payload, &idx);
  context->requestedXEdges = readU32(payload, &idx);
  context->requestedYEdges = readU32(payload, &idx);
  context->emittedXEdges = readU32(payload, &idx);
  context->emittedYEdges = readU32(payload, &idx);
  context->doneBits = readU32(payload, &idx);
  return idx == XY_MOTION_FAULT_CONTEXT_WIRE_SIZE ? 1u : 0u;
}

uint32_t XyMotionFaultContext_Checksum(const XyMotionFaultContext* context)
{
  uint8_t packed[XY_MOTION_FAULT_CONTEXT_WIRE_SIZE] = {0u};
  if (XyMotionFaultContext_Pack(context, packed, sizeof(packed)) == 0u) return 0u;
  return checksumBytes(packed, sizeof(packed));
}

void XyMotionFaultContext_WriteRetained(XyMotionFaultRetainedContext* retained,
                                        const XyMotionFaultContext* context)
{
  if (retained == 0 || context == 0) return;
  retained->magic = 0u;
  retained->version = XY_MOTION_FAULT_RETAINED_VERSION;
  retained->size = (uint16_t)sizeof(*retained);
  retained->context = *context;
  retained->checksum = XyMotionFaultContext_Checksum(context);
  retained->magic = XY_MOTION_FAULT_RETAINED_MAGIC;
}

uint32_t XyMotionFaultContext_ReadRetained(const XyMotionFaultRetainedContext* retained,
                                           XyMotionFaultContext* context)
{
  if (retained == 0 || context == 0) return 0u;
  if (retained->magic != XY_MOTION_FAULT_RETAINED_MAGIC ||
      retained->version != XY_MOTION_FAULT_RETAINED_VERSION ||
      retained->size != (uint16_t)sizeof(*retained)) return 0u;
  const uint32_t checksum = XyMotionFaultContext_Checksum(&retained->context);
  if (checksum != retained->checksum) return 0u;
  *context = retained->context;
  return context->version == XY_MOTION_FAULT_CONTEXT_VERSION && context->valid != 0u ? 1u : 0u;
}

void XyMotionFaultContext_ClearRetained(XyMotionFaultRetainedContext* retained)
{
  if (retained != 0) memset(retained, 0, sizeof(*retained));
}
