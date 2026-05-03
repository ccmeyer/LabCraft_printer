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
#include "task.h"

class Gripper {
public:
  static Gripper& instance();

  /** Initialize pump + valve GPIO and timers
   *  pumpPort/pumpPin: GPIO for pump control (active HIGH)
   *  valvePort/valvePin: GPIO for valve (HIGH=open grip, LOW=release)
   *  refreshPeriodTicks: how often to re-pulse pump (ticks)
   *  pulseDurationTicks: how long each pulse lasts (ticks)
   */
  void begin(GPIO_TypeDef* pumpPort, uint16_t pumpPin,
             GPIO_TypeDef* valvePort, uint16_t valvePin,
             TickType_t refreshPeriodTicks,
             TickType_t pulseDurationTicks);

  /// Open gripper (apply vacuum), then pulse pump
  void open();
  /// Close gripper (vent), then pulse pump
  void close();
  /// Immediately turn pump off (stop vacuum)
  void stopPump();
  /// Stop pump refresh
  void stopRefresh();
  /// Force gripper hardware to a safe idle state
  void forceOff();

  // ---- Runtime setters/getters (ticks) ----
  void      setRefreshPeriodTicks(TickType_t ticks);
  void      setPulseDurationTicks(TickType_t ticks);
  TickType_t getRefreshPeriodTicks() const { return _refreshPeriod; }
  TickType_t getPulseDurationTicks() const { return _pulseDuration; }

  // ---- Convenience setters/getters (ms) ----
  void     setRefreshPeriodMs(uint32_t ms);
  void     setPulseDurationMs(uint32_t ms);
  uint32_t getRefreshPeriodMs() const;
  uint32_t getPulseDurationMs() const;

  // ---- coordination helpers ----
  bool lockVacuumGate(TickType_t waitTicks);   // take the gate (Printer uses this at job start)
  void unlockVacuumGate();                     // release the gate (Printer uses this at job end)
  bool isRefreshing() const { return _isRefreshing; }



private:
  Gripper();
  static void refreshTimerCallback(TimerHandle_t xTimer);
  static void pumpOffTimerCallback(TimerHandle_t xTimer);

  static void refreshTaskEntry(void* pv);

  bool _busy = false;

  void pulsePump();

  GPIO_TypeDef* _pumpPort;
  uint16_t      _pumpPin;
  GPIO_TypeDef* _valvePort;
  uint16_t      _valvePin;

  TimerHandle_t _refreshTimer;
  TimerHandle_t _pumpOffTimer;

  TickType_t    _refreshPeriod;   // ticks
  TickType_t    _pulseDuration;   // ticks

  TaskHandle_t _callerTask = nullptr;	// For blocking the Open/Close action

  // ---- synchronization state ----
  static SemaphoreHandle_t _vacuumGate;  // binary semaphore shared with Printer
  TaskHandle_t   _refreshTask = nullptr; // worker that performs refresh pulses
  volatile bool  _refreshEnabled = false; // true while background refresh may pulse
  volatile bool  _isRefreshing = false;  // true while a refresh/open/close pulse is active
  bool           _gateHeld     = false;  // true if THIS gripper instance took the gate
};


#ifdef __cplusplus
extern "C" {
#endif

void MX_GRIPPER_Init(void);
void MX_GRIPPER_Open(void);
void MX_GRIPPER_Close(void);
void MX_GRIPPER_StopPump(void);
void MX_GRIPPER_StopRefresh(void);
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
