#ifndef DROPLETPRINTER_H
#define DROPLETPRINTER_H

#include "TaskCommand.h"
#include "PressureSensor.h"
#include "PressureRegulator.h"
#include <Arduino.h>
#include "stm32f4xx_hal.h"

class DropletPrinter {
public:
    DropletPrinter(PressureSensor& sensor, PressureRegulator& regulator, TaskQueue& taskQueue, int printPin, int refuelPin, TIM_HandleTypeDef* htimPrint, TIM_HandleTypeDef* htimRefuel, uint32_t channelPrint, uint32_t channelRefuel);

    void setPrintingParameters(int frequency, unsigned long duration, int pressureTolerance);
    void setDuration(unsigned long duration);
    unsigned long getDuration() const;
    void startPrinting(int numberOfDroplets);
    bool isPrintingComplete() const;
    bool isBusy() const;
    void resetDropletCounts();
    void enterPrintMode();
    void exitPrintMode();

private:
    int printPin;
    int refuelPin;
    PressureSensor& sensor;
    PressureRegulator& regulator;
    TaskQueue& taskQueue;
    
    unsigned long frequency;              // Printing frequency (Hz)
    unsigned long interval;               // Interval between droplets (microseconds)
    unsigned long duration;     // Duration the valve is open per droplet (microseconds)
    int pressureTolerance;      // Acceptable pressure tolerance (units depend on the sensor)

    int targetDroplets;         // Total droplets to print
    int printedDroplets;        // Droplets printed so far
    bool printingComplete;      // Flag to indicate if printing is complete
    bool resetTriggered;       // Flag to indicate that the syringe reset has been triggered

    Task printDropletTask;      // Task for printing droplets

    TIM_HandleTypeDef* htimPrint;    // Timer handler for one-pulse mode
    TIM_HandleTypeDef* htimRefuel;   // Timer handler for refueling chamber
    uint32_t channelPrint;                // Timer channel for one-pulse mode
    uint32_t channelRefuel;          // Timer channel for refueling chamber

    void printDroplet();        // Method to handle printing a single droplet
    void configureTimer(TIM_HandleTypeDef* htim, uint32_t channel, unsigned long duration);      // Method to configure the timer for one-pulse mode
    uint32_t convertMicrosecondsToTicks(uint32_t microseconds, uint32_t timerClockFrequency, uint32_t prescaler);
};

#endif // DROPLETPRINTER_H
