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
    void disableRegulator();
    void homeSyringe();

    void beginRegulation();
    void setTargetPressureAbsolute(int targetPressure);
    void setTargetPressureRelative(int targetPressure);
    float getTargetPressure();
    long getCurrentPosition();
    long getTargetPosition();
    void stopRegulation();
    void resetSyringe();
    bool isBusy();
    bool isRegulating();
    void resetState();  // Method to reset the state of the regulator
    void restartRegulation();  // Method to restart pressure regulation task if already regulating
    void resetTargetReached();  // Method to reset the targetReached flag

private:
    CustomStepper& stepper;       // Reference to the CustomStepper controlling the syringe
    PressureSensor& sensor;       // Reference to the PressureSensor
    TaskQueue& taskQueue;         // Reference to the global TaskQueue

    Task adjustPressureTask;      // Task to adjust pressure
    Task resetSyringeTask;        // Task to reset the syringe
    Task homeSyringeTask;         // Task to home the syringe
    Task stepTask;                // Task to step the motor

    int valvePin;                 // Pin for the pressure regulator valve
    bool regulatingPressure;      // Flag to indicate if pressure regulation is active
    bool resetInProgress;         // Flag to indicate if the syringe is being reset
    float targetPressure;           // Target pressure to maintain
    int tolerance;                // Tolerance range for pressure regulation
    int cutoff;                   // Cutoff value for pressure regulation
    bool homing;                  // Flag to indicate if the syringe is homing

    float currentPressure;          // Current pressure reading
    float previousPressure;         // Previous pressure reading
    float pressureDifference;       // Difference between target and current pressure
    bool targetReached;             // Flag to indicate if the target pressure is reached

    int syringeSpeed;             // Speed of the syringe motor
    int adjustInterval;   // Interval for adjusting pressure
    int resetInterval;    // Interval for resetting the syringe
    int stepInterval;     // Interval for stepping the syringe motor
    bool stepperTaskActive;       // Flag to indicate if the stepper task is active
    int lowerBound;               // Lower bound for the syringe position
    int upperBound;               // Upper bound for the syringe position

    void adjustPressure();        // Method to adjust the pressure based on current readings
    void stepMotorDirectly();    // Method to step the motor directly
    void homeSyringeCheck();      // Method to check if the syringe is homed
};

#endif // PRESSUREREGULATOR_H