#ifndef ORCHESTRATOR_H
#define ORCHESTRATOR_H

#include "stm32f4xx_hal.h"
#include "FreeRTOS.h"
#include "queue.h"
#include "task.h"
#include "event_groups.h"
#include "semphr.h"
#include "Stepper.h"
#include "PressureRegulator.h"
#include "BoardConfig.h"

#include <cstdint>
#include <cstring>

// bit-flags for waiting on completion
#define BIT_LED_DONE      (1u << 0)
#define BIT_STEPPER1_DONE (1u << 1)
#define BIT_STEPPER2_DONE (1u << 2)
#define BIT_STEPPER3_DONE (1u << 3)
#define BIT_STEPPER4_DONE (1u << 4)
#define BIT_STEPPER5_DONE (1u << 5)
#define BIT_PRINTING_DONE (1u << 6)
#define BIT_GRIPPER_DONE  (1u << 7)
#define BIT_FLASH_DONE    (1u << 8)
#define BIT_PRESSURE_P_READY    (1u << 9)   // Print regulator
#define BIT_PRESSURE_R_READY    (1u << 10)  // Refuel regulator
#define BIT_HOME_X_DONE   (1u << 11)
#define BIT_HOME_Y_DONE   (1u << 12)
#define BIT_HOME_Z_DONE   (1u << 13)  // optional if you want async Z too
#define BIT_HOME_P_DONE   (1u << 14)
#define BIT_HOME_R_DONE   (1u << 15)



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

	CMD_SET_AXIS_MAXSPEED = 0x40,   // p1=axis (0..4), p2=max Hz
	CMD_SET_AXIS_ACCEL    = 0x41,   // p1=axis (0..4), p2=accel (steps/s^2)
	CMD_SET_AXIS_PROFILE  = 0x42,   // p1=axis (0..4), p2=profile (0,1,2)

	CMD_HOME_XY = 0x43,
	CMD_HOME_PR_BOTH = 0x44,

	CMD_WAIT = 0x50,	// p1=wait time (ms)

	CMD_ENABLE_PRINT_PROFILE = 0x60,
	CMD_DISABLE_PRINT_PROFILE = 0x61,
	CMD_SET_GRIPPER_PARAMS = 0x62,

	CMD_INIT_FLASH = 0xC0,
	CMD_STOP_FLASH = 0xC1,
	CMD_SET_FLASH_DURATION = 0xC2,
	CMD_SET_FLASH_DELAY = 0xC3,
	CMD_SET_IMAGING_DROPLETS = 0xC4,


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
		CMD_BYE_ACK     = 0xF6,
		CMD_CLEAR_ACK	= 0xF7,
		CMD_BYE_DONE	= 0xF8,
		CMD_RESET_REPORT = 0xF9,

		CMD_SELFTEST_START  = 0xFA,
		CMD_SELFTEST_RESULT = 0xFB,
		CMD_SELFTEST_DONE   = 0xFC,
		CMD_SELFTEST_ABORT  = 0xFD
	  };

  // complete packet, decoded from Comm
  struct Command {
    CmdType  cmd;
    uint8_t  seq8;
    uint32_t  seq32;     // full sequence
    bool      hasSeq32;  // parsed TLV present

    uint32_t p1 = 0, p2 = 0, p3 = 0;   // raw 32-bit storage
    uint8_t  p1Len = 0, p2Len = 0, p3Len = 0; // TLV value lengths (0,1,2,4)

    // Integer views (unsigned and signed)
    inline uint32_t p1u() const { return p1; }
    inline uint32_t p2u() const { return p2; }
    inline uint32_t p3u() const { return p3; }
    inline int32_t  p1s() const { return int32_t(p1); }
    inline int32_t  p2s() const { return int32_t(p2); }
    inline int32_t  p3s() const { return int32_t(p3); }

    // Boolean flag view (for sign bit you send as 0/1)
    inline bool  p1b() const { return p1 != 0; }
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

  static uint32_t getLastCmdNum() {
	  return instance()->_lastExecutedCmdNum;
  }

  static uint32_t getCurrentCmdNum() {
	  return instance()->_currentCmdNum;
  }

  bool waitForBit(EventBits_t bit);
  bool waitForBits(EventBits_t bits);
  void executeCommand(const Command &cmd);

  // Capture last command to reset the blocking condition
  Command _inFlight;
  Command _lastPausedCmd;
  uint32_t _currentCmdNum;
  uint32_t _lastExecutedCmdNum;

  // epoch/seq tracking
  uint16_t  _seqEpoch             = 0;
  uint8_t   _lastSeq8             = 0;

  volatile bool _pauseRequested  = false;
  volatile bool _resumeRequested = false;
  volatile bool _clearRequested  = false;
	  volatile bool _acknowledgeRequested = false;
	  volatile bool _shutdownRequested = false;
	  volatile bool _selfTestAbortRequested = false;



  volatile bool _paused = false;
  volatile bool _clearing = false;

  void clearQueue();
  void pauseCurrent();
  void resumeCurrent();
  void cancelCurrent();

//  void performShutdown(uint8_t byeSeq);
  void performShutdown(uint8_t byeSeq8, uint32_t byeSeq32, bool have32);

#if (LC_HAS_IMAGING > 0)

  void flashNotifyFromISR(uint16_t GPIO_Pin);
  void setFlashDelay(uint32_t flashDelay);
  void setImagingDroplets(uint16_t imagingDroplets) { _imagingDroplets = imagingDroplets; }
  void scheduleFlashIn();

  static uint32_t getFlashDelay()       { return instance()->_flashDelay; }
  static uint32_t getExtCount()         { return instance()->g_exti8_count; }
  static uint32_t getFlashAckCount()    { return instance()->g_flash_ack_count; }
  static uint32_t getFlashTaskWakeCount(){ return instance()->g_flash_task_wake_count; }
  static uint32_t getFlashTaskDoneCount(){ return instance()->g_flash_task_done_count; }
  static uint32_t getFlashInitCmdCount() { return instance()->g_flash_init_cmd_count; }
  static uint32_t getFlashInitOkCount() { return instance()->g_flash_init_ok_count; }
  static uint32_t getFlashInitTaskCreateFailCount() { return instance()->g_flash_init_task_create_fail_count; }
  static uint32_t getFlashInitTimerCreateFailCount() { return instance()->g_flash_init_timer_create_fail_count; }
  static uint16_t getImagingDroplets()  { return instance()->_imagingDroplets; }
  void noteFlashAckFromISR()            { g_flash_ack_count++; }

#else

  // ---- Legacy stubs: compile-safe, return zeros ----
  void flashNotifyFromISR(uint16_t) {}
  void setFlashDelay(uint32_t) {}
  void setImagingDroplets(uint16_t) {}
  void scheduleFlashIn() {}

  static uint32_t getFlashDelay()       { return 0; }
  static uint32_t getExtCount()         { return 0; }
  static uint32_t getFlashAckCount()    { return 0; }
  static uint32_t getFlashTaskWakeCount(){ return 0; }
  static uint32_t getFlashTaskDoneCount(){ return 0; }
  static uint32_t getFlashInitCmdCount() { return 0; }
  static uint32_t getFlashInitOkCount() { return 0; }
  static uint32_t getFlashInitTaskCreateFailCount() { return 0; }
  static uint32_t getFlashInitTimerCreateFailCount() { return 0; }
  static uint16_t getImagingDroplets()  { return 0; }

#endif

  TimerHandle_t    _flashAckTmr = nullptr;   // FreeRTOS software timer to clear the strobe
  void         _flashAckHigh();
  void         _flashAckLow();

  void startHomeAsync(Stepper* s,
                      uint32_t fastHz,
                      uint32_t slowHz,
                      uint32_t backoffSteps,
                      EventBits_t doneBit);

  void startRegHomeAsync(PressureRegulator* r,
                         uint32_t fastHz,
                         uint32_t slowHz,
                         uint32_t backoffSteps,
                         EventBits_t doneBit);

private:
  static Orchestrator* 	_instance;

  static void            _taskEntry(void* pv);
  void                   _run();

  QueueHandle_t          _cmdQueue;
  TaskHandle_t           _taskHandle;
  EventGroupHandle_t     _doneEvents;

  // --- CMD_WAIT support (pause-aware, resume-able) ---
  TickType_t _waitRemainingTicks = 0;

  static constexpr uint32_t WAIT_QUANTUM_MS = 20;

  bool pauseAwareDelayTicks(TickType_t& remainingTicks);
  static TickType_t msToAtLeast1Tick(uint32_t ms);

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

  static constexpr uint32_t kFlashAckMs = 5; // how long to hold the "flash fired" pin high

  // GPIO that reports "flash fired" to the Pi
  GPIO_TypeDef*    _flashAckPort = GPIOE;
  uint16_t         _flashAckPin  = GPIO_PIN_12;
  volatile bool _awaitingRelease = false;   // true after 1st EXTI until line goes LOW
  volatile uint32_t g_exti8_count = 0;
  volatile uint32_t g_flash_ack_count = 0;
  volatile uint32_t g_flash_task_wake_count = 0;
  volatile uint32_t g_flash_task_done_count = 0;
  volatile uint32_t g_flash_init_cmd_count = 0;
  volatile uint32_t g_flash_init_ok_count = 0;
  volatile uint32_t g_flash_init_task_create_fail_count = 0;
  volatile uint32_t g_flash_init_timer_create_fail_count = 0;


  static void _flashAckTimerCb(TimerHandle_t);

  bool _flashInProgress = false;


  static void _homeTaskEntry(void* ctx);
  struct HomeTaskArgs {
    Stepper*   stepper;
    uint32_t   fastHz;
    uint32_t   slowHz;
    uint32_t   backoffSteps;
    EventBits_t doneBit;
  };

  static void _regHomeTaskEntry(void* ctx);
  struct RegHomeTaskArgs {
    PressureRegulator* reg;
    uint32_t           fastHz;
    uint32_t           slowHz;
    uint32_t           backoffSteps;
    EventBits_t        doneBit;
  };

  // ---- Static stacks/TCBs for homing tasks (no heap allocation) ----
  static constexpr uint16_t HOME_STACK_WORDS     = 320;  // ~1280 bytes
  static constexpr uint16_t REG_HOME_STACK_WORDS = 384;  // ~1536 bytes

  // X & Y home tasks
  StaticTask_t  _tcbHomeX{};
  StaticTask_t  _tcbHomeY{};
  StaticTask_t  _tcbHomeZ{};
  StackType_t   _stackHomeX[HOME_STACK_WORDS];
  StackType_t   _stackHomeY[HOME_STACK_WORDS];
  StackType_t   _stackHomeZ[HOME_STACK_WORDS];
  TaskHandle_t  _taskHomeX = nullptr;
  TaskHandle_t  _taskHomeY = nullptr;
  TaskHandle_t  _taskHomeZ = nullptr;
  HomeTaskArgs  _argsHomeX{};
  HomeTaskArgs  _argsHomeY{};
  HomeTaskArgs  _argsHomeZ{};

  // P regulator home task
  StaticTask_t     _tcbHomeP{};
  StackType_t      _stackHomeP[REG_HOME_STACK_WORDS];
  TaskHandle_t     _taskHomeP = nullptr;
  RegHomeTaskArgs  _argsHomeP{};

#if (LC_PRESSURE_PORTS > 1)
  // R regulator home task (only on dual-channel machines)
  StaticTask_t     _tcbHomeR{};
  StackType_t      _stackHomeR[REG_HOME_STACK_WORDS];
  TaskHandle_t     _taskHomeR = nullptr;
  RegHomeTaskArgs  _argsHomeR{};
#endif
};

#endif // ORCHESTRATOR_H
