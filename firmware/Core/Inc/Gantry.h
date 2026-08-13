/*
 * Gantry.h
 *
 *  Created on: Jun 18, 2025
 *      Author: conar
 */

#ifndef INC_GANTRY_H_
#define INC_GANTRY_H_

#include <cstdint>
#include "Stepper.h"
#include "CoordinatedXyExecutor.h"
#include "CoordinatedXyIsrInstrumentation.h"
#include "CoordinatedXyTimerSchedulePolicy.h"

struct GantryPosition {
  int32_t x, y, z;
};

enum class CoordinatedStartStatus : uint8_t {
  Started = 0u,
  Immediate = 1u,
  Disabled = 2u,
  Busy = 3u,
  InvalidPlan = 4u,
  PositionOutOfRange = 5u,
  LimitAsserted = 6u,
  HardwareMismatch = 7u,
  UnsupportedMixedAxis = 8u,
};

struct CoordinatedXySnapshot {
  CoordinatedStartStatus startStatus = CoordinatedStartStatus::Disabled;
  CoordinatedXyExecutor::State state = CoordinatedXyExecutor::State::Idle;
  CoordinatedXyExecutor::TerminalReason terminalReason =
      CoordinatedXyExecutor::TerminalReason::None;
  uint32_t requestedXSteps = 0u;
  uint32_t requestedYSteps = 0u;
  uint32_t emittedXSteps = 0u;
  uint32_t emittedYSteps = 0u;
  uint32_t masterSteps = 0u;
  uint32_t timer2Interrupts = 0u;
  uint32_t timer7Interrupts = 0u;
  uint32_t risingEdges = 0u;
  uint32_t fallingEdges = 0u;
  uint32_t arrMin = 0u;
  uint32_t arrMax = 0u;
  uint32_t pendingUpdateCount = 0u;
  uint32_t timerRearmCount = 0u;
  uint32_t timerRearmPendingCount = 0u;
  uint32_t timerRearmDelayMaxCycles = 0u;
  uint32_t conditionalDecisionCount = 0u;
  uint32_t conditionalDecisionMissingCount = 0u;
  uint32_t conditionalNonRearmSlackMinTicks = 0u;
  uint32_t timerScheduleSaturationFlags = 0u;
  uint32_t selectedMasterRateHz = 0u;
  uint32_t selectedMasterAccelerationStepsPerSec2 = 0u;
  uint32_t accelerationSteps = 0u;
  uint32_t cruiseSteps = 0u;
  uint32_t decelerationSteps = 0u;
  bool triangular = false;
  CoordinatedXyIsrInstrumentation::Snapshot timing{};
  uint32_t durationErrorBasisPoints = 0u;
  uint32_t maskChecksum = 0u;
  uint32_t arrChecksum = 0u;
  int32_t xPosition = 0;
  int32_t yPosition = 0;
  int32_t xTarget = 0;
  int32_t yTarget = 0;
  uint32_t doneBits = 0u;
  bool xStepLow = true;
  bool yStepLow = true;
  bool timerOwned = false;
};

/// High-level controller for a 3-axis gantry (X, Y, Z).
class Gantry {
public:
  /// Get the singleton instance
  static Gantry* instance();

  Gantry();
  void begin();


  /// Move each axis by (dx, dy, dz) full-steps, using feedHz as top speed on the longest axis
  CoordinatedStartStatus moveBy(int32_t dx,
                                int32_t dy,
                                int32_t dz,
                                uint32_t feedHz);

  CoordinatedStartStatus moveTo(int32_t x, int32_t y, uint32_t feedHz);

  CoordinatedStartStatus startCoordinatedXY(int64_t dx,
                                             int64_t dy,
                                             uint32_t requestedRateHz = 0u);
  CoordinatedXySnapshot coordinatedSnapshot() const;
  bool requestCoordinatedLimitAbort(Stepper::Axis axis);
  static bool dispatchCoordinatedTimerFromIsr(TIM_HandleTypeDef* htim);
  static void recordCoordinatedTim2IrqExitFromIsr(uint32_t irqExitCycle);
  static void requestCoordinatedLimitAbortFromIsr(Stepper::Axis axis);

  static void pauseXYZMotors();
  static void resumeXYZMotors();
  static void cancelXYZMotors();

  GantryPosition getPosition() const;

  // Convenience APIs to set accel/profile per axis from app code
  void setAxisAccel(Stepper::Axis ax, float steps_per_s2);
  void setAccelAll(float steps_per_s2);
  void setAccelProfileAll(Stepper::AccelProfile p);


private:
  void _pauseCoordinatedTask();
  void _resumeCoordinatedTask();
  bool _cancelCoordinatedTask();
  void _finishCoordinatedHardware(bool aborted,
                                  bool stepStateKnownLow = false);
  void _finishCoordinatedFromIsr(bool aborted,
                                 BaseType_t* woken,
                                 bool timingSampleWillFollow = false);
  bool _requestCoordinatedLimitAbortTask(Stepper::Axis axis);
  bool _handleCoordinatedTimerFromIsr(TIM_HandleTypeDef* htim);
#if defined(__GNUC__) && !defined(UNIT_TEST)
  __attribute__((hot))
#endif
  bool _handleCoordinatedTim2BodyFromIsr();
  void _resetCoordinatedInstrumentation(uint32_t firstArr);
  void _observeCoordinatedArr(uint32_t arr);

  static Gantry* _instance;
  uint32_t 		 _minStepHz = 3000;
  CoordinatedXyPlanner::CoordinatedXyPlan _coordinatedPlan{};
  CoordinatedXyExecutor::Cursor _coordinatedCursor{};
  Stepper* _coordinatedX = nullptr;
  Stepper* _coordinatedY = nullptr;
  TIM_HandleTypeDef* _coordinatedMasterTimer = nullptr;
  volatile bool _coordinatedTimerOwned = false;
  CoordinatedStartStatus _coordinatedStartStatus = CoordinatedStartStatus::Disabled;
  volatile uint32_t _coordinatedTim7Interrupts = 0u;
  volatile uint32_t _coordinatedPendingUpdateCount = 0u;
  volatile uint32_t _coordinatedArrMin = 0u;
  volatile uint32_t _coordinatedArrMax = 0u;
  volatile uint32_t _coordinatedProgrammedArr = 0u;
  volatile uint32_t _coordinatedTimerRearmCount = 0u;
  volatile uint32_t _coordinatedTimerRearmPendingCount = 0u;
  volatile uint32_t _coordinatedTimerRearmDelayMaxCycles = 0u;
  volatile uint32_t _coordinatedConditionalDecisionCount = 0u;
  volatile uint32_t _coordinatedConditionalDecisionMissingCount = 0u;
  volatile uint32_t _coordinatedConditionalNonRearmSlackMinTicks = 0u;
  volatile uint32_t _coordinatedTimerScheduleSaturationFlags = 0u;
  CoordinatedXyIsrInstrumentation::State _coordinatedTiming{};

};

extern "C" {
  /// Initialize all three steppers (call once, e.g. in main() after MX_STEPPER#_Init)
  void MX_GANTRY_Init(void);

  /// C wrapper for moveBy
  void MX_GANTRY_MoveBy(int32_t dx, int32_t dy, int32_t dz, uint32_t feedHz);
  void MX_GANTRY_MoveTo(int32_t x, int32_t y, int32_t z, uint32_t feedHz);
  void MX_GANTRY_RecordTim2IrqExit(uint32_t irqExitCycle);
}


#endif /* INC_GANTRY_H_ */
