#ifndef PIN_ASSIGNMENTS_H
#define PIN_ASSIGNMENTS_H
#include <Arduino.h>

const int ledPin = PA13;    // Onboard LED

//== FAN PINS ===========================================
const int printPin = PE5;       // Fan1 - J51
const int pumpValvePin = PA8;  // Fan0 - J50
// const int pumpValvePin2 = PD12; // Fan2 - J52
const int refuelPin = PD12;     // Fan2 - J52
const int pumpPin = PD13;       // Fan3 - J53
const int printValvePin = PD14; // Fan4 - J54
const int refuelValvePin = PD15; // Fan5 - J55

//== LIMIT SWITCH PINS ===========================================
const int xstop = PG6;  // DIAG0 - J27
const int ystop = PG9;  // DIAG1 - J29
const int zstop = PG10; // DIAG2 - J31
const int pstop = PG11; // DIAG3 - J33
const int rstop = PG12; // DIAG4 - J35

//==STEPPER MOTOR PINS ===========================================

// --DRIVER 0--
// Standard control modality
const bool Z_INV_DIR = true; // Invert direction for Motor0_1
const int Z_EN_PIN = PF14;      // Enable - EN pin top left
const int Z_DIR_PIN = PF12;     // Direction - DIR pin bottom left
const int Z_STEP_PIN = PF13;    // Step - STP pin second from bottom left

// UART communication - Requires jumper in JXC between pins 1 and 2 (second from left column, X is for driver number)
const int Z_SW_TX = PC4;        // UART-SoftwareSerial receive pin - Attached to the DRIVERX_CS pins of the motor
const int Z_SW_RX = Z_SW_TX;    // UART-SoftwareSerial transmit pin - Uses the same pin as receive

// --DRIVER 1--
// Standard control modality
const bool Y_INV_DIR = false; // Invert direction for Motor1_1
const int Y_EN_PIN = PF15;      // Enable - EN pin top left
const int Y_DIR_PIN = PG1;     // Direction - DIR pin bottom left
const int Y_STEP_PIN = PG0;    // Step - STP pin second from bottom left

// UART communication - Requires jumper in JXC between pins 1 and 2 (second from left column, X is for driver number)
const int Y_SW_TX = PD11;        // UART-SoftwareSerial receive pin - Attached to the DRIVERX_CS pins of the motor
const int Y_SW_RX = Y_SW_TX;    // UART-SoftwareSerial transmit pin - Uses the same pin as receive

// --DRIVER 2-- Driver 2 has two ports: Motor2_1 and Motor2_2
// Motor2_1 - X right side - Uses modified wiring green, black, blue, red
// Motor2_2 - X left side - Uses standard wiring red, blue, green, black
// Standard control modality
const bool X_INV_DIR = false; // Invert direction for Motor2_1
const int X_EN_PIN = PG5;      // Enable - EN pin top left
const int X_DIR_PIN = PG3;     // Direction - DIR pin bottom left
const int X_STEP_PIN = PF11;    // Step - STP pin second from bottom left

// UART communication - Requires jumper in JXC between pins 1 and 2 (second from left column, X is for driver number)
const int X_SW_TX = PC6;        // UART-SoftwareSerial receive pin - Attached to the DRIVERX_CS pins of the motor
const int X_SW_RX = X_SW_TX;    // UART-SoftwareSerial transmit pin - Uses the same pin as receive

// --DRIVER 3--
// Standard control modality
const bool P_INV_DIR = false; // Invert direction for Motor3_1
const int P_EN_PIN = PA0;      // Enable - EN pin top left
const int P_DIR_PIN = PC1;     // Direction - DIR pin bottom left
const int P_STEP_PIN = PG4;    // Step - STP pin second from bottom left

// UART communication - Requires jumper in JXC between pins 1 and 2 (second from left column, X is for driver number)
const int P_SW_TX = PC7;        // UART-SoftwareSerial receive pin - Attached to the DRIVERX_CS pins of the motor
const int P_SW_RX = P_SW_TX;    // UART-SoftwareSerial transmit pin - Uses the same pin as receive

// --DRIVER 4--
// Standard control modality
const bool R_INV_DIR = false; // Invert direction for Motor4_1
const int R_EN_PIN = PG2;      // Enable - EN pin top left
const int R_DIR_PIN = PF10;     // Direction - DIR pin bottom left
const int R_STEP_PIN = PF9;    // Step - STP pin second from bottom left

// UART communication - Requires jumper in JXC between pins 1 and 2 (second from left column, X is for driver number)
const int R_SW_TX = PF2;        // UART-SoftwareSerial receive pin - Attached to the DRIVERX_CS pins of the motor
const int R_SW_RX = R_SW_TX;    // UART-SoftwareSerial transmit pin - Uses the same pin as receive


// --I2C communication--
// All I2C pins in J73
// top to bottom: 3V3, GND, SCL, SDA
// Two columns with duplicate pins
// SCL - PB8
// SDA - PB9
// Wire color top to bottom: black, green, red, blue





#endif
