#include "FlashCyclePolicy.h"

namespace FlashCyclePolicy {

namespace {

uint32_t nextNonzeroCycleId(State& state)
{
  uint32_t id = state.nextCycleId;
  if (id == kNoCycleId) {
    id = 1u;
  }
  state.nextCycleId = id + 1u;
  if (state.nextCycleId == kNoCycleId) {
    state.nextCycleId = 1u;
  }
  return id;
}

}  // namespace

uint32_t beginCycle(State& state)
{
  const uint32_t id = nextNonzeroCycleId(state);
  state.activeCycleId = id;
  state.scheduledCycleId = kNoCycleId;
  state.inProgress = true;
  state.ackExpected = false;
  state.ackObserved = false;
  return id;
}

bool schedule(State& state, uint32_t cycleId)
{
  if (!state.inProgress ||
      state.activeCycleId == kNoCycleId ||
      state.activeCycleId != cycleId ||
      state.scheduledCycleId != kNoCycleId ||
      state.ackExpected) {
    return false;
  }
  state.scheduledCycleId = cycleId;
  state.ackObserved = false;
  return true;
}

bool consumeScheduledFire(State& state)
{
  if (!state.inProgress ||
      state.activeCycleId == kNoCycleId ||
      state.scheduledCycleId != state.activeCycleId) {
    return false;
  }
  state.scheduledCycleId = kNoCycleId;
  state.ackExpected = true;
  return true;
}

bool noteAck(State& state)
{
  if (!state.inProgress || state.activeCycleId == kNoCycleId || !state.ackExpected) {
    return false;
  }
  state.ackExpected = false;
  state.ackObserved = true;
  return true;
}

void finish(State& state)
{
  state.activeCycleId = kNoCycleId;
  state.scheduledCycleId = kNoCycleId;
  state.inProgress = false;
  state.ackExpected = false;
  state.ackObserved = false;
}

bool isActive(const State& state)
{
  return state.inProgress && state.activeCycleId != kNoCycleId;
}

bool isScheduled(const State& state)
{
  return state.scheduledCycleId != kNoCycleId;
}

bool isAckExpected(const State& state)
{
  return state.ackExpected;
}

}  // namespace FlashCyclePolicy
