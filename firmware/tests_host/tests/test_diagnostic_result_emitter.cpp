#include "CppUTest/TestHarness.h"
#include "DiagnosticResultEmitter.h"

#include <cstdio>
#include <cstring>

namespace {

size_t findTag(const uint8_t* payload, size_t len, uint8_t tag)
{
    size_t idx = 2u;
    while ((idx + 2u) <= len) {
        const uint8_t currentTag = payload[idx++];
        const uint8_t valueLen = payload[idx++];
        if (currentTag == tag) {
            return idx - 2u;
        }
        idx += valueLen;
    }
    return len;
}

uint32_t readU32(const uint8_t* p)
{
    return static_cast<uint32_t>(p[0]) |
           (static_cast<uint32_t>(p[1]) << 8) |
           (static_cast<uint32_t>(p[2]) << 16) |
           (static_cast<uint32_t>(p[3]) << 24);
}

uint16_t readU16(const uint8_t* p)
{
    return static_cast<uint16_t>(p[0]) |
           static_cast<uint16_t>(p[1] << 8);
}

} // namespace

TEST_GROUP(DiagnosticResultEmitter)
{
};

TEST(DiagnosticResultEmitter, ResultPayloadPreservesCurrentLayout)
{
    uint8_t payload[256] = {0};
    const size_t len = DiagnosticResultEmitter::buildResultPayload(
        payload,
        sizeof(payload),
        0x42u,
        0x12345678u,
        1001u,
        "comm_crc_known_vector",
        true,
        "crc=19255;expected=19255",
        0x01020304u);

    UNSIGNED_LONGS_EQUAL(0xFBu, payload[0]);
    UNSIGNED_LONGS_EQUAL(0x42u, payload[1]);

    const size_t testId = findTag(payload, len, DiagnosticResultEmitter::kTagTestId);
    CHECK_TRUE(testId < len);
    UNSIGNED_LONGS_EQUAL(2u, payload[testId + 1]);
    UNSIGNED_LONGS_EQUAL(1001u, readU16(&payload[testId + 2]));

    const size_t name = findTag(payload, len, DiagnosticResultEmitter::kTagName);
    CHECK_TRUE(name < len);
    UNSIGNED_LONGS_EQUAL(std::strlen("comm_crc_known_vector"), payload[name + 1]);
    MEMCMP_EQUAL("comm_crc_known_vector", &payload[name + 2], std::strlen("comm_crc_known_vector"));

    const size_t pass = findTag(payload, len, DiagnosticResultEmitter::kTagPass);
    CHECK_TRUE(pass < len);
    UNSIGNED_LONGS_EQUAL(1u, payload[pass + 1]);
    UNSIGNED_LONGS_EQUAL(1u, payload[pass + 2]);

    const size_t metrics = findTag(payload, len, DiagnosticResultEmitter::kTagMetrics);
    CHECK_TRUE(metrics < len);
    UNSIGNED_LONGS_EQUAL(std::strlen("crc=19255;expected=19255"), payload[metrics + 1]);
    MEMCMP_EQUAL("crc=19255;expected=19255", &payload[metrics + 2], std::strlen("crc=19255;expected=19255"));

    const size_t ts = findTag(payload, len, DiagnosticResultEmitter::kTagTimestamp);
    CHECK_TRUE(ts < len);
    UNSIGNED_LONGS_EQUAL(0x01020304u, readU32(&payload[ts + 2]));

    const size_t run = findTag(payload, len, DiagnosticResultEmitter::kTagRunId);
    CHECK_TRUE(run < len);
    UNSIGNED_LONGS_EQUAL(0x12345678u, readU32(&payload[run + 2]));
}

TEST(DiagnosticResultEmitter, ResultPayloadCapsLongNamesAndMetricsLikeFirmware)
{
    char longName[64];
    std::memset(longName, 'N', sizeof(longName));
    longName[sizeof(longName) - 1u] = '\0';

    char longMetrics[256];
    std::memset(longMetrics, 'M', sizeof(longMetrics));
    longMetrics[sizeof(longMetrics) - 1u] = '\0';

    uint8_t payload[256] = {0};
    const size_t len = DiagnosticResultEmitter::buildResultPayload(
        payload,
        sizeof(payload),
        0x01u,
        0x02u,
        0x03u,
        longName,
        false,
        longMetrics,
        0x04u);

    const size_t name = findTag(payload, len, DiagnosticResultEmitter::kTagName);
    CHECK_TRUE(name < len);
    UNSIGNED_LONGS_EQUAL(32u, payload[name + 1]);

    const size_t metrics = findTag(payload, len, DiagnosticResultEmitter::kTagMetrics);
    CHECK_TRUE(metrics < len);
    UNSIGNED_LONGS_EQUAL(198u, payload[metrics + 1]);
}

TEST(DiagnosticResultEmitter, GripperSealMetricsFitWithoutTruncatingAnalyzerFields)
{
    const char successMetrics[] =
        "target_raw=2512;valve_drive=diagnostic_one_pulse;pulse_ms=2000;tick_us=100;bursts=1;"
        "head_valve_mode=both;reg_vent=0;reg_pause=1;grip=1;refresh=0;"
        "p_drop=100;r_drop=100;drop_raw=100;timeout=0";
    const char failureMetrics[] =
        "target_raw=2512;valve_drive=diagnostic_one_pulse;pulse_ms=2000;tick_us=100;bursts=0;"
        "phase=condition;cond_done=2;reg_pause=0;grip=1;refresh=0;"
        "drop_raw=0;ready_ms=5000;timeout=1;grip_ok=1";

    uint8_t payload[256] = {0};
    size_t len = DiagnosticResultEmitter::buildResultPayload(
        payload,
        sizeof(payload),
        0x01u,
        0x02u,
        2501u,
        "gripper_seal_closed_decay_factory",
        true,
        successMetrics,
        0x04u);
    size_t metrics = findTag(payload, len, DiagnosticResultEmitter::kTagMetrics);
    CHECK_TRUE(metrics < len);
    UNSIGNED_LONGS_EQUAL(std::strlen(successMetrics), payload[metrics + 1]);
    MEMCMP_EQUAL(successMetrics, &payload[metrics + 2], std::strlen(successMetrics));

    len = DiagnosticResultEmitter::buildResultPayload(
        payload,
        sizeof(payload),
        0x01u,
        0x02u,
        2503u,
        "gripper_seal_repeatability_factory",
        false,
        failureMetrics,
        0x04u);
    metrics = findTag(payload, len, DiagnosticResultEmitter::kTagMetrics);
    CHECK_TRUE(metrics < len);
    UNSIGNED_LONGS_EQUAL(std::strlen(failureMetrics), payload[metrics + 1]);
    MEMCMP_EQUAL(failureMetrics, &payload[metrics + 2], std::strlen(failureMetrics));
}

TEST(DiagnosticResultEmitter, GripperStressRasterMetricsFitWithoutTruncatingDecimationFields)
{
    const char metricsText[] =
        "psi=3000;z_home_to=0;pulses=10;moves=384;xy_home_to=0;move_to=0;guard=0;bound=0;"
        "park_x=500;park_y=500;park_to=0;ready=0;timeout=0;fresh_to=0;focus=1;"
        "trace=1;sc=1031;stride=5;sample_ms=25";
    const char name[] = "gripper_motion_raster_3psi_factory";
    const size_t metricsBudget =
        DiagnosticResultEmitter::kResultMetricsFrameBudget -
        DiagnosticResultEmitter::kMaxResultNameBytes;

    CHECK_TRUE(std::strlen(metricsText) <= metricsBudget);

    uint8_t payload[256] = {0};
    const size_t len = DiagnosticResultEmitter::buildResultPayload(
        payload,
        sizeof(payload),
        0x01u,
        0x02u,
        2512u,
        name,
        true,
        metricsText,
        0x04u);

    const size_t metrics = findTag(payload, len, DiagnosticResultEmitter::kTagMetrics);
    CHECK_TRUE(metrics < len);
    UNSIGNED_LONGS_EQUAL(std::strlen(metricsText), payload[metrics + 1]);
    MEMCMP_EQUAL(metricsText, &payload[metrics + 2], std::strlen(metricsText));
    CHECK_TRUE(std::strstr(metricsText, "stride=5") != nullptr);
    CHECK_TRUE(std::strstr(metricsText, "sample_ms=25") != nullptr);
}

TEST(DiagnosticResultEmitter, CoordinatedXyEntryLatenessMetricsFitAtSaturatedValues)
{
    char metricsText[224] = {};
    const int written = std::snprintf(
        metricsText,
        sizeof(metricsText),
        "i2=%lu;s=%lu;mi=%lu;cm=%lu;ca=%lu;pm=%lu;lc=%lu;dm=%lu;sm=1;lf=%lu;sf=%lu;to=%lu;fv=1;tr=5;la=%lu;ra=%lu",
        4294967295ul,
        4294967295ul,
        4294967295ul,
        4294967295ul,
        4294967295ul,
        4294967295ul,
        4294967295ul,
        4294967295ul,
        4294967295ul,
        4294967295ul,
        4294967295ul,
        4294967295ul,
        4294967295ul);
    const char name[] = "coord_xy_40khz_entry_lateness";
    const size_t nameLength = std::strlen(name) >
            DiagnosticResultEmitter::kMaxResultNameBytes
        ? DiagnosticResultEmitter::kMaxResultNameBytes
        : std::strlen(name);
    const size_t metricsBudget =
        DiagnosticResultEmitter::kResultMetricsFrameBudget - nameLength;

    CHECK_TRUE(written > 0);
    CHECK_TRUE(static_cast<size_t>(written) < sizeof(metricsText));
    CHECK_TRUE(static_cast<size_t>(written) <= metricsBudget);

    uint8_t payload[256] = {0};
    const size_t len = DiagnosticResultEmitter::buildResultPayload(
        payload,
        sizeof(payload),
        0x01u,
        0x02u,
        2073u,
        name,
        true,
        metricsText,
        0x04u);
    const size_t metrics =
        findTag(payload, len, DiagnosticResultEmitter::kTagMetrics);
    CHECK_TRUE(metrics < len);
    UNSIGNED_LONGS_EQUAL(std::strlen(metricsText), payload[metrics + 1]);
    MEMCMP_EQUAL(metricsText, &payload[metrics + 2], std::strlen(metricsText));
}

TEST(DiagnosticResultEmitter, CoordinatedXySingleIrqMetricsFitAtSaturatedValues)
{
    char metricsText[224] = {};
    const int written = std::snprintf(
        metricsText,
        sizeof(metricsText),
        "em=1;ip=%lu;i2=%lu;pc=%lu;pn=%lu;px=%lu;pe=%lu;ds=%lu;mi=%lu;md=%lu;sl=%lu;pu=%lu;ok=1;sf=%lu;to=%lu",
        4294967295ul,
        4294967295ul,
        4294967295ul,
        4294967295ul,
        4294967295ul,
        4294967295ul,
        4294967295ul,
        4294967295ul,
        4294967295ul,
        4294967295ul,
        4294967295ul,
        4294967295ul,
        4294967295ul);
    const char name[] = "coord_xy_single_irq_pulse";
    const size_t nameLength = std::strlen(name) >
            DiagnosticResultEmitter::kMaxResultNameBytes
        ? DiagnosticResultEmitter::kMaxResultNameBytes
        : std::strlen(name);
    const size_t metricsBudget =
        DiagnosticResultEmitter::kResultMetricsFrameBudget - nameLength;

    CHECK_TRUE(written > 0);
    CHECK_TRUE(static_cast<size_t>(written) < sizeof(metricsText));
    CHECK_TRUE(static_cast<size_t>(written) <= metricsBudget);

    uint8_t payload[256] = {0};
    const size_t len = DiagnosticResultEmitter::buildResultPayload(
        payload,
        sizeof(payload),
        0x01u,
        0x02u,
        2074u,
        name,
        true,
        metricsText,
        0x04u);
    const size_t metrics =
        findTag(payload, len, DiagnosticResultEmitter::kTagMetrics);
    CHECK_TRUE(metrics < len);
    UNSIGNED_LONGS_EQUAL(std::strlen(metricsText), payload[metrics + 1]);
    MEMCMP_EQUAL(metricsText, &payload[metrics + 2], std::strlen(metricsText));
}

TEST(DiagnosticResultEmitter, CoordinatedXyMres3DeadlineMetricsFitAtAcceptedValues)
{
    const char metricsText[] =
        "i2=220000;s=220000;mi=0;cm=127;ca=127;pm=0;lc=0;dm=255;"
        "ds=219990;di=0;md=0;sl=450;sm=0;lf=0;sf=0;to=0;"
        "rm=2;dc=219990;ci=0;ns=1126;rc=12;rp=0;rd=64;"
        "fv=0;tr=0;la=0;ra=0;hm=0";
    const char name[] = "coord_xy_prod_conditional_rearm";
    CHECK_TRUE(std::strlen(name) <= DiagnosticResultEmitter::kMaxResultNameBytes);
    const size_t nameLength = std::strlen(name) >
            DiagnosticResultEmitter::kMaxResultNameBytes
        ? DiagnosticResultEmitter::kMaxResultNameBytes
        : std::strlen(name);
    const size_t metricsBudget =
        DiagnosticResultEmitter::kResultMetricsFrameBudget - nameLength;

    CHECK_TRUE(std::strlen(metricsText) <= metricsBudget);

    uint8_t payload[256] = {0};
    const size_t len = DiagnosticResultEmitter::buildResultPayload(
        payload,
        sizeof(payload),
        0x01u,
        0x02u,
        2082u,
        name,
        true,
        metricsText,
        0x04u);
    const size_t metrics =
        findTag(payload, len, DiagnosticResultEmitter::kTagMetrics);
    CHECK_TRUE(metrics < len);
    UNSIGNED_LONGS_EQUAL(std::strlen(metricsText), payload[metrics + 1]);
    MEMCMP_EQUAL(metricsText, &payload[metrics + 2], std::strlen(metricsText));
}

TEST(DiagnosticResultEmitter, Tmc2208Mres3ConfigurationMetricsFit)
{
    const char metricsText[] =
        "mr=3;mf=0;dd=1;gc=193;cc=855638099;tx=4;tf=0;"
        "ve=1;ae=1;lu=2;ge=1;sf=0;to=0";
    const char name[] = "tmc2208_production_mres3_config";
    const size_t nameLength = std::strlen(name) >
            DiagnosticResultEmitter::kMaxResultNameBytes
        ? DiagnosticResultEmitter::kMaxResultNameBytes
        : std::strlen(name);
    const size_t metricsBudget =
        DiagnosticResultEmitter::kResultMetricsFrameBudget - nameLength;

    CHECK_TRUE(std::strlen(metricsText) <= metricsBudget);
    uint8_t payload[256] = {0};
    const size_t len = DiagnosticResultEmitter::buildResultPayload(
        payload,
        sizeof(payload),
        0x01u,
        0x02u,
        2083u,
        name,
        true,
        metricsText,
        0x04u);
    CHECK_TRUE(len > 0u);
}

TEST(DiagnosticResultEmitter, ConditionalRearmMetricsFit)
{
    const char metricsText[] =
        "rm=2;rg=1125;it=900;dc=219990;mi=0;rc=10;rp=0;rd=64;"
        "ic=10;ix=0;ir=10;im=900;ns=1126;wm=4500;sf=0;to=0";
    const char name[] = "coord_xy_conditional_rearm";
    const size_t nameLength = std::strlen(name) >
            DiagnosticResultEmitter::kMaxResultNameBytes
        ? DiagnosticResultEmitter::kMaxResultNameBytes
        : std::strlen(name);
    CHECK_TRUE(std::strlen(metricsText) <=
        DiagnosticResultEmitter::kResultMetricsFrameBudget - nameLength);
    uint8_t payload[256] = {0};
    CHECK_TRUE(DiagnosticResultEmitter::buildResultPayload(
        payload, sizeof(payload), 1u, 2u, 2086u, name, true,
        metricsText, 4u) > 0u);
}

TEST(DiagnosticResultEmitter, DonePayloadPreservesCurrentLayout)
{
    uint8_t payload[64] = {0};
    const size_t len = DiagnosticResultEmitter::buildDonePayload(
        payload,
        sizeof(payload),
        0x22u,
        0xAABBCCDDu,
        23u,
        22u,
        1u,
        true,
        0x0A0B0C0Du);

    UNSIGNED_LONGS_EQUAL(0xFCu, payload[0]);
    UNSIGNED_LONGS_EQUAL(0x22u, payload[1]);

    const size_t run = findTag(payload, len, DiagnosticResultEmitter::kTagRunId);
    CHECK_TRUE(run < len);
    UNSIGNED_LONGS_EQUAL(0xAABBCCDDu, readU32(&payload[run + 2]));

    const size_t total = findTag(payload, len, DiagnosticResultEmitter::kTagTotal);
    CHECK_TRUE(total < len);
    UNSIGNED_LONGS_EQUAL(23u, readU16(&payload[total + 2]));

    const size_t passed = findTag(payload, len, DiagnosticResultEmitter::kTagPassed);
    CHECK_TRUE(passed < len);
    UNSIGNED_LONGS_EQUAL(22u, readU16(&payload[passed + 2]));

    const size_t failed = findTag(payload, len, DiagnosticResultEmitter::kTagFailed);
    CHECK_TRUE(failed < len);
    UNSIGNED_LONGS_EQUAL(1u, readU16(&payload[failed + 2]));

    const size_t aborted = findTag(payload, len, DiagnosticResultEmitter::kTagAborted);
    CHECK_TRUE(aborted < len);
    UNSIGNED_LONGS_EQUAL(1u, payload[aborted + 2]);

    const size_t ts = findTag(payload, len, DiagnosticResultEmitter::kTagTimestamp);
    CHECK_TRUE(ts < len);
    UNSIGNED_LONGS_EQUAL(0x0A0B0C0Du, readU32(&payload[ts + 2]));
}
