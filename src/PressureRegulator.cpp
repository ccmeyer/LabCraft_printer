#include "PressureRegulator.h"
#include <Arduino.h>

// Constructor
PressureRegulator::PressureRegulator(CustomStepper& stepper, PressureSensor& sensor, TaskQueue& taskQueue,int valvePin)
    : stepper(stepper), sensor(sensor), taskQueue(taskQueue), 
      adjustPressureTask([this]() { this->adjustPressure(); }, 0), 
      resetSyringeTask([this]() { this->resetSyringe(); }, 0), 
      regulatingPressure(false), resetInProgress(false),valvePin(valvePin), targetPressure(1639), 
      tolerance(3), cutoff(200), currentPressure(1639), pressureDifference(0), syringeSpeed(0), adjustInterval(100) {
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

// Method to begin pressure regulation
void PressureRegulator::beginRegulation(int targetPressure) {
    this->targetPressure = targetPressure;
    regulatingPressure = true;
    adjustPressureTask.nextExecutionTime = micros();
    taskQueue.addTask(adjustPressureTask);
}

// Method to set the target pressure
void PressureRegulator::setTargetPressure(int targetPressure) {
    this->targetPressure = targetPressure;
}

// Method to get the target pressure
float PressureRegulator::getTargetPressure() {
    return targetPressure;
}

// Method to get the current pressure
float PressureRegulator::getCurrentPressure() {
    return sensor.getPressure();
}

// Method to stop pressure regulation
void PressureRegulator::stopRegulation() {
    regulatingPressure = false;
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
    else if (stepper.isBusy()) { // Continue resetting
        // stepper.stepMotor(); // Continue stepping if not done
        resetSyringeTask.nextExecutionTime = micros() + 1000;
        taskQueue.addTask(resetSyringeTask);
    } 
    else {                            // Flag reset complete
        resetInProgress = false;
        digitalWrite(valvePin, LOW);
        if (regulatingPressure) {
            adjustPressureTask.nextExecutionTime = micros();
            taskQueue.addTask(adjustPressureTask); // Resume pressure regulation
        }
    }
}

// Method to adjust the pressure based on current readings
void PressureRegulator::adjustPressure() {
    if (!regulatingPressure || resetInProgress) {   // Only regulate pressure when it's active
        return;
    }

    // Get the current pressure from the sensor
    currentPressure = sensor.getPressure();

    // Calculate the difference between current pressure and target pressure
    pressureDifference = currentPressure - targetPressure;

    // Determine the speed based on the difference
    syringeSpeed = 0;
    if (pressureDifference > cutoff) {
        syringeSpeed = 1500;  // Move quickly when far above target pressure
    } else if (pressureDifference < -cutoff) {
        syringeSpeed = -1500; // Move quickly when far below target pressure
    } else if (abs(pressureDifference) <= tolerance) {
        syringeSpeed = 0;          // Stop moving when within tolerance range
    } else {
        // Map the absolute value of pressure difference to a speed between the min and max speed
        syringeSpeed = map(abs(pressureDifference), tolerance, cutoff, 300, 1500);
        // Apply the sign of the pressure difference to the speed
        syringeSpeed *= (pressureDifference < 0) ? -1 : 1;
    }

    // Set the speed of the stepper motor and move
    stepper.setSpeed(syringeSpeed);
    stepper.moveRelative(syringeSpeed);
    stepper.runSpeed();

    // Check if the syringe needs to be reset
    if (stepper.currentPosition() < -300 || stepper.currentPosition() > 25000) {
        resetSyringe();
    } else {
        // Reinsert the task into the queue
        adjustPressureTask.nextExecutionTime = micros() + adjustInterval;
        taskQueue.addTask(adjustPressureTask);
    }
}
