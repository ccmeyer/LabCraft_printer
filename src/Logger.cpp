#include "Logger.h"
#include <Arduino.h>


Logger::Logger(LogLevel logLevel) : logBufferPos(0), currentLogLevel(logLevel) {
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

// Flush log buffer to storage (e.g., SD card or Serial output)
void Logger::flushLogBuffer() {
    // Example: You could print to Serial, write to an SD card, etc.
    Serial.print("<<<");
    Serial.print(logBuffer);
    Serial.println(">>>");

    Serial.flush();
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