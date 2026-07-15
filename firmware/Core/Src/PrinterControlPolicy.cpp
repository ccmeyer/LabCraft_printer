#include "PrinterControlPolicy.h"

namespace PrinterControlPolicy {

void requestPause(PrinterControlState& state, bool commandActive) {
  if (commandActive) {
    state.pauseRequested = true;
  }
}

void requestResume(PrinterControlState& state) {
  state.pauseRequested = false;
  state.pauseAcknowledged = false;
}

void requestCancel(PrinterControlState& state) {
  state.cancelGeneration++;
  state.pauseRequested = false;
  state.pauseAcknowledged = false;
}

void acknowledgePause(PrinterControlState& state, bool acknowledged) {
  state.pauseAcknowledged = acknowledged;
}

uint32_t captureCommandGeneration(const PrinterControlState& state) {
  return state.cancelGeneration;
}

bool isCommandCancelled(const PrinterControlState& state, uint32_t commandGeneration) {
  return state.cancelGeneration != commandGeneration;
}

bool shouldPauseAtDropletBoundary(const PrinterControlState& state,
                                  uint32_t commandGeneration,
                                  int32_t remaining) {
  return remaining > 0 && state.pauseRequested &&
         !isCommandCancelled(state, commandGeneration);
}

}  // namespace PrinterControlPolicy
