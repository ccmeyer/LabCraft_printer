#ifndef GRIPPER_H
#define GRIPPER_H

#include "TaskCommand.h"

class Gripper {
public:
    Gripper(int pumpPin, int valveOpenPin, int valveClosePin, TaskQueue& taskQueue);

    void turnOnPump(int duration);
    void turnOffPump();
    void openGripper();
    void closeGripper();
    void refreshVacuum();
    void stopVacuumRefresh();

private:
    int pumpPin;
    int valveOpenPin;
    int valveClosePin;
    unsigned long lastPumpActivationTime;
    bool pumpActive;
    bool gripperOpen;
    int refreshInterval = 10000; // Default refresh interval of 60 seconds

    TaskQueue& taskQueue;  // Reference to the global TaskQueue

    Task pumpOffTask;      // Task to turn off the pump after a duration
    Task refreshVacuumTask; // Task to periodically refresh the vacuum
};

#endif // GRIPPER_H