/*
 * Gripper.h
 *
 *  Created on: Jun 20, 2025
 *      Author: conar
 */

#ifndef INC_GRIPPER_H_
#define INC_GRIPPER_H_

#include "stm32f4xx_hal.h"
#include "FreeRTOS.h"
#include "timers.h"
#include "semphr.h"
#include "GripperRefreshPolicy.h"

class Gripper {
public:
  static constexpr uint32_t DISPENSE_COOLDOWN_MS = 3000u;

  static Gripper& instance();

  void begin(GPIO_TypeDef* pumpPort, uint16_t pumpPin,
             GPIO_TypeDef* valvePort, uint16_t valvePin,
             TickType_t refreshPeriodTicks,
             TickType_t pulseDurationTicks);

  // Explicit commands issue one pulse but never enable periodic refresh.
  void open();
  void close();
  void stopPump();
  void forceOff();

  // Deferred refresh is enabled only for a production print-profile window.
  bool enableDeferredRefresh();
  void disableDeferredRefresh();
  bool isDeferredRefreshEnabled() const;
  bool hasPendingRefresh() const;
  uint32_t remainingDispenseCooldownMs() const;

  // Printer calls this only after a successful dispense while it still owns
  // the shared gate. True transfers responsibility for releasing that gate.
  bool claimPendingRefreshAfterDispenseWithGateHeld();

  // Test/diagnostic visibility. Normal expiry reaches this through the timer.
  bool markRefreshDue();

  void      setRefreshPeriodTicks(TickType_t ticks);
  void      setPulseDurationTicks(TickType_t ticks);
  TickType_t getRefreshPeriodTicks() const { return _refreshPeriod; }
  TickType_t getPulseDurationTicks() const { return _pulseDuration; }

  void     setRefreshPeriodMs(uint32_t ms);
  void     setPulseDurationMs(uint32_t ms);
  uint32_t getRefreshPeriodMs() const;
  uint32_t getPulseDurationMs() const;
  uint32_t getPumpPulseCount() const { return _pumpPulseCount; }
  uint32_t getRefreshPulseCount() const { return _refreshPulseCount; }
  uint32_t getLastPumpPulseTickMs() const { return _lastPumpPulseTickMs; }
  uint32_t getLastClosePulseTickMs() const { return _lastClosePulseTickMs; }
  uint32_t getLastPulseCompletionTickMs() const;
  bool     isRefreshTimerArmed() const;
  bool     hasPumpPulseTelemetry() const { return _hasPumpPulseTelemetry; }
  bool     hasClosePulseTelemetry() const { return _hasClosePulseTelemetry; }

  bool lockVacuumGate(TickType_t waitTicks);
  void unlockVacuumGate();
  bool isRefreshing() const;

private:
  Gripper();
  static void refreshTimerCallback(TimerHandle_t xTimer);
  static void pumpOffTimerCallback(TimerHandle_t xTimer);

  void explicitPulse(GPIO_PinState valveState, bool resetRefreshTelemetry);
  bool beginPumpPulse(bool backgroundRefresh, bool explicitCommand);
  void completeFailedPulse(bool backgroundRefresh, bool explicitCommand);
  bool startOrResetRefreshTimer();
  void disablePolicyAfterTimerFailure(const char* operation);
  void recordPumpPulse(bool backgroundRefresh);

  GPIO_TypeDef* _pumpPort;
  uint16_t      _pumpPin;
  GPIO_TypeDef* _valvePort;
  uint16_t      _valvePin;

  TimerHandle_t _refreshTimer;
  TimerHandle_t _pumpOffTimer;

  TickType_t    _refreshPeriod;
  TickType_t    _pulseDuration;

  static SemaphoreHandle_t _vacuumGate;
  volatile bool  _isRefreshing = false;
  bool           _gateHeld = false;
  bool           _explicitCommandPulse = false;
  GripperRefreshPolicy::State _refreshPolicy{};

  volatile uint32_t _pumpPulseCount = 0;
  volatile uint32_t _refreshPulseCount = 0;
  volatile uint32_t _lastPumpPulseTickMs = 0;
  volatile uint32_t _lastClosePulseTickMs = 0;
  volatile bool     _hasPumpPulseTelemetry = false;
  volatile bool     _hasClosePulseTelemetry = false;
};

#ifdef __cplusplus
extern "C" {
#endif

void MX_GRIPPER_Init(void);
void MX_GRIPPER_Open(void);
void MX_GRIPPER_Close(void);
void MX_GRIPPER_StopPump(void);
void MX_GRIPPER_EnableDeferredRefresh(void);
void MX_GRIPPER_DisableDeferredRefresh(void);
void MX_GRIPPER_ForceOff(void);

void     MX_GRIPPER_SetRefreshPeriodMs(uint32_t ms);
void     MX_GRIPPER_SetPulseDurationMs(uint32_t ms);
uint32_t MX_GRIPPER_GetRefreshPeriodMs(void);
uint32_t MX_GRIPPER_GetPulseDurationMs(void);

BaseType_t MX_VACUUM_Lock(TickType_t waitTicks);
void       MX_VACUUM_Unlock(void);

#ifdef __cplusplus
}
#endif

#endif // INC_GRIPPER_H_
