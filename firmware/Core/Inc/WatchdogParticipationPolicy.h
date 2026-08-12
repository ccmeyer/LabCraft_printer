#pragma once

#include <stdint.h>

/* Pure mask operations shared by the task-context watchdog implementation and
 * host tests. Callers are responsible for making each read/modify/write
 * transition atomic. */
static inline uint32_t WatchdogParticipation_Enable(uint32_t mask, uint32_t bit)
{
  return mask | bit;
}

static inline uint32_t WatchdogParticipation_Disable(uint32_t mask, uint32_t bit)
{
  return mask & ~bit;
}
