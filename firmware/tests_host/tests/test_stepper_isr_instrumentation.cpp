#include "CppUTest/TestHarness.h"
#include "StepperIsrInstrumentation.h"

#include <cstdint>
#include <limits>

using StepperIsrInstrumentation::Phase;
using StepperIsrInstrumentation::State;

TEST_GROUP(StepperIsrInstrumentation)
{
};

TEST(StepperIsrInstrumentation, ClassifiesExactLegacyPhaseBoundaries)
{
    LONGS_EQUAL(static_cast<long>(Phase::Completion),
                static_cast<long>(StepperIsrInstrumentation::classifyPhase(200u, 0u, 200u, 40u, 40u)));
    LONGS_EQUAL(static_cast<long>(Phase::Acceleration),
                static_cast<long>(StepperIsrInstrumentation::classifyPhase(39u, 161u, 200u, 40u, 40u)));
    LONGS_EQUAL(static_cast<long>(Phase::Cruise),
                static_cast<long>(StepperIsrInstrumentation::classifyPhase(40u, 160u, 200u, 40u, 40u)));
    LONGS_EQUAL(static_cast<long>(Phase::Cruise),
                static_cast<long>(StepperIsrInstrumentation::classifyPhase(160u, 40u, 200u, 40u, 40u)));
    LONGS_EQUAL(static_cast<long>(Phase::Deceleration),
                static_cast<long>(StepperIsrInstrumentation::classifyPhase(161u, 39u, 200u, 40u, 40u)));
}

TEST(StepperIsrInstrumentation, ResetClearsPreviousMoveState)
{
    State state{};
    StepperIsrInstrumentation::reset(state, 100u);
    StepperIsrInstrumentation::recordSample(
        state, Phase::Cruise, 110u, 130u, true, true, false);

    StepperIsrInstrumentation::reset(state, 500u);
    const auto snapshot = StepperIsrInstrumentation::makeSnapshot(state);

    CHECK_TRUE(snapshot.valid);
    CHECK_TRUE(snapshot.active);
    CHECK_FALSE(snapshot.aborted);
    UNSIGNED_LONGS_EQUAL(0u, snapshot.totalEntries);
    UNSIGNED_LONGS_EQUAL(0u, snapshot.completedPulses);
    UNSIGNED_LONGS_EQUAL(0u, snapshot.pendingObservations);
    UNSIGNED_LONGS_EQUAL(500u, snapshot.startCycle);
}

TEST(StepperIsrInstrumentation, TracksPhaseCountsMaximaPulsesAndPendingStreak)
{
    State state{};
    StepperIsrInstrumentation::reset(state, 100u);
    StepperIsrInstrumentation::recordSample(
        state, Phase::Acceleration, 110u, 150u, true, false, false);
    StepperIsrInstrumentation::recordSample(
        state, Phase::Acceleration, 160u, 230u, true, true, false);
    StepperIsrInstrumentation::recordSample(
        state, Phase::Cruise, 240u, 260u, false, true, false);
    StepperIsrInstrumentation::recordSample(
        state, Phase::Deceleration, 270u, 325u, true, false, false);
    StepperIsrInstrumentation::recordSample(
        state, Phase::Completion, 330u, 345u, false, false, true);

    const auto snapshot = StepperIsrInstrumentation::makeSnapshot(state);
    CHECK_FALSE(snapshot.active);
    UNSIGNED_LONGS_EQUAL(5u, snapshot.totalEntries);
    UNSIGNED_LONGS_EQUAL(2u, snapshot.phaseEntries[static_cast<uint8_t>(Phase::Acceleration)]);
    UNSIGNED_LONGS_EQUAL(1u, snapshot.phaseEntries[static_cast<uint8_t>(Phase::Cruise)]);
    UNSIGNED_LONGS_EQUAL(1u, snapshot.phaseEntries[static_cast<uint8_t>(Phase::Deceleration)]);
    UNSIGNED_LONGS_EQUAL(1u, snapshot.phaseEntries[static_cast<uint8_t>(Phase::Completion)]);
    UNSIGNED_LONGS_EQUAL(70u, snapshot.phaseMaxCycles[static_cast<uint8_t>(Phase::Acceleration)]);
    UNSIGNED_LONGS_EQUAL(20u, snapshot.phaseMaxCycles[static_cast<uint8_t>(Phase::Cruise)]);
    UNSIGNED_LONGS_EQUAL(55u, snapshot.phaseMaxCycles[static_cast<uint8_t>(Phase::Deceleration)]);
    UNSIGNED_LONGS_EQUAL(70u, snapshot.maxCycles);
    UNSIGNED_LONGS_EQUAL(2u, snapshot.completedPulses);
    UNSIGNED_LONGS_EQUAL(3u, snapshot.pendingObservations);
    UNSIGNED_LONGS_EQUAL(2u, snapshot.maxPendingStreak);
    UNSIGNED_LONGS_EQUAL(245u, static_cast<uint32_t>(snapshot.durationCycles));
}

TEST(StepperIsrInstrumentation, SaturatesCountersInsteadOfWrapping)
{
    State state{};
    StepperIsrInstrumentation::reset(state, 0u);
    state.totalEntries = std::numeric_limits<uint32_t>::max();
    state.phaseEntries[static_cast<uint8_t>(Phase::Cruise)] = std::numeric_limits<uint32_t>::max();
    state.completedPulses = std::numeric_limits<uint32_t>::max();
    state.pendingObservations = std::numeric_limits<uint32_t>::max();
    state.currentPendingStreak = std::numeric_limits<uint32_t>::max();

    StepperIsrInstrumentation::recordSample(
        state, Phase::Cruise, 10u, 20u, true, true, false);
    const auto snapshot = StepperIsrInstrumentation::makeSnapshot(state);

    UNSIGNED_LONGS_EQUAL(std::numeric_limits<uint32_t>::max(), snapshot.totalEntries);
    UNSIGNED_LONGS_EQUAL(std::numeric_limits<uint32_t>::max(), snapshot.completedPulses);
    UNSIGNED_LONGS_EQUAL(std::numeric_limits<uint32_t>::max(), snapshot.pendingObservations);
    CHECK_TRUE((snapshot.saturationFlags & StepperIsrInstrumentation::SaturatedTotalEntries) != 0u);
    CHECK_TRUE((snapshot.saturationFlags & StepperIsrInstrumentation::SaturatedPhaseEntries) != 0u);
    CHECK_TRUE((snapshot.saturationFlags & StepperIsrInstrumentation::SaturatedCompletedPulses) != 0u);
    CHECK_TRUE((snapshot.saturationFlags & StepperIsrInstrumentation::SaturatedPendingObservations) != 0u);
    CHECK_TRUE((snapshot.saturationFlags & StepperIsrInstrumentation::SaturatedPendingStreak) != 0u);
}

TEST(StepperIsrInstrumentation, CalculatesDurationAcrossOneCycleCounterWrap)
{
    State state{};
    StepperIsrInstrumentation::reset(state, 0xFFFFFFF0u);
    StepperIsrInstrumentation::recordSample(
        state, Phase::Completion, 0xFFFFFFF8u, 0x00000020u, false, false, true);

    const auto snapshot = StepperIsrInstrumentation::makeSnapshot(state);
    UNSIGNED_LONGS_EQUAL(1u, snapshot.cycleWraps);
    UNSIGNED_LONGS_EQUAL(48u, static_cast<uint32_t>(snapshot.durationCycles));
}

TEST(StepperIsrInstrumentation, CalculatesDurationAcrossMultipleCycleCounterWraps)
{
    State state{};
    StepperIsrInstrumentation::reset(state, 0xFFFFFF00u);
    StepperIsrInstrumentation::recordSample(
        state, Phase::Cruise, 0xFFFFFF80u, 0x00000040u, false, false, false);
    StepperIsrInstrumentation::recordSample(
        state, Phase::Completion, 0xFFFFFFC0u, 0x00000080u, false, false, true);

    const auto snapshot = StepperIsrInstrumentation::makeSnapshot(state);
    UNSIGNED_LONGS_EQUAL(2u, snapshot.cycleWraps);
    const uint64_t expected = (static_cast<uint64_t>(1u) << 32) + 0x180u;
    CHECK_EQUAL(expected, snapshot.durationCycles);
}

TEST(StepperIsrInstrumentation, FinishWithoutSampleRecordsAbort)
{
    State state{};
    StepperIsrInstrumentation::reset(state, 100u);
    StepperIsrInstrumentation::finishWithoutSample(state, 175u, true);

    const auto snapshot = StepperIsrInstrumentation::makeSnapshot(state);
    CHECK_FALSE(snapshot.active);
    CHECK_TRUE(snapshot.aborted);
    UNSIGNED_LONGS_EQUAL(75u, static_cast<uint32_t>(snapshot.durationCycles));
    UNSIGNED_LONGS_EQUAL(0u, snapshot.totalEntries);
}
