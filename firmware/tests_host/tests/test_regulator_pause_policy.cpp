#include "CppUTest/TestHarness.h"
#include "RegulatorPausePolicy.h"

TEST_GROUP(RegulatorPausePolicyTests)
{
};

TEST(RegulatorPausePolicyTests, CapturesBothActiveChannels) {
  RegulatorPausePolicy::Snapshot snapshot{};

  RegulatorPausePolicy::captureOnce(snapshot, true, true);

  CHECK_TRUE(snapshot.valid);
  CHECK_TRUE(snapshot.printWasActive);
  CHECK_TRUE(snapshot.refuelWasActive);
}

TEST(RegulatorPausePolicyTests, CapturesEachActiveCombination) {
  RegulatorPausePolicy::Snapshot printOnly{};
  RegulatorPausePolicy::captureOnce(printOnly, true, false);
  CHECK_TRUE(printOnly.printWasActive);
  CHECK_FALSE(printOnly.refuelWasActive);

  RegulatorPausePolicy::Snapshot refuelOnly{};
  RegulatorPausePolicy::captureOnce(refuelOnly, false, true);
  CHECK_FALSE(refuelOnly.printWasActive);
  CHECK_TRUE(refuelOnly.refuelWasActive);

  RegulatorPausePolicy::Snapshot neither{};
  RegulatorPausePolicy::captureOnce(neither, false, false);
  CHECK_TRUE(neither.valid);
  CHECK_FALSE(neither.printWasActive);
  CHECK_FALSE(neither.refuelWasActive);
}

TEST(RegulatorPausePolicyTests, RepeatedPauseDoesNotOverwriteOriginalSnapshot) {
  RegulatorPausePolicy::Snapshot snapshot{};
  RegulatorPausePolicy::captureOnce(snapshot, true, false);

  RegulatorPausePolicy::captureOnce(snapshot, false, true);

  CHECK_TRUE(snapshot.valid);
  CHECK_TRUE(snapshot.printWasActive);
  CHECK_FALSE(snapshot.refuelWasActive);
}

TEST(RegulatorPausePolicyTests, ConsumeReturnsSnapshotAndPreventsSecondResume) {
  RegulatorPausePolicy::Snapshot snapshot{};
  RegulatorPausePolicy::captureOnce(snapshot, true, true);

  const RegulatorPausePolicy::Snapshot first = RegulatorPausePolicy::consume(snapshot);
  const RegulatorPausePolicy::Snapshot second = RegulatorPausePolicy::consume(snapshot);

  CHECK_TRUE(first.valid);
  CHECK_TRUE(first.printWasActive);
  CHECK_TRUE(first.refuelWasActive);
  CHECK_FALSE(snapshot.valid);
  CHECK_FALSE(second.valid);
}

TEST(RegulatorPausePolicyTests, DiscardPreventsResume) {
  RegulatorPausePolicy::Snapshot snapshot{};
  RegulatorPausePolicy::captureOnce(snapshot, true, true);

  RegulatorPausePolicy::discard(snapshot);
  const RegulatorPausePolicy::Snapshot consumed = RegulatorPausePolicy::consume(snapshot);

  CHECK_FALSE(snapshot.valid);
  CHECK_FALSE(snapshot.printWasActive);
  CHECK_FALSE(snapshot.refuelWasActive);
  CHECK_FALSE(consumed.valid);
}
