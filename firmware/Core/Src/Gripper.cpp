/*
 * Gripper.cpp
 *
 *  Created on: Jun 20, 2025
 *      Author: conar
 */

#include "Gripper.h"
#include "Orchestrator.h"
#include "FreeRTOS.h"
#include "timers.h"
#include "task.h"
#include "event_groups.h"
#include "semphr.h"

static void EXTI8_SoftwareTrigger(void)
{
    EXTI->PR = (1u<<8);         // clear pending
    EXTI->SWIER |= (1u<<8);     // software trigger EXTI8
}

// singleton
Gripper& Gripper::instance() {
  static Gripper g;
  return g;
}

SemaphoreHandle_t Gripper::_vacuumGate = nullptr;

Gripper::Gripper()
  : _pumpPort(nullptr), _pumpPin(0),
    _valvePort(nullptr), _valvePin(0),
    _refreshTimer(nullptr), _pumpOffTimer(nullptr),
    _refreshPeriod(0), _pulseDuration(0), _callerTask(nullptr),
    _refreshTask(nullptr), _refreshEnabled(false), _isRefreshing(false),
    _gateHeld(false)
{}

void Gripper::begin(GPIO_TypeDef* pumpPort, uint16_t pumpPin,
                    GPIO_TypeDef* valvePort, uint16_t valvePin,
                    TickType_t refreshPeriodTicks,
                    TickType_t pulseDurationTicks)
{
  _pumpPort       = pumpPort;   _pumpPin   = pumpPin;
  _valvePort      = valvePort;  _valvePin  = valvePin;
  _refreshPeriod  = refreshPeriodTicks;
  _pulseDuration  = pulseDurationTicks;
  _busy = false;
  _refreshEnabled = false;

  // --- GPIO setup ---
  __HAL_RCC_GPIOD_CLK_ENABLE();
  GPIO_InitTypeDef gi = {};
  gi.Pin   = _pumpPin;
  gi.Mode  = GPIO_MODE_OUTPUT_PP;
  gi.Pull  = GPIO_NOPULL;
  gi.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(_pumpPort, &gi);
  HAL_GPIO_WritePin(_pumpPort, _pumpPin, GPIO_PIN_RESET);

  __HAL_RCC_GPIOA_CLK_ENABLE();
  gi.Pin = _valvePin;
  HAL_GPIO_Init(_valvePort, &gi);
  HAL_GPIO_WritePin(_valvePort, _valvePin, GPIO_PIN_RESET);

  // --- create vacuum gate if not yet created (initially AVAILABLE)
  if (_vacuumGate == nullptr) {
    _vacuumGate = xSemaphoreCreateBinary();
    configASSERT(_vacuumGate != nullptr);
    xSemaphoreGive(_vacuumGate);
  }

  // --- Timers (do NOT start refresh yet) ---
  _refreshTimer = xTimerCreate(
    "GripRef",
    _refreshPeriod,        // ticks (auto-reload)
    pdTRUE,
    this,
    Gripper::refreshTimerCallback
  );

  _pumpOffTimer = xTimerCreate(
    "GripOff",
    _pulseDuration,        // ticks (one-shot)
    pdFALSE,
    this,
    Gripper::pumpOffTimerCallback
  );

  // --- create refresh worker task
  xTaskCreate(Gripper::refreshTaskEntry, "GRP_REFR", 256, this,
              tskIDLE_PRIORITY + 1, &_refreshTask);
}

// --- generic helpers
bool Gripper::lockVacuumGate(TickType_t waitTicks) {
  if (_vacuumGate == nullptr) return false;
  if (xSemaphoreTake(_vacuumGate, waitTicks) == pdTRUE) {
    // NOTE: Only set _gateHeld for gripper-owned sections.
    // Printer takes the gate too, but it WON'T set _gateHeld.
    return true;
  }
  return false;
}

void Gripper::unlockVacuumGate() {
  if (_vacuumGate) {
    xSemaphoreGive(_vacuumGate);
  }
}

void Gripper::open() {
  if (_busy) return;        // simple guard; orchestrator should serialize
  _busy = true;

  // --- block until we own the vacuum window
  if (!lockVacuumGate(portMAX_DELAY)) {
    _busy = false;
    return;
  }
  _gateHeld = true;
  _isRefreshing = true;
  _refreshEnabled = true;

  EXTI8_SoftwareTrigger();
  // start refreshing from now on
  if (_refreshTimer) {
    xTimerStart(_refreshTimer, 0);
  }

  // apply vacuum
  HAL_GPIO_WritePin(_valvePort, _valvePin, GPIO_PIN_SET);
  // turn pump on
  HAL_GPIO_WritePin(_pumpPort, _pumpPin, GPIO_PIN_SET);
  // schedule pump off
  xTimerStart(_pumpOffTimer, 0);
}


void Gripper::close() {
  if (_busy) return;        // simple guard; orchestrator should serialize
  _busy = true;

  // --- block until we own the vacuum window
  if (!lockVacuumGate(portMAX_DELAY)) {
    _busy = false;
    return;
  }
  _gateHeld = true;
  _isRefreshing = true;
  _refreshEnabled = true;

  // start refreshing from now on
  if (_refreshTimer) {
    xTimerStart(_refreshTimer, 0);
  }

  // vent (valve low)
  HAL_GPIO_WritePin(_valvePort, _valvePin, GPIO_PIN_RESET);
  // turn pump on
  HAL_GPIO_WritePin(_pumpPort, _pumpPin, GPIO_PIN_SET);
  // schedule pump off
  xTimerStart(_pumpOffTimer, 0);
}


void Gripper::stopPump() {
  HAL_GPIO_WritePin(_pumpPort, _pumpPin, GPIO_PIN_RESET);
}

void Gripper::stopRefresh() {
  _refreshEnabled = false;
  if (_refreshTimer) {
    xTimerStop(_refreshTimer, 0);
  }
  HAL_GPIO_WritePin(_pumpPort, _pumpPin, GPIO_PIN_RESET);
}

void Gripper::forceOff() {
  _refreshEnabled = false;
  if (_refreshTimer) {
    xTimerStop(_refreshTimer, 0);
  }
  if (_pumpOffTimer) {
    xTimerStop(_pumpOffTimer, 0);
  }
  if (_pumpPort != nullptr) {
    HAL_GPIO_WritePin(_pumpPort, _pumpPin, GPIO_PIN_RESET);
  }
  if (_valvePort != nullptr) {
    HAL_GPIO_WritePin(_valvePort, _valvePin, GPIO_PIN_RESET);
  }

  _isRefreshing = false;
  _busy = false;
  if (_gateHeld && _vacuumGate) {
    _gateHeld = false;
    xSemaphoreGive(_vacuumGate);
  } else {
    _gateHeld = false;
  }
}

// ==== runtime setters/getters ====

void Gripper::setRefreshPeriodTicks(TickType_t ticks) {
  _refreshPeriod = ticks;
  if (_refreshTimer) {
    BaseType_t wasActive = xTimerIsTimerActive(_refreshTimer);
    xTimerChangePeriod(_refreshTimer, ticks, 0);  // this (re)starts…
    if (!wasActive) {
      xTimerStop(_refreshTimer, 0);              // …so stop to preserve state
    }
  }
}

void Gripper::setPulseDurationTicks(TickType_t ticks) {
  _pulseDuration = ticks;
  if (_pumpOffTimer) {
    BaseType_t wasActive = xTimerIsTimerActive(_pumpOffTimer);
    xTimerChangePeriod(_pumpOffTimer, ticks, 0);
    if (!wasActive) {
      xTimerStop(_pumpOffTimer, 0);
    }
  }
}

void Gripper::setRefreshPeriodMs(uint32_t ms) {
  setRefreshPeriodTicks(pdMS_TO_TICKS(ms));
}

void Gripper::setPulseDurationMs(uint32_t ms) {
  setPulseDurationTicks(pdMS_TO_TICKS(ms));
}

uint32_t Gripper::getRefreshPeriodMs() const {
  return (uint32_t)(_refreshPeriod * portTICK_PERIOD_MS);
}

uint32_t Gripper::getPulseDurationMs() const {
  return (uint32_t)(_pulseDuration * portTICK_PERIOD_MS);
}


// ==== private ====

//void Gripper::refreshTimerCallback(TimerHandle_t) {
//  // just pulse the pump again
//  Gripper::instance().pulsePump();
//}

// do NOT pulse in the timer callback; just notify the worker task
void Gripper::refreshTimerCallback(TimerHandle_t xTimer) {
  Gripper* self = static_cast<Gripper*>(pvTimerGetTimerID(xTimer));
  if (self && self->_refreshTask && self->_refreshEnabled) {
    // coalesces if multiple periods elapse
    xTaskNotifyGive(self->_refreshTask);
  }
}

// Refresh worker (runs in task context; can block on semaphore)
void Gripper::refreshTaskEntry(void* pv) {
  auto* self = static_cast<Gripper*>(pv);
  for (;;) {
    // wait for a refresh period tick
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

    // if already in a refresh pulse (open/close/previous refresh), skip
    if (!self->_refreshEnabled || self->_isRefreshing) {
      continue;
    }

    // Take the vacuum window; will block if a print job is active
    if (!self->lockVacuumGate(portMAX_DELAY)) {
      continue; // unexpected, but safe to skip
    }
    if (!self->_refreshEnabled) {
      self->unlockVacuumGate();
      continue;
    }
    self->_gateHeld     = true;
    self->_isRefreshing = true;

    // Perform the pulse
    self->pulsePump();
    // Gate is released later by pumpOffTimerCallback
  }
}

void Gripper::pumpOffTimerCallback(TimerHandle_t) {
  auto &g = Gripper::instance();
  // turn pump off
  HAL_GPIO_WritePin(g._pumpPort, g._pumpPin, GPIO_PIN_RESET);

  // signal done to orchestrator (timer callback runs in daemon task, not ISR)
  EventGroupHandle_t eg = Orchestrator::getDoneEvents();
  if (eg) {
    xEventGroupSetBits(eg, BIT_GRIPPER_DONE);
  }

  // Mark refresh complete and release the vacuum gate if we own it
  g._isRefreshing = false;
  if (g._gateHeld && g._vacuumGate) {
    g._gateHeld = false;
    xSemaphoreGive(g._vacuumGate);
  }

  g._busy = false;
}

void Gripper::pulsePump() {
  HAL_GPIO_WritePin(_pumpPort, _pumpPin, GPIO_PIN_SET);
  xTimerStart(_pumpOffTimer, 0);
}

// ==== C API wrappers ====
extern "C" {

void MX_GRIPPER_Init(void) {
  // pump=PD13, valve=PA8, refresh=30000ms, pulse=800ms
  Gripper::instance().begin(
    GPIOD, GPIO_PIN_13,
    GPIOA, GPIO_PIN_8,
    pdMS_TO_TICKS(60000),
    pdMS_TO_TICKS(800)
  );
}

void MX_GRIPPER_Open(void)  { Gripper::instance().open(); }
void MX_GRIPPER_Close(void) { Gripper::instance().close(); }
void MX_GRIPPER_StopRefresh(void) { Gripper::instance().stopRefresh(); }
void MX_GRIPPER_StopPump(void)    { Gripper::instance().stopPump(); }
void MX_GRIPPER_ForceOff(void)    { Gripper::instance().forceOff(); }

// New: Orchestrator-facing setters/getters (ms)
void     MX_GRIPPER_SetRefreshPeriodMs(uint32_t ms) { Gripper::instance().setRefreshPeriodMs(ms); }
void     MX_GRIPPER_SetPulseDurationMs(uint32_t ms) { Gripper::instance().setPulseDurationMs(ms); }
uint32_t MX_GRIPPER_GetRefreshPeriodMs(void)        { return Gripper::instance().getRefreshPeriodMs(); }
uint32_t MX_GRIPPER_GetPulseDurationMs(void)        { return Gripper::instance().getPulseDurationMs(); }

BaseType_t MX_VACUUM_Lock(TickType_t waitTicks) {
  return Gripper::instance().lockVacuumGate(waitTicks) ? pdTRUE : pdFALSE;
}
void MX_VACUUM_Unlock(void) {
  Gripper::instance().unlockVacuumGate();
}

} // extern "C"
