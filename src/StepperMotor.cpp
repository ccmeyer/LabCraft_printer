#include "StepperMotor.h"
#include <TMCStepper.h>
#include <AccelStepper.h>


StepperMotor::StepperMotor(int enablePin, int dirPin, int stepPin, int Rx, int Tx, float R_SENSE)
    : stepper(AccelStepper::DRIVER, stepPin, dirPin), driver(Rx,Tx,R_SENSE), enablePin(enablePin)  {
    // Initialize any other member variables if needed
}

void StepperMotor::setupMotor(uint16_t rmsCurrent, uint16_t microsteps, uint16_t maxSpeed, uint16_t acceleration) {
    // Initialize TMCstepper object
    driver.begin();
    driver.rms_current(rmsCurrent);
    driver.microsteps(microsteps);
    driver.pwm_autoscale(1);

    // Initialize AccelStepper object
    stepper.setMaxSpeed(maxSpeed); // 100mm/s @ 80 steps/mm
    stepper.setAcceleration(acceleration); // 2000mm/s^2
    stepper.setEnablePin(enablePin);
    stepper.setPinsInverted(false, false, true);   //TODO - figure out if this is necessary
    stepper.disableOutputs();
}

void StepperMotor::setMaxSpeed(int16_t maxSpeed)
{
    stepper.setMaxSpeed(maxSpeed);
}

void StepperMotor::setAcceleration(int16_t acceleration)
{
    stepper.setAcceleration(acceleration);
}

void StepperMotor::setSpeed(int16_t speed)
{
    stepper.setSpeed(speed);
}

void StepperMotor::runSpeed()
{
    stepper.runSpeed();
}

void StepperMotor::rms_current(int rmsCurrent)
{
    driver.rms_current(rmsCurrent);
}

void StepperMotor::moveTo(long steps)
{
    stepper.moveTo(steps);
}

void StepperMotor::microsteps(int microsteps)
{
    driver.microsteps(microsteps);
}

void StepperMotor::run()
{
    stepper.run();
}

void StepperMotor::stop()
{
    stepper.stop();
}

void StepperMotor::move(long steps)
{
    stepper.move(steps);
}

long StepperMotor::currentPosition()
{
    return stepper.currentPosition();
}

void StepperMotor::setCurrentPosition(long position)
{
    stepper.setCurrentPosition(position);
}

long StepperMotor::distanceToGo()
{
    return stepper.distanceToGo();
}

void StepperMotor::enableOutputs()
{
    stepper.enableOutputs();
}

void StepperMotor::disableOutputs()
{
    stepper.disableOutputs();
}