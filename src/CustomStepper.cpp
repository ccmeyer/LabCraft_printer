#include "CustomStepper.h"
#include "GlobalState.h"
#include "Logger.h"
#include <Arduino.h>

// Constructor
CustomStepper::CustomStepper(uint8_t interface, uint8_t enablePin, uint8_t stepPin, uint8_t dirPin, int limitSwitchPin, TaskQueue& taskQueue, Logger& loggerRef, bool invertDir)
    : AccelStepper(interface, stepPin, dirPin),enablePin(enablePin), limitSwitchPin(limitSwitchPin), taskQueue(taskQueue), loggerRef(loggerRef), limitPressed(false), invertDir(invertDir), 
      homingComplete(false), homingStage(HOMING_COMPLETE), busy(false),maxSpeed(4000), maxAcceleration(24000), originalSpeed(4000), originalAcceleration(24000),
      stepTask([this]() { this->stepMotor(); }, 0),
      homingTask([this]() { this->continueHoming(); }, 0) {
    pinMode(limitSwitchPin, INPUT);
}

// Method to access the _stepInterval variable
unsigned long CustomStepper::getStepInterval() {
    return _stepInterval;  // Accessing protected member from AccelStepper
}

// Method to check if the motor is moving forward
bool CustomStepper::movingForward() {
    return _direction == DIRECTION_CW;  // Check the direction of the motor
}

// Method to use computeNewSpeed function
void CustomStepper::updateStepInterval() {
    computeNewSpeed();  // Update the step interval using AccelStepper's method
}

// Method to check if the motor is busy
bool CustomStepper::isBusy() const{
    return busy;
}

// Method to set up the motor
void CustomStepper::setupMotor() {
    setMaxSpeed(maxSpeed);  // Set a reasonable speed for the motor
    setAcceleration(maxAcceleration);  // Set a reasonable acceleration for the motor
    setEnablePin(enablePin);
    setPinsInverted(invertDir, false, true);
    disableOutputs();
}

// Method to set the motor properties
void CustomStepper::setProperties(int newSpeed, int newAcceleration) {
    maxSpeed = newSpeed;
    maxAcceleration = newAcceleration;
    originalSpeed = newSpeed;
    originalAcceleration = newAcceleration;
    setMaxSpeed(maxSpeed);
    setAcceleration(maxAcceleration);
}   

// Method to reset the acceleration
void CustomStepper::resetProperties() {
    setProperties(originalSpeed, originalAcceleration);
}

// Method to enable the motor
void CustomStepper::enableMotor() {
    loggerRef.logEvent(STEPPER_ENABLE, TASK_START, enablePin, LOG_INFO);
    enableOutputs();
    loggerRef.logEvent(STEPPER_ENABLE, TASK_END, enablePin, LOG_INFO);
}

void CustomStepper::disableMotor() {
    loggerRef.logEvent(STEPPER_DISABLE, TASK_START, enablePin, LOG_INFO);
    disableOutputs();
    loggerRef.logEvent(STEPPER_DISABLE, TASK_END, enablePin, LOG_INFO);
}

// Method to set the target position
void CustomStepper::setTargetPosition(long position) {
    loggerRef.logEvent(STEPPER_MOVE, TASK_START, enablePin, LOG_INFO);
    moveTo(position);
    busy = true;
    stepTask.nextExecutionTime = micros();
    taskQueue.addTask(stepTask);
}

// Method to move the motor by a relative distance
void CustomStepper::moveRelative(long distance) {
    loggerRef.logEvent(STEPPER_MOVE, TASK_START, enablePin, LOG_INFO);
    move(distance);
    busy = true;
    stepTask.nextExecutionTime = micros();
    taskQueue.addTask(stepTask);
}

// Method to perform a single step
void CustomStepper::stepMotor() {
    if (currentState == PAUSED) {
        stepTask.nextExecutionTime = micros() + 10000;
        taskQueue.addTask(stepTask);
        return;
    }
    
    if (distanceToGo() == 0) {
        stop();
        busy = false;
        loggerRef.logEvent(STEPPER_MOVE, TASK_END, enablePin, LOG_INFO);
    } else if (limitPressed && !movingForward()) {
        safeStop();
        setAcceleration(maxAcceleration);
        busy = false;
        limitPressed = false;
        loggerRef.logEvent(STEPPER_MOVE, TASK_ERROR, enablePin, LOG_ERROR);
    } else if (runSpeed()) {
        updateStepInterval();
        stepTask.nextExecutionTime = micros() + getStepInterval()-100;
        taskQueue.addTask(stepTask);
        checkLimitSwitch();
    } else {
        stepTask.nextExecutionTime = micros() + 10;
        taskQueue.addTask(stepTask);
    }
}

// Method to safely stop the motor
void CustomStepper::safeStop() {
    setAcceleration(30000);
    stop();
    runToPosition();
}

// Method to stop the motor and reset the busy flag
void CustomStepper::completeStop() {
    stop();
    busy = false;
}

// Method to reset the state of the motor
void CustomStepper::resetState() {
    setSpeed(0);
    stop();
    busy = false;
    limitPressed = false;
    homingStage = HOMING_COMPLETE;
    resetProperties();
    moveTo(currentPosition());
    updateStepInterval();
}

// Method to check the limit switch
void CustomStepper::checkLimitSwitch() {
    if (digitalRead(limitSwitchPin) == HIGH) {
        limitPressed = true;
    } else {
        limitPressed = false;
    }
}

// Method to check if homing is complete
bool CustomStepper::isHomingComplete() const{
    return homingComplete;
}

// Method to start the homing process
void CustomStepper::beginHoming() {
    loggerRef.logEvent(STEPPER_HOMING, TASK_START, enablePin, LOG_INFO);
    homingComplete = false;
    homingStage = HOMING_START;
    busy = true;
    homingTask.nextExecutionTime = micros();
    taskQueue.addTask(homingTask);
}

// Method to continue the homing process
void CustomStepper::continueHoming() {
    if (currentState == PAUSED) {
        homingTask.nextExecutionTime = micros() + 10000;
        taskQueue.addTask(homingTask);
        return;
    }
    switch (homingStage) {
        case HOMING_START:
            // Serial.println("Starting homing process");
            setMaxSpeed(maxSpeed / 2.5);
            setAcceleration(maxAcceleration / 4);
            move(-50000);
            updateStepInterval();
            homingStage = TOWARD_SWITCH;
            break;
        case TOWARD_SWITCH:
            if (limitPressed) {
                // Serial.println("Limit switch pressed");
                safeStop();
                setMaxSpeed(maxSpeed / 30);
                setAcceleration(maxAcceleration / 30);
                move(10000);
                updateStepInterval();
                homingStage = AWAY_FROM_SWITCH;
            } else {
                runSpeed();
                updateStepInterval();
                checkLimitSwitch();
            }
            break;
        case AWAY_FROM_SWITCH:
            if (!limitPressed) {
                // Serial.println("Limit switch not pressed");
                setCurrentPosition(0);
                safeStop();
                setMaxSpeed(maxSpeed / 2.5);
                setAcceleration(maxAcceleration / 2.5);
                moveTo(500);
                updateStepInterval();
                homingStage = RESET_POS;
            } else {
                runSpeed();
                updateStepInterval();
                checkLimitSwitch();
            }
            break;
        case RESET_POS:
            if (distanceToGo() == 0) {
                // Serial.println("Position reset");
                safeStop();
                setMaxSpeed(maxSpeed);
                setAcceleration(maxAcceleration);
                updateStepInterval();
                homingStage = HOMING_COMPLETE;
                homingComplete = true;
                busy = false;
                loggerRef.logEvent(STEPPER_HOMING, TASK_END, enablePin, LOG_INFO);
            } else {
                runSpeed();
                updateStepInterval();
                checkLimitSwitch();
            }
            break;
        default:
            break;
    }
    if (!homingComplete) {
        homingTask.nextExecutionTime = micros() + 10;
        taskQueue.addTask(homingTask);
    }
}

// Method to perform a manual step in the forward direction
void CustomStepper::manualStepForward() {
    stepForward();
}

// Method to perform a manual step in the backward direction
void CustomStepper::manualStepBackward() {
    stepBackward();
}