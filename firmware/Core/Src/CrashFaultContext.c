#include "CrashFaultContext.h"

typedef char CrashFaultContext_SizeMustMatchWire[
    (sizeof(CrashFaultContextV1) == CRASH_FAULT_CONTEXT_WIRE_SIZE) ? 1 : -1];

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

uint32_t CrashFaultContext_Checksum(const CrashFaultContextV1* context)
{
  if (context == NULL) {
    return 0u;
  }
  const uint8_t* bytes = (const uint8_t*)context;
  uint32_t hash = 2166136261u;
  for (size_t i = 0u; i < sizeof(*context); ++i) {
    hash ^= bytes[i];
    hash *= 16777619u;
  }
  return (hash == 0u) ? 1u : hash;
}

uint32_t CrashFaultContext_ValidateRetained(const CrashFaultContextRetained* retained,
                                            CrashFaultContextV1* contextOut)
{
  if ((retained == NULL) ||
      (retained->magic != CRASH_FAULT_CONTEXT_RETAINED_MAGIC) ||
      (retained->version != CRASH_FAULT_CONTEXT_VERSION) ||
      (retained->size != (uint16_t)sizeof(*retained)) ||
      (retained->context.version != CRASH_FAULT_CONTEXT_VERSION)) {
    return 0u;
  }
  const uint32_t checksum = CrashFaultContext_Checksum(&retained->context);
  if ((checksum == 0u) || (checksum != retained->checksum)) {
    return 0u;
  }
  if (contextOut != NULL) {
    *contextOut = retained->context;
  }
  return 1u;
}

uint32_t CrashFaultContext_SelectCoreFrame(uint32_t rawSp,
                                           uint32_t excReturn,
                                           uint32_t ramLow,
                                           uint32_t ramHigh,
                                           uint32_t* coreFrameOut)
{
  const uint32_t fpOffset = ((excReturn & (1u << 4)) == 0u) ? (18u * 4u) : 0u;
  if ((rawSp & 0x3u) != 0u || rawSp < ramLow || rawSp > (UINT32_MAX - fpOffset)) {
    return 0u;
  }
  const uint32_t frame = rawSp + fpOffset;
  if (frame < ramLow || frame > ramHigh || (ramHigh - frame) < (8u * 4u)) {
    return 0u;
  }
  if (coreFrameOut != NULL) {
    *coreFrameOut = frame;
  }
  return 1u;
}

uint8_t CrashFaultContext_MatchStack(uint32_t sp,
                                     const CrashFaultStackRange* ranges,
                                     size_t rangeCount,
                                     uint32_t* stackLowOut,
                                     uint32_t* stackHighOut)
{
  if (ranges == NULL) {
    return 0u;
  }
  for (size_t i = 0u; i < rangeCount; ++i) {
    if (ranges[i].low < ranges[i].high && sp >= ranges[i].low && sp < ranges[i].high) {
      if (stackLowOut != NULL) *stackLowOut = ranges[i].low;
      if (stackHighOut != NULL) *stackHighOut = ranges[i].high;
      return ranges[i].taskId;
    }
  }
  return 0u;
}

uint32_t CrashFaultContext_Pack(const CrashFaultContextV1* context,
                                uint8_t* out,
                                size_t outLen)
{
  if ((context == NULL) || (out == NULL) || (outLen < CRASH_FAULT_CONTEXT_WIRE_SIZE)) {
    return 0u;
  }
  size_t idx = 0u;
  out[idx++] = context->version;
  out[idx++] = context->flags;
  out[idx++] = context->faultKind;
  out[idx++] = context->taskId;
  out[idx++] = context->activeCommand;
  out[idx++] = context->homePhaseX;
  out[idx++] = context->homePhaseY;
  out[idx++] = context->homePhaseZ;
  out[idx++] = context->homePhaseP;
  out[idx++] = context->homePhaseR;
  writeU16(out, &idx, context->ipsr);

#define WRITE_CONTEXT_U32(field) writeU32(out, &idx, context->field)
  WRITE_CONTEXT_U32(excReturn);
  WRITE_CONTEXT_U32(activeSp);
  WRITE_CONTEXT_U32(msp);
  WRITE_CONTEXT_U32(psp);
  WRITE_CONTEXT_U32(taskStackLow);
  WRITE_CONTEXT_U32(taskStackHigh);
  WRITE_CONTEXT_U32(r0);
  WRITE_CONTEXT_U32(r1);
  WRITE_CONTEXT_U32(r2);
  WRITE_CONTEXT_U32(r3);
  WRITE_CONTEXT_U32(r12);
  WRITE_CONTEXT_U32(lr);
  WRITE_CONTEXT_U32(pc);
  WRITE_CONTEXT_U32(xpsr);
  WRITE_CONTEXT_U32(cfsr);
  WRITE_CONTEXT_U32(hfsr);
  WRITE_CONTEXT_U32(dfsr);
  WRITE_CONTEXT_U32(afsr);
  WRITE_CONTEXT_U32(shcsr);
  WRITE_CONTEXT_U32(mmfar);
  WRITE_CONTEXT_U32(bfar);
  WRITE_CONTEXT_U32(control);
  WRITE_CONTEXT_U32(basepri);
  WRITE_CONTEXT_U32(primask);
  WRITE_CONTEXT_U32(faultmask);
#undef WRITE_CONTEXT_U32

  return (idx == CRASH_FAULT_CONTEXT_WIRE_SIZE) ? 1u : 0u;
}
