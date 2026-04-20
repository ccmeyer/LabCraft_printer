#include "OrchestratorCompletionPolicy.h"

namespace OrchestratorCompletionPolicy {

bool didInterruptibleWaitComplete(bool waitCompleted) {
    return waitCompleted;
}

bool didPauseAwareDelayComplete(bool delayCompleted, uint32_t remainingTicks) {
    return delayCompleted && remainingTicks == 0u;
}

void retireCurrentCommand(uint32_t currentCmdNum, uint32_t& lastExecutedCmdNum, uint32_t& lastRetiredCmdNum) {
    lastExecutedCmdNum = currentCmdNum;
    lastRetiredCmdNum = currentCmdNum;
}

}  // namespace OrchestratorCompletionPolicy
