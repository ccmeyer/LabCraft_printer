/*
 * Comm.h
 *
 *  Created on: Jun 17, 2025
 *      Author: conar
 */

#ifndef INC_COMM_H_
#define INC_COMM_H_

#include "BoardConfig.h"
#include "stm32f4xx_hal.h"
#include "CommCodec.h"
#include "CrashLog.h"
#include <cstdint>
#include <cstddef>
#include "FreeRTOS.h"
#include "semphr.h"

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
static constexpr uint8_t TAG_FLASH_WIDTH   = 0x61;
static constexpr uint8_t TAG_FLASH_DELAY   = 0x62;
static constexpr uint8_t TAG_FLASH_DROPS   = 0x63;
static constexpr uint8_t TAG_EXT_COUNT     = 0x64;


static constexpr uint8_t TAG_X_MAX_HZ  = 0x70;
static constexpr uint8_t TAG_Y_MAX_HZ  = 0x71;
static constexpr uint8_t TAG_Z_MAX_HZ  = 0x72;
static constexpr uint8_t TAG_X_ACCEL   = 0x73; // steps/s^2 (truncate to u16 if you like)
static constexpr uint8_t TAG_Y_ACCEL   = 0x74;
static constexpr uint8_t TAG_Z_ACCEL   = 0x75;

static constexpr uint8_t TAG_GRIP_PULSE     = 0x80;
static constexpr uint8_t TAG_GRIP_REFRESH   = 0x81;

static constexpr uint8_t TAG_RESET_SEQ32               = 0x10;
static constexpr uint8_t TAG_RESET_CAUSE              = 0x11;
static constexpr uint8_t TAG_RESET_FLAGS              = 0x12;
static constexpr uint8_t TAG_RESET_LAST_FAULT         = 0x13;
static constexpr uint8_t TAG_RESET_LAST_TASK          = 0x14;
static constexpr uint8_t TAG_RESET_BOOT_COUNT         = 0x15;
static constexpr uint8_t TAG_RESET_FAULT_COUNT        = 0x16;
static constexpr uint8_t TAG_RESET_WATCHDOG_COUNT     = 0x17;
static constexpr uint8_t TAG_RESET_WATCHDOG_STICKY_CT = 0x18;
static constexpr uint8_t TAG_RESET_WATCHDOG_RAW_SR    = 0x19;
static constexpr uint8_t TAG_RESET_UPTIME_MS          = 0x1A;
static constexpr uint8_t TAG_RESET_BOOT_STAGE         = 0x1B;
static constexpr uint8_t TAG_RESET_RECOVERY_BOOT      = 0x1C;
static constexpr uint8_t TAG_RESET_FAULT_STAGE        = 0x1D;
static constexpr uint8_t TAG_RESET_WATCHDOG_LATE_TASK = 0x1E;
static constexpr uint8_t TAG_RESET_ACTIVE_COMMAND     = 0x1F;



class Comm {
public:
    Comm(UART_HandleTypeDef* huart);
    /// call once (from main.c) to arm UART‐RX interrupts
    void begin();

    /// access from ISR
    static Comm* instance() { return _instance; }

    // framing & CRC
    static uint16_t crc16(const uint8_t* data, uint16_t len);
    static constexpr uint8_t START_BYTE = 0xAA;

    // parse a valid, length-checked, crc-checked packet
    void handlePacket(const uint8_t* buf, uint8_t len);

    // Send a 2‐byte payload: <cmd, seq>, wrapped in START/len/CRC
    void sendCommandByte(uint8_t cmd, uint8_t seq = 0);
    void sendAckWithSeq32(uint8_t ackCmd, uint8_t seq8, uint32_t seq32, bool includeSeq32);
    void sendResetReport(uint8_t seq8, uint32_t seq32, const CrashLogSnapshot* snap, uint32_t recoveryBoot);

    void sendFrame(UART_HandleTypeDef* huart,
                          const uint8_t* payload,
                          size_t        len);

    // briefly pause status spam (optional)
    void setStatusPaused(bool p);

    void resetReceiveState();

    static void resetStatusMetrics();
    static uint32_t getStatusChunk0Count();
    static uint32_t getStatusChunk1Count();
    static uint32_t getStatusAlternationErrors();
    static uint32_t getStatusPeriodAvgMs();
    static uint32_t getStatusPeriodMaxJitterMs();

    // RX byte feeder (called from UART ISR or from USB receive callback)
    void onRxByte(uint8_t b);
    void onRxBytes(const uint8_t* data, uint32_t len);

    UART_HandleTypeDef* _huart;
    uint8_t             _rxByte;



    CommCodec::RxParser _rxParser{};

    volatile bool _txBusy = false;
    uint8_t _txBuf[160];   // >= max frame size (header + payload + CRC)

    UART_HandleTypeDef* handle() const { return _huart; }
    void on_tx_cplt() { _txBusy = false; }  // or a nicer name




    // sequence tracking  <<< SEQ
    uint8_t _expectedSeq      = 0;
    uint8_t _lastCompletedSeq = 0xFF;

    volatile bool 	  _needRxRearm = false;

private:

    static Comm*        _instance;
    // for status task
    static void statusTaskEntry(void* pv);
    void        statusTask();

    SemaphoreHandle_t _txMutex = nullptr;
    volatile bool     _statusPaused = false;

    // transport write (UART or USB)
    bool txWrite(const uint8_t* data, size_t len, uint32_t timeout_ms);

    // helper to build and send framed packet in one go
    bool sendFramed(const uint8_t* payload, size_t len, uint32_t timeout_ms);
    bool sendRawFrame(UART_HandleTypeDef* huart, const uint8_t* frame, size_t len, uint32_t timeout_ms);

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
