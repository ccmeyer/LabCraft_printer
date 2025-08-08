/*
 * Comm.h
 *
 *  Created on: Jun 17, 2025
 *      Author: conar
 */

#ifndef INC_COMM_H_
#define INC_COMM_H_
//#include "stm32f4xx_hal.h"
//#include "FreeRTOS.h"
//
//class Comm {
//public:
//  Comm(UART_HandleTypeDef* huart);
//  static Comm* instance() { return _instance; }
//  void begin();
//
//  // call when an action fully completes:
//  void notifyCommandComplete(uint8_t seq) { _lastCompletedSeq = seq; }
//
//private:
//  UART_HandleTypeDef* _huart;
//  uint8_t             _rxByte;
//
//  // RX state
//  enum RxState { WAIT_START, WAIT_LEN, WAIT_DATA };
//  RxState _rxState = WAIT_START;
//  uint8_t _rxLen    = 0;
//  uint8_t _rxBuf[16];
//  uint8_t _rxIdx    = 0;
//
//  // sequence tracking  <<< SEQ
//  uint8_t _expectedSeq      = 0;
//  uint8_t _lastCompletedSeq = 0xFF;
//
//  // status task
//  static void statusTaskEntry(void* pv);
//  void        statusTask();
//
//  // framing & CRC
//  static constexpr uint8_t START_BYTE = 0xAA;
//  static uint16_t crc16(const uint8_t* data, uint16_t len);
//
//  // send generic frame
//  void sendFrame(const uint8_t* payload, size_t len);
//
//  // parse a valid, length-checked, crc-checked packet
//  void handlePacket(const uint8_t* buf, uint8_t len);
//
//  static Comm* _instance;
//};
//
//// C‐API init
//extern "C" void MX_COMM_Init(UART_HandleTypeDef* huart);
//// called by actions when done:
//extern "C" void COMM_CommandComplete(uint8_t seq);

#include "stm32f4xx_hal.h"
#include <cstdint>

static constexpr uint8_t CMD_STATUS        = 0x02;
static constexpr uint8_t TAG_LED_TOTAL     = 0x10;
static constexpr uint8_t TAG_LED_REMAIN    = 0x11;
static constexpr uint8_t TAG_PRINT_P       = 0x12;
static constexpr uint8_t TAG_REFUEL_P      = 0x13;
static constexpr uint8_t TAG_TAR_PRINT_P   = 0x14;
static constexpr uint8_t TAG_TAR_REFUEL_P  = 0x15;

static constexpr uint8_t TAG_X_POS         = 0x20;
static constexpr uint8_t TAG_Y_POS         = 0x21;
static constexpr uint8_t TAG_Z_POS         = 0x22;
static constexpr uint8_t TAG_P_POS         = 0x23;
static constexpr uint8_t TAG_R_POS         = 0x24;

static constexpr uint8_t TAG_TAR_X_POS     = 0x25;
static constexpr uint8_t TAG_TAR_Y_POS     = 0x26;
static constexpr uint8_t TAG_TAR_Z_POS     = 0x27;
static constexpr uint8_t TAG_TAR_P_POS     = 0x28;
static constexpr uint8_t TAG_TAR_R_POS     = 0x29;

static constexpr uint8_t TAG_DROP_TOTAL    = 0x30;
static constexpr uint8_t TAG_DROP_REMAIN   = 0x31;
static constexpr uint8_t TAG_PRINT_PW      = 0x32;
static constexpr uint8_t TAG_REFUEL_PW     = 0x33;
static constexpr uint8_t TAG_DISP_FREQ     = 0x34;

static constexpr uint8_t TAG_ACTIVE_P	   = 0x40;
static constexpr uint8_t TAG_ACTIVE_R	   = 0x41;
static constexpr uint8_t TAG_CMD_DEPTH     = 0x50;
static constexpr uint8_t TAG_LAST_CMD      = 0x51;
static constexpr uint8_t TAG_CURR_CMD      = 0x52;

static constexpr uint8_t TAG_FLASH_NUM	   = 0x60;

class Comm {
public:
    Comm(UART_HandleTypeDef* huart);
    /// call once (from main.c) to arm UART‐RX interrupts
    void begin();

    /// access from ISR
    static Comm* instance() { return _instance; }
    void sendFrame(UART_HandleTypeDef* huart,
                          const uint8_t* payload,
                          size_t        len);
    UART_HandleTypeDef* _huart;
    uint8_t             _rxByte;
    enum RxState { WAIT_START, WAIT_LEN, WAIT_DATA };
    RxState _rxState = WAIT_START;
    uint8_t _rxLen    = 0;
    uint8_t _rxBuf[64];
    uint8_t _rxIdx    = 0;

    // framing & CRC
    static uint16_t crc16(const uint8_t* data, uint16_t len);
    static constexpr uint8_t START_BYTE = 0xAA;


    // sequence tracking  <<< SEQ
    uint8_t _expectedSeq      = 0;
    uint8_t _lastCompletedSeq = 0xFF;

    // parse a valid, length-checked, crc-checked packet
    void handlePacket(const uint8_t* buf, uint8_t len);

    // Send a 2‐byte payload: <cmd, seq>, wrapped in START/len/CRC
    void sendCommandByte(uint8_t cmd, uint8_t seq = 0);

private:

    static Comm*        _instance;
    // for status task
    static void statusTaskEntry(void* pv);
    void        statusTask();



    // send generic frame
    void sendFrame(const uint8_t* payload, size_t len);
};

#ifdef __cplusplus
extern "C" {
#endif
/// C‐API to call from main.c
void MX_COMM_Init(UART_HandleTypeDef* huart);
#ifdef __cplusplus
}
#endif

#endif /* INC_COMM_H_ */
