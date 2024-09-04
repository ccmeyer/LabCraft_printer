#include "Gripper.h"
#include <Arduino.h>

// Constructor
Gripper::Gripper(int pumpPin, int valvePin1, int valvePin2, TaskQueue& taskQueue)
    : pumpPin(pumpPin), valvePin1(valvePin1), valvePin2(valvePin2), taskQueue(taskQueue), pumpActive(false), 
      gripperOpen(false), refreshTaskScheduled(false),lastPumpActivationTime(0), busy(false), currentMicros(0),
      pumpOffTask([this]() { this->turnOffPump(); }, 0), 
      refreshVacuumTask([this]() { this->refreshVacuum(); }, 0) {
    pinMode(pumpPin, OUTPUT);
    pinMode(valvePin1, OUTPUT);
    pinMode(valvePin2, OUTPUT);
    digitalWrite(pumpPin, LOW);
    digitalWrite(valvePin1, LOW);
    digitalWrite(valvePin2, LOW);
}

// Method to check if the gripper is busy
bool Gripper::isBusy() const {
    return busy;
}

// Method to set the busy flag
void Gripper::setBusy(bool busy) {
    noInterrupts();
    this->busy = busy;
    interrupts();
}

bool Gripper::isOpen() const{
    return gripperOpen;
}

// Method to turn on the pump for a specified duration
void Gripper::turnOnPump(int duration) {
    lastPumpActivationTime = micros();

    digitalWrite(pumpPin, HIGH);
    setBusy(true);

    // Update the next execution time for the pumpOffTask
    pumpOffTask.nextExecutionTime = lastPumpActivationTime + duration;
    taskQueue.addTask(pumpOffTask);
}

// Method to turn off the pump
void Gripper::turnOffPump() {
    digitalWrite(pumpPin, LOW);
    setBusy(false);
}

// Method to open the gripper
void Gripper::openGripper() {
    digitalWrite(valvePin1, HIGH);
    digitalWrite(valvePin2, HIGH);
    // Serial.println("Opening gripper");
    turnOnPump(pumpOnDuration);  // Turn on the pump for 500ms to ensure full opening
    gripperOpen = true;
}

// Method to close the gripper
void Gripper::closeGripper() {
    digitalWrite(valvePin1, LOW);
    digitalWrite(valvePin2, LOW);
    // Serial.println("Closing gripper");
    turnOnPump(pumpOnDuration);  // Turn on the pump for 500ms to ensure full closing
    gripperOpen = false;
    if (!refreshTaskScheduled){
        startVacuumRefresh();
    }
}

// Method to refresh the vacuum periodically
void Gripper::refreshVacuum() {
    Serial.println("--Refreshing vacuum");
    currentMicros = micros();
    if (!pumpActive) {
        refreshTaskScheduled = false;
        interrupts();
        return;
    }
    if ((currentMicros - lastPumpActivationTime >= refreshInterval)) {
        // Serial.println("Refreshing vacuum");
        turnOnPump(pumpOnDuration);  // Turn on the pump for 500ms to refresh the vacuum

        // Update the next execution time for the refreshVacuumTask
        refreshVacuumTask.nextExecutionTime = currentMicros + refreshInterval;
        taskQueue.addTask(refreshVacuumTask);
        refreshTaskScheduled = true;
    } else {
        // If the pump is active but the refresh interval hasn't elapsed, reinsert the task
        refreshVacuumTask.nextExecutionTime = lastPumpActivationTime + refreshInterval;
        taskQueue.addTask(refreshVacuumTask);
        refreshTaskScheduled = true;
    }
}

// Method to start the vacuum refresh
void Gripper::startVacuumRefresh() {
    if (!refreshTaskScheduled) {
        pumpActive = true;
        refreshVacuumTask.nextExecutionTime = micros() + refreshInterval;
        taskQueue.addTask(refreshVacuumTask);
        refreshTaskScheduled = true;
    }
}

// Method to stop the vacuum refresh
void Gripper::stopVacuumRefresh() {
    // Serial.println("Stopping vacuum refresh");
    pumpActive = false;
}