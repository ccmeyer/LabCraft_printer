#include "CppUTest/TestHarness.h"

#include "PrinterControlPolicy.h"

TEST_GROUP(PrinterControlPolicy)
{
};

TEST(PrinterControlPolicy, ActiveCommandPausesAtNextDropletBoundary)
{
    PrinterControlState state{};
    const uint32_t generation = PrinterControlPolicy::captureCommandGeneration(state);

    PrinterControlPolicy::requestPause(state, true);

    CHECK_TRUE(PrinterControlPolicy::shouldPauseAtDropletBoundary(state, generation, 2));
}

TEST(PrinterControlPolicy, IdleCommandDoesNotRetainPauseRequest)
{
    PrinterControlState state{};
    PrinterControlPolicy::requestPause(state, false);
    CHECK_FALSE(state.pauseRequested);
}

TEST(PrinterControlPolicy, ResumePreservesCommandGeneration)
{
    PrinterControlState state{};
    const uint32_t generation = PrinterControlPolicy::captureCommandGeneration(state);
    PrinterControlPolicy::requestPause(state, true);
    PrinterControlPolicy::acknowledgePause(state, true);

    PrinterControlPolicy::requestResume(state);

    CHECK_FALSE(state.pauseRequested);
    CHECK_FALSE(state.pauseAcknowledged);
    CHECK_FALSE(PrinterControlPolicy::isCommandCancelled(state, generation));
}

TEST(PrinterControlPolicy, CancelUnblocksPauseAndInvalidatesActiveCommand)
{
    PrinterControlState state{};
    const uint32_t generation = PrinterControlPolicy::captureCommandGeneration(state);
    PrinterControlPolicy::requestPause(state, true);
    PrinterControlPolicy::acknowledgePause(state, true);

    PrinterControlPolicy::requestCancel(state);

    CHECK_FALSE(state.pauseRequested);
    CHECK_FALSE(state.pauseAcknowledged);
    CHECK_TRUE(PrinterControlPolicy::isCommandCancelled(state, generation));
}

TEST(PrinterControlPolicy, CommandQueuedAfterCancelUsesNewGeneration)
{
    PrinterControlState state{};
    PrinterControlPolicy::requestCancel(state);
    const uint32_t generation = PrinterControlPolicy::captureCommandGeneration(state);
    CHECK_FALSE(PrinterControlPolicy::isCommandCancelled(state, generation));
}

TEST(PrinterControlPolicy, FinalDropletCompletionDoesNotBlockOnPause)
{
    PrinterControlState state{};
    const uint32_t generation = PrinterControlPolicy::captureCommandGeneration(state);
    PrinterControlPolicy::requestPause(state, true);
    CHECK_FALSE(PrinterControlPolicy::shouldPauseAtDropletBoundary(state, generation, 0));
}
