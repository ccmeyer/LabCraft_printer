#include "GripperStepper.h"

extern HardwareSerial SerialUART1;

// Constructor
GripperStepper::GripperStepper(
    uint8_t enPin,
    uint8_t stepPin,
    uint8_t dirPin,
    uint8_t address
    // TaskQueue& taskQueue
)
    : _serialPort(SerialUART1), // Use Serial1 for hardware UART
      _driver(&_serialPort, 0.11f, 0b00),
    //   taskQueue(taskQueue),
      _enPin(enPin),
      _stepPin(stepPin),
      _dirPin(dirPin),
      _address(address),
      _homingStallValue(100),
      _objectStallValue(100),
      _currentStallValue(100),
      _isClosing(false),
      _isOpen(false)
{
    // Empty constructor body
}

void GripperStepper::initialize() {
      // // Begin SoftwareSerial communication
    // _serialPort.begin(115200);
    _driver.beginSerial(115200);
    Serial.println("DEBUG:Initializing gripper stepper");
    // Initialize pins
    pinMode(_enPin, OUTPUT);
    pinMode(_stepPin, OUTPUT);
    pinMode(_dirPin, OUTPUT);
    // pinMode(_SW_RX, INPUT_PULLUP); // Ensure pull-up resistor is enabled

    digitalWrite(_enPin, LOW); // Disable driver
    
    // Initialize TMC2209 driver
    _driver.begin();

    // Configure driver settings
    _driver.toff(4);
    _driver.blank_time(24);
    _driver.rms_current(800); // Set motor RMS current
    _driver.microsteps(16);
    _driver.TCOOLTHRS(0xFFFFF);
    // _driver.en_spreadCycle(false);
    // _driver.pdn_disable(true); // Use UART
    // _driver.mstep_reg_select(true);
    _driver.semin(5);
    _driver.semax(2);
    _driver.sedn(0b01);
    // _driver.IHOLD(10);       // Standstill current (0-31)
    // _driver.IRUN(31);        // Run current (0-31)
    // _driver.IHOLDDELAY(5);   // Current ramping delay between IHOLD and IRUN    _driver.en_stallguard(true);
    _driver.SGTHRS(_currentStallValue);
    // _driver.semin(5);
    // _driver.semax(2);
    // _driver.sedn(0b01);
    Serial.println("DEBUG:End Config");

}

void GripperStepper::home() {
    digitalWrite(_dirPin, HIGH); // Adjust based on your setup
    _isClosing = true;

    _currentStallValue = _homingStallValue;
    _driver.SGTHRS(_currentStallValue);

    digitalWrite(_enPin, LOW); // Enable driver

    while (!isStalled()) {
        stepMotor();
        delayMicroseconds(500);
    }

    stopMotor();

    // Move back a few steps to release pressure
    digitalWrite(_dirPin, LOW);
    for (int i = 0; i < 50; i++) {
        stepMotor();
        delayMicroseconds(500);
    }

    stopMotor();
}

bool GripperStepper::isOpen() {
    return _isOpen;
}

bool GripperStepper::isBusy() {
    return _isClosing;
}

void GripperStepper::openGripper() {
    Serial.println("DEBUG:Opening gripper");
    digitalWrite(_dirPin, LOW); // Adjust based on your setup
    _isClosing = true;
    // _driver.en_stallguard(false);

    digitalWrite(_enPin, LOW); // Enable driver

    const int openSteps = 1000; // Adjust as needed

    for (int i = 0; i < openSteps; i++) {
        stepMotor();
        delayMicroseconds(500);
        Serial.println("DEBUG:Opening gripper step");

        // if (isStalled()) {
        //     _isOpen = true;
        //     break;
        // }
    }
    _isClosing = false;

    stopMotor();
    // _driver.en_stallguard(true);
}

void GripperStepper::closeGripper() {
    Serial.println("DEBUG:Closing gripper");
    digitalWrite(_dirPin, HIGH); // Adjust based on your setup
    _isClosing = true;

    // _currentStallValue = _objectStallValue;
    // _driver.SGTHRS(_currentStallValue);

    digitalWrite(_enPin, LOW); // Enable driver

    const int closeSteps = 1000; // Adjust as needed

    for (int i = 0; i < closeSteps; i++) {
        stepMotor();
        delayMicroseconds(500);
        // if (isStalled()) {
        //     _isOpen = false;
        //     break;
        // }
    }
    _isClosing = false;
    stopMotor();

    return;
}

bool GripperStepper::isStalled() {
    uint16_t sg_result = _driver.SG_RESULT();

    // Uncomment for debugging
    Serial.print("DEBUG:SG_RESULT- ");
    Serial.println(sg_result);

    return (sg_result < _currentStallValue);
}

void GripperStepper::stopMotor() {
    digitalWrite(_enPin, HIGH); // Disable driver
}

void GripperStepper::stepMotor() {
    digitalWrite(_stepPin, HIGH);
    delayMicroseconds(2); // Minimum HIGH pulse width
    digitalWrite(_stepPin, LOW);
    delayMicroseconds(2); // Minimum LOW pulse width
}
