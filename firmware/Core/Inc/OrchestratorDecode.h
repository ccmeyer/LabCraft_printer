#ifndef INC_ORCHESTRATORDECODE_H_
#define INC_ORCHESTRATORDECODE_H_

#include <cstdint>

namespace OrchestratorDecode {

enum class Action : uint8_t {
  NoOp = 0,
  SetAxisMaxSpeed,
  SetAxisAccel,
  SetAxisProfile,
  Wait
};

struct CommandView {
  uint8_t cmd = 0;
  uint32_t p1 = 0;
  uint32_t p2 = 0;
  uint32_t p3 = 0;
};

struct Intent {
  Action action = Action::NoOp;
  uint8_t axis = 0;
  uint32_t value = 0;
  uint32_t waitMs = 0;
};

Intent decodeIntent(const CommandView& cmd);

}  // namespace OrchestratorDecode

#endif /* INC_ORCHESTRATORDECODE_H_ */
