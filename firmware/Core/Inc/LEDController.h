/*
 * LEDController.h
 *
 *  Created on: Jun 17, 2025
 *      Author: conar
 */

#ifndef LEDCONTROLLER_H
#define LEDCONTROLLER_H

#include "stm32f4xx_hal.h"
#include "FreeRTOS.h"
#include "queue.h"
#include "task.h"
#include <cstdint>

// simple POD to request blinks
struct BlinkCommand {
  uint16_t count;
  uint32_t delayMs;
};

class LEDController {
public:
  /// singleton accessor
  static LEDController* instance();
  LEDController(GPIO_TypeDef* port, uint16_t pin);
  /// must be called once after MX_GPIO_Init()
  void begin();

  /// enqueue a new blink request (called by Orchestrator)
  void enqueue(const BlinkCommand& cmd);

  /// for statusTask
  uint32_t    getTotalExecuted() const { return _totalExecuted; }
  uint16_t    getRemaining()     const { return _remaining;     }

  /// expose the queue to other modules if needed
  QueueHandle_t getQueue() const { return _queue; }

private:

  static void      taskEntry(void* pv);
  void             taskLoop();

  GPIO_TypeDef*    _port;
  uint16_t         _pin;
  QueueHandle_t    _queue;
  TaskHandle_t     _task;

  // blink statistics
  uint32_t         _totalExecuted = 0;
  uint16_t         _remaining     = 0;

  static LEDController* _instance;
};

#endif // LEDCONTROLLER_H

//#ifndef SRC_LEDCONTROLLER_H_
//#define SRC_LEDCONTROLLER_H_
//
//#include "stm32f4xx_hal.h"
//#include "FreeRTOS.h"
//#include "queue.h"
//#include "task.h"
//#include <cstdint>
//
///// One blink command: flash `count` times, `delayMs` between on/off
//struct BlinkCommand {
//    uint16_t count;
//    uint16_t delayMs;
//};
//
//class LEDController {
//public:
//    /// ctor takes the GPIO port & pin for the on‐board LED
//    LEDController(GPIO_TypeDef* port, uint16_t pin);
//
//    /// call once (from main.c) to create the RTOS queue & task
//    void begin();
//
//    /// allow others (Comm) to grab our queue handle
//    QueueHandle_t getQueue() const { return _queue; }
//    static LEDController* instance() { return _instance; }
//    uint32_t getTotalExecuted() const { return _totalExecuted; }
//    uint16_t getRemaining()     const { return _remaining;     }
//
//private:
//    static LEDController* _instance;
//    /// RTOS task wrapper
//    static void taskEntry(void* pvParameters);
//    /// actual blink loop
//    void        taskLoop();
//
//    GPIO_TypeDef* _port;
//    uint16_t      _pin;
//    QueueHandle_t _queue;
//    TaskHandle_t  _task;
//
//    // new state for status tracking
//    uint32_t _totalExecuted = 0;
//    uint16_t _remaining     = 0;
//};
//
//#ifdef __cplusplus
//extern "C" {
//#endif
///// C‐API to call from main.c
//void          MX_LED_Init(void);
///// C‐API to get the queue handle (used by Comm)
//QueueHandle_t MX_LED_GetQueue(void);
//#ifdef __cplusplus
//}
//#endif
//#endif /* SRC_LEDCONTROLLER_H_ */
