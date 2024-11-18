#include "DropletPrinter.h"
#include "GlobalState.h"

// Constructor
DropletPrinter::DropletPrinter(PressureSensor& sensor, PressureRegulator& printRegulator, PressureRegulator& refuelRegulator, TaskQueue& taskQueue,int printPin, int refuelPin, TIM_HandleTypeDef* htimPrint, TIM_HandleTypeDef* htimRefuel, uint32_t channelPrint, uint32_t channelRefuel)
    : printPin(printPin), refuelPin(refuelPin), sensor(sensor), printRegulator(printRegulator), refuelRegulator(refuelRegulator), taskQueue(taskQueue),htimPrint(htimPrint), htimRefuel(htimRefuel), channelPrint(channelPrint),channelRefuel(channelRefuel),
      frequency(20), interval(50000), refuelDelay(25000), printDuration(4200), refuelDuration(4200), pressureTolerance(20), 
      targetDroplets(0), printedDroplets(0), printingComplete(true), resetTriggered(false), refuelRequested(false),printActive(true),refuelActive(true),
      printDropletTask([this]() { this->printDroplet(); }, 0), refuelTask([this]() { this->refuelPulse(); }, 0) {
    pinMode(printPin, OUTPUT);
    pinMode(refuelPin, OUTPUT);
    digitalWrite(printPin, LOW); // Ensure the print valve is closed initially
    digitalWrite(refuelPin, LOW); // Ensure the refuel valve is closed initially
}

// Method to set the printing parameters
void DropletPrinter::setPrintingParameters(int frequency, unsigned long duration, int pressureTolerance) {
    this->frequency = frequency;
    this->interval = (1000000L / frequency);
    this->refuelDelay = interval / 2;
    this->printDuration = duration;
    configureTimer(htimRefuel, channelRefuel, duration);
    this->pressureTolerance = pressureTolerance;
}

// Method to set the duration for printing
void DropletPrinter::setPrintDuration(unsigned long duration) {
    this->printDuration = duration;
    configureTimer(htimPrint, channelPrint, duration);
}

// Method to set the duration for refueling
void DropletPrinter::setRefuelDuration(unsigned long duration) {
    this->refuelDuration = duration;
    configureTimer(htimRefuel, channelRefuel, duration);
}

// Method to get the duration
unsigned long DropletPrinter::getPrintDuration() const{
    return printDuration;
}

// Method to get the refuel duration
unsigned long DropletPrinter::getRefuelDuration() const{
    return refuelDuration;
}

// Method to enter print mode
void DropletPrinter::enterPrintMode() {
    sensor.setReadInterval(2000);  // Set the read interval to 2ms for faster response
    printRegulator.setAdjustInterval(2000); // Set the adjust interval to 2ms for faster response
    refuelRegulator.setAdjustInterval(2000); // Set the adjust interval to 2ms for faster response
    printRegulator.setPressureTolerance(1);
    refuelRegulator.setPressureTolerance(2);
}

// Method to exit print mode
void DropletPrinter::exitPrintMode() {
    sensor.setReadInterval(5000);  // Reset the read interval to 5ms
    printRegulator.setAdjustInterval(5000); // Reset the adjust interval to 5ms
    refuelRegulator.setAdjustInterval(5000); // Reset the adjust interval to 5ms
    printRegulator.setPressureTolerance(10);
    refuelRegulator.setPressureTolerance(10);
}

// Method to start printing the specified number of droplets
void DropletPrinter::startPrinting(int numberOfDroplets) {
    targetDroplets += numberOfDroplets;
    printingComplete = false;
    printRegulator.resetTargetReached();

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
    resetTriggered = false;
}



// Convert microseconds to timer ticks based on the clock frequency and prescaler
uint32_t DropletPrinter::convertMicrosecondsToTicks(uint32_t microseconds, uint32_t timerClockFrequency, uint32_t prescaler) {
    return (microseconds * (timerClockFrequency / 1e6)) / prescaler;
}
// Internal method to configure the timer in one-pulse mode
void DropletPrinter::configureTimer(TIM_HandleTypeDef* htim, uint32_t channel, unsigned long duration) {
    TIM_OC_InitTypeDef sConfigOC = {0};

    // Convert the pulse duration in microseconds to timer ticks
    uint32_t timerTicks = convertMicrosecondsToTicks(duration, 84000000, 84);  // For 84MHz clock and prescaler 84
    // uint32_t timerTicks = 5;

    // Configure the timer for one-pulse mode
    // htim->Instance = TIM9;  // Replace TIMx with your timer (e.g., TIM1, TIM2, etc.)
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
    // Serial.println("Timer configured");
}

// Method to deactivate the print valve
void DropletPrinter::deactivatePrint() {
    printActive = false;
}

// Method to deactivate the refuel valve
void DropletPrinter::deactivateRefuel() {
    refuelActive = false;
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
        printActive = true;
        refuelActive = true;
        return;
    }
    if (refuelRequested) {
        refuelTask.nextExecutionTime = micros();
        taskQueue.addTask(refuelTask);

        printDropletTask.nextExecutionTime = micros() + 10000; // Delay by 10ms before retrying
        taskQueue.addTask(printDropletTask);
        return;
    }
    if (printRegulator.isResetInProgress()){
        resetTriggered = true;
        printDropletTask.nextExecutionTime = micros() + 10000;
        taskQueue.addTask(printDropletTask);
        return;
    } else if (resetTriggered) {
        resetTriggered = false;
        sensor.setReadInterval(2000);  // Set the read interval to 2ms for faster response
        printRegulator.setAdjustInterval(2000); // Set the adjust interval to 2ms for faster response
        printRegulator.setPressureTolerance(1);
    }

    // Check the current pressure
    if (printRegulator.isRegulating()) {
        float currentPressure = sensor.getPrintPressure();
        float targetPressure = printRegulator.getTargetPressure();
        if (abs(currentPressure - targetPressure) > pressureTolerance) {
            // If the pressure is out of range, delay and retry
            printDropletTask.nextExecutionTime = micros() + 1000; // Delay by 1ms before retrying
            taskQueue.addTask(printDropletTask);
            return;
        }        
    }
    if (printActive) {
        // Open the valve to print the droplet
        configureTimer(htimPrint, channelPrint, printDuration);  // Configure the timer for the print duration
        HAL_TIM_PWM_Start(htimPrint, channelPrint);  // Start the PWM signal
        HAL_TIM_OnePulse_Start(htimPrint, channelPrint);  // Start the one-pulse mode
    }

    refuelRequested = true;  // Request a refuel after printing the droplet

    // Increment the printed droplet count
    printedDroplets++;

    
    // Schedule the refuel pulse based on the printing frequency
    refuelTask.nextExecutionTime = micros() + refuelDelay;
    taskQueue.addTask(refuelTask);

    // Schedule the next droplet print based on the printing frequency
    printDropletTask.nextExecutionTime = micros() + interval;
    taskQueue.addTask(printDropletTask);
}

// Method to handle refueling the chamber
void DropletPrinter::refuelPulse() {
    if (currentState == PAUSED) {
        refuelTask.nextExecutionTime = micros() + 10000;
        taskQueue.addTask(refuelTask);
        return;
    }
    if (!refuelRequested) {
        return;
    }
    if (refuelRegulator.isResetInProgress()){
        refuelTask.nextExecutionTime = micros() + 10000;
        taskQueue.addTask(refuelTask);
        return;
    }

    // Check the current pressure
    if (refuelRegulator.isRegulating()) {
        float currentPressure = sensor.getRefuelPressure();
        float targetPressure = refuelRegulator.getTargetPressure();
        if (abs(currentPressure - targetPressure) > pressureTolerance) {
            // If the pressure is out of range, delay and retry
            refuelTask.nextExecutionTime = micros() + 1000; // Delay by 1ms before retrying
            taskQueue.addTask(refuelTask);
            return;
        }        
    }
    if (refuelActive) {
        // Open the valve to refuel the chamber
        configureTimer(htimRefuel, channelRefuel, refuelDuration);  // Configure the timer for the refuel duration
        HAL_TIM_PWM_Start(htimRefuel, channelRefuel);  // Start the PWM signal
        HAL_TIM_OnePulse_Start(htimRefuel, channelRefuel);  // Start the one-pulse mode
    }
    refuelRequested = false;  // Reset the refuel request flag
}