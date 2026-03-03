/*
 * PressureSensor.cpp
 *
 *  Created on: Jun 17, 2025
 *      Author: conar
 */

#include "PressureSensor.h"
#include "PressureRegulator.h"
#include "PressureRegulatorMath.h"
#include "Logger.h"
#include "FreeRTOS.h"
#include "task.h"
#include "WatchdogSupervisor.h"

#include <cstring>

extern "C" {
  #include "stm32f4xx_hal_i2c.h"    // <-- this declares HAL_I2C_Init(I2C_HandleTypeDef *hi2c)
}

namespace {
constexpr uint32_t kPressureI2cTimeoutMs = 20u;
}


// singleton init
PressureSensor* PressureSensor::_instance = nullptr;

PressureSensor::PressureSensor(I2C_HandleTypeDef* hi2c,
                               uint8_t tcaAddr,
                               uint8_t sensorAddr,
                               TickType_t readIntervalMs)
  : _hi2c(hi2c),
    _tcaAddr(tcaAddr),
    _sensorAddr(sensorAddr),
    _readInterval(pdMS_TO_TICKS(readIntervalMs))
{

  // zero‐fill our smoothing buffers
  std::memset(_readings, 0, sizeof(_readings));
  _readIndex[0] = _readIndex[1] = 0;
  _total[0] = _total[1] = 0;
  _average[0] = _average[1] = 0;

  // Safety defaults: disabled until user sets a limit
  _safetyRawMax[0] = _safetyRawMax[1] = 0;
  _overCtr[0] = _overCtr[1] = 0;
  _faultLatched[0] = _faultLatched[1] = false;
  for (uint8_t i = 0; i < MAX_PORTS; ++i) {
    _controlSample[i].raw = 0;
    _controlSample[i].avg = 0;
    _controlSample[i].previousRaw = 0;
    _controlSample[i].tickMs = 0;
    _controlSample[i].valid = false;
    _controlSample[i].lastReadRejected = false;
    _controlSample[i].rejectReason = RejectReason::None;
    _validationCfg[i] = ValidationConfig{};
  }
}

PressureSensor* PressureSensor::instance() {
  return _instance;
}

// call this once, right after MX_I2C#_Init() but before any I²C traffic
void PressureSensor::I2C1_BusRecovery()
{
  // fetch the pins from your singleton
  auto *self = PressureSensor::instance();

  HAL_I2C_DeInit(self->_hi2c);
  // 1) Temporarily reconfigure SCL & SDA as open‐drain GPIOs:
  GPIO_InitTypeDef gpio = {};
  gpio.Mode  = GPIO_MODE_OUTPUT_OD;
  gpio.Pull  = GPIO_PULLUP;
  gpio.Speed = GPIO_SPEED_FREQ_HIGH;


  // change these to the pins your I²C1 uses:
  gpio.Pin  = self->_SCLPin;
	HAL_GPIO_Init(self->_SCLPort, &gpio);

	gpio.Pin  = self->_SDAPin;
	HAL_GPIO_Init(self->_SDAPort, &gpio);

	// 2) Clock SCL at least 9× to free SDA
	for (int i = 0; i < 9; ++i) {
	  HAL_GPIO_WritePin(self->_SCLPort, self->_SCLPin, GPIO_PIN_SET);
	  vTaskDelay(1);
	  HAL_GPIO_WritePin(self->_SCLPort, self->_SCLPin, GPIO_PIN_RESET);
	  vTaskDelay(1);
	}

	// 3) Generate STOP: SDA high when SCL high
	HAL_GPIO_WritePin(self->_SDAPort, self->_SDAPin, GPIO_PIN_RESET);
	HAL_GPIO_WritePin(self->_SCLPort, self->_SCLPin, GPIO_PIN_SET);
	vTaskDelay(1);
	HAL_GPIO_WritePin(self->_SDAPort, self->_SDAPin, GPIO_PIN_SET);
	vTaskDelay(1);
  // 4) Re-init pins back to AF-OD for I2C
  //    (re-call CubeMX-generated init)
//  MX_I2C1_Init();
  HAL_I2C_Init(self->_hi2c);
}

void PressureSensor::begin() {
  // nothing special on I2C side—MX_I2C#_Init() was run by CubeMX
  _instance = this;

  // now create our FreeRTOS task:
  xTaskCreate(
    taskEntry,
    "Pressure",
    256,
    this,
    tskIDLE_PRIORITY+1,
    &_taskHandle
  );
}

void PressureSensor::start() {
  // let the task run
  vTaskResume(_taskHandle);
}

void PressureSensor::stop() {
  vTaskSuspend(_taskHandle);
}

void PressureSensor::taskEntry(void* pv) {
  // unwrap pointer and loop forever
  static_cast<PressureSensor*>(pv)->taskLoop();
  vTaskDelete(nullptr);
}

void PressureSensor::taskLoop() {
    uint8_t port = 0;
    Watchdog_EnableTask(CRASH_TASK_PRESSURE);

    // run bus-recovery once up front:
    I2C1_BusRecovery();     // drain off any stuck bus low


    // skip the first 10 reads
    for (int i = 0; i < 10; ++i) { vTaskDelay(_readInterval); }

    for (;;) {
        Watchdog_CheckIn(CRASH_TASK_PRESSURE);
//    	Logger::instance()->log("TEST %u\r\n", port);
        // 1) switch the I²C multiplexer
    	HAL_StatusTypeDef st;
        st = selectPort(port);
    	if (st != HAL_OK) {
    		I2C1_BusRecovery();
    		vTaskDelay(pdMS_TO_TICKS(2)); // small backoff
    	  continue;
    	}

        // 2) grab a raw reading and validate it for control use
        uint16_t raw = readSensorRaw(port);
        PressureRegulatorMath::ValidationConfig cfg{};
        cfg.minRaw = _validationCfg[port].minRaw;
        cfg.maxRaw = _validationCfg[port].maxRaw;
        cfg.maxStepPerSample = _validationCfg[port].maxStepPerSample;
        cfg.maxConsecutiveRejects = _validationCfg[port].maxConsecutiveRejects;
        const auto validation = PressureRegulatorMath::validatePressureSample(
            _controlSample[port].raw,
            raw,
            _rejectStreak[port],
            cfg);

        uint16_t committedRaw = _controlSample[port].raw;
        if (validation.accept) {
          committedRaw = validation.committedRaw;
          _rejectStreak[port] = 0;
        } else {
          _rejectStreak[port]++;
          _controlSample[port].rejectCount++;
          if (validation.reason == PressureRegulatorMath::PressureRejectReason::RailLow ||
              validation.reason == PressureRegulatorMath::PressureRejectReason::RailHigh) {
            _controlSample[port].railRejectCount++;
          } else if (validation.reason == PressureRegulatorMath::PressureRejectReason::Spike) {
            _controlSample[port].spikeRejectCount++;
          }
        }

        _controlSample[port].previousRaw = _controlSample[port].raw;
        _controlSample[port].raw = committedRaw;
        _controlSample[port].valid = true;
        _controlSample[port].lastReadRejected = !validation.accept;
        _controlSample[port].tickMs = HAL_GetTick();
        switch (validation.reason) {
          case PressureRegulatorMath::PressureRejectReason::RailLow:
            _controlSample[port].rejectReason = RejectReason::RailLow;
            break;
          case PressureRegulatorMath::PressureRejectReason::RailHigh:
            _controlSample[port].rejectReason = RejectReason::RailHigh;
            break;
          case PressureRegulatorMath::PressureRejectReason::Spike:
            _controlSample[port].rejectReason = RejectReason::Spike;
            break;
          default:
            _controlSample[port].rejectReason = RejectReason::None;
            break;
        }

        // 3) smooth the committed value in the circular buffer for status/UI
        _total[port] -= _readings[port][_readIndex[port]];
        _readings[port][_readIndex[port]] = (int32_t)committedRaw;
        _total[port] += (int32_t)committedRaw;
        _readIndex[port] = (_readIndex[port] + 1) % NUM_READINGS;
        _average[port] = _total[port] / NUM_READINGS;
        _controlSample[port].avg = static_cast<uint16_t>(_average[port]);

        if (_safetyEnabled && _safetyRawMax[port] != 0 && !_faultLatched[port]) {
          if (_average[port] > (int32_t)_safetyRawMax[port]) {
            if (++_overCtr[port] >= SAFETY_HITS) {
              _overCtr[port] = 0;
              _faultLatched[port] = true;

              Logger::instance()->log("[PS] Over-pressure trip on port %u: avg=%ld, limit=%u\r\n",
                                      (unsigned)port, (long)_average[port], (unsigned)_safetyRawMax[port]);

              // Route the safety home onto the regulator task so the pressure task
              // does not block long enough to starve the watchdog.
              if (port == 0) {
                PressureRegulator::regP().requestSafetyHome();
              } else {
                PressureRegulator::regR().requestSafetyHome();
              }
            }
          } else {
            _overCtr[port] = 0;
          }
        }

        // 4) next port (works for 1 or 2)
        port++;
        if (port >= _numPorts) port = 0;
        // 5) delay before the next read
        vTaskDelay(_readInterval);
    }
}

HAL_StatusTypeDef PressureSensor::selectPort(uint8_t port) {
#if LC_HAS_TCA9548A
  uint8_t b = uint8_t(1u << port);
  return HAL_I2C_Master_Transmit(_hi2c, _tcaAddr << 1, &b, 1, kPressureI2cTimeoutMs);
#else
  (void)port;
  return HAL_OK;
#endif
}

uint16_t PressureSensor::readSensorRaw(uint8_t port) {
  uint8_t buf[4];
  HAL_StatusTypeDef st = HAL_I2C_Master_Receive(_hi2c, _sensorAddr << 1, buf, 4, kPressureI2cTimeoutMs);
  if (st != HAL_OK) {
    I2C1_BusRecovery();
    return _controlSample[port].raw;
  }
  uint8_t p1 = buf[0], p2 = buf[1];
  uint16_t raw = (uint16_t(p1 & 0x3F) << 8) | p2;
  return raw;
}

void PressureSensor::setSafetyRawMax(uint8_t port, uint16_t rawMax) {
  if (port > 1) return;
  taskENTER_CRITICAL();
  _safetyRawMax[port] = rawMax;        // 0 disables for that port
  _overCtr[port] = 0;
  taskEXIT_CRITICAL();
}

void PressureSensor::enableSafety(bool enable) {
  taskENTER_CRITICAL();
  _safetyEnabled = enable;
  _overCtr[0] = _overCtr[1] = 0;
  taskEXIT_CRITICAL();
}

void PressureSensor::clearSafetyFault(uint8_t port) {
  if (port > 1) return;
  taskENTER_CRITICAL();
  _faultLatched[port] = false;
  _overCtr[port] = 0;
  taskEXIT_CRITICAL();
}

void PressureSensor::setValidationConfig(uint8_t port, const ValidationConfig& cfg) {
  if (port >= MAX_PORTS) return;
  taskENTER_CRITICAL();
  _validationCfg[port] = cfg;
  taskEXIT_CRITICAL();
}

PressureSensor::ValidationConfig PressureSensor::getValidationConfig(uint8_t port) const {
  if (port >= MAX_PORTS) port = MAX_PORTS - 1;
  return _validationCfg[port];
}

extern "C" {

void MX_PS_Init(I2C_HandleTypeDef* hi2c,
                uint8_t tcaAddress,
                uint8_t sensorAddress)
{
    // Construct the singleton and begin its FreeRTOS task
    static PressureSensor ps(hi2c, tcaAddress, sensorAddress, 5);
    ps.begin();
    ps.setSafetyRawMax(0, 8000);
#if LC_PRESSURE_PORTS > 1
    ps.setSafetyRawMax(1, 8000);
#endif
    ps.enableSafety(true);


}

void MX_PS_ClearSafetyFault(uint8_t port) {
  if (PressureSensor::instance()) PressureSensor::instance()->clearSafetyFault(port);
}

} // extern "C"

