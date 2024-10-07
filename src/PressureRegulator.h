#ifndef PRESSUREREGULATOR_H
#define PRESSUREREGULATOR_H

#include "PressureSensor.h"
#include "CustomStepper.h"
#include "TaskCommand.h"
#include "Logger.h"

class PressureRegulator {
public:
    PressureRegulator(CustomStepper& stepper, PressureSensor& sensor, TaskQueue& taskQueue, Logger& loggerRef, int valvePin);

    void setupRegulator();
    void enableRegulator();
    void disableRegulator();
    void homeSyringe();

    void beginRegulation();
    void setTargetPressureAbsolute(int targetPressure);
    void setTargetPressureRelative(int targetPressure);
    float getTargetPressure() const;
    long getCurrentPosition() const;
    long getTargetPosition() const;
    void stopRegulation();
    void resetSyringe();
    bool isBusy() const;
    bool isRegulating() const;
    void resetState();  // Method to reset the state of the regulator
    void restartRegulation();  // Method to restart pressure regulation task if already regulating
    void resetTargetReached();  // Method to reset the targetReached flag
    void setAdjustInterval(unsigned long interval);  // Method to set the adjust interval
    bool isResetInProgress() const;  // Method to check if the syringe is being reset
    void setPressureTolerance(int tolerance);  // Method to set the pressure tolerance

private:
    CustomStepper& stepper;       // Reference to the CustomStepper controlling the syringe
    PressureSensor& sensor;       // Reference to the PressureSensor
    TaskQueue& taskQueue;         // Reference to the global TaskQueue

    Task adjustPressureTask;      // Task to adjust pressure
    Task resetSyringeTask;        // Task to reset the syringe
    Task homeSyringeTask;         // Task to home the syringe
    Task stepTask;                // Task to step the motor

    Logger& loggerRef;            // Reference to the global Logger

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
    int targetReachedCounter;      // Counter for target reached
    float deadband;                 // Deadband for pressure regulation

    long motorPosition;             // Current position of the syringe motor
    long totalRange;                // Total range of the syringe motor
    float positionFactor;            // Scale between 0 (start) and 1 (far inside)
    int maxSpeed;                   // Maximum speed for the syringe motor
    int minSpeed;                   // Minimum speed for the syringe motor

    int syringeSpeed;             // Speed of the syringe motor
    unsigned long adjustInterval;   // Interval for adjusting pressure
    unsigned long resetInterval;    // Interval for resetting the syringe
    unsigned long stepInterval;     // Interval for stepping the syringe motor
    bool stepperTaskActive;       // Flag to indicate if the stepper task is active
    int lowerBound;               // Lower bound for the syringe position
    int upperBound;               // Upper bound for the syringe position

    void adjustPressure();        // Method to adjust the pressure based on current readings
    void stepMotorDirectly();    // Method to step the motor directly
    void homeSyringeCheck();      // Method to check if the syringe is homed
};

#endif // PRESSUREREGULATOR_H