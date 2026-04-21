#include "CppUTest/TestHarness.h"
#include "SelfTestCommandPolicy.h"

TEST_GROUP(SelfTestCommandPolicy)
{
};

TEST(SelfTestCommandPolicy, ResolveRunIdPrefersExplicitTag) {
    const uint32_t resolved = SelfTestCommandPolicy::resolveRunId(true, 0xCAFEBABEu, true, 0x12345678u, 0x00000009u);
    UNSIGNED_LONGS_EQUAL(0xCAFEBABEu, resolved);
}

TEST(SelfTestCommandPolicy, ResolveRunIdFallsBackToSeq32ForLegacySenders) {
    const uint32_t resolved = SelfTestCommandPolicy::resolveRunId(false, 0u, true, 0x12345678u, 0x00000009u);
    UNSIGNED_LONGS_EQUAL(0x12345678u, resolved);
}

TEST(SelfTestCommandPolicy, ResolveRunIdFallsBackToCurrentCommandWhenNoMetadataPresent) {
    const uint32_t resolved = SelfTestCommandPolicy::resolveRunId(false, 0u, false, 0u, 0x00000009u);
    UNSIGNED_LONGS_EQUAL(0x00000009u, resolved);
}

TEST(SelfTestCommandPolicy, ResolveTimeoutMsPreservesExplicitTimeout) {
    const uint32_t resolved = SelfTestCommandPolicy::resolveTimeoutMs(true, 30000u);
    UNSIGNED_LONGS_EQUAL(30000u, resolved);
}

TEST(SelfTestCommandPolicy, ResolveTimeoutMsDefaultsToZeroWhenMissing) {
    const uint32_t resolved = SelfTestCommandPolicy::resolveTimeoutMs(false, 30000u);
    UNSIGNED_LONGS_EQUAL(0u, resolved);
}
