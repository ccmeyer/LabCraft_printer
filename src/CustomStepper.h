#ifndef CUSTOMSTEPPER_H
#define CUSTOMSTEPPER_H

#include <AccelStepper.h>
#include "TaskCommand.h"

class CustomStepper : public AccelStepper {
public:
    CustomStepper(uint8_t interface, uint8_t stepPin, uint8_t dirPin, int limitSwitchPin, TaskQueue& taskQueue, bool enable = true);

    void stepWithLimitCheck();    // Task to step the motor and check the limit switch
    void initiateHoming();        // Start the homing process
    void continueHoming();        // Continue the homing process after each step
    bool isAtLimit() const;       // Check if the limit switch is triggered
    void setTargetPosition(long position);  // Set a new target position and start moving
    unsigned long getStepInterval();       // Method to access _stepInterval
    void updateStepInterval();             // Method to use computeNewSpeed

private:
    int limitSwitchPin;          // Pin for the limit switch
    TaskQueue& taskQueue;        // Reference to the global TaskQueue

    Task stepTask;               // Task to manage motor stepping
    Task homingTask;             // Task to manage homing process

    void stepMotor();            // Perform a single step
};

#endif // CUSTOMSTEPPER_H