/**
 * @file main.cpp
 * @brief This file contains the main code for the Octopus Connect project.
 *
 * The main.cpp file includes various libraries and defines classes and functions
 * used in the Octopus Connect project. It also contains the setup and loop functions
 * for the Arduino board. The code initializes the system clock, sets up limit switches,
 * defines a Gripper class, and handles serial communication and pressure control.
 */
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
#include <vector>
#include "pin_assignments.h"
#include "pin_functions.h"
#include "all_constants.h"
#include "PressureSensor.h"

/**
 * @class LED
 * @brief Represents an LED object used for flashing samples to image them.
 * 
 * The LED class provides functionality to control an LED connected to a specific pin. It allows
 * the user to flash the LED on and off for a specific duration at a specified interval to illuminate samples for imaging.
 */
class LED {
private:
    int triggerPin; // Pin number for the LED trigger
    int signalPin; // Pin number for the LED signal
    int startDelay; // Delay before the first flash in microseconds
    int numFlashes; // Number of flashes
    int duration; // Duration of the flash in microseconds
    int interval; // Interval between flashes in milliseconds
    unsigned long previousMillis; // Time of the previous flash
    bool active; // Flag to indicate if the LED is active
    int state; // Current state of the LED
    bool triggered; // Flag to indicate if the LED is triggered

public:
    // Constructor to initialize the LED object
    LED(int triggerPin, int signalPin, int startDelay, int duration, int interval, int numFlashes)
        : triggerPin(triggerPin), signalPin(signalPin), startDelay(startDelay),
          duration(duration), interval(interval), numFlashes(numFlashes), previousMillis(0), state(0), active(false), triggered(false) {
        pinMode(triggerPin, OUTPUT);
        digitalWrite(triggerPin, LOW);

        pinMode(signalPin, INPUT);
        // digitalWrite(signalPin, LOW);
    }

    void setNumFlashes(int flashes) { numFlashes = flashes; }
    void setDuration(int dur) { duration = dur; }
    void setInterval(int inter) { interval = inter; }
    void setStartDelay(int delay) { startDelay = delay; }

    void activate() { active = true; }
    void deactivate() { active = false; }

    bool isActive() const { return active; }

    // Method to check for signal
    bool isSignaled() {
        state = digitalRead(signalPin);
        if (state == LOW) {
            triggered = false;
            return false;
        } else if (state == HIGH && !triggered) {
            triggered = true;
            return true;
        } else if (state == HIGH && triggered) {
            return false;
        }
        return false; // Ensure all control paths return a value
    }

    // Method to flash the LED
    void flash() {
      delayMicroseconds(startDelay);

      for (int i = 0; i < numFlashes; i++) {
        digitalWrite(triggerPin, HIGH);
        delayMicroseconds(duration);
        digitalWrite(triggerPin, LOW);
        delay(interval);
      }
    }
};

/**
 * @class LimitSwitch
 * @brief Represents a limit switch for a specific axis.
 * 
 * The LimitSwitch class provides functionality to handle a limit switch
 * connected to a specific pin on a microcontroller. It keeps track of the
 * switch state, debounce time, and provides methods to access the switch
 * status and time of triggering.
 */
class LimitSwitch {
private:
    char axis;
    bool pressed;
    bool triggered;
    unsigned long switchTime;
    unsigned long lastSwitchTime;
    int pin;
    int debounce;
    int led;
    bool triggerCaught;

public:
    // Constructor
    LimitSwitch(char axis, int pin, int debounce, int led)
        : axis(axis), pressed(false), triggered(false),
          switchTime(0), lastSwitchTime(0), pin(pin), debounce(debounce), led(led) {}

    // Getter methods for accessing private member variables
    char getAxis() const { return axis; }
    bool isPressed() const { return pressed; }
    bool isTriggered() const { return triggered; }
    unsigned long getSwitchTime() const { return switchTime; }
    unsigned long getLastSwitchTime() const { return lastSwitchTime; }
    bool isTriggerCaught() const { return triggerCaught; }

    void catchTrigger() {triggerCaught = true;}

    // Method to handle interrupt service routine
    void isr() {
        pressed = digitalRead(pin);
        if (pressed) {
            switchTime = millis();
            if (switchTime - lastSwitchTime > debounce) {
                triggered = true;
                triggerCaught = false;
                lastSwitchTime = switchTime;
                // digitalWrite(led, HIGH);
            }
        } else {
            triggered = false;
            // digitalWrite(led, LOW);
        }
    }
};

// Printing variables
int currentDroplets = 0;
int targetDroplets = 0;
int newDroplets = 0;

// Define structure for a task
/**
 * @brief Represents a task to be executed periodically.
 */
struct Task {
    void (*function)(); // Function pointer for the task
    unsigned long interval; // Interval in milliseconds
    unsigned long lastExecutionTime; // Last execution time in milliseconds
};

Task* refreshGripperTaskPtr = nullptr; // Define the pointer
int refreshGripperTaskIndex = 3;


/**
 * @class Gripper
 * @brief Represents a gripper object used for controlling a gripper mechanism.
 */
class Gripper {
private:
    bool active;
    bool closed;
    bool pumpOn;
    // unsigned long lastExecution;
    unsigned long lastPumpActivation;
    unsigned long lastRefreshTime;
    int pumpInterval;
    int refreshInterval;

    int pumpValvePin1;
    int pumpValvePin2;
    int pumpPin;
    Task* refreshGripperTaskPtr;

public:
  // Constructor to initialize variables
  Gripper(int pumpValvePin1, int pumpValvePin2, int pumpPin, Task* refreshGripperTaskPtr)
    : active(false), closed(false), pumpOn(false),
      lastPumpActivation(0), lastRefreshTime(0), pumpInterval(750),refreshInterval(2000),
      pumpValvePin1(pumpValvePin1), pumpValvePin2(pumpValvePin2), pumpPin(pumpPin), refreshGripperTaskPtr(refreshGripperTaskPtr) {}

  bool isActive() const { return active; }
  bool isClosed() const { return closed; }
  bool isOpen() const { return !closed; }
  bool isPumpOn() const { return pumpOn; }
  unsigned long previousMillis() const { return lastPumpActivation; }


  void activatePump() {
    Serial.println("DEBUG Activating pump");
    digitalWrite(pumpPin, HIGH);
    pumpOn = true;
    lastPumpActivation = millis();
    if(refreshGripperTaskPtr != nullptr) { // Check if the pointer has been set
        refreshGripperTaskPtr->lastExecutionTime = lastPumpActivation + pumpInterval;
    }
  }

  void checkPump() {
    Serial.println("DEBUG Checking pump");
    if(pumpOn && millis() - lastPumpActivation >= pumpInterval) {
      digitalWrite(pumpPin, LOW);
      pumpOn = false;
    }
  }
  
  // Method to toggle the gripper state
  void closeGripper() {
    Serial.println("DEBUG Closing gripper");
    if (!active) {
      active = true;
    }
    digitalWrite(pumpValvePin1, LOW);
    digitalWrite(pumpValvePin2, LOW);
    closed = true;
    activatePump();
    lastRefreshTime = millis(); // Reset the refresh time
  }

  // Method to toggle the gripper state
  void openGripper() {
    Serial.println("DEBUG Opening gripper");
    if (!active) {
      active = true;
    }
    digitalWrite(pumpValvePin1, HIGH);
    digitalWrite(pumpValvePin2, HIGH);
    closed = false;
    activatePump();
    lastRefreshTime = millis(); // Reset the refresh time
  }

  // Method to turn off the gripper
  void gripperOff() {
    digitalWrite(pumpValvePin1, LOW);
    digitalWrite(pumpValvePin2, LOW);
    digitalWrite(pumpPin, LOW);
    active = false;
    closed = false;
  }

  void refreshGripper() {
    if (active) {
      if (millis() - lastRefreshTime >= refreshInterval) {
        activatePump();
        lastRefreshTime = millis(); // Reset the refresh time
      }
    }
  }
};

Gripper gripper = Gripper(pumpValvePin1,pumpValvePin2,pumpPin,refreshGripperTaskPtr);

// Function wrapper to periodically check if the pump is still on
void checkGripper(){
  gripper.checkPump();
}
// Pressure control variables
bool manualControl = false;
bool printSyringeOpen = false;
bool resetP = false;

int changeCurrent = 0;

bool motorsActive = false;

// BIDIRECTIONAL SERIAL COMMUNICATION VARIABLES

const byte numChars = 64;
char receivedChars[numChars];
char tempChars[numChars];        // temporary array for use when parsing

// variables to hold the parsed data
char commandName[numChars] = {0};
int commandNum = 0;
int lastCompletedCmdNum = 0;
// String commandName = "";
long param1 = 0;
long param2 = 0;
long param3 = 0;

bool correctPos = true;

String state = "Free";
int updateCounter = 0;
bool newData = false;

bool receivingNewData = true;
unsigned long waitStartTime = 0;
unsigned long waitTime = 0;

unsigned long currentMillis;
unsigned long currentMicros;

unsigned long endMicros;
unsigned long cycleTime = 0;
static const int numCycles = 5;
// unsigned long cycleTimes[numCycles];
int cycleIndex = 0;
unsigned long averageCycle = 0;
bool pressureRead = false;
unsigned long maxCycle = 0;

int numIterations = 0;

int frequency = 1000000;

bool pressureCorrect = false;
bool regulatePressure = false;

// TMC2208Stepper driverX = TMC2208Stepper(X_SW_RX, X_SW_TX, R_SENSE); // Software serial
// TMC2208Stepper driverY = TMC2208Stepper(Y_SW_RX, Y_SW_TX, R_SENSE); // Software serial
// TMC2208Stepper driverZ = TMC2208Stepper(Z_SW_RX, Z_SW_TX, R_SENSE); // Software serial
// TMC2208Stepper driverP = TMC2208Stepper(P_SW_RX, P_SW_TX, R_SENSE); // Software serial

AccelStepper stepperX = AccelStepper(stepperX.DRIVER, X_STEP_PIN, X_DIR_PIN);
AccelStepper stepperY = AccelStepper(stepperY.DRIVER, Y_STEP_PIN, Y_DIR_PIN);
AccelStepper stepperZ = AccelStepper(stepperZ.DRIVER, Z_STEP_PIN, Z_DIR_PIN);
AccelStepper stepperP = AccelStepper(stepperP.DRIVER, P_STEP_PIN, P_DIR_PIN);

AccelStepper* steppers[] = {&stepperZ,&stepperX,&stepperY,&stepperP};

PressureSensor pressureSensor = PressureSensor(TCAAddress, sensorAddress);

LimitSwitch limitX = LimitSwitch('X',xstop,debounceAll,ledPin);
LimitSwitch limitY = LimitSwitch('Y',ystop,debounceAll,ledPin);
LimitSwitch limitZ = LimitSwitch('Z',zstop,debounceAll,ledPin);
LimitSwitch limitP = LimitSwitch('P',pstop,debounceAll,ledPin);

// Define an array to hold all limit switch objects
LimitSwitch* limits[] = {&limitZ, &limitX, &limitY, &limitP};

// Static variable to keep track of the current switch index
static int currentSwitchIndex = 0;

LED led = LED(flashPin,cameraPin,startDelay,flashDuration,flashInterval,numFlashes);

bool ledActive = false;
bool ledTriggered = false;
/**
 * @enum HomingState
 * @brief Represents the different states of the homing process.
 * 
 * The HomingState enum defines the possible states of the homing process
 * for the motor axes. It is used to track the current state of the homing
 * process and determine the next action to be taken.
 */
enum HomingState {
    IDLE,
    INITIATE,
    HOMING,
    RETRACTION,
    RESET_POS
};

HomingState homingState = IDLE;


/**
 * Checks the limit switches and performs necessary actions based on their state.
 * This function is responsible for stopping the stepper motor, catching the trigger,
 * and controlling the LED pin based on the state of the limit switches.
 */
void checkLimitSwitches() {
    // // Get the current limit switch object
    LimitSwitch* currentSwitch = limits[currentSwitchIndex];
    AccelStepper* currentStepper = steppers[currentSwitchIndex];
    // // Call the isr() function for the current switch
    currentSwitch->isr();

    if (homingState == IDLE) {
      if (currentSwitch->isTriggered() && !currentSwitch->isTriggerCaught()){
        currentStepper->stop();
        currentSwitch->catchTrigger();
        digitalWrite(ledPin, HIGH);
      } else if (currentSwitch->isTriggered() && currentSwitch->isTriggerCaught()) {
        digitalWrite(ledPin, HIGH);
      } else {
        digitalWrite(ledPin, LOW);
      }
    }

    // Increment the switch index for the next call
    currentSwitchIndex++;
    if (currentSwitchIndex >= 4) {
        currentSwitchIndex = 0;
    }
}
// Reads the pressure sensor if it is the right time
void checkPressure(){
  currentPressure = pressureSensor.smoothPressure();
  pressureRead = true;
}

// Define a structure to hold information for each stage of homing
struct HomingStage {
    int direction;
    int homingSpeed;           // Speed for homing
    int retractionSpeed;       // Speed for retraction
    int normalSpeed;           // Speed for normal operation
    int normalAccel;           // Acceleration for normal operation
};

// Array of homing stages for each motor
HomingStage homingStages[] = {
    {1,2500, -200,maxSpeedXYZ,accelerationXYZ},   // Z homing
    {1,1500, -25,maxSpeedXYZ,accelerationXYZ},   // X homing
    {-1,1500, -25,maxSpeedXYZ,accelerationXYZ},  // Y homing
    {1,3000, -200,maxSpeedP,accelerationP},   // P homing
};

int homingAxisNumber = 4;

/**
 * Moves the home axis through the homing stages.
 * 
 * The function moves the home axis through a series of homing stages, including initiation, homing, retraction, and reset position.
 * It uses limit switches to determine the position of the axis and stepper motors to control the movement.
 * 
 * @param None
 * @return None
 */
void homeAxis() {
  if (homingAxisNumber >= 4){
    return;
  }
  LimitSwitch* currentSwitch = limits[homingAxisNumber];
  AccelStepper* currentStepper = steppers[homingAxisNumber];
  HomingStage currentStage = homingStages[homingAxisNumber];

  switch(homingState) {
    case IDLE:
      break;
    case INITIATE:
      if (homingAxisNumber == 3) {
        digitalWrite(printValvePin, HIGH);
        printSyringeOpen = true;
      }
      homingState = HOMING;
      currentStepper->setAcceleration(10000);
      break;
    case HOMING:
      if (!currentSwitch->isTriggered()) {
        currentStepper->setMaxSpeed(currentStage.direction * currentStage.homingSpeed);
        currentStepper->move(currentStage.direction * 100);
        currentStepper->run();
      } else {
        currentStepper->stop();
        homingState = RETRACTION;
      }
      break;
    case RETRACTION:
      if (currentSwitch->isTriggered()) {
        currentStepper->setMaxSpeed(currentStage.direction * currentStage.retractionSpeed);
        currentStepper->move(currentStage.direction * -10);
        currentStepper->run();
      } else {
        currentStepper->stop();
        currentStepper->setCurrentPosition(0);
        currentStepper->setMaxSpeed(currentStage.direction * currentStage.homingSpeed);
        currentStepper->moveTo(currentStage.direction * -500);
        homingState = RESET_POS;
      }
      break;
    case RESET_POS:
      if (currentStepper->distanceToGo() != 0) {
        currentStepper->run();
      } else {
        currentStepper->stop();
        currentStepper->setMaxSpeed(currentStage.direction * currentStage.normalSpeed);
        currentStepper->setAcceleration(currentStage.normalAccel);
        if (homingAxisNumber == 3){
          homingState = IDLE;
          digitalWrite(printValvePin, LOW);
          printSyringeOpen = false;
        } else {
          homingState = INITIATE;
        }
        homingAxisNumber++;
      }
      break;
    default:
      break;
  }
}

// Steps motor if it is the right time, moves Y -> X -> Z
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
  } else {
    homeAxis();
  }
}

void printDroplet(){
  digitalWrite(printPin, HIGH);
  delayMicroseconds(3000);
  digitalWrite(printPin, LOW);
}

// Prints droplets if in the correct position and at correct pressure
void checkDroplets(){
  if (correctPos == true && currentDroplets < targetDroplets){
    if (currentPressure > targetPressureP - toleranceDroplet && currentPressure < targetPressureP + toleranceDroplet && resetP == false){
      state = "Printing";
      if (currentMillis - previousMillisDroplet > intervalDroplet) {
        printDroplet();
        currentDroplets++;
        previousMillisDroplet = currentMillis;
      }
    }
  }
}

/**
 * Resets the syringe by moving the stepper motor to a specific position.
 * If the reset process is already initiated, it continues until the stepper motor reaches its destination.
 * Once the reset is complete, the syringe is closed and the reset flag is set to false.
 */
void resetSyringe() {
  if (!resetP) {    // Initiate the reset process
    stepperP.stop();
    resetP = true;
    digitalWrite(printValvePin, HIGH);
    printSyringeOpen = true;
    delay(50);
    stepperP.moveTo(-200);
    stepperP.run();
  } 
  else if (stepperP.distanceToGo() != 0) { //Continue resetting
    stepperP.run();
  } 
  else {                            //Flag reset complete
    digitalWrite(printValvePin, LOW);
    printSyringeOpen = false;
    delay(50);
    resetP = false;
  }
}

/**
 * Adjusts the pressure based on the target pressure and current pressure.
 * This function regulates the pressure by controlling the speed of a stepper motor.
 * It calculates the difference between the current pressure and the target pressure,
 * and adjusts the speed of the stepper motor accordingly.
 * 
 * Preconditions:
 * - The motors must be active.
 * - The pressure regulation must be enabled.
 * 
 * Postconditions:
 * - The stepper motor speed is adjusted based on the pressure difference.
 * - The stepper motor moves towards the target position.
 * - The stepper motor runs at the set speed.
 */
void adjustPressure() {
  if (!motorsActive || !regulatePressure) {   // Only regulate pressure when motors are active and instructed to
    return;
  }

  if (resetP || stepperP.currentPosition() < lowerBound || stepperP.currentPosition() > upperBound) {
    resetSyringe();
    return;
  }
  // Calculate the difference between current pressure and target pressure
  int pressureDifference = currentPressure - targetPressureP;

  // Determine the speed based on the difference
  if (pressureDifference > cutoffSyringe) {
      syringeSpeed = syringeMaxSpeed;  // Move quickly when far above target pressure
  } else if (pressureDifference < -cutoffSyringe) {
      syringeSpeed = -syringeMaxSpeed; // Move quickly when far below target pressure
  } else if (abs(pressureDifference) <= toleranceSyringe) {
      syringeSpeed = 0;          // Stop moving when within tolerance range
  } else {
      // Map the absolute value of pressure difference to a speed between the min and max speed
        syringeSpeed = map(abs(pressureDifference), toleranceSyringe, cutoffSyringe, syringeMinSpeed, syringeMaxSpeed);
        // Apply the sign of the pressure difference to the speed
        syringeSpeed *= (pressureDifference < 0) ? -1 : 1;
  }

  // Set the speed of the stepper motor
  stepperP.setSpeed(syringeSpeed);

  // Move the stepper motor towards the target position
  stepperP.move(syringeSpeed);

  // Run the stepper motor at the set speed
  stepperP.runSpeed();
}

// Refresh the vacuum in the gripper on a constant interval
void refreshGripper(){
  if (gripper.isActive() == true) {
    gripper.activatePump();
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

/**
 * @brief Reads data from the serial port and stores it in a character array.
 * 
 * This function reads data from the serial port and stores it in the `receivedChars` character array.
 * It uses the `<` character as the start marker and the `>` character as the end marker to identify the beginning and end of a message.
 * The received data is stored in the `receivedChars` array until the end marker is received, at which point the function sets the `newData` flag to true.
 * 
 * @note This function assumes that the `receivedChars` array has been declared and initialized before calling this function.
 * 
 * @note This function assumes that the `numChars` variable has been defined and represents the maximum number of characters that can be stored in the `receivedChars` array.
 * 
 * @note This function assumes that the `receivingNewData` and `newData` variables have been declared and initialized before calling this function.
 * 
 * @note This function assumes that the `Serial` object has been initialized and is available for reading.
 */
void readSerial(){
  static bool recvInProgress = false;
  static byte ndx = 0;
  char startMarker = '<';
  char endMarker = '>';
  char rc;

  while (Serial.available() > 0) {
    receivingNewData = false;
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

enum CommandType {
    RELATIVE_XYZ,
    ABSOLUTE_XYZ,
    RELATIVE_PRESSURE,
    ABSOLUTE_PRESSURE,
    PRINT,
    RESET_P,
    OPEN_GRIPPER,
    CLOSE_GRIPPER,
    GRIPPER_OFF,
    ENABLE_MOTORS,
    DISABLE_MOTORS,
    HOME_ALL,
    REGULATE_PRESSURE,
    DEREGULATE_PRESSURE,
    PAUSE,
    RESUME,
    WAIT,
    CLEAR_QUEUE,
    UNKNOWN,
    CHANGE_ACCEL,
    RESET_ACCEL,
    GATE_ON,
    GATE_OFF,
    FLASH_ON,
    ACTIVATE_LED,
    DEACTIVATE_LED,
    SET_FLASH,
    SET_DELAY,
    CAMERA_ON,
    // Add more command types as needed
};

/**
 * @brief Represents a command with associated parameters.
 */
struct Command {
  int commandNum; /**< The command number. */
  CommandType type; /**< The type of command. */
  long param1; /**< The first parameter. */
  long param2; /**< The second parameter. */
  long param3; /**< The third parameter. */
  
  /**
   * @brief Constructs a Command object with the specified parameters.
   * @param num The command number.
   * @param t The type of command.
   * @param p1 The first parameter.
   * @param p2 The second parameter.
   * @param p3 The third parameter.
   */
  Command(int num, CommandType t, long p1, long p2, long p3) : 
    commandNum(num), type(t), param1(p1), param2(p2), param3(p3) {}
};

CommandType commandType;

enum State {
    FREE,
    MOVING_XYZ,
    CHANGING_PRESSURE,
    PRINTING,
    HOMING_AXIS,
    PUMPING,
    WAITING,
    PAUSED
    // Add more states as needed
};

// Command queue
std::queue<Command> commandQueue;

// Current state
State currentState = FREE;

// Function to map command names to command types
CommandType mapCommandType(const char* commandName) {
    if (strcmp(commandName, "RELATIVE_XYZ") == 0) {
        return RELATIVE_XYZ;
    } else if (strcmp(commandName, "ABSOLUTE_XYZ") == 0) {
        return ABSOLUTE_XYZ;
    } else if (strcmp(commandName, "RELATIVE_PRESSURE") == 0) {
        return RELATIVE_PRESSURE;
    } else if (strcmp(commandName, "ABSOLUTE_PRESSURE") == 0) {
        return ABSOLUTE_PRESSURE;
    } else if (strcmp(commandName, "PRINT") == 0) {
        return PRINT;
    } else if (strcmp(commandName, "RESET_P") == 0) {
        return RESET_P;
    } else if (strcmp(commandName, "OPEN_GRIPPER") == 0) {
        return OPEN_GRIPPER;
    } else if (strcmp(commandName, "CLOSE_GRIPPER") == 0) {
        return CLOSE_GRIPPER;
    } else if (strcmp(commandName, "GRIPPER_OFF") == 0) {
        return GRIPPER_OFF;
    } else if (strcmp(commandName, "ENABLE_MOTORS") == 0) {
        return ENABLE_MOTORS;
    } else if (strcmp(commandName, "DISABLE_MOTORS") == 0) {
        return DISABLE_MOTORS;
    } else if (strcmp(commandName, "HOME_ALL") == 0) {
        return HOME_ALL;
    } else if (strcmp(commandName, "REGULATE_PRESSURE") == 0) {
        return REGULATE_PRESSURE;
    } else if (strcmp(commandName, "DEREGULATE_PRESSURE") == 0) {
        return DEREGULATE_PRESSURE;
    } else if (strcmp(commandName, "PAUSE") == 0) {
        return PAUSE;
    } else if (strcmp(commandName, "RESUME") == 0) {
        return RESUME;
    } else if (strcmp(commandName, "CLEAR_QUEUE") == 0) {
        return CLEAR_QUEUE;
    } else if (strcmp(commandName, "WAIT") == 0) {
        return WAIT;
    } else if (strcmp(commandName, "CHANGE_ACCEL") == 0) {
        return CHANGE_ACCEL;
    } else if (strcmp(commandName, "RESET_ACCEL") == 0) {
        return RESET_ACCEL;
    } else if (strcmp(commandName, "GATE_ON") == 0) {
        return GATE_ON;
    } else if (strcmp(commandName, "GATE_OFF") == 0) {
        return GATE_OFF;
    } else if (strcmp(commandName, "FLASH_ON") == 0) {
        return FLASH_ON;
    } else if (strcmp(commandName, "SET_FLASH") == 0) {
        return SET_FLASH;
    } else if (strcmp(commandName, "SET_DELAY") == 0) {
        return SET_DELAY;
    } else if (strcmp(commandName, "CAMERA_ON") == 0) {
        return CAMERA_ON;
    } else if (strcmp(commandName, "ACTIVATE_LED") == 0) {
        return ACTIVATE_LED;
    } else if (strcmp(commandName, "DEACTIVATE_LED") == 0) {
        return DEACTIVATE_LED;
    } else {
        return UNKNOWN;
    }
}

Command convertCommand() {
  strcpy(tempChars, receivedChars);
  char * strtokIndx; // this is used by strtok() as an index
  
  strtokIndx = strtok(tempChars,",");      // get the first part - the command ID
  if (strtokIndx == NULL) {
    // Handle missing commandNum
    Command newCommand(0, UNKNOWN, 0, 0, 0);
    return newCommand;
  }
  commandNum = atoi(strtokIndx); 

  
  strtokIndx = strtok(NULL, ",");
  if (strtokIndx == NULL) {
    // Handle missing commandName
    Command newCommand(0, UNKNOWN, 0, 0, 0);
    return newCommand;
  }
  strcpy(commandName, strtokIndx); // copy it to messageFromPC
  // commandName = String(commandText);

  strtokIndx = strtok(NULL, ",");
  if (strtokIndx == NULL) {
    // Handle missing param1
    Command newCommand(0, UNKNOWN, 0, 0, 0);
    return newCommand;
  }
  param1 = atol(strtokIndx);

  strtokIndx = strtok(NULL, ",");
  if (strtokIndx == NULL) {
    // Handle missing param2
    Command newCommand(0, UNKNOWN, 0, 0, 0);
    return newCommand;
  }
  param2 = atol(strtokIndx);

  strtokIndx = strtok(NULL, ",");
  if (strtokIndx == NULL) {
    // Handle missing param3
    Command newCommand(0, UNKNOWN, 0, 0, 0);
    return newCommand;
  }
  param3 = atol(strtokIndx);
  commandType = mapCommandType(commandName);
  Command newCommand(commandNum, commandType, param1, param2, param3);
  return newCommand;
}

void updateCommandQueue(Command& newCommand) {
  lastAddedCmdNum = newCommand.commandNum;
  commandQueue.push(newCommand);
}

/**
 * Executes the given command.
 *
 * @param cmd The command to be executed.
 */
void executeCommand(const Command& cmd) {
  // Perform actions based on the command type
  currentCmdNum = cmd.commandNum;
  switch (cmd.type) {
    case RELATIVE_XYZ:
      stepperX.moveTo(stepperX.currentPosition()+cmd.param1);
      stepperY.moveTo(stepperY.currentPosition()+cmd.param2);
      stepperZ.moveTo(stepperZ.currentPosition()+cmd.param3);
      correctPos = false;
      currentState = MOVING_XYZ;
      break;
    case ABSOLUTE_XYZ:
      stepperX.moveTo(cmd.param1);
      stepperY.moveTo(cmd.param2);
      stepperZ.moveTo(cmd.param3);
      correctPos = false;
      currentState = MOVING_XYZ;
      break;
    case RELATIVE_PRESSURE:
      targetPressureP = targetPressureP + cmd.param1;
      break;
    case ABSOLUTE_PRESSURE:
      targetPressureP = cmd.param1;
      break;
    case PRINT:
      targetDroplets = targetDroplets + cmd.param1;
      currentState = PRINTING;
      break;
    case RESET_P:
      resetSyringe();
      break;
    case OPEN_GRIPPER:
      gripper.openGripper();
      break;
    case CLOSE_GRIPPER:
      gripper.closeGripper();
      break;
    case GRIPPER_OFF:
      gripper.gripperOff();
      break;
    case ENABLE_MOTORS:
      stepperX.enableOutputs();
      stepperY.enableOutputs();
      stepperZ.enableOutputs();
      stepperP.enableOutputs();
      motorsActive = true;
      break;
    case DISABLE_MOTORS:
      stepperX.disableOutputs();
      stepperY.disableOutputs();
      stepperZ.disableOutputs();
      stepperP.disableOutputs();
      motorsActive = false;
      break;
    case CHANGE_ACCEL:
      stepperX.setAcceleration(cmd.param1);
      stepperY.setAcceleration(cmd.param1);
      stepperZ.setAcceleration(cmd.param1);
      break;
    case RESET_ACCEL:
      stepperX.setAcceleration(accelerationXYZ);
      stepperY.setAcceleration(accelerationXYZ);
      stepperZ.setAcceleration(accelerationXYZ);
      break;
    case HOME_ALL:
      homingState = INITIATE;
      homingAxisNumber = 0;
      currentState = HOMING_AXIS;
      break;
    case REGULATE_PRESSURE:
      regulatePressure = true;
      break;
    case DEREGULATE_PRESSURE:
      regulatePressure = false;
      break;
    case GATE_ON:
      digitalWrite(gatePin, HIGH);
      break;
    case GATE_OFF:
      digitalWrite(gatePin, LOW);
      break;
    case FLASH_ON:
      // for (int i = 0; i < cmd.param1; i++){
      //   digitalWrite(flashPin, HIGH);
      //   delayMicroseconds(cmd.param2);
      //   digitalWrite(flashPin, LOW);
      //   delay(cmd.param3);
      // }
      led.flash();
      break;
    case ACTIVATE_LED:
      led.activate();
      break;
    case DEACTIVATE_LED:
      led.deactivate();
      break;
    case SET_FLASH:
      led.setNumFlashes(cmd.param1);
      led.setDuration(cmd.param2);
      led.setInterval(cmd.param3);
      break;
    case SET_DELAY:
      led.setStartDelay(cmd.param1);
      break;
    case CAMERA_ON:
      digitalWrite(cameraPin, HIGH);
      delay(cmd.param1);
      digitalWrite(flashPin, HIGH);
      delayMicroseconds(cmd.param2);
      digitalWrite(flashPin, LOW);
      // delay(cmd.param3);
      // delay(cmd.param1);
      digitalWrite(cameraPin, LOW);
      break;
    case PAUSE:
      break;
    case CLEAR_QUEUE:
      while (!commandQueue.empty()) {
        commandQueue.pop();
      }
      stepperX.stop();
      stepperY.stop();
      stepperZ.stop();
      stepperP.stop();
      targetDroplets = 0;
      currentDroplets = 0;
      targetPressureP = currentPressure;
      currentCmdNum = 0;
      lastCompletedCmdNum = 0;
      lastAddedCmdNum = 0;
      currentState = FREE;
      break;
    case UNKNOWN:
      break;
    case WAIT:
      currentState = WAITING;
      waitStartTime = millis();
      waitTime = cmd.param1;
      break;
    default:
      currentState = FREE;
  }
}

/**
 * Executes the next command in the command queue if the queue is not empty and the current state is FREE.
 */
void executeNextCommand(){
  if (!commandQueue.empty() && currentState == FREE) {
    // Dequeue the next command
    Command nextCmd = commandQueue.front();
    commandQueue.pop();

    // Execute the command
    executeCommand(nextCmd);
  }
}

// Sends the current status of the machine to the computer via Serial
void sendStatus() {
  if (currentState == PAUSED) {
    currentState = PAUSED;
  } else if (stepperY.distanceToGo() != 0) {
    currentState = MOVING_XYZ;
    state = "MovingY";
  } else if (stepperX.distanceToGo() != 0){
    currentState = MOVING_XYZ;
    state = "MovingX";
  } else if (stepperZ.distanceToGo() != 0){
    currentState = MOVING_XYZ;
    state = "MovingZ";
  } else if (currentDroplets != targetDroplets){
    currentState = PRINTING;
    state = "Printing";
  } else if (gripper.isPumpOn() == true){
    currentState = PUMPING;
    state = "Pump_on";
  } else {
    currentState = FREE;
    lastCompletedCmdNum = currentCmdNum;
    state = "Free";
  }
  ledActive = led.isActive();
  ledTriggered = led.isSignaled();
  Serial.print("State:"); Serial.print(state);
  Serial.print(",Com_open:"); Serial.print(receivingNewData);
  Serial.print(",Last_completed:"); Serial.print(lastCompletedCmdNum);
  Serial.print(",Last_added:"); Serial.print(lastAddedCmdNum);
  Serial.print(",Current_command:"); Serial.print(currentCmdNum);
  Serial.print(",Max_cycle:"); Serial.print(maxCycle);
  Serial.print(",Cycle_count:"); Serial.print(numIterations);
  Serial.print(",X:"); Serial.print(stepperX.currentPosition());
  Serial.print(",Y:"); Serial.print(stepperY.currentPosition());
  Serial.print(",Z:"); Serial.print(stepperZ.currentPosition());
  Serial.print(",P:"); Serial.print(stepperP.currentPosition());
  Serial.print(",Droplets:"); Serial.print(currentDroplets);
  Serial.print(",Gripper:"); Serial.print(gripper.isOpen());
  Serial.print(",LED_Active:"); Serial.print(ledActive);
  Serial.print(",LED_Triggered:"); Serial.print(ledTriggered);
  Serial.print(",Pressure:"); Serial.println(currentPressure);
  numIterations = 0;
  maxCycle = 0;
}

// Checks for and parses new commands
void getNewCommand(){
  // Read data coming from the Serial communication with the PC
  readSerial();

  // If new data is found parse the signal and execute the command
  if (newData == true){
    Command newCommand = convertCommand();
    if (newCommand.type == PAUSE){
      currentState = PAUSED;
    } else if (newCommand.type == RESUME){
      currentState = FREE;
    } else if (newCommand.type == CLEAR_QUEUE){
      while (!commandQueue.empty()) {
        commandQueue.pop();
      }
      stepperX.stop();
      stepperY.stop();
      stepperZ.stop();
      stepperP.stop();
      targetDroplets = 0;
      currentDroplets = 0;
      targetPressureP = currentPressure;
      currentCmdNum = 0;
      lastCompletedCmdNum = 0;
      lastAddedCmdNum = 0;

      currentState = FREE;
    }else {
      updateCommandQueue(newCommand);
    }
    newData = false;
    receivingNewData = true;
  }
}

unsigned long average (unsigned long * array, int len)  // assuming array is int.
{
  long sum = 0L ;  // sum will be larger than an item, long for safety.
  for (int i = 0 ; i < len ; i++)
    sum += array [i] ;
  return  ((unsigned long) sum) / len ;  // average will be fractional, so float may be appropriate.
}

void checkCamera(){
  if (led.isActive()){
    if (led.isSignaled()){
      led.flash();
    }
  } 
}

// Initialize tasks: 
// Order of tasks in the vector is used elsewhere:
// Task 1: Check limit switches every 2 milliseconds
// Task 2: Check pressure every 10 milliseconds
// Task 3: Check gripper every 500 milliseconds
// Task 4: Refresh gripper every 60000 milliseconds
// Task 5: Send status every 50 milliseconds
// Task 6: Get new command every 10 milliseconds
// Task 7: Execute next command every 10 milliseconds
std::vector<Task> tasks = {
    {checkLimitSwitches, 2, 0}, // Task 1
    {checkPressure, 10, 3},
    {checkGripper, 100, 23},
    {refreshGripper, 60000, 0},
    {sendStatus, 50, 3},
    {getNewCommand, 10, 0},
    {executeNextCommand, 10, 5},
    {checkCamera, 2, 1},
    // Add more tasks as needed
};

void setup() {
  SystemClock_Config();
  setupPins();

	Serial.begin(115200);
  while(!Serial);

  // driverX.begin();             // Initiate pins and registeries
  // driverX.rms_current(800);    // Set stepper current to 600mA. The command is the same as command TMC2130.setCurrent(600, 0.11, 0.5);
  // driverX.pwm_autoscale(1);
  // driverX.microsteps(8);

  stepperX.setMaxSpeed(maxSpeedXYZ); // 100mm/s @ 80 steps/mm
  stepperX.setAcceleration(accelerationXYZ); // 2000mm/s^2
  stepperX.setEnablePin(X_EN_PIN);
  stepperX.setPinsInverted(false, false, true);
  stepperX.disableOutputs();

  // driverY.begin();             // Initiate pins and registeries
  // driverY.rms_current(800);    // Set stepper current to 600mA. The command is the same as command TMC2130.setCurrent(600, 0.11, 0.5);
  // driverY.pwm_autoscale(1);
  // driverY.microsteps(8);

  stepperY.setMaxSpeed(maxSpeedXYZ); // 100mm/s @ 80 steps/mm
  stepperY.setAcceleration(accelerationXYZ); // 2000mm/s^2
  stepperY.setEnablePin(Y_EN_PIN);
  stepperY.setPinsInverted(false, false, true);
  stepperY.disableOutputs();

  // driverZ.begin();             // Initiate pins and registeries
  // driverZ.rms_current(800);    // Set stepper current to 600mA. The command is the same as command TMC2130.setCurrent(600, 0.11, 0.5);
  // driverZ.pwm_autoscale(1);
  // driverZ.microsteps(8);

  stepperZ.setMaxSpeed(maxSpeedXYZ); // 100mm/s @ 80 steps/mm
  stepperZ.setAcceleration(accelerationXYZ); // 2000mm/s^2
  stepperZ.setEnablePin(Z_EN_PIN);
  stepperZ.setPinsInverted(false, false, true);
  stepperZ.disableOutputs();

  // driverP.begin();             // Initiate pins and registeries
  // driverP.rms_current(800);    // Set stepper current to 600mA. The command is the same as command TMC2130.setCurrent(600, 0.11, 0.5);
  // driverP.pwm_autoscale(1);
  // driverP.microsteps(8);

  stepperP.setMaxSpeed(maxSpeedP); // 100mm/s @ 80 steps/mm
  stepperP.setAcceleration(accelerationP); // 2000mm/s^2
  stepperP.setEnablePin(P_EN_PIN);
  stepperP.setPinsInverted(false, false, true);
  stepperP.disableOutputs();

  pressureSensor.resetPressure();
  pressureSensor.beginCommunication(sdaPin,sclPin,frequency);

  // for (int i = 0; i < numCycles; i++) {
  //       cycleTimes[i] = 0;
  // }
  
  delay(500);
  blinkLED();
  blinkLED();
}

void loop() {
  currentMillis = millis();
  currentMicros = micros();

  // Iterate over tasks
  for (auto& task : tasks) {
      // Check if enough time has elapsed for the task
      if (currentMillis - task.lastExecutionTime >= task.interval) {
          // Execute the task function
          task.function();
          // Update the last execution time
          task.lastExecutionTime = currentMillis;
      }
  }
  if (currentState != PAUSED && currentState != WAITING){
    adjustPressure();
    checkMotors();
    checkDroplets();
  } else if (currentState == WAITING){
    if (currentMillis - waitStartTime > waitTime){
      currentState = FREE;
    }
  }
  getCycleTime();

  numIterations++;
}