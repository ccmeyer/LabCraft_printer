#ifndef COORDINATOR_H
#define COORDINATOR_H

#include "DropletPrinter.h"
#include "Flash.h"
#include "TaskCommand.h"

class Coordinator {
private:
    DropletPrinter& printer;
    Flash& flash;
    TaskQueue& taskQueue;
    Task checkSignalTask;

    int cameraPin;
    unsigned long readDelay;

    bool reading;
    bool triggerDetected;
    void printDropletsWithFlash();
    void readCameraSignal();

public:
    Coordinator(DropletPrinter& printer, Flash& flash, TaskQueue& taskQueue, int cameraPin);
    void startReading();
    void stopReading();
    
};

#endif