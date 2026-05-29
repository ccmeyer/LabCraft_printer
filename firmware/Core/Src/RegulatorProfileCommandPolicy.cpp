#include "RegulatorProfileCommandPolicy.h"

namespace RegulatorProfileCommandPolicy {

namespace {

static constexpr uint32_t kRecoveryCommitBit = (1u << 16);
static constexpr uint32_t kRecoveryReservedMask = 0xFFFE0000u;
static constexpr uint32_t kSlewReadyChannelReservedMask = 0xFFFFFF00u;

bool validChannel(uint8_t channel) {
  return (channel == kChannelPrint) || (channel == kChannelRefuel);
}

bool inRange(uint32_t value, uint32_t minValue, uint32_t maxValue) {
  return (value >= minValue) && (value <= maxValue);
}

Status decodeSimpleChannel(uint32_t p1, uint8_t& channel) {
  channel = static_cast<uint8_t>(p1 & 0xFFu);
  if ((p1 & kSlewReadyChannelReservedMask) != 0u) {
    return Status::ReservedBitsSet;
  }
  return validChannel(channel) ? Status::Ok : Status::InvalidChannel;
}

Status validateRecovery(const RecoveryConfig& cfg) {
  if (!inRange(cfg.activeTicks, 0u, 20u) ||
      !inRange(cfg.baseBoostHz, 0u, 6000u) ||
      !inRange(cfg.pulseCoeffHzPerUs, 0u, 4u) ||
      !inRange(cfg.pressureCoeffHzPerRaw, 0u, 4u) ||
      !inRange(cfg.maxBoostHz, 0u, 12000u) ||
      !inRange(cfg.recoveryFloorHz, 0u, 5000u) ||
      !inRange(cfg.recoveryExitErrorRaw, 1u, 30u) ||
      !inRange(cfg.maxExtendTicks, 0u, 10u)) {
    return Status::OutOfRange;
  }
  return Status::Ok;
}

}  // namespace

uint32_t packU16Pair(uint16_t low, uint16_t high) {
  return static_cast<uint32_t>(low) | (static_cast<uint32_t>(high) << 16);
}

uint16_t lowU16(uint32_t value) {
  return static_cast<uint16_t>(value & 0xFFFFu);
}

uint16_t highU16(uint32_t value) {
  return static_cast<uint16_t>((value >> 16) & 0xFFFFu);
}

void resetRecoveryStaging(RecoveryStaging& staging) {
  staging = RecoveryStaging{};
}

RecoveryChunkResult applyRecoveryChunk(RecoveryStaging& staging,
                                       uint32_t p1,
                                       uint32_t p2,
                                       uint32_t p3) {
  RecoveryChunkResult result{};
  result.channel = static_cast<uint8_t>(p1 & 0xFFu);
  result.chunkIndex = static_cast<uint8_t>((p1 >> 8) & 0xFFu);
  result.commit = (p1 & kRecoveryCommitBit) != 0u;

  if ((p1 & kRecoveryReservedMask) != 0u) {
    result.status = Status::ReservedBitsSet;
    return result;
  }
  if (!validChannel(result.channel)) {
    result.status = Status::InvalidChannel;
    return result;
  }
  if (result.chunkIndex > 2u) {
    result.status = Status::InvalidChunk;
    return result;
  }
  if (result.commit && result.chunkIndex != 2u) {
    result.status = Status::InvalidChunk;
    return result;
  }
  if (staging.channelSet && staging.channel != result.channel) {
    result.status = Status::ChannelMismatch;
    return result;
  }

  auto markChannel = [&]() {
    staging.channelSet = true;
    staging.channel = result.channel;
  };

  if (result.chunkIndex == 0u) {
    RecoveryConfig candidate = staging.config;
    candidate.activeTicks = lowU16(p2);
    candidate.baseBoostHz = highU16(p2);
    candidate.pulseCoeffHzPerUs = lowU16(p3);
    candidate.pressureCoeffHzPerRaw = highU16(p3);
    result.status = validateRecovery(candidate);
    if (result.status == Status::Ok) {
      markChannel();
      staging.config = candidate;
      staging.hasChunk0 = true;
    }
    return result;
  }

  if (result.chunkIndex == 1u) {
    RecoveryConfig candidate = staging.config;
    candidate.maxBoostHz = lowU16(p2);
    candidate.recoveryFloorHz = highU16(p2);
    candidate.recoveryExitErrorRaw = lowU16(p3);
    candidate.maxExtendTicks = highU16(p3);
    result.status = validateRecovery(candidate);
    if (result.status == Status::Ok) {
      markChannel();
      staging.config = candidate;
      staging.hasChunk1 = true;
    }
    return result;
  }

  if ((p2 & ~0x7u) != 0u || p3 != 0u) {
    result.status = Status::ReservedBitsSet;
    return result;
  }
  RecoveryConfig candidate = staging.config;
  candidate.allowExtendWhileUndershoot = (p2 & 0x1u) != 0u;
  candidate.boostOnlyWhenUndershoot = (p2 & 0x2u) != 0u;
  candidate.linearDecay = (p2 & 0x4u) != 0u;
  if (result.commit) {
    if (!staging.hasChunk0 || !staging.hasChunk1) {
      result.status = Status::MissingChunk;
      return result;
    }
    result.status = validateRecovery(candidate);
    if (result.status == Status::Ok) {
      result.committed = true;
      result.config = candidate;
      resetRecoveryStaging(staging);
    }
    return result;
  }

  markChannel();
  staging.config = candidate;
  result.status = Status::Ok;
  result.config = staging.config;
  return result;
}

SlewResult decodeSlew(uint32_t p1, uint32_t p2, uint32_t p3) {
  SlewResult result{};
  result.status = decodeSimpleChannel(p1, result.channel);
  if (result.status != Status::Ok) {
    return result;
  }
  if ((p3 & 0xFFFFFF00u) != 0u) {
    result.status = Status::ReservedBitsSet;
    return result;
  }
  result.config.maxHzDeltaUpPerLoop = lowU16(p2);
  result.config.maxHzDeltaDownPerLoop = highU16(p2);
  result.config.recoveryBypassSlewTicks = static_cast<uint8_t>(p3 & 0xFFu);
  if (!inRange(result.config.maxHzDeltaUpPerLoop, 1u, 2500u) ||
      !inRange(result.config.maxHzDeltaDownPerLoop, 1u, 2500u) ||
      !inRange(result.config.recoveryBypassSlewTicks, 0u, 5u)) {
    result.status = Status::OutOfRange;
  }
  return result;
}

ReadyResult decodeReady(uint32_t p1, uint32_t p2, uint32_t p3) {
  ReadyResult result{};
  result.status = decodeSimpleChannel(p1, result.channel);
  if (result.status != Status::Ok) {
    return result;
  }
  if ((p2 & 0xFFFF0000u) != 0u || (p3 & 0xFFFFFF00u) != 0u) {
    result.status = Status::ReservedBitsSet;
    return result;
  }
  result.config.readyTolRaw = lowU16(p2);
  result.config.consecutiveSamples = static_cast<uint8_t>(p3 & 0xFFu);
  if (!inRange(result.config.readyTolRaw, 1u, 25u) ||
      !inRange(result.config.consecutiveSamples, 1u, 5u)) {
    result.status = Status::OutOfRange;
  }
  return result;
}

RestoreRequest decodeRestore(uint32_t p1, uint32_t p2, uint32_t p3) {
  RestoreRequest result{};
  if (p3 != 0u) {
    result.status = Status::ReservedBitsSet;
    return result;
  }
  if (p1 == 0u || (p1 & ~0x3u) != 0u) {
    result.status = Status::InvalidRestoreMask;
    return result;
  }
  if (p2 > 1u) {
    result.status = Status::InvalidRestoreSource;
    return result;
  }
  result.restorePrint = (p1 & 0x1u) != 0u;
  result.restoreRefuel = (p1 & 0x2u) != 0u;
  result.source = (p2 == 0u) ? RestoreSource::Baseline : RestoreSource::Defaults;
  return result;
}

const char* statusName(Status status) {
  switch (status) {
    case Status::Ok: return "ok";
    case Status::InvalidChannel: return "invalid_channel";
    case Status::InvalidChunk: return "invalid_chunk";
    case Status::ReservedBitsSet: return "reserved_bits";
    case Status::OutOfRange: return "out_of_range";
    case Status::MissingChunk: return "missing_chunk";
    case Status::ChannelMismatch: return "channel_mismatch";
    case Status::InvalidRestoreMask: return "invalid_restore_mask";
    case Status::InvalidRestoreSource: return "invalid_restore_source";
    default: return "unknown";
  }
}

}  // namespace RegulatorProfileCommandPolicy
