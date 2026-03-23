/*
 * Orchestrator.cpp
 *
 *  Created on: Jun 19, 2025
 *      Author: conar
 */
#include "BoardConfig.h"
#include "Orchestrator.h"
#include "OrchestratorDecode.h"
#include "LEDController.h"    // your LED queue + done-event
#include "Stepper.h"          // MX_STEPPERx_Move(), MX_STEPPERx_Stop(), MX_STEPPERx_IsBusy()
#include "Gripper.h"
#include "Printer.h"
#include "PressureRegulator.h"
#include "PressureRegulatorMath.h"
#include "PressureTargetPolicy.h"
#include "PressureSensor.h"
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
    _taskHandle(nullptr),
    _doneEvents(nullptr)
{
	_instance = this;
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

BaseType_t Orchestrator::enqueueFromISR(const Command& cmd, BaseType_t* pxHigherPriorityTaskWoken) {
	// special commands — handle immediately

	    switch (cmd.cmd) {
			case CMD_HELLO: {
			  CrashLog_SetBootStage(CRASH_BOOT_STAGE_HELLO_RX);
			  // Reset any stale state and request HELLO_ACK
			  _paused = false; _pauseRequested = false;
		  _seqEpoch=0; _lastSeq8=0; _currentCmdNum=0; _lastExecutedCmdNum=0;
		  _resumeRequested = false; _clearRequested = false;
		  _inFlight = cmd;                 // capture seq/cmd for ACK
		  _acknowledgeRequested = true;
	      if (pxHigherPriorityTaskWoken) *pxHigherPriorityTaskWoken = pdTRUE; // wake task to send ACK

		  return pdFALSE;
		}
		case CMD_GOODBYE: {
		  _inFlight = cmd;                 // capture seq/cmd for ACK
		  _paused = true;
		  _pauseRequested = true;
		  _shutdownRequested = true;
//		  _clearRequested = true;
		  _acknowledgeRequested = true;
		  return pdFALSE;
		}
        case CMD_PAUSE:
		  // request a pause
		  _paused = true;
		  _pauseRequested = true;
		  return pdFALSE;           // don't put into the queue
		case CMD_RESUME:
		  _resumeRequested = true;
		  return pdFALSE;
	      case CMD_CLEAR: {
//    	  xQueueReset(_cmdQueue);
			  _inFlight = cmd;                 // capture seq/cmd for ACK
	    	  _clearRequested = true;
	    	  _acknowledgeRequested = true;
	        // inject these at head so they fire immediately
	        return pdFALSE;
	      }
	      case CMD_SELFTEST_ABORT: {
	        _selfTestAbortRequested = true;
	        return pdFALSE;
	      }
	      default: {
	    	  return xQueueSendFromISR(_cmdQueue, &cmd, pxHigherPriorityTaskWoken);
	      }
	    }
}


void Orchestrator::pauseCurrent() {
  Logger::instance()->log("pauseCurrent\r\n");
  Gantry::instance()->pauseXYZMotors();
  Printer::instance()->pauseDispense();
//  PressureRegulator::regP().pause();
//  PressureRegulator::regR().pause();
  xEventGroupClearBits(_doneEvents,
      BIT_LED_DONE|BIT_STEPPER1_DONE|BIT_STEPPER2_DONE|
      BIT_STEPPER3_DONE|BIT_PRINTING_DONE|BIT_GRIPPER_DONE);
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
    // Interrupt conditions (match your waitForBit() intent)
    if (_paused || _pauseRequested || _clearRequested || _shutdownRequested) {
      return false;
    }

    TickType_t step = remainingTicks;
    if (step > quantum) step = quantum;

    vTaskDelay(step);

    if (remainingTicks >= step) remainingTicks -= step;
    else remainingTicks = 0;
  }
  return true;
}

bool Orchestrator::waitForBit(EventBits_t bit) {
  const TickType_t ticks = pdMS_TO_TICKS(50);
  while (true) {
    Watchdog_CheckIn(CRASH_TASK_ORCH);
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
		// If a PAUSE came in, stop waiting immediately.
		if (_paused) {
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

void Orchestrator::_run() {
  Watchdog_EnableTask(CRASH_TASK_ORCH);
  maybeSendResetReport(0u, 0u);
  for (;;) {
	  Watchdog_CheckIn(CRASH_TASK_ORCH);
		  if (_acknowledgeRequested) {
		  const uint8_t seq8  = _inFlight.seq8;
		  const uint32_t seq32 = _inFlight.hasSeq32 ? _inFlight.seq32 : _currentCmdNum;
		  const bool have32 = _inFlight.hasSeq32;
//          // Reply with appropriate ACK using the same sequence number
//          uint8_t seq = _inFlight.seq;
	          switch (_inFlight.cmd) {
	            case CMD_HELLO:{
//            	Comm::instance()->sendCommandByte(CMD_HELLO_ACK, seq);
	            	Comm::instance()->sendAckWithSeq32(CMD_HELLO_ACK, seq8, seq32, have32);
	            	CrashLog_SetBootStage(CRASH_BOOT_STAGE_HELLO_ACK);
	            	Watchdog_Arm();
	            	CrashLog_LogBootSummary();
	            	maybeSendResetReport(seq8, seq32);
	                // Then resume status & cosmetic stuff
	                Comm::instance()->setStatusPaused(false);
				#if LC_HAS_LED_STRIP == 1
				  MX_LEDSTRIP_FadeTo(100,500);
				#endif
            	break;
            }
            case CMD_GOODBYE: {
            	Comm::instance()->setStatusPaused(true);
//            	Comm::instance()->sendCommandByte(CMD_BYE_ACK, seq);
            	Comm::instance()->sendAckWithSeq32(CMD_BYE_ACK, seq8, seq32, have32);
            	// Start next session clean
            	Comm::instance()->resetReceiveState();
//            	MX_LEDSTRIP_FadeTo(0,500);
				#if LC_HAS_LED_STRIP == 1
				  MX_LEDSTRIP_FadeTo(0,500);
				#endif
            	break;
            }
            case CMD_CLEAR:{
            	Comm::instance()->setStatusPaused(true);
//            	Comm::instance()->sendCommandByte(CMD_CLEAR_ACK, seq);
            	Comm::instance()->sendAckWithSeq32(CMD_CLEAR_ACK, seq8, seq32, have32);
            	break;
            }
            default: break;
          }

		  _acknowledgeRequested = false;

	  }
	  if (_pauseRequested) {
		    Logger::instance()->log("Run\r\n");
	        pauseCurrent();
	        _paused = true;
	        _pauseRequested = false;
	        _lastPausedCmd = _inFlight;    // remember what we were doing
	      }

	  if (_resumeRequested) {
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
			    }
			  } else {
			    _lastExecutedCmdNum = _currentCmdNum;
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

        _currentCmdNum = 0;
        _lastExecutedCmdNum = 0;
        _seqEpoch = 0;
        _lastSeq8 = 0;

        xEventGroupClearBits(_doneEvents,
            BIT_LED_DONE|BIT_STEPPER1_DONE|BIT_STEPPER2_DONE|BIT_STEPPER3_DONE|BIT_PRINTING_DONE|BIT_GRIPPER_DONE);

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
      BIT_LED_DONE|BIT_STEPPER1_DONE|BIT_STEPPER2_DONE|BIT_STEPPER3_DONE|BIT_PRINTING_DONE|BIT_GRIPPER_DONE|
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
      	  waitForBit(BIT_STEPPER1_DONE);
          break;
        }
        case CMD_MOVE_Y: {
          // p1=direction, p2=steps, p3=freqHz
          Stepper::stepperY()->move(cmd.p1, cmd.p2, cmd.p3,2000);
      	  waitForBit(BIT_STEPPER2_DONE);
          break;
        }
        case CMD_MOVE_Z: {
          // p1=direction, p2=steps, p3=freqHz
          Stepper::stepperZ()->move(cmd.p1, cmd.p2, cmd.p3,2000);
      	  waitForBit(BIT_STEPPER3_DONE);
          break;
        }
        case CMD_ABS_X: {
          // p1=direction, p2=steps, p3=freqHz
          Stepper::stepperX()->moveTo(cmd.p1, cmd.p2, cmd.p3,2000);
          // wait for stepper ISR to signal BIT_STEPPER_DONE
      	  waitForBit(BIT_STEPPER1_DONE);
          break;
        }
        case CMD_ABS_Y: {
          // p1=direction, p2=steps, p3=freqHz
          Stepper::stepperY()->moveTo(cmd.p1, cmd.p2, cmd.p3,2000);
          // wait for stepper ISR to signal BIT_STEPPER_DONE
      	  waitForBit(BIT_STEPPER2_DONE);
          break;
        }
        case CMD_ABS_Z: {
          // p1=direction, p2=steps, p3=freqHz
          Logger::instance()->log("ABS-Z\r\n");
          Stepper::stepperZ()->moveTo(cmd.p1, cmd.p2, cmd.p3,2000);
          // wait for stepper ISR to signal BIT_STEPPER_DONE
      	  waitForBit(BIT_STEPPER3_DONE);
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
          waitForBit(BIT_HOME_X_DONE);
          break;
        }
        case CMD_HOME_Y: {
          xEventGroupClearBits(_doneEvents, BIT_HOME_Y_DONE);
          startHomeAsync(Stepper::stepperY(), cmd.p1, cmd.p2, cmd.p3, BIT_HOME_Y_DONE);
          waitForBit(BIT_HOME_Y_DONE);
          break;
        }
        case CMD_HOME_Z: {
          xEventGroupClearBits(_doneEvents, BIT_HOME_Z_DONE);
          startHomeAsync(Stepper::stepperZ(), cmd.p1, cmd.p2, cmd.p3, BIT_HOME_Z_DONE);
          waitForBit(BIT_HOME_Z_DONE);
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
          waitForBit(BIT_STEPPER1_DONE);
          waitForBit(BIT_STEPPER2_DONE);
          break;
        }
        case CMD_GRIPPER_OPEN: {
// #if (LC_CRASH_TEST_GRIPPER_OPEN_WDT != 0)
//           runGripperOpenWatchdogCrashTest();
// #endif
      	  MX_GRIPPER_Open();
      	  waitForBit(BIT_GRIPPER_DONE);
  		  break;
  		}
        case CMD_GRIPPER_CLOSE: {
      	  MX_GRIPPER_Close();
      	  waitForBit(BIT_GRIPPER_DONE);
  		  break;
  		}
        case CMD_GRIPPER_OFF: {
      	  MX_GRIPPER_StopRefresh();
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
			Printer::instance()->enqueue(cmd.p1, cmd.p2,PulseMode::BOTH);
			waitForBit(BIT_PRINTING_DONE);
          break;
        }
        case CMD_DISPENSE_PRINT: {
          // param p1 = pulse width in microseconds, p2 = rate in Hz
			Printer::instance()->enqueue(cmd.p1, cmd.p2,PulseMode::PRINT_ONLY);
			waitForBit(BIT_PRINTING_DONE);
          break;
        }
        case CMD_DISPENSE_REFUEL: {
          // param p1 = pulse width in microseconds, p2 = rate in Hz
			Printer::instance()->enqueue(cmd.p1, cmd.p2,PulseMode::REFUEL_ONLY);
			waitForBit(BIT_PRINTING_DONE);
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
              waitForBit(BIT_PRESSURE_P_READY);
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
			    waitForBit(BIT_PRESSURE_R_READY);
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
              waitForBit(BIT_PRESSURE_P_READY);
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
			  waitForBit(BIT_PRESSURE_R_READY);
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
          waitForBit(BIT_HOME_P_DONE);
          break;
        }
        case CMD_HOME_REFUEL: {
		#if (LC_PRESSURE_PORTS > 1)
		  xEventGroupClearBits(_doneEvents, BIT_HOME_R_DONE);
		  startRegHomeAsync(&PressureRegulator::regR(), cmd.p1, cmd.p2, cmd.p3, BIT_HOME_R_DONE);
		  waitForBit(BIT_HOME_R_DONE);
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
          waitForBits(BIT_HOME_X_DONE | BIT_HOME_Y_DONE);
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
		  waitForBits(BIT_HOME_P_DONE | BIT_HOME_R_DONE);
		#else
		  xEventGroupClearBits(_doneEvents, BIT_HOME_P_DONE);
		  startRegHomeAsync(&PressureRegulator::regP(), fastHz, slowHz, backoff, BIT_HOME_P_DONE);
		  waitForBit(BIT_HOME_P_DONE);
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
			} case CMD_SELFTEST_START: {
				  Comm* comm = Comm::instance();
				  if (!comm || !comm->handle()) {
				    break;
				  }

                  comm->setStatusPaused(true);

				  _selfTestAbortRequested = false;
				  const uint32_t runId = cmd.hasSeq32 ? cmd.seq32 : _currentCmdNum;
				  const uint8_t outSeq8 = cmd.seq8;
                  const uint32_t selftestStartMs = HAL_GetTick();
                  uint32_t lastProgressEmitMs = 0u;
				  uint16_t total = 0;
				  uint16_t passed = 0;
				  uint16_t failed = 0;
				  bool aborted = false;
                  const uint16_t selectedPressureTraceTest =
                      (cmd.p3Len >= 2u) ? static_cast<uint16_t>(cmd.p3u() & 0xFFFFu) : 0u;
                  const bool runPressureSweepCore = (selectedPressureTraceTest == 2301u);
                  const bool runPressureSweepExtended = (selectedPressureTraceTest == 2302u);
                  const bool runPressureSweepFocused = (selectedPressureTraceTest == 2303u);
                  const bool runPressureSweepMicro = (selectedPressureTraceTest == 2304u);
                  const bool runPressureDiagnosticsByFlag = (cmd.p2Len > 0u) && (cmd.p2u() != 0u);
                  const bool runSinglePressureTraceSelection =
                      (selectedPressureTraceTest >= 2101u) && (selectedPressureTraceTest <= 2104u);

                  auto shouldRunPressureTraceCase = [&](uint16_t testId) {
                    if (runPressureSweepCore || runPressureSweepExtended || runPressureSweepFocused || runPressureSweepMicro) {
                      return false;
                    }
                    if (runSinglePressureTraceSelection) {
                      return selectedPressureTraceTest == testId;
                    }
                    if (selectedPressureTraceTest != 0u) {
                      return false;
                    }
                    // Keep default FULL gate lightweight; run pressure diagnostics only when explicitly requested.
                    return runPressureDiagnosticsByFlag;
                  };

					  auto sendResult = [&](uint16_t testId, const char* name, bool pass, const char* metrics) {
                        // Keep status spam suppressed for the whole self-test window.
                        comm->setStatusPaused(true);
					    uint8_t payload[256] = {0};
					    size_t idx = 0;
					    payload[idx++] = CMD_SELFTEST_RESULT;
				    payload[idx++] = outSeq8;

				    payload[idx++] = 0x30; payload[idx++] = 2;
				    payload[idx++] = static_cast<uint8_t>(testId & 0xFFu);
				    payload[idx++] = static_cast<uint8_t>((testId >> 8) & 0xFFu);

					    const size_t nameLenRaw = strlen(name);
					    const uint8_t nameLen = static_cast<uint8_t>((nameLenRaw > 32u) ? 32u : nameLenRaw);
				    payload[idx++] = 0x31; payload[idx++] = nameLen;
				    memcpy(&payload[idx], name, nameLen); idx += nameLen;

				    payload[idx++] = 0x32; payload[idx++] = 1;
				    payload[idx++] = pass ? 1u : 0u;

						    const size_t metricsLenRaw = strlen(metrics);
						    const size_t maxMetricsByFrame = (230u > static_cast<size_t>(nameLen)) ? (230u - static_cast<size_t>(nameLen)) : 0u;
						    const uint8_t metricsLen = static_cast<uint8_t>((metricsLenRaw > maxMetricsByFrame) ? maxMetricsByFrame : metricsLenRaw);
					    payload[idx++] = 0x33; payload[idx++] = metricsLen;
					    memcpy(&payload[idx], metrics, metricsLen); idx += metricsLen;

				    const uint32_t ts = HAL_GetTick();
				    payload[idx++] = 0x34; payload[idx++] = 4;
				    payload[idx++] = static_cast<uint8_t>(ts & 0xFFu);
				    payload[idx++] = static_cast<uint8_t>((ts >> 8) & 0xFFu);
				    payload[idx++] = static_cast<uint8_t>((ts >> 16) & 0xFFu);
				    payload[idx++] = static_cast<uint8_t>((ts >> 24) & 0xFFu);

				    payload[idx++] = 0x21; payload[idx++] = 4;
				    payload[idx++] = static_cast<uint8_t>(runId & 0xFFu);
				    payload[idx++] = static_cast<uint8_t>((runId >> 8) & 0xFFu);
				    payload[idx++] = static_cast<uint8_t>((runId >> 16) & 0xFFu);
				    payload[idx++] = static_cast<uint8_t>((runId >> 24) & 0xFFu);

				    comm->sendFrame(comm->handle(), payload, idx);
				  };

					  auto runOne = [&](uint16_t testId, const char* name, bool pass, const char* metrics) {
				    if (_selfTestAbortRequested) {
				      aborted = true;
				      return false;
				    }
				    total++;
				    if (pass) passed++; else failed++;
				    sendResult(testId, name, pass, metrics);
				    if (_selfTestAbortRequested) {
				      aborted = true;
				      return false;
				    }
				    return true;
				  };

                  auto maybeSendProgress = [&](const char* stage) {
                    const uint32_t nowMs = HAL_GetTick();
                    if ((nowMs - lastProgressEmitMs) < 1000u) {
                      return;
                    }
                    lastProgressEmitMs = nowMs;
                    unsigned long hwmWords = 0u;
#if (INCLUDE_uxTaskGetStackHighWaterMark == 1)
                    hwmWords = static_cast<unsigned long>(uxTaskGetStackHighWaterMark(nullptr));
#endif
                    char metrics[128];
                    snprintf(metrics, sizeof(metrics),
                             "kind=progress;stage=%s;elapsed_ms=%lu;stk_hwm_w=%lu",
                             stage,
                             static_cast<unsigned long>(nowMs - selftestStartMs),
                             hwmWords);
                    sendResult(0u, "selftest_progress", true, metrics);
                  };
                  auto sendProgressStage = [&](const char* stage) {
                    const uint32_t nowMs = HAL_GetTick();
                    lastProgressEmitMs = nowMs;
                    unsigned long hwmWords = 0u;
#if (INCLUDE_uxTaskGetStackHighWaterMark == 1)
                    hwmWords = static_cast<unsigned long>(uxTaskGetStackHighWaterMark(nullptr));
#endif
                    char metrics[128];
                    snprintf(metrics, sizeof(metrics),
                             "kind=progress;stage=%s;elapsed_ms=%lu;stk_hwm_w=%lu",
                             stage,
                             static_cast<unsigned long>(nowMs - selftestStartMs),
                             hwmWords);
                    sendResult(0u, "selftest_progress", true, metrics);
                  };

                  static constexpr uint8_t TAG_TRACE_KIND = 0x39;
                  static constexpr uint8_t TAG_TRACE_CHUNK_INDEX = 0x3A;
                  static constexpr uint8_t TAG_TRACE_CHUNK_TOTAL = 0x3B;
                  static constexpr uint8_t TAG_TRACE_FORMAT = 0x3C;
                  static constexpr uint8_t TAG_TRACE_PAYLOAD = 0x3D;
                  static constexpr uint8_t TRACE_KIND_SAMPLES = 1u;
                  static constexpr uint8_t TRACE_KIND_EVENTS = 2u;
                  static constexpr uint8_t TRACE_FORMAT_SAMPLE_V1 = 1u;
                  static constexpr uint8_t TRACE_FORMAT_EVENT_V1 = 2u;
                  const bool exportPressureTrace = (cmd.p2Len > 0u) && (cmd.p2u() != 0u);

                  auto sendTraceChunk = [&](uint16_t testId,
                                            const char* name,
                                            bool pass,
                                            uint8_t traceKind,
                                            uint8_t traceFormat,
                                            uint16_t chunkIndex,
                                            uint16_t chunkTotal,
                                            const uint8_t* payloadBytes,
                                            uint8_t payloadLen) {
                    // Reassert status suppression before each trace chunk burst.
                    comm->setStatusPaused(true);
                    static uint8_t payload[192];
                    memset(payload, 0, sizeof(payload));
                    size_t idx = 0;
                    payload[idx++] = CMD_SELFTEST_RESULT;
                    payload[idx++] = outSeq8;
                    payload[idx++] = 0x30; payload[idx++] = 2;
                    payload[idx++] = static_cast<uint8_t>(testId & 0xFFu);
                    payload[idx++] = static_cast<uint8_t>((testId >> 8) & 0xFFu);
                    const size_t nameLenRaw = strlen(name);
                    const uint8_t nameLen = static_cast<uint8_t>((nameLenRaw > 48u) ? 48u : nameLenRaw);
                    payload[idx++] = 0x31; payload[idx++] = nameLen;
                    memcpy(&payload[idx], name, nameLen); idx += nameLen;
                    payload[idx++] = 0x32; payload[idx++] = 1; payload[idx++] = pass ? 1u : 0u;
                    payload[idx++] = TAG_TRACE_KIND; payload[idx++] = 1; payload[idx++] = traceKind;
                    payload[idx++] = TAG_TRACE_FORMAT; payload[idx++] = 1; payload[idx++] = traceFormat;
                    payload[idx++] = TAG_TRACE_CHUNK_INDEX; payload[idx++] = 2;
                    payload[idx++] = static_cast<uint8_t>(chunkIndex & 0xFFu);
                    payload[idx++] = static_cast<uint8_t>((chunkIndex >> 8) & 0xFFu);
                    payload[idx++] = TAG_TRACE_CHUNK_TOTAL; payload[idx++] = 2;
                    payload[idx++] = static_cast<uint8_t>(chunkTotal & 0xFFu);
                    payload[idx++] = static_cast<uint8_t>((chunkTotal >> 8) & 0xFFu);
                    payload[idx++] = TAG_TRACE_PAYLOAD; payload[idx++] = payloadLen;
                    memcpy(&payload[idx], payloadBytes, payloadLen); idx += payloadLen;
                    payload[idx++] = 0x21; payload[idx++] = 4;
                    payload[idx++] = static_cast<uint8_t>(runId & 0xFFu);
                    payload[idx++] = static_cast<uint8_t>((runId >> 8) & 0xFFu);
                    payload[idx++] = static_cast<uint8_t>((runId >> 16) & 0xFFu);
                    payload[idx++] = static_cast<uint8_t>((runId >> 24) & 0xFFu);
                    Watchdog_CheckIn(CRASH_TASK_ORCH);
                    comm->sendFrame(comm->handle(), payload, idx);
                  };

                  auto exportTrace = [&](uint16_t testId, const char* name, bool pass) -> bool {
                    if (!exportPressureTrace) {
                      return true;
                    }
                    auto& recorder = PressureTraceRecorder::instance();
                    static constexpr uint8_t kSampleChunkBytes = 80u;
                    static constexpr uint8_t kEventChunkBytes = 80u;
                    static constexpr TickType_t kExportMaxTicks = pdMS_TO_TICKS(6000u);
                    const TickType_t exportStart = xTaskGetTickCount();
                    unsigned long exportHwmWords = 0u;
#if (INCLUDE_uxTaskGetStackHighWaterMark == 1)
                    exportHwmWords = static_cast<unsigned long>(uxTaskGetStackHighWaterMark(nullptr));
#endif
                    if (exportHwmWords > 0u && exportHwmWords < 64u) {
                      sendProgressStage("trace_stack_low");
                      return false;
                    }
                    const auto* samples = reinterpret_cast<const uint8_t*>(recorder.samples());
                    const uint16_t totalSampleBytes = static_cast<uint16_t>(recorder.sampleCount() * sizeof(PressureTraceSample));
                    const uint16_t sampleChunks = (totalSampleBytes == 0u) ? 0u : static_cast<uint16_t>((totalSampleBytes + kSampleChunkBytes - 1u) / kSampleChunkBytes);
                    if (sampleChunks > 1024u) {
                      sendProgressStage("trace_sample_chunk_oob");
                      return false;
                    }
                    for (uint16_t chunkIndex = 0; chunkIndex < sampleChunks; ++chunkIndex) {
                      if ((xTaskGetTickCount() - exportStart) > kExportMaxTicks) {
                        sendProgressStage("trace_export_to");
                        return false;
                      }
                      Watchdog_CheckIn(CRASH_TASK_ORCH);
                      maybeSendProgress("trace_export");
                      const uint16_t offset = static_cast<uint16_t>(chunkIndex * kSampleChunkBytes);
                      const uint16_t remain = static_cast<uint16_t>(totalSampleBytes - offset);
                      const uint8_t chunkLen = static_cast<uint8_t>((remain > kSampleChunkBytes) ? kSampleChunkBytes : remain);
                      sendTraceChunk(testId, name, pass, TRACE_KIND_SAMPLES, TRACE_FORMAT_SAMPLE_V1, chunkIndex, sampleChunks, samples + offset, chunkLen);
                      vTaskDelay(1);
                    }
                    const auto* events = reinterpret_cast<const uint8_t*>(recorder.events());
                    const uint16_t totalEventBytes = static_cast<uint16_t>(recorder.eventCount() * sizeof(PressureTraceEvent));
                    const uint16_t eventChunks = (totalEventBytes == 0u) ? 0u : static_cast<uint16_t>((totalEventBytes + kEventChunkBytes - 1u) / kEventChunkBytes);
                    if (eventChunks > 1024u) {
                      sendProgressStage("trace_event_chunk_oob");
                      return false;
                    }
                    for (uint16_t chunkIndex = 0; chunkIndex < eventChunks; ++chunkIndex) {
                      if ((xTaskGetTickCount() - exportStart) > kExportMaxTicks) {
                        sendProgressStage("trace_export_to");
                        return false;
                      }
                      Watchdog_CheckIn(CRASH_TASK_ORCH);
                      maybeSendProgress("trace_export");
                      const uint16_t offset = static_cast<uint16_t>(chunkIndex * kEventChunkBytes);
                      const uint16_t remain = static_cast<uint16_t>(totalEventBytes - offset);
                      const uint8_t chunkLen = static_cast<uint8_t>((remain > kEventChunkBytes) ? kEventChunkBytes : remain);
                      sendTraceChunk(testId, name, pass, TRACE_KIND_EVENTS, TRACE_FORMAT_EVENT_V1, chunkIndex, eventChunks, events + offset, chunkLen);
                      vTaskDelay(1);
                    }
                    return true;
                  };

				  auto runAckRoundtrip = [&](uint16_t testId, const char* name, uint8_t ackCmd, bool includeSeq32, bool doneLabel, const char* extraMetrics = nullptr, bool extraPass = true) {
				    uint8_t ackPayload[8] = {0};
				    const uint8_t ackLen = CommCodec::buildAckPayload(ackCmd, outSeq8, runId, includeSeq32, ackPayload, sizeof(ackPayload));
				    uint8_t frame[16] = {0};
				    const size_t frameLen = CommCodec::encodeFrame(ackPayload, ackLen, frame, sizeof(frame));

				    CommCodec::RxParser parser{};
				    uint8_t parsedLen = 0;
				    int readyCount = 0;
				    for (size_t i = 0; i < frameLen; ++i) {
				      if (CommCodec::feedRxByte(parser, frame[i], parsedLen) == CommCodec::FeedResult::FrameReady) {
				        readyCount++;
				      }
				    }

				    const auto decoded = CommCodec::decodeCommand(parser.rxBuf, parsedLen);
				    const bool seq8Match = (decoded.seq8 == outSeq8);
				    const bool seq32Match = includeSeq32 ? (decoded.hasSeq32 && decoded.seq32 == runId) : !decoded.hasSeq32;
				    const bool pass = extraPass &&
				                      (ackLen == (includeSeq32 ? 8u : 2u)) &&
				                      (frameLen == static_cast<size_t>(ackLen + 4u)) &&
				                      (readyCount == 1) &&
				                      (decoded.cmd == ackCmd) &&
				                      seq8Match &&
				                      seq32Match;

				    char metrics[128];
				    int written = 0;
				    if (doneLabel) {
				      written = snprintf(metrics, sizeof(metrics), "done_cmd=%u;seq8_match=%u;seq32_match=%u",
				                         static_cast<unsigned>(ackCmd),
				                         static_cast<unsigned>(seq8Match ? 1u : 0u),
				                         static_cast<unsigned>(seq32Match ? 1u : 0u));
				    } else {
				      written = snprintf(metrics, sizeof(metrics), "ack_cmd=%u;seq8_match=%u;seq32_match=%u",
				                         static_cast<unsigned>(ackCmd),
				                         static_cast<unsigned>(seq8Match ? 1u : 0u),
				                         static_cast<unsigned>(seq32Match ? 1u : 0u));
				    }
				    if (extraMetrics && extraMetrics[0] != '\0' && written > 0 && static_cast<size_t>(written) < sizeof(metrics) - 1u) {
				      snprintf(metrics + written, sizeof(metrics) - static_cast<size_t>(written), ";%s", extraMetrics);
				    }
				    return runOne(testId, name, pass, metrics);
				  };

				  auto sampleStatusWindow = [&](uint32_t sampleMs,
					                                uint32_t& chunk0Seen,
					                                uint32_t& chunk1Seen,
					                                uint32_t& alternationErrors,
					                                uint32_t& periodMsAvg,
					                                uint32_t& periodMsMaxJitter) {
					    Comm::resetStatusMetrics();
					    comm->setStatusPaused(false);
					    Watchdog_CheckIn(CRASH_TASK_ORCH);
					    vTaskDelay(pdMS_TO_TICKS(sampleMs));
					    chunk0Seen = Comm::getStatusChunk0Count();
				    chunk1Seen = Comm::getStatusChunk1Count();
				    alternationErrors = Comm::getStatusAlternationErrors();
				    periodMsAvg = Comm::getStatusPeriodAvgMs();
				    periodMsMaxJitter = Comm::getStatusPeriodMaxJitterMs();
                    comm->setStatusPaused(true);
				  };

				  uint32_t statusChunk0Seen = 0;
					  uint32_t statusChunk1Seen = 0;
					  uint32_t statusAlternationErrors = 0;
					  uint32_t statusPeriodMsAvg = 0;
					  uint32_t statusPeriodMsMaxJitter = 0;
					  const bool fullProfile = (cmd.p1Len > 0u) && (cmd.p1u() == 1u);
                      const bool pressureSweepOnly = runPressureSweepCore || runPressureSweepExtended || runPressureSweepFocused || runPressureSweepMicro;
					  bool fullHomePass = pressureSweepOnly;

					  auto absDiff32 = [](int32_t a, int32_t b) -> uint32_t {
					    const int64_t diff = static_cast<int64_t>(a) - static_cast<int64_t>(b);
					    return static_cast<uint32_t>((diff < 0) ? -diff : diff);
					  };

					  auto isHomedPosition = [](int32_t pos) -> bool {
					    return (pos >= 80) && (pos <= 140);
					  };

					  auto waitPressureReady = [&](PressureRegulator& reg,
					                               uint8_t sensorPort,
					                               int32_t targetPressure,
					                               bool stepUp,
					                               uint32_t timeoutMs,
					                               uint32_t& settleTimeMs,
					                               uint32_t& overshoot,
					                               uint32_t& steadyStateError) {
					    PressureSensor* sensor = PressureSensor::instance();
					    if (!sensor) {
					      settleTimeMs = timeoutMs;
					      overshoot = 0u;
					      steadyStateError = 0u;
					      return false;
					    }

					    const uint32_t startMs = HAL_GetTick();
					    int32_t peakPressure = sensor->getPressure(sensorPort);
					    int32_t troughPressure = peakPressure;

						    while ((HAL_GetTick() - startMs) < timeoutMs) {
						      Watchdog_CheckIn(CRASH_TASK_ORCH);
                              maybeSendProgress("wait_pressure_ready");
						      const int32_t pressure = sensor->getPressure(sensorPort);
						      if (pressure > peakPressure) peakPressure = pressure;
					      if (pressure < troughPressure) troughPressure = pressure;
					      if (reg.isPressureOk()) {
					        break;
					      }
					      if (_selfTestAbortRequested) {
					        break;
					      }
					      vTaskDelay(pdMS_TO_TICKS(20));
					    }

					    const uint32_t elapsedMs = HAL_GetTick() - startMs;
					    settleTimeMs = elapsedMs;
					    const int32_t finalPressure = sensor->getPressure(sensorPort);
					    steadyStateError = absDiff32(finalPressure, targetPressure);
					    if (stepUp) {
					      overshoot = (peakPressure > targetPressure)
					                  ? static_cast<uint32_t>(peakPressure - targetPressure)
					                  : 0u;
					    } else {
					      overshoot = (troughPressure < targetPressure)
					                  ? static_cast<uint32_t>(targetPressure - troughPressure)
					                  : 0u;
					    }
						    return reg.isPressureOk();
						  };

						  auto waitBitsWithTimeout = [&](EventBits_t bits, uint32_t timeoutMs) {
                            sendProgressStage("wait_bits_enter");
						    const TickType_t pollTicks = msToAtLeast1Tick(10u);
                            const uint32_t startMs = HAL_GetTick();
							    while ((HAL_GetTick() - startMs) < timeoutMs) {
							      Watchdog_CheckIn(CRASH_TASK_ORCH);
                                  maybeSendProgress("wait_bits");
							      if (_selfTestAbortRequested) {
							        return false;
							      }
                                  const EventBits_t result = xEventGroupGetBits(_doneEvents);
						      if ((result & bits) == bits) {
                                sendProgressStage("wait_bits_set");
						        return true;
						      }
                              maybeSendProgress("wait_bits_tick");
                              vTaskDelay(pollTicks);
						    }
                            sendProgressStage("wait_bits_to");
						    return false;
						  };
                          auto delayWithWatchdog = [&](uint32_t delayMs, const char* progressStage) {
                            const uint32_t startMs = HAL_GetTick();
                            while ((HAL_GetTick() - startMs) < delayMs) {
                              Watchdog_CheckIn(CRASH_TASK_ORCH);
                              maybeSendProgress(progressStage);
                              if (_selfTestAbortRequested) {
                                return false;
                              }
                              const uint32_t elapsedMs = HAL_GetTick() - startMs;
                              const uint32_t remainMs = (elapsedMs < delayMs) ? (delayMs - elapsedMs) : 0u;
                              const uint32_t sliceMs = (remainMs > 25u) ? 25u : remainMs;
                              if (sliceMs == 0u) {
                                break;
                              }
                              vTaskDelay(msToAtLeast1Tick(sliceMs));
                            }
                            return true;
                          };

                          auto waitPrinterIdleWithTimeout = [&](Printer* printer, uint32_t timeoutMs) {
                            if (printer == nullptr) {
                              return false;
                            }
                            sendProgressStage("wait_printer_idle_enter");
                            const TickType_t pollTicks = pdMS_TO_TICKS(10);
                            const TickType_t timeoutTicks = pdMS_TO_TICKS(timeoutMs);
                            TickType_t waitedTicks = 0;
                            while (waitedTicks < timeoutTicks) {
                              Watchdog_CheckIn(CRASH_TASK_ORCH);
                              maybeSendProgress("wait_printer_idle");
                              if (!printer->isBusy()) {
                                sendProgressStage("wait_printer_idle_ok");
                                return true;
                              }
                              if (_selfTestAbortRequested) {
                                return false;
                              }
                              const TickType_t waitTicks = (pollTicks == 0) ? 1 : pollTicks;
                              vTaskDelay(waitTicks);
                              waitedTicks += waitTicks;
                            }
                            sendProgressStage("wait_printer_idle_to");
                            return false;
                          };

                      auto computeTraceMetrics = [&](uint16_t nominalPeriodMs,
                                                     uint32_t& baselinePressure,
                                                     uint32_t& minPressure,
                                                     uint32_t& maxPressure,
                                                     uint32_t& maxUndershoot,
                                                     uint32_t& maxOvershoot,
                                                     uint32_t& worstRecoveryMs,
                                                     uint32_t& meanRecoveryMs,
                                                     uint32_t& readyMissCount,
                                                     uint32_t& maxDeadlineSlipMs,
                                                     uint32_t& meanDeadlineSlipMs,
                                                     uint32_t& zeroCrossCount,
                                                     uint32_t& sampleRejectCount) {
                        baselinePressure = 0u;
                        minPressure = 0u;
                        maxPressure = 0u;
                        maxUndershoot = 0u;
                        maxOvershoot = 0u;
                        worstRecoveryMs = 0u;
                        meanRecoveryMs = 0u;
                        readyMissCount = 0u;
                        maxDeadlineSlipMs = 0u;
                        meanDeadlineSlipMs = 0u;
                        zeroCrossCount = 0u;
                        sampleRejectCount = 0u;
                        auto& recorder = PressureTraceRecorder::instance();
                        if (recorder.sampleCount() == 0u) {
                          return;
                        }
                        const PressureTraceSample* samples = recorder.samples();
                        baselinePressure = samples[0].controlPressure;
                        minPressure = samples[0].controlPressure;
                        maxPressure = samples[0].controlPressure;
                        int32_t prevErr = samples[0].error;
                        uint32_t recoveryTotal = 0u;
                        uint32_t recoveryCount = 0u;
                        uint32_t firstPulseDt = 0u;
                        uint32_t pulseCount = 0u;
                        const PressureTraceEvent* events = recorder.events();
                        const uint16_t eventCount = recorder.eventCount();
                        for (uint16_t i = 0; i < eventCount; ++i) {
                          if (events[i].type == static_cast<uint8_t>(PressureTraceEventType::PulseEnd)) {
                            pulseCount++;
                            if (firstPulseDt == 0u) {
                              firstPulseDt = events[i].dtMs;
                            }
                            const uint32_t actualDt = events[i].dtMs;
                            const uint32_t expectedDt =
                                (pulseCount <= 1u)
                                    ? actualDt
                                    : (static_cast<uint32_t>(firstPulseDt) +
                                       static_cast<uint32_t>(pulseCount - 1u) * nominalPeriodMs);
                            const uint16_t slip = PressureRegulatorMath::computeDeadlineSlipMs(expectedDt, actualDt);
                            meanDeadlineSlipMs += slip;
                            if (slip > maxDeadlineSlipMs) maxDeadlineSlipMs = slip;
                          }
                        }
                        for (uint16_t i = 0; i < eventCount; ++i) {
                          if (events[i].type != static_cast<uint8_t>(PressureTraceEventType::PulseEnd)) {
                            continue;
                          }
                          const uint32_t pulseDt = events[i].dtMs;
                          uint32_t nextPulseDt = 0xFFFFFFFFu;
                          for (uint16_t j = i + 1u; j < eventCount; ++j) {
                            if (events[j].type == static_cast<uint8_t>(PressureTraceEventType::PulseEnd)) {
                              nextPulseDt = events[j].dtMs;
                              break;
                            }
                          }

                          bool sawReadyExit = false;
                          bool recovered = false;
                          for (uint16_t j = i + 1u; j < eventCount; ++j) {
                            const auto eventType = static_cast<PressureTraceEventType>(events[j].type);
                            if ((nextPulseDt != 0xFFFFFFFFu) && (events[j].dtMs >= nextPulseDt)) {
                              break;
                            }
                            if (eventType == PressureTraceEventType::ReadyExit) {
                              sawReadyExit = true;
                              continue;
                            }
                            if (sawReadyExit && (eventType == PressureTraceEventType::ReadyEnter)) {
                              const uint32_t recovery = events[j].dtMs - pulseDt;
                              recoveryTotal += recovery;
                              recoveryCount++;
                              if (recovery > worstRecoveryMs) worstRecoveryMs = recovery;
                              recovered = true;
                              break;
                            }
                          }

                          if (!sawReadyExit) {
                            recoveryCount++;
                            continue;
                          }
                          if (!recovered) {
                            readyMissCount++;
                          }
                        }
                        for (uint16_t i = 0; i < recorder.sampleCount(); ++i) {
                          const auto& sample = samples[i];
                          if (sample.controlPressure < minPressure) minPressure = sample.controlPressure;
                          if (sample.controlPressure > maxPressure) maxPressure = sample.controlPressure;
                          if (sample.target > sample.controlPressure) {
                            const uint32_t under = sample.target - sample.controlPressure;
                            if (under > maxUndershoot) maxUndershoot = under;
                          } else {
                            const uint32_t over = sample.controlPressure - sample.target;
                            if (over > maxOvershoot) maxOvershoot = over;
                          }
                          if ((sample.flags & 0x20u) != 0u) sampleRejectCount++;
                          if (((prevErr < 0) && (sample.error > 0)) || ((prevErr > 0) && (sample.error < 0))) {
                            zeroCrossCount++;
                          }
                          prevErr = sample.error;
                        }
                        if (pulseCount > 0u) {
                          meanDeadlineSlipMs /= pulseCount;
                        }
                        if (recoveryCount > 0u) {
                          meanRecoveryMs = recoveryTotal / recoveryCount;
                        }
                      };

					  auto areMotorsDisabled = [&]() -> bool {
					    const bool xDisabled = HAL_GPIO_ReadPin(Stepper::stepperX()->enPort(), Stepper::stepperX()->enPin()) == GPIO_PIN_SET;
					    const bool yDisabled = HAL_GPIO_ReadPin(Stepper::stepperY()->enPort(), Stepper::stepperY()->enPin()) == GPIO_PIN_SET;
					    const bool zDisabled = HAL_GPIO_ReadPin(Stepper::stepperZ()->enPort(), Stepper::stepperZ()->enPin()) == GPIO_PIN_SET;
					    const bool pDisabled = HAL_GPIO_ReadPin(Stepper::stepperP()->enPort(), Stepper::stepperP()->enPin()) == GPIO_PIN_SET;
					#if (LC_PRESSURE_PORTS > 1)
					    const bool rDisabled = HAL_GPIO_ReadPin(Stepper::stepperR()->enPort(), Stepper::stepperR()->enPin()) == GPIO_PIN_SET;
					    return xDisabled && yDisabled && zDisabled && pDisabled && rDisabled;
					#else
					    return xDisabled && yDisabled && zDisabled && pDisabled;
					#endif
					  };

					  auto areRegulatorsStopped = [&]() -> bool {
					    const bool pStopped = !PressureRegulator::regP().isActive();
					#if (LC_PRESSURE_PORTS > 1)
					    const bool rStopped = !PressureRegulator::regR().isActive();
					    return pStopped && rStopped;
					#else
					    return pStopped;
					#endif
					  };

					  auto areValvesClosed = [&]() -> bool {
					    const bool pClosed = !PressureRegulator::regP().isValveOpen();
					#if (LC_PRESSURE_PORTS > 1)
					    const bool rClosed = !PressureRegulator::regR().isValveOpen();
					    return pClosed && rClosed;
					#else
					    return pClosed;
					#endif
					  };

                      auto psiToRaw = [](uint32_t psiMilli) -> uint16_t {
                        const uint32_t psiOffset = 1638u;
                        const uint32_t fss = 13107u;
                        const uint32_t psiMaxMilli = 15000u;
                        const uint32_t scaled = (psiMilli * fss + (psiMaxMilli / 2u)) / psiMaxMilli;
                        return static_cast<uint16_t>(psiOffset + scaled);
                      };

                      struct PressureTraceCaseMetrics {
                        uint32_t baselinePressure = 0u;
                        uint32_t minPressure = 0u;
                        uint32_t maxPressure = 0u;
                        uint32_t maxUndershoot = 0u;
                        uint32_t maxOvershoot = 0u;
                        uint32_t worstRecoveryMs = 0u;
                        uint32_t meanRecoveryMs = 0u;
                        uint32_t readyMissCount = 0u;
                        uint32_t maxDeadlineSlipMs = 0u;
                        uint32_t meanDeadlineSlipMs = 0u;
                        uint32_t zeroCrossCount = 0u;
                        uint32_t sampleRejectCount = 0u;
                        uint32_t traceSampleCount = 0u;
                        uint32_t traceEventCount = 0u;
                        bool pass = false;
                      };

                      auto maybeExportTrace = [&](bool shouldExport,
                                                  uint16_t testId,
                                                  const char* name,
                                                  bool pass) -> bool {
                        if (!shouldExport) {
                          return true;
                        }
                        return exportTrace(testId, name, pass);
                      };

                      auto runPressureTraceCase = [&](uint16_t testId,
                                                      const char* name,
                                                      uint8_t channel,
                                                      uint16_t targetRaw,
                                                      uint16_t pulseWidthUs,
                                                      uint16_t dropletCount,
                                                      uint16_t rateHz,
                                                      PulseMode mode,
                                                      bool requireBothReady,
                                                      uint16_t secondaryTargetRaw,
                                                      uint16_t secondaryPulseWidthUs,
                                                      PressureTraceCaseMetrics* outMetrics,
                                                      bool emitResult,
                                                      bool shouldExportTrace) {
                        static constexpr uint32_t kPressureStabilizationMs = 1000u;
                        sendProgressStage("trace_case_enter");
                        PressureTraceCaseMetrics computed{};
                        if (!fullProfile) {
                          if (emitResult) {
                            return runOne(testId, name, true, "profile=SAFE;executed=0;fixture_required=1;pressure_trace=0;gate=safe_only");
                          }
                          computed.pass = true;
                          if (outMetrics) *outMetrics = computed;
                          return true;
                        }
                        if (!fullHomePass && !pressureSweepOnly) {
                          if (emitResult) {
                            return runOne(testId, name, false, "base=0;min=0;max=0;under=0;over=0;rec_w=0;rec_m=0;ready_miss=1;slip_w=0;slip_m=0;zero=0;rejects=0;sc=0;ec=0");
                          }
                          if (outMetrics) *outMetrics = computed;
                          return false;
                        }

                        auto& recorder = PressureTraceRecorder::instance();
                        recorder.reset();
                        PressureTraceConfig traceCfg{};
                        traceCfg.channel = (channel == 0u) ? PressureTraceChannel::Print : PressureTraceChannel::Refuel;
                        traceCfg.maxSamples = PressureTraceRecorder::kMaxSamples;
                        traceCfg.maxEvents = PressureTraceRecorder::kMaxEvents;
                        recorder.configure(traceCfg);

                        Printer* printer = Printer::instance();
                        if ((printer == nullptr) || (PressureSensor::instance() == nullptr)) {
                          if (emitResult) {
                            return runOne(testId, name, false, "base=0;min=0;max=0;under=0;over=0;rec_w=0;rec_m=0;ready_miss=1;slip_w=0;slip_m=0;zero=0;rejects=0;sc=0;ec=0");
                          }
                          if (outMetrics) *outMetrics = computed;
                          return false;
                        }

                        PressureRegulator& reg = (channel == 0u) ? PressureRegulator::regP() : PressureRegulator::regR();
                        PressureRegulator* secondaryReg = nullptr;
                        bool secondaryReadyOk = true;
                        const uint32_t originalPrintPulse = printer->getPrintPulse();
                        const uint32_t originalRefuelPulse = printer->getRefuelPulse();
                        const uint16_t baselineTarget = static_cast<uint16_t>(reg.getTarget());
                        uint16_t secondaryBaselineTarget = 0u;
                        reg.start();
                        printer->setDiagnosticReadyTimeout(true, 4500u);
                        if (requireBothReady) {
#if (LC_PRESSURE_PORTS > 1)
                          secondaryReg = (channel == 0u) ? &PressureRegulator::regR() : &PressureRegulator::regP();
                          secondaryBaselineTarget = static_cast<uint16_t>(secondaryReg->getTarget());
                          secondaryReg->start();
                          xEventGroupClearBits(_doneEvents, (channel == 0u) ? BIT_PRESSURE_R_READY : BIT_PRESSURE_P_READY);
                          const uint16_t secTarget = (secondaryTargetRaw == 0u)
                                                       ? ((channel == 0u) ? psiToRaw(500u) : psiToRaw(1000u))
                                                       : secondaryTargetRaw;
                          secondaryReg->setTargetSafe(secTarget);
                          secondaryReadyOk = waitBitsWithTimeout((channel == 0u) ? BIT_PRESSURE_R_READY : BIT_PRESSURE_P_READY, 5000u);
#endif
                        }
                        if (channel == 0u) {
                          printer->setPrintPulse(pulseWidthUs);
                        } else {
                          printer->setRefuelPulse(pulseWidthUs);
                        }
                        if (requireBothReady && (secondaryPulseWidthUs > 0u)) {
                          if (channel == 0u) {
#if (LC_PRESSURE_PORTS > 1)
                            printer->setRefuelPulse(secondaryPulseWidthUs);
#endif
                          } else {
                            printer->setPrintPulse(secondaryPulseWidthUs);
                          }
                        }
                        xEventGroupClearBits(_doneEvents, BIT_PRINTING_DONE | ((channel == 0u) ? BIT_PRESSURE_P_READY : BIT_PRESSURE_R_READY));
                        reg.setTargetSafe(targetRaw);
                        sendProgressStage("trace_wait_ready");
                        const bool readyOk = waitBitsWithTimeout((channel == 0u) ? BIT_PRESSURE_P_READY : BIT_PRESSURE_R_READY, 5000u);
                        bool printDone = false;
                        bool queued = false;
                        if (secondaryReadyOk && readyOk) {
                          sendProgressStage("trace_stabilize");
                          if (!delayWithWatchdog(kPressureStabilizationMs, "trace_stabilize")) {
                            sendProgressStage("trace_abort_pre_enqueue");
                          } else if (_selfTestAbortRequested) {
                            sendProgressStage("trace_abort_pre_enqueue");
                          } else {
                            recorder.arm();
                            recorder.start(HAL_GetTick());
                            if (!delayWithWatchdog(traceCfg.preRollMs, "trace_preroll")) {
                              sendProgressStage("trace_abort_pre_enqueue");
                            } else {
                              sendProgressStage("trace_enqueue");
                              queued = printer->enqueueWithTimeout(dropletCount, rateHz, mode, pdMS_TO_TICKS(250));
                              if (queued) {
                                sendProgressStage("trace_wait_done");
                                printDone = waitBitsWithTimeout(BIT_PRINTING_DONE, 5000u);
                              } else {
                                sendProgressStage("trace_enqueue_to");
                                printDone = false;
                              }
                              if (printDone) {
                                (void)delayWithWatchdog(traceCfg.postRollMs, "trace_postroll");
                              }
                              recorder.stop(HAL_GetTick());
                            }
                          }
                        }
                        if (queued && !printDone) {
                          // Prevent a timed-out run from leaking into the next sweep combo.
                          sendProgressStage("trace_cancel");
                          printer->cancelDispense();
                          (void)waitPrinterIdleWithTimeout(printer, 500u);
                        }
                        sendProgressStage("trace_restore");
                        reg.setTargetSafe(baselineTarget);
#if (LC_PRESSURE_PORTS > 1)
                        if (secondaryReg != nullptr) {
                          secondaryReg->setTargetSafe(secondaryBaselineTarget);
                        }
#endif
                        vTaskDelay(pdMS_TO_TICKS(50));
                        sendProgressStage("trace_restore_pulses");
                        printer->setPrintPulse(originalPrintPulse);
                        printer->setRefuelPulse(originalRefuelPulse);
                        printer->setDiagnosticReadyTimeout(false, 0u);
                        sendProgressStage("trace_pause_regs");
                        reg.pause();
#if (LC_PRESSURE_PORTS > 1)
                        if (secondaryReg != nullptr) {
                          secondaryReg->pause();
                        }
#endif

                        computed.traceSampleCount = recorder.sampleCount();
                        computed.traceEventCount = recorder.eventCount();
                        sendProgressStage("trace_metrics_start");
                        Watchdog_CheckIn(CRASH_TASK_ORCH);
                        computeTraceMetrics(rateHz == 0u ? 0u : static_cast<uint16_t>(1000u / rateHz),
                                            computed.baselinePressure,
                                            computed.minPressure,
                                            computed.maxPressure,
                                            computed.maxUndershoot,
                                            computed.maxOvershoot,
                                            computed.worstRecoveryMs,
                                            computed.meanRecoveryMs,
                                            computed.readyMissCount,
                                            computed.maxDeadlineSlipMs,
                                            computed.meanDeadlineSlipMs,
                                            computed.zeroCrossCount,
                                            computed.sampleRejectCount);
                        Watchdog_CheckIn(CRASH_TASK_ORCH);
                        sendProgressStage("trace_metrics_done");
                        computed.pass = secondaryReadyOk &&
                                        readyOk &&
                                        printDone &&
                                        (computed.maxDeadlineSlipMs <= 250u) &&
                                        (computed.readyMissCount == 0u);

                        if (outMetrics) *outMetrics = computed;

                        if (emitResult) {
                          char metrics[224];
                          snprintf(metrics, sizeof(metrics),
                                   "base=%lu;min=%lu;max=%lu;under=%lu;over=%lu;rec_w=%lu;rec_m=%lu;ready_miss=%lu;slip_w=%lu;slip_m=%lu;zero=%lu;rejects=%lu;sc=%lu;ec=%lu",
                                   static_cast<unsigned long>(computed.baselinePressure),
                                   static_cast<unsigned long>(computed.minPressure),
                                   static_cast<unsigned long>(computed.maxPressure),
                                   static_cast<unsigned long>(computed.maxUndershoot),
                                   static_cast<unsigned long>(computed.maxOvershoot),
                                   static_cast<unsigned long>(computed.worstRecoveryMs),
                                   static_cast<unsigned long>(computed.meanRecoveryMs),
                                   static_cast<unsigned long>(computed.readyMissCount),
                                   static_cast<unsigned long>(computed.maxDeadlineSlipMs),
                                   static_cast<unsigned long>(computed.meanDeadlineSlipMs),
                                   static_cast<unsigned long>(computed.zeroCrossCount),
                                   static_cast<unsigned long>(computed.sampleRejectCount),
                                   static_cast<unsigned long>(computed.traceSampleCount),
                                   static_cast<unsigned long>(computed.traceEventCount));
                          sendProgressStage("trace_result_emit");
                          Watchdog_CheckIn(CRASH_TASK_ORCH);
                          const bool reported = runOne(testId, name, computed.pass, metrics);
                          sendProgressStage("trace_result_done");
                          if (!reported) {
                            return false;
                          }
                          if (!maybeExportTrace(shouldExportTrace, testId, name, computed.pass)) {
                            sendProgressStage("trace_export_abort");
                            aborted = true;
                            _selfTestAbortRequested = true;
                            return false;
                          }
                          return true;
                        }

                        return true;
                      };

				  {
				    static const uint8_t known[] = {'1','2','3','4','5','6','7','8','9'};
				    const uint16_t crc = CommCodec::crc16(known, sizeof(known));
				    char metrics[48];
				    snprintf(metrics, sizeof(metrics), "crc=%u", static_cast<unsigned>(crc));
				    if (!runOne(1001, "comm_crc_known_vector", (crc == 0x4B37u), metrics)) goto selftest_done;
				  }

				  {
				    uint8_t ackPayload[8] = {0};
				    const uint8_t ackLen = CommCodec::buildAckPayload(0xF4, 0x22, runId, true, ackPayload, sizeof(ackPayload));
				    uint8_t frame[16] = {0};
				    const size_t frameLen = CommCodec::encodeFrame(ackPayload, ackLen, frame, sizeof(frame));
				    CommCodec::RxParser parser{};
				    uint8_t parsedLen = 0;
				    int readyCount = 0;
				    for (size_t i = 0; i < frameLen; ++i) {
				      if (CommCodec::feedRxByte(parser, frame[i], parsedLen) == CommCodec::FeedResult::FrameReady) {
				        readyCount++;
				      }
				    }
				    const auto decoded = CommCodec::decodeCommand(parser.rxBuf, parsedLen);
				    const bool pass = (ackLen == 8u) && (frameLen == 12u) && (readyCount == 1) &&
				                      (decoded.cmd == 0xF4u) && (decoded.seq8 == 0x22u) && decoded.hasSeq32;
				    char metrics[48];
				    snprintf(metrics, sizeof(metrics), "frame_len=%u", static_cast<unsigned>(frameLen));
				    if (!runOne(1002, "comm_frame_roundtrip", pass, metrics)) goto selftest_done;
				  }

				  if (!runAckRoundtrip(1010, "session_hello_ack", CMD_HELLO_ACK, true, false)) goto selftest_done;
				  if (!runAckRoundtrip(1011, "session_goodbye_ack", CMD_BYE_ACK, true, false)) goto selftest_done;
				  if (!runAckRoundtrip(1012, "session_goodbye_done", CMD_BYE_DONE, true, true)) goto selftest_done;

				  sampleStatusWindow(260u,
				                    statusChunk0Seen,
				                    statusChunk1Seen,
				                    statusAlternationErrors,
				                    statusPeriodMsAvg,
				                    statusPeriodMsMaxJitter);

				  {
				    static constexpr unsigned kStatusTagCount = 18u;
				    const bool pass = (statusChunk0Seen > 0u) && (statusChunk1Seen > 0u);
				    char metrics[96];
				    snprintf(metrics, sizeof(metrics), "tag_count=%u;has_seq32=0;chunk0_seen=%lu;chunk1_seen=%lu",
				             kStatusTagCount,
				             static_cast<unsigned long>(statusChunk0Seen),
				             static_cast<unsigned long>(statusChunk1Seen));
				    if (!runOne(1003, "status_frame_shape", pass, metrics)) goto selftest_done;
				  }

				  {
				    xQueueReset(_cmdQueue);
				    const UBaseType_t queueDepthAfterClear = uxQueueMessagesWaiting(_cmdQueue);
				    char extra[48];
				    snprintf(extra, sizeof(extra), "queue_depth_after_clear=%u", static_cast<unsigned>(queueDepthAfterClear));
				    if (!runAckRoundtrip(1013, "clear_queue_ack", CMD_CLEAR_ACK, true, false, extra, (queueDepthAfterClear == 0u))) goto selftest_done;
				  }

				  {
				    const bool pass = (statusChunk0Seen >= 2u) && (statusChunk1Seen >= 2u) && (statusAlternationErrors == 0u);
				    char metrics[96];
				    snprintf(metrics, sizeof(metrics), "chunk0_seen=%lu;chunk1_seen=%lu;alternation_errors=%lu",
				             static_cast<unsigned long>(statusChunk0Seen),
				             static_cast<unsigned long>(statusChunk1Seen),
				             static_cast<unsigned long>(statusAlternationErrors));
				    if (!runOne(1020, "status_chunk_alternation_safe", pass, metrics)) goto selftest_done;
				  }

				  {
				    const bool pass = (statusPeriodMsAvg >= 35u) && (statusPeriodMsAvg <= 90u) && (statusPeriodMsMaxJitter <= 40u);
				    char metrics[96];
				    snprintf(metrics, sizeof(metrics), "period_ms_avg=%lu;period_ms_max_jitter=%lu",
				             static_cast<unsigned long>(statusPeriodMsAvg),
				             static_cast<unsigned long>(statusPeriodMsMaxJitter));
				    if (!runOne(1021, "status_cadence_safe", pass, metrics)) goto selftest_done;
				  }

					  {
					    const uint32_t t0 = HAL_GetTick();
					    vTaskDelay(pdMS_TO_TICKS(10));
					    const uint32_t dt = HAL_GetTick() - t0;
					    char metrics[48];
					    snprintf(metrics, sizeof(metrics), "delta_ms=%lu", static_cast<unsigned long>(dt));
					    if (!runOne(1004, "uptime_counter_read", dt >= 1u, metrics)) goto selftest_done;
					  }
	
					  {
					    const uint32_t flashDelay = Orchestrator::getFlashDelay();
                        const uint32_t extCount = Orchestrator::getExtCount();
                        const uint32_t flashAckCount = Orchestrator::getFlashAckCount();
                        const uint32_t flashTaskWakeCount = Orchestrator::getFlashTaskWakeCount();
                        const uint32_t flashTaskDoneCount = Orchestrator::getFlashTaskDoneCount();
					    const uint32_t flashInitCmdCount = Orchestrator::getFlashInitCmdCount();
					    const uint32_t flashInitOkCount = Orchestrator::getFlashInitOkCount();
					    const uint32_t flashInitTaskCreateFailCount = Orchestrator::getFlashInitTaskCreateFailCount();
					    const uint32_t flashInitTimerCreateFailCount = Orchestrator::getFlashInitTimerCreateFailCount();
					    const uint32_t flashSessionArmed = Orchestrator::isFlashSessionArmed() ? 1u : 0u;
					    const uint32_t flashFaultLatched = Orchestrator::isFlashFaultLatched() ? 1u : 0u;
					    const char* flashFaultReason = Orchestrator::getFlashFaultReason();
                        const uint32_t flashOutputArmed = static_cast<uint32_t>(MX_FLASH_IsOutputArmed());
                        const char* flashOutputMode = MX_FLASH_OutputModeToken();
                        uint32_t flashWidthNs = 0;
                        uint32_t flashWidthMinNs = 0;
                        uint32_t flashWidthMaxNs = 0;
	#if LC_HAS_IMAGING == 1
					    if (auto* flash = Flash::instance()) {
					      flashWidthNs = flash->getPulseDuration();
					    }
                        flashWidthMinNs = static_cast<uint32_t>(Flash::kMinPulseNs);
                        flashWidthMaxNs = static_cast<uint32_t>(Flash::kMaxPulseNs);
	#endif
					    char metrics[384];
					    snprintf(metrics, sizeof(metrics),
                                "flash_delay_us=%lu;flash_width_ns=%lu;flash_width_min_ns=%lu;flash_width_max_ns=%lu;"
                                 "ext_count=%lu;flash_ack_count=%lu;flash_task_wake_count=%lu;flash_task_done_count=%lu;"
                                 "flash_init_cmd_count=%lu;flash_init_ok_count=%lu;flash_init_task_create_fail_count=%lu;flash_init_timer_create_fail_count=%lu;"
                                 "flash_session_armed=%lu;flash_fault_latched=%lu;flash_fault_reason=%s;flash_output_armed=%lu;flash_output_mode=%s",
					             static_cast<unsigned long>(flashDelay),
					             static_cast<unsigned long>(flashWidthNs),
                                 static_cast<unsigned long>(flashWidthMinNs),
                                 static_cast<unsigned long>(flashWidthMaxNs),
                                 static_cast<unsigned long>(extCount),
                                 static_cast<unsigned long>(flashAckCount),
                                 static_cast<unsigned long>(flashTaskWakeCount),
                                 static_cast<unsigned long>(flashTaskDoneCount),
                                 static_cast<unsigned long>(flashInitCmdCount),
                                 static_cast<unsigned long>(flashInitOkCount),
                                 static_cast<unsigned long>(flashInitTaskCreateFailCount),
                                 static_cast<unsigned long>(flashInitTimerCreateFailCount),
                                 static_cast<unsigned long>(flashSessionArmed),
                                 static_cast<unsigned long>(flashFaultLatched),
                                 flashFaultReason,
                                 static_cast<unsigned long>(flashOutputArmed),
                                 flashOutputMode);
					    if (!runOne(1005, "flash_config_readonly", true, metrics)) goto selftest_done;
					  }

                      {
                        const uint16_t priorDrops = _imagingDroplets;
                        setImagingDroplets(0);
                        const uint32_t extPre = Orchestrator::getExtCount();
                        const uint32_t ackPre = Orchestrator::getFlashAckCount();
                        const uint32_t wakePre = Orchestrator::getFlashTaskWakeCount();
                        const uint32_t donePre = Orchestrator::getFlashTaskDoneCount();
                        static constexpr uint32_t kBurstCycles = 5u;
                        uint32_t started = 0u;
                        uint32_t timedOut = 0u;
                        for (uint32_t i = 0; i < kBurstCycles; ++i) {
                            if (_flashTaskHandle == nullptr) {
                                break;
                            }
                            xEventGroupClearBits(_doneEvents, BIT_FLASH_DONE);
                            const BaseType_t noteRc = xTaskNotify(_flashTaskHandle, 0x1u, eSetBits);
                            if (noteRc != pdPASS) {
                                continue;
                            }
                            started++;
                            if (!waitBitsWithTimeout(BIT_FLASH_DONE, 250u)) {
                                timedOut++;
                            }
                            vTaskDelay(msToAtLeast1Tick(3u));
                        }
                        const uint32_t extPost = Orchestrator::getExtCount();
                        const uint32_t ackPost = Orchestrator::getFlashAckCount();
                        const uint32_t wakePost = Orchestrator::getFlashTaskWakeCount();
                        const uint32_t donePost = Orchestrator::getFlashTaskDoneCount();
                        setImagingDroplets(priorDrops);

                        const uint32_t dExt = extPost - extPre;
                        const uint32_t dAck = ackPost - ackPre;
                        const uint32_t dWake = wakePost - wakePre;
                        const uint32_t dDone = donePost - donePre;
                        const bool taskPresent = (_flashTaskHandle != nullptr);
                        const uint32_t flashSessionArmed = Orchestrator::isFlashSessionArmed() ? 1u : 0u;
                        const uint32_t flashFaultLatched = Orchestrator::isFlashFaultLatched() ? 1u : 0u;
                        const char* flashFaultReason = Orchestrator::getFlashFaultReason();
                        const uint32_t flashOutputArmed = static_cast<uint32_t>(MX_FLASH_IsOutputArmed());
                        const char* flashOutputMode = MX_FLASH_OutputModeToken();
                        const bool pass = (!taskPresent) ||
                                          ((started > 0u) &&
                                           (timedOut == 0u) &&
                                           (dWake >= started) &&
                                           (dDone >= started) &&
                                           (dAck >= started));
                        char metrics[320];
                        snprintf(metrics, sizeof(metrics),
                                 "skipped_no_flash_task=%lu;cycles_req=%lu;cycles_started=%lu;cycles_timeout=%lu;ext_delta=%lu;flash_ack_delta=%lu;flash_task_wake_delta=%lu;flash_task_done_delta=%lu;"
                                 "flash_session_armed=%lu;flash_fault_latched=%lu;flash_fault_reason=%s;flash_output_armed=%lu;flash_output_mode=%s",
                                 static_cast<unsigned long>(taskPresent ? 0u : 1u),
                                 static_cast<unsigned long>(kBurstCycles),
                                 static_cast<unsigned long>(started),
                                 static_cast<unsigned long>(timedOut),
                                 static_cast<unsigned long>(dExt),
                                 static_cast<unsigned long>(dAck),
                                 static_cast<unsigned long>(dWake),
                                 static_cast<unsigned long>(dDone),
                                 static_cast<unsigned long>(flashSessionArmed),
                                 static_cast<unsigned long>(flashFaultLatched),
                                 flashFaultReason,
                                 static_cast<unsigned long>(flashOutputArmed),
                                 flashOutputMode);
                        if (!runOne(1007, "flash_imaging_burst_diag_safe", pass, metrics)) goto selftest_done;
                      }
	
					  {
					    static const char kBuildInfo[] = __DATE__ " " __TIME__;
					    char metrics[96];
					    snprintf(metrics, sizeof(metrics), "version_len=%u;build_epoch=%s",
					             static_cast<unsigned>(strlen(kBuildInfo)),
					             kBuildInfo);
					    if (!runOne(1006, "fw_build_info", strlen(kBuildInfo) > 0u, metrics)) goto selftest_done;
					  }

						  {
						    static const uint8_t recoveryStream[] = {
					      0x00, 0x7E, 0x55, 0xAB,
					      0xAA, 0x02, 0xF3, 0x01, 0x84, 0x80,
					      0xAA, 0x3F,
					      0xAA, 0x03, 0x10, 0x20, 0x30, 0x40, 0x50,
					      0xAA, 0x02, 0xF3, 0x01, 0x84, 0x80
					    };
					    CommCodec::RxParser parser{};
					    uint8_t parsedLen = 0;
					    uint16_t framesRecovered = 0;
					    uint16_t crcMismatchCount = 0;
					    uint16_t lengthRejectCount = 0;
					    for (size_t i = 0; i < sizeof(recoveryStream); ++i) {
					      const auto result = CommCodec::feedRxByte(parser, recoveryStream[i], parsedLen);
					      if (result == CommCodec::FeedResult::FrameReady) {
					        framesRecovered++;
					      } else if (result == CommCodec::FeedResult::CrcMismatch) {
					        crcMismatchCount++;
					      } else if (result == CommCodec::FeedResult::LengthRejected) {
					        lengthRejectCount++;
					      }
					    }
					    const bool pass = (framesRecovered == 2u) &&
					                      (crcMismatchCount == 1u) &&
					                      (lengthRejectCount == 1u) &&
					                      (parser.state == CommCodec::RxParser::WAIT_START);
					    char metrics[112];
						    snprintf(metrics, sizeof(metrics),
						             "noise_bytes_injected=%u;frames_recovered=%u;crc_mismatch_count=%u;length_reject_count=%u",
						             4u,
						             static_cast<unsigned>(framesRecovered),
						             static_cast<unsigned>(crcMismatchCount),
						             static_cast<unsigned>(lengthRejectCount));
							    if (!runOne(1030, "uart_recovery_after_noise_safe", pass, metrics)) goto selftest_done;
							  }

						  {
						    static constexpr size_t kSelfTestTaskSnapshotCap = 16u;
						    static constexpr uint32_t kSelfTestHeapNowMinBytes = 4096u;
						    static constexpr uint32_t kSelfTestHeapMinMinBytes = 3072u;
						    static constexpr uint16_t kSelfTestStackMinWords = 32u;
						    static TaskStatus_t taskStats[kSelfTestTaskSnapshotCap];
						    const UBaseType_t taskCount = uxTaskGetNumberOfTasks();
						    const UBaseType_t captured = uxTaskGetSystemState(taskStats, kSelfTestTaskSnapshotCap, nullptr);
						    const bool trunc = (taskCount > kSelfTestTaskSnapshotCap) || ((captured == 0u) && (taskCount > 0u));
						    bool hasOrch = false;
						    bool hasStatus = false;
						    bool hasPrinter = false;
						    bool hasPressure = false;
						    bool hasLogStats = false;
						    bool hasFlashMon = false;
						    uint32_t pregCount = 0u;
						    uint16_t stackMinWords = 0xFFFFu;
						    uint16_t printerHwmWords = 0u;
						    uint16_t flashMonHwmWords = 0u;
						    char stackMinTask[12] = "none";
						    for (UBaseType_t i = 0; i < captured; ++i) {
						      const char* taskName = taskStats[i].pcTaskName;
						      if (taskName == nullptr) {
						        continue;
						      }
						      bool trackForMin = false;
						      if (strcmp(taskName, "Orch") == 0) {
						        hasOrch = true;
						        trackForMin = true;
						      } else if (strcmp(taskName, "Status") == 0) {
						        hasStatus = true;
						        trackForMin = true;
						      } else if (strcmp(taskName, "PRNT") == 0) {
						        hasPrinter = true;
						        printerHwmWords = taskStats[i].usStackHighWaterMark;
						        trackForMin = true;
						      } else if (strcmp(taskName, "Pressure") == 0) {
						        hasPressure = true;
						        trackForMin = true;
						      } else if (strcmp(taskName, "LogStats") == 0) {
						        hasLogStats = true;
						        trackForMin = true;
						      } else if (strcmp(taskName, "FlashMon") == 0) {
						        hasFlashMon = true;
						        flashMonHwmWords = taskStats[i].usStackHighWaterMark;
						        trackForMin = true;
						      } else if (strcmp(taskName, "PReg") == 0) {
						        pregCount++;
						        trackForMin = true;
						      }
						      if (trackForMin && (taskStats[i].usStackHighWaterMark < stackMinWords)) {
						        stackMinWords = taskStats[i].usStackHighWaterMark;
						        snprintf(stackMinTask, sizeof(stackMinTask), "%s", taskName);
						      }
						    }
						    const uint32_t heapNow = xPortGetFreeHeapSize();
						    const uint32_t heapMin = xPortGetMinimumEverFreeHeapSize();
						    const uint32_t stackOverflowFired = RTOS_StackOverflowHookFired();
						    const uint32_t coreMissing = (hasOrch ? 0u : 1u) +
						                                 (hasStatus ? 0u : 1u) +
						                                 (hasPrinter ? 0u : 1u) +
						                                 (hasPressure ? 0u : 1u) +
						                                 (hasLogStats ? 0u : 1u);
						    const bool pass = (heapNow >= kSelfTestHeapNowMinBytes) &&
						                      (heapMin >= kSelfTestHeapMinMinBytes) &&
						                      (stackMinWords >= kSelfTestStackMinWords) &&
						                      (coreMissing == 0u) &&
						                      !trunc &&
						                      (pregCount == static_cast<uint32_t>(LC_PRESSURE_PORTS)) &&
						                      (stackOverflowFired == 0u);
						    char metrics[256];
						    snprintf(metrics,
						             sizeof(metrics),
						             "heap_now=%lu;heap_min=%lu;stk_min=%u;stk_task=%s;task_n=%u;core_miss=%lu;preg_n=%lu;trunc=%u;stk_ovf=%lu;prnt_hwm_words=%u;flashmon_hwm_words=%u;flashmon_present=%u",
						             static_cast<unsigned long>(heapNow),
						             static_cast<unsigned long>(heapMin),
						             static_cast<unsigned>(stackMinWords),
						             stackMinTask,
						             static_cast<unsigned>(captured),
						             static_cast<unsigned long>(coreMissing),
						             static_cast<unsigned long>(pregCount),
						             trunc ? 1u : 0u,
						             static_cast<unsigned long>(stackOverflowFired),
						             static_cast<unsigned>(printerHwmWords),
						             static_cast<unsigned>(flashMonHwmWords),
						             hasFlashMon ? 1u : 0u);
						    if (!runOne(1040, "rtos_memory_headroom_safe", pass, metrics)) goto selftest_done;
						  }

						#if (LC_CRASHLOG_SELFTEST_ENABLE != 0)
						  {
						    CrashLogSnapshot snap{};
						    CrashLog_GetSnapshot(&snap);
						    const bool pending = (snap.flags & CRASHLOG_FLAG_PENDING) != 0u;
						    const bool sticky = (snap.flags & CRASHLOG_FLAG_WDT_ARM_STICKY) != 0u;
						    const bool staleWatchdogHistory =
						        pending &&
						        sticky &&
						        (snap.lastFault == CRASH_FAULT_WDT_STARVE) &&
						        (snap.resetCause != CRASH_RESET_IWDG);
						    const bool pass = (!pending && (snap.lastFault == CRASH_FAULT_NONE)) || staleWatchdogHistory;
						    char metrics[224];
						    snprintf(metrics,
						             sizeof(metrics),
						             "pending=%u;sticky=%u;fault=%s;task=%s;reset=%s;boot=%lu;fault_ct=%lu;wdg_ct=%lu;sticky_ct=%lu;raw_sr=%lu;boot_stage=%s;wdg_late=%s",
						             pending ? 1u : 0u,
						             sticky ? 1u : 0u,
						             CrashLog_FaultKindName(snap.lastFault),
						             CrashLog_TaskIdName(snap.lastTask),
						             CrashLog_ResetCauseName(snap.resetCause),
						             static_cast<unsigned long>(snap.bootCount),
						             static_cast<unsigned long>(snap.faultCountTotal),
						             static_cast<unsigned long>(snap.watchdogResetCount),
						             static_cast<unsigned long>(snap.watchdogStickyCount),
						             static_cast<unsigned long>(snap.watchdogRawStatus),
						             CrashLog_BootStageName(snap.bootStage),
						             CrashLog_TaskIdName(snap.watchdogLateTask));
						    if (!runOne(1041, "crash_record_retained_safe", pass, metrics)) goto selftest_done;
						  }
						#endif

						#if (LC_WATCHDOG_SELFTEST_ENABLE != 0)
						  {
						    const WatchdogArmResult armResult = Watchdog_GetArmResult();
						    const uint32_t enabled = Watchdog_IsEnabled();
						    const uint32_t reqN = Watchdog_GetRequiredTaskCount();
						    const uint32_t liveN = Watchdog_GetLiveTaskCount();
						    const CrashTaskId lateTask = Watchdog_GetLateTask();
						    const uint32_t recoveryBoot = CrashLog_IsWatchdogRecoveryBoot();
						    const bool passArmed = (armResult == WATCHDOG_ARM_RESULT_ARMED) &&
						        (enabled == 1u) &&
						        (lateTask == CRASH_TASK_NONE) &&
						        (reqN > 0u) &&
						        (liveN == reqN);
						    const bool passStickySkip = (armResult == WATCHDOG_ARM_RESULT_SKIPPED_STICKY_STATUS) &&
						        (enabled == 0u) &&
						        (lateTask == CRASH_TASK_NONE) &&
						        (reqN == 0u) &&
						        (liveN == 0u);
						    const bool pass = passArmed || passStickySkip;
						    char metrics[192];
						    snprintf(metrics,
						             sizeof(metrics),
						             "enabled=%lu;arm_result=%s;timeout_ms=%lu;init_timeout_ms=%lu;req_n=%lu;live_n=%lu;late_task=%s;raw_sr=%lu;sticky_ct=%lu;recovery_boot=%lu",
						             static_cast<unsigned long>(enabled),
						             Watchdog_ArmResultName(armResult),
						             static_cast<unsigned long>(Watchdog_GetTimeoutMs()),
						             static_cast<unsigned long>(Watchdog_GetInitTimeoutMs()),
						             static_cast<unsigned long>(reqN),
						             static_cast<unsigned long>(liveN),
						             CrashLog_TaskIdName(lateTask),
						             static_cast<unsigned long>(Watchdog_GetRawStatus()),
						             static_cast<unsigned long>(Watchdog_GetStickyStatusCount()),
						             static_cast<unsigned long>(recoveryBoot));
						    if (!runOne(1042, "watchdog_supervisor_safe", pass, metrics)) goto selftest_done;
						  }
						#endif

						  {
						    if (!fullProfile || pressureSweepOnly) {
						      if (!runOne(2001,
						                  "motion_home_cycle_full",
						                  true,
						                  pressureSweepOnly ? "profile=FULL;executed=0;fixture_required=1;motion=0;gate=sweep_only" : "profile=SAFE;executed=0;fixture_required=1;motion=0;gate=safe_only")) {
						        goto selftest_done;
						      }
						    } else {
						      static constexpr uint32_t kHomeFastHz = 30000u;
						      static constexpr uint32_t kHomeSlowHz = 3000u;
						      static constexpr uint32_t kHomeBackoffSteps = 400u;
						      static constexpr uint32_t kHomeTimeoutMs = 20000u;
						      uint32_t homeSuccessAxes = 0u;
						      const uint32_t expectedAxes = 2u + static_cast<uint32_t>(LC_PRESSURE_PORTS);
						      const uint32_t homeStartMs = HAL_GetTick();
						      EventBits_t homeBits = BIT_HOME_X_DONE | BIT_HOME_Y_DONE | BIT_HOME_P_DONE;

						      Stepper::stepperX()->enableMotor();
						      Stepper::stepperY()->enableMotor();
						      Stepper::stepperP()->enableMotor();
						#if (LC_PRESSURE_PORTS > 1)
						      Stepper::stepperR()->enableMotor();
						      homeBits |= BIT_HOME_R_DONE;
						#endif

						      xEventGroupClearBits(_doneEvents, homeBits);
						      startHomeAsync(Stepper::stepperX(), kHomeFastHz, kHomeSlowHz, kHomeBackoffSteps, BIT_HOME_X_DONE);
						      startHomeAsync(Stepper::stepperY(), kHomeFastHz, kHomeSlowHz, kHomeBackoffSteps, BIT_HOME_Y_DONE);
						      startRegHomeAsync(&PressureRegulator::regP(), kHomeFastHz, kHomeSlowHz, kHomeBackoffSteps, BIT_HOME_P_DONE);
						#if (LC_PRESSURE_PORTS > 1)
						      startRegHomeAsync(&PressureRegulator::regR(), kHomeFastHz, kHomeSlowHz, kHomeBackoffSteps, BIT_HOME_R_DONE);
						#endif
						      const bool homeCompleted = waitBitsWithTimeout(homeBits, kHomeTimeoutMs);

						      if (isHomedPosition(Stepper::stepperX()->getPosition())) homeSuccessAxes++;
						      if (isHomedPosition(Stepper::stepperY()->getPosition())) homeSuccessAxes++;
						      if (isHomedPosition(Stepper::stepperP()->getPosition())) homeSuccessAxes++;
						#if (LC_PRESSURE_PORTS > 1)
						      if (isHomedPosition(Stepper::stepperR()->getPosition())) homeSuccessAxes++;
						#endif

						      const uint32_t homeTimeMs = HAL_GetTick() - homeStartMs;
						      const uint32_t limitHits = homeSuccessAxes;
						      const bool homePass = homeCompleted && (homeSuccessAxes == expectedAxes);
						      fullHomePass = homePass;
						      char metrics[96];
						      snprintf(metrics, sizeof(metrics),
						               "home_time_ms=%lu;home_success_axes=%lu;limit_hits=%lu",
						               static_cast<unsigned long>(homeTimeMs),
						               static_cast<unsigned long>(homeSuccessAxes),
						               static_cast<unsigned long>(limitHits));
						      if (!runOne(2001, "motion_home_cycle_full", homePass, metrics)) goto selftest_done;
						      if (!homePass) goto selftest_done;
						    }
						  }

						  {
						    if (!fullProfile || pressureSweepOnly) {
						      if (!runOne(2002,
						                  "motion_absolute_move_bounds_full",
						                  true,
						                  pressureSweepOnly ? "profile=FULL;executed=0;fixture_required=1;motion=0;gate=sweep_only" : "profile=SAFE;executed=0;fixture_required=1;motion=0;gate=safe_only")) {
						        goto selftest_done;
						      }
						    } else if (!fullHomePass) {
						      if (!runOne(2002,
						                  "motion_absolute_move_bounds_full",
						                  false,
						                  "target_x=400;target_y=400;target_z=0;final_error_steps=0;bound_violation=1")) {
						        goto selftest_done;
						      }
						    } else {
						      static constexpr int32_t kTargetX = 400;
						      static constexpr int32_t kTargetY = 400;
						      static constexpr int32_t kTargetZ = 0;
						      static constexpr uint32_t kMoveFeedHz = 4000u;
						      const int32_t homeX = Stepper::stepperX()->getPosition();
						      const int32_t homeY = Stepper::stepperY()->getPosition();
						      bool boundViolation = false;
						      uint32_t finalErrorSteps = 0u;

						      xEventGroupClearBits(_doneEvents, BIT_STEPPER1_DONE | BIT_STEPPER2_DONE);
						      Gantry::instance()->moveTo(kTargetX, kTargetY, kMoveFeedHz);
						      const bool reachedTarget = waitForBit(BIT_STEPPER1_DONE) && waitForBit(BIT_STEPPER2_DONE);
						      const GantryPosition targetPos = Gantry::instance()->getPosition();
						      const uint32_t targetErrorX = absDiff32(targetPos.x, kTargetX);
						      const uint32_t targetErrorY = absDiff32(targetPos.y, kTargetY);
						      finalErrorSteps = (targetErrorX > targetErrorY) ? targetErrorX : targetErrorY;
						      boundViolation = (targetPos.x < 0) || (targetPos.y < 0) ||
						                       (targetPos.x > (kTargetX + 50)) || (targetPos.y > (kTargetY + 50));

						      xEventGroupClearBits(_doneEvents, BIT_STEPPER1_DONE | BIT_STEPPER2_DONE);
						      Gantry::instance()->moveTo(homeX, homeY, kMoveFeedHz);
						      const bool returnedHome = waitForBit(BIT_STEPPER1_DONE) && waitForBit(BIT_STEPPER2_DONE);
						      const GantryPosition returnPos = Gantry::instance()->getPosition();
						      const uint32_t returnErrorX = absDiff32(returnPos.x, homeX);
						      const uint32_t returnErrorY = absDiff32(returnPos.y, homeY);
						      const uint32_t returnError = (returnErrorX > returnErrorY) ? returnErrorX : returnErrorY;
						      if (returnError > finalErrorSteps) finalErrorSteps = returnError;
						      boundViolation = boundViolation ||
						                       (returnPos.x < 0) || (returnPos.y < 0) ||
						                       (returnPos.x > (kTargetX + 50)) || (returnPos.y > (kTargetY + 50));

						      const bool movePass = reachedTarget && returnedHome && !boundViolation && (finalErrorSteps <= 4u);
						      char metrics[96];
						      snprintf(metrics, sizeof(metrics),
						               "target_x=%ld;target_y=%ld;target_z=%ld;final_error_steps=%lu;bound_violation=%u",
						               static_cast<long>(kTargetX),
						               static_cast<long>(kTargetY),
						               static_cast<long>(kTargetZ),
						               static_cast<unsigned long>(finalErrorSteps),
						               static_cast<unsigned>(boundViolation ? 1u : 0u));
						      if (!runOne(2002, "motion_absolute_move_bounds_full", movePass, metrics)) goto selftest_done;
						    }
						  }

						  {
						    if (!fullProfile || pressureSweepOnly) {
						      if (!runOne(2003,
						                  "pressure_regulator_step_response_full",
						                  true,
						                  pressureSweepOnly ? "profile=FULL;executed=0;fixture_required=1;pressure=0;gate=sweep_only" : "profile=SAFE;executed=0;fixture_required=1;pressure=0;gate=safe_only")) {
						        goto selftest_done;
						      }
						    } else if (!fullHomePass) {
						      if (!runOne(2003,
						                  "pressure_regulator_step_response_full",
						                  false,
						                  "target_pressure=0;settle_time_ms=0;overshoot=0;steady_state_error=0")) {
						        goto selftest_done;
						      }
						    } else {
						      static constexpr uint32_t kBaselineTimeoutMs = 3000u;
						      static constexpr uint32_t kSettleTimeoutMs = 4000u;
						      static constexpr int32_t kPressureDelta = 200;
						      PressureSensor* sensor = PressureSensor::instance();
						      PressureRegulator& reg = PressureRegulator::regP();
						      const int32_t baselineTarget = static_cast<int32_t>(reg.getTarget());
						      int32_t targetPressure = baselineTarget + kPressureDelta;
						      bool stepUp = true;
						      if (targetPressure > 5600) {
						        targetPressure = baselineTarget - kPressureDelta;
						        stepUp = false;
						      }
						      uint32_t settleTimeMs = kSettleTimeoutMs;
						      uint32_t overshoot = 0u;
						      uint32_t steadyStateError = 0u;
						      bool pressurePass = false;

						      if (sensor && targetPressure != baselineTarget) {
						        reg.start();
						        xEventGroupClearBits(_doneEvents, BIT_PRESSURE_P_READY);
						        uint32_t baselineSettleMs = 0u;
						        uint32_t baselineOvershoot = 0u;
						        uint32_t baselineError = 0u;
						        const bool baselineReady = waitPressureReady(reg,
						                                                0u,
						                                                baselineTarget,
						                                                true,
						                                                kBaselineTimeoutMs,
						                                                baselineSettleMs,
						                                                baselineOvershoot,
						                                                baselineError);
						        xEventGroupClearBits(_doneEvents, BIT_PRESSURE_P_READY);
						        reg.setTargetSafe(targetPressure);
						        targetPressure = static_cast<int32_t>(reg.getTarget());
						        pressurePass = baselineReady &&
						                       waitPressureReady(reg,
						                                         0u,
						                                         targetPressure,
						                                         stepUp,
						                                         kSettleTimeoutMs,
						                                         settleTimeMs,
						                                         overshoot,
						                                         steadyStateError);
						        xEventGroupClearBits(_doneEvents, BIT_PRESSURE_P_READY);
						        reg.setTargetSafe(baselineTarget);
						        uint32_t restoreSettleMs = 0u;
						        uint32_t restoreOvershoot = 0u;
						        uint32_t restoreError = 0u;
						        (void)waitPressureReady(reg,
						                                0u,
						                                baselineTarget,
						                                !stepUp,
						                                kSettleTimeoutMs,
						                                restoreSettleMs,
						                                restoreOvershoot,
						                                restoreError);
						        reg.pause();
						      }

						      pressurePass = pressurePass && (steadyStateError <= 120u) && (overshoot <= 300u);
						      char metrics[96];
						      snprintf(metrics, sizeof(metrics),
						               "target_pressure=%ld;settle_time_ms=%lu;overshoot=%lu;steady_state_error=%lu",
						               static_cast<long>(targetPressure),
						               static_cast<unsigned long>(settleTimeMs),
						               static_cast<unsigned long>(overshoot),
						               static_cast<unsigned long>(steadyStateError));
						      if (!runOne(2003, "pressure_regulator_step_response_full", pressurePass, metrics)) goto selftest_done;
						    }
						  }

						  {
						    if (!fullProfile || pressureSweepOnly) {
						      if (!runOne(2004,
						                  "valve_actuation_sequence_full",
						                  true,
						                  pressureSweepOnly ? "profile=FULL;executed=0;fixture_required=1;valves=0;gate=sweep_only" : "profile=SAFE;executed=0;fixture_required=1;valves=0;gate=safe_only")) {
						        goto selftest_done;
						      }
						    } else if (!fullHomePass) {
						      if (!runOne(2004,
						                  "valve_actuation_sequence_full",
						                  false,
						                  "valve_open_count=0;valve_close_count=0;sequence_order_ok=0")) {
						        goto selftest_done;
						      }
						    } else {
						      uint32_t openCount = 0u;
						      uint32_t closeCount = 0u;
						      bool sequenceOrderOk = true;

						      PressureRegulator::regP().openValve();
						      openCount++;
						      sequenceOrderOk = sequenceOrderOk && PressureRegulator::regP().isValveOpen();
						      vTaskDelay(pdMS_TO_TICKS(10));
						      PressureRegulator::regP().closeValve();
						      closeCount++;
						      sequenceOrderOk = sequenceOrderOk && !PressureRegulator::regP().isValveOpen();

						#if (LC_PRESSURE_PORTS > 1)
						      PressureRegulator::regR().openValve();
						      openCount++;
						      sequenceOrderOk = sequenceOrderOk && PressureRegulator::regR().isValveOpen();
						      vTaskDelay(pdMS_TO_TICKS(10));
						      PressureRegulator::regR().closeValve();
						      closeCount++;
						      sequenceOrderOk = sequenceOrderOk && !PressureRegulator::regR().isValveOpen();
						#endif

						      const bool valvePass = sequenceOrderOk && (openCount == closeCount);
						      char metrics[96];
						      snprintf(metrics, sizeof(metrics),
						               "valve_open_count=%lu;valve_close_count=%lu;sequence_order_ok=%u",
						               static_cast<unsigned long>(openCount),
						               static_cast<unsigned long>(closeCount),
						               static_cast<unsigned>(sequenceOrderOk ? 1u : 0u));
						      if (!runOne(2004, "valve_actuation_sequence_full", valvePass, metrics)) goto selftest_done;
						    }
						  }

						  {
						    if (!fullProfile || pressureSweepOnly) {
						      if (!runOne(2005,
						                  "print_refuel_pulse_integrity_full",
						                  true,
						                  pressureSweepOnly ? "profile=FULL;executed=0;fixture_required=1;pulses=0;gate=sweep_only" : "profile=SAFE;executed=0;fixture_required=1;pulses=0;gate=safe_only")) {
						        goto selftest_done;
						      }
						    } else if (!fullHomePass) {
						      if (!runOne(2005,
						                  "print_refuel_pulse_integrity_full",
						                  false,
						                  "pulse_count=0;pulse_width_min_ns=0;pulse_width_max_ns=0")) {
						        goto selftest_done;
						      }
						    } else {
						      Printer* printer = Printer::instance();
						      uint32_t pulseCount = 0u;
						      uint32_t pulseWidthMinNs = 0u;
						      uint32_t pulseWidthMaxNs = 0u;
						      bool pulsePass = false;

						      if (printer != nullptr) {
						        const uint32_t printPulseNs = printer->getPrintPulse() * 1000u;
						#if (LC_PRESSURE_PORTS > 1)
						        const uint32_t refuelPulseNs = printer->getRefuelPulse() * 1000u;
						#else
						        const uint32_t refuelPulseNs = printPulseNs;
						#endif
						        pulseWidthMinNs = (printPulseNs < refuelPulseNs) ? printPulseNs : refuelPulseNs;
						        pulseWidthMaxNs = (printPulseNs > refuelPulseNs) ? printPulseNs : refuelPulseNs;

						        printer->pulsePrint();
						        pulseCount++;
						        vTaskDelay(pdMS_TO_TICKS(5));
						#if (LC_PRESSURE_PORTS > 1)
						        printer->pulseRefuel();
						        pulseCount++;
						        vTaskDelay(pdMS_TO_TICKS(5));
						#endif
						        pulsePass = (pulseCount >= 1u) && (pulseWidthMinNs > 0u) && (pulseWidthMaxNs >= pulseWidthMinNs);
						      }

						      char metrics[96];
						      snprintf(metrics, sizeof(metrics),
						               "pulse_count=%lu;pulse_width_min_ns=%lu;pulse_width_max_ns=%lu",
						               static_cast<unsigned long>(pulseCount),
						               static_cast<unsigned long>(pulseWidthMinNs),
						               static_cast<unsigned long>(pulseWidthMaxNs));
						      if (!runOne(2005, "print_refuel_pulse_integrity_full", pulsePass, metrics)) goto selftest_done;
						    }
						  }

						  {
						    if (!fullProfile || pressureSweepOnly) {
						      if (!runOne(2006,
						                  "emergency_abort_and_safe_stop_full",
						                  true,
						                  pressureSweepOnly ? "profile=FULL;executed=0;fixture_required=1;abort=0;gate=sweep_only" : "profile=SAFE;executed=0;fixture_required=1;abort=0;gate=safe_only")) {
						        goto selftest_done;
						      }
						    } else if (!fullHomePass) {
						      if (!runOne(2006,
						                  "emergency_abort_and_safe_stop_full",
						                  false,
						                  "abort_latency_ms=0;motors_disabled=0;regulators_stopped=0;valves_safe_state=0")) {
						        goto selftest_done;
						      }
						    } else {
						      static constexpr uint32_t kAbortMoveSteps = 200u;
						      static constexpr uint32_t kAbortMoveHz = 4000u;
						      static constexpr uint32_t kAbortLatencyLimitMs = 1000u;
						      PressureRegulator::regP().start();
						      Stepper::stepperX()->enableMotor();
						      Stepper::stepperX()->move(true, kAbortMoveSteps, kAbortMoveHz, 0u);
						      const uint32_t abortStartMs = HAL_GetTick();
						      performShutdown(outSeq8, runId, true);
						      const uint32_t abortLatencyMs = HAL_GetTick() - abortStartMs;
						      const bool motorsDisabled = areMotorsDisabled();
						      const bool regulatorsStopped = areRegulatorsStopped();
						      const bool valvesSafeState = areValvesClosed();
						      const bool abortPass = (abortLatencyMs <= kAbortLatencyLimitMs) &&
						                             motorsDisabled &&
						                             regulatorsStopped &&
						                             valvesSafeState;
						      char metrics[96];
						      snprintf(metrics, sizeof(metrics),
						               "abort_latency_ms=%lu;motors_disabled=%u;regulators_stopped=%u;valves_safe_state=%u",
						               static_cast<unsigned long>(abortLatencyMs),
						               static_cast<unsigned>(motorsDisabled ? 1u : 0u),
						               static_cast<unsigned>(regulatorsStopped ? 1u : 0u),
						               static_cast<unsigned>(valvesSafeState ? 1u : 0u));
						      if (!runOne(2006, "emergency_abort_and_safe_stop_full", abortPass, metrics)) goto selftest_done;
						    }
						  }

                          {
                          struct SweepParamSet {
                            uint8_t paramId;
                            PressureRegulator::RecoveryConfig printRecovery;
                            PressureRegulator::SlewConfig printSlew;
                            PressureRegulator::RecoveryConfig refuelRecovery;
                            PressureRegulator::SlewConfig refuelSlew;
                          };

                          struct SweepScenario {
                            uint8_t scenarioId;
                            uint8_t channel;
                            uint16_t targetRaw;
                            uint16_t secondaryTargetRaw;
                            uint16_t pulseUs;
                            uint16_t secondaryPulseUs;
                            uint16_t droplets;
                            uint16_t hz;
                            PulseMode mode;
                            bool requireBothReady;
                            uint8_t modeCode;
                          };

                          auto computeSweepScore = [&](const PressureTraceCaseMetrics& m) -> uint32_t {
                            return (1000u * m.readyMissCount) +
                                   (4u * m.maxDeadlineSlipMs) +
                                   (2u * m.worstRecoveryMs) +
                                   m.maxOvershoot +
                                   m.maxUndershoot +
                                   m.zeroCrossCount;
                          };

                          auto shouldExportSweepTrace = [&](const PressureTraceCaseMetrics& m) -> bool {
                            return (m.readyMissCount > 0u) ||
                                   (m.maxDeadlineSlipMs > 120u) ||
                                   (m.maxOvershoot > 20u) ||
                                   (m.maxUndershoot > 40u);
                          };

                          auto runPressureSweepSuite = [&](uint16_t suiteId) -> bool {
                            const bool isCoreSuite = (suiteId == 2301u);
                            const bool isExtendedSuite = (suiteId == 2302u);
                            const bool isFocusedSuite = (suiteId == 2303u);
                            const bool isMicroSuite = (suiteId == 2304u);
                            const uint16_t suiteSummaryTestId = isCoreSuite ? 2391u : (isExtendedSuite ? 2491u : (isFocusedSuite ? 2591u : 2691u));
                            const char* suiteSummaryName = isCoreSuite ? "pressure_sweep_summary_s2301"
                                                                       : (isExtendedSuite ? "pressure_sweep_summary_s2302"
                                                                                          : (isFocusedSuite ? "pressure_sweep_summary_s2303"
                                                                                                           : "pressure_sweep_summary_s2304"));
                            if (!fullProfile) {
                              return runOne(suiteSummaryTestId,
                                            suiteSummaryName,
                                            true,
                                            "suite=0;combos=0;pass_combo_count=0;best_param=0;best_score=0;worst_score=0;trace_exported_count=0");
                            }
                            if (!fullHomePass) {
                              return runOne(suiteSummaryTestId,
                                            suiteSummaryName,
                                            false,
                                            "suite=0;combos=0;pass_combo_count=0;best_param=0;best_score=0;worst_score=0;trace_exported_count=0");
                            }

                            PressureRegulator& regP = PressureRegulator::regP();
#if (LC_PRESSURE_PORTS > 1)
                            PressureRegulator& regR = PressureRegulator::regR();
#endif
                            const PressureRegulator::RecoveryConfig baselinePrintRecovery = regP.getRecoveryConfig();
                            const PressureRegulator::SlewConfig baselinePrintSlew = regP.getSlewConfig();
#if (LC_PRESSURE_PORTS > 1)
                            const PressureRegulator::RecoveryConfig baselineRefuelRecovery = regR.getRecoveryConfig();
                            const PressureRegulator::SlewConfig baselineRefuelSlew = regR.getSlewConfig();
#else
                            const PressureRegulator::RecoveryConfig baselineRefuelRecovery = baselinePrintRecovery;
                            const PressureRegulator::SlewConfig baselineRefuelSlew = baselinePrintSlew;
#endif

                            auto applyParamSet = [&](const SweepParamSet& set) {
                              regP.setRecoveryConfig(set.printRecovery);
                              regP.setSlewConfig(set.printSlew);
#if (LC_PRESSURE_PORTS > 1)
                              regR.setRecoveryConfig(set.refuelRecovery);
                              regR.setSlewConfig(set.refuelSlew);
#endif
                            };

                            auto restoreBaseline = [&]() {
                              regP.setRecoveryConfig(baselinePrintRecovery);
                              regP.setSlewConfig(baselinePrintSlew);
#if (LC_PRESSURE_PORTS > 1)
                              regR.setRecoveryConfig(baselineRefuelRecovery);
                              regR.setSlewConfig(baselineRefuelSlew);
#endif
                            };

                            SweepParamSet params[10]{};
                            uint16_t paramCount = 0u;

                            if (!(isFocusedSuite || isMicroSuite)) {
                              params[paramCount++] = SweepParamSet{
                                  0u, baselinePrintRecovery, baselinePrintSlew, baselineRefuelRecovery, baselineRefuelSlew};
                            }

                            auto p2PrintRecovery = baselinePrintRecovery;
                            p2PrintRecovery.activeTicks = 4u;
                            p2PrintRecovery.baseBoostHz = 500u;
                            p2PrintRecovery.maxBoostHz = 2500u;
                            p2PrintRecovery.maxExtendTicks = 2u;
                            p2PrintRecovery.allowExtendWhileUndershoot = true;
                            auto p2PrintSlew = baselinePrintSlew;
                            p2PrintSlew.maxHzDeltaUpPerLoop = 900u;
                            p2PrintSlew.maxHzDeltaDownPerLoop = 900u;
                            p2PrintSlew.recoveryBypassSlewTicks = 1u;
                            if (!(isFocusedSuite || isMicroSuite)) {
                              params[paramCount++] = SweepParamSet{
                                  2u, p2PrintRecovery, p2PrintSlew, baselineRefuelRecovery, baselineRefuelSlew};
                            }

                            if (isExtendedSuite || isFocusedSuite || isMicroSuite) {
                              auto p1PrintRecovery = baselinePrintRecovery;
                              p1PrintRecovery.activeTicks = 2u;
                              p1PrintRecovery.baseBoostHz = 250u;
                              p1PrintRecovery.pulseCoeffHzPerUs = 1u;
                              p1PrintRecovery.maxBoostHz = 1200u;
                              p1PrintRecovery.maxExtendTicks = 0u;
                              p1PrintRecovery.allowExtendWhileUndershoot = false;
                              auto p1PrintSlew = baselinePrintSlew;
                              p1PrintSlew.maxHzDeltaUpPerLoop = 500u;
                              p1PrintSlew.maxHzDeltaDownPerLoop = 1100u;
                              p1PrintSlew.recoveryBypassSlewTicks = 0u;
                              params[paramCount++] = SweepParamSet{
                                  1u, p1PrintRecovery, p1PrintSlew, baselineRefuelRecovery, baselineRefuelSlew};

                              if (isExtendedSuite) {
                                auto p3PrintRecovery = baselinePrintRecovery;
                                p3PrintRecovery.activeTicks = 0u;
                                p3PrintRecovery.baseBoostHz = 0u;
                                p3PrintRecovery.pulseCoeffHzPerUs = 0u;
                                p3PrintRecovery.pressureCoeffHzPerRaw = 0u;
                                p3PrintRecovery.maxBoostHz = 0u;
                                auto p3PrintSlew = baselinePrintSlew;
                                params[paramCount++] = SweepParamSet{
                                    3u, p3PrintRecovery, p3PrintSlew, baselineRefuelRecovery, baselineRefuelSlew};

                                // Promote micro-sweep winner (param 11) into full 2302 coverage.
                                auto p11PrintRecovery = baselinePrintRecovery;
                                p11PrintRecovery.activeTicks = 2u;
                                p11PrintRecovery.baseBoostHz = 350u;
                                p11PrintRecovery.maxBoostHz = 1700u;
                                auto p11RefuelRecovery = baselineRefuelRecovery;
                                p11RefuelRecovery.activeTicks = 6u;
                                p11RefuelRecovery.baseBoostHz = baselineRefuelRecovery.baseBoostHz + 350u;
                                p11RefuelRecovery.maxBoostHz = baselineRefuelRecovery.maxBoostHz + 900u;
                                p11RefuelRecovery.maxExtendTicks = 1u;
                                auto p11PrintSlew = baselinePrintSlew;
                                p11PrintSlew.maxHzDeltaUpPerLoop = 650u;
                                p11PrintSlew.maxHzDeltaDownPerLoop = 950u;
                                auto p11RefuelSlew = baselineRefuelSlew;
                                p11RefuelSlew.maxHzDeltaUpPerLoop = baselineRefuelSlew.maxHzDeltaUpPerLoop + 300u;
                                p11RefuelSlew.maxHzDeltaDownPerLoop = baselineRefuelSlew.maxHzDeltaDownPerLoop + 200u;
                                params[paramCount++] = SweepParamSet{
                                    11u, p11PrintRecovery, p11PrintSlew, p11RefuelRecovery, p11RefuelSlew};
                              }

                              auto p5PrintRecovery = baselinePrintRecovery;
                              p5PrintRecovery.activeTicks = 2u;
                              p5PrintRecovery.baseBoostHz = 350u;
                              p5PrintRecovery.maxBoostHz = 1700u;
                              auto p5RefuelRecovery = baselineRefuelRecovery;
                              p5RefuelRecovery.activeTicks = 6u;
                              p5RefuelRecovery.baseBoostHz = baselineRefuelRecovery.baseBoostHz;
                              p5RefuelRecovery.maxBoostHz = baselineRefuelRecovery.maxBoostHz;
                              p5RefuelRecovery.maxExtendTicks = 1u;
                              auto p5PrintSlew = baselinePrintSlew;
                              p5PrintSlew.maxHzDeltaUpPerLoop = 650u;
                              p5PrintSlew.maxHzDeltaDownPerLoop = 950u;
                              auto p5RefuelSlew = baselineRefuelSlew;
                              p5RefuelSlew.maxHzDeltaUpPerLoop = baselineRefuelSlew.maxHzDeltaUpPerLoop;
                              p5RefuelSlew.maxHzDeltaDownPerLoop = baselineRefuelSlew.maxHzDeltaDownPerLoop + 200u;
                              params[paramCount++] = SweepParamSet{
                                  5u, p5PrintRecovery, p5PrintSlew, p5RefuelRecovery, p5RefuelSlew};

                              if (isFocusedSuite) {
                                // Focused variants around the best-performing param 1 for scenarios 2/6/8.
                                auto p6PrintRecovery = p1PrintRecovery;
                                auto p6PrintSlew = p1PrintSlew;
                                auto p6RefuelRecovery = baselineRefuelRecovery;
                                p6RefuelRecovery.activeTicks = baselineRefuelRecovery.activeTicks + 2u;
                                p6RefuelRecovery.baseBoostHz = baselineRefuelRecovery.baseBoostHz + 600u;
                                p6RefuelRecovery.maxBoostHz = baselineRefuelRecovery.maxBoostHz + 1500u;
                                p6RefuelRecovery.maxExtendTicks = baselineRefuelRecovery.maxExtendTicks + 1u;
                                auto p6RefuelSlew = baselineRefuelSlew;
                                p6RefuelSlew.maxHzDeltaUpPerLoop = baselineRefuelSlew.maxHzDeltaUpPerLoop + 500u;
                                p6RefuelSlew.maxHzDeltaDownPerLoop = baselineRefuelSlew.maxHzDeltaDownPerLoop;
                                params[paramCount++] = SweepParamSet{
                                    6u, p6PrintRecovery, p6PrintSlew, p6RefuelRecovery, p6RefuelSlew};

                                auto p7PrintRecovery = p1PrintRecovery;
                                p7PrintRecovery.activeTicks = 3u;
                                p7PrintRecovery.baseBoostHz = 350u;
                                p7PrintRecovery.maxBoostHz = 1600u;
                                auto p7PrintSlew = p1PrintSlew;
                                p7PrintSlew.maxHzDeltaUpPerLoop = 700u;
                                p7PrintSlew.maxHzDeltaDownPerLoop = 900u;
                                auto p7RefuelRecovery = p6RefuelRecovery;
                                p7RefuelRecovery.activeTicks = p6RefuelRecovery.activeTicks + 1u;
                                p7RefuelRecovery.baseBoostHz = p6RefuelRecovery.baseBoostHz + 300u;
                                p7RefuelRecovery.maxBoostHz = p6RefuelRecovery.maxBoostHz + 1000u;
                                auto p7RefuelSlew = p6RefuelSlew;
                                p7RefuelSlew.maxHzDeltaUpPerLoop = p6RefuelSlew.maxHzDeltaUpPerLoop + 300u;
                                params[paramCount++] = SweepParamSet{
                                    7u, p7PrintRecovery, p7PrintSlew, p7RefuelRecovery, p7RefuelSlew};
                              }

                              if (isMicroSuite) {
                                // Micro-variants around p1/p5 with small refuel-only deltas.
                                auto p8PrintRecovery = p1PrintRecovery;
                                auto p8PrintSlew = p1PrintSlew;
                                auto p8RefuelRecovery = baselineRefuelRecovery;
                                p8RefuelRecovery.baseBoostHz = baselineRefuelRecovery.baseBoostHz + 250u;
                                p8RefuelRecovery.maxBoostHz = baselineRefuelRecovery.maxBoostHz + 600u;
                                auto p8RefuelSlew = baselineRefuelSlew;
                                p8RefuelSlew.maxHzDeltaUpPerLoop = baselineRefuelSlew.maxHzDeltaUpPerLoop + 200u;
                                params[paramCount++] = SweepParamSet{
                                    8u, p8PrintRecovery, p8PrintSlew, p8RefuelRecovery, p8RefuelSlew};

                                auto p9PrintRecovery = p1PrintRecovery;
                                auto p9PrintSlew = p1PrintSlew;
                                auto p9RefuelRecovery = baselineRefuelRecovery;
                                p9RefuelRecovery.baseBoostHz = baselineRefuelRecovery.baseBoostHz + 450u;
                                p9RefuelRecovery.maxBoostHz = baselineRefuelRecovery.maxBoostHz + 1000u;
                                auto p9RefuelSlew = baselineRefuelSlew;
                                p9RefuelSlew.maxHzDeltaUpPerLoop = baselineRefuelSlew.maxHzDeltaUpPerLoop + 350u;
                                params[paramCount++] = SweepParamSet{
                                    9u, p9PrintRecovery, p9PrintSlew, p9RefuelRecovery, p9RefuelSlew};

                                auto p10PrintRecovery = p5PrintRecovery;
                                auto p10PrintSlew = p5PrintSlew;
                                auto p10RefuelRecovery = p5RefuelRecovery;
                                p10RefuelRecovery.baseBoostHz = p5RefuelRecovery.baseBoostHz + 200u;
                                p10RefuelRecovery.maxBoostHz = p5RefuelRecovery.maxBoostHz + 500u;
                                auto p10RefuelSlew = p5RefuelSlew;
                                p10RefuelSlew.maxHzDeltaUpPerLoop = p5RefuelSlew.maxHzDeltaUpPerLoop + 150u;
                                params[paramCount++] = SweepParamSet{
                                    10u, p10PrintRecovery, p10PrintSlew, p10RefuelRecovery, p10RefuelSlew};

                                auto p11PrintRecovery = p5PrintRecovery;
                                auto p11PrintSlew = p5PrintSlew;
                                auto p11RefuelRecovery = p5RefuelRecovery;
                                p11RefuelRecovery.baseBoostHz = p5RefuelRecovery.baseBoostHz + 350u;
                                p11RefuelRecovery.maxBoostHz = p5RefuelRecovery.maxBoostHz + 900u;
                                auto p11RefuelSlew = p5RefuelSlew;
                                p11RefuelSlew.maxHzDeltaUpPerLoop = p5RefuelSlew.maxHzDeltaUpPerLoop + 300u;
                                params[paramCount++] = SweepParamSet{
                                    11u, p11PrintRecovery, p11PrintSlew, p11RefuelRecovery, p11RefuelSlew};
                              }
                            }

                            SweepScenario scenarios[8]{};
                            uint16_t scenarioCount = 0u;
                            if (isExtendedSuite) {
                              scenarios[scenarioCount++] = SweepScenario{2u, 0u, psiToRaw(1000u), 0u, 1300u, 0u, 10u, 20u, PulseMode::PRINT_ONLY, false, 0u};
                              scenarios[scenarioCount++] = SweepScenario{3u, 0u, psiToRaw(1200u), 0u, 1800u, 0u, 10u, 20u, PulseMode::PRINT_ONLY, false, 0u};
                              scenarios[scenarioCount++] = SweepScenario{4u, 1u, psiToRaw(500u), 0u, 3000u, 0u, 10u, 20u, PulseMode::REFUEL_ONLY, false, 1u};
                              scenarios[scenarioCount++] = SweepScenario{6u, 0u, psiToRaw(1000u), psiToRaw(500u), 1300u, 3000u, 10u, 20u, PulseMode::BOTH, true, 2u};
                              scenarios[scenarioCount++] = SweepScenario{1u, 0u, psiToRaw(600u), 0u, 1300u, 0u, 10u, 20u, PulseMode::PRINT_ONLY, false, 0u};
                              scenarios[scenarioCount++] = SweepScenario{5u, 1u, psiToRaw(600u), 0u, 3000u, 0u, 10u, 20u, PulseMode::REFUEL_ONLY, false, 1u};
                              scenarios[scenarioCount++] = SweepScenario{7u, 0u, psiToRaw(800u), 0u, 1500u, 0u, 12u, 25u, PulseMode::PRINT_ONLY, false, 0u};
                              scenarios[scenarioCount++] = SweepScenario{8u, 1u, psiToRaw(450u), 0u, 3200u, 0u, 12u, 25u, PulseMode::REFUEL_ONLY, false, 1u};
                            } else if (isFocusedSuite || isMicroSuite) {
                              // Focused high-value scenarios: print guard, dual coupling, and refuel high-slip.
                              scenarios[scenarioCount++] = SweepScenario{2u, 0u, psiToRaw(1000u), 0u, 1300u, 0u, 10u, 20u, PulseMode::PRINT_ONLY, false, 0u};
                              scenarios[scenarioCount++] = SweepScenario{6u, 0u, psiToRaw(1000u), psiToRaw(500u), 1300u, 3000u, 10u, 20u, PulseMode::BOTH, true, 2u};
                              scenarios[scenarioCount++] = SweepScenario{8u, 1u, psiToRaw(450u), 0u, 3200u, 0u, 12u, 25u, PulseMode::REFUEL_ONLY, false, 1u};
                            } else {
                              // 120s rapid suite: one high-stress print case, compare params directly.
                              scenarios[scenarioCount++] = SweepScenario{3u, 0u, psiToRaw(1200u), 0u, 1800u, 0u, 10u, 20u, PulseMode::PRINT_ONLY, false, 0u};
                            }

                            const uint16_t comboBaseTestId = isCoreSuite ? 2310u : (isExtendedSuite ? 2410u : (isFocusedSuite ? 2510u : 2610u));
                            uint16_t comboIndex = 0u;
                            uint16_t passComboCount = 0u;
                            uint16_t traceExportedCount = 0u;
                            // Extended 2302 is metrics-first under tight runtime budgets; raw trace export
                            // is disabled here to avoid transport instability during large chunk bursts.
                            const uint16_t traceExportBudget = isExtendedSuite ? 0u : ((isFocusedSuite || isMicroSuite) ? 3u : 0xFFFFu);
                            const uint32_t comboSoftTimeoutMs = isExtendedSuite ? 16000u : ((isFocusedSuite || isMicroSuite) ? 14000u : 12000u);
                            const uint32_t suiteBudgetMs = isExtendedSuite ? 110000u : 0u;
                            const uint32_t suiteStartMs = HAL_GetTick();
                            bool suiteTimedOut = false;
                            uint32_t bestScore = 0xFFFFFFFFu;
                            uint32_t worstScore = 0u;
                            uint8_t bestParam = 0u;

                            for (uint16_t p = 0u; p < paramCount; ++p) {
                              char paramStage[32];
                              snprintf(paramStage, sizeof(paramStage), "sw_param_p%u",
                                       static_cast<unsigned>(params[p].paramId));
                              sendProgressStage(paramStage);
                              applyParamSet(params[p]);
                              for (uint16_t s = 0u; s < scenarioCount; ++s) {
                                if ((suiteBudgetMs > 0u) && ((HAL_GetTick() - suiteStartMs) >= suiteBudgetMs)) {
                                  suiteTimedOut = true;
                                  sendProgressStage("sw_suite_budget_to");
                                  break;
                                }
                                maybeSendProgress("sweep_combo");
                                PressureTraceCaseMetrics caseMetrics{};
                                const uint16_t comboTestId = static_cast<uint16_t>(comboBaseTestId + comboIndex);
                                char comboName[40];
                                snprintf(comboName, sizeof(comboName), "pressure_sweep_s%u_p%u_c%u",
                                         static_cast<unsigned>(suiteId),
                                         static_cast<unsigned>(params[p].paramId),
                                         static_cast<unsigned>(scenarios[s].scenarioId));
                                char comboStage[32];
                                snprintf(comboStage, sizeof(comboStage), "sw_cstart_p%u_c%u",
                                         static_cast<unsigned>(params[p].paramId),
                                         static_cast<unsigned>(scenarios[s].scenarioId));
                                sendProgressStage(comboStage);
                                const uint32_t comboStartMs = HAL_GetTick();
                                const bool executed = runPressureTraceCase(comboTestId,
                                                                           comboName,
                                                                           scenarios[s].channel,
                                                                           scenarios[s].targetRaw,
                                                                           scenarios[s].pulseUs,
                                                                           scenarios[s].droplets,
                                                                           scenarios[s].hz,
                                                                           scenarios[s].mode,
                                                                           scenarios[s].requireBothReady,
                                                                           scenarios[s].secondaryTargetRaw,
                                                                           scenarios[s].secondaryPulseUs,
                                                                           &caseMetrics,
                                                                           false,
                                                                           false);
                                if (!executed) {
                                  sendProgressStage("sw_combo_exec_fail");
                                  restoreBaseline();
                                  return false;
                                }
                                const uint32_t comboElapsedMs = HAL_GetTick() - comboStartMs;
                                const bool comboTimedOut = comboElapsedMs > comboSoftTimeoutMs;
                                if (comboTimedOut) {
                                  sendProgressStage("sw_combo_soft_to");
                                }

                                const bool comboPass = caseMetrics.pass && !comboTimedOut;
                                if (comboPass) {
                                  passComboCount++;
                                }
                                const uint32_t score = computeSweepScore(caseMetrics);
                                if (score < bestScore) {
                                  bestScore = score;
                                  bestParam = params[p].paramId;
                                }
                                if (score > worstScore) {
                                  worstScore = score;
                                }
                                const bool exportThisTrace = exportPressureTrace &&
                                                             (traceExportedCount < traceExportBudget) &&
                                                             shouldExportSweepTrace(caseMetrics);
                                if (exportThisTrace) {
                                  traceExportedCount++;
                                }

                                char metrics[240];
                                snprintf(metrics, sizeof(metrics),
                                         "suite=%u;param=%u;scenario=%u;mode=%u;under=%lu;over=%lu;rec_w=%lu;rec_m=%lu;ready_miss=%lu;slip_w=%lu;slip_m=%lu;zero=%lu;rejects=%lu;sc=%lu;ec=%lu;trace=%u;score=%lu;combo_ms=%lu;combo_to=%u",
                                         static_cast<unsigned>(suiteId),
                                         static_cast<unsigned>(params[p].paramId),
                                         static_cast<unsigned>(scenarios[s].scenarioId),
                                         static_cast<unsigned>(scenarios[s].modeCode),
                                         static_cast<unsigned long>(caseMetrics.maxUndershoot),
                                         static_cast<unsigned long>(caseMetrics.maxOvershoot),
                                         static_cast<unsigned long>(caseMetrics.worstRecoveryMs),
                                         static_cast<unsigned long>(caseMetrics.meanRecoveryMs),
                                         static_cast<unsigned long>(caseMetrics.readyMissCount),
                                         static_cast<unsigned long>(caseMetrics.maxDeadlineSlipMs),
                                         static_cast<unsigned long>(caseMetrics.meanDeadlineSlipMs),
                                         static_cast<unsigned long>(caseMetrics.zeroCrossCount),
                                         static_cast<unsigned long>(caseMetrics.sampleRejectCount),
                                         static_cast<unsigned long>(caseMetrics.traceSampleCount),
                                         static_cast<unsigned long>(caseMetrics.traceEventCount),
                                         static_cast<unsigned>(exportThisTrace ? 1u : 0u),
                                         static_cast<unsigned long>(score),
                                         static_cast<unsigned long>(comboElapsedMs),
                                         static_cast<unsigned>(comboTimedOut ? 1u : 0u));
                                sendProgressStage("sw_combo_emit");
                                if (!runOne(comboTestId, comboName, comboPass, metrics)) {
                                  restoreBaseline();
                                  return false;
                                }
                                sendProgressStage("sw_combo_emit_ok");
                                if (!maybeExportTrace(exportThisTrace, comboTestId, comboName, comboPass)) {
                                  sendProgressStage("trace_export_fail");
                                } else if (exportThisTrace) {
                                  sendProgressStage("sw_combo_export_ok");
                                }
                                comboIndex++;
                              }
                              if (suiteTimedOut) {
                                break;
                              }
                            }

                            restoreBaseline();
                            if (bestScore == 0xFFFFFFFFu) {
                              bestScore = 0u;
                              bestParam = 0u;
                            }
                            const uint16_t combosPlanned = static_cast<uint16_t>(paramCount * scenarioCount);
                            const uint16_t combosRun = comboIndex;
                            char summaryMetrics[192];
                            snprintf(summaryMetrics, sizeof(summaryMetrics),
                                     "suite=%u;combos=%u;combos_run=%u;pass_combo_count=%u;best_param=%u;best_score=%lu;worst_score=%lu;trace_exported_count=%u;suite_timeout=%u",
                                     static_cast<unsigned>(suiteId),
                                     static_cast<unsigned>(combosPlanned),
                                     static_cast<unsigned>(combosRun),
                                     static_cast<unsigned>(passComboCount),
                                     static_cast<unsigned>(bestParam),
                                     static_cast<unsigned long>(bestScore),
                                     static_cast<unsigned long>(worstScore),
                                     static_cast<unsigned>(traceExportedCount),
                                     static_cast<unsigned>(suiteTimedOut ? 1u : 0u));
                            return runOne(suiteSummaryTestId,
                                          suiteSummaryName,
                                          (!suiteTimedOut) && (passComboCount == combosPlanned),
                                          summaryMetrics);
                          };

                          if (runPressureSweepCore) {
                            if (!runPressureSweepSuite(2301u)) goto selftest_done;
                          }
                          if (runPressureSweepExtended) {
                            if (!runPressureSweepSuite(2302u)) goto selftest_done;
                          }
                          if (runPressureSweepFocused) {
                            if (!runPressureSweepSuite(2303u)) goto selftest_done;
                          }
                          if (runPressureSweepMicro) {
                            if (!runPressureSweepSuite(2304u)) goto selftest_done;
                          }

                          if (shouldRunPressureTraceCase(2101)) {
                            if (!runPressureTraceCase(2101,
                                                      "pressure_recovery_trace_print_single",
                                                      0u,
                                                      psiToRaw(1000u),
                                                      1300u,
                                                      1u,
                                                      20u,
                                                      PulseMode::PRINT_ONLY,
                                                      false,
                                                      0u,
                                                      0u,
                                                      nullptr,
                                                      true,
                                                      exportPressureTrace)) goto selftest_done;
                          }

                          if (shouldRunPressureTraceCase(2102)) {
                            if (!runPressureTraceCase(2102,
                                                      "pressure_recovery_trace_print_repeated",
                                                      0u,
                                                      psiToRaw(1000u),
                                                      1300u,
                                                      10u,
                                                      20u,
                                                      PulseMode::PRINT_ONLY,
                                                      false,
                                                      0u,
                                                      0u,
                                                      nullptr,
                                                      true,
                                                      exportPressureTrace)) goto selftest_done;
                          }

#if (LC_PRESSURE_PORTS > 1)
                          if (shouldRunPressureTraceCase(2103)) {
                            if (!runPressureTraceCase(2103,
                                                      "pressure_recovery_trace_refuel_repeated",
                                                      1u,
                                                      psiToRaw(500u),
                                                      3000u,
                                                      10u,
                                                      20u,
                                                      PulseMode::REFUEL_ONLY,
                                                      false,
                                                      0u,
                                                      0u,
                                                      nullptr,
                                                      true,
                                                      exportPressureTrace)) goto selftest_done;
                          }

                          if (shouldRunPressureTraceCase(2104)) {
                            if (!runPressureTraceCase(2104,
                                                      "pressure_recovery_trace_dual_interleaved",
                                                      0u,
                                                      psiToRaw(1000u),
                                                      1300u,
                                                      10u,
                                                      20u,
                                                      PulseMode::BOTH,
                                                      true,
                                                      psiToRaw(500u),
                                                      3000u,
                                                      nullptr,
                                                      true,
                                                      exportPressureTrace)) goto selftest_done;
                          }
#else
                          if (!runOne(2103,
                                      "pressure_recovery_trace_refuel_repeated",
                                      false,
                                      "baseline_pressure_raw=0;min_pressure_raw=0;max_pressure_raw=0;max_undershoot_raw=0;max_overshoot_raw=0;worst_recovery_ms=0;mean_recovery_ms=0;ready_miss_count=1;max_deadline_slip_ms=0;mean_deadline_slip_ms=0;zero_cross_count=0;sample_reject_count=0")) goto selftest_done;
                          if (!runOne(2104,
                                      "pressure_recovery_trace_dual_interleaved",
                                      false,
                                      "baseline_pressure_raw=0;min_pressure_raw=0;max_pressure_raw=0;max_undershoot_raw=0;max_overshoot_raw=0;worst_recovery_ms=0;mean_recovery_ms=0;ready_miss_count=1;max_deadline_slip_ms=0;mean_deadline_slip_ms=0;zero_cross_count=0;sample_reject_count=0")) goto selftest_done;
#endif
                          }
			
							  selftest_done:
                          comm->setStatusPaused(true);
						  uint8_t donePayload[64] = {0};
				  size_t d = 0;
				  donePayload[d++] = CMD_SELFTEST_DONE;
				  donePayload[d++] = outSeq8;

				  donePayload[d++] = 0x21; donePayload[d++] = 4;
				  donePayload[d++] = static_cast<uint8_t>(runId & 0xFFu);
				  donePayload[d++] = static_cast<uint8_t>((runId >> 8) & 0xFFu);
				  donePayload[d++] = static_cast<uint8_t>((runId >> 16) & 0xFFu);
				  donePayload[d++] = static_cast<uint8_t>((runId >> 24) & 0xFFu);

				  donePayload[d++] = 0x35; donePayload[d++] = 2;
				  donePayload[d++] = static_cast<uint8_t>(total & 0xFFu);
				  donePayload[d++] = static_cast<uint8_t>((total >> 8) & 0xFFu);

				  donePayload[d++] = 0x36; donePayload[d++] = 2;
				  donePayload[d++] = static_cast<uint8_t>(passed & 0xFFu);
				  donePayload[d++] = static_cast<uint8_t>((passed >> 8) & 0xFFu);

				  donePayload[d++] = 0x37; donePayload[d++] = 2;
				  donePayload[d++] = static_cast<uint8_t>(failed & 0xFFu);
				  donePayload[d++] = static_cast<uint8_t>((failed >> 8) & 0xFFu);

				  donePayload[d++] = 0x38; donePayload[d++] = 1;
				  donePayload[d++] = aborted ? 1u : 0u;

				  const uint32_t ts = HAL_GetTick();
				  donePayload[d++] = 0x34; donePayload[d++] = 4;
				  donePayload[d++] = static_cast<uint8_t>(ts & 0xFFu);
				  donePayload[d++] = static_cast<uint8_t>((ts >> 8) & 0xFFu);
				  donePayload[d++] = static_cast<uint8_t>((ts >> 16) & 0xFFu);
				  donePayload[d++] = static_cast<uint8_t>((ts >> 24) & 0xFFu);

				  comm->sendFrame(comm->handle(), donePayload, d);
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

			  if (!completed && _waitRemainingTicks > 0) {
			    // Interrupted by PAUSE/CLEAR/SHUTDOWN.
			    // Do NOT advance _lastExecutedCmdNum yet — RESUME will finish it.
			    return;
			  }

			  // Completed: fall through to end-of-command bookkeeping
			  break;
			}
        default:
          // unknown—ignore
      	HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);
          break;
      }
  _lastExecutedCmdNum = _currentCmdNum;
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
  MX_GRIPPER_StopRefresh();
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

  _currentCmdNum = 0;
  _lastExecutedCmdNum = 0;
  xEventGroupClearBits(_doneEvents,
    BIT_LED_DONE|BIT_STEPPER1_DONE|BIT_STEPPER2_DONE|BIT_STEPPER3_DONE|BIT_PRINTING_DONE|BIT_FLASH_DONE);

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
	    const auto triggerAction = FlashSafety::onTrigger(_instance->_flashSafety);
	    if (triggerAction == FlashSafety::TriggerAction::IgnoredDisarmed ||
	        triggerAction == FlashSafety::TriggerAction::IgnoredFaultLatched ||
	        triggerAction == FlashSafety::TriggerAction::IgnoredBusy) {
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

    if (_imagingDroplets == 0){
    	Orchestrator::instance()->scheduleFlashIn();
    }
    else {
        Printer::instance()->setFlashOnLast(true);
        Printer::instance()->enqueue(_imagingDroplets, _imagingFreq,PulseMode::BOTH);
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
