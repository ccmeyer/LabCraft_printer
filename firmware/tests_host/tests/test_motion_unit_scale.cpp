#include "MotionUnitScale.h"
#include "CppUTest/TestHarness.h"

#include <cstdint>
#include <limits>

TEST_GROUP(MotionUnitScale) {};

TEST(MotionUnitScale, Mres2IsIdentityAndMres3HalvesNativeCommands) {
  UNSIGNED_LONGS_EQUAL(
      1u, MotionUnitScale::logicalUnitsPerNativeStepForMres(2u));
  UNSIGNED_LONGS_EQUAL(
      2u, MotionUnitScale::logicalUnitsPerNativeStepForMres(3u));
  UNSIGNED_LONGS_EQUAL(20000u,
      MotionUnitScale::toNativeRate(40000u, 2u));
  UNSIGNED_LONGS_EQUAL(70000u,
      MotionUnitScale::toNativeAcceleration(140000u, 2u));
  UNSIGNED_LONGS_EQUAL(10000u,
      MotionUnitScale::toNativeStepCycles(20000u, 2u));
  UNSIGNED_LONGS_EQUAL(20000u,
      MotionUnitScale::toLogicalMagnitude(10000u, 2u));
}

TEST(MotionUnitScale, OddPositiveAndNegativeDisplacementsTruncateTowardZero) {
  const auto positive = MotionUnitScale::quantizeDisplacement(100, 5, 2u);
  CHECK_TRUE(positive.valid);
  CHECK_TRUE(positive.positive);
  UNSIGNED_LONGS_EQUAL(2u, positive.nativeStepCycles);
  UNSIGNED_LONGS_EQUAL(4u, positive.logicalMagnitude);
  LONGS_EQUAL(104, positive.target);

  const auto negative = MotionUnitScale::quantizeDisplacement(100, -5, 2u);
  CHECK_TRUE(negative.valid);
  CHECK_FALSE(negative.positive);
  UNSIGNED_LONGS_EQUAL(2u, negative.nativeStepCycles);
  UNSIGNED_LONGS_EQUAL(4u, negative.logicalMagnitude);
  LONGS_EQUAL(96, negative.target);
}

TEST(MotionUnitScale, AbsoluteTargetCanonicalizationUsesCurrentPosition) {
  int32_t target = 0;
  CHECK_TRUE(MotionUnitScale::canonicalizeAbsoluteTarget(10, 9, target));
  LONGS_EQUAL(10, target);
  CHECK_TRUE(MotionUnitScale::canonicalizeAbsoluteTarget(0, 9, target));
  LONGS_EQUAL(8, target);
  CHECK_TRUE(MotionUnitScale::canonicalizeAbsoluteTarget(10, 3, target));
  LONGS_EQUAL(4, target);
}

TEST(MotionUnitScale, ZeroAndBoundaryMovesRemainValid) {
  UNSIGNED_LONGS_EQUAL(0u, MotionUnitScale::toLogicalMagnitude(123u, 0u));
  UNSIGNED_LONGS_EQUAL(
      std::numeric_limits<uint32_t>::max(),
      MotionUnitScale::toLogicalMagnitude(
          std::numeric_limits<uint32_t>::max(), 2u));

  const auto zero = MotionUnitScale::quantizeDisplacement(7, 0, 2u);
  CHECK_TRUE(zero.valid);
  UNSIGNED_LONGS_EQUAL(0u, zero.nativeStepCycles);
  LONGS_EQUAL(7, zero.target);

  const auto high = MotionUnitScale::quantizeDisplacement(
      std::numeric_limits<int32_t>::min(),
      static_cast<int64_t>(std::numeric_limits<uint32_t>::max()),
      2u);
  CHECK_TRUE(high.valid);
  LONGS_EQUAL(2147483646, high.target);
}

TEST(MotionUnitScale, ActiveProductionScalePreservesLegacyExternalUnits) {
  UNSIGNED_LONGS_EQUAL(2u, MotionUnitScale::logicalUnitsPerNativeStep());
  UNSIGNED_LONGS_EQUAL(20000u, MotionUnitScale::toNativeRate(40000u));
  UNSIGNED_LONGS_EQUAL(70000u,
      MotionUnitScale::toNativeAcceleration(140000u));
}
