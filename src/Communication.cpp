#include "Communication.h"
#include "GlobalState.h"
#include <Arduino.h>

// Constructor
Communication::Communication(TaskQueue& taskQueue, CommandQueue& commandQueue, Gripper& gripper, 
CustomStepper& stepperX, CustomStepper& stepperY, CustomStepper& stepperZ, PressureSensor& pressureSensor,
PressureRegulator& printRegulator, PressureRegulator& refuelRegulator, DropletPrinter& printer,
Flash& flash, Coordinator& coord, int baudRate)
    : taskQueue(taskQueue), commandQueue(commandQueue), gripper(gripper), stepperX(stepperX), stepperY(stepperY), stepperZ(stepperZ), 
    pressureSensor(pressureSensor), printRegulator(printRegulator), refuelRegulator(refuelRegulator), printer(printer), flash(flash), coord(coord), baudRate(baudRate), 
    receiveCommandTask([this]() { this->receiveCommand(); }, 0), 
    sendStatusTask([this]() { this->sendStatus(); }, 0),
    executeCmdTask([this]() { this->executeCommandTask(); }, 0),
    waitTask([this]() { this->stopWaiting(); }, 0) {}

// Method to initialize the serial communication
void Communication::beginSerial() {
    Serial.begin(baudRate);
    startTasks();
}

// Method to start the communication tasks
void Communication::startTasks() {
    Serial.println("Starting tasks");
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
                noInterrupts();
                Serial.println(stepperX.currentPosition());
                interrupts();
                statusStep = Y;
                break;
            case Y:
                Serial.print("Y:");
                noInterrupts();
                Serial.println(stepperY.currentPosition());
                interrupts();
                statusStep = Z;
                break;
            case Z:
                Serial.print("Z:");
                noInterrupts();
                Serial.println(stepperZ.currentPosition());
                interrupts();
                statusStep = P;
                break;
            case P:
                Serial.print("P:");
                noInterrupts();
                Serial.println(printRegulator.getCurrentPosition());
                interrupts();
                statusStep = R;
                break;
            case R:
                Serial.print("R:");
                noInterrupts();
                Serial.println(refuelRegulator.getCurrentPosition());
                interrupts();
                statusStep = TARGET_X;
                break;
            case TARGET_X:
                Serial.print("Tar_X:");
                noInterrupts();
                Serial.println(stepperX.targetPosition());
                interrupts();
                statusStep = TARGET_Y;
                break;
            case TARGET_Y:
                Serial.print("Tar_Y:");
                noInterrupts();
                Serial.println(stepperY.targetPosition());
                interrupts();
                statusStep = TARGET_Z;
                break;
            case TARGET_Z:
                Serial.print("Tar_Z:");
                noInterrupts();
                Serial.println(stepperZ.targetPosition());
                interrupts();
                statusStep = TARGET_P;
                break;
            case TARGET_P:
                Serial.print("Tar_P:");
                noInterrupts();
                Serial.println(printRegulator.getTargetPosition());
                interrupts();
                statusStep = TARGET_R;
                break;
            case TARGET_R:
                Serial.print("Tar_R:");
                noInterrupts();
                Serial.println(refuelRegulator.getTargetPosition());
                interrupts();
                statusStep = GRIPPER;
                break;
            case GRIPPER:
                Serial.print("Gripper:");
                noInterrupts();
                Serial.println(gripper.isOpen());
                interrupts();
                statusStep = PRESSURE_P;
                break;
            case PRESSURE_P:
                Serial.print("Pressure_P:");
                noInterrupts();
                Serial.println(round(pressureSensor.getPrintPressure()));
                interrupts();
                statusStep = PRESSURE_R;
                break;
            case PRESSURE_R:
                Serial.print("Pressure_R:");
                noInterrupts();
                Serial.println(round(pressureSensor.getRefuelPressure()));
                interrupts();
                statusStep = TARGET_PRINT;
                break;
            case TARGET_PRINT:
                Serial.print("Tar_print:");
                noInterrupts();
                Serial.println(round(printRegulator.getTargetPressure()));
                interrupts();
                statusStep = TARGET_REFUEL;
                break;
            case TARGET_REFUEL:
                Serial.print("Tar_refuel:");
                noInterrupts();
                Serial.println(round(refuelRegulator.getTargetPressure()));
                interrupts();
                statusStep = PULSE_WIDTH_PRINT;
                break;
            case PULSE_WIDTH_PRINT:
                Serial.print("Print_width:");
                noInterrupts();
                Serial.println(printer.getPrintDuration());
                interrupts();
                statusStep = PULSE_WIDTH_REFUEL;
                break;
            case PULSE_WIDTH_REFUEL:
                Serial.print("Refuel_width:");
                noInterrupts();
                Serial.println(printer.getRefuelDuration());
                interrupts();
                statusStep = MICROS;
                break;
            case MICROS:
                Serial.print("Micros:");
                Serial.println(micros());
                statusStep = FLASHES;
                break;
            case FLASHES:
                Serial.print("Flashes:");
                Serial.println(flash.getNumFlashes());
                statusStep = FLASH_WIDTH;
                break;
            case FLASH_WIDTH:
                Serial.print("Flash_width:");
                Serial.println(flash.getFlashWidth());
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
    taskQueue.resetWatchdog();
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
    noInterrupts();
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
        printRegulator.resetState();
        refuelRegulator.resetState();
        currentCmdNum = 0;
        lastCompletedCmdNum = 0;
        lastAddedCmdNum = 0;
        currentState = RUNNING;
        Serial.println("--Reset");
        startTasks();
        pressureSensor.startReading();
        printRegulator.restartRegulation();
        refuelRegulator.restartRegulation();
        gripper.resetRefreshCounter();
        Serial.println("--Restarted tasks");
    } else {
        Serial.print("Adding command: ");
        Serial.println(newCommand.type);
        lastAddedCmdNum = newCommand.commandNum;
        commandQueue.addCommand(newCommand);
    }
    interrupts();
}

// Task to execute the next command from the command queue
void Communication::executeCommandTask() {
    noInterrupts();
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
    interrupts();
}

// Method to check if the system is free to execute a new command
bool Communication::checkIfFree() const{
    if (currentState == PAUSED || waiting || stepperX.isBusy() || stepperY.isBusy() || stepperZ.isBusy() || gripper.isBusy() || printRegulator.isBusy() || refuelRegulator.isBusy() || printer.isBusy()) {
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
            printRegulator.enableRegulator();
            refuelRegulator.enableRegulator();
            break;
        case DISABLE_MOTORS:
            stepperX.disableMotor();
            stepperY.disableMotor();
            stepperZ.disableMotor();
            printRegulator.disableRegulator();
            refuelRegulator.disableRegulator();
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
            printRegulator.homeSyringe();
            break;
        case HOME_R:
            refuelRegulator.homeSyringe();
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
        case REGULATE_PRESSURE_P:
            printRegulator.beginRegulation();
            printRegulator.setTargetPressureAbsolute(8192);
            break;
        case REGULATE_PRESSURE_R:
            refuelRegulator.beginRegulation();
            refuelRegulator.setTargetPressureAbsolute(8192);
            break;
        case DEREGULATE_PRESSURE:
            printRegulator.stopRegulation();
            refuelRegulator.stopRegulation();
            break;
        case RELATIVE_PRESSURE_P:
            printRegulator.setTargetPressureRelative(cmd.param1);
            break;
        case ABSOLUTE_PRESSURE_P:
            printRegulator.setTargetPressureAbsolute(cmd.param1);
            break;
        case RELATIVE_PRESSURE_R:
            refuelRegulator.setTargetPressureRelative(cmd.param1);
            break;
        case ABSOLUTE_PRESSURE_R:
            refuelRegulator.setTargetPressureAbsolute(cmd.param1);
            break;
        case PRINT:
            printer.startPrinting(cmd.param1);
            break;
        case PRINT_ONLY:
            printer.deactivateRefuel();
            printer.startPrinting(cmd.param1);
            break;
        case REFUEL_ONLY:
            printer.deactivatePrint();
            printer.startPrinting(cmd.param1);
            break;
        case RESET_P:
            printRegulator.resetSyringe();
            break;
        case RESET_R:
            refuelRegulator.resetSyringe();
            break;
        case WAIT:
            startWaiting(cmd.param1);
            break;
        case SET_WIDTH_P:
            printer.setPrintDuration(cmd.param1);
            break;
        case SET_WIDTH_R:
            printer.setRefuelDuration(cmd.param1);
            break;
        case START_READ_CAMERA:
            coord.startReading();
            break;
        case STOP_READ_CAMERA:
            coord.stopReading();
            break;
        case SET_WIDTH_F:
            flash.setFlashDuration(cmd.param1);
            break;
        case PRINT_MODE:
            printer.enterPrintMode();
            break;
        case NORMAL_MODE:
            printer.exitPrintMode();
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

// Method to start the wait task
void Communication::startWaiting(unsigned long waitTime) {
    waiting = true;
    waitTask.nextExecutionTime = micros() + (waitTime * 1000);
    taskQueue.addTask(waitTask);
}

// Method to stop waiting
void Communication::stopWaiting() {
    waiting = false;
}