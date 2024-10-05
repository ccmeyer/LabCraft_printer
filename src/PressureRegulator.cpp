#include "PressureRegulator.h"
#include "GlobalState.h"
#include <Arduino.h>

// Constructor
PressureRegulator::PressureRegulator(CustomStepper& stepper, PressureSensor& sensor, TaskQueue& taskQueue,int valvePin)
    : stepper(stepper), sensor(sensor), taskQueue(taskQueue), 
      adjustPressureTask([this]() { this->adjustPressure(); }, 0), 
      resetSyringeTask([this]() { this->resetSyringe(); }, 0), 
      homeSyringeTask([this]() { this->homeSyringeCheck(); }, 0),
      stepTask([this]() { this->stepMotorDirectly(); }, 0),
      regulatingPressure(false), resetInProgress(false),valvePin(valvePin), targetPressure(1638), 
      tolerance(10), cutoff(200), homing(false), currentPressure(1638), previousPressure(1638), pressureDifference(0), targetReached(true), syringeSpeed(0), targetReachedCounter(0),
      adjustInterval(5000), resetInterval(5000), stepInterval(1000), stepperTaskActive(false), lowerBound(-300), upperBound(25000), maxSpeed(1500), minSpeed(300), motorPosition(0), totalRange(25000) {
        pinMode(valvePin, OUTPUT);
        digitalWrite(valvePin, LOW);
      }

// Method to setup the pressure regulator
void PressureRegulator::setupRegulator() {
    stepper.setupMotor();
    stepper.setProperties(6000, 24000);
}

// Method to enable the pressure regulator
void PressureRegulator::enableRegulator() {
    stepper.enableMotor();
}

// Method to disable the pressure regulator
void PressureRegulator::disableRegulator() {
    stepper.disableMotor();
}

// Method to set the pressure tolerance
void PressureRegulator::setPressureTolerance(int tolerance) {
    this->tolerance = tolerance;
    deadband = tolerance / 2.0;
}

// Method to home the syringe
void PressureRegulator::homeSyringe() {
    homing = true;
    syringeSpeed = 0;
    digitalWrite(valvePin, HIGH);
    stepper.beginHoming();
    homeSyringeTask.nextExecutionTime = micros() + 1000;
    taskQueue.addTask(homeSyringeTask);
}

// Method to check if the syringe is homed
void PressureRegulator::homeSyringeCheck() {
    if (currentState == PAUSED) {
        homeSyringeTask.nextExecutionTime = micros() + 10000;
        taskQueue.addTask(homeSyringeTask);
        return;
    }
    if (stepper.isHomingComplete()) {
        digitalWrite(valvePin, LOW);
        homing = false;
        stepperTaskActive = false;
        if (regulatingPressure) {
            adjustPressureTask.nextExecutionTime = micros();
            taskQueue.addTask(adjustPressureTask); // Resume pressure regulation
        }
    } else {
        homeSyringeTask.nextExecutionTime = micros() + 10000;
        taskQueue.addTask(homeSyringeTask);
    }
}

// Method to begin pressure regulation
void PressureRegulator::beginRegulation() {
    regulatingPressure = true;
    adjustPressureTask.nextExecutionTime = micros();
    taskQueue.addTask(adjustPressureTask);
}

// Method to restart pressure regulation task if already regulating
void PressureRegulator::restartRegulation() {
    if (regulatingPressure) {
        adjustPressureTask.nextExecutionTime = micros();
        taskQueue.addTask(adjustPressureTask);
    }
}

// Method to set the target pressure
void PressureRegulator::setTargetPressureAbsolute(int targetPressure) {
    this->targetPressure = targetPressure;
    resetTargetReached();
}

// Method to set the target pressure relative to the current target pressure
void PressureRegulator::setTargetPressureRelative(int targetPressure) {
    this->targetPressure += targetPressure;
    resetTargetReached();
}

// Method to get the target pressure
float PressureRegulator::getTargetPressure() const{
    return targetPressure;
}

// Method to get the current position of the syringe
long PressureRegulator::getCurrentPosition() const{
    return stepper.currentPosition();
}

// Method to get the target position of the syringe
long PressureRegulator::getTargetPosition() const{
    return stepper.targetPosition();
}

// Method to stop pressure regulation
void PressureRegulator::stopRegulation() {
    regulatingPressure = false;
    stepper.stop();
    syringeSpeed = 0;

}

// Method to check if the syringe is busy
bool PressureRegulator::isBusy() const{
    if ((regulatingPressure && !targetReached) || resetInProgress || stepper.isBusy()) {
        return true;
    } else {
        return false;
    }
}

// Method to check if pressure regulation is active
bool PressureRegulator::isRegulating() const{
    return regulatingPressure;
}

// Method to reset the state of the regulator
void PressureRegulator::resetState() {
    resetInProgress = false;
    homing = false;
    syringeSpeed = 0;
    targetReached = true;
    targetReachedCounter = 0;
    stepperTaskActive = false;
    targetPressure = sensor.getPressure();
    setPressureTolerance(10);
    setAdjustInterval(5000);
    stepper.resetState();
    digitalWrite(valvePin, LOW);
}

// Method to reset the targetReached flag
void PressureRegulator::resetTargetReached() {
    targetReached = false;
    targetReachedCounter = 0;
}

// Method to set the adjust interval
void PressureRegulator::setAdjustInterval(unsigned long interval) {
    adjustInterval = interval;
}

// Method to check if the syringe is being reset
bool PressureRegulator::isResetInProgress() const {
    return resetInProgress;
}
    
// Method to reset the syringe
void PressureRegulator::resetSyringe() {
    if (currentState == PAUSED) {
        resetSyringeTask.nextExecutionTime = micros() + 10000;
        taskQueue.addTask(resetSyringeTask);
        return;
    }
    if (!resetInProgress) {    // Initiate the reset process
        stepper.stop();
        resetInProgress = true;
        sensor.setReadInterval(5000);  // Reset the read interval to 5ms
        setAdjustInterval(5000); // Reset the adjust interval to 5ms
        digitalWrite(valvePin, HIGH);
        stepper.setTargetPosition(0);
        resetSyringeTask.nextExecutionTime = micros();
        taskQueue.addTask(resetSyringeTask);
    } 
    else if (stepper.distanceToGo() != 0 ) { // Continue resetting
        resetSyringeTask.nextExecutionTime = micros() + resetInterval;
        taskQueue.addTask(resetSyringeTask);
    } 
    else {                            // Flag reset complete
        resetInProgress = false;
        stepperTaskActive = false;
        resetTargetReached();
        digitalWrite(valvePin, LOW);
        if (regulatingPressure) {
            adjustPressureTask.nextExecutionTime = micros();
            taskQueue.addTask(adjustPressureTask); // Resume pressure regulation
        }
    }
}

// Method to adjust the pressure based on current readings
void PressureRegulator::adjustPressure() {
    noInterrupts();
    if (currentState == PAUSED) {
        adjustPressureTask.nextExecutionTime = micros() + 10000;
        taskQueue.addTask(adjustPressureTask);
        return;
    }
    if (!regulatingPressure || resetInProgress || homing) {
        interrupts();
        return;
    }

    currentPressure = sensor.getPressure();

    pressureDifference = currentPressure - targetPressure;

    maxSpeed = 2000;
    minSpeed = 350;

    // Deadband buffer to avoid small fluctuations causing motor movements
    if (abs(pressureDifference) <= 1 && !targetReached) {
        syringeSpeed = 0;
        targetReachedCounter++;
        if (targetReachedCounter >= 20) {
            targetReached = true;
            targetReachedCounter = 0;
        }
    } 
    // If we are already within the tolerance but small fluctuations occur, do nothing
    else if (targetReached && abs(pressureDifference) <= tolerance) {
        syringeSpeed = 0;
    }
    // Move the syringe faster if we're far from the target
    else if (abs(pressureDifference) > cutoff) {
        syringeSpeed = maxSpeed;
        resetTargetReached();
    } 
    // Adjust speed based on how far off we are
    else {
        syringeSpeed = map(abs(pressureDifference), 0, cutoff, minSpeed, maxSpeed);
        resetTargetReached();
    }

    syringeSpeed *= (pressureDifference < 0) ? 1 : -1;

    // Set the step interval based on the syringe speed
    if (syringeSpeed != 0) {
        stepInterval = 1000000L / abs(syringeSpeed); // Calculate step interval based on speed
        stepper.setSpeed(syringeSpeed);
        if (!stepperTaskActive) {
            stepTask.nextExecutionTime = micros();
            taskQueue.addTask(stepTask);
            stepperTaskActive = true;
        }
    }

    adjustPressureTask.nextExecutionTime = micros() + adjustInterval;
    taskQueue.addTask(adjustPressureTask);
    interrupts();
}

void PressureRegulator::stepMotorDirectly() {
    if (currentState == PAUSED) {
        stepTask.nextExecutionTime = micros() + 10000;
        taskQueue.addTask(stepTask);
        return;
    }
    // Prevent direct motor stepping while syringe reset is in progress
    if (resetInProgress) {
        // Exit the function early if reset is in progress
        return;
    }
    if (stepper.currentPosition() > upperBound) {
        resetSyringe();
        return;
    } else if (stepper.currentPosition() < lowerBound) {
        setTargetPressureAbsolute(1638);
        resetSyringe();
        return;
    }
    if (syringeSpeed != 0) {
        if (syringeSpeed > 0) {
            stepper.manualStepForward();  // Directly step forward
        } else {
            stepper.manualStepBackward(); // Directly step backward
        }
        stepTask.nextExecutionTime = micros() + stepInterval;
        taskQueue.addTask(stepTask);
    } else {
        stepperTaskActive = false;
    }
}