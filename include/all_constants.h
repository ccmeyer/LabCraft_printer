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
uint16_t maxSpeedXYZ = 100*steps_per_mm;
uint16_t accelerationXYZ = 100*steps_per_mm;
uint16_t maxSpeedP = 50*steps_per_mm;
uint16_t accelerationP = 50*steps_per_mm;

// Pressure sensor variables
int TCAAddress = 0x70;
int sensorAddress = 40;
float currentPressure;
const int sdaPin = PB9;
const int sclPin = PB8;

int targetPressureP = 1600;
int targetPressureR = 1600;
int tolerancePump = 100;
int toleranceDroplet = 400;
int changeP = 0;
int changeR = 0;

int lowerBound = -10000;
int upperBound = 1000;

// Timing variables
unsigned long previousMillisWrite = 0;
unsigned long intervalWrite = 100;

unsigned long previousMillisRead = 0;
unsigned long intervalRead = 21;

unsigned long previousMillisPressure = 0;
unsigned long intervalPressure = 6; // 120msec / 255cycles ~= 0.5 msec/cycle

unsigned long previousMillisDroplet = 0;
unsigned long intervalDroplet = 47;

unsigned long previousMillisGripperOn = 0;
unsigned long intervalGripperOn = 500;

unsigned long previousMillisGripperRestart = 0;
unsigned long intervalGripperRestart = 60000;

unsigned long previousMillisLimit = 0;
unsigned long intervalLimit = 9;


#endif