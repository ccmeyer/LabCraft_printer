#pragma once

#include <cstdint>

namespace OrchestratorCompletionPolicy {

enum class AbsXyDisposition : uint8_t {
    Completed = 0u,
    Interrupted = 1u,
    MotionFailure = 2u,
};

enum class DirectMoveDisposition : uint8_t {
    Completed = 0u,
    Interrupted = 1u,
    MotionFailure = 2u,
};

enum class AbsXyResumeDisposition : uint8_t {
    CompleteWithoutWait = 0u,
    WaitForDoneBits = 1u,
    MotionFailure = 2u,
};

struct AbsXyCompletionInput {
    bool startAccepted = false;
    bool waitCompleted = false;
    bool controlInterrupted = false;
    bool terminalCompleted = false;
    bool terminalFailure = false;
    bool endpointMatches = false;
    bool targetsMatch = false;
};

struct DirectMoveCompletionInput {
    bool startAccepted = false;
    bool waitCompleted = false;
    bool controlInterrupted = false;
    bool terminalCompleted = false;
    bool terminalFailure = false;
    bool endpointMatches = false;
    bool targetsMatch = false;
};

struct AbsXyResumeInput {
    bool targetCanonical = false;
    bool startAccepted = false;
    bool executorActive = false;
    bool terminalCompleted = false;
    bool endpointMatches = false;
    bool targetsMatch = false;
};

bool didInterruptibleWaitComplete(bool waitCompleted);
bool didPauseAwareDelayComplete(bool delayCompleted, uint32_t remainingTicks);
bool shouldHoldRegulatorsForAbsXy(int32_t dx, int32_t dy, uint32_t thresholdSteps, bool printerBusy);
AbsXyDisposition evaluateAbsXyCompletion(const AbsXyCompletionInput& input);
AbsXyResumeDisposition evaluateAbsXyResume(
    const AbsXyResumeInput& input);
DirectMoveDisposition evaluateDirectMoveCompletion(
    const DirectMoveCompletionInput& input);
void retireCurrentCommand(uint32_t currentCmdNum, uint32_t& lastExecutedCmdNum, uint32_t& lastRetiredCmdNum);
void retireFailedAcceptedCommands(uint32_t lastAcceptedCmdNum,
                                  uint32_t& currentCmdNum,
                                  uint32_t& lastRetiredCmdNum);

}  // namespace OrchestratorCompletionPolicy
