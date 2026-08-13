/*
 * Gantry.cpp
 *
 *  Created on: Jun 18, 2025
 *      Author: conar
 */

#include "Gantry.h"
#include "Stepper.h"
#include "Orchestrator.h"
#include "cmsis_os.h"      // for osDelay
#include "task.h"
#include <algorithm>       // for std::max
#include <cmath>           // for std::abs
#include <limits>
#include <utility>   // <-- for std::pair

// the three C APIs you already have for your steppers:
extern "C" void MX_STEPPERX_Init(void);
extern "C" void MX_STEPPERY_Init(void);
extern "C" void MX_STEPPERZ_Init(void);

extern "C" void MX_STEPPERX_Move(uint8_t dir, uint32_t steps, uint32_t freqHz,uint32_t accelSteps);
extern "C" void MX_STEPPERY_Move(uint8_t dir, uint32_t steps, uint32_t freqHz,uint32_t accelSteps);
extern "C" void MX_STEPPERZ_Move(uint8_t dir, uint32_t steps, uint32_t freqHz,uint32_t accelSteps);

extern "C" uint8_t MX_STEPPERX_IsBusy(void);
extern "C" uint8_t MX_STEPPERY_IsBusy(void);
extern "C" uint8_t MX_STEPPERZ_IsBusy(void);

extern "C" int32_t MX_STEPPERX_GetPos(void);
extern "C" int32_t MX_STEPPERY_GetPos(void);
extern "C" int32_t MX_STEPPERZ_GetPos(void);

extern TIM_HandleTypeDef htim2;
extern TIM_HandleTypeDef htim7;

#if LC_COORDINATED_XY_ISR_INSTRUMENTATION_ENABLE != 0
extern "C" {
volatile uint8_t g_lcCoordinatedTim2IrqTimingArmed = 0u;
volatile uint8_t g_lcCoordinatedTim2IrqEntryValid = 0u;
volatile uint8_t g_lcCoordinatedTim2IrqEntryTimerValid = 0u;
volatile uint32_t g_lcCoordinatedTim2IrqEntryCycle = 0u;
volatile uint32_t g_lcCoordinatedTim2IrqEntryTimerCount = 0u;
volatile uint32_t g_lcCoordinatedTim2IrqEntryTimerArr = 0u;
}
#endif

namespace {

#if defined(__GNUC__) && !defined(UNIT_TEST)
#define LC_COORDINATED_HW_OPTIMIZED __attribute__((optimize("O2"), hot))
#define LC_COORDINATED_HW_ALWAYS_INLINE \
  inline __attribute__((always_inline, optimize("O2")))
#else
#define LC_COORDINATED_HW_OPTIMIZED
#define LC_COORDINATED_HW_ALWAYS_INLINE inline
#endif

bool gantryIsApb2Timer(TIM_TypeDef* instance) {
  return instance == TIM1 || instance == TIM8 || instance == TIM9 ||
         instance == TIM10 || instance == TIM11;
}

uint32_t gantryTimerInputHz(TIM_HandleTypeDef* timer, uint16_t prescaler) {
  RCC_ClkInitTypeDef clocks{};
  uint32_t flashLatency = 0u;
  HAL_RCC_GetClockConfig(&clocks, &flashLatency);
  const bool apb2 = gantryIsApb2Timer(timer->Instance);
  const uint32_t pclk = apb2 ? HAL_RCC_GetPCLK2Freq() : HAL_RCC_GetPCLK1Freq();
  const bool doubled = apb2
      ? clocks.APB2CLKDivider != RCC_HCLK_DIV1
      : clocks.APB1CLKDivider != RCC_HCLK_DIV1;
  return (doubled ? pclk * 2u : pclk) / (static_cast<uint32_t>(prescaler) + 1u);
}

uint32_t gantryTimerMaxArr(TIM_HandleTypeDef* timer) {
  return (timer->Instance == TIM2 || timer->Instance == TIM5)
      ? std::numeric_limits<uint32_t>::max()
      : 0xFFFFu;
}

LC_COORDINATED_HW_ALWAYS_INLINE
uint32_t gantryCycleNow() {
  return DWT->CYCCNT;
}

LC_COORDINATED_HW_ALWAYS_INLINE
CoordinatedXyIsrInstrumentation::Phase gantryTimingPhase(
    CoordinatedXyPlanner::ProfilePhase phase) {
  switch (phase) {
    case CoordinatedXyPlanner::ProfilePhase::Acceleration:
      return CoordinatedXyIsrInstrumentation::Phase::Acceleration;
    case CoordinatedXyPlanner::ProfilePhase::Deceleration:
      return CoordinatedXyIsrInstrumentation::Phase::Deceleration;
    case CoordinatedXyPlanner::ProfilePhase::Cruise:
    default:
      return CoordinatedXyIsrInstrumentation::Phase::Cruise;
  }
}

void gantryEnableCycleCounter() {
  CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
  if ((DWT->CTRL & DWT_CTRL_CYCCNTENA_Msk) == 0u) {
    DWT->CYCCNT = 0u;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
  }
}

bool gantryCycleCounterReady() {
  gantryEnableCycleCounter();
  if ((DWT->CTRL & DWT_CTRL_CYCCNTENA_Msk) == 0u) return false;
  const uint32_t before = DWT->CYCCNT;
  __NOP();
  __NOP();
  __NOP();
  __NOP();
  __NOP();
  __NOP();
  __NOP();
  __NOP();
  return DWT->CYCCNT != before;
}

LC_COORDINATED_HW_ALWAYS_INLINE
void gantryStopAndClearUpdateTimer(TIM_HandleTypeDef* timer) {
  if (timer == nullptr || timer->Instance == nullptr) return;

  // Coordinated execution owns these base timers exclusively. Avoid the
  // comparatively expensive HAL stop path on the terminal edge so the final
  // pulse has the same bounded ISR budget as every other edge.
  timer->Instance->DIER &= ~TIM_IT_UPDATE;
  timer->Instance->CR1 &= ~TIM_CR1_CEN;
  timer->Instance->SR = ~TIM_FLAG_UPDATE;
  // HAL_TIM_Base_Start_IT() refuses a timer whose handle is still BUSY.
  // Mirror HAL_TIM_Base_Stop_IT()'s ownership handoff so a terminal
  // coordinated move can be followed immediately by a legacy move.
  timer->State = HAL_TIM_STATE_READY;
}

}  // namespace


//----------------------------------------------------------------------
// Singleton
// singleton init
Gantry* Gantry::_instance = nullptr;

Gantry* Gantry::instance() {
  return _instance;
}

Gantry::Gantry() {};

void Gantry::begin() {
  _instance = this;
  _coordinatedExecutionMode = CoordinatedXyExecutor::ExecutionMode::TwoEdge;
}

bool Gantry::setCoordinatedExecutionModeForDiagnostics(
    CoordinatedXyExecutor::ExecutionMode mode) {
  if (mode != CoordinatedXyExecutor::ExecutionMode::TwoEdge &&
      mode != CoordinatedXyExecutor::ExecutionMode::CompleteStep) {
    return false;
  }
  if (mode == CoordinatedXyExecutor::ExecutionMode::CompleteStep &&
      !gantryCycleCounterReady()) {
    return false;
  }
  taskENTER_CRITICAL();
  Stepper* sx = Stepper::stepperX();
  Stepper* sy = Stepper::stepperY();
  const bool available = !_coordinatedTimerOwned &&
      !CoordinatedXyExecutor::isActive(_coordinatedCursor) &&
      (sx == nullptr || !sx->_coordinatedReserved) &&
      (sy == nullptr || !sy->_coordinatedReserved);
  if (available) {
    _coordinatedExecutionMode = mode;
  }
  taskEXIT_CRITICAL();
  return available;
}

CoordinatedXyExecutor::ExecutionMode Gantry::coordinatedExecutionMode() const {
  taskENTER_CRITICAL();
  const CoordinatedXyExecutor::ExecutionMode mode = _coordinatedExecutionMode;
  taskEXIT_CRITICAL();
  return mode;
}

CoordinatedStartStatus Gantry::moveTo(int32_t x,
                                      int32_t y,
                                      uint32_t feedHz) {
#if LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE != 0
	(void)feedHz;
	const GantryPosition current = getPosition();
	return startCoordinatedXY(
	    static_cast<int64_t>(x) - current.x,
	    static_cast<int64_t>(y) - current.y,
	    0u);
#else
	const int64_t dx = static_cast<int64_t>(x) - MX_STEPPERX_GetPos();
	const int64_t dy = static_cast<int64_t>(y) - MX_STEPPERY_GetPos();
	if (dx < std::numeric_limits<int32_t>::min() ||
	    dx > std::numeric_limits<int32_t>::max() ||
	    dy < std::numeric_limits<int32_t>::min() ||
	    dy > std::numeric_limits<int32_t>::max()) {
	  return CoordinatedStartStatus::PositionOutOfRange;
	}
	return moveBy(static_cast<int32_t>(dx),
	              static_cast<int32_t>(dy),
	              0,
	              feedHz);
#endif
}
//----------------------------------------------------------------------
CoordinatedStartStatus Gantry::moveBy(int32_t dx,
                                      int32_t dy,
                                      int32_t dz,
                                      uint32_t /*feedHz unused*/) {
  if (dz != 0 && (dx != 0 || dy != 0)) {
    return CoordinatedStartStatus::UnsupportedMixedAxis;
  }
#if LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE != 0
  if (dz == 0) {
    return startCoordinatedXY(dx, dy, 0u);
  }
#endif
  const uint32_t Nx = static_cast<uint32_t>(
      dx < 0 ? -static_cast<int64_t>(dx) : static_cast<int64_t>(dx));
  const uint32_t Ny = static_cast<uint32_t>(
      dy < 0 ? -static_cast<int64_t>(dy) : static_cast<int64_t>(dy));
  const uint32_t Nz = static_cast<uint32_t>(
      dz < 0 ? -static_cast<int64_t>(dz) : static_cast<int64_t>(dz));

  const uint32_t Nmax = std::max(std::max(Nx, Ny), Nz);
  if (Nmax == 0u) return CoordinatedStartStatus::Immediate;

  Stepper* sx = Stepper::stepperX();
  Stepper* sy = Stepper::stepperY();
  Stepper* sz = Stepper::stepperZ();
  if (!sx || !sy || !sz) return CoordinatedStartStatus::HardwareMismatch;

  // Find which axis is the "longest" for this move
  Stepper* slong = (Nmax == Nx) ? sx : (Nmax == Ny ? sy : sz);
  const uint32_t feedRefHz = slong->maxSpeedHz();  // run the longest at its own max

  auto planHz = [&](Stepper* s, uint32_t Nsteps)->uint32_t {
    if (Nsteps == 0u) return 0u;
    uint64_t v_scaled = (uint64_t)feedRefHz * (uint64_t)Nsteps / (uint64_t)Nmax; // proportional
    uint32_t v = (uint32_t)std::min<uint64_t>(v_scaled, s->maxSpeedHz());        // clamp to axis cap
    if (v < _minStepHz) v = _minStepHz;                                          // floor for smoothness
    return v;
  };

  const uint32_t fx = planHz(sx, Nx);
  const uint32_t fy = planHz(sy, Ny);
  const uint32_t fz = planHz(sz, Nz);

  MX_STEPPERX_Move(dx >= 0, Nx, fx, /*accelSteps ignored*/ 0u);
  MX_STEPPERY_Move(dy >= 0, Ny, fy, /*accelSteps ignored*/ 0u);
  MX_STEPPERZ_Move(dz >= 0, Nz, fz, /*accelSteps ignored*/ 0u);
  return CoordinatedStartStatus::Started;
}

CoordinatedStartStatus Gantry::startCoordinatedXY(int64_t dx,
                                                  int64_t dy,
                                                  uint32_t requestedRateHz) {
#if LC_COORDINATED_XY_EXECUTOR_ENABLE == 0
  (void)dx;
  (void)dy;
  (void)requestedRateHz;
  _coordinatedStartStatus = CoordinatedStartStatus::Disabled;
  return _coordinatedStartStatus;
#else
  Stepper* sx = Stepper::stepperX();
  Stepper* sy = Stepper::stepperY();
  Stepper* sz = Stepper::stepperZ();
  if (sx == nullptr || sy == nullptr || sz == nullptr ||
      sx->_htim != &htim2 || sy->_htim != &htim7 ||
      sx->_htim == sy->_htim) {
    _coordinatedStartStatus = CoordinatedStartStatus::HardwareMismatch;
    return _coordinatedStartStatus;
  }

  taskENTER_CRITICAL();
  const bool alreadyActive = _coordinatedTimerOwned ||
      CoordinatedXyExecutor::isActive(_coordinatedCursor);
  taskEXIT_CRITICAL();
  if (alreadyActive ||
      sx->isBusy() || sx->_homeSequenceActive || sx->_legacyMoveStartPending ||
      sy->isBusy() || sy->_homeSequenceActive || sy->_legacyMoveStartPending ||
      sz->isBusy() || sz->_homeSequenceActive || sz->_legacyMoveStartPending) {
    _coordinatedStartStatus = CoordinatedStartStatus::Busy;
    return _coordinatedStartStatus;
  }

  const int64_t targetX = static_cast<int64_t>(sx->_pos) + dx;
  const int64_t targetY = static_cast<int64_t>(sy->_pos) + dy;
  if (targetX < std::numeric_limits<int32_t>::min() ||
      targetX > std::numeric_limits<int32_t>::max() ||
      targetY < std::numeric_limits<int32_t>::min() ||
      targetY > std::numeric_limits<int32_t>::max()) {
    _coordinatedStartStatus = CoordinatedStartStatus::PositionOutOfRange;
    return _coordinatedStartStatus;
  }

  auto accelerationLimit = [](Stepper* stepper) -> uint32_t {
    const float acceleration = stepper->accelStepsPerSec2();
    if (!std::isfinite(acceleration) || acceleration < 1.0f ||
        acceleration > static_cast<float>(std::numeric_limits<uint32_t>::max())) {
      return 0u;
    }
    return static_cast<uint32_t>(acceleration);
  };

  CoordinatedXyPlanner::PlanRequest request{};
  request.deltaX = dx;
  request.deltaY = dy;
  request.requestedMasterRateHz = requestedRateHz;
  request.xLimits = {sx->maxSpeedHz(), accelerationLimit(sx)};
  request.yLimits = {sy->maxSpeedHz(), accelerationLimit(sy)};
  request.timer = {
      gantryTimerInputHz(sx->_htim, sx->_prescaler),
      gantryTimerMaxArr(sx->_htim),
      2000u,
  };

  CoordinatedXyPlanner::CoordinatedXyPlan plan{};
  const CoordinatedXyPlanner::PlanStatus planStatus =
      CoordinatedXyPlanner::prepare(request, plan);
  if (planStatus == CoordinatedXyPlanner::PlanStatus::Immediate) {
    _coordinatedPlan = plan;
    (void)CoordinatedXyExecutor::arm(
        plan, _coordinatedCursor, _coordinatedExecutionMode);
    sx->_targetPos = sx->_pos;
    sy->_targetPos = sy->_pos;
    _coordinatedX = sx;
    _coordinatedY = sy;
    _coordinatedMasterTimer = sx->_htim;
    _coordinatedTimerOwned = false;
    _coordinatedProgrammedArr = 0u;
    _coordinatedPulseHighCycles = 0u;
    _resetCoordinatedInstrumentation(0u);
#if LC_COORDINATED_XY_ISR_INSTRUMENTATION_ENABLE != 0
    CoordinatedXyIsrInstrumentation::finishWithoutSample(
        _coordinatedTiming, gantryCycleNow(), false);
#endif
    _coordinatedStartStatus = CoordinatedStartStatus::Immediate;
    xEventGroupClearBits(Orchestrator::getDoneEvents(),
                         BIT_STEPPER1_DONE | BIT_STEPPER2_DONE);
    xEventGroupSetBits(Orchestrator::getDoneEvents(),
                       BIT_STEPPER1_DONE | BIT_STEPPER2_DONE);
    return _coordinatedStartStatus;
  }
  if (planStatus != CoordinatedXyPlanner::PlanStatus::Ready) {
    _coordinatedStartStatus = CoordinatedStartStatus::InvalidPlan;
    return _coordinatedStartStatus;
  }
  if (sx->_isLimitAsserted() || sy->_isLimitAsserted()) {
    _coordinatedStartStatus = CoordinatedStartStatus::LimitAsserted;
    return _coordinatedStartStatus;
  }

  const CoordinatedXyExecutor::ExecutionMode executionMode =
      coordinatedExecutionMode();
  uint32_t completeStepTargetArr = 0u;
  uint32_t completeStepStartArr = 0u;
  uint32_t pulseHighCycles = 0u;
  if (executionMode == CoordinatedXyExecutor::ExecutionMode::CompleteStep) {
    pulseHighCycles = CoordinatedXyExecutor::minimumPulseCoreCycles(
        HAL_RCC_GetHCLKFreq(), plan.timer.minPulseNs);
    if (!gantryCycleCounterReady() || pulseHighCycles == 0u ||
        !CoordinatedXyExecutor::fullPeriodArr(
            plan.targetArr, plan.timer.maxArr, completeStepTargetArr) ||
        !CoordinatedXyExecutor::fullPeriodArr(
            plan.startArr, plan.timer.maxArr, completeStepStartArr) ||
        completeStepTargetArr > completeStepStartArr) {
      _coordinatedStartStatus = CoordinatedStartStatus::HardwareMismatch;
      return _coordinatedStartStatus;
    }
  }

  CoordinatedXyExecutor::Cursor executorCursor{};
  if (CoordinatedXyExecutor::arm(plan, executorCursor, executionMode) !=
      CoordinatedXyExecutor::ArmStatus::Ready) {
    _coordinatedStartStatus = CoordinatedStartStatus::InvalidPlan;
    return _coordinatedStartStatus;
  }
  uint32_t firstProgrammedArr = executorCursor.cachedEvent.arr;
  if (executionMode == CoordinatedXyExecutor::ExecutionMode::CompleteStep &&
      !CoordinatedXyExecutor::fullPeriodArr(
          executorCursor.cachedEvent.arr,
          plan.timer.maxArr,
          firstProgrammedArr)) {
    _coordinatedStartStatus = CoordinatedStartStatus::HardwareMismatch;
    return _coordinatedStartStatus;
  }

  const CoordinatedXyExecutor::AxisReservationState xReservation{
      sx->_togglesRemaining != 0u || sx->_legacyMoveStartPending,
      sx->_homeSequenceActive,
      sx->_coordinatedReserved,
  };
  const CoordinatedXyExecutor::AxisReservationState yReservation{
      sy->_togglesRemaining != 0u || sy->_legacyMoveStartPending,
      sy->_homeSequenceActive,
      sy->_coordinatedReserved,
  };
  if (CoordinatedXyExecutor::evaluateReservation(xReservation, yReservation) !=
      CoordinatedXyExecutor::ReservationStatus::Ready) {
    _coordinatedStartStatus = CoordinatedStartStatus::Busy;
    return _coordinatedStartStatus;
  }

  if (!sx->_tryReserveCoordinated()) {
    _coordinatedStartStatus = CoordinatedStartStatus::Busy;
    return _coordinatedStartStatus;
  }
  if (!sy->_tryReserveCoordinated()) {
    sx->_releaseCoordinatedReservation();
    _coordinatedStartStatus = CoordinatedStartStatus::Busy;
    return _coordinatedStartStatus;
  }

  // The position and limit checks above are intentionally repeated after both
  // reservations. A legacy move may finish between planning and reservation;
  // once reserved, neither position can change before the coordinated start.
  const int64_t reservedTargetX = static_cast<int64_t>(sx->_pos) + dx;
  const int64_t reservedTargetY = static_cast<int64_t>(sy->_pos) + dy;
  if (reservedTargetX < std::numeric_limits<int32_t>::min() ||
      reservedTargetX > std::numeric_limits<int32_t>::max() ||
      reservedTargetY < std::numeric_limits<int32_t>::min() ||
      reservedTargetY > std::numeric_limits<int32_t>::max()) {
    sy->_releaseCoordinatedReservation();
    sx->_releaseCoordinatedReservation();
    _coordinatedStartStatus = CoordinatedStartStatus::PositionOutOfRange;
    return _coordinatedStartStatus;
  }
  if (sx->_isLimitAsserted() || sy->_isLimitAsserted()) {
    sy->_releaseCoordinatedReservation();
    sx->_releaseCoordinatedReservation();
    _coordinatedStartStatus = CoordinatedStartStatus::LimitAsserted;
    return _coordinatedStartStatus;
  }

  HAL_TIM_Base_Stop_IT(sx->_htim);
  HAL_TIM_Base_Stop_IT(sy->_htim);
  __HAL_TIM_CLEAR_FLAG(sx->_htim, TIM_FLAG_UPDATE);
  __HAL_TIM_CLEAR_FLAG(sy->_htim, TIM_FLAG_UPDATE);

  const bool xParticipates = plan.xSteps != 0u;
  const bool yParticipates = plan.ySteps != 0u;
  sx->_prepareCoordinatedAxis(
      xParticipates,
      plan.xDirection == CoordinatedXyPlanner::Direction::Positive,
      static_cast<int32_t>(reservedTargetX));
  sy->_prepareCoordinatedAxis(
      yParticipates,
      plan.yDirection == CoordinatedXyPlanner::Direction::Positive,
      static_cast<int32_t>(reservedTargetY));

  _coordinatedPlan = plan;
  _coordinatedCursor = executorCursor;
  _coordinatedX = sx;
  _coordinatedY = sy;
  _coordinatedMasterTimer = sx->_htim;
  _coordinatedPulseHighCycles = pulseHighCycles;
  _resetCoordinatedInstrumentation(_coordinatedCursor.cachedEvent.arr);
  xEventGroupClearBits(Orchestrator::getDoneEvents(),
                       BIT_STEPPER1_DONE | BIT_STEPPER2_DONE);

  __HAL_TIM_SET_PRESCALER(_coordinatedMasterTimer, sx->_prescaler);
  _coordinatedProgrammedArr = firstProgrammedArr;
  __HAL_TIM_SET_AUTORELOAD(_coordinatedMasterTimer, firstProgrammedArr);
  __HAL_TIM_SET_COUNTER(_coordinatedMasterTimer, 0u);
  __HAL_TIM_CLEAR_FLAG(_coordinatedMasterTimer, TIM_FLAG_UPDATE);

  taskENTER_CRITICAL();
  _coordinatedTimerOwned = true;
#if LC_COORDINATED_XY_ISR_INSTRUMENTATION_ENABLE != 0
  g_lcCoordinatedTim2IrqTimingArmed = 1u;
#endif
  const CoordinatedXyExecutor::ControlDisposition startDisposition =
      CoordinatedXyExecutor::start(_coordinatedCursor);
  taskEXIT_CRITICAL();
  if (startDisposition != CoordinatedXyExecutor::ControlDisposition::Deferred ||
      HAL_TIM_Base_Start_IT(_coordinatedMasterTimer) != HAL_OK) {
    taskENTER_CRITICAL();
    (void)CoordinatedXyExecutor::requestCancel(_coordinatedCursor);
    _finishCoordinatedHardware(true);
#if LC_COORDINATED_XY_ISR_INSTRUMENTATION_ENABLE != 0
    CoordinatedXyIsrInstrumentation::finishWithoutSample(
        _coordinatedTiming, gantryCycleNow(), true);
#endif
    taskEXIT_CRITICAL();
    _coordinatedStartStatus = CoordinatedStartStatus::HardwareMismatch;
    return _coordinatedStartStatus;
  }

  _coordinatedStartStatus = CoordinatedStartStatus::Started;
  return _coordinatedStartStatus;
#endif
}

void Gantry::_resetCoordinatedInstrumentation(uint32_t firstArr) {
  gantryEnableCycleCounter();
#if LC_COORDINATED_XY_ISR_INSTRUMENTATION_ENABLE != 0
  g_lcCoordinatedTim2IrqTimingArmed = 0u;
  g_lcCoordinatedTim2IrqEntryValid = 0u;
  g_lcCoordinatedTim2IrqEntryTimerValid = 0u;
  g_lcCoordinatedTim2IrqEntryCycle = 0u;
  g_lcCoordinatedTim2IrqEntryTimerCount = 0u;
  g_lcCoordinatedTim2IrqEntryTimerArr = 0u;
#endif
  _coordinatedTim7Interrupts = 0u;
  _coordinatedPendingUpdateCount = 0u;
  _coordinatedMaxIsrCycles = 0u;
  _coordinatedLimitAbortRequestCount = 0u;
  _coordinatedRawLimitAbortCount = 0u;
  _coordinatedLimitRequestRisingEdges = 0u;
  _coordinatedLimitRequestFallingEdges = 0u;
  _coordinatedArrMin = firstArr;
  _coordinatedArrMax = firstArr;
#if LC_COORDINATED_XY_ISR_INSTRUMENTATION_ENABLE != 0
  CoordinatedXyIsrInstrumentation::reset(
      _coordinatedTiming, gantryCycleNow());
#else
  _coordinatedTiming = CoordinatedXyIsrInstrumentation::State{};
#endif
}

LC_COORDINATED_HW_ALWAYS_INLINE
void Gantry::_observeCoordinatedArr(uint32_t arr) {
  if (arr < _coordinatedArrMin) _coordinatedArrMin = arr;
  if (arr > _coordinatedArrMax) _coordinatedArrMax = arr;
}

LC_COORDINATED_HW_ALWAYS_INLINE
void Gantry::_finishCoordinatedHardware(bool aborted,
                                        bool stepStateKnownLow) {
  gantryStopAndClearUpdateTimer(_coordinatedMasterTimer);
  if (_coordinatedY != nullptr) {
    gantryStopAndClearUpdateTimer(_coordinatedY->_htim);
  }
  if (_coordinatedX != nullptr) {
    if (aborted) {
      if (stepStateKnownLow) {
        _coordinatedX->_finishAbortedCoordinatedAxisFromLow();
      } else {
        _coordinatedX->_finishCoordinatedAxis(true);
      }
    } else {
      _coordinatedX->_finishCompletedCoordinatedAxisFromLow();
    }
  }
  if (_coordinatedY != nullptr) {
    if (aborted) {
      if (stepStateKnownLow) {
        _coordinatedY->_finishAbortedCoordinatedAxisFromLow();
      } else {
        _coordinatedY->_finishCoordinatedAxis(true);
      }
    } else {
      _coordinatedY->_finishCompletedCoordinatedAxisFromLow();
    }
  }
  _coordinatedTimerOwned = false;
#if LC_COORDINATED_XY_ISR_INSTRUMENTATION_ENABLE != 0
  g_lcCoordinatedTim2IrqTimingArmed = 0u;
  g_lcCoordinatedTim2IrqEntryValid = 0u;
#endif
}

LC_COORDINATED_HW_ALWAYS_INLINE
void Gantry::_finishCoordinatedFromIsr(bool aborted,
                                       BaseType_t* woken,
                                       bool timingSampleWillFollow) {
#if LC_COORDINATED_XY_ISR_INSTRUMENTATION_ENABLE != 0
  if (aborted) {
    CoordinatedXyIsrInstrumentation::markAborted(_coordinatedTiming);
  }
#endif
  // Executor terminal transitions are accepted only while STEP is already
  // low: either before a new rise or immediately after the accounted fall.
  _finishCoordinatedHardware(aborted, true);
  xEventGroupSetBitsFromISR(Orchestrator::getDoneEvents(),
                            BIT_STEPPER1_DONE | BIT_STEPPER2_DONE,
                            woken);
#if LC_COORDINATED_XY_ISR_INSTRUMENTATION_ENABLE != 0
  if (!timingSampleWillFollow) {
    CoordinatedXyIsrInstrumentation::finishWithoutSample(
        _coordinatedTiming, gantryCycleNow(), aborted);
  }
#else
  (void)timingSampleWillFollow;
#endif
}

LC_COORDINATED_HW_OPTIMIZED
bool Gantry::_handleCoordinatedTimerFromIsr(TIM_HandleTypeDef* htim) {
#if LC_COORDINATED_XY_EXECUTOR_ENABLE == 0
  (void)htim;
  return false;
#else
  if (!_coordinatedTimerOwned || htim == nullptr) return false;
  if (_coordinatedY != nullptr && htim == _coordinatedY->_htim) {
    ++_coordinatedTim7Interrupts;
    HAL_TIM_Base_Stop_IT(htim);
    __HAL_TIM_CLEAR_FLAG(htim, TIM_FLAG_UPDATE);
    return true;
  }
  if (htim != _coordinatedMasterTimer) return false;

#if LC_COORDINATED_XY_ISR_INSTRUMENTATION_ENABLE != 0
  const bool irqEntryValid = g_lcCoordinatedTim2IrqEntryValid != 0u;
  const uint32_t irqEntryCycle = g_lcCoordinatedTim2IrqEntryCycle;
  g_lcCoordinatedTim2IrqEntryValid = 0u;
#endif
  const uint32_t entryCycle = gantryCycleNow();
#if LC_COORDINATED_XY_ISR_INSTRUMENTATION_ENABLE != 0
  const CoordinatedXyIsrInstrumentation::Phase timingPhase =
      gantryTimingPhase(_coordinatedCursor.cachedEvent.phase);
  const uint32_t timingArr = _coordinatedProgrammedArr;
#endif
  CoordinatedXyExecutor::ControlDisposition observedLimit =
      CoordinatedXyExecutor::ControlDisposition::AlreadySatisfied;
  if (_coordinatedX != nullptr &&
      _coordinatedX->_coordinatedLimitAssertedFast()) {
    if (_coordinatedLimitAbortRequestCount == 0u) {
      _coordinatedLimitRequestRisingEdges = _coordinatedCursor.risingEdges;
      _coordinatedLimitRequestFallingEdges = _coordinatedCursor.fallingEdges;
    }
    ++_coordinatedLimitAbortRequestCount;
    ++_coordinatedRawLimitAbortCount;
    observedLimit = CoordinatedXyExecutor::requestLimitAbort(
        _coordinatedCursor, CoordinatedXyExecutor::LimitAxis::X);
  } else if (_coordinatedY != nullptr &&
             _coordinatedY->_coordinatedLimitAssertedFast()) {
    if (_coordinatedLimitAbortRequestCount == 0u) {
      _coordinatedLimitRequestRisingEdges = _coordinatedCursor.risingEdges;
      _coordinatedLimitRequestFallingEdges = _coordinatedCursor.fallingEdges;
    }
    ++_coordinatedLimitAbortRequestCount;
    ++_coordinatedRawLimitAbortCount;
    observedLimit = CoordinatedXyExecutor::requestLimitAbort(
        _coordinatedCursor, CoordinatedXyExecutor::LimitAxis::Y);
  }

  if (observedLimit == CoordinatedXyExecutor::ControlDisposition::StopNow) {
    BaseType_t woken = pdFALSE;
    _finishCoordinatedFromIsr(true, &woken, true);
    const uint32_t recordedExitCycle = gantryCycleNow();
#if LC_COORDINATED_XY_ISR_INSTRUMENTATION_ENABLE != 0
    const bool entryTimerValid =
        g_lcCoordinatedTim2IrqEntryTimerValid != 0u;
    const uint32_t entryTimerCount =
        g_lcCoordinatedTim2IrqEntryTimerCount;
    const uint32_t entryTimerArr = g_lcCoordinatedTim2IrqEntryTimerArr;
    g_lcCoordinatedTim2IrqEntryTimerValid = 0u;
    CoordinatedXyIsrInstrumentation::recordSample(
        _coordinatedTiming,
        timingPhase,
        entryCycle,
        recordedExitCycle,
        timingArr,
        false,
        false,
        true);
    const uint32_t finalExitCycle = gantryCycleNow();
    CoordinatedXyIsrInstrumentation::completeSampleTiming(
        _coordinatedTiming,
        timingPhase,
        entryCycle,
        recordedExitCycle,
        finalExitCycle,
        true);
    CoordinatedXyIsrInstrumentation::beginIrqPathSample(
        _coordinatedTiming,
        irqEntryValid,
        irqEntryCycle,
        entryTimerValid,
        entryTimerCount,
        entryTimerArr,
        entryCycle,
        false,
        true);
#else
    const uint32_t finalExitCycle = recordedExitCycle;
#endif
    const uint32_t cycles = finalExitCycle - entryCycle;
    if (cycles > _coordinatedMaxIsrCycles) {
      _coordinatedMaxIsrCycles = cycles;
    }
    portYIELD_FROM_ISR(woken);
    return true;
  }

  CoordinatedXyExecutor::TickResult tick{};
  CoordinatedXyExecutor::TickStatus status =
      CoordinatedXyExecutor::TickStatus::InvalidState;
  const bool completeStepMode = _coordinatedCursor.executionMode ==
      CoordinatedXyExecutor::ExecutionMode::CompleteStep;
  if (completeStepMode) {
    CoordinatedXyExecutor::TickResult prepared{};
    status = CoordinatedXyExecutor::prepareCompleteStep(
        _coordinatedPlan, _coordinatedCursor, prepared);
    tick = prepared;
    if (status == CoordinatedXyExecutor::TickStatus::Raised) {
      const uint8_t preparedMask = static_cast<uint8_t>(prepared.mask);
      const bool preparedX =
          (preparedMask & static_cast<uint8_t>(
              CoordinatedXyPlanner::StepMask::X)) != 0u;
      const bool preparedY =
          (preparedMask & static_cast<uint8_t>(
              CoordinatedXyPlanner::StepMask::Y)) != 0u;
      if (!preparedX && !preparedY) {
        status = CoordinatedXyExecutor::forcePlannerFault(
            _coordinatedCursor, tick);
      } else {
        if (preparedX) _coordinatedX->_writeCoordinatedStep(true);
        if (preparedY) _coordinatedY->_writeCoordinatedStep(true);
        const uint32_t pulseStartCycle = gantryCycleNow();
        while (static_cast<uint32_t>(gantryCycleNow() - pulseStartCycle) <
               _coordinatedPulseHighCycles) {
          __NOP();
        }
        const uint32_t pulseHighCycles =
            static_cast<uint32_t>(gantryCycleNow() - pulseStartCycle);
        if (preparedX) _coordinatedX->_writeCoordinatedStep(false);
        if (preparedY) _coordinatedY->_writeCoordinatedStep(false);
#if LC_COORDINATED_XY_ISR_INSTRUMENTATION_ENABLE != 0
        CoordinatedXyIsrInstrumentation::recordCompleteStepPulse(
            _coordinatedTiming, pulseHighCycles);
#endif
        status = CoordinatedXyExecutor::commitCompleteStep(
            _coordinatedPlan, _coordinatedCursor, tick);
      }
    }
  } else {
    status = CoordinatedXyExecutor::onTimerUpdate(
        _coordinatedPlan, _coordinatedCursor, tick);
  }
  _observeCoordinatedArr(tick.arr);
  const uint8_t tickMask = static_cast<uint8_t>(tick.mask);
  const bool stepX =
      (tickMask & static_cast<uint8_t>(CoordinatedXyPlanner::StepMask::X)) != 0u;
  const bool stepY =
      (tickMask & static_cast<uint8_t>(CoordinatedXyPlanner::StepMask::Y)) != 0u;

  if (!completeStepMode &&
      status == CoordinatedXyExecutor::TickStatus::Raised) {
    if (stepX) {
      _coordinatedX->_writeCoordinatedStep(true);
    }
    if (stepY) {
      _coordinatedY->_writeCoordinatedStep(true);
    }
  } else if (tick.accountCompletePulse) {
    if (stepX) {
      if (!completeStepMode) _coordinatedX->_writeCoordinatedStep(false);
      _coordinatedX->_accountCoordinatedPulse();
    }
    if (stepY) {
      if (!completeStepMode) _coordinatedY->_writeCoordinatedStep(false);
      _coordinatedY->_accountCoordinatedPulse();
    }
  }

  if (tick.updateArr) {
    _observeCoordinatedArr(tick.nextArr);
    uint32_t nextProgrammedArr = tick.nextArr;
    const bool arrValid = !completeStepMode ||
        CoordinatedXyExecutor::fullPeriodArr(
            tick.nextArr,
            _coordinatedPlan.timer.maxArr,
            nextProgrammedArr);
    if (!arrValid) {
      status = CoordinatedXyExecutor::forcePlannerFault(
          _coordinatedCursor, tick);
    } else {
      _coordinatedProgrammedArr = nextProgrammedArr;
      __HAL_TIM_SET_AUTORELOAD(
          _coordinatedMasterTimer, nextProgrammedArr);
    }
  }

  BaseType_t woken = pdFALSE;
  bool updatePending = false;
  const bool terminal = tick.stopTimer &&
      status != CoordinatedXyExecutor::TickStatus::Paused;
  if (tick.stopTimer) {
    if (status == CoordinatedXyExecutor::TickStatus::Paused) {
      HAL_TIM_Base_Stop_IT(_coordinatedMasterTimer);
      __HAL_TIM_CLEAR_FLAG(_coordinatedMasterTimer, TIM_FLAG_UPDATE);
    } else {
      const bool aborted = status != CoordinatedXyExecutor::TickStatus::Completed;
      _finishCoordinatedFromIsr(aborted, &woken, true);
    }
  } else if (__HAL_TIM_GET_FLAG(_coordinatedMasterTimer, TIM_FLAG_UPDATE) != RESET) {
    ++_coordinatedPendingUpdateCount;
    updatePending = true;
  }

  const uint32_t recordedExitCycle = gantryCycleNow();
#if LC_COORDINATED_XY_ISR_INSTRUMENTATION_ENABLE != 0
  // Consume the new entry-register capture only after the existing pending
  // observation so Stage 1 cannot perturb the value it is correlating.
  const bool entryTimerValid =
      g_lcCoordinatedTim2IrqEntryTimerValid != 0u;
  const uint32_t entryTimerCount =
      g_lcCoordinatedTim2IrqEntryTimerCount;
  const uint32_t entryTimerArr = g_lcCoordinatedTim2IrqEntryTimerArr;
  g_lcCoordinatedTim2IrqEntryTimerValid = 0u;
  CoordinatedXyIsrInstrumentation::recordSample(
      _coordinatedTiming,
      timingPhase,
      entryCycle,
      recordedExitCycle,
      timingArr,
      updatePending,
      tick.accountCompletePulse,
      terminal);
  const uint32_t finalExitCycle = gantryCycleNow();
  CoordinatedXyIsrInstrumentation::completeSampleTiming(
      _coordinatedTiming,
      timingPhase,
      entryCycle,
      recordedExitCycle,
      finalExitCycle,
      terminal);
  CoordinatedXyIsrInstrumentation::beginIrqPathSample(
      _coordinatedTiming,
      irqEntryValid,
      irqEntryCycle,
      entryTimerValid,
      entryTimerCount,
      entryTimerArr,
      entryCycle,
      updatePending,
      terminal);
#else
  const uint32_t finalExitCycle = recordedExitCycle;
#endif
  const uint32_t cycles = finalExitCycle - entryCycle;
  if (cycles > _coordinatedMaxIsrCycles) {
    _coordinatedMaxIsrCycles = cycles;
  }
  portYIELD_FROM_ISR(woken);
  return true;
#endif
}

bool Gantry::dispatchCoordinatedTimerFromIsr(TIM_HandleTypeDef* htim) {
  return _instance != nullptr && _instance->_handleCoordinatedTimerFromIsr(htim);
}

LC_COORDINATED_HW_OPTIMIZED
void Gantry::recordCoordinatedTim2IrqExitFromIsr(uint32_t irqExitCycle) {
#if LC_COORDINATED_XY_ISR_INSTRUMENTATION_ENABLE != 0
  if (_instance != nullptr) {
    TIM_HandleTypeDef* timer = _instance->_coordinatedMasterTimer;
    const bool timerValid = timer != nullptr && timer->Instance != nullptr;
    CoordinatedXyIsrInstrumentation::recordTim2Deadline(
        _instance->_coordinatedTiming,
        timerValid,
        timerValid ? timer->Instance->CNT : 0u,
        timerValid ? timer->Instance->ARR : 0u,
        timerValid && (timer->Instance->SR & TIM_SR_UIF) != 0u);
    CoordinatedXyIsrInstrumentation::completeIrqPath(
        _instance->_coordinatedTiming, irqExitCycle);
  }
#else
  (void)irqExitCycle;
#endif
}

extern "C" LC_COORDINATED_HW_OPTIMIZED
void MX_GANTRY_RecordTim2IrqExit(uint32_t irqExitCycle) {
  Gantry::recordCoordinatedTim2IrqExitFromIsr(irqExitCycle);
}

#undef LC_COORDINATED_HW_OPTIMIZED
#undef LC_COORDINATED_HW_ALWAYS_INLINE

//// moveBy: fan-in three axes so they finish simultaneously
//void Gantry::moveBy(int32_t dx, int32_t dy, int32_t dz, uint32_t feedHz) {
//  // 1) how many steps on each
//  uint32_t absx = std::abs(dx),
//           absy = std::abs(dy),
//           absz = std::abs(dz);
//
//  // 2) longest axis
//  uint32_t longest = std::max({absx, absy, absz});
//  if (longest == 0u) return;  // nothing to do
//
//  // ---- distance-aware policy ------------------------------------------------
//  // The shorter the move, the lower the top speed and the fatter the ramps.
//  // Tunables (steps):
//  const uint32_t L1 = 50u;
//  const uint32_t L2 = 200u;
//  const uint32_t L3 = 1000u;
//  const uint32_t L4 = 2000u;
//
//  // Fixed accel budgets (FULL steps) for medium/large moves (tune as needed)
////  const uint32_t A_MED   = 800u;   // for L2 < longest <= L3
//  const uint32_t A_LONG  = 1500u;  // for L3 < longest <= L4
//  const uint32_t A_XLONG = 2500u;  // for L4 < longest
//
//  // Tunables per bracket
//  float     feedScale     = 1.0f;     // scales the user feedHz
//  uint32_t  minFloorHz    = _minStepHz;
//  bool      useFracAccel  = false;    // true → fractional accel; false → fixed accel
//  float     accelFrac     = 0.0f;     // only used if useFracAccel==true
//  uint32_t  accelFixed    = 0u;       // only used if useFracAccel==false
//
//  if (longest <= L1) {
//    // Very short: very gentle, heavy ramping
//    feedScale    = 0.25f;
//    minFloorHz   = 600u;
//    useFracAccel = true;
//    accelFrac    = 0.90f;
//  } else if (longest <= L2) {
//    // Short: still gentle
//    feedScale    = 0.30f;
//    minFloorHz   = 1200u;
//    useFracAccel = true;
//    accelFrac    = 0.90f;
//  } else if (longest <= L3) {
//    // Medium: fixed accel so we reach speed quickly
//    feedScale    = 0.30f;
//    minFloorHz   = 1200u;
//    useFracAccel = true;
//    accelFrac    = 0.90f;
//  } else if (longest <= L4) {
//    // Long: fixed accel, near full speed
//    feedScale    = 1.00f;
//    minFloorHz   = 2500u;
//    useFracAccel = false;
//    accelFixed   = A_LONG;
//  } else {
//    // Very long: fixed accel, full speed
//    feedScale    = 1.00f;
//    minFloorHz   = _minStepHz;  // let your global floor rule
//    useFracAccel = false;
//    accelFixed   = A_XLONG;
//  }
//
//  const uint32_t feedHzEff = static_cast<uint32_t>(float(feedHz) * feedScale);
//
//  // Time-coupled per-axis top rates so all axes finish together
//  auto rateFor = [&](uint32_t axisSteps)->uint32_t {
//    if (axisSteps == 0u) return 0u;
//    uint32_t f = static_cast<uint32_t>((uint64_t)feedHzEff * axisSteps / longest);
//    // floor is lower for tiny moves; higher for bigger moves
//    uint32_t floorHz = std::min(_minStepHz, minFloorHz);
//    return std::max(f, floorHz);
//  };
//
//  // Per-axis accel budget (FULL steps)
//  auto accelFor = [&](uint32_t axisSteps)->uint32_t {
//    if (axisSteps == 0u) return 0u;
//
//    // never spend more than half the move on accel (triangular fallback)
//    uint32_t cap = axisSteps / 2u;
//    if (cap == 0u) cap = 1u;
//
//    uint32_t a;
//    if (useFracAccel) {
//      a = static_cast<uint32_t>(std::ceil(float(axisSteps) * accelFrac));
//    } else {
//      a = accelFixed;
//    }
//
//    if (a > cap) a = cap;
//    if (a < 1u)  a = 1u;
//    return a;
//  };
//
//  uint32_t fx = rateFor(absx),
//           fy = rateFor(absy),
//           fz = rateFor(absz);
//
//  uint32_t ax = accelFor(absx),
//		   ay = accelFor(absy),
//		   az = accelFor(absz);
//
//  // 4) start all three
//  MX_STEPPERX_Move(dx >= 0, absx, fx, ax);
//  MX_STEPPERY_Move(dy >= 0, absy, fy, ay);
//  MX_STEPPERZ_Move(dz >= 0, absz, fz, az);
//
//}
void Gantry::setAxisAccel(Stepper::Axis ax, float a) {
  if (auto s = Stepper::getAxis(ax)) s->setAccelStepsPerSec2(a);
}
void Gantry::setAccelAll(float a) {
  setAxisAccel(Stepper::X_AXIS, a);
  setAxisAccel(Stepper::Y_AXIS, a);
  setAxisAccel(Stepper::Z_AXIS, a);
}
void Gantry::setAccelProfileAll(Stepper::AccelProfile p) {
  if (auto s = Stepper::stepperX()) s->setAccelProfile(p);
  if (auto s = Stepper::stepperY()) s->setAccelProfile(p);
  if (auto s = Stepper::stepperZ()) s->setAccelProfile(p);
}

void Gantry::_pauseCoordinatedTask() {
  taskENTER_CRITICAL();
  const CoordinatedXyExecutor::ControlDisposition disposition =
      CoordinatedXyExecutor::requestPause(_coordinatedCursor);
  if (disposition == CoordinatedXyExecutor::ControlDisposition::StopNow &&
      _coordinatedMasterTimer != nullptr) {
    HAL_TIM_Base_Stop_IT(_coordinatedMasterTimer);
    __HAL_TIM_CLEAR_FLAG(_coordinatedMasterTimer, TIM_FLAG_UPDATE);
  }
  taskEXIT_CRITICAL();
}

void Gantry::_resumeCoordinatedTask() {
  bool signalDone = false;
  taskENTER_CRITICAL();
  const CoordinatedXyExecutor::ControlDisposition disposition =
      CoordinatedXyExecutor::resume(_coordinatedCursor);
  if (disposition == CoordinatedXyExecutor::ControlDisposition::Deferred &&
      _coordinatedMasterTimer != nullptr) {
    uint32_t programmedArr = _coordinatedCursor.cachedEvent.arr;
    const bool arrValid =
        _coordinatedCursor.executionMode !=
            CoordinatedXyExecutor::ExecutionMode::CompleteStep ||
        CoordinatedXyExecutor::fullPeriodArr(
            _coordinatedCursor.cachedEvent.arr,
            _coordinatedPlan.timer.maxArr,
            programmedArr);
    if (!arrValid) {
      CoordinatedXyExecutor::TickResult fault{};
      (void)CoordinatedXyExecutor::forcePlannerFault(
          _coordinatedCursor, fault);
      _finishCoordinatedHardware(true);
#if LC_COORDINATED_XY_ISR_INSTRUMENTATION_ENABLE != 0
      CoordinatedXyIsrInstrumentation::finishWithoutSample(
          _coordinatedTiming, gantryCycleNow(), true);
#endif
      signalDone = true;
    } else {
      _coordinatedProgrammedArr = programmedArr;
      __HAL_TIM_SET_AUTORELOAD(_coordinatedMasterTimer, programmedArr);
      __HAL_TIM_SET_COUNTER(_coordinatedMasterTimer, 0u);
      __HAL_TIM_CLEAR_FLAG(_coordinatedMasterTimer, TIM_FLAG_UPDATE);
      (void)HAL_TIM_Base_Start_IT(_coordinatedMasterTimer);
    }
  }
  taskEXIT_CRITICAL();
  if (signalDone) {
    xEventGroupSetBits(Orchestrator::getDoneEvents(),
                       BIT_STEPPER1_DONE | BIT_STEPPER2_DONE);
  }
}

bool Gantry::_cancelCoordinatedTask(uint32_t* risingEdgesBefore,
                                    uint32_t* fallingEdgesBefore) {
  bool signalDone = false;
  taskENTER_CRITICAL();
  if (risingEdgesBefore != nullptr) {
    *risingEdgesBefore = _coordinatedCursor.risingEdges;
  }
  if (fallingEdgesBefore != nullptr) {
    *fallingEdgesBefore = _coordinatedCursor.fallingEdges;
  }
  const CoordinatedXyExecutor::ControlDisposition disposition =
      CoordinatedXyExecutor::requestCancel(_coordinatedCursor);
  if (disposition == CoordinatedXyExecutor::ControlDisposition::StopNow) {
    _finishCoordinatedHardware(true);
#if LC_COORDINATED_XY_ISR_INSTRUMENTATION_ENABLE != 0
    CoordinatedXyIsrInstrumentation::finishWithoutSample(
        _coordinatedTiming, gantryCycleNow(), true);
#endif
    signalDone = true;
  }
  taskEXIT_CRITICAL();
  if (signalDone) {
    xEventGroupSetBits(Orchestrator::getDoneEvents(),
                       BIT_STEPPER1_DONE | BIT_STEPPER2_DONE);
  }
  return disposition == CoordinatedXyExecutor::ControlDisposition::Deferred ||
         disposition == CoordinatedXyExecutor::ControlDisposition::StopNow;
}

bool Gantry::_requestCoordinatedLimitAbortTask(Stepper::Axis axis,
                                                uint32_t* risingEdgesBefore,
                                                uint32_t* fallingEdgesBefore) {
  if (axis != Stepper::X_AXIS && axis != Stepper::Y_AXIS) return false;
  bool signalDone = false;
  taskENTER_CRITICAL();
  if (risingEdgesBefore != nullptr) {
    *risingEdgesBefore = _coordinatedCursor.risingEdges;
  }
  if (fallingEdgesBefore != nullptr) {
    *fallingEdgesBefore = _coordinatedCursor.fallingEdges;
  }
  const CoordinatedXyExecutor::ControlDisposition disposition =
      CoordinatedXyExecutor::requestLimitAbort(
          _coordinatedCursor,
          axis == Stepper::X_AXIS ? CoordinatedXyExecutor::LimitAxis::X
                                  : CoordinatedXyExecutor::LimitAxis::Y);
  if (disposition == CoordinatedXyExecutor::ControlDisposition::StopNow) {
    _finishCoordinatedHardware(true);
#if LC_COORDINATED_XY_ISR_INSTRUMENTATION_ENABLE != 0
    CoordinatedXyIsrInstrumentation::finishWithoutSample(
        _coordinatedTiming, gantryCycleNow(), true);
#endif
    signalDone = true;
  }
  taskEXIT_CRITICAL();
  if (signalDone) {
    xEventGroupSetBits(Orchestrator::getDoneEvents(),
                       BIT_STEPPER1_DONE | BIT_STEPPER2_DONE);
  }
  return disposition == CoordinatedXyExecutor::ControlDisposition::Deferred ||
         disposition == CoordinatedXyExecutor::ControlDisposition::StopNow ||
         disposition == CoordinatedXyExecutor::ControlDisposition::AlreadySatisfied;
}

bool Gantry::requestCoordinatedLimitAbortForDiagnostics(Stepper::Axis axis) {
  return _requestCoordinatedLimitAbortTask(axis);
}

bool Gantry::requestCoordinatedCancelForDiagnostics(
    uint32_t& risingEdgesBefore,
    uint32_t& fallingEdgesBefore) {
  return _cancelCoordinatedTask(&risingEdgesBefore, &fallingEdgesBefore);
}

bool Gantry::requestCoordinatedLimitAbortForDiagnostics(
    Stepper::Axis axis,
    uint32_t& risingEdgesBefore,
    uint32_t& fallingEdgesBefore) {
  return _requestCoordinatedLimitAbortTask(
      axis, &risingEdgesBefore, &fallingEdgesBefore);
}

void Gantry::requestCoordinatedLimitAbortFromIsr(Stepper::Axis axis) {
#if LC_COORDINATED_XY_EXECUTOR_ENABLE != 0
  Gantry* gantry = _instance;
  if (gantry == nullptr ||
      (axis != Stepper::X_AXIS && axis != Stepper::Y_AXIS)) {
    return;
  }
  if (gantry->_coordinatedLimitAbortRequestCount == 0u) {
    gantry->_coordinatedLimitRequestRisingEdges =
        gantry->_coordinatedCursor.risingEdges;
    gantry->_coordinatedLimitRequestFallingEdges =
        gantry->_coordinatedCursor.fallingEdges;
  }
  ++gantry->_coordinatedLimitAbortRequestCount;
  const CoordinatedXyExecutor::ControlDisposition requestDisposition =
      CoordinatedXyExecutor::requestLimitAbort(
          gantry->_coordinatedCursor,
          axis == Stepper::X_AXIS ? CoordinatedXyExecutor::LimitAxis::X
                                  : CoordinatedXyExecutor::LimitAxis::Y);
  if (requestDisposition == CoordinatedXyExecutor::ControlDisposition::StopNow) {
    BaseType_t woken = pdFALSE;
    gantry->_finishCoordinatedFromIsr(true, &woken);
    portYIELD_FROM_ISR(woken);
  }
#else
  (void)axis;
#endif
}

void Gantry::pauseXYZMotors() {
  if (_instance != nullptr &&
      CoordinatedXyExecutor::isActive(_instance->_coordinatedCursor)) {
    _instance->_pauseCoordinatedTask();
    if (auto* z = Stepper::stepperZ()) z->pauseMove();
    return;
  }
  for (auto axis : { Stepper::X_AXIS, Stepper::Y_AXIS, Stepper::Z_AXIS }) {
	if (auto s = Stepper::getAxis(axis)) s->pauseMove();
  }
}
void Gantry::resumeXYZMotors() {
  if (_instance != nullptr &&
      CoordinatedXyExecutor::isActive(_instance->_coordinatedCursor)) {
    _instance->_resumeCoordinatedTask();
    if (auto* z = Stepper::stepperZ()) z->resumeMove();
    return;
  }
  for (auto axis : { Stepper::X_AXIS, Stepper::Y_AXIS, Stepper::Z_AXIS }) {
	if (auto s = Stepper::getAxis(axis)) s->resumeMove();
  }
}
void Gantry::cancelXYZMotors() {
  if (_instance != nullptr &&
      CoordinatedXyExecutor::isActive(_instance->_coordinatedCursor)) {
    (void)_instance->_cancelCoordinatedTask();
    if (auto* z = Stepper::stepperZ()) z->cancelMove();
    return;
  }
  for (auto axis : { Stepper::X_AXIS, Stepper::Y_AXIS, Stepper::Z_AXIS }) {
	if (auto s = Stepper::getAxis(axis)) s->cancelMove();
  }
}

CoordinatedXySnapshot Gantry::coordinatedSnapshot() const {
  CoordinatedXySnapshot snapshot{};
  taskENTER_CRITICAL();
  snapshot.startStatus = _coordinatedStartStatus;
  snapshot.state = _coordinatedCursor.state;
  snapshot.terminalReason = _coordinatedCursor.terminalReason;
  snapshot.executionMode = _coordinatedCursor.executionMode;
  snapshot.requestedXSteps = _coordinatedPlan.xSteps;
  snapshot.requestedYSteps = _coordinatedPlan.ySteps;
  snapshot.emittedXSteps = _coordinatedCursor.xEmittedSteps;
  snapshot.emittedYSteps = _coordinatedCursor.yEmittedSteps;
  snapshot.masterSteps = _coordinatedPlan.masterSteps;
  snapshot.timer2Interrupts = _coordinatedCursor.timerInterrupts;
  snapshot.timer7Interrupts = _coordinatedTim7Interrupts;
  snapshot.risingEdges = _coordinatedCursor.risingEdges;
  snapshot.fallingEdges = _coordinatedCursor.fallingEdges;
  snapshot.arrMin = _coordinatedArrMin;
  snapshot.arrMax = _coordinatedArrMax;
  snapshot.pendingUpdateCount = _coordinatedPendingUpdateCount;
  snapshot.maxIsrCycles = _coordinatedMaxIsrCycles;
  snapshot.selectedMasterRateHz = _coordinatedPlan.masterRateHz;
  snapshot.selectedMasterAccelerationStepsPerSec2 =
      _coordinatedPlan.masterAccelerationStepsPerSec2;
  snapshot.accelerationSteps = _coordinatedPlan.accelerationSteps;
  snapshot.cruiseSteps = _coordinatedPlan.cruiseSteps;
  snapshot.decelerationSteps = _coordinatedPlan.decelerationSteps;
  snapshot.triangular = _coordinatedPlan.triangular;
  snapshot.timing = CoordinatedXyIsrInstrumentation::makeSnapshot(
      _coordinatedTiming);
  snapshot.limitAbortRequestCount = _coordinatedLimitAbortRequestCount;
  snapshot.rawLimitAbortCount = _coordinatedRawLimitAbortCount;
  snapshot.limitRequestRisingEdges = _coordinatedLimitRequestRisingEdges;
  snapshot.limitRequestFallingEdges = _coordinatedLimitRequestFallingEdges;
  snapshot.maskChecksum = _coordinatedCursor.maskChecksum;
  snapshot.arrChecksum = _coordinatedCursor.arrChecksum;
  snapshot.timerOwned = _coordinatedTimerOwned;
  if (_coordinatedX != nullptr) {
    snapshot.xPosition = _coordinatedX->_pos;
    snapshot.xTarget = _coordinatedX->_targetPos;
    snapshot.xStepLow = _coordinatedX->_coordinatedStepIsLow();
  }
  if (_coordinatedY != nullptr) {
    snapshot.yPosition = _coordinatedY->_pos;
    snapshot.yTarget = _coordinatedY->_targetPos;
    snapshot.yStepLow = _coordinatedY->_coordinatedStepIsLow();
  }
  taskEXIT_CRITICAL();
  for (uint8_t i = 0u;
       i < static_cast<uint8_t>(CoordinatedXyIsrInstrumentation::Phase::Count);
       ++i) {
    snapshot.phaseMeanCycles[i] =
        CoordinatedXyIsrInstrumentation::phaseMeanCycles(
            snapshot.timing,
            static_cast<CoordinatedXyIsrInstrumentation::Phase>(i));
  }
  snapshot.terminalMeanCycles =
      CoordinatedXyIsrInstrumentation::terminalMeanCycles(snapshot.timing);
  snapshot.durationErrorBasisPoints =
      CoordinatedXyIsrInstrumentation::durationErrorBasisPoints(
          snapshot.timing,
          HAL_RCC_GetHCLKFreq(),
          _coordinatedPlan.timer.inputClockHz);
  snapshot.minimumPulseCoreCycles = _coordinatedPulseHighCycles;
  snapshot.doneBits = static_cast<uint32_t>(
      xEventGroupGetBits(Orchestrator::getDoneEvents()));
  return snapshot;
}

GantryPosition Gantry::getPosition() const {
  return {
    MX_STEPPERX_GetPos(),
    MX_STEPPERY_GetPos(),
    MX_STEPPERZ_GetPos()
  };
}

//----------------------------------------------------------------------
// C API
extern "C" {

void MX_GANTRY_Init(void) {
  // make sure each Stepper is configured first
  static Gantry g;
  g.begin();

  MX_STEPPERX_Init();
  MX_STEPPERY_Init();
  MX_STEPPERZ_Init();
}

void MX_GANTRY_MoveBy(int32_t dx, int32_t dy, int32_t dz, uint32_t feedHz) {
  Gantry::instance()->moveBy(dx, dy, dz, feedHz);
}

void MX_GANTRY_MoveTo(int32_t x, int32_t y, int32_t z, uint32_t feedHz) {
  Gantry::instance()->moveTo(x, y, feedHz);
}

} // extern "C"


