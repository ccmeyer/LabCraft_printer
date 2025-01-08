#include "Coordinator.h"

// Constructor
Coordinator::Coordinator(DropletPrinter& printer, Flash& flash, TaskQueue& taskQueue, int cameraPin)
    : printer(printer), flash(flash), taskQueue(taskQueue), cameraPin(cameraPin), checkSignalTask([this]() { this->readCameraSignal(); }, 0), 
    triggerDetected(false), reading(false), readDelay(2000) {
        pinMode(cameraPin, INPUT);
    }

// Method to start reading the camera signal
void Coordinator::startReading() {
    reading = true;
    printer.enterImagingMode();
    checkSignalTask.nextExecutionTime = micros();
    taskQueue.addTask(checkSignalTask);
}

// Method to stop reading the camera signal
void Coordinator::stopReading() {
    reading = false;
    printer.exitImagingMode();
}

// Method to read the camera signal
void Coordinator::readCameraSignal() {
    if (reading) {
        int state = digitalRead(cameraPin);
        if (state == HIGH && !triggerDetected) {
            triggerDetected = true;
            printDropletsWithFlash();
        } else if (state == LOW) {
            triggerDetected = false;
        }
        checkSignalTask.nextExecutionTime = micros();
        taskQueue.addTask(checkSignalTask);
    }
}

// Method to print a droplet with flash
void Coordinator::printDropletsWithFlash() {
    // flash.triggerFlashWithDelay();
    // printer.resetDropletCounts();
    printer.startPrinting(10);
}
