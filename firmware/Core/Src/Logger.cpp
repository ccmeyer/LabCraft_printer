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

Logger::Logger() {}

Logger* Logger::instance() {
  return _instance;
}

void Logger::begin(UART_HandleTypeDef* huart, DMA_HandleTypeDef* hdma_tx) {
  _instance = this;
  _huart = huart;
  _hdma  = hdma_tx;
}

void Logger::log(const char* fmt, ...) {
  // 1) format into a temporary buffer
  char tmp[512];
  va_list ap;
  va_start(ap, fmt);
  int len = vsnprintf(tmp, sizeof(tmp), fmt, ap);
  va_end(ap);
  if (len <= 0) return;
  size_t n = (len > (int)BUF_SIZE ? BUF_SIZE : static_cast<size_t>(len));

  // 2) copy into the ring buffer
  for (size_t i = 0; i < n; ++i) {
    this->_buf[_head] = static_cast<uint8_t>(tmp[i]);
    _head = (_head + 1) % BUF_SIZE;
  }

  // 3) kick off a DMA send if not already in flight
  _flush();
}

void Logger::_flush() {
//  if (_dmaBusy || _head == _tail) return;
//  size_t chunk = (_head > _tail)
//    ? (_head - _tail)
//    : (BUF_SIZE - _tail);
//  _dmaBusy = true;
//  HAL_UART_Transmit_DMA(_huart, &this->_buf[_tail], chunk);
	if (_dmaBusy || _head == _tail) return;
	size_t chunk = (_head >= _tail) ? (_head - _tail) : (BUF_SIZE - _tail);
	_inflightLen = chunk;
	_dmaBusy = true;
	HAL_UART_Transmit_DMA(_huart, &_buf[_tail], (uint16_t)chunk);
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
  _tail = (_tail + _inflightLen) % BUF_SIZE;
  _inflightLen = 0;
  _dmaBusy  = false;
  _flush();

}

// C‐API entry point; call this in main.c after you init USART1 & its DMA
extern "C" void MX_LOGGER_Init(UART_HandleTypeDef* huart1, DMA_HandleTypeDef* hdma_usart1_tx) {
  static Logger logger;
  logger.begin(huart1, hdma_usart1_tx);
  logger.startRunTimeStatsTask(3000 /* ms */);
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
    // spawn at idle+1, 512 words stack
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
    // one buffer to hold the table
    char buf[STATS_BUF_SZ];
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





