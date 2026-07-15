#ifndef INC_PRINTERCONTROLPOLICY_H_
#define INC_PRINTERCONTROLPOLICY_H_

#include <cstdint>

struct PrinterControlState {
  volatile bool pauseRequested = false;
  volatile bool pauseAcknowledged = false;
  volatile uint32_t cancelGeneration = 0u;
};

namespace PrinterControlPolicy {

void requestPause(PrinterControlState& state, bool commandActive);
void requestResume(PrinterControlState& state);
void requestCancel(PrinterControlState& state);
void acknowledgePause(PrinterControlState& state, bool acknowledged);
uint32_t captureCommandGeneration(const PrinterControlState& state);
bool isCommandCancelled(const PrinterControlState& state, uint32_t commandGeneration);
bool shouldPauseAtDropletBoundary(const PrinterControlState& state,
                                  uint32_t commandGeneration,
                                  int32_t remaining);

}  // namespace PrinterControlPolicy

#endif /* INC_PRINTERCONTROLPOLICY_H_ */
