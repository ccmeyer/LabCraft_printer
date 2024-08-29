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
    CustomStepper(uint8_t interface, uint8_t enablePin, uint8_t stepPin, uint8_t dirPin, int limitSwitchPin, TaskQueue& taskQueue, bool invertDir);

    bool isBusy();               // Method to check if the motor is busy
    void setupMotor();           // Method to set up the motor
    void setProperties(int newSpeed, int newAcceleration);  // Method to set the motor properties
    void resetProperties();    // Method to reset the acceleration
    void enableMotor();           // Method to enable the motor
    void disableMotor();          // Method to disable the motor
    void safeStop();              // Method to safely stop the motor
    void checkLimitSwitch();      // Method to check the limit switch
    void beginHoming();           // Method to start the homing process
    bool isHomingComplete();      // Method to check if homing is complete

    void setTargetPosition(long position);  // Set a new target position and start moving
    void moveRelative(long distance);       // Move the motor by a relative distance
    unsigned long getStepInterval();       // Method to access _stepInterval
    bool movingForward();                   // Method to check if the motor direction is forward
    void updateStepInterval();             // Method to use computeNewSpeed
    void stepMotor();            // Perform a single step
    void manualStepForward();    // Perform a manual step in the forward direction
    void manualStepBackward();   // Perform a manual step in the backward direction


private:
    bool busy;
    bool invertDir;              // Flag to indicate if the direction is inverted
    int limitSwitchPin;          // Pin for the limit switch
    int enablePin;               // Pin for the enable signal
    bool limitPressed;           // Flag to indicate if the limit switch is pressed
    int maxSpeed;         // Maximum speed for the motor
    int maxAcceleration;     // Acceleration for the motor
    int originalSpeed;           // Original speed of the motor
    int originalAcceleration;    // Original acceleration of the motor
    
    bool homingComplete;         // Flag to indicate if homing is complete
    HomingStage homingStage;     // Current stage of the homing process

    TaskQueue& taskQueue;        // Reference to the global TaskQueue
    Task stepTask;               // Task to manage motor stepping
    Task homingTask;             // Task to manage homing process

    void continueHoming();       // Continue the homing process
};

#endif // CUSTOMSTEPPER_H