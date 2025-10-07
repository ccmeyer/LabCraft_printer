/*
 * Orchestrator.cpp
 *
 *  Created on: Jun 19, 2025
 *      Author: conar
 */

#include "Orchestrator.h"
#include "LEDController.h"    // your LED queue + done-event
#include "Stepper.h"          // MX_STEPPERx_Move(), MX_STEPPERx_Stop(), MX_STEPPERx_IsBusy()
#include "Gripper.h"
#include "Printer.h"
#include "PressureRegulator.h"
#include "Logger.h"
#include "Flash.h"
#include "Flash.hpp"
#include "Gantry.h"
#include "Comm.h"
#include "LEDStrip.h"
#include "cmsis_os.h"         // for portMAX_DELAY, pdTRUE, etc.

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
    512,    this,
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
      default: {
    	  return xQueueSendFromISR(_cmdQueue, &cmd, pxHigherPriorityTaskWoken);
      }
    }
}

void Orchestrator::pauseCurrent() {
  Logger::instance()->log("pauseCurrent\r\n");
  Gantry::instance()->pauseXYZMotors();
  Printer::instance()->pauseDispense();
  xEventGroupClearBits(_doneEvents,
      BIT_LED_DONE|BIT_STEPPER1_DONE|BIT_STEPPER2_DONE|
      BIT_STEPPER3_DONE|BIT_PRINTING_DONE|BIT_GRIPPER_DONE);
}

void Orchestrator::resumeCurrent() {
  Logger::instance()->log("resumeCurrent\r\n");
  Gantry::instance()->resumeXYZMotors();
  Printer::instance()->resumeDispense();
}
void Orchestrator::cancelCurrent() {
//  Logger::instance()->log("cancelCurrent\r\n");
  Gantry::instance()->cancelXYZMotors();
  Printer::instance()->cancelDispense();
}

void Orchestrator::_taskEntry(void* pv) {
  static_cast<Orchestrator*>(pv)->_run();
}

bool Orchestrator::waitForBit(EventBits_t bit) {
  const TickType_t ticks = pdMS_TO_TICKS(50);
  while (true) {
    // If a PAUSE came in, stop waiting immediately.
    if (_paused) {
      return false;
    }
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
	if ( (result & bits) != 0 ) {
	  return true;  // we got the signal, normal completion
	}
	// else: timed out, loop again (to check _paused)
  }
}

void Orchestrator::_run() {
  for (;;) {
	  if (_acknowledgeRequested) {
          // Reply with appropriate ACK using the same sequence number
          uint8_t seq = _inFlight.seq;
          switch (_inFlight.cmd) {
            case CMD_HELLO:{
            	Comm::instance()->sendCommandByte(CMD_HELLO_ACK, seq);
                // Then resume status & cosmetic stuff
                Comm::instance()->setStatusPaused(false);
            	MX_LEDSTRIP_FadeTo(100,500);
            	break;
            }
            case CMD_GOODBYE: {
            	Comm::instance()->setStatusPaused(true);
            	Comm::instance()->sendCommandByte(CMD_BYE_ACK, seq);
            	// Start next session clean
            	Comm::instance()->resetReceiveState();
//            	MX_LEDSTRIP_FadeTo(0,500);
            	break;
            }
            case CMD_CLEAR:{
            	Comm::instance()->setStatusPaused(true);
            	Comm::instance()->sendCommandByte(CMD_CLEAR_ACK, seq);
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
	  // Use the GOODBYE seq so host can correlate if it wants
	  performShutdown(_inFlight.seq);
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
	// Detect wrap and compute absolute numbers
	if (cmd.seq < _lastSeq8 && (_lastSeq8 - cmd.seq) > 128) {
	  _seqEpoch++;  // crossed 255->0
	}
	_lastSeq8 = cmd.seq;

	_currentCmdNum = (uint32_t(_seqEpoch) << 8) | uint32_t(cmd.seq);
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
          auto ax = (Stepper::Axis)cmd.p1;
          if (auto s = Stepper::getAxis(ax)) s->setMaxSpeedHz((uint32_t)cmd.p2);
          break;
        }
        case CMD_SET_AXIS_ACCEL: {
          auto ax = (Stepper::Axis)cmd.p1;
          if (auto s = Stepper::getAxis(ax)) s->setAccelStepsPerSec2((float)cmd.p2);
          break;
        }
        case CMD_SET_AXIS_PROFILE: {
          auto ax = (Stepper::Axis)cmd.p1;
          auto pf = (Stepper::AccelProfile)cmd.p2;
          if (auto s = Stepper::getAxis(ax)) s->setAccelProfile(pf);
          break;
        }
        case CMD_HOME_X: {
          MX_STEPPERX_Home(cmd.p1, cmd.p2,cmd.p3);
		  break;
		}
        case CMD_HOME_Y: {
          MX_STEPPERY_Home(cmd.p1, cmd.p2,cmd.p3);
		  break;
		}
        case CMD_HOME_Z: {
          MX_STEPPERZ_Home(cmd.p1, cmd.p2,cmd.p3);
		  break;
		}
        case CMD_ENABLE_MOTORS: {
          Stepper::stepperX()->enableMotor();
          Stepper::stepperY()->enableMotor();
          Stepper::stepperZ()->enableMotor();
          Stepper::stepperP()->enableMotor();
          Stepper::stepperR()->enableMotor();
		  break;
		}
        case CMD_DISABLE_MOTORS: {
          Stepper::stepperX()->disableMotor();
          Stepper::stepperY()->disableMotor();
          Stepper::stepperZ()->disableMotor();
          Stepper::stepperP()->disableMotor();
          Stepper::stepperR()->disableMotor();
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
        	if (!_flashTaskHandle) {
        		xTaskCreate(
					_flashTaskEntry,
					"FlashMon",
					128,
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
          break;
        }
        case CMD_STOP_FLASH: {
          // Ends the flash trigger monitoring task
        	if (_flashTaskHandle) {
        		vTaskDelete(_flashTaskHandle);
        		_flashTaskHandle = nullptr;
        	}
          break;
        }
        case CMD_SET_FLASH_DURATION: {
            Flash::instance()->setDurationNs(cmd.p1);
          break;
        }
        case CMD_SET_FLASH_DELAY: {
          setFlashDelay(cmd.p1);
          break;
        }
        case CMD_SET_IMAGING_DROPLETS: {
          setImagingDroplets(cmd.p1);
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
        	int32_t  target = (int32_t)cmd.p1u();
			PressureRegulator::regR().setTargetSafe(target);
            xEventGroupClearBits(_doneEvents, BIT_PRESSURE_R_READY);
            waitForBit(BIT_PRESSURE_R_READY);
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
			bool  sign   = cmd.p1b();
			int32_t  delta  = (int32_t)cmd.p2u();
			  if (delta == 0) { Logger::instance()->log("[PReg] REL R delta=0\n"); break; }
			PressureRegulator::regR().setRelativeTargetSafe(sign, delta);
			xEventGroupClearBits(_doneEvents, BIT_PRESSURE_R_READY);
			waitForBit(BIT_PRESSURE_R_READY);
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
        	PressureRegulator::regP().homeWithValve(cmd.p1, cmd.p2, cmd.p3);
			break;
		}
        case CMD_HOME_REFUEL: {
        	PressureRegulator::regR().homeWithValve(cmd.p1, cmd.p2, cmd.p3);
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

          // Clear the "both regulators home finished" bits
          xEventGroupClearBits(_doneEvents, BIT_HOME_P_DONE | BIT_HOME_R_DONE);

          // Kick off both, in parallel. This runs Valve+Stepper homing per regulator.
          startRegHomeAsync(&PressureRegulator::regP(), fastHz, slowHz, backoff, BIT_HOME_P_DONE);
          startRegHomeAsync(&PressureRegulator::regR(), fastHz, slowHz, backoff, BIT_HOME_R_DONE);

          // Block here until both are done
          waitForBits(BIT_HOME_P_DONE | BIT_HOME_R_DONE);
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
        	PressureRegulator::regR().openValve();
			break;
		}
        case CMD_R_VALVE_CLOSE: {
        	PressureRegulator::regR().closeValve();
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
			PressureRegulator::regR().start();
			break;
		}
		case CMD_R_REG_STOP: {
			PressureRegulator::regR().pause();
			break;
		}
		case CMD_RESET_PRINT: {
			PressureRegulator::regP().resetSyringe();
			break;
		}
		case CMD_RESET_REFUEL: {
			PressureRegulator::regR().resetSyringe();
			break;
		}
		case CMD_LEDSTRIP_ON: {
			MX_LEDSTRIP_FadeTo(100,2000);
			break;
		}
		case CMD_LEDSTRIP_OFF: {
			MX_LEDSTRIP_FadeTo(0,500);
			break;
		}
        default:
          // unknown—ignore
      	HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);
          break;
      }
  _lastExecutedCmdNum = _currentCmdNum;
  }

void Orchestrator::performShutdown(uint8_t byeSeq)
{
//  Logger::instance()->log("Shutdown start\r\n");

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
  PressureRegulator::regR().pause();

  PressureRegulator::regP().openValve();
  PressureRegulator::regR().openValve();

  // 4) Gripper off
  MX_GRIPPER_StopRefresh();
//
//  // 5) Disable motors
  Stepper::stepperX()->disableMotor();
  Stepper::stepperY()->disableMotor();
  Stepper::stepperZ()->disableMotor();
  Stepper::stepperP()->disableMotor();
  Stepper::stepperR()->disableMotor();

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
  MX_LEDSTRIP_FadeTo(0, 500);

  // small settle delay for hardware
  vTaskDelay(pdMS_TO_TICKS(500));

  PressureRegulator::regP().closeValve();
  PressureRegulator::regR().closeValve();
//

  _paused = true;     // remain paused until next HELLO
  _clearing = false;

  Logger::instance()->log("Shutdown done\r\n");

  // 8) Tell host we’re safe. Status is paused, but command bytes still go out.
  Comm::instance()->sendCommandByte(CMD_BYE_DONE, byeSeq);
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
  } else {
    // Fallback for any other axis (Z, P, R) if you ever call this path:
    Logger::instance()->log("[Home] No static bank for this axis; running blocking fallback\r\n");
    s->home(fastHz, slowHz, backoffSteps);
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
    // As a last resort, run blocking so the command still completes
    s->home(fastHz, slowHz, backoffSteps);
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
  else if (a->reg == &PressureRegulator::regR()) instance()->_taskHomeR = nullptr;

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
  } else if (r == &PressureRegulator::regR()) {
    tcb = &_tcbHomeR; stack = _stackHomeR; handle = &_taskHomeR; args = &_argsHomeR; name = "HomePR_R";
  } else {
    Logger::instance()->log("[HomePR] No static bank for this regulator; blocking fallback\r\n");
    r->homeWithValve(fastHz, slowHz, backoffSteps);
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
    r->homeWithValve(fastHz, slowHz, backoffSteps);
    xEventGroupSetBits(_doneEvents, doneBit);
  }
}


//===========================================================================//
// flash-monitor task
//===========================================================================//

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
			HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);
		    BaseType_t woke = pdFALSE;
		    // just poke the FlashTask
		    xTaskNotifyFromISR(
		      _instance->_flashTaskHandle,
		      0,            // notification value (unused)
//		      eNoAction,
			  eIncrement,
		      &woke
		    );
		    portYIELD_FROM_ISR(woke);
		  }
	}

void Orchestrator::_flashTaskEntry(void* pv) {
  static_cast<Orchestrator*>(pv)->_flashTaskLoop();
}

void Orchestrator::_flashTaskLoop() {
  for (;;) {
    // wait for the EXTI ISR to notify us
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

    _flashInProgress = true;
    xEventGroupClearBits(_doneEvents, BIT_FLASH_DONE);

    if (_imagingDroplets == 0){
    	Orchestrator::instance()->scheduleFlashIn();
    }
    else {
        Printer::instance()->setFlashOnLast(true);
        Printer::instance()->enqueue(_imagingDroplets, _imagingFreq,PulseMode::BOTH);
    }

    // then don’t proceed until the Pi’s line goes back low
    while (HAL_GPIO_ReadPin(_trigPort, _trigPin) == GPIO_PIN_SET) {
      vTaskDelay(pdMS_TO_TICKS(1));
    }

    _flashInProgress = false;
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
    Orchestrator::instance()->_flashAckHigh();

    // Drop it low in ~2 ms via a FreeRTOS software timer
    BaseType_t hpw = pdFALSE;
    xTimerStartFromISR(Orchestrator::instance()->_flashAckTmr, &hpw);
    portYIELD_FROM_ISR(hpw);
}
