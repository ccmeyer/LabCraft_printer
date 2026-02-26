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
  _flashOnLast = false;

  // Create queue and task
  _queue = xQueueCreate(8, sizeof(DispenseCommand));
  xTaskCreate(taskEntry, "PRNT", 256, this,
              tskIDLE_PRIORITY + 1, &_taskHandle);
}

void Printer::configureTimerPrint() {
	if (!_htimPrint) return;

    TIM_OC_InitTypeDef sConfigOC = {0};

    // 1) Update base timer parameters
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

  TIM_OC_InitTypeDef sConfigOC = {0};

  _htimRefuel->Init.Period            = (_refuelPulseUs * 2) - 1;
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

void Printer::enqueue(uint16_t count, uint16_t rateHz, PulseMode mode) {
  DispenseCommand cmd{count, rateHz, mode};
  xQueueSend(_queue, &cmd, portMAX_DELAY);
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

void Printer::taskEntry(void* pv) {
  static_cast<Printer*>(pv)->taskLoop();
  vTaskDelete(nullptr);
}

void Printer::taskLoop() {
  DispenseCommand cmd;
  for (;;) {
    if (xQueueReceive(_queue, &cmd, portMAX_DELAY) == pdTRUE) {

      _remaining = cmd.count;
      _cancelRequested = false;              // clear any old cancel

      // Apply per-command frequency if provided
      if (cmd.rateHz > 0) {
        _dispenseHz = cmd.rateHz;
      }

      // --- wait for any in-flight gripper refresh to finish and
      //             then hold the vacuum window for the entire job.
      bool printingHoldsGate = Gripper::instance().lockVacuumGate(portMAX_DELAY);
      (void)printingHoldsGate; // for safety; expect true

      uint32_t periodMs = 1000u / _dispenseHz;
      uint32_t halfDelay = periodMs / 2;
      while (_remaining > 0 && !_cancelRequested) {

    	// ---------- PRINT PULSE ----------
        if (cmd.mode != PulseMode::REFUEL_ONLY) {
		    while (!PressureRegulator::regP().isPressureOk() && !_cancelRequested) {
			  vTaskDelay(pdMS_TO_TICKS(2));   // cheap wake‐up every 2 ms
		    }
		    if (_cancelRequested) break;
        	PressureRegulator::regP().beginDispenseQuiet(0);
        	vTaskDelay(pdMS_TO_TICKS(2));
        	pulsePrint();

			#if LC_HAS_IMAGING == 1
			  // If this was the final print pulse, schedule flash now
			  if (_flashOnLast && _remaining == 1) {
				_flashOnLast = false;
				Orchestrator::instance()->scheduleFlashIn();
			  }
			#else
			  // No flash support: just clear the flag so it doesn't linger
			  if (_flashOnLast && _remaining == 1) {
				_flashOnLast = false;
			  }
			#endif
            PressureRegulator::regP().endDispenseQuiet(2);
        }
        vTaskDelay(pdMS_TO_TICKS(halfDelay));

        // if someone hit “cancel” during the delay…
		if (_cancelRequested) {
			break;
		}

		// ---------- REFUEL PULSE ----------
		if (cmd.mode != PulseMode::PRINT_ONLY) {
		#if (LC_PRESSURE_PORTS > 1)
          // On dual-channel machines, wait for refuel pressure + pulse refuel
          while (!PressureRegulator::regR().isPressureOk() && !_cancelRequested) {
            vTaskDelay(pdMS_TO_TICKS(2));
          }
          if (_cancelRequested) break;

          PressureRegulator::regR().beginDispenseQuiet(0);
          vTaskDelay(pdMS_TO_TICKS(2));
          pulseRefuel();
          PressureRegulator::regR().endDispenseQuiet(2);
		#else
          // Legacy: no refuel channel exists. Treat as no-op so host never hangs.
          (void)0;
		#endif
		}
        vTaskDelay(pdMS_TO_TICKS(halfDelay));

        if (_cancelRequested) break;

        _totalDispensed++;
        _remaining--;
      }
      // --- always release the vacuum window at job end
      Gripper::instance().unlockVacuumGate();

      xEventGroupSetBits(Orchestrator::getDoneEvents(), BIT_PRINTING_DONE);
    }
  }
}

void Printer::pauseDispense() {
  if (_taskHandle)
    vTaskSuspend(_taskHandle);
}

void Printer::resumeDispense() {
  if (_taskHandle)
    vTaskResume(_taskHandle);
}

void Printer::cancelDispense() {
  // 1) request the task to stop
  _cancelRequested = true;
  _remaining = 0;

  // 2) empty any queued future commands
  if (_queue) xQueueReset(_queue);

  // 3) wake the task so it can see _cancelRequested
  if (_taskHandle) vTaskResume(_taskHandle);
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

