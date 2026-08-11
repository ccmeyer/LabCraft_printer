#include "CppUTest/TestHarness.h"
#include "DiagnosticResultEmitter.h"
#include "StepperInstrumentationReport.h"

#include <cstring>

namespace {

StepperIsrInstrumentation::Snapshot completedSnapshot(uint32_t pulses,
                                                       uint32_t accelMax,
                                                       uint32_t cruiseMax,
                                                       uint32_t decelMax)
{
  StepperIsrInstrumentation::Snapshot snapshot{};
  snapshot.valid = true;
  snapshot.completedPulses = pulses;
  snapshot.totalEntries = StepperInstrumentationReport::expectedTotalEntries(pulses);
  if (pulses != 0u) {
    snapshot.phaseEntries[static_cast<uint8_t>(StepperIsrInstrumentation::Phase::Acceleration)] = 2u;
    snapshot.phaseEntries[static_cast<uint8_t>(StepperIsrInstrumentation::Phase::Deceleration)] = 2u;
    snapshot.phaseEntries[static_cast<uint8_t>(StepperIsrInstrumentation::Phase::Completion)] = 1u;
    snapshot.phaseEntries[static_cast<uint8_t>(StepperIsrInstrumentation::Phase::Cruise)] =
        snapshot.totalEntries - 5u;
  }
  snapshot.phaseMaxCycles[static_cast<uint8_t>(StepperIsrInstrumentation::Phase::Acceleration)] = accelMax;
  snapshot.phaseMaxCycles[static_cast<uint8_t>(StepperIsrInstrumentation::Phase::Cruise)] = cruiseMax;
  snapshot.phaseMaxCycles[static_cast<uint8_t>(StepperIsrInstrumentation::Phase::Deceleration)] = decelMax;
  return snapshot;
}

size_t findTag(const uint8_t* payload, size_t len, uint8_t tag)
{
  size_t index = 2u;
  while ((index + 2u) <= len) {
    const uint8_t currentTag = payload[index++];
    const uint8_t valueLen = payload[index++];
    if (currentTag == tag) {
      return index - 2u;
    }
    index += valueLen;
  }
  return len;
}

} // namespace

TEST_GROUP(StepperInstrumentationReport)
{
};

TEST(StepperInstrumentationReport, ExpectedEntriesIncludesFinalCompletionInterrupt)
{
  UNSIGNED_LONGS_EQUAL(0u, StepperInstrumentationReport::expectedTotalEntries(0u));
  UNSIGNED_LONGS_EQUAL(3u, StepperInstrumentationReport::expectedTotalEntries(1u));
  UNSIGNED_LONGS_EQUAL(2001u, StepperInstrumentationReport::expectedTotalEntries(1000u));
}

TEST(StepperInstrumentationReport, PassesExactTwoAxisAndZeroAxisMoves)
{
  StepperInstrumentationReport::MoveObservation diagonal{};
  diagonal.deltaXSteps = 10000;
  diagonal.deltaYSteps = -5000;
  diagonal.endpointReached = true;
  diagonal.x = completedSnapshot(10000u, 500u, 100u, 550u);
  diagonal.y = completedSnapshot(5000u, 480u, 90u, 530u);
  CHECK_TRUE(StepperInstrumentationReport::movePasses(diagonal));

  StepperInstrumentationReport::MoveObservation xOnly{};
  xOnly.deltaXSteps = 1000;
  xOnly.endpointReached = true;
  xOnly.x = completedSnapshot(1000u, 300u, 80u, 310u);
  xOnly.y = completedSnapshot(0u, 0u, 0u, 0u);
  CHECK_TRUE(StepperInstrumentationReport::movePasses(xOnly));
}

TEST(StepperInstrumentationReport, RejectsTimeoutEndpointAndSnapshotFailures)
{
  StepperInstrumentationReport::MoveObservation observation{};
  observation.deltaXSteps = 1000;
  observation.endpointReached = true;
  observation.x = completedSnapshot(1000u, 300u, 80u, 310u);
  observation.y = completedSnapshot(0u, 0u, 0u, 0u);

  observation.timedOut = true;
  CHECK_FALSE(StepperInstrumentationReport::movePasses(observation));
  observation.timedOut = false;
  observation.endpointReached = false;
  CHECK_FALSE(StepperInstrumentationReport::movePasses(observation));
  observation.endpointReached = true;
  observation.x.aborted = true;
  CHECK_FALSE(StepperInstrumentationReport::movePasses(observation));
  observation.x.aborted = false;
  observation.x.saturationFlags = StepperIsrInstrumentation::SaturatedPendingStreak;
  CHECK_FALSE(StepperInstrumentationReport::movePasses(observation));
  observation.x.saturationFlags = StepperIsrInstrumentation::SaturatedNone;
  observation.x.totalEntries--;
  CHECK_FALSE(StepperInstrumentationReport::movePasses(observation));
}

TEST(StepperInstrumentationReport, CompactMetricsPreserveAllFieldsInExistingResultFrame)
{
  StepperInstrumentationReport::MoveObservation observation{};
  observation.deltaXSteps = -8416;
  observation.deltaYSteps = -30000;
  observation.effectiveRateHz = 40000u;
  observation.endpointReached = true;
  observation.statusWatchdogAgeMaxMs = 500u;
  observation.statusPeriodMaxMs = 1000u;
  observation.statusFrameCount = 100u;
  observation.x = completedSnapshot(8416u, 99999999u, 99999999u, 99999999u);
  observation.y = completedSnapshot(30000u, 99999998u, 99999998u, 99999998u);
  observation.x.durationCycles = 8589934591ULL;
  observation.x.cycleWraps = 1u;
  observation.x.pendingObservations = 16833u;
  observation.x.maxPendingStreak = 16833u;
  observation.y.pendingObservations = 60001u;
  observation.y.maxPendingStreak = 60001u;

  char metrics[192] = {0};
  const size_t metricsLen =
      StepperInstrumentationReport::buildMetrics(metrics, sizeof(metrics), observation);
  CHECK_TRUE(metricsLen > 0u);
  STRCMP_CONTAINS("dx=-8416;dy=-30000;hz=40000;to=0;ep=1", metrics);
  STRCMP_CONTAINS("du=8589934591;wr=1", metrics);
  STRCMP_CONTAINS("xn=16833;xp=8416;xo=16833", metrics);
  STRCMP_CONTAINS("yn=60001;yp=30000;yo=60001", metrics);
  STRCMP_CONTAINS("am=99999999;cm=99999999;dm=99999999;ps=60001;sf=0", metrics);

  const char name[] = "motion_timing_camera_ratio";
  CHECK_TRUE(metricsLen <=
             (DiagnosticResultEmitter::kResultMetricsFrameBudget - std::strlen(name)));
  uint8_t payload[256] = {0u};
  const size_t payloadLen = DiagnosticResultEmitter::buildResultPayload(
      payload, sizeof(payload), 1u, 2u, 2024u, name, true, metrics, 3u);
  const size_t metricsTag =
      findTag(payload, payloadLen, DiagnosticResultEmitter::kTagMetrics);
  CHECK_TRUE(metricsTag < payloadLen);
  UNSIGNED_LONGS_EQUAL(metricsLen, payload[metricsTag + 1u]);
  MEMCMP_EQUAL(metrics, &payload[metricsTag + 2u], metricsLen);
}

TEST(StepperInstrumentationReport, CompactMetricsFormatMaximumDurationWithoutPrintfLongLong)
{
  StepperInstrumentationReport::MoveObservation observation{};
  observation.x.durationCycles = 18446744073709551615ULL;

  char metrics[192] = {0};
  const size_t metricsLen =
      StepperInstrumentationReport::buildMetrics(metrics, sizeof(metrics), observation);

  CHECK_TRUE(metricsLen > 0u);
  STRCMP_CONTAINS("du=18446744073709551615;wr=0", metrics);
}

TEST(StepperInstrumentationReport, ReturnsZeroInsteadOfEmittingTruncatedMetrics)
{
  StepperInstrumentationReport::MoveObservation observation{};
  char metrics[8] = {'x'};
  UNSIGNED_LONGS_EQUAL(
      0u,
      StepperInstrumentationReport::buildMetrics(metrics, sizeof(metrics), observation));
  STRCMP_EQUAL("", metrics);
}
