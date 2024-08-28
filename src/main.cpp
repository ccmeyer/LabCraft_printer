#include <Arduino.h>

// The section below comes from this git repo: https://github.com/maxgerhardt/nucleo-f446ze-with-arduino/tree/main
// It was originally located after the void loop() but I moved it up to make sure that I set the
// clock speed before beginning the other communication.

bool clockConfig = false;

extern "C" void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};
  RCC_PeriphCLKInitTypeDef PeriphClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);
  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLM = 6;
  RCC_OscInitStruct.PLL.PLLN = 168;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = 7;
  RCC_OscInitStruct.PLL.PLLR = 3;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }
  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV4;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV2;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_5) != HAL_OK)
  {
    Error_Handler();
  }
  PeriphClkInitStruct.PeriphClockSelection = RCC_PERIPHCLK_CLK48;
  PeriphClkInitStruct.Clk48ClockSelection = RCC_CLK48CLKSOURCE_PLLQ;
  if (HAL_RCCEx_PeriphCLKConfig(&PeriphClkInitStruct) != HAL_OK)
  {
    Error_Handler();
  }
  clockConfig = true;
}

#include "TaskCommand.h"
#include "Communication.h"
#include "Gripper.h"
#include "CustomStepper.h"
#include "pin_assignments.h"
#include "all_constants.h"

TaskQueue taskQueue;
CommandQueue commandQueue;
Gripper gripper(pumpPin, pumpValvePin1, pumpValvePin2, taskQueue);
CustomStepper stepperX(stepperX.DRIVER,X_EN_PIN, X_STEP_PIN, X_DIR_PIN, xstop, taskQueue,X_INV_DIR);
CustomStepper stepperY(stepperY.DRIVER,Y_EN_PIN, Y_STEP_PIN, Y_DIR_PIN, ystop, taskQueue,Y_INV_DIR);
CustomStepper stepperZ(stepperZ.DRIVER,Z_EN_PIN, Z_STEP_PIN, Z_DIR_PIN, zstop, taskQueue,Z_INV_DIR);

Communication comm(taskQueue, commandQueue, gripper, stepperX, stepperY,stepperZ, 115200);


void setup() {
    SystemClock_Config();
    stepperX.setupMotor();
    // stepperX.enableMotor();
    stepperY.setupMotor();
    // stepperY.enableMotor();
    stepperZ.setupMotor();
    // stepperZ.enableMotor();
    stepperZ.setProperties(6000, 6000);
    comm.beginSerial();
}

void loop() {
    taskQueue.executeNextTask();
    comm.IncrementCycleCounter();
}