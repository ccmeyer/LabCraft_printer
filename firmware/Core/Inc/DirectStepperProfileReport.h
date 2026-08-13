#ifndef INC_DIRECTSTEPPERPROFILEREPORT_H_
#define INC_DIRECTSTEPPERPROFILEREPORT_H_

#include "DirectStepperProfile.h"
#include "StepperIsrInstrumentation.h"

#include <cstddef>
#include <cstdint>

namespace DirectStepperProfileReport {

struct MoveObservation {
  uint8_t axis = 0u;
  uint32_t logicalDistance = 0u;
  uint32_t effectiveRateHz = 0u;
  uint32_t expectedNativePulses = 0u;
  bool timedOut = false;
  bool endpointReached = false;
  bool instrumentationRequired = false;
  uint32_t statusWatchdogAgeMaxMs = 0u;
  uint32_t statusPeriodMaxMs = 0u;
  uint32_t statusFrameCount = 0u;
  DirectStepperProfile::Snapshot profile{};
  StepperIsrInstrumentation::Snapshot instrumentation{};
};

bool movePasses(const MoveObservation& observation);
size_t buildMetrics(char* out,
                    size_t capacity,
                    const MoveObservation& observation);

}  // namespace DirectStepperProfileReport

#endif /* INC_DIRECTSTEPPERPROFILEREPORT_H_ */
