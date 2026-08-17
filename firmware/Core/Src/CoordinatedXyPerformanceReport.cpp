#include "CoordinatedXyPerformanceReport.h"

#include "CoordinatedXyTimerSchedulePolicy.h"

#include <cstdio>
#include <limits>

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
  } else {
    destination += increment;
  }
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

uint32_t aggregateActiveMax(const Aggregate& aggregate) {
  uint32_t maximum = 0u;
  for (uint8_t i = 0u;
       i < phaseIndex(CoordinatedXyIsrInstrumentation::Phase::Count);
       ++i) {
    if (aggregate.phaseMaxCycles[i] > maximum) {
      maximum = aggregate.phaseMaxCycles[i];
    }
  }
  return maximum;
}

bool rearmEvidenceConsistent(uint32_t rearmCount,
                             uint32_t rearmDelayMaxCycles) {
  return (rearmCount == 0u && rearmDelayMaxCycles == 0u) ||
      (rearmCount != 0u && rearmDelayMaxCycles != 0u);
}

}  // namespace

uint32_t boundedHomeGuardSteps(int32_t currentPositionSteps,
                               uint32_t axisEnvelopeMaximumSteps,
                               uint32_t marginSteps,
                               uint32_t minimumGuardSteps,
                               bool positionKnown) {
  uint64_t guard = static_cast<uint64_t>(axisEnvelopeMaximumSteps) + marginSteps;
  if (positionKnown && currentPositionSteps >= 0 &&
      static_cast<uint64_t>(currentPositionSteps) <= axisEnvelopeMaximumSteps) {
    guard = static_cast<uint64_t>(currentPositionSteps) + marginSteps;
  }
  if (guard < minimumGuardSteps) guard = minimumGuardSteps;
  return guard > std::numeric_limits<uint32_t>::max()
      ? std::numeric_limits<uint32_t>::max()
      : static_cast<uint32_t>(guard);
}

bool shallowMoveTimingExpectation(
    uint32_t requestedRateHz,
    uint32_t masterEdges,
    ShallowMoveTimingExpectation& expectation) {
  expectation = {};
  if (requestedRateHz == 10000u &&
      (masterEdges == 17100u || masterEdges == 19574u)) {
    expectation.selectedRateHz = 10000u;
    expectation.targetArr = 8999u;
    expectation.startArr = 44995u;
    return true;
  }
  if (requestedRateHz == 40000u && masterEdges == 17100u) {
    expectation.selectedRateHz = 36986u;
    expectation.targetArr = 2432u;
    expectation.startArr = 12160u;
    return true;
  }
  if (requestedRateHz == 40000u && masterEdges == 19574u) {
    expectation.selectedRateHz = 39571u;
    expectation.targetArr = 2273u;
    expectation.startArr = 11365u;
    return true;
  }
  return false;
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
  if (observation.requestedXEdges != observation.expectedXEdges ||
      observation.requestedYEdges != observation.expectedYEdges) {
    failures |= kMoveFailureRequestedCounts;
  }
  if (observation.emittedXEdges != observation.expectedXEdges ||
      observation.emittedYEdges != observation.expectedYEdges) {
    failures |= kMoveFailureEmittedCounts;
  }
  if (observation.masterEdges != observation.expectedMasterEdges) {
    failures |= kMoveFailureMasterCount;
  }
  if (observation.selectedRateHz != observation.expectedRateHz) {
    failures |= kMoveFailureSelectedRate;
  }
  if (observation.timer2Callbacks != observation.expectedMasterEdges ||
      observation.timer7Callbacks != 0u) {
    failures |= kMoveFailureTimerCounts;
  }
  const uint32_t expectedDecisions = observation.timer2Callbacks == 0u
      ? 0u : observation.timer2Callbacks - 1u;
  if (observation.conditionalDecisionCount != expectedDecisions ||
      observation.conditionalDecisionMissingCount != 0u ||
      observation.timerRearmPendingCount != 0u ||
      !rearmEvidenceConsistent(observation.timerRearmCount,
                               observation.timerRearmDelayMaxCycles) ||
      observation.conditionalNonRearmSlackMinTicks <=
          CoordinatedXyTimerSchedulePolicy::kConditionalGuardTicks) {
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
      timing.activeEdgeEvents != observation.expectedMasterEdges ||
      timing.terminalCallbacks != 1u ||
      timing.terminalStageSamples != 1u ||
      timing.terminalStageAccountingViolations != 0u ||
      timing.irqPathSamples != observation.timer2Callbacks ||
      timing.irqPathMissing != 0u ||
      timing.entryTimerSamples != observation.timer2Callbacks ||
      timing.entryTimerMissing != 0u) {
    failures |= kMoveFailureTimingCounts;
  }
  if (observation.minimumDeadlineSlackTicks != 0u &&
      (observation.timer2Callbacks == 0u ||
       timing.deadlineSamples != observation.timer2Callbacks - 1u ||
       timing.deadlineMissing != 0u || timing.deadlineMisses != 0u ||
       timing.deadlineSlackMinTicks < observation.minimumDeadlineSlackTicks)) {
    failures |= kMoveFailureDeadlineSlack;
  }
  if (observation.requireNoLateEntries && timing.lateEntryCount != 0u) {
    failures |= kMoveFailureEntryLateness;
  }
  if (observation.cleanupEdgeEvents != 0u) {
    failures |= kMoveFailureCleanupEdges;
  }
  if (observation.edgeSpacingViolations != 0u) {
    failures |= kMoveFailureEdgeSpacing;
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
  if (observation.durationErrorBasisPoints > limits.durationErrorMaxBasisPoints) {
    failures |= kMoveFailureDuration;
  }
  if (observation.statusPeriodMaxMs > limits.statusPeriodMaxMs) {
    failures |= kMoveFailureStatusPeriod;
  }
  if (observation.statusWatchdogAgeMaxMs > limits.statusWatchdogAgeMaxMs) {
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

bool canContinueAfterTerminalBudgetOnlyFailure(uint32_t failureMask) {
  return (failureMask & ~kMoveFailureTerminalCycles) == 0u;
}

uint32_t terminalAverageCycles(const Aggregate& aggregate) {
  return aggregate.terminalSampleCount == 0u
      ? 0u
      : aggregate.terminalTotalCycles / aggregate.terminalSampleCount;
}

void addMove(Aggregate& aggregate,
             const MoveObservation& observation,
             const Limits& limits) {
  const uint32_t failureMask = moveFailureMask(observation, limits);
  aggregate.moveFailureMask |= failureMask;
  addSaturating(aggregate.moveCount, 1u, aggregate.saturationFlags);
  addSaturating(aggregate.expectedXEdges, observation.expectedXEdges,
                aggregate.saturationFlags);
  addSaturating(aggregate.expectedYEdges, observation.expectedYEdges,
                aggregate.saturationFlags);
  addSaturating(aggregate.expectedMasterEdges, observation.expectedMasterEdges,
                aggregate.saturationFlags);
  addSaturating(aggregate.emittedXEdges, observation.emittedXEdges,
                aggregate.saturationFlags);
  addSaturating(aggregate.emittedYEdges, observation.emittedYEdges,
                aggregate.saturationFlags);
  addSaturating(aggregate.masterEdges, observation.masterEdges,
                aggregate.saturationFlags);
  addSaturating(aggregate.cleanupEdgeEvents, observation.cleanupEdgeEvents,
                aggregate.saturationFlags);
  addSaturating(aggregate.edgeSpacingViolations,
                observation.edgeSpacingViolations,
                aggregate.saturationFlags);
  addSaturating(aggregate.timer2Callbacks, observation.timer2Callbacks,
                aggregate.saturationFlags);
  addSaturating(aggregate.timer7Callbacks, observation.timer7Callbacks,
                aggregate.saturationFlags);
  addSaturating(aggregate.timerRearmCount, observation.timerRearmCount,
                aggregate.saturationFlags);
  addSaturating(aggregate.timerRearmPendingCount,
                observation.timerRearmPendingCount,
                aggregate.saturationFlags);
  if (observation.timerRearmDelayMaxCycles > aggregate.timerRearmDelayMaxCycles) {
    aggregate.timerRearmDelayMaxCycles = observation.timerRearmDelayMaxCycles;
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
  aggregate.timerScheduleSaturationFlags |=
      observation.timerScheduleSaturationFlags;
  for (uint8_t i = 0u;
       i < phaseIndex(CoordinatedXyIsrInstrumentation::Phase::Count);
       ++i) {
    addSaturating(aggregate.phaseCallbacks[i],
                  observation.timing.phaseCallbacks[i],
                  aggregate.saturationFlags);
    if (observation.timing.phaseMaxCycles[i] > aggregate.phaseMaxCycles[i]) {
      aggregate.phaseMaxCycles[i] = observation.timing.phaseMaxCycles[i];
    }
  }
  const bool firstTerminalSample = aggregate.terminalSampleCount == 0u;
  addSaturating(aggregate.terminalSampleCount,
                observation.timing.terminalStageSamples,
                aggregate.saturationFlags);
  addSaturating(aggregate.terminalTotalCycles,
                observation.timing.terminalTotalCycles,
                aggregate.saturationFlags);
  addSaturating(aggregate.terminalStageAccountingViolations,
                observation.timing.terminalStageAccountingViolations,
                aggregate.saturationFlags);
  if (observation.timing.terminalStageSamples != 0u &&
      (firstTerminalSample || observation.timing.terminalMinCycles <
          aggregate.terminalMinCycles)) {
    aggregate.terminalMinCycles = observation.timing.terminalMinCycles;
  }
  if (observation.timing.terminalStageSamples != 0u &&
      observation.timing.terminalMaxCycles > limits.terminalMaxCycles) {
    addSaturating(aggregate.terminalOverBudgetCount,
                  1u,
                  aggregate.saturationFlags);
  }
  if (observation.timing.terminalStageSamples != 0u &&
      (firstTerminalSample ||
       observation.timing.terminalMaxCycles > aggregate.terminalMaxCycles)) {
    aggregate.terminalMaxCycles = observation.timing.terminalMaxCycles;
    aggregate.worstTerminalCommonCycles =
        observation.timing.worstTerminalCommonCycles;
    aggregate.worstTerminalShutdownCycles =
        observation.timing.worstTerminalShutdownCycles;
    aggregate.worstTerminalInstrumentationCycles =
        observation.timing.worstTerminalInstrumentationCycles;
    aggregate.worstTerminalPreHandlerCycles =
        observation.timing.worstTerminalPreHandlerCycles;
    aggregate.worstTerminalFullIrqCycles =
        observation.timing.worstTerminalFullIrqCycles;
  }
  addSaturating(aggregate.irqPathSamples, observation.timing.irqPathSamples,
                aggregate.saturationFlags);
  addSaturating(aggregate.irqPathMissing, observation.timing.irqPathMissing,
                aggregate.saturationFlags);
  if (observation.timing.preHandlerMaxCycles > aggregate.preHandlerMaxCycles) {
    aggregate.preHandlerMaxCycles = observation.timing.preHandlerMaxCycles;
  }
  if (observation.timing.fullIrqMaxCycles > aggregate.fullIrqMaxCycles) {
    aggregate.fullIrqMaxCycles = observation.timing.fullIrqMaxCycles;
  }
  if (observation.timing.activeFullIrqMaxCycles > aggregate.activeFullIrqMaxCycles) {
    aggregate.activeFullIrqMaxCycles = observation.timing.activeFullIrqMaxCycles;
  }
  if (observation.timing.terminalFullIrqMaxCycles > aggregate.terminalFullIrqMaxCycles) {
    aggregate.terminalFullIrqMaxCycles = observation.timing.terminalFullIrqMaxCycles;
  }
  if (observation.timing.pendingPreHandlerMaxCycles > aggregate.pendingPreHandlerMaxCycles) {
    aggregate.pendingPreHandlerMaxCycles = observation.timing.pendingPreHandlerMaxCycles;
  }
  if (observation.timing.pendingFullIrqMaxCycles > aggregate.pendingFullIrqMaxCycles) {
    aggregate.pendingFullIrqMaxCycles = observation.timing.pendingFullIrqMaxCycles;
  }
  addSaturating(aggregate.entryTimerSamples, observation.timing.entryTimerSamples,
                aggregate.saturationFlags);
  addSaturating(aggregate.entryTimerMissing, observation.timing.entryTimerMissing,
                aggregate.saturationFlags);
  if (observation.timing.entryTimerCountMax > aggregate.entryTimerCountMax) {
    aggregate.entryTimerCountMax = observation.timing.entryTimerCountMax;
  }
  if (observation.timing.pendingEntryTimerCountMax > aggregate.pendingEntryTimerCountMax) {
    aggregate.pendingEntryTimerCountMax = observation.timing.pendingEntryTimerCountMax;
  }
  addSaturating(aggregate.lateEntryCount, observation.timing.lateEntryCount,
                aggregate.saturationFlags);
  if (observation.timing.entryScheduleOverrunMaxCycles >
      aggregate.entryScheduleOverrunMaxCycles) {
    aggregate.entryScheduleOverrunMaxCycles =
        observation.timing.entryScheduleOverrunMaxCycles;
  }
  const bool firstDeadlineSample = aggregate.deadlineSamples == 0u;
  addSaturating(aggregate.deadlineSamples, observation.timing.deadlineSamples,
                aggregate.saturationFlags);
  addSaturating(aggregate.deadlineMissing, observation.timing.deadlineMissing,
                aggregate.saturationFlags);
  addSaturating(aggregate.deadlineMisses, observation.timing.deadlineMisses,
                aggregate.saturationFlags);
  if (observation.timing.deadlineSamples != 0u &&
      (firstDeadlineSample || observation.timing.deadlineSlackMinTicks <
          aggregate.deadlineSlackMinTicks)) {
    aggregate.deadlineSlackMinTicks = observation.timing.deadlineSlackMinTicks;
  }
  addSaturating(aggregate.pendingObservations,
                observation.timing.pendingObservations,
                aggregate.saturationFlags);
  if (observation.timing.maxPendingStreak > aggregate.maxPendingStreak) {
    aggregate.maxPendingStreak = observation.timing.maxPendingStreak;
  }
  if (observation.durationErrorBasisPoints > aggregate.durationErrorMaxBasisPoints) {
    aggregate.durationErrorMaxBasisPoints = observation.durationErrorBasisPoints;
  }
  if (observation.statusPeriodMaxMs > aggregate.statusPeriodMaxMs) {
    aggregate.statusPeriodMaxMs = observation.statusPeriodMaxMs;
  }
  if (observation.statusWatchdogAgeMaxMs > aggregate.statusWatchdogAgeMaxMs) {
    aggregate.statusWatchdogAgeMaxMs = observation.statusWatchdogAgeMaxMs;
  }
  addSaturating(aggregate.statusFrameCount, observation.statusFrameCount,
                aggregate.saturationFlags);
  addSaturating(aggregate.statusAlternationErrors,
                observation.statusAlternationErrors,
                aggregate.saturationFlags);
  addSaturating(aggregate.watchdogLateCount, observation.watchdogLateCount,
                aggregate.saturationFlags);
  addSaturating(aggregate.cycleWraps, observation.timing.cycleWraps,
                aggregate.saturationFlags);
  aggregate.saturationFlags |= observation.timing.saturationFlags;
  if (observation.timerScheduleSaturationFlags != 0u) {
    aggregate.saturationFlags |= 0x40000000u;
  }
  if (observation.timedOut) {
    addSaturating(aggregate.timeoutCount, 1u, aggregate.saturationFlags);
  }
  aggregate.requireTerminalCycleBudget =
      aggregate.requireTerminalCycleBudget &&
      observation.requireTerminalCycleBudget;
  aggregate.exactAndSafe = aggregate.exactAndSafe && failureMask == 0u;
}

bool aggregatePasses(const Aggregate& aggregate,
                     uint32_t expectedMoves,
                     uint32_t expectedXEdges,
                     uint32_t expectedYEdges,
                     uint32_t expectedMasterEdges,
                     const Limits& limits) {
  return aggregate.exactAndSafe && aggregate.moveCount == expectedMoves &&
      aggregate.expectedXEdges == expectedXEdges &&
      aggregate.expectedYEdges == expectedYEdges &&
      aggregate.expectedMasterEdges == expectedMasterEdges &&
      aggregate.emittedXEdges == expectedXEdges &&
      aggregate.emittedYEdges == expectedYEdges &&
      aggregate.masterEdges == expectedMasterEdges &&
      aggregate.cleanupEdgeEvents == 0u &&
      aggregate.edgeSpacingViolations == 0u &&
      aggregate.timer2Callbacks == expectedMasterEdges &&
      aggregate.timer7Callbacks == 0u &&
      aggregate.timer2Callbacks >= aggregate.moveCount &&
      aggregate.conditionalDecisionCount ==
          aggregate.timer2Callbacks - aggregate.moveCount &&
      aggregate.conditionalDecisionMissingCount == 0u &&
      aggregate.timerRearmPendingCount == 0u &&
      rearmEvidenceConsistent(aggregate.timerRearmCount,
                              aggregate.timerRearmDelayMaxCycles) &&
      aggregate.conditionalNonRearmSlackMinTicks >
          CoordinatedXyTimerSchedulePolicy::kConditionalGuardTicks &&
      aggregate.timerScheduleSaturationFlags == 0u &&
      aggregate.pendingObservations == 0u &&
      aggregate.maxPendingStreak == 0u &&
      aggregate.saturationFlags == 0u && aggregate.timeoutCount == 0u &&
      aggregate.statusAlternationErrors == 0u &&
      aggregate.watchdogLateCount == 0u &&
      aggregate.cycleWraps <= aggregate.moveCount &&
      aggregate.statusFrameCount > 0u &&
      aggregate.terminalSampleCount == aggregate.moveCount &&
      aggregate.terminalStageAccountingViolations == 0u &&
      aggregateActiveMax(aggregate) <= limits.activeMaxCycles &&
      (!aggregate.requireTerminalCycleBudget ||
       aggregate.terminalMaxCycles <= limits.terminalMaxCycles) &&
      aggregate.durationErrorMaxBasisPoints <= limits.durationErrorMaxBasisPoints &&
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
      "hz=%lu;n=%lu;xe=%lu;ye=%lu;me=%lu;i2=%lu;i7=%lu;ok=%u;"
      "ce=%lu;sv=%lu;pu=%lu;ps=%lu;am=%lu;tm=%lu;de=%lu;sg=%lu;wd=%lu;sa=%lu;"
      "wl=%lu;cw=%lu;sf=%lu;xd=%lu;yd=%lu;to=%lu",
      static_cast<unsigned long>(rateHz),
      static_cast<unsigned long>(aggregate.moveCount),
      static_cast<unsigned long>(aggregate.emittedXEdges),
      static_cast<unsigned long>(aggregate.emittedYEdges),
      static_cast<unsigned long>(aggregate.masterEdges),
      static_cast<unsigned long>(aggregate.timer2Callbacks),
      static_cast<unsigned long>(aggregate.timer7Callbacks),
      static_cast<unsigned>(aggregate.exactAndSafe ? 1u : 0u),
      static_cast<unsigned long>(aggregate.cleanupEdgeEvents),
      static_cast<unsigned long>(aggregate.edgeSpacingViolations),
      static_cast<unsigned long>(aggregate.pendingObservations),
      static_cast<unsigned long>(aggregate.maxPendingStreak),
      static_cast<unsigned long>(aggregateActiveMax(aggregate)),
      static_cast<unsigned long>(aggregate.terminalMaxCycles),
      static_cast<unsigned long>(aggregate.durationErrorMaxBasisPoints),
      static_cast<unsigned long>(aggregate.statusPeriodMaxMs),
      static_cast<unsigned long>(aggregate.statusWatchdogAgeMaxMs),
      static_cast<unsigned long>(aggregate.statusAlternationErrors),
      static_cast<unsigned long>(aggregate.watchdogLateCount),
      static_cast<unsigned long>(aggregate.cycleWraps),
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

size_t buildCameraTransitionMetrics(
    char* out,
    size_t capacity,
    const Aggregate& aggregate,
    const CameraTransitionEvidence& evidence) {
  if (out == nullptr || capacity == 0u) return 0u;
  const int written = std::snprintf(
      out,
      capacity,
      "fs=%lu;n=%lu;xe=%lu;ye=%lu;i2=%lu;i7=%lu;pu=%lu;"
      "en=%u;sl=%u;ow=%u;lb=%u;hs=%ld;he=%ld;hg=%lu;"
      "hi=%lu;hpc=%lu;hpu=%lu;hd=%lu;mf=%lu;ab=%lu;am=%lu;tm=%lu;"
      "sf=%lu;to=%u",
      static_cast<unsigned long>(evidence.failureStage),
      static_cast<unsigned long>(aggregate.moveCount),
      static_cast<unsigned long>(aggregate.emittedXEdges),
      static_cast<unsigned long>(aggregate.emittedYEdges),
      static_cast<unsigned long>(aggregate.timer2Callbacks),
      static_cast<unsigned long>(aggregate.timer7Callbacks),
      static_cast<unsigned long>(aggregate.pendingObservations),
      evidence.transitionSafe ? 1u : 0u,
      evidence.stepsLow ? 1u : 0u,
      evidence.timerOwned ? 1u : 0u,
      evidence.limitBefore ? 1u : 0u,
      static_cast<long>(evidence.homeStartPositionSteps),
      static_cast<long>(evidence.homeEndPositionSteps),
      static_cast<unsigned long>(evidence.homeGuardSteps),
      static_cast<unsigned long>(evidence.homeIsrEntries),
      static_cast<unsigned long>(evidence.homeCompletedPulses),
      static_cast<unsigned long>(evidence.homePendingObservations),
      static_cast<unsigned long>(evidence.homeDriftSteps),
      static_cast<unsigned long>(aggregate.moveFailureMask),
      static_cast<unsigned long>(
          kCoordinatedActiveHandlerRegressionBudgetCycles),
      static_cast<unsigned long>(aggregateActiveMax(aggregate)),
      static_cast<unsigned long>(aggregate.terminalMaxCycles),
      static_cast<unsigned long>(aggregate.saturationFlags),
      evidence.homeEvidence ? 0u : 1u);
  if (written < 0 || static_cast<size_t>(written) >= capacity) {
    out[0] = '\0';
    return 0u;
  }
  return static_cast<size_t>(written);
}

}  // namespace CoordinatedXyPerformanceReport
