// #pragma once
#ifndef ALL_CONSTANTS_H
#define ALL_CONSTANTS_H
#include <Arduino.h>

// // Stepper motor variables
int rmsCurrent = 1000;
int microsteps = 8;
int steps_per_mm = 80;      //TODO - Figure out actual steps to mm conversions
// int steps_per_mm = 320;      //TODO - Figure out actual steps to mm conversions
float R_SENSE = 0.11f;           // SilentStepStick series use 0.11
uint16_t maxSpeedXYZ = 50*steps_per_mm;
uint16_t accelerationXYZ = 300*steps_per_mm;
uint16_t maxSpeedP = 50*steps_per_mm;
uint16_t accelerationP = 50*steps_per_mm;

// Pressure sensor variables
int TCAAddress = 0x70;
int sensorAddress = 40;
float currentPressure;
const int sdaPin = PB9;
const int sclPin = PB8;

const int syringeMaxSpeed = 1500;      // Maximum speed when far from target pressure
const int syringeMinSpeed = 300;       // Minimum speed when close to target pressure
const int toleranceSyringe = 3;  // Tolerance range around target pressure
const int cutoffSyringe = 200;

int pressureDifference;
int syringeSpeed;

int targetPressureP = 1638;
int toleranceDroplet = 20;
int changeP = 0;
int changeR = 0;

int lowerBound = -25000;
int upperBound = 300;

int debounceAll = 50;

int currentCmdNum = 0;
int lastAddedCmdNum = 0;

// LED variables
int startDelay = 3000;
int flashDuration = 2000;
int flashInterval = 25;
int numFlashes = 1;

// Timing variables
// unsigned long previousMillisWrite = 0;
// unsigned long intervalWrite = 51;

// unsigned long previousMillisRead = 0;
// unsigned long intervalRead = 11;

// unsigned long previousMillisPressure = 0;
// unsigned long intervalPressure = 9; // 120msec / 255cycles ~= 0.5 msec/cycle

unsigned long previousMillisDroplet = 0;
unsigned long intervalDroplet = 47;

// unsigned long previousMillisGripperOn = 0;
// unsigned long intervalGripperOn = 500;

// unsigned long previousMillisGripperRestart = 0;
// unsigned long intervalGripperRestart = 60000;

// unsigned long previousMillisLimit = 0;
// unsigned long intervalLimit = 2;


#endif