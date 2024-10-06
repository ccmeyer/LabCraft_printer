#include "Logger.h"
#include "TaskCommand.h"
#include "GlobalState.h"
#include <Arduino.h>


Logger::Logger(LogLevel logLevel, TaskQueue& taskQueue) : logBufferPos(0), taskQueue(taskQueue), currentLogLevel(logLevel),
flushLogBufferTask([this]() { this->checkFlushBuffer(); }, 0) {
    memset(logBuffer, 0, sizeof(logBuffer));
}

// Log an event with task ID, state, and optional value
void Logger::logEvent(TaskID taskID, TaskState taskState, int32_t value, LogLevel level) {
    // Serial.println("DEBUG-Logging event...");
    if (level <= currentLogLevel) {
        int len = snprintf(logBuffer + logBufferPos, sizeof(logBuffer) - logBufferPos,
                           "%lu, %u, %u, %d-", micros(), taskID, taskState, value);
        logBufferPos += len;
        // Flush if near buffer capacity
        if (logBufferPos > sizeof(logBuffer) - 100) {
            flushLogBuffer();
        }
    }
}

// Set the current log level
void Logger::setLogLevel(LogLevel level) {
    currentLogLevel = level;
}

// Start the log transfer process
void Logger::startLogTransfer() {
    flushLogBufferTask.nextExecutionTime = micros() + flushInterval;
    taskQueue.addTask(flushLogBufferTask);
}

// Check if the log buffer needs to be flushed
void Logger::checkFlushBuffer() {
    if (logBufferPos > 0) {
        // If the machine is idle, flush the log buffer
        if (currentState == IDLE) {
            flushLogBuffer();
        }
        // Reschedule log flushing based on whether the machine is busy
        flushLogBufferTask.nextExecutionTime = micros() + (currentState == IDLE ? flushInterval : 10000);
        taskQueue.addTask(flushLogBufferTask);
    } else {
        // If the buffer is empty, reschedule for normal flush interval
        flushLogBufferTask.nextExecutionTime = micros() + flushInterval;
        taskQueue.addTask(flushLogBufferTask);
    }
}

// Flush log buffer to storage (e.g., SD card or Serial output)
void Logger::flushLogBuffer() {
    // Example: You could print to Serial, write to an SD card, etc.
    Serial.print("<<<");
    Serial.print(logBuffer);
    Serial.println(">>>");

    Serial.flush();

    // Clear the entire buffer content and reset buffer position
    memset(logBuffer, 0, sizeof(logBuffer));
    logBufferPos = 0;  // Reset buffer position
}

// Private helper to add a message to the log buffer
void Logger::addToLogBuffer(const char* message) {
    size_t messageLen = strlen(message);
    if (logBufferPos + messageLen < sizeof(logBuffer)) {
        strncpy(logBuffer + logBufferPos, message, messageLen);
        logBufferPos += messageLen;
    }
}