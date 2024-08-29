#include "TaskCommand.h"
#include <Arduino.h>

// Add a task to the queue
void TaskQueue::addTask(const Task& task) {
    taskQueue.push(task);
}

// Method to execute the next task in the task queue
void TaskQueue::executeNextTask() {
    if (!taskQueue.empty()) {
        Task currentTask = taskQueue.top();
        unsigned long currentMillis = micros();

        if (currentMillis >= currentTask.nextExecutionTime) {
            taskQueue.pop();
            currentTask.function();  // Execute the task
        }
    }
}

// Remove the next task from the queue
void TaskQueue::removeTask() {
    if (!taskQueue.empty()) {
        taskQueue.pop();
    }
}

// Check if the queue is empty
bool TaskQueue::isEmpty() const {
    return taskQueue.empty();
}

// Add a command to the queue
void CommandQueue::addCommand(const Command& command) {
    commandQueue.push(command);
}

// Get next command from the queue
Command CommandQueue::getNextCommand() {
    if (!commandQueue.empty()) {
        return commandQueue.front();
    } else {
        return Command(0, UNKNOWN, 0, 0, 0);
    }
}

// Remove the next command from the queue
void CommandQueue::removeCommand() {
    if (!commandQueue.empty()) {
        commandQueue.pop();
    }
}

// Check if the command queue is empty
bool CommandQueue::isEmpty() const {
    return commandQueue.empty();
}

// Function to convert received serial data into a Command object
Command convertCommand(const char* receivedChars) {
    char tempChars[64];
    strcpy(tempChars, receivedChars);
    char* strtokIndx;

    strtokIndx = strtok(tempChars, ",");
    int commandNum = strtokIndx != NULL ? atoi(strtokIndx) : 0;

    strtokIndx = strtok(NULL, ",");
    CommandType commandType = strtokIndx != NULL ? mapCommandType(strtokIndx) : UNKNOWN;

    strtokIndx = strtok(NULL, ",");
    long param1 = strtokIndx != NULL ? atol(strtokIndx) : 0;

    strtokIndx = strtok(NULL, ",");
    long param2 = strtokIndx != NULL ? atol(strtokIndx) : 0;

    strtokIndx = strtok(NULL, ",");
    long param3 = strtokIndx != NULL ? atol(strtokIndx) : 0;

    return Command(commandNum, commandType, param1, param2, param3);
}

// Function to map command names to command types
CommandType mapCommandType(const char* commandName) {
    if (strcmp(commandName, "OPEN_GRIPPER") == 0) {
        return OPEN_GRIPPER;
    } else if (strcmp(commandName, "CLOSE_GRIPPER") == 0) {
        return CLOSE_GRIPPER;
    } else if (strcmp(commandName, "GRIPPER_OFF") == 0) {
        return GRIPPER_OFF;
    } else if (strcmp(commandName, "ENABLE_MOTORS") == 0) {
        return ENABLE_MOTORS;
    } else if (strcmp(commandName, "DISABLE_MOTORS") == 0) {
        return DISABLE_MOTORS;
    } else if (strcmp(commandName, "RELATIVE_X") == 0) {
        return RELATIVE_X;
    } else if (strcmp(commandName, "ABSOLUTE_X") == 0) {
        return ABSOLUTE_X;
    } else if (strcmp(commandName, "HOME_X") == 0) {
        return HOME_X;
    } else if (strcmp(commandName, "RELATIVE_Y") == 0) {
        return RELATIVE_Y;
    } else if (strcmp(commandName, "ABSOLUTE_Y") == 0) {
        return ABSOLUTE_Y;
    } else if (strcmp(commandName, "HOME_Y") == 0) {
        return HOME_Y;
    } else if (strcmp(commandName, "RELATIVE_Z") == 0) {
        return RELATIVE_Z;
    } else if (strcmp(commandName, "ABSOLUTE_Z") == 0) {
        return ABSOLUTE_Z;
    } else if (strcmp(commandName, "HOME_Z") == 0) {
        return HOME_Z;
    } else if (strcmp(commandName, "CHANGE_ACCEL") == 0) {
        return CHANGE_ACCEL;
    } else if (strcmp(commandName, "RESET_ACCEL") == 0) {
        return RESET_ACCEL;
    } else if (strcmp(commandName, "REGULATE_PRESSURE") == 0) {
        return REGULATE_PRESSURE;
    } else if (strcmp(commandName, "DEREGULATE_PRESSURE") == 0) {
        return DEREGULATE_PRESSURE;
    } else if (strcmp(commandName, "RELATIVE_PRESSURE") == 0) {
        return RELATIVE_PRESSURE;
    } else if (strcmp(commandName, "ABSOLUTE_PRESSURE") == 0) {
        return ABSOLUTE_PRESSURE;
    } else {
        return UNKNOWN;
    }
}