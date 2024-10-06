#include "Gripper.h"
#include "Logger.h"
#include <Arduino.h>

// Constructor
Gripper::Gripper(int pumpPin, int valvePin1, int valvePin2, TaskQueue& taskQueue, Logger& loggerRef)
    : pumpPin(pumpPin), valvePin1(valvePin1), valvePin2(valvePin2), taskQueue(taskQueue), loggerRef(loggerRef), pumpActive(false), 
      gripperOpen(false), refreshTaskCounter(0),lastPumpActivationTime(0), busy(false), currentMicros(0),
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
    loggerRef.logEvent(GRIPPER_PUMP_ON, TASK_START, duration, LOG_DEBUG);
    lastPumpActivationTime = micros();

    digitalWrite(pumpPin, HIGH);
    setBusy(true);

    // Update the next execution time for the pumpOffTask
    pumpOffTask.nextExecutionTime = lastPumpActivationTime + duration;
    taskQueue.addTask(pumpOffTask);
    loggerRef.logEvent(GRIPPER_PUMP_ON, TASK_END, 0, LOG_DEBUG);
}

// Method to turn off the pump
void Gripper::turnOffPump() {
    loggerRef.logEvent(GRIPPER_PUMP_OFF, TASK_START, 0, LOG_DEBUG);
    digitalWrite(pumpPin, LOW);
    setBusy(false);
    loggerRef.logEvent(GRIPPER_PUMP_OFF, TASK_END, 0, LOG_DEBUG);
}

// Method to set the open flag
void Gripper::setOpen(bool gripperOpen) {
    noInterrupts();
    this->gripperOpen = gripperOpen;
    interrupts();
}

// Method to open the gripper
void Gripper::openGripper() {
    loggerRef.logEvent(GRIPPER_OPEN, TASK_START, 0, LOG_DEBUG);
    digitalWrite(valvePin1, HIGH);
    digitalWrite(valvePin2, HIGH);
    // Serial.println("Opening gripper");
    turnOnPump(pumpOnDuration);  // Turn on the pump for 500ms to ensure full opening
    setOpen(true);
    loggerRef.logEvent(GRIPPER_OPEN, TASK_END, 0, LOG_DEBUG);
}

// Method to close the gripper
void Gripper::closeGripper() {
    loggerRef.logEvent(GRIPPER_CLOSE, TASK_START, 0, LOG_DEBUG);
    digitalWrite(valvePin1, LOW);
    digitalWrite(valvePin2, LOW);
    // Serial.println("Closing gripper");
    turnOnPump(pumpOnDuration);  // Turn on the pump for 500ms to ensure full closing
    setOpen(false);
    if (refreshTaskCounter == 0){
        startVacuumRefresh();
    }
    loggerRef.logEvent(GRIPPER_CLOSE, TASK_END, 0, LOG_DEBUG);
}

// Method to reset the refresh counter
void Gripper::resetRefreshCounter() {
    noInterrupts();
    refreshTaskCounter = 0;
    interrupts();
}

// Method to refresh the vacuum periodically
void Gripper::refreshVacuum() {
    // Serial.println("--Refreshing vacuum");
    // Serial.println(refreshTaskCounter);
    loggerRef.logEvent(GRIPPER_PUMP_REFRESH, TASK_START, 0, LOG_DEBUG);
    currentMicros = micros();
    if (!pumpActive) {
        // setRefreshTaskScheduled(false);
        changeRefreshCounter(-1);
        return;
    }
    if ((currentMicros - lastPumpActivationTime >= refreshInterval)) {
        // Serial.println("Refreshing vacuum");
        turnOnPump(pumpOnDuration);  // Turn on the pump for 500ms to refresh the vacuum
        changeRefreshCounter(-1);
        // Update the next execution time for the refreshVacuumTask
        if (refreshTaskCounter == 0){
            refreshVacuumTask.nextExecutionTime = currentMicros + refreshInterval;
            taskQueue.addTask(refreshVacuumTask);
            changeRefreshCounter(1);
        }
        
    } else {
        // If the pump is active but the refresh interval hasn't elapsed, reinsert the task
        changeRefreshCounter(-1);
        if (refreshTaskCounter == 0){
            refreshVacuumTask.nextExecutionTime = lastPumpActivationTime + refreshInterval;
            taskQueue.addTask(refreshVacuumTask);
            changeRefreshCounter(1);
        }
    }
    loggerRef.logEvent(GRIPPER_PUMP_REFRESH, TASK_END, 0, LOG_DEBUG);
}

// Method to set the refresh task scheduled flag
void Gripper::changeRefreshCounter(int counterChange) {
    noInterrupts();
    this->refreshTaskCounter += counterChange;
    interrupts();
}

// Method to start the vacuum refresh
void Gripper::startVacuumRefresh() {
    loggerRef.logEvent(GRIPPER_REFRESH_START, TASK_START, 0, LOG_DEBUG);
    if (refreshTaskCounter == 0) {
        pumpActive = true;
        refreshVacuumTask.nextExecutionTime = micros() + refreshInterval;
        taskQueue.addTask(refreshVacuumTask);
        changeRefreshCounter(1);
    }
    loggerRef.logEvent(GRIPPER_REFRESH_START, TASK_END, 0, LOG_DEBUG);
}

// Method to stop the vacuum refresh
void Gripper::stopVacuumRefresh() {
    loggerRef.logEvent(GRIPPER_REFRESH_STOP, TASK_START, 0, LOG_DEBUG);
    // Serial.println("Stopping vacuum refresh");
    pumpActive = false;
    loggerRef.logEvent(GRIPPER_REFRESH_STOP, TASK_END, 0, LOG_DEBUG);
}