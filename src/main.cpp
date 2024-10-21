#include <Arduino.h>

#include <HardwareSerial.h>
#include "GripperStepper.h"

#include "pin_assignments.h"
#include "all_constants.h"

HardwareSerial SerialUART1(USART2);
TMC2209Stepper driver(&SerialUART1, 0.11f, 0b00);

bool gripperOpen = false;

void setup() {
    Serial.begin(115200);
    while(!Serial);
    delay(1000);
    Serial.println("Serial initialized");
    delay(1000);
    SerialUART1.setTx(GRIPPER_UART_TX);
    SerialUART1.setRx(GRIPPER_UART_RX);
    // SerialUART1.setHalfDuplex(); // Enable half-duplex mode
    SerialUART1.begin(115200);
    Serial.println("Gripper UART initialized");

    // Serial.print("Half-duplex mode: ");
    // Serial.println(SerialUART1.isHalfDuplex());
    // SerialUART1.enableHalfDuplexRx();

    driver.beginSerial(115200);

    pinMode(GRIPPER_EN, OUTPUT);
    pinMode(GRIPPER_STEP, OUTPUT);
    pinMode(GRIPPER_DIR, OUTPUT);

    digitalWrite(GRIPPER_EN, LOW);
    driver.begin();
    driver.toff(4);
    driver.blank_time(24);
    driver.rms_current(1800); // mA
    driver.microsteps(256);
    // driver.TCOOLTHRS(0xFFFFF); // 20bit max
    // driver.semin(5);
    // driver.semax(2);
    // driver.sedn(0b01);
    // driver.SGTHRS(100);
    Serial.println("DEBUG:End Config");
    uint8_t result = driver.test_connection();
    Serial.print("Test connection result: ");
    Serial.println(result);
    uint32_t gconf = driver.GCONF();
    Serial.print("GCONF: 0x");
    Serial.println(gconf, HEX);
}

void loop() {
  // SerialUART1.write('A'); // Send a character
  // delay(100);

  // if (SerialUART1.available()) {
  //     char c = SerialUART1.read();
  //     Serial.print("Received: ");
  //     Serial.println(c);
  // } else {
  //     Serial.println("No data received.");
  // }
  // delay(1000);
  if (gripperOpen) {
      Serial.println("Opening gripper");
      digitalWrite(GRIPPER_DIR, LOW); // Adjust based on your setup
  } else {
      Serial.println("Closing gripper");
      digitalWrite(GRIPPER_DIR, HIGH); // Adjust based on your setup
  }
  
  const int steps = 10000; // Adjust as needed
  // driver.microsteps(8);
  uint16_t sg_result = driver.SG_RESULT();
  uint16_t stall_counter = 0;
  for (int i = 0; i < steps; i++) {
      digitalWrite(GRIPPER_STEP, HIGH);
      delayMicroseconds(2); // Minimum HIGH pulse width
      digitalWrite(GRIPPER_STEP, LOW);
      delayMicroseconds(2); // Minimum LOW pulse width
      // sg_result = driver.SG_RESULT();
      // if (sg_result < 30) {
      //     stall_counter++;
      //     if (stall_counter > 10) {
      //         Serial.print("Stall detected-");
      //         Serial.println(sg_result);
      //         gripperOpen = !gripperOpen;
      //         delay(1000);
      //         break;
      //     }
      // } else {
      //       stall_counter = 0;
      // }
      delayMicroseconds(100);
      // Serial.println("DEBUG:Opening gripper step");
  }
  // uint16_t sg_result = driver.SG_RESULT();
  // Serial.println(sg_result);
  delay(500);
  gripperOpen = !gripperOpen;

  // Serial.println("Closing gripper");
  // digitalWrite(GRIPPER_DIR, HIGH); // Adjust based on your setup
  // const int closeSteps = 1000; // Adjust as needed
  // // driver.microsteps(64);
  // for (int i = 0; i < closeSteps; i++) {
  //     digitalWrite(GRIPPER_STEP, HIGH);
  //     delayMicroseconds(2); // Minimum HIGH pulse width
  //     digitalWrite(GRIPPER_STEP, LOW);
  //     delayMicroseconds(2); // Minimum LOW pulse width
  //     delayMicroseconds(500);
      
  // }
  // delay(500);
  // sg_result = driver.SG_RESULT();
  // Serial.println(sg_result);
  // delay(50);

}