#include "Communication.h"
#include <Arduino.h>

// Constructor
Communication::Communication(TaskQueue& taskQueue, int baudRate)
    : taskQueue(taskQueue), baudRate(baudRate), 
    receiveCommandTask([this]() { this->receiveCommand(); }, 0), 
    sendStatusTask([this]() { this->sendStatus(); }, 0) {}

// Method to initialize the serial communication
void Communication::beginSerial() {
    Serial.begin(baudRate);
    receiveCommandTask.nextExecutionTime = millis() + receiveInterval;
    sendStatusTask.nextExecutionTime = millis() + sendInterval;
    taskQueue.addTask(receiveCommandTask);
    taskQueue.addTask(sendStatusTask);
}

// Method to send the status message
void Communication::sendStatus() {
    if (Serial.availableForWrite() >= 20) { // Check if serial buffer is not full
        Serial.print("Status message:"); 
        Serial.println(cycleCounter);
        cycleCounter = 0;
    }
    sendStatusTask.nextExecutionTime = millis() + sendInterval;
    taskQueue.addTask(sendStatusTask);
}

// Method to read and parse the serial data
void Communication::receiveCommand() {
    readSerial();
    if (newData) {
        receivedCounter++;
        newData = false;
    }
    receiveCommandTask.nextExecutionTime = millis() + receiveInterval;
    taskQueue.addTask(receiveCommandTask);
}

void Communication::IncrementCycleCounter() {
    cycleCounter++;
}
    
// Method to read the serial data
void Communication::readSerial(){
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

// Command convertCommand() {
//   strcpy(tempChars, receivedChars);
//   char * strtokIndx; // this is used by strtok() as an index
  
//   strtokIndx = strtok(tempChars,",");      // get the first part - the command ID
//   if (strtokIndx == NULL) {
//     // Handle missing commandNum
//     Command newCommand(0, UNKNOWN, 0, 0, 0);
//     return newCommand;
//   }
//   commandNum = atoi(strtokIndx); 

  
//   strtokIndx = strtok(NULL, ",");
//   if (strtokIndx == NULL) {
//     // Handle missing commandName
//     Command newCommand(0, UNKNOWN, 0, 0, 0);
//     return newCommand;
//   }
//   strcpy(commandName, strtokIndx); // copy it to messageFromPC
//   // commandName = String(commandText);

//   strtokIndx = strtok(NULL, ",");
//   if (strtokIndx == NULL) {
//     // Handle missing param1
//     Command newCommand(0, UNKNOWN, 0, 0, 0);
//     return newCommand;
//   }
//   param1 = atol(strtokIndx);

//   strtokIndx = strtok(NULL, ",");
//   if (strtokIndx == NULL) {
//     // Handle missing param2
//     Command newCommand(0, UNKNOWN, 0, 0, 0);
//     return newCommand;
//   }
//   param2 = atol(strtokIndx);

//   strtokIndx = strtok(NULL, ",");
//   if (strtokIndx == NULL) {
//     // Handle missing param3
//     Command newCommand(0, UNKNOWN, 0, 0, 0);
//     return newCommand;
//   }
//   param3 = atol(strtokIndx);
//   commandType = mapCommandType(commandName);
//   Command newCommand(commandNum, commandType, param1, param2, param3);
//   return newCommand;
// }

// void updateCommandQueue(Command& newCommand) {
//   lastAddedCmdNum = newCommand.commandNum;
//   commandQueue.push(newCommand);
// }

// /**
//  * Executes the given command.
//  *
//  * @param cmd The command to be executed.
//  */
// void executeCommand(const Command& cmd) {
//   // Perform actions based on the command type
//   currentCmdNum = cmd.commandNum;
//   switch (cmd.type) {
//     case RELATIVE_XYZ:
//       break;
//     default:
//       currentState = FREE;
//   }
// }

// /**
//  * Executes the next command in the command queue if the queue is not empty and the current state is FREE.
//  */
// void executeNextCommand(){
//   if (!commandQueue.empty() && currentState == FREE) {
//     // Dequeue the next command
//     Command nextCmd = commandQueue.front();
//     commandQueue.pop();

//     // Execute the command
//     executeCommand(nextCmd);
//   }
// }