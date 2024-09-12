#ifndef PRESSURESENSOR_H
#define PRESSURESENSOR_H

#include "TaskCommand.h"

class PressureSensor {
public:
    PressureSensor(int sensorAddress, TaskQueue& taskQueue);

    void beginCommunication(int sdaPin, int sclPin, int frequency);
    void resetPressure();
    float getPressure() const;
    void setReadInterval(int interval);  // Set the read interval
    void startReading();                // Start periodic pressure reading
    void stopReading();                 // Stop periodic pressure reading

private:
    int sensorAddress;
    float rawPressure;
    float currentPressure;
    float readings[10];  // Array to store pressure readings for smoothing
    int readIndex = 0;
    float total = 0;
    float average = 0;
    static const int numReadings = 10;
    unsigned long readInterval = 10000;  // Default read interval of 10 msec
    bool reading = false;

    TaskQueue& taskQueue;
    Task readPressureTask;

    void readPressure();
    void smoothPressure();
};

#endif // PRESSURESENSOR_H