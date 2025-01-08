#ifndef FLASH_H
#define FLASH_H

#include "TaskCommand.h"
#include <Arduino.h>
#include "stm32f4xx_hal.h"

class Flash {
public:
    Flash(int flashPin, TaskQueue& taskQueue, TIM_HandleTypeDef* htimFlash, uint32_t channelFlash);
    bool isBusy() const;
    int getNumFlashes() const;
    unsigned long getFlashWidth() const;
    void setFlashDuration(unsigned long duration);
    unsigned long getFlashDelay() const;
    void setFlashDelay(unsigned long delay);
    void triggerFlashWithDelay();

private:
    int flashPin;

    TIM_HandleTypeDef* htimFlash;
    uint32_t channelFlash;

    TaskQueue& taskQueue;
    bool busy = false;
    unsigned long flashDuration; // Duration the flash is on (nanoseconds, 100nsec resolution)
    unsigned long flashDelay;   // Delay before the flash is triggered (microseconds)
    bool triggered = false;
    int numFlashes = 0;

    void configureTimer(TIM_HandleTypeDef* htim, uint32_t channel, unsigned long duration);      // Method to configure the timer for one-pulse mode
    void triggerFlash();
};

#endif