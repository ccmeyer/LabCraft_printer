#include "StepperInstrumentationReport.h"

#include <cstdio>
#include <cstdint>
#include <limits>

namespace StepperInstrumentationReport {
namespace {

uint32_t absoluteSteps(int32_t delta)
{
  const int64_t wide = static_cast<int64_t>(delta);
  return static_cast<uint32_t>((wide < 0) ? -wide : wide);
}

bool snapshotPasses(const StepperIsrInstrumentation::Snapshot& snapshot,
                    uint32_t expectedPulses)
{
  if (!snapshot.valid || snapshot.active || snapshot.aborted ||
      snapshot.saturationFlags != StepperIsrInstrumentation::SaturatedNone ||
      snapshot.completedPulses != expectedPulses ||
      snapshot.totalEntries != expectedTotalEntries(expectedPulses)) {
    return false;
  }

  uint64_t phaseEntryTotal = 0u;
  for (uint8_t i = 0u;
       i < static_cast<uint8_t>(StepperIsrInstrumentation::Phase::Count);
       ++i) {
    phaseEntryTotal += snapshot.phaseEntries[i];
  }
  return phaseEntryTotal == snapshot.totalEntries;
}

uint32_t phaseMax(const StepperIsrInstrumentation::Snapshot& x,
                  const StepperIsrInstrumentation::Snapshot& y,
                  StepperIsrInstrumentation::Phase phase)
{
  const uint8_t index = static_cast<uint8_t>(phase);
  return (x.phaseMaxCycles[index] > y.phaseMaxCycles[index])
      ? x.phaseMaxCycles[index]
      : y.phaseMaxCycles[index];
}

uint32_t greater(uint32_t a, uint32_t b)
{
  return (a > b) ? a : b;
}

uint64_t greater(uint64_t a, uint64_t b)
{
  return (a > b) ? a : b;
}

void formatUnsigned64(uint64_t value, char (&out)[21])
{
  char reversed[20] = {0};
  size_t digits = 0u;
  do {
    reversed[digits++] = static_cast<char>('0' + (value % 10u));
    value /= 10u;
  } while (value != 0u);

  for (size_t i = 0u; i < digits; ++i) {
    out[i] = reversed[digits - i - 1u];
  }
  out[digits] = '\0';
}

} // namespace

uint32_t expectedTotalEntries(uint32_t completedPulses)
{
  if (completedPulses == 0u) {
    return 0u;
  }
  if (completedPulses > ((std::numeric_limits<uint32_t>::max() - 1u) / 2u)) {
    return std::numeric_limits<uint32_t>::max();
  }
  return (completedPulses * 2u) + 1u;
}

bool movePasses(const MoveObservation& observation)
{
  return !observation.timedOut &&
         observation.endpointReached &&
         snapshotPasses(observation.x, absoluteSteps(observation.deltaXSteps)) &&
         snapshotPasses(observation.y, absoluteSteps(observation.deltaYSteps));
}

size_t buildMetrics(char* out,
                    size_t capacity,
                    const MoveObservation& observation)
{
  if (out == nullptr || capacity == 0u) {
    return 0u;
  }

  const uint64_t durationCycles =
      greater(observation.x.durationCycles, observation.y.durationCycles);
  const uint32_t cycleWraps =
      greater(observation.x.cycleWraps, observation.y.cycleWraps);
  const uint32_t maxPendingStreak =
      greater(observation.x.maxPendingStreak, observation.y.maxPendingStreak);
  const uint32_t saturationFlags =
      observation.x.saturationFlags | observation.y.saturationFlags;
  char durationCyclesText[21] = {0};
  formatUnsigned64(durationCycles, durationCyclesText);

  const int written = std::snprintf(
      out,
      capacity,
      "dx=%ld;dy=%ld;hz=%lu;to=%u;ep=%u;wd=%lu;sg=%lu;sn=%lu;"
      "du=%s;wr=%lu;xn=%lu;xp=%lu;xo=%lu;yn=%lu;yp=%lu;yo=%lu;"
      "am=%lu;cm=%lu;dm=%lu;ps=%lu;sf=%lu",
      static_cast<long>(observation.deltaXSteps),
      static_cast<long>(observation.deltaYSteps),
      static_cast<unsigned long>(observation.effectiveRateHz),
      static_cast<unsigned>(observation.timedOut ? 1u : 0u),
      static_cast<unsigned>(observation.endpointReached ? 1u : 0u),
      static_cast<unsigned long>(observation.statusWatchdogAgeMaxMs),
      static_cast<unsigned long>(observation.statusPeriodMaxMs),
      static_cast<unsigned long>(observation.statusFrameCount),
      durationCyclesText,
      static_cast<unsigned long>(cycleWraps),
      static_cast<unsigned long>(observation.x.totalEntries),
      static_cast<unsigned long>(observation.x.completedPulses),
      static_cast<unsigned long>(observation.x.pendingObservations),
      static_cast<unsigned long>(observation.y.totalEntries),
      static_cast<unsigned long>(observation.y.completedPulses),
      static_cast<unsigned long>(observation.y.pendingObservations),
      static_cast<unsigned long>(phaseMax(observation.x,
                                          observation.y,
                                          StepperIsrInstrumentation::Phase::Acceleration)),
      static_cast<unsigned long>(phaseMax(observation.x,
                                          observation.y,
                                          StepperIsrInstrumentation::Phase::Cruise)),
      static_cast<unsigned long>(phaseMax(observation.x,
                                          observation.y,
                                          StepperIsrInstrumentation::Phase::Deceleration)),
      static_cast<unsigned long>(maxPendingStreak),
      static_cast<unsigned long>(saturationFlags));

  if (written < 0 || static_cast<size_t>(written) >= capacity) {
    out[0] = '\0';
    return 0u;
  }
  return static_cast<size_t>(written);
}

} // namespace StepperInstrumentationReport
