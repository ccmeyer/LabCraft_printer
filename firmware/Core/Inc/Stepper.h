/*
 * Stepper.h
 *
 *  Created on: Jun 17, 2025
 *      Author: conar
 */

#ifndef INC_STEPPER_H_
#define INC_STEPPER_H_

#include "BoardConfig.h"
#include "DirectStepperProfile.h"
#include "HomeInterruptionPolicy.h"
#include "MotionLimitDebouncePolicy.h"
#include "StepperLimitPolicy.h"
#include "StepperIsrInstrumentation.h"
#include "stm32f4xx_hal.h"
#include "FreeRTOS.h"
#include "event_groups.h"
#include <cstdint>

class Gantry;

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

  enum class DirectMoveStartStatus : uint8_t {
    Started = 0u,
    Immediate = 1u,
    Unavailable = 2u,
    Busy = 3u,
    InvalidRequest = 4u,
    PositionOutOfRange = 5u,
    LimitBlocked = 6u,
  };

  enum class DirectMoveState : uint8_t {
    Idle = 0u,
    Armed = 1u,
    Running = 2u,
    Paused = 3u,
    Completed = 4u,
    Canceled = 5u,
    LimitAborted = 6u,
    Faulted = 7u,
  };

  enum class DirectMoveTerminalReason : uint8_t {
    None = 0u,
    Completed = 1u,
    Canceled = 2u,
    LimitAborted = 3u,
    ProfileFault = 4u,
    StartRejected = 5u,
  };

  struct DirectMoveSnapshot {
    Axis axis = X_AXIS;
    DirectMoveStartStatus startStatus = DirectMoveStartStatus::Unavailable;
    DirectMoveState state = DirectMoveState::Idle;
    DirectMoveTerminalReason terminalReason = DirectMoveTerminalReason::None;
    int32_t startPosition = 0;
    int32_t targetPosition = 0;
    int32_t endPosition = 0;
    uint32_t requestedEdges = 0u;
    uint32_t emittedEdges = 0u;
    uint32_t resumeCount = 0u;
    uint32_t resumeStartRateHz = 0u;
    uint32_t resumeStartArr = 0u;
    uint32_t pauseCleanupEdges = 0u;
    uint32_t resumeStartFailures = 0u;
    bool direction = true;
    bool movingTowardLimit = false;
    bool limitAssertedAtStart = false;
    bool limitSeen = false;
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
  DirectMoveStartStatus move(bool direction,
                             uint32_t steps,
                             uint32_t targetHz,
                             uint32_t accelSteps);

  DirectMoveStartStatus moveTo(bool sign,
                               uint32_t newPos,
                               uint32_t freqHz,
                               uint32_t accelSteps);

  void setSpeedHz(uint32_t freqHz);		/// Change speed on the fly (constant‐rate mode only)

  /// Homing sequence with cooperative operator cancellation.
  /// @param fastHz   coarse feed rate
  /// @param slowHz   fine feed rate
  /// @param backoffSteps  number of full steps to back off between phases
  HomeInterruptionPolicy::Outcome home(
      uint32_t fastHz,
      uint32_t slowHz,
      uint32_t backoffSteps,
      const HomeInterruptionPolicy::CancellationToken* cancelToken = nullptr);
  bool waitUntilDone(
      uint32_t timeoutMs = 0u,
      const HomeInterruptionPolicy::CancellationToken* cancelToken = nullptr);
  static uint32_t recommendedWaitTimeoutMs(uint32_t steps, uint32_t freqHz);

  void setHomeDir(bool toward_limit) { _homeTowardLimitDir = toward_limit; }
  void setHomeGuardSteps(uint32_t s) { _homeGuardSteps = s ? s : 100000; }
  uint32_t homeGuardSteps() const { return _homeGuardSteps; }


  /// Abort any in-progress move immediately
  void stop();

  bool _paused = false;
  bool _resume = false;

  /// Temporarily halt the timer but keep _togglesRemaining/_togglesDone
  void pauseMove();

  /// Restart the timer from wherever we left off
  DirectMoveStartStatus resumeMove();

  /// Cancel the move entirely (clear remaining toggles)
  void cancelMove();

  void enableMotor();
  void disableMotor();

  /// Called from IRQ → fan out to the correct object
  static void dispatch(TIM_HandleTypeDef* htim);

  /// True if you’re mid‐move
  bool isBusy() const { return _togglesRemaining > 0 || _coordinatedReserved; }

  /// Current full-step position
  int32_t getPosition() const { return _pos; }
  int32_t getTargetPosition() const { return _targetPos; }
  DirectMoveSnapshot getLastDirectMoveSnapshot() const;
  bool stepIsLow() const;

  struct HomeDiagnosticSnapshot {
    enum class Phase : uint8_t {
      NotStarted = 0,
      InitialCheck,
      InitialRelease,
      CoarseSeek,
      Probe,
      PreFineRelease,
      FineSeek,
      FinalBackoff,
    };

    int32_t startPositionSteps = 0;
    int32_t endPositionSteps = 0;
    int32_t fineLimitPositionSteps = 0;
    int32_t finalBackoffPositionSteps = 0;
    uint32_t coarseCommandSteps = 0;
    uint32_t coarseAccountedSteps = 0;
    uint32_t moveTimeoutCount = 0;
    uint32_t blockedStartRecoveryCount = 0;
    uint32_t moveStartFailureCount = 0;
    DirectMoveStartStatus lastMoveStartStatus =
        DirectMoveStartStatus::Unavailable;
    Phase phase = Phase::NotStarted;
    HomeInterruptionPolicy::Outcome outcome =
        HomeInterruptionPolicy::Outcome::NotStarted;
    bool limitSeen = false;
    bool limitAsserted = false;
    bool success = false;
  };

  HomeDiagnosticSnapshot getLastHomeDiagnosticSnapshot() const { return _homeDiagnosticSnapshot; }
  StepperIsrInstrumentation::Snapshot getLastMoveInstrumentationSnapshot() const;
  DirectStepperProfile::Snapshot getLastDirectProfileSnapshot() const {
    return DirectStepperProfile::snapshot(_directProfileState);
  }
  bool isLimitAssertedForDiagnostics() const { return _isLimitAsserted(); }
  MotionLimitDebouncePolicy::Snapshot getLimitDebounceSnapshot() const;
  bool limitDebounceTimebaseValid() const;
  bool homeDirectionTowardLimitForDiagnostics() const {
    return _homeTowardLimitDir;
  }
  bool enableOutputsAssertedForDiagnostics() const {
    if (_enPort == nullptr || (_enPort->ODR & _enPin) != 0u) return false;
    return !_dualDriver ||
           (_enPort2 != nullptr && (_enPort2->ODR & _enPin2) == 0u);
  }


  void configureLimitPin(GPIO_TypeDef* port, uint16_t pin);
  /// Attach a switch using the fixed production 15 ms confirmation policy.
  void attachLimitSwitch(GPIO_TypeDef* port,
                         uint16_t      pin,
                         bool          activeHigh = true,
                         StepperLimitPolicy::PullMode pullMode = StepperLimitPolicy::PullMode::Auto);

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
  friend class Gantry;
  DirectMoveStartStatus _moveWithInitialRate(bool direction,
                                             uint32_t steps,
                                             uint32_t targetHz,
                                             uint32_t accelSteps,
                                             uint32_t initialRateHz);

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
  volatile bool _coordinatedReserved = false;
  volatile bool _homeSequenceActive = false;
  volatile bool _legacyMoveStartPending = false;
  DirectMoveSnapshot _directMoveSnapshot{};
  DirectMoveSnapshot _directMoveResumeSnapshot{};
  bool _directMoveResumePending = false;
  uint32_t _directMoveEmittedOffset = 0u;

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
  DirectStepperProfile::State _directProfileState{};

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
  bool          _tryReserveCoordinated();
  void          _releaseCoordinatedReservation();
  void          _prepareCoordinatedAxis(bool participating,
                                        bool direction,
                                        int32_t targetPosition);
  void          _writeCoordinatedStep(bool high);
  void          _accountCoordinatedEdge();
  void          _finishCoordinatedAxis(bool aborted);
  void          _finishAbortedCoordinatedAxisFromLow();
  void          _finishCompletedCoordinatedAxisFromLow();
  bool          _coordinatedStepIsLow() const;
  bool          _readCoordinatedStepHigh(bool& high) const;
#if defined(__GNUC__) && !defined(UNIT_TEST)
  __attribute__((always_inline)) inline bool
#else
  inline bool
#endif
                _coordinatedLimitAssertedFast() const {
    if (_limPort == nullptr || _limPin == 0u) return false;
    const bool high = (_limPort->IDR & static_cast<uint32_t>(_limPin)) != 0u;
    return high == _limitActiveHigh;
  }

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
  volatile uint32_t _moveGeneration = 0u;
  volatile uint32_t _debounceArmedGeneration = 0u;
  MotionLimitDebouncePolicy::State _limitDebounceState{};
  uint32_t _limitDebounceCycles = 0u;
  bool _limitDebounceTimebaseValid = false;
  volatile bool _limitDebounceIgnoreUntilRelease = false;
  volatile bool _limitReleasePending = false;
  volatile uint32_t _limitReleaseStartCycle = 0u;

  bool     _homeTowardLimitDir = false;     // default; set per-axis in init
  uint32_t _homeGuardSteps     = 300000;    // large but finite
  HomeDiagnosticSnapshot _homeDiagnosticSnapshot{};
  #if (LC_STEPPER_ISR_INSTRUMENTATION_ENABLE != 0)
  StepperIsrInstrumentation::State _isrInstrumentation{};
  #endif

  struct LimitStableSample {
    bool stable = false;
    bool timebaseValid = false;
    uint32_t elapsedCycles = 0u;
  };

  // ISR entrypoint
  void _onRawLimitInterruptFromIsr();
  void _maskExtiLineFromIsr();
  void _unmaskExtiLineFromIsr();
  void _unmaskExtiLine();
  void _prepareForNewMove();
  void _observeLimitLevelFromIsr(bool asserted, uint32_t nowCycle);
  bool _takeConfirmedLimitFromIsr();
  bool _stopForConfirmedLimitFromIsr();
  void _observeLimitLevelFromTask(bool asserted, uint32_t nowCycle);
#if defined(__GNUC__) && !defined(UNIT_TEST)
  __attribute__((always_inline))
#endif
  bool _usesHardwareLimitDebounce() const {
    return _axis == X_AXIS || _axis == Y_AXIS;
  }
  bool _confirmReleasedForNextApproach(
      const HomeInterruptionPolicy::CancellationToken* cancelToken = nullptr);
  LimitStableSample _sampleLimitLevelStable(
      bool assertedLevel,
      const HomeInterruptionPolicy::CancellationToken* cancelToken = nullptr);
  LimitStableSample _sampleLimitStable(
      const HomeInterruptionPolicy::CancellationToken* cancelToken = nullptr);
  bool _backOffLimitUntilReleased(uint32_t chunkSteps,
                                  uint32_t freqHz,
                                  uint32_t releaseGuardSteps,
                                  bool alwaysBackOffOnce,
                                  const char* phaseLabel,
                                  const HomeInterruptionPolicy::CancellationToken* cancelToken);
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
