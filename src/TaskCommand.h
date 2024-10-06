#ifndef TASKCOMMAND_H
#define TASKCOMMAND_H

#include <functional>
#include <queue>
#include <vector>
#include <cstring> // For strcmp()
#include "Logger.h"
#include "stm32f4xx_hal.h"
#include <stm32f4xx_hal_iwdg.h>

// Task struct to represent a scheduled task
struct Task {
    std::function<void()> function;       // Function pointer to the task's function
    unsigned long nextExecutionTime;      // The next time the task should run

    Task(std::function<void()> func, unsigned long execTime)
        : function(func), nextExecutionTime(execTime) {}
};

// Task queue to manage scheduled tasks
class TaskQueue {
public:
    TaskQueue(IWDG_HandleTypeDef* watchdogPtr, Logger& loggerRef);  // Constructor for TaskQueue
    void addTask(const Task& task);       // Add a task to the queue
    void removeTask();                    // Remove the next task from the queue
    void executeNextTask();               // Execute the next task in the queue
    bool isEmpty() const;                 // Check if the queue is empty
    void resetWatchdog();                 // Reset the watchdog timer

private:
    // Custom comparator for priority queue (sorted by nextExecutionTime)
    struct CompareTask {
        bool operator()(const Task& t1, const Task& t2) {
            return (t1.nextExecutionTime - t2.nextExecutionTime) < (unsigned long)(1UL << 31); // Earlier tasks have higher priority
        }
    };

    std::priority_queue<Task, std::vector<Task>, CompareTask> taskQueue;  // Priority queue to store tasks
    bool taskRunning = false;  // Flag to indicate if a task is currently running
    IWDG_HandleTypeDef* watchdog;  // Pointer to the watchdog handler
    unsigned long currentMicros;  // Current micros value
};

enum CommandType {
    OPEN_GRIPPER,
    CLOSE_GRIPPER,
    GRIPPER_OFF,
    ENABLE_MOTORS,
    DISABLE_MOTORS,
    RELATIVE_X,
    ABSOLUTE_X,
    RELATIVE_Y,
    ABSOLUTE_Y,
    RELATIVE_Z,
    ABSOLUTE_Z,
    HOME_X,
    HOME_Y,
    HOME_Z,
    HOME_P,
    CHANGE_ACCEL,
    RESET_ACCEL,
    REGULATE_PRESSURE,
    DEREGULATE_PRESSURE,
    RELATIVE_PRESSURE,
    ABSOLUTE_PRESSURE,
    SET_WIDTH,
    PRINT,
    RESET_P,
    PRINT_MODE,
    NORMAL_MODE,
    WAIT,
    PAUSE,
    RESUME,
    CLEAR_QUEUE,
    UNKNOWN
    // Add more command types as needed
};

// Command struct to store the command details
struct Command {
    int commandNum;
    CommandType type;
    long param1;
    long param2;
    long param3;

    Command(int num, CommandType t, long p1, long p2, long p3)
        : commandNum(num), type(t), param1(p1), param2(p2), param3(p3) {}
};

// Command queue to manage incoming commands
class CommandQueue {
public:
    void addCommand(const Command& command);       // Add a command to the queue
    // void executeNextCommand();                     // Execute the next command in the queue
    Command getNextCommand();                      // Get the next command from the queue
    void removeCommand();                          // Remove the next command from the queue
    bool isEmpty() const;                          // Check if the queue is empty

private:
    std::queue<Command> commandQueue;
};

// Function to map command names to command types
CommandType mapCommandType(const char* commandName);

// Function to convert received serial data into a Command object
Command convertCommand(const char* receivedChars);

#endif // TASKCOMMAND_H
