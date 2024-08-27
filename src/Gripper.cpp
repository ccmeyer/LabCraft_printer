#include "Gripper.h"
#include <Arduino.h>

// Constructor
Gripper::Gripper(int pumpPin, int valveOpenPin, int valveClosePin, TaskQueue& taskQueue)
    : pumpPin(pumpPin), valveOpenPin(valveOpenPin), valveClosePin(valveClosePin), taskQueue(taskQueue), pumpActive(false), gripperOpen(false), lastPumpActivationTime(0),
      pumpOffTask([this]() { this->turnOffPump(); }, 0), refreshVacuumTask([this]() { this->refreshVacuum(); }, 0) {
    // pinMode(pumpPin, OUTPUT);
    // pinMode(valveOpenPin, OUTPUT);
    // pinMode(valveClosePin, OUTPUT);
}

// Method to turn on the pump for a specified duration
void Gripper::turnOnPump(int duration) {
    // digitalWrite(pumpPin, HIGH);
    if (!pumpActive){
        Serial.println("Starting vacuum refresh");
        pumpActive = true;
        lastPumpActivationTime = micros();
        refreshVacuumTask.nextExecutionTime = lastPumpActivationTime + refreshInterval;
        taskQueue.addTask(refreshVacuumTask);
    }
    lastPumpActivationTime = micros();
    Serial.println("Turning on pump");

    // Update the next execution time for the pumpOffTask
    pumpOffTask.nextExecutionTime = micros() + duration;
    taskQueue.addTask(pumpOffTask);
}

// Method to turn off the pump
void Gripper::turnOffPump() {
    // digitalWrite(pumpPin, LOW);
    Serial.println("Turning off pump");
    // pumpActive = false;
}

// Method to open the gripper
void Gripper::openGripper() {
    // digitalWrite(valveOpenPin, HIGH);
    Serial.println("Opening gripper");
    turnOnPump(500);  // Turn on the pump for 500ms to ensure full opening
    gripperOpen = true;
}

// Method to close the gripper
void Gripper::closeGripper() {
    // digitalWrite(valveClosePin, HIGH);
    Serial.println("Closing gripper");
    turnOnPump(500);  // Turn on the pump for 500ms to ensure full closing
    gripperOpen = false;
}

// Method to refresh the vacuum periodically
void Gripper::refreshVacuum() {
    if (pumpActive && (micros() - lastPumpActivationTime >= refreshInterval)) {
        Serial.println("Refreshing vacuum");
        turnOnPump(500);  // Turn on the pump for 500ms to refresh the vacuum

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






// // Constructor
// Gripper::Gripper(int pumpPin, int valveOpenPin, int valveClosePin, TaskQueue& taskQueue)
//     : pumpPin(pumpPin), valveOpenPin(valveOpenPin), valveClosePin(valveClosePin), taskQueue(taskQueue), pumpActive(false), gripperOpen(false), lastPumpActivationTime(0) {
//     pinMode(pumpPin, OUTPUT);
//     pinMode(valveOpenPin, OUTPUT);
//     pinMode(valveClosePin, OUTPUT);
// }

// // Method to turn on the pump for a specified duration
// void Gripper::turnOnPump(int duration) {
//     digitalWrite(pumpPin, HIGH);
//     pumpActive = true;
//     lastPumpActivationTime = micros();

//     // Schedule a task to turn off the pump after the specified duration
//     pumpOffTask = Task(std::bind(&Gripper::turnOffPump, this), micros() + duration, 0);
//     taskQueue.addTask(pumpOffTask);
// }

// // Method to turn off the pump
// void Gripper::turnOffPump() {
//     digitalWrite(pumpPin, LOW);
//     pumpActive = false;
// }

// // Method to open the gripper
// void Gripper::openGripper() {
//     digitalWrite(valveClosePin, LOW); // Ensure close valve is off
//     digitalWrite(valveOpenPin, HIGH); // Open the gripper
//     turnOnPump(500); // Keep the pump running for 5 seconds to ensure full opening
//     gripperOpen = true;

//     // Schedule vacuum refresh if needed
//     refreshVacuumTask.nextExecutionTime = micros() + 60000;
//     taskQueue.addTask(refreshVacuumTask);
// }

// // Method to close the gripper
// void Gripper::closeGripper() {
//     digitalWrite(valveOpenPin, LOW);  // Ensure open valve is off
//     digitalWrite(valveClosePin, HIGH); // Close the gripper
//     turnOnPump(5000); // Keep the pump running for 5 seconds to ensure full closing
//     gripperOpen = false;

//     // Schedule vacuum refresh if needed
//     refreshVacuumTask.nextExecutionTime = micros() + 60000;
//     taskQueue.addTask(refreshVacuumTask);
// }

// // Method to refresh the vacuum at regular intervals
// void Gripper::refreshVacuum(int refreshInterval) {
//     unsigned long currentTime = micros();
//     if ((currentTime - lastPumpActivationTime) >= refreshInterval) {
//         turnOnPump(5000); // Refresh the vacuum by running the pump for 5 seconds
//     }

//     // Reinsert the task to refresh the vacuum again after the specified interval
//     refreshVacuumTask.nextExecutionTime = lastPumpActivationTime + refreshInterval;
//     taskQueue.addTask(refreshVacuumTask);
// }

// // Method to stop the vacuum refresh
// void Gripper::stopVacuumRefresh() {
//     // Simply remove the refresh vacuum task from the queue
//     refreshVacuumTask = {};  // Resetting the task effectively stops it from being re-added
// }

// // Helper method to schedule vacuum refresh
// void Gripper::scheduleRefreshVacuum(int refreshInterval) {
//     refreshVacuumTask = {std::bind(&Gripper::refreshVacuum, this, refreshInterval), micros() + refreshInterval, 0};
//     taskQueue.addTask(refreshVacuumTask);
// }