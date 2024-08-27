#ifndef COMMUNICATION_H
#define COMMUNICATION_H

#include "TaskCommand.h"
#include "Gripper.h"
#include <Arduino.h>

class Communication {
public:
    Communication(TaskQueue& taskQueue, CommandQueue& commandQueue, Gripper& gripper, int baudRate);

    void beginSerial();
    void sendStatus();
    void readSerial();
    void receiveCommand();
    void parseAndAddCommand();
    void executeCommandTask();
    void IncrementCycleCounter();

private:
    TaskQueue& taskQueue;
    CommandQueue& commandQueue;
    Gripper& gripper;  // Reference to the Gripper object
    int baudRate;
    bool receivingNewData = true;
    bool newData = false;
    static const byte numChars = 64;
    char receivedChars[64];
    int receiveInterval = 10; // Default receive interval of 50 msec
    int sendInterval = 100;  // Default send interval of 10 msec
    int commandExecutionInterval = 20;  // Interval for executing commands
    int receivedCounter = 0;
    int cycleCounter = 0;

    Task receiveCommandTask;       // Task to read serial data
    Task sendStatusTask;          // Task to send status
    Task executeCmdTask;        // Task to execute the next command

    void executeCommand(const Command& cmd);
};
#endif // COMMUNICATION_H