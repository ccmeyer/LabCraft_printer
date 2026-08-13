#pragma once

#include <cstdint>

#ifndef LC_TMC2208_MRES
#define LC_TMC2208_MRES 2
#endif

#ifndef LC_TMC2208_DIAGNOSTIC_BUILD
#define LC_TMC2208_DIAGNOSTIC_BUILD 0
#endif

#if (LC_TMC2208_MRES != 2) && (LC_TMC2208_MRES != 3)
#error "LC_TMC2208_MRES must be 2 (1/64) or 3 (1/32)"
#endif

#if (LC_TMC2208_DIAGNOSTIC_BUILD != 0) && (LC_TMC2208_DIAGNOSTIC_BUILD != 1)
#error "LC_TMC2208_DIAGNOSTIC_BUILD must be 0 or 1"
#endif

#if (LC_TMC2208_DIAGNOSTIC_BUILD != 0) && (LC_TMC2208_MRES != 3)
#error "The TMC2208 diagnostic build requires LC_TMC2208_MRES=3"
#endif

namespace TMC2208Configuration {

struct Values {
  uint8_t mres = 2u;
  bool multistepFilter = false;
  bool doubleEdge = true;
  uint32_t gconf = 0u;
  uint32_t chopconf = 0u;
};

inline constexpr Values valuesForMres(uint8_t mres) {
  return Values{
      mres,
      false,
      true,
      0x000000C1u,
      static_cast<uint32_t>(0x30000053u |
                            (static_cast<uint32_t>(mres) << 24u)),
  };
}

inline constexpr Values buildValues() {
  return valuesForMres(static_cast<uint8_t>(LC_TMC2208_MRES));
}

inline constexpr bool isMres3DiagnosticBuild() {
  return LC_TMC2208_DIAGNOSTIC_BUILD != 0 && LC_TMC2208_MRES == 3;
}

inline constexpr bool preservesMres2PhysicalRate(uint32_t rateHz) {
  return LC_TMC2208_MRES == 3 && rateHz == 20000u;
}

inline constexpr bool preservesMres2PhysicalAcceleration(
    uint32_t accelerationStepsPerSec2) {
  return LC_TMC2208_MRES == 3 && accelerationStepsPerSec2 == 70000u;
}

}  // namespace TMC2208Configuration
