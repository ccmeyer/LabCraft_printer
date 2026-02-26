/*
 * LEDController.cpp
 *
 *  Created on: Jun 17, 2025
 *      Author: conar
 */

#include "LEDController.h"
#include "Orchestrator.h"        // for Orchestrator::getDoneEvents()
#include "stm32f4xx_hal.h"

// singleton pointer
LEDController* LEDController::_instance = nullptr;

// file‐scope instance, initialized in C‐API
static LEDController ledController(GPIOA, GPIO_PIN_13);

// C‐API: call this once from main.c after MX_GPIO_Init()
extern "C" void MX_LED_Init(void) {
  ledController.begin();
}

// C‐API to let someone else fetch our queue
extern "C" QueueHandle_t MX_LED_GetQueue(void) {
  return ledController.getQueue();
}

LEDController::LEDController(GPIO_TypeDef* port, uint16_t pin)
  : _port(port), _pin(pin),
    _queue(nullptr), _task(nullptr)
{}

LEDController* LEDController::instance() {
  return _instance;
}

void LEDController::begin() {
  _instance = this;

  // queue holds up to 8 blink requests
  _queue = xQueueCreate(8, sizeof(BlinkCommand));

  // spawn the blink‐task
  xTaskCreate(
    taskEntry,
    "LED",
    128,
    this,
    tskIDLE_PRIORITY + 1,
    &_task
  );
}

void LEDController::enqueue(const BlinkCommand& cmd) {
  // called from Orchestrator task context
  xQueueSend(_queue, &cmd, portMAX_DELAY);
}

void LEDController::taskEntry(void* pv) {
  static_cast<LEDController*>(pv)->taskLoop();
  vTaskDelete(nullptr);
}

void LEDController::taskLoop() {
  for (;;) {
    BlinkCommand cmd;
    // wait for a blink command
    if (xQueueReceive(_queue, &cmd, portMAX_DELAY) == pdTRUE) {
      _remaining = cmd.count;
      for (uint16_t i = 0; i < cmd.count; ++i) {
        // LED on
        HAL_GPIO_WritePin(_port, _pin, GPIO_PIN_SET);
        vTaskDelay(pdMS_TO_TICKS(cmd.delayMs));
        // LED off
        HAL_GPIO_WritePin(_port, _pin, GPIO_PIN_RESET);
        vTaskDelay(pdMS_TO_TICKS(cmd.delayMs));

        ++_totalExecuted;
        --_remaining;
      }

      // signal the orchestrator that we're done
      xEventGroupSetBits(
        Orchestrator::getDoneEvents(),
        BIT_LED_DONE
      );
    }
  }
}


//#include "LEDController.h"
//#include "stm32f4xx_hal.h"   // for HAL_GPIO_WritePin()
//#include <cstring>
//
////------------------------------------------------------------------------------
//// static singleton pointer
//LEDController* LEDController::_instance = nullptr;
//
//// file‐scope singleton instance
//static LEDController ledController(GPIOA, GPIO_PIN_13);
//
//// C‐API entry: call this once from main.c
//extern "C" void MX_LED_Init(void) {
//    ledController.begin();
//}
//
//// C‐API to fetch our queue handle
//extern "C" QueueHandle_t MX_LED_GetQueue(void) {
//    return ledController.getQueue();
//}
//
////------------------------------------------------------------------------------
//// LEDController implementation
//
//LEDController::LEDController(GPIO_TypeDef* port, uint16_t pin)
//  : _port(port), _pin(pin), _queue(nullptr), _task(nullptr)
//{}
//
//void LEDController::begin() {
//    _instance = this;
//    // queue holds up to 8 BlinkCommand items
//    _queue = xQueueCreate(8, sizeof(BlinkCommand));
//    // spawn the blink‐task at priority (IDLE+1)
//    xTaskCreate(
//      taskEntry,
//      "LED",           // name
//      128,             // stack (words)
//      this,            // pvParameters → our this
//      tskIDLE_PRIORITY+1,
//      &_task
//    );
//}
//
//void LEDController::taskEntry(void* pvParameters) {
//    auto self = static_cast<LEDController*>(pvParameters);
//    self->taskLoop();
//    vTaskDelete(nullptr);
//}
//
//void LEDController::taskLoop() {
//    BlinkCommand cmd;
//    for (;;) {
//        // wait for next BlinkCommand
//        if (xQueueReceive(_queue, &cmd, portMAX_DELAY) == pdTRUE) {
//            // reset remaining & accumulate total
//            _remaining     = cmd.count;
//            for (uint16_t i = 0; i < cmd.count; ++i) {
//                HAL_GPIO_WritePin(_port, _pin, GPIO_PIN_SET);
//                vTaskDelay(pdMS_TO_TICKS(cmd.delayMs));
//                HAL_GPIO_WritePin(_port, _pin, GPIO_PIN_RESET);
//                vTaskDelay(pdMS_TO_TICKS(cmd.delayMs));
//
//                // track total
//                ++_totalExecuted;
//                --_remaining;
//            }
//        }
//    }
//}
