#include "DirectStepperProfileReport.h"

#include <cstdio>
#include <limits>

namespace DirectStepperProfileReport {
namespace {

uint32_t expectedEntries(uint32_t pulses) {
  if (pulses == 0u) return 0u;
  if (pulses > ((std::numeric_limits<uint32_t>::max() - 1u) / 2u)) {
    return std::numeric_limits<uint32_t>::max();
  }
  return (pulses * 2u) + 1u;
}

uint32_t maximumActivePhaseCycles(
    const StepperIsrInstrumentation::Snapshot& snapshot) {
  uint32_t maximum = 0u;
  for (uint8_t index = 0u;
       index <= static_cast<uint8_t>(StepperIsrInstrumentation::Phase::Deceleration);
       ++index) {
    if (snapshot.phaseMaxCycles[index] > maximum) {
      maximum = snapshot.phaseMaxCycles[index];
    }
  }
  return maximum;
}

bool profilePasses(const MoveObservation& observation) {
  const auto& profile = observation.profile;
  return observation.expectedNativePulses <=
             (std::numeric_limits<uint32_t>::max() / 2u) &&
         profile.selected && !profile.active && profile.completed &&
         !profile.prepareFailed && !profile.runtimeFailed && !profile.aborted &&
         profile.totalToggles == (observation.expectedNativePulses * 2u) &&
         profile.accelConsumed == profile.accelIntervals &&
         profile.decelConsumed == DirectStepperProfile::expectedDecelSamples(
             profile.totalToggles,
             profile.accelIntervals,
             profile.decelIntervals);
}

bool instrumentationPasses(const MoveObservation& observation) {
  if (!observation.instrumentationRequired) return true;
  const auto& snapshot = observation.instrumentation;
  return snapshot.valid && !snapshot.active && !snapshot.aborted &&
         snapshot.saturationFlags == StepperIsrInstrumentation::SaturatedNone &&
         snapshot.completedPulses == observation.expectedNativePulses &&
         snapshot.totalEntries == expectedEntries(observation.expectedNativePulses) &&
         snapshot.pendingObservations == 0u &&
         snapshot.maxPendingStreak == 0u;
}

}  // namespace

bool movePasses(const MoveObservation& observation) {
  return !observation.timedOut && observation.endpointReached &&
         observation.expectedNativePulses != 0u &&
         profilePasses(observation) && instrumentationPasses(observation);
}

size_t buildMetrics(char* out,
                    size_t capacity,
                    const MoveObservation& observation) {
  if (out == nullptr || capacity == 0u) return 0u;

  const auto& profile = observation.profile;
  const auto& timing = observation.instrumentation;
  const int written = std::snprintf(
      out,
      capacity,
      "ax=%u;ds=%lu;hz=%lu;np=%lu;to=%u;ep=%u;nm=%u;co=%u;pf=%u;"
      "rf=%u;ab=%u;tt=%lu;ai=%lu;ac=%lu;di=%lu;dc=%lu;en=%lu;"
      "pc=%lu;po=%lu;mx=%lu;tm=%lu;sf=%lu;wd=%lu;sg=%lu;sn=%lu",
      static_cast<unsigned>(observation.axis),
      static_cast<unsigned long>(observation.logicalDistance),
      static_cast<unsigned long>(observation.effectiveRateHz),
      static_cast<unsigned long>(observation.expectedNativePulses),
      static_cast<unsigned>(observation.timedOut ? 1u : 0u),
      static_cast<unsigned>(observation.endpointReached ? 1u : 0u),
      static_cast<unsigned>(profile.selected ? 1u : 0u),
      static_cast<unsigned>(profile.completed ? 1u : 0u),
      static_cast<unsigned>(profile.prepareFailed ? 1u : 0u),
      static_cast<unsigned>(profile.runtimeFailed ? 1u : 0u),
      static_cast<unsigned>(profile.aborted ? 1u : 0u),
      static_cast<unsigned long>(profile.totalToggles),
      static_cast<unsigned long>(profile.accelIntervals),
      static_cast<unsigned long>(profile.accelConsumed),
      static_cast<unsigned long>(profile.decelIntervals),
      static_cast<unsigned long>(profile.decelConsumed),
      static_cast<unsigned long>(timing.totalEntries),
      static_cast<unsigned long>(timing.completedPulses),
      static_cast<unsigned long>(timing.pendingObservations),
      static_cast<unsigned long>(maximumActivePhaseCycles(timing)),
      static_cast<unsigned long>(timing.phaseMaxCycles[
          static_cast<uint8_t>(StepperIsrInstrumentation::Phase::Completion)]),
      static_cast<unsigned long>(timing.saturationFlags),
      static_cast<unsigned long>(observation.statusWatchdogAgeMaxMs),
      static_cast<unsigned long>(observation.statusPeriodMaxMs),
      static_cast<unsigned long>(observation.statusFrameCount));
  if (written < 0 || static_cast<size_t>(written) >= capacity) {
    out[0] = '\0';
    return 0u;
  }
  return static_cast<size_t>(written);
}

}  // namespace DirectStepperProfileReport
