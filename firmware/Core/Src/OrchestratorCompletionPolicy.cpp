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

AbsXyDisposition evaluateAbsXyCompletion(const AbsXyCompletionInput& input) {
    if (!input.startAccepted || input.terminalFailure) {
        return AbsXyDisposition::MotionFailure;
    }
    if (input.controlInterrupted) {
        return AbsXyDisposition::Interrupted;
    }
    if (!input.waitCompleted || !input.terminalCompleted || !input.endpointMatches ||
        !input.targetsMatch) {
        return AbsXyDisposition::MotionFailure;
    }
    return AbsXyDisposition::Completed;
}

AbsXyResumeDisposition evaluateAbsXyResume(
    const AbsXyResumeInput& input) {
    if (!input.targetCanonical || !input.startAccepted ||
        !input.targetsMatch) {
        return AbsXyResumeDisposition::MotionFailure;
    }
    if (input.terminalCompleted && !input.executorActive) {
        return input.endpointMatches
            ? AbsXyResumeDisposition::CompleteWithoutWait
            : AbsXyResumeDisposition::MotionFailure;
    }
    if (input.executorActive && !input.terminalCompleted &&
        !input.endpointMatches) {
        return AbsXyResumeDisposition::WaitForDoneBits;
    }
    return AbsXyResumeDisposition::MotionFailure;
}

DirectMoveDisposition evaluateDirectMoveCompletion(
    const DirectMoveCompletionInput& input) {
    if (!input.startAccepted || input.terminalFailure) {
        return DirectMoveDisposition::MotionFailure;
    }
    if (input.controlInterrupted) {
        return DirectMoveDisposition::Interrupted;
    }
    if (!input.waitCompleted || !input.terminalCompleted ||
        !input.endpointMatches || !input.targetsMatch) {
        return DirectMoveDisposition::MotionFailure;
    }
    return DirectMoveDisposition::Completed;
}

void retireCurrentCommand(uint32_t currentCmdNum, uint32_t& lastExecutedCmdNum, uint32_t& lastRetiredCmdNum) {
    lastExecutedCmdNum = currentCmdNum;
    lastRetiredCmdNum = currentCmdNum;
}

void retireFailedAcceptedCommands(uint32_t lastAcceptedCmdNum,
                                  uint32_t& currentCmdNum,
                                  uint32_t& lastRetiredCmdNum) {
    if (lastAcceptedCmdNum > lastRetiredCmdNum) {
        lastRetiredCmdNum = lastAcceptedCmdNum;
    }
    currentCmdNum = lastRetiredCmdNum;
}

}  // namespace OrchestratorCompletionPolicy
