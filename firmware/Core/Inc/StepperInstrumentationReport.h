#ifndef INC_STEPPERINSTRUMENTATIONREPORT_H_
#define INC_STEPPERINSTRUMENTATIONREPORT_H_

#include "StepperIsrInstrumentation.h"

#include <cstddef>
#include <cstdint>

namespace StepperInstrumentationReport {

struct MoveObservation {
  int32_t deltaXSteps = 0;
  int32_t deltaYSteps = 0;
  uint32_t effectiveRateHz = 0u;
  bool timedOut = false;
  bool endpointReached = false;
  uint32_t statusWatchdogAgeMaxMs = 0u;
  uint32_t statusPeriodMaxMs = 0u;
  uint32_t statusFrameCount = 0u;
  StepperIsrInstrumentation::Snapshot x{};
  StepperIsrInstrumentation::Snapshot y{};
};

uint32_t expectedTotalEntries(uint32_t completedPulses);
bool movePasses(const MoveObservation& observation);
size_t buildMetrics(char* out, size_t capacity, const MoveObservation& observation);

} // namespace StepperInstrumentationReport

#endif /* INC_STEPPERINSTRUMENTATIONREPORT_H_ */
