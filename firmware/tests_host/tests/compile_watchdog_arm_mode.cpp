#include "WatchdogSupervisor.h"

#ifndef EXPECTED_WATCHDOG_ARM_MODE
#error "EXPECTED_WATCHDOG_ARM_MODE must be provided by the compile target"
#endif

static_assert(LC_WATCHDOG_ARM_MODE == EXPECTED_WATCHDOG_ARM_MODE,
              "watchdog arm mode does not match the requested build");
