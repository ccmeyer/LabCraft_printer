#ifndef PIN_ASSIGNMENTS_H
#define PIN_ASSIGNMENTS_H
#include <Arduino.h>

const int ledPin = PA13;

//== FAN PINS ===========================================
const int printPin = PA8;           // Fan0
const int pumpValvePin1 = PE5;            // Fan1
const int pumpValvePin2 = PD12;     // Fan2
const int pumpPin = PD13;     // Fan3
const int printValvePin = PD14;      // Fan4
const int Fan5 = PD15;      // Fan5

//== LIMIT SWITCH PINS ===========================================
const int xstop = PG6;
const int ystop = PG9;
const int zstop = PG10;
const int pstop = PG11;

//==STEPPER MOTOR PINS ===========================================

// --DRIVER 0--
// Standard control modality
const int Z_EN_PIN = PF14;      // Enable - EN pin top left
const int Z_DIR_PIN = PF12;     // Direction - DIR pin bottom left
const int Z_STEP_PIN = PF13;    // Step - STP pin second from bottom left

// UART communication - Requires jumper in JXC between pins 1 and 2 (second from left column, X is for driver number)
const int Z_SW_TX = PC4;        // UART-SoftwareSerial receive pin - Attached to the DRIVERX_CS pins of the motor
const int Z_SW_RX = Z_SW_TX;    // UART-SoftwareSerial transmit pin - Uses the same pin as receive

// --DRIVER 1--
// Standard control modality
const int Y_EN_PIN = PF15;      // Enable - EN pin top left
const int Y_DIR_PIN = PG1;     // Direction - DIR pin bottom left
const int Y_STEP_PIN = PG0;    // Step - STP pin second from bottom left

// UART communication - Requires jumper in JXC between pins 1 and 2 (second from left column, X is for driver number)
const int Y_SW_TX = PD11;        // UART-SoftwareSerial receive pin - Attached to the DRIVERX_CS pins of the motor
const int Y_SW_RX = Y_SW_TX;    // UART-SoftwareSerial transmit pin - Uses the same pin as receive

// --DRIVER 2-- Driver 2 has two ports: Motor2_1 and Motor2_2
// Standard control modality
const int X_EN_PIN = PG5;      // Enable - EN pin top left
const int X_DIR_PIN = PG3;     // Direction - DIR pin bottom left
const int X_STEP_PIN = PF11;    // Step - STP pin second from bottom left

// UART communication - Requires jumper in JXC between pins 1 and 2 (second from left column, X is for driver number)
const int X_SW_TX = PC6;        // UART-SoftwareSerial receive pin - Attached to the DRIVERX_CS pins of the motor
const int X_SW_RX = X_SW_TX;    // UART-SoftwareSerial transmit pin - Uses the same pin as receive

// --DRIVER 3--
// Standard control modality
const int P_EN_PIN = PA0;      // Enable - EN pin top left
const int P_DIR_PIN = PC1;     // Direction - DIR pin bottom left
const int P_STEP_PIN = PG4;    // Step - STP pin second from bottom left

// UART communication - Requires jumper in JXC between pins 1 and 2 (second from left column, X is for driver number)
const int P_SW_TX = PC7;        // UART-SoftwareSerial receive pin - Attached to the DRIVERX_CS pins of the motor
const int P_SW_RX = P_SW_TX;    // UART-SoftwareSerial transmit pin - Uses the same pin as receive







#endif
