/*
 * Comm.cpp
 *
 *  Created on: Jun 17, 2025
 *      Author: conar
 */
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
#include "Flash.hpp"

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


// framing constants
static constexpr uint8_t START_BYTE = 0xAA;
static constexpr int   MAX_BUF    = 64;  // enough for cmd + 3×2B + CRC

static constexpr uint8_t TAG_P1 = 0x01;
static constexpr uint8_t TAG_P2 = 0x02;
static constexpr uint8_t TAG_P3 = 0x03;

// bring in the LED queue getter
//extern "C" QueueHandle_t MX_LED_GetQueue();

//------------------------------------------------------------------------------
// static singleton pointer
Comm* Comm::_instance = nullptr;

Comm::Comm(UART_HandleTypeDef* huart)
  : _huart(huart), _rxByte(0)
{}

// CRC16-X25
uint16_t Comm::crc16(const uint8_t* data, uint16_t len) {
    uint16_t crc = 0xFFFF;
    while (len--) {
        crc ^= *data++;
        for (int i=0; i<8; ++i)
            crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : (crc >> 1);
    }
    return crc;
}

void Comm::begin() {
    _instance = this;
    // arm the HAL RX interrupt for 1 byte
    HAL_UART_Receive_IT(_huart, &_rxByte, 1);

    // spawn status‐sender task @50 ms intervals
    xTaskCreate(
      statusTaskEntry, "Status", 128,
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

// This is invoked by HAL when the UART Rx completes
extern "C" void HAL_UART_RxCpltCallback(UART_HandleTypeDef* huart) {
	auto c = Comm::instance();
  // re-arm always
  HAL_UART_Receive_IT(huart, &c->_rxByte, 1);

  if (!c || huart != c->_huart) return;

  uint8_t b = c->_rxByte;
  HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);

  switch (c->_rxState) {
	case Comm::WAIT_START:
	  if (b == Comm::START_BYTE)
		c->_rxState = Comm::WAIT_LEN;
	  break;

	case Comm::WAIT_LEN:
	  c->_rxLen = b;
	  if ((size_t)c->_rxLen + 2 <= sizeof(c->_rxBuf)) {
		c->_rxIdx = 0;
		c->_rxState = Comm::WAIT_DATA;
	  } else {
		c->_rxState = Comm::WAIT_START;
	  }
	  break;

	case Comm::WAIT_DATA:
//		HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);
	  c->_rxBuf[c->_rxIdx++] = b;
	  if (c->_rxIdx >= c->_rxLen + 2) {
		// got full payload + CRC
		uint16_t recCrc = uint16_t(c->_rxBuf[c->_rxLen])
						| (uint16_t(c->_rxBuf[c->_rxLen+1])<<8);
		if (recCrc == Comm::crc16(c->_rxBuf, c->_rxLen)) {
		  c->handlePacket(c->_rxBuf, c->_rxLen);
		}
		c->_rxState = Comm::WAIT_START;
	  }
	  break;
  }
}

void Comm::handlePacket(const uint8_t* buf, uint8_t len) {
    // Must have at least cmd+seq
    if (len < 2) {
        return;
    }

    // 1) basic header
    Orchestrator::Command oc;
    oc.cmd = static_cast<Orchestrator::CmdType>(buf[0]);
    oc.seq = buf[1];

//    HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);
    // 2) default all params to zero
    oc.p1 = 0;  oc.p2 = 0;  oc.p3 = 0;

    // 3) TLV decode
    int idx = 2;
    while (idx + 1 < len) {
        uint8_t tag = buf[idx++];
        uint8_t l   = buf[idx++];
        if (idx + l > len) break; // bounds check
        uint32_t v  = 0;
        // little-endian assemble
        for (int i = 0; i < l; ++i) {
            v |= uint32_t(buf[idx++]) << (8 * i);
        }
        switch (tag) {
          case TAG_P1: oc.p1 = v; break;
          case TAG_P2: oc.p2 = v; break;
          case TAG_P3: oc.p3 = v; break;
          default: /* ignore unknown tags */ break;
        }
    }

    // 4) dispatch
    auto orch = Orchestrator::instance();
    if (!orch) {
        // Orchestrator not ready yet; ignore safely (no ACK from here)
        return;
    }
    BaseType_t woken = pdFALSE;
    orch->enqueueFromISR(oc, &woken);
    portYIELD_FROM_ISR(woken);
}

void Comm::resetReceiveState() {
    _rxState = WAIT_START;
    _rxIdx   = 0;
}

//void Comm::handlePacket(const uint8_t* buf, uint8_t len) {
//    // 1) basic header
//    Orchestrator::Command oc;
//    oc.cmd = static_cast<Orchestrator::CmdType>(buf[0]);
//    oc.seq = buf[1];
//
//    // 2) default all params to zero
//    oc.p1 = 0;  oc.p2 = 0;  oc.p3 = 0;
//
//    // 3) TLV decode
//    int idx = 2;
//    while (idx < len) {
//        uint8_t tag = buf[idx++];
//        uint8_t l   = buf[idx++];
//        uint32_t v  = 0;
//        // little-endian assemble
//        for (int i = 0; i < l; ++i) {
//            v |= uint32_t(buf[idx++]) << (8 * i);
//        }
//        switch (tag) {
//          case TAG_P1: oc.p1 = v; break;
//          case TAG_P2: oc.p2 = v; break;
//          case TAG_P3: oc.p3 = v; break;
//          default: /* ignore unknown tags */ break;
//        }
//    }
//
//    // 4) dispatch
//    BaseType_t woken = pdFALSE;
//    Orchestrator::instance()->enqueueFromISR(oc, &woken);
//    portYIELD_FROM_ISR(woken);
//}

void Comm::sendCommandByte(uint8_t cmd, uint8_t seq) {
  uint8_t payload[2] = { cmd, seq };
  uint8_t header[2]  = { START_BYTE, 2 };
  uint16_t crc       = crc16(payload, 2);
  uint8_t tail[2]    = { uint8_t(crc & 0xFF), uint8_t(crc >> 8) };
  // block‐send directly on UART2:
  HAL_UART_Transmit(_huart, header, 2, HAL_MAX_DELAY);
  HAL_UART_Transmit(_huart, payload, 2, HAL_MAX_DELAY);
  HAL_UART_Transmit(_huart, tail, 2, HAL_MAX_DELAY);
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
    uint8_t  header[2] = { 0xAA, (uint8_t)len };
    uint16_t crc = Comm::crc16(payload, len);

    // send header
    HAL_UART_Transmit(huart, header, 2, HAL_MAX_DELAY);
    // send payload
    HAL_UART_Transmit(huart, (uint8_t*)payload, len, HAL_MAX_DELAY);
    // send crc
    uint8_t tail[2] = { uint8_t(crc & 0xFF), uint8_t(crc >> 8) };
    HAL_UART_Transmit(huart, tail, 2, HAL_MAX_DELAY);
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
//	Chunk chunk = CHUNK_0;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(50));

        switch (chunk) {
        	case CHUNK_0: {
				// LED, pressure, flash

				uint8_t payload[1 + 12*(1+1+4)] = {};
				size_t idx = 0;

				auto ps = PressureSensor::instance();
				uint16_t printP  = uint16_t(ps->getPrintPressure()  + 0.5f);
				uint16_t refuelP = uint16_t(ps->getRefuelPressure() + 0.5f);

				uint32_t targetPrint = PressureRegulator::regP().getTarget();
				uint32_t targetRefuel = PressureRegulator::regR().getTarget();

				auto printer = Printer::instance();
				uint32_t dropTot = printer->getTotalDispensed();
				uint32_t dropRem = printer->getRemaining();
				uint32_t printW = printer->getPrintPulse();
				uint32_t refuelW = printer->getRefuelPulse();
				uint32_t dispHz = printer->getDispenseHz();

				UBaseType_t depth = Orchestrator::getCommandDepth();
				uint16_t currentCmd = Orchestrator::getCurrentCmdNum();
				uint16_t lastCmd = Orchestrator::getLastCmdNum();

				// Command byte first
				payload[idx++] = CMD_STATUS;

				APPEND_U16(payload, idx, TAG_PRINT_P,     printP);
				APPEND_U16(payload, idx, TAG_REFUEL_P,    refuelP);

				APPEND_U16(payload, idx, TAG_TAR_PRINT_P, targetPrint);
				APPEND_U16(payload, idx, TAG_TAR_REFUEL_P, targetRefuel);

				APPEND_S32(payload, idx, TAG_DROP_TOTAL,  dropTot);
				APPEND_S32(payload, idx, TAG_DROP_REMAIN, dropRem);

				APPEND_U16(payload, idx, TAG_PRINT_PW,    printW);
				APPEND_U16(payload, idx, TAG_REFUEL_PW,   refuelW);
				APPEND_U16(payload, idx, TAG_DISP_FREQ,   dispHz);

				APPEND_U16(payload, idx, TAG_CMD_DEPTH,   depth);
				APPEND_U16(payload, idx, TAG_CURR_CMD,    currentCmd);
				APPEND_U16(payload, idx, TAG_LAST_CMD,    lastCmd);

		        sendFrame(_huart, payload, idx);
				chunk = static_cast<Chunk>((chunk + 1) % CHUNK_COUNT);

				break;
        	}
			case CHUNK_1: {
				uint8_t payload[1 + 12*(1+1+4)] = {};
				size_t idx = 0;

				auto pos = Gantry::instance()->getPosition();
				auto posP = Stepper::stepperP()->getPosition();
				auto posR = Stepper::stepperR()->getPosition();

				int32_t tarX = Stepper::stepperX()->getTargetPosition();
				int32_t tarY = Stepper::stepperY()->getTargetPosition();
				int32_t tarZ = Stepper::stepperZ()->getTargetPosition();
//				int32_t tarP = Stepper::stepperP()->getTargetPosition();
//				int32_t tarR = Stepper::stepperR()->getTargetPosition();

				bool activeP = PressureRegulator::regP().isActive();
				bool activeR = PressureRegulator::regR().isActive();

				uint16_t currentCmd = Orchestrator::getCurrentCmdNum();
				uint16_t lastCmd = Orchestrator::getLastCmdNum();

				// Command byte first
				payload[idx++] = CMD_STATUS;

				APPEND_S32(payload, idx, TAG_X_POS,       pos.x);
				APPEND_S32(payload, idx, TAG_Y_POS,       pos.y);
				APPEND_S32(payload, idx, TAG_Z_POS,       pos.z);
				APPEND_S32(payload, idx, TAG_P_POS,       posP);
				APPEND_S32(payload, idx, TAG_R_POS,       posR);
		//
				APPEND_S32(payload, idx, TAG_TAR_X_POS,   tarX);
				APPEND_S32(payload, idx, TAG_TAR_Y_POS,   tarY);
				APPEND_S32(payload, idx, TAG_TAR_Z_POS,   tarZ);
//				APPEND_S32(payload, idx, TAG_TAR_P_POS,   tarP);
//				APPEND_S32(payload, idx, TAG_TAR_R_POS,   tarR);

				APPEND_U16(payload, idx, TAG_ACTIVE_P,    activeP);
				APPEND_U16(payload, idx, TAG_ACTIVE_R,    activeR);

				APPEND_U16(payload, idx, TAG_CURR_CMD,    currentCmd);
				APPEND_U16(payload, idx, TAG_LAST_CMD,    lastCmd);

		        sendFrame(_huart, payload, idx);
				chunk = static_cast<Chunk>((chunk + 1) % CHUNK_COUNT);

				break;
			}
			default:{}
        }

    }
}

