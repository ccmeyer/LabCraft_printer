/*
 * Gripper.cpp
 *
 *  Created on: Jun 20, 2025
 *      Author: conar
 */

#include "Gripper.h"
#include "Logger.h"
#include "Orchestrator.h"
#include "event_groups.h"

Gripper& Gripper::instance() {
  static Gripper g;
  return g;
}

SemaphoreHandle_t Gripper::_vacuumGate = nullptr;

Gripper::Gripper()
  : _pumpPort(nullptr), _pumpPin(0),
    _valvePort(nullptr), _valvePin(0),
    _refreshTimer(nullptr), _pumpOffTimer(nullptr),
    _refreshPeriod(0), _pulseDuration(0)
{}

void Gripper::begin(GPIO_TypeDef* pumpPort, uint16_t pumpPin,
                    GPIO_TypeDef* valvePort, uint16_t valvePin,
                    TickType_t refreshPeriodTicks,
                    TickType_t pulseDurationTicks)
{
  _pumpPort = pumpPort;
  _pumpPin = pumpPin;
  _valvePort = valvePort;
  _valvePin = valvePin;
  _refreshPeriod = refreshPeriodTicks;
  _pulseDuration = pulseDurationTicks;
  _isRefreshing = false;
  _gateHeld = false;
  _explicitCommandPulse = false;
  GripperRefreshPolicy::initialize(_refreshPolicy);

  __HAL_RCC_GPIOD_CLK_ENABLE();
  GPIO_InitTypeDef gi = {};
  gi.Pin = _pumpPin;
  gi.Mode = GPIO_MODE_OUTPUT_PP;
  gi.Pull = GPIO_NOPULL;
  gi.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(_pumpPort, &gi);
  HAL_GPIO_WritePin(_pumpPort, _pumpPin, GPIO_PIN_RESET);

  __HAL_RCC_GPIOA_CLK_ENABLE();
  gi.Pin = _valvePin;
  HAL_GPIO_Init(_valvePort, &gi);
  HAL_GPIO_WritePin(_valvePort, _valvePin, GPIO_PIN_RESET);

  if (_vacuumGate == nullptr) {
    _vacuumGate = xSemaphoreCreateBinary();
    configASSERT(_vacuumGate != nullptr);
    xSemaphoreGive(_vacuumGate);
  }

  // Deferred expiry is one-shot. It records pending work only.
  _refreshTimer = xTimerCreate(
      "GripRef", _refreshPeriod, pdFALSE, this,
      Gripper::refreshTimerCallback);
  _pumpOffTimer = xTimerCreate(
      "GripOff", _pulseDuration, pdFALSE, this,
      Gripper::pumpOffTimerCallback);
  configASSERT(_refreshTimer != nullptr);
  configASSERT(_pumpOffTimer != nullptr);
}

bool Gripper::lockVacuumGate(TickType_t waitTicks) {
  return _vacuumGate != nullptr &&
         xSemaphoreTake(_vacuumGate, waitTicks) == pdTRUE;
}

void Gripper::unlockVacuumGate() {
  if (_vacuumGate != nullptr) {
    xSemaphoreGive(_vacuumGate);
  }
}

void Gripper::open() {
  explicitPulse(GPIO_PIN_SET, false);
}

void Gripper::close() {
  explicitPulse(GPIO_PIN_RESET, true);
}

void Gripper::explicitPulse(GPIO_PinState valveState,
                            bool resetRefreshTelemetry) {
  // Waiting here is intentional: an explicit command queued behind an active
  // deferred pulse must eventually complete and signal the orchestrator.
  if (!lockVacuumGate(portMAX_DELAY)) {
    EventGroupHandle_t eg = Orchestrator::getDoneEvents();
    if (eg != nullptr) xEventGroupSetBits(eg, BIT_GRIPPER_DONE);
    return;
  }

  _gateHeld = true;
  if (resetRefreshTelemetry) {
    _refreshPulseCount = 0;
    _lastClosePulseTickMs = HAL_GetTick();
    _hasClosePulseTelemetry = true;
  }
  HAL_GPIO_WritePin(_valvePort, _valvePin, valveState);
  if (!beginPumpPulse(false, true)) {
    completeFailedPulse(false, true);
  }
}

bool Gripper::beginPumpPulse(bool backgroundRefresh, bool explicitCommand) {
  // Arm pump-off before energizing the pump. A timer queue failure can then
  // never leave the pump stuck on.
  if (_pumpOffTimer == nullptr ||
      xTimerChangePeriod(_pumpOffTimer, _pulseDuration, 0) != pdPASS) {
    if (_pumpPort != nullptr) {
      HAL_GPIO_WritePin(_pumpPort, _pumpPin, GPIO_PIN_RESET);
    }
    Logger::instance()->log("[Gripper] pump-off timer arm failed\r\n");
    return false;
  }

  taskENTER_CRITICAL();
  _isRefreshing = true;
  _explicitCommandPulse = explicitCommand;
  taskEXIT_CRITICAL();
  recordPumpPulse(backgroundRefresh);
  HAL_GPIO_WritePin(_pumpPort, _pumpPin, GPIO_PIN_SET);
  return true;
}

void Gripper::completeFailedPulse(bool backgroundRefresh,
                                  bool explicitCommand) {
  taskENTER_CRITICAL();
  _isRefreshing = false;
  _explicitCommandPulse = false;
  if (backgroundRefresh) {
    (void)GripperRefreshPolicy::markRefreshDue(_refreshPolicy);
  }
  taskEXIT_CRITICAL();

  if (_gateHeld && _vacuumGate != nullptr) {
    _gateHeld = false;
    xSemaphoreGive(_vacuumGate);
  }
  if (explicitCommand) {
    EventGroupHandle_t eg = Orchestrator::getDoneEvents();
    if (eg != nullptr) xEventGroupSetBits(eg, BIT_GRIPPER_DONE);
  }
}

void Gripper::stopPump() {
  if (_pumpPort != nullptr) {
    HAL_GPIO_WritePin(_pumpPort, _pumpPin, GPIO_PIN_RESET);
  }
}

bool Gripper::startOrResetRefreshTimer() {
  if (_refreshTimer == nullptr ||
      xTimerChangePeriod(_refreshTimer, _refreshPeriod, 0) != pdPASS) {
    disablePolicyAfterTimerFailure("start/reset");
    return false;
  }
  return true;
}

void Gripper::disablePolicyAfterTimerFailure(const char* operation) {
  taskENTER_CRITICAL();
  (void)GripperRefreshPolicy::disable(_refreshPolicy);
  taskEXIT_CRITICAL();
  Logger::instance()->log("[Gripper] refresh timer %s failed; deferred mode disabled\r\n",
                          operation != nullptr ? operation : "command");
}

bool Gripper::enableDeferredRefresh() {
  taskENTER_CRITICAL();
  (void)GripperRefreshPolicy::enableDeferred(_refreshPolicy);
  taskEXIT_CRITICAL();
  return startOrResetRefreshTimer();
}

void Gripper::disableDeferredRefresh() {
  taskENTER_CRITICAL();
  (void)GripperRefreshPolicy::disable(_refreshPolicy);
  taskEXIT_CRITICAL();
  if (_refreshTimer != nullptr && xTimerStop(_refreshTimer, 0) != pdPASS) {
    disablePolicyAfterTimerFailure("stop");
  }
}

bool Gripper::isDeferredRefreshEnabled() const {
  taskENTER_CRITICAL();
  const bool enabled = GripperRefreshPolicy::isDeferred(_refreshPolicy);
  taskEXIT_CRITICAL();
  return enabled;
}

bool Gripper::hasPendingRefresh() const {
  taskENTER_CRITICAL();
  const bool pending = GripperRefreshPolicy::hasPending(_refreshPolicy);
  taskEXIT_CRITICAL();
  return pending;
}

bool Gripper::markRefreshDue() {
  taskENTER_CRITICAL();
  const bool marked = GripperRefreshPolicy::markRefreshDue(_refreshPolicy);
  taskEXIT_CRITICAL();
  return marked;
}

uint32_t Gripper::remainingDispenseCooldownMs() const {
  taskENTER_CRITICAL();
  const uint32_t remaining = GripperRefreshPolicy::remainingDispenseCooldownMs(
      _refreshPolicy, HAL_GetTick(), DISPENSE_COOLDOWN_MS);
  taskEXIT_CRITICAL();
  return remaining;
}

uint32_t Gripper::getLastPulseCompletionTickMs() const {
  taskENTER_CRITICAL();
  const uint32_t completion = _refreshPolicy.lastPulseCompletionMs;
  taskEXIT_CRITICAL();
  return completion;
}

bool Gripper::isRefreshTimerArmed() const {
  return _refreshTimer != nullptr &&
         xTimerIsTimerActive(_refreshTimer) != pdFALSE;
}

bool Gripper::isRefreshing() const {
  taskENTER_CRITICAL();
  const bool refreshing = _isRefreshing;
  taskEXIT_CRITICAL();
  return refreshing;
}

bool Gripper::claimPendingRefreshAfterDispenseWithGateHeld() {
  taskENTER_CRITICAL();
  const bool claimed =
      GripperRefreshPolicy::claimPendingAfterDispense(_refreshPolicy);
  taskEXIT_CRITICAL();
  if (!claimed) {
    return false;
  }

  if (_refreshTimer != nullptr && xTimerIsTimerActive(_refreshTimer) != pdFALSE &&
      xTimerStop(_refreshTimer, 0) != pdPASS) {
    disablePolicyAfterTimerFailure("stop before pulse");
    return false;
  }

  // Printer already owns the semaphore. From this point the Gripper owns the
  // responsibility to release it when the pump-off callback completes.
  _gateHeld = true;
  if (!beginPumpPulse(true, false)) {
    completeFailedPulse(true, false);
    return true;
  }
  return true;
}

void Gripper::forceOff() {
  taskENTER_CRITICAL();
  GripperRefreshPolicy::initialize(_refreshPolicy);
  _isRefreshing = false;
  _explicitCommandPulse = false;
  taskEXIT_CRITICAL();

  if (_refreshTimer != nullptr) (void)xTimerStop(_refreshTimer, 0);
  if (_pumpOffTimer != nullptr) (void)xTimerStop(_pumpOffTimer, 0);
  if (_pumpPort != nullptr) {
    HAL_GPIO_WritePin(_pumpPort, _pumpPin, GPIO_PIN_RESET);
  }
  if (_valvePort != nullptr) {
    HAL_GPIO_WritePin(_valvePort, _valvePin, GPIO_PIN_RESET);
  }
  if (_gateHeld && _vacuumGate != nullptr) {
    _gateHeld = false;
    xSemaphoreGive(_vacuumGate);
  } else {
    _gateHeld = false;
  }
}

void Gripper::setRefreshPeriodTicks(TickType_t ticks) {
  _refreshPeriod = ticks;
  if (isDeferredRefreshEnabled()) {
    (void)startOrResetRefreshTimer();
  }
}

void Gripper::setPulseDurationTicks(TickType_t ticks) {
  _pulseDuration = ticks;
}

void Gripper::setRefreshPeriodMs(uint32_t ms) {
  setRefreshPeriodTicks(pdMS_TO_TICKS(ms));
}

void Gripper::setPulseDurationMs(uint32_t ms) {
  setPulseDurationTicks(pdMS_TO_TICKS(ms));
}

uint32_t Gripper::getRefreshPeriodMs() const {
  return static_cast<uint32_t>(_refreshPeriod * portTICK_PERIOD_MS);
}

uint32_t Gripper::getPulseDurationMs() const {
  return static_cast<uint32_t>(_pulseDuration * portTICK_PERIOD_MS);
}

void Gripper::refreshTimerCallback(TimerHandle_t xTimer) {
  Gripper* self = static_cast<Gripper*>(pvTimerGetTimerID(xTimer));
  if (self != nullptr) {
    (void)self->markRefreshDue();
  }
}

void Gripper::pumpOffTimerCallback(TimerHandle_t xTimer) {
  Gripper* self = static_cast<Gripper*>(pvTimerGetTimerID(xTimer));
  if (self == nullptr) return;

  HAL_GPIO_WritePin(self->_pumpPort, self->_pumpPin, GPIO_PIN_RESET);
  const uint32_t completedMs = HAL_GetTick();
  taskENTER_CRITICAL();
  const bool explicitCommand = self->_explicitCommandPulse;
  self->_explicitCommandPulse = false;
  self->_isRefreshing = false;
  const auto directive = GripperRefreshPolicy::recordPulseCompleted(
      self->_refreshPolicy, completedMs);
  taskEXIT_CRITICAL();

  if (directive == GripperRefreshPolicy::PeriodicTimerDirective::StartOrReset) {
    (void)self->startOrResetRefreshTimer();
  }

  if (self->_gateHeld && self->_vacuumGate != nullptr) {
    self->_gateHeld = false;
    xSemaphoreGive(self->_vacuumGate);
  }
  if (explicitCommand) {
    EventGroupHandle_t eg = Orchestrator::getDoneEvents();
    if (eg != nullptr) xEventGroupSetBits(eg, BIT_GRIPPER_DONE);
  }
}

void Gripper::recordPumpPulse(bool backgroundRefresh) {
  const uint32_t nowMs = HAL_GetTick();
  _pumpPulseCount++;
  _lastPumpPulseTickMs = nowMs;
  _hasPumpPulseTelemetry = true;
  if (backgroundRefresh) {
    _refreshPulseCount++;
  }
}

extern "C" {

void MX_GRIPPER_Init(void) {
  Gripper::instance().begin(
      GPIOD, GPIO_PIN_13,
      GPIOA, GPIO_PIN_8,
      pdMS_TO_TICKS(60000),
      pdMS_TO_TICKS(800));
}

void MX_GRIPPER_Open(void) { Gripper::instance().open(); }
void MX_GRIPPER_Close(void) { Gripper::instance().close(); }
void MX_GRIPPER_StopPump(void) { Gripper::instance().stopPump(); }
void MX_GRIPPER_EnableDeferredRefresh(void) {
  (void)Gripper::instance().enableDeferredRefresh();
}
void MX_GRIPPER_DisableDeferredRefresh(void) {
  Gripper::instance().disableDeferredRefresh();
}
void MX_GRIPPER_ForceOff(void) { Gripper::instance().forceOff(); }

void MX_GRIPPER_SetRefreshPeriodMs(uint32_t ms) {
  Gripper::instance().setRefreshPeriodMs(ms);
}
void MX_GRIPPER_SetPulseDurationMs(uint32_t ms) {
  Gripper::instance().setPulseDurationMs(ms);
}
uint32_t MX_GRIPPER_GetRefreshPeriodMs(void) {
  return Gripper::instance().getRefreshPeriodMs();
}
uint32_t MX_GRIPPER_GetPulseDurationMs(void) {
  return Gripper::instance().getPulseDurationMs();
}

BaseType_t MX_VACUUM_Lock(TickType_t waitTicks) {
  return Gripper::instance().lockVacuumGate(waitTicks) ? pdTRUE : pdFALSE;
}
void MX_VACUUM_Unlock(void) {
  Gripper::instance().unlockVacuumGate();
}

} // extern "C"
