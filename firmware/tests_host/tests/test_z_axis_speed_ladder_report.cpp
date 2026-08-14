#include "CppUTest/TestHarness.h"
#include "ZAxisSpeedLadderReport.h"

#include <cstring>

using ZAxisSpeedLadderReport::MoveObservation;
using ZAxisSpeedLadderReport::TierObservation;

namespace {

MoveObservation passingMove(uint32_t logicalDistance,
                            uint32_t nativePulses,
                            uint32_t callbacks)
{
  MoveObservation move{};
  move.logicalDistance = logicalDistance;
  move.expectedNativePulses = nativePulses;
  move.endpointReached = true;
  move.profile.selected = true;
  move.profile.completed = true;
  move.profile.totalToggles = nativePulses * 2u;
  move.profile.accelIntervals = 10u;
  move.profile.accelConsumed = 10u;
  move.profile.decelIntervals = 10u;
  move.profile.decelConsumed = 9u;
  move.timing.valid = true;
  move.timing.completedPulses = nativePulses;
  move.timing.totalEntries = callbacks;
  move.timing.fullIrqSamples = callbacks;
  move.timing.deadlineSamples = callbacks - 1u;
  move.timing.minimumDeadlineSlackCycles = 1000u;
  move.timing.phaseMaxCycles[static_cast<uint8_t>(
      StepperIsrInstrumentation::Phase::Cruise)] = 500u;
  move.timing.fullIrqActiveMaxCycles = 700u;
  move.timing.fullIrqTerminalMaxCycles = 900u;
  return move;
}

TierObservation passingTier()
{
  TierObservation tier{};
  tier.rateHz = 50000u;
  tier.accelerationStepsPerSec2 = 100000u;
  for (uint32_t index = 0u; index < 6u; ++index) {
    ZAxisSpeedLadderReport::accumulateMove(
        tier, passingMove(79900u, 39950u, 79901u));
  }
  tier.completedRepetitions = 3u;
  tier.homeSpanSteps = 4u;
  tier.homeDriftSteps = 5u;
  tier.returnErrorSteps = 2u;
  tier.statusEvidenceValid = true;
  tier.statusPeriodMaxMs = 70u;
  tier.statusWatchdogAgeMaxMs = 60u;
  tier.statusAlternationErrors = 0u;
  return tier;
}

}  // namespace

TEST_GROUP(ZAxisSpeedLadderReport) {};

TEST(ZAxisSpeedLadderReport, AcceptsExactCompleteTier)
{
  const TierObservation tier = passingTier();
  CHECK_TRUE(ZAxisSpeedLadderReport::tierPasses(
      tier, 50000u, 100000u, 479400u, 239700u, 479406u, 479400u));
}

TEST(ZAxisSpeedLadderReport, RejectsWrongRateOrAccelerationEvidence)
{
  TierObservation tier = passingTier();
  CHECK_FALSE(ZAxisSpeedLadderReport::tierPasses(
      tier, 40000u, 100000u, 479400u, 239700u, 479406u, 479400u));
  CHECK_FALSE(ZAxisSpeedLadderReport::tierPasses(
      tier, 50000u, 140000u, 479400u, 239700u, 479406u, 479400u));
}

TEST(ZAxisSpeedLadderReport, RejectsTimingCoverageDeadlineAndProfileFailures)
{
  TierObservation tier = passingTier();
  tier.fullIrqSamples--;
  CHECK_FALSE(ZAxisSpeedLadderReport::tierPasses(
      tier, 50000u, 100000u, 479400u, 239700u, 479406u, 479400u));
  tier = passingTier();
  tier.deadlineMisses = 1u;
  CHECK_FALSE(ZAxisSpeedLadderReport::tierPasses(
      tier, 50000u, 100000u, 479400u, 239700u, 479406u, 479400u));
  tier = passingTier();
  tier.profileFailureCount = 1u;
  CHECK_FALSE(ZAxisSpeedLadderReport::tierPasses(
      tier, 50000u, 100000u, 479400u, 239700u, 479406u, 479400u));
}

TEST(ZAxisSpeedLadderReport, SeparatesBodyFullVectorAndSlackLimits)
{
  TierObservation tier = passingTier();
  tier.activeBodyMaxCycles = 2250u;
  tier.activeFullIrqMaxCycles = 2550u;
  tier.minimumDeadlineSlackCycles = 900u;
  CHECK_TRUE(ZAxisSpeedLadderReport::tierPasses(
      tier, 50000u, 100000u, 479400u, 239700u, 479406u, 479400u));

  tier = passingTier();
  tier.activeBodyMaxCycles = 2251u;
  CHECK_FALSE(ZAxisSpeedLadderReport::tierPasses(
      tier, 50000u, 100000u, 479400u, 239700u, 479406u, 479400u));

  tier = passingTier();
  tier.activeFullIrqMaxCycles = 2551u;
  CHECK_FALSE(ZAxisSpeedLadderReport::tierPasses(
      tier, 50000u, 100000u, 479400u, 239700u, 479406u, 479400u));

  tier = passingTier();
  tier.minimumDeadlineSlackCycles = 899u;
  CHECK_FALSE(ZAxisSpeedLadderReport::tierPasses(
      tier, 50000u, 100000u, 479400u, 239700u, 479406u, 479400u));
}

TEST(ZAxisSpeedLadderReport, AcceptsAtMostOneDwtWrapPerMeasuredMove)
{
  TierObservation tier = passingTier();
  tier.cycleWrapCount = ZAxisSpeedLadderReport::kMeasuredMovesPerTier;
  CHECK_TRUE(ZAxisSpeedLadderReport::tierPasses(
      tier, 50000u, 100000u, 479400u, 239700u, 479406u, 479400u));
  ++tier.cycleWrapCount;
  CHECK_FALSE(ZAxisSpeedLadderReport::tierPasses(
      tier, 50000u, 100000u, 479400u, 239700u, 479406u, 479400u));
}

TEST(ZAxisSpeedLadderReport, RejectsHomeStatusLimitAndSaturationFailures)
{
  TierObservation tier = passingTier();
  tier.homeDriftSteps = 26u;
  CHECK_FALSE(ZAxisSpeedLadderReport::tierPasses(
      tier, 50000u, 100000u, 479400u, 239700u, 479406u, 479400u));
  tier = passingTier();
  tier.statusPeriodMaxMs = 126u;
  CHECK_FALSE(ZAxisSpeedLadderReport::tierPasses(
      tier, 50000u, 100000u, 479400u, 239700u, 479406u, 479400u));
  tier = passingTier();
  tier.limitConfirmations = 1u;
  CHECK_FALSE(ZAxisSpeedLadderReport::tierPasses(
      tier, 50000u, 100000u, 479400u, 239700u, 479406u, 479400u));
  tier = passingTier();
  tier.saturationFlags = 1u;
  CHECK_FALSE(ZAxisSpeedLadderReport::tierPasses(
      tier, 50000u, 100000u, 479400u, 239700u, 479406u, 479400u));
}

TEST(ZAxisSpeedLadderReport, MetricsFitTheGenericResultBudget)
{
  TierObservation tier = passingTier();
  char metrics[224] = {};
  const size_t length = ZAxisSpeedLadderReport::buildMetrics(
      metrics, sizeof(metrics), tier);
  CHECK(length > 0u);
  CHECK(length <= (230u - std::strlen("z_speed_ladder_40k_a100k")));
  STRCMP_CONTAINS("hz=50000;ac=100000;rep=3", metrics);
  STRCMP_CONTAINS("cb=479406;s=479406;mi=0", metrics);
  STRCMP_CONTAINS("cw=0", metrics);
}
