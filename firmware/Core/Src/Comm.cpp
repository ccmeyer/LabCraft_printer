/*
 * Comm.cpp
 *
 *  Created on: Jun 17, 2025
 *      Author: conar
 */
#include "BoardConfig.h"
#include "Comm.h"
#include "stm32f4xx_hal.h"
#include "FreeRTOS.h"
#include "queue.h"
#include "task.h"
#include "LEDController.h"   // for BlinkCommand & MX_LED_GetQueue()
#include "PressureSensor.h"
#include "Printer.h"
#include "Orchestrator.h"
#include "PressureRegulator.h"
#include "Gantry.h"
#include "Gripper.h"
#include "Logger.h"
#include "CommCodec.h"

#if (LC_HAS_IMAGING == 1)
#include "Flash.hpp"
#endif


// Append an unsigned 16 bit value
#define APPEND_U16(p, idx, tag, v)      \
  do {                                  \
    p[(idx)++] = tag;                   \
    p[(idx)++] = 2;                     \
    p[(idx)++] = uint8_t((v) & 0xFF);   \
    p[(idx)++] = uint8_t((v)>>8 & 0xFF);\
  } while(0)

// Append a signed 32 bit value
#define APPEND_S32(p, idx, tag, v)       \
  do {                                   \
    p[(idx)++] = tag;                    \
    p[(idx)++] = 4;                      \
    p[(idx)++] = uint8_t((v)      &0xFF);\
    p[(idx)++] = uint8_t((v)>> 8 &0xFF);\
    p[(idx)++] = uint8_t((v)>>16 &0xFF);\
    p[(idx)++] = uint8_t((v)>>24 &0xFF);\
  } while(0)

//------------------------------------------------------------------------------
// static singleton pointer
Comm* Comm::_instance = nullptr;

Comm::Comm(UART_HandleTypeDef* huart)
  : _huart(huart), _rxByte(0)
{}

// CRC16-X25
uint16_t Comm::crc16(const uint8_t* data, uint16_t len) {
    return CommCodec::crc16(data, len);
}

void Comm::begin() {
    _instance = this;

    // Create TX mutex
    _txMutex = xSemaphoreCreateMutex();

    // arm the HAL RX interrupt for 1 byte
    HAL_UART_Receive_IT(_huart, &_rxByte, 1);

    // spawn status‐sender task @50 ms intervals
    xTaskCreate(
      statusTaskEntry, "Status", 256,
      this,                // pvParameters
      tskIDLE_PRIORITY+1,  // priority
      nullptr
    );
}

// C‐API entry: call once from main.c
extern "C" void MX_COMM_Init(UART_HandleTypeDef* huart) {
    static Comm comm(huart);
    comm.begin();
}

extern "C" void HAL_UART_ErrorCallback(UART_HandleTypeDef* huart) {
    auto c = Comm::instance();
    if (!c || huart != c->_huart) return;

    // Stop whatever the HAL thinks it's doing
    HAL_UART_AbortReceive_IT(huart);
    HAL_UART_AbortTransmit_IT(huart);

    // Clear common error flags (HAL/series specific; this works on F4 HAL)
    __HAL_UART_CLEAR_PEFLAG(huart);
    __HAL_UART_CLEAR_FEFLAG(huart);
    __HAL_UART_CLEAR_NEFLAG(huart);
    __HAL_UART_CLEAR_OREFLAG(huart);

    // Reset our parser
    c->resetReceiveState();

    // Try to re-arm RX; if busy, set a flag to retry from task context
    if (HAL_UART_Receive_IT(huart, &c->_rxByte, 1) != HAL_OK) {
        c->_needRxRearm = true;   // new volatile flag on Comm
    }
}

// This is invoked by HAL when the UART Rx completes
extern "C" void HAL_UART_RxCpltCallback(UART_HandleTypeDef* huart) {
	auto c = Comm::instance();

  if (!c || huart != c->_huart) return;

  uint8_t b = c->_rxByte;

  if (HAL_UART_Receive_IT(huart, &c->_rxByte, 1) != HAL_OK) {
    c->_needRxRearm = true;
  }

//  HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);

  uint8_t payloadLen = 0;
  if (CommCodec::feedRxByte(c->_rxParser, b, payloadLen) == CommCodec::FeedResult::FrameReady) {
      c->handlePacket(c->_rxParser.rxBuf, payloadLen);
  }
}

void Comm::setStatusPaused(bool p) {
    _statusPaused = p;
}

void Comm::handlePacket(const uint8_t* buf, uint8_t len) {
  if (len < 2) return;

  Orchestrator::Command oc{};
  const auto decoded = CommCodec::decodeCommand(buf, len);
  oc.cmd = static_cast<Orchestrator::CmdType>(decoded.cmd);
  oc.seq8 = decoded.seq8;
  oc.p1 = decoded.p1;
  oc.p2 = decoded.p2;
  oc.p3 = decoded.p3;
  oc.p1Len = decoded.p1Len;
  oc.p2Len = decoded.p2Len;
  oc.p3Len = decoded.p3Len;
  oc.seq32 = decoded.seq32;
  oc.hasSeq32 = decoded.hasSeq32;

  if (auto orch = Orchestrator::instance()) {
    BaseType_t woken = pdFALSE;
    orch->enqueueFromISR(oc, &woken);
    portYIELD_FROM_ISR(woken);
  }
}

void Comm::resetReceiveState() {
    _rxParser.state = CommCodec::RxParser::WAIT_START;
    _rxParser.rxIdx = 0;
    _rxParser.rxLen = 0;
}

void Comm::sendCommandByte(uint8_t cmd, uint8_t seq) {
    if (xSemaphoreTake(_txMutex, pdMS_TO_TICKS(50)) != pdTRUE) {
        return; // last resort: skip; you could log here
    }
    uint8_t payload[2] = { cmd, seq };
    uint8_t frame[2 + sizeof(payload) + 2] = {0};
    const size_t frameLen = CommCodec::encodeFrame(payload, sizeof(payload), frame, sizeof(frame));
    if (frameLen > 0) {
        HAL_UART_Transmit(_huart, frame, frameLen, HAL_MAX_DELAY);
    }
    xSemaphoreGive(_txMutex);
}

void Comm::sendAckWithSeq32(uint8_t ackCmd, uint8_t seq8, uint32_t seq32, bool includeSeq32) {
  uint8_t payload[2 + 2 + 4] = {0}; // [ack, seq8] + [tag,len,val]
  const uint8_t payloadLen = CommCodec::buildAckPayload(ackCmd, seq8, seq32, includeSeq32, payload, sizeof(payload));
  if (payloadLen == 0) {
      return;
  }

  uint8_t frame[2 + sizeof(payload) + 2] = {0};
  const size_t frameLen = CommCodec::encodeFrame(payload, payloadLen, frame, sizeof(frame));
  if (frameLen > 0) {
      HAL_UART_Transmit(_huart, frame, frameLen, HAL_MAX_DELAY);
  }
}


// ——— STATUS TASK ———

void Comm::statusTaskEntry(void* pv) {
    static_cast<Comm*>(pv)->statusTask();
    vTaskDelete(nullptr);
}

//  [ 0xAA | len | payload… | CRClo | CRChi ]
void Comm::sendFrame(UART_HandleTypeDef* huart,
                      const uint8_t* payload,
                      size_t        len)
{
    if (xSemaphoreTake(_txMutex, pdMS_TO_TICKS(50)) != pdTRUE) {
        return; // last resort: skip; you could log here
    }
    if (len > 255) {
        xSemaphoreGive(_txMutex);
        return;
    }

    uint8_t frame[2 + 255 + 2] = {0};
    const size_t frameLen = CommCodec::encodeFrame(payload, static_cast<uint8_t>(len), frame, sizeof(frame));
    if (frameLen > 0) {
        HAL_UART_Transmit(huart, frame, frameLen, HAL_MAX_DELAY);
    }
    xSemaphoreGive(_txMutex);
}

void uart_diag(UART_HandleTypeDef* huart)
{
    uint32_t pclk = (huart->Instance==USART1 || huart->Instance==USART6)
                    ? HAL_RCC_GetPCLK2Freq() : HAL_RCC_GetPCLK1Freq();
    uint32_t brr = huart->Instance->BRR;
    uint32_t cr1 = huart->Instance->CR1;
    uint32_t cr3 = huart->Instance->CR3;
    uint32_t over8 = (cr1 & USART_CR1_OVER8) ? 1u : 0u;

    // Rough actual baud estimate (good enough to catch “way off” cases)
    uint32_t mant = brr >> 4, frac = brr & 0xFu;
    uint32_t actual_baud = over8
        ? (pclk * 2u) / ((mant << 1) | frac)        // oversampling by 8
        : (pclk)      / (mant * 16u + frac);        // oversampling by 16
    if (auto L = Logger::instance()) {
        L->log("COMM diag: PCLK=%lu BRR=0x%04lx OVER8=%lu HWFC=%s actual=%lu baud\r\n",
                (unsigned long)pclk, (unsigned long)brr, (unsigned long)over8,
                (cr3 & (USART_CR3_RTSE|USART_CR3_CTSE)) ? "ON" : "OFF",
                (unsigned long)actual_baud);
    }
}

// Give your enum a real name:
enum Chunk : int {
  CHUNK_0,
  CHUNK_1,
  CHUNK_COUNT
};

// Make your variable that type:
static Chunk chunk = CHUNK_0;

void Comm::statusTask() {
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(50));

        if (_needRxRearm) {
          if (HAL_UART_Receive_IT(_huart, &_rxByte, 1) == HAL_OK) {
            _needRxRearm = false;
          }
        }
        if (_statusPaused) continue;

        switch (chunk) {
        	case CHUNK_0: {
				// LED, pressure, flash
				uint8_t payload[1 + 18*(1+1+4)] = {};
				size_t idx = 0;

				uint16_t printP  = 0;
				uint16_t refuelP = 0;
				auto ps = PressureSensor::instance();
				if (ps) {
				  printP = (uint16_t)ps->getPrintPressure();
				#if (LC_PRESSURE_PORTS > 1)
				  refuelP = (uint16_t)ps->getRefuelPressure();
				#endif
				}
				uint16_t targetPrint = (uint16_t)PressureRegulator::regP().getTarget();
				uint16_t targetRefuel = 0;
				#if (LC_PRESSURE_PORTS > 1)
				  targetRefuel = (uint16_t)PressureRegulator::regR().getTarget();
				#endif
				auto printer = Printer::instance();
				uint32_t dropTot = printer->getTotalDispensed();
				uint32_t dropRem = printer->getRemaining();
				uint32_t printW = printer->getPrintPulse();
				uint32_t refuelW = 0;
				#if (LC_PRESSURE_PORTS > 1)
				refuelW = printer->getRefuelPulse();   // if legacy Printer keeps this, fine; otherwise gate it
				#endif
				uint32_t dispHz = printer->getDispenseHz();

				uint32_t xMax = (uint32_t)Stepper::stepperX()->maxSpeedHz();
				uint32_t yMax = (uint32_t)Stepper::stepperY()->maxSpeedHz();
				uint32_t zMax = (uint32_t)Stepper::stepperZ()->maxSpeedHz();

				uint32_t xAcc = (uint32_t)Stepper::stepperX()->accelStepsPerSec2();
				uint32_t yAcc = (uint32_t)Stepper::stepperY()->accelStepsPerSec2();
				uint32_t zAcc = (uint32_t)Stepper::stepperZ()->accelStepsPerSec2();

				UBaseType_t depth = Orchestrator::getCommandDepth();
				uint32_t currentCmd = Orchestrator::getCurrentCmdNum();
				uint32_t lastCmd = Orchestrator::getLastCmdNum();

				// Command byte first
				payload[idx++] = CMD_STATUS;

				APPEND_U16(payload, idx, TAG_PRINT_P,     printP);
				APPEND_U16(payload, idx, TAG_REFUEL_P,    refuelP);

				APPEND_U16(payload, idx, TAG_TAR_PRINT_P,  targetPrint);
				APPEND_U16(payload, idx, TAG_TAR_REFUEL_P, targetRefuel);

				APPEND_S32(payload, idx, TAG_DROP_TOTAL,  dropTot);
				APPEND_S32(payload, idx, TAG_DROP_REMAIN, dropRem);

				APPEND_U16(payload, idx, TAG_PRINT_PW,    printW);
				APPEND_U16(payload, idx, TAG_REFUEL_PW,   refuelW);
				APPEND_U16(payload, idx, TAG_DISP_FREQ,   dispHz);

				APPEND_S32(payload, idx, TAG_X_MAX_HZ, xMax);
				APPEND_S32(payload, idx, TAG_Y_MAX_HZ, yMax);
				APPEND_S32(payload, idx, TAG_Z_MAX_HZ, zMax);

				APPEND_S32(payload, idx, TAG_X_ACCEL,  xAcc);
				APPEND_S32(payload, idx, TAG_Y_ACCEL,  yAcc);
				APPEND_S32(payload, idx, TAG_Z_ACCEL,  zAcc);

				APPEND_S32(payload, idx, TAG_CMD_DEPTH,   depth);
				APPEND_S32(payload, idx, TAG_CURR_CMD,    currentCmd);
				APPEND_S32(payload, idx, TAG_LAST_CMD,    lastCmd);

				sendFrame(_huart, payload, idx);
				chunk = static_cast<Chunk>((chunk + 1) % CHUNK_COUNT);

				break;
        	}
			case CHUNK_1: {
				uint8_t payload[1 + 19*(1+1+4)] = {};
				size_t idx = 0;

				auto pos = Gantry::instance()->getPosition();
				auto posP = Stepper::stepperP()->getPosition();
				int32_t posR = 0;
				#if (LC_PRESSURE_PORTS > 1)
				posR = Stepper::stepperR()->getPosition();
				#endif

				int32_t tarX = Stepper::stepperX()->getTargetPosition();
				int32_t tarY = Stepper::stepperY()->getTargetPosition();
				int32_t tarZ = Stepper::stepperZ()->getTargetPosition();

				bool activeP = PressureRegulator::regP().isActive();
				bool activeR = false;
				#if (LC_PRESSURE_PORTS > 1)
				activeR = PressureRegulator::regR().isActive();
				#endif

				uint32_t gripperPulseDuration = Gripper::instance().getPulseDurationMs();
				uint32_t gripperRefreshPeriod = Gripper::instance().getRefreshPeriodMs();



				uint32_t numFlashes = 0;
				uint32_t flashDuration = 0;
				uint32_t flashDelay = 0;
				uint16_t imagingDroplets = 0;
				uint32_t extCount = 0;
				#if (LC_HAS_IMAGING == 1)
				  if (auto f = Flash::instance()) {
				    numFlashes = f->getPulses();
				    flashDuration = f->getPulseDuration();
				  }
				  flashDelay = Orchestrator::getFlashDelay();
				  imagingDroplets = Orchestrator::getImagingDroplets();
				  extCount = Orchestrator::getExtCount();
				#endif

//				uint32_t numFlashes = Flash::instance()->getPulses();
//				uint32_t flashDuration = Flash::instance()->getPulseDuration();
//				uint32_t extCount = Orchestrator::getExtCount();

				uint32_t currentCmd = Orchestrator::getCurrentCmdNum();
				uint32_t lastCmd = Orchestrator::getLastCmdNum();

				// Command byte first
				payload[idx++] = CMD_STATUS;

				APPEND_S32(payload, idx, TAG_X_POS,       pos.x);
				APPEND_S32(payload, idx, TAG_Y_POS,       pos.y);
				APPEND_S32(payload, idx, TAG_Z_POS,       pos.z);
				APPEND_S32(payload, idx, TAG_P_POS,       posP);
				APPEND_S32(payload, idx, TAG_R_POS,       posR);

				APPEND_S32(payload, idx, TAG_TAR_X_POS,   tarX);
				APPEND_S32(payload, idx, TAG_TAR_Y_POS,   tarY);
				APPEND_S32(payload, idx, TAG_TAR_Z_POS,   tarZ);

				APPEND_S32(payload, idx, TAG_FLASH_NUM,	  numFlashes);
				APPEND_S32(payload, idx, TAG_FLASH_WIDTH, flashDuration);
				APPEND_S32(payload, idx, TAG_FLASH_DELAY, flashDelay);
				APPEND_U16(payload, idx, TAG_FLASH_DROPS, imagingDroplets);
				APPEND_S32(payload, idx, TAG_EXT_COUNT,   extCount);

				APPEND_U16(payload, idx, TAG_ACTIVE_P,    activeP);
				APPEND_U16(payload, idx, TAG_ACTIVE_R,    activeR);

				APPEND_S32(payload, idx, TAG_GRIP_PULSE,   gripperPulseDuration);
				APPEND_S32(payload, idx, TAG_GRIP_REFRESH,   gripperRefreshPeriod);

				APPEND_S32(payload, idx, TAG_CURR_CMD,    currentCmd);
				APPEND_S32(payload, idx, TAG_LAST_CMD,    lastCmd);

		        sendFrame(_huart, payload, idx);
				chunk = static_cast<Chunk>((chunk + 1) % CHUNK_COUNT);

				break;
			}
			default:{}
        }

    }
}
