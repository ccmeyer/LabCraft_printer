#include "CoordinatedXyPerformanceReport.h"

#include <cstdio>
#include <limits>

#if defined(__GNUC__) && !defined(UNIT_TEST)
#pragma GCC push_options
#pragma GCC optimize("Os")
#endif

namespace CoordinatedXyPerformanceReport {
namespace {

constexpr uint8_t phaseIndex(CoordinatedXyIsrInstrumentation::Phase phase) {
  return static_cast<uint8_t>(phase);
}

void addSaturating(uint32_t& destination,
                   uint32_t increment,
                   uint32_t& saturationFlags) {
  if (increment > (std::numeric_limits<uint32_t>::max() - destination)) {
    destination = std::numeric_limits<uint32_t>::max();
    saturationFlags |= 0x80000000u;
    return;
  }
  destination += increment;
}

uint32_t activeMax(const CoordinatedXyIsrInstrumentation::Snapshot& timing) {
  uint32_t maximum = 0u;
  for (uint8_t i = 0u;
       i < phaseIndex(CoordinatedXyIsrInstrumentation::Phase::Count);
       ++i) {
    if (timing.phaseMaxCycles[i] > maximum) maximum = timing.phaseMaxCycles[i];
  }
  return maximum;
}

bool rearmEvidenceConsistent(uint32_t rearmCount,
                             uint32_t rearmDelayMaxCycles) {
  return (rearmCount == 0u && rearmDelayMaxCycles == 0u) ||
      (rearmCount != 0u && rearmDelayMaxCycles != 0u);
}

bool injectionEvidencePasses(bool required,
                             uint32_t expectedCount,
                             uint32_t rearmCount,
                             uint32_t injectionCount,
                             uint32_t injectionFailureCount,
                             uint32_t injectionRearmCount,
                             uint32_t injectionDecisionSlackMaxTicks,
                             uint32_t injectionWaitMaxCycles) {
  if (!required) {
    return injectionCount == 0u && injectionFailureCount == 0u &&
        injectionRearmCount == 0u &&
        injectionDecisionSlackMaxTicks == 0u &&
        injectionWaitMaxCycles == 0u;
  }
  return rearmCount >= expectedCount && injectionCount == expectedCount &&
      injectionFailureCount == 0u &&
      injectionRearmCount == expectedCount &&
      injectionDecisionSlackMaxTicks <=
          CoordinatedXyTimerSchedulePolicy::kConditionalGuardTicks &&
      injectionWaitMaxCycles > 0u &&
      injectionWaitMaxCycles <=
          CoordinatedXyTimerSchedulePolicy::kInjectionMaxCoreCycles;
}

}  // namespace

uint32_t boundedHomeGuardSteps(int32_t currentPositionSteps,
                               uint32_t axisEnvelopeMaximumSteps,
                               uint32_t marginSteps,
                               uint32_t minimumGuardSteps,
                               bool positionKnown) {
  uint64_t guard = static_cast<uint64_t>(axisEnvelopeMaximumSteps) +
                   static_cast<uint64_t>(marginSteps);
  if (positionKnown && currentPositionSteps >= 0 &&
      static_cast<uint64_t>(currentPositionSteps) <=
          static_cast<uint64_t>(axisEnvelopeMaximumSteps)) {
    guard = static_cast<uint64_t>(currentPositionSteps) +
            static_cast<uint64_t>(marginSteps);
  }
  if (guard < minimumGuardSteps) guard = minimumGuardSteps;
  if (guard > std::numeric_limits<uint32_t>::max()) {
    return std::numeric_limits<uint32_t>::max();
  }
  return static_cast<uint32_t>(guard);
}

uint32_t moveFailureMask(const MoveObservation& observation,
                         const Limits& limits) {
  const auto& timing = observation.timing;
  uint32_t failures = 0u;
  if (observation.timedOut) failures |= kMoveFailureTimedOut;
  if (!observation.endpointMatches) failures |= kMoveFailureEndpoint;
  if (!observation.targetsMatch) failures |= kMoveFailureTargets;
  if (!observation.completionTogether) failures |= kMoveFailureCompletion;
  if (!observation.pinsLow) failures |= kMoveFailurePins;
  if (!observation.ownershipReleased) failures |= kMoveFailureOwnership;
  if (!observation.checksumMatch) failures |= kMoveFailureChecksum;
  if (observation.requestedXSteps != observation.expectedXSteps ||
      observation.requestedYSteps != observation.expectedYSteps) {
    failures |= kMoveFailureRequestedCounts;
  }
  if (observation.emittedXSteps != observation.expectedXSteps ||
      observation.emittedYSteps != observation.expectedYSteps) {
    failures |= kMoveFailureEmittedCounts;
  }
  if (observation.masterSteps != observation.expectedMasterSteps) {
    failures |= kMoveFailureMasterCount;
  }
  if (observation.selectedRateHz != observation.expectedRateHz) {
    failures |= kMoveFailureSelectedRate;
  }
  if ((observation.interruptsPerMasterStep != 1u &&
       observation.interruptsPerMasterStep != 2u) ||
      observation.timer2Callbacks !=
          (observation.expectedMasterSteps *
           observation.interruptsPerMasterStep) ||
      observation.timer7Callbacks != 0u) {
    failures |= kMoveFailureTimerCounts;
  }
  const bool completeStepMode = observation.executionMode ==
      CoordinatedXyExecutor::ExecutionMode::CompleteStep;
  if (completeStepMode != (observation.interruptsPerMasterStep == 1u)) {
    failures |= kMoveFailureExecutionMode;
  }
  const bool rearmMode = observation.timerScheduleMode ==
      CoordinatedXyTimerSchedulePolicy::Mode::RearmFromActualEdge;
  const bool conditionalMode = observation.timerScheduleMode ==
      CoordinatedXyTimerSchedulePolicy::Mode::ConditionalLateRearm;
  const uint32_t expectedRearms = observation.timer2Callbacks == 0u
      ? 0u
      : observation.timer2Callbacks - 1u;
  if ((rearmMode &&
       (completeStepMode || observation.timerRearmCount != expectedRearms ||
         observation.timerRearmPendingCount != 0u ||
         observation.timerRearmDelayMaxCycles == 0u ||
         observation.conditionalDecisionCount != 0u ||
         observation.conditionalDecisionMissingCount != 0u ||
         observation.lateInjectionCount != 0u)) ||
      (conditionalMode &&
       (completeStepMode ||
        observation.conditionalDecisionCount != expectedRearms ||
        observation.conditionalDecisionMissingCount != 0u ||
        observation.timerRearmPendingCount != 0u ||
        !rearmEvidenceConsistent(observation.timerRearmCount,
                                 observation.timerRearmDelayMaxCycles) ||
        observation.conditionalNonRearmSlackMinTicks <=
            CoordinatedXyTimerSchedulePolicy::kConditionalGuardTicks ||
        !injectionEvidencePasses(
            observation.requireLateInjectionEvidence,
            1u,
            observation.timerRearmCount,
            observation.lateInjectionCount,
            observation.lateInjectionFailureCount,
            observation.lateInjectionRearmCount,
            observation.lateInjectionDecisionSlackMaxTicks,
            observation.lateInjectionWaitMaxCycles) ||
        observation.timerScheduleSaturationFlags != 0u)) ||
      (!rearmMode && !conditionalMode &&
       (observation.timerRearmCount != 0u ||
         observation.timerRearmPendingCount != 0u ||
         observation.timerRearmDelayMaxCycles != 0u ||
         observation.conditionalDecisionCount != 0u ||
         observation.conditionalDecisionMissingCount != 0u ||
         observation.lateInjectionCount != 0u ||
         observation.timerScheduleSaturationFlags != 0u))) {
    failures |= kMoveFailureTimerRearm;
  }
  if (observation.timerScheduleSaturationFlags != 0u) {
    failures |= kMoveFailureScheduleSaturation;
  }
  if (observation.terminalReason !=
      CoordinatedXyExecutor::TerminalReason::Completed) {
    failures |= kMoveFailureTerminalReason;
  }
  if (observation.arrMin != observation.expectedTargetArr ||
      observation.arrMax != observation.expectedStartArr) {
    failures |= kMoveFailureArrRange;
  }
  if (!timing.valid || timing.active || timing.aborted) {
    failures |= kMoveFailureTimingState;
  }
  if (timing.totalCallbacks != observation.timer2Callbacks ||
      timing.completedPulses != observation.expectedMasterSteps ||
      timing.terminalCallbacks != 1u) {
    failures |= kMoveFailureTimingCounts;
  }
  if (completeStepMode &&
      (observation.minimumPulseCoreCycles == 0u ||
       timing.completeStepPulseSamples != observation.expectedMasterSteps ||
       timing.completeStepPulseMinCycles <
           observation.minimumPulseCoreCycles)) {
    failures |= kMoveFailurePulseTiming;
  }
  if (completeStepMode &&
      (timing.deadlineSamples != observation.timer2Callbacks ||
       timing.deadlineMissing != 0u || timing.deadlineMisses != 0u ||
       timing.deadlineSlackMinTicks == 0u)) {
    failures |= kMoveFailureDeadlineSlack;
  }
  if (!completeStepMode && observation.minimumDeadlineSlackTicks != 0u &&
      (observation.timer2Callbacks == 0u ||
       timing.deadlineSamples != observation.timer2Callbacks - 1u ||
       timing.deadlineMissing != 0u || timing.deadlineMisses != 0u ||
       timing.deadlineSlackMinTicks < observation.minimumDeadlineSlackTicks)) {
    failures |= kMoveFailureDeadlineSlack;
  }
  if (observation.requireNoLateEntries && timing.lateEntryCount != 0u) {
    failures |= kMoveFailureEntryLateness;
  }
  if (timing.pendingObservations != 0u || timing.maxPendingStreak != 0u) {
    failures |= kMoveFailurePendingUpdate;
  }
  if (timing.saturationFlags != 0u) failures |= kMoveFailureSaturation;
  if (timing.cycleWraps > limits.maxCycleWrapsPerMove) {
    failures |= kMoveFailureCycleWrap;
  }
  if (activeMax(timing) > limits.activeMaxCycles) {
    failures |= kMoveFailureActiveCycles;
  }
  if (observation.requireTerminalCycleBudget &&
      timing.terminalMaxCycles > limits.terminalMaxCycles) {
    failures |= kMoveFailureTerminalCycles;
  }
  if (observation.durationErrorBasisPoints >
      limits.durationErrorMaxBasisPoints) {
    failures |= kMoveFailureDuration;
  }
  if (observation.statusPeriodMaxMs > limits.statusPeriodMaxMs) {
    failures |= kMoveFailureStatusPeriod;
  }
  if (observation.statusWatchdogAgeMaxMs >
      limits.statusWatchdogAgeMaxMs) {
    failures |= kMoveFailureStatusWatchdog;
  }
  if (observation.statusAlternationErrors != 0u) {
    failures |= kMoveFailureStatusAlternation;
  }
  if (observation.watchdogLateCount != 0u) {
    failures |= kMoveFailureWatchdogLate;
  }
  return failures;
}

bool movePasses(const MoveObservation& observation, const Limits& limits) {
  return moveFailureMask(observation, limits) == 0u;
}

bool moveCanContinueAfterCompletion(const MoveObservation& observation,
                                    const Limits& limits) {
  const uint32_t failures = moveFailureMask(observation, limits);
  return (failures & ~kMoveCollectionSoftFailureMask) == 0u;
}

void captureFirstFailure(FailureTelemetry& telemetry,
                         bool movePassed,
                         CoordinatedXyExecutor::TerminalReason terminalReason,
                         uint32_t limitAbortRequestCount,
                         uint32_t rawLimitAbortCount,
                         uint32_t failureMask) {
  if (movePassed || telemetry.valid) return;
  telemetry.valid = true;
  telemetry.terminalReason = terminalReason;
  telemetry.limitAbortRequestCount = limitAbortRequestCount;
  telemetry.rawLimitAbortCount = rawLimitAbortCount;
  telemetry.failureMask = failureMask;
}

void addMove(Aggregate& aggregate,
             const MoveObservation& observation,
             const Limits& limits) {
  const uint32_t qualificationFailureMask =
      moveFailureMask(observation, limits);
  const bool firstMove = aggregate.moveCount == 0u;
  const bool modeConsistent = firstMove ||
      (aggregate.interruptsPerMasterStep ==
           observation.interruptsPerMasterStep &&
       aggregate.executionMode == observation.executionMode &&
       aggregate.timerScheduleMode == observation.timerScheduleMode &&
       aggregate.requireLateInjectionEvidence ==
           observation.requireLateInjectionEvidence &&
       aggregate.requireTerminalCycleBudget ==
           observation.requireTerminalCycleBudget &&
       aggregate.minimumPulseCoreCycles ==
           observation.minimumPulseCoreCycles);
  if (firstMove) {
    aggregate.interruptsPerMasterStep = observation.interruptsPerMasterStep;
    aggregate.executionMode = observation.executionMode;
    aggregate.timerScheduleMode = observation.timerScheduleMode;
    aggregate.requireLateInjectionEvidence =
        observation.requireLateInjectionEvidence;
    aggregate.requireTerminalCycleBudget =
        observation.requireTerminalCycleBudget;
    aggregate.minimumPulseCoreCycles = observation.minimumPulseCoreCycles;
  }
  addSaturating(aggregate.timerRearmCount,
                observation.timerRearmCount,
                aggregate.saturationFlags);
  addSaturating(aggregate.timerRearmPendingCount,
                observation.timerRearmPendingCount,
                aggregate.saturationFlags);
  if (observation.timerRearmDelayMaxCycles >
      aggregate.timerRearmDelayMaxCycles) {
    aggregate.timerRearmDelayMaxCycles =
        observation.timerRearmDelayMaxCycles;
  }
  addSaturating(aggregate.conditionalDecisionCount,
                observation.conditionalDecisionCount,
                aggregate.saturationFlags);
  addSaturating(aggregate.conditionalDecisionMissingCount,
                observation.conditionalDecisionMissingCount,
                aggregate.saturationFlags);
  if (observation.conditionalNonRearmSlackMinTicks != 0u &&
      (aggregate.conditionalNonRearmSlackMinTicks == 0u ||
       observation.conditionalNonRearmSlackMinTicks <
           aggregate.conditionalNonRearmSlackMinTicks)) {
    aggregate.conditionalNonRearmSlackMinTicks =
        observation.conditionalNonRearmSlackMinTicks;
  }
  addSaturating(aggregate.lateInjectionCount,
                observation.lateInjectionCount,
                aggregate.saturationFlags);
  addSaturating(aggregate.lateInjectionFailureCount,
                observation.lateInjectionFailureCount,
                aggregate.saturationFlags);
  addSaturating(aggregate.lateInjectionRearmCount,
                observation.lateInjectionRearmCount,
                aggregate.saturationFlags);
  if (observation.lateInjectionDecisionSlackMaxTicks >
      aggregate.lateInjectionDecisionSlackMaxTicks) {
    aggregate.lateInjectionDecisionSlackMaxTicks =
        observation.lateInjectionDecisionSlackMaxTicks;
  }
  if (observation.lateInjectionWaitMaxCycles >
      aggregate.lateInjectionWaitMaxCycles) {
    aggregate.lateInjectionWaitMaxCycles =
        observation.lateInjectionWaitMaxCycles;
  }
  aggregate.timerScheduleSaturationFlags |=
      observation.timerScheduleSaturationFlags;
  addSaturating(aggregate.moveCount, 1u, aggregate.saturationFlags);
  addSaturating(aggregate.expectedXSteps,
                observation.expectedXSteps,
                aggregate.saturationFlags);
  addSaturating(aggregate.expectedYSteps,
                observation.expectedYSteps,
                aggregate.saturationFlags);
  addSaturating(aggregate.expectedMasterSteps,
                observation.expectedMasterSteps,
                aggregate.saturationFlags);
  addSaturating(aggregate.emittedXSteps,
                observation.emittedXSteps,
                aggregate.saturationFlags);
  addSaturating(aggregate.emittedYSteps,
                observation.emittedYSteps,
                aggregate.saturationFlags);
  addSaturating(aggregate.masterSteps,
                observation.masterSteps,
                aggregate.saturationFlags);
  addSaturating(aggregate.timer2Callbacks,
                observation.timer2Callbacks,
                aggregate.saturationFlags);
  addSaturating(aggregate.timer7Callbacks,
                observation.timer7Callbacks,
                aggregate.saturationFlags);
  for (uint8_t i = 0u;
       i < phaseIndex(CoordinatedXyIsrInstrumentation::Phase::Count);
       ++i) {
    addSaturating(aggregate.phaseCallbacks[i],
                  observation.timing.phaseCallbacks[i],
                  aggregate.saturationFlags);
    addSaturating(aggregate.phaseCycleSums[i],
                  observation.timing.phaseCycleSums[i],
                  aggregate.saturationFlags);
    if (observation.timing.phaseMaxCycles[i] > aggregate.phaseMaxCycles[i]) {
      aggregate.phaseMaxCycles[i] = observation.timing.phaseMaxCycles[i];
    }
  }
  if (observation.timing.terminalMaxCycles > aggregate.terminalMaxCycles) {
    aggregate.terminalMaxCycles = observation.timing.terminalMaxCycles;
  }
  addSaturating(aggregate.irqPathSamples,
                observation.timing.irqPathSamples,
                aggregate.saturationFlags);
  addSaturating(aggregate.irqPathMissing,
                observation.timing.irqPathMissing,
                aggregate.saturationFlags);
  addSaturating(aggregate.preHandlerCycleSum,
                observation.timing.preHandlerCycleSum,
                aggregate.saturationFlags);
  addSaturating(aggregate.fullIrqCycleSum,
                observation.timing.fullIrqCycleSum,
                aggregate.saturationFlags);
  if (observation.timing.preHandlerMaxCycles > aggregate.preHandlerMaxCycles) {
    aggregate.preHandlerMaxCycles = observation.timing.preHandlerMaxCycles;
  }
  if (observation.timing.fullIrqMaxCycles > aggregate.fullIrqMaxCycles) {
    aggregate.fullIrqMaxCycles = observation.timing.fullIrqMaxCycles;
  }
  if (observation.timing.activeFullIrqMaxCycles >
      aggregate.activeFullIrqMaxCycles) {
    aggregate.activeFullIrqMaxCycles =
        observation.timing.activeFullIrqMaxCycles;
  }
  if (observation.timing.terminalFullIrqMaxCycles >
      aggregate.terminalFullIrqMaxCycles) {
    aggregate.terminalFullIrqMaxCycles =
        observation.timing.terminalFullIrqMaxCycles;
  }
  if (observation.timing.pendingPreHandlerMaxCycles >
      aggregate.pendingPreHandlerMaxCycles) {
    aggregate.pendingPreHandlerMaxCycles =
        observation.timing.pendingPreHandlerMaxCycles;
  }
  if (observation.timing.pendingFullIrqMaxCycles >
      aggregate.pendingFullIrqMaxCycles) {
    aggregate.pendingFullIrqMaxCycles =
        observation.timing.pendingFullIrqMaxCycles;
  }
  addSaturating(aggregate.entryTimerSamples,
                observation.timing.entryTimerSamples,
                aggregate.saturationFlags);
  addSaturating(aggregate.entryTimerMissing,
                observation.timing.entryTimerMissing,
                aggregate.saturationFlags);
  addSaturating(aggregate.entryTimerCountSum,
                observation.timing.entryTimerCountSum,
                aggregate.saturationFlags);
  if (observation.timing.entryTimerCountMax >
      aggregate.entryTimerCountMax) {
    aggregate.entryTimerCountMax = observation.timing.entryTimerCountMax;
  }
  if (observation.timing.pendingEntryTimerCountMax >
      aggregate.pendingEntryTimerCountMax) {
    aggregate.pendingEntryTimerCountMax =
        observation.timing.pendingEntryTimerCountMax;
  }
  addSaturating(aggregate.lateEntryCount,
                observation.timing.lateEntryCount,
                aggregate.saturationFlags);
  if (observation.timing.entryScheduleOverrunMaxCycles >
      aggregate.entryScheduleOverrunMaxCycles) {
    aggregate.entryScheduleOverrunMaxCycles =
        observation.timing.entryScheduleOverrunMaxCycles;
  }
  const bool firstPulseSample = aggregate.completeStepPulseSamples == 0u;
  addSaturating(aggregate.completeStepPulseSamples,
                observation.timing.completeStepPulseSamples,
                aggregate.saturationFlags);
  if (observation.timing.completeStepPulseSamples != 0u &&
      (firstPulseSample || observation.timing.completeStepPulseMinCycles <
          aggregate.completeStepPulseMinCycles)) {
    aggregate.completeStepPulseMinCycles =
        observation.timing.completeStepPulseMinCycles;
  }
  if (observation.timing.completeStepPulseMaxCycles >
      aggregate.completeStepPulseMaxCycles) {
    aggregate.completeStepPulseMaxCycles =
        observation.timing.completeStepPulseMaxCycles;
  }
  const bool firstDeadlineSample = aggregate.deadlineSamples == 0u;
  addSaturating(aggregate.deadlineSamples,
                observation.timing.deadlineSamples,
                aggregate.saturationFlags);
  addSaturating(aggregate.deadlineMissing,
                observation.timing.deadlineMissing,
                aggregate.saturationFlags);
  addSaturating(aggregate.deadlineMisses,
                observation.timing.deadlineMisses,
                aggregate.saturationFlags);
  if (observation.timing.deadlineSamples != 0u &&
      (firstDeadlineSample || observation.timing.deadlineSlackMinTicks <
          aggregate.deadlineSlackMinTicks)) {
    aggregate.deadlineSlackMinTicks =
        observation.timing.deadlineSlackMinTicks;
  }
  addSaturating(aggregate.intentionalWaitCycleSum,
                observation.timing.intentionalWaitCycleSum,
                aggregate.saturationFlags);
  if (observation.timing.intentionalWaitMaxCycles >
      aggregate.intentionalWaitMaxCycles) {
    aggregate.intentionalWaitMaxCycles =
        observation.timing.intentionalWaitMaxCycles;
  }
  addSaturating(aggregate.pendingObservations,
                observation.timing.pendingObservations,
                aggregate.saturationFlags);
  if (observation.timing.maxPendingStreak > aggregate.maxPendingStreak) {
    aggregate.maxPendingStreak = observation.timing.maxPendingStreak;
  }
  if (observation.durationErrorBasisPoints >
      aggregate.durationErrorMaxBasisPoints) {
    aggregate.durationErrorMaxBasisPoints =
        observation.durationErrorBasisPoints;
  }
  if (observation.statusPeriodMaxMs > aggregate.statusPeriodMaxMs) {
    aggregate.statusPeriodMaxMs = observation.statusPeriodMaxMs;
  }
  if (observation.statusWatchdogAgeMaxMs >
      aggregate.statusWatchdogAgeMaxMs) {
    aggregate.statusWatchdogAgeMaxMs = observation.statusWatchdogAgeMaxMs;
  }
  addSaturating(aggregate.statusFrameCount,
                observation.statusFrameCount,
                aggregate.saturationFlags);
  addSaturating(aggregate.statusAlternationErrors,
                observation.statusAlternationErrors,
                aggregate.saturationFlags);
  addSaturating(aggregate.watchdogLateCount,
                observation.watchdogLateCount,
                aggregate.saturationFlags);
  addSaturating(aggregate.cycleWraps,
                observation.timing.cycleWraps,
                aggregate.saturationFlags);
  aggregate.saturationFlags |= observation.timing.saturationFlags;
  if (observation.timerScheduleSaturationFlags != 0u) {
    aggregate.saturationFlags |= 0x40000000u;
  }
  if (observation.timedOut) {
    addSaturating(aggregate.timeoutCount, 1u, aggregate.saturationFlags);
  }
  if (qualificationFailureMask != 0u) {
    addSaturating(aggregate.qualificationFailureMoveCount,
                  1u,
                  aggregate.saturationFlags);
    aggregate.qualificationFailureMask |= qualificationFailureMask;
  }
  aggregate.exactAndSafe = aggregate.exactAndSafe && modeConsistent &&
      qualificationFailureMask == 0u;
}

uint32_t phaseMeanCycles(const Aggregate& aggregate,
                         CoordinatedXyIsrInstrumentation::Phase phase) {
  const uint8_t index = phaseIndex(phase);
  if (index >= phaseIndex(CoordinatedXyIsrInstrumentation::Phase::Count) ||
      aggregate.phaseCallbacks[index] == 0u) {
    return 0u;
  }
  const uint32_t mean =
      aggregate.phaseCycleSums[index] / aggregate.phaseCallbacks[index];
  return mean;
}

uint32_t preHandlerMeanCycles(const Aggregate& aggregate) {
  if (aggregate.irqPathSamples == 0u) return 0u;
  return aggregate.preHandlerCycleSum / aggregate.irqPathSamples;
}

uint32_t fullIrqMeanCycles(const Aggregate& aggregate) {
  if (aggregate.irqPathSamples == 0u) return 0u;
  return aggregate.fullIrqCycleSum / aggregate.irqPathSamples;
}

uint32_t entryTimerMeanTicks(const Aggregate& aggregate) {
  if (aggregate.entryTimerSamples == 0u) return 0u;
  return aggregate.entryTimerCountSum / aggregate.entryTimerSamples;
}

bool aggregatePasses(const Aggregate& aggregate,
                     uint32_t expectedMoves,
                     uint32_t expectedXSteps,
                     uint32_t expectedYSteps,
                     uint32_t expectedMasterSteps,
                     const Limits& limits) {
  uint32_t activeMaximum = 0u;
  for (uint8_t i = 0u;
       i < phaseIndex(CoordinatedXyIsrInstrumentation::Phase::Count);
       ++i) {
    if (aggregate.phaseMaxCycles[i] > activeMaximum) {
      activeMaximum = aggregate.phaseMaxCycles[i];
    }
  }
  return aggregate.exactAndSafe && aggregate.moveCount == expectedMoves &&
      aggregate.expectedXSteps == expectedXSteps &&
      aggregate.expectedYSteps == expectedYSteps &&
      aggregate.expectedMasterSteps == expectedMasterSteps &&
      aggregate.emittedXSteps == expectedXSteps &&
      aggregate.emittedYSteps == expectedYSteps &&
      aggregate.masterSteps == expectedMasterSteps &&
      (aggregate.interruptsPerMasterStep == 1u ||
       aggregate.interruptsPerMasterStep == 2u) &&
      aggregate.timer2Callbacks ==
          (expectedMasterSteps * aggregate.interruptsPerMasterStep) &&
      aggregate.timer7Callbacks == 0u &&
      ((aggregate.timerScheduleMode ==
            CoordinatedXyTimerSchedulePolicy::Mode::FreeRunning &&
        aggregate.timerRearmCount == 0u &&
        aggregate.timerRearmPendingCount == 0u &&
        aggregate.timerRearmDelayMaxCycles == 0u) ||
       (aggregate.timerScheduleMode ==
             CoordinatedXyTimerSchedulePolicy::Mode::RearmFromActualEdge &&
        aggregate.interruptsPerMasterStep == 2u &&
        aggregate.timer2Callbacks >= aggregate.moveCount &&
        aggregate.timerRearmCount ==
            (aggregate.timer2Callbacks - aggregate.moveCount) &&
        aggregate.timerRearmPendingCount == 0u &&
        aggregate.timerRearmDelayMaxCycles > 0u) ||
       (aggregate.timerScheduleMode ==
            CoordinatedXyTimerSchedulePolicy::Mode::ConditionalLateRearm &&
        aggregate.interruptsPerMasterStep == 2u &&
         aggregate.timer2Callbacks >= aggregate.moveCount &&
         aggregate.conditionalDecisionCount ==
             (aggregate.timer2Callbacks - aggregate.moveCount) &&
         aggregate.conditionalDecisionMissingCount == 0u &&
         aggregate.timerRearmPendingCount == 0u &&
         rearmEvidenceConsistent(aggregate.timerRearmCount,
                                 aggregate.timerRearmDelayMaxCycles) &&
         injectionEvidencePasses(
             aggregate.requireLateInjectionEvidence,
             aggregate.moveCount,
             aggregate.timerRearmCount,
             aggregate.lateInjectionCount,
             aggregate.lateInjectionFailureCount,
             aggregate.lateInjectionRearmCount,
             aggregate.lateInjectionDecisionSlackMaxTicks,
             aggregate.lateInjectionWaitMaxCycles) &&
         aggregate.conditionalNonRearmSlackMinTicks >
             CoordinatedXyTimerSchedulePolicy::kConditionalGuardTicks &&
         aggregate.timerScheduleSaturationFlags == 0u)) &&
      aggregate.pendingObservations == 0u &&
      aggregate.maxPendingStreak == 0u &&
      aggregate.saturationFlags == 0u && aggregate.timeoutCount == 0u &&
      aggregate.statusAlternationErrors == 0u &&
      aggregate.watchdogLateCount == 0u &&
      aggregate.cycleWraps <= aggregate.moveCount &&
      aggregate.statusFrameCount > 0u &&
      activeMaximum <= limits.activeMaxCycles &&
      (!aggregate.requireTerminalCycleBudget ||
       aggregate.terminalMaxCycles <= limits.terminalMaxCycles) &&
      aggregate.durationErrorMaxBasisPoints <=
          limits.durationErrorMaxBasisPoints &&
      aggregate.statusPeriodMaxMs <= limits.statusPeriodMaxMs &&
      aggregate.statusWatchdogAgeMaxMs <= limits.statusWatchdogAgeMaxMs;
}

size_t buildMetrics(char* out,
                    size_t capacity,
                    uint32_t rateHz,
                    const Aggregate& aggregate,
                    uint32_t xDriftSteps,
                    uint32_t yDriftSteps) {
  if (out == nullptr || capacity == 0u) return 0u;
  const int written = std::snprintf(
      out,
      capacity,
      "hz=%lu;n=%lu;xe=%lu;ye=%lu;ms=%lu;i2=%lu;i7=%lu;ok=%u;"
      "pu=%lu;ps=%lu;am=%lu;aa=%lu;cm=%lu;ca=%lu;dm=%lu;da=%lu;"
      "tm=%lu;de=%lu;sg=%lu;wd=%lu;sa=%lu;wl=%lu;cw=%lu;qf=%lu;"
      "qm=%lu;sf=%lu;xd=%lu;yd=%lu;to=%lu",
      static_cast<unsigned long>(rateHz),
      static_cast<unsigned long>(aggregate.moveCount),
      static_cast<unsigned long>(aggregate.emittedXSteps),
      static_cast<unsigned long>(aggregate.emittedYSteps),
      static_cast<unsigned long>(aggregate.masterSteps),
      static_cast<unsigned long>(aggregate.timer2Callbacks),
      static_cast<unsigned long>(aggregate.timer7Callbacks),
      static_cast<unsigned>(aggregate.exactAndSafe ? 1u : 0u),
      static_cast<unsigned long>(aggregate.pendingObservations),
      static_cast<unsigned long>(aggregate.maxPendingStreak),
      static_cast<unsigned long>(aggregate.phaseMaxCycles[0]),
      static_cast<unsigned long>(phaseMeanCycles(
          aggregate, CoordinatedXyIsrInstrumentation::Phase::Acceleration)),
      static_cast<unsigned long>(aggregate.phaseMaxCycles[1]),
      static_cast<unsigned long>(phaseMeanCycles(
          aggregate, CoordinatedXyIsrInstrumentation::Phase::Cruise)),
      static_cast<unsigned long>(aggregate.phaseMaxCycles[2]),
      static_cast<unsigned long>(phaseMeanCycles(
          aggregate, CoordinatedXyIsrInstrumentation::Phase::Deceleration)),
      static_cast<unsigned long>(aggregate.terminalMaxCycles),
      static_cast<unsigned long>(aggregate.durationErrorMaxBasisPoints),
      static_cast<unsigned long>(aggregate.statusPeriodMaxMs),
      static_cast<unsigned long>(aggregate.statusWatchdogAgeMaxMs),
      static_cast<unsigned long>(aggregate.statusAlternationErrors),
      static_cast<unsigned long>(aggregate.watchdogLateCount),
      static_cast<unsigned long>(aggregate.cycleWraps),
      static_cast<unsigned long>(aggregate.qualificationFailureMoveCount),
      static_cast<unsigned long>(aggregate.qualificationFailureMask),
      static_cast<unsigned long>(aggregate.saturationFlags),
      static_cast<unsigned long>(xDriftSteps),
      static_cast<unsigned long>(yDriftSteps),
      static_cast<unsigned long>(aggregate.timeoutCount));
  if (written < 0 || static_cast<size_t>(written) >= capacity) {
    out[0] = '\0';
    return 0u;
  }
  return static_cast<size_t>(written);
}

}  // namespace CoordinatedXyPerformanceReport

#if defined(__GNUC__) && !defined(UNIT_TEST)
#pragma GCC pop_options
#endif
