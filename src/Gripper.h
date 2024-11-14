#ifndef GRIPPER_H
#define GRIPPER_H

#include "TaskCommand.h"

class Gripper {
public:
    Gripper(int pumpPin, int valvePin, TaskQueue& taskQueue);
    
    bool isBusy() const;
    void setBusy(bool busy);
    bool isOpen() const;
    void setOpen(bool gripperOpen);
    void turnOnPump(int duration);
    void turnOffPump();
    void openGripper();
    void closeGripper();
    void refreshVacuum();
    void changeRefreshCounter(int counterChange);
    void resetRefreshCounter();
    void startVacuumRefresh();
    void stopVacuumRefresh();

private:
    int pumpPin;
    int valvePin;
    unsigned long lastPumpActivationTime;
    bool pumpActive;
    int refreshTaskCounter;
    volatile bool busy;
    bool gripperOpen;
    unsigned long pumpOnDuration = 1500000; // Default pump on duration of 1500ms
    unsigned long refreshInterval = 60000000; // Default refresh interval of 60 seconds
    unsigned long currentMicros;

    TaskQueue& taskQueue;  // Reference to the global TaskQueue

    Task pumpOffTask;      // Task to turn off the pump after a duration
    Task refreshVacuumTask; // Task to periodically refresh the vacuum
};

#endif // GRIPPER_H