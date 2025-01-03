#include "Flash.h"
#include "GlobalState.h"
#include "pin_functions.h"

// Constructor
Flash::Flash(int flashPin, int cameraPin, TaskQueue& taskQueue) :
    flashPin(flashPin), cameraPin(cameraPin), taskQueue(taskQueue), readDelay(2000),
    checkFlashTask([this]() { this->readCameraPin(); }, 0) {
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

// Method to trigger the flash
void Flash::triggerFlash() {
    blinkLED();
    delay(100);
    blinkLED();
    delay(100);
    numFlashes++;
}