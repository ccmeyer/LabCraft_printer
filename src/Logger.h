#ifndef LOGGER_H
#define LOGGER_H

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
    TASK_ERROR = 2
};

enum TaskID {
    PRESSURE_REGULATOR = 0,
    COMM_TX = 1,
    COMM_RX = 2,
    PRESSURE_READING = 3,
    STEPPER = 4
};

class Logger {
public:
    Logger(LogLevel logLevel = LOG_DEBUG);  // Constructor to initialize the logger with the desired level
    void logEvent(TaskID taskID, TaskState taskState, int32_t value = -1, LogLevel level = LOG_INFO);
    void setLogLevel(LogLevel level);      // Change the logging level
    void flushLogBuffer();                 // Write log buffer to storage (file, SD card, etc.)
    
private:
    char logBuffer[4096];                  // Buffer for storing log messages before flushing
    size_t logBufferPos;                   // Current position in the buffer
    LogLevel currentLogLevel;              // Current logging level

    void addToLogBuffer(const char* message);  // Helper to add message to buffer
};

#endif // LOGGER_H