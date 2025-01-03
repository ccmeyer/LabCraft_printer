#ifndef FLASH_H
#define FLASH_H

#include "TaskCommand.h"
#include <Arduino.h>
#include "stm32f4xx_hal.h"

class Flash {
private:
    int flashPin;
    int cameraPin;
    TaskQueue& taskQueue;
    Task checkFlashTask;
    bool busy = false;

    bool reading = false;
    int state = LOW;
    bool triggered = false;
    int numFlashes = 0;

    unsigned long readDelay;

    void readCameraPin();
    void triggerFlash();

public:
    Flash(int flashPin, int cameraPin, TaskQueue& taskQueue);
    bool isBusy() const;
    bool isReading() const;
    bool isTriggered() const;
    int getNumFlashes() const;

    void startReading();
    void stopReading();

};

#endif