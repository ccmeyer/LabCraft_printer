#include "FlashSafety.h"

namespace FlashSafety {

const char* faultReasonToken(FaultReason reason)
{
  switch (reason) {
    case FaultReason::LineHighOnArm:
      return "line_high_on_arm";
    case FaultReason::RetriggerWhileHigh:
      return "retrigger_while_high";
    case FaultReason::LineStuckHigh:
      return "line_stuck_high";
    case FaultReason::None:
    default:
      return "none";
  }
}

}  // namespace FlashSafety
