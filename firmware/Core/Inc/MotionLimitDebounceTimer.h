#ifndef INC_MOTIONLIMITDEBOUNCETIMER_H_
#define INC_MOTIONLIMITDEBOUNCETIMER_H_

#include "MotionLimitDebouncePolicy.h"
#include "stm32f4xx_hal.h"

#include <cstdint>

namespace MotionLimitDebounceTimer {

enum class Axis : uint8_t {
  X = 0u,
  Y = 1u,
};

struct ConfirmationSnapshot {
  bool valid = false;
  bool sourceExtiTim5 = false;
  Axis axis = Axis::X;
  uint32_t moveGeneration = 0u;
  uint32_t candidateTimerCount = 0u;
  uint32_t deadlineTimerCount = 0u;
  uint32_t serviceTimerCount = 0u;
  uint32_t irqLatenessUs = 0u;
  uint32_t transitionCount = 0u;
  uint32_t restartCount = 0u;
  uint32_t armFailureCount = 0u;
  int32_t candidatePosition = 0;
  int32_t consumedPosition = 0;
  bool rawExpiryAsserted = false;
};

struct AxisSnapshot {
  MotionLimitDebouncePolicy::Snapshot debounce{};
  ConfirmationSnapshot confirmation{};
  uint32_t armFailureCount = 0u;
  bool configured = false;
};

struct HealthSnapshot {
  bool initialized = false;
  bool instanceValid = false;
  bool configurationValid = false;
  bool running = false;
  bool nvicValid = false;
  uint32_t timerInputHz = 0u;
  uint32_t tickHz = 0u;
  uint32_t prescaler = 0u;
  uint32_t period = 0u;
  uint32_t timingFailureCount = 0u;
  uint32_t armFailureCount = 0u;
  bool diagnosticActive = false;
  bool diagnosticComplete = false;
  uint32_t diagnosticStartCount = 0u;
  uint32_t diagnosticServiceCount = 0u;
  uint32_t diagnosticElapsedUs = 0u;
};

bool initialize(TIM_HandleTypeDef* timer);
bool attach(Axis axis,
            GPIO_TypeDef* port,
            uint16_t pin,
            bool activeHigh);
void onExtiFromIsr(Axis axis,
                   uint32_t moveGeneration,
                   int32_t position,
                   bool candidateAllowed);
bool takeConfirmedFromIsr(Axis axis,
                          uint32_t moveGeneration,
                          int32_t consumedPosition);
void recordStopPositionFromIsr(Axis axis, int32_t stoppedPosition);
void completeMoveFromIsr(Axis axis, int32_t stoppedPosition);
void cancel(Axis axis, bool rejectPending = false);
AxisSnapshot snapshot(Axis axis);
ConfirmationSnapshot lastConfirmation(Axis axis);
HealthSnapshot healthSnapshot();
bool healthy();
bool armDiagnostic();
void handleIrq();

}  // namespace MotionLimitDebounceTimer

#ifdef __cplusplus
extern "C" {
#endif

void MX_MotionLimitDebounceTimer_Init(void);
void MotionLimitDebounceTimer_IRQHandler(void);

#ifdef __cplusplus
}
#endif

#endif  // INC_MOTIONLIMITDEBOUNCETIMER_H_
