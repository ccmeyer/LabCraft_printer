/*
 * Stepper.h
 *
 *  Created on: Jun 17, 2025
 *      Author: conar
 */

#ifndef INC_STEPPER_H_
#define INC_STEPPER_H_

#include "BoardConfig.h"
#include "StepperLimitPolicy.h"
#include "stm32f4xx_hal.h"
#include "FreeRTOS.h"
#include "event_groups.h"
#include <cstdint>

// maximum number of steppers we’ll track
static constexpr int MAX_STEPPERS = 5;

class Stepper {
public:

  /// Identify which axis this instance drives
  enum Axis {
	X_AXIS = 0,
	Y_AXIS = 1,
	Z_AXIS = 2,
	P_AXIS = 3,
	R_AXIS = 4,
	NUM_AXES = 5
  };
  /// Construct & register yourself
  Stepper();

  /// Retrieve the stepper for a given axis (nullptr if not inited)
  static Stepper* getAxis(Axis axis);
  static Stepper* stepperX() { return getAxis(X_AXIS); }
  static Stepper* stepperY() { return getAxis(Y_AXIS); }
  static Stepper* stepperZ() { return getAxis(Z_AXIS); }
  static Stepper* stepperP() { return getAxis(P_AXIS); }
#if LC_PRESSURE_PORTS > 1
  static Stepper* stepperR() { return getAxis(R_AXIS); }
#else
  static Stepper* stepperR() { return nullptr; }
#endif
  /// Bind this object to a hardware timer + pins + doneBit (doneBit must be one of your BIT_STEPPERx_DONE macros)
  void begin(
	Axis			   axis,
    TIM_HandleTypeDef* htim,
    GPIO_TypeDef*      stepPort, uint16_t stepPin,
    GPIO_TypeDef*      dirPort,  uint16_t dirPin,
    GPIO_TypeDef*      enPort,   uint16_t enPin,
    uint32_t           doneBit,  uint16_t prescaler,
	bool			   _invertDirection,
	bool 			   homeDirection
  );

  /// If you invert direction, that logical sense stays the same,
  /// but the hardware DIR pin is driven active‐low instead of high.
  void setDirectionInverted(bool invert) { _invertDirection = invert; }

  /** Schedule a move:
   *  - `steps` full steps total
   *  - `targetHz` maximum step-frequency in Hz
   *  - `accelSteps` how many full steps to spend accelerating (and same to decelerate)
   */
  void move(bool direction, uint32_t steps, uint32_t targetHz, uint32_t accelSteps);

  void moveTo(bool sign, uint32_t newPos, uint32_t freqHz, uint32_t accelSteps);

  void setSpeedHz(uint32_t freqHz);		/// Change speed on the fly (constant‐rate mode only)

  /// Homing sequence. Returns false if any phase times out.
  /// @param fastHz   coarse feed rate
  /// @param slowHz   fine feed rate
  /// @param backoffSteps  number of full steps to back off between phases
  bool home(uint32_t fastHz, uint32_t slowHz, uint32_t backoffSteps);
  bool waitUntilDone(uint32_t timeoutMs = 0u);
  static uint32_t recommendedWaitTimeoutMs(uint32_t steps, uint32_t freqHz);

  void setHomeDir(bool toward_limit) { _homeTowardLimitDir = toward_limit; }
  void setHomeGuardSteps(uint32_t s) { _homeGuardSteps = s ? s : 100000; }


  /// Abort any in-progress move immediately
  void stop();

  bool _paused = false;
  bool _resume = false;

  /// Temporarily halt the timer but keep _togglesRemaining/_togglesDone
  void pauseMove();

  /// Restart the timer from wherever we left off
  void resumeMove();

  /// Cancel the move entirely (clear remaining toggles)
  void cancelMove();

  void enableMotor();
  void disableMotor();

  /// Called from IRQ → fan out to the correct object
  static void dispatch(TIM_HandleTypeDef* htim);

  /// True if you’re mid‐move
  bool isBusy() const { return _togglesRemaining > 0; }

  /// Current full-step position
  int32_t getPosition() const { return _pos; }
  int32_t getTargetPosition() const { return _targetPos; }


  void configureLimitPin(GPIO_TypeDef* port, uint16_t pin);
  /// Call this once (from your Init wrapper) to attach a switch
  void attachLimitSwitch(GPIO_TypeDef* port,
                         uint16_t      pin,
                         TickType_t    debounceMs = 10,
						 bool          activeHigh = true,
                         StepperLimitPolicy::PullMode pullMode = StepperLimitPolicy::PullMode::Auto);

  void setHomeHardStopOnLimit(bool enabled) { _homeHardStopOnLimit = enabled; }

  /// Called once we’ve confirmed the switch really is closed
  void onLimitTriggered();

  // static helper to route the EXTI callback into the right Stepper
  static void handleExtiFromIsr(uint16_t pin);

  uint16_t dirPin() const { return _dirPin; }
  GPIO_TypeDef* dirPort() const { return _dirPort; }

  uint16_t enPin() const { return _enPin; }
  GPIO_TypeDef* enPort() const { return _enPort; }

  /// Add a second driver (must be called *after* the primary `begin()`)
  void addDriver(
    GPIO_TypeDef* stepPort, uint16_t stepPin,
    GPIO_TypeDef* dirPort,  uint16_t dirPin,
    GPIO_TypeDef* enPort,   uint16_t enPin
  );

  // Motion-profile shape for accel/decel interpolation (jerk behavior)
  enum AccelProfile : uint8_t {
    PROFILE_TRAPEZOIDAL_LINEAR = 0,   // constant accel (jerk is impulsive)
    PROFILE_SCURVE_COSINE      = 1,   // smooth accel using 0.5*(1-cos(pi*t))
    PROFILE_SCURVE_MINJERK     = 2    // min-jerk 10-15-6 polynomial
  };

  void setAccelProfile(AccelProfile p) { _profile = p; }
  AccelProfile accelProfile() const { return _profile; }

  // Acceleration in steps/s^2 (per axis). Gantry will use this to compute accelSteps.
  void  setAccelStepsPerSec2(float a) { _accel_sps2 = (a > 1.f ? a : 1.f); }
  float accelStepsPerSec2() const     { return _accel_sps2; }

  // Optional per-axis speed cap (Hz of step pulses)
  void     setMaxSpeedHz(uint32_t hz) { _max_speed_hz = (hz ? hz : 1u); }
  uint32_t maxSpeedHz() const         { return _max_speed_hz; }


private:
  // hardware bindings
  TIM_HandleTypeDef* _htim      = nullptr;
  GPIO_TypeDef*      _stepPort  = nullptr;
  uint16_t           _stepPin   = 0;
  GPIO_TypeDef*      _dirPort   = nullptr;
  uint16_t           _dirPin    = 0;
  GPIO_TypeDef*      _enPort    = nullptr;
  uint16_t           _enPin     = 0;
  uint32_t           _doneBit   = 0;       // event‐group bit
  uint16_t			 _prescaler = 0;
  bool				 _invertDirection = false;

  // *** optional second driver ***
  bool               _dualDriver = false;
  GPIO_TypeDef*      _stepPort2  = nullptr;
  uint16_t           _stepPin2   = 0;
  GPIO_TypeDef*      _dirPort2   = nullptr;
  uint16_t           _dirPin2    = 0;
  GPIO_TypeDef*      _enPort2    = nullptr;
  uint16_t           _enPin2     = 0;

  // Define and retrieve the specified axes stepper
  Axis               _axis      = X_AXIS;
  static Stepper*    _axes[NUM_AXES];

  // position tracking
  int32_t  _pos        = 0;
  int32_t  _targetPos  = 0;
  bool     _direction  = true;

  // motion profile
  uint32_t _totalToggles     = 0;   // 2×full steps
  uint32_t _togglesRemaining = 0;
  uint32_t _togglesDone      = 0;
  uint32_t _accelToggles     = 0;   // 2×accelSteps
  uint32_t _decelToggles     = 0;

  // timer periods
  uint32_t _startARR    = 0;
  uint32_t _targetARR   = 0;
  int32_t  _deltaARR    = 0;       // may be negative

  // Save last move
  bool     _lastDirection  = true;
  uint32_t _lastFreqHz = 0;
  uint32_t _lastAccel = 0;

  AccelProfile _profile       = PROFILE_SCURVE_COSINE; // default: gentle S-curve
  float        _accel_sps2    = 140000.f;   // sensible default; tune per axis
  uint32_t     _max_speed_hz  = 40000u;    // per-axis cap; clamp in Gantry

  // --- Soft-stop on endstop support ---
  bool     _softStopOnLimit = false;   // enable only during home approaches
  bool     _inSoftStop      = false;   // we've already re-shaped the tail

  // Soft-stop tuning
  float    _softstop_accel_factor        = 4.0f;   // default: ~6× normal accel
  float    _softstop_accel_override_sps2 = 0.f;    // 0=off; when >0, use this accel
  uint32_t _softstop_floor_hz            = 200u;   // final crawl rate at end of brake

  void     _requestSoftStop();         // re-shape current move into a decel tail

  // called each timer tick
  void          _stepTick();

  // your existing members …
  GPIO_TypeDef*   _limPort    = nullptr;
  uint16_t        _limPin     = 0;
  TimerHandle_t   _debounceTimer = nullptr;
  uint32_t        _limitPull = GPIO_NOPULL;

  IRQn_Type   _extiIRQn   = (IRQn_Type)0;
  uint8_t     _extiLine   = 0;          // 0..15
  bool        _limitActiveHigh = true; // pressed = HIGH? (else LOW)
  volatile bool _limitSeenThisMove = false;
  volatile bool _limitHandledThisMove = false;
  volatile bool _limitDroppedAfterLatch = false;
  volatile uint32_t _limitHitCount = 0u;
  volatile uint32_t _limitDropCount = 0u;

  bool     _homeTowardLimitDir = false;     // default; set per-axis in init
  uint32_t _homeGuardSteps     = 300000;    // large but finite
  bool     _homeHardStopOnLimit = false;

  // ISR entrypoint
  void _onRawLimitInterruptFromIsr();
  void _maskExtiLineFromIsr();
  void _unmaskExtiLineFromIsr();
  void _unmaskExtiLine();
  void _onLimitTriggeredFromIsr(BaseType_t* pxHigherPriorityTaskWoken);
  bool _backOffLimitUntilReleased(uint32_t chunkSteps,
                                  uint32_t freqHz,
                                  uint32_t releaseGuardSteps,
                                  bool alwaysBackOffOnce,
                                  const char* phaseLabel);
  void _resetMoveLimitState();
  void _logLimitDebug(const char* reason) const;

  // software‐timer callback (runs in task context)
  static void _debounceTimerCb(TimerHandle_t timer);

  inline bool _isLimitAsserted() const {
    GPIO_PinState s = HAL_GPIO_ReadPin(_limPort, _limPin);
    return (s == GPIO_PIN_SET) == _limitActiveHigh;
  }
};

// C‐API wrappers
extern "C" {
  void MX_STEPPERX_Init(void);
  void MX_STEPPERY_Init(void);
  void MX_STEPPERZ_Init(void);
  void MX_STEPPERP_Init(void);
#if (LC_PRESSURE_PORTS > 1)
  void MX_STEPPERR_Init(void);
#endif

  void MX_STEPPERX_Move(uint8_t d, uint32_t s, uint32_t f, uint32_t a);
  void MX_STEPPERY_Move(uint8_t d, uint32_t s, uint32_t f, uint32_t a);
  void MX_STEPPERZ_Move(uint8_t d, uint32_t s, uint32_t f, uint32_t a);
  void MX_STEPPERP_Move(uint8_t d, uint32_t s, uint32_t f, uint32_t a);
#if (LC_PRESSURE_PORTS > 1)
  void MX_STEPPERR_Move(uint8_t d, uint32_t s, uint32_t f, uint32_t a);
#endif

  void MX_STEPPERX_MoveTo(uint8_t d, uint32_t s, uint32_t f, uint32_t a);
  void MX_STEPPERY_MoveTo(uint8_t d, uint32_t s, uint32_t f, uint32_t a);
  void MX_STEPPERZ_MoveTo(uint8_t d, uint32_t s, uint32_t f, uint32_t a);
  void MX_STEPPERP_MoveTo(uint8_t d, uint32_t s, uint32_t f, uint32_t a);
#if (LC_PRESSURE_PORTS > 1)
  void MX_STEPPERR_MoveTo(uint8_t d, uint32_t s, uint32_t f, uint32_t a);
#endif

  void MX_STEPPERX_Home(uint32_t fastHz, uint32_t slowHz, uint32_t backoffSteps);
  void MX_STEPPERY_Home(uint32_t fastHz, uint32_t slowHz, uint32_t backoffSteps);
  void MX_STEPPERZ_Home(uint32_t fastHz, uint32_t slowHz, uint32_t backoffSteps);
  void MX_STEPPERP_Home(uint32_t fastHz, uint32_t slowHz, uint32_t backoffSteps);
#if (LC_PRESSURE_PORTS > 1)
  void MX_STEPPERR_Home(uint32_t fastHz, uint32_t slowHz, uint32_t backoffSteps);
#endif
  uint8_t MX_STEPPERX_IsBusy(void);
  uint8_t MX_STEPPERY_IsBusy(void);
  uint8_t MX_STEPPERZ_IsBusy(void);
  uint8_t MX_STEPPERP_IsBusy(void);
#if (LC_PRESSURE_PORTS > 1)
  uint8_t MX_STEPPERR_IsBusy(void);
#endif

  void MX_STEPPERX_Stop(void);
  void MX_STEPPERY_Stop(void);
  void MX_STEPPERZ_Stop(void);
  void MX_STEPPERP_Stop(void);
#if (LC_PRESSURE_PORTS > 1)
  void MX_STEPPERR_Stop(void);
#endif

}

#endif /* INC_STEPPER_H_ */
