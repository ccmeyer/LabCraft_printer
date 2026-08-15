# Calibration Recording Store Migration: Milestone 4A Completion Record

Status: Complete

Prepared: 2026-08-15

## Outcome

Milestone 4A makes the canonical compact index the default source for
current-session prerequisites, characterization history, persisted selection,
load/preview, recheck-context construction, and calibration application. The
legacy `calibration.json` writer remains active and its data remains available
through a typed compatibility adapter.

History materialization reads only the compact index and the in-memory legacy
compatibility document. It does not recursively scan recording directories or
open result bundles. Selection, preview, recheck, and application resolve the
selected row again and validate the exact index/result/update/meta chain before
using it. Authority-marked invalid data and parity conflicts fail closed.

The host reader contracts, explicit repair workflow, fresh-reload lifecycle,
and frozen 8-head x 25-run workload pass. A clean Raspberry Pi 5 qualification
passes every inherited Milestone 3 timing and RSS limit, and the tracked
primary-reader candidate baseline is frozen. No firmware, device protocol,
image-analysis, physical-camera, motion, pressure, dispense, serial, GPIO, or
historical experiment behavior was modified.

## Implemented contract

- `CalibrationRecordingReader` is Qt-free and reports `canonical_only`,
  `legacy_only`, `matching_dual`, `canonical_invalid_legacy_fallback`,
  `parity_conflict`, and `unavailable` states through immutable snapshots,
  resolved selections, issues, and diagnostics.
- Canonical terminal results and index events contain bounded
  `labcraft.calibration_recording.summary_projection` v1 rows. The canonical
  and legacy paths share the same pure row-materialization functions.
- The manager's completed-run cache is populated only after successful
  result/index/meta completion. Stopped, failed, incomplete, orphaned, or
  storage-error runs cannot satisfy current-session prerequisites.
- Every UI action re-resolves the selected row before use and validates path
  containment, identities and hashes, terminal state, application eligibility,
  head/stock identity, projection fingerprint, and dual-write parity.
- Recheck context is resolved from stable process-run/update identities and
  loads only the selected characterization bundle plus any required
  same-session trajectory bundle.
- `execution_calibrations.json` schema v2 stores nullable result, result-hash,
  process-run, and update identities while retaining legacy source fields and
  deterministic record IDs. Schema-v1 documents remain readable.
- Index repair is explicit and offline. Dry-run is the default; `--apply`
  refuses invalid or conflicting bundles, backs up an existing index by
  content hash, and atomically writes the rebuilt index without modifying run
  bundles or `calibration.json`.
- `LABCRAFT_CALIBRATION_PRIMARY_READER=legacy` provides reader rollback while
  canonical and legacy writes continue. Invalid preference values warn and
  default to canonical. `LABCRAFT_CALIBRATION_LEGACY_FALLBACK=0` disables only
  eligible historical unmarked fallback; it never makes corrupt authority data
  or a parity conflict applicable.

## SIL and automated evidence

The registered `calibration_storage_primary_reader_contract_v1` lifecycle
journey covers canonical-only, legacy-only, matching-dual, invalid-new, and
conflicting experiments across fresh application composition. It verifies
stable identities, multi-head/stock isolation, current-session prerequisites,
canonical preview/load/application values, exact recheck dispatch context,
post-selection mutation rejection, explicit repair dry-run/apply, fallback
flags, and zero physical-interface activity.

The registered `calibration_storage_primary_reader_8x25_v1` workload preserves
the Milestone 3 fixture and normalized workload identities:

| Evidence | Exact value |
| --- | ---: |
| Process runs | 200 |
| Legacy session envelopes | 201 |
| Legacy updates | 232 |
| Canonical updates | 232 |
| Canonical results | 200 |
| Canonical index events | 200 |
| Diagnostic recording directories | 200 |
| Workload captures | 0 |
| Separate key-evidence drain probe | 2 frames |
| Integrity failures | 0 |
| Reader fallback events | 0 |
| Reader conflict events | 0 |
| Routine recursive scans/result reads | 0 / 0 |

The frozen fixture SHA-256 is
`0a2b57a0ea07bbe437ee3037c9ca2a9331a38dbdcae5fbb908e8390d8f592621`;
the normalized workload hash is
`f99bdfc4150c98d0d2a37fd43d3cf4353ca1b20240152cfb264c89c9800ff341`.
Both match the Milestone 3 comparison source.

Final host validation:

```text
Focused reader, manager, adapter, repair, application-store, baseline, and Pi-lane tests: pass
Primary-reader lifecycle SIL: pass
Primary-reader 8x25 stress SIL: pass
4767 passed, 143 skipped, 533 warnings: full Python suite
```

The warnings are existing Qt deprecation notices. Firmware checks were not run
because nothing under `firmware/` changed.

## Raspberry Pi qualification

| Field | Qualified value |
| --- | --- |
| Source commit | `62d0e74ed1c4566237d8c75bf1c5399259b52d4f` (clean) |
| Target | Raspberry Pi 5 Model B Rev 1.0, aarch64 |
| OS | Linux `6.12.20+rpt-rpi-2712` |
| Storage | NVMe, ext4, `/dev/nvme0n1p2` bind-mounted report root |
| Runtime | Python 3.11.2, PySide6 6.7.1, Qt 6.7.1, offscreen |
| Isolation | Bubblewrap private `/dev`, read-only root, network unshared |
| Report set | `verification_reports/virtual_workflows/pi-sil/calibration_storage_primary_reader_8x25_v1/20260815T190804635008Z_62d0e74ed1c4_report_set/report_set.json` |
| Report-set SHA-256 | `614610ecd34d61dc7dc3c9f50e7cac59f70185e2ab607adbdc90b0b4ff02e0c7` |
| Hardware-proof SHA-256 | `a761e99004b3febdf270a0ee235e10d446dd90fab7b7f3d600e2128359610bcf` |
| Milestone 3 baseline SHA-256 | `379dc373e2684f3743c0fee21b7cc28cb046f777e5f0cc30b2b06187d2efaf40` |
| Tracked primary-reader baseline | `tests/performance/baselines/calibration_storage_primary_reader_pi5_v1.json` |
| Primary-reader baseline SHA-256 | `8c7406ae013b9c53590841c65e01c5adb25902292a89cb34ee856d8eb3d956a6` |

Raw report evidence:

| Role | Run ID | Report SHA-256 |
| --- | --- | --- |
| Warmup | `05ed4f6f-da85-4b95-9d5f-8381433924b7` | `6e0d9367e15be877d3215f7ea33d58c09eaffd0c85fa74edfff95627e13530df` |
| Measured | `372b3109-a563-4a06-acd0-e66fd79c262c` | `5399cba4a352a633623da37fb02dbc5a50c5dd0c2a025d525c03d662768a856f` |
| Measured | `336a9ed9-fbf9-493a-8507-482df96dafbd` | `9a6057107babe4ebd838fd65f6bbb724fb2ee0c894c719c7e443030239fd57c9` |
| Measured | `47590a3a-3240-47d9-8c9c-019d5fa5158f` | `7dfd59db1491646b065411af158eeeba3c3c08f5e827e4ae1a75e93f13caa991` |

Every inherited Milestone 3 comparison passes. Representative measured values
and limits are:

| Metric | Measured values | Milestone 3 upper limit |
| --- | --- | ---: |
| Legacy rewrite p95 | 402.758, 403.134, 403.070 ms | 505.556 ms |
| Canonical update append p95 | 13.726, 13.737, 13.941 ms | 17.694 ms |
| Update latency p95 | 405.235, 405.639, 404.265 ms | 507.381 ms |
| Process finalize p95 | 98.235, 97.712, 97.084 ms | 121.479 ms |
| History load p95 | 0.978, 0.978, 0.992 ms | 3.465 ms |
| Fresh reload | 69.728, 70.013, 70.232 ms | 95.354 ms |
| Peak RSS | 477,970,432; 526,352,384; 575,078,400 B | 862,846,976 B |
| RSS growth | 22,298,624; 20,791,296; 20,267,008 B | 22,380,544 B |

New reader candidate limits use the established maximum-plus-margin formula:

| Reader metric | Samples/run | Candidate upper limit |
| --- | ---: | ---: |
| Cold compact-index read | 1 | 368.871 ms |
| Cached summary materialization | 8 | 136.563 ms |
| Exact selected bundle validation | 8 | 806.556 ms |
| Recheck-context resolution | 8 | 2.860 ms |

Each measured run retained 7,970,868 bytes of legacy `calibration.json` and
22,590,097 total scenario bytes. The baseline retains all run-level latency
distributions, file-access counts, first/last-quartile behavior, RSS,
artifact inventory, fixture/workload identity, and environment identity.

## Source coordination, risks, and rollback

The implementation was developed and qualified through these reviewable
commits:

- `1da2bf0e` — canonical reader implementation and contracts;
- `ebf20f88` — isolated canonical recheck performance probe;
- `897994ad` — committed-history snapshot cache;
- `62d0e74e` — isolated fresh-reload timing measurement.

Each qualification source was committed locally, pushed to
`origin/feature/motor_movement_LUT`, and fast-forwarded into the clean Pi
checkout. The final evidence commit is deployed through the same workflow;
local, origin, and Pi branch/tree/submodule identities and clean tracked state
are verified after deployment. No reset, force-push, firmware action, or
direct source-file copy is used.

Milestone 4A still retains legacy dual-writes and the whole-file rewrite cost.
Secondary calibration consumers remain Milestone 4B, historical conversion
remains Milestone 5, and full camera/image-analysis SIL remains deferred. This
qualification establishes reader integrity and storage performance, not
physical calibration quality.

Operational rollback sets `LABCRAFT_CALIBRATION_PRIMARY_READER=legacy` and
restarts the application; canonical writes and legacy dual-writes continue.
`LABCRAFT_CALIBRATION_STORE_AUTHORITATIVE=0` remains the broader Milestone 3
rollback. If code rollback is required, create and deploy a revert commit
through the same origin/Pi fast-forward workflow. No historical file,
canonical bundle, firmware, protocol, motion, pressure, or hardware recovery
is required.
