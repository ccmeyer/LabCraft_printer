#ifndef INC_COORDINATEDXYPERFORMANCEREPORT_H_
#define INC_COORDINATEDXYPERFORMANCEREPORT_H_

#include "CoordinatedXyIsrInstrumentation.h"

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
  uint32_t expectedXSteps = 0u;
  uint32_t expectedYSteps = 0u;
  uint32_t expectedMasterSteps = 0u;
  uint32_t emittedXSteps = 0u;
  uint32_t emittedYSteps = 0u;
  uint32_t masterSteps = 0u;
  uint32_t timer2Callbacks = 0u;
  uint32_t timer7Callbacks = 0u;
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
  bool exactAndSafe = true;
};

uint32_t boundedHomeGuardSteps(int32_t currentPositionSteps,
                               uint32_t axisEnvelopeMaximumSteps,
                               uint32_t marginSteps,
                               uint32_t minimumGuardSteps,
                               bool positionKnown);

bool movePasses(const MoveObservation& observation, const Limits& limits);
uint32_t moveFailureMask(const MoveObservation& observation,
                         const Limits& limits);
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
