#ifndef PRESSURESENSOR_H
#define PRESSURESENSOR_H

#include "TaskCommand.h"
#include "Logger.h"

class PressureSensor {
public:
    PressureSensor(int sensorAddress, TaskQueue& taskQueue, Logger& loggerRef);

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
    float readings[5];  // Array to store pressure readings for smoothing
    int readIndex = 0;
    float total = 0;
    float average = 0;
    static const int numReadings = 5;
    unsigned long readInterval = 5000;  // Default read interval of 10 msec
    bool reading = false;

    int errorCounter = 0;  // Track sensor errors
    static const int maxErrors = 10;  // Maximum allowed errors before resetting sensor

    TaskQueue& taskQueue;
    Task readPressureTask;

    Logger& loggerRef;

    void readPressure();
    void smoothPressure();
    void resetSensorCommunication();  // New method to reset sensor
};

#endif // PRESSURESENSOR_H