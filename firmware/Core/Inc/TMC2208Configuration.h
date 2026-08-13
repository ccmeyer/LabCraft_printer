#pragma once

#include <cstdint>

namespace TMC2208Configuration {

static constexpr uint8_t kMres = 3u;

struct Values {
  uint8_t mres = 2u;
  bool multistepFilter = false;
  bool doubleEdge = true;
  uint32_t gconf = 0u;
  uint32_t chopconf = 0u;
};

inline constexpr Values buildValues() {
  return Values{
      kMres,
      false,
      true,
      0x000000C1u,
      static_cast<uint32_t>(0x30000053u |
                            (static_cast<uint32_t>(kMres) << 24u)),
  };
}

inline constexpr bool preservesMres2PhysicalRate(uint32_t rateHz) {
  return kMres == 3u && rateHz == 40000u;
}

inline constexpr bool preservesMres2PhysicalAcceleration(
    uint32_t accelerationStepsPerSec2) {
  return kMres == 3u && accelerationStepsPerSec2 == 140000u;
}

}  // namespace TMC2208Configuration
