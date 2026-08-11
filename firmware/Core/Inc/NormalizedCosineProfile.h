#ifndef INC_NORMALIZEDCOSINEPROFILE_H_
#define INC_NORMALIZEDCOSINEPROFILE_H_

#include <cstdint>

namespace NormalizedCosineProfile {

constexpr uint32_t kLutIntervals = 256u;
constexpr uint32_t kEaseFractionBits = 20u;
constexpr uint32_t kEaseOne = 1u << kEaseFractionBits;

enum class PrepareStatus : uint8_t {
  Ready = 0,
  Immediate = 1,
  InvalidBounds = 2,
};

struct RampSpec {
  uint32_t fromArr = 0u;
  uint32_t toArr = 0u;
  uint32_t minArr = 0u;
  uint32_t maxArr = 0u;
  uint32_t intervalCount = 0u;
};

struct RampCursor {
  uint32_t fromArr = 0u;
  uint32_t toArr = 0u;
  uint32_t currentSampleArr = 0u;
  uint32_t rangeArr = 0u;
  uint32_t intervalCount = 0u;
  uint32_t intervalIndex = 0u;
  uint32_t phaseQ32 = 0u;
  uint32_t phaseIncrementQ32 = 0u;
  uint32_t phaseRemainderIncrement = 0u;
  uint32_t phaseRemainder = 0u;
  bool descending = false;
  PrepareStatus status = PrepareStatus::InvalidBounds;
};

PrepareStatus prepare(const RampSpec& spec, RampCursor& cursor);
#if defined(__GNUC__) && !defined(UNIT_TEST)
__attribute__((always_inline))
#endif
inline uint32_t currentArr(const RampCursor& cursor) {
  return cursor.currentSampleArr;
}
bool advance(RampCursor& cursor);
bool atEndpoint(const RampCursor& cursor);

}  // namespace NormalizedCosineProfile

#endif /* INC_NORMALIZEDCOSINEPROFILE_H_ */
