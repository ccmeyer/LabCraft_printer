#include "PressureRegulatorMath.h"

namespace PressureRegulatorMath {

int32_t clampTarget(const TargetLimits& limits, int32_t requested) {
  int32_t clamped = requested;
  if (clamped < limits.minTarget) clamped = limits.minTarget;
  if (clamped > limits.maxTarget) clamped = limits.maxTarget;

  int32_t delta = clamped - limits.currentTarget;
  if (delta > limits.maxCmdStep) clamped = limits.currentTarget + limits.maxCmdStep;
  if (delta < -limits.maxCmdStep) clamped = limits.currentTarget - limits.maxCmdStep;

  return clamped;
}

int32_t clampRelativeTarget(const TargetLimits& limits, bool sign, int32_t delta) {
  if (delta < 0) delta = -delta;
  if (delta > limits.maxRelStep) delta = limits.maxRelStep;

  int32_t next = limits.currentTarget + (sign ? delta : -delta);
  if (next < limits.minTarget) next = limits.minTarget;
  if (next > limits.maxTarget) next = limits.maxTarget;
  return next;
}

int32_t targetRawToFixed(int32_t targetRaw, uint8_t fractionalBits) {
  return static_cast<int32_t>(static_cast<int64_t>(targetRaw) *
                              (static_cast<int64_t>(1) << fractionalBits));
}

int32_t targetFixedToRaw(int32_t targetFixed, uint8_t fractionalBits) {
  if (fractionalBits == 0u) {
    return targetFixed;
  }
  const int32_t half = static_cast<int32_t>(1L << (fractionalBits - 1u));
  if (targetFixed >= 0) {
    return (targetFixed + half) / static_cast<int32_t>(1L << fractionalBits);
  }
  return (targetFixed - half) / static_cast<int32_t>(1L << fractionalBits);
}

bool isTargetRampActive(int32_t rampedTargetFixed,
                        int32_t requestedTargetRaw,
                        uint8_t fractionalBits) {
  return rampedTargetFixed != targetRawToFixed(requestedTargetRaw, fractionalBits);
}

int32_t advanceRampedTarget(int32_t rampedTargetFixed,
                            int32_t requestedTargetRaw,
                            uint32_t slewRawPerSec,
                            uint32_t elapsedMs,
                            uint8_t fractionalBits) {
  const int32_t targetFixed = targetRawToFixed(requestedTargetRaw, fractionalBits);
  if ((rampedTargetFixed == targetFixed) || (slewRawPerSec == 0u) || (elapsedMs == 0u)) {
    return rampedTargetFixed;
  }

  const int64_t delta = static_cast<int64_t>(targetFixed) - static_cast<int64_t>(rampedTargetFixed);
  const int64_t absDelta = (delta < 0) ? -delta : delta;
  int64_t step = (static_cast<int64_t>(slewRawPerSec) *
                  static_cast<int64_t>(elapsedMs) *
                  (static_cast<int64_t>(1) << fractionalBits)) / 1000LL;
  if (step <= 0) {
    step = 1;
  }
  if (step >= absDelta) {
    return targetFixed;
  }
  return static_cast<int32_t>(static_cast<int64_t>(rampedTargetFixed) + ((delta > 0) ? step : -step));
}

uint32_t capRequestedHzForTargetRamp(uint32_t requestedHz,
                                     bool rampActive,
                                     uint32_t capHz) {
  if (rampActive && (capHz > 0u) && (requestedHz > capHz)) {
    return capHz;
  }
  return requestedHz;
}

bool pressureReadyForRequestedTarget(int32_t pressureRaw,
                                     int32_t requestedTargetRaw,
                                     uint32_t readyTolRaw,
                                     bool rampActive) {
  if (rampActive) {
    return false;
  }
  const int64_t error = static_cast<int64_t>(pressureRaw) - static_cast<int64_t>(requestedTargetRaw);
  const uint64_t absError = static_cast<uint64_t>((error < 0) ? -error : error);
  return absError <= static_cast<uint64_t>(readyTolRaw);
}

ProfileState applyPrintProfile(const ProfileState& state, bool enabled) {
  ProfileState next = state;
  const int64_t prevIContrib = static_cast<int64_t>(state.kiCurrent) * state.integral;

  next.kpCurrent = enabled ? state.kpPrint : state.kpTrack;
  next.kiCurrent = enabled ? state.kiPrint : state.kiTrack;
  next.kdCurrent = enabled ? state.kdPrint : state.kdTrack;
  next.maxHzDeltaPerLoop = enabled ? state.maxHzDeltaPrint : state.maxHzDeltaTrack;

  if (next.kiCurrent == 0) {
    next.iContrib = prevIContrib;
    return next;
  }

  const int64_t desired = (prevIContrib != 0) ? prevIContrib : state.iContrib;
  int64_t newIntegral = desired / static_cast<int64_t>(next.kiCurrent);
  if (newIntegral > state.iCap) newIntegral = state.iCap;
  if (newIntegral < -state.iCap) newIntegral = -state.iCap;

  next.integral = newIntegral;
  next.iContrib = static_cast<int64_t>(next.kiCurrent) * next.integral;
  return next;
}

ValidationResult validatePressureSample(uint16_t previous,
                                        uint16_t incoming,
                                        uint8_t consecutiveRejects,
                                        const ValidationConfig& cfg) {
  ValidationResult result{};
  result.committedRaw = previous;

  if (incoming < cfg.minRaw) {
    result.reason = PressureRejectReason::RailLow;
  } else if (incoming > cfg.maxRaw) {
    result.reason = PressureRejectReason::RailHigh;
  } else {
    const uint16_t delta = static_cast<uint16_t>((incoming > previous) ? (incoming - previous) : (previous - incoming));
    if ((previous != 0u) && (delta > cfg.maxStepPerSample)) {
      result.reason = PressureRejectReason::Spike;
    } else {
      result.accept = true;
      result.reason = PressureRejectReason::None;
      result.committedRaw = incoming;
      return result;
    }
  }

  if (consecutiveRejects >= cfg.maxConsecutiveRejects) {
    result.accept = true;
    result.committedRaw = incoming;
  }
  return result;
}

uint32_t computeRecoveryBoostHz(uint16_t triggerPressureRaw,
                                uint16_t pulseWidthUs,
                                const RecoveryConfig& cfg,
                                uint16_t psiOffsetRaw) {
  uint32_t boost = cfg.baseBoostHz;
  if (triggerPressureRaw > psiOffsetRaw) {
    boost += static_cast<uint32_t>(cfg.pressureCoeffHzPerRaw) * static_cast<uint32_t>(triggerPressureRaw - psiOffsetRaw);
  }
  boost += static_cast<uint32_t>(cfg.pulseCoeffHzPerUs) * static_cast<uint32_t>(pulseWidthUs);
  if (boost > cfg.maxBoostHz) {
    boost = cfg.maxBoostHz;
  }
  return boost;
}

uint32_t decayRecoveryBoostHz(uint32_t initialBoostHz,
                              uint16_t ticksRemaining,
                              uint16_t ticksInitial,
                              bool linearDecay) {
  if ((initialBoostHz == 0u) || (ticksRemaining == 0u) || (ticksInitial == 0u)) {
    return 0u;
  }
  if (!linearDecay) {
    return initialBoostHz;
  }
  return static_cast<uint32_t>((static_cast<uint64_t>(initialBoostHz) * ticksRemaining) / ticksInitial);
}

uint16_t computeDeadlineSlipMs(uint32_t nominalTickMs, uint32_t actualTickMs) {
  if (actualTickMs <= nominalTickMs) {
    return 0u;
  }
  const uint32_t diff = actualTickMs - nominalTickMs;
  return static_cast<uint16_t>((diff > 0xFFFFu) ? 0xFFFFu : diff);
}

uint32_t computeRecoveryRequestedHz(const RecoveryState& state) {
  uint32_t requested = state.baseRequestedHz;
  if (state.recoveryActive) {
    const bool undershoot = (state.errorRaw < -state.readyTolRaw);
    if (!state.boostOnlyWhenUndershoot || undershoot) {
      requested += state.decayedBoostHz;
    }
  }

  if (state.recoveryActive && state.recoveryFloorHz > 0u && requested < state.recoveryFloorHz) {
    requested = state.recoveryFloorHz;
  }
  if (requested < state.minRequestedHz) {
    requested = state.minRequestedHz;
  }
  if (state.maxRequestedHz > 0u && requested > state.maxRequestedHz) {
    requested = state.maxRequestedHz;
  }
  return requested;
}

uint32_t applyAsymmetricSlew(uint32_t requestedHz,
                             uint32_t lastHz,
                             const SlewConfig& cfg) {
  if (requestedHz > lastHz) {
    uint32_t delta = requestedHz - lastHz;
    if (delta > cfg.maxHzDeltaUpPerLoop) {
      return lastHz + cfg.maxHzDeltaUpPerLoop;
    }
    return requestedHz;
  }

  uint32_t delta = lastHz - requestedHz;
  if (delta > cfg.maxHzDeltaDownPerLoop) {
    return lastHz - cfg.maxHzDeltaDownPerLoop;
  }
  return requestedHz;
}

uint16_t defaultReadyTolRaw(uint8_t sensorPort) {
  return (sensorPort == 0u) ? 4u : 8u;
}

bool shouldExtendRecovery(int32_t errorRaw,
                          int32_t readyTolRaw,
                          uint16_t ticksExtended,
                          uint16_t maxExtendTicks,
                          bool allowExtendWhileUndershoot,
                          uint16_t recoveryExitErrorRaw) {
  if (!allowExtendWhileUndershoot || maxExtendTicks == 0u || ticksExtended >= maxExtendTicks) {
    return false;
  }

  const int32_t absError = (errorRaw >= 0) ? errorRaw : -errorRaw;
  const int32_t exitTol = (recoveryExitErrorRaw > 0u) ? static_cast<int32_t>(recoveryExitErrorRaw) : readyTolRaw;
  if (absError <= exitTol) {
    return false;
  }
  return (errorRaw < 0);
}

}  // namespace PressureRegulatorMath
