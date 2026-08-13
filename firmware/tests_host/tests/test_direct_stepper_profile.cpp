#include "CppUTest/TestHarness.h"
#include "DirectStepperProfile.h"

namespace {

DirectStepperProfile::State preparedState(uint32_t total,
                                          uint32_t accel,
                                          uint32_t decel) {
  DirectStepperProfile::State state{};
  CHECK_TRUE(DirectStepperProfile::prepare(
      state, total, accel, decel, 1000u, 200u, 100u, 2000u));
  return state;
}

}  // namespace

TEST_GROUP(DirectStepperProfile) {};

TEST(DirectStepperProfile, RejectsInvalidBoundsAndToggleCounts) {
  DirectStepperProfile::State state{};
  CHECK_FALSE(DirectStepperProfile::prepare(
      state, 0u, 0u, 0u, 1000u, 200u, 100u, 2000u));
  CHECK_TRUE(DirectStepperProfile::snapshot(state).prepareFailed);

  CHECK_FALSE(DirectStepperProfile::prepare(
      state, 10u, 11u, 2u, 1000u, 200u, 100u, 2000u));
  CHECK_FALSE(DirectStepperProfile::prepare(
      state, 10u, 2u, 2u, 99u, 200u, 100u, 2000u));
}

TEST(DirectStepperProfile, PreservesLegacyAccelerationCruiseAndDecelBoundaries) {
  auto state = preparedState(20u, 4u, 4u);
  DirectStepperProfile::Sample sample{};
  uint32_t priorAccelArr = 1001u;
  uint32_t priorDecelArr = 0u;

  for (uint32_t done = 0u; done < 20u; ++done) {
    CHECK_TRUE(DirectStepperProfile::nextSample(
        state, done, 20u - done, sample));
    if (done < 4u) {
      CHECK_EQUAL(static_cast<int>(DirectStepperProfile::Phase::Acceleration),
                  static_cast<int>(sample.phase));
      CHECK_TRUE(sample.arr <= priorAccelArr);
      priorAccelArr = sample.arr;
    } else if (done > 16u) {
      CHECK_EQUAL(static_cast<int>(DirectStepperProfile::Phase::Deceleration),
                  static_cast<int>(sample.phase));
      CHECK_TRUE(sample.arr >= priorDecelArr);
      priorDecelArr = sample.arr;
    } else {
      CHECK_EQUAL(static_cast<int>(DirectStepperProfile::Phase::Cruise),
                  static_cast<int>(sample.phase));
      UNSIGNED_LONGS_EQUAL(200u, sample.arr);
    }
  }

  CHECK_TRUE(DirectStepperProfile::finish(state));
  const auto snapshot = DirectStepperProfile::snapshot(state);
  CHECK_TRUE(snapshot.selected);
  CHECK_TRUE(snapshot.completed);
  UNSIGNED_LONGS_EQUAL(4u, snapshot.accelConsumed);
  UNSIGNED_LONGS_EQUAL(3u, snapshot.decelConsumed);
}

TEST(DirectStepperProfile, ShortTriangularMoveKeepsAccelerationPrecedence) {
  auto state = preparedState(10u, 5u, 5u);
  DirectStepperProfile::Sample sample{};
  for (uint32_t done = 0u; done < 10u; ++done) {
    CHECK_TRUE(DirectStepperProfile::nextSample(
        state, done, 10u - done, sample));
    if (done < 5u) {
      CHECK_EQUAL(static_cast<int>(DirectStepperProfile::Phase::Acceleration),
                  static_cast<int>(sample.phase));
    } else if (done == 5u) {
      CHECK_EQUAL(static_cast<int>(DirectStepperProfile::Phase::Cruise),
                  static_cast<int>(sample.phase));
    } else {
      CHECK_EQUAL(static_cast<int>(DirectStepperProfile::Phase::Deceleration),
                  static_cast<int>(sample.phase));
    }
  }
  CHECK_TRUE(DirectStepperProfile::finish(state));
  UNSIGNED_LONGS_EQUAL(4u, DirectStepperProfile::snapshot(state).decelConsumed);
}

TEST(DirectStepperProfile, DetectsCounterMismatchAndAbort) {
  DirectStepperProfile::Sample sample{};
  auto mismatch = preparedState(10u, 2u, 2u);
  CHECK_FALSE(DirectStepperProfile::nextSample(mismatch, 1u, 10u, sample));
  CHECK_TRUE(DirectStepperProfile::snapshot(mismatch).runtimeFailed);

  auto aborted = preparedState(10u, 2u, 2u);
  DirectStepperProfile::abort(aborted);
  const auto abortedSnapshot = DirectStepperProfile::snapshot(aborted);
  CHECK_TRUE(abortedSnapshot.aborted);
  CHECK_FALSE(abortedSnapshot.active);
  CHECK_FALSE(DirectStepperProfile::finish(aborted));
}

TEST(DirectStepperProfile, FinishRejectsIncompleteCursorCoverage) {
  auto state = preparedState(10u, 2u, 2u);
  CHECK_FALSE(DirectStepperProfile::finish(state));
  CHECK_TRUE(DirectStepperProfile::snapshot(state).runtimeFailed);
}

TEST(DirectStepperProfile, ExpectedDecelSamplesIsWrapSafeAndMatchesStrictBoundary) {
  UNSIGNED_LONGS_EQUAL(3u,
      DirectStepperProfile::expectedDecelSamples(20u, 4u, 4u));
  UNSIGNED_LONGS_EQUAL(4u,
      DirectStepperProfile::expectedDecelSamples(10u, 5u, 5u));
  UNSIGNED_LONGS_EQUAL(0u,
      DirectStepperProfile::expectedDecelSamples(10u, 11u, 2u));
}
