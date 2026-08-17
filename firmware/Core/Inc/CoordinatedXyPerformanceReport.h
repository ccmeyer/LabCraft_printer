#ifndef INC_COORDINATEDXYPERFORMANCEREPORT_H_
#define INC_COORDINATEDXYPERFORMANCEREPORT_H_

#include "CoordinatedXyExecutor.h"
#include "CoordinatedXyIsrInstrumentation.h"

#include <cstddef>
#include <cstdint>

namespace CoordinatedXyPerformanceReport {

static constexpr uint32_t kCoordinatedActiveHandlerRegressionBudgetCycles =
    2600u;
static constexpr uint32_t kCoordinatedTerminalHandlerBudgetCycles = 3500u;

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
static constexpr uint32_t kMoveFailureDeadlineSlack = 1u << 25;
static constexpr uint32_t kMoveFailureTimerRearm = 1u << 26;
static constexpr uint32_t kMoveFailureScheduleSaturation = 1u << 27;
static constexpr uint32_t kMoveFailureTerminalReason = 1u << 28;
static constexpr uint32_t kMoveFailureEntryLateness = 1u << 29;
static constexpr uint32_t kMoveFailureCleanupEdges = 1u << 30;
static constexpr uint32_t kMoveFailureEdgeSpacing = 1u << 31;

struct Limits {
  uint32_t activeMaxCycles =
      kCoordinatedActiveHandlerRegressionBudgetCycles;
  // Terminal cleanup runs after the final STEP edge while TIM2 is stopping,
  // so it is not constrained by the 4,500-core-cycle active edge interval.
  // Keep a separate bounded regression gate with 20% margin above the
  // accepted 2,910-cycle HIL maximum.
  uint32_t terminalMaxCycles = kCoordinatedTerminalHandlerBudgetCycles;
  uint32_t durationErrorMaxBasisPoints = 100u;
  uint32_t statusPeriodMaxMs = 100u;
  uint32_t statusWatchdogAgeMaxMs = 100u;
  uint32_t maxCycleWrapsPerMove = 1u;
};

struct ShallowMoveTimingExpectation {
  uint32_t selectedRateHz = 0u;
  uint32_t targetArr = 0u;
  uint32_t startArr = 0u;
};

struct MoveObservation {
  uint32_t expectedXEdges = 0u;
  uint32_t expectedYEdges = 0u;
  uint32_t expectedMasterEdges = 0u;
  uint32_t expectedRateHz = 0u;
  uint32_t expectedTargetArr = 0u;
  uint32_t expectedStartArr = 0u;
  uint32_t timerRearmCount = 0u;
  uint32_t timerRearmPendingCount = 0u;
  uint32_t timerRearmDelayMaxCycles = 0u;
  uint32_t conditionalDecisionCount = 0u;
  uint32_t conditionalDecisionMissingCount = 0u;
  uint32_t conditionalNonRearmSlackMinTicks = 0u;
  uint32_t timerScheduleSaturationFlags = 0u;
  CoordinatedXyExecutor::TerminalReason terminalReason =
      CoordinatedXyExecutor::TerminalReason::None;
  uint32_t requestedXEdges = 0u;
  uint32_t requestedYEdges = 0u;
  uint32_t emittedXEdges = 0u;
  uint32_t emittedYEdges = 0u;
  uint32_t masterEdges = 0u;
  uint32_t cleanupEdgeEvents = 0u;
  uint32_t edgeSpacingViolations = 0u;
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

struct Aggregate {
  uint32_t moveCount = 0u;
  uint32_t moveFailureMask = 0u;
  uint32_t expectedXEdges = 0u;
  uint32_t expectedYEdges = 0u;
  uint32_t expectedMasterEdges = 0u;
  uint32_t emittedXEdges = 0u;
  uint32_t emittedYEdges = 0u;
  uint32_t masterEdges = 0u;
  uint32_t cleanupEdgeEvents = 0u;
  uint32_t edgeSpacingViolations = 0u;
  uint32_t timer2Callbacks = 0u;
  uint32_t timer7Callbacks = 0u;
  uint32_t timerRearmCount = 0u;
  uint32_t timerRearmPendingCount = 0u;
  uint32_t timerRearmDelayMaxCycles = 0u;
  uint32_t conditionalDecisionCount = 0u;
  uint32_t conditionalDecisionMissingCount = 0u;
  uint32_t conditionalNonRearmSlackMinTicks = 0u;
  uint32_t timerScheduleSaturationFlags = 0u;
  uint32_t phaseCallbacks[static_cast<uint8_t>(CoordinatedXyIsrInstrumentation::Phase::Count)] = {};
  uint32_t phaseMaxCycles[static_cast<uint8_t>(CoordinatedXyIsrInstrumentation::Phase::Count)] = {};
  uint32_t terminalMaxCycles = 0u;
  uint32_t terminalSampleCount = 0u;
  uint32_t terminalMinCycles = 0u;
  uint32_t terminalTotalCycles = 0u;
  uint32_t terminalOverBudgetCount = 0u;
  uint32_t terminalStageAccountingViolations = 0u;
  uint32_t worstTerminalCommonCycles = 0u;
  uint32_t worstTerminalShutdownCycles = 0u;
  uint32_t worstTerminalInstrumentationCycles = 0u;
  uint32_t worstTerminalPreHandlerCycles = 0u;
  uint32_t worstTerminalFullIrqCycles = 0u;
  uint32_t irqPathSamples = 0u;
  uint32_t irqPathMissing = 0u;
  uint32_t preHandlerMaxCycles = 0u;
  uint32_t fullIrqMaxCycles = 0u;
  uint32_t activeFullIrqMaxCycles = 0u;
  uint32_t terminalFullIrqMaxCycles = 0u;
  uint32_t pendingPreHandlerMaxCycles = 0u;
  uint32_t pendingFullIrqMaxCycles = 0u;
  uint32_t entryTimerSamples = 0u;
  uint32_t entryTimerMissing = 0u;
  uint32_t entryTimerCountMax = 0u;
  uint32_t pendingEntryTimerCountMax = 0u;
  uint32_t lateEntryCount = 0u;
  uint32_t entryScheduleOverrunMaxCycles = 0u;
  uint32_t deadlineSamples = 0u;
  uint32_t deadlineMissing = 0u;
  uint32_t deadlineMisses = 0u;
  uint32_t deadlineSlackMinTicks = 0u;
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
  bool requireTerminalCycleBudget = true;
  bool exactAndSafe = true;
};

struct CameraTransitionEvidence {
  uint32_t failureStage = 0u;
  bool transitionSafe = false;
  bool stepsLow = false;
  bool timerOwned = false;
  bool limitBefore = false;
  int32_t homeStartPositionSteps = 0;
  int32_t homeEndPositionSteps = 0;
  uint32_t homeGuardSteps = 0u;
  uint32_t homeIsrEntries = 0u;
  uint32_t homeCompletedPulses = 0u;
  uint32_t homePendingObservations = 0u;
  uint32_t homeDriftSteps = 0u;
  bool homeEvidence = false;
};

uint32_t boundedHomeGuardSteps(int32_t currentPositionSteps,
                               uint32_t axisEnvelopeMaximumSteps,
                               uint32_t marginSteps,
                               uint32_t minimumGuardSteps,
                               bool positionKnown);
bool shallowMoveTimingExpectation(
    uint32_t requestedRateHz,
    uint32_t masterEdges,
    ShallowMoveTimingExpectation& expectation);
uint32_t moveFailureMask(const MoveObservation& observation,
                         const Limits& limits);
bool movePasses(const MoveObservation& observation, const Limits& limits);
bool canContinueAfterTerminalBudgetOnlyFailure(uint32_t failureMask);
uint32_t terminalAverageCycles(const Aggregate& aggregate);
void addMove(Aggregate& aggregate,
             const MoveObservation& observation,
             const Limits& limits);
bool aggregatePasses(const Aggregate& aggregate,
                     uint32_t expectedMoves,
                     uint32_t expectedXEdges,
                     uint32_t expectedYEdges,
                     uint32_t expectedMasterEdges,
                     const Limits& limits);
size_t buildMetrics(char* out,
                    size_t capacity,
                    uint32_t rateHz,
                    const Aggregate& aggregate,
                    uint32_t xDriftSteps,
                    uint32_t yDriftSteps);
size_t buildCameraTransitionMetrics(
    char* out,
    size_t capacity,
    const Aggregate& aggregate,
    const CameraTransitionEvidence& evidence);

}  // namespace CoordinatedXyPerformanceReport

#endif /* INC_COORDINATEDXYPERFORMANCEREPORT_H_ */
