#ifndef COMMUNICATION_H
#define COMMUNICATION_H

#include "TaskCommand.h"
#include <Arduino.h>

class Communication {
public:
    Communication(TaskQueue& taskQueue, int baudRate);

    void beginSerial();
    void sendStatus();
    void readSerial();
    void receiveCommand();
    void IncrementCycleCounter();

private:
    TaskQueue& taskQueue;
    int baudRate;
    bool receivingNewData = true;
    bool newData = false;
    static const byte numChars = 64;
    char receivedChars[64];
    int receiveInterval = 10; // Default receive interval of 50 msec
    int sendInterval = 100;  // Default send interval of 10 msec
    int receivedCounter = 0;
    int cycleCounter = 0;

    Task receiveCommandTask;       // Task to read serial data
    Task sendStatusTask;          // Task to send status
};
#endif // COMMUNICATION_H