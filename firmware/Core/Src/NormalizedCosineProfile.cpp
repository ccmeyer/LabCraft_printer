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

constexpr uint32_t kCosineEaseQ20[kLutIntervals + 1u] = {
    0u, 39u, 158u, 355u, 632u, 987u, 1421u, 1933u,
    2525u, 3195u, 3943u, 4770u, 5675u, 6658u, 7719u, 8858u,
    10074u, 11368u, 12739u, 14187u, 15712u, 17314u, 18992u, 20746u,
    22576u, 24481u, 26462u, 28517u, 30648u, 32852u, 35131u, 37483u,
    39909u, 42408u, 44979u, 47622u, 50337u, 53124u, 55981u, 58909u,
    61907u, 64975u, 68112u, 71317u, 74591u, 77933u, 81341u, 84817u,
    88358u, 91966u, 95638u, 99375u, 103176u, 107040u, 110967u, 114957u,
    119008u, 123120u, 127292u, 131525u, 135816u, 140166u, 144574u, 149039u,
    153560u, 158138u, 162770u, 167457u, 172198u, 176991u, 181837u, 186735u,
    191683u, 196682u, 201729u, 206826u, 211970u, 217161u, 222399u, 227682u,
    233009u, 238381u, 243795u, 249252u, 254750u, 260289u, 265867u, 271485u,
    277140u, 282833u, 288562u, 294327u, 300126u, 305959u, 311825u, 317723u,
    323652u, 329611u, 335599u, 341616u, 347661u, 353732u, 359828u, 365950u,
    372095u, 378263u, 384454u, 390665u, 396896u, 403147u, 409416u, 415702u,
    422004u, 428322u, 434655u, 441001u, 447359u, 453729u, 460110u, 466500u,
    472899u, 479305u, 485719u, 492138u, 498562u, 504990u, 511421u, 517854u,
    524288u, 530722u, 537155u, 543586u, 550014u, 556438u, 562857u, 569271u,
    575677u, 582076u, 588466u, 594847u, 601217u, 607575u, 613921u, 620254u,
    626572u, 632874u, 639160u, 645429u, 651680u, 657911u, 664122u, 670313u,
    676481u, 682626u, 688748u, 694844u, 700915u, 706960u, 712977u, 718965u,
    724924u, 730853u, 736751u, 742617u, 748450u, 754249u, 760014u, 765743u,
    771436u, 777091u, 782709u, 788287u, 793826u, 799324u, 804781u, 810195u,
    815567u, 820894u, 826177u, 831415u, 836606u, 841750u, 846847u, 851894u,
    856893u, 861841u, 866739u, 871585u, 876378u, 881119u, 885806u, 890438u,
    895016u, 899537u, 904002u, 908410u, 912760u, 917051u, 921284u, 925456u,
    929568u, 933619u, 937609u, 941536u, 945400u, 949201u, 952938u, 956610u,
    960218u, 963759u, 967235u, 970643u, 973985u, 977259u, 980464u, 983601u,
    986669u, 989667u, 992595u, 995452u, 998239u, 1000954u, 1003597u, 1006168u,
    1008667u, 1011093u, 1013445u, 1015724u, 1017928u, 1020059u, 1022114u, 1024095u,
    1026000u, 1027830u, 1029584u, 1031262u, 1032864u, 1034389u, 1035837u, 1037208u,
    1038502u, 1039718u, 1040857u, 1041918u, 1042901u, 1043806u, 1044633u, 1045381u,
    1046051u, 1046643u, 1047155u, 1047589u, 1047944u, 1048221u, 1048418u, 1048537u,
    1048576u,
};

static_assert(sizeof(kCosineEaseQ20) == 1028u, "The normalized cosine LUT must occupy 1,028 bytes");

uint32_t clampArr(uint32_t value, uint32_t minimum, uint32_t maximum) {
  if (value < minimum) return minimum;
  if (value > maximum) return maximum;
  return value;
}

LC_PROFILE_FORCE_INLINE uint32_t easeQ20(uint32_t phaseQ32) {
  const uint32_t index = phaseQ32 >> 24u;
  const uint32_t fractionQ16 = (phaseQ32 >> 8u) & 0xFFFFu;
  const uint32_t lower = kCosineEaseQ20[index];
  const uint32_t delta = kCosineEaseQ20[index + 1u] - lower;
  return lower + ((delta * fractionQ16) >> 16u);
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
    cursor.phaseIncrementQ32 = static_cast<uint32_t>(kPhaseRange / spec.intervalCount);
    cursor.phaseRemainderIncrement = static_cast<uint32_t>(kPhaseRange % spec.intervalCount);
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
    cursor.phaseRemainder = static_cast<uint32_t>(remainder - cursor.intervalCount);
    ++cursor.phaseQ32;
  } else {
    cursor.phaseRemainder = static_cast<uint32_t>(remainder);
  }

  const uint32_t ease = easeQ20(cursor.phaseQ32);
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
