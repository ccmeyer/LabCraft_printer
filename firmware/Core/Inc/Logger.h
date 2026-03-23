/*
 * Logger.h
 *
 *  Created on: Jun 23, 2025
 *      Author: conar
 */

#ifndef INC_LOGGER_H_
#define INC_LOGGER_H_

#include "stm32f4xx_hal.h"
#include <cstdarg>
#include <cstdint>
#include "FreeRTOS.h"
#include "semphr.h"
#include "task.h"

class Logger {
public:

  UART_HandleTypeDef* _huart = nullptr;
  DMA_HandleTypeDef*  _hdma  = nullptr;
  volatile bool       _dmaBusy = false;
  /// Get the one and only Logger
  static Logger* instance();
  UART_HandleTypeDef* handle() const { return _huart; }
  void on_tx_cplt();   // calls your existing _dmaComplete()

  Logger();

  /// Must call once (after MX_USART1_UART_Init & MX_DMA_Init)
  void begin(UART_HandleTypeDef* huart, DMA_HandleTypeDef* hdma_tx);

  /// Enqueue a formatted log line
  void log(const char* fmt, ...);

  void _flush();
  void _dmaComplete();

  /// After begin(), call this once to start stats reporting every `periodMs`:
  void startRunTimeStatsTask(uint32_t periodMs = 1000);

private:
  static Logger* _instance;

  static constexpr size_t BUF_SIZE = 512;
  uint8_t   _buf[BUF_SIZE];
  char      _formatScratch[BUF_SIZE] = {};
  volatile size_t _head = 0, _tail = 0;
  size_t _inflightLen = 0;
  SemaphoreHandle_t _logMutex = nullptr;

  // Task handle so we could suspend/kill it if we ever wanted
  TaskHandle_t _statsTaskHandle = nullptr;

  // FreeRTOS task entry
  static void statsTaskEntry(void* arg);
  void statsTask(uint32_t periodMs);

  // (you need this for vTaskGetRunTimeStats)
  static constexpr size_t STATS_BUF_SZ = 512;

  // HAL will call this when DMA finishes a transfer:
//  void HAL_DMA_TxCpltCallback(DMA_HandleTypeDef *hdma);
  void HAL_UART_TxCpltCallback(UART_HandleTypeDef *huart);
};

// C API for main.c
extern "C" void MX_LOGGER_Init(UART_HandleTypeDef* huart1, DMA_HandleTypeDef* hdma_usart1_tx);
extern "C" void MX_LOGGER_Log_entry(const char* fmt);

#endif /* INC_LOGGER_H_ */
