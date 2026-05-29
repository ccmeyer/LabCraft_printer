#ifndef INC_REGULATORPROFILECOMMANDPOLICY_H_
#define INC_REGULATORPROFILECOMMANDPOLICY_H_

#include <cstdint>

namespace RegulatorProfileCommandPolicy {

static constexpr uint8_t kCmdSetRecovery = 0x68u;
static constexpr uint8_t kCmdSetSlew = 0x69u;
static constexpr uint8_t kCmdSetReady = 0x6Au;
static constexpr uint8_t kCmdRestore = 0x6Bu;
static constexpr uint8_t kCmdQuery = 0x6Cu;

static constexpr uint8_t kChannelPrint = 0u;
static constexpr uint8_t kChannelRefuel = 1u;

enum class Status : uint8_t {
  Ok = 0,
  InvalidChannel,
  InvalidChunk,
  ReservedBitsSet,
  OutOfRange,
  MissingChunk,
  ChannelMismatch,
  InvalidRestoreMask,
  InvalidRestoreSource
};

enum class RestoreSource : uint8_t {
  Baseline = 0,
  Defaults = 1
};

struct RecoveryConfig {
  uint16_t activeTicks = 0;
  uint16_t baseBoostHz = 0;
  uint16_t pulseCoeffHzPerUs = 0;
  uint16_t pressureCoeffHzPerRaw = 0;
  uint16_t maxBoostHz = 0;
  uint16_t recoveryFloorHz = 0;
  uint16_t recoveryExitErrorRaw = 1;
  uint16_t maxExtendTicks = 0;
  bool allowExtendWhileUndershoot = false;
  bool boostOnlyWhenUndershoot = true;
  bool linearDecay = true;
};

struct SlewConfig {
  uint16_t maxHzDeltaUpPerLoop = 1;
  uint16_t maxHzDeltaDownPerLoop = 1;
  uint8_t recoveryBypassSlewTicks = 0;
};

struct ReadyConfig {
  uint16_t readyTolRaw = 1;
  uint8_t consecutiveSamples = 1;
};

struct RecoveryStaging {
  bool channelSet = false;
  uint8_t channel = 0;
  bool hasChunk0 = false;
  bool hasChunk1 = false;
  RecoveryConfig config{};
};

struct RecoveryChunkResult {
  Status status = Status::Ok;
  uint8_t channel = 0;
  uint8_t chunkIndex = 0;
  bool commit = false;
  bool committed = false;
  RecoveryConfig config{};
};

struct SlewResult {
  Status status = Status::Ok;
  uint8_t channel = 0;
  SlewConfig config{};
};

struct ReadyResult {
  Status status = Status::Ok;
  uint8_t channel = 0;
  ReadyConfig config{};
};

struct RestoreRequest {
  Status status = Status::Ok;
  bool restorePrint = false;
  bool restoreRefuel = false;
  RestoreSource source = RestoreSource::Baseline;
};

uint32_t packU16Pair(uint16_t low, uint16_t high);
uint16_t lowU16(uint32_t value);
uint16_t highU16(uint32_t value);

void resetRecoveryStaging(RecoveryStaging& staging);

RecoveryChunkResult applyRecoveryChunk(RecoveryStaging& staging,
                                       uint32_t p1,
                                       uint32_t p2,
                                       uint32_t p3);
SlewResult decodeSlew(uint32_t p1, uint32_t p2, uint32_t p3);
ReadyResult decodeReady(uint32_t p1, uint32_t p2, uint32_t p3);
RestoreRequest decodeRestore(uint32_t p1, uint32_t p2, uint32_t p3);

const char* statusName(Status status);

}  // namespace RegulatorProfileCommandPolicy

#endif /* INC_REGULATORPROFILECOMMANDPOLICY_H_ */
