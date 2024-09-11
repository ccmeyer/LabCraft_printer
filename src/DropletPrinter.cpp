#include "DropletPrinter.h"
#include "GlobalState.h"

// Constructor
DropletPrinter::DropletPrinter(PressureSensor& sensor, PressureRegulator& regulator, TaskQueue& taskQueue,int valvePin, TIM_HandleTypeDef* htim, uint32_t channel)
    : valvePin(valvePin), sensor(sensor), regulator(regulator), taskQueue(taskQueue),htim(htim), channel(channel),
      frequency(20), interval(50000), duration(3000), pressureTolerance(20), 
      targetDroplets(0), printedDroplets(0), printingComplete(true),
      printDropletTask([this]() { this->printDroplet(); }, 0) {
    pinMode(valvePin, OUTPUT);
    digitalWrite(valvePin, LOW); // Ensure the valve is closed initially
}

// Method to set the printing parameters
void DropletPrinter::setPrintingParameters(int frequency, unsigned long duration, int pressureTolerance) {
    this->frequency = frequency;
    this->interval = (1000000L / frequency);
    this->duration = duration;
    configureTimer();
    this->pressureTolerance = pressureTolerance;
}

// Method to set the duration
void DropletPrinter::setDuration(unsigned long duration) {
    this->duration = duration;
    Serial.println("Setting duration");
    configureTimer();
}

// Method to get the duration
unsigned long DropletPrinter::getDuration() const{
    return duration;
}

// Method to start printing the specified number of droplets
void DropletPrinter::startPrinting(int numberOfDroplets) {
    targetDroplets += numberOfDroplets;
    printingComplete = false;
    regulator.resetTargetReached();

    // Start the printing task
    printDropletTask.nextExecutionTime = micros();
    taskQueue.addTask(printDropletTask);
}

// Method to check if printing is complete
bool DropletPrinter::isPrintingComplete() const {
    return printingComplete;
}

// Method to check if the printer is busy
bool DropletPrinter::isBusy() const{
    return !printingComplete;
}

// Method to reset the droplet counts
void DropletPrinter::resetDropletCounts() {
    targetDroplets = 0;
    printedDroplets = 0;
    printingComplete = true;
}

// Convert microseconds to timer ticks based on the clock frequency and prescaler
uint32_t DropletPrinter::convertMicrosecondsToTicks(uint32_t microseconds, uint32_t timerClockFrequency, uint32_t prescaler) {
    return (microseconds * (timerClockFrequency / 1e6)) / prescaler;
}
// Internal method to configure the timer in one-pulse mode
void DropletPrinter::configureTimer() {
    TIM_OC_InitTypeDef sConfigOC = {0};

    // Convert the pulse duration in microseconds to timer ticks
    uint32_t timerTicks = convertMicrosecondsToTicks(duration, 84000000, 84);  // For 84MHz clock and prescaler 84
    // uint32_t timerTicks = 5;
    Serial.println("Setting up timer");
    Serial.println(timerTicks);

    // Configure the timer for one-pulse mode
    htim->Instance = TIM9;  // Replace TIMx with your timer (e.g., TIM1, TIM2, etc.)
    htim->Init.Period = (timerTicks*2) - 1;  // Set the period (time for one pulse)
    htim->Init.CounterMode = TIM_COUNTERMODE_UP;
    htim->Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    htim->Init.RepetitionCounter = 0;       // Only one repetition (single pulse)

    // Initialize the timer in one-pulse mode
    if (HAL_TIM_OnePulse_Init(htim, TIM_OPMODE_SINGLE) != HAL_OK) {
        Serial.println("One Pulse Mode initialization failed");
    }
    // Configure the output compare mode for PWM
    sConfigOC.OCMode = TIM_OCMODE_PWM1;     // Set PWM mode 1
    sConfigOC.Pulse = timerTicks;    // Set the duty cycle (pulse duration)
    sConfigOC.OCPolarity = TIM_OCPOLARITY_LOW;
    sConfigOC.OCNPolarity = TIM_OCNPOLARITY_HIGH;
    sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
    
    /// Configure the PWM on the specific channel
    if (HAL_TIM_PWM_ConfigChannel(htim, &sConfigOC, channel) != HAL_OK) {
        Serial.println("PWM configuration failed");
    }
    Serial.println("Timer configured");
}

// Method to handle printing a single droplet
void DropletPrinter::printDroplet() {
    if (currentState == PAUSED) {
        printDropletTask.nextExecutionTime = micros() + 10000;
        taskQueue.addTask(printDropletTask);
        return;
    }
    if (printedDroplets >= targetDroplets) {
        printingComplete = true;
        return;
    }

    // Check the current pressure
    if (regulator.isRegulating()) {
        float currentPressure = sensor.getPressure();
        float targetPressure = regulator.getTargetPressure();
        if (abs(currentPressure - targetPressure) > pressureTolerance) {
            // If the pressure is out of range, delay and retry
            printDropletTask.nextExecutionTime = micros() + 1000; // Delay by 1ms before retrying
            taskQueue.addTask(printDropletTask);
            return;
        }        
    }

    // Open the valve to print the droplet
    configureTimer();
    HAL_TIM_PWM_Start(htim, channel);  // Start the PWM signal
    HAL_TIM_OnePulse_Start(htim, channel);  // Start the one-pulse mode

    // Increment the printed droplet count
    printedDroplets++;

    // Schedule the next droplet print based on the printing frequency
    printDropletTask.nextExecutionTime = micros() + interval;
    taskQueue.addTask(printDropletTask);
}
