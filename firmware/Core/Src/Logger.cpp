/*
 * Logger.cpp
 *
 *  Created on: Jun 23, 2025
 *      Author: conar
 */

#include "Logger.h"
#include "timers.h"
#include "stm32f4xx_hal_tim.h"

#include <cstdio>
#include <cstring>
#include <vector>
#include "task.h"

// singleton init
Logger* Logger::_instance = nullptr;

namespace {

uint32_t loggerSaveAndDisableInterrupts()
{
  const uint32_t primask = __get_PRIMASK();
  __disable_irq();
  return primask;
}

void loggerRestoreInterrupts(uint32_t primask)
{
  __set_PRIMASK(primask);
}

bool loggerSchedulerRunning()
{
  return xTaskGetSchedulerState() != taskSCHEDULER_NOT_STARTED;
}

}  // namespace

Logger::Logger() {}

Logger* Logger::instance() {
  return _instance;
}

void Logger::begin(UART_HandleTypeDef* huart, DMA_HandleTypeDef* hdma_tx) {
  _instance = this;
  _huart = huart;
  _hdma  = hdma_tx;
  _logMutex = xSemaphoreCreateMutex();
}

void Logger::log(const char* fmt, ...) {
  if (fmt == nullptr) return;

  const bool schedulerRunning = loggerSchedulerRunning();
  bool schedulerSuspended = false;
  bool mutexLocked = false;
  if (schedulerRunning) {
    if (_logMutex != nullptr) {
      if (xSemaphoreTake(_logMutex, portMAX_DELAY) == pdTRUE) {
        mutexLocked = true;
      } else {
        vTaskSuspendAll();
        schedulerSuspended = true;
      }
    } else {
      vTaskSuspendAll();
      schedulerSuspended = true;
    }
  }

  // 1) format into a logger-owned scratch buffer
  va_list ap;
  va_start(ap, fmt);
  const int len = vsnprintf(_formatScratch, sizeof(_formatScratch), fmt, ap);
  va_end(ap);
  if (len <= 0) {
    if (mutexLocked) {
      xSemaphoreGive(_logMutex);
    } else if (schedulerSuspended) {
      (void)xTaskResumeAll();
    }
    return;
  }
  size_t n = (len > (int)BUF_SIZE ? BUF_SIZE : static_cast<size_t>(len));

  // 2) copy into the ring buffer
  const uint32_t primask = loggerSaveAndDisableInterrupts();
  for (size_t i = 0; i < n; ++i) {
    this->_buf[_head] = static_cast<uint8_t>(_formatScratch[i]);
    _head = (_head + 1) % BUF_SIZE;
  }
  loggerRestoreInterrupts(primask);

  // 3) kick off a DMA send if not already in flight
  _flush();

  if (mutexLocked) {
    xSemaphoreGive(_logMutex);
  } else if (schedulerSuspended) {
    (void)xTaskResumeAll();
  }
}

void Logger::_flush() {
  if (_huart == nullptr) return;

  uint8_t* txPtr = nullptr;
  uint16_t txLen = 0u;
  {
    const uint32_t primask = loggerSaveAndDisableInterrupts();
    if (_dmaBusy || _head == _tail) {
      loggerRestoreInterrupts(primask);
      return;
    }
    const size_t chunk = (_head >= _tail) ? (_head - _tail) : (BUF_SIZE - _tail);
    _inflightLen = chunk;
    _dmaBusy = true;
    txPtr = &_buf[_tail];
    txLen = static_cast<uint16_t>(chunk);
    loggerRestoreInterrupts(primask);
  }

  if (HAL_UART_Transmit_DMA(_huart, txPtr, txLen) != HAL_OK) {
    const uint32_t primask = loggerSaveAndDisableInterrupts();
    _inflightLen = 0u;
    _dmaBusy = false;
    loggerRestoreInterrupts(primask);
  }
}

//// Called by HAL when the DMA transfer completes
//extern "C" void HAL_DMA_TxCpltCallback(DMA_HandleTypeDef *hdma) {
//  auto log = Logger::instance();
//  if (hdma == log->_hdma) {
//    log->_dmaComplete();
//  }
//}

//extern "C" void HAL_UART_TxCpltCallback(UART_HandleTypeDef *huart)
//{
//    auto L = Logger::instance();
//    if (huart == L->_huart) {
//        L->_dmaComplete();
//    }
//}

void Logger::on_tx_cplt() { _dmaComplete(); }  // reuse your existing logic

void Logger::_dmaComplete() {
  // we just sent “chunk” bytes from _tail
//  size_t chunk = (_head > _tail)
//    ? (_head - _tail)
//    : (BUF_SIZE - _tail);
//  _tail     = (_tail + chunk) % BUF_SIZE;
// if there's more left, send it now
//	_flush();
  const uint32_t primask = loggerSaveAndDisableInterrupts();
  _tail = (_tail + _inflightLen) % BUF_SIZE;
  _inflightLen = 0u;
  _dmaBusy = false;
  loggerRestoreInterrupts(primask);
  _flush();

}

// C‐API entry point; call this in main.c after you init USART1 & its DMA
extern "C" void MX_LOGGER_Init(UART_HandleTypeDef* huart1, DMA_HandleTypeDef* hdma_usart1_tx) {
  static Logger logger;
  logger.begin(huart1, hdma_usart1_tx);
  logger.startRunTimeStatsTask(3000 /* ms */);
}

extern "C" void MX_LOGGER_Log_entry(const char* fmt) {
  if (fmt == nullptr) {
    return;
  }
  Logger::instance()->log("%s", fmt);
}

static void EXTI8_DiagDump(void)
{
    uint32_t moder = (GPIOE->MODER  >> (8*2)) & 0x3u; // 0=input, 1=out, 2=AF, 3=analog
    uint32_t pupd  = (GPIOE->PUPDR  >> (8*2)) & 0x3u; // 0=no,1=PU,2=PD
    uint32_t idr   = (GPIOE->IDR    >> 8) & 1u;

    // EXTI8 mapping: EXTICR3 bits [3:0]
    uint32_t exticr3 = SYSCFG->EXTICR[2];
    uint32_t exti8_port = (exticr3 >> 0) & 0xFu; // 1=PB, 4=PE, 6=PG, etc. (0=PA)

    uint32_t imr  = (EXTI->IMR  >> 8) & 1u;
    uint32_t rtsr = (EXTI->RTSR >> 8) & 1u;
    uint32_t ftsr = (EXTI->FTSR >> 8) & 1u;
    uint32_t pr   = (EXTI->PR   >> 8) & 1u;

    Logger::instance()->log("PE8 MODER=%lu PUPD=%lu IDR=%lu  EXTI8 map=%lu(IMR=%lu,RTSR=%lu,FTSR=%lu,PR=%lu)\r\n",
                moder, pupd, idr, exti8_port, imr, rtsr, ftsr, pr);
}


void Logger::startRunTimeStatsTask(uint32_t periodMs) {
    // Keep this diagnostic task lightweight; move large scratch buffers out of task stack.
    xTaskCreate(
      statsTaskEntry,
      "LogStats",
	  512,
      reinterpret_cast<void*>(periodMs),
      tskIDLE_PRIORITY+1,
      &_statsTaskHandle
    );
}

void Logger::statsTaskEntry(void* arg) {
    uint32_t periodMs = reinterpret_cast<uint32_t>(arg);
    Logger::instance()->statsTask(periodMs);
    vTaskDelete(nullptr);
}
static const size_t STATS_BUF_SZ = 512;

void Logger::statsTask(uint32_t periodMs) {
    // Use static storage so runtime-stats formatting does not consume task stack headroom.
    static char buf[STATS_BUF_SZ];
    TickType_t ticks = pdMS_TO_TICKS(periodMs);
    EXTI8_DiagDump();

    for (;;) {
		HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);

        vTaskDelay(ticks);

        // fill buf with a textual table of "<task>    <abs time>   <%>"
        vTaskGetRunTimeStats(buf);
        log("===LOG===\n%s\n", buf);
    }
}





