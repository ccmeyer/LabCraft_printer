/*
 * LEDStrip.cpp
 *
 *  Created on: Jun 30, 2025
 *      Author: conar
 */

#include "BoardConfig.h"
#include "LEDStrip.h"

#if (LC_HAS_LED_STRIP == 1)
#include <cmath>

LEDStrip& LEDStrip::instance() {
  static LEDStrip S;
  return S;
}

void LEDStrip::begin(TIM_HandleTypeDef* htim3) {
  _htim = htim3;
  _arr  = __HAL_TIM_GET_AUTORELOAD(_htim);

  // start PWM at 0%
  __HAL_TIM_SET_COMPARE(_htim, _ch, 0);
  HAL_TIM_PWM_Start(_htim, _ch);

  // create a queue for fade requests
  _fadeQ = xQueueCreate( 4, sizeof(FadeReq) );

  // spawn the fade-handling task
  xTaskCreate(
    fadeTaskEntry,
    "LEDFade",
    128,              // stack
    this,
    tskIDLE_PRIORITY,
    &_fadeT
  );
}

void LEDStrip::setBrightness(uint8_t pct) {
  if (!_htim) return;
  if (pct>100) pct = 100;
  _cur = pct;
  uint32_t ccr = ((uint32_t)(_arr+1) * pct) / 100;
  __HAL_TIM_SET_COMPARE(_htim, _ch, ccr);
}

void LEDStrip::fadeTo(uint8_t targetPct, uint32_t durationMs) {
  if (!_fadeQ) return;
  FadeReq r{ targetPct, durationMs };
  // if queue full, drop oldest
  if (uxQueueSpacesAvailable(_fadeQ) == 0) {
    FadeReq dummy;
    xQueueReceive(_fadeQ, &dummy, 0);
  }
  xQueueSend(_fadeQ, &r, 0);
}

// static
void LEDStrip::fadeTaskEntry(void* pv) {
  static_cast<LEDStrip*>(pv)->fadeTask();
}

void LEDStrip::fadeTask() {
  FadeReq req;
  for (;;) {
    // wait forever for a fade request
    if (xQueueReceive(_fadeQ, &req, portMAX_DELAY) == pdPASS) {
      uint8_t start = _cur;
      uint8_t end   = req.target;
      int    delta = int(end) - int(start);
      if (delta == 0) {
        setBrightness(end);
        continue;
      }
      // we'll step one percent at a time:
      uint32_t steps = std::abs(delta);
      // how long between each 1% step
      TickType_t tickDelay = req.duration > 0
        ? pdMS_TO_TICKS(req.duration / steps)
        : 0;
      int8_t dir = (delta>0 ? +1 : -1);

      for (uint32_t i = 0; i <= steps; ++i) {
        setBrightness( uint8_t(start + dir* i) );
        if (i<steps && tickDelay) {
          vTaskDelay(tickDelay);
        }
      }
    }
  }
}

// C wrappers
extern "C" void MX_LEDSTRIP_Init(TIM_HandleTypeDef* htim3) {
  LEDStrip::instance().begin(htim3);
}
extern "C" void MX_LEDSTRIP_SetBrightness(uint8_t pct) {
  LEDStrip::instance().setBrightness(pct);
}
extern "C" void MX_LEDSTRIP_FadeTo(uint8_t pct, uint32_t ms) {
  LEDStrip::instance().fadeTo(pct,ms);
}
extern "C" void MX_LEDSTRIP_Off() {
  LEDStrip::instance().off();
}


#else  // (LC_HAS_LED_STRIP == 0)

// ---- Legacy / no-strip build: compile-safe no-op stubs ----

LEDStrip& LEDStrip::instance() {
  static LEDStrip S;
  return S;
}

void LEDStrip::begin(TIM_HandleTypeDef* htim3) { (void)htim3; }
void LEDStrip::setBrightness(uint8_t pct) { (void)pct; }
void LEDStrip::fadeTo(uint8_t targetPct, uint32_t durationMs) {
  (void)targetPct; (void)durationMs;
}

extern "C" void MX_LEDSTRIP_Init(TIM_HandleTypeDef* htim3) { (void)htim3; }
extern "C" void MX_LEDSTRIP_SetBrightness(uint8_t pct) { (void)pct; }
extern "C" void MX_LEDSTRIP_FadeTo(uint8_t pct, uint32_t ms) { (void)pct; (void)ms; }
extern "C" void MX_LEDSTRIP_Off(void) {}

#endif

//#include "LEDStrip.h"
//#include "FreeRTOS.h"
//#include "task.h"
//#include "semphr.h"
//#include "main.h"  // for extern htim3, hdma_tim3_ch3
//#include <cstring>
//
////extern DMA_HandleTypeDef &hdma_tim3_ch3;
//
//// singleton init
//LEDStrip* LEDStrip::_instance = nullptr;
//
////LEDStrip::LEDStrip() {}
//
//LEDStrip* LEDStrip::instance() {
//  return _instance;
//}
//
//
////LEDStrip& LEDStrip::instance() {
////  static LEDStrip inst;
////  return inst;
////}
//
//LEDStrip::LEDStrip()
// : _htim(nullptr)
// , _buf(nullptr)
// , _buflen(0)
// , _busy(false)
// , _taskHandle(nullptr)
// , _dmaDoneSem(nullptr)
//{}
//
//// Calculate the total number of PWM words we need:
////   24 bits per LED, plus RESET_PULSES low‐words
//static constexpr size_t DMA_BUF_LEN =
//    LEDStrip::LED_COUNT * 24 + LEDStrip::RESET_PULSES;
//
//// A flat global lives in SRAM1 by default, which is DMA¹-capable.
//// We also align it to 4 bytes so the bus sees clean 32-bit transfers.
//__attribute__((aligned(4)))
//static uint16_t led_dma_buf[DMA_BUF_LEN];
//
//void LEDStrip::begin(TIM_HandleTypeDef* htim3, DMA_HandleTypeDef* hdma) {
//  _instance = this;
//  _htim   = htim3;
//  _hdma   = hdma;
//  _buf    = led_dma_buf;
//  _buflen = DMA_BUF_LEN;
//
//
////  // somewhere in MX_LEDSTRIP_BEGIN, after MX_DMA_Init():
//  HAL_DMA_RegisterCallback(_hdma,
//						 HAL_DMA_XFER_CPLT_CB_ID,
//						 HAL_DMA_XferCpltCallback);
//
//  // Clear everything so we start dark
//  memset(_buf, 0, sizeof(led_dma_buf));
//
//  // create a binary semaphore (initially empty)
//  _dmaDoneSem = xSemaphoreCreateBinary();
//
//
//  // spawn our LED strip task
//  xTaskCreate(
//    ledTaskEntry,
//    "LED_DMA",
//    256,
//    this,
//    tskIDLE_PRIORITY+1,
//    &_taskHandle
//  );
//
//  // start the timer base (so CCR updates work)
////  HAL_TIM_PWM_Start(_htim, TIM_CHANNEL_3);
//
//
////  HAL_TIM_Base_Start(_htim);
//  HAL_GPIO_WritePin(GPIOA, GPIO_PIN_13, GPIO_PIN_SET);
//
////  HAL_GPIO_WritePin(GPIOA, GPIO_PIN_13, GPIO_PIN_SET);
//
//}
//
//void LEDStrip::fill(uint8_t r, uint8_t g, uint8_t b) {
//  // pack GRB bits into timing values
//  for(uint32_t i = 0; i < LED_COUNT; ++i) {
//    uint32_t grb = (uint32_t(g)<<16) | (uint32_t(r)<<8) | b;
//    for(int bit = 23; bit >= 0; --bit) {
//      bool one = (grb & (1u<<bit)) != 0;
//      _buf[i*24 + (23-bit)] = one ? T1H : T0H;
//    }
//  }
//  // the reset gap
//  std::memset(_buf + LED_COUNT*24, 0, RESET_PULSES * sizeof(uint16_t));
//}
//
//void LEDStrip::show() {
//  if (_busy || !_taskHandle) return;
//  _busy = true;
//  // notify the LED task to start a DMA transfer
//  xTaskNotifyGive(_taskHandle);
//}
//
//void LEDStrip::onDmaComplete() {
//  BaseType_t woke = pdFALSE;
//  // give the semaphore so task can stop DMA in task context
//  xSemaphoreGiveFromISR(_dmaDoneSem, &woke);
//  portYIELD_FROM_ISR(woke);
//}
//
//// static
//void LEDStrip::ledTaskEntry(void* pv) {
//  static_cast<LEDStrip*>(pv)->ledTask();
//}
//
//void LEDStrip::ledTask() {
//  for (;;) {
//    // wait for someone to call show()
//    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
//
////    // start the DMA-driven PWM
////    HAL_TIM_PWM_Start_DMA(
////      _htim,
////      TIM_CHANNEL_3,
////      reinterpret_cast<uint32_t*>(_buf),
////      _buflen
////    );
//    if (HAL_TIM_PWM_Start_DMA(_htim, TIM_CHANNEL_3,
//            reinterpret_cast<uint32_t*>(_buf),
//            _buflen) != HAL_OK)
//    {
//      // oops, DMA never started—blink the on-board LED so we know
//      HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);
//    }
//
//    // wait for the ISR to give us the semaphore
//    xSemaphoreTake(_dmaDoneSem, portMAX_DELAY);
//
//    // now safe to stop DMA from task context
//    HAL_TIM_PWM_Stop_DMA(_htim, TIM_CHANNEL_3);
//
//    // allow another show()
//    _busy = false;
//  }
//}
//
//extern "C" void HAL_DMA_XferCpltCallback(DMA_HandleTypeDef *hdma)
//{
////  HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);
//
//  // TIM3_CH3 uses DMA1_Stream7:
//  if (hdma == LEDStrip::instance()->hdma()) {
//    // wake the LEDStrip task so it can stop DMA in thread context
//	  MX_LEDSTRIP_DMA_COMPLETE();
//  }
//}
//
//
//// C wrappers for main.c
//extern "C" void MX_LEDSTRIP_BEGIN(TIM_HandleTypeDef* htim3, DMA_HandleTypeDef* hdma) {
//  LEDStrip::instance()->begin(htim3,hdma);
//}
//extern "C" void MX_LEDSTRIP_FILL(uint8_t r, uint8_t g, uint8_t b) {
//  LEDStrip::instance()->fill(r,g,b);
//}
//extern "C" void MX_LEDSTRIP_SHOW() {
//  LEDStrip::instance()->show();
//}
//extern "C" void MX_LEDSTRIP_DMA_COMPLETE() {
//  LEDStrip::instance()->onDmaComplete();
//}
//
//
//

//#include "LEDStrip.h"
//#include "FreeRTOS.h"      // for pvPortMalloc() if you want RTOS heap
//#include "task.h"
//#include "main.h"          // gets extern htim3, hdma_tim3_ch3
//
//LEDStrip& LEDStrip::instance() {
//  static LEDStrip inst;
//  return inst;
//}
//
//LEDStrip::LEDStrip()
// : _htim(nullptr), _buf(nullptr), _buflen(0), _busy(false)
//{}
//
//void LEDStrip::begin(TIM_HandleTypeDef* htim3) {
//  _htim   = htim3;
//  // total bits = 24 bits per LED, plus reset pulses
//  _buflen = LED_COUNT*24 + RESET_PULSES;
//  // allocate buffer (16-bit values for CCR3)
//  _buf = static_cast<uint16_t*>(
//    pvPortMalloc(sizeof(uint16_t)*_buflen)
//  );
//  // kick the timer running (PWM idle)
//  HAL_TIM_Base_Start(_htim);
//}
//
//void LEDStrip::fill(uint8_t r, uint8_t g, uint8_t b) {
//  // WS2812 uses G-then-R-then-B order
//  for(uint32_t i=0;i<LED_COUNT;i++){
//    uint32_t grb = (uint32_t(g)<<16) | (uint32_t(r)<<8) | b;
//    for(int bit=23; bit>=0; --bit){
//      bool one = (grb & (1u<<bit))!=0;
//      _buf[i*24 + (23-bit)] = one ? T1H : T0H;
//    }
//  }
//  // reset pulses = all zero
//  for(uint32_t i=LED_COUNT*24; i<_buflen; ++i)
//    _buf[i] = 0;
//}
//
//void LEDStrip::show() {
//  if(_busy) return;
//  _busy = true;
//  // restart the DMA+PWM
//  HAL_TIM_PWM_Stop_DMA(_htim, TIM_CHANNEL_3);
//  HAL_TIM_PWM_Start_DMA(_htim, TIM_CHANNEL_3,
//                       reinterpret_cast<uint32_t*>(_buf),
//                       _buflen);
//}
//
//void LEDStrip::onDmaComplete() {
//  // Called from ISR
//  _busy = false;
////  HAL_TIM_PWM_Stop_DMA(_htim, TIM_CHANNEL_3);
//}
//
//extern "C" void MX_LEDSTRIP_BEGIN(TIM_HandleTypeDef* htim3){
//	LEDStrip::instance().begin(htim3);
//}
//
//extern "C" void MX_LEDSTRIP_FILL(uint8_t r, uint8_t g, uint8_t b){
//	LEDStrip::instance().fill(r, g, b);
//}
//
//extern "C" void MX_LEDSTRIP_SHOW(){
//	LEDStrip::instance().show();
//}
//
//extern "C" void MX_LEDSTRIP_DMA_COMPLETE(){
//	LEDStrip::instance().onDmaComplete();
//}

