#ifndef FLASH_H
#define FLASH_H

#include "TaskCommand.h"
#include <Arduino.h>
#include "stm32f4xx_hal.h"

class Flash {
public:
    Flash(int flashPin, int cameraPin, TaskQueue& taskQueue, TIM_HandleTypeDef* htimFlash, uint32_t channelFlash);
    bool isBusy() const;
    bool isReading() const;
    bool isTriggered() const;
    int getNumFlashes() const;
    unsigned long getFlashWidth() const;
    void setFlashDuration(unsigned long duration);


    void startReading();
    void stopReading();

private:
    int flashPin;
    int cameraPin;

    TIM_HandleTypeDef* htimFlash;
    uint32_t channelFlash;

    TaskQueue& taskQueue;
    Task checkFlashTask;
    bool busy = false;

    bool reading = false;
    int state = LOW;
    unsigned long readDelay;

    unsigned long flashDuration; // Duration the flash is on (microseconds)
    bool triggered = false;
    int numFlashes = 0;


    void readCameraPin();
    uint32_t convertMicrosecondsToTicks(uint32_t microseconds, uint32_t timerClockFrequency, uint32_t prescaler);
    void configureTimer(TIM_HandleTypeDef* htim, uint32_t channel, unsigned long duration);      // Method to configure the timer for one-pulse mode
    void triggerFlash();
};

#endif