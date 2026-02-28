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
    768,    this,
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
        executeCommand(cmd);
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
        	if (!_flashTaskHandle) {
        		xTaskCreate(
					_flashTaskEntry,
					"FlashMon",
					256,
					this,
					tskIDLE_PRIORITY+3,     // even higher than Orchestrator
					&_flashTaskHandle
        		);
        	}
			if (!_flashAckTmr) {
			_flashAckTmr = xTimerCreate(
				"FlashAck", pdMS_TO_TICKS(kFlashAckMs), pdFALSE, this, _flashAckTimerCb);
			}
			HAL_GPIO_WritePin(_flashAckPort, _flashAckPin, GPIO_PIN_RESET);
		#endif
          break;
        }
        case CMD_STOP_FLASH: {
		#if LC_HAS_IMAGING == 1
          // Ends the flash trigger monitoring task
        	if (_flashTaskHandle) {
        		vTaskDelete(_flashTaskHandle);
        		_flashTaskHandle = nullptr;
        	}
		#endif
          break;
        }
        case CMD_SET_FLASH_DURATION: {
		#if LC_HAS_IMAGING == 1
          Flash::instance()->setDurationNs(cmd.p1);
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
        	int32_t  target = (int32_t)cmd.p1u();
        	PressureRegulator::regP().setTargetSafe(target);
            // ensure we re-wait even if already in band
            xEventGroupClearBits(_doneEvents, BIT_PRESSURE_P_READY);
            waitForBit(BIT_PRESSURE_P_READY);
        	break;
        }
        case CMD_PR_REFUEL: {
			#if (LC_PRESSURE_PORTS > 1)
        	  int32_t  target = (int32_t)cmd.p1u();
			  PressureRegulator::regR().setTargetSafe(target);
			  xEventGroupClearBits(_doneEvents, BIT_PRESSURE_R_READY);
			  waitForBit(BIT_PRESSURE_R_READY);
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
			PressureRegulator::regP().setRelativeTargetSafe(sign, delta);
            // ensure we re-wait even if already in band
            xEventGroupClearBits(_doneEvents, BIT_PRESSURE_P_READY);
            waitForBit(BIT_PRESSURE_P_READY);
			break;
		}
        case CMD_PR_REFUEL_REL: {
			#if (LC_PRESSURE_PORTS > 1)
			bool  sign   = cmd.p1b();
			int32_t  delta  = (int32_t)cmd.p2u();
			  if (delta == 0) { Logger::instance()->log("[PReg] REL R delta=0\n"); break; }
			PressureRegulator::regR().setRelativeTargetSafe(sign, delta);
			xEventGroupClearBits(_doneEvents, BIT_PRESSURE_R_READY);
			waitForBit(BIT_PRESSURE_R_READY);
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
			PressureRegulator::regP().resetSyringe();
			break;
		}
		case CMD_RESET_REFUEL: {
		#if (LC_PRESSURE_PORTS > 1)
		  PressureRegulator::regR().resetSyringe();
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

				  _selfTestAbortRequested = false;
				  const uint32_t runId = cmd.hasSeq32 ? cmd.seq32 : _currentCmdNum;
				  const uint8_t outSeq8 = cmd.seq8;
				  uint16_t total = 0;
				  uint16_t passed = 0;
				  uint16_t failed = 0;
				  bool aborted = false;

					  auto sendResult = [&](uint16_t testId, const char* name, bool pass, const char* metrics) {
					    uint8_t payload[256] = {0};
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

				    payload[idx++] = 0x32; payload[idx++] = 1;
				    payload[idx++] = pass ? 1u : 0u;

						    const size_t metricsLenRaw = strlen(metrics);
						    const uint8_t metricsLen = static_cast<uint8_t>((metricsLenRaw > 160u) ? 160u : metricsLenRaw);
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
				  };

				  uint32_t statusChunk0Seen = 0;
					  uint32_t statusChunk1Seen = 0;
					  uint32_t statusAlternationErrors = 0;
					  uint32_t statusPeriodMsAvg = 0;
					  uint32_t statusPeriodMsMaxJitter = 0;
					  const bool fullProfile = (cmd.p1Len > 0u) && (cmd.p1u() == 1u);
					  bool fullHomePass = false;

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
						    const TickType_t chunkTicks = pdMS_TO_TICKS(50);
						    const TickType_t timeoutTicks = pdMS_TO_TICKS(timeoutMs);
						    TickType_t waitedTicks = 0;
							    while (waitedTicks < timeoutTicks) {
							      Watchdog_CheckIn(CRASH_TASK_ORCH);
							      if (_selfTestAbortRequested) {
							        return false;
							      }
						      const TickType_t waitTicks = ((timeoutTicks - waitedTicks) > chunkTicks) ? chunkTicks : (timeoutTicks - waitedTicks);
						      const EventBits_t result = xEventGroupWaitBits(
						          _doneEvents,
						          bits,
						          pdFALSE,
						          pdTRUE,
						          waitTicks);
						      if ((result & bits) == bits) {
						        return true;
						      }
						      waitedTicks += waitTicks;
						    }
						    return false;
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
					    uint32_t flashWidthNs = 0;
	#if LC_HAS_IMAGING == 1
					    if (auto* flash = Flash::instance()) {
					      flashWidthNs = flash->getPulseDuration();
					    }
	#endif
					    char metrics[96];
					    snprintf(metrics, sizeof(metrics), "flash_delay_us=%lu;flash_width_ns=%lu",
					             static_cast<unsigned long>(flashDelay),
					             static_cast<unsigned long>(flashWidthNs));
					    if (!runOne(1005, "flash_config_readonly", true, metrics)) goto selftest_done;
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
						    uint32_t pregCount = 0u;
						    uint16_t stackMinWords = 0xFFFFu;
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
						        trackForMin = true;
						      } else if (strcmp(taskName, "Pressure") == 0) {
						        hasPressure = true;
						        trackForMin = true;
						      } else if (strcmp(taskName, "LogStats") == 0) {
						        hasLogStats = true;
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
						    char metrics[176];
						    snprintf(metrics,
						             sizeof(metrics),
						             "heap_now=%lu;heap_min=%lu;stk_min=%u;stk_task=%s;task_n=%u;core_miss=%lu;preg_n=%lu;trunc=%u;stk_ovf=%lu",
						             static_cast<unsigned long>(heapNow),
						             static_cast<unsigned long>(heapMin),
						             static_cast<unsigned>(stackMinWords),
						             stackMinTask,
						             static_cast<unsigned>(captured),
						             static_cast<unsigned long>(coreMissing),
						             static_cast<unsigned long>(pregCount),
						             trunc ? 1u : 0u,
						             static_cast<unsigned long>(stackOverflowFired));
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
						    char metrics[192];
						    snprintf(metrics,
						             sizeof(metrics),
						             "pending=%u;sticky=%u;fault=%s;task=%s;reset=%s;boot=%lu;fault_ct=%lu;wdg_ct=%lu;sticky_ct=%lu;raw_sr=%lu;boot_stage=%s",
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
						             CrashLog_BootStageName(snap.bootStage));
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
						    if (!fullProfile) {
						      if (!runOne(2001,
						                  "motion_home_cycle_full",
						                  true,
						                  "profile=SAFE;executed=0;fixture_required=1;motion=0;gate=safe_only")) {
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
						    if (!fullProfile) {
						      if (!runOne(2002,
						                  "motion_absolute_move_bounds_full",
						                  true,
						                  "profile=SAFE;executed=0;fixture_required=1;motion=0;gate=safe_only")) {
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
						    if (!fullProfile) {
						      if (!runOne(2003,
						                  "pressure_regulator_step_response_full",
						                  true,
						                  "profile=SAFE;executed=0;fixture_required=1;pressure=0;gate=safe_only")) {
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
						    if (!fullProfile) {
						      if (!runOne(2004,
						                  "valve_actuation_sequence_full",
						                  true,
						                  "profile=SAFE;executed=0;fixture_required=1;valves=0;gate=safe_only")) {
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
						    if (!fullProfile) {
						      if (!runOne(2005,
						                  "print_refuel_pulse_integrity_full",
						                  true,
						                  "profile=SAFE;executed=0;fixture_required=1;pulses=0;gate=safe_only")) {
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
						    if (!fullProfile) {
						      if (!runOne(2006,
						                  "emergency_abort_and_safe_stop_full",
						                  true,
						                  "profile=SAFE;executed=0;fixture_required=1;abort=0;gate=safe_only")) {
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
			
							  selftest_done:
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

// ---------- Async homing task ----------
void Orchestrator::_homeTaskEntry(void* ctx)
{
  auto* a = static_cast<HomeTaskArgs*>(ctx);
  a->stepper->home(a->fastHz, a->slowHz, a->backoffSteps);
  xEventGroupSetBits(Orchestrator::getDoneEvents(), a->doneBit);

  // Clear the handle for this bank so a new home can be started later
  if (a->stepper == Stepper::stepperX()) instance()->_taskHomeX = nullptr;
  else if (a->stepper == Stepper::stepperY()) instance()->_taskHomeY = nullptr;
  else if (a->stepper == Stepper::stepperZ()) instance()->_taskHomeZ = nullptr;

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
  a->reg->homeWithValve(a->fastHz, a->slowHz, a->backoffSteps);
  xEventGroupSetBits(Orchestrator::getDoneEvents(), a->doneBit);

  if (a->reg == &PressureRegulator::regP()) instance()->_taskHomeP = nullptr;
#if (LC_PRESSURE_PORTS > 1)
  else if (a->reg == &PressureRegulator::regR()) instance()->_taskHomeR = nullptr;
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

	    if (_instance->_awaitingRelease) {
	      // Already handling a HIGH level; ignore spurious repeats
	      return;
	    }
	    _instance->_awaitingRelease = true;

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


    _flashInProgress = true;
    xEventGroupClearBits(_doneEvents, BIT_FLASH_DONE);

    Logger::instance()->log("-FLASH RX-\r\n");

    if (_imagingDroplets == 0){
    	Orchestrator::instance()->scheduleFlashIn();
    }
    else {
        Printer::instance()->setFlashOnLast(true);
        Printer::instance()->enqueue(_imagingDroplets, _imagingFreq,PulseMode::BOTH);
    }

//    Logger::instance()->log("-FLASH COMP-\r\n");

    // then don’t proceed until the Pi’s line goes back low
    while (HAL_GPIO_ReadPin(_trigPort, _trigPin) == GPIO_PIN_SET) {
      vTaskDelay(pdMS_TO_TICKS(1));
    }

    Logger::instance()->log("-FLASH COMP-\r\n");

//    // release the latch and drop any queued notifies that arrived while high
    _awaitingRelease = false;

    // Drain any latched notifications using the SAME bitwise API:
    uint32_t dummy;
    while (xTaskNotifyWait(0, 0xFFFFFFFFu, &dummy, 0) == pdTRUE) {
      // loop clears any pending bits (if your EXTI queued extras)
    }

    _flashInProgress = false;
    xEventGroupSetBits(_doneEvents, BIT_FLASH_DONE);
    Logger::instance()->log("-FLASH DONE-\r\n");
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
    Orchestrator::instance()->_flashAckHigh();

    // Drop it low in ~2 ms via a FreeRTOS software timer
    BaseType_t hpw = pdFALSE;
    xTimerStartFromISR(Orchestrator::instance()->_flashAckTmr, &hpw);
    portYIELD_FROM_ISR(hpw);
}
#else

// Safe stubs so the project links even if callbacks remain referenced somewhere.
extern "C" void MX_FLASH_TriggerCallback(uint16_t GPIO_Pin) { (void)GPIO_Pin; }
extern "C" void MX_FLASH_Acknowledge() {}

//void Orchestrator::scheduleFlashIn() {}
//void Orchestrator::flashNotifyFromISR(uint16_t GPIO_Pin) { (void)GPIO_Pin; }

#endif
