#ifndef CUSTOMSTEPPER_H
#define CUSTOMSTEPPER_H

#include <AccelStepper.h>
#include "TaskCommand.h"

enum HomingStage {
    HOMING_START,
    TOWARD_SWITCH,
    AWAY_FROM_SWITCH,
    RESET_POS,
    HOMING_COMPLETE
};

class CustomStepper : public AccelStepper {
public:
    CustomStepper(uint8_t interface, uint8_t enablePin, uint8_t stepPin, uint8_t dirPin, int limitSwitchPin, TaskQueue& taskQueue, bool enable = true);

    void setupMotor();           // Method to set up the motor
    void enableMotor();           // Method to enable the motor
    void disableMotor();          // Method to disable the motor
    void safeStop();              // Method to safely stop the motor
    void checkLimitSwitch();      // Method to check the limit switch
    void beginHoming();           // Method to start the homing process

    void setTargetPosition(long position);  // Set a new target position and start moving
    void moveRelative(long distance);       // Move the motor by a relative distance
    unsigned long getStepInterval();       // Method to access _stepInterval
    bool movingForward();                   // Method to check if the motor direction is forward
    void updateStepInterval();             // Method to use computeNewSpeed


private:
    int limitSwitchPin;          // Pin for the limit switch
    int enablePin;               // Pin for the enable signal
    bool limitPressed;           // Flag to indicate if the limit switch is pressed
    bool homingComplete;         // Flag to indicate if homing is complete
    HomingStage homingStage;     // Current stage of the homing process

    TaskQueue& taskQueue;        // Reference to the global TaskQueue
    Task stepTask;               // Task to manage motor stepping
    Task homingTask;             // Task to manage homing process

    void stepMotor();            // Perform a single step
    void continueHoming();       // Continue the homing process
};

#endif // CUSTOMSTEPPER_H