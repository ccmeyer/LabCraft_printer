# Calibration Recording Store Migration: Milestone 1 Completion Record

Status: Complete

Prepared: 2026-08-14

## Outcome

Milestone 1 now has a hardware-isolated storage-contract SIL implementation
around the unchanged current `calibration.json` and `calibration_recordings`
writers. The host lifecycle and frozen 8-head x 25-run workload pass. The
qualified Raspberry Pi 5 workload also passes, and its clean report set and
tracked candidate baseline are frozen.

No file under `FreeRTOS-interface/` or `firmware/` was modified. No production
or historical experiment was read, rewritten, moved, or deleted. All scenario
data was created beneath temporary/ignored SIL roots.

## Implemented evidence

- Seven reviewed `labcraft.calibration_storage_contract_fixture` v1 fixture
  families: 16 processes, 14 completed, one stopped, one failed, and 17
  ordered updates.
- One approximately 350 KiB five-update online-stream payload, deterministic
  semantic hashes, and frozen legacy source coordinates.
- Simulation-only `ScriptedCalibrationProcess`, `StorageContractRunner`,
  artifact correlation, recorder drain, capture decoding, and writer latency
  collection. Construction fails outside the canonical `SimulatedMachine`
  runtime with hardware access disabled.
- Exact parity between fixture projections, legacy steps, and recorder
  `analysis.jsonl`; multi-head/stock isolation; terminal lifecycle cleanup;
  0/2/4 capture-policy proxies; and recorder-disabled behavior.
- Fresh MVC composition, authoritative experiment reload, stable legacy-source
  row selection, preview/application through the real UI and Controller, and
  verification of the applied source run/phase/timestamp/fingerprint.
- Frozen `calibration_storage_legacy_baseline_8x25_v1`: 200 process runs, 232
  updates, 200 recording directories, zero workload pixels, one expected
  manager-created empty legacy session envelope, and a separate two-frame
  recorder-drain probe.
- A fail-closed candidate-baseline tool that retains environment/source,
  fixture/workload hashes, exact counts, storage latency distributions,
  first/last quartiles, reload/history latency, RSS, artifact growth, raw
  report hashes, and explicit Milestone 2 deferred fields.
- A storage-specific reference-only report-set profile, so Pi evidence does
  not invent or require print-array responsiveness metrics.
- Newline-stable frozen text hashing for cross-platform SIL source audits;
  existing reviewed hash identities remain unchanged on Windows and Linux.

## Fixture file hashes

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
| `calibration_storage_contract_legacy_baseline_8x25_v1.json` | `0a2b57a0ea07bbe437ee3037c9ca2a9331a38dbdcae5fbb908e8390d8f592621` |

The catalog semantic hash is
`15e6bd78f585310c6e548409c5ff85a2c43f6786d3f8d323d154e0e3ae9e2be5`.
The frozen performance workload semantic hash produced by the journey is
`f99bdfc4150c98d0d2a37fd43d3cf4353ca1b20240152cfb264c89c9800ff341`.

## Validation record

Passed during implementation:

```text
209 passed: final storage, baseline, report-set, source-audit, manifest, selection, and Pi orchestration contracts
1 passed in 8.74s: final calibration storage lifecycle SIL
1 passed in 129.19s: final calibration storage 8x25 stress SIL
manifest validation: pass
```

Retained host reports:

| Scenario | Report | SHA-256 | Result |
| --- | --- | --- | --- |
| Lifecycle | `verification_reports/calibration_storage_m1_host/calibration_storage_contract_v1/20260815T025217162185Z_composed/report.json` | `692021f5ecad69d52bab893dafaf03ad6f08dacf3ed41541d6e1ef0f921b7477` | pass |
| Stress | `verification_reports/calibration_storage_m1_host/calibration_storage_legacy_baseline_8x25_v1/20260815T025233123271Z_composed/report.json` | `c9b0f4ea910f67cd4c4d54badc7ae30bf12da8044b4f1b934ead41b2a980ca3c` | pass |

The final Windows stress report is diagnostic: 125,292.6 ms total, 432
legacy rewrites, 207.54 ms rewrite p95, 1.01 ms recorder-append p95, 49.23
ms first-quartile update p95, 220.63 ms last-quartile update p95, 40.77 ms
fresh reload, 390,844,416 bytes peak RSS, 8,079,756 bytes of legacy JSON,
and 27,138,942 total scenario bytes. These values characterize the host and
are not target-Pi gates.

Final full Python suite:

```text
4705 passed, 137 skipped, 483 warnings in 222.65s
```

## Pi qualification

The final qualification used the following identity:

| Field | Qualified value |
| --- | --- |
| Source commit | `ddea246c2aa89f492abf9cc8d4755e92af92d9f0` (clean) |
| Target | Raspberry Pi 5 Model B Rev 1.0, aarch64 |
| OS | Linux `6.12.20+rpt-rpi-2712` |
| Storage | NVMe, ext4, `/dev/nvme0n1p2` |
| Runtime | Python 3.11.2, PySide6 6.7.1, Qt 6.7.1, offscreen |
| Isolation | Bubblewrap private `/dev`, read-only root, network unshared |
| Report set | `verification_reports/virtual_workflows/pi-sil/calibration_storage_legacy_baseline_8x25_v1/20260815T043836790058Z_ddea246c2aa8_report_set/report_set.json` |
| Report-set SHA-256 | `ab48b7615547915043c0cab9e4a699f7c63fd2545af6483c62ce408441d41e8d` |
| Retrieved archive SHA-256 | `a2a83995538a00ecf28276b3438d36a271b6c6cfcdeed4291a57c126bc1d964e` |
| Tracked baseline | `tests/performance/baselines/calibration_storage_legacy_pi5_v1.json` |
| Baseline SHA-256 | `236b15ee5addcaec26621072fb6cbd8672337a098bf77f93e948a5805cae86b5` |

Raw evidence:

| Role | Run ID | Report SHA-256 |
| --- | --- | --- |
| Warmup | `7a117a6b-4592-40f9-853e-81149b6613ef` | `71f8a62adac160747dbce826fdd0a3bf8d0b6e36a60c5805002afae56a4fa0ca` |
| Measured | `d821ebd9-7494-42d9-9fa2-191e64c3af75` | `7e762f63393bf5220779707db80d7f7a79f4b46995e59cbad9f666b0f74dba55` |
| Measured | `dc0f517a-4b3c-49d4-a354-3a40809049e0` | `135e7d917ccbb62f3f520a2f2cb5e4b366eb7061ce9b7026b0bc5e60c768a6b1` |
| Measured | `8037cc68-d245-4729-8751-29cc21a005aa` | `2b9409c544841455316a8aa2578b7e14f92a74b3784635509de1593afb8add7c` |

All measured reports contain 200 processes, 232 updates, 201 legacy run
envelopes, 200 recording directories, zero workload captures, and a two-frame
drain probe. Measured durations were 232.67, 233.96, and 234.14 seconds.

| Metric | Measured p95 values | Candidate upper limit |
| --- | --- | --- |
| Legacy rewrite latency | 396.67, 396.48, 397.33 ms | 496.50 ms |
| Recorder append latency | 2.748, 2.831, 2.827 ms | 3.831 ms |
| First-quartile update latency | 90.72, 91.00, 91.00 ms | 113.75 ms |
| Last-quartile update latency | 430.88, 430.52, 430.20 ms | 538.51 ms |
| Fresh reload latency | 253.97, 279.30, 75.61 ms | 431.24 ms |
| Peak RSS | 473,677,824; 522,289,152; 571,179,008 bytes | 862,846,976 bytes |
| RSS growth | 18,153,472; 14,942,208; 15,646,720 bytes | 22,380,544 bytes |
| `calibration.json` size | 7,840,095 bytes each | 9,800,118.75 bytes |
| Total scenario bytes | 26,367,422 bytes each | 32,959,277.5 bytes |

The Windows SSH client reset after the clean warmup, but the remote isolated
collector continued to terminal completion. The resulting report set was
bundled with its original proof and trace, retrieved, and independently
validated against the remote SHA-256 sidecar. Pre-existing untracked Pi HIL
helpers were temporarily staged outside the repository for the clean-source
measurement, then restored with matching hashes and sizes.

## Risks and rollback

The observed Windows stress workload confirms the expected growing whole-file
rewrite cost; its timing is diagnostic and cannot substitute for target-Pi
qualification. Current readers also retain the documented limitation that an
error after a partial application-eligible legacy update is not authoritatively
terminal-filtered; that behavior belongs to later store/reader milestones.

Rollback removes the SIL modules, fixtures, tests, registry/manifest entries,
Pi allowlist entry, baseline tooling/artifact, and these documentation updates.
No persisted-data rollback, firmware action, protocol recovery, or hardware
recovery is required.
