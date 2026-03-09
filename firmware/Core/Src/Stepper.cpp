/*
 * Stepper.cpp
 *
 *  Created on: Jun 17, 2025
 *      Author: conar
 */

#include "Stepper.h"
#include "StepperProfileMath.h"
#include "Orchestrator.h"          // for getDoneEvents()
#include "Logger.h"
#include "FreeRTOS.h"
#include "event_groups.h"
#include "timers.h"
#include "stm32f4xx_hal.h"
#include <stdint.h>
#include <cstdlib>
#include <cmath>          // for cosf()

// --- Timer helpers ----------------------------------------------------------
static inline bool is_apb2_timer(TIM_TypeDef* inst) {
  return inst==TIM1 || inst==TIM8 || inst==TIM9 || inst==TIM10 || inst==TIM11;
}
static inline bool is_32bit_timer(TIM_TypeDef* inst) {
  return inst==TIM2 || inst==TIM5;
}
static inline uint32_t timer_input_hz(TIM_HandleTypeDef* htim, uint16_t prescaler) {
  RCC_ClkInitTypeDef cfg; uint32_t flash;
  HAL_RCC_GetClockConfig(&cfg, &flash);

  const bool apb2 = is_apb2_timer(htim->Instance);
  const uint32_t pclk = apb2 ? HAL_RCC_GetPCLK2Freq() : HAL_RCC_GetPCLK1Freq();
  const bool x2 = apb2 ? (cfg.APB2CLKDivider != RCC_HCLK_DIV1)
                       : (cfg.APB1CLKDivider != RCC_HCLK_DIV1);
  const uint32_t tclk = x2 ? (pclk * 2u) : pclk;         // true timer clock
  return tclk / (uint32_t(prescaler) + 1u);
}
static inline uint32_t timer_max_arr(TIM_HandleTypeDef* htim) {
  return is_32bit_timer(htim->Instance) ? 0xFFFFFFFFu : 0xFFFFu;
}
static constexpr uint32_t kMoveWaitPollMs = 20u;
static constexpr uint32_t kMoveWaitSlackMs = 4000u;
static constexpr uint32_t kMoveWaitMinMs = 1000u;
static constexpr uint32_t kMoveWaitMaxMs = 30000u;

static TickType_t stepperMsToAtLeast1Tick(uint32_t ms)
{
  if (ms == 0u) {
    return 0u;
  }
  TickType_t ticks = pdMS_TO_TICKS(ms);
  return (ticks == 0u) ? 1u : ticks;
}
// Compute ARR from desired square-wave frequency
static inline uint32_t arr_for_freq(uint32_t tclk_eff, uint32_t freq_hz) {
  return StepperProfileMath::arrForFreq(tclk_eff, freq_hz);
}

static inline uint8_t port_code(GPIO_TypeDef* p) {
  if (p==GPIOA) return 0;
  if (p==GPIOB) return 1;
  if (p==GPIOC) return 2;
  if (p==GPIOD) return 3;
  if (p==GPIOE) return 4;
  if (p==GPIOF) return 5;
  if (p==GPIOG) return 6;
  if (p==GPIOH) return 7;
  return 0;
}
static inline int pin_number_from_mask(uint16_t pinmask) {
  for (int i=0;i<16;++i) if ((pinmask & (1u<<i))!=0) return i;
  return 0;
}

// static storage for each axis
Stepper* Stepper::_axes[Stepper::NUM_AXES] = { nullptr };


Stepper::Stepper() {}

// retrieve by axis
Stepper* Stepper::getAxis(Axis axis) {
  if (axis < NUM_AXES) return _axes[axis];
  return nullptr;
}

void Stepper::begin(
	Axis			   axis,
    TIM_HandleTypeDef* htim,
    GPIO_TypeDef*      stepPort, uint16_t stepPin,
    GPIO_TypeDef*      dirPort,  uint16_t dirPin,
    GPIO_TypeDef*      enPort,   uint16_t enPin,
    uint32_t           doneBit, uint16_t prescaler,
	bool invertDirection, bool homeDirection
) {
  _htim     = htim;
  _stepPort = stepPort;  _stepPin = stepPin;
  _dirPort  = dirPort;   _dirPin  = dirPin;
  _enPort   = enPort;    _enPin   = enPin;
  _doneBit  = doneBit;   _prescaler = prescaler;
  _invertDirection = invertDirection;

  // mark in the static axis array
  _axis = axis;
  _axes[axis] = this;

  // no second driver at start
  _dualDriver = false;

  // make sure the pins are outputs and set enable high to disable the motor
  HAL_GPIO_WritePin(_enPort, _enPin, GPIO_PIN_SET);
}

// After you've called begin(), call this to wire up the second motor driver
void Stepper::addDriver(
    GPIO_TypeDef* stepPort, uint16_t stepPin,
    GPIO_TypeDef* dirPort,  uint16_t dirPin,
    GPIO_TypeDef* enPort,   uint16_t enPin
) {
  _dualDriver = true;
  _stepPort2  = stepPort; _stepPin2 = stepPin;
  _dirPort2   = dirPort;  _dirPin2  = dirPin;
  _enPort2    = enPort;   _enPin2   = enPin;
  // bring secondary enable high
  HAL_GPIO_WritePin(_enPort2, _enPin2, GPIO_PIN_SET);
}

void Stepper::moveTo(bool sign, uint32_t newPos, uint32_t freqHz, uint32_t accelSteps) {
  // Interpret (sign,newPos) as a signed absolute position
  int32_t target = sign ? (int32_t)newPos : -(int32_t)newPos;
  int32_t delta  = target - _pos;

  if (delta == 0) {
	HAL_TIM_Base_Stop_IT(_htim);
	xEventGroupSetBits(Orchestrator::getDoneEvents(), _doneBit);
	return;
  }

  const bool direction = (delta > 0);
  const uint32_t steps = (delta > 0) ? (uint32_t)delta : (uint32_t)(-delta);
  move(direction, steps, freqHz, accelSteps);
}

void Stepper::move(bool direction, uint32_t steps, uint32_t freqHz, uint32_t /*accelSteps ignored*/) {
  if (!_htim || _togglesRemaining != 0) return;

  if (steps == 0u) {
    xEventGroupSetBits(Orchestrator::getDoneEvents(), _doneBit);
    return;
  }

  // Track target position
  _targetPos     = direction ? (_pos + (int32_t)steps) : (_pos - (int32_t)steps);
  const bool hwDir = direction ^ _invertDirection;
  _direction      = direction;
  _lastDirection  = direction;

  const uint32_t tclkEff = timer_input_hz(_htim, _prescaler);
  const uint32_t maxARR  = timer_max_arr(_htim);
  StepperProfileMath::MovePlanInput planInput{};
  planInput.steps = steps;
  planInput.requestedHz = freqHz;
  planInput.maxSpeedHz = _max_speed_hz;
  planInput.accelStepsPerSec2 = _accel_sps2;
  planInput.timerClockHz = tclkEff;
  planInput.timerMaxArr = maxARR;
  const StepperProfileMath::MovePlan plan = StepperProfileMath::planMove(planInput);

  const uint32_t v_req = plan.cruiseHz;
  _lastFreqHz = v_req;    // for pause/resume
  _lastAccel  = 0u;       // legacy field; not used anymore

  _inSoftStop = false;    // fresh move; no soft-stop armed yet

  // toggles: 2 per full step
  _totalToggles     = steps * 2u;
  _togglesRemaining = _totalToggles;
  _togglesDone      = 0u;

  _accelToggles = plan.accelToggles;
  _decelToggles = plan.decelToggles;

  // ---------- GPIO DIR/EN ----------
  HAL_GPIO_WritePin(_dirPort,  _dirPin,  hwDir ? GPIO_PIN_SET : GPIO_PIN_RESET);
  if (_dualDriver) HAL_GPIO_WritePin(_dirPort2, _dirPin2, hwDir ? GPIO_PIN_SET : GPIO_PIN_RESET);

  HAL_GPIO_WritePin(_enPort,   _enPin,   GPIO_PIN_RESET);
  if (_dualDriver) HAL_GPIO_WritePin(_enPort2, _enPin2, GPIO_PIN_RESET);

  _targetARR = plan.targetArr;
  _startARR = plan.startArr;

  // Linear fallback slope (kept for completeness; S-curve below uses _start/_target)
  const uint32_t Aeff = (_accelToggles ? _accelToggles : 1u);
  const int32_t  num  = (int32_t)_startARR - (int32_t)_targetARR;
  _deltaARR           = num / (int32_t)Aeff;

  // Prime timer
  __HAL_TIM_SET_PRESCALER (_htim, _prescaler);
  __HAL_TIM_SET_AUTORELOAD(_htim, _startARR);
  __HAL_TIM_SET_COUNTER   (_htim, 0);
  __HAL_TIM_CLEAR_FLAG    (_htim, TIM_FLAG_UPDATE);
  HAL_TIM_Base_Start_IT(_htim);
}

void Stepper::setSpeedHz(uint32_t freqHz) {
  if (!_htim || !_togglesRemaining) return;

  const uint32_t tclkEff = timer_input_hz(_htim, _prescaler);
  const uint32_t maxARR  = timer_max_arr(_htim);

  // Respect min pulse width (same as in move())
  const uint32_t kMinPulseNs = 2000u;
  uint32_t minTicks = (uint32_t)(((uint64_t)kMinPulseNs * tclkEff + 999999999ULL) / 1000000000ULL);
  if (minTicks < 2u) minTicks = 2u;
  const uint32_t minARR = minTicks - 1u;

  uint32_t newARR = arr_for_freq(tclkEff, freqHz);
  if (newARR < minARR) newARR = minARR;
  if (newARR > maxARR) newARR = maxARR;

  _targetARR = newARR;
}

void Stepper::_requestSoftStop()
{
  if (_togglesRemaining == 0 || _inSoftStop) return;

  const uint32_t tclkEff = timer_input_hz(_htim, _prescaler);

  // Current ARR -> instantaneous step rate
  uint32_t arr_now = __HAL_TIM_GET_AUTORELOAD(_htim);
  if (arr_now < 1u) arr_now = 1u;
  const uint32_t v_cur = (uint32_t)((uint64_t)tclkEff / (uint64_t)(2u * (arr_now + 1u)));

  // Pick braking accel: override > factor*normal > normal
  float a = (_accel_sps2 > 1.f) ? _accel_sps2 : 1.f;
  if (_softstop_accel_override_sps2 > 0.f) {
    a = _softstop_accel_override_sps2;
  } else if (_softstop_accel_factor > 1.f) {
    a *= _softstop_accel_factor;
  }

  // Braking distance s = v^2/(2a)
  uint32_t s_decel = (uint32_t)std::ceil((double)v_cur * (double)v_cur / (2.0 * (double)a));
  if (s_decel < 1u) s_decel = 1u;

  // Convert to toggles and clamp to remaining
  uint32_t tail_toggles = s_decel * 2u;
  if (tail_toggles > _togglesRemaining) tail_toggles = _togglesRemaining;

  // --- CRITICAL FIX: make this tail the only remaining motion ---
  _accelToggles     = 0u;
  _decelToggles     = tail_toggles;
  _totalToggles     = _togglesDone + _decelToggles;
  _togglesRemaining = _decelToggles;                   // <— shrink rem so we actually stop

  // Decel shape: from current ARR to a slow floor
  const uint32_t maxARR = timer_max_arr(_htim);
  uint32_t arr_floor    = arr_for_freq(tclkEff, _softstop_floor_hz);
  if (arr_floor > maxARR) arr_floor = maxARR;

  _targetARR = arr_now;      // start decel at current period (faster)
  _startARR  = arr_floor;    // end at slow rate

  _inSoftStop = true;
}

uint32_t Stepper::recommendedWaitTimeoutMs(uint32_t steps, uint32_t freqHz)
{
  const uint32_t safeHz = (freqHz == 0u) ? 1u : freqHz;
  const uint64_t motionMs = (((uint64_t)steps * 1000u) + safeHz - 1u) / safeHz;
  uint64_t timeoutMs = motionMs + kMoveWaitSlackMs;
  if (timeoutMs < kMoveWaitMinMs) timeoutMs = kMoveWaitMinMs;
  if (timeoutMs > kMoveWaitMaxMs) timeoutMs = kMoveWaitMaxMs;
  return (uint32_t)timeoutMs;
}

bool Stepper::home(uint32_t fastHz, uint32_t slowHz, uint32_t backoffSteps) {

	Logger::instance()->log(
	  "[Home %d] lim pin=%u activeHigh=%d initial=%s\r\n",
	  (int)_axis, (unsigned)_limPin, (int)_limitActiveHigh,
	  _isLimitAsserted() ? "PRESSED" : "released");

  const float    saved_override = _softstop_accel_override_sps2;
  const uint32_t saved_floor    = _softstop_floor_hz;
  auto restoreHomeState = [&]() {
    _softstop_accel_override_sps2 = saved_override;
    _softstop_floor_hz = saved_floor;
    _softStopOnLimit = false;
  };

  auto runMoveAndWait = [&](bool direction, uint32_t steps, uint32_t freqHz) -> bool {
    xEventGroupClearBits(Orchestrator::getDoneEvents(), _doneBit);
    move(direction, steps, freqHz, 0u);
    if (steps == 0u) {
      return true;
    }
    const uint32_t timeoutMs = Stepper::recommendedWaitTimeoutMs(steps, freqHz);
    if (waitUntilDone(timeoutMs)) {
      return true;
    }
    Logger::instance()->log("[Home %d] move timeout steps=%lu hz=%lu\r\n",
                            (int)_axis,
                            (unsigned long)steps,
                            (unsigned long)freqHz);
    restoreHomeState();
    return false;
  };

	// Replace the raw HAL_GPIO_ReadPin(...) comparisons with _isLimitAsserted():
	if (_isLimitAsserted()) {
	  if (!runMoveAndWait(!_homeTowardLimitDir, backoffSteps * 2u, slowHz)) {
        return false;
      }
	  while (_isLimitAsserted()) {
	    if (!runMoveAndWait(!_homeTowardLimitDir, backoffSteps * 2u, slowHz)) {
          return false;
        }
	  }
	}
//  // If already pressed, back off in the opposite direction until it releases
//  if (HAL_GPIO_ReadPin(_limPort, _limPin) == (_limitActiveHigh ? GPIO_PIN_SET : GPIO_PIN_RESET)) {
//    move(!_homeTowardLimitDir, backoffSteps*2, slowHz, 0); waitUntilDone();
//    while (HAL_GPIO_ReadPin(_limPort, _limPin) == (_limitActiveHigh ? GPIO_PIN_SET : GPIO_PIN_RESET)) {
//      move(!_homeTowardLimitDir, backoffSteps*2, slowHz, 0); waitUntilDone();
//    }
//  }
  const float kMinHomeBrakeAccel = 800000.f; // steps/s^2
  float home_brake_accel = _accel_sps2 * _softstop_accel_factor;
  if (home_brake_accel < kMinHomeBrakeAccel) home_brake_accel = kMinHomeBrakeAccel;

  _softstop_accel_override_sps2 = home_brake_accel;
  _softstop_floor_hz            = 200u;

  // Coarse approach with finite guard
  _softStopOnLimit = true;
  if (!runMoveAndWait(_homeTowardLimitDir, _homeGuardSteps, fastHz)) {
    return false;
  }
  _softStopOnLimit = false;


  if (!_isLimitAsserted()) {
    _softStopOnLimit = true;
    if (!runMoveAndWait(_homeTowardLimitDir, backoffSteps * 4u, slowHz)) {
      return false;
    }
    _softStopOnLimit = false;

    if (!_isLimitAsserted()) {
      Logger::instance()->log("[Home] Limit not detected on %d — abort\r\n", (int)_axis);
      restoreHomeState();
      return false;
    }
  }
//  // If we arrived without the switch, try a short slow probe; else abort
//  GPIO_PinState s_now = HAL_GPIO_ReadPin(_limPort, _limPin);
//  if (s_now != (_limitActiveHigh ? GPIO_PIN_SET : GPIO_PIN_RESET)) {
//    _softStopOnLimit = true;
//    move(_homeTowardLimitDir, backoffSteps*4, slowHz, 0);
//    waitUntilDone();
//    _softStopOnLimit = false;
//
//    s_now = HAL_GPIO_ReadPin(_limPort, _limPin);
//    if (s_now != (_limitActiveHigh ? GPIO_PIN_SET : GPIO_PIN_RESET)) {
//      Logger::instance()->log("[Home] Limit not detected on %d — abort\r\n", (int)_axis);
//      _softstop_accel_override_sps2 = saved_override;
//      _softstop_floor_hz            = saved_floor;
//      return;
//    }
//  }

  // Back off a bit
  _softstop_accel_override_sps2 = 0.f;
  if (!runMoveAndWait(!_homeTowardLimitDir, backoffSteps, slowHz)) {
    return false;
  }

  // Fine approach (short)
  _softstop_accel_override_sps2 = home_brake_accel;
  _softStopOnLimit = true;
  if (!runMoveAndWait(_homeTowardLimitDir, backoffSteps * 8u, slowHz)) {
    return false;
  }
  _softStopOnLimit = false;

  // Zero & move off switch slightly
  _pos = 0;
  _softstop_accel_override_sps2 = 0.f;
  if (!runMoveAndWait(!_homeTowardLimitDir, 100u, slowHz)) {
    return false;
  }

  restoreHomeState();
  return true;
}

bool Stepper::waitUntilDone(uint32_t timeoutMs) {
  if (_togglesRemaining == 0u) {
    return true;
  }

  if (timeoutMs == 0u) {
    xEventGroupWaitBits(
        Orchestrator::getDoneEvents(),
        _doneBit,
        pdTRUE, pdTRUE,
        portMAX_DELAY
    );
    return true;
  }

  const TickType_t pollTicks = stepperMsToAtLeast1Tick(kMoveWaitPollMs);
  const uint32_t startMs = HAL_GetTick();
  while (_togglesRemaining != 0u) {
    const EventBits_t result = xEventGroupWaitBits(
        Orchestrator::getDoneEvents(),
        _doneBit,
        pdTRUE, pdTRUE,
        pollTicks
    );
    if ((result & _doneBit) != 0u || _togglesRemaining == 0u) {
      return true;
    }
    if ((HAL_GetTick() - startMs) >= timeoutMs) {
      Logger::instance()->log("[Stepper %d] wait timeout rem=%lu pos=%ld target=%ld\r\n",
                              (int)_axis,
                              (unsigned long)_togglesRemaining,
                              (long)_pos,
                              (long)_targetPos);
      stop();
      xEventGroupClearBits(Orchestrator::getDoneEvents(), _doneBit);
      return false;
    }
  }
  return true;
}


void Stepper::stop() {

  if (!_htim) return;

  HAL_TIM_Base_Stop_IT(_htim);

  _togglesRemaining = _togglesDone = 0;
  _inSoftStop = false;
}

void Stepper::enableMotor() {
  HAL_GPIO_WritePin(_enPort, _enPin, GPIO_PIN_RESET);
  if (_dualDriver) {
	HAL_GPIO_WritePin(_enPort2, _enPin2, GPIO_PIN_RESET);
  }
}

void Stepper::disableMotor() {
  HAL_GPIO_WritePin(_enPort, _enPin, GPIO_PIN_SET);
  if (_dualDriver) {
	HAL_GPIO_WritePin(_enPort2, _enPin2, GPIO_PIN_SET);
  }
}

void Stepper::pauseMove() {
  if (!_htim) return;
  HAL_TIM_Base_Stop_IT(_htim);
}

void Stepper::resumeMove() {
	uint32_t newSteps = (_togglesRemaining +1) / 2;
	_togglesRemaining = _togglesDone = 0;
	_accelToggles = _decelToggles = 0;

	move(_lastDirection, newSteps, _lastFreqHz, _lastAccel);
}

void Stepper::cancelMove() {
  // stop *and* clear all counts
  if (!_htim || _togglesRemaining == 0) return;
  _togglesRemaining = 0;
  _inSoftStop = false;
}

void Stepper::_stepTick() {
  uint32_t done = _togglesDone;
  uint32_t rem  = _togglesRemaining;

  if (rem == 0) {
    // complete
    HAL_TIM_Base_Stop_IT(_htim);

    // signal orchestrator
    BaseType_t woken = pdFALSE;
    xEventGroupSetBitsFromISR(
      Orchestrator::getDoneEvents(),
      _doneBit,
      &woken
    );
    portYIELD_FROM_ISR(woken);
    return;
  }

  auto ease01 = [&](float t)->float {
	    return StepperProfileMath::ease01(static_cast<StepperProfileMath::Profile>(_profile), t);
	  };

  // choose period
  int32_t arr;
  if (done < _accelToggles) {
    float t    = float(done) / float(_accelToggles);    // 0…1
    float e    = ease01(t);
    arr        = _startARR + int32_t((float(_targetARR) - float(_startARR)) * e);
  }
  else if (done > (_totalToggles - _decelToggles)) {
    uint32_t d = done - (_totalToggles - _decelToggles);
    float t    = float(d) / float(_decelToggles);       // 0…1
    float e    = ease01(t);
    arr        = _targetARR + int32_t((float(_startARR) - float(_targetARR)) * e);
  }
  else {
    arr = _targetARR;
  }

  // update timer period
  __HAL_TIM_SET_AUTORELOAD(_htim, uint32_t(arr));

  // toggle STEP
  HAL_GPIO_TogglePin(_stepPort, _stepPin);
  if (_dualDriver) {
    HAL_GPIO_TogglePin(_stepPort2, _stepPin2);
  }
//  HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);

  --_togglesRemaining;
  ++_togglesDone;

  // every two toggles = one full step
  if ((_togglesDone & 1) == 0) {
    _pos += (_direction ? +1 : -1);
  }
}

// dispatch timer IRQ to correct axis
void Stepper::dispatch(TIM_HandleTypeDef* htim) {
  for (int i = 0; i < NUM_AXES; ++i) {
    Stepper* s = _axes[i];
    if (s && s->_htim == htim) {
      s->_stepTick();
      break;
    }
  }
}

// Call this once (e.g. in MX_STEPPERx_Init) before using attachLimitSwitch()
void Stepper::configureLimitPin(GPIO_TypeDef* port, uint16_t pin) {
  // 1) Enable GPIO port & SYSCFG clocks
  __HAL_RCC_GPIOG_CLK_ENABLE();
  __HAL_RCC_SYSCFG_CLK_ENABLE();

  // 2) Configure PG6 as input with pull-up
  GPIO_InitTypeDef gi = {};
  gi.Pin  = pin;
  gi.Mode = GPIO_MODE_IT_RISING;     // interrupt on active-low press
  gi.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(port, &gi);

  // 3) Route PG6 to EXTI6 via SYSCFG
  //    EXTI6 is in EXTICR[1] (lines 4-7)
  uint32_t idx = 6 - 4;               // line offset within EXTICR[1]
  uint32_t shift = (idx & 3) * 4;
  SYSCFG->EXTICR[1] = (SYSCFG->EXTICR[1] & ~(0xF << shift))
                    | (0x6 /* port G */ << shift);

  // 4) Enable & prioritize the EXTI9_5_IRQn
  HAL_NVIC_SetPriority(EXTI9_5_IRQn, 6, 0);
  HAL_NVIC_EnableIRQ(EXTI9_5_IRQn);
}


void Stepper::attachLimitSwitch(GPIO_TypeDef* port,
                                uint16_t      pin,
                                TickType_t    debounceMs,
                                bool          activeHigh)
{
  _limPort = port;
  _limPin  = pin;
  _limitActiveHigh = true;

  auto enable_gpio_clock = [](GPIO_TypeDef* p){
    if (p==GPIOA) __HAL_RCC_GPIOA_CLK_ENABLE();
    else if (p==GPIOB) __HAL_RCC_GPIOB_CLK_ENABLE();
    else if (p==GPIOC) __HAL_RCC_GPIOC_CLK_ENABLE();
    else if (p==GPIOD) __HAL_RCC_GPIOD_CLK_ENABLE();
    else if (p==GPIOE) __HAL_RCC_GPIOE_CLK_ENABLE();
    else if (p==GPIOF) __HAL_RCC_GPIOF_CLK_ENABLE();
    else if (p==GPIOG) __HAL_RCC_GPIOG_CLK_ENABLE();
    else if (p==GPIOH) __HAL_RCC_GPIOH_CLK_ENABLE();
  };
  enable_gpio_clock(port);
  __HAL_RCC_SYSCFG_CLK_ENABLE();

  // 1) Configure GPIO as EXTI with correct edge + pull
  GPIO_InitTypeDef gi{};
  gi.Pin   = pin;
  gi.Mode  = activeHigh ? GPIO_MODE_IT_RISING : GPIO_MODE_IT_FALLING;
  gi.Pull  = activeHigh ? GPIO_PULLDOWN : GPIO_PULLUP;
  gi.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(port, &gi);

  // 2) Program SYSCFG EXTICR for the correct port/line
  const int line   = pin_number_from_mask(pin);   // 0..15
  const int reg    = line / 4;                    // 0..3
  const int shift  = (line % 4) * 4;
  uint32_t val     = SYSCFG->EXTICR[reg];
  val &= ~(0xFu << shift);
  val |= (uint32_t)port_code(port) << shift;
  SYSCFG->EXTICR[reg] = val;

  // 3) Pick and enable the right NVIC IRQ for this EXTI line group
  _extiLine = (uint8_t)line;
  if      (line <= 4)      _extiIRQn = (IRQn_Type)(EXTI0_IRQn + line);
  else if (line <= 9)      _extiIRQn = EXTI9_5_IRQn;
  else                     _extiIRQn = EXTI15_10_IRQn;

  HAL_NVIC_SetPriority(_extiIRQn, 6, 0);
  HAL_NVIC_EnableIRQ(_extiIRQn);

  // 4) Create one-shot debounce timer
  _debounceTimer = xTimerCreate(
    "LmtDbnc", debounceMs, pdFALSE, this,
    [](TimerHandle_t t){
      auto *self = static_cast<Stepper*>(pvTimerGetTimerID(t));
      // Clear pending and re-enable the IRQ we disabled in ISR:
      __HAL_GPIO_EXTI_CLEAR_FLAG(self->_limPin);
      HAL_NVIC_EnableIRQ(self->_extiIRQn);
      // Confirm still pressed with the configured polarity
      GPIO_PinState s = HAL_GPIO_ReadPin(self->_limPort, self->_limPin);
      const bool pressed = (s == GPIO_PIN_SET) == self->_limitActiveHigh;
      if (pressed) self->onLimitTriggered();
    }
  );
}

// This should be called from your HAL_GPIO_EXTI_Callback in main.c:
void Stepper::_onRawLimitInterruptFromIsr()
{
  BaseType_t woken = pdFALSE;
  // 1) disable EXTI line IRQ to debounce
//  HAL_NVIC_DisableIRQ(EXTI9_5_IRQn);
  HAL_NVIC_DisableIRQ(_extiIRQn);           // disable the *correct* IRQ group

  // 2) clear any stray pending interrupt
  __HAL_GPIO_EXTI_CLEAR_FLAG(_limPin);
  // 3) start the debounce timer
  xTimerStartFromISR(_debounceTimer, &woken);
  portYIELD_FROM_ISR(woken);
}

// Your public handler once debounce confirms it’s really pressed
void Stepper::onLimitTriggered()
{
//  HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);

  if (_softStopOnLimit && _togglesRemaining != 0) {
    // Gentle stop: reshape the current move into a decel tail and let the ISR finish it
    _requestSoftStop();
    return;  // do not signal "done" yet; _stepTick() will when the tail ends
  }

  // stop the motor immediately
  stop();

  // if you want to treat a limit hit as “done” for the orchestrator:
  BaseType_t w = pdFALSE;
  xEventGroupSetBitsFromISR(
    Orchestrator::getDoneEvents(),
    _doneBit,
    &w
  );
  portYIELD_FROM_ISR(w);
}

//------------------------------------------------------------------------------
// Static dispatcher from HAL’s EXTI callback — call this in main.c:
void Stepper::handleExtiFromIsr(uint16_t pin)
{
  for (int i = 0; i < NUM_AXES; ++i) {
	Stepper* s = _axes[i];
	if (s && s->_limPin == pin) {
	  s->_onRawLimitInterruptFromIsr();
	  break;
	}
  }
}


// =============================================================================
//  C‐API wrappers: one set per motor
// =============================================================================

extern TIM_HandleTypeDef htim2;
extern TIM_HandleTypeDef htim7;
extern TIM_HandleTypeDef htim10;
extern TIM_HandleTypeDef htim13;
extern TIM_HandleTypeDef htim14;
#if (LC_PRESSURE_PORTS > 1)
extern TIM_HandleTypeDef htim14;
#endif

extern "C" void MX_STEPPERX_Init(void) {
  static Stepper s1;
#if (LC_PRESSURE_PORTS > 1)
  bool invertDir = false;
  bool homeDir = false;
#else
  bool invertDir = true;
  bool homeDir = false;
#endif
  s1.begin(Stepper::X_AXIS,
		   &htim2,
           GPIOF, GPIO_PIN_11,    // STEP
           GPIOG, GPIO_PIN_3,    // DIR
           GPIOG, GPIO_PIN_5,  // ENABLE

		   BIT_STEPPER1_DONE,	// Stop-bit
		   0,					// Prescaler
		   invertDir,				// Invert direction
		   homeDir);				// Home direction
  s1.attachLimitSwitch(GPIOG,GPIO_PIN_6,pdMS_TO_TICKS(15));
  s1.addDriver(GPIOG, GPIO_PIN_4,    // STEP
               GPIOC, GPIO_PIN_1,    // DIR
               GPIOA, GPIO_PIN_0);  // ENABLE
}

extern "C" void MX_STEPPERY_Init(void) {
  static Stepper s2;
#if (LC_PRESSURE_PORTS > 1)
  bool invertDir = true;
  bool homeDir = false;
#else
  bool invertDir = false;
  bool homeDir = true;
#endif
  s2.begin(Stepper::Y_AXIS,
		   &htim7,
           GPIOG, GPIO_PIN_0,    // STEP
           GPIOG, GPIO_PIN_1,    // DIR
           GPIOF, GPIO_PIN_15,  // ENABLE
		   BIT_STEPPER2_DONE,	// Stop-bit
		   0,					// Prescaler
		   invertDir,			// Invert direction
		   homeDir);			// Home direction
  s2.attachLimitSwitch(GPIOG,GPIO_PIN_9,pdMS_TO_TICKS(15));
}

extern "C" void MX_STEPPERZ_Init(void) {
  static Stepper s3;
  s3.begin(Stepper::Z_AXIS,
		   &htim10,
           GPIOF, GPIO_PIN_13,   // STEP
           GPIOF, GPIO_PIN_12,   // DIR
           GPIOF, GPIO_PIN_14,  // ENABLE
		   BIT_STEPPER3_DONE,	// Stop-bit
		   1,					// Prescaler - TIM10 uses APB2 which is twice as fast as APB1
		   true,				// Invert direction
		   false);				// Home direction
  s3.attachLimitSwitch(GPIOG,GPIO_PIN_10,pdMS_TO_TICKS(15));
  s3.setMaxSpeedHz(60000);
}

extern "C" void MX_STEPPERP_Init(void) {
	  static Stepper s4;
#if (LC_PRESSURE_PORTS > 1)
	  bool invertDir = false;
	  bool homeDir = false;
#else
	  bool invertDir = true;
	  bool homeDir = false;
#endif
	  s4.begin(Stepper::P_AXIS,
			   &htim13,
	           GPIOF, GPIO_PIN_9,    // STEP
	           GPIOF, GPIO_PIN_10,    // DIR
	           GPIOG, GPIO_PIN_2,  // ENABLE
			   BIT_STEPPER4_DONE,	// Stop-bit
			   0,					// Prescaler
			   invertDir,				// Invert direction
			   homeDir);				// Home direction
	  s4.attachLimitSwitch(GPIOG,GPIO_PIN_11,pdMS_TO_TICKS(15));
	}
#if (LC_PRESSURE_PORTS > 1)
extern "C" void MX_STEPPERR_Init(void) {
  static Stepper s5;
  s5.begin(Stepper::R_AXIS,
		   &htim14,
           GPIOC, GPIO_PIN_13,    // STEP
           GPIOF, GPIO_PIN_0,    // DIR
           GPIOF, GPIO_PIN_1,  // ENABLE
		   BIT_STEPPER5_DONE,	// Stop-bit
		   0,					// Prescaler
		   false,				// Invert direction
		   false);				// Home direction
  s5.attachLimitSwitch(GPIOG,GPIO_PIN_12,pdMS_TO_TICKS(15));
}
#endif

extern "C" void MX_STEPPERX_Move(uint8_t d,uint32_t steps,uint32_t freq,uint32_t accelSteps) {Stepper::stepperX()->move(d, steps, freq, accelSteps);}
extern "C" void MX_STEPPERY_Move(uint8_t d,uint32_t steps,uint32_t freq,uint32_t accelSteps) {Stepper::stepperY()->move(d, steps, freq, accelSteps);}
extern "C" void MX_STEPPERZ_Move(uint8_t d,uint32_t steps,uint32_t freq,uint32_t accelSteps) {Stepper::stepperZ()->move(d, steps, freq, accelSteps);}
extern "C" void MX_STEPPERP_Move(uint8_t d,uint32_t steps,uint32_t freq,uint32_t accelSteps) {Stepper::stepperP()->move(d, steps, freq, accelSteps);}
#if (LC_PRESSURE_PORTS > 1)
extern "C" void MX_STEPPERR_Move(uint8_t d,uint32_t steps,uint32_t freq,uint32_t accelSteps) {Stepper::stepperR()->move(d, steps, freq, accelSteps);}
#endif

extern "C" void MX_STEPPERX_MoveTo(uint8_t s,uint32_t steps,uint32_t freq,uint32_t accelSteps) {Stepper::stepperX()->moveTo(s, steps, freq, accelSteps);}
extern "C" void MX_STEPPERY_MoveTo(uint8_t s,uint32_t steps,uint32_t freq,uint32_t accelSteps) {Stepper::stepperY()->moveTo(s, steps, freq, accelSteps);}
extern "C" void MX_STEPPERZ_MoveTo(uint8_t s,uint32_t steps,uint32_t freq,uint32_t accelSteps) {Stepper::stepperZ()->moveTo(s, steps, freq, accelSteps);}
extern "C" void MX_STEPPERP_MoveTo(uint8_t s,uint32_t steps,uint32_t freq,uint32_t accelSteps) {Stepper::stepperP()->moveTo(s, steps, freq, accelSteps);}
#if (LC_PRESSURE_PORTS > 1)
extern "C" void MX_STEPPERR_MoveTo(uint8_t s,uint32_t steps,uint32_t freq,uint32_t accelSteps) {Stepper::stepperR()->moveTo(s, steps, freq, accelSteps);}
#endif

extern "C" void MX_STEPPERX_Home(uint32_t fastHz, uint32_t slowHz, uint32_t backoffSteps) {Stepper::stepperX()->home(fastHz, slowHz, backoffSteps);}
extern "C" void MX_STEPPERY_Home(uint32_t fastHz, uint32_t slowHz, uint32_t backoffSteps) {Stepper::stepperY()->home(fastHz, slowHz, backoffSteps);}
extern "C" void MX_STEPPERZ_Home(uint32_t fastHz, uint32_t slowHz, uint32_t backoffSteps) {Stepper::stepperZ()->home(fastHz, slowHz, backoffSteps);}
extern "C" void MX_STEPPERP_Home(uint32_t fastHz, uint32_t slowHz, uint32_t backoffSteps) {Stepper::stepperP()->home(fastHz, slowHz, backoffSteps);}
#if (LC_PRESSURE_PORTS > 1)
extern "C" void MX_STEPPERR_Home(uint32_t fastHz, uint32_t slowHz, uint32_t backoffSteps) {Stepper::stepperR()->home(fastHz, slowHz, backoffSteps);}
#endif

extern uint8_t MX_STEPPERX_IsBusy(void){ return Stepper::stepperX()->isBusy(); }
extern uint8_t MX_STEPPERY_IsBusy(void){ return Stepper::stepperY()->isBusy(); }
extern uint8_t MX_STEPPERZ_IsBusy(void){ return Stepper::stepperZ()->isBusy(); }
extern uint8_t MX_STEPPERP_IsBusy(void){ return Stepper::stepperP()->isBusy(); }
#if (LC_PRESSURE_PORTS > 1)
extern uint8_t MX_STEPPERR_IsBusy(void){ return Stepper::stepperR()->isBusy(); }
#endif

extern "C" void MX_STEPPERX_Stop(void)  { Stepper::stepperX()->stop(); }
extern "C" void MX_STEPPERY_Stop(void)  { Stepper::stepperY()->stop(); }
extern "C" void MX_STEPPERZ_Stop(void)  { Stepper::stepperZ()->stop(); }
extern "C" void MX_STEPPERP_Stop(void)  { Stepper::stepperP()->stop(); }
#if (LC_PRESSURE_PORTS > 1)
extern "C" void MX_STEPPERR_Stop(void)  { Stepper::stepperR()->stop(); }
#endif

extern "C" int32_t MX_STEPPERX_GetPos(){ return Stepper::stepperX()->getPosition(); }
extern "C" int32_t MX_STEPPERY_GetPos(){ return Stepper::stepperY()->getPosition(); }
extern "C" int32_t MX_STEPPERZ_GetPos(){ return Stepper::stepperZ()->getPosition(); }
extern "C" int32_t MX_STEPPERP_GetPos(){ return Stepper::stepperP()->getPosition(); }
#if (LC_PRESSURE_PORTS > 1)
extern "C" int32_t MX_STEPPERR_GetPos(){ return Stepper::stepperR()->getPosition(); }
#endif

extern "C" void MX_DISPATCH(TIM_HandleTypeDef* htim) {
	Stepper::dispatch(htim);
}

extern "C" void MX_ATTACH_LIMIT(uint16_t GPIO_Pin){
	Stepper::handleExtiFromIsr(GPIO_Pin);
}
