#pragma once

#include <cstdint>

namespace OrchestratorCompletionPolicy {

bool didInterruptibleWaitComplete(bool waitCompleted);
bool didPauseAwareDelayComplete(bool delayCompleted, uint32_t remainingTicks);
bool shouldHoldRegulatorsForAbsXy(int32_t dx, int32_t dy, uint32_t thresholdSteps, bool printerBusy);
void retireCurrentCommand(uint32_t currentCmdNum, uint32_t& lastExecutedCmdNum, uint32_t& lastRetiredCmdNum);

}  // namespace OrchestratorCompletionPolicy
