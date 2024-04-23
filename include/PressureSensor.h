// PressureSensor.h
#ifndef PRESSURE_SENSOR_H
#define PRESSURE_SENSOR_H

#include <Wire.h>
#include <Arduino.h>

class PressureSensor {
public:
    PressureSensor(int TCAAddress, int sensorAddress);
    void beginCommunication(int sdaPin, int sclPin, int frequency);
    void resetPressure();
    float getPressure();
    float readPressure(int port);
    void tcaselect(int port);
    float smoothPressure();

private:
    // struct PressureData {
    //     uint8_t state = 0;
    //     uint16_t data = 0;
    // };
    // PressureData measuredPressure;

    int currentPort = 0;
    bool TCAset = false;
    int TCAAddress;
    int sensorAddress;

    // For smoothing
    uint8_t currentState = 0;
    uint16_t currentPressure = 0;
    
    static const int numReadings = 10;
    int readings[numReadings];
    int readIndex = 0;
    long total = 0;
    float average = 0;
};

#endif
