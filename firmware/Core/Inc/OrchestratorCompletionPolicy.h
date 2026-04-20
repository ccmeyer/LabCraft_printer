#pragma once

#include <cstdint>

namespace OrchestratorCompletionPolicy {

bool didInterruptibleWaitComplete(bool waitCompleted);
bool didPauseAwareDelayComplete(bool delayCompleted, uint32_t remainingTicks);
void retireCurrentCommand(uint32_t currentCmdNum, uint32_t& lastExecutedCmdNum, uint32_t& lastRetiredCmdNum);

}  // namespace OrchestratorCompletionPolicy
