#include "PressureSensor.h"
// #include <Wire.h>
byte p1, p2, t1, t2;

PressureSensor::PressureSensor(int TCAAddress, int sensorAddress) : TCAAddress(TCAAddress),sensorAddress(sensorAddress) {}

void PressureSensor::beginCommunication(int sdaPin, int sclPin) {
    Wire.setSDA(sdaPin);
    Wire.setSCL(sclPin);
    Wire.begin();        // join i2c bus (address optional for master)
}

void PressureSensor::resetPressure() {
    // Set all initial pressure readings to 0
    for (int thisReading = 0; thisReading < numReadings; thisReading++) {
        readings[thisReading] = 0;
  }
}

float PressureSensor::getPressure() {
    return currentPressure;
}

void PressureSensor::tcaselect(int port) {
  // Sets the multiplexer to i2c port i
  if (port == currentPort && TCAset == true) return;
 
  Wire.beginTransmission(TCAAddress);
  Wire.write(1 << port);
  Wire.endTransmission();
  TCAset = true;
}

float PressureSensor::readPressure(int port) {
    tcaselect(port);
    Wire.requestFrom(40, 4);    // Request 4 bytes from peripheral device
    while (Wire.available()) { // peripheral may send less than requested
        p1 = Wire.read();
        p2 = Wire.read();
        t1 = Wire.read();
        t2 = Wire.read();
    }
    uint8_t pressureState = (p1 & 0b11000000) >> 6;
    uint16_t pressureRaw = ((p1 & 0b00111111) << 8) | p2;
    currentState = pressureState;
    currentPressure = pressureRaw;
    return currentPressure;
}

float PressureSensor::smoothPressure() {
    // Adapted from https://docs.arduino.cc/built-in-examples/analog/Smoothing/
    float pressure = readPressure(0);
    // if (measuredPressure.state == 0) {
    //     total = total - readings[readIndex];
    //     readings[readIndex] = pressure;
    //     total = total + readings[readIndex];
    //     readIndex = (readIndex + 1) % numReadings; // Use modulo to wrap around
    //     average = total / numReadings;
    //     measuredPressure.data = average;
    // }
    total = total - readings[readIndex];
    readings[readIndex] = pressure;
    total = total + readings[readIndex];
    readIndex = readIndex + 1;
    if (readIndex >= numReadings) {
        readIndex = 0;
        }
    average = total / numReadings;
    currentPressure = average;
    return currentPressure;
}
