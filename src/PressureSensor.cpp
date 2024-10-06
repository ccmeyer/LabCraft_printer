#include "PressureSensor.h"
#include "Logger.h"
#include <Wire.h>

// Constructor
PressureSensor::PressureSensor(int sensorAddress, TaskQueue& taskQueue, Logger& loggerRef)
    : sensorAddress(sensorAddress), taskQueue(taskQueue), loggerRef(loggerRef),
    readPressureTask([this]() { this->smoothPressure(); }, 0) {}

// Method to begin I2C communication with the pressure sensor
void PressureSensor::beginCommunication(int sdaPin, int sclPin, int frequency) {
    Wire.setSDA(sdaPin);
    Wire.setSCL(sclPin);
    Wire.begin();        // Join I2C bus
    Wire.setClock(frequency);
}

// Method to reset the pressure readings
void PressureSensor::resetPressure() {
    for (int thisReading = 0; thisReading < numReadings; thisReading++) {
        readings[thisReading] = 0;
    }
    total = 0;
    average = 0;
    readIndex = 0;
    currentPressure = 0;
    errorCounter = 0;  // Reset error counter on pressure reset
}

// Method to get the current pressure value
float PressureSensor::getPressure() const {
    return currentPressure;
}

// Private method to read raw pressure from the sensor
void PressureSensor::readPressure() {
    byte p1, p2, t1, t2;

    Wire.requestFrom(sensorAddress, 4);
    unsigned long startTime = micros();
    while (Wire.available() < 4 && micros() - startTime < 1000) {
        // Wait for data with a 1 msec timeout
    }

    if (Wire.available() == 4) {
        p1 = Wire.read();
        p2 = Wire.read();
        t1 = Wire.read();
        t2 = Wire.read();

        uint8_t pressureState = (p1 & 0b11000000) >> 6;
        uint16_t pressureRaw = ((p1 & 0b00111111) << 8) | p2;

        rawPressure = pressureRaw;
    } else {
        rawPressure = 0;  // Indicate a failure to read pressure
    }
}

// Private method to smooth the pressure readings and handle errors
void PressureSensor::smoothPressure() {
    loggerRef.logEvent(PRESSURE_READING, TASK_START, 0, LOG_DEBUG);

    if (!reading) {
        return;
    }

    readPressure();

    // Handle 0 pressure readings (errors)
    if (rawPressure == 0) {
        errorCounter++;
        loggerRef.logEvent(PRESSURE_READING, TASK_ERROR, errorCounter, LOG_ERROR);

        if (errorCounter > maxErrors) {
            resetSensorCommunication();  // Reset the sensor after max errors
        }
    } else {
        // Reset error counter if valid reading is received
        errorCounter = 0;

        // Update the smoothing process
        total = total - readings[readIndex];
        readings[readIndex] = rawPressure;
        total = total + readings[readIndex];
        readIndex = readIndex + 1;

        if (readIndex >= numReadings) {
            readIndex = 0;
        }

        average = total / numReadings;
        currentPressure = average;
    }

    // Reschedule the task to run again
    readPressureTask.nextExecutionTime = micros() + readInterval;
    taskQueue.addTask(readPressureTask);

    loggerRef.logEvent(PRESSURE_READING, TASK_END, currentPressure, LOG_DEBUG);
}

// Method to reset sensor communication
void PressureSensor::resetSensorCommunication() {
    loggerRef.logEvent(PRESSURE_READING, TASK_RESET, 0, LOG_ERROR);

    Wire.end();         // End I2C communication
    delay(100);         // Small delay before reconnecting
    Wire.begin();       // Reinitialize I2C communication
}

// Method to set the read interval
void PressureSensor::setReadInterval(int interval) {
    readInterval = interval;
}

// Method to start periodic pressure reading
void PressureSensor::startReading() {
    reading = true;
    setReadInterval(5000);
    readPressureTask.nextExecutionTime = micros() + readInterval;
    taskQueue.addTask(readPressureTask);
}

// Method to stop periodic pressure reading
void PressureSensor::stopReading() {
    reading = false;
}