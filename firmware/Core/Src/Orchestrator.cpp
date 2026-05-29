/*
 * Orchestrator.cpp
 *
 *  Created on: Jun 19, 2025
 *      Author: conar
 */
#include "BoardConfig.h"
#include "Orchestrator.h"
#include "Diagnostics.h"
#include "OrchestratorCompletionPolicy.h"
#include "OrchestratorDecode.h"
#include "SelfTestCommandPolicy.h"
#include "LEDController.h"    // your LED queue + done-event
#include "Stepper.h"          // MX_STEPPERx_Move(), MX_STEPPERx_Stop(), MX_STEPPERx_IsBusy()
#include "Gripper.h"
#include "Printer.h"
#include "PressureRegulator.h"
#include "PressureRegulatorMath.h"
#include "PressureTargetPolicy.h"
#include "PressureSensor.h"
#include "RegulatorProfileCommandPolicy.h"
#include "Logger.h"
#include "Gantry.h"
#include "Comm.h"
#include "CommCodec.h"
#include "CrashLog.h"
#include "CrashLogCodec.h"
#include "WatchdogSupervisor.h"
#include "cmsis_os.h"         // for portMAX_DELAY, pdTRUE, etc.
#include "task.h"
#include <cstdio>
#include <cstring>

#if LC_HAS_IMAGING > 0
  #include "Flash.h"
  #include "Flash.hpp"
#endif

#if LC_HAS_LED_STRIP > 0
  #include "LEDStrip.h"
#endif

extern "C" uint32_t RTOS_StackOverflowHookFired(void);

Orchestrator* Orchestrator::_instance = nullptr;

namespace {

const char* flashDisarmReasonToken(const char* reason)
{
  return (reason != nullptr && reason[0] != '\0') ? reason : "unknown";
}

}

namespace {
bool s_resetReportSent = false;
namespace RegProfile = RegulatorProfileCommandPolicy;

RegProfile::RecoveryStaging s_regProfileRecoveryStaging[2]{};
bool s_regProfileBaselineCaptured = false;
PressureRegulator::RuntimeConfigSnapshot s_regProfileBaselinePrint{};
#if (LC_PRESSURE_PORTS > 1)
PressureRegulator::RuntimeConfigSnapshot s_regProfileBaselineRefuel{};
#endif

PressureRegulator* regulatorForRegProfileChannel(uint8_t channel) {
  if (channel == RegProfile::kChannelPrint) {
    return &PressureRegulator::regP();
  }
#if (LC_PRESSURE_PORTS > 1)
  if (channel == RegProfile::kChannelRefuel) {
    return &PressureRegulator::regR();
  }
#endif
  return nullptr;
}

PressureRegulator::RecoveryConfig toRuntimeRecovery(
    const RegProfile::RecoveryConfig& cfg) {
  PressureRegulator::RecoveryConfig runtime{};
  runtime.activeTicks = cfg.activeTicks;
  runtime.baseBoostHz = cfg.baseBoostHz;
  runtime.pulseCoeffHzPerUs = cfg.pulseCoeffHzPerUs;
  runtime.pressureCoeffHzPerRaw = cfg.pressureCoeffHzPerRaw;
  runtime.maxBoostHz = cfg.maxBoostHz;
  runtime.recoveryFloorHz = cfg.recoveryFloorHz;
  runtime.recoveryExitErrorRaw = cfg.recoveryExitErrorRaw;
  runtime.maxExtendTicks = cfg.maxExtendTicks;
  runtime.allowExtendWhileUndershoot = cfg.allowExtendWhileUndershoot;
  runtime.boostOnlyWhenUndershoot = cfg.boostOnlyWhenUndershoot;
  runtime.linearDecay = cfg.linearDecay;
  return runtime;
}

PressureRegulator::SlewConfig toRuntimeSlew(const RegProfile::SlewConfig& cfg) {
  PressureRegulator::SlewConfig runtime{};
  runtime.maxHzDeltaUpPerLoop = cfg.maxHzDeltaUpPerLoop;
  runtime.maxHzDeltaDownPerLoop = cfg.maxHzDeltaDownPerLoop;
  runtime.recoveryBypassSlewTicks = cfg.recoveryBypassSlewTicks;
  return runtime;
}

PressureRegulator::ReadyConfig toRuntimeReady(const RegProfile::ReadyConfig& cfg) {
  PressureRegulator::ReadyConfig runtime{};
  runtime.readyTolRaw = cfg.readyTolRaw;
  runtime.consecutiveSamples = cfg.consecutiveSamples;
  return runtime;
}

void captureRegProfileBaselineIfNeeded() {
  if (s_regProfileBaselineCaptured) {
    return;
  }
  s_regProfileBaselinePrint = PressureRegulator::regP().getRuntimeConfigSnapshot();
#if (LC_PRESSURE_PORTS > 1)
  s_regProfileBaselineRefuel = PressureRegulator::regR().getRuntimeConfigSnapshot();
#endif
  s_regProfileBaselineCaptured = true;
}

void resetRegProfileSessionState() {
  RegProfile::resetRecoveryStaging(s_regProfileRecoveryStaging[0]);
  RegProfile::resetRecoveryStaging(s_regProfileRecoveryStaging[1]);
  s_regProfileBaselineCaptured = false;
}

void logRegProfileReject(const char* commandName, RegProfile::Status status) {
  Logger::instance()->log(
      "[RegProfile] %s rejected: %s\r\n",
      commandName,
      RegProfile::statusName(status));
}

void logRegProfileNoChannel(const char* commandName, uint8_t channel) {
  Logger::instance()->log(
      "[RegProfile] %s rejected: unavailable channel %u\r\n",
      commandName,
      static_cast<unsigned>(channel));
}

#ifndef LC_CRASH_TEST_GRIPPER_OPEN_WDT
#define LC_CRASH_TEST_GRIPPER_OPEN_WDT 0
#endif

void runGripperOpenWatchdogCrashTest() {
  for (;;) {
    /* Intentionally starve orchestrator watchdog check-ins for crash-log validation. */
  }
}

bool shouldSendResetReport(const CrashLogSnapshot& snap) {
  return ((snap.flags & CRASHLOG_FLAG_PENDING) != 0u) ||
         (snap.resetCause == CRASH_RESET_IWDG) ||
         (snap.resetCause == CRASH_RESET_WWDG);
}

void maybeSendResetReport(uint8_t seq8, uint32_t seq32) {
  if (s_resetReportSent) {
    return;
  }
  CrashLogSnapshot snap{};
  CrashLog_GetSnapshot(&snap);
  if (!shouldSendResetReport(snap)) {
    return;
  }
  Comm::instance()->sendResetReport(seq8, seq32, &snap, CrashLog_IsWatchdogRecoveryBoot());
  s_resetReportSent = true;
}
}

Orchestrator::Orchestrator()
  : _cmdQueue(nullptr),
    _ackQueue(nullptr),
    _taskHandle(nullptr),
    _doneEvents(nullptr)
{
	_instance = this;
	_currentCmdNum = 0;
	_lastExecutedCmdNum = 0;
	_lastAcceptedCmdNum = 0;
	_lastRetiredCmdNum = 0;
	_nextExpectedCmdNum = 1;
	_pauseAfterSeq32 = 0;
	_trigPort = GPIOE;
	_trigPin = GPIO_PIN_8;
	_flashDelay = 1000;
	_imagingDroplets = 1;
	_imagingFreq = 20;
}

Orchestrator* Orchestrator::instance() {
  return _instance;
}

void Orchestrator::begin() {
  // queue for up to 16 commands
  _cmdQueue    = xQueueCreate(16, sizeof(Command));
  _ackQueue    = xQueueCreate(16, sizeof(AckMessage));
  // event bits to wait on finish
  _doneEvents  = xEventGroupCreate();

  xTaskCreate(
    _taskEntry, "Orch",
    3328,    this,
    tskIDLE_PRIORITY + 2,
    &_taskHandle
  );
}

extern "C" void MX_ORCH_Init()
{
  static Orchestrator orch;
  orch.begin();
}

BaseType_t Orchestrator::enqueueAckFromISR(const AckMessage& ack, BaseType_t* pxHigherPriorityTaskWoken) {
    if (_ackQueue == nullptr) {
        return pdFALSE;
    }
    return xQueueSendFromISR(_ackQueue, &ack, pxHigherPriorityTaskWoken);
}

void Orchestrator::retireAcceptedPendingCommands() {
    if (_lastAcceptedCmdNum > _lastRetiredCmdNum) {
        _lastRetiredCmdNum = _lastAcceptedCmdNum;
    }
    _currentCmdNum = _lastRetiredCmdNum;
}

void Orchestrator::applyPauseAfterWatermark() {
    if (_pauseAfterSeq32 == 0u) {
        return;
    }
    if (_lastRetiredCmdNum < _pauseAfterSeq32) {
        return;
    }

    cancelCurrent();
    if (_cmdQueue) {
        Command dump{};
        while (xQueueReceive(_cmdQueue, &dump, 0) == pdTRUE) { /* discard queued future work */ }
    }
    retireAcceptedPendingCommands();
    _paused = true;
    _pauseRequested = false;
    _pauseAfterSeq32 = 0u;
    _pauseWatermarkReached = true;
}

BaseType_t Orchestrator::enqueueFromISR(const Command& cmd, BaseType_t* pxHigherPriorityTaskWoken) {
	// special commands — handle immediately

	    switch (cmd.cmd) {
			case CMD_HELLO: {
			  CrashLog_SetBootStage(CRASH_BOOT_STAGE_HELLO_RX);
			  // Reset any stale state and request HELLO_ACK
			  _paused = false; _pauseRequested = false;
		  _seqEpoch=0; _lastSeq8=0; _currentCmdNum=0; _lastExecutedCmdNum=0;
		  _resumeRequested = false; _clearRequested = false;
		  _shutdownRequested = false;
		  _pauseWatermarkReached = false;
		  _pauseAfterSeq32 = 0u;
		  _lastAcceptedCmdNum = 0u;
		  _lastRetiredCmdNum = 0u;
		  _nextExpectedCmdNum = 1u;
		  _inFlight = cmd;
		  AckMessage ack{};
		  ack.ackCmd = CMD_HELLO_ACK;
		  ack.seq8 = cmd.seq8;
		  ack.seq32 = cmd.hasSeq32 ? cmd.seq32 : 0u;
		  ack.includeSeq32 = cmd.hasSeq32;
		  ack.includeCapabilities = true;
		  ack.capabilities = TRANSPORT_CAPABILITIES;
		  return enqueueAckFromISR(ack, pxHigherPriorityTaskWoken);
		}
		case CMD_GOODBYE: {
		  _inFlight = cmd;
		  _paused = true;
		  _pauseRequested = true;
		  _shutdownRequested = true;
		  AckMessage ack{};
		  ack.ackCmd = CMD_BYE_ACK;
		  ack.seq8 = cmd.seq8;
		  ack.seq32 = cmd.hasSeq32 ? cmd.seq32 : 0u;
		  ack.includeSeq32 = cmd.hasSeq32;
		  return enqueueAckFromISR(ack, pxHigherPriorityTaskWoken);
		}
        case CMD_PAUSE:
		  _paused = true;
		  _pauseRequested = true;
		  return pdFALSE;
		case CMD_RESUME:
		  _resumeRequested = true;
		  return pdFALSE;
	      case CMD_CLEAR: {
			  _inFlight = cmd;
	    	  _clearRequested = true;
	    	  AckMessage ack{};
	    	  ack.ackCmd = CMD_CLEAR_ACK;
	    	  ack.seq8 = cmd.seq8;
	    	  ack.seq32 = cmd.hasSeq32 ? cmd.seq32 : 0u;
	    	  ack.includeSeq32 = cmd.hasSeq32;
	          return enqueueAckFromISR(ack, pxHigherPriorityTaskWoken);
	      }
	      case CMD_PAUSE_AFTER_SEQ32: {
	    	  AckMessage ack{};
	    	  ack.ackCmd = CMD_QUEUE_ACK;
	    	  ack.seq8 = cmd.seq8;
	    	  ack.seq32 = cmd.hasSeq32 ? cmd.seq32 : 0u;
	    	  ack.includeSeq32 = cmd.hasSeq32;
	    	  ack.includeAckResult = true;
	    	  if (cmd.hasSeq32 && cmd.p1u() >= _lastExecutedCmdNum) {
	    	  	  _pauseAfterSeq32 = cmd.p1u();
	    	  	  _pauseWatermarkReached = false;
	    	  	  ack.ackResult = ACK_RESULT_WATERMARK_SET;
	    	  } else {
	    	  	  ack.ackResult = ACK_RESULT_WATERMARK_REJECTED;
	    	  }
	    	  return enqueueAckFromISR(ack, pxHigherPriorityTaskWoken);
	      }
	      case CMD_SELFTEST_ABORT: {
	        _selfTestAbortRequested = true;
	        return pdFALSE;
	      }
	      default: {
	    	  break;
	      }
	    }

	if (!cmd.hasSeq32) {
		return pdFALSE;
	}

	AckMessage ack{};
	ack.ackCmd = CMD_QUEUE_ACK;
	ack.seq8 = cmd.seq8;
	ack.seq32 = cmd.seq32;
	ack.includeSeq32 = true;
	ack.includeAckResult = true;

	if (cmd.seq32 < _nextExpectedCmdNum) {
		ack.ackResult = ACK_RESULT_DUPLICATE;
		return enqueueAckFromISR(ack, pxHigherPriorityTaskWoken);
	}

	if (cmd.seq32 > _nextExpectedCmdNum) {
		ack.ackResult = ACK_RESULT_GAP;
		ack.includeExpectedSeq32 = true;
		ack.expectedSeq32 = _nextExpectedCmdNum;
		return enqueueAckFromISR(ack, pxHigherPriorityTaskWoken);
	}

	if (_cmdQueue == nullptr) {
		ack.ackResult = ACK_RESULT_BUSY;
		return enqueueAckFromISR(ack, pxHigherPriorityTaskWoken);
	}

	const BaseType_t queued = xQueueSendFromISR(_cmdQueue, &cmd, pxHigherPriorityTaskWoken);
	if (queued == pdPASS) {
		_lastAcceptedCmdNum = cmd.seq32;
		_nextExpectedCmdNum = cmd.seq32 + 1u;
		ack.ackResult = ACK_RESULT_ACCEPTED;
	} else {
		ack.ackResult = ACK_RESULT_BUSY;
	}
	(void)enqueueAckFromISR(ack, pxHigherPriorityTaskWoken);
	return queued;
}


void Orchestrator::pauseCurrent() {
  Logger::instance()->log("pauseCurrent\r\n");
  Gantry::instance()->pauseXYZMotors();
  Printer::instance()->pauseDispense();
//  PressureRegulator::regP().pause();
//  PressureRegulator::regR().pause();
  xEventGroupClearBits(_doneEvents,
      BIT_LED_DONE|BIT_STEPPER1_DONE|BIT_STEPPER2_DONE|
      BIT_STEPPER3_DONE|BIT_PRINTING_DONE|BIT_FLASH_PRINT_DONE|BIT_GRIPPER_DONE);
}

void Orchestrator::resumeCurrent() {
  Logger::instance()->log("resumeCurrent\r\n");
  Gantry::instance()->resumeXYZMotors();
  Printer::instance()->resumeDispense();
//  PressureRegulator::regP().start();
//  PressureRegulator::regR().start();
}
void Orchestrator::cancelCurrent() {
//  Logger::instance()->log("cancelCurrent\r\n");
  Gantry::instance()->cancelXYZMotors();
  Printer::instance()->cancelDispense();
}

void Orchestrator::_taskEntry(void* pv) {
  static_cast<Orchestrator*>(pv)->_run();
}

TickType_t Orchestrator::msToAtLeast1Tick(uint32_t ms)
{
  if (ms == 0) return 0;
  TickType_t t = pdMS_TO_TICKS(ms);
  return (t == 0) ? 1 : t;  // ensure tiny waits still delay at least 1 tick
}

bool Orchestrator::pauseAwareDelayTicks(TickType_t& remainingTicks)
{
  const TickType_t quantum = msToAtLeast1Tick(WAIT_QUANTUM_MS);

  while (remainingTicks > 0) {
    Watchdog_CheckIn(CRASH_TASK_ORCH);
    drainAckQueue();
    // Interrupt conditions (match your waitForBit() intent)
    if (_paused || _pauseRequested || _clearRequested || _shutdownRequested) {
      return false;
    }

    TickType_t step = remainingTicks;
    if (step > quantum) step = quantum;

    vTaskDelay(step);
    drainAckQueue();

    if (remainingTicks >= step) remainingTicks -= step;
    else remainingTicks = 0;
  }
  return true;
}

bool Orchestrator::waitForBit(EventBits_t bit) {
  const TickType_t ticks = pdMS_TO_TICKS(50);
  while (true) {
    Watchdog_CheckIn(CRASH_TASK_ORCH);
    drainAckQueue();
    // If a PAUSE came in, stop waiting immediately.
//    if (_paused) {
//      return false;
//    }
	if (_paused || _pauseRequested || _clearRequested || _shutdownRequested) return false;
    // Wait in small chunks
    EventBits_t result = xEventGroupWaitBits(
      _doneEvents,
      bit,
      pdTRUE,  // clear on exit
      pdTRUE,  // wait for all bits (just one here)
      ticks
    );
    drainAckQueue();
    if ( (result & bit) != 0 ) {
      return true;  // we got the signal, normal completion
    }
    // else: timed out, loop again (to check _paused)
  }
}

bool Orchestrator::waitForBits(EventBits_t bits)
{
  const TickType_t ticks = pdMS_TO_TICKS(50);
  while (true) {
    Watchdog_CheckIn(CRASH_TASK_ORCH);
    drainAckQueue();
		// If a PAUSE came in, stop waiting immediately.
		if (_paused || _pauseRequested || _clearRequested || _shutdownRequested) {
		  return false;
	}
	// Wait in small chunks
	EventBits_t result = xEventGroupWaitBits(
	  _doneEvents,
	  bits,
	  pdTRUE,  // clear on exit
	  pdTRUE,  // wait for all bits (just one here)
	  ticks
	);
    drainAckQueue();
//	if ( (result & bits) != 0 ) {
//	  return true;  // we got the signal, normal completion
//	}
    // require ALL the bits, not any one of them ***
    if ( (result & bits) == bits ) {
      return true;
    }
	// else: timed out, loop again (to check _paused)
  }
}

void Orchestrator::drainAckQueue() {
  if (_ackQueue == nullptr) {
    return;
  }
  AckMessage ack{};
  while (xQueueReceive(_ackQueue, &ack, 0) == pdTRUE) {
    if (ack.ackCmd == CMD_HELLO_ACK) {
      CrashLog_SetBootStage(CRASH_BOOT_STAGE_HELLO_ACK);
      Watchdog_Arm();
      CrashLog_LogBootSummary();
      maybeSendResetReport(ack.seq8, ack.seq32);
      Comm::instance()->setStatusPaused(false);
    #if LC_HAS_LED_STRIP == 1
      MX_LEDSTRIP_FadeTo(100,500);
    #endif
    } else if (ack.ackCmd == CMD_BYE_ACK || ack.ackCmd == CMD_CLEAR_ACK) {
      Comm::instance()->setStatusPaused(true);
      if (ack.ackCmd == CMD_BYE_ACK) {
        Comm::instance()->resetReceiveState();
      #if LC_HAS_LED_STRIP == 1
        MX_LEDSTRIP_FadeTo(0,500);
      #endif
      }
    }

    Comm::instance()->sendAckWithSeq32(
      ack.ackCmd,
      ack.seq8,
      ack.seq32,
      ack.includeSeq32,
      ack.includeAckResult,
      ack.ackResult,
      ack.includeExpectedSeq32,
      ack.expectedSeq32,
      ack.includeCapabilities,
      ack.capabilities
    );
  }
}

void Orchestrator::_run() {
  Watchdog_EnableTask(CRASH_TASK_ORCH);
  maybeSendResetReport(0u, 0u);
  for (;;) {
	  Watchdog_CheckIn(CRASH_TASK_ORCH);
	  drainAckQueue();
	  if (_pauseRequested) {
		    Logger::instance()->log("Run\r\n");
	        pauseCurrent();
	        _paused = true;
	        _pauseRequested = false;
	        _lastPausedCmd = _inFlight;    // remember what we were doing
	      }

	  if (_resumeRequested) {
		if (_pauseWatermarkReached) {
			_pauseWatermarkReached = false;
			_pauseAfterSeq32 = 0u;
			_paused = false;
			_resumeRequested = false;
			continue;
		}
		resumeCurrent();
		_paused = false;
		_resumeRequested = false;
		switch (_lastPausedCmd.cmd) {
			case CMD_MOVE_X: waitForBit(BIT_STEPPER1_DONE); break;
			case CMD_MOVE_Y: waitForBit(BIT_STEPPER2_DONE); break;
			case CMD_MOVE_Z: waitForBit(BIT_STEPPER3_DONE); break;
			case CMD_DISPENSE: waitForBit(BIT_PRINTING_DONE); break;
			case CMD_GRIPPER_OPEN: waitForBit(BIT_GRIPPER_DONE); break;
			case CMD_WAIT: {
			  if (_waitRemainingTicks > 0) {
			    TickType_t rem = _waitRemainingTicks;
			    bool completed = pauseAwareDelayTicks(rem);
			    _waitRemainingTicks = rem;

			    if (completed && _waitRemainingTicks == 0) {
			      _lastExecutedCmdNum = _currentCmdNum;
			      _lastRetiredCmdNum = _lastExecutedCmdNum;
			    }
			  } else {
			    _lastExecutedCmdNum = _currentCmdNum;
			    _lastRetiredCmdNum = _lastExecutedCmdNum;
			  }
			  break;
			}
			// … etc …
			default: {

			}
		  }
	  }
	  if (_clearRequested) {
        // Silence status briefly to reduce traffic during reset (optional)
        Comm::instance()->setStatusPaused(true);

        cancelCurrent();
        xQueueReset(_cmdQueue);
        Comm::instance()->resetReceiveState();

        retireAcceptedPendingCommands();
        _pauseAfterSeq32 = 0u;
        _pauseWatermarkReached = false;
        _resumeRequested = false;
        _pauseRequested = false;

        xEventGroupClearBits(_doneEvents,
            BIT_LED_DONE|BIT_STEPPER1_DONE|BIT_STEPPER2_DONE|BIT_STEPPER3_DONE|BIT_PRINTING_DONE|BIT_FLASH_PRINT_DONE|BIT_GRIPPER_DONE);

        _paused = false;
        _clearRequested = false;
        Logger::instance()->log("--Cleared--\r\n");

        // small grace period then resume status
        vTaskDelay(pdMS_TO_TICKS(20));
        Comm::instance()->setStatusPaused(false);
	  }

	// —— SHUTDOWN: do it after BYE_ACK ——
	if (_shutdownRequested) {
	  // Use the *same* GOODBYE seq so host can match BYE_DONE
	  const uint8_t  seq8   = _inFlight.seq8;
	  const uint32_t seq32  = _inFlight.hasSeq32 ? _inFlight.seq32 : _currentCmdNum;
	  const bool     have32 = _inFlight.hasSeq32;

	  performShutdown(seq8, seq32, have32);
	  _shutdownRequested = false;
	}

	applyPauseAfterWatermark();

	if (_paused) {
	  vTaskDelay(pdMS_TO_TICKS(50));
	  continue;
	}
	// if a flash cycle is underway, wait until it's done
    if (_flashInProgress) {
      (void)waitForBit(BIT_FLASH_DONE);
      // _flashInProgress is cleared by the flash task
    }

    Command cmd;
    // 1) always block here until there’s anything in the queue
    if (xQueueReceive(_cmdQueue, &cmd, pdMS_TO_TICKS(50)) == pdPASS){
        // Flush any queue ACKs generated for this command before a long-running
        // handler like CMD_SELFTEST_START enters its execution path.
        drainAckQueue();
        // We got a real command—execute it
        _inFlight = cmd;
        CrashLog_SetActiveContext(CRASH_TASK_ORCH, static_cast<uint8_t>(cmd.cmd));
        executeCommand(cmd);
        CrashLog_ClearActiveContext();
    }
  }
}

/// factor out all your “case CMD_MOVE_X / CMD_LED / etc” into this:
void Orchestrator::executeCommand(const Command &cmd) {
  bool commandCompleted = true;
	if (cmd.hasSeq32) {
		_currentCmdNum = cmd.seq32;
		_lastSeq8      = cmd.seq8;   // optional: keep for legacy
	} else {
	    if (cmd.seq8 < _lastSeq8 && (_lastSeq8 - cmd.seq8) > 128) { _seqEpoch++; }
	    _lastSeq8 = cmd.seq8;
	    _currentCmdNum = (uint32_t(_seqEpoch) << 8) | uint32_t(cmd.seq8);
	  }
//  _currentCmdNum = cmd.seq;

  // clear done‐bits
  xEventGroupClearBits(_doneEvents,
      BIT_LED_DONE|BIT_STEPPER1_DONE|BIT_STEPPER2_DONE|BIT_STEPPER3_DONE|BIT_PRINTING_DONE|BIT_FLASH_PRINT_DONE|BIT_GRIPPER_DONE|
	  BIT_PRESSURE_P_READY | BIT_PRESSURE_R_READY);

  switch(cmd.cmd) {
	   case CMD_LED: {
          // queue it to the LED controller
//          BlinkCommand bc { cmd.p1, cmd.p2 };
//          LEDController::instance()->enqueue(bc);
//
//          // block until LEDController signals BIT_LED_DONE
//          waitForBit(BIT_LED_DONE);
          break;
        }
        case CMD_MOVE_X: {
          // p1=direction, p2=steps, p3=freqHz
          Stepper::stepperX()->move(cmd.p1, cmd.p2, cmd.p3,2000);
          // wait for stepper ISR to signal BIT_STEPPER_DONE
      	  commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(waitForBit(BIT_STEPPER1_DONE));
          break;
        }
        case CMD_MOVE_Y: {
          // p1=direction, p2=steps, p3=freqHz
          Stepper::stepperY()->move(cmd.p1, cmd.p2, cmd.p3,2000);
      	  commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(waitForBit(BIT_STEPPER2_DONE));
          break;
        }
        case CMD_MOVE_Z: {
          // p1=direction, p2=steps, p3=freqHz
          Stepper::stepperZ()->move(cmd.p1, cmd.p2, cmd.p3,2000);
      	  commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(waitForBit(BIT_STEPPER3_DONE));
          break;
        }
        case CMD_ABS_X: {
          // p1=direction, p2=steps, p3=freqHz
          Stepper::stepperX()->moveTo(cmd.p1, cmd.p2, cmd.p3,2000);
          // wait for stepper ISR to signal BIT_STEPPER_DONE
      	  commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(waitForBit(BIT_STEPPER1_DONE));
          break;
        }
        case CMD_ABS_Y: {
          // p1=direction, p2=steps, p3=freqHz
          Stepper::stepperY()->moveTo(cmd.p1, cmd.p2, cmd.p3,2000);
          // wait for stepper ISR to signal BIT_STEPPER_DONE
      	  commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(waitForBit(BIT_STEPPER2_DONE));
          break;
        }
        case CMD_ABS_Z: {
          // p1=direction, p2=steps, p3=freqHz
          Logger::instance()->log("ABS-Z\r\n");
          Stepper::stepperZ()->moveTo(cmd.p1, cmd.p2, cmd.p3,2000);
          // wait for stepper ISR to signal BIT_STEPPER_DONE
      	  commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(waitForBit(BIT_STEPPER3_DONE));
          break;
        }
	        case CMD_SET_AXIS_MAXSPEED: {
	          const auto intent = OrchestratorDecode::decodeIntent(
	              {static_cast<uint8_t>(cmd.cmd), cmd.p1u(), cmd.p2u(), cmd.p3u()});
	          auto ax = static_cast<Stepper::Axis>(intent.axis);
	          if (auto s = Stepper::getAxis(ax)) s->setMaxSpeedHz(intent.value);
	          break;
	        }
	        case CMD_SET_AXIS_ACCEL: {
	          const auto intent = OrchestratorDecode::decodeIntent(
	              {static_cast<uint8_t>(cmd.cmd), cmd.p1u(), cmd.p2u(), cmd.p3u()});
	          auto ax = static_cast<Stepper::Axis>(intent.axis);
	          if (auto s = Stepper::getAxis(ax)) s->setAccelStepsPerSec2((float)intent.value);
	          break;
	        }
	        case CMD_SET_AXIS_PROFILE: {
	          const auto intent = OrchestratorDecode::decodeIntent(
	              {static_cast<uint8_t>(cmd.cmd), cmd.p1u(), cmd.p2u(), cmd.p3u()});
	          auto ax = static_cast<Stepper::Axis>(intent.axis);
	          auto pf = static_cast<Stepper::AccelProfile>(intent.value);
	          if (auto s = Stepper::getAxis(ax)) s->setAccelProfile(pf);
	          break;
	        }
        case CMD_HOME_X: {
          xEventGroupClearBits(_doneEvents, BIT_HOME_X_DONE);
          startHomeAsync(Stepper::stepperX(), cmd.p1, cmd.p2, cmd.p3, BIT_HOME_X_DONE);
          commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(waitForBit(BIT_HOME_X_DONE));
          break;
        }
        case CMD_HOME_Y: {
          xEventGroupClearBits(_doneEvents, BIT_HOME_Y_DONE);
          startHomeAsync(Stepper::stepperY(), cmd.p1, cmd.p2, cmd.p3, BIT_HOME_Y_DONE);
          commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(waitForBit(BIT_HOME_Y_DONE));
          break;
        }
        case CMD_HOME_Z: {
          xEventGroupClearBits(_doneEvents, BIT_HOME_Z_DONE);
          startHomeAsync(Stepper::stepperZ(), cmd.p1, cmd.p2, cmd.p3, BIT_HOME_Z_DONE);
          commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(waitForBit(BIT_HOME_Z_DONE));
          break;
        }
        case CMD_ENABLE_MOTORS: {
          Stepper::stepperX()->enableMotor();
          Stepper::stepperY()->enableMotor();
          Stepper::stepperZ()->enableMotor();
          Stepper::stepperP()->enableMotor();
		#if (LC_PRESSURE_PORTS > 1)
          Stepper::stepperR()->enableMotor();
		#endif
		  break;
		}
        case CMD_DISABLE_MOTORS: {
          Stepper::stepperX()->disableMotor();
          Stepper::stepperY()->disableMotor();
          Stepper::stepperZ()->disableMotor();
          Stepper::stepperP()->disableMotor();
		#if (LC_PRESSURE_PORTS > 1)
          Stepper::stepperR()->disableMotor();
		#endif
          break;
		}
        case CMD_ABS_XY: {
          // p1=X, p2=Y, p3=freqHz
          Gantry::instance()->moveTo(cmd.p1,cmd.p2,cmd.p3);
          commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(
              waitForBit(BIT_STEPPER1_DONE) && waitForBit(BIT_STEPPER2_DONE)
          );
          break;
        }
        case CMD_GRIPPER_OPEN: {
// #if (LC_CRASH_TEST_GRIPPER_OPEN_WDT != 0)
//           runGripperOpenWatchdogCrashTest();
// #endif
      	  MX_GRIPPER_Open();
      	  commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(waitForBit(BIT_GRIPPER_DONE));
  		  break;
  		}
        case CMD_GRIPPER_CLOSE: {
      	  MX_GRIPPER_Close();
      	  commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(waitForBit(BIT_GRIPPER_DONE));
  		  break;
  		}
        case CMD_GRIPPER_OFF: {
      	  MX_GRIPPER_ForceOff();
  		  break;
  		}
        case CMD_PRINT: {
          Printer::instance()->pulsePrint();
          break;
        }
        case CMD_REFUEL: {
          Printer::instance()->pulseRefuel();
          break;
        }
        case CMD_DISPENSE: {
          // param p1 = pulse width in microseconds, p2 = rate in Hz
			Printer::instance()->enqueue(cmd.p1, cmd.p2, PulseMode::BOTH, BIT_PRINTING_DONE);
			commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(waitForBit(BIT_PRINTING_DONE));
          break;
        }
        case CMD_DISPENSE_PRINT: {
          // param p1 = pulse width in microseconds, p2 = rate in Hz
			Printer::instance()->enqueue(cmd.p1, cmd.p2, PulseMode::PRINT_ONLY, BIT_PRINTING_DONE);
			commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(waitForBit(BIT_PRINTING_DONE));
          break;
        }
        case CMD_DISPENSE_REFUEL: {
          // param p1 = pulse width in microseconds, p2 = rate in Hz
			Printer::instance()->enqueue(cmd.p1, cmd.p2, PulseMode::REFUEL_ONLY, BIT_PRINTING_DONE);
			commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(waitForBit(BIT_PRINTING_DONE));
          break;
        }
        case CMD_INIT_FLASH: {
          // Starts the flash trigger monitoring task
		#if LC_HAS_IMAGING == 1
            g_flash_init_cmd_count++;
            const bool taskExisted = (_flashTaskHandle != nullptr);
        	if (!_flashTaskHandle) {
        		const BaseType_t taskRc = xTaskCreate(
					_flashTaskEntry,
					"FlashMon",
					512,
					this,
					tskIDLE_PRIORITY+3,     // even higher than Orchestrator
					&_flashTaskHandle
        		);
                if (taskRc != pdPASS || !_flashTaskHandle) {
                    g_flash_init_task_create_fail_count++;
                }
        	}
			if (!_flashAckTmr) {
			_flashAckTmr = xTimerCreate(
				"FlashAck", pdMS_TO_TICKS(kFlashAckMs), pdFALSE, this, _flashAckTimerCb);
                if (!_flashAckTmr) {
                    g_flash_init_timer_create_fail_count++;
                }
			}
			_flashAckLow();
            if (_flashAckTmr) {
              xTimerStop(_flashAckTmr, 0);
            }
            if (_flashTaskHandle && _flashAckTmr && !taskExisted) {
                if (_armFlashSession()) {
                    g_flash_init_ok_count++;
                }
            } else if (_flashTaskHandle && _flashAckTmr && FlashSafety::isSessionArmed(_flashSafety)) {
                MX_FLASH_ArmOutput();
                g_flash_init_ok_count++;
            }
		#endif
          break;
        }
        case CMD_STOP_FLASH: {
		#if LC_HAS_IMAGING == 1
          // Ends the flash trigger monitoring task
            _disarmFlashSession("stop", true);
        	if (_flashTaskHandle) {
        		vTaskDelete(_flashTaskHandle);
        		_flashTaskHandle = nullptr;
        	}
		#endif
          break;
        }
        case CMD_SET_FLASH_DURATION: {
		#if LC_HAS_IMAGING == 1
          const uint16_t safePulseNs = Flash::clampPulseDurationNs(cmd.p1);
          Flash::instance()->setDurationNs(safePulseNs);
		#endif
          break;
        }
        case CMD_SET_FLASH_DELAY: {
		#if LC_HAS_IMAGING == 1
          setFlashDelay(cmd.p1);
		#endif
          break;
        }
        case CMD_SET_IMAGING_DROPLETS: {
		#if LC_HAS_IMAGING == 1
          setImagingDroplets(cmd.p1);
		#endif
          break;
        }
        case CMD_PR_PRINT: {
        	PressureRegulator& reg = PressureRegulator::regP();
        	int32_t  target = (int32_t)cmd.p1u();
        	reg.setTargetSafe(target);
            // ensure we re-wait even if already in band
            xEventGroupClearBits(_doneEvents, BIT_PRESSURE_P_READY);
            if (PressureTargetPolicy::shouldWaitForReadyAfterTargetChange(reg.isActive())) {
              commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(waitForBit(BIT_PRESSURE_P_READY));
            }
        	break;
        }
        case CMD_PR_REFUEL: {
			#if (LC_PRESSURE_PORTS > 1)
        	  PressureRegulator& reg = PressureRegulator::regR();
        	  int32_t  target = (int32_t)cmd.p1u();
			  reg.setTargetSafe(target);
			  xEventGroupClearBits(_doneEvents, BIT_PRESSURE_R_READY);
			  if (PressureTargetPolicy::shouldWaitForReadyAfterTargetChange(reg.isActive())) {
			    commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(waitForBit(BIT_PRESSURE_R_READY));
			  }
			#else
			  // Legacy: single channel → log message
			  Logger::instance()->log("Legacy has no refuel channel");
			#endif
			break;
		}
        case CMD_PR_PRINT_REL: {
			bool  sign   = cmd.p1b();
			int32_t  delta  = (int32_t)cmd.p2u();
			  if (delta == 0) { Logger::instance()->log("[PReg] REL P delta=0\n"); break; }
			PressureRegulator& reg = PressureRegulator::regP();
			reg.setRelativeTargetSafe(sign, delta);
            // ensure we re-wait even if already in band
            xEventGroupClearBits(_doneEvents, BIT_PRESSURE_P_READY);
            if (PressureTargetPolicy::shouldWaitForReadyAfterTargetChange(reg.isActive())) {
              commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(waitForBit(BIT_PRESSURE_P_READY));
            }
			break;
		}
        case CMD_PR_REFUEL_REL: {
			#if (LC_PRESSURE_PORTS > 1)
			bool  sign   = cmd.p1b();
			int32_t  delta  = (int32_t)cmd.p2u();
			  if (delta == 0) { Logger::instance()->log("[PReg] REL R delta=0\n"); break; }
			PressureRegulator& reg = PressureRegulator::regR();
			reg.setRelativeTargetSafe(sign, delta);
			xEventGroupClearBits(_doneEvents, BIT_PRESSURE_R_READY);
			if (PressureTargetPolicy::shouldWaitForReadyAfterTargetChange(reg.isActive())) {
			  commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(waitForBit(BIT_PRESSURE_R_READY));
			}
			#else
			Logger::instance()->log("Legacy has no refuel channel");
			#endif
			break;
		}
        case CMD_SET_PW_PRINT: {
			Printer::instance()->setPrintPulse(cmd.p1);
			break;
		}
        case CMD_SET_PW_REFUEL: {
			Printer::instance()->setRefuelPulse(cmd.p1);
			break;
		}
        case CMD_HOME_PRINT: {
          xEventGroupClearBits(_doneEvents, BIT_HOME_P_DONE);
          startRegHomeAsync(&PressureRegulator::regP(), cmd.p1, cmd.p2, cmd.p3, BIT_HOME_P_DONE);
          commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(waitForBit(BIT_HOME_P_DONE));
          break;
        }
        case CMD_HOME_REFUEL: {
		#if (LC_PRESSURE_PORTS > 1)
		  xEventGroupClearBits(_doneEvents, BIT_HOME_R_DONE);
		  startRegHomeAsync(&PressureRegulator::regR(), cmd.p1, cmd.p2, cmd.p3, BIT_HOME_R_DONE);
		  commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(waitForBit(BIT_HOME_R_DONE));
		#else
		  Logger::instance()->log("Legacy has no refuel channel");
		#endif
		  break;
		}
        case CMD_HOME_XY: {
          // p1 = fastHz, p2 = slowHz, p3 = backoffSteps
          uint32_t fastHz = cmd.p1, slowHz = cmd.p2, backoff = cmd.p3;

          // Clear "home done" bits for these axes
          xEventGroupClearBits(_doneEvents, BIT_HOME_X_DONE | BIT_HOME_Y_DONE);

          // Fire both homing tasks in parallel
          startHomeAsync(Stepper::stepperX(), fastHz, slowHz, backoff, BIT_HOME_X_DONE);
          startHomeAsync(Stepper::stepperY(), fastHz, slowHz, backoff, BIT_HOME_Y_DONE);

          // Wait for both to finish
          commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(
              waitForBits(BIT_HOME_X_DONE | BIT_HOME_Y_DONE)
          );
          break;
        }
        case CMD_HOME_PR_BOTH: {
          // p1 = fastHz, p2 = slowHz, p3 = backoffSteps
          uint32_t fastHz   = cmd.p1;
          uint32_t slowHz   = cmd.p2;
          uint32_t backoff  = cmd.p3;

		#if (LC_PRESSURE_PORTS > 1)
		  xEventGroupClearBits(_doneEvents, BIT_HOME_P_DONE | BIT_HOME_R_DONE);
		  startRegHomeAsync(&PressureRegulator::regP(), fastHz, slowHz, backoff, BIT_HOME_P_DONE);
		  startRegHomeAsync(&PressureRegulator::regR(), fastHz, slowHz, backoff, BIT_HOME_R_DONE);
		  commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(
		      waitForBits(BIT_HOME_P_DONE | BIT_HOME_R_DONE)
		  );
		#else
		  xEventGroupClearBits(_doneEvents, BIT_HOME_P_DONE);
		  startRegHomeAsync(&PressureRegulator::regP(), fastHz, slowHz, backoff, BIT_HOME_P_DONE);
		  commandCompleted = OrchestratorCompletionPolicy::didInterruptibleWaitComplete(waitForBit(BIT_HOME_P_DONE));
		#endif
          break;
        }
        case CMD_P_VALVE_OPEN: {
        	PressureRegulator::regP().openValve();
			break;
		}
        case CMD_P_VALVE_CLOSE: {
        	PressureRegulator::regP().closeValve();
			break;
		}
        case CMD_R_VALVE_OPEN: {
		#if (LC_PRESSURE_PORTS > 1)
		  PressureRegulator::regR().openValve();
		#else
		  Logger::instance()->log("Legacy has no refuel channel");
		#endif
		  break;
		}
        case CMD_R_VALVE_CLOSE: {
		#if (LC_PRESSURE_PORTS > 1)
		  PressureRegulator::regR().closeValve();
		#else
		  Logger::instance()->log("Legacy has no refuel channel");
		#endif
		  break;
		}
        case CMD_P_REG_START: {
			PressureRegulator::regP().start();
			break;
		}
		case CMD_P_REG_STOP: {
			PressureRegulator::regP().pause();
			break;
		}
		case CMD_R_REG_START: {
		#if (LC_PRESSURE_PORTS > 1)
		  PressureRegulator::regR().start();
		#else
		  Logger::instance()->log("Legacy has no refuel channel");
		#endif
		  break;
		}
		case CMD_R_REG_STOP: {
		#if (LC_PRESSURE_PORTS > 1)
		  PressureRegulator::regR().pause();
		#else
		  Logger::instance()->log("Legacy has no refuel channel");
		#endif
		  break;
		}
		case CMD_RESET_PRINT: {
			PressureRegulator::regP().resetSyringe(CRASH_TASK_ORCH);
			break;
		}
		case CMD_RESET_REFUEL: {
		#if (LC_PRESSURE_PORTS > 1)
		  PressureRegulator::regR().resetSyringe(CRASH_TASK_ORCH);
		#else
		  Logger::instance()->log("Legacy has no refuel channel");
		#endif
		  break;
		}
		case CMD_LEDSTRIP_ON: {
			#if LC_HAS_LED_STRIP == 1
			  MX_LEDSTRIP_FadeTo(100,2000);
			#endif
//			MX_LEDSTRIP_FadeTo(100,2000);
			break;
		}
		case CMD_LEDSTRIP_OFF: {
			#if LC_HAS_LED_STRIP == 1
			  MX_LEDSTRIP_FadeTo(0,2000);
			#endif
//			MX_LEDSTRIP_FadeTo(0,500);
			break;
		}
		case CMD_ENABLE_PRINT_PROFILE: {
			  PressureRegulator::regP().setPrintProfile(true);
			#if (LC_PRESSURE_PORTS > 1)
			  PressureRegulator::regR().setPrintProfile(true);
			#endif
			  MX_GRIPPER_SetRefreshPeriodMs(30000);

			  break;
	    } case CMD_DISABLE_PRINT_PROFILE: {
			  PressureRegulator::regP().setPrintProfile(false);
			#if (LC_PRESSURE_PORTS > 1)
			  PressureRegulator::regR().setPrintProfile(false);
			#endif
			  MX_GRIPPER_SetRefreshPeriodMs(120000);
			  break;
			} case CMD_SET_GRIPPER_PARAMS: {
				  // p1 = Refresh, p2 = Pulse duration
				  uint32_t refreshPeriod   = cmd.p1;
				  uint32_t pulseDuration   = cmd.p2;
				  MX_GRIPPER_SetRefreshPeriodMs(refreshPeriod);
				  MX_GRIPPER_SetPulseDurationMs(pulseDuration);
				  break;
			} case CMD_REFUEL_VACUUM_ENTER: {
			#if (LC_PRESSURE_PORTS > 1)
				  const int32_t targetRaw = static_cast<int32_t>(cmd.p1u());
				  const uint32_t prepPositionSteps = cmd.p2u();
				  const uint32_t moveHz = cmd.p3u();
				  bool homeWaitInterrupted = false;
				  if (!enterRefuelVacuumModeWithAsyncHome(
				          targetRaw,
				          prepPositionSteps,
				          moveHz,
				          &homeWaitInterrupted)) {
				    Logger::instance()->log("[PReg] Refuel vacuum enter failed\r\n");
				    if (homeWaitInterrupted) {
				      commandCompleted = false;
				    }
				  }
			#else
				  Logger::instance()->log("Legacy has no refuel channel");
			#endif
				  break;
			} case CMD_REFUEL_VACUUM_SET_TARGET: {
			#if (LC_PRESSURE_PORTS > 1)
				  const int32_t targetRaw = static_cast<int32_t>(cmd.p1u());
				  if (!PressureRegulator::regR().setVacuumTargetSafe(targetRaw)) {
				    Logger::instance()->log("[PReg] Refuel vacuum target rejected\r\n");
				  }
			#else
				  Logger::instance()->log("Legacy has no refuel channel");
			#endif
				  break;
			} case CMD_REFUEL_VACUUM_EXIT: {
			#if (LC_PRESSURE_PORTS > 1)
				  const int32_t restoreRaw = static_cast<int32_t>(cmd.p1u());
				  if (!PressureRegulator::regR().exitVacuumMode(
				          restoreRaw,
				          CRASH_TASK_ORCH)) {
				    Logger::instance()->log("[PReg] Refuel vacuum exit failed\r\n");
				  }
			#else
				  Logger::instance()->log("Legacy has no refuel channel");
			#endif
				  break;
			} case CMD_SET_REG_RECOVERY_PROFILE: {
				  const uint8_t rawChannel = static_cast<uint8_t>(cmd.p1u() & 0xFFu);
				  if ((rawChannel == RegProfile::kChannelRefuel) &&
				      (regulatorForRegProfileChannel(rawChannel) == nullptr)) {
				    logRegProfileNoChannel("set_recovery", rawChannel);
				    break;
				  }
				  RegProfile::RecoveryStaging& staging =
				      s_regProfileRecoveryStaging[(rawChannel == RegProfile::kChannelRefuel) ? 1u : 0u];
				  const auto result = RegProfile::applyRecoveryChunk(
				      staging,
				      cmd.p1u(),
				      cmd.p2u(),
				      cmd.p3u());
				  if (result.status != RegProfile::Status::Ok) {
				    logRegProfileReject("set_recovery", result.status);
				    break;
				  }
				  if (!result.committed) {
				    break;
				  }
				  PressureRegulator* reg = regulatorForRegProfileChannel(result.channel);
				  if (reg == nullptr) {
				    logRegProfileNoChannel("set_recovery", result.channel);
				    break;
				  }
				  captureRegProfileBaselineIfNeeded();
				  reg->applyRuntimeRecoveryConfig(toRuntimeRecovery(result.config));
				  Logger::instance()->log(
				      "[RegProfile] recovery applied channel=%u\r\n",
				      static_cast<unsigned>(result.channel));
				  break;
			} case CMD_SET_REG_SLEW_PROFILE: {
				  const auto result = RegProfile::decodeSlew(cmd.p1u(), cmd.p2u(), cmd.p3u());
				  if (result.status != RegProfile::Status::Ok) {
				    logRegProfileReject("set_slew", result.status);
				    break;
				  }
				  PressureRegulator* reg = regulatorForRegProfileChannel(result.channel);
				  if (reg == nullptr) {
				    logRegProfileNoChannel("set_slew", result.channel);
				    break;
				  }
				  captureRegProfileBaselineIfNeeded();
				  reg->applyRuntimeSlewConfig(toRuntimeSlew(result.config));
				  Logger::instance()->log(
				      "[RegProfile] slew applied channel=%u\r\n",
				      static_cast<unsigned>(result.channel));
				  break;
			} case CMD_SET_REG_READY_PROFILE: {
				  const auto result = RegProfile::decodeReady(cmd.p1u(), cmd.p2u(), cmd.p3u());
				  if (result.status != RegProfile::Status::Ok) {
				    logRegProfileReject("set_ready", result.status);
				    break;
				  }
				  PressureRegulator* reg = regulatorForRegProfileChannel(result.channel);
				  if (reg == nullptr) {
				    logRegProfileNoChannel("set_ready", result.channel);
				    break;
				  }
				  captureRegProfileBaselineIfNeeded();
				  reg->applyRuntimeReadyConfig(toRuntimeReady(result.config));
				  Logger::instance()->log(
				      "[RegProfile] ready applied channel=%u\r\n",
				      static_cast<unsigned>(result.channel));
				  break;
			} case CMD_RESTORE_REG_PROFILE: {
				  const auto request = RegProfile::decodeRestore(cmd.p1u(), cmd.p2u(), cmd.p3u());
				  if (request.status != RegProfile::Status::Ok) {
				    logRegProfileReject("restore", request.status);
				    break;
				  }
				  if (request.restoreRefuel &&
				      (regulatorForRegProfileChannel(RegProfile::kChannelRefuel) == nullptr)) {
				    logRegProfileNoChannel("restore", RegProfile::kChannelRefuel);
				    break;
				  }
				  if (request.source == RegProfile::RestoreSource::Defaults) {
				    if (request.restorePrint) {
				      PressureRegulator::regP().restoreDefaultRuntimeConfig();
				    }
				#if (LC_PRESSURE_PORTS > 1)
				    if (request.restoreRefuel) {
				      PressureRegulator::regR().restoreDefaultRuntimeConfig();
				    }
				#endif
				    resetRegProfileSessionState();
				    Logger::instance()->log("[RegProfile] defaults restored\r\n");
				    break;
				  }
				  if (s_regProfileBaselineCaptured) {
				    if (request.restorePrint) {
				      PressureRegulator::regP().restoreRuntimeConfigSnapshot(s_regProfileBaselinePrint);
				    }
				#if (LC_PRESSURE_PORTS > 1)
				    if (request.restoreRefuel) {
				      PressureRegulator::regR().restoreRuntimeConfigSnapshot(s_regProfileBaselineRefuel);
				    }
				#endif
				    Logger::instance()->log("[RegProfile] baseline restored\r\n");
				  } else {
				    Logger::instance()->log("[RegProfile] restore baseline no-op\r\n");
				  }
				  resetRegProfileSessionState();
				  break;
			} case CMD_QUERY_REG_PROFILE: {
				  Logger::instance()->log("[RegProfile] query reserved\r\n");
				  break;
			} case CMD_SELFTEST_START: {
				  Comm* comm = Comm::instance();
				  if (!comm || !comm->handle()) {
				    break;
				  }
				  const uint8_t outSeq8 = cmd.seq8;
				  if (cmd.hasSeq32) {
				      comm->sendAckWithSeq32(
				          CMD_QUEUE_ACK,
				          outSeq8,
				          cmd.seq32,
				          true,
				          true,
				          ACK_RESULT_ACCEPTED,
				          false,
				          0u,
				          false,
				          0u
				      );
				  }

				  comm->setStatusPaused(true);
				  _selfTestAbortRequested = false;

				  DiagnosticsRequest request{};
				  request.seq8 = outSeq8;
				  request.runId = SelfTestCommandPolicy::resolveRunId(
				      cmd.hasRunId,
				      cmd.runId,
				      cmd.hasSeq32,
				      cmd.seq32,
				      _currentCmdNum
				  );
				  request.timeoutMs = SelfTestCommandPolicy::resolveTimeoutMs(cmd.hasTimeoutMs, cmd.timeoutMs);
				  request.fullProfile = (cmd.p1Len > 0u) && (cmd.p1u() == 1u);
				  request.runPressureDiagnostics = (cmd.p2Len > 0u) && (cmd.p2u() != 0u);
				  request.exportPressureTrace = request.runPressureDiagnostics;
				  request.selectedPressureTraceTest = (cmd.p3Len >= 2u) ? static_cast<uint16_t>(cmd.p3u() & 0xFFFFu) : 0u;
				  request.selectedDiagnosticId = request.selectedPressureTraceTest;

				  (void)DiagnosticsRunner::runSelfTest(*this, request);
				  _selfTestAbortRequested = false;
				  break;
								} case CMD_WAIT: {
					  // p1 = wait time (ms)
					  const auto intent = OrchestratorDecode::decodeIntent(
					      {static_cast<uint8_t>(cmd.cmd), cmd.p1u(), cmd.p2u(), cmd.p3u()});
					  uint32_t ms = intent.waitMs;
                            if (ms == 0) {
                              break; // immediate completion
                            }

                    _waitRemainingTicks = msToAtLeast1Tick(ms);

                    TickType_t rem = _waitRemainingTicks;
                    bool completed = pauseAwareDelayTicks(rem);
                    _waitRemainingTicks = rem;
                    commandCompleted = OrchestratorCompletionPolicy::didPauseAwareDelayComplete(
                        completed,
                        static_cast<uint32_t>(_waitRemainingTicks)
                    );
                    break;
                  }
        default:
          // unknown—ignore
      	HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);
          break;
      }
  if (!commandCompleted) {
      return;
  }
  OrchestratorCompletionPolicy::retireCurrentCommand(_currentCmdNum, _lastExecutedCmdNum, _lastRetiredCmdNum);
  }

void Orchestrator::performShutdown(uint8_t byeSeq8, uint32_t byeSeq32, bool have32)
{
//  Logger::instance()->log("Shutdown start\r\n");
  Watchdog_CheckIn(CRASH_TASK_ORCH);

  _clearing = true;

  // 1) Stop anything active
  pauseCurrent();             // pause gantry, printer; clears bits
  cancelCurrent();            // cancel active motion/dispense

  // 2) Stop background tasks/services
  _disarmFlashSession("shutdown", true);
  if (_flashTaskHandle) {
    vTaskDelete(_flashTaskHandle);
    _flashTaskHandle = nullptr;
  }
//
//  // 3) Pressure regulators and valves safe
  PressureRegulator::regP().pause();
  PressureRegulator::regP().openValve();

#if (LC_PRESSURE_PORTS > 1)
  PressureRegulator::regR().pause();
  PressureRegulator::regR().openValve();
#endif

  // 4) Gripper off
  MX_GRIPPER_ForceOff();
//
//  // 5) Disable motors
  Stepper::stepperX()->disableMotor();
  Stepper::stepperY()->disableMotor();
  Stepper::stepperZ()->disableMotor();
  Stepper::stepperP()->disableMotor();
#if (LC_PRESSURE_PORTS > 1)
  Stepper::stepperR()->disableMotor();
#endif
  // 6) Drain queue (no xQueueReset)
  if (_cmdQueue) {
    Command dump;
    while (xQueueReceive(_cmdQueue, &dump, 0) == pdTRUE) { /* discard */ }
  }

  retireAcceptedPendingCommands();
  _pauseAfterSeq32 = 0u;
  _pauseWatermarkReached = false;
  xEventGroupClearBits(_doneEvents,
    BIT_LED_DONE|BIT_STEPPER1_DONE|BIT_STEPPER2_DONE|BIT_STEPPER3_DONE|BIT_PRINTING_DONE|BIT_FLASH_PRINT_DONE|BIT_FLASH_DONE);

  // 7) UI off (asynchronous; don’t block)
//  MX_LEDSTRIP_FadeTo(0, 500);
#if LC_HAS_LED_STRIP
  MX_LEDSTRIP_FadeTo(0,500);
#endif

  // small settle delay for hardware
  Watchdog_CheckIn(CRASH_TASK_ORCH);
  vTaskDelay(pdMS_TO_TICKS(500));
  Watchdog_CheckIn(CRASH_TASK_ORCH);

  PressureRegulator::regP().closeValve();
#if (LC_PRESSURE_PORTS > 1)
  PressureRegulator::regR().closeValve();
#endif//

  _paused = true;     // remain paused until next HELLO
  _clearing = false;

  Logger::instance()->log("Shutdown done\r\n");

//   8) Tell host we’re safe. Status is paused, but command bytes still go out.
//  Comm::instance()->sendCommandByte(CMD_BYE_DONE, byeSeq);
  Watchdog_CheckIn(CRASH_TASK_ORCH);
  Comm::instance()->sendAckWithSeq32(CMD_BYE_DONE, byeSeq8, byeSeq32, have32);
}

void Orchestrator::_logHomeTaskStackUsage(const char* taskName,
                                          uint16_t allocWords,
                                          uint16_t hwmWords)
{
  Logger* logger = Logger::instance();
  if (logger == nullptr) {
    return;
  }

  const char* safeTaskName = (taskName != nullptr) ? taskName : "unknown";
  logger->log("[Stack] task=%s alloc_w=%u hwm_w=%u\r\n",
              safeTaskName,
              static_cast<unsigned>(allocWords),
              static_cast<unsigned>(hwmWords));
  if ((hwmWords != 0u) && (hwmWords < HOME_STACK_WARN_WORDS)) {
    logger->log("[StackWarn] task=%s alloc_w=%u hwm_w=%u\r\n",
                safeTaskName,
                static_cast<unsigned>(allocWords),
                static_cast<unsigned>(hwmWords));
  }
}

// ---------- Async homing task ----------
void Orchestrator::_homeTaskEntry(void* ctx)
{
  auto* a = static_cast<HomeTaskArgs*>(ctx);
  Orchestrator* orch = instance();
  const char* taskName = "HomeAx";
  volatile uint16_t* hwmSlot = nullptr;
  if ((orch != nullptr) && (a != nullptr)) {
    if (a->stepper == Stepper::stepperX()) {
      taskName = "HomeX";
      hwmSlot = &orch->_homeXStackHwmWords;
    } else if (a->stepper == Stepper::stepperY()) {
      taskName = "HomeY";
      hwmSlot = &orch->_homeYStackHwmWords;
    } else if (a->stepper == Stepper::stepperZ()) {
      taskName = "HomeZ";
      hwmSlot = &orch->_homeZStackHwmWords;
    }
  }

  a->stepper->home(a->fastHz, a->slowHz, a->backoffSteps);

  uint16_t hwmWords = 0u;
#if (INCLUDE_uxTaskGetStackHighWaterMark == 1)
  const UBaseType_t hwm = uxTaskGetStackHighWaterMark(nullptr);
  hwmWords = (hwm > 0xFFFFu) ? 0xFFFFu : static_cast<uint16_t>(hwm);
#endif
  if (hwmSlot != nullptr) {
    *hwmSlot = hwmWords;
  }
  _logHomeTaskStackUsage(taskName, HOME_STACK_WORDS, hwmWords);

  xEventGroupSetBits(Orchestrator::getDoneEvents(), a->doneBit);

  // Clear the handle for this bank so a new home can be started later
  if (orch != nullptr) {
    if (a->stepper == Stepper::stepperX()) orch->_taskHomeX = nullptr;
    else if (a->stepper == Stepper::stepperY()) orch->_taskHomeY = nullptr;
    else if (a->stepper == Stepper::stepperZ()) orch->_taskHomeZ = nullptr;
  }

  vTaskDelete(nullptr);
}

void Orchestrator::startHomeAsync(Stepper* s,
                                  uint32_t fastHz,
                                  uint32_t slowHz,
                                  uint32_t backoffSteps,
                                  EventBits_t doneBit)
{
  // Choose a static bank based on which axis we were asked to home
  StaticTask_t* tcb   = nullptr;
  StackType_t*  stack = nullptr;
  TaskHandle_t* handle= nullptr;
  HomeTaskArgs* args  = nullptr;
  const char*   name  = "HomeAx";

  if (s == Stepper::stepperX()) {
    tcb = &_tcbHomeX; stack = _stackHomeX; handle = &_taskHomeX; args = &_argsHomeX; name = "HomeX";
  } else if (s == Stepper::stepperY()) {
    tcb = &_tcbHomeY; stack = _stackHomeY; handle = &_taskHomeY; args = &_argsHomeY; name = "HomeY";
  } else if (s == Stepper::stepperZ()) {
    tcb = &_tcbHomeZ; stack = _stackHomeZ; handle = &_taskHomeZ; args = &_argsHomeZ; name = "HomeZ";
  } else {
    Logger::instance()->log("[Home] No static bank for this axis; refusing blocking fallback\r\n");
    xEventGroupSetBits(_doneEvents, doneBit);
    return;
  }

  if (*handle != nullptr) {
    Logger::instance()->log("[Home] %s already running; ignoring duplicate request\r\n", name);
    return;
  }

  // Populate the (persistent) args
  args->stepper      = s;
  args->fastHz       = fastHz;
  args->slowHz       = slowHz;
  args->backoffSteps = backoffSteps;
  args->doneBit      = doneBit;

  // Create without touching the heap
  *handle = xTaskCreateStatic(
      _homeTaskEntry,
      name,
      HOME_STACK_WORDS,
      (void*)args,
      tskIDLE_PRIORITY + 3,
      stack,
      tcb);

  if (!*handle) {
    Logger::instance()->log("[Home] xTaskCreateStatic failed for %s\r\n", name);
    xEventGroupSetBits(_doneEvents, doneBit);
  }
}

// ---------------- Regulator async homing ----------------

void Orchestrator::_regHomeTaskEntry(void* ctx)
{
  auto* a = static_cast<RegHomeTaskArgs*>(ctx);
  Orchestrator* orch = instance();
  const char* taskName = "HomePR";
  volatile uint16_t* hwmSlot = nullptr;
  if ((orch != nullptr) && (a != nullptr)) {
    if (a->reg == &PressureRegulator::regP()) {
      taskName = "HomePR_P";
      hwmSlot = &orch->_homePStackHwmWords;
    }
#if (LC_PRESSURE_PORTS > 1)
    else if (a->reg == &PressureRegulator::regR()) {
      taskName = "HomePR_R";
      hwmSlot = &orch->_homeRStackHwmWords;
    }
#endif
  }

  a->reg->homeWithValve(a->fastHz, a->slowHz, a->backoffSteps);

  uint16_t hwmWords = 0u;
#if (INCLUDE_uxTaskGetStackHighWaterMark == 1)
  const UBaseType_t hwm = uxTaskGetStackHighWaterMark(nullptr);
  hwmWords = (hwm > 0xFFFFu) ? 0xFFFFu : static_cast<uint16_t>(hwm);
#endif
  if (hwmSlot != nullptr) {
    *hwmSlot = hwmWords;
  }
  _logHomeTaskStackUsage(taskName, REG_HOME_STACK_WORDS, hwmWords);

  xEventGroupSetBits(Orchestrator::getDoneEvents(), a->doneBit);

  if ((orch != nullptr) && (a->reg == &PressureRegulator::regP())) {
    orch->_taskHomeP = nullptr;
  }
#if (LC_PRESSURE_PORTS > 1)
  else if ((orch != nullptr) && (a->reg == &PressureRegulator::regR())) {
    orch->_taskHomeR = nullptr;
  }
#endif
  vTaskDelete(nullptr);
}

void Orchestrator::startRegHomeAsync(PressureRegulator* r,
                                     uint32_t fastHz,
                                     uint32_t slowHz,
                                     uint32_t backoffSteps,
                                     EventBits_t doneBit)
{
  StaticTask_t*    tcb    = nullptr;
  StackType_t*     stack  = nullptr;
  TaskHandle_t*    handle = nullptr;
  RegHomeTaskArgs* args   = nullptr;
  const char*      name   = "HomePR";

  if (r == &PressureRegulator::regP()) {
    tcb = &_tcbHomeP; stack = _stackHomeP; handle = &_taskHomeP; args = &_argsHomeP; name = "HomePR_P";
  }

#if (LC_PRESSURE_PORTS > 1)
  else if (r == &PressureRegulator::regR()) {
    tcb = &_tcbHomeR; stack = _stackHomeR; handle = &_taskHomeR; args = &_argsHomeR; name = "HomePR_R";
  }
#endif

  else {
    Logger::instance()->log("[HomePR] No static bank for this regulator; refusing blocking fallback\r\n");
    xEventGroupSetBits(_doneEvents, doneBit);
    return;
  }

  if (*handle != nullptr) {
    Logger::instance()->log("[HomePR] %s already running; ignoring duplicate request\r\n", name);
    return;
  }

  args->reg          = r;
  args->fastHz       = fastHz;
  args->slowHz       = slowHz;
  args->backoffSteps = backoffSteps;
  args->doneBit      = doneBit;

  *handle = xTaskCreateStatic(
      _regHomeTaskEntry,
      name,
      REG_HOME_STACK_WORDS,
      (void*)args,
      tskIDLE_PRIORITY + 3,
      stack,
      tcb);

  if (!*handle) {
    Logger::instance()->log("[HomePR] xTaskCreateStatic failed for %s\r\n", name);
    xEventGroupSetBits(_doneEvents, doneBit);
  }
}

bool Orchestrator::enterRefuelVacuumModeWithAsyncHome(int32_t targetRaw,
                                                      uint32_t prepPositionSteps,
                                                      uint32_t moveHz,
                                                      bool* homeWaitInterrupted)
{
  if (homeWaitInterrupted != nullptr) {
    *homeWaitInterrupted = false;
  }

#if (LC_PRESSURE_PORTS > 1)
  if (_taskHomeR != nullptr) {
    Logger::instance()->log("[PReg] Refuel vacuum enter refused: async home already running\r\n");
    return false;
  }

  xEventGroupClearBits(_doneEvents, BIT_HOME_R_DONE);
  startRegHomeAsync(
      &PressureRegulator::regR(),
      PressureRegulator::kHomeFastHzDefault,
      PressureRegulator::kHomeSlowHzDefault,
      PressureRegulator::kHomeBackoffDefault,
      BIT_HOME_R_DONE);

  const bool homeDone = waitForBit(BIT_HOME_R_DONE);
  if (!homeDone) {
    if (homeWaitInterrupted != nullptr) {
      *homeWaitInterrupted = true;
    }
    Logger::instance()->log("[PReg] Refuel vacuum enter interrupted during async home\r\n");
    return false;
  }

  return PressureRegulator::regR().enterVacuumModeAfterHome(
      targetRaw,
      prepPositionSteps,
      moveHz,
      CRASH_TASK_ORCH);
#else
  Logger::instance()->log("Legacy has no refuel channel");
  return false;
#endif
}


//===========================================================================//
// flash-monitor task
//===========================================================================//
#if LC_HAS_IMAGING == 1
extern TIM_HandleTypeDef htim12;		// Used to time the flash delay accurately down to the microsecond


void Orchestrator::setFlashDelay(uint32_t flashDelay) {
	_flashDelay = flashDelay;
}

bool Orchestrator::_isFlashTriggerHigh() const {
  return HAL_GPIO_ReadPin(_trigPort, _trigPin) == GPIO_PIN_SET;
}

void Orchestrator::_clearFlashTaskNotifications() {
  if (!_flashTaskHandle) {
    return;
  }
  (void)xTaskNotifyStateClear(_flashTaskHandle);
}

void Orchestrator::_logFlashArmed() {
  Logger::instance()->log("FLASH_ARMED\r\n");
}

void Orchestrator::_logFlashDisarmed(const char* reason) {
  Logger::instance()->log("FLASH_DISARMED reason=%s\r\n", flashDisarmReasonToken(reason));
}

void Orchestrator::_logFlashFault(FlashSafety::FaultReason reason) {
  Logger::instance()->log("FLASH_FAULT reason=%s\r\n", FlashSafety::faultReasonToken(reason));
}

void Orchestrator::_latchFlashFault(FlashSafety::FaultReason reason, bool deferLog) {
  _flashSafety.sessionArmed = false;
  _flashSafety.awaitingRelease = false;
  _flashSafety.faultLatched = true;
  _flashSafety.faultReason = reason;
  MX_FLASH_SetSafeIdle();
  if (deferLog) {
    _flashFaultLogPending = true;
    return;
  }
  _logFlashFault(reason);
  _logFlashDisarmed("fault");
}

void Orchestrator::_emitPendingFlashFaultLogs() {
  if (!_flashFaultLogPending) {
    return;
  }
  _flashFaultLogPending = false;
  if (_flashSafety.faultLatched) {
    MX_FLASH_SetSafeIdle();
    _logFlashFault(_flashSafety.faultReason);
    _logFlashDisarmed("fault");
  }
}

bool Orchestrator::_armFlashSession() {
  _flashAckLow();
  if (_flashAckTmr) {
    xTimerStop(_flashAckTmr, 0);
  }
  _flashFaultLogPending = false;
  _clearFlashTaskNotifications();
  const auto armAction = FlashSafety::arm(_flashSafety, _isFlashTriggerHigh());
  if (armAction == FlashSafety::ArmAction::FaultLatched) {
    MX_FLASH_SetSafeIdle();
    _logFlashFault(_flashSafety.faultReason);
    _logFlashDisarmed("fault");
    return false;
  }
  MX_FLASH_ArmOutput();
  _logFlashArmed();
  return true;
}

void Orchestrator::_disarmFlashSession(const char* reason, bool clearFault) {
  const bool hadState = FlashSafety::isSessionArmed(_flashSafety) ||
                        FlashSafety::isFaultLatched(_flashSafety) ||
                        _flashSafety.awaitingRelease;
  _flashAckLow();
  if (_flashAckTmr) {
    xTimerStop(_flashAckTmr, 0);
  }
  _clearFlashTaskNotifications();
  _flashFaultLogPending = false;
  MX_FLASH_SetSafeIdle();
  if (hadState) {
    _logFlashDisarmed(reason);
  }
  _flashSafety.sessionArmed = false;
  _flashSafety.awaitingRelease = false;
  if (clearFault) {
    _flashSafety.faultLatched = false;
    _flashSafety.faultReason = FlashSafety::FaultReason::None;
  }
}


// schedule a one-shot callback in N microseconds:
void Orchestrator::scheduleFlashIn() {
  // clear any pending flags
  __HAL_TIM_CLEAR_FLAG(&htim12, TIM_FLAG_CC1|TIM_FLAG_UPDATE);

  // Reset the counter so the delay is "from now"
  __HAL_TIM_SET_COUNTER(&htim12, 0);

  // set compare value = desired delay in µs
  __HAL_TIM_SET_COMPARE(&htim12, TIM_CHANNEL_1, _flashDelay);

  // ARR must be >= CCR+1 so the compare can happen:
  __HAL_TIM_SET_AUTORELOAD(&htim12, _flashDelay + 1);

  // start output-compare with interrupt
  HAL_TIM_OC_Start_IT(&htim12, TIM_CHANNEL_1);
}

void Orchestrator::flashNotifyFromISR(uint16_t GPIO_Pin) {
	if (_instance && GPIO_Pin == _instance->_trigPin && _instance->_flashTaskHandle) {
		g_exti8_count++;
	    const bool lineHigh = _instance->_isFlashTriggerHigh();
	    const auto triggerAction = FlashSafety::onTrigger(_instance->_flashSafety, lineHigh);
	    if (triggerAction == FlashSafety::TriggerAction::IgnoredDisarmed ||
	        triggerAction == FlashSafety::TriggerAction::IgnoredFaultLatched ||
	        triggerAction == FlashSafety::TriggerAction::IgnoredBusy ||
	        triggerAction == FlashSafety::TriggerAction::IgnoredLineLow) {
	      return;
	    }

		HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);
	    BaseType_t woke = pdFALSE;
	    // Use eSetBits so multiple notifies coalesce into a single event
	    xTaskNotifyFromISR(_instance->_flashTaskHandle, 0x1, eSetBits, &woke);
	    portYIELD_FROM_ISR(woke);

//		BaseType_t woke = pdFALSE;
//		// just poke the FlashTask
//		xTaskNotifyFromISR(
//		  _instance->_flashTaskHandle,
//		  0,            // notification value (unused)
////		      eNoAction,
//		  eIncrement,
//		  &woke
//		);
//		portYIELD_FROM_ISR(woke);
	  }
	}

void Orchestrator::_flashTaskEntry(void* pv) {
  static_cast<Orchestrator*>(pv)->_flashTaskLoop();
}

void Orchestrator::_flashTaskLoop() {
  for (;;) {
    // wait for the EXTI ISR to notify us
//    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
//    xTaskNotifyStateClear(NULL);

	// Wait for a (coalesced) notification
	uint32_t note = 0;
	xTaskNotifyWait(/*ulBitsToClearOnEntry*/0, /*ulBitsToClearOnExit*/0xFFFFFFFFu, &note, portMAX_DELAY);
    g_flash_task_wake_count++;
    _emitPendingFlashFaultLogs();
    if (!FlashSafety::isSessionArmed(_flashSafety) || FlashSafety::isFaultLatched(_flashSafety)) {
      continue;
    }


    _flashInProgress = true;
    xEventGroupClearBits(_doneEvents, BIT_FLASH_DONE);

    const bool waitForPrintCompletion = (_imagingDroplets != 0u);
    if (!waitForPrintCompletion) {
    	Orchestrator::instance()->scheduleFlashIn();
    }
    else {
        Printer::instance()->setFlashOnLast(true);
        xEventGroupClearBits(_doneEvents, BIT_FLASH_PRINT_DONE);
        Printer::instance()->enqueue(
            _imagingDroplets,
            _imagingFreq,
            PulseMode::BOTH,
            BIT_FLASH_PRINT_DONE);
    }

//    Logger::instance()->log("-FLASH COMP-\r\n");

    // then don’t proceed until the Pi’s line goes back low
    for (;;) {
      const auto releaseAction = FlashSafety::onReleasePoll(_flashSafety, _isFlashTriggerHigh());
      if (releaseAction == FlashSafety::ReleaseAction::Released) {
        break;
      }
      vTaskDelay(pdMS_TO_TICKS(1));
    }

    _emitPendingFlashFaultLogs();

    if (waitForPrintCompletion) {
      (void)waitForBit(BIT_FLASH_PRINT_DONE);
    }

    _clearFlashTaskNotifications();

    _flashInProgress = false;
    g_flash_task_done_count++;
    xEventGroupSetBits(_doneEvents, BIT_FLASH_DONE);
  }
}

void Orchestrator::_flashAckHigh() {
  HAL_GPIO_WritePin(_flashAckPort, _flashAckPin, GPIO_PIN_SET);
}

void Orchestrator::_flashAckLow() {
  HAL_GPIO_WritePin(_flashAckPort, _flashAckPin, GPIO_PIN_RESET);
}

void Orchestrator::_flashAckTimerCb(TimerHandle_t tmr) {
  auto* self = static_cast<Orchestrator*>(pvTimerGetTimerID(tmr));
  self->_flashAckLow();
}

extern "C" void MX_FLASH_TriggerCallback(uint16_t GPIO_Pin) {
//	HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);
	Orchestrator::instance()->flashNotifyFromISR(GPIO_Pin);
}

extern "C" void MX_FLASH_Acknowledge() {
//	HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);
    // Immediately raise the "flash fired" GPIO so the Pi can edge-trigger
    auto* orch = Orchestrator::instance();
    orch->_flashAckHigh();
    orch->noteFlashAckFromISR();

    // Drop it low in ~2 ms via a FreeRTOS software timer
    BaseType_t hpw = pdFALSE;
    xTimerStartFromISR(orch->_flashAckTmr, &hpw);
    portYIELD_FROM_ISR(hpw);
}
#else

// Safe stubs so the project links even if callbacks remain referenced somewhere.
extern "C" void MX_FLASH_TriggerCallback(uint16_t GPIO_Pin) { (void)GPIO_Pin; }
extern "C" void MX_FLASH_Acknowledge() {}

//void Orchestrator::scheduleFlashIn() {}
//void Orchestrator::flashNotifyFromISR(uint16_t GPIO_Pin) { (void)GPIO_Pin; }

#endif
