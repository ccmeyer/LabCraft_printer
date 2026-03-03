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
