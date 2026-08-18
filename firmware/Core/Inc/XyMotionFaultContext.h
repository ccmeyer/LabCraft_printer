#ifndef INC_XYMOTIONFAULTCONTEXT_H_
#define INC_XYMOTIONFAULTCONTEXT_H_

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define XY_MOTION_FAULT_CONTEXT_VERSION 1u
#define XY_MOTION_FAULT_CONTEXT_WIRE_SIZE 60u
#define XY_MOTION_FAULT_RETAINED_MAGIC 0x58594654u
#define XY_MOTION_FAULT_RETAINED_VERSION 1u

#define XY_MOTION_FAULT_FLAG_TARGETS_CANONICAL  (1u << 0)
#define XY_MOTION_FAULT_FLAG_START_ACCEPTED     (1u << 1)
#define XY_MOTION_FAULT_FLAG_WAIT_COMPLETED     (1u << 2)
#define XY_MOTION_FAULT_FLAG_CONTROL_INTERRUPTED (1u << 3)
#define XY_MOTION_FAULT_FLAG_ENDPOINT_MATCHES   (1u << 4)
#define XY_MOTION_FAULT_FLAG_TARGETS_MATCH      (1u << 5)
#define XY_MOTION_FAULT_FLAG_TIMER_OWNED        (1u << 6)
#define XY_MOTION_FAULT_FLAG_RESUME_VALIDATION  (1u << 7)

typedef enum {
  XY_MOTION_FAULT_NONE = 0,
  XY_MOTION_FAULT_START_REJECTED = 1,
  XY_MOTION_FAULT_X_LIMIT = 2,
  XY_MOTION_FAULT_Y_LIMIT = 3,
  XY_MOTION_FAULT_PLANNER = 4,
  XY_MOTION_FAULT_ENDPOINT_MISMATCH = 5,
  XY_MOTION_FAULT_RESUME_TERMINAL_MISMATCH = 6,
} XyMotionFaultReason;

typedef struct {
  uint8_t version;
  uint8_t valid;
  uint8_t reason;
  uint8_t startStatus;
  uint8_t executorState;
  uint8_t terminalReason;
  uint8_t flags;
  uint8_t reserved;
  uint32_t commandSeq32;
  uint32_t captureUptimeMs;
  int32_t startX;
  int32_t startY;
  int32_t targetX;
  int32_t targetY;
  int32_t endX;
  int32_t endY;
  uint32_t requestedXEdges;
  uint32_t requestedYEdges;
  uint32_t emittedXEdges;
  uint32_t emittedYEdges;
  uint32_t doneBits;
} XyMotionFaultContext;

typedef struct {
  uint32_t magic;
  uint16_t version;
  uint16_t size;
  uint32_t checksum;
  XyMotionFaultContext context;
} XyMotionFaultRetainedContext;

const char* XyMotionFaultContext_ReasonName(uint8_t reason);
void XyMotionFaultContext_Init(XyMotionFaultContext* context);
uint32_t XyMotionFaultContext_Pack(const XyMotionFaultContext* context,
                                   uint8_t* out,
                                   size_t outLen);
uint32_t XyMotionFaultContext_Unpack(XyMotionFaultContext* context,
                                     const uint8_t* payload,
                                     size_t payloadLen);
uint32_t XyMotionFaultContext_Checksum(const XyMotionFaultContext* context);
void XyMotionFaultContext_WriteRetained(XyMotionFaultRetainedContext* retained,
                                        const XyMotionFaultContext* context);
uint32_t XyMotionFaultContext_ReadRetained(const XyMotionFaultRetainedContext* retained,
                                           XyMotionFaultContext* context);
void XyMotionFaultContext_ClearRetained(XyMotionFaultRetainedContext* retained);

#ifdef __cplusplus
}
#endif

#endif /* INC_XYMOTIONFAULTCONTEXT_H_ */
