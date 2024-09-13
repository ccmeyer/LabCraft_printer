#include "PressureSensor.h"
#include <Wire.h>

// Constructor
PressureSensor::PressureSensor(int sensorAddress, TaskQueue& taskQueue)
    : sensorAddress(sensorAddress), taskQueue(taskQueue), 
    readPressureTask([this]() { this->smoothPressure(); }, 0) {}

// Method to begin I2C communication with the pressure sensor
void PressureSensor::beginCommunication(int sdaPin, int sclPin, int frequency) {
    Wire.setSDA(sdaPin);
    Wire.setSCL(sclPin);
    Wire.begin();        // Join I2C bus
    Wire.setClock(frequency);
    // Serial.println("Pressure sensor initialized");
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
}

// Method to get the current pressure value
float PressureSensor::getPressure() const{
    return currentPressure;
}

// Private method to read raw pressure from the sensor
void PressureSensor::readPressure() {
    byte p1, p2, t1, t2;

    Wire.requestFrom(sensorAddress, 4);    // Request 4 bytes from peripheral device
    while (Wire.available()) { // Peripheral may send less than requested
        p1 = Wire.read();
        p2 = Wire.read();
        t1 = Wire.read();
        t2 = Wire.read();
    }

    uint8_t pressureState = (p1 & 0b11000000) >> 6;
    uint16_t pressureRaw = ((p1 & 0b00111111) << 8) | p2;

    rawPressure = pressureRaw;
}

// Method to set the read interval
void PressureSensor::setReadInterval(unsigned long interval) {
    readInterval = interval;
} 

// Private method to smooth the pressure readings
void PressureSensor::smoothPressure() {
    if (!reading) {
        return;
    }
    readPressure();

    total = total - readings[readIndex];
    readings[readIndex] = rawPressure;
    total = total + readings[readIndex];
    readIndex = readIndex + 1;

    if (readIndex >= numReadings) {
        readIndex = 0;
    }

    average = total / numReadings;
    currentPressure = average;

    // Reschedule the task to run again
    readPressureTask.nextExecutionTime = micros() + readInterval;  // Adjust interval as needed
    taskQueue.addTask(readPressureTask);
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
    // This can be implemented by simply not rescheduling the task in `smoothPressure()`
}
