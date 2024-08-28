#ifndef COMMUNICATION_H
#define COMMUNICATION_H

#include "TaskCommand.h"
#include "Gripper.h"
#include "CustomStepper.h"
#include <Arduino.h>

enum StatusStep {
    CYCLE_COUNT,
    LAST_COMPLETED_CMD,
    LAST_ADDED_CMD,
    CURRENT_CMD,
    X,
    Y,
    Z,
    TARGET_X,
    TARGET_Y,
    TARGET_Z,
    GRIPPER
};

class Communication {
public:
    Communication(TaskQueue& taskQueue, CommandQueue& commandQueue, Gripper& gripper, 
    CustomStepper& stepperX, CustomStepper& stepperY, CustomStepper& stepperZ, int baudRate);

    void beginSerial();
    void sendStatus();
    void readSerial();
    void receiveCommand();
    void parseAndAddCommand();
    void executeCommandTask();
    bool checkIfFree();
    void IncrementCycleCounter();

private:
    TaskQueue& taskQueue;
    CommandQueue& commandQueue;
    Gripper& gripper;  // Reference to the Gripper object
    CustomStepper& stepperX;  // Reference to the CustomStepper object
    CustomStepper& stepperY;  // Reference to the CustomStepper object
    CustomStepper& stepperZ;  // Reference to the CustomStepper object
    StatusStep statusStep = CYCLE_COUNT;

    int baudRate;
    bool receivingNewData = true;
    bool newData = false;
    static const byte numChars = 64;
    char receivedChars[64];
    int receiveInterval = 10000; // Default receive interval of 50 msec
    int sendInterval = 10000;  // Default send interval of 10 msec
    int commandExecutionInterval = 10000;  // Interval for executing commands
    int receivedCounter = 0;
    int cycleCounter = 0;
    int currentCmdNum = 0;
    int lastCompletedCmdNum = 0;
    int lastAddedCmdNum = 0;


    Task receiveCommandTask;       // Task to read serial data
    Task sendStatusTask;          // Task to send status
    Task executeCmdTask;        // Task to execute the next command

    void executeCommand(const Command& cmd);
};
#endif // COMMUNICATION_H