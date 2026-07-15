/*
 * Printer.cpp
 *
 *  Created on: Jun 20, 2025
 *      Author: conar
 */
#include "Printer.h"
#include "Orchestrator.h"
#include "PressureRegulator.h"
#include "stm32f4xx_hal.h"
#include "FreeRTOS.h"
#include "queue.h"
#include "task.h"
#include "Gripper.h"

// CubeMX-generated timer handles
extern TIM_HandleTypeDef htim9; // APB2, TIM9
#if (LC_PRESSURE_PORTS > 1)
// Only needed on dual-channel builds
extern TIM_HandleTypeDef htim4; // APB1, TIM4

#endif

// singleton pointer
static Printer* _printerInstance = nullptr;

namespace {

constexpr uint32_t kTimer16MaxTicks = 65535u;

uint32_t alternateForTimer(TIM_HandleTypeDef* htim) {
  if (htim == nullptr) return 0u;
  if (htim->Instance == TIM4) return GPIO_AF2_TIM4;
  if (htim->Instance == TIM9) return GPIO_AF3_TIM9;
  return 0u;
}

void restoreValvePinAlternate(TIM_HandleTypeDef* htim, GPIO_TypeDef* port, uint16_t pin) {
  if (htim == nullptr || port == nullptr || pin == 0u) return;
  const uint32_t alternate = alternateForTimer(htim);
  if (alternate == 0u) return;
  GPIO_InitTypeDef gpio{};
  gpio.Pin = pin;
  gpio.Mode = GPIO_MODE_AF_PP;
  gpio.Pull = GPIO_PULLDOWN;
  gpio.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  gpio.Alternate = alternate;
  HAL_GPIO_Init(port, &gpio);
}

bool configureValveTimerLongPulse(TIM_HandleTypeDef* htim,
                                  uint32_t channel,
                                  GPIO_TypeDef* port,
                                  uint16_t pin,
                                  uint32_t normalPrescaler,
                                  uint32_t pulseMs,
                                  uint32_t tickUs) {
  if (htim == nullptr || port == nullptr || pin == 0u) {
    return false;
  }
  if (pulseMs == 0u || tickUs == 0u) {
    return false;
  }
  const uint64_t pulseTicks = ((static_cast<uint64_t>(pulseMs) * 1000ULL) + tickUs - 1ULL) /
                              static_cast<uint64_t>(tickUs);
  const uint64_t periodTicks = pulseTicks * 2ULL;
  if (pulseTicks == 0ULL || periodTicks == 0ULL || periodTicks > (static_cast<uint64_t>(kTimer16MaxTicks) + 1ULL)) {
    return false;
  }
  const uint64_t prescalerTicks = (static_cast<uint64_t>(normalPrescaler) + 1ULL) *
                                  static_cast<uint64_t>(tickUs);
  if (prescalerTicks == 0ULL || prescalerTicks > (static_cast<uint64_t>(kTimer16MaxTicks) + 1ULL)) {
    return false;
  }

  restoreValvePinAlternate(htim, port, pin);
  HAL_TIM_OnePulse_Stop(htim, channel);
  HAL_TIM_PWM_Stop(htim, channel);
  __HAL_TIM_DISABLE(htim);

  htim->Init.Prescaler = static_cast<uint32_t>(prescalerTicks - 1ULL);
  htim->Init.Period = static_cast<uint32_t>(periodTicks - 1ULL);
  htim->Init.CounterMode = TIM_COUNTERMODE_UP;
  htim->Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim->Init.RepetitionCounter = 0;
  if (HAL_TIM_Base_Init(htim) != HAL_OK) {
    return false;
  }
  if (HAL_TIM_OnePulse_Init(htim, TIM_OPMODE_SINGLE) != HAL_OK) {
    return false;
  }

  TIM_OC_InitTypeDef sConfigOC = {0};
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = static_cast<uint32_t>(pulseTicks);
  sConfigOC.OCPolarity = TIM_OCPOLARITY_LOW;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  if (HAL_TIM_PWM_ConfigChannel(htim, &sConfigOC, channel) != HAL_OK) {
    return false;
  }

  __HAL_TIM_SET_COUNTER(htim, 0);
  return true;
}

bool startValveTimerLongPulse(TIM_HandleTypeDef* htim, uint32_t channel) {
  if (htim == nullptr) {
    return false;
  }
  __HAL_TIM_DISABLE_IT(htim, TIM_IT_CC1);
  __HAL_TIM_CLEAR_FLAG(htim, TIM_FLAG_CC1);
  __HAL_TIM_CLEAR_FLAG(htim, TIM_FLAG_UPDATE);
  __HAL_TIM_SET_COUNTER(htim, 0);
  if (HAL_TIM_PWM_Start(htim, channel) != HAL_OK) {
    return false;
  }
  (void)HAL_TIM_OnePulse_Start(htim, channel);
  return true;
}

}  // namespace

Printer* Printer::instance() {
  return _printerInstance;
}

Printer::Printer() = default;

void Printer::begin(
    TIM_HandleTypeDef* refuelTimer,
	uint32_t		   refuelChannel,
    GPIO_TypeDef*      refuelPort, uint16_t refuelPin,
    TIM_HandleTypeDef* printTimer,
	uint32_t		   printChannel,
    GPIO_TypeDef*      printPort,  uint16_t printPin,
    uint32_t           printPulseUs,
    uint32_t           refuelPulseUs
) {
  _printerInstance = this;

  _htimRefuel = refuelTimer;
  _refuelChannel = refuelChannel;
  _refuelPort = refuelPort;  _refuelPin = refuelPin;
  _htimPrint  = printTimer;
  _printChannel = printChannel;
  _printPort  = printPort;   _printPin  = printPin;
  _printPulseUs  = printPulseUs;
  _refuelPulseUs = refuelPulseUs;
  _normalPrintPrescaler = _htimPrint ? _htimPrint->Init.Prescaler : 0u;
  _normalRefuelPrescaler = _htimRefuel ? _htimRefuel->Init.Prescaler : 0u;

  // Create queue and task
  _queue = xQueueCreate(8, sizeof(DispenseCommand));
  xTaskCreate(taskEntry, "PRNT", 256, this,
              tskIDLE_PRIORITY + 1, &_taskHandle);
}

void Printer::configureTimerPrint() {
	if (!_htimPrint) return;
    restoreValvePinAlternate(_htimPrint, _printPort, _printPin);

    TIM_OC_InitTypeDef sConfigOC = {0};

    // 1) Update base timer parameters
    _htimPrint->Init.Prescaler         = _normalPrintPrescaler;
    _htimPrint->Init.Period            = (_printPulseUs*2) - 1;  // Set the period (time for one pulse)
    _htimPrint->Init.CounterMode       = TIM_COUNTERMODE_UP;
    _htimPrint->Init.ClockDivision     = TIM_CLOCKDIVISION_DIV1;
    _htimPrint->Init.RepetitionCounter = 0;
    HAL_TIM_Base_Init(_htimPrint);

    // 2) Re-enable one-pulse mode on EVERY reconfigure
    HAL_TIM_OnePulse_Init(_htimPrint, TIM_OPMODE_SINGLE);

    // 3) Set up PWM1 compare value
    sConfigOC.OCMode     = TIM_OCMODE_PWM1;
    sConfigOC.Pulse      = _printPulseUs;         // CCR
    sConfigOC.OCPolarity = TIM_OCPOLARITY_LOW;
    sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
    HAL_TIM_PWM_ConfigChannel(_htimPrint, &sConfigOC, _printChannel);
}

void Printer::configureTimerRefuel() {
#if (LC_PRESSURE_PORTS > 1)
  if (!_htimRefuel) return;
  restoreValvePinAlternate(_htimRefuel, _refuelPort, _refuelPin);

  TIM_OC_InitTypeDef sConfigOC = {0};

  _htimRefuel->Init.Period            = (_refuelPulseUs * 2) - 1;
  _htimRefuel->Init.Prescaler         = _normalRefuelPrescaler;
  _htimRefuel->Init.CounterMode       = TIM_COUNTERMODE_UP;
  _htimRefuel->Init.ClockDivision     = TIM_CLOCKDIVISION_DIV1;
  _htimRefuel->Init.RepetitionCounter = 0;
  HAL_TIM_Base_Init(_htimRefuel);

  HAL_TIM_OnePulse_Init(_htimRefuel, TIM_OPMODE_SINGLE);

  sConfigOC.OCMode     = TIM_OCMODE_PWM1;
  sConfigOC.Pulse      = _refuelPulseUs;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_LOW;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  HAL_TIM_PWM_ConfigChannel(_htimRefuel, &sConfigOC, _refuelChannel);
#else
  // Legacy: no refuel valve/timer
  (void)0;
#endif
}

void Printer::enqueue(
    uint16_t count,
    uint16_t rateHz,
    PulseMode mode,
    uint32_t completionBit,
    bool flashOnLast,
    uint32_t flashCycleId,
    TickType_t gateWaitTimeoutTicks) {
  (void)enqueueWithTimeout(
      count,
      rateHz,
      mode,
      portMAX_DELAY,
      completionBit,
      flashOnLast,
      flashCycleId,
      gateWaitTimeoutTicks);
}

bool Printer::enqueueWithTimeout(
    uint16_t count,
    uint16_t rateHz,
    PulseMode mode,
    TickType_t timeoutTicks,
    uint32_t completionBit,
    bool flashOnLast,
    uint32_t flashCycleId,
    TickType_t gateWaitTimeoutTicks) {
  if (_queue == nullptr) {
    return false;
  }
  DispenseCommand cmd{
      count,
      rateHz,
      mode,
      completionBit,
      flashOnLast,
      flashCycleId,
      gateWaitTimeoutTicks,
      PrinterControlPolicy::captureCommandGeneration(_control)};
  if (xQueueSend(_queue, &cmd, 0) == pdTRUE) {
    return true;
  }
  if (timeoutTicks == 0) {
    return false;
  }
  const TickType_t start = xTaskGetTickCount();
  while ((xTaskGetTickCount() - start) < timeoutTicks) {
    vTaskDelay(1);
    if (xQueueSend(_queue, &cmd, 0) == pdTRUE) {
      return true;
    }
  }
  return false;
}

void Printer::setDiagnosticReadyTimeout(bool enabled, uint32_t timeoutMs) {
  _diagReadyTimeoutEnabled = enabled;
  _diagReadyTimeoutTicks = enabled ? pdMS_TO_TICKS(timeoutMs) : 0;
  if (_diagReadyTimeoutEnabled && _diagReadyTimeoutTicks == 0) {
    _diagReadyTimeoutTicks = 1;
  }
}

bool Printer::isBusy() const {
  return _remaining > 0;
}

uint32_t Printer::getTotalDispensed() const {
  return _totalDispensed;
}

uint32_t Printer::getRemaining() const {
  return _remaining;
}

void Printer::recordDispenseResult(PrinterDispenseResult result, uint32_t flashCycleId) {
  _lastDispenseResult = result;
  _lastDispenseResultCycleId = flashCycleId;
}

void Printer::taskEntry(void* pv) {
  static_cast<Printer*>(pv)->taskLoop();
  vTaskDelete(nullptr);
}

void Printer::taskLoop() {
  DispenseCommand cmd;
  for (;;) {
    if (xQueueReceive(_queue, &cmd, portMAX_DELAY) == pdTRUE) {

      _commandActive = true;
      _remaining = cmd.count;
      bool internalCancelRequested = false;
      PrinterDispenseResult commandResult = PrinterDispenseResult::Completed;
      auto commandCancelled = [&]() {
        return internalCancelRequested ||
               PrinterControlPolicy::isCommandCancelled(_control, cmd.controlGeneration);
      };
      auto waitAtDropletBoundary = [&]() {
        while (PrinterControlPolicy::shouldPauseAtDropletBoundary(
            _control, cmd.controlGeneration, _remaining)) {
          PrinterControlPolicy::acknowledgePause(_control, true);
          (void)ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        }
        PrinterControlPolicy::acknowledgePause(_control, false);
        return _remaining > 0 && !commandCancelled();
      };

      // Apply per-command frequency if provided
      if (cmd.rateHz > 0) {
        _dispenseHz = cmd.rateHz;
      }

      // --- wait for any in-flight gripper refresh to finish and
      //             then hold the vacuum window for the entire job.
      bool printingHoldsGate = false;
      const TickType_t gateWaitStart = xTaskGetTickCount();
      TickType_t gatePollTicks = pdMS_TO_TICKS(10u);
      if (gatePollTicks == 0u) gatePollTicks = 1u;
      for (;;) {
        if (!waitAtDropletBoundary()) {
          break;
        }
        TickType_t waitTicks = gatePollTicks;
        if (cmd.gateWaitTimeoutTicks != portMAX_DELAY) {
          const TickType_t elapsed = xTaskGetTickCount() - gateWaitStart;
          if (elapsed >= cmd.gateWaitTimeoutTicks) {
            waitTicks = 0u;
          } else {
            const TickType_t remainingWait = cmd.gateWaitTimeoutTicks - elapsed;
            if (waitTicks > remainingWait) waitTicks = remainingWait;
          }
        }
        if (Gripper::instance().lockVacuumGate(waitTicks)) {
          printingHoldsGate = true;
          break;
        }
        if (cmd.gateWaitTimeoutTicks != portMAX_DELAY &&
            (xTaskGetTickCount() - gateWaitStart) >= cmd.gateWaitTimeoutTicks) {
          break;
        }
      }
      if (!printingHoldsGate) {
        recordDispenseResult(commandCancelled()
            ? PrinterDispenseResult::Cancelled
            : PrinterDispenseResult::GateTimeout,
            cmd.flashCycleId);
        _remaining = 0;
        if (cmd.completionBit != 0u) {
          xEventGroupSetBits(Orchestrator::getDoneEvents(), cmd.completionBit);
        }
        _commandActive = false;
        continue;
      }

      const uint32_t rateHz = (_dispenseHz == 0u) ? 1u : _dispenseHz;
      TickType_t periodTicks = pdMS_TO_TICKS(1000u / rateHz);
      if (periodTicks == 0) periodTicks = 1;
      TickType_t halfPeriodTicks = periodTicks / 2;
      if (halfPeriodTicks == 0) halfPeriodTicks = 1;
      TickType_t nextPhaseTick = xTaskGetTickCount();
      const TickType_t readyPollTicks = pdMS_TO_TICKS(2);

      auto delayUntil = [&](TickType_t targetTick, bool honorPause) {
        for (;;) {
          if (commandCancelled()) {
            return false;
          }
          if (honorPause && _control.pauseRequested) {
            return false;
          }
          const TickType_t now = xTaskGetTickCount();
          if (static_cast<int32_t>(targetTick - now) <= 0) {
            return true;
          }
          (void)ulTaskNotifyTake(pdTRUE, targetTick - now);
        }
      };
      auto advancePhase = [&](TickType_t stepTicks, bool rebaseOnAnyLate) {
        nextPhaseTick += stepTicks;
        TickType_t now = xTaskGetTickCount();
        const int32_t lateTicks = static_cast<int32_t>(now - nextPhaseTick);
        const int32_t threshold = rebaseOnAnyLate ? 0 : static_cast<int32_t>(stepTicks);
        if (lateTicks > threshold) {
          // Rebase late schedules to avoid burst catch-up.
          nextPhaseTick = now + stepTicks;
        }
      };

      while (_remaining > 0 && !commandCancelled()) {
        if (!waitAtDropletBoundary()) {
          break;
        }
        if (!delayUntil(nextPhaseTick, true)) {
          if (commandCancelled()) {
            break;
          }
          continue;
        }

    	// ---------- PRINT PULSE ----------
        if (cmd.mode != PulseMode::REFUEL_ONLY) {
            TickType_t readyWaitStart = xTaskGetTickCount();
		    while (!PressureRegulator::regP().isPressureOk() && !commandCancelled()) {
              if (_control.pauseRequested) {
                if (!waitAtDropletBoundary()) {
                  break;
                }
                readyWaitStart = xTaskGetTickCount();
              }
              if (_diagReadyTimeoutEnabled &&
                  ((xTaskGetTickCount() - readyWaitStart) >= _diagReadyTimeoutTicks)) {
                internalCancelRequested = true;
                break;
              }
			  vTaskDelay(readyPollTicks);   // cheap wake-up while waiting for pressure ready
		    }
		    if (commandCancelled() || !waitAtDropletBoundary()) break;
            PressureRegulator::DisturbanceEvent disturbance{};
            disturbance.type = PressureRegulator::PulseType::Print;
            disturbance.pulseWidthUs = static_cast<uint16_t>(_printPulseUs);
            disturbance.pressureAtTrigger = PressureSensor::instance()->getLatestRaw(0u);
            disturbance.tickMs = HAL_GetTick();
            PressureRegulator::regP().notifyPulseStart(disturbance);
        	PressureRegulator::regP().beginDispenseQuiet(0);
        	pulsePrint();

			#if LC_HAS_IMAGING == 1
			  // If this was the final print pulse, schedule flash now
			  if (cmd.flashOnLast && _remaining == 1) {
				if (!Orchestrator::instance()->scheduleFlashIn(cmd.flashCycleId)) {
                  commandResult = PrinterDispenseResult::FlashScheduleFailed;
                }
			  }
			#else
			  // No flash support: just clear the flag so it doesn't linger
			  (void)cmd.flashOnLast;
			#endif
            PressureRegulator::regP().endDispenseQuiet(2);
            disturbance.tickMs = HAL_GetTick();
            disturbance.pressureAtTrigger = PressureSensor::instance()->getLatestRaw(0u);
            PressureRegulator::regP().notifyPulseEnd(disturbance);
            if (commandResult == PrinterDispenseResult::FlashScheduleFailed) {
              break;
            }
        }
        if (cmd.mode == PulseMode::BOTH) {
          advancePhase(halfPeriodTicks, false);
          if (!delayUntil(nextPhaseTick, false)) {
            break;
          }
        }

        // if someone hit “cancel” during the delay…
		if (commandCancelled()) {
			break;
		}

		// ---------- REFUEL PULSE ----------
		if (cmd.mode != PulseMode::PRINT_ONLY) {
		#if (LC_PRESSURE_PORTS > 1)
          // On dual-channel machines, wait for refuel pressure + pulse refuel
          TickType_t readyWaitStart = xTaskGetTickCount();
          while (!PressureRegulator::regR().isPressureOk() && !commandCancelled()) {
            if (cmd.mode == PulseMode::REFUEL_ONLY && _control.pauseRequested) {
              if (!waitAtDropletBoundary()) {
                break;
              }
              readyWaitStart = xTaskGetTickCount();
            }
            if (_diagReadyTimeoutEnabled &&
                ((xTaskGetTickCount() - readyWaitStart) >= _diagReadyTimeoutTicks)) {
              internalCancelRequested = true;
              break;
            }
            vTaskDelay(readyPollTicks);
          }
          if (commandCancelled() ||
              (cmd.mode == PulseMode::REFUEL_ONLY && !waitAtDropletBoundary())) break;

          PressureRegulator::DisturbanceEvent disturbance{};
          disturbance.type = PressureRegulator::PulseType::Refuel;
          disturbance.pulseWidthUs = static_cast<uint16_t>(_refuelPulseUs);
          disturbance.pressureAtTrigger = PressureSensor::instance()->getLatestRaw(1u);
          disturbance.tickMs = HAL_GetTick();
          PressureRegulator::regR().notifyPulseStart(disturbance);
          PressureRegulator::regR().beginDispenseQuiet(0);
          vTaskDelay(pdMS_TO_TICKS(2));
          pulseRefuel();
          PressureRegulator::regR().endDispenseQuiet(2);
          disturbance.tickMs = HAL_GetTick();
          disturbance.pressureAtTrigger = PressureSensor::instance()->getLatestRaw(1u);
          PressureRegulator::regR().notifyPulseEnd(disturbance);
		#else
          // Legacy: no refuel channel exists. Treat as no-op so host never hangs.
          (void)0;
		#endif
        }
        if (cmd.mode == PulseMode::BOTH) {
          advancePhase(halfPeriodTicks, false);
        }
        if (cmd.mode != PulseMode::BOTH) {
          advancePhase(periodTicks, true);
        }

        if (commandCancelled()) break;

        _totalDispensed++;
        _remaining--;
      }
      // --- always release the vacuum window at job end
      Gripper::instance().unlockVacuumGate();

      if (commandResult == PrinterDispenseResult::Completed && commandCancelled()) {
        commandResult = PrinterDispenseResult::Cancelled;
      }
      if (commandResult != PrinterDispenseResult::Completed) {
        _remaining = 0;
      }
      recordDispenseResult(commandResult, cmd.flashCycleId);

      if (cmd.completionBit != 0u) {
        xEventGroupSetBits(Orchestrator::getDoneEvents(), cmd.completionBit);
      }
      PrinterControlPolicy::acknowledgePause(_control, false);
      _commandActive = false;
    }
  }
}

void Printer::pauseDispense() {
  PrinterControlPolicy::requestPause(_control, _commandActive);
  if (_taskHandle) {
    xTaskNotifyGive(_taskHandle);
  }
}

void Printer::resumeDispense() {
  PrinterControlPolicy::requestResume(_control);
  if (_taskHandle) {
    xTaskNotifyGive(_taskHandle);
  }
}

void Printer::cancelDispense() {
  PrinterControlPolicy::requestCancel(_control);

  if (_queue) xQueueReset(_queue);

  if (_taskHandle) {
    xTaskNotifyGive(_taskHandle);
  }
}

bool Printer::waitUntilIdle(TickType_t timeoutTicks) const {
  const TickType_t start = xTaskGetTickCount();
  while (_commandActive) {
    if ((xTaskGetTickCount() - start) >= timeoutTicks) {
      return false;
    }
    vTaskDelay(1);
  }
  return true;
}

bool Printer::hasReachedPauseBoundary() const {
  return !_commandActive || _control.pauseAcknowledged;
}

bool Printer::beginDiagnosticLongPulse(PulseMode mode, uint32_t pulseMs, uint32_t tickUs) {
  if (_diagnosticLongPulseActive) {
    endDiagnosticLongPulse();
  }

  _diagnosticPulsePrint = false;
  _diagnosticPulseRefuel = false;

  const bool pulsePrint = (mode != PulseMode::REFUEL_ONLY) &&
                          (_htimPrint != nullptr) &&
                          (_printPort != nullptr) &&
                          (_printPin != 0u);
#if (LC_PRESSURE_PORTS > 1)
  const bool pulseRefuel = (mode != PulseMode::PRINT_ONLY) &&
                           (_htimRefuel != nullptr) &&
                           (_refuelPort != nullptr) &&
                           (_refuelPin != 0u);
#else
  const bool pulseRefuel = false;
#endif
  if (!pulsePrint && !pulseRefuel) {
    return false;
  }

  if (pulsePrint) {
    if (!configureValveTimerLongPulse(_htimPrint,
                                      _printChannel,
                                      _printPort,
                                      _printPin,
                                      _normalPrintPrescaler,
                                      pulseMs,
                                      tickUs)) {
      endDiagnosticLongPulse();
      return false;
    }
    _diagnosticPulsePrint = true;
  }

  if (pulseRefuel) {
#if (LC_PRESSURE_PORTS > 1)
    if (!configureValveTimerLongPulse(_htimRefuel,
                                      _refuelChannel,
                                      _refuelPort,
                                      _refuelPin,
                                      _normalRefuelPrescaler,
                                      pulseMs,
                                      tickUs)) {
      endDiagnosticLongPulse();
      return false;
    }
    _diagnosticPulseRefuel = true;
#endif
  }

  if (_diagnosticPulsePrint && !startValveTimerLongPulse(_htimPrint, _printChannel)) {
    endDiagnosticLongPulse();
    return false;
  }

#if (LC_PRESSURE_PORTS > 1)
  if (_diagnosticPulseRefuel && !startValveTimerLongPulse(_htimRefuel, _refuelChannel)) {
    endDiagnosticLongPulse();
    return false;
  }
#endif

  _diagnosticLongPulseActive = _diagnosticPulsePrint || _diagnosticPulseRefuel;
  return _diagnosticLongPulseActive;
}

void Printer::endDiagnosticLongPulse() {
  if (_diagnosticPulsePrint) {
    HAL_TIM_OnePulse_Stop(_htimPrint, _printChannel);
    HAL_TIM_PWM_Stop(_htimPrint, _printChannel);
    configureTimerPrint();
  }

#if (LC_PRESSURE_PORTS > 1)
  if (_diagnosticPulseRefuel) {
    HAL_TIM_OnePulse_Stop(_htimRefuel, _refuelChannel);
    HAL_TIM_PWM_Stop(_htimRefuel, _refuelChannel);
    configureTimerRefuel();
  }
#endif

  _diagnosticPulsePrint = false;
  _diagnosticPulseRefuel = false;
  _diagnosticLongPulseActive = false;
}

void Printer::pulsePrint() {
    // 1) Reconfigure the timer so OPM is set
    configureTimerPrint();

    // 2) Disable & clear any pending CC1/update interrupts
    __HAL_TIM_DISABLE_IT(_htimPrint, TIM_IT_CC1);
    __HAL_TIM_CLEAR_FLAG(_htimPrint, TIM_FLAG_CC1);
    __HAL_TIM_CLEAR_FLAG(_htimPrint, TIM_FLAG_UPDATE);

    // 3) Reset counter & start the one‐pulse PWM
    __HAL_TIM_SET_COUNTER(_htimPrint, 0);
    HAL_TIM_PWM_Start(_htimPrint, _printChannel);
    HAL_TIM_OnePulse_Start(_htimPrint, _printChannel);
}

void Printer::pulseRefuel() {
#if (LC_PRESSURE_PORTS > 1)
  if (!_htimRefuel) return;

  configureTimerRefuel();

  __HAL_TIM_DISABLE_IT(_htimRefuel, TIM_IT_CC1);
  __HAL_TIM_CLEAR_FLAG(_htimRefuel, TIM_FLAG_CC1);
  __HAL_TIM_CLEAR_FLAG(_htimRefuel, TIM_FLAG_UPDATE);

  __HAL_TIM_SET_COUNTER(_htimRefuel, 0);
  HAL_TIM_PWM_Start(_htimRefuel, _refuelChannel);
  HAL_TIM_OnePulse_Start(_htimRefuel, _refuelChannel);
#else
  // Legacy: no refuel hardware
  (void)0;
#endif
}

void Printer::onCompareMatch(TIM_HandleTypeDef* htim) {
  // If you don't actually use this path anymore (one-pulse PWM used instead),
  // keep it as a harmless stub so callbacks never break the build.
  (void)htim;
}

// C API wrappers
extern "C" {

void MX_PRINTER_Init(uint32_t printPulseUs, uint32_t refuelPulseUs) {
  static Printer printer;

#if (LC_PRESSURE_PORTS > 1)
  // Current board wiring (edit if your BoardConfig routes these differently)
  printer.begin(&htim4, TIM_CHANNEL_1, GPIOD, GPIO_PIN_12,
                &htim9, TIM_CHANNEL_1, GPIOE, GPIO_PIN_5,
                printPulseUs, refuelPulseUs);
#else
  // Legacy: no refuel valve. Pass nullptr/0 for refuel hardware.
  printer.begin(nullptr, 0, nullptr, 0,
                &htim9, TIM_CHANNEL_1, GPIOE, GPIO_PIN_5,
                printPulseUs, refuelPulseUs);
#endif
}

void MX_PRINTER_Enqueue(uint16_t count, uint16_t rateHz) {
  Printer::instance()->enqueue(count, rateHz, PulseMode::BOTH);
}

void MX_PRINTER_Enqueue_Print(uint16_t count, uint16_t rateHz) {
  Printer::instance()->enqueue(count, rateHz, PulseMode::PRINT_ONLY);
}

void MX_PRINTER_Enqueue_Refuel(uint16_t count, uint16_t rateHz) {
  Printer::instance()->enqueue(count, rateHz, PulseMode::REFUEL_ONLY);
}

uint32_t MX_PRINTER_GetTotal(void) {
  return Printer::instance()->getTotalDispensed();
}

uint32_t MX_PRINTER_GetRemaining(void) {
  return Printer::instance()->getRemaining();
}

void MX_PRINTER_COMPARE_MATCH(TIM_HandleTypeDef* htim){
	Printer::instance()->onCompareMatch(htim);
}

}

