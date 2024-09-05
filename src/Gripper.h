#ifndef GRIPPER_H
#define GRIPPER_H

#include "TaskCommand.h"

class Gripper {
public:
    Gripper(int pumpPin, int valvePin1, int valvePin2, TaskQueue& taskQueue);
    
    bool isBusy() const;
    void setBusy(bool busy);
    bool isOpen() const;
    void setOpen(bool gripperOpen);
    void turnOnPump(int duration);
    void turnOffPump();
    void openGripper();
    void closeGripper();
    void refreshVacuum();
    void setRefreshTaskScheduled(bool refreshTaskScheduled);
    void startVacuumRefresh();
    void stopVacuumRefresh();

private:
    int pumpPin;
    int valvePin1;
    int valvePin2;
    unsigned long lastPumpActivationTime;
    bool pumpActive;
    bool refreshTaskScheduled;
    volatile bool busy;
    bool gripperOpen;
    int pumpOnDuration = 1500000; // Default pump on duration of 1500ms
    int refreshInterval = 60000000; // Default refresh interval of 60 seconds
    long currentMicros;

    TaskQueue& taskQueue;  // Reference to the global TaskQueue

    Task pumpOffTask;      // Task to turn off the pump after a duration
    Task refreshVacuumTask; // Task to periodically refresh the vacuum
};

#endif // GRIPPER_H