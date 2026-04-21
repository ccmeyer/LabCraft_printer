#ifndef INC_SELFTESTCOMMANDPOLICY_H_
#define INC_SELFTESTCOMMANDPOLICY_H_

#include <cstdint>

namespace SelfTestCommandPolicy {

inline uint32_t resolveRunId(bool hasRunId, uint32_t runId, bool hasSeq32, uint32_t seq32, uint32_t fallbackCurrentCmd) {
    if (hasRunId) {
        return runId;
    }
    if (hasSeq32) {
        return seq32;
    }
    return fallbackCurrentCmd;
}

inline uint32_t resolveTimeoutMs(bool hasTimeoutMs, uint32_t timeoutMs) {
    return hasTimeoutMs ? timeoutMs : 0u;
}

} // namespace SelfTestCommandPolicy

#endif // INC_SELFTESTCOMMANDPOLICY_H_
