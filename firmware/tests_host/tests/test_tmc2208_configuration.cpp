#include "TMC2208Configuration.h"
#include "CppUTest/TestHarness.h"

TEST_GROUP(TMC2208Configuration) {};

TEST(TMC2208Configuration, ProductionValuesDisableIncompatibleFilter) {
  const auto values = TMC2208Configuration::valuesForMres(2u);
  UNSIGNED_LONGS_EQUAL(2u, values.mres);
  CHECK_FALSE(values.multistepFilter);
  CHECK_TRUE(values.doubleEdge);
  UNSIGNED_LONGS_EQUAL(0x000000C1u, values.gconf);
  UNSIGNED_LONGS_EQUAL(0x32000053u, values.chopconf);
}

TEST(TMC2208Configuration, DiagnosticValuesSelectOneThirtySecondMicrosteps) {
  const auto values = TMC2208Configuration::valuesForMres(3u);
  UNSIGNED_LONGS_EQUAL(3u, values.mres);
  CHECK_FALSE(values.multistepFilter);
  CHECK_TRUE(values.doubleEdge);
  UNSIGNED_LONGS_EQUAL(0x000000C1u, values.gconf);
  UNSIGNED_LONGS_EQUAL(0x33000053u, values.chopconf);
}

TEST(TMC2208Configuration, DefaultProductionBuildUsesMres3) {
  const auto values = TMC2208Configuration::buildValues();
  UNSIGNED_LONGS_EQUAL(3u, values.mres);
  CHECK_FALSE(TMC2208Configuration::isMres3DiagnosticBuild());
  CHECK_TRUE(TMC2208Configuration::isProductionMres3Build());
  CHECK_TRUE(TMC2208Configuration::preservesMres2PhysicalRate(40000u));
  CHECK_TRUE(
      TMC2208Configuration::preservesMres2PhysicalAcceleration(140000u));
}
