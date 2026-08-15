# Calibration Recording Store Migration: Milestone 1 Completion Record

Status: Host implementation validated; Pi qualification pending

Prepared: 2026-08-14

## Outcome

Milestone 1 now has a hardware-isolated storage-contract SIL implementation
around the unchanged current `calibration.json` and `calibration_recordings`
writers. The host lifecycle and frozen 8-head x 25-run workload pass. This
record remains open because no qualified Pi host was supplied, so the required
measured Pi report set and tracked candidate baseline do not yet exist.

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
14 passed: fixture, sanitizer, scripted-process, and baseline unit coverage
1 passed: calibration storage lifecycle SIL
1 passed in 127.16s: calibration storage 8x25 stress SIL
162 passed: combined storage, registry, manifest, action, and Pi orchestration contracts
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
4702 passed, 137 skipped, 483 warnings in 221.42s
```

## Pending Pi qualification

Run from a clean implementation commit:

```powershell
.\tools\run_pi_virtual_workflow.ps1 `
  -PiHost <qualified-pi-host> `
  -Scenario calibration_storage_legacy_baseline_8x25_v1 `
  -HostLabel pi5-calibration-storage-legacy-v1 `
  -WarmupRuns 1 `
  -MeasuredRuns 3 `
  -SpeedMultiplier 1000 `
  -TimeoutSeconds 1800
```

Then freeze the candidate without overwriting existing evidence:

```powershell
.\env\Scripts\python.exe -m tools.sil.calibration_storage_baseline `
  --report-set <retrieved-report_set.json> `
  --output tests\performance\baselines\calibration_storage_legacy_pi5_v1.json
```

Milestone 1 becomes complete only after this record contains the source commit,
Pi/storage/Python/Qt identity, raw report and report-set hashes, tracked
baseline hash, qualified result, and final full-suite result.

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
