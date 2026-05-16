/*
 * PressureSensor.h
 *
 *  Created on: Jun 17, 2025
 *      Author: conar
 */

#ifndef INC_PRESSURESENSOR_H_
#define INC_PRESSURESENSOR_H_

#include "stm32f4xx_hal.h"
#include "FreeRTOS.h"
#include "task.h"
#include "BoardConfig.h"

#include "cmsis_os.h"

class PressureSensor {
public:
    enum class RejectReason : uint8_t {
      None = 0,
      RailLow,
      RailHigh,
      Spike
    };

    struct ValidationConfig {
      uint16_t minRaw = 1200;
      uint16_t maxRaw = 7000;
      uint16_t maxStepPerSample = 250;
      uint8_t maxConsecutiveRejects = 3;
    };

    struct ControlSample {
      uint16_t raw = 0;
      uint16_t avg = 0;
      uint16_t previousRaw = 0;
      uint32_t tickMs = 0;
      bool valid = false;
      bool lastReadRejected = false;
      RejectReason rejectReason = RejectReason::None;
      uint32_t rejectCount = 0;
      uint32_t railRejectCount = 0;
      uint32_t spikeRejectCount = 0;
    };

    /// Singleton accessor
    static PressureSensor* instance();

    /// ctor: pass in your I2C handle, the TCA mux address, and the sensor 7-bit address
    PressureSensor(I2C_HandleTypeDef* hi2c,
                   uint8_t tcaAddr,
                   uint8_t sensorAddr,
                   TickType_t readIntervalMs = 50);

    /// Must be called once (after MX_I2C1_Init, before osKernelStart)
    void begin();

    /// Start/stop your periodic readings
    void start();
    void stop();

    uint16_t getPrintPressure()  const { return (uint16_t)_average[0]; }

    // map refuel->print on legacy so older code doesn’t crash
    uint16_t getRefuelPressure() const {
      return (uint16_t)_average[(_numPorts > 1) ? 1 : 0];
    }

    int32_t getPressure(uint8_t port) const {
      if (port >= _numPorts) return _average[_numPorts - 1]; // or 0
      return _average[port];
    }

    ControlSample getControlSample(uint8_t port) const {
      if (port >= _numPorts) port = _numPorts - 1;
      return _controlSample[port];
    }

    uint16_t getLatestRaw(uint8_t port) const {
      if (port >= _numPorts) port = _numPorts - 1;
      return _controlSample[port].raw;
    }

    uint16_t getAverageRaw(uint8_t port) const {
      if (port >= _numPorts) port = _numPorts - 1;
      return static_cast<uint16_t>(_average[port]);
    }

    void setValidationConfig(uint8_t port, const ValidationConfig& cfg);
    ValidationConfig getValidationConfig(uint8_t port) const;

    uint8_t numPorts() const { return _numPorts; }

    bool beginDiagnosticFocus(uint8_t port);
    void endDiagnosticFocus();

    static void I2C1_BusRecovery();

    void setSafetyRawMax(uint8_t port, uint16_t rawMax);
    void enableSafety(bool enable);
    void clearSafetyFault(uint8_t port);
    bool isSafetyFaultLatched(uint8_t port) const { return _faultLatched[port]; }

private:
    static PressureSensor* _instance;

    I2C_HandleTypeDef* _hi2c;
    uint8_t            _tcaAddr;
    uint8_t            _sensorAddr;

    GPIO_TypeDef*	   _SCLPort = GPIOB;
    uint16_t 		   _SCLPin = GPIO_PIN_8;
    GPIO_TypeDef*	   _SDAPort = GPIOB;
    uint16_t 		   _SDAPin = GPIO_PIN_9;

    static constexpr uint8_t MAX_PORTS = 2;
    uint8_t _numPorts = LC_PRESSURE_PORTS;

    static constexpr size_t NUM_READINGS = 5;
    int32_t   _readings[MAX_PORTS][NUM_READINGS];
    size_t  _readIndex[MAX_PORTS];
    int32_t   _total[MAX_PORTS];
    int32_t   _average[MAX_PORTS];

    TickType_t _readInterval;
    TaskHandle_t _taskHandle = nullptr;

    static void taskEntry(void* pv);
    void taskLoop();

    /// pick one of the two downstream ports on your TCA9548A
    HAL_StatusTypeDef selectPort(uint8_t port);

    /// do the actual I2C read of 4 bytes into raw, decode into float
    uint16_t readSensorRaw(uint8_t port);

    static constexpr uint8_t SAFETY_HITS = 3;   // consecutive samples over limit (~15 ms at 5 ms/sample)
    bool     _safetyEnabled = true;
    uint16_t _safetyRawMax[MAX_PORTS];      // 0 => disabled for that port
    uint8_t  _overCtr[MAX_PORTS];
    bool     _faultLatched[MAX_PORTS];
    ControlSample _controlSample[MAX_PORTS];
    ValidationConfig _validationCfg[MAX_PORTS];
    uint8_t _rejectStreak[MAX_PORTS] = {0, 0};
    bool _diagnosticFocusEnabled = false;
    uint8_t _diagnosticFocusPort = 0;
};
#ifdef __cplusplus
extern "C" {
#endif

/// call once (after MX_I2C1_Init) to construct & start the FreeRTOS task
void MX_PS_Init(I2C_HandleTypeDef* hi2c,
                uint8_t tcaAddress,
                uint8_t sensorAddress);

/// (optional) if you want separate start/stop hooks
void MX_PS_Start(void);
void MX_PS_Stop(void);

#ifdef __cplusplus
}
#endif



#endif /* INC_PRESSURESENSOR_H_ */
