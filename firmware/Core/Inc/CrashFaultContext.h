#ifndef INC_CRASHFAULTCONTEXT_H_
#define INC_CRASHFAULTCONTEXT_H_

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define CRASH_FAULT_CONTEXT_VERSION 1u
#define CRASH_FAULT_CONTEXT_WIRE_SIZE 112u
#define CRASH_FAULT_CONTEXT_RETAINED_MAGIC 0x46585443u /* "CTXF" */

#define CRASH_FAULT_CONTEXT_FLAG_CORE_FRAME_VALID  (1u << 0)
#define CRASH_FAULT_CONTEXT_FLAG_FP_EXTENDED_FRAME (1u << 1)
#define CRASH_FAULT_CONTEXT_FLAG_TASK_STACK_MATCHED (1u << 2)
#define CRASH_FAULT_CONTEXT_FLAG_MMFAR_VALID        (1u << 3)
#define CRASH_FAULT_CONTEXT_FLAG_BFAR_VALID         (1u << 4)
#define CRASH_FAULT_CONTEXT_FLAG_HANDLER_MODE       (1u << 5)
#define CRASH_FAULT_CONTEXT_FLAG_STACK_POINTER_VALID (1u << 6)

typedef enum {
  CRASH_HOME_PHASE_IDLE = 0,
  CRASH_HOME_PHASE_INITIAL_CHECK,
  CRASH_HOME_PHASE_COARSE_SEEK,
  CRASH_HOME_PHASE_RELEASE,
  CRASH_HOME_PHASE_FINE_SEEK,
  CRASH_HOME_PHASE_FINAL_BACKOFF,
  CRASH_HOME_PHASE_SUCCEEDED,
  CRASH_HOME_PHASE_CANCELED,
  CRASH_HOME_PHASE_FAILED
} CrashHomePhase;

typedef enum {
  CRASH_HOME_AXIS_X = 0,
  CRASH_HOME_AXIS_Y,
  CRASH_HOME_AXIS_Z,
  CRASH_HOME_AXIS_P,
  CRASH_HOME_AXIS_R,
  CRASH_HOME_AXIS_COUNT
} CrashHomeAxis;

typedef struct {
  uint8_t version;
  uint8_t flags;
  uint8_t faultKind;
  uint8_t taskId;
  uint8_t activeCommand;
  uint8_t homePhaseX;
  uint8_t homePhaseY;
  uint8_t homePhaseZ;
  uint8_t homePhaseP;
  uint8_t homePhaseR;
  uint16_t ipsr;
  uint32_t excReturn;
  uint32_t activeSp;
  uint32_t msp;
  uint32_t psp;
  uint32_t taskStackLow;
  uint32_t taskStackHigh;
  uint32_t r0;
  uint32_t r1;
  uint32_t r2;
  uint32_t r3;
  uint32_t r12;
  uint32_t lr;
  uint32_t pc;
  uint32_t xpsr;
  uint32_t cfsr;
  uint32_t hfsr;
  uint32_t dfsr;
  uint32_t afsr;
  uint32_t shcsr;
  uint32_t mmfar;
  uint32_t bfar;
  uint32_t control;
  uint32_t basepri;
  uint32_t primask;
  uint32_t faultmask;
} CrashFaultContextV1;

typedef struct {
  uint32_t magic;
  uint16_t version;
  uint16_t size;
  uint32_t checksum;
  CrashFaultContextV1 context;
} CrashFaultContextRetained;

typedef struct {
  uint8_t taskId;
  uint32_t low;
  uint32_t high;
} CrashFaultStackRange;

uint32_t CrashFaultContext_Checksum(const CrashFaultContextV1* context);
uint32_t CrashFaultContext_ValidateRetained(const CrashFaultContextRetained* retained,
                                            CrashFaultContextV1* contextOut);
uint32_t CrashFaultContext_SelectCoreFrame(uint32_t rawSp,
                                           uint32_t excReturn,
                                           uint32_t ramLow,
                                           uint32_t ramHigh,
                                           uint32_t* coreFrameOut);
uint8_t CrashFaultContext_MatchStack(uint32_t sp,
                                     const CrashFaultStackRange* ranges,
                                     size_t rangeCount,
                                     uint32_t* stackLowOut,
                                     uint32_t* stackHighOut);
uint32_t CrashFaultContext_Pack(const CrashFaultContextV1* context,
                                uint8_t* out,
                                size_t outLen);

#ifdef __cplusplus
}
#endif

#endif /* INC_CRASHFAULTCONTEXT_H_ */
