#include "CustomStepper.h"
#include <Arduino.h>

// Constructor
CustomStepper::CustomStepper(uint8_t interface, uint8_t enablePin, uint8_t stepPin, uint8_t dirPin, int limitSwitchPin, TaskQueue& taskQueue, bool enable)
    : AccelStepper(interface, stepPin, dirPin),enablePin(enablePin), limitSwitchPin(limitSwitchPin), taskQueue(taskQueue), limitPressed(false),
      stepTask([this]() { this->stepMotor(); }, 0) {
    //   homingTask([this]() { this->continueHoming(); }, 0) 
    pinMode(limitSwitchPin, INPUT);
}

// Method to access the _stepInterval variable
unsigned long CustomStepper::getStepInterval() {
    return _stepInterval;  // Accessing protected member from AccelStepper
}

// Method to use computeNewSpeed function
void CustomStepper::updateStepInterval() {
    computeNewSpeed();  // Update the step interval using AccelStepper's method
}

// Method to set up the motor
void CustomStepper::setupMotor() {
    Serial.println("Setting up motor");
    setMaxSpeed(4000);  // Set a reasonable speed for the motor
    setAcceleration(8000);  // Set a reasonable acceleration for the motor
    setEnablePin(enablePin);
    setPinsInverted(false, false, true);
    disableOutputs();
}

// Method to enable the motor
void CustomStepper::enableMotor() {
    Serial.println("Enabling motor");
    enableOutputs();
}

void CustomStepper::disableMotor() {
    Serial.println("Disabling motor");
    disableOutputs();
}

// Method to set the target position
void CustomStepper::setTargetPosition(long position) {
    Serial.print("Setting target position: ");
    Serial.println(position);
    moveTo(position);
    stepTask.nextExecutionTime = micros();
    taskQueue.addTask(stepTask);
}

// Method to perform a single step
void CustomStepper::stepMotor() {
    if (distanceToGo() == 0) {
        Serial.println("Target position reached");
        stop();
    } else if (limitPressed) {
        safeStop();
        limitPressed = false;
    } else if (runSpeed()) {
        updateStepInterval();
        stepTask.nextExecutionTime = micros() + getStepInterval();
        taskQueue.addTask(stepTask);
        checkLimitSwitch();
    } else {
        stepTask.nextExecutionTime = micros() + 10;
        taskQueue.addTask(stepTask);
    }
}

// Method to safely stop the motor
void CustomStepper::safeStop() {
    Serial.println("Starting safe stop");
    stop();
    runToPosition();
}

// Method to check the limit switch
void CustomStepper::checkLimitSwitch() {
    if (digitalRead(limitSwitchPin) == HIGH) {
        limitPressed = true;
        Serial.println("Limit switch pressed");
    } else {
        limitPressed = false;
    }
}

// // Method to step the motor and check the limit switch
// void CustomStepper::stepWithLimitCheck() {
//     if (isAtLimit()) {
//         stop();  // Stop the motor if the limit switch is triggered
//     } else {
//         runSpeed();  // Step the motor at the current speed
//         stepTask.nextExecutionTime = micros() + getStepInterval();
//         taskQueue.addTask(stepTask);  // Reinsert the task into the queue
//     }
// }

// // Method to start the homing process
// void CustomStepper::initiateHoming() {
//     setMaxSpeed(1000);  // Set a reasonable speed for homing
//     setAcceleration(1000);  // Set a reasonable acceleration for homing
//     homingTask.nextExecutionTime = micros();
//     taskQueue.addTask(homingTask);
// }

// // Method to continue the homing process after each step
// void CustomStepper::continueHoming() {
//     if (isAtLimit()) {
//         stop();  // Stop the motor if the limit switch is triggered
//         setCurrentPosition(0);  // Set the current position as 0 (home)
//         move(500);  // Move away from the limit switch to complete homing
//         homingTask.nextExecutionTime = micros() + 100;  // Delay before moving away
//         taskQueue.addTask(homingTask);  // Reinsert the task to move away
//     } else {
//         move(-1);  // Continue moving towards the limit switch
//         runSpeed();  // Perform a step
//         homingTask.nextExecutionTime = micros() + getStepInterval();
//         taskQueue.addTask(homingTask);  // Reinsert the task for the next step
//     }
// }

// // Method to check if the limit switch is triggered
// bool CustomStepper::isAtLimit() const {
//     return digitalRead(limitSwitchPin) == LOW;
// }

// // Method to set a new target position and start moving
// void CustomStepper::setTargetPosition(long position) {
//     moveTo(position);
//     stepTask.nextExecutionTime = micros();
//     taskQueue.addTask(stepTask);  // Start stepping towards the target position
// }

