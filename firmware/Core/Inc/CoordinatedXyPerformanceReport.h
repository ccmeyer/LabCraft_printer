#ifndef INC_COORDINATEDXYPERFORMANCEREPORT_H_
#define INC_COORDINATEDXYPERFORMANCEREPORT_H_

#include "CoordinatedXyExecutor.h"
#include "CoordinatedXyIsrInstrumentation.h"
#include "CoordinatedXyTimerSchedulePolicy.h"

#include <cstddef>
#include <cstdint>

namespace CoordinatedXyPerformanceReport {

// Compact diagnostic classification for every movePasses() gate. Related
// count/state checks share a bit so a failed target report can identify the
// gate without exceeding the self-test result-frame budget.
static constexpr uint32_t kMoveFailureTimedOut = 1u << 0;
static constexpr uint32_t kMoveFailureEndpoint = 1u << 1;
static constexpr uint32_t kMoveFailureTargets = 1u << 2;
static constexpr uint32_t kMoveFailureCompletion = 1u << 3;
static constexpr uint32_t kMoveFailurePins = 1u << 4;
static constexpr uint32_t kMoveFailureOwnership = 1u << 5;
static constexpr uint32_t kMoveFailureChecksum = 1u << 6;
static constexpr uint32_t kMoveFailureRequestedCounts = 1u << 7;
static constexpr uint32_t kMoveFailureEmittedCounts = 1u << 8;
static constexpr uint32_t kMoveFailureMasterCount = 1u << 9;
static constexpr uint32_t kMoveFailureSelectedRate = 1u << 10;
static constexpr uint32_t kMoveFailureTimerCounts = 1u << 11;
static constexpr uint32_t kMoveFailureArrRange = 1u << 12;
static constexpr uint32_t kMoveFailureTimingState = 1u << 13;
static constexpr uint32_t kMoveFailureTimingCounts = 1u << 14;
static constexpr uint32_t kMoveFailurePendingUpdate = 1u << 15;
static constexpr uint32_t kMoveFailureSaturation = 1u << 16;
static constexpr uint32_t kMoveFailureCycleWrap = 1u << 17;
static constexpr uint32_t kMoveFailureActiveCycles = 1u << 18;
static constexpr uint32_t kMoveFailureTerminalCycles = 1u << 19;
static constexpr uint32_t kMoveFailureDuration = 1u << 20;
static constexpr uint32_t kMoveFailureStatusPeriod = 1u << 21;
static constexpr uint32_t kMoveFailureStatusWatchdog = 1u << 22;
static constexpr uint32_t kMoveFailureStatusAlternation = 1u << 23;
static constexpr uint32_t kMoveFailureWatchdogLate = 1u << 24;
static constexpr uint32_t kMoveFailureExecutionMode = 1u << 25;
static constexpr uint32_t kMoveFailurePulseTiming = 1u << 26;
static constexpr uint32_t kMoveFailureDeadlineSlack = 1u << 27;
static constexpr uint32_t kMoveFailureTimerRearm = 1u << 28;
static constexpr uint32_t kMoveFailureScheduleSaturation = 1u << 29;
static constexpr uint32_t kMoveFailureTerminalReason = 1u << 30;
static constexpr uint32_t kMoveFailureEntryLateness = 1u << 31;

static constexpr uint32_t kMoveCollectionSoftFailureMask =
    kMoveFailurePendingUpdate |
    kMoveFailureCycleWrap |
    kMoveFailureActiveCycles |
    kMoveFailureTerminalCycles |
    kMoveFailureDuration |
    kMoveFailureStatusPeriod |
    kMoveFailureStatusWatchdog |
    kMoveFailureStatusAlternation |
    kMoveFailureDeadlineSlack |
    kMoveFailureTimerRearm |
    kMoveFailureEntryLateness;

struct Limits {
  uint32_t activeMaxCycles = 2025u;
  uint32_t terminalMaxCycles = 2250u;
  uint32_t durationErrorMaxBasisPoints = 100u;
  uint32_t statusPeriodMaxMs = 100u;
  uint32_t statusWatchdogAgeMaxMs = 100u;
  uint32_t maxCycleWrapsPerMove = 1u;
};

struct MoveObservation {
  uint32_t expectedXSteps = 0u;
  uint32_t expectedYSteps = 0u;
  uint32_t expectedMasterSteps = 0u;
  uint32_t expectedRateHz = 0u;
  uint32_t expectedTargetArr = 0u;
  uint32_t expectedStartArr = 0u;
  uint32_t interruptsPerMasterStep = 2u;
  CoordinatedXyExecutor::ExecutionMode executionMode =
      CoordinatedXyExecutor::ExecutionMode::TwoEdge;
  CoordinatedXyTimerSchedulePolicy::Mode timerScheduleMode =
      CoordinatedXyTimerSchedulePolicy::Mode::FreeRunning;
  uint32_t minimumPulseCoreCycles = 0u;
  uint32_t timerRearmCount = 0u;
  uint32_t timerRearmPendingCount = 0u;
  uint32_t timerRearmDelayMaxCycles = 0u;
  uint32_t conditionalDecisionCount = 0u;
  uint32_t conditionalDecisionMissingCount = 0u;
  uint32_t conditionalNonRearmSlackMinTicks = 0u;
  uint32_t lateInjectionCount = 0u;
  uint32_t lateInjectionFailureCount = 0u;
  uint32_t lateInjectionRearmCount = 0u;
  uint32_t lateInjectionDecisionSlackMaxTicks = 0u;
  uint32_t lateInjectionWaitMaxCycles = 0u;
  uint32_t timerScheduleSaturationFlags = 0u;
  CoordinatedXyExecutor::TerminalReason terminalReason =
      CoordinatedXyExecutor::TerminalReason::None;
  uint32_t requestedXSteps = 0u;
  uint32_t requestedYSteps = 0u;
  uint32_t emittedXSteps = 0u;
  uint32_t emittedYSteps = 0u;
  uint32_t masterSteps = 0u;
  uint32_t selectedRateHz = 0u;
  uint32_t timer2Callbacks = 0u;
  uint32_t timer7Callbacks = 0u;
  uint32_t arrMin = 0u;
  uint32_t arrMax = 0u;
  uint32_t durationErrorBasisPoints = 0u;
  uint32_t statusPeriodMaxMs = 0u;
  uint32_t statusWatchdogAgeMaxMs = 0u;
  uint32_t statusFrameCount = 0u;
  uint32_t statusAlternationErrors = 0u;
  uint32_t watchdogLateCount = 0u;
  uint32_t minimumDeadlineSlackTicks = 0u;
  // Diagnostic conditional-rearm selectors deliberately inject one late
  // edge. Production conditional rearm compiles that mechanism out and
  // instead requires all injection telemetry to remain zero.
  bool requireLateInjectionEvidence = true;
  // The terminal callback runs after the last physical STEP edge. Production
  // qualification records its cost but relies on the preceding per-edge
  // deadline evidence; diagnostic selectors retain the historical budget.
  bool requireTerminalCycleBudget = true;
  bool requireNoLateEntries = false;
  bool endpointMatches = false;
  bool targetsMatch = false;
  bool completionTogether = false;
  bool pinsLow = false;
  bool ownershipReleased = false;
  bool checksumMatch = false;
  bool timedOut = false;
  CoordinatedXyIsrInstrumentation::Snapshot timing{};
};

struct FailureTelemetry {
  bool valid = false;
  CoordinatedXyExecutor::TerminalReason terminalReason =
      CoordinatedXyExecutor::TerminalReason::None;
  uint32_t limitAbortRequestCount = 0u;
  uint32_t rawLimitAbortCount = 0u;
  uint32_t failureMask = 0u;
};

struct Aggregate {
  uint32_t moveCount = 0u;
  uint32_t expectedXSteps = 0u;
  uint32_t expectedYSteps = 0u;
  uint32_t expectedMasterSteps = 0u;
  uint32_t emittedXSteps = 0u;
  uint32_t emittedYSteps = 0u;
  uint32_t masterSteps = 0u;
  uint32_t timer2Callbacks = 0u;
  uint32_t timer7Callbacks = 0u;
  uint32_t interruptsPerMasterStep = 0u;
  CoordinatedXyExecutor::ExecutionMode executionMode =
      CoordinatedXyExecutor::ExecutionMode::TwoEdge;
  CoordinatedXyTimerSchedulePolicy::Mode timerScheduleMode =
      CoordinatedXyTimerSchedulePolicy::Mode::FreeRunning;
  uint32_t minimumPulseCoreCycles = 0u;
  uint32_t timerRearmCount = 0u;
  uint32_t timerRearmPendingCount = 0u;
  uint32_t timerRearmDelayMaxCycles = 0u;
  uint32_t conditionalDecisionCount = 0u;
  uint32_t conditionalDecisionMissingCount = 0u;
  uint32_t conditionalNonRearmSlackMinTicks = 0u;
  uint32_t lateInjectionCount = 0u;
  uint32_t lateInjectionFailureCount = 0u;
  uint32_t lateInjectionRearmCount = 0u;
  uint32_t lateInjectionDecisionSlackMaxTicks = 0u;
  uint32_t lateInjectionWaitMaxCycles = 0u;
  uint32_t timerScheduleSaturationFlags = 0u;
  uint32_t phaseCallbacks[static_cast<uint8_t>(CoordinatedXyIsrInstrumentation::Phase::Count)] = {};
  uint32_t phaseCycleSums[static_cast<uint8_t>(CoordinatedXyIsrInstrumentation::Phase::Count)] = {};
  uint32_t phaseMaxCycles[static_cast<uint8_t>(CoordinatedXyIsrInstrumentation::Phase::Count)] = {};
  uint32_t terminalMaxCycles = 0u;
  uint32_t irqPathSamples = 0u;
  uint32_t irqPathMissing = 0u;
  uint32_t preHandlerCycleSum = 0u;
  uint32_t preHandlerMaxCycles = 0u;
  uint32_t fullIrqCycleSum = 0u;
  uint32_t fullIrqMaxCycles = 0u;
  uint32_t activeFullIrqMaxCycles = 0u;
  uint32_t terminalFullIrqMaxCycles = 0u;
  uint32_t pendingPreHandlerMaxCycles = 0u;
  uint32_t pendingFullIrqMaxCycles = 0u;
  uint32_t entryTimerSamples = 0u;
  uint32_t entryTimerMissing = 0u;
  uint32_t entryTimerCountSum = 0u;
  uint32_t entryTimerCountMax = 0u;
  uint32_t pendingEntryTimerCountMax = 0u;
  uint32_t lateEntryCount = 0u;
  uint32_t entryScheduleOverrunMaxCycles = 0u;
  uint32_t completeStepPulseSamples = 0u;
  uint32_t completeStepPulseMinCycles = 0u;
  uint32_t completeStepPulseMaxCycles = 0u;
  uint32_t deadlineSamples = 0u;
  uint32_t deadlineMissing = 0u;
  uint32_t deadlineMisses = 0u;
  uint32_t deadlineSlackMinTicks = 0u;
  uint32_t intentionalWaitCycleSum = 0u;
  uint32_t intentionalWaitMaxCycles = 0u;
  uint32_t pendingObservations = 0u;
  uint32_t maxPendingStreak = 0u;
  uint32_t durationErrorMaxBasisPoints = 0u;
  uint32_t statusPeriodMaxMs = 0u;
  uint32_t statusWatchdogAgeMaxMs = 0u;
  uint32_t statusFrameCount = 0u;
  uint32_t statusAlternationErrors = 0u;
  uint32_t watchdogLateCount = 0u;
  uint32_t cycleWraps = 0u;
  uint32_t saturationFlags = 0u;
  uint32_t timeoutCount = 0u;
  uint32_t qualificationFailureMoveCount = 0u;
  uint32_t qualificationFailureMask = 0u;
  bool requireLateInjectionEvidence = true;
  bool requireTerminalCycleBudget = true;
  bool exactAndSafe = true;
};

uint32_t boundedHomeGuardSteps(int32_t currentPositionSteps,
                               uint32_t axisEnvelopeMaximumSteps,
                               uint32_t marginSteps,
                               uint32_t minimumGuardSteps,
                               bool positionKnown);

bool movePasses(const MoveObservation& observation, const Limits& limits);
bool moveCanContinueAfterCompletion(const MoveObservation& observation,
                                    const Limits& limits);
uint32_t moveFailureMask(const MoveObservation& observation,
                         const Limits& limits);
void captureFirstFailure(FailureTelemetry& telemetry,
                         bool movePassed,
                         CoordinatedXyExecutor::TerminalReason terminalReason,
                         uint32_t limitAbortRequestCount,
                         uint32_t rawLimitAbortCount,
                         uint32_t failureMask = 0u);
void addMove(Aggregate& aggregate,
             const MoveObservation& observation,
             const Limits& limits);
uint32_t phaseMeanCycles(const Aggregate& aggregate,
                         CoordinatedXyIsrInstrumentation::Phase phase);
uint32_t preHandlerMeanCycles(const Aggregate& aggregate);
uint32_t fullIrqMeanCycles(const Aggregate& aggregate);
uint32_t entryTimerMeanTicks(const Aggregate& aggregate);
bool aggregatePasses(const Aggregate& aggregate,
                     uint32_t expectedMoves,
                     uint32_t expectedXSteps,
                     uint32_t expectedYSteps,
                     uint32_t expectedMasterSteps,
                     const Limits& limits);
size_t buildMetrics(char* out,
                    size_t capacity,
                    uint32_t rateHz,
                    const Aggregate& aggregate,
                    uint32_t xDriftSteps,
                    uint32_t yDriftSteps);

}  // namespace CoordinatedXyPerformanceReport

#endif /* INC_COORDINATEDXYPERFORMANCEREPORT_H_ */
