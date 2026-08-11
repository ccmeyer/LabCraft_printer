# Milestone 12 Slice 12.4 Completion Record

Status: complete

Date: 2026-08-09

Commit boundary: cumulative Milestone 12 worktree; one final milestone commit
is required after Slice 12.5.

## Delivered

- Added the literal nine-case `authoritative_persistence_safeguards_v1`
  catalog covering ambiguous pending intent, missing checkpoint, checkpoint
  plan/progress conflicts, progress-plan conflict, immutable-history conflict,
  missing calibration link, design hash conflict, and incomplete bundle.
- Added a strict prelaunch hook between retained SIL session initialization and
  application launch. Existing journeys do not use it.
- Built every pristine fixture with production plan, revision, progress,
  resume, and calibration serializers under the current retained SIL root;
  copied it once; changed one allowlisted target; and emitted a fault manifest.
- Drove the real Experiment Editor and Select Experiment Folder action through
  production `load_experiment()` and `inspect_authoritative_execution()`, then
  attempted the actual disabled `Execution Locked` control.
- Proved pristine source and faulted copy hashes remain unchanged after load,
  no activation or dispatch occurs, and all model/lifecycle/queue state remains
  exact around the rejected activation action.
- Included `calibration.json` in each pristine baseline because the application
  initializes that legacy file when absent. This prevents an incidental load
  write and makes the no-post-launch-write claim strict.
- Kept production persistence/MVC, firmware, protocol, physical behavior,
  refill, Milestone 11A, and Milestone 13 unchanged.

## Frozen contracts

- source catalog canonical SHA-256:
  `0a945b0394be7641f366dda40187f1bbf0b760af341b4940f35fc4ffc1c84b8c`;
- registered matrix catalog SHA-256:
  `64fffe3723489cb812358be06f146c22fd72cf36c4fc61292d5820154a06656c`;
- source JSON file SHA-256:
  `78e029fca7cdf29fa8fcb6fbab5d682692945bc7c8eda48a69d31430c47b2122`;
- fault-builder source SHA-256:
  `7161192f966007a1e5042867f794b3cc4d786feb734c4a80ff08c90e25dd0b3e`.

The missing-`progress.json` production issue embeds the absolute case-owned
path and therefore differs between exact replays. Reports retain that complete
raw UI text. The typed oracle uses the independent portable literal
`progress.json is missing from the authoritative execution bundle.` only after
proving that the raw OS message names the exact faulted-copy path; no production
message is discarded or computed by the product algorithm.

## Executable evidence

The source-current fresh-child matrix passed 9/9:

`verification_reports/m12_slice4_matrix_final/authoritative_persistence_safeguards_v1/20260809T074951113030Z_22e3a800-2e1/aggregate.json`

Aggregate SHA-256:
`3db0c79349821b3fa49a65e2cb2e11011665ef4fb4d7252bfe30aa74fe3b4afa`.
Its exact replay passed 9/9 at
`verification_reports/m12_slice4_replay_final/authoritative_persistence_safeguards_v1/20260809T075025694461Z_4f38bbe3-2e1/aggregate.json`, SHA-256
`43e2a98cdad7f3407f55480e7a85388ed1e0447ad9d9967537d0c4925d074060`.

The three required Windows-visible cases and their replays passed and were
manually inspected. Direct/replay screenshots were byte-identical for:

- ambiguous pending intent:
  `36da2f316ce9ee18c74c62cd3ee99e7201eb8314bbb2da80a7ad11d2536609a7`;
- missing calibration link:
  `171f3c67ac7aec08b477aff11827748f8f8fc2f0cf899b6e26d69491baf072e3`.

The missing-progress screenshots differ only in their deliberately unique
contained absolute roots; direct SHA-256 is
`fff40483ce9204d65f4f0d7b90255e4f19d966ea2193752617da56e93e52a67c`
and replay SHA-256 is
`87fd66abf5a6c40862c65761f80afb35ba3924efa99fb0c34c3a71b546bf1a8c`.
Both visibly show the exact current run's missing `progress.json` path and the
disabled `Execution Locked` control.

## Focused validation

- catalog/builder/matrix/action/composition/manifest and adjacent production
  persistence unit selection: `281 passed in 9.51s`;
- real-Qt fresh-process system family with `--run-sil-lifecycle`:
  `9 passed in 30.99s`;
- matrix direct and replay: `9/9` pass each;
- visible direct and replay: `6/6` pass;
- `git diff --check`: pass (line-ending notices only).

New unit and system test SHA-256 values are
`b31315226caab00fe9d304afb658807dac4198af8f750e8f85cc280a5aade7d1`
and `5eb3b139590c972f2448ddc39a2624c068f4290552fdcd196b21518f8f38c37f`.

## Risks and rollback

Path escape, accidental source mutation, multiple faults, syntax-only failure,
and post-launch repair/write are controlled by resolved-root containment,
pre-existing-root refusal, no symlinks, exact inventory deltas, parse-after-
write, source/faulted after-load hashes, and the shared oracle. All copies and
manifests are retained under the current SIL session root for diagnosis.

Rollback removes the catalog, builder, optional prelaunch callback, persistence
journey/driver/matrix registration, tests, and slice docs. It does not remove
retained reports automatically and cannot touch user experiments or historical
evidence.

## Deferred

Final aggregate-to-capability registration, all-catalog source-current replay
and visible qualification, Milestone 11A compatibility, the full Python suite,
final documentation, and the one Milestone 12 commit remain assigned to Slice
12.5. Milestone 13 remains unstarted.
