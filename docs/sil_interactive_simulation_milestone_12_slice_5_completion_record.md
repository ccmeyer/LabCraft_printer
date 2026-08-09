# Milestone 12 Slice 12.5 Completion Record

Status: complete

Date: 2026-08-09

Commit boundary: cumulative Milestone 12 worktree; one final milestone commit
is required after this record is reviewed.

## Delivered

- Registered the three safeguard matrix contracts in the tracked capability
  manifest with exact ordered case IDs, catalog hashes, shared assertion, and
  focused system-test nodes.
- Added the matrix aggregate-to-manifest evidence join and validation without
  changing existing scenario/suite capability claims.
- Preserved all 34 compact case contracts and the shared
  `safeguard_rejection_no_mutation_no_dispatch` oracle.
- Restored the execution-preflight report payload to its correct function,
  made `tests/system` an explicit package so the full suite collects unit and
  system modules independently, and scoped Upload Design to the editor
  safeguard action family so the pre-existing smoke action contract remains
  exact.
- Ran complete direct/replay, visible, optimizer-360, lifecycle,
  host-regression, focused, system, and default-suite qualification.
- Updated the README and operator runbook. Firmware, protocol, production MVC,
  physical behavior, refill, Milestone 11/11A history, and Milestone 13 were
  not changed.

## Frozen source and catalogs

- executable/verification source-tree identity:
  `febdea578d1accd35793fb24736e9ff932bc6479d10cdf5bff1c231399528b9f`
  (917 files);
- tracked capability manifest:
  `0b79d8a99f5353c8017588cfe42036fc65ca9eec930f729a54209b32a8fe5bb0`;
- registered matrix catalog hashes:
  - editor: `7b75e9776402641a1b8b00527b394de8296f5ed29875af52c05970de328d7da5`;
  - preflight: `0a4169cfc5f844e25cc02c1af74ab9b26b01d82a9703470b85adfc0b0ed763c2`;
  - persistence: `64fffe3723489cb812358be06f146c22fd72cf36c4fc61292d5820154a06656c`;
- source JSON hashes:
  - editor: `c00c5e1b809156762f1ca42cc8b9e29461adfaa63295e0cf98c031574feea3a2`;
  - preflight: `f35a6aa52104cfe182d2f2853f699993406bbe1af4a5eee4ea70cc5dcbcb94fd`;
  - persistence: `78e029fca7cdf29fa8fcb6fbab5d682692945bc7c8eda48a69d31430c47b2122`.

Documentation changes are excluded by the source-tree identity contract; no
executable or verification input changed after the final fingerprint was
captured.

## Definitive matrix evidence

All complete aggregates are manifest-registered and use manifest SHA-256
`0b79d8a99f5353c8017588cfe42036fc65ca9eec930f729a54209b32a8fe5bb0`.

| Matrix | Result | Aggregate | SHA-256 |
| --- | --- | --- | --- |
| editor direct | 8/8 | `verification_reports/m12_final4_editor_direct/editor_safeguards_v1/20260809T090818620117Z_eed40b1b-16c/aggregate.json` | `1068468b66806dbc1024437c41b7ba2413dfe95d194d676dd5b1305183c5670a` |
| editor replay | 8/8 | `verification_reports/m12_final4_editor_replay/editor_safeguards_v1/20260809T091015182796Z_07d860fd-35a/aggregate.json` | `70351f39bed318c9c2a24ab379239303a719afcdd1f30f7b311892c505cecefc` |
| preflight direct | 17/17 | `verification_reports/m12_final4_preflight_direct/execution_preflight_safeguards_v1/20260809T090847802116Z_645a848f-607/aggregate.json` | `2792ab39235ef09619efd5294c925179a08a07f8618f68bfe730f2ab010fa135` |
| preflight replay | 17/17 | `verification_reports/m12_final4_preflight_replay/execution_preflight_safeguards_v1/20260809T091044380612Z_f0054ff4-f5d/aggregate.json` | `8a4ec610de034e9a46a5f0734f75bcfa7a110348cb5c2156bfb1dce6802e2008` |
| persistence direct | 9/9 | `verification_reports/m12_final4_persistence_direct/authoritative_persistence_safeguards_v1/20260809T090943730976Z_e43b826b-de9/aggregate.json` | `fd51b560f405d2909ee44498a245d2151e6bd3051fb0337cdf85881134ff67a9` |
| persistence replay | 9/9 | `verification_reports/m12_final4_persistence_replay/authoritative_persistence_safeguards_v1/20260809T091140333106Z_b6071079-d7c/aggregate.json` | `935d8c98dc7a3f643806a20713ddd03d2b956371bb2eb0bff3d7fb68b90b1c2f` |

The 68 direct/replay child reports all pass. Their shared oracle audit found
zero failed checks: literal outcome/UI, persistence, model, lifecycle, queue,
dispatch, runtime state, workflow state, and no-activation evidence are exact.
The 18 persistence child reports each retain exactly one prelaunch mutation to
the declared path, distinct original/mutated hashes, equal inventories at all
other paths, and an unmodified pristine source.

## Visible qualification

All ten required visible cases and their ten exact replays pass, retaining 25
PNG artifacts in each root:

- `verification_reports/m12_final4_visible_direct/`;
- `verification_reports/m12_final4_visible_replay/`.

All ten final direct rejection/locked-state screenshots were manually
inspected. Direct/replay rejection screenshots are byte-identical except the
incomplete-bundle case, whose exact banner contains its deliberately unique
absolute fault root.

| Case | Direct SHA-256 | Replay SHA-256 |
| --- | --- | --- |
| printed exceeds final | `60cdf94f1b905b0a09264ae66a40130c1a246d763922f92ebd09e4a4985b96e0` | same |
| capacity plus one | `f036d1b87b52ef52446e0070c9b0c1614b5d08227bb82d687580f692fd0f0714` | same |
| excluded uploaded well | `41dbb41e8a1f7c11af994027480d6ba0f7b015333aa80834d9f937b7a18ba520` | same |
| missing applied calibration | `93b32655a3866cf5e4892c71d1e16e329e0adc5373c30603803811bb4ba30b38` | same |
| wrong printer-head binding | `579629e08d8806af6d0f064c625bd7b835c54ca5b6079882cd791ba1b3eff3b8` | same |
| progressed recalibration | `f55ad8ebc228debf946a45728aa31e3725c1d95e8613c936325299d19c2815b7` | same |
| invalid-boundary head exchange | `a127cbdb680bb84404e03d8ef59f600d0b77f1ac8b32c378493c5893309ebb0a` | same |
| ambiguous pending intent | `98ce74c89e3084fa69348b315755bbd5a547b45ac1381895b3f660626d8dc118` | same |
| missing calibration link | `cd0f93451d146cd4e2609ae1bc41e005a28727081d553c63ccc7ccd3115b2aee` | same |
| incomplete bundle | `25c21dd95fc746ae4f52bb5d0a21a201f941a63587409b04f7c77b8ef0e73508` | `3ba3c70bf99564c768f3ec79bb99f83594881e2b46cd21f46898febc989cda49` |

## Immutable positive control and compatibility suites

Optimizer-360 direct and replay both pass from the final fingerprint with
three application sessions, five stocks, 1,800 intents, and 46,208 drops:

- `verification_reports/m12_final4_optimizer360_direct/`;
- `verification_reports/m12_final4_optimizer360_replay/`.

The immutable hashes remain fixture
`d7f4de4aafeaf4a66751872d017d89393c263d48b5ffefa1b0e1690efaa10783`,
case `f238d4d90b822fdf52d4170b1f6fc1871b3d73f56df3aad543637f3e5d4078d8`,
requested multiset `5acfa8580c581231275e2b6f17ec757d71df5dcc4696196e1c0f9b2176ee7afd`,
achieved multiset `418cf4a50cc0015c52b9b093a5df9096df98930dc0f58f42aa37c30830fe64f0`,
assignment `5f84bfd4cd7c2c0d4b289b6797c50feeab9739a65d56ac2fc3949da030ab3ed2`,
and count oracle `3f86a60425d2c0d6abf0839d9f0fca16a41a6e398125053dd849d2e9b397458f`.

Compatibility aggregates:

- lifecycle direct 9/9, SHA-256
  `d69ad6bbc452464d3d0c4f927753b8d829a64225a10e8b7f766f57226f62ddc9`;
- lifecycle replay 9/9, SHA-256
  `a1aa60d0ebfb10f6e2de99889b1bd4d5d94e0f6544dd2ea77af8bf8533207f7d`;
- host regression direct 1/1, SHA-256
  `71c45a36eebf8beda5923cf18974dc03727ae26a78f7eb430bb198a8e32982b0`;
- host regression replay 1/1, SHA-256
  `1aa7b6474065739a5c8a318ed708ad8ab96964ce280df55df55a7c3a5bd46f89`.

The complete `host_stress` aggregate is not a Milestone 12 gate. Its known
preexisting 384x10 pulse-width fixture/staging mismatch remains separate from
the passing direct safeguards and optimizer-360 compatibility control.

## Automated validation

- focused product-adjacent and safeguard workflow selection: `611 passed in
  19.12s`;
- real-Qt safeguard system families with `--run-sil-lifecycle`: `34 passed in
  117.20s`;
- exact required default suite, invoked with a 900000 ms timeout:
  `4269 passed, 127 skipped in 246.83s`;
- analysis-pipeline tests: not run because analysis-pipeline code was not
  affected;
- `git diff --check`: pass (line-ending notices only).

## Risks, rollback, and scope

The main residual risk is that these host-SIL checks prove application
fail-closed behavior, not firmware or physical-device safety. Dynamic absolute
paths are retained in raw missing-file UI evidence and independently mapped to
portable literal typed classifications. Historical failed/pre-fix evidence is
left intact and is not cited as final qualification.

Rollback removes the three catalogs, shared contracts, fault builder,
drivers/journeys/matrix registration, manifest join, tests, and Milestone 12
documentation as one commit. It does not delete retained evidence or any user
experiment. No firmware, device protocol, release metadata, or Milestone
11/11A artifact is part of rollback.

Milestone 13 remains out of scope and unstarted. It cannot begin unless this
deterministic Milestones 9-12 baseline, including the immutable Milestone 11A
positive control, remains stable.
