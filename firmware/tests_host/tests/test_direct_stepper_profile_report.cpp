#include "CppUTest/TestHarness.h"
#include "DirectStepperProfileReport.h"

#include <cstring>
#include <limits>

namespace {

DirectStepperProfileReport::MoveObservation validObservation(bool instrumented) {
  DirectStepperProfileReport::MoveObservation observation{};
  observation.axis = 0u;
  observation.logicalDistance = 14000u;
  observation.effectiveRateHz = 40000u;
  observation.expectedNativePulses = 7000u;
  observation.endpointReached = true;
  observation.instrumentationRequired = instrumented;
  observation.profile.selected = true;
  observation.profile.completed = true;
  observation.profile.totalToggles = 14000u;
  observation.profile.accelIntervals = 5716u;
  observation.profile.accelConsumed = 5716u;
  observation.profile.decelIntervals = 5716u;
  observation.profile.decelConsumed = 5715u;
  if (instrumented) {
    observation.instrumentation.valid = true;
    observation.instrumentation.totalEntries = 14001u;
    observation.instrumentation.completedPulses = 7000u;
  }
  return observation;
}

}  // namespace

TEST_GROUP(DirectStepperProfileReport) {};

TEST(DirectStepperProfileReport, PassesCompleteInstrumentedAndUninstrumentedMoves) {
  CHECK_TRUE(DirectStepperProfileReport::movePasses(validObservation(true)));
  CHECK_TRUE(DirectStepperProfileReport::movePasses(validObservation(false)));
}

TEST(DirectStepperProfileReport, RejectsProfileAndTimingEvidenceFailures) {
  auto observation = validObservation(true);
  observation.profile.runtimeFailed = true;
  CHECK_FALSE(DirectStepperProfileReport::movePasses(observation));

  observation = validObservation(true);
  observation.profile.decelConsumed = 5716u;
  CHECK_FALSE(DirectStepperProfileReport::movePasses(observation));

  observation = validObservation(true);
  observation.instrumentation.pendingObservations = 1u;
  CHECK_FALSE(DirectStepperProfileReport::movePasses(observation));

  observation = validObservation(true);
  observation.instrumentation.completedPulses = 6999u;
  CHECK_FALSE(DirectStepperProfileReport::movePasses(observation));

  observation = validObservation(false);
  observation.expectedNativePulses =
      (std::numeric_limits<uint32_t>::max() / 2u) + 1u;
  CHECK_FALSE(DirectStepperProfileReport::movePasses(observation));
}

TEST(DirectStepperProfileReport, MetricsFitGenericResultFrameBudget) {
  auto observation = validObservation(true);
  observation.statusWatchdogAgeMaxMs = 123u;
  observation.statusPeriodMaxMs = 60u;
  observation.statusFrameCount = 42u;
  observation.instrumentation.phaseMaxCycles[0] = 999u;
  char metrics[208] = {0};
  const size_t length = DirectStepperProfileReport::buildMetrics(
      metrics, sizeof(metrics), observation);
  CHECK_TRUE(length > 0u);
  CHECK_TRUE(length < sizeof(metrics));
  STRCMP_CONTAINS("nm=1;co=1;pf=0;rf=0;ab=0", metrics);
  STRCMP_CONTAINS("ai=5716;ac=5716;di=5716;dc=5715", metrics);
}

TEST(DirectStepperProfileReport, RejectsTruncatedMetricBuffer) {
  char metrics[32] = {0};
  UNSIGNED_LONGS_EQUAL(
      0u,
      DirectStepperProfileReport::buildMetrics(
          metrics, sizeof(metrics), validObservation(true)));
  STRCMP_EQUAL("", metrics);
}
