#ifndef COMMUNICATION_H
#define COMMUNICATION_H

#include "TaskCommand.h"
#include "Gripper.h"
#include "CustomStepper.h"
#include "PressureSensor.h"
#include "PressureRegulator.h"
#include "DropletPrinter.h"
#include "Flash.h"
#include "Coordinator.h"
#include <Arduino.h>

enum StatusStep {
    CYCLE_COUNT,
    LAST_COMPLETED_CMD,
    LAST_ADDED_CMD,
    CURRENT_CMD,
    X,
    Y,
    Z,
    P,
    R,
    TARGET_X,
    TARGET_Y,
    TARGET_Z,
    TARGET_P,
    TARGET_R,
    GRIPPER,
    PRESSURE_P,
    PRESSURE_R,
    TARGET_PRINT,
    TARGET_REFUEL,
    PULSE_WIDTH_PRINT,
    PULSE_WIDTH_REFUEL,
    MICROS,
    FLASH_WIDTH,
    FLASHES
};

class Communication {
public:
    Communication(TaskQueue& taskQueue, CommandQueue& commandQueue, Gripper& gripper, 
    CustomStepper& stepperX, CustomStepper& stepperY, CustomStepper& stepperZ, 
    PressureSensor& pressureSensor, PressureRegulator& printRegulator, PressureRegulator& refuelRegulator, DropletPrinter& printer,
    Flash& flash, Coordinator& coord, int baudRate);

    void beginSerial();
    void startTasks();
    void sendStatus();
    void readSerial();
    void receiveCommand();
    void parseAndAddCommand();
    void executeCommandTask();
    bool checkIfFree() const;
    void startWaiting(unsigned long waitTime);
    void stopWaiting();
    void IncrementCycleCounter();

private:
    TaskQueue& taskQueue;
    CommandQueue& commandQueue;
    Gripper& gripper;  // Reference to the Gripper object
    CustomStepper& stepperX;  // Reference to the CustomStepper object
    CustomStepper& stepperY;  // Reference to the CustomStepper object
    CustomStepper& stepperZ;  // Reference to the CustomStepper object
    PressureSensor& pressureSensor;  // Reference to the PressureSensor object
    PressureRegulator& printRegulator;  // Reference to the PressureRegulator object
    PressureRegulator& refuelRegulator;  // Reference to the PressureRegulator object
    DropletPrinter& printer;  // Reference to the DropletPrinter object
    Flash& flash;       // Reference to the Flash object
    Coordinator& coord;  // Reference to the Coordinator object
    StatusStep statusStep = CYCLE_COUNT;

    int baudRate;
    bool receivingNewData = true;
    bool newData = false;
    static const byte numChars = 64;
    char receivedChars[64];
    unsigned long receiveInterval = 20000; // Default receive interval of 50 msec
    unsigned long sendInterval = 10000;  // Default send interval of 10 msec
    unsigned long commandExecutionInterval = 10000;  // Interval for executing commands
    int receivedCounter = 0;
    int cycleCounter = 0;
    int currentCmdNum = 0;
    int lastCompletedCmdNum = 0;
    int lastAddedCmdNum = 0;
    bool waiting = false;

    Task receiveCommandTask;       // Task to read serial data
    Task sendStatusTask;          // Task to send status
    Task executeCmdTask;        // Task to execute the next command
    Task waitTask;              // Task to wait for a certain time

    void executeCommand(const Command& cmd);
};
#endif // COMMUNICATION_H