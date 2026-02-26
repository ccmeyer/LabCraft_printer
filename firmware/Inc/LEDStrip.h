/*
 * LEDStrip.h
 *
 *  Created on: Jun 30, 2025
 *      Author: conar
 */

#ifndef INC_LEDSTRIP_H_
#define INC_LEDSTRIP_H_

#include "BoardConfig.h"
#include "stm32f4xx_hal.h"
#include <cstdint>
#include "FreeRTOS.h"
#include "task.h"
#include "queue.h"

class LEDStrip {
public:
  static LEDStrip& instance();

  /// Call once after MX_TIM3_Init()
  void begin(TIM_HandleTypeDef* htim3);

  /// Immediately set brightness 0–100%
  void setBrightness(uint8_t pct);

  /// Fade from current brightness → target over durationMs milliseconds
  void fadeTo(uint8_t targetPct, uint32_t durationMs);

  /// Turn off immediately
  inline void off() { setBrightness(0); }

private:
  LEDStrip() = default;

  // the fade request struct we’ll pass via queue
  struct FadeReq {
    uint8_t  target;
    uint32_t duration;
  };

  // task entry & loop
  static void   fadeTaskEntry(void* pv);
  void          fadeTask();

  TIM_HandleTypeDef* _htim  = nullptr;
  uint32_t            _ch    = TIM_CHANNEL_3;
  uint32_t            _arr   = 0;
  uint8_t             _cur   = 0;        // last-set brightness
  QueueHandle_t       _fadeQ = nullptr;
  TaskHandle_t        _fadeT = nullptr;
};

// C-API wrappers
extern "C" {
  void MX_LEDSTRIP_Init(TIM_HandleTypeDef* htim3);
  void MX_LEDSTRIP_SetBrightness(uint8_t pct);
  void MX_LEDSTRIP_FadeTo(uint8_t pct, uint32_t ms);
  void MX_LEDSTRIP_Off(void);
}

#endif // INC_LEDSTRIP_H_

//
//#ifndef INC_LEDSTRIP_H_
//#define INC_LEDSTRIP_H_
//
//#include "stm32f4xx_hal.h"
//#include "FreeRTOS.h"
//#include "task.h"
//#include "semphr.h"
//#include <cstdint>
//
//class LEDStrip {
//public:
//  static LEDStrip* instance();
//
//  LEDStrip();
//
//  /// Number of LEDs, and reset‐pulse count, made public for compile-time use
//  static constexpr uint32_t LED_COUNT    = 144;
//  static constexpr uint32_t RESET_PULSES = 50;
//
//  /// Call once (after MX_TIM3_Init + MX_DMA_Init)
//  void begin(TIM_HandleTypeDef* htim3, DMA_HandleTypeDef* hdma);
//
//  /// Fill internal buffer with GRB color
//  void fill(uint8_t r, uint8_t g, uint8_t b);
//
//  /// Kick off an update.  Returns immediately.
//  void show();
//
//  /// True if a show() is in flight
//  bool isBusy() const { return _busy; }
//
//  DMA_HandleTypeDef* hdma() {return _hdma; }
//
//  /// Called from TIM3 DMA‐complete ISR
//  void onDmaComplete();
//
//private:
////  LEDStrip();
////  ~LEDStrip() = default;
//  static LEDStrip* _instance;
//
//
//  // FreeRTOS task to drive the DMA/PWM calls
//  static void ledTaskEntry(void* pv);
//  void ledTask();
//
//  TIM_HandleTypeDef* _htim;
//  DMA_HandleTypeDef* _hdma;
//  uint16_t*          _buf;
//  uint32_t           _buflen;
//  volatile bool      _busy;
//
//  TaskHandle_t       _taskHandle;
//  SemaphoreHandle_t  _dmaDoneSem;
//
//  static constexpr uint32_t TIMER_CLOCK  = 90'000'000; // APB1×2
//  static constexpr uint32_t WS_FREQ      = 800'000;    // 800kHz
//  static constexpr uint16_t PWM_PERIOD   = TIMER_CLOCK/WS_FREQ; // ≈112
//  static constexpr uint16_t T0H          =  36;  // ≈0.4μs
//  static constexpr uint16_t T1H          =  76;  // ≈0.85μs
//};
//
//extern "C" void MX_LEDSTRIP_BEGIN(TIM_HandleTypeDef* htim3, DMA_HandleTypeDef* hdma);
//extern "C" void MX_LEDSTRIP_FILL(uint8_t r, uint8_t g, uint8_t b);
//extern "C" void MX_LEDSTRIP_SHOW();
//extern "C" void MX_LEDSTRIP_DMA_COMPLETE();
//extern "C" void HAL_DMA_XferCpltCallback(DMA_HandleTypeDef *hdma);

//#include "stm32f4xx_hal.h"
//#include <cstdint>
//
//class LEDStrip {
//public:
//  static LEDStrip& instance();
//
//  /// Call once, e.g. in StartDefaultTask
//  void begin(TIM_HandleTypeDef* htim3);
//
//  /// Fill _internal_ buffer with GRB white/black/etc.
//  void fill(uint8_t r, uint8_t g, uint8_t b);
//
//  /// Kick off a one-shot DMA/PWM transfer
//  /// (returns immediately; check isBusy())
//  void show();
//
//  /// Is a DMA transfer in flight?
//  bool isBusy() const { return _busy; }
//
//  /// Must be called from HAL_TIM_PWM_PulseFinishedCallback
//  void onDmaComplete();
//
//private:
//  LEDStrip();
//  TIM_HandleTypeDef* _htim;
//  uint16_t*          _buf;
//  uint32_t           _buflen;
//  bool               _busy;
//
//  static constexpr uint32_t LED_COUNT      = 144;
//  static constexpr uint32_t RESET_PULSES   = 50;   // >50 µs low
//  static constexpr uint32_t TIMER_CLOCK    = 90'000'000; // APB1×2
//  static constexpr uint32_t WS_FREQ        = 800'000;    // 800 kHz
//  static constexpr uint16_t PWM_PERIOD     = TIMER_CLOCK/WS_FREQ; // ≈112
//  static constexpr uint16_t T0H            =  36;  // ≈0.4 µs @ 90 MHz
//  static constexpr uint16_t T1H            =  76;  // ≈0.85 µs
//
//};
//
//extern "C" void MX_LEDSTRIP_BEGIN(TIM_HandleTypeDef* htim3);
//extern "C" void MX_LEDSTRIP_FILL(uint8_t r, uint8_t g, uint8_t b);
//extern "C" void MX_LEDSTRIP_SHOW();
//extern "C" void MX_LEDSTRIP_DMA_COMPLETE();
//

//#endif /* INC_LEDSTRIP_H_ */
