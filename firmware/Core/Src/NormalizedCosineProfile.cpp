#include "NormalizedCosineProfile.h"

#include <cstddef>

namespace NormalizedCosineProfile {

namespace {

#if defined(__GNUC__) && !defined(UNIT_TEST)
#define LC_PROFILE_ISR_OPTIMIZED __attribute__((optimize("O2"), hot))
#define LC_PROFILE_FORCE_INLINE inline __attribute__((always_inline))
#else
#define LC_PROFILE_ISR_OPTIMIZED
#define LC_PROFILE_FORCE_INLINE inline
#endif

// Period-domain transform of a cosine applied to velocity squared. The table
// assumes the coordinated planner's nominal 5:1 start/target period ratio:
//
//   E(u) = (1 - cos(pi*u)) / 2
//   P(u) / Ptarget = 5 / sqrt(1 + 24*E(u))
//
// Interpolating this table into ARR keeps the ISR fixed-point and bounded,
// while avoiding the 3.17x acceleration amplification caused by applying the
// cosine directly to ARR. Ascending (deceleration) ramps use the time-reversed
// table so acceleration and deceleration remain reciprocal.
constexpr uint32_t kVelocitySquaredCosinePeriodEaseQ20[
    kLutIntervals + 1u] = {
    0u, 592u, 2362u, 5297u, 9371u, 14554u, 20803u, 28071u,
    36303u, 45440u, 55419u, 66173u, 77634u, 89732u, 102397u, 115563u,
    129161u, 143127u, 157399u, 171919u, 186632u, 201486u, 216433u, 231429u,
    246435u, 261414u, 276333u, 291163u, 305878u, 320455u, 334874u, 349117u,
    363171u, 377021u, 390658u, 404073u, 417259u, 430210u, 442923u, 455396u,
    467625u, 479611u, 491353u, 502853u, 514111u, 525130u, 535913u, 546462u,
    556781u, 566872u, 576741u, 586390u, 595824u, 605048u, 614065u, 622880u,
    631497u, 639921u, 648156u, 656207u, 664078u, 671774u, 679298u, 686655u,
    693849u, 700884u, 707764u, 714494u, 721076u, 727516u, 733815u, 739979u,
    746010u, 751913u, 757689u, 763344u, 768878u, 774297u, 779603u, 784798u,
    789885u, 794868u, 799749u, 804531u, 809215u, 813805u, 818303u, 822711u,
    827031u, 831266u, 835418u, 839488u, 843479u, 847393u, 851231u, 854996u,
    858688u, 862311u, 865865u, 869352u, 872774u, 876132u, 879427u, 882662u,
    885837u, 888954u, 892014u, 895019u, 897969u, 900866u, 903711u, 906505u,
    909250u, 911946u, 914594u, 917196u, 919752u, 922263u, 924731u, 927156u,
    929539u, 931881u, 934182u, 936445u, 938668u, 940854u, 943003u, 945115u,
    947192u, 949233u, 951241u, 953214u, 955155u, 957063u, 958939u, 960785u,
    962599u, 964384u, 966139u, 967865u, 969562u, 971232u, 972874u, 974488u,
    976077u, 977639u, 979176u, 980687u, 982174u, 983636u, 985075u, 986489u,
    987881u, 989249u, 990596u, 991920u, 993222u, 994503u, 995763u, 997002u,
    998220u, 999418u, 1000597u, 1001756u, 1002896u, 1004016u, 1005118u,
    1006202u, 1007267u, 1008314u, 1009344u, 1010356u, 1011350u, 1012328u,
    1013289u, 1014234u, 1015162u, 1016074u, 1016970u, 1017851u, 1018715u,
    1019565u, 1020399u, 1021218u, 1022023u, 1022813u, 1023588u, 1024349u,
    1025096u, 1025829u, 1026549u, 1027254u, 1027946u, 1028625u, 1029290u,
    1029942u, 1030581u, 1031208u, 1031821u, 1032422u, 1033011u, 1033587u,
    1034151u, 1034703u, 1035242u, 1035770u, 1036286u, 1036790u, 1037283u,
    1037764u, 1038234u, 1038692u, 1039139u, 1039575u, 1039999u, 1040413u,
    1040816u, 1041207u, 1041588u, 1041959u, 1042318u, 1042667u, 1043006u,
    1043334u, 1043652u, 1043959u, 1044256u, 1044542u, 1044819u, 1045085u,
    1045342u, 1045588u, 1045824u, 1046050u, 1046267u, 1046473u, 1046670u,
    1046857u, 1047034u, 1047201u, 1047359u, 1047507u, 1047645u, 1047773u,
    1047892u, 1048002u, 1048102u, 1048192u, 1048273u, 1048344u, 1048405u,
    1048458u, 1048500u, 1048533u, 1048557u, 1048571u, 1048576u,
};

static_assert(sizeof(kVelocitySquaredCosinePeriodEaseQ20) == 1028u,
              "The normalized cosine LUT must occupy 1,028 bytes");

uint32_t clampArr(uint32_t value, uint32_t minimum, uint32_t maximum) {
  if (value < minimum) return minimum;
  if (value > maximum) return maximum;
  return value;
}

LC_PROFILE_FORCE_INLINE uint32_t forwardEaseQ20(uint32_t phaseQ32) {
  const uint32_t index = phaseQ32 >> 24u;
  const uint32_t fractionQ16 = (phaseQ32 >> 8u) & 0xFFFFu;
  const uint32_t lower = kVelocitySquaredCosinePeriodEaseQ20[index];
  const uint32_t delta =
      kVelocitySquaredCosinePeriodEaseQ20[index + 1u] - lower;
  return lower + ((delta * fractionQ16) >> 16u);
}

LC_PROFILE_FORCE_INLINE uint32_t easeQ20(uint32_t phaseQ32,
                                         bool descending) {
  if (descending) return forwardEaseQ20(phaseQ32);
  const uint32_t reversePhaseQ32 = 0u - phaseQ32;
  return kEaseOne - forwardEaseQ20(reversePhaseQ32);
}

}  // namespace

PrepareStatus prepare(const RampSpec& spec, RampCursor& cursor) {
  cursor = RampCursor{};
  if (spec.minArr > spec.maxArr) {
    return cursor.status;
  }

  cursor.fromArr = clampArr(spec.fromArr, spec.minArr, spec.maxArr);
  cursor.toArr = clampArr(spec.toArr, spec.minArr, spec.maxArr);
  cursor.currentSampleArr = cursor.fromArr;
  cursor.descending = cursor.fromArr > cursor.toArr;
  cursor.rangeArr = cursor.descending
      ? (cursor.fromArr - cursor.toArr)
      : (cursor.toArr - cursor.fromArr);
  cursor.intervalCount = spec.intervalCount;

  if (spec.intervalCount == 0u) {
    cursor.fromArr = cursor.toArr;
    cursor.currentSampleArr = cursor.toArr;
    cursor.status = PrepareStatus::Immediate;
    return cursor.status;
  }

  if (spec.intervalCount > 1u) {
    constexpr uint64_t kPhaseRange = uint64_t{1u} << 32u;
    cursor.phaseIncrementQ32 = static_cast<uint32_t>(
        kPhaseRange / spec.intervalCount);
    cursor.phaseRemainderIncrement = static_cast<uint32_t>(
        kPhaseRange % spec.intervalCount);
  }
  cursor.status = PrepareStatus::Ready;
  return cursor.status;
}

LC_PROFILE_ISR_OPTIMIZED bool advance(RampCursor& cursor) {
  if (cursor.status == PrepareStatus::InvalidBounds ||
      cursor.status == PrepareStatus::Immediate ||
      cursor.intervalIndex >= cursor.intervalCount) {
    return false;
  }

  ++cursor.intervalIndex;
  if (cursor.intervalIndex >= cursor.intervalCount) {
    cursor.currentSampleArr = cursor.toArr;
    return true;
  }

  cursor.phaseQ32 += cursor.phaseIncrementQ32;
  const uint64_t remainder = static_cast<uint64_t>(cursor.phaseRemainder) +
                             cursor.phaseRemainderIncrement;
  if (remainder >= cursor.intervalCount) {
    cursor.phaseRemainder = static_cast<uint32_t>(
        remainder - cursor.intervalCount);
    ++cursor.phaseQ32;
  } else {
    cursor.phaseRemainder = static_cast<uint32_t>(remainder);
  }

  const uint32_t ease = easeQ20(cursor.phaseQ32, cursor.descending);
  const uint32_t offset = static_cast<uint32_t>(
      (static_cast<uint64_t>(cursor.rangeArr) * ease) >> kEaseFractionBits);
  cursor.currentSampleArr = cursor.descending
      ? (cursor.fromArr - offset)
      : (cursor.fromArr + offset);
  return true;
}

LC_PROFILE_ISR_OPTIMIZED bool atEndpoint(const RampCursor& cursor) {
  return cursor.status == PrepareStatus::Immediate ||
         (cursor.status == PrepareStatus::Ready &&
          cursor.intervalIndex >= cursor.intervalCount);
}

#undef LC_PROFILE_FORCE_INLINE
#undef LC_PROFILE_ISR_OPTIMIZED

}  // namespace NormalizedCosineProfile
