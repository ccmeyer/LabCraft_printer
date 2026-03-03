/*
 * PressureRegulator.h
 *
 *  Created on: Jun 21, 2025
 *      Author: conar
 */

#ifndef INC_PRESSUREREGULATOR_H_
#define INC_PRESSUREREGULATOR_H_
#include "Stepper.h"
#include "PressureSensor.h"
#include "PressureTraceRecorder.h"
#include "FreeRTOS.h"
#include "task.h"
#include <cmath>
#include "BoardConfig.h"

class PressureRegulator {
public:
  enum class PulseType : uint8_t {
    Print = 0,
    Refuel = 1
  };

  struct DisturbanceEvent {
    PulseType type = PulseType::Print;
    uint16_t pulseWidthUs = 0;
    uint16_t dropletCount = 1;
    uint16_t pressureAtTrigger = 0;
    uint32_t tickMs = 0;
  };

  struct RecoveryConfig {
    uint16_t activeTicks = 4;
    uint16_t baseBoostHz = 1500;
    uint16_t pulseCoeffHzPerUs = 1;
    uint16_t pressureCoeffHzPerRaw = 1;
    uint16_t maxBoostHz = 8000;
    uint16_t recoveryFloorHz = 0;
    uint16_t recoveryExitErrorRaw = 3;
    uint16_t maxExtendTicks = 0;
    bool allowExtendWhileUndershoot = false;
    bool boostOnlyWhenUndershoot = true;
    bool linearDecay = true;
  };

  struct SlewConfig {
    uint32_t maxHzDeltaUpPerLoop = 2000;
    uint32_t maxHzDeltaDownPerLoop = 2000;
    uint8_t recoveryBypassSlewTicks = 0;
  };

  struct ReadyConfig {
    uint16_t readyTolRaw = 4;
    uint8_t consecutiveSamples = 1;
  };

  /// Configure the regulator loop.
  /// @param stepper       Reference to the Stepper driving this chamber
  /// @param htim          The same TIM_HandleTypeDef* you gave that Stepper
  /// @param targetPressure  Pressure units you want to hold
  /// @param minRateHz     Minimum stepping rate (Hz) in the “coast” region
  /// @param maxRateHz     Maximum stepping rate (Hz) when far off target
  /// @param tolerance     ±range around target in pressure units
  void begin(
    Stepper&            stepper,
    TIM_HandleTypeDef*  htim,
	uint8_t				sensorPort,
	int32_t             targetPressure,
    uint32_t            minRateHz,
    uint32_t            maxRateHz,
	int32_t             tolerance,
    GPIO_TypeDef*       valvePort,
    uint16_t            valvePin,
	uint32_t            doneBit
  );
  /// Start the regulation loop (timer + task)
  void start();

  /// Pause regulation (timer + task)
  void pause();

  /// Change the target on the fly
  void setTarget(int32_t p) { _target = p; }
  void setRelativeTarget(bool sign, int32_t p);
  void setTargetSafe(int32_t requested);
  void setRelativeTargetSafe(bool sign, int32_t delta);
  uint32_t getCurrentArr() const { return _currentArr; }
  uint32_t getTarget() const { return _target; }

  bool isActive() const { return _active; }

  /// Perform homing sequence with valve open/close around stepper home
  void homeWithValve(uint32_t fastHz, uint32_t slowHz, uint32_t backoffSteps);
  void homeWithValveFast();
  void requestSafetyHome();

  void resetSyringe();

  void openValve();
  void closeValve();
  bool isValveOpen() const {
    return (_valvePort != nullptr) &&
           (_valvePin != 0u) &&
           (HAL_GPIO_ReadPin(_valvePort, _valvePin) == GPIO_PIN_SET);
  }

  // after both have been begun you can call these:
  static PressureRegulator& regP() { return *get(0); }
#if (LC_PRESSURE_PORTS > 1)
  static PressureRegulator& regR() { return *get(1); }
#else
  // Legacy build: keep symbol for compile-compat, but alias to P.
  // If you prefer "hard fail", remove this and update call sites instead.
  static PressureRegulator& regR() { return *get(0); }
#endif

  bool isPressureOk() const { return _pressureOk; }
  void setRecoveryConfig(const RecoveryConfig& cfg) { _recoveryCfg = cfg; }
  RecoveryConfig getRecoveryConfig() const { return _recoveryCfg; }
  void setReadyConfig(const ReadyConfig& cfg) {
    _readyCfg = cfg;
    _printTol = cfg.readyTolRaw;
  }
  ReadyConfig getReadyConfig() const { return _readyCfg; }
  void notifyPulseStart(const DisturbanceEvent& ev);
  void notifyPulseEnd(const DisturbanceEvent& ev);
  bool isRecoveryActive() const { return _recoveryActive; }
  uint32_t getCurrentRecoveryBoostHz() const { return _recoveryCurrentBoostHz; }
  void setSlewConfig(const SlewConfig& cfg) { _slewCfg = cfg; }
  SlewConfig getSlewConfig() const { return _slewCfg; }

  // Call ~1–2 ms before opening the droplet valve
  void beginDispenseQuiet(uint32_t pre_ms = 2);
  // Call immediately after closing the droplet valve
  void endDispenseQuiet(uint32_t post_ms = 3);

  // Switch to the gentler PID while printing arrays
  void setPrintProfile(bool enabled);

  // Attach the "inner end" limit switch (near syringe end)
  // activeHigh=false for the common NO-to-GND wiring with pull-up
  void attachInnerLimitSwitch(GPIO_TypeDef* port,
                              uint16_t      pin,
                              TickType_t    debounceMs = pdMS_TO_TICKS(15),
                              bool          activeHigh  = true);

  // static router from EXTI to the right instance
  static void handleInnerLimitFromIsr(uint16_t pin);

private:
  Stepper*           _stepper    = nullptr;
  TIM_HandleTypeDef* _htim       = nullptr;
  int32_t            _target     = 0;
  uint32_t           _minHz      = 0;
  uint32_t           _maxHz      = 0;
  int32_t            _tol        = 0;
  TaskHandle_t       _taskHandle = nullptr;

  int32_t _minTarget   = 1638;        // raw sensor units
  int32_t _maxTarget   = 6007;    // raw sensor units (14-bit)
  int32_t _maxCmdStep  = 3000;      // max change allowed per setTargetSafe() call
  int32_t _maxRelStep  = 880;      // max |delta| allowed per relative change

  uint32_t             _doneBit   = 0;

  volatile bool		 _active	 = false;
  uint8_t			 _sensorPort = 0;

  uint32_t			 _printTol	 = 0;
  bool 				 _pressureOk = false;

  bool        _quietActive = false;
//  bool        _pausedByQuiet = false;
  TickType_t  _quietReleaseTick = 0;
  bool        _freezeI = false;
  bool       _quietPreHold    = false;   // true after begin(), false after end()

  // valve control
  GPIO_TypeDef*      _valvePort  = nullptr;
  uint16_t           _valvePin   = 0;
  bool               _homing     = false;
  bool				 _resetting	 = false;
  uint32_t			 _stepLimit	 = 100000;
  uint32_t			 _resetPos	 = 500;

  // control state
  bool     _stepping    = false;
  uint32_t _lastRateHz  = 0;
  bool     _lastDir     = false;
  uint32_t _currentArr = 0;

//  bool 	   wasNegative = false;

  static constexpr uint32_t MAX_STEPS = 10000000;  // “infinite” for our purposes

  // registry machinery:
#if (LC_PRESSURE_PORTS > 1)
  	static constexpr int MAX_REGS = 2;
#else
    static constexpr int MAX_REGS = 1;
#endif
	static PressureRegulator* _registry[MAX_REGS];
	static int                _regCount;
	static PressureRegulator* get(int i) {
	    // Safe fallback: return first registered regulator if index is invalid
	    if (_regCount <= 0) return nullptr;
	    if (i < 0 || i >= _regCount) return _registry[0];
	    if (_registry[i] == nullptr) return _registry[0];
	    return _registry[i];
	}
	// integer PID (fixed point)
	static constexpr uint32_t GAIN = 1024;      // 10-bit fraction
	static constexpr float    DT   = 0.005f;    // 5 ms
	// Pre-scaled integer gains:
	// KP_S = KP * GAIN
	// KI_S = (KI * DT) * GAIN   (integral accumulates raw error per tick)
	// KD_S = (KD / DT) * GAIN   (derivative is error delta per tick)
	static constexpr int32_t  KP_S = int32_t(30.0f   * GAIN);                 // 30720
	static constexpr int32_t  KI_S = int32_t(1.2f*DT * GAIN + 0.5f);          // 2
	static constexpr int32_t  KD_S = int32_t((0.015f/DT) * GAIN + 0.5f);      // 3072

  int32_t  _lastError = 0;
//	int64_t  _integral  = 0;   // scaled by 1 (since KI_S already has DT)


	  // Runtime-tunable PID gains (start with your existing constants)
	  int32_t _KPc = KP_S, _KIc = KI_S, _KDc = KD_S;
	  // Softer profile for printing (reduce aggressiveness)
	  int32_t _KP_print = KP_S/2, _KI_print = 0, _KD_print = KD_S/2;
	  int32_t _KP_track = KP_S,   _KI_track = KI_S, _KD_track = KD_S;

	  int64_t  _integral  = 0;     // scaled by 1
	  int64_t  _I_contrib = 0;     // tracks _KIc * _integral across gain changes
  RecoveryConfig _recoveryCfg{};
  ReadyConfig _readyCfg{};
  bool _recoveryActive = false;
  uint16_t _recoveryTicksRemaining = 0;
  uint16_t _recoveryTicksInitial = 0;
  uint32_t _recoveryInitialBoostHz = 0;
  uint32_t _recoveryCurrentBoostHz = 0;
  uint16_t _recoveryPressureAtTrigger = 0;
  uint16_t _recoveryPulseWidthUs = 0;
  uint32_t _recoveryTriggerTickMs = 0;
  uint16_t _recoveryTicksExtended = 0;
  uint8_t _recoveryBypassRemaining = 0;
  uint8_t _readyConsecutiveCount = 0;
  bool _traceLastPressureOk = false;

	  static constexpr int64_t I_CAP = 20000;  // same cap used in the loop

  static constexpr uint32_t MAX_HZ_DELTA_PER_LOOP = 2000;
  SlewConfig _slewCfg{};
  SlewConfig _slewCfgTrack{MAX_HZ_DELTA_PER_LOOP, MAX_HZ_DELTA_PER_LOOP, 0};
  SlewConfig _slewCfgPrint{500, 300, 2};

	//	  static constexpr uint32_t MAX_STEPS = 10000000;


  static void taskEntry(void* pv) {
    static_cast<PressureRegulator*>(pv)->controlLoop();
  }
  void controlLoop();
  PressureTraceChannel traceChannel() const {
    return (_sensorPort == 0u) ? PressureTraceChannel::Print : PressureTraceChannel::Refuel;
  }
  void recordTraceSample(const PressureSensor::ControlSample& sample,
                         int32_t error,
                         int32_t dErr,
                         uint32_t requestedHz,
                         uint32_t appliedHz,
                         bool dir);
  void recordTraceEvent(PressureTraceEventType type, uint16_t value0 = 0, uint16_t value1 = 0);
  uint32_t computeRecoveryBoostHz() const;


  // ---------- Inner-limit (syringe end) support ----------
  GPIO_TypeDef* _innerPort        = nullptr;
  uint16_t      _innerPin         = 0;
  bool          _innerActiveHigh  = false;
  TimerHandle_t _innerDebounceTmr = nullptr;
  IRQn_Type     _innerIRQn        = (IRQn_Type)0;
  uint8_t       _innerLine        = 0; // 0..15

  void _onRawInnerLimitInterruptFromIsr();
  static void _innerDebounceTimerCb(TimerHandle_t t);

  // Notification bit to request homing from the task context
  static constexpr uint32_t NOTIF_INNER_LIMIT = (1u << 0);
  static constexpr uint32_t NOTIF_SAFETY_HOME = (1u << 1);

  // Default homing parameters used when inner limit is hit
  static constexpr uint32_t kHomeFastHzDefault   = 30000;
  static constexpr uint32_t kHomeSlowHzDefault   = 3000;
  static constexpr uint32_t kHomeBackoffDefault  = 400;
};

#endif /* INC_PRESSUREREGULATOR_H_ */
