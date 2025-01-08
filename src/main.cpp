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
#include "PressureSensor.h"
#include "PressureRegulator.h"
#include "DropletPrinter.h"
#include "Flash.h"
#include "Coordinator.h"
#include "pin_assignments.h"
#include "pin_functions.h"
#include "all_constants.h"
#include "GlobalState.h"
#include "stm32f4xx_hal.h"
#include <stm32f4xx_hal_iwdg.h>

SystemState currentState = RUNNING; // Define the global state
IWDG_HandleTypeDef hiwdg; // Define the watchdog handle
TIM_HandleTypeDef htim9;  // Timer 9 handle for printing droplets
TIM_HandleTypeDef htim4;  // Timer 4 handle for refueling chamber and flash
TIM_HandleTypeDef htim3;  // Timer 3 handle for flash duration

TaskQueue taskQueue(&hiwdg);
CommandQueue commandQueue;
Gripper gripper(pumpPin, pumpValvePin, taskQueue);
CustomStepper stepperX(stepperX.DRIVER,X_EN_PIN, X_STEP_PIN, X_DIR_PIN, xstop, taskQueue,X_INV_DIR);
CustomStepper stepperY(stepperY.DRIVER,Y_EN_PIN, Y_STEP_PIN, Y_DIR_PIN, ystop, taskQueue,Y_INV_DIR);
CustomStepper stepperZ(stepperZ.DRIVER,Z_EN_PIN, Z_STEP_PIN, Z_DIR_PIN, zstop, taskQueue,Z_INV_DIR);
CustomStepper stepperP(stepperP.DRIVER,P_EN_PIN, P_STEP_PIN, P_DIR_PIN, pstop, taskQueue,P_INV_DIR);
CustomStepper stepperR(stepperR.DRIVER,R_EN_PIN, R_STEP_PIN, R_DIR_PIN, rstop, taskQueue,R_INV_DIR);
PressureSensor pressureSensor(TCAAddress, sensorAddress, taskQueue);
PressureRegulator printRegulator(stepperP, pressureSensor,taskQueue,printValvePin,printPort);
PressureRegulator refuelRegulator(stepperR, pressureSensor,taskQueue,refuelValvePin,refuelPort);
Flash flash(flashPin, taskQueue,&htim3, TIM_CHANNEL_3);
DropletPrinter printer(pressureSensor, printRegulator, refuelRegulator, taskQueue, printPin, refuelPin, &htim9, &htim4, TIM_CHANNEL_1, TIM_CHANNEL_1,flash);
Coordinator coord(printer, flash, taskQueue, cameraPin);
Communication comm(taskQueue, commandQueue, gripper, stepperX, stepperY, stepperZ, pressureSensor, printRegulator, refuelRegulator, printer, flash, coord, 115200);

/** Configure and initialize the hardware timers for accurate GPIO timing
 * Refer to the stm32f446re.pdf datasheet, Table 11 for the GPIO alternate functions and timer information
 */
// Configure GPIO for TIM9 channel 1
void configureGPIOForTimer9() {
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    __HAL_RCC_GPIOE_CLK_ENABLE();  // Enable the GPIO clock (GPIOE for PE5)

    GPIO_InitStruct.Pin = GPIO_PIN_5;  // Select the pin number (i.e. GPIO_PIN_5 for PE5)
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    GPIO_InitStruct.Alternate = GPIO_AF3_TIM9;  // TIM9 alternate function

    HAL_GPIO_Init(GPIOE, &GPIO_InitStruct);  // Select the port number (i.e. GPIOE for PE5)
}

void configureGPIOForTimer4() {
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    // Enable GPIO clocks for Port D and Port B
    __HAL_RCC_GPIOD_CLK_ENABLE();  // Clock for PD12

    // --- Configure PD12 (TIM4 Channel 1) ---
    GPIO_InitStruct.Pin = GPIO_PIN_12;  // PD12
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;  // Alternate function, push-pull
    GPIO_InitStruct.Pull = GPIO_NOPULL;     // No pull-up or pull-down
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    GPIO_InitStruct.Alternate = GPIO_AF2_TIM4;  // TIM4 alternate function
    HAL_GPIO_Init(GPIOD, &GPIO_InitStruct);    // Initialize GPIO PD12
}

// Configure GPIO for TIM3 channel 3
void configureGPIOForTimer3() {
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    __HAL_RCC_GPIOB_CLK_ENABLE();  // Enable the GPIO clock (GPIOB for PB0)

    GPIO_InitStruct.Pin = GPIO_PIN_0;  // Select the pin number (i.e. GPIO_PIN_0 for PB0)
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_PULLDOWN;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    GPIO_InitStruct.Alternate = GPIO_AF2_TIM3;  // TIM3 alternate function

    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);  // Select the port number (i.e. GPIOB for PB0)
}

void initTimer9() {
    htim9.Instance = TIM9;  // Use TIM9
    htim9.Init.Prescaler = 83;  // Set the prescaler for 1MHz timer clock (84MHz system clock / 84 prescaler)
    htim9.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim9.Init.Period = 0xFFFF;  // Set a default period, can be adjusted later in DropletPrinter class
    htim9.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    htim9.Init.RepetitionCounter = 0;  // No repetition
    __HAL_RCC_TIM9_CLK_ENABLE();  // Enable the clock for TIM9

    if (HAL_TIM_Base_Init(&htim9) != HAL_OK) {
        // Initialization error
        Serial.println("Timer initialization failed");
    }
}

void initTimer4() {
    htim4.Instance = TIM4;  // Use TIM4
    htim4.Init.Prescaler = 83;  // Set the prescaler for 1MHz timer clock (84MHz system clock / 84 prescaler)
    htim4.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim4.Init.Period = 0xFFFF;  // Set a default period
    htim4.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    htim4.Init.RepetitionCounter = 0;  // No repetition
    __HAL_RCC_TIM4_CLK_ENABLE();  // Enable the clock for TIM4

    if (HAL_TIM_Base_Init(&htim4) != HAL_OK) {
        // Initialization error
        Serial.println("Timer 4 initialization failed");
    }
}

void initTimer3() {
    htim3.Instance = TIM3;  // Use TIM3
    htim3.Init.Prescaler = 8-1;  // Prescaler for 10.5 MHz (84000000 / 8)
    htim3.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim3.Init.Period = 0xFFFF;  // Set a default period, can be adjusted later in DropletPrinter class
    htim3.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    htim3.Init.RepetitionCounter = 0;  // No repetition
    __HAL_RCC_TIM3_CLK_ENABLE();  // Enable the clock for TIM3

    if (HAL_TIM_Base_Init(&htim3) != HAL_OK) {
        // Initialization error
        Serial.println("Timer initialization failed");
    }
}

void setup() {
    SystemClock_Config();
    
    configureGPIOForTimer9();
    initTimer9();

    configureGPIOForTimer4();
    initTimer4();

    configureGPIOForTimer3();
    initTimer3();

    stepperX.setupMotor();
    stepperY.setupMotor();
    stepperZ.setupMotor();
    stepperZ.setProperties(6000, 24000);
    pressureSensor.beginCommunication(sdaPin,sclPin,wireFrequency);
    pressureSensor.startReading();
    printRegulator.setupRegulator();
    refuelRegulator.setupRegulator();
    comm.beginSerial();

    __HAL_RCC_WWDG_CLK_ENABLE(); // Enable the clock for the watchdog
    hiwdg.Instance = IWDG;       // Use the IWDG instance
    hiwdg.Init.Prescaler = IWDG_PRESCALER_64;  // Set prescaler
    hiwdg.Init.Reload = 3125;    // Set reload value (timeout duration)

    // Initialize the watchdog timer
    if (HAL_IWDG_Init(&hiwdg) != HAL_OK) {
        // Handle initialization error
        Serial.println("Watchdog initialization failed");
    }
    Serial.println("System initialized with watchdog");
}

void loop() {
    taskQueue.executeNextTask();
    comm.IncrementCycleCounter();
}