#ifndef INC_PRESSUREREGULATORMATH_H_
#define INC_PRESSUREREGULATORMATH_H_

#include <cstdint>

namespace PressureRegulatorMath {

enum class PressureRejectReason : uint8_t {
  None = 0,
  RailLow,
  RailHigh,
  Spike
};

struct TargetLimits {
  int32_t currentTarget = 0;
  int32_t minTarget = 0;
  int32_t maxTarget = 0;
  int32_t maxCmdStep = 0;
  int32_t maxRelStep = 0;
};

struct ValidationConfig {
  uint16_t minRaw = 1200;
  uint16_t maxRaw = 7000;
  uint16_t maxStepPerSample = 250;
  uint8_t maxConsecutiveRejects = 3;
};

struct ValidationResult {
  bool accept = false;
  PressureRejectReason reason = PressureRejectReason::None;
  uint16_t committedRaw = 0;
};

struct ProfileState {
  int32_t kpCurrent = 0;
  int32_t kiCurrent = 0;
  int32_t kdCurrent = 0;
  int32_t kpPrint = 0;
  int32_t kiPrint = 0;
  int32_t kdPrint = 0;
  int32_t kpTrack = 0;
  int32_t kiTrack = 0;
  int32_t kdTrack = 0;
  int64_t integral = 0;
  int64_t iContrib = 0;
  int64_t iCap = 0;
  uint32_t maxHzDeltaPerLoop = 0;
  uint32_t maxHzDeltaPrint = 0;
  uint32_t maxHzDeltaTrack = 0;
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

struct RecoveryState {
  uint32_t baseRequestedHz = 0;
  uint32_t decayedBoostHz = 0;
  bool recoveryActive = false;
  int32_t errorRaw = 0;
  int32_t readyTolRaw = 0;
  bool boostOnlyWhenUndershoot = true;
  uint32_t maxRequestedHz = 0;
  uint32_t minRequestedHz = 0;
  uint32_t recoveryFloorHz = 0;
};

struct SlewConfig {
  uint32_t maxHzDeltaUpPerLoop = 2000;
  uint32_t maxHzDeltaDownPerLoop = 2000;
};

int32_t clampTarget(const TargetLimits& limits, int32_t requested);
int32_t clampRelativeTarget(const TargetLimits& limits, bool sign, int32_t delta);
int32_t targetRawToFixed(int32_t targetRaw, uint8_t fractionalBits);
int32_t targetFixedToRaw(int32_t targetFixed, uint8_t fractionalBits);
bool isTargetRampActive(int32_t rampedTargetFixed,
                        int32_t requestedTargetRaw,
                        uint8_t fractionalBits);
int32_t advanceRampedTarget(int32_t rampedTargetFixed,
                            int32_t requestedTargetRaw,
                            uint32_t slewRawPerSec,
                            uint32_t elapsedMs,
                            uint8_t fractionalBits);
uint32_t capRequestedHzForTargetRamp(uint32_t requestedHz,
                                     bool rampActive,
                                     uint32_t capHz);
bool pressureReadyForRequestedTarget(int32_t pressureRaw,
                                     int32_t requestedTargetRaw,
                                     uint32_t readyTolRaw,
                                     bool rampActive);
ProfileState applyPrintProfile(const ProfileState& state, bool enabled);
ValidationResult validatePressureSample(uint16_t previous,
                                        uint16_t incoming,
                                        uint8_t consecutiveRejects,
                                        const ValidationConfig& cfg);
uint32_t computeRecoveryBoostHz(uint16_t triggerPressureRaw,
                                uint16_t pulseWidthUs,
                                const RecoveryConfig& cfg,
                                uint16_t psiOffsetRaw);
uint32_t decayRecoveryBoostHz(uint32_t initialBoostHz,
                              uint16_t ticksRemaining,
                              uint16_t ticksInitial,
                              bool linearDecay);
uint16_t computeDeadlineSlipMs(uint32_t nominalTickMs, uint32_t actualTickMs);
uint32_t computeRecoveryRequestedHz(const RecoveryState& state);
uint32_t applyAsymmetricSlew(uint32_t requestedHz,
                             uint32_t lastHz,
                             const SlewConfig& cfg);
uint16_t defaultReadyTolRaw(uint8_t sensorPort);
bool shouldExtendRecovery(int32_t errorRaw,
                          int32_t readyTolRaw,
                          uint16_t ticksExtended,
                          uint16_t maxExtendTicks,
                          bool allowExtendWhileUndershoot,
                          uint16_t recoveryExitErrorRaw);

}  // namespace PressureRegulatorMath

#endif /* INC_PRESSUREREGULATORMATH_H_ */
