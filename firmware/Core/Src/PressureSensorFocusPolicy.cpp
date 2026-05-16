#include "PressureSensorFocusPolicy.h"

namespace PressureSensorFocusPolicy {

namespace {

uint8_t normalizePort(uint8_t port, uint8_t numPorts) {
  if (numPorts == 0u) {
    return 0u;
  }
  return (port < numPorts) ? port : 0u;
}

}  // namespace

uint8_t portForRead(uint8_t roundRobinPort,
                    uint8_t numPorts,
                    bool focusEnabled,
                    uint8_t focusPort) {
  if (focusEnabled) {
    return normalizePort(focusPort, numPorts);
  }
  return normalizePort(roundRobinPort, numPorts);
}

uint8_t nextPortAfterRead(uint8_t currentPort,
                          uint8_t numPorts,
                          bool focusEnabled,
                          uint8_t focusPort) {
  if (focusEnabled) {
    return normalizePort(focusPort, numPorts);
  }
  if (numPorts == 0u) {
    return 0u;
  }
  const uint8_t nextPort = static_cast<uint8_t>(currentPort + 1u);
  return (nextPort >= numPorts) ? 0u : nextPort;
}

}  // namespace PressureSensorFocusPolicy
