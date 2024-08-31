#ifndef DROPLETPRINTER_H
#define DROPLETPRINTER_H

#include "TaskCommand.h"
#include "PressureSensor.h"
#include "PressureRegulator.h"
#include <Arduino.h>

class DropletPrinter {
public:
    DropletPrinter(PressureSensor& sensor, PressureRegulator& regulator, TaskQueue& taskQueue, int valvePin);

    void setPrintingParameters(int frequency, unsigned long duration, int pressureTolerance);
    void setDuration(unsigned long duration);
    unsigned long getDuration();
    void startPrinting(int numberOfDroplets);
    bool isPrintingComplete() const;
    bool isBusy();
    void resetDropletCounts();

private:
    int valvePin;
    PressureSensor& sensor;
    PressureRegulator& regulator;
    TaskQueue& taskQueue;
    
    int frequency;              // Printing frequency (Hz)
    int interval;               // Interval between droplets (microseconds)
    unsigned long duration;     // Duration the valve is open per droplet (microseconds)
    int pressureTolerance;      // Acceptable pressure tolerance (units depend on the sensor)

    int targetDroplets;         // Total droplets to print
    int printedDroplets;        // Droplets printed so far
    bool printingComplete;      // Flag to indicate if printing is complete

    Task printDropletTask;      // Task for printing droplets

    void printDroplet();        // Method to handle printing a single droplet
};

#endif // DROPLETPRINTER_H
