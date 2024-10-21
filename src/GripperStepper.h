#ifndef GRIPPER_STEPPER_H
#define GRIPPER_STEPPER_H

#include <Arduino.h>
#include "TaskCommand.h"
#include <TMCStepper.h>
#include <HardwareSerial.h>
#include "pin_assignments.h"
// #include <SoftwareSerial.h> // Include SoftwareSerial library
// #include "all_constants.h"
// float R_SENSE = 0.11f;           // SilentStepStick series use 0.11

// using namespace TMC2208_n;

class GripperStepper {
public:
    GripperStepper(
        uint8_t enPin,
        uint8_t stepPin,
        uint8_t dirPin,
        uint8_t address
        // TaskQueue& taskQueue
    );

    // Initialization function
    void initialize();

    // Function to perform homing
    void home();

    // Function to check if the gripper is open
    bool isOpen();

    // Function to check if the gripper is busy
    bool isBusy();

    // Function to open the gripper
    void openGripper();

    // Function to close the gripper
    void closeGripper(); // Returns true if an object is detected

    // Function to check StallGuard status
    bool isStalled();

    // Function to stop the motor
    void stopMotor();

private:
    // UART communication
    // HardwareSerial& _serialPort;
    HardwareSerial _serialPort;

    // TMC2209 driver instance (real object)
    TMC2209Stepper _driver;

    // TaskQueue& taskQueue;   // Reference to the global TaskQueue

    // Pin definitions
    uint8_t _enPin;
    uint8_t _stepPin;
    uint8_t _dirPin;
    uint8_t _address;

    // StallGuard threshold values
    uint8_t _homingStallValue;
    uint8_t _objectStallValue;

    // Current StallGuard value
    uint8_t _currentStallValue;

    // Movement direction
    bool _isClosing; // true: closing, false: opening
    bool _isOpen;     // true: open, false: closed

    // Helper functions
    void stepMotor();
};

#endif // GRIPPER_STEPPER_H
