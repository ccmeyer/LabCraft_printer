#include <Arduino.h>

// The section below comes from this git repo: https://github.com/maxgerhardt/nucleo-f446ze-with-arduino/tree/main
// It was originally located after the void loop() but I moved it up to make sure that I set the
// clock speed before beginning the other communication.

bool clockConfig = false;

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
  clockConfig = true;
}

#include <TMCStepper.h>         // Sets up UART communication
#include <AccelStepper.h>       // Coordinates motor movements
#include <Wire.h>
#include <queue>
#include "pin_assignments.h"
#include "pin_functions.h"
// #include "StepperMotor.h"
#include "all_constants.h"
#include "PressureSensor.h"

bool xstopPressed = false;
bool ystopPressed = false;
bool zstopPressed = false;
bool pstopPressed = false;

bool triggeredX = false;
bool triggeredY = false;
bool triggeredZ = false;
bool triggeredP = false;

// Limit switch variables
int limitXstate = 0;
unsigned long switch_time_X = 0;
unsigned long last_switch_time_X = 0;

int limitYstate = 0;
unsigned long switch_time_Y = 0;
unsigned long last_switch_time_Y = 0;

int limitZstate = 0;
unsigned long switch_time_Z = 0;
unsigned long last_switch_time_Z = 0;

int limitPstate = 0;
unsigned long switch_time_P = 0;
unsigned long last_switch_time_P = 0;

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

const byte numChars = 64;
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

unsigned long currentMillis;
unsigned long currentMicros;

unsigned long endMicros;
unsigned long cycleTime = 0;
static const int numCycles = 5;
unsigned long cycleTimes[numCycles];
int cycleIndex = 0;
unsigned long averageCycle = 0;
bool pressureRead = false;
unsigned long maxCycle = 0;

int numIterations = 0;

int frequency = 1000000;

bool pressureCorrect = false;
bool regulatePressure = false;

// StepperMotor motorZ = StepperMotor(X_EN_PIN,X_DIR_PIN,X_STEP_PIN,X_SW_RX,X_SW_TX,R_SENSE);
// StepperMotor motorY = StepperMotor(Y_EN_PIN,Y_DIR_PIN,Y_STEP_PIN,Y_SW_RX,Y_SW_TX,R_SENSE);
// StepperMotor motorX = StepperMotor(Z_EN_PIN,Z_DIR_PIN,Z_STEP_PIN,Z_SW_RX,Z_SW_TX,R_SENSE);
// StepperMotor motorP = StepperMotor(P_EN_PIN,P_DIR_PIN,P_STEP_PIN,P_SW_RX,P_SW_TX,R_SENSE);

// TMC2208Stepper driverX = TMC2208Stepper(X_SW_RX, X_SW_TX, R_SENSE); // Software serial
// TMC2208Stepper driverY = TMC2208Stepper(Y_SW_RX, Y_SW_TX, R_SENSE); // Software serial
// TMC2208Stepper driverZ = TMC2208Stepper(Z_SW_RX, Z_SW_TX, R_SENSE); // Software serial
// TMC2208Stepper driverP = TMC2208Stepper(P_SW_RX, P_SW_TX, R_SENSE); // Software serial

AccelStepper stepperX = AccelStepper(stepperX.DRIVER, X_STEP_PIN, X_DIR_PIN);
AccelStepper stepperY = AccelStepper(stepperY.DRIVER, Y_STEP_PIN, Y_DIR_PIN);
AccelStepper stepperZ = AccelStepper(stepperZ.DRIVER, Z_STEP_PIN, Z_DIR_PIN);
AccelStepper stepperP = AccelStepper(stepperP.DRIVER, P_STEP_PIN, P_DIR_PIN);

PressureSensor pressureSensor = PressureSensor(TCAAddress, sensorAddress);

// Reads the pressure sensor if it is the right time
void checkPressure(){
  if (currentMillis - previousMillisPressure > intervalPressure) {
    previousMillisPressure = currentMillis;
    currentPressure = pressureSensor.smoothPressure();
    pressureRead = true;
  }
}

enum HomingState {
    IDLE,
    X_HOMING,
    X_RETRACTION,
    X_RESET,
    Y_HOMING,
    Y_RETRACTION,
    Y_RESET,
    Z_HOMING,
    Z_RETRACTION,
    Z_RESET,
    P_HOMING,
    P_RETRACTION,
    P_RESET
};

HomingState homingState = IDLE;

void XlimitISR() {
  xstopPressed = digitalRead(xstop);
  if (xstopPressed == true){
    switch_time_X = millis();
    if (switch_time_X - last_switch_time_X > debounce){
      triggeredX = true;
      last_switch_time_X = switch_time_X;
      if (homingState == IDLE){
        stepperX.stop();
      }
    } 
  } else {
    triggeredX = false;
  }
}

void YlimitISR() {
  ystopPressed = digitalRead(ystop);
  if (ystopPressed == true){
    switch_time_Y = millis();
    if (switch_time_Y - last_switch_time_Y > debounce){
      triggeredY = true;
      last_switch_time_Y = switch_time_Y;
      if (homingState == IDLE){
        stepperY.stop();
      }
    } 
  } else {
    triggeredY = false;
  }
}

void ZlimitISR() {
  zstopPressed = digitalRead(zstop);
  if (zstopPressed == true){
    switch_time_Z = millis();
    if (switch_time_Z - last_switch_time_Z > debounce){
      triggeredZ = true;
      last_switch_time_Z = switch_time_Z;
      if (homingState == IDLE){
        stepperZ.stop();
      }
    } 
  } else {
    triggeredZ = false;
  }
}

void PlimitISR() {
  pstopPressed = digitalRead(pstop);
  if (pstopPressed == true){
    switch_time_P = millis();
    if (switch_time_P - last_switch_time_P > debounce){
      triggeredP = true;
      last_switch_time_P = switch_time_P;
      if (homingState == IDLE){
        stepperP.stop();
      }
    } 
  } else {
    triggeredP = false;
  }
}

enum LimitSwitch {
    LimitX,
    LimitY,
    LimitZ,
    LimitP,
    NUM_SWITCHES
};

LimitSwitch currentLimitSwitch = LimitX;
int numLimitSwitches = 4;

// Triggers the limit switch service routine
void readLimitSwitch(LimitSwitch current){
  switch (current){
    case LimitX:
      XlimitISR();
      break;
    case LimitY:
      YlimitISR();
      break;
    case LimitZ:
      ZlimitISR();
      break;
    case LimitP:
      PlimitISR();
      break;
    default:
      digitalWrite(ledPin, HIGH); 
      break;
  }
}

// Loops the limit switch back to the start
void cycleLimitSwitch() {
    currentLimitSwitch = static_cast<LimitSwitch>((static_cast<int>(currentLimitSwitch) + 1) % static_cast<int>(NUM_SWITCHES));
}

// Checks the next limit switch in the sequence
void checkLimitSwitches() {
  if (currentMillis - previousMillisLimit > intervalLimit) {
    previousMillisLimit = currentMillis;
    readLimitSwitch(currentLimitSwitch);
    cycleLimitSwitch();
  }
}

void homingProtocolXYZ(){
  switch(homingState){
    case IDLE:
      break;
    case X_HOMING:
      if (triggeredX == true){
        stepperX.stop();
        homingState = X_RETRACTION;
        state = "X-retracting";
      } else {
        stepperX.setSpeed(10*steps_per_mm);
        stepperX.move(100);
        stepperX.runSpeed();
      }
      break;
    case X_RETRACTION:
      if (triggeredX == false){
        stepperX.stop();
        stepperX.setCurrentPosition(0);
        stepperX.setSpeed(-10*steps_per_mm);
        stepperX.moveTo(-500);
        homingState = X_RESET;
      } else {
        stepperX.setSpeed(-1*steps_per_mm);
        stepperX.move(-10);
        stepperX.runSpeed();
      }
      break;
    case X_RESET:
      if (stepperX.currentPosition() == -500){
        stepperX.stop();
        homingState = Y_HOMING;
      } else {
        stepperX.run();
      }
      break;
    case Y_HOMING:
      if (triggeredY == true){
        stepperY.stop();
        homingState = Y_RETRACTION;
        state = "Y-retracting";
      } else {
        stepperY.setSpeed(-10*steps_per_mm);
        stepperY.move(-100);
        stepperY.runSpeed();
      }
      break;
    case Y_RETRACTION:
      if (triggeredY == false){
        stepperY.stop();
        stepperY.setCurrentPosition(0);
        stepperY.setSpeed(10*steps_per_mm);
        stepperY.moveTo(500);
        homingState = Y_RESET;
      } else {
        stepperY.setSpeed(1*steps_per_mm);
        stepperY.move(10);
        stepperY.runSpeed();
      }
      break;
    case Y_RESET:
      if (stepperY.currentPosition() == 500){
        stepperY.stop();
        homingState = Z_HOMING;
      } else {
        stepperY.run();
      }
      break;
    case Z_HOMING:
      if (triggeredZ == true){
        stepperZ.stop();
        homingState = Z_RETRACTION;
        state = "Z-retracting";
      } else {
        stepperZ.setSpeed(20*steps_per_mm);
        stepperZ.move(100);
        stepperZ.runSpeed();
      }
      break;
    case Z_RETRACTION:
      if (triggeredZ == false){
        stepperZ.stop();
        stepperZ.setCurrentPosition(0);
        stepperZ.setSpeed(-10*steps_per_mm);
        stepperZ.moveTo(-500);
        homingState = Z_RESET;
      } else {
        stepperZ.setSpeed(-2*steps_per_mm);
        stepperZ.move(-10);
        stepperZ.runSpeed();
      }
      break;
    case Z_RESET:
      if (stepperZ.currentPosition() == -500){
        stepperZ.stop();
        digitalWrite(printValvePin, HIGH);
        printSyringeOpen = true;
        delay(50);
        homingState = P_HOMING;
      } else {
        stepperZ.run();
      }
      break;
    case P_HOMING:
      if (triggeredP == true){
        stepperP.stop();
        homingState = P_RETRACTION;
        state = "P-retracting";
      } else {
        stepperP.setSpeed(20*steps_per_mm);
        stepperP.move(100);
        stepperP.runSpeed();
      }
      break;
    case P_RETRACTION:
      if (triggeredP == false){
        stepperP.stop();
        stepperP.setCurrentPosition(0);
        stepperP.setSpeed(-10*steps_per_mm);
        stepperP.moveTo(-500);
        homingState = P_RESET;
      } else {
        stepperP.setSpeed(-2*steps_per_mm);
        stepperP.move(-10);
        stepperP.runSpeed();
      }
      break;
    case P_RESET:
      if (stepperP.currentPosition() == -500){
        stepperP.stop();
        digitalWrite(printValvePin, LOW);
        printSyringeOpen = false;
        digitalWrite(printValvePin, HIGH);
        printSyringeOpen = true;
        delay(10);
        digitalWrite(printValvePin, LOW);
        printSyringeOpen = false;
        homingState = IDLE;
      } else {
        stepperP.run();
      }
      break;
    default:
      break;
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

    stepperX.moveTo(stepperX.currentPosition()+stepsX);
    stepperY.moveTo(stepperY.currentPosition()+stepsY);
    stepperZ.moveTo(stepperZ.currentPosition()+stepsZ);
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

    stepperX.moveTo(stepsX);
    stepperY.moveTo(stepsY);
    stepperZ.moveTo(stepsZ);
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
    // driverX.rms_current(rmsCurrent);
    // driverY.rms_current(rmsCurrent);
    // driverZ.rms_current(rmsCurrent);
    // driverP.rms_current(rmsCurrent);
    changeCurrent = 0;

    state = "Changing current";
  }
  else if (command == "resetXYZ"){
    stepperX.setCurrentPosition(0);
    stepperY.setCurrentPosition(0);
    stepperZ.setCurrentPosition(0);
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
    stepperP.setCurrentPosition(0);
  }
  else if (command == "resetP") {
    stepperP.stop();
    resetP = true;
    digitalWrite(printValvePin, HIGH);
    printSyringeOpen = true;
    delay(50);
    stepperP.moveTo(-1000);
    stepperP.run();
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
      // delay(300);
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
    stepperX.enableOutputs();
    stepperY.enableOutputs();
    stepperZ.enableOutputs();
    stepperP.enableOutputs();
    motorsActive = true;
  }
  else if (command == "disable"){
    stepperX.disableOutputs();
    stepperY.disableOutputs();
    stepperZ.disableOutputs();
    stepperP.disableOutputs();
    motorsActive = false;
  }
  else if (command == "homeAll"){
    homingState = X_HOMING;
    state = "X-Homing";
  }
  else if (command == "regPressure"){
    regulatePressure = true;
  }
  else if (command == "unregPressure"){
    regulatePressure = false;
  }
  else {
    blinkLED();
    state = "Free";
  }
  newData = false;
}

// Sends the current status of the machine to the computer via Serial
void sendStatus() {
  if (currentMillis - previousMillisWrite > intervalWrite) {
    previousMillisWrite = currentMillis;

    if (stepperY.distanceToGo() != 0) {
      state = "MovingY";
    } else if (stepperX.distanceToGo() != 0){
      state = "MovingX";
    } else if (stepperZ.distanceToGo() != 0){
      state = "MovingZ";
    } else if (currentDroplets != targetDroplets){
      state = "Printing";
    } else {
      state = "Free";
    }

    Serial.print("Serial:");
    Serial.print(state);
    Serial.print(",");
    Serial.print("Max_cycle:");
    Serial.print(maxCycle);
    Serial.print(",");
    Serial.print("Cycle_count:");
    Serial.print(numIterations);
    Serial.print(",");
    Serial.print("X:");
    Serial.print(stepperX.currentPosition());
    Serial.print(",");
    Serial.print("Y:");
    Serial.print(stepperY.currentPosition());
    Serial.print(",");
    Serial.print("Z:");
    Serial.print(stepperZ.currentPosition());
    Serial.print(",");
    Serial.print("P:");
    Serial.print(stepperP.currentPosition());
    Serial.print(",");
    Serial.print("Current:");
    Serial.print(stepsZ);
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
    numIterations = 0;
    maxCycle = 0;
  }
}

// Checks for and parses new commands
void getNewCommand(){
  // Read data coming from the Serial communication with the PC
  if (currentMillis - previousMillisRead > intervalRead && state == "Free" && newData == false) {
    previousMillisRead = currentMillis;
    readSerial();
  }

  // If new data is found parse the signal and execute the command
  if (newData == true){
    parseData();
  }
}

void checkMotors(){
  if (homingState == IDLE){
    if (stepperY.distanceToGo() != 0) {
      stepperY.run();
    } else if (stepperX.distanceToGo() != 0){
      stepperX.run();
    } else if (stepperZ.distanceToGo() != 0){
      stepperZ.run();
    } else {
      correctPos = true;
    }
  }
}

void printDroplet(){
  digitalWrite(printPin, HIGH);
  delayMicroseconds(3000);
  digitalWrite(printPin, LOW);
  currentDroplets++;
}

void checkDroplets(){
  if (correctPos == true && currentDroplets < targetDroplets){
    if (currentPressure > targetPressureP - toleranceDroplet && currentPressure < targetPressureP + toleranceDroplet && resetP == false){
      state = "Printing";
      if (currentMillis - previousMillisDroplet > intervalDroplet) {
        previousMillisDroplet = currentMillis;
        printDroplet();
        currentDroplets++;
      }
    }
  }
}

void adjustPressure(){
  // // Adjust the syringe pump to maintain the desired pressure
  // // Resetting begins when the plunger is near the end of the syringe
  // // the valve connected to the syringe is opened and the plunger is pulled to the back of the syringe to reset the position

  if (motorsActive == true && manualControl == false && regulatePressure == true){

    if (resetP == true && stepperP.distanceToGo() != 0) //Continue resetting
    { 
      stepperP.run();
    } 
    else if (resetP == true && stepperP.distanceToGo() == 0) //Flag reset complete
    {
      digitalWrite(printValvePin, LOW);
      printSyringeOpen = false;
      delay(50);
      resetP = false;
    }
    else if (resetP == false)
    {
      if (stepperP.currentPosition() < lowerBound || stepperP.currentPosition() > upperBound) // Start reset
      {
        stepperP.stop();
        resetP = true;
        digitalWrite(printValvePin, HIGH);
        printSyringeOpen = true;
        delay(50);
        stepperP.moveTo(0);
        stepperP.run();

        // Drives the syringe motor fast or slow depending on the desired pressure change
      } else if (currentPressure > targetPressureP + 1000) {
        pressureCorrect = false;
        stepperP.setSpeed(20*steps_per_mm);
        stepperP.move(100);
        stepperP.runSpeed();
      } else if (currentPressure < targetPressureP - 1000) {
        pressureCorrect = false;
        stepperP.setSpeed(-20*steps_per_mm);
        stepperP.move(-100);
        stepperP.runSpeed();
      } else if (currentPressure > targetPressureP + tolerancePump) {
        pressureCorrect = false;
        stepperP.setSpeed(5*steps_per_mm);
        stepperP.move(10);
        stepperP.runSpeed();
      } else if (currentPressure < targetPressureP - tolerancePump) {
        pressureCorrect = false;
        stepperP.setSpeed(-5*steps_per_mm);
        stepperP.move(-10);
        stepperP.runSpeed();
      } else {
        if (pressureCorrect == false){
          stepperP.stop();
          pressureCorrect = true;
        }
      }
    } 
  }
}

void checkGripper(){
  if (gripperPumpOn == true) {
    if (currentMillis - previousMillisGripperOn > intervalGripperOn) {
      previousMillisGripperOn = currentMillis;
      digitalWrite(pumpPin, LOW);
      gripperPumpOn = false;
    }
  }
}

// Refresh the vacuum in the gripper on a constant interval
void refreshGripper(){
  if (gripperActive == true) {
    if (currentMillis - previousMillisGripperOn > intervalGripperRestart) {
      digitalWrite(pumpPin, HIGH);
      previousMillisGripperOn = currentMillis;
      gripperPumpOn = true;
    }
  }
}

void getCycleTime(){
  if (pressureRead == true){
    endMicros = micros();
    cycleTime = endMicros - currentMicros;
    if (cycleTime > maxCycle){
      maxCycle = cycleTime;
    }
    pressureRead = false;
  }
}

unsigned long average (unsigned long * array, int len)  // assuming array is int.
{
  long sum = 0L ;  // sum will be larger than an item, long for safety.
  for (int i = 0 ; i < len ; i++)
    sum += array [i] ;
  return  ((unsigned long) sum) / len ;  // average will be fractional, so float may be appropriate.
}

void setup() {
  SystemClock_Config();
	Serial.begin(115200);
  while(!Serial);

  setupPins();

  // SPI.begin();
  // motorX.setupMotor(rmsCurrent,microsteps,maxSpeedXYZ,accelerationXYZ);   // rmsCurrent,microsteps,maxSpeed,acceleration
  // motorY.setupMotor(rmsCurrent,microsteps,maxSpeedXYZ,accelerationXYZ);   // rmsCurrent,microsteps,maxSpeed,acceleration
  // motorZ.setupMotor(rmsCurrent,microsteps,maxSpeedXYZ,accelerationXYZ);   // rmsCurrent,microsteps,maxSpeed,acceleration
  // motorP.setupMotor(rmsCurrent,microsteps,maxSpeedP,accelerationP);   // rmsCurrent,microsteps,maxSpeed,acceleration
  
  // driverX.begin();             // Initiate pins and registeries
  // driverX.rms_current(800);    // Set stepper current to 600mA. The command is the same as command TMC2130.setCurrent(600, 0.11, 0.5);
  // driverX.pwm_autoscale(1);
  // driverX.microsteps(8);

  stepperX.setMaxSpeed(100*steps_per_mm); // 100mm/s @ 80 steps/mm
  stepperX.setAcceleration(100*steps_per_mm); // 2000mm/s^2
  stepperX.setEnablePin(X_EN_PIN);
  stepperX.setPinsInverted(false, false, true);
  stepperX.disableOutputs();

  // driverY.begin();             // Initiate pins and registeries
  // driverY.rms_current(800);    // Set stepper current to 600mA. The command is the same as command TMC2130.setCurrent(600, 0.11, 0.5);
  // driverY.pwm_autoscale(1);
  // driverY.microsteps(8);

  stepperY.setMaxSpeed(100*steps_per_mm); // 100mm/s @ 80 steps/mm
  stepperY.setAcceleration(100*steps_per_mm); // 2000mm/s^2
  stepperY.setEnablePin(Y_EN_PIN);
  stepperY.setPinsInverted(false, false, true);
  stepperY.disableOutputs();

  // driverZ.begin();             // Initiate pins and registeries
  // driverZ.rms_current(800);    // Set stepper current to 600mA. The command is the same as command TMC2130.setCurrent(600, 0.11, 0.5);
  // driverZ.pwm_autoscale(1);
  // driverZ.microsteps(8);

  stepperZ.setMaxSpeed(100*steps_per_mm); // 100mm/s @ 80 steps/mm
  stepperZ.setAcceleration(100*steps_per_mm); // 2000mm/s^2
  stepperZ.setEnablePin(Z_EN_PIN);
  stepperZ.setPinsInverted(false, false, true);
  stepperZ.disableOutputs();

  // driverP.begin();             // Initiate pins and registeries
  // driverP.rms_current(800);    // Set stepper current to 600mA. The command is the same as command TMC2130.setCurrent(600, 0.11, 0.5);
  // driverP.pwm_autoscale(1);
  // driverP.microsteps(8);

  stepperP.setMaxSpeed(50*steps_per_mm); // 100mm/s @ 80 steps/mm
  stepperP.setAcceleration(50*steps_per_mm); // 2000mm/s^2
  stepperP.setEnablePin(P_EN_PIN);
  stepperP.setPinsInverted(false, false, true);
  stepperP.disableOutputs();

  pressureSensor.resetPressure();
  pressureSensor.beginCommunication(sdaPin,sclPin,frequency);

  for (int i = 0; i < numCycles; i++) {
        cycleTimes[i] = 0;
  }
  
  delay(500);
  blinkLED();
  blinkLED();
}

void loop() {
  currentMillis = millis();
  currentMicros = micros();


  checkLimitSwitches();

  homingProtocolXYZ();

  checkPressure();

  sendStatus();

  getNewCommand();

  checkMotors();

  checkDroplets();

  adjustPressure();

  checkGripper();

  refreshGripper();

  getCycleTime();
  
  numIterations++;
}