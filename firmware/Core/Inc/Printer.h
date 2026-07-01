/*
 * Printer.h
 *
 *  Created on: Jun 20, 2025
 *      Author: conar
 */

// Printer.h
#ifndef INC_PRINTER_H_
#define INC_PRINTER_H_

#include "BoardConfig.h"
#include "stm32f4xx_hal.h"
#include <cstdint>
#include "FreeRTOS.h"
#include "queue.h"
#include "task.h"
#include "PrinterCompletionBits.h"

// in Printer.h, above class Printer:
enum class PulseMode : uint8_t {
  BOTH        = 0,
  PRINT_ONLY  = 1,
  REFUEL_ONLY = 2
};

class Printer {
public:
  /// Dispense command: number of droplets and frequency (Hz)
  struct DispenseCommand {
    uint16_t count;
    uint16_t rateHz;
    PulseMode   mode;
    uint32_t completionBit;
    bool flashOnLast = false;
    uint32_t flashCycleId = 0;
  };

  /// Get the singleton
  static Printer* instance();

  /// Construct
  Printer();

  /**
   * Initialize the two valves with their timers:
   *   - refuelTimer → refuelPort/refuelPin (TIM4_CH1)
   *   - printTimer  → printPort/printPin   (TIM9_CH1)
   * Users must have MX_TIM4_Init() and MX_TIM9_Init() generated so 1 tick = 1µs.
   * Also set default pulse widths in microseconds.
   */
  void begin(
    TIM_HandleTypeDef* refuelTimer,
	uint32_t		   refuelChannel,
    GPIO_TypeDef*      refuelPort, uint16_t refuelPin,
    TIM_HandleTypeDef* printTimer,
	uint32_t		   printChannel,
    GPIO_TypeDef*      printPort,  uint16_t printPin,
    uint32_t           printPulseUs,
    uint32_t           refuelPulseUs
  );

  /// Enqueue a dispense operation (blocking until queued)
  void enqueue(
    uint16_t count,
    uint16_t rateHz,
    PulseMode mode,
    uint32_t completionBit = PRINTER_COMPLETION_HOST_DONE_BIT,
    bool flashOnLast = false,
    uint32_t flashCycleId = 0
  );

  /// Enqueue with explicit timeout (used by self-test to avoid deadlock).
  bool enqueueWithTimeout(
    uint16_t count,
    uint16_t rateHz,
    PulseMode mode,
    TickType_t timeoutTicks,
    uint32_t completionBit = PRINTER_COMPLETION_HOST_DONE_BIT,
    bool flashOnLast = false,
    uint32_t flashCycleId = 0
  );

  /// Diagnostic-only guard to bound pressure-ready waits inside taskLoop().
  void setDiagnosticReadyTimeout(bool enabled, uint32_t timeoutMs);

  /// Pause the dispensing task (won't start any new pulses)
  void pauseDispense();

  /// Resume dispensing, picking up where we left off
  void resumeDispense();

  /// Stop & clear the current command entirely
  void cancelDispense();

  /// True if currently dispensing
  bool isBusy() const;

  /// Get total droplets ever dispensed
  uint32_t getTotalDispensed() const;

  /// Get droplets remaining in current job
  uint32_t getRemaining() const;

  void setPrintPulse(uint32_t us) { _printPulseUs = us; }		// Timer is set so 1 tick = 1 usec
  void setRefuelPulse(uint32_t us) { _refuelPulseUs = us; }		// Timer is set so 1 tick = 1 usec
  void setDispenseHz(uint32_t Hz) { _dispenseHz = Hz; }


  uint32_t getPrintPulse() const { return _printPulseUs; }
  uint32_t getRefuelPulse() const { return _refuelPulseUs; }
  uint32_t getDispenseHz() const { return _dispenseHz; }


  /// low-level pulse
//  void pulsePrint(uint32_t width_us);
//  void pulseRefuel(uint32_t width_us);
  void pulsePrint();
  void pulseRefuel();

  /// Diagnostic-only: start a longer one-pulse valve burst using scaled timer ticks.
  bool beginDiagnosticLongPulse(PulseMode mode, uint32_t pulseMs, uint32_t tickUs = 100u);
  void endDiagnosticLongPulse();

  void onCompareMatch(TIM_HandleTypeDef* htim);

private:
  // hardware
  TIM_HandleTypeDef* _htimRefuel = nullptr;
  uint32_t           _refuelChannel = 0;
  GPIO_TypeDef*      _refuelPort = nullptr;
  uint16_t           _refuelPin  = 0;

  TIM_HandleTypeDef* _htimPrint = nullptr;
  uint32_t           _printChannel = 0;
  GPIO_TypeDef*      _printPort = nullptr;
  uint16_t           _printPin  = 0;

  // default pulse widths
  uint32_t _printPulseUs = 0;
  uint32_t _refuelPulseUs = 0;

  uint32_t _dispenseHz = 20;

  // queue + task
  QueueHandle_t _queue = nullptr;
  TaskHandle_t  _taskHandle = nullptr;

  // stats
  volatile uint32_t _totalDispensed = 0;
  volatile int32_t _remaining = 0;
  volatile bool     _cancelRequested = false;
  bool _diagReadyTimeoutEnabled = false;
  TickType_t _diagReadyTimeoutTicks = 0;
  bool _diagnosticLongPulseActive = false;
  bool _diagnosticPulsePrint = false;
  bool _diagnosticPulseRefuel = false;
  uint32_t _normalPrintPrescaler = 0;
  uint32_t _normalRefuelPrescaler = 0;

  // dispense loop
  void taskLoop();
  static void taskEntry(void* pv);

  void configureTimerPrint();
  void configureTimerRefuel();

  /// compare-match handler (from HAL IRQ)
  friend void HAL_TIM_OC_DelayElapsedCallback(TIM_HandleTypeDef *htim);
};

// C API
extern "C" {
	void MX_PRINTER_Init(uint32_t printPulseUs, uint32_t refuelPulseUs);
	void MX_PRINTER_Enqueue(uint16_t count, uint16_t rateHz);
	void MX_PRINTER_Enqueue_Print(uint16_t count, uint16_t rateHz);
	void MX_PRINTER_Enqueue_Refuel(uint16_t count, uint16_t rateHz);
	uint32_t MX_PRINTER_GetTotal(void);
	uint32_t MX_PRINTER_GetRemaining(void);
	void MX_PRINTER_COMPARE_MATCH(TIM_HandleTypeDef* htim);
}

#endif // INC_PRINTER_H_
