#include "CppUTest/TestHarness.h"
#include "RegulatorProfileCommandPolicy.h"

namespace R = RegulatorProfileCommandPolicy;

TEST_GROUP(RegulatorProfileCommandPolicy)
{
};

TEST(RegulatorProfileCommandPolicy, CommandIdsMatchReservedStageTwoContract) {
    UNSIGNED_LONGS_EQUAL(0x68u, R::kCmdSetRecovery);
    UNSIGNED_LONGS_EQUAL(0x69u, R::kCmdSetSlew);
    UNSIGNED_LONGS_EQUAL(0x6Au, R::kCmdSetReady);
    UNSIGNED_LONGS_EQUAL(0x6Bu, R::kCmdRestore);
    UNSIGNED_LONGS_EQUAL(0x6Cu, R::kCmdQuery);
}

TEST(RegulatorProfileCommandPolicy, RecoveryStagesAndCommitsValidChunks) {
    R::RecoveryStaging staging{};

    auto r0 = R::applyRecoveryChunk(
        staging,
        (0u << 8) | R::kChannelPrint,
        R::packU16Pair(2u, 300u),
        R::packU16Pair(1u, 0u));
    LONGS_EQUAL((int)R::Status::Ok, (int)r0.status);
    CHECK_FALSE(r0.committed);

    auto r1 = R::applyRecoveryChunk(
        staging,
        (1u << 8) | R::kChannelPrint,
        R::packU16Pair(1500u, 0u),
        R::packU16Pair(3u, 0u));
    LONGS_EQUAL((int)R::Status::Ok, (int)r1.status);

    auto r2 = R::applyRecoveryChunk(
        staging,
        (2u << 8) | (1u << 16) | R::kChannelPrint,
        0x6u,
        0u);
    LONGS_EQUAL((int)R::Status::Ok, (int)r2.status);
    CHECK_TRUE(r2.committed);
    UNSIGNED_LONGS_EQUAL(2u, r2.config.activeTicks);
    UNSIGNED_LONGS_EQUAL(300u, r2.config.baseBoostHz);
    CHECK_FALSE(r2.config.allowExtendWhileUndershoot);
    CHECK_TRUE(r2.config.boostOnlyWhenUndershoot);
    CHECK_TRUE(r2.config.linearDecay);
    CHECK_FALSE(staging.hasChunk0);
    CHECK_FALSE(staging.hasChunk1);
}

TEST(RegulatorProfileCommandPolicy, RecoveryRejectsMissingChunkInvalidChannelAndReservedBits) {
    R::RecoveryStaging staging{};

    auto missing = R::applyRecoveryChunk(
        staging,
        (2u << 8) | (1u << 16) | R::kChannelPrint,
        0x7u,
        0u);
    LONGS_EQUAL((int)R::Status::MissingChunk, (int)missing.status);

    auto badChannel = R::applyRecoveryChunk(staging, 2u, 0u, 0u);
    LONGS_EQUAL((int)R::Status::InvalidChannel, (int)badChannel.status);

    auto badReserved = R::applyRecoveryChunk(
        staging,
        (3u << 16) | R::kChannelPrint,
        0u,
        0u);
    LONGS_EQUAL((int)R::Status::ReservedBitsSet, (int)badReserved.status);
}

TEST(RegulatorProfileCommandPolicy, RecoveryRejectsOutOfRangeValuesWithoutStaging) {
    R::RecoveryStaging staging{};

    auto bad = R::applyRecoveryChunk(
        staging,
        (0u << 8) | R::kChannelPrint,
        R::packU16Pair(21u, 300u),
        R::packU16Pair(1u, 0u));
    LONGS_EQUAL((int)R::Status::OutOfRange, (int)bad.status);
    CHECK_FALSE(staging.hasChunk0);

    auto good = R::applyRecoveryChunk(
        staging,
        (0u << 8) | R::kChannelPrint,
        R::packU16Pair(20u, 300u),
        R::packU16Pair(1u, 0u));
    LONGS_EQUAL((int)R::Status::Ok, (int)good.status);
    CHECK_TRUE(staging.hasChunk0);
}

TEST(RegulatorProfileCommandPolicy, SlewAndReadyDecodeAndValidateBounds) {
    auto slew = R::decodeSlew(
        R::kChannelRefuel,
        R::packU16Pair(1200u, 450u),
        3u);
    LONGS_EQUAL((int)R::Status::Ok, (int)slew.status);
    UNSIGNED_LONGS_EQUAL(R::kChannelRefuel, slew.channel);
    UNSIGNED_LONGS_EQUAL(1200u, slew.config.maxHzDeltaUpPerLoop);
    UNSIGNED_LONGS_EQUAL(450u, slew.config.maxHzDeltaDownPerLoop);
    UNSIGNED_LONGS_EQUAL(3u, slew.config.recoveryBypassSlewTicks);

    auto badSlew = R::decodeSlew(R::kChannelPrint, R::packU16Pair(0u, 450u), 0u);
    LONGS_EQUAL((int)R::Status::OutOfRange, (int)badSlew.status);

    auto ready = R::decodeReady(R::kChannelPrint, 4u, 1u);
    LONGS_EQUAL((int)R::Status::Ok, (int)ready.status);
    UNSIGNED_LONGS_EQUAL(4u, ready.config.readyTolRaw);
    UNSIGNED_LONGS_EQUAL(1u, ready.config.consecutiveSamples);

    auto badReady = R::decodeReady(R::kChannelPrint, R::packU16Pair(26u, 0u), 1u);
    LONGS_EQUAL((int)R::Status::OutOfRange, (int)badReady.status);
}

TEST(RegulatorProfileCommandPolicy, SlewAndReadyRejectReservedBits) {
    auto badSlewP1 = R::decodeSlew(0x100u | R::kChannelPrint, R::packU16Pair(1u, 1u), 0u);
    LONGS_EQUAL((int)R::Status::ReservedBitsSet, (int)badSlewP1.status);

    auto badSlewP3 = R::decodeSlew(R::kChannelPrint, R::packU16Pair(1u, 1u), 0x100u);
    LONGS_EQUAL((int)R::Status::ReservedBitsSet, (int)badSlewP3.status);

    auto badReadyP2 = R::decodeReady(R::kChannelPrint, R::packU16Pair(4u, 1u), 1u);
    LONGS_EQUAL((int)R::Status::ReservedBitsSet, (int)badReadyP2.status);

    auto badReadyP3 = R::decodeReady(R::kChannelPrint, 4u, 0x100u);
    LONGS_EQUAL((int)R::Status::ReservedBitsSet, (int)badReadyP3.status);
}

TEST(RegulatorProfileCommandPolicy, RestoreValidatesMaskAndSource) {
    auto both = R::decodeRestore(0x3u, 0u, 0u);
    LONGS_EQUAL((int)R::Status::Ok, (int)both.status);
    CHECK_TRUE(both.restorePrint);
    CHECK_TRUE(both.restoreRefuel);
    LONGS_EQUAL((int)R::RestoreSource::Baseline, (int)both.source);

    auto defaults = R::decodeRestore(0x1u, 1u, 0u);
    LONGS_EQUAL((int)R::Status::Ok, (int)defaults.status);
    CHECK_TRUE(defaults.restorePrint);
    CHECK_FALSE(defaults.restoreRefuel);
    LONGS_EQUAL((int)R::RestoreSource::Defaults, (int)defaults.source);

    auto badMask = R::decodeRestore(0u, 0u, 0u);
    LONGS_EQUAL((int)R::Status::InvalidRestoreMask, (int)badMask.status);

    auto badSource = R::decodeRestore(0x1u, 2u, 0u);
    LONGS_EQUAL((int)R::Status::InvalidRestoreSource, (int)badSource.status);
}
