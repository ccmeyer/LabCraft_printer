#include "OrchestratorDecode.h"

namespace OrchestratorDecode {

namespace {
constexpr uint8_t CMD_SET_AXIS_MAXSPEED = 0x40u;
constexpr uint8_t CMD_SET_AXIS_ACCEL = 0x41u;
constexpr uint8_t CMD_SET_AXIS_PROFILE = 0x42u;
constexpr uint8_t CMD_WAIT = 0x50u;
}

Intent decodeIntent(const CommandView& cmd) {
  switch (cmd.cmd) {
    case CMD_SET_AXIS_MAXSPEED:
      return {Action::SetAxisMaxSpeed, static_cast<uint8_t>(cmd.p1), cmd.p2, 0u};
    case CMD_SET_AXIS_ACCEL:
      return {Action::SetAxisAccel, static_cast<uint8_t>(cmd.p1), cmd.p2, 0u};
    case CMD_SET_AXIS_PROFILE:
      return {Action::SetAxisProfile, static_cast<uint8_t>(cmd.p1), cmd.p2, 0u};
    case CMD_WAIT:
      return {Action::Wait, 0u, 0u, cmd.p1};
    default:
      return {};
  }
}

}  // namespace OrchestratorDecode
