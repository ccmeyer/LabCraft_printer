#ifndef STEPPER_MOTOR_H
#define STEPPER_MOTOR_H

#include <TMCStepper.h>
#include <AccelStepper.h>
#include <Arduino.h>


class StepperMotor {
public:
    StepperMotor(int enablePin, int dirPin, int stepPin, int Rx, int Tx, float R_SENSE);
    void setupMotor(uint16_t rmsCurrent, uint16_t microsteps, uint16_t maxSpeed, uint16_t acceleration);
    void moveTo(long steps);
    void microsteps(int microsteps);
    void rms_current(int rmsCurrent);
    void setMaxSpeed(int16_t maxSpeed);
    void setAcceleration(int16_t acceleration);
    void setSpeed(int16_t speed);
    void runSpeed();
    void run();
    void stop();
    void move(long steps);
    long currentPosition();
    void setCurrentPosition(long position);
    long distanceToGo();
    void enableOutputs();
    void disableOutputs();
    // Add more functions as needed

private:
    TMC2208Stepper driver;
    AccelStepper stepper;
    int enablePin;
    // Add more member variables as needed
};

#endif