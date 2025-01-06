#include "Flash.h"
#include "GlobalState.h"
#include "pin_functions.h"

// Constructor
Flash::Flash(int flashPin, int cameraPin, TaskQueue& taskQueue, TIM_HandleTypeDef* htimFlash, uint32_t channelFlash) :
    flashPin(flashPin), cameraPin(cameraPin), taskQueue(taskQueue), htimFlash(htimFlash), channelFlash(channelFlash),
    readDelay(2000), flashDuration(1800), checkFlashTask([this]() { this->readCameraPin(); }, 0) {
    pinMode(flashPin, OUTPUT);
    digitalWrite(flashPin, LOW); // Ensure the flash is off initially
    pinMode(cameraPin, INPUT);
}

// Method to check if the flash is busy
bool Flash::isBusy() const {
    return busy;
}

// Method to check if the flash is reading
bool Flash::isReading() const {
    return reading;
}

// Method to check if the flash is triggered
bool Flash::isTriggered() const {
    return triggered;
}

// Method to get the number of flashes
int Flash::getNumFlashes() const {
    return numFlashes;
}

// Method to get the flash width
unsigned long Flash::getFlashWidth() const {
    return flashDuration;
}

// Method to start reading the camera pin
void Flash::startReading() {
    reading = true;
    checkFlashTask.nextExecutionTime = micros();
    taskQueue.addTask(checkFlashTask);
}

// Method to stop reading the camera pin
void Flash::stopReading() {
    reading = false;
}

// Method to read the camera pin
void Flash::readCameraPin() {
    if (reading) {
        busy = true;
        state = digitalRead(cameraPin);
        if (state == LOW) {
            // Camera pin is low indicating no flash
            triggered = false;
        } else if (state == HIGH && !triggered) {
            // Camera pin is high indicating flash, avoids duplicate triggers
            triggered = true;
            triggerFlash();
        }
        checkFlashTask.nextExecutionTime = micros() + readDelay;
        taskQueue.addTask(checkFlashTask);
        busy = false;
    } else {
        busy = false;
    }
}

// Convert microseconds to timer ticks based on the clock frequency and prescaler
uint32_t Flash::convertMicrosecondsToTicks(uint32_t microseconds, uint32_t timerClockFrequency, uint32_t prescaler) {
    return (microseconds * (timerClockFrequency / 1e6)) / prescaler;
}
// Internal method to configure the timer in one-pulse mode
void Flash::configureTimer(TIM_HandleTypeDef* htim, uint32_t channel, unsigned long duration) {
    TIM_OC_InitTypeDef sConfigOC = {0};

    // Convert the pulse duration in microseconds to timer ticks
    uint32_t timerTicks = convertMicrosecondsToTicks(duration, 84000000, 84);  // For 84MHz clock and prescaler 84
    // uint32_t timerTicks = 5;

    // Configure the timer for one-pulse mode
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

// Method to set the flash duration
void Flash::setFlashDuration(unsigned long duration) {
    this->flashDuration = duration;
    configureTimer(htimFlash, channelFlash, duration);
}

// Method to trigger the flash
void Flash::triggerFlash() {
    configureTimer(htimFlash, channelFlash, flashDuration);
    HAL_TIM_PWM_Start(htimFlash, channelFlash);  // Start the PWM signal
    HAL_TIM_OnePulse_Start(htimFlash, channelFlash);  // Start the one-pulse mode
    numFlashes++;
}