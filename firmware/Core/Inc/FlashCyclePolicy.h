#ifndef INC_FLASHCYCLEPOLICY_H_
#define INC_FLASHCYCLEPOLICY_H_

#include <cstdint>

namespace FlashCyclePolicy {

static constexpr uint32_t kNoCycleId = 0u;

struct State {
  uint32_t nextCycleId = 1u;
  uint32_t activeCycleId = kNoCycleId;
  uint32_t scheduledCycleId = kNoCycleId;
  bool inProgress = false;
  bool ackExpected = false;
  bool ackObserved = false;
};

uint32_t beginCycle(State& state);
bool schedule(State& state, uint32_t cycleId);
bool consumeScheduledFire(State& state);
bool noteAck(State& state);
void finish(State& state);

bool isActive(const State& state);
bool isScheduled(const State& state);
bool isAckExpected(const State& state);

}  // namespace FlashCyclePolicy

#endif  // INC_FLASHCYCLEPOLICY_H_
