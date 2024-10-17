#ifndef GRIPPER_STEPPER_H
#define GRIPPER_STEPPER_H

#include <Arduino.h>
#include "TaskCommand.h"
#include <TMCStepper.h>
#include <SoftwareSerial.h> // Include SoftwareSerial library

// Define the RSENSE resistor value for TMC2209 (e.g., 0.11 Ohm)
#define R_SENSE 0.11f

class GripperStepper {
public:
    GripperStepper(
        uint8_t enPin,
        uint8_t stepPin,
        uint8_t dirPin,
        uint8_t uartPin,
        uint8_t address,
        TaskQueue& taskQueue
    );

    // Initialization function
    void initialize();

    // Function to perform homing
    void home();

    // Function to open the gripper
    void openGripper();

    // Function to close the gripper
    bool closeGripper(); // Returns true if an object is detected

    // Function to check StallGuard status
    bool isStalled();

    // Function to stop the motor
    void stopMotor();

private:
    // UART communication
    SoftwareSerial _softSerial;

    // TMC2209 driver instance (real object)
    TMC2209Stepper _driver;

    TaskQueue& taskQueue;   // Reference to the global TaskQueue

    // Pin definitions
    uint8_t _enPin;
    uint8_t _stepPin;
    uint8_t _dirPin;
    uint8_t _uartPin;
    uint8_t _address;

    // StallGuard threshold values
    uint8_t _homingStallValue;
    uint8_t _objectStallValue;

    // Current StallGuard value
    uint8_t _currentStallValue;

    // Movement direction
    bool _isClosing; // true: closing, false: opening

    // Helper functions
    void stepMotor();
};

#endif // GRIPPER_STEPPER_H
