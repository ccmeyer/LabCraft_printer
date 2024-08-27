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
        unsigned long currentMillis = millis();

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

// // Execute the next command in the command queue
// void CommandQueue::executeNextCommand() {
//     if (!commandQueue.empty()) {
//         Command currentCommand = commandQueue.front();
//         commandQueue.pop();

//         // Handle the command based on its type
//         switch (currentCommand.type) {
//             case OPEN_GRIPPER:
//                 Serial.println("Executing OPEN_GRIPPER");
//                 // Add logic to open the gripper
//                 break;
//             case CLOSE_GRIPPER:
//                 Serial.println("Executing CLOSE_GRIPPER");
//                 // Add logic to close the gripper
//                 break;
//             case GRIPPER_OFF:
//                 Serial.println("Executing GRIPPER_OFF");
//                 // Add logic to turn the gripper off
//                 break;
//             case UNKNOWN:
//             default:
//                 Serial.println("Unknown Command");
//                 break;
//         }
//     }
// }

// Check if the command queue is empty
bool CommandQueue::isEmpty() const {
    return commandQueue.empty();
}

// Function to map command names to command types
CommandType mapCommandType(const char* commandName) {
    if (strcmp(commandName, "OPEN_GRIPPER") == 0) {
        return OPEN_GRIPPER;
    } else if (strcmp(commandName, "CLOSE_GRIPPER") == 0) {
        return CLOSE_GRIPPER;
    } else if (strcmp(commandName, "GRIPPER_OFF") == 0) {
        return GRIPPER_OFF;
    } else {
        return UNKNOWN;
    }
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