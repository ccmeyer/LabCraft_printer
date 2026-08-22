#include "MotionLimitDebounceTimer.h"

#include "ExtiDebounce.h"
#include "main.h"

#include <limits>

namespace MotionLimitDebounceTimer {
namespace {

constexpr uint32_t kExpectedTickHz = 1000000u;
constexpr uint32_t kExpectedPrescaler = 89u;
constexpr uint32_t kExpectedPeriod = 0xFFFFFFFFu;
constexpr uint32_t kIrqPriority = 5u;

struct AxisState {
  GPIO_TypeDef* port = nullptr;
  uint16_t pin = 0u;
  bool activeHigh = true;
  bool configured = false;
  MotionLimitDebouncePolicy::HardwareState debounce{};
  volatile uint32_t moveGeneration = 0u;
  volatile int32_t candidatePosition = 0;
  volatile uint32_t armFailureCount = 0u;
  ConfirmationSnapshot confirmation{};
};

TIM_HandleTypeDef* g_timer = nullptr;
AxisState g_axes[2]{};
volatile bool g_initialized = false;
volatile uint32_t g_timingFailureCount = 0u;
volatile uint32_t g_armFailureCount = 0u;
volatile bool g_diagnosticActive = false;
volatile bool g_diagnosticComplete = false;
volatile uint32_t g_diagnosticStartCount = 0u;
volatile uint32_t g_diagnosticServiceCount = 0u;

AxisState& axisState(Axis axis) {
  return g_axes[axis == Axis::Y ? 1u : 0u];
}

uint32_t axisInterrupt(Axis axis) {
  return axis == Axis::X ? TIM_IT_CC1 : TIM_IT_CC2;
}

uint32_t axisFlag(Axis axis) {
  return axis == Axis::X ? TIM_FLAG_CC1 : TIM_FLAG_CC2;
}

void setAxisCompare(Axis axis, uint32_t value) {
  if (axis == Axis::X) {
    g_timer->Instance->CCR1 = value;
  } else {
    g_timer->Instance->CCR2 = value;
  }
}

void incrementSaturating(volatile uint32_t& value) {
  if (value != std::numeric_limits<uint32_t>::max()) {
    ++value;
  }
}

uint32_t timerInputHz() {
  RCC_ClkInitTypeDef clocks{};
  uint32_t flashLatency = 0u;
  HAL_RCC_GetClockConfig(&clocks, &flashLatency);
  const uint32_t pclk = HAL_RCC_GetPCLK1Freq();
  return clocks.APB1CLKDivider == RCC_HCLK_DIV1 ? pclk : pclk * 2u;
}

bool nvicConfigurationValid() {
  if (NVIC_GetEnableIRQ(TIM5_IRQn) == 0u) {
    return false;
  }
  uint32_t preemptPriority = 0u;
  uint32_t subPriority = 0u;
  HAL_NVIC_GetPriority(
      TIM5_IRQn, NVIC_PRIORITYGROUP_4, &preemptPriority, &subPriority);
  return preemptPriority == kIrqPriority && subPriority == 0u;
}

bool configurationValid() {
  if (g_timer == nullptr || g_timer->Instance != TIM5) {
    return false;
  }
  const uint32_t inputHz = timerInputHz();
  const uint32_t prescaler = g_timer->Instance->PSC;
  return prescaler == kExpectedPrescaler &&
      g_timer->Instance->ARR == kExpectedPeriod &&
      inputHz / (prescaler + 1u) == kExpectedTickHz;
}

bool timerOperational() {
  return g_initialized && configurationValid() &&
      (g_timer->Instance->CR1 & TIM_CR1_CEN) != 0u &&
      nvicConfigurationValid();
}

bool readAsserted(const AxisState& state) {
  if (!state.configured || state.port == nullptr || state.pin == 0u) {
    return false;
  }
  const bool high =
      (state.port->IDR & static_cast<uint32_t>(state.pin)) != 0u;
  return high == state.activeHigh;
}

uint32_t extiMask(const AxisState& state) {
  if (!state.configured || state.pin == 0u) {
    return 0u;
  }
  uint8_t line = 0u;
  uint16_t pin = state.pin;
  while ((pin >>= 1u) != 0u) {
    ++line;
  }
  return ExtiDebounce::lineMask(line);
}

void maskExti(const AxisState& state) {
  const uint32_t mask = extiMask(state);
  if (mask != 0u) {
    EXTI->IMR &= ~mask;
  }
}

void unmaskExti(const AxisState& state) {
  const uint32_t mask = extiMask(state);
  if (mask != 0u) {
    EXTI->IMR |= mask;
  }
}

void clearExti(const AxisState& state) {
  const uint32_t mask = extiMask(state);
  if (mask != 0u) {
    EXTI->PR = mask;
  }
}

void disableAxisCompare(Axis axis) {
  if (g_timer == nullptr || g_timer->Instance == nullptr) {
    return;
  }
  __HAL_TIM_DISABLE_IT(g_timer, axisInterrupt(axis));
  __HAL_TIM_CLEAR_FLAG(g_timer, axisFlag(axis));
}

void recordConfirmation(Axis axis,
                        AxisState& state,
                        uint32_t serviceCount,
                        bool rawAsserted) {
  state.confirmation.valid = true;
  state.confirmation.sourceExtiTim5 = true;
  state.confirmation.axis = axis;
  state.confirmation.moveGeneration = state.moveGeneration;
  state.confirmation.candidateTimerCount = state.debounce.startCount;
  state.confirmation.deadlineTimerCount = state.debounce.deadlineCount;
  state.confirmation.serviceTimerCount = serviceCount;
  state.confirmation.irqLatenessUs = MotionLimitDebouncePolicy::deadlineReached(
      serviceCount, state.debounce.deadlineCount)
      ? serviceCount - state.debounce.deadlineCount
      : 0u;
  state.confirmation.transitionCount = state.debounce.transitionCount;
  state.confirmation.restartCount = state.debounce.restartCount;
  state.confirmation.armFailureCount = state.armFailureCount;
  state.confirmation.candidatePosition = state.candidatePosition;
  state.confirmation.consumedPosition = state.candidatePosition;
  state.confirmation.rawExpiryAsserted = rawAsserted;
}

void recordArmFailure(Axis axis, AxisState& state, uint32_t serviceCount) {
  incrementSaturating(state.armFailureCount);
  incrementSaturating(g_armFailureCount);
  incrementSaturating(g_timingFailureCount);
  const auto decision =
      MotionLimitDebouncePolicy::forceHardwareConfirmation(state.debounce);
  if (decision == MotionLimitDebouncePolicy::HardwareDecision::Confirmed) {
    recordConfirmation(axis, state, serviceCount, readAsserted(state));
  }
}

bool armAxisCompare(Axis axis, AxisState& state) {
  if (!timerOperational()) {
    recordArmFailure(axis, state,
                     (g_timer != nullptr && g_timer->Instance != nullptr)
                         ? g_timer->Instance->CNT
                         : 0u);
    return false;
  }
  setAxisCompare(axis, state.debounce.deadlineCount);
  __HAL_TIM_CLEAR_FLAG(g_timer, axisFlag(axis));
  __HAL_TIM_ENABLE_IT(g_timer, axisInterrupt(axis));
  return true;
}

void beginCandidate(Axis axis,
                    AxisState& state,
                    uint32_t moveGeneration,
                    int32_t position) {
  const uint32_t now =
      (g_timer != nullptr && g_timer->Instance != nullptr)
          ? g_timer->Instance->CNT
          : 0u;
  state.moveGeneration = moveGeneration;
  state.candidatePosition = position;
  const bool operational = timerOperational();
  const auto decision = MotionLimitDebouncePolicy::beginHardwareCandidate(
      state.debounce,
      now,
      MotionLimitDebouncePolicy::kHardwareDebounceUs,
      operational);
  if (decision == MotionLimitDebouncePolicy::HardwareDecision::Confirmed) {
    incrementSaturating(state.armFailureCount);
    incrementSaturating(g_armFailureCount);
    incrementSaturating(g_timingFailureCount);
    recordConfirmation(axis, state, now, readAsserted(state));
    return;
  }
  if (decision == MotionLimitDebouncePolicy::HardwareDecision::Started) {
    (void)armAxisCompare(axis, state);
  }
}

void closeUnmaskRace(Axis axis, AxisState& state) {
  clearExti(state);
  unmaskExti(state);
  __DSB();
  const uint32_t mask = extiMask(state);
  const bool pending = mask != 0u && (EXTI->PR & mask) != 0u;
  const bool asserted = readAsserted(state);
  if (!asserted) {
    if (pending) {
      clearExti(state);
    }
    return;
  }

  // The assertion arrived while the line was being cleared/unmasked. Own it
  // here so it cannot wait for another physical edge.
  maskExti(state);
  clearExti(state);
  beginCandidate(axis,
                 state,
                 state.moveGeneration,
                 state.candidatePosition);
}

void serviceAxis(Axis axis) {
  AxisState& state = axisState(axis);
  disableAxisCompare(axis);
  if (state.debounce.phase != MotionLimitDebouncePolicy::Phase::Pending) {
    return;
  }
  const uint32_t serviceCount = g_timer->Instance->CNT;
  if (!timerOperational()) {
    recordArmFailure(axis, state, serviceCount);
    return;
  }
  const uint32_t mask = extiMask(state);
  const bool stickyTransition =
      mask != 0u && (EXTI->PR & mask) != 0u;
  const bool asserted = readAsserted(state);
  const auto decision = MotionLimitDebouncePolicy::evaluateHardwareExpiry(
      state.debounce,
      asserted,
      stickyTransition,
      serviceCount,
      MotionLimitDebouncePolicy::kHardwareDebounceUs,
      true);

  switch (decision) {
    case MotionLimitDebouncePolicy::HardwareDecision::Confirmed:
      recordConfirmation(axis, state, serviceCount, asserted);
      return;
    case MotionLimitDebouncePolicy::HardwareDecision::Restarted:
      clearExti(state);
      __DSB();
      state.debounce.startCount = g_timer->Instance->CNT;
      state.debounce.deadlineCount =
          state.debounce.startCount +
          MotionLimitDebouncePolicy::kHardwareDebounceUs;
      if (!readAsserted(state)) {
        MotionLimitDebouncePolicy::cancelHardware(state.debounce, true);
        closeUnmaskRace(axis, state);
        return;
      }
      if ((EXTI->PR & extiMask(state)) != 0u) {
        MotionLimitDebouncePolicy::noteHardwareTransition(state.debounce);
      }
      (void)armAxisCompare(axis, state);
      return;
    case MotionLimitDebouncePolicy::HardwareDecision::Rejected:
      closeUnmaskRace(axis, state);
      return;
    case MotionLimitDebouncePolicy::HardwareDecision::Pending:
      (void)armAxisCompare(axis, state);
      return;
    case MotionLimitDebouncePolicy::HardwareDecision::None:
    case MotionLimitDebouncePolicy::HardwareDecision::Started:
    case MotionLimitDebouncePolicy::HardwareDecision::AlreadyConfirmed:
      return;
  }
}

AxisSnapshot copyAxisSnapshot(const AxisState& state) {
  AxisSnapshot result{};
  result.debounce = MotionLimitDebouncePolicy::makeSnapshot(state.debounce);
  result.confirmation = state.confirmation;
  result.armFailureCount = state.armFailureCount;
  result.configured = state.configured;
  return result;
}

}  // namespace

bool initialize(TIM_HandleTypeDef* timer) {
  g_timer = timer;
  g_initialized = false;
  g_diagnosticActive = false;
  g_diagnosticComplete = false;

  if (g_timer == nullptr || g_timer->Instance != TIM5 ||
      !configurationValid()) {
    incrementSaturating(g_timingFailureCount);
    return false;
  }

  __HAL_TIM_DISABLE_IT(
      g_timer, TIM_IT_CC1 | TIM_IT_CC2 | TIM_IT_CC3 | TIM_IT_CC4);
  __HAL_TIM_CLEAR_FLAG(
      g_timer, TIM_FLAG_CC1 | TIM_FLAG_CC2 | TIM_FLAG_CC3 | TIM_FLAG_CC4);
  if (HAL_TIM_Base_Start(g_timer) != HAL_OK) {
    incrementSaturating(g_timingFailureCount);
    return false;
  }
  HAL_NVIC_SetPriority(TIM5_IRQn, kIrqPriority, 0u);
  HAL_NVIC_EnableIRQ(TIM5_IRQn);
  g_initialized = true;
  if (!timerOperational()) {
    g_initialized = false;
    incrementSaturating(g_timingFailureCount);
    return false;
  }
  return true;
}

bool attach(Axis axis,
            GPIO_TypeDef* port,
            uint16_t pin,
            bool activeHigh) {
  AxisState& state = axisState(axis);
  state.port = port;
  state.pin = pin;
  state.activeHigh = activeHigh;
  state.configured = port != nullptr && pin != 0u;
  return state.configured;
}

void onExtiFromIsr(Axis axis,
                   uint32_t moveGeneration,
                   int32_t position,
                   bool candidateAllowed) {
  AxisState& state = axisState(axis);
  if (!state.configured) {
    return;
  }
  if (state.debounce.phase == MotionLimitDebouncePolicy::Phase::Pending) {
    MotionLimitDebouncePolicy::noteHardwareTransition(state.debounce);
    return;
  }
  if (state.debounce.phase == MotionLimitDebouncePolicy::Phase::Confirmed ||
      !candidateAllowed || !readAsserted(state)) {
    return;
  }

  maskExti(state);
  clearExti(state);
  __DSB();
  if (!readAsserted(state)) {
    closeUnmaskRace(axis, state);
    return;
  }
  beginCandidate(axis, state, moveGeneration, position);
}

bool takeConfirmedFromIsr(Axis axis,
                          uint32_t moveGeneration,
                          int32_t consumedPosition) {
  AxisState& state = axisState(axis);
  if (state.debounce.phase != MotionLimitDebouncePolicy::Phase::Confirmed ||
      !MotionLimitDebouncePolicy::hardwareGenerationMatches(
          state.moveGeneration, moveGeneration) ||
      !state.confirmation.valid) {
    return false;
  }
  state.confirmation.consumedPosition = consumedPosition;
  return true;
}

void recordStopPositionFromIsr(Axis axis, int32_t stoppedPosition) {
  AxisState& state = axisState(axis);
  if (state.debounce.phase == MotionLimitDebouncePolicy::Phase::Confirmed &&
      state.confirmation.valid) {
    state.confirmation.consumedPosition = stoppedPosition;
  }
}

void cancel(Axis axis, bool rejectPending) {
  const uint32_t primask = __get_PRIMASK();
  __disable_irq();
  AxisState& state = axisState(axis);
  disableAxisCompare(axis);
  MotionLimitDebouncePolicy::cancelHardware(state.debounce, rejectPending);
  state.moveGeneration = 0u;
  clearExti(state);
  unmaskExti(state);
  if (primask == 0u) {
    __enable_irq();
  }
}

AxisSnapshot snapshot(Axis axis) {
  const uint32_t primask = __get_PRIMASK();
  __disable_irq();
  const AxisSnapshot result = copyAxisSnapshot(axisState(axis));
  if (primask == 0u) {
    __enable_irq();
  }
  return result;
}

ConfirmationSnapshot lastConfirmation(Axis axis) {
  return snapshot(axis).confirmation;
}

HealthSnapshot healthSnapshot() {
  HealthSnapshot result{};
  const uint32_t primask = __get_PRIMASK();
  __disable_irq();
  result.initialized = g_initialized;
  result.instanceValid = g_timer != nullptr && g_timer->Instance == TIM5;
  if (result.instanceValid) {
    result.timerInputHz = timerInputHz();
    result.prescaler = g_timer->Instance->PSC;
    result.period = g_timer->Instance->ARR;
    result.tickHz = result.timerInputHz / (result.prescaler + 1u);
    result.running = (g_timer->Instance->CR1 & TIM_CR1_CEN) != 0u;
  }
  result.nvicValid = nvicConfigurationValid();
  result.configurationValid = configurationValid();
  result.timingFailureCount = g_timingFailureCount;
  result.armFailureCount = g_armFailureCount;
  result.diagnosticActive = g_diagnosticActive;
  result.diagnosticComplete = g_diagnosticComplete;
  result.diagnosticStartCount = g_diagnosticStartCount;
  result.diagnosticServiceCount = g_diagnosticServiceCount;
  result.diagnosticElapsedUs =
      g_diagnosticServiceCount - g_diagnosticStartCount;
  if (primask == 0u) {
    __enable_irq();
  }
  return result;
}

bool healthy() {
  return timerOperational();
}

bool armDiagnostic() {
  const uint32_t primask = __get_PRIMASK();
  __disable_irq();
  if (!timerOperational() || g_diagnosticActive) {
    incrementSaturating(g_timingFailureCount);
    if (primask == 0u) {
      __enable_irq();
    }
    return false;
  }
  g_diagnosticStartCount = g_timer->Instance->CNT;
  g_diagnosticServiceCount = g_diagnosticStartCount;
  g_diagnosticComplete = false;
  g_diagnosticActive = true;
  g_timer->Instance->CCR3 =
      g_diagnosticStartCount +
      MotionLimitDebouncePolicy::kHardwareDebounceUs;
  __HAL_TIM_CLEAR_FLAG(g_timer, TIM_FLAG_CC3);
  __HAL_TIM_ENABLE_IT(g_timer, TIM_IT_CC3);
  if (primask == 0u) {
    __enable_irq();
  }
  return true;
}

void handleIrq() {
  if (g_timer == nullptr || g_timer->Instance == nullptr) {
    return;
  }
  if (__HAL_TIM_GET_FLAG(g_timer, TIM_FLAG_CC1) != RESET &&
      __HAL_TIM_GET_IT_SOURCE(g_timer, TIM_IT_CC1) != RESET) {
    serviceAxis(Axis::X);
  }
  if (__HAL_TIM_GET_FLAG(g_timer, TIM_FLAG_CC2) != RESET &&
      __HAL_TIM_GET_IT_SOURCE(g_timer, TIM_IT_CC2) != RESET) {
    serviceAxis(Axis::Y);
  }
  if (__HAL_TIM_GET_FLAG(g_timer, TIM_FLAG_CC3) != RESET &&
      __HAL_TIM_GET_IT_SOURCE(g_timer, TIM_IT_CC3) != RESET) {
    __HAL_TIM_DISABLE_IT(g_timer, TIM_IT_CC3);
    __HAL_TIM_CLEAR_FLAG(g_timer, TIM_FLAG_CC3);
    g_diagnosticServiceCount = g_timer->Instance->CNT;
    g_diagnosticActive = false;
    g_diagnosticComplete = true;
  }
}

}  // namespace MotionLimitDebounceTimer

extern TIM_HandleTypeDef htim5;

extern "C" void MX_MotionLimitDebounceTimer_Init(void) {
  (void)MotionLimitDebounceTimer::initialize(&htim5);
}

extern "C" void MotionLimitDebounceTimer_IRQHandler(void) {
  MotionLimitDebounceTimer::handleIrq();
}
