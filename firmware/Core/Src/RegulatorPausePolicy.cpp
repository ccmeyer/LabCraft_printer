#include "RegulatorPausePolicy.h"

namespace RegulatorPausePolicy {

void captureOnce(Snapshot& snapshot, bool printActive, bool refuelActive) {
  if (snapshot.valid) {
    return;
  }

  snapshot.valid = true;
  snapshot.printWasActive = printActive;
  snapshot.refuelWasActive = refuelActive;
}

Snapshot consume(Snapshot& snapshot) {
  const Snapshot captured = snapshot;
  discard(snapshot);
  return captured;
}

void discard(Snapshot& snapshot) {
  snapshot = Snapshot{};
}

}  // namespace RegulatorPausePolicy
