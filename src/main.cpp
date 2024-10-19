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
#include <TMCStepper.h>
#include <HardwareSerial.h>
#include "Gripper.h"
#include "GripperStepper.h"
#include "CustomStepper.h"
#include "PressureSensor.h"
#include "PressureRegulator.h"
#include "DropletPrinter.h"
#include "pin_assignments.h"
#include "all_constants.h"
#include "GlobalState.h"
#include "stm32f4xx_hal.h"
#include <stm32f4xx_hal_iwdg.h>

SystemState currentState = RUNNING; // Define the global state
IWDG_HandleTypeDef hiwdg; // Define the watchdog handle
TIM_HandleTypeDef htim9;  // Define your timer handle

TaskQueue taskQueue(&hiwdg);
CommandQueue commandQueue;
// Gripper gripper(pumpPin, pumpValvePin1, pumpValvePin2, taskQueue);
// HardwareSerial& TMC_UART = Serial6; // Using UART7 for communication
HardwareSerial SerialUART1(GRIPPER_UART_RX, GRIPPER_UART_TX);
GripperStepper gripperStepper(GRIPPER_EN, GRIPPER_STEP, GRIPPER_DIR, GRIPPER_ADDRESS, taskQueue);
CustomStepper stepperX(stepperX.DRIVER,X_EN_PIN, X_STEP_PIN, X_DIR_PIN, xstop, taskQueue,X_INV_DIR);
CustomStepper stepperY(stepperY.DRIVER,Y_EN_PIN, Y_STEP_PIN, Y_DIR_PIN, ystop, taskQueue,Y_INV_DIR);
CustomStepper stepperZ(stepperZ.DRIVER,Z_EN_PIN, Z_STEP_PIN, Z_DIR_PIN, zstop, taskQueue,Z_INV_DIR);
CustomStepper stepperP(stepperP.DRIVER,P_EN_PIN, P_STEP_PIN, P_DIR_PIN, pstop, taskQueue,P_INV_DIR);
PressureSensor pressureSensor(sensorAddress,taskQueue);
PressureRegulator regulator(stepperP, pressureSensor,taskQueue,printValvePin);
DropletPrinter printer(pressureSensor, regulator, taskQueue, printPin, &htim9, TIM_CHANNEL_1);

Communication comm(taskQueue, commandQueue, gripperStepper, stepperX, stepperY, stepperZ, pressureSensor, regulator, printer, 115200);

// Configure GPIO for TIM9 channel (assuming GPIO PA2 for example, you should replace with your actual pin)
void configureGPIOForTimer() {
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    __HAL_RCC_GPIOE_CLK_ENABLE();  // Enable the GPIO clock (replace with the appropriate port)

    GPIO_InitStruct.Pin = GPIO_PIN_5;  // Replace with the correct pin number for your valve pin
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    GPIO_InitStruct.Alternate = GPIO_AF3_TIM9;  // TIM9 alternate function

    HAL_GPIO_Init(GPIOE, &GPIO_InitStruct);  // Replace GPIOA with your GPIO port
}

void initTimer9() {
    htim9.Instance = TIM9;  // Use TIM9
    htim9.Init.Prescaler = 83;  // Set the prescaler for 1MHz timer clock (84MHz system clock / 84 prescaler)
    htim9.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim9.Init.Period = 0xFFFF;  // Set a default period, can be adjusted later in DropletPrinter class
    htim9.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    htim9.Init.RepetitionCounter = 0;  // No repetition

    if (HAL_TIM_Base_Init(&htim9) != HAL_OK) {
        // Initialization error
        Serial.println("Timer initialization failed");
    }
}


void setup() {
    SystemClock_Config();
    
    configureGPIOForTimer();
    initTimer9();

    stepperX.setupMotor();
    stepperY.setupMotor();
    stepperZ.setupMotor();
    stepperZ.setProperties(6000, 24000);
    pressureSensor.beginCommunication(sdaPin,sclPin,wireFrequency);
    pressureSensor.startReading();
    regulator.setupRegulator();
    comm.beginSerial();
    // SerialUART1.begin(115200);
    gripperStepper.initialize();

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