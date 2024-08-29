#include "Communication.h"
#include "GlobalState.h"
#include <Arduino.h>

// Constructor
Communication::Communication(TaskQueue& taskQueue, CommandQueue& commandQueue, Gripper& gripper, 
CustomStepper& stepperX, CustomStepper& stepperY, CustomStepper& stepperZ, PressureSensor& pressureSensor,
PressureRegulator& regulator, DropletPrinter& printer, int baudRate)
    : taskQueue(taskQueue), commandQueue(commandQueue), gripper(gripper), stepperX(stepperX), stepperY(stepperY), stepperZ(stepperZ), 
    pressureSensor(pressureSensor), regulator(regulator), printer(printer), baudRate(baudRate), 
    receiveCommandTask([this]() { this->receiveCommand(); }, 0), 
    sendStatusTask([this]() { this->sendStatus(); }, 0),
    executeCmdTask([this]() { this->executeCommandTask(); }, 0) {}

// Method to initialize the serial communication
void Communication::beginSerial() {
    Serial.begin(baudRate);
    startTasks();
}

// Method to start the communication tasks
void Communication::startTasks() {
    receiveCommandTask.nextExecutionTime = micros() + receiveInterval;
    sendStatusTask.nextExecutionTime = micros() + sendInterval;
    executeCmdTask.nextExecutionTime = micros() + commandExecutionInterval;
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
                Serial.println(cycleCounter);
                statusStep = LAST_COMPLETED_CMD;
                break;
            case LAST_COMPLETED_CMD:
                Serial.print("Last_completed:");
                Serial.println(lastCompletedCmdNum);
                statusStep = LAST_ADDED_CMD;
                break;
            case LAST_ADDED_CMD:    
                Serial.print("Last_added:");
                Serial.println(lastAddedCmdNum);
                statusStep = CURRENT_CMD;
                break;
            case CURRENT_CMD:
                Serial.print("Current_command:");
                Serial.println(currentCmdNum);
                statusStep = X;
                break;
            case X:
                Serial.print("X:");
                Serial.println(stepperX.currentPosition());
                statusStep = Y;
                break;
            case Y:
                Serial.print("Y:");
                Serial.println(stepperY.currentPosition());
                statusStep = Z;
                break;
            case Z:
                Serial.print("Z:");
                Serial.println(stepperZ.currentPosition());
                statusStep = P;
                break;
            case P:
                Serial.print("P:");
                Serial.println(regulator.getCurrentPosition());
                statusStep = TARGET_X;
                break;
            case TARGET_X:
                Serial.print("Tar_X:");
                Serial.println(stepperX.targetPosition());
                statusStep = TARGET_Y;
                break;
            case TARGET_Y:
                Serial.print("Tar_Y:");
                Serial.println(stepperY.targetPosition());
                statusStep = TARGET_Z;
                break;
            case TARGET_Z:
                Serial.print("Tar_Z:");
                Serial.println(stepperZ.targetPosition());
                statusStep = TARGET_P;
                break;
            case TARGET_P:
                Serial.print("Tar_P:");
                Serial.println(regulator.getTargetPosition());
                statusStep = GRIPPER;
                break;
            case GRIPPER:
                Serial.print("Gripper:");
                Serial.println(gripper.isOpen());
                statusStep = PRESSURE;
                break;
            case PRESSURE:
                Serial.print("Pressure:");
                Serial.println(round(pressureSensor.getPressure()));
                statusStep = TARGET_PRESSURE;
                break;
            case TARGET_PRESSURE:
                Serial.print("Tar_pressure:");
                Serial.println(round(regulator.getTargetPressure()));
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
    if (newCommand.type == PAUSE) {
        currentState = PAUSED;
    } else if (newCommand.type == RESUME) {
        currentState = RUNNING;
    } else if (newCommand.type == CLEAR_QUEUE) {
        Serial.println("--Clearing");
        while (!commandQueue.isEmpty()) {
            commandQueue.removeCommand();
        }
        while (!taskQueue.isEmpty()) {
            taskQueue.removeTask();
        }
        Serial.println("Queue cleared");
        stepperX.resetState();
        stepperY.resetState();
        stepperZ.resetState();
        printer.resetDropletCounts();
        regulator.resetState();
        currentCmdNum = 0;
        lastCompletedCmdNum = 0;
        lastAddedCmdNum = 0;
        currentState = RUNNING;
        Serial.println("--Reset");
        startTasks();
        pressureSensor.startReading();
        regulator.restartRegulation();
        Serial.println("--Restarted tasks");
    } else {
        Serial.print("Adding command: ");
        Serial.println(newCommand.type);
        lastAddedCmdNum = newCommand.commandNum;
        commandQueue.addCommand(newCommand);
    } 
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
    } else {
        if (checkIfFree()) {
            lastCompletedCmdNum = currentCmdNum;
        }
    }
    
    // Reinsert the task into the queue to execute the next command
    executeCmdTask.nextExecutionTime = micros() + commandExecutionInterval;
    taskQueue.addTask(executeCmdTask);
}

// Method to check if the system is free to execute a new command
bool Communication::checkIfFree() {
    if (currentState == PAUSED || stepperX.isBusy() || stepperY.isBusy() || stepperZ.isBusy() || gripper.isBusy() || regulator.isBusy() || printer.isBusy()) {
        Serial.println("---Busy");
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
            regulator.enableRegulator();
            break;
        case DISABLE_MOTORS:
            stepperX.disableMotor();
            stepperY.disableMotor();
            stepperZ.disableMotor();
            regulator.disableRegulator();
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
        case HOME_P:
            regulator.homeSyringe();
            break;
        case CHANGE_ACCEL:
            stepperX.setAcceleration(cmd.param1);
            stepperY.setAcceleration(cmd.param1);
            stepperZ.setAcceleration(cmd.param1);
            break;
        case RESET_ACCEL:
            stepperX.resetProperties();
            stepperY.resetProperties();
            stepperZ.resetProperties();
            break;
        case REGULATE_PRESSURE:
            regulator.beginRegulation();
            regulator.setTargetPressureAbsolute(1638);
            break;
        case DEREGULATE_PRESSURE:
            regulator.stopRegulation();
            break;
        case RELATIVE_PRESSURE:
            regulator.setTargetPressureRelative(cmd.param1);
            break;
        case ABSOLUTE_PRESSURE:
            regulator.setTargetPressureAbsolute(cmd.param1);
            break;
        case PRINT:
            printer.startPrinting(cmd.param1);
            break;
        case RESET_P:
            regulator.resetSyringe();
            break;
        case PAUSE:
            currentState = PAUSED;
            break;
        case RESUME:
            currentState = RUNNING;
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