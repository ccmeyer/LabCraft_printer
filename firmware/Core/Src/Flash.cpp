/*
 * Flash.cpp
 *
 *  Created on: Jun 27, 2025
 *      Author: conar
 */
#include "BoardConfig.h"

#if (LC_HAS_IMAGING == 1)

#include "Flash.hpp"
#include "Flash.h"
#include "task.h"

// Compute actual TIM1 effective clock (accounts for APB2 prescaler x2 behavior)
static uint32_t tim1_input_hz(TIM_HandleTypeDef* htim) {
  RCC_ClkInitTypeDef cfg; uint32_t flash;
  HAL_RCC_GetClockConfig(&cfg, &flash);

  const uint32_t pclk2 = HAL_RCC_GetPCLK2Freq();
  const bool x2 = (cfg.APB2CLKDivider != RCC_HCLK_DIV1);
  const uint32_t tclk = x2 ? (pclk2 * 2u) : pclk2;

  const uint32_t psc = (uint32_t)htim->Init.Prescaler;
  return tclk / (psc + 1u);
}

//// Helper: convert ns→ticks at 180 MHz
//static uint32_t ns_to_ticks(uint16_t ns) {
//    // 180 MHz → 180 ticks per µs → 0.18 ticks/ns
//    // round to nearest tick
//    return (uint32_t)((ns * 180 + 500) / 1000);
//}

static uint32_t ns_to_ticks(uint32_t timerHz, uint16_t ns) {
  // ticks = timerHz * ns / 1e9 (rounded)
  uint64_t num = (uint64_t)timerHz * (uint64_t)ns + 500000000ULL;
  uint32_t t = (uint32_t)(num / 1000000000ULL);
  return (t < 1u) ? 1u : t;
}

// single global pointer for EXTI callback bridge
Flash* Flash::_instance = nullptr;

//Flash::Flash(TIM_HandleTypeDef* htim,
//             uint32_t            channel
//			 )
//  : _htim(htim),
//    _channel(channel),
//    _pulseTicks(0),
//	_ticksPerUs(180),
//	_numPulses(0)
//{
//  // register the singleton for the EXTI bridge
//  _instance = this;
//}

Flash::Flash(TIM_HandleTypeDef* htim,
             uint32_t            channel
			 )
  : _htim(htim),
    _channel(channel)
{
  // register the singleton for the EXTI bridge
  _instance = this;
}

Flash* Flash::instance() {
	return _instance;
}

//void Flash::begin(uint16_t pulseDurationNs) {
//    // 1) compute initial tick count (at least 1)
//    _pulseTicks = ns_to_ticks(pulseDurationNs);
//    if (_pulseTicks < 1) _pulseTicks = 1;
//
//    // 2) configure the OC channel with our initial period/compare
//    configureTimer();
//}

void Flash::begin(uint16_t pulseDurationNs) {
  _pulseDurationNs = pulseDurationNs;
  _timerHz = tim1_input_hz(_htim);
  _pulseTicks = ns_to_ticks(_timerHz, pulseDurationNs);
  // TIM1 is 16-bit; keep ARR in range: ARR = 2*ticks - 1 <= 0xFFFF
  if (_pulseTicks > 32768u) _pulseTicks = 32768u;
  configureTimer();
}

void Flash::configureTimer() {
    TIM_OC_InitTypeDef sConfigOC = {0};

    // 1) Update base timer parameters
    //    Period must be >= CCR+1 to guarantee a single compare
    _htim->Init.Period            = (_pulseTicks * 2u) - 1u;  // Set the period (time for one pulse)
    _htim->Init.CounterMode       = TIM_COUNTERMODE_UP;
    _htim->Init.ClockDivision     = TIM_CLOCKDIVISION_DIV1;
    _htim->Init.RepetitionCounter = 0;
    HAL_TIM_Base_Init(_htim);

    // 2) Re-enable one-pulse mode on EVERY reconfigure
    HAL_TIM_OnePulse_Init(_htim, TIM_OPMODE_SINGLE);

    // 3) Set up PWM1 compare value
    sConfigOC.OCMode     = TIM_OCMODE_PWM1;
    sConfigOC.Pulse      = _pulseTicks;         // CCR
    sConfigOC.OCPolarity = TIM_OCPOLARITY_LOW;
    sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
    HAL_TIM_PWM_ConfigChannel(_htim, &sConfigOC, _channel);
}

//void Flash::setDurationNs(uint16_t pulseDurationNs) {
//    // recompute tick count
//	_pulseDurationNs = pulseDurationNs;
//    uint32_t ticks = ns_to_ticks(pulseDurationNs);
//    _pulseTicks = (ticks < 1 ? 1 : ticks);
//
//    // update period & CCR for next flash
//    configureTimer();
//}

void Flash::setDurationNs(uint16_t pulseDurationNs) {
  _pulseDurationNs = pulseDurationNs;           // FIX
  if (_timerHz == 0) _timerHz = tim1_input_hz(_htim);
  _pulseTicks = ns_to_ticks(_timerHz, pulseDurationNs);
  if (_pulseTicks > 32768u) _pulseTicks = 32768u;
  configureTimer();
}


void Flash::flashOnce() {
    // 1) Reconfigure the timer so OPM is set
    configureTimer();

    // 2) Disable & clear any pending CC1/update interrupts
    __HAL_TIM_DISABLE_IT(_htim, TIM_IT_CC1);
    __HAL_TIM_CLEAR_FLAG(_htim, TIM_FLAG_CC1);
    __HAL_TIM_CLEAR_FLAG(_htim, TIM_FLAG_UPDATE);

    // 3) Reset counter & start the one‐pulse PWM
    __HAL_TIM_SET_COUNTER(_htim, 0);
    HAL_TIM_PWM_Start(_htim, _channel);
    HAL_TIM_OnePulse_Start(_htim, _channel);

    _numPulses++;
}


//------------------------------------------------------------------------------
// C wrappers for inclusion in main.c
//------------------------------------------------------------------------------

extern "C" {

/** Initialize the C++ Flash singleton. */
void MX_FLASH_Init(uint16_t pulseDurationNs) {
  // htim1 is declared by CubeMX in a C file, so we extern it here:
  extern TIM_HandleTypeDef htim1;
  // create a static instance so its lifetime is the full program
  static Flash flash(&htim1,
                     TIM_CHANNEL_1);
  flash.begin(pulseDurationNs);
}

void MX_FLASH_ONCE() {
	Flash::instance()->flashOnce();
}

} // extern "C"


#else

#include "Flash.h"
extern "C" void MX_FLASH_Init(uint16_t) {}
extern "C" void MX_FLASH_ONCE() {}

#endif

