#ifndef ORCHESTRATOR_H
#define ORCHESTRATOR_H

#include "stm32f4xx_hal.h"
#include "FreeRTOS.h"
#include "queue.h"
#include "task.h"
#include "event_groups.h"
#include <cstdint>

// bit-flags for waiting on completion
#define BIT_LED_DONE      (1 << 0)
#define BIT_STEPPER1_DONE (1 << 1)
#define BIT_STEPPER2_DONE (1 << 2)
#define BIT_STEPPER3_DONE (1 << 3)
#define BIT_STEPPER4_DONE (1 << 4)
#define BIT_STEPPER5_DONE (1 << 5)
#define BIT_PRINTING_DONE (1 << 6)



class Orchestrator {
public:
  // the two command types we currently support
  enum CmdType : uint8_t {
    CMD_LED   = 0x01,  // flash LED
    CMD_MOVE_X  = 0x02,  // move one axis
    CMD_MOVE_Y  = 0x03,  // move one axis
    CMD_MOVE_Z  = 0x04,  // move one axis

	CMD_HOME_X  = 0x05,  // Home one axis
	CMD_HOME_Y  = 0x06,  // Home one axis
	CMD_HOME_Z  = 0x07,  // Home one axis

	CMD_ENABLE_MOTORS = 0x08,
	CMD_DISABLE_MOTORS = 0x09,

	CMD_ABS_X = 0x0A,
	CMD_ABS_Y = 0x0B,
	CMD_ABS_Z = 0x0C,

	CMD_REL_XY = 0x0D,
	CMD_ABS_XY = 0x0E,

	CMD_GRIPPER_OPEN = 0X10,	// Open Gripper
	CMD_GRIPPER_CLOSE = 0X11,	// Close Gripper
	CMD_GRIPPER_OFF = 0X12,	// Stop Gripper

	CMD_PRINT = 0x20,
	CMD_REFUEL = 0x21,
	CMD_DISPENSE = 0x22,
	CMD_DISPENSE_PRINT = 0x23,
	CMD_DISPENSE_REFUEL = 0x24,

	CMD_LEDSTRIP_ON = 0x30,
	CMD_LEDSTRIP_OFF = 0x31,

	CMD_INIT_FLASH = 0xC0,
	CMD_STOP_FLASH = 0xC1,
	CMD_SET_FLASH_DURATION = 0xC2,
	CMD_SET_FLASH_DELAY = 0xC3,
	CMD_SET_IMAGING_DROPLETS = 0XC4,


	CMD_SET_PW_PRINT = 0xD0,
	CMD_SET_PW_REFUEL = 0xD1,

	CMD_PR_PRINT = 0xE0,
	CMD_PR_REFUEL = 0xE1,

	CMD_HOME_PRINT = 0xE2,
	CMD_HOME_REFUEL = 0xE3,
	CMD_P_VALVE_OPEN = 0xE4,
	CMD_P_VALVE_CLOSE = 0xE5,
	CMD_R_VALVE_OPEN = 0xE6,
	CMD_R_VALVE_CLOSE = 0xE7,
	CMD_P_REG_START = 0xE8,
	CMD_P_REG_STOP = 0xE9,
	CMD_R_REG_START = 0xEA,
	CMD_R_REG_STOP = 0xEB,

	CMD_PR_PRINT_REL = 0xEC,
	CMD_PR_REFUEL_REL = 0xED,

	CMD_RESET_PRINT = 0xEE,
	CMD_RESET_REFUEL = 0xEF,

	CMD_PAUSE = 0xF0,
    CMD_RESUME = 0xF1,
	CMD_CLEAR = 0xF2,
	CMD_HELLO       = 0xF3,
	CMD_HELLO_ACK   = 0xF4,
	CMD_GOODBYE     = 0xF5,
	CMD_BYE_ACK     = 0xF6
  };

  // complete packet, decoded from Comm
  struct Command {
    CmdType   cmd;
    uint8_t   seq;
    uint32_t  p1, p2, p3;
  };

  Orchestrator();

  static Orchestrator* instance();
  void begin();
//  void waitForBit(uint32_t targetBit);

  // called from ISR to push a new command
  BaseType_t enqueueFromISR(const Command& cmd, BaseType_t* pxHigherPriorityTaskWoken);

  /// allow LEDController to set the DONE bit
  static EventGroupHandle_t getDoneEvents() {
    return instance()->_doneEvents;
  }

  static UBaseType_t getCommandDepth() {
	  return uxQueueMessagesWaiting(instance()->_cmdQueue);
  }

  static uint16_t getLastCmdNum() {
	  return instance()->_lastExecutedCmdNum;
  }

  static uint16_t getCurrentCmdNum() {
	  return instance()->_currentCmdNum;
  }

  bool waitForBit(EventBits_t bit);
  void executeCommand(const Command &cmd);

  // Capture last command to reset the blocking condition
  Command _inFlight;
  Command _lastPausedCmd;
  uint16_t _currentCmdNum;
  uint16_t _lastExecutedCmdNum;

  volatile bool _pauseRequested  = false;
  volatile bool _resumeRequested = false;
  volatile bool _clearRequested  = false;
  volatile bool _acknowledgeRequested = false;
  bool _paused = false;

  void clearQueue();
  void pauseCurrent();
  void resumeCurrent();
  void cancelCurrent();

  /// Called from your EXTI ISR to poke the flash task
  void flashNotifyFromISR(uint16_t GPIO_Pin);

  void setFlashDelay(uint32_t flashDelay);
  void setImagingDroplets(uint16_t imagingDroplets) { _imagingDroplets = imagingDroplets; }

  void scheduleFlashIn();


private:
  static Orchestrator* 	_instance;

  static void            _taskEntry(void* pv);
  void                   _run();

  QueueHandle_t          _cmdQueue;
  TaskHandle_t           _taskHandle;
  EventGroupHandle_t     _doneEvents;

  TaskHandle_t   _flashTaskHandle = nullptr;
  // flash-monitor task entry
  static void      _flashTaskEntry(void* pv);
  // flash-monitor task loop
  void             _flashTaskLoop();

  GPIO_TypeDef*      _trigPort;
  uint16_t           _trigPin;
  uint32_t			 _flashDelay;
  uint16_t			 _imagingDroplets;
  uint16_t			 _imagingFreq;
};

#endif // ORCHESTRATOR_H
