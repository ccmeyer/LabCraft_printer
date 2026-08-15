# Calibration Recording Store Migration: Milestone 3 Completion Record

Status: Complete

Prepared: 2026-08-15

## Outcome

Milestone 3 makes the canonical calibration recording store authoritative for
new process runs while retaining the existing `calibration.json` dual-write
and legacy readers. Structured persistence is always active by default. The
former recording checkbox is now a session-scoped capture-retention selector
with `Structured only`, `Key evidence`, and `Full` choices; every application
session starts at `Key evidence`.

Canonical run creation precedes process startup, canonical update append and
fsync precede each legacy step, and terminal result/index/meta commits precede
manager completion and queue advance. New authority-marked legacy rows are
blocked from load, recheck, preview, and application unless their canonical
reference, update hash chain, parity, terminal result, and committed index
event all validate. Historical legacy-only rows remain usable.

The host storage contract, failure injection, fresh-reload lifecycle, and
frozen 8-head x 25-run workload pass. The qualified Raspberry Pi 5 comparison
passes all Milestone 2 timing and RSS limits, and a tracked authoritative
candidate baseline is frozen. No firmware, protocol, image-analysis,
physical-camera, motion, pressure, dispense, balance, or GPIO behavior
changed. No historical or production experiment was read or modified.

## Implemented contract

- `CaptureRetentionPolicy` is ordered as `structured_only`, `key_evidence`,
  and `full`. Manager policy changes are rejected while a process or
  capture-owned queue is active. The compatibility record-mode accessors
  control pixels only in authoritative mode.
- Every concrete production calibration process has an explicit result kind,
  terminal adapter, and minimum capture policy. Undeclared processes cannot
  start. Dataset, stream-gravimetric, and refuel dataset acquisition require
  `Full`; lower selections are rejected rather than silently elevated.
- Every capture request has a stable ID, retention class, requested/effective
  policy, dimensions, outcome, and terminal counters. Omitted captures have no
  path and enqueue no image copy. Optional failures remain warnings; missing,
  failed, or pending required full evidence fails terminal completion.
- Canonical update payloads receive a
  `labcraft.calibration_recording.legacy_ref` v1 reference before hashing. The
  exact canonical payload is returned for the legacy write, so dual-write
  semantic parity does not depend on reconstructing the row.
- Canonical run/update/result/index/meta failures use one fail-closed manager
  path. They stop the process, prevent the affected legacy step or successful
  completion, release runtime resources, clear queued work, and retain a
  best-effort `storage_error` terminal state.
- The rollback flag `LABCRAFT_CALIBRATION_STORE_AUTHORITATIVE=0`, followed by
  application restart, restores the Milestone 2 legacy-authoritative checkbox
  and recorder-toggle behavior without deleting additive canonical artifacts.

## Schemas and fixture identities

Canonical schemas remain:

| Artifact | Schema |
| --- | --- |
| Update | `labcraft.calibration_recording.update` v1 |
| Result | `labcraft.calibration_recording.result` v1 |
| Run metadata | `labcraft.calibration_recording.run_meta` v2 |
| Index event | `labcraft.calibration_recording.index_event` v1 |
| Legacy canonical reference | `labcraft.calibration_recording.legacy_ref` v1 |

The functional catalog remains
`labcraft.calibration_storage_contract_catalog` v1 and its members remain
`labcraft.calibration_storage_contract_fixture` v1. The reviewed fixture
SHA-256 identities are:

| Fixture | SHA-256 |
| --- | --- |
| `catalog_v1.json` | `8b93d6e864bd02cba3c77b879b67a0b1566442661e1b9b3b0e210d78dba48dd1` |
| `capture_policy_v1.json` | `c9fc5a76adba9aba9a9a6145810fc3288ea03e6a18ccc00d94a7ea01266c5745` |
| `droplet_sequence_nominal_v1.json` | `7aac8b0e468a9f4cfc73c28682fb889d686aa6e9daabfc38dfd9829574c04db1` |
| `legacy_parity_v1.json` | `21f76e55358e2a6842f65d7b8157890117a2744c3e186b8fe66b520006164909` |
| `multi_head_isolation_v1.json` | `78bdbdba7a31149efdd37d1f55e289842303eeb4c4001b6b531e1315cb4ce261` |
| `non_calibration_terminal_v1.json` | `0020f4ec728c3dff7201c094d8d03f34501e6b724dc5aec0c97d766bc7c190a7` |
| `online_stream_large_multi_update_v1.json` | `7e54c477738dfd3eebf55ee4ccbb64af40a73e71e6aa35ce08a9ee6c322ad2cf` |
| `stopped_and_error_v1.json` | `de54e432798bece0fed6b37aa82f9b468b92b7430bef09660987df6d8dfb2655` |

The frozen stress fixture SHA-256 is
`0a2b57a0ea07bbe437ee3037c9ca2a9331a38dbdcae5fbb908e8390d8f592621`;
its normalized workload hash is
`f99bdfc4150c98d0d2a37fd43d3cf4353ca1b20240152cfb264c89c9800ff341`.
Both match the Milestone 2 comparison source.

## SIL and automated evidence

The registered `calibration_storage_authoritative_contract_v1` journey proves
16 process lifecycles, 17 ordered updates, canonical/legacy/diagnostic parity,
16 terminal results and index events, multi-head isolation, fresh MVC reload,
authority-aware UI selection/application, and deterministic 0/2/4 capture
retention. It also proves stopped/error exclusion and zero physical interface
activity.

The registered `calibration_storage_authoritative_8x25_v1` workload proves,
per run:

| Evidence | Exact value |
| --- | ---: |
| Process runs | 200 |
| Legacy updates | 232 |
| Canonical updates | 232 |
| Canonical results | 200 |
| Index events | 200 |
| Diagnostic recording directories | 200 |
| Workload captures | 0 |
| Separate key-evidence drain probe | 2 frames |
| Integrity failures | 0 |

Failure coverage includes mandatory run creation, update append/parity,
result/index/meta finalization, required capture omission/failure/drain, queue
suppression, invalid authority references, incomplete/stopped/error results,
and rollback-mode compatibility.

Final host validation:

```text
62 passed in 7.56s: focused store, failure, adapter, policy, scripted-process, baseline, and Pi-lane contracts
1 passed in 9.24s: authoritative lifecycle SIL
1 passed in 133.87s: authoritative 8x25 stress SIL
4754 passed, 141 skipped, 533 warnings in 228.78s: final full Python suite
```

The warnings are existing Qt deprecation notices. Firmware checks were not
run because nothing under `firmware/` changed.

## Pi qualification

| Field | Qualified value |
| --- | --- |
| Source commit | `430123e0312d308a5ee8fb4be87b869d9aad6f27` (clean) |
| Target | Raspberry Pi 5 Model B Rev 1.0, aarch64 |
| OS | Linux `6.12.20+rpt-rpi-2712` |
| Storage | NVMe, ext4, `/dev/nvme0n1p2` bind-mounted report root |
| Runtime | Python 3.11.2, PySide6 6.7.1, Qt 6.7.1, offscreen |
| Isolation | Bubblewrap private `/dev`, read-only root, network unshared |
| Report set | `verification_reports/virtual_workflows/pi-sil/calibration_storage_authoritative_8x25_v1/20260815T085940685676Z_430123e0312d_report_set/report_set.json` |
| Report-set SHA-256 | `81cfccfd5854a622444c5867884e99f2cfd6497aaaf73519bb1c60ece45a7d7c` |
| Retrieved archive SHA-256 | `31d896881d6aa6a3c99fe851cba9f5976e1103e1ff0bf90b5795e77891a34582` |
| Hardware-proof SHA-256 | `f9d5b3a8fb33c036d319cc4e84bacbebcf7284a969200775f3e0b28c61d08dad` |
| Shadow baseline SHA-256 | `6557555ddf84e3e56f97f39510039d4894a1ce20c4b6b48670e102ee50b83108` |
| Tracked authoritative baseline | `tests/performance/baselines/calibration_storage_authoritative_pi5_v1.json` |
| Authoritative baseline SHA-256 | `379dc373e2684f3743c0fee21b7cc28cb046f777e5f0cc30b2b06187d2efaf40` |

Raw evidence:

| Role | Run ID | Report SHA-256 | Duration |
| --- | --- | --- | ---: |
| Warmup | `b6849cc9-3b96-428d-97dd-fe99be3df531` | `6a0af6873ffdf8897125b84adeda36badfa081bf198738399621ceb0c5e143d9` | 230.15 s |
| Measured | `a83c7b7d-475e-48f8-9f4b-75358e45b050` | `9b58e1e8751c40ec77d9b077a9a762b2e6955171d6bb0b07c6d954a0229044d0` | 235.10 s |
| Measured | `341a8602-b87c-48a0-94ab-456fce3ed238` | `b394992252fd78235d865f8a95888bd03f091101f3e35d8b8d5bdde10ff51a56` | 235.93 s |
| Measured | `97ca88bd-7baf-435c-8112-8e8c39b7f68c` | `254411d841191844206b0537376189d4e9f7d2dcd78087795b1783744ff09e8d` | 236.85 s |

All Milestone 2 comparisons passed:

| Metric | Measured values | Milestone 2 upper limit |
| --- | --- | ---: |
| Legacy rewrite p95 | 403.655, 403.216, 404.642 ms | 496.496 ms |
| Canonical update append p95 | 13.873, 14.001, 14.194 ms | 17.514 ms |
| Recorder append p95 | 2.789, 2.829, 2.857 ms | 3.831 ms |
| Result finalize p95 | 0.299, 0.296, 0.297 ms | 1.276 ms |
| Index append p95 | 3.486, 3.394, 3.428 ms | 4.416 ms |
| Update latency p95 | 405.586, 405.933, 405.793 ms | 498.602 ms |
| Process finalize p95 | 97.382, 93.609, 96.390 ms | 121.241 ms |
| First-quartile update p95 | 111.455, 112.942, 112.252 ms | 113.749 ms |
| Last-quartile update p95 | 461.649, 455.882, 456.873 ms | 538.508 ms |
| History load p95 | 2.400, 2.465, 2.412 ms | 4.474 ms |
| Fresh reload | 74.966, 75.551, 76.466 ms | 431.243 ms |
| Peak RSS | 477,200,384; 525,500,416; 574,668,800 B | 862,846,976 B |
| RSS growth | 17,465,344; 15,777,792; 15,908,864 B | 22,380,544 B |

The new authoritative candidate upper limits are 505.556 ms for legacy
rewrite p95, 17.694 ms for canonical append p95, 3.857 ms for recorder append
p95, 1.299 ms for result finalize p95, 4.486 ms for index append p95, and
121.479 ms for process finalize p95. The tracked baseline retains every
run-level distribution, first/last-quartile behavior, history/reload latency,
RSS observation, exact count, artifact inventory, fixture/workload identity,
and source/environment identity.

Each measured run retained 7,970,868 bytes of legacy `calibration.json` and
30,512,751 total scenario bytes. Relative to Milestone 2, the authority marker
and canonical references add 130,773 legacy bytes and 491,068 total bytes for
this frozen workload. Artifact growth remains measured rather than used as a
regression gate while both stores are intentionally retained.

## Source coordination, risks, and rollback

The validated implementation was committed locally as `430123e0`, pushed to
`origin/feature/motor_movement_LUT`, and fast-forwarded into the clean Pi
checkout before qualification. The Pi branch, tracked status, tree, and
CppUTest submodule were verified before and after that update. No reset,
force-push, firmware action, or direct file copy was used.

Milestone 3 still pays the legacy whole-file rewrite cost and stores both
representations. Legacy readers remain until Milestone 4, and full camera/image
analysis SIL remains deferred. The qualification establishes structured
persistence, capture-retention decisions, integrity validation, and Pi storage
performance only; it does not establish physical calibration quality.

Operational rollback is to set
`LABCRAFT_CALIBRATION_STORE_AUTHORITATIVE=0` and restart the application. This
restores legacy-authoritative completion and the former checkbox semantics but
does not delete canonical artifacts. If code rollback is required, create and
deploy a revert commit through the same origin/Pi fast-forward workflow. No
historical file, persisted canonical bundle, firmware, protocol, motion,
pressure, or hardware recovery is required.
