#ifndef PRESSURESENSOR_H
#define PRESSURESENSOR_H

#include "TaskCommand.h"
#include <Wire.h>

class PressureSensor {
public:
    PressureSensor(int sensorAddress, TaskQueue& taskQueue);

    void beginCommunication(int sdaPin, int sclPin, int frequency);
    void resetPressure();
    float getPressure();
    float readPressure(int port);
    float smoothPressure();
    void schedulePressureRead(int interval);
    
private:
    int sensorAddress;
    TaskQueue& taskQueue;  // Reference to the global TaskQueue

    float readings[10];   // Array to hold pressure readings for smoothing
    int numReadings = 10; // Number of readings for smoothing
    int readIndex = 0;    // Index of the current reading
    float total = 0;      // Total of all readings
    float average = 0;    // Average of the readings
    float currentPressure = 0; // Current pressure value
    uint8_t currentState;

    Task readPressureTask; // Task to periodically read the pressure

    void readPressureTaskFunction(); // Function that the task will call
};

#endif // PRESSURESENSOR_H
