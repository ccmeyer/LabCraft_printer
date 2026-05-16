#ifndef INC_PRESSURESENSORFOCUSPOLICY_H_
#define INC_PRESSURESENSORFOCUSPOLICY_H_

#include <cstdint>

namespace PressureSensorFocusPolicy {

uint8_t portForRead(uint8_t roundRobinPort,
                    uint8_t numPorts,
                    bool focusEnabled,
                    uint8_t focusPort);

uint8_t nextPortAfterRead(uint8_t currentPort,
                          uint8_t numPorts,
                          bool focusEnabled,
                          uint8_t focusPort);

}  // namespace PressureSensorFocusPolicy

#endif  // INC_PRESSURESENSORFOCUSPOLICY_H_
