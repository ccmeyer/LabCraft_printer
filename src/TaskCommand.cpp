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



// // Method to add a command to the command queue
// void CommandQueue::addCommand(Command cmd) {
//     commandQueue.push(cmd);
// }

// // Method to execute the next command in the command queue
// void CommandQueue::executeNextCommand() {
//     if (!commandQueue.empty() && currentState == FREE) {
//         Command nextCmd = commandQueue.front();
//         commandQueue.pop();

//         executeCommand(nextCmd);
//     }
// }

// // Method to execute a specific command
// void CommandQueue::executeCommand(const Command& cmd) {

// }
