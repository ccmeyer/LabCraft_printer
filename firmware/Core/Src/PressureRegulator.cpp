/*
 * PressureRegulator.cpp
 *
 *  Created on: Jun 21, 2025
 *      Author: conar
 */

#include "PressureRegulator.h"
#include "PressureRegulatorMath.h"
#include "Orchestrator.h"
#include "Logger.h"
#include "Printer.h"
#include "timers.h"
#include "FreeRTOS.h"
#include "event_groups.h"
#include "stm32f4xx_hal.h"
#include "WatchdogSupervisor.h"
#include <cmath>

static inline uint8_t pr_port_code(GPIO_TypeDef* p) {
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

static inline void enable_gpio_clock(GPIO_TypeDef* p){
  if (p==GPIOA) __HAL_RCC_GPIOA_CLK_ENABLE();
  else if (p==GPIOB) __HAL_RCC_GPIOB_CLK_ENABLE();
  else if (p==GPIOC) __HAL_RCC_GPIOC_CLK_ENABLE();
  else if (p==GPIOD) __HAL_RCC_GPIOD_CLK_ENABLE();
  else if (p==GPIOE) __HAL_RCC_GPIOE_CLK_ENABLE();
  else if (p==GPIOF) __HAL_RCC_GPIOF_CLK_ENABLE();
  else if (p==GPIOG) __HAL_RCC_GPIOG_CLK_ENABLE();
  else if (p==GPIOH) __HAL_RCC_GPIOH_CLK_ENABLE();
}

static inline int pr_pin_number_from_mask(uint16_t pinmask) {
  for (int i=0;i<16;++i) if ((pinmask & (1u<<i))!=0) return i;
  return 0;
}

static inline bool rtos_running() {
  return xTaskGetSchedulerState() == taskSCHEDULER_RUNNING;
}

// ——— Registry init ———
PressureRegulator* PressureRegulator::_registry[PressureRegulator::MAX_REGS] = { nullptr };
int                PressureRegulator::_regCount = 0;

void PressureRegulator::begin(
  Stepper&           stepper,
  TIM_HandleTypeDef* htim,
  uint8_t			 sensorPort,
  int32_t              targetPressure,
  uint32_t           minRateHz,
  uint32_t           maxRateHz,
  int32_t              tolerance,
  GPIO_TypeDef*      valvePort,
  uint16_t           valvePin,
  uint32_t            doneBit
) {
  _stepper = &stepper;
  _htim    = htim;
  _sensorPort = sensorPort;
  _target  = targetPressure;
  _minHz   = minRateHz;
  _maxHz   = maxRateHz;
  _tol     = tolerance;
  _valvePort = valvePort;
  _valvePin  = valvePin;
  _stepping  = false;
  _homing    = false;
  _resetting = false;
  _printTol = 3;
  _doneBit = doneBit;

  _active = false;
  _quietActive = false;
  _quietPreHold = false;
//  _pausedByQuiet = false;
  _freezeI = false;
  _I_contrib     = 0;
  _integral      = 0;

  enable_gpio_clock(_valvePort);
  // ensure valve closed at start
  HAL_GPIO_WritePin(_valvePort, _valvePin, GPIO_PIN_RESET);

  _minHz = (minRateHz == 0 ? 1u : minRateHz);
  _maxHz = (maxRateHz < _minHz ? _minHz : maxRateHz);

  // Register ourselves:
  if (_regCount < MAX_REGS) {
    _registry[_regCount++] = this;
  }

  // Create the periodic regulation task
  BaseType_t ok = xTaskCreate(taskEntry, "PReg", 1024, this,
                              tskIDLE_PRIORITY + 4, &_taskHandle);

//  Logger::instance()->log("[PReg] xTaskCreate ok=%ld handle=%p freeHeap=%lu\r\n",
//                          (long)ok, _taskHandle, (unsigned long)xPortGetFreeHeapSize());
  if (ok != pdPASS) {
//    Logger::instance()->log("[PReg] xTaskCreate failed (stack=%u words)\r\n", 2048u);
    return;
  }
  // Suspend so it cannot run until start()
  if (_taskHandle) {
    vTaskSuspend(_taskHandle);
  }
  Watchdog_DisableTask((_sensorPort == 0u) ? CRASH_TASK_PREG_P : CRASH_TASK_PREG_R);
  _stepper->stop();
}


void PressureRegulator::start() {
  if (_active) return;
  _active = true;
  PressureSensor::instance()->clearSafetyFault(_sensorPort);

  _quietActive   = false;
  _quietPreHold  = false;
//  _pausedByQuiet = false;
  _freezeI       = false;
  _I_contrib     = 0;

  if (_innerPort != nullptr && _innerPin != 0) {
    __HAL_GPIO_EXTI_CLEAR_FLAG(_innerPin);
  }
  if (_stepper) _stepper->enableMotor();  // <-- ensure enabled


  int32_t measured = PressureSensor::instance()->getPressure(_sensorPort);
  _lastError = measured - _target;
  _integral  = 0;

  // seed step speed from proportional term only
  int64_t uS = (int64_t)_KPc  * (int64_t)_lastError; // scaled
  uint32_t initHz = (uint32_t)( llabs(uS) / GAIN );
  if (initHz < _minHz) initHz = _minHz;
  if (initHz > _maxHz) initHz = _maxHz;
  bool dir = (_lastError < 0);

  _lastRateHz = initHz;
  _lastDir    = dir;
  _stepping   = false;

  if (_taskHandle) vTaskResume(_taskHandle);
  Watchdog_EnableTask((_sensorPort == 0u) ? CRASH_TASK_PREG_P : CRASH_TASK_PREG_R);
  Logger::instance()->log("[PReg] START port=%u handle=%p\r\n",
                          (unsigned)_sensorPort, _taskHandle);
  //  if (_taskHandle) xTaskNotifyGive(_taskHandle);
}

void PressureRegulator::pause() {
  _active = false;
  if (_taskHandle) vTaskSuspend(_taskHandle);
  Watchdog_DisableTask((_sensorPort == 0u) ? CRASH_TASK_PREG_P : CRASH_TASK_PREG_R);
  if (_stepping) { _stepper->stop(); _stepping = false; }
  _integral = 0;
}

//void PressureRegulator::setPrintProfile(bool enabled) {
//  _KPc = enabled ? _KP_print : _KP_track;
//  _KIc = enabled ? _KI_print : _KI_track;
//  _KDc = enabled ? _KD_print : _KD_track;
//  _maxHzDeltaPerLoop = enabled ? _maxHzDeltaPerLoop_print : 2000;
//}

void PressureRegulator::setPrintProfile(bool enabled) {
  taskENTER_CRITICAL();  // avoid races with controlLoop on _integral/_KIc

  PressureRegulatorMath::ProfileState state{};
  state.kpCurrent = _KPc;
  state.kiCurrent = _KIc;
  state.kdCurrent = _KDc;
  state.kpPrint = _KP_print;
  state.kiPrint = _KI_print;
  state.kdPrint = _KD_print;
  state.kpTrack = _KP_track;
  state.kiTrack = _KI_track;
  state.kdTrack = _KD_track;
  state.integral = _integral;
  state.iContrib = _I_contrib;
  state.iCap = I_CAP;
  state.maxHzDeltaPerLoop = _maxHzDeltaPerLoop;
  state.maxHzDeltaPrint = _maxHzDeltaPerLoop_print;
  state.maxHzDeltaTrack = MAX_HZ_DELTA_PER_LOOP;

  state = PressureRegulatorMath::applyPrintProfile(state, enabled);

  _KPc = state.kpCurrent;
  _KIc = state.kiCurrent;
  _KDc = state.kdCurrent;
  _integral = state.integral;
  _I_contrib = state.iContrib;
  _maxHzDeltaPerLoop = state.maxHzDeltaPerLoop;

  taskEXIT_CRITICAL();
}

void PressureRegulator::beginDispenseQuiet(uint32_t /*pre_ms*/) {
  _quietActive  = true;
  _quietPreHold = true;      // stay quiet until endDispenseQuiet() is called
  _freezeI      = true;
//  if (_stepping) { _stepper->pauseMove(); _pausedByQuiet = true; }
  // Stop any in-flight “infinite” move so we won’t resume with stale sign/speed.
  if (_stepping) {
    _stepper->stop();
    _stepping = false;
  }

  // Reset derivative baseline to avoid a D-kick when we resume
  int32_t p = PressureSensor::instance()->getPressure(_sensorPort);
  _lastError = p - _target;
}

void PressureRegulator::endDispenseQuiet(uint32_t post_ms) {
  _quietPreHold     = false;                                   // allow release by time
  _quietReleaseTick = xTaskGetTickCount() + pdMS_TO_TICKS(post_ms);
}

void PressureRegulator::setRelativeTarget(bool sign, int32_t p) {
	if (sign) _target += p;
	else _target -= p;
}

static inline float clampf(float v, float lo, float hi) {
  return (v < lo) ? lo : (v > hi) ? hi : v;
}


// Use these from Orchestrator (see above)
void PressureRegulator::setTargetSafe(int32_t requested) {
		  PressureRegulatorMath::TargetLimits limits{};
		  limits.currentTarget = _target;
		  limits.minTarget = _minTarget;
		  limits.maxTarget = _maxTarget;
		  limits.maxCmdStep = _maxCmdStep;
		  limits.maxRelStep = _maxRelStep;
		  _target = PressureRegulatorMath::clampTarget(limits, requested);
		  _pressureOk = false;
		}

void PressureRegulator::setRelativeTargetSafe(bool sign, int32_t delta) {
		  PressureRegulatorMath::TargetLimits limits{};
		  limits.currentTarget = _target;
		  limits.minTarget = _minTarget;
		  limits.maxTarget = _maxTarget;
		  limits.maxCmdStep = _maxCmdStep;
		  limits.maxRelStep = _maxRelStep;
		  _target = PressureRegulatorMath::clampRelativeTarget(limits, sign, delta);
		  _pressureOk = false;
}

void PressureRegulator::openValve() {
	HAL_GPIO_WritePin(_valvePort, _valvePin, GPIO_PIN_SET);
}
void PressureRegulator::closeValve() {
	HAL_GPIO_WritePin(_valvePort, _valvePin, GPIO_PIN_RESET);
}

void PressureRegulator::homeWithValve(uint32_t fastHz, uint32_t slowHz, uint32_t backoffSteps) {
    // Prevent control loop from issuing new moves
    _homing = true;
    Printer::instance()->pauseDispense();
    const CrashTaskId watchdogTaskId = (_sensorPort == 0u) ? CRASH_TASK_PREG_P : CRASH_TASK_PREG_R;
//    if (_taskHandle) vTaskSuspend(_taskHandle);
    // If called from our own control task, don't suspend ourselves.
    TaskHandle_t me = xTaskGetCurrentTaskHandle();
    const bool calledFromOwnTask = (_taskHandle && me == _taskHandle);

    if (!calledFromOwnTask && _taskHandle) {
      vTaskSuspend(_taskHandle);
      Watchdog_DisableTask(watchdogTaskId);
    }


    // Open valve
    HAL_GPIO_WritePin(_valvePort, _valvePin, GPIO_PIN_SET);
	Logger::instance()->log("homing-valve open\r\n");

    if (_stepping) {
        _stepper->stop();         // kill the hardware timer
        _stepping = false;        // clear our flag
        vTaskDelay(pdMS_TO_TICKS(10)); // give it a moment to settle
    }

    // Perform homing on the stepper
    _stepper->home(fastHz, slowHz, backoffSteps);

    // Close valve
    HAL_GPIO_WritePin(_valvePort, _valvePin, GPIO_PIN_RESET);

    // Resume control loop
    _homing = false;
    // Only resume if we are supposed to be active
//    if (_active && _taskHandle) {
//      vTaskResume(_taskHandle);
//    }
    if (!calledFromOwnTask && _active && _taskHandle) {
      vTaskResume(_taskHandle);
      Watchdog_EnableTask(watchdogTaskId);
    }
    Printer::instance()->resumeDispense();
    Logger::instance()->log("homing-complete\r\n");
}

void PressureRegulator::resetSyringe() {
    // 1) mark and pause
    _resetting = true;
    Logger::instance()->log("[PReg] Starting syringe reset\r\n");
    Printer::instance()->pauseDispense();

    // 2) open the valve for free flow
    HAL_GPIO_WritePin(_valvePort,_valvePin,GPIO_PIN_SET);

    if (_stepping) {
        _stepper->stop();         // kill the hardware timer
        _stepping = false;        // clear our flag
        vTaskDelay(pdMS_TO_TICKS(10)); // give it a moment to settle
    }

    int32_t pos   = _stepper->getPosition();
	int32_t delta = _resetPos - pos;

	if (delta != 0) {
	  // 4a) direction: true = forward (positive), false = reverse (negative)
	  bool dir = (delta > 0);

	  // 4b) number of steps = |delta|
	  uint32_t steps = static_cast<uint32_t>(std::abs(delta));

	  // 5) command the stepper
	  uint32_t runHz = (_maxHz ? _maxHz : 500);
	  _stepper->move(dir, steps, runHz, /*accel*/2000);

	  // 6) block until it’s done
	  const TickType_t waitPeriod = pdMS_TO_TICKS(5);
	  while (_stepper->isBusy()) {
		  vTaskDelay(waitPeriod);
	  }
	} else {
	  Logger::instance()->log("[PReg] Already at RESET_POS, skipping motion\r\n");
	}

    // 6) close the valve and resume printing
    HAL_GPIO_WritePin(_valvePort,_valvePin,GPIO_PIN_RESET);
    vTaskDelay(pdMS_TO_TICKS(1000)); // give it a moment to settle
    Printer::instance()->resumeDispense();

    Logger::instance()->log("[PReg] Syringe reset complete\r\n");
    _resetting = false;
}

void PressureRegulator::homeWithValveFast(){
	homeWithValve(kHomeFastHzDefault, kHomeSlowHzDefault, kHomeBackoffDefault);
}


void PressureRegulator::controlLoop() {
  const TickType_t period = pdMS_TO_TICKS(5);  // 200 Hz tick
  const CrashTaskId watchdogTaskId = (_sensorPort == 0u) ? CRASH_TASK_PREG_P : CRASH_TASK_PREG_R;
  Watchdog_EnableTask(watchdogTaskId);
  Logger::instance()->log("CONTROL LOOP\r\n");
  for (;;) {
    Watchdog_CheckIn(watchdogTaskId);

	  // ---- Quiet window handling ----
	  if (_quietActive) {
	    if (_quietPreHold) {
	      // Still in the pre-hold phase: remain quiet indefinitely until endDispenseQuiet()
	      vTaskDelay(period);
	      continue;
	    }
	    // Post-hold phase: release once the time has elapsed
	    if ((int32_t)(xTaskGetTickCount() - _quietReleaseTick) >= 0) {
	      _quietActive = false;
	      _freezeI     = false;
	      // Intentionally do NOT resume any previous move; we stopped it at beginQuiet.
	      // The next iteration will compute error and start a fresh move with the correct sign/speed.
	    }
	    vTaskDelay(period);
	    continue;
	  }

	// Handle asynchronous requests (inner limit → home)
	uint32_t notif = 0;
	(void)xTaskNotifyWait(0, 0xFFFFFFFFu, &notif, 0);
	if (notif & NOTIF_INNER_LIMIT) {
//	  Logger::instance()->log("[PReg] Inner limit tripped → homing now\r\n");
//	  homeWithValve(kHomeFastHzDefault, kHomeSlowHzDefault, kHomeBackoffDefault);
	  homeWithValveFast();
	  // After homing, continue loop; we will re-enter _active flow as usual.
	}

    if (!_active) {
      if (_stepping) { _stepper->stop(); _stepping = false; }
      vTaskDelay(period);
      continue;
    }
    if (_homing || _resetting) { vTaskDelay(period); continue; }

    int32_t pos = _stepper->getPosition();
    if ( (uint32_t)llabs((long long)pos) >= _stepLimit ) {
//      Logger::instance()->log("[PReg] Position exceeded, auto-reset syringe\r\n");
      homeWithValveFast();
      vTaskDelay(period);
      continue;
    }

    // 1) sample pressure (INT)
    int32_t pressure = PressureSensor::instance()->getPressure(_sensorPort);

    // sanity bounds on target
    if (_target < _minTarget || _target > _maxTarget) {
      Logger::instance()->log("[PReg] target out of range: %ld\r\n", (long)_target);
      // bring target back gently toward measured within rails
      if (_target < _minTarget) _target = _minTarget;
      if (_target > _maxTarget) _target = _maxTarget;
      vTaskDelay(period);
      continue;
    }

    int32_t error = pressure - _target;

    // READY flag / print gating
    _pressureOk = ( llabs((long long)error) <= _printTol );
    if (_pressureOk && _doneBit != 0) {
      xEventGroupSetBits(Orchestrator::getDoneEvents(), _doneBit);
    }

    // 2) Integer PID with runtime gains
    if (!_freezeI && _KIc != 0) {
      _integral += (int64_t)error;
      if (_integral >  I_CAP) _integral =  I_CAP;
      if (_integral < -I_CAP) _integral = -I_CAP;
    }
    int32_t dErr = error - _lastError;
    _lastError   = error;

    int64_t uS = (int64_t)_KPc * (int64_t)error
               + (int64_t)_KIc * (int64_t)_integral
               + (int64_t)_KDc * (int64_t)dErr;

//    // 2) Integer PID (scaled)
//    _integral += (int64_t)error;                 // Ki already contains dt
//    // anti-windup (keep integral within a sane band)
//    const int64_t I_CAP = 20000;                 // tune as needed
//    if (_integral >  I_CAP) _integral =  I_CAP;
//    if (_integral < -I_CAP) _integral = -I_CAP;
//
//    int32_t dErr = error - _lastError;
//    _lastError   = error;
//
//    int64_t uS =
//        (int64_t)KP_S * (int64_t)error
//      + (int64_t)KI_S * (int64_t)_integral
//      + (int64_t)KD_S * (int64_t)dErr;

    uint32_t rawHz = (uint32_t)( llabs(uS) / GAIN );
    if (rawHz < _minHz) rawHz = _minHz;
    if (rawHz > _maxHz) rawHz = _maxHz;
    if (rawHz == 0) rawHz = (_minHz ? _minHz : 1);  // never 0 Hz


    // optional rate limiting instead of EMA (keeps it integer)
    if (_stepping) {
      uint32_t desired = rawHz;
      if (desired > _lastRateHz) {
        uint32_t inc = desired - _lastRateHz;
        if (inc > _maxHzDeltaPerLoop) desired = _lastRateHz + _maxHzDeltaPerLoop;
      } else {
        uint32_t dec = _lastRateHz - desired;
        if (dec > _maxHzDeltaPerLoop) desired = _lastRateHz - _maxHzDeltaPerLoop;
      }
      rawHz = desired;
    }

    bool dir = (error < 0);
    // Decide what direction we SHOULD move now
    bool desiredDir = (error < 0);  // same logic you use later

    // If we are currently stepping in the wrong direction (i.e., making error worse),
    // stop immediately and let the next iteration start a fresh move with the right sign.
    if (_stepping) {
      bool movingWrongWay =
          ( desiredDir && (_lastDir == false) ) ||   // need to push up, but lastDir was "down"
          (!desiredDir && (_lastDir == true) );      // need to pull down, but lastDir was "up"

      if (movingWrongWay) {
        _stepper->stop();
        _stepping    = false;
        _integral    = 0;     // harmless with KI=0 during print; also helps if KI>0 in track
        _lastRateHz  = 0;     // so we don’t rate-limit from an old high speed
      }
    }

    // 3) command stepper
    if (!_stepping) {
      _stepper->enableMotor();
      _stepper->move(dir, MAX_STEPS, rawHz, /*accel*/1);
      _stepping  = true;
      _lastRateHz= rawHz;
      _lastDir   = dir;
    } else {
      if (rawHz != _lastRateHz) {
        _stepper->setSpeedHz(rawHz);
        _lastRateHz = rawHz;
      }
      if (dir != _lastDir) {
        HAL_GPIO_WritePin(_stepper->dirPort(), _stepper->dirPin(),
                          dir ? GPIO_PIN_SET : GPIO_PIN_RESET);
        _lastDir = dir;
      }
    }

    // 4) deadband: stop once inside tolerance
    if ( llabs((long long)error) <= _tol && _stepping ) {
      _stepper->stop();
      _stepping = false;
      _integral = 0;
    }

    vTaskDelay(period);
  }
}

void PressureRegulator::attachInnerLimitSwitch(GPIO_TypeDef* port,
                                               uint16_t      pin,
                                               TickType_t    debounceMs,
                                               bool          activeHigh)
{
  _innerPort       = port;
  _innerPin        = pin;
  _innerActiveHigh = activeHigh;

  // 1) Ensure clocks are on for this GPIO port and SYSCFG
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

  // 2) Configure GPIO as EXTI with correct pull & edge
  GPIO_InitTypeDef gi{};
  gi.Pin   = pin;
  gi.Mode  = activeHigh ? GPIO_MODE_IT_RISING : GPIO_MODE_IT_FALLING;
  gi.Pull  = activeHigh ? GPIO_PULLDOWN       : GPIO_PULLUP;
  gi.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(port, &gi);

  // 3) Route to EXTI line via SYSCFG
  const int line  = pr_pin_number_from_mask(pin);   // 0..15
  const int reg   = line / 4;
  const int shift = (line % 4) * 4;
  uint32_t val    = SYSCFG->EXTICR[reg];
  val &= ~(0xFu << shift);
  val |= (uint32_t)pr_port_code(port) << shift;
  SYSCFG->EXTICR[reg] = val;

  // 4) Compute and enable the IRQ group
  _innerLine = (uint8_t)line;
  if      (line <= 4) _innerIRQn = (IRQn_Type)(EXTI0_IRQn + line);
  else if (line <= 9) _innerIRQn = EXTI9_5_IRQn;
  else                _innerIRQn = EXTI15_10_IRQn;

  HAL_NVIC_SetPriority(_innerIRQn, 6, 0);

  // Clear any latent pending bits before we enable the IRQ
  __HAL_GPIO_EXTI_CLEAR_FLAG(pin);

  // 5) Software one-shot debounce timer
  _innerDebounceTmr = xTimerCreate(
    "RegInnerDbnc", debounceMs, pdFALSE, this,
    [](TimerHandle_t t){
      auto *self = static_cast<PressureRegulator*>(pvTimerGetTimerID(t));
      // Clear & re-enable the IRQ we disabled in ISR:
      __HAL_GPIO_EXTI_CLEAR_FLAG(self->_innerPin);
      HAL_NVIC_EnableIRQ(self->_innerIRQn);

      // Confirm it's still pressed with the configured polarity
      GPIO_PinState s = HAL_GPIO_ReadPin(self->_innerPort, self->_innerPin);
      const bool pressed = ((s == GPIO_PIN_SET) == self->_innerActiveHigh);
      if (pressed && self->_taskHandle) {
        xTaskNotify(self->_taskHandle, NOTIF_INNER_LIMIT, eSetBits);
      }
    }

  );
  HAL_NVIC_EnableIRQ(_innerIRQn);

}

void PressureRegulator::_onRawInnerLimitInterruptFromIsr()
{
  // If RTOS isn't running yet, just clear and bail. We'll catch it later.
  if (!rtos_running() || _innerDebounceTmr == nullptr) {
    __HAL_GPIO_EXTI_CLEAR_FLAG(_innerPin);
    return;
  }

  BaseType_t woken = pdFALSE;
  HAL_NVIC_DisableIRQ(_innerIRQn);
  __HAL_GPIO_EXTI_CLEAR_FLAG(_innerPin);
  xTimerStartFromISR(_innerDebounceTmr, &woken);
  portYIELD_FROM_ISR(woken);
}

void PressureRegulator::handleInnerLimitFromIsr(uint16_t pin)
{
  for (int i = 0; i < _regCount; ++i) {
    auto *r = _registry[i];
    if (r && r->_innerPin == pin) {
      r->_onRawInnerLimitInterruptFromIsr();
      break;
    }
  }
}

// C‐API wrappers

extern "C" {

//// Regulator for chamber 1 (axis #4 / StepperP / TIM13)
//void MX_PRESSURE_REGP_Init(int32_t target, uint32_t minHz, uint32_t maxHz, int32_t tol) {
//  static PressureRegulator regP;
//  extern TIM_HandleTypeDef htim13;
//  // StepperP motor  initialized with MX_STEPPERP_Init()
//  regP.begin(*Stepper::stepperP(),
//             &htim13,
//			 0,		// Sensor port
//             target, minHz, maxHz, tol,
//			 GPIOD,GPIO_PIN_14,
//			 BIT_PRESSURE_P_READY);
//
//  // Inner limit on PG13 (active low with pull-up)
//  regP.attachInnerLimitSwitch(GPIOG, GPIO_PIN_13, pdMS_TO_TICKS(15), /*activeHigh=*/true);
//
//}
// Regulator for chamber 1 (axis #4 / StepperP / TIM13)
void MX_PRESSURE_REGP_Init(int32_t target, uint32_t minHz, uint32_t maxHz, int32_t tol) {
  static PressureRegulator regP;
  extern TIM_HandleTypeDef htim13;
  // StepperP motor  initialized with MX_STEPPERP_Init()
  auto *sp = Stepper::stepperP();
  if (!sp) {
    Logger::instance()->log("[PReg] stepperP() is null\r\n");
    return;
  }
  regP.begin(*sp,
             &htim13,
			 0,		// Sensor port
             target, minHz, maxHz, tol,
			 GPIOD,GPIO_PIN_14,
			 BIT_PRESSURE_P_READY);

  // Inner limit on PG13 (active low with pull-up)
  regP.attachInnerLimitSwitch(GPIOG, GPIO_PIN_13, pdMS_TO_TICKS(15), /*activeHigh=*/true);

}


void MX_PRESSURE_REGP_SetTarget(int32_t p) {
  PressureRegulator::regP().setTarget(p);
}

void MX_REGP_HOME(uint32_t fastHz, uint32_t slowHz, uint32_t backoffSteps) {
	PressureRegulator::regP().homeWithValve(fastHz, slowHz, backoffSteps);
}

#if (LC_PRESSURE_PORTS > 1)

//// Regulator for chamber 2 (axis #5 / StepperR / TIM14)
//void MX_PRESSURE_REGR_Init(int32_t target, uint32_t minHz, uint32_t maxHz, int32_t tol) {
//  static PressureRegulator regR;
//  extern TIM_HandleTypeDef htim14;
//
//  regR.begin(*Stepper::stepperR(),
//             &htim14,
//             1,        // Sensor port
//             target, minHz, maxHz, tol,
//             GPIOD, GPIO_PIN_15,
//             BIT_PRESSURE_R_READY);
//
//  regR.attachInnerLimitSwitch(GPIOG, GPIO_PIN_14, pdMS_TO_TICKS(15), /*activeHigh=*/true);
//}

// Regulator for chamber 2 (axis #5 / StepperR / TIM14)
void MX_PRESSURE_REGR_Init(int32_t target, uint32_t minHz, uint32_t maxHz, int32_t tol) {
  static PressureRegulator regR;
  extern TIM_HandleTypeDef htim14;
  auto *sp = Stepper::stepperR();
  if (!sp) {
    Logger::instance()->log("[PReg] stepperR() is null\r\n");
    return;
  }
  regR.begin(*sp,
             &htim14,
             1,        // Sensor port
             target, minHz, maxHz, tol,
             GPIOD, GPIO_PIN_15,
             BIT_PRESSURE_R_READY);

  regR.attachInnerLimitSwitch(GPIOG, GPIO_PIN_14, pdMS_TO_TICKS(15), /*activeHigh=*/true);
}

void MX_PRESSURE_REGR_SetTarget(int32_t p) {
  PressureRegulator::regR().setTarget(p);
}

void MX_REGR_HOME(uint32_t fastHz, uint32_t slowHz, uint32_t backoffSteps) {
  PressureRegulator::regR().homeWithValve(fastHz, slowHz, backoffSteps);
}

#else

// Legacy build: provide stubs so the whole firmware still links even if something calls these.
void MX_PRESSURE_REGR_Init(int32_t target, uint32_t minHz, uint32_t maxHz, int32_t tol) {
  (void)target; (void)minHz; (void)maxHz; (void)tol;
  Logger::instance()->log("[PReg] REGR init requested, but legacy build has 1 pressure channel\r\n");
}

void MX_PRESSURE_REGR_SetTarget(int32_t p) {
  (void)p;
  // optional: log once if you want (but avoid spamming)
}

void MX_REGR_HOME(uint32_t fastHz, uint32_t slowHz, uint32_t backoffSteps) {
  (void)fastHz; (void)slowHz; (void)backoffSteps;
  Logger::instance()->log("[PReg] REGR home requested, but legacy build has 1 pressure channel\r\n");
}

#endif

void MX_REG_INNER_LIMIT(uint16_t GPIO_Pin) {
  PressureRegulator::handleInnerLimitFromIsr(GPIO_Pin);
}
} // extern "C"
