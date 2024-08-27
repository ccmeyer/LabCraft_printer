#include "Communication.h"
#include <Arduino.h>

// Constructor
Communication::Communication(TaskQueue& taskQueue, CommandQueue& commandQueue, Gripper& gripper, 
CustomStepper& stepperX, CustomStepper& stepperY, int baudRate)
    : taskQueue(taskQueue), commandQueue(commandQueue), gripper(gripper), stepperX(stepperX), stepperY(stepperY), baudRate(baudRate), 
    receiveCommandTask([this]() { this->receiveCommand(); }, 0), 
    sendStatusTask([this]() { this->sendStatus(); }, 0),
    executeCmdTask([this]() { this->executeCommandTask(); }, 0) {}

// Method to initialize the serial communication
void Communication::beginSerial() {
    Serial.begin(baudRate);
    receiveCommandTask.nextExecutionTime = micros() + receiveInterval;
    sendStatusTask.nextExecutionTime = micros() + sendInterval;
    taskQueue.addTask(receiveCommandTask);
    taskQueue.addTask(sendStatusTask);
    taskQueue.addTask(executeCmdTask);
}

// Method to send the status message
void Communication::sendStatus() {
    if (Serial.availableForWrite() >= 20) { // Check if serial buffer is not full
        Serial.print("Status message:"); 
        Serial.println(cycleCounter);
        cycleCounter = 0;
    }
    sendStatusTask.nextExecutionTime = micros() + sendInterval;
    taskQueue.addTask(sendStatusTask);
}

// Method to read and parse the serial data
void Communication::receiveCommand() {
    readSerial();
    if (newData) {
        receivedCounter++;
        parseAndAddCommand();
        newData = false;
    }
    receiveCommandTask.nextExecutionTime = micros() + receiveInterval;
    taskQueue.addTask(receiveCommandTask);
}

void Communication::IncrementCycleCounter() {
    cycleCounter++;
}
    
// Method to read the serial data
void Communication::readSerial(){
    static bool recvInProgress = false;
    static byte ndx = 0;
    char startMarker = '<';
    char endMarker = '>';
    char rc;

    while (Serial.available() > 0) {
        receivingNewData = false;
        rc = Serial.read();

        if (recvInProgress == true) {
            if (rc != endMarker) {
                receivedChars[ndx] = rc;
                ndx++;
                if (ndx >= numChars) {
                    ndx = numChars - 1;
                }
            }
            else {
                receivedChars[ndx] = '\0'; // terminate the string
                recvInProgress = false;
                ndx = 0;
                newData = true;
            }
        }
        else if (rc == startMarker) {
            recvInProgress = true;
        }
    }
}

// Method to parse the received command and add it to the command queue
void Communication::parseAndAddCommand() {
    Command newCommand = convertCommand(receivedChars);
    commandQueue.addCommand(newCommand);
}

// Task to execute the next command from the command queue
void Communication::executeCommandTask() {
    if (!commandQueue.isEmpty()) {
        if (checkIfFree()) {
            Command nextCmd = commandQueue.getNextCommand();
            executeCommand(nextCmd);
            commandQueue.removeCommand(); // Remove the command after execution
        }
    }
    
    // Reinsert the task into the queue to execute the next command
    executeCmdTask.nextExecutionTime = micros() + commandExecutionInterval;
    taskQueue.addTask(executeCmdTask);
}

// Method to check if the system is free to execute a new command
bool Communication::checkIfFree() {
    if (stepperX.isBusy() || stepperY.isBusy() || gripper.isBusy()) {
        return false;
    } else {
        return true;
    }
}

// Method to execute the command
void Communication::executeCommand(const Command& cmd) {
    switch (cmd.type) {
        case OPEN_GRIPPER:
            gripper.openGripper();
            break;
        case CLOSE_GRIPPER:
            gripper.closeGripper();
            break;
        case GRIPPER_OFF:
            gripper.stopVacuumRefresh();
            break;
        case ENABLE_X:
            stepperX.enableMotor();
            break;
        case DISABLE_X:
            stepperX.disableMotor();
            break;
        case RELATIVE_X:
            stepperX.moveRelative(cmd.param1);
            break;
        case ABSOLUTE_X:
            stepperX.setTargetPosition(cmd.param1);
            break;
        case HOME_X:
            stepperX.beginHoming();
            break;
        case ENABLE_Y:
            stepperY.enableMotor();
            break;
        case DISABLE_Y:
            stepperY.disableMotor();
            break;
        case RELATIVE_Y:
            stepperY.moveRelative(cmd.param1);
            break;
        case ABSOLUTE_Y:
            stepperY.setTargetPosition(cmd.param1);
            break;
        case HOME_Y:
            stepperY.beginHoming();
            break;
        case UNKNOWN:
            Serial.println("Unknown command type");
            // Handle unknown command
            break;
        // Add more cases for other command types
        default:
            // Handle unknown command
            break;
    }
}