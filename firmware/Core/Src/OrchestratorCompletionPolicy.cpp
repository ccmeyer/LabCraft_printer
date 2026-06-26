#include "OrchestratorCompletionPolicy.h"

namespace OrchestratorCompletionPolicy {

namespace {

uint32_t absDelta(int32_t delta) {
    const int64_t wide = static_cast<int64_t>(delta);
    return static_cast<uint32_t>((wide < 0) ? -wide : wide);
}

}  // namespace

bool didInterruptibleWaitComplete(bool waitCompleted) {
    return waitCompleted;
}

bool didPauseAwareDelayComplete(bool delayCompleted, uint32_t remainingTicks) {
    return delayCompleted && remainingTicks == 0u;
}

bool shouldHoldRegulatorsForAbsXy(int32_t dx, int32_t dy, uint32_t thresholdSteps, bool printerBusy) {
    if (printerBusy) {
        return false;
    }
    const uint32_t absDx = absDelta(dx);
    const uint32_t absDy = absDelta(dy);
    const uint32_t longest = (absDx > absDy) ? absDx : absDy;
    return longest >= thresholdSteps;
}

void retireCurrentCommand(uint32_t currentCmdNum, uint32_t& lastExecutedCmdNum, uint32_t& lastRetiredCmdNum) {
    lastExecutedCmdNum = currentCmdNum;
    lastRetiredCmdNum = currentCmdNum;
}

}  // namespace OrchestratorCompletionPolicy
