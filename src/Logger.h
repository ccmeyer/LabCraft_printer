#ifndef LOGGER_H
#define LOGGER_H

#include "TaskCommand.h"

#include <stdio.h>
#include <stdint.h>
#include <string.h>

// Log levels for controlling verbosity
enum LogLevel {
    LOG_ERROR = 0,  // Only errors
    LOG_INFO = 1,   // Errors and important info
    LOG_DEBUG = 2   // All details, including debug info
};

enum TaskState {
    TASK_START = 0,
    TASK_END = 1,
    TASK_ERROR = 2,
    TASK_RESET = 3,
    TASK_SINGLE = 4
};

enum TaskID {
    COMM_TX = 0,
    COMM_RX = 1,
    PRESSURE_READING = 2,
    GRIPPER_PUMP_ON = 3,
    GRIPPER_PUMP_OFF = 4,
    GRIPPER_OPEN = 5,
    GRIPPER_CLOSE = 6,
    GRIPPER_REFRESH_START = 7,
    GRIPPER_REFRESH_STOP = 8,
    GRIPPER_PUMP_REFRESH = 9,
    STEPPER_ENABLE = 10,
    STEPPER_DISABLE = 11,
    STEPPER_MOVE = 12,
    STEPPER_HOMING = 13,
    MACHINE_WAITING = 14,
    MACHINE_PAUSED = 15,
    COMMAND_READ_ERROR = 16,
    MODE_PRINT = 17,
    MODE_NORMAL = 18,
    PRINT_DROPLETS = 19,
    PRESSURE_REGULATION = 20,
    PRESSURE_SET = 21,
};

class Logger {
public:
    Logger(LogLevel logLevel, TaskQueue& taskQueue);  // Constructor to initialize the logger with the desired level
    void logEvent(TaskID taskID, TaskState taskState, int32_t value = -1, LogLevel level = LOG_INFO);
    void setLogLevel(LogLevel level);      // Change the logging level
    void flushLogBuffer();                 // Write log buffer to storage (file, SD card, etc.)
    void checkFlushBuffer();               // Check if the log buffer needs to be flushed
    void startLogTransfer();               // Start the log transfer process

private:
    char logBuffer[4096];                  // Buffer for storing log messages before flushing
    size_t logBufferPos;                   // Current position in the buffer
    LogLevel currentLogLevel;              // Current logging level

    TaskQueue& taskQueue;                  // Reference to the task queue for adding tasks
    Task flushLogBufferTask;               // Task to periodically flush the log buffer
    unsigned long flushInterval = 50000;  // Default read interval of 10 msec
    void addToLogBuffer(const char* message);  // Helper to add message to buffer
};

#endif // LOGGER_H