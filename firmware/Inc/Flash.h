/*
 * Flash.h
 *
 *  Created on: Jun 27, 2025
 *      Author: conar
 */

#ifndef FLASH_H
#define FLASH_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Initialize the hardware flash driver.
 * Must be called after HAL_Init(), SystemClock_Config(),
 * MX_GPIO_Init() and MX_TIM1_Init().
 *
 * @param pulseTicks  Number of TIM1 ticks for a 1 µs flash.
 *                    (e.g. at 180 MHz timer clock, PSC=0 → tick≈5.56 ns,
 *                    so pulseTicks≈180)
 */
void MX_FLASH_Init(uint16_t pulseDurationNs);

///**
// * Call this from your C HAL_GPIO_EXTI_Callback whenever EXTI8 fires:
// *
// * void HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin) {
// *   FLASH_TriggerCallback(GPIO_Pin);
// * }
// *
// * @param GPIO_Pin  the pin that triggered the EXTI (expect GPIO_PIN_8)
// */
//void MX_FLASH_TriggerCallback(uint16_t GPIO_Pin);

void MX_FLASH_ONCE();

#ifdef __cplusplus
}
#endif

#endif // FLASH_H
