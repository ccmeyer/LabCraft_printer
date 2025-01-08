#include "Flash.h"
#include "GlobalState.h"
#include "pin_functions.h"

// Constructor
Flash::Flash(int flashPin, TaskQueue& taskQueue, TIM_HandleTypeDef* htimFlash, uint32_t channelFlash) :
    flashPin(flashPin), taskQueue(taskQueue), htimFlash(htimFlash), channelFlash(channelFlash),
    flashDuration(100), flashDelay(1500) {
    pinMode(flashPin, OUTPUT);
    digitalWrite(flashPin, LOW); // Ensure the flash is off initially
}

// Method to check if the flash is busy
bool Flash::isBusy() const {
    return busy;
}

// Method to get the number of flashes
int Flash::getNumFlashes() const {
    return numFlashes;
}

// Method to get the flash width
unsigned long Flash::getFlashWidth() const {
    return flashDuration;
}

// Method to get the flash delay
unsigned long Flash::getFlashDelay() const {
    return flashDelay;
}

// Method to set the flash delay
void Flash::setFlashDelay(unsigned long delay) {
    this->flashDelay = delay;
}

// Internal method to configure the timer in one-pulse mode
void Flash::configureTimer(TIM_HandleTypeDef* htim, uint32_t channel, unsigned long duration) {
    TIM_OC_InitTypeDef sConfigOC = {0};

    // Calculate ticks based on nanoseconds
    const uint32_t timerFrequency = 84000000;  // Timer clock = 84 MHz
    const uint32_t prescaler = 8;
    const double tickDuration_ns = (1e9 * prescaler) / timerFrequency; // Time per tick in nanoseconds (~95.2 ns)

    // Calculate the number of ticks for the desired duration
    uint32_t timerTicks = static_cast<uint32_t>(round(duration / tickDuration_ns));

    // Configure the timer for one-pulse mode
    htim->Init.Period = (timerTicks*2) - 1;  // Set the period (time for one pulse)
    // uint32_t timerTicks = 10;
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

    // Clear any leftover flags
    __HAL_TIM_CLEAR_FLAG(htimFlash, TIM_FLAG_CC3);    // Clear capture/compare flag for channel 3
    __HAL_TIM_CLEAR_FLAG(htimFlash, TIM_FLAG_UPDATE); // Clear update event flag

    // Reset the counter to 0
    __HAL_TIM_SET_COUNTER(htimFlash, 0);

    // Explicitly enable the timer
    __HAL_TIM_ENABLE(htimFlash);

    configureTimer(htimFlash, channelFlash, flashDuration);

    HAL_TIM_PWM_Start(htimFlash, channelFlash);  // Start the PWM signal
    HAL_TIM_OnePulse_Start(htimFlash, channelFlash);  // Start the one-pulse mode
    numFlashes++;
}

// Method to trigger the flash with a delay
void Flash::triggerFlashWithDelay() {
    busy = true;
    delayMicroseconds(flashDelay);
    triggerFlash();
    busy = false;
}