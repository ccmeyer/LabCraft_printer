#include "ZAxisSpeedLadderReport.h"

#include <cstdio>
#include <limits>

namespace ZAxisSpeedLadderReport {
namespace {

void addSaturating(uint32_t& destination,
                   uint32_t value,
                   uint32_t& saturationFlags)
{
  if (destination > std::numeric_limits<uint32_t>::max() - value) {
    destination = std::numeric_limits<uint32_t>::max();
    saturationFlags |= (1u << 31);
  } else {
    destination += value;
  }
}

void updateMaximum(uint32_t& destination, uint32_t value)
{
  if (value > destination) destination = value;
}

uint32_t maximumActiveBodyCycles(
    const StepperIsrInstrumentation::Snapshot& snapshot)
{
  uint32_t maximum = 0u;
  for (uint8_t index = 0u;
       index <= static_cast<uint8_t>(
           StepperIsrInstrumentation::Phase::Deceleration);
       ++index) {
    updateMaximum(maximum, snapshot.phaseMaxCycles[index]);
  }
  return maximum;
}

bool profilePasses(const MoveObservation& move)
{
  const auto& profile = move.profile;
  return profile.selected && !profile.active && profile.completed &&
      !profile.prepareFailed && !profile.runtimeFailed && !profile.aborted &&
      move.expectedNativePulses <=
          (std::numeric_limits<uint32_t>::max() / 2u) &&
      profile.totalToggles == move.expectedNativePulses * 2u &&
      profile.accelConsumed == profile.accelIntervals &&
      profile.decelConsumed == DirectStepperProfile::expectedDecelSamples(
          profile.totalToggles,
          profile.accelIntervals,
          profile.decelIntervals);
}

}  // namespace

void accumulateMove(TierObservation& tier, const MoveObservation& move)
{
  addSaturating(tier.logicalDistance, move.logicalDistance,
                tier.saturationFlags);
  addSaturating(tier.nativePulses, move.timing.completedPulses,
                tier.saturationFlags);
  addSaturating(tier.callbacks, move.timing.totalEntries,
                tier.saturationFlags);
  addSaturating(tier.fullIrqSamples, move.timing.fullIrqSamples,
                tier.saturationFlags);
  addSaturating(tier.missingFullIrqSamples,
                move.timing.missingFullIrqSamples,
                tier.saturationFlags);
  addSaturating(tier.pendingObservations, move.timing.pendingObservations,
                tier.saturationFlags);
  updateMaximum(tier.maximumPendingStreak, move.timing.maxPendingStreak);
  updateMaximum(tier.activeBodyMaxCycles,
                maximumActiveBodyCycles(move.timing));
  updateMaximum(tier.activeFullIrqMaxCycles,
                move.timing.fullIrqActiveMaxCycles);
  updateMaximum(tier.terminalFullIrqMaxCycles,
                move.timing.fullIrqTerminalMaxCycles);
  updateMaximum(tier.entryTimerCountMax, move.timing.entryTimerCountMax);
  addSaturating(tier.deadlineSamples, move.timing.deadlineSamples,
                tier.saturationFlags);
  addSaturating(tier.deadlineMisses, move.timing.deadlineMisses,
                tier.saturationFlags);
  if (move.timing.minimumDeadlineSlackCycles <
      tier.minimumDeadlineSlackCycles) {
    tier.minimumDeadlineSlackCycles =
        move.timing.minimumDeadlineSlackCycles;
  }
  addSaturating(tier.cycleWrapCount, move.timing.cycleWraps,
                tier.saturationFlags);
  tier.saturationFlags |= move.timing.saturationFlags;

  if (!profilePasses(move)) {
    addSaturating(tier.profileFailureCount, 1u, tier.saturationFlags);
  }
  if (!move.endpointReached) {
    addSaturating(tier.endpointFailureCount, 1u, tier.saturationFlags);
  }
  if (move.timedOut) {
    addSaturating(tier.timeoutCount, 1u, tier.saturationFlags);
  }
}

bool tierPasses(const TierObservation& tier,
                uint32_t expectedLogicalDistance,
                uint32_t expectedNativePulses,
                uint32_t expectedCallbacks,
                uint32_t expectedDeadlineSamples)
{
  return !tier.skipped &&
      tier.completedRepetitions == kRequiredRepetitions &&
      tier.logicalDistance == expectedLogicalDistance &&
      tier.nativePulses == expectedNativePulses &&
      tier.callbacks == expectedCallbacks &&
      tier.fullIrqSamples == expectedCallbacks &&
      tier.missingFullIrqSamples == 0u &&
      tier.pendingObservations == 0u && tier.maximumPendingStreak == 0u &&
      tier.activeBodyMaxCycles <= kActiveBodyLimitCycles &&
      tier.activeFullIrqMaxCycles <= kActiveFullIrqLimitCycles &&
      tier.terminalFullIrqMaxCycles <= kTerminalFullIrqLimitCycles &&
      tier.deadlineSamples == expectedDeadlineSamples &&
      tier.deadlineMisses == 0u &&
      tier.minimumDeadlineSlackCycles >= kMinimumDeadlineSlackCycles &&
      tier.profileFailureCount == 0u && tier.endpointFailureCount == 0u &&
      tier.timeoutCount == 0u &&
      tier.cycleWrapCount <= kMeasuredMovesPerTier &&
      tier.saturationFlags == 0u &&
      tier.homeSpanSteps <= kHomeErrorLimitLogicalSteps &&
      tier.homeDriftSteps <= kHomeErrorLimitLogicalSteps &&
      tier.returnErrorSteps <= kReturnErrorLimitLogicalSteps &&
      tier.limitConfirmations == 0u && !tier.limitPending &&
      tier.statusEvidenceValid &&
      tier.statusPeriodMaxMs <= kStatusPeriodLimitMs &&
      tier.statusWatchdogAgeMaxMs <= kStatusWatchdogAgeLimitMs &&
      tier.statusAlternationErrors == 0u;
}

size_t buildMetrics(char* out,
                    size_t capacity,
                    const TierObservation& tier)
{
  if (out == nullptr || capacity == 0u) return 0u;
  const int written = std::snprintf(
      out,
      capacity,
      "hz=%lu;rep=%lu;ld=%lu;np=%lu;cb=%lu;s=%lu;mi=%lu;po=%lu;"
      "ps=%lu;bm=%lu;fm=%lu;tm=%lu;em=%lu;ds=%lu;dm=%lu;sl=%lu;"
      "pf=%lu;ep=%lu;cw=%lu;zs=%lu;zd=%lu;zr=%lu;lf=%lu;lp=%u;sg=%lu;"
      "wd=%lu;sa=%lu;sf=%lu;to=%lu;sk=%u",
      static_cast<unsigned long>(tier.rateHz),
      static_cast<unsigned long>(tier.completedRepetitions),
      static_cast<unsigned long>(tier.logicalDistance),
      static_cast<unsigned long>(tier.nativePulses),
      static_cast<unsigned long>(tier.callbacks),
      static_cast<unsigned long>(tier.fullIrqSamples),
      static_cast<unsigned long>(tier.missingFullIrqSamples),
      static_cast<unsigned long>(tier.pendingObservations),
      static_cast<unsigned long>(tier.maximumPendingStreak),
      static_cast<unsigned long>(tier.activeBodyMaxCycles),
      static_cast<unsigned long>(tier.activeFullIrqMaxCycles),
      static_cast<unsigned long>(tier.terminalFullIrqMaxCycles),
      static_cast<unsigned long>(tier.entryTimerCountMax),
      static_cast<unsigned long>(tier.deadlineSamples),
      static_cast<unsigned long>(tier.deadlineMisses),
      static_cast<unsigned long>(tier.minimumDeadlineSlackCycles),
      static_cast<unsigned long>(tier.profileFailureCount),
      static_cast<unsigned long>(tier.endpointFailureCount),
      static_cast<unsigned long>(tier.cycleWrapCount),
      static_cast<unsigned long>(tier.homeSpanSteps),
      static_cast<unsigned long>(tier.homeDriftSteps),
      static_cast<unsigned long>(tier.returnErrorSteps),
      static_cast<unsigned long>(tier.limitConfirmations),
      static_cast<unsigned>(tier.limitPending ? 1u : 0u),
      static_cast<unsigned long>(tier.statusPeriodMaxMs),
      static_cast<unsigned long>(tier.statusWatchdogAgeMaxMs),
      static_cast<unsigned long>(tier.statusAlternationErrors),
      static_cast<unsigned long>(tier.saturationFlags),
      static_cast<unsigned long>(tier.timeoutCount),
      static_cast<unsigned>(tier.skipped ? 1u : 0u));
  if (written < 0 || static_cast<size_t>(written) >= capacity) {
    out[0] = '\0';
    return 0u;
  }
  return static_cast<size_t>(written);
}

}  // namespace ZAxisSpeedLadderReport
