#include "PressureRegulator.h"
#include <Arduino.h>

// Constructor
PressureRegulator::PressureRegulator(CustomStepper& stepper, PressureSensor& sensor, TaskQueue& taskQueue,int valvePin)
    : stepper(stepper), sensor(sensor), taskQueue(taskQueue), 
      adjustPressureTask([this]() { this->adjustPressure(); }, 0), 
      resetSyringeTask([this]() { this->resetSyringe(); }, 0), 
      stepTask([this]() { this->stepMotorDirectly(); }, 0),
      regulatingPressure(false), resetInProgress(false),valvePin(valvePin), targetPressure(1638), 
      tolerance(3), cutoff(200), currentPressure(1638), previousPressure(1638), pressureDifference(0), targetReached(true), syringeSpeed(0), 
      adjustInterval(5000), resetInterval(5000), stepInterval(1000), stepperTaskActive(false), lowerBound(-300), upperBound(25000) {
        pinMode(valvePin, OUTPUT);
        digitalWrite(valvePin, LOW);
      }

// Method to setup the pressure regulator
void PressureRegulator::setupRegulator() {
    stepper.setupMotor();
}

// Method to enable the pressure regulator
void PressureRegulator::enableRegulator() {
    stepper.enableMotor();
}

// Method to disable the pressure regulator
void PressureRegulator::disableRegulator() {
    stepper.disableMotor();
}

// Method to begin pressure regulation
void PressureRegulator::beginRegulation() {
    regulatingPressure = true;
    adjustPressureTask.nextExecutionTime = micros();
    taskQueue.addTask(adjustPressureTask);
}

// Method to set the target pressure
void PressureRegulator::setTargetPressureAbsolute(int targetPressure) {
    this->targetPressure = targetPressure;
    targetReached = false;
}

// Method to set the target pressure relative to the current target pressure
void PressureRegulator::setTargetPressureRelative(int targetPressure) {
    this->targetPressure += targetPressure;
    targetReached = false;
}

// Method to get the target pressure
float PressureRegulator::getTargetPressure() {
    return targetPressure;
}

// Method to get the current position of the syringe
long PressureRegulator::getCurrentPosition() {
    return stepper.currentPosition();
}

// Method to get the target position of the syringe
long PressureRegulator::getTargetPosition() {
    return stepper.targetPosition();
}

// Method to stop pressure regulation
void PressureRegulator::stopRegulation() {
    regulatingPressure = false;
    stepper.stop();
    syringeSpeed = 0;

}

// Method to check if the syringe is busy
bool PressureRegulator::isBusy() {
    if ((regulatingPressure && !targetReached) || resetInProgress) {
        return true;
    } else {
        return false;
    }
}
    
// Method to reset the syringe
void PressureRegulator::resetSyringe() {
    if (!resetInProgress) {    // Initiate the reset process
        stepper.stop();
        resetInProgress = true;
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
        digitalWrite(valvePin, LOW);
        if (regulatingPressure) {
            adjustPressureTask.nextExecutionTime = micros();
            taskQueue.addTask(adjustPressureTask); // Resume pressure regulation
        }
    }
}

// Method to adjust the pressure based on current readings
void PressureRegulator::adjustPressure() {
    if (!regulatingPressure || resetInProgress) return;

    currentPressure = sensor.getPressure();

    pressureDifference = currentPressure - targetPressure;

    if (abs(pressureDifference) <= tolerance) {
        syringeSpeed = 0;
    } else if (abs(pressureDifference) > cutoff) {
        syringeSpeed = 1500;
    } else {
        syringeSpeed = map(abs(pressureDifference), tolerance, cutoff, 100, 1500);
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
    } else {
        targetReached = true;
    }

    adjustPressureTask.nextExecutionTime = micros() + adjustInterval;
    taskQueue.addTask(adjustPressureTask);
}

void PressureRegulator::stepMotorDirectly() {
    if (stepper.currentPosition() < lowerBound || stepper.currentPosition() > upperBound) {
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