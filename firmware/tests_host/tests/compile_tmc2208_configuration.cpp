#include "TMC2208Configuration.h"

static_assert(TMC2208Configuration::buildValues().mres == 3u,
              "diagnostic build must select MRES=3");
static_assert(TMC2208Configuration::isMres3DiagnosticBuild(),
              "diagnostic marker must be active");
static_assert(TMC2208Configuration::buildValues().gconf == 0x000000C1u,
              "multistep filter must be disabled");
static_assert(TMC2208Configuration::buildValues().chopconf == 0x33000053u,
              "MRES and DEDGE bits must match the diagnostic register");
static_assert(TMC2208Configuration::preservesMres2PhysicalRate(20000u),
              "20 kHz must preserve the MRES2 physical rate");
static_assert(
    TMC2208Configuration::preservesMres2PhysicalAcceleration(70000u),
    "70k microsteps/s2 must preserve the MRES2 physical acceleration");

int compileTmc2208Mres3DiagnosticConfiguration() {
  return 0;
}
