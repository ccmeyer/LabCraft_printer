#include "Gripper.h"
#include <Arduino.h>

// Constructor
Gripper::Gripper(int pumpPin, int valvePin1, int valvePin2, TaskQueue& taskQueue)
    : pumpPin(pumpPin), valvePin1(valvePin1), valvePin2(valvePin2), taskQueue(taskQueue), pumpActive(false), gripperOpen(false), lastPumpActivationTime(0),
      pumpOffTask([this]() { this->turnOffPump(); }, 0), 
      refreshVacuumTask([this]() { this->refreshVacuum(); }, 0) {
    pinMode(pumpPin, OUTPUT);
    pinMode(valvePin1, OUTPUT);
    pinMode(valvePin2, OUTPUT);
    digitalWrite(pumpPin, LOW);
    digitalWrite(valvePin1, LOW);
    digitalWrite(valvePin2, LOW);
}

// Method to turn on the pump for a specified duration
void Gripper::turnOnPump(int duration) {
    if (!pumpActive){
        Serial.println("Starting vacuum refresh");
        pumpActive = true;
        lastPumpActivationTime = micros();
        refreshVacuumTask.nextExecutionTime = lastPumpActivationTime + refreshInterval;
        taskQueue.addTask(refreshVacuumTask);
    }
    digitalWrite(pumpPin, HIGH);
    lastPumpActivationTime = micros();
    Serial.println("Turning on pump");

    // Update the next execution time for the pumpOffTask
    pumpOffTask.nextExecutionTime = micros() + duration;
    taskQueue.addTask(pumpOffTask);
}

// Method to turn off the pump
void Gripper::turnOffPump() {
    digitalWrite(pumpPin, LOW);
    Serial.println("Turning off pump");
}

// Method to open the gripper
void Gripper::openGripper() {
    digitalWrite(valvePin1, HIGH);
    digitalWrite(valvePin2, HIGH);
    Serial.println("Opening gripper");
    turnOnPump(pumpOnDuration);  // Turn on the pump for 500ms to ensure full opening
    gripperOpen = true;
}

// Method to close the gripper
void Gripper::closeGripper() {
    digitalWrite(valvePin1, LOW);
    digitalWrite(valvePin2, LOW);
    Serial.println("Closing gripper");
    turnOnPump(pumpOnDuration);  // Turn on the pump for 500ms to ensure full closing
    gripperOpen = false;
}

// Method to refresh the vacuum periodically
void Gripper::refreshVacuum() {
    if (pumpActive && (micros() - lastPumpActivationTime >= refreshInterval)) {
        Serial.println("Refreshing vacuum");
        turnOnPump(pumpOnDuration);  // Turn on the pump for 500ms to refresh the vacuum

        // Update the next execution time for the refreshVacuumTask
        refreshVacuumTask.nextExecutionTime = micros() + refreshInterval;
        taskQueue.addTask(refreshVacuumTask);
    } else if (pumpActive) {
        // If the pump is active but the refresh interval hasn't elapsed, reinsert the task
        refreshVacuumTask.nextExecutionTime = lastPumpActivationTime + refreshInterval;
        taskQueue.addTask(refreshVacuumTask);
    } 
}

// Method to stop the vacuum refresh
void Gripper::stopVacuumRefresh() {
    Serial.println("Stopping vacuum refresh");
    pumpActive = false;
}