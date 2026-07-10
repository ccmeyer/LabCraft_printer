#ifndef INC_PRESSUREREGULATORTELEMETRY_H_
#define INC_PRESSUREREGULATORTELEMETRY_H_

#include "RegulatorTelemetry.h"

#ifdef __cplusplus
extern "C" {
#endif

void PressureRegulator_CaptureTelemetryContext(RegulatorTelemetryResetContext* out,
                                               uint32_t pWatchdogEnabled,
                                               uint32_t pWatchdogAgeMs,
                                               uint32_t rWatchdogEnabled,
                                               uint32_t rWatchdogAgeMs,
                                               uint32_t snapshotTickMs);

#ifdef __cplusplus
}
#endif

#endif /* INC_PRESSUREREGULATORTELEMETRY_H_ */
