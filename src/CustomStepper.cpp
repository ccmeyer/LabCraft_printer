#include "CustomStepper.h"
#include <Arduino.h>

// Constructor
CustomStepper::CustomStepper(uint8_t interface, uint8_t stepPin, uint8_t dirPin, int limitSwitchPin, TaskQueue& taskQueue, bool enable)
    : AccelStepper(interface, stepPin, dirPin), limitSwitchPin(limitSwitchPin), taskQueue(taskQueue),
      stepTask([this]() { this->stepWithLimitCheck(); }, 0),
      homingTask([this]() { this->continueHoming(); }, 0) {
    // pinMode(limitSwitchPin, INPUT_PULLUP);
}

// Method to step the motor and check the limit switch
void CustomStepper::stepWithLimitCheck() {
    if (isAtLimit()) {
        stop();  // Stop the motor if the limit switch is triggered
    } else {
        runSpeed();  // Step the motor at the current speed
        stepTask.nextExecutionTime = micros() + getStepInterval();
        taskQueue.addTask(stepTask);  // Reinsert the task into the queue
    }
}

// Method to start the homing process
void CustomStepper::initiateHoming() {
    setMaxSpeed(1000);  // Set a reasonable speed for homing
    setAcceleration(1000);  // Set a reasonable acceleration for homing
    homingTask.nextExecutionTime = millis();
    taskQueue.addTask(homingTask);
}

// Method to continue the homing process after each step
void CustomStepper::continueHoming() {
    if (isAtLimit()) {
        stop();  // Stop the motor if the limit switch is triggered
        setCurrentPosition(0);  // Set the current position as 0 (home)
        move(500);  // Move away from the limit switch to complete homing
        homingTask.nextExecutionTime = millis() + 100;  // Delay before moving away
        taskQueue.addTask(homingTask);  // Reinsert the task to move away
    } else {
        move(-1);  // Continue moving towards the limit switch
        runSpeed();  // Perform a step
        homingTask.nextExecutionTime = micros() + getStepInterval();
        taskQueue.addTask(homingTask);  // Reinsert the task for the next step
    }
}

// Method to check if the limit switch is triggered
bool CustomStepper::isAtLimit() const {
    return digitalRead(limitSwitchPin) == LOW;
}

// Method to set a new target position and start moving
void CustomStepper::setTargetPosition(long position) {
    moveTo(position);
    stepTask.nextExecutionTime = micros();
    taskQueue.addTask(stepTask);  // Start stepping towards the target position
}

// Method to access the _stepInterval variable
unsigned long CustomStepper::getStepInterval() {
    return _stepInterval;  // Accessing protected member from AccelStepper
}

// Method to use computeNewSpeed function
void CustomStepper::updateStepInterval() {
    computeNewSpeed();  // Update the step interval using AccelStepper's method
}