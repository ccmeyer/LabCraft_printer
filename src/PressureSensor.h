#ifndef PRESSURESENSOR_H
#define PRESSURESENSOR_H

#include "TaskCommand.h"

class PressureSensor {
public:
    PressureSensor(int TCAAddress, int sensorAddress, TaskQueue& taskQueue);

    void beginCommunication(int sdaPin, int sclPin, int frequency);
    void resetPressure();
    float getPrintPressure() const;  // Get pressure for port 0
    float getRefuelPressure() const;    // Get pressure for port 1
    void startReading();                // Start periodic pressure reading
    void stopReading();                 // Stop periodic pressure reading
    void setReadInterval(unsigned long interval);  // Set the read interval

private:
    int TCAAddress;
    int currentPort = 0;
    int sensorAddress;
    float rawPressure[2];
    float currentPressure[2];
    float readings[2][5];  // Array to store pressure readings for smoothing
    int readIndex[2] = {0, 0};
    float total[2] = {0, 0};
    float average[2] = {0, 0};
    static const int numReadings = 5;
    unsigned long readInterval = 5000;  // Default read interval of 10 msec
    unsigned long switchInterval = 1000;  // Default switch interval of 1 msec
    bool reading = false;

    TaskQueue& taskQueue;
    Task readPressureTask;
    Task switchPortTask;

    void readPressure();
    void smoothPressure();
    void tcaselect();
};

#endif // PRESSURESENSOR_H