/*
 * Heartbeat.c
 *
 *  Created on: Jan 29, 2026
 *      Author: conar
 */

#include "cmsis_os.h"
#include "stm32f4xx_hal.h"
#include "main.h"

static void HeartbeatTask(void const * argument)
{
  (void)argument;
  for (;;)
  {
    HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);
    osDelay(1000); // 4 Hz blink
  }
}

void MX_HEARTBEAT_Start(void)
{
  osThreadDef(Heartbeat, HeartbeatTask, osPriorityLow, 0, 128);
  osThreadCreate(osThread(Heartbeat), NULL);
}
