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
  if (observation.timer2Callbacks != observation.expectedMasterSteps * 2u ||
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
      timing.completedPulses != observation.expectedMasterSteps ||
      timing.terminalCallbacks != 1u ||
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

void addMove(Aggregate& aggregate,
             const MoveObservation& observation,
             const Limits& limits) {
  const uint32_t failureMask = moveFailureMask(observation, limits);
  addSaturating(aggregate.moveCount, 1u, aggregate.saturationFlags);
  addSaturating(aggregate.expectedXSteps, observation.expectedXSteps,
                aggregate.saturationFlags);
  addSaturating(aggregate.expectedYSteps, observation.expectedYSteps,
                aggregate.saturationFlags);
  addSaturating(aggregate.expectedMasterSteps, observation.expectedMasterSteps,
                aggregate.saturationFlags);
  addSaturating(aggregate.emittedXSteps, observation.emittedXSteps,
                aggregate.saturationFlags);
  addSaturating(aggregate.emittedYSteps, observation.emittedYSteps,
                aggregate.saturationFlags);
  addSaturating(aggregate.masterSteps, observation.masterSteps,
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
  if (observation.timing.terminalMaxCycles > aggregate.terminalMaxCycles) {
    aggregate.terminalMaxCycles = observation.timing.terminalMaxCycles;
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
                     uint32_t expectedXSteps,
                     uint32_t expectedYSteps,
                     uint32_t expectedMasterSteps,
                     const Limits& limits) {
  return aggregate.exactAndSafe && aggregate.moveCount == expectedMoves &&
      aggregate.expectedXSteps == expectedXSteps &&
      aggregate.expectedYSteps == expectedYSteps &&
      aggregate.expectedMasterSteps == expectedMasterSteps &&
      aggregate.emittedXSteps == expectedXSteps &&
      aggregate.emittedYSteps == expectedYSteps &&
      aggregate.masterSteps == expectedMasterSteps &&
      aggregate.timer2Callbacks == expectedMasterSteps * 2u &&
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
      "hz=%lu;n=%lu;xe=%lu;ye=%lu;ms=%lu;i2=%lu;i7=%lu;ok=%u;"
      "pu=%lu;ps=%lu;am=%lu;tm=%lu;de=%lu;sg=%lu;wd=%lu;sa=%lu;"
      "wl=%lu;cw=%lu;sf=%lu;xd=%lu;yd=%lu;to=%lu",
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

}  // namespace CoordinatedXyPerformanceReport
