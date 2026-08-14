#ifndef INC_ZAXISSPEEDLADDERREPORT_H_
#define INC_ZAXISSPEEDLADDERREPORT_H_

#include "DirectStepperProfile.h"
#include "StepperIsrInstrumentation.h"

#include <cstddef>
#include <cstdint>

namespace ZAxisSpeedLadderReport {

constexpr uint32_t kRequiredRepetitions = 3u;
constexpr uint32_t kMeasuredMovesPerTier = kRequiredRepetitions * 2u;
constexpr uint32_t kActiveBodyLimitCycles = 2250u;
constexpr uint32_t kActiveFullIrqLimitCycles = 2550u;
constexpr uint32_t kTerminalFullIrqLimitCycles = 4500u;
constexpr uint32_t kMinimumDeadlineSlackCycles = 900u;
constexpr uint32_t kHomeErrorLimitLogicalSteps = 25u;
constexpr uint32_t kReturnErrorLimitLogicalSteps = 10u;
constexpr uint32_t kStatusPeriodLimitMs = 125u;
constexpr uint32_t kStatusWatchdogAgeLimitMs = 100u;

struct MoveObservation {
  uint32_t logicalDistance = 0u;
  uint32_t expectedNativePulses = 0u;
  bool timedOut = false;
  bool endpointReached = false;
  DirectStepperProfile::Snapshot profile{};
  StepperIsrInstrumentation::Snapshot timing{};
};

struct TierObservation {
  uint32_t rateHz = 0u;
  uint32_t accelerationStepsPerSec2 = 0u;
  uint32_t completedRepetitions = 0u;
  uint32_t logicalDistance = 0u;
  uint32_t nativePulses = 0u;
  uint32_t callbacks = 0u;
  uint32_t fullIrqSamples = 0u;
  uint32_t missingFullIrqSamples = 0u;
  uint32_t pendingObservations = 0u;
  uint32_t maximumPendingStreak = 0u;
  uint32_t activeBodyMaxCycles = 0u;
  uint32_t activeFullIrqMaxCycles = 0u;
  uint32_t terminalFullIrqMaxCycles = 0u;
  uint32_t entryTimerCountMax = 0u;
  uint32_t deadlineSamples = 0u;
  uint32_t deadlineMisses = 0u;
  uint32_t minimumDeadlineSlackCycles = UINT32_MAX;
  uint32_t profileFailureCount = 0u;
  uint32_t endpointFailureCount = 0u;
  uint32_t timeoutCount = 0u;
  uint32_t cycleWrapCount = 0u;
  uint32_t saturationFlags = 0u;
  uint32_t homeSpanSteps = 0u;
  uint32_t homeDriftSteps = 0u;
  uint32_t returnErrorSteps = 0u;
  uint32_t limitConfirmations = 0u;
  bool limitPending = false;
  bool statusEvidenceValid = false;
  uint32_t statusPeriodMaxMs = UINT32_MAX;
  uint32_t statusWatchdogAgeMaxMs = UINT32_MAX;
  uint32_t statusAlternationErrors = UINT32_MAX;
  bool skipped = false;
};

void accumulateMove(TierObservation& tier, const MoveObservation& move);
bool tierPasses(const TierObservation& tier,
                uint32_t expectedRateHz,
                uint32_t expectedAccelerationStepsPerSec2,
                uint32_t expectedLogicalDistance,
                uint32_t expectedNativePulses,
                uint32_t expectedCallbacks,
                uint32_t expectedDeadlineSamples);
size_t buildMetrics(char* out,
                    size_t capacity,
                    const TierObservation& tier);

}  // namespace ZAxisSpeedLadderReport

#endif  // INC_ZAXISSPEEDLADDERREPORT_H_
