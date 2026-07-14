#pragma once

namespace RegulatorPausePolicy {

struct Snapshot {
  bool valid = false;
  bool printWasActive = false;
  bool refuelWasActive = false;
};

void captureOnce(Snapshot& snapshot, bool printActive, bool refuelActive);
Snapshot consume(Snapshot& snapshot);
void discard(Snapshot& snapshot);

}  // namespace RegulatorPausePolicy
