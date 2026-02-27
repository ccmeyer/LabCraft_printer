#include "CppUTest/TestHarness.h"
#include <cstddef>

extern "C" {
#include "nvm_codec.h"
}

TEST_GROUP(NvmCodec)
{
};

TEST(NvmCodec, DefaultsProduceValidRecord) {
    nvm_config_t cfg{};
    nvm_codec_defaults(&cfg);

    UNSIGNED_LONGS_EQUAL(NVM_MAGIC, cfg.magic);
    UNSIGNED_LONGS_EQUAL(NVM_VERSION, cfg.version);
    UNSIGNED_LONGS_EQUAL(115200u, cfg.baud);
    DOUBLES_EQUAL(1.0, cfg.gain, 0.0001);
    CHECK_TRUE(nvm_codec_is_valid(&cfg));
}

TEST(NvmCodec, CorruptedCrcIsRejected) {
    nvm_config_t cfg{};
    nvm_codec_defaults(&cfg);
    cfg.crc ^= 0x01020304u;

    CHECK_FALSE(nvm_codec_is_valid(&cfg));
}

TEST(NvmCodec, VersionMismatchIsRejected) {
    nvm_config_t cfg{};
    nvm_codec_defaults(&cfg);
    cfg.version += 1u;
    nvm_codec_finalize(&cfg);
    cfg.version += 1u;

    CHECK_FALSE(nvm_codec_is_valid(&cfg));
}

TEST(NvmCodec, FinalizeRecomputesStableCrc) {
    nvm_config_t cfg{};
    nvm_codec_defaults(&cfg);
    const uint32_t originalCrc = cfg.crc;

    cfg.flags = 0x55AA55AAu;
    nvm_codec_finalize(&cfg);

    CHECK_TRUE(cfg.crc != originalCrc);
    UNSIGNED_LONGS_EQUAL(nvm_crc32_block(&cfg, offsetof(nvm_config_t, crc)), cfg.crc);
}
