#include "DropletPrinter.h"
#include "GlobalState.h"

// Constructor
DropletPrinter::DropletPrinter(PressureSensor& sensor, PressureRegulator& regulator, TaskQueue& taskQueue,int valvePin)
    : valvePin(valvePin), sensor(sensor), regulator(regulator), taskQueue(taskQueue),
      frequency(20), interval(50000), duration(3000), pressureTolerance(20), 
      targetDroplets(0), printedDroplets(0), printingComplete(true),
      printDropletTask([this]() { this->printDroplet(); }, 0) {
    pinMode(valvePin, OUTPUT);
    digitalWrite(valvePin, LOW); // Ensure the valve is closed initially
}

// Method to set the printing parameters
void DropletPrinter::setPrintingParameters(int frequency, unsigned long duration, int pressureTolerance) {
    this->frequency = frequency;
    this->interval = (1000000L / frequency);
    this->duration = duration;
    this->pressureTolerance = pressureTolerance;
}

// Method to set the duration
void DropletPrinter::setDuration(unsigned long duration) {
    this->duration = duration;
}

// Method to get the duration
unsigned long DropletPrinter::getDuration() {
    return duration;
}

// Method to start printing the specified number of droplets
void DropletPrinter::startPrinting(int numberOfDroplets) {
    targetDroplets += numberOfDroplets;
    printingComplete = false;
    regulator.resetTargetReached();

    // Start the printing task
    printDropletTask.nextExecutionTime = micros();
    taskQueue.addTask(printDropletTask);
}

// Method to check if printing is complete
bool DropletPrinter::isPrintingComplete() const {
    return printingComplete;
}

// Method to check if the printer is busy
bool DropletPrinter::isBusy() {
    return !printingComplete;
}

// Method to reset the droplet counts
void DropletPrinter::resetDropletCounts() {
    targetDroplets = 0;
    printedDroplets = 0;
    printingComplete = true;
}

// Method to handle printing a single droplet
void DropletPrinter::printDroplet() {
    if (currentState == PAUSED) {
        printDropletTask.nextExecutionTime = micros() + 10000;
        taskQueue.addTask(printDropletTask);
        return;
    }
    if (printedDroplets >= targetDroplets) {
        printingComplete = true;
        return;
    }

    // Check the current pressure
    if (regulator.isRegulating()) {
        float currentPressure = sensor.getPressure();
        float targetPressure = regulator.getTargetPressure();
        if (abs(currentPressure - targetPressure) > pressureTolerance) {
            // If the pressure is out of range, delay and retry
            printDropletTask.nextExecutionTime = micros() + 1000; // Delay by 1ms before retrying
            taskQueue.addTask(printDropletTask);
            return;
        }        
    }

    // Open the valve to print the droplet
    digitalWrite(valvePin, HIGH);
    delayMicroseconds(duration); // Wait for the defined duration
    digitalWrite(valvePin, LOW);

    // Increment the printed droplet count
    printedDroplets++;

    // Schedule the next droplet print based on the printing frequency
    printDropletTask.nextExecutionTime = micros() + interval;
    taskQueue.addTask(printDropletTask);
}
