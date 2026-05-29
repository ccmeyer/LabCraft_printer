/*
 * PressureRegulator.cpp
 *
 *  Created on: Jun 21, 2025
 *      Author: conar
 */

#include "PressureRegulator.h"
#include "ExtiDebounce.h"
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

static TickType_t pregMsToAtLeast1Tick(uint32_t ms)
{
  if (ms == 0u) {
    return 0u;
  }
  TickType_t ticks = pdMS_TO_TICKS(ms);
  return (ticks == 0u) ? 1u : ticks;
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
  seedControlTarget(_target, HAL_GetTick());
  _minHz   = minRateHz;
  _maxHz   = maxRateHz;
  _tol     = tolerance;
  _valvePort = valvePort;
  _valvePin  = valvePin;
  _stepping  = false;
  _homing    = false;
  _resetting = false;
  _vacuumMode = false;
  _doneBit = doneBit;
  _printProfileEnabled = false;
  loadDefaultRuntimeConfig();

  _active = false;
  _quietActive = false;
  _quietPreHold = false;
//  _pausedByQuiet = false;
  _freezeI = false;
  _I_contrib     = 0;
  _integral      = 0;
  _recoveryActive = false;
  _recoveryTicksRemaining = 0;
  _recoveryTicksInitial = 0;
  _recoveryInitialBoostHz = 0;
  _recoveryCurrentBoostHz = 0;
  _recoveryTicksExtended = 0;
  _recoveryBypassRemaining = 0;
  _readyConsecutiveCount = 0;
  _traceLastPressureOk = false;

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

uint32_t PressureRegulator::getControlTarget() const {
  const int32_t raw = controlTargetRaw();
  return (raw < 0) ? 0u : static_cast<uint32_t>(raw);
}

bool PressureRegulator::isTargetRamping() const {
  if (!_targetRampInitialized) {
    return false;
  }
  return PressureRegulatorMath::isTargetRampActive(
      _controlTargetFixed,
      _target,
      TARGET_RAMP_FRACTIONAL_BITS);
}

void PressureRegulator::loadDefaultRuntimeConfig() {
  _readyCfg.readyTolRaw = PressureRegulatorMath::defaultReadyTolRaw(_sensorPort);
  _readyCfg.consecutiveSamples = 1u;
  _printTol = _readyCfg.readyTolRaw;

  if (_sensorPort == 0u) {
    _recoveryCfg = RecoveryConfig{};
    _recoveryCfg.activeTicks = 2;
    _recoveryCfg.baseBoostHz = 300;
    _recoveryCfg.pulseCoeffHzPerUs = 1;
    _recoveryCfg.pressureCoeffHzPerRaw = 0;
    _recoveryCfg.maxBoostHz = 1500;
    _recoveryCfg.recoveryFloorHz = 0;
    _recoveryCfg.recoveryExitErrorRaw = 3;
    _recoveryCfg.maxExtendTicks = 0;
    _recoveryCfg.allowExtendWhileUndershoot = false;
    _recoveryCfg.boostOnlyWhenUndershoot = true;
    _recoveryCfg.linearDecay = true;
  } else {
    _recoveryCfg.activeTicks = 8;
    _recoveryCfg.baseBoostHz = 2000;
    _recoveryCfg.pulseCoeffHzPerUs = 2;
    _recoveryCfg.pressureCoeffHzPerRaw = 1;
    _recoveryCfg.maxBoostHz = 10000;
    _recoveryCfg.recoveryFloorHz = 1200;
    _recoveryCfg.recoveryExitErrorRaw = 4;
    _recoveryCfg.maxExtendTicks = 4;
    _recoveryCfg.allowExtendWhileUndershoot = true;
    _recoveryCfg.boostOnlyWhenUndershoot = true;
    _recoveryCfg.linearDecay = true;
  }

  _slewCfgTrack = SlewConfig{MAX_HZ_DELTA_PER_LOOP, MAX_HZ_DELTA_PER_LOOP, 0};
  if (_sensorPort == 0u) {
    _slewCfgPrint = SlewConfig{600, 1200, 0};
  } else {
    _slewCfgPrint = SlewConfig{1200, 450, 3};
  }
  _slewCfg = _printProfileEnabled ? _slewCfgPrint : _slewCfgTrack;
}

PressureRegulator::RuntimeConfigSnapshot PressureRegulator::getRuntimeConfigSnapshot() const {
  RuntimeConfigSnapshot snapshot{};
  snapshot.recovery = _recoveryCfg;
  snapshot.ready = _readyCfg;
  snapshot.activeSlew = _slewCfg;
  snapshot.trackSlew = _slewCfgTrack;
  snapshot.printSlew = _slewCfgPrint;
  snapshot.printProfileEnabled = _printProfileEnabled;
  return snapshot;
}

void PressureRegulator::restoreRuntimeConfigSnapshot(const RuntimeConfigSnapshot& snapshot) {
  taskENTER_CRITICAL();
  _recoveryCfg = snapshot.recovery;
  _readyCfg = snapshot.ready;
  _printTol = snapshot.ready.readyTolRaw;
  _slewCfgTrack = snapshot.trackSlew;
  _slewCfgPrint = snapshot.printSlew;
  _printProfileEnabled = snapshot.printProfileEnabled;
  _slewCfg = snapshot.activeSlew;
  _recoveryActive = false;
  _recoveryTicksRemaining = 0;
  _recoveryCurrentBoostHz = 0;
  _recoveryBypassRemaining = 0;
  _readyConsecutiveCount = 0;
  taskEXIT_CRITICAL();
}

void PressureRegulator::restoreDefaultRuntimeConfig() {
  taskENTER_CRITICAL();
  loadDefaultRuntimeConfig();
  _recoveryActive = false;
  _recoveryTicksRemaining = 0;
  _recoveryCurrentBoostHz = 0;
  _recoveryBypassRemaining = 0;
  _readyConsecutiveCount = 0;
  taskEXIT_CRITICAL();
}

void PressureRegulator::applyRuntimeRecoveryConfig(const RecoveryConfig& cfg) {
  taskENTER_CRITICAL();
  _recoveryCfg = cfg;
  _recoveryActive = false;
  _recoveryTicksRemaining = 0;
  _recoveryCurrentBoostHz = 0;
  _recoveryBypassRemaining = 0;
  taskEXIT_CRITICAL();
}

void PressureRegulator::applyRuntimeSlewConfig(const SlewConfig& cfg) {
  taskENTER_CRITICAL();
  if (_printProfileEnabled) {
    _slewCfgPrint = cfg;
  } else {
    _slewCfgTrack = cfg;
  }
  _slewCfg = cfg;
  taskEXIT_CRITICAL();
}

void PressureRegulator::applyRuntimeReadyConfig(const ReadyConfig& cfg) {
  taskENTER_CRITICAL();
  _readyCfg = cfg;
  _printTol = cfg.readyTolRaw;
  _readyConsecutiveCount = 0;
  taskEXIT_CRITICAL();
}

void PressureRegulator::seedControlTarget(int32_t targetRaw, uint32_t tickMs) {
  _controlTargetFixed = PressureRegulatorMath::targetRawToFixed(
      targetRaw,
      TARGET_RAMP_FRACTIONAL_BITS);
  _targetRampLastTickMs = tickMs;
  _targetRampInitialized = true;
}

int32_t PressureRegulator::controlTargetRaw() const {
  if (!_targetRampInitialized) {
    return _target;
  }
  return PressureRegulatorMath::targetFixedToRaw(
      _controlTargetFixed,
      TARGET_RAMP_FRACTIONAL_BITS);
}

int32_t PressureRegulator::advanceControlTarget(uint32_t tickMs) {
  if (!_targetRampInitialized) {
    seedControlTarget(_target, tickMs);
    return _target;
  }
  const uint32_t elapsedMs = tickMs - _targetRampLastTickMs;
  _controlTargetFixed = PressureRegulatorMath::advanceRampedTarget(
      _controlTargetFixed,
      _target,
      kSetpointSlewRawPerSec,
      elapsedMs,
      TARGET_RAMP_FRACTIONAL_BITS);
  _targetRampLastTickMs = tickMs;
  return controlTargetRaw();
}

void PressureRegulator::updateRequestedTarget(int32_t requestedTarget) {
  const uint32_t nowMs = HAL_GetTick();
  (void)advanceControlTarget(nowMs);

  const bool changed = (requestedTarget != _target);
  _target = requestedTarget;
  _pressureOk = false;
  _readyConsecutiveCount = 0;
  if (changed && _active && (_stepper != nullptr)) {
    _targetTransitionMonitorActive = true;
    _targetTransitionTravelLogged = false;
    _targetTransitionStartPosition = _stepper->getPosition();
  } else if (changed) {
    _targetTransitionMonitorActive = false;
    _targetTransitionTravelLogged = false;
  }
}

void PressureRegulator::updateTargetTransitionMonitor(int32_t position,
                                                      bool rampActive,
                                                      bool pressureReady) {
  if (!_targetTransitionMonitorActive) {
    return;
  }

  const uint32_t absPosition = static_cast<uint32_t>(llabs(static_cast<long long>(position)));
  const int64_t delta = static_cast<int64_t>(position) -
                        static_cast<int64_t>(_targetTransitionStartPosition);
  const uint32_t absDelta = static_cast<uint32_t>((delta < 0) ? -delta : delta);
  if (!_targetTransitionTravelLogged &&
      ((absPosition >= kTransitionTravelWarnAbsSteps) ||
       (absDelta >= kTransitionTravelWarnDeltaSteps))) {
    Logger::instance()->log("[PReg] setpoint travel warn port=%u pos=%ld delta=%lu target=%ld control=%ld\r\n",
                            static_cast<unsigned>(_sensorPort),
                            static_cast<long>(position),
                            static_cast<unsigned long>(absDelta),
                            static_cast<long>(_target),
                            static_cast<long>(controlTargetRaw()));
    _targetTransitionTravelLogged = true;
  }

  if (!rampActive && pressureReady) {
    _targetTransitionMonitorActive = false;
  }
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
  _recoveryActive = false;
  _recoveryTicksRemaining = 0;
  _recoveryCurrentBoostHz = 0;
  _recoveryTicksExtended = 0;
  _recoveryBypassRemaining = 0;
  _readyConsecutiveCount = 0;

  if (_innerPort != nullptr && _innerPin != 0) {
    __HAL_GPIO_EXTI_CLEAR_FLAG(_innerPin);
  }
  if (_stepper) _stepper->enableMotor();  // <-- ensure enabled

  int32_t measured = _target;
  if (PressureSensor::instance()) {
    measured = static_cast<int32_t>(PressureSensor::instance()->getLatestRaw(_sensorPort));
  }
  int32_t rampStart = measured;
  if (rampStart < activeMinTarget()) rampStart = activeMinTarget();
  if (rampStart > _maxTarget) rampStart = _maxTarget;
  seedControlTarget(rampStart, HAL_GetTick());
  _targetTransitionMonitorActive = (rampStart != _target) && (_stepper != nullptr);
  _targetTransitionTravelLogged = false;
  _targetTransitionStartPosition = (_stepper != nullptr) ? _stepper->getPosition() : 0;

  _lastError = measured - controlTargetRaw();
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
  _targetTransitionMonitorActive = false;
  _targetTransitionTravelLogged = false;
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
  state.maxHzDeltaPerLoop = _slewCfg.maxHzDeltaUpPerLoop;
  state.maxHzDeltaPrint = _slewCfgPrint.maxHzDeltaUpPerLoop;
  state.maxHzDeltaTrack = _slewCfgTrack.maxHzDeltaUpPerLoop;

  state = PressureRegulatorMath::applyPrintProfile(state, enabled);

  _KPc = state.kpCurrent;
  _KIc = state.kiCurrent;
  _KDc = state.kdCurrent;
  _integral = state.integral;
  _I_contrib = state.iContrib;
  _printProfileEnabled = enabled;
  _slewCfg = enabled ? _slewCfgPrint : _slewCfgTrack;

  taskEXIT_CRITICAL();
}

void PressureRegulator::beginDispenseQuiet(uint32_t /*pre_ms*/) {
  _quietActive  = true;
  _quietPreHold = true;      // stay quiet until endDispenseQuiet() is called
  _freezeI      = true;
  recordTraceEvent(PressureTraceEventType::QuietStart);
//  if (_stepping) { _stepper->pauseMove(); _pausedByQuiet = true; }
  // Stop any in-flight “infinite” move so we won’t resume with stale sign/speed.
  if (_stepping) {
    _stepper->stop();
    _stepping = false;
  }

  // Reset derivative baseline to avoid a D-kick when we resume
  int32_t p = _target;
  if (PressureSensor::instance()) {
    p = static_cast<int32_t>(PressureSensor::instance()->getLatestRaw(_sensorPort));
  }
  _lastError = p - controlTargetRaw();
}

void PressureRegulator::endDispenseQuiet(uint32_t post_ms) {
  _quietPreHold     = false;                                   // allow release by time
  _quietReleaseTick = xTaskGetTickCount() + pdMS_TO_TICKS(post_ms);
  recordTraceEvent(PressureTraceEventType::QuietEnd, static_cast<uint16_t>(post_ms));
}

void PressureRegulator::notifyPulseStart(const DisturbanceEvent& ev) {
  _recoveryPressureAtTrigger = ev.pressureAtTrigger;
  _recoveryPulseWidthUs = ev.pulseWidthUs;
  _recoveryTriggerTickMs = ev.tickMs;
  recordTraceEvent(PressureTraceEventType::PulseStart, ev.pulseWidthUs, ev.pressureAtTrigger);
}

void PressureRegulator::notifyPulseEnd(const DisturbanceEvent& ev) {
  _recoveryPressureAtTrigger = ev.pressureAtTrigger;
  _recoveryPulseWidthUs = ev.pulseWidthUs;
  _recoveryTriggerTickMs = ev.tickMs;
  _recoveryInitialBoostHz = PressureRegulatorMath::computeRecoveryBoostHz(
      ev.pressureAtTrigger,
      ev.pulseWidthUs,
      PressureRegulatorMath::RecoveryConfig{
          _recoveryCfg.activeTicks,
          _recoveryCfg.baseBoostHz,
          _recoveryCfg.pulseCoeffHzPerUs,
          _recoveryCfg.pressureCoeffHzPerRaw,
          _recoveryCfg.maxBoostHz,
          _recoveryCfg.recoveryFloorHz,
          _recoveryCfg.recoveryExitErrorRaw,
          _recoveryCfg.maxExtendTicks,
          _recoveryCfg.allowExtendWhileUndershoot,
          _recoveryCfg.boostOnlyWhenUndershoot,
          _recoveryCfg.linearDecay},
      static_cast<uint16_t>(_minTarget));
  _recoveryTicksInitial = _recoveryCfg.activeTicks;
  _recoveryTicksRemaining = _recoveryCfg.activeTicks;
  _recoveryTicksExtended = 0u;
  _recoveryBypassRemaining = _slewCfg.recoveryBypassSlewTicks;
  _recoveryCurrentBoostHz = _recoveryInitialBoostHz;
  _recoveryActive = (_recoveryCurrentBoostHz > 0u) && (_recoveryTicksRemaining > 0u);
  recordTraceEvent(PressureTraceEventType::PulseEnd, ev.pulseWidthUs, ev.pressureAtTrigger);
  if (_recoveryActive) {
    recordTraceEvent(
        PressureTraceEventType::RecoveryStart,
        static_cast<uint16_t>((_recoveryCurrentBoostHz > 0xFFFFu) ? 0xFFFFu : _recoveryCurrentBoostHz),
        _recoveryTicksRemaining);
  }
}

void PressureRegulator::setTarget(int32_t p) {
  updateRequestedTarget(p);
}

void PressureRegulator::setRelativeTarget(bool sign, int32_t p) {
	if (sign) updateRequestedTarget(_target + p);
	else updateRequestedTarget(_target - p);
}

static inline float clampf(float v, float lo, float hi) {
  return (v < lo) ? lo : (v > hi) ? hi : v;
}


// Use these from Orchestrator (see above)
void PressureRegulator::setTargetSafe(int32_t requested) {
		  PressureRegulatorMath::TargetLimits limits{};
		  limits.currentTarget = _target;
		  limits.minTarget = activeMinTarget();
		  limits.maxTarget = _maxTarget;
		  limits.maxCmdStep = _maxCmdStep;
		  limits.maxRelStep = _maxRelStep;
		  updateRequestedTarget(PressureRegulatorMath::clampTarget(limits, requested));
		}

void PressureRegulator::setRelativeTargetSafe(bool sign, int32_t delta) {
		  PressureRegulatorMath::TargetLimits limits{};
		  limits.currentTarget = _target;
		  limits.minTarget = activeMinTarget();
		  limits.maxTarget = _maxTarget;
		  limits.maxCmdStep = _maxCmdStep;
		  limits.maxRelStep = _maxRelStep;
		  updateRequestedTarget(PressureRegulatorMath::clampRelativeTarget(limits, sign, delta));
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
    TaskHandle_t me = xTaskGetCurrentTaskHandle();
    const bool calledFromOwnTask = (_taskHandle && me == _taskHandle);
    const bool taskHandlePresent = (_taskHandle != nullptr);
    bool homeOk = false;

    // If called from our own control task, temporarily remove it from watchdog coverage.
    if (calledFromOwnTask) {
      Watchdog_DisableTask(watchdogTaskId);
    } else if (_taskHandle) {
      vTaskSuspend(_taskHandle);
      Watchdog_DisableTask(watchdogTaskId);
    }

    auto finishHome = [&]() {
      HAL_GPIO_WritePin(_valvePort, _valvePin, GPIO_PIN_RESET);
      _homing = false;

      if (calledFromOwnTask) {
        Watchdog_EnableTask(watchdogTaskId);
        Watchdog_CheckIn(watchdogTaskId);
      } else if (_active && taskHandlePresent) {
        vTaskResume(_taskHandle);
        Watchdog_EnableTask(watchdogTaskId);
      }

      if (homeOk) {
        Printer::instance()->resumeDispense();
        Logger::instance()->log("homing-complete\r\n");
      } else {
        Printer::instance()->cancelDispense();
        Logger::instance()->log("[PReg] Homing failed or timed out; dispense canceled\r\n");
      }
    };

    // Open valve
    HAL_GPIO_WritePin(_valvePort, _valvePin, GPIO_PIN_SET);
	Logger::instance()->log("homing-valve open\r\n");

    if (_stepping) {
        _stepper->stop();         // kill the hardware timer
        _stepping = false;        // clear our flag
        vTaskDelay(pregMsToAtLeast1Tick(10u)); // give it a moment to settle
    }

    // Perform homing on the stepper
    homeOk = _stepper->home(fastHz, slowHz, backoffSteps);
    finishHome();
}

void PressureRegulator::resetSyringe(CrashTaskId callerWatchdogTaskId) {
    // 1) mark and pause
    _resetting = true;
    Logger::instance()->log("[PReg] Starting syringe reset\r\n");
    Printer::instance()->pauseDispense();
    bool resetOk = true;

    auto checkInCaller = [&]() {
      if (callerWatchdogTaskId != CRASH_TASK_NONE) {
        Watchdog_CheckIn(callerWatchdogTaskId);
      }
    };

    auto delayWithCallerCheckIn = [&](uint32_t delayMs) {
      TickType_t remaining = pregMsToAtLeast1Tick(delayMs);
      const TickType_t slice = pregMsToAtLeast1Tick(20u);
      while (remaining > 0u) {
        checkInCaller();
        TickType_t step = (remaining > slice) ? slice : remaining;
        vTaskDelay(step);
        remaining -= step;
      }
    };

    auto waitForResetMove = [&](uint32_t steps, uint32_t runHz) -> bool {
      const TickType_t waitPeriod = pregMsToAtLeast1Tick(5u);
      const uint32_t timeoutMs = Stepper::recommendedWaitTimeoutMs(steps, runHz);
      const uint32_t startMs = HAL_GetTick();
      while (_stepper->isBusy()) {
        checkInCaller();
        vTaskDelay(waitPeriod);
        if ((HAL_GetTick() - startMs) >= timeoutMs) {
          _stepper->stop();
          Logger::instance()->log("[PReg] Syringe reset timed out steps=%lu hz=%lu\r\n",
                                  (unsigned long)steps,
                                  (unsigned long)runHz);
          return false;
        }
      }
      return true;
    };

    // 2) open the valve for free flow
    HAL_GPIO_WritePin(_valvePort,_valvePin,GPIO_PIN_SET);

    if (_stepping) {
        _stepper->stop();         // kill the hardware timer
        _stepping = false;        // clear our flag
        delayWithCallerCheckIn(10u); // give it a moment to settle
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
	  resetOk = waitForResetMove(steps, runHz);
	} else {
	  Logger::instance()->log("[PReg] Already at RESET_POS, skipping motion\r\n");
	}

    // 6) close the valve and resume printing
    HAL_GPIO_WritePin(_valvePort,_valvePin,GPIO_PIN_RESET);
    if (resetOk) {
      delayWithCallerCheckIn(1000u); // give it a moment to settle
      Printer::instance()->resumeDispense();
      Logger::instance()->log("[PReg] Syringe reset complete\r\n");
    } else {
      Printer::instance()->cancelDispense();
      Logger::instance()->log("[PReg] Syringe reset failed; dispense canceled\r\n");
    }
    _resetting = false;
}

bool PressureRegulator::enterVacuumMode(int32_t targetRaw,
                                        uint32_t prepPositionSteps,
                                        uint32_t moveHz,
                                        CrashTaskId callerWatchdogTaskId) {
    if (_stepper == nullptr) {
      Logger::instance()->log("[PReg] Vacuum enter failed: no stepper\r\n");
      return false;
    }

    if (prepPositionSteps == 0u) prepPositionSteps = 20000u;
    if (moveHz == 0u) moveHz = 5000u;

    if (targetRaw < _vacuumMinTarget) targetRaw = _vacuumMinTarget;
    if (targetRaw > _minTarget) targetRaw = _minTarget;

    Printer::instance()->pauseDispense();
    homeWithValveFast();
    return enterVacuumModeAfterHome(
        targetRaw,
        prepPositionSteps,
        moveHz,
        callerWatchdogTaskId);
}

bool PressureRegulator::enterVacuumModeAfterHome(int32_t targetRaw,
                                                 uint32_t prepPositionSteps,
                                                 uint32_t moveHz,
                                                 CrashTaskId callerWatchdogTaskId) {
    if (_stepper == nullptr) {
      Logger::instance()->log("[PReg] Vacuum enter failed: no stepper\r\n");
      return false;
    }

    if (prepPositionSteps == 0u) prepPositionSteps = 20000u;
    if (moveHz == 0u) moveHz = 5000u;

    if (targetRaw < _vacuumMinTarget) targetRaw = _vacuumMinTarget;
    if (targetRaw > _minTarget) targetRaw = _minTarget;

    const auto homeSnapshot = _stepper->getLastHomeDiagnosticSnapshot();
    if (!homeSnapshot.success) {
      _vacuumMode = false;
      _resetting = false;
      closeValve();
      Printer::instance()->cancelDispense();
      Logger::instance()->log("[PReg] Vacuum enter failed: refuel home failed\r\n");
      return false;
    }

    Printer::instance()->pauseDispense();
    pause();
    _resetting = true;
    openValve();

    if (_stepping) {
      _stepper->stop();
      _stepping = false;
      vTaskDelay(pregMsToAtLeast1Tick(10u));
    }

    auto checkInCaller = [&]() {
      if (callerWatchdogTaskId != CRASH_TASK_NONE) {
        Watchdog_CheckIn(callerWatchdogTaskId);
      }
    };

    _stepper->enableMotor();
    _stepper->moveTo(true, prepPositionSteps, moveHz, 2000u);
    const uint32_t timeoutMs = Stepper::recommendedWaitTimeoutMs(prepPositionSteps, moveHz);
    const uint32_t startMs = HAL_GetTick();
    const TickType_t waitPeriod = pregMsToAtLeast1Tick(5u);
    bool moveOk = true;
    while (_stepper->isBusy()) {
      checkInCaller();
      vTaskDelay(waitPeriod);
      if ((HAL_GetTick() - startMs) >= timeoutMs) {
        _stepper->stop();
        moveOk = false;
        break;
      }
    }

    closeValve();
    _resetting = false;

    if (!moveOk) {
      _vacuumMode = false;
      Printer::instance()->cancelDispense();
      Logger::instance()->log("[PReg] Vacuum enter failed: prep move timed out\r\n");
      return false;
    }

    _vacuumMode = true;
    updateRequestedTarget(targetRaw);
    start();
    Printer::instance()->resumeDispense();
    Logger::instance()->log("[PReg] Vacuum mode active target=%ld prep=%lu\r\n",
                            (long)targetRaw,
                            (unsigned long)prepPositionSteps);
    return true;
}

bool PressureRegulator::setVacuumTargetSafe(int32_t requested) {
    if (!_vacuumMode) {
      Logger::instance()->log("[PReg] Vacuum target ignored: mode inactive\r\n");
      return false;
    }
    if (requested < _vacuumMinTarget) requested = _vacuumMinTarget;
    if (requested > _minTarget) requested = _minTarget;
    updateRequestedTarget(requested);
    return true;
}

bool PressureRegulator::exitVacuumMode(int32_t restoreTargetRaw,
                                       CrashTaskId callerWatchdogTaskId) {
    const bool wasVacuumMode = _vacuumMode;
    pause();
    _vacuumMode = false;

    if (restoreTargetRaw < _minTarget) restoreTargetRaw = _minTarget;
    if (restoreTargetRaw > _maxTarget) restoreTargetRaw = _maxTarget;

    if (wasVacuumMode) {
      resetSyringe(callerWatchdogTaskId);
    } else {
      closeValve();
    }

    updateRequestedTarget(restoreTargetRaw);
    start();
    Printer::instance()->resumeDispense();
    Logger::instance()->log("[PReg] Vacuum mode exited restore=%ld\r\n",
                            (long)restoreTargetRaw);
    return true;
}

void PressureRegulator::homeWithValveFast(){
	homeWithValve(kHomeFastHzDefault, kHomeSlowHzDefault, kHomeBackoffDefault);
}

void PressureRegulator::requestSafetyHome() {
  if (_taskHandle == nullptr) {
    Logger::instance()->log("[PReg] Safety home requested with no task handle\r\n");
    return;
  }
  xTaskNotify(_taskHandle, NOTIF_SAFETY_HOME, eSetBits);
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
        if (PressureSensor::instance() != nullptr) {
          const auto quietSample = PressureSensor::instance()->getControlSample(_sensorPort);
          const int32_t quietTarget = controlTargetRaw();
          const int32_t quietError = static_cast<int32_t>(quietSample.raw) - quietTarget;
          recordTraceSample(quietSample, quietTarget, quietError, 0, 0, 0, _lastDir);
        }
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
	if (notif & NOTIF_SAFETY_HOME) {
	  Logger::instance()->log("[PReg] Safety home requested\r\n");
	  homeWithValveFast();
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

    // 1) sample pressure from the latest validated control sample
    PressureSensor* sensor = PressureSensor::instance();
    if (sensor == nullptr) {
      vTaskDelay(period);
      continue;
    }
    const auto controlSample = sensor->getControlSample(_sensorPort);
    int32_t pressure = static_cast<int32_t>(controlSample.raw);

    // sanity bounds on target
    const int32_t minTarget = activeMinTarget();
    if (_target < minTarget || _target > _maxTarget) {
      Logger::instance()->log("[PReg] target out of range: %ld\r\n", (long)_target);
      // bring target back gently toward measured within rails
      int32_t clampedTarget = _target;
      if (clampedTarget < minTarget) clampedTarget = minTarget;
      if (clampedTarget > _maxTarget) clampedTarget = _maxTarget;
      updateRequestedTarget(clampedTarget);
      vTaskDelay(period);
      continue;
    }

    const int32_t controlTarget = advanceControlTarget(HAL_GetTick());
    const bool targetRamping = isTargetRamping();
    int32_t error = pressure - controlTarget;

    const bool inReadyBand = PressureRegulatorMath::pressureReadyForRequestedTarget(
        pressure,
        _target,
        _printTol,
        targetRamping);
    if (inReadyBand) {
      if (_readyConsecutiveCount < _readyCfg.consecutiveSamples) {
        _readyConsecutiveCount++;
      }
    } else {
      _readyConsecutiveCount = 0;
    }
    _pressureOk = (_readyConsecutiveCount >= _readyCfg.consecutiveSamples);
    if (_pressureOk != _traceLastPressureOk) {
      recordTraceEvent(_pressureOk ? PressureTraceEventType::ReadyEnter : PressureTraceEventType::ReadyExit,
                       static_cast<uint16_t>((pressure > 0xFFFFL) ? 0xFFFFu : pressure));
      _traceLastPressureOk = _pressureOk;
    }
    if (_pressureOk && _doneBit != 0) {
      xEventGroupSetBits(Orchestrator::getDoneEvents(), _doneBit);
    }
    updateTargetTransitionMonitor(pos, targetRamping, _pressureOk);

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

    const uint32_t pidRequestedHz = (uint32_t)( llabs(uS) / GAIN );
    if (_recoveryActive) {
      _recoveryCurrentBoostHz = computeRecoveryBoostHz();
      bool extendRecovery = PressureRegulatorMath::shouldExtendRecovery(
          error,
          static_cast<int32_t>(_readyCfg.readyTolRaw),
          _recoveryTicksExtended,
          _recoveryCfg.maxExtendTicks,
          _recoveryCfg.allowExtendWhileUndershoot,
          _recoveryCfg.recoveryExitErrorRaw);
      if (_recoveryTicksRemaining > 0u) {
        _recoveryTicksRemaining--;
      }
      if ((_recoveryTicksRemaining == 0u) && extendRecovery) {
        _recoveryTicksRemaining = 1u;
        _recoveryTicksExtended++;
      } else if (_recoveryTicksRemaining == 0u) {
        _recoveryActive = false;
        _recoveryCurrentBoostHz = 0u;
        recordTraceEvent(PressureTraceEventType::RecoveryEnd);
      }
    } else {
      _recoveryCurrentBoostHz = 0u;
    }
    uint32_t requestedHz = PressureRegulatorMath::computeRecoveryRequestedHz(
        PressureRegulatorMath::RecoveryState{
            pidRequestedHz,
            _recoveryCurrentBoostHz,
            _recoveryActive,
            error,
            static_cast<int32_t>(_readyCfg.readyTolRaw),
            _recoveryCfg.boostOnlyWhenUndershoot,
            _maxHz,
            _minHz,
            _recoveryCfg.recoveryFloorHz});
    if (requestedHz == 0u) requestedHz = (_minHz ? _minHz : 1u);

    requestedHz = PressureRegulatorMath::capRequestedHzForTargetRamp(
        requestedHz,
        targetRamping,
        kSetpointSlewSpeedCapHz);

    // Asymmetric slew limiting: faster up, slower down to reduce overshoot risk.
    if (_stepping) {
      if (_recoveryBypassRemaining > 0u) {
        _recoveryBypassRemaining--;
      } else {
        requestedHz = PressureRegulatorMath::applyAsymmetricSlew(
            requestedHz,
            _lastRateHz,
            PressureRegulatorMath::SlewConfig{
                _slewCfg.maxHzDeltaUpPerLoop,
                _slewCfg.maxHzDeltaDownPerLoop});
      }
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
      _stepper->move(dir, MAX_STEPS, requestedHz, /*accel*/1);
      _stepping  = true;
      _lastRateHz= requestedHz;
      _lastDir   = dir;
    } else {
      if (requestedHz != _lastRateHz) {
        _stepper->setSpeedHz(requestedHz);
        _lastRateHz = requestedHz;
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

    recordTraceSample(controlSample, controlTarget, error, dErr, requestedHz, _lastRateHz, dir);

    vTaskDelay(period);
  }
}

uint32_t PressureRegulator::computeRecoveryBoostHz() const {
  return PressureRegulatorMath::decayRecoveryBoostHz(
      _recoveryInitialBoostHz,
      _recoveryTicksRemaining,
      _recoveryTicksInitial,
      _recoveryCfg.linearDecay);
}

void PressureRegulator::recordTraceSample(const PressureSensor::ControlSample& sample,
                                          int32_t controlTargetRaw,
                                          int32_t error,
                                          int32_t dErr,
                                          uint32_t requestedHz,
                                          uint32_t appliedHz,
                                          bool dir) {
  auto& recorder = PressureTraceRecorder::instance();
  if (!recorder.isCapturing()) {
    return;
  }
  PressureTraceSample trace{};
  const uint32_t now = HAL_GetTick();
  const uint32_t dt = now - recorder.startTickMs();
  trace.dtMs = static_cast<uint16_t>((dt > 0xFFFFu) ? 0xFFFFu : dt);
  trace.rawPressure = sample.raw;
  trace.controlPressure = sample.raw;
  trace.avgPressure = sample.avg;
  trace.target = static_cast<uint16_t>((controlTargetRaw < 0) ? 0 : controlTargetRaw);
  trace.error = static_cast<int16_t>(error);
  trace.dError = static_cast<int16_t>(dErr);
  trace.requestedHz = static_cast<uint16_t>((requestedHz > 0xFFFFu) ? 0xFFFFu : requestedHz);
  trace.appliedHz = static_cast<uint16_t>((appliedHz > 0xFFFFu) ? 0xFFFFu : appliedHz);
  if (_pressureOk) trace.flags |= 0x01u;
  if (_stepping) trace.flags |= 0x02u;
  if (dir) trace.flags |= 0x04u;
  if (_quietActive) trace.flags |= 0x08u;
  if (_recoveryActive) trace.flags |= 0x10u;
  if (sample.lastReadRejected) trace.flags |= 0x20u;
  trace.ffBoostHzDiv16 = static_cast<uint8_t>((_recoveryCurrentBoostHz / 16u) > 0xFFu ? 0xFFu : (_recoveryCurrentBoostHz / 16u));
  recorder.recordSample(traceChannel(), trace);
}

void PressureRegulator::recordTraceEvent(PressureTraceEventType type, uint16_t value0, uint16_t value1) {
  auto& recorder = PressureTraceRecorder::instance();
  if (!recorder.isCapturing()) {
    return;
  }
  PressureTraceEvent event{};
  const uint32_t now = HAL_GetTick();
  const uint32_t dt = now - recorder.startTickMs();
  event.dtMs = static_cast<uint16_t>((dt > 0xFFFFu) ? 0xFFFFu : dt);
  event.type = static_cast<uint8_t>(type);
  event.value0 = value0;
  event.value1 = value1;
  recorder.recordEvent(traceChannel(), event);
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
    PressureRegulator::_innerDebounceTimerCb
  );
  if (_innerDebounceTmr == nullptr) {
    Logger::instance()->log("[PReg] debounce timer create failed port=%u\r\n",
                            (unsigned)_sensorPort);
  }
  HAL_NVIC_EnableIRQ(_innerIRQn);

}

void PressureRegulator::_onRawInnerLimitInterruptFromIsr()
{
  // If RTOS isn't running yet, just clear and bail. We'll catch it later.
  if (!rtos_running()) {
    __HAL_GPIO_EXTI_CLEAR_FLAG(_innerPin);
    return;
  }

  BaseType_t woken = pdFALSE;
  _maskInnerExtiLineFromIsr();
  __HAL_GPIO_EXTI_CLEAR_FLAG(_innerPin);

  BaseType_t timerRc = pdFAIL;
  if (_innerDebounceTmr != nullptr) {
    timerRc = xTimerStartFromISR(_innerDebounceTmr, &woken);
  }

  const auto armAction = ExtiDebounce::decideArmAction(
      true,
      _innerDebounceTmr != nullptr,
      timerRc == pdPASS);
  if (armAction == ExtiDebounce::ArmAction::Armed) {
    portYIELD_FROM_ISR(woken);
    return;
  }

  const bool pressed = _isInnerLimitAsserted();
  __HAL_GPIO_EXTI_CLEAR_FLAG(_innerPin);
  _unmaskInnerExtiLineFromIsr();
  if (pressed) {
    _notifyInnerLimitFromIsr(&woken);
  }
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

void PressureRegulator::_maskInnerExtiLineFromIsr()
{
  const uint32_t mask = ExtiDebounce::lineMask(_innerLine);
  if (mask != 0u) {
    EXTI->IMR &= ~mask;
  }
}

void PressureRegulator::_unmaskInnerExtiLineFromIsr()
{
  const uint32_t mask = ExtiDebounce::lineMask(_innerLine);
  if (mask != 0u) {
    EXTI->IMR |= mask;
  }
}

void PressureRegulator::_unmaskInnerExtiLine()
{
  taskENTER_CRITICAL();
  _unmaskInnerExtiLineFromIsr();
  taskEXIT_CRITICAL();
}

void PressureRegulator::_notifyInnerLimitFromIsr(BaseType_t* pxHigherPriorityTaskWoken)
{
  if (_taskHandle != nullptr) {
    xTaskNotifyFromISR(_taskHandle, NOTIF_INNER_LIMIT, eSetBits, pxHigherPriorityTaskWoken);
  }
}

void PressureRegulator::_innerDebounceTimerCb(TimerHandle_t timer)
{
  auto* self = static_cast<PressureRegulator*>(pvTimerGetTimerID(timer));
  if (self == nullptr) {
    return;
  }

  __HAL_GPIO_EXTI_CLEAR_FLAG(self->_innerPin);
  self->_unmaskInnerExtiLine();
  if (self->_isInnerLimitAsserted() && self->_taskHandle != nullptr) {
    xTaskNotify(self->_taskHandle, NOTIF_INNER_LIMIT, eSetBits);
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
