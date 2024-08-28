#include "Communication.h"
#include <Arduino.h>

// Constructor
Communication::Communication(TaskQueue& taskQueue, CommandQueue& commandQueue, Gripper& gripper, 
CustomStepper& stepperX, CustomStepper& stepperY, CustomStepper& stepperZ, int baudRate)
    : taskQueue(taskQueue), commandQueue(commandQueue), gripper(gripper), stepperX(stepperX), stepperY(stepperY), stepperZ(stepperZ), baudRate(baudRate), 
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
        switch (statusStep) {
            case CYCLE_COUNT:
                Serial.print("Cycle_count:");
                Serial.print(cycleCounter);
                statusStep = LAST_COMPLETED_CMD;
                break;
            case LAST_COMPLETED_CMD:
                Serial.print(",Last_completed:");
                Serial.print(lastCompletedCmdNum);
                statusStep = LAST_ADDED_CMD;
                break;
            case LAST_ADDED_CMD:    
                Serial.print(",Last_added:");
                Serial.print(lastAddedCmdNum);
                statusStep = CURRENT_CMD;
                break;
            case CURRENT_CMD:
                Serial.print(",Current_command:");
                Serial.print(currentCmdNum);
                statusStep = X;
                break;
            case X:
                Serial.print(",X:");
                Serial.print(stepperX.currentPosition());
                statusStep = Y;
                break;
            case Y:
                Serial.print(",Y:");
                Serial.print(stepperY.currentPosition());
                statusStep = Z;
                break;
            case Z:
                Serial.print(",Z:");
                Serial.print(stepperZ.currentPosition());
                statusStep = TARGET_X;
                break;
            case TARGET_X:
                Serial.print(",Tar_X:");
                Serial.print(stepperX.targetPosition());
                statusStep = TARGET_Y;
                break;
            case TARGET_Y:
                Serial.print(",Tar_Y:");
                Serial.print(stepperY.targetPosition());
                statusStep = TARGET_Z;
                break;
            case TARGET_Z:
                Serial.print(",Tar_Z:");
                Serial.print(stepperZ.targetPosition());
                statusStep = GRIPPER;
                break;
            case GRIPPER:
                Serial.print(",Gripper:");
                Serial.print(gripper.isOpen());
                Serial.println();
                statusStep = CYCLE_COUNT;
                break;
        }
    }
    cycleCounter = 0;
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
    lastAddedCmdNum = newCommand.commandNum;
    commandQueue.addCommand(newCommand);
}

// Task to execute the next command from the command queue
void Communication::executeCommandTask() {
    if (!commandQueue.isEmpty()) {
        if (checkIfFree()) {
            lastCompletedCmdNum = currentCmdNum;
            Command nextCmd = commandQueue.getNextCommand();
            executeCommand(nextCmd);
            currentCmdNum = nextCmd.commandNum;
            commandQueue.removeCommand(); // Remove the command after execution
        }
    }
    
    // Reinsert the task into the queue to execute the next command
    executeCmdTask.nextExecutionTime = micros() + commandExecutionInterval;
    taskQueue.addTask(executeCmdTask);
}

// Method to check if the system is free to execute a new command
bool Communication::checkIfFree() {
    if (stepperX.isBusy() || stepperY.isBusy() || stepperZ.isBusy() || gripper.isBusy()) {
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
        case ENABLE_MOTORS:
            stepperX.enableMotor();
            stepperY.enableMotor();
            stepperZ.enableMotor();
            break;
        case DISABLE_MOTORS:
            stepperX.disableMotor();
            stepperY.disableMotor();
            stepperZ.disableMotor();
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
        case RELATIVE_Y:
            stepperY.moveRelative(cmd.param1);
            break;
        case ABSOLUTE_Y:
            stepperY.setTargetPosition(cmd.param1);
            break;
        case HOME_Y:
            stepperY.beginHoming();
            break;
        case RELATIVE_Z:
            stepperZ.moveRelative(cmd.param1);
            break;
        case ABSOLUTE_Z:
            stepperZ.setTargetPosition(cmd.param1);
            break;
        case HOME_Z:
            stepperZ.beginHoming();
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