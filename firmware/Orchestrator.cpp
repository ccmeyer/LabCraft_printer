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
		case CMD_HELLO:
		  // Reset any stale state
		  _paused = false; _pauseRequested = false;
		  _resumeRequested = false; _clearRequested = false;
		  _acknowledgeRequested = true;

		  return pdFALSE;
//    	case CMD_HELLO: {
//          // 1) reset internal state
////			HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);
////			vTaskDelay(500);
////			HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);
////			vTaskDelay(500);
////			HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);
////			vTaskDelay(500);
////			HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);
////			vTaskDelay(500);
//		  _acknowledgeRequested = true;
////          _paused = false;
////          _pauseRequested = false;
////          _resumeRequested = false;
////          _clearRequested = true;
//          // 2) send HELLO_ACK
////          Comm::instance()->sendCommandByte(CMD_HELLO_ACK, cmd.seq);
//          return pdFALSE;   // don’t enqueue
//        }
//        case CMD_GOODBYE: {
//          // 1) pause everything
//          _paused = true;
//          _pauseRequested = true;
//          _clearRequested = true;
//          // 2) send BYE_ACK
////          Comm::instance()->sendCommandByte(CMD_BYE_ACK, cmd.seq);
//          return pdFALSE;
//        }
        case CMD_PAUSE:
		  // request a pause
		  _paused = true;
		  _pauseRequested = true;
		  return pdFALSE;           // don't put into the queue
		case CMD_RESUME:
		  _resumeRequested = true;
		  return pdFALSE;
      case CMD_CLEAR: {
    	  _clearRequested = true;
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
}

void Orchestrator::resumeCurrent() {
  Logger::instance()->log("resumeCurrent\r\n");
  Gantry::instance()->resumeXYZMotors();
  Printer::instance()->resumeDispense();
}
void Orchestrator::cancelCurrent() {
  Logger::instance()->log("cancelCurrent\r\n");
  Gantry::instance()->cancelXYZMotors();
  Printer::instance()->cancelDispense();
}

void Orchestrator::clearQueue() {
	xQueueReset(_cmdQueue);
	Logger::instance()->log("Reset\r\n");
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

void Orchestrator::_run() {
  for (;;) {
	  if (_acknowledgeRequested) {

		  Comm::instance()->sendCommandByte(CMD_HELLO_ACK, 0);
		  HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);
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
			// … etc …
			default: {

			}
		  }
	  }
	  if (_clearRequested) {
        cancelCurrent();
		clearQueue();
		_paused = false;
		_clearRequested = false;
	  }

	if (_paused) {
	  vTaskDelay(pdMS_TO_TICKS(50));
	  continue;
	}
//	if (_paused) {
//	  // if we’re paused we just defer this command until later
////	  xQueueSendToFront(_cmdQueue, &cmd, 0);
//	  vTaskDelay(pdMS_TO_TICKS(10));
//	  continue;
//	}

    Command cmd;
    // 1) always block here until there’s anything in the queue
    if (xQueueReceive(_cmdQueue, &cmd, portMAX_DELAY) != pdPASS)
      continue;
    // remember which one is in flight
    _inFlight = cmd;
	executeCommand(cmd);
  }
}

/// factor out all your “case CMD_MOVE_X / CMD_LED / etc” into this:
void Orchestrator::executeCommand(const Command &cmd) {
  _currentCmdNum = cmd.seq;
  // clear done‐bits
  xEventGroupClearBits(_doneEvents,
      BIT_LED_DONE|BIT_STEPPER1_DONE|BIT_STEPPER2_DONE|BIT_STEPPER3_DONE|BIT_PRINTING_DONE);

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
  		  break;
  		}
        case CMD_GRIPPER_CLOSE: {
      	  MX_GRIPPER_Close();
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
        	PressureRegulator::regP().setTarget(cmd.p1);
        	break;
        }
        case CMD_PR_REFUEL: {
        	PressureRegulator::regR().setTarget(cmd.p1);
			break;
		}
        case CMD_PR_PRINT_REL: {
        	PressureRegulator::regP().setRelativeTarget(cmd.p1, cmd.p2);
			break;
		}
        case CMD_PR_REFUEL_REL: {
			PressureRegulator::regR().setRelativeTarget(cmd.p1, cmd.p2);
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
      	vTaskDelay(500);
      	HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);
      	vTaskDelay(500);
      	HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);
      	vTaskDelay(500);
      	HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);
      	vTaskDelay(500);
          break;
      }
  _lastExecutedCmdNum = cmd.seq;
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

  // set compare value = desired delay in µs
  __HAL_TIM_SET_COMPARE(&htim12, TIM_CHANNEL_1, _flashDelay);

  // ARR must be >= CCR+1 so the compare can happen:
  __HAL_TIM_SET_AUTORELOAD(&htim12, _flashDelay + 1);

  // start output-compare with interrupt
  HAL_TIM_OC_Start_IT(&htim12, TIM_CHANNEL_1);
}

void Orchestrator::flashNotifyFromISR(uint16_t GPIO_Pin) {
	if (_instance && GPIO_Pin == _instance->_trigPin && _instance->_flashTaskHandle) {
//			HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);
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

//    // now in thread context — safe to do HAL calls
//    xEventGroupClearBits(_doneEvents, BIT_PRINTING_DONE);
    Printer::instance()->setFlashOnLast(true);
    Printer::instance()->enqueue(_imagingDroplets, _imagingFreq,PulseMode::BOTH);
//    waitForBit(BIT_PRINTING_DONE);
//    MX_FLASH_ONCE();

//    scheduleFlashIn(_flashDelay);  // e.g. 1800 for 1.8 ms, output compare fires the flash

    // 4) then don’t proceed until the Pi’s line goes back low
    while (HAL_GPIO_ReadPin(_trigPort, _trigPin) == GPIO_PIN_SET) {
      vTaskDelay(pdMS_TO_TICKS(1));
    }
  }
}

extern "C" void MX_FLASH_TriggerCallback(uint16_t GPIO_Pin) {
//	HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_13);
	Orchestrator::instance()->flashNotifyFromISR(GPIO_Pin);
}
