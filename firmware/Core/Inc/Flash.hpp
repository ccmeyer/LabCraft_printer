/*
 * Flash.hpp
 *
 *  Created on: Jun 27, 2025
 *      Author: conar
 */

#ifndef INC_FLASH_HPP_
#define INC_FLASH_HPP_

#include "BoardConfig.h"
#include "FlashOutputState.h"
#include "FreeRTOS.h"
#include "stm32f4xx_hal.h"
#include "task.h"

/**
 * Flash
 *
 * Uses TIM1_CH1 (PE9) in one-pulse PWM mode to generate a single
 * hardware-timed pulse. PE9 is reclaimed as a GPIO low output whenever
 * imaging is not explicitly armed so the flash-driver input never floats.
 */

#if (LC_HAS_IMAGING == 1)
class Flash {
public:
  static constexpr uint16_t kMinPulseNs = 100u;
  static constexpr uint16_t kMaxPulseNs = 5000u;

  /**
   * Construct the singleton.
   * @param htim         must be &htim1
   * @param channel      must be TIM_CHANNEL_1
   */
  Flash(TIM_HandleTypeDef* htim,
        uint32_t            channel);
  /// Get the singleton instance
  static Flash* instance();
  static uint16_t clampPulseDurationNs(uint32_t pulseDurationNs);
  /**
   * Configure TIM1 (one‐pulse + PWM1), set the desired pulse width.
   * @param pulseTicks  count of TIM1 ticks for your 1 µs pulse
   */
  void begin(uint16_t pulseDurationNs);
  void setDurationNs(uint16_t pulseDurationNs);		//Give flash duration in microseconds

  void armOutput();
  void setSafeIdleOutput();
  void reportOutputState() const;
  void flashOnce();

  uint32_t getPulses() const { return _numPulses; }
  uint32_t getPulseDuration() const { return _pulseDurationNs; }
  bool isOutputArmed() const { return FlashOutputState::isArmedOutput(_outputState); }
  const char* getOutputModeToken() const { return FlashOutputState::modeToken(_outputState.mode); }


//private:
//  void configureTimer();
//
//  void onTrigger();
//
//  TIM_HandleTypeDef* _htim;
//  uint32_t           _channel;
//  uint32_t			 _pulseDurationNs;
//  uint32_t           _pulseTicks;
//  uint16_t			 _ticksPerUs;
//  uint32_t			 _numPulses;
//
//  static Flash*      _instance;

private:
  void configureTimer();
  void configureOutputPinForTimer();
  void configureOutputPinForSafeIdle();
  void logOutputState(const char* prefix) const;

//  void onTrigger();

  TIM_HandleTypeDef* _htim;
  uint32_t           _channel;
  uint32_t			 _pulseDurationNs = 0;
  uint32_t           _pulseTicks = 0;
  uint32_t			 _timerHz = 0;
  uint32_t			 _numPulses = 0;
  FlashOutputState::State _outputState{};

  static Flash*      _instance;
};


#else
// Legacy stub: safe no-op, getters return 0.
class Flash {
public:
  static Flash* instance() { static Flash f; return &f; }
  static uint16_t clampPulseDurationNs(uint32_t pulseDurationNs) {
    if (pulseDurationNs < 100u) return 100u;
    if (pulseDurationNs > 5000u) return 5000u;
    return static_cast<uint16_t>(pulseDurationNs);
  }
  void begin(uint16_t) {}
  void setDurationNs(uint16_t) {}
  void armOutput() {}
  void setSafeIdleOutput() {}
  void reportOutputState() const {}
  void flashOnce() {}
  uint32_t getPulses() const { return 0; }
  uint32_t getPulseDuration() const { return 0; }
  bool isOutputArmed() const { return false; }
  const char* getOutputModeToken() const { return "safe_idle"; }
private:
  Flash() = default;
};

#endif
#endif // INC_FLASH_HPP_
