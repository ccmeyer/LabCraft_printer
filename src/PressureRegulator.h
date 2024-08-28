#ifndef PRESSUREREGULATOR_H
#define PRESSUREREGULATOR_H

#include "PressureSensor.h"
#include "CustomStepper.h"
#include "TaskCommand.h"

class PressureRegulator {
public:
    PressureRegulator(CustomStepper& stepper, PressureSensor& sensor, TaskQueue& taskQueue, int valvePin);

    void setupRegulator();
    void enableRegulator();
    void beginRegulation(int targetPressure);
    void setTargetPressure(int targetPressure);
    float getTargetPressure();
    float getCurrentPressure();
    void stopRegulation();
    void resetSyringe();

private:
    CustomStepper& stepper;       // Reference to the CustomStepper controlling the syringe
    PressureSensor& sensor;       // Reference to the PressureSensor
    TaskQueue& taskQueue;         // Reference to the global TaskQueue

    Task adjustPressureTask;      // Task to adjust pressure
    Task resetSyringeTask;        // Task to reset the syringe
    int valvePin;                 // Pin for the pressure regulator valve
    bool regulatingPressure;      // Flag to indicate if pressure regulation is active
    bool resetInProgress;         // Flag to indicate if the syringe is being reset
    float targetPressure;           // Target pressure to maintain
    int tolerance;                // Tolerance range for pressure regulation
    int cutoff;                   // Cutoff value for pressure regulation
    float currentPressure;          // Current pressure reading
    int pressureDifference;       // Difference between target and current pressure
    int syringeSpeed;             // Speed of the syringe motor
    int adjustInterval;   // Interval for adjusting pressure

    void adjustPressure();        // Method to adjust the pressure based on current readings
};

#endif // PRESSUREREGULATOR_H