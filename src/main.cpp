#include <Arduino.h>

// The section below comes from this git repo: https://github.com/maxgerhardt/nucleo-f446ze-with-arduino/tree/main
// It was originally located after the void loop() but I moved it up to make sure that I set the
// clock speed before beginning the other communication.
extern "C" void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};
  RCC_PeriphCLKInitTypeDef PeriphClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);
  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLM = 6;
  RCC_OscInitStruct.PLL.PLLN = 168;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = 7;
  RCC_OscInitStruct.PLL.PLLR = 3;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }
  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV4;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV2;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_5) != HAL_OK)
  {
    Error_Handler();
  }
  PeriphClkInitStruct.PeriphClockSelection = RCC_PERIPHCLK_CLK48;
  PeriphClkInitStruct.Clk48ClockSelection = RCC_CLK48CLKSOURCE_PLLQ;
  if (HAL_RCCEx_PeriphCLKConfig(&PeriphClkInitStruct) != HAL_OK)
  {
    Error_Handler();
  }
}

#include <TMCStepper.h>         // Sets up UART communication
#include <AccelStepper.h>       // Coordinates motor movements
#include <Wire.h>
#include "pin_assignments.h"
#include "pin_functions.h"
#include "StepperMotor.h"
#include "all_constants.h"
#include "PressureSensor.h"

bool xstopPressed = false;

// Limit switch variables
int limitXstate = 0;
unsigned long switch_time = 0;
unsigned long last_switch_time = 0;
int debounce = 50;

// Printing variables
int currentDroplets = 0;
int targetDroplets = 0;
int newDroplets = 0;

// Gripper variables
bool gripperActive = false;
bool gripperClosed = false;
bool gripperPumpOn = false;

// Pressure control variables
bool manualControl = false;
bool printSyringeOpen = false;
bool refuelSyringeOpen = false;
bool resetP = false;
bool resetR = false;

int changeCurrent = 0;

bool motorsActive = false;

// BIDIRECTIONAL SERIAL COMMUNICATION VARIABLES

const byte numChars = 32;
char receivedChars[numChars];
char tempChars[numChars];        // temporary array for use when parsing

// variables to hold the parsed data
char commandID[numChars] = {0};
String command = "";
int stepsX = 0;
int stepsY = 0;
int stepsZ = 0;
int stepsP = 0;
int stepsR = 0;
bool correctPos = true;

String state = "Free";
int updateCounter = 0;
String event = "";
bool newData = false;

StepperMotor motorZ = StepperMotor(X_EN_PIN,X_DIR_PIN,X_STEP_PIN,X_SW_RX,X_SW_TX,R_SENSE);
StepperMotor motorY = StepperMotor(Y_EN_PIN,Y_DIR_PIN,Y_STEP_PIN,Y_SW_RX,Y_SW_TX,R_SENSE);
StepperMotor motorX = StepperMotor(Z_EN_PIN,Z_DIR_PIN,Z_STEP_PIN,Z_SW_RX,Z_SW_TX,R_SENSE);
StepperMotor motorP = StepperMotor(P_EN_PIN,P_DIR_PIN,P_STEP_PIN,P_SW_RX,P_SW_TX,R_SENSE);

PressureSensor pressureSensor = PressureSensor(TCAAddress, sensorAddress);


void XlimitISR() {
  switch_time = millis();
  if (switch_time - last_switch_time > debounce){
    digitalWrite(ledPin, HIGH);
    motorX.stop();
    motorY.stop();
    motorZ.stop();
    last_switch_time = switch_time;
  } 
}

void readSerial(){
  static bool recvInProgress = false;
  static byte ndx = 0;
  char startMarker = '<';
  char endMarker = '>';
  char rc;

  while (Serial.available() > 0) {

    rc = Serial.read();

    if (recvInProgress == true) {
      if (rc != endMarker) {
        receivedChars[ndx] = rc;
        ndx++;
        if (ndx >= numChars) {
          ndx = numChars - 1;
        }
      }
      else {
        receivedChars[ndx] = '\0'; // terminate the string
        recvInProgress = false;
        ndx = 0;
        newData = true;
      }
    }
    else if (rc == startMarker) {
      recvInProgress = true;
    }
  }
}

void parseData() {      // split the data into its parts
  strcpy(tempChars, receivedChars);
  char * strtokIndx; // this is used by strtok() as an index
  
  strtokIndx = strtok(tempChars,",");      // get the first part - the command ID
  strcpy(commandID, strtokIndx); // copy it to messageFromPC
  command = String(commandID);
  if (command == "relativeXYZ"){
    strtokIndx = strtok(NULL, ","); // this continues where the previous call left off
    stepsX = atoi(strtokIndx);     // convert this part to an integer
    
    strtokIndx = strtok(NULL, ","); 
    stepsY = atoi(strtokIndx);    
    
    strtokIndx = strtok(NULL, ",");
    stepsZ = atoi(strtokIndx);     

    motorX.moveTo(motorX.currentPosition()+stepsX);
    motorY.moveTo(motorY.currentPosition()+stepsY);
    motorZ.moveTo(motorZ.currentPosition()+stepsZ);
    correctPos = false;
    state = "MovingXYZ";
  }
  else if (command == "absoluteXYZ"){
    strtokIndx = strtok(NULL, ","); // this continues where the previous call left off
    stepsX = atoi(strtokIndx);     // convert this part to an integer
    
    strtokIndx = strtok(NULL, ","); 
    stepsY = atoi(strtokIndx);    
    
    strtokIndx = strtok(NULL, ",");
    stepsZ = atoi(strtokIndx);     

    motorX.moveTo(stepsX);
    motorY.moveTo(stepsY);
    motorZ.moveTo(stepsZ);
    correctPos = false;
    state = "MovingXYZ";
  }
  else if (command == "relativePR"){
    strtokIndx = strtok(NULL, ","); // this continues where the previous call left off
    changeP = atoi(strtokIndx);     // convert this part to an integer
    
    strtokIndx = strtok(NULL, ","); 
    changeR = atoi(strtokIndx);

    targetPressureP = targetPressureP + changeP;
    targetPressureR = targetPressureR + changeR;

    changeP = 0;
    changeR = 0;

    state = "Changing pressures";
  }
  else if (command == "absolutePR"){
    strtokIndx = strtok(NULL, ","); // this continues where the previous call left off
    changeP = atoi(strtokIndx);     // convert this part to an integer
    
    strtokIndx = strtok(NULL, ","); 
    changeR = atoi(strtokIndx);

    targetPressureP = changeP;
    targetPressureR = changeR;

    changeP = 0;
    changeR = 0;

    state = "Changing pressures";
  }
  else if (command == "relativeCurrent"){
    strtokIndx = strtok(NULL, ","); // this continues where the previous call left off
    changeCurrent = atoi(strtokIndx);     // convert this part to an integer

    rmsCurrent = rmsCurrent + changeCurrent;
    motorX.rms_current(rmsCurrent);
    motorY.rms_current(rmsCurrent);
    motorZ.rms_current(rmsCurrent);
    motorP.rms_current(rmsCurrent);

    changeCurrent = 0;

    state = "Changing current";
  }
  else if (command == "resetXYZ"){
    motorX.setCurrentPosition(0);
    motorY.setCurrentPosition(0);
    motorZ.setCurrentPosition(0);
    state = "resetting XYZ";
  }
  else if (command == "print"){
    strtokIndx = strtok(NULL, ","); // this continues where the previous call left off
    newDroplets = atoi(strtokIndx);     // convert this part to an integer
    targetDroplets = targetDroplets + newDroplets;
    state = "Printing";
  } 
  else if (command == "openP"){
    manualControl = true;
    digitalWrite(printValvePin, HIGH);
    printSyringeOpen = true;
    delay(50);
  }
  else if (command == "closeP"){
    digitalWrite(printValvePin, LOW);
    delay(50);
    printSyringeOpen = false;
    manualControl = false;
    motorP.setCurrentPosition(0);
  }
  else if (command == "resetP") {
    motorP.stop();
    resetP = true;
    digitalWrite(printValvePin, HIGH);
    printSyringeOpen = true;
    delay(50);
    motorP.moveTo(0);
    motorP.run();
  }
  else if (command == "gripperToggle"){
    if (gripperActive == false) {
      gripperActive = true;
    }
    if (gripperClosed == false){
      digitalWrite(pumpValvePin1, LOW);
      digitalWrite(pumpValvePin2, LOW);
      digitalWrite(pumpPin, HIGH);

      gripperPumpOn = true;
      gripperClosed = true;
      unsigned long currentMillis = millis();
      previousMillisGripperOn = currentMillis;
    } else {
      digitalWrite(pumpValvePin1, HIGH);
      digitalWrite(pumpValvePin2, HIGH);
      digitalWrite(pumpPin, HIGH);
      delay(300);
      gripperPumpOn = true;
      gripperClosed = false;
      unsigned long currentMillis = millis();
      previousMillisGripperOn = currentMillis;
    }
  }
  else if (command == "gripperOff"){
    digitalWrite(pumpValvePin1, LOW);
    digitalWrite(pumpValvePin2, LOW);
    digitalWrite(pumpPin, LOW);
    gripperActive = false;
    gripperClosed = false;
  }
  else if (command == "enable"){
    motorX.enableOutputs();
    motorY.enableOutputs();
    motorZ.enableOutputs();
    motorP.enableOutputs();
    motorsActive = true;
  }
  else if (command == "disable"){
    motorX.disableOutputs();
    motorY.disableOutputs();
    motorZ.disableOutputs();
    motorP.disableOutputs();
    motorsActive = false;
  }
  else {
    digitalWrite(ledPin,HIGH);
    delay(500);
    digitalWrite(ledPin,LOW);
    state = "Free";
  }
  newData = false;
}

void setup() {
	Serial.begin(115200);
  while(!Serial);

  setupPins();

  SPI.begin();
  motorX.setupMotor(rmsCurrent,microsteps,maxSpeedXYZ,accelerationXYZ);   // rmsCurrent,microsteps,maxSpeed,acceleration
  motorY.setupMotor(rmsCurrent,microsteps,maxSpeedXYZ,accelerationXYZ);   // rmsCurrent,microsteps,maxSpeed,acceleration
  motorZ.setupMotor(rmsCurrent,microsteps,maxSpeedXYZ,accelerationXYZ);   // rmsCurrent,microsteps,maxSpeed,acceleration
  motorP.setupMotor(rmsCurrent,microsteps,maxSpeedP,accelerationP);   // rmsCurrent,microsteps,maxSpeed,acceleration
  
  pressureSensor.resetPressure();
  pressureSensor.beginCommunication(sdaPin,sclPin);
  
  delay(500);
  blinkLED();
  blinkLED();
}

void loop() {
  unsigned long currentMillis = millis();

  if (currentMillis - previousMillisLimit > intervalLimit) {
    previousMillisLimit = currentMillis;
    xstopPressed = digitalRead(xstop);
    if (xstopPressed == true){
      XlimitISR();
    }
    else {
      digitalWrite(ledPin, LOW);      
    }
  }

  if (currentMillis - previousMillisPressure > intervalPressure) {
    previousMillisPressure = currentMillis;
    currentPressure = pressureSensor.smoothPressure();
  }

  if (currentMillis - previousMillisWrite > intervalWrite) {
    previousMillisWrite = currentMillis;
    // currentPressure = pressureSensor.getPressure();
    Serial.print("Serial:");
    Serial.print(state);
    Serial.print(",");
    Serial.print("Event:");
    Serial.print(event);
    Serial.print(",");
    Serial.print("X:");
    Serial.print(motorX.currentPosition());
    Serial.print(",");
    Serial.print("Y:");
    Serial.print(motorY.currentPosition());
    Serial.print(",");
    Serial.print("Z:");
    Serial.print(motorZ.currentPosition());
    Serial.print(",");
    Serial.print("P:");
    Serial.print(motorP.currentPosition());
    Serial.print(",");
    Serial.print("Current:");
    Serial.print(rmsCurrent);
    Serial.print(",");
    Serial.print("Print_valve:");
    Serial.print(printSyringeOpen);
    Serial.print(",");
    Serial.print("Droplets:");
    Serial.print(currentDroplets);
    Serial.print(",");
    Serial.print("Set_print:");
    Serial.print(targetPressureP);
    Serial.print(",");
    Serial.print("Print_pressure:");
    Serial.println(currentPressure);
  }

  // Read data coming from the Serial communication with the PC
  if (currentMillis - previousMillisRead > intervalRead && state == "Free" && newData == false) {
    previousMillisRead = currentMillis;
    readSerial();
  }

  // If new data is found parse the signal and execute the command
  if (newData == true){
    parseData();
  }

  // Drive motors sequentially, X before Y, Y before Z
  if (motorY.distanceToGo() != 0) {
    motorY.run();
    correctPos = false;
    state = "MovingY";
  } else if (motorX.distanceToGo() != 0){
    motorX.run();
    correctPos = false;
    state = "MovingX";
  } else if (motorZ.distanceToGo() != 0){
    motorZ.run();
    correctPos = false;
    state = "MovingZ";
  } else {
    correctPos = true;
  }

  // Checks if droplets needed to be printed and prints if in the right position
  if (correctPos == true && currentDroplets < targetDroplets){
    if (currentPressure > targetPressureP - toleranceDroplet && currentPressure < targetPressureP + toleranceDroplet && resetP == false){
      state = "Printing";
      if (currentMillis - previousMillisDroplet > intervalDroplet) {
        previousMillisDroplet = currentMillis;
        digitalWrite(printPin, HIGH);
        delayMicroseconds(3000);
        digitalWrite(printPin, LOW);
        currentDroplets++;
      }
    }
  }

  // Pass a signal to the PC that it is open for the next command
  if (correctPos == true && currentDroplets == targetDroplets){
    state = "Free";
  }

  // Adjust the syringe pump to maintain the desired pressure
  // Resetting begins when the plunger is near the end of the syringe
  // the valve connected to the syringe is opened and the plunger is pulled to the back of the syringe to reset the position
  if (motorsActive == true && manualControl == false){

    if (resetP == true && motorP.distanceToGo() != 0) //Continue resetting
    { 
      motorP.run();
    } 
    else if (resetP == true && motorP.distanceToGo() == 0) //Flag reset complete
    {
      digitalWrite(printValvePin, LOW);
      printSyringeOpen = false;
      delay(50);
      resetP = false;
    }
    else if (resetP == false)
    {
      if (motorP.currentPosition() < lowerBound || motorP.currentPosition() > upperBound) // Start reset
      {
        motorP.stop();
        resetP = true;
        digitalWrite(printValvePin, HIGH);
        printSyringeOpen = true;
        delay(50);
        motorP.moveTo(0);
        motorP.run();

        // Drives the syringe motor fast or slow depending on the desired pressure change
      } else if (currentPressure > targetPressureP + 1000) {
        motorP.setSpeed(20*steps_per_mm);
        motorP.move(100);
        motorP.runSpeed();
      } else if (currentPressure < targetPressureP - 1000) {
        motorP.setSpeed(-20*steps_per_mm);
        motorP.move(-100);
        motorP.runSpeed();
      } else if (currentPressure > targetPressureP + tolerancePump) {
        motorP.setSpeed(5*steps_per_mm);
        motorP.move(10);
        motorP.runSpeed();
      } else if (currentPressure < targetPressureP - tolerancePump) {
        motorP.setSpeed(-5*steps_per_mm);
        motorP.move(-10);
        motorP.runSpeed();
      } else {
        motorP.stop();
      }
    } 
    // else if (resetP == false && currentPressure != 0) {
    //   state = "P-state wrong";
    // }
  }

  // Gripper shutoff when the timer for the pump is over
  if (gripperPumpOn == true) {
    if (currentMillis - previousMillisGripperOn > intervalGripperOn) {
      previousMillisGripperOn = currentMillis;
      digitalWrite(pumpPin, LOW);
      gripperPumpOn = false;
    }
  }
  
  // Refresh the vacuum in the gripper on a constant interval
  if (gripperActive == true) {
    if (currentMillis - previousMillisGripperOn > intervalGripperRestart) {
      digitalWrite(pumpPin, HIGH);
      previousMillisGripperOn = currentMillis;
      gripperPumpOn = true;
    }
  }
}