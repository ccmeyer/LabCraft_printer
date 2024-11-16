#include "PressureSensor.h"
#include <Wire.h>

// Constructor
PressureSensor::PressureSensor(int TCAAddress, int sensorAddress, TaskQueue& taskQueue)
    : TCAAddress(TCAAddress), sensorAddress(sensorAddress), taskQueue(taskQueue), 
    readPressureTask([this]() { this->smoothPressure(); }, 0), switchPortTask([this]() { this-> tcaselect(); }, 0) {}

// Method to begin I2C communication with the pressure sensor
void PressureSensor::beginCommunication(int sdaPin, int sclPin, int frequency) {
    Wire.setSDA(sdaPin);
    Wire.setSCL(sclPin);
    Wire.begin();        // Join I2C bus
    Wire.setClock(frequency);
    tcaselect();        // Select the first i2c port
    // Serial.println("Pressure sensor initialized");
}

// Method to reset the pressure readings for both ports
void PressureSensor::resetPressure() {
    for (int i = 0; i < 2; i++) {
        for (int thisReading = 0; thisReading < numReadings; thisReading++) {
            readings[i][thisReading] = 0;
        }
        total[i] = 0;
        average[i] = 0;
        readIndex[i] = 0;
        currentPressure[i] = 0;
    }
}

// Method to get the current printing pressure value (port 0)
float PressureSensor::getPrintPressure() const {
    return currentPressure[0];
}

// Method to get the current refuel pressure value (port 1)
float PressureSensor::getRefuelPressure() const {
    return currentPressure[1];
}

// Method to set the desired i2c port on the multiplexer
void PressureSensor::tcaselect() {
  // Sets the multiplexer to i2c port i
//   if (port == currentPort && TCAset == true) return;
 
  Wire.beginTransmission(TCAAddress);
  Wire.write(1 << currentPort);
  Wire.endTransmission();

  if (currentPort == 0) {
    currentPort = 1;
  } else {
    currentPort = 0;
  }
}

// Private method to read raw pressure from the sensor
void PressureSensor::readPressure() {
    byte p1, p2, t1, t2;

    Wire.requestFrom(sensorAddress, 4);    // Request 4 bytes from peripheral device
    while (Wire.available()) { // Peripheral may send less than requested
        p1 = Wire.read();
        p2 = Wire.read();
        t1 = Wire.read();
        t2 = Wire.read();
    }

    uint8_t pressureState = (p1 & 0b11000000) >> 6;
    uint16_t pressureRaw = ((p1 & 0b00111111) << 8) | p2;

    rawPressure[currentPort] = pressureRaw;
}

// Method to set the read interval
void PressureSensor::setReadInterval(unsigned long interval) {
    readInterval = interval;
} 

// Private method to smooth the pressure readings
void PressureSensor::smoothPressure() {
    if (!reading) {
        return;
    }
    readPressure();
    int port = currentPort;
    total[port] = total[port] - readings[port][readIndex[port]];
    readings[port][readIndex[port]] = rawPressure[port];
    total[port] = total[port] + readings[port][readIndex[port]];
    readIndex[port] = readIndex[port] + 1;

    if (readIndex[port] >= numReadings) {
        readIndex[port] = 0;
    }

    average[port] = total[port] / numReadings;
    currentPressure[port] = average[port];

    // Schedule the port switch task
    switchPortTask.nextExecutionTime = micros() + switchInterval;
    taskQueue.addTask(switchPortTask);

    // Reschedule the task to run again
    readPressureTask.nextExecutionTime = micros() + readInterval;  // Adjust interval as needed
    taskQueue.addTask(readPressureTask);
}

// Method to start periodic pressure reading
void PressureSensor::startReading() {
    reading = true;
    setReadInterval(5000);
    readPressureTask.nextExecutionTime = micros() + readInterval;
    taskQueue.addTask(readPressureTask);
}

// Method to stop periodic pressure reading
void PressureSensor::stopReading() {
    reading = false;
    // This can be implemented by simply not rescheduling the task in `smoothPressure()`
}
