# Calibration Recording Store Migration: Milestone 4B Completion Record

Status: Complete

Prepared: 2026-08-15

## Outcome

Milestone 4B makes canonical session/result/update references the default for
calibration memory, audit evidence, exports, recording summaries, and the
offline replay/analysis consumers identified by the tracked inventory. Legacy
dual-writing and typed fallbacks remain active. No historical experiment,
firmware, device protocol, image-analysis, motion, pressure, dispense, camera,
serial, or GPIO behavior is changed.

`CalibrationSessionSnapshot` resolves exact compact-index entries and validates
each selected terminal bundle without scanning recording directories.
Calibration-memory schema v2 stores the session and result list; aggregation
succeeds with `calibration.json` absent and blocks corrupt or conflicting
canonical evidence. Schema-v1 summaries retain their legacy path.

Exports use manifest schema v2, include the compact index and complete run
bundles, validate and inventory canonical results, and retain legacy files
when present. Recording-summary CSVs add result identity, hash, outcome, index
state, and application eligibility. The shared offline update loader prefers
`updates.jsonl`, falls back to diagnostic `analysis.jsonl`, and rejects parity
conflicts. Existing image/dataset diagnostic streams remain unchanged.

## SIL and progress evidence

The registered `calibration_storage_secondary_reader_contract_v1` lifecycle
passes against the full 16-process fixture catalog, including a canonical
memory rebuild while the SIL-owned legacy file is temporarily unavailable,
complete dual-format export, fresh application reload, exact UI application,
and zero hardware-interface activity.

The registered `calibration_storage_secondary_reader_8x25_v1` stress journey
passes the frozen 8-head x 25-process workload with 200 process results, 232
updates, 200 index events, no workload pixels, and one separate two-frame
key-evidence probe. It measures memory rebuild, recording summary, offline
update load, and complete export alongside inherited writer/reader/RSS metrics.

Both journeys emit `labcraft.virtual_workflow.progress` v1 lines. The stress
workload reports setup; 0, 25, 50, ..., 200 processes; fresh reload; memory;
summary; and export. The Windows Pi orchestrator streams SSH output live while
retaining it for report-path parsing.

Host validation:

```text
Focused secondary-consumer, reader, memory, audit, export, manifest, baseline,
and Pi-lane tests: 221 passed
Secondary-reader lifecycle SIL: pass
Secondary-reader 8x25 stress SIL: pass (200 processes / 232 updates)
Final focused evidence/orchestration tests: 50 passed
Full Python suite: 4781 passed, 145 skipped, 533 warnings
```

The first Pi warm-up completed all 200 results, 232 updates, 200 index events,
the two-frame evidence probe, and every secondary-consumer measurement with
zero integrity failures. It was classified as failed only because the retained
legacy whole-file writer made the run take about 37 minutes, exhausting the
original 1,800-second scenario deadline before final artifact inspection. The
qualification contract now uses 3,600 seconds; this preserves the frozen
workload and records the observed legacy-write cost instead of truncating it.
At the operator's direction, Milestone 4B requires no warm-up and one measured
Pi pass. The baseline is explicitly single-sample candidate evidence;
the former three-measured-run requirement is reserved for an intentional
extended qualification rather than routine milestone completion.

## Qualification evidence

The shortened Pi gate uses zero warm-ups and one measured candidate. A locally
timed-out wrapper left a duplicate collector active during the retained pass;
both collectors completed equivalent clean first passes. The retained report
is therefore conservative concurrent-load evidence. Both exact collector
trees were stopped before further passes, and the duplicate report is not
blended into the baseline.

```text
Implementation commit: 50bd4279352bb30266a9d47994d304713a30ecaf
Source tree SHA-256: bb47f779e9df2a1bc5b521fa92bc57966329892008bae7934659e3c95398c5ba
Measured report SHA-256: a04d8b3f9896244b35bc01f5ddc7143653d5593679fee7e16f20275e49300722
Report-set SHA-256: f1fb7c3df5a1ead9e4c64d67ac475b3225126fe36755d886b50e7b3f156fa7dd
Hardware-proof SHA-256: 6685b48d68019f9fd734ea167e7e07912ad6e5da8844aeb4c1d9a2fb2e18bef0
Hardware-trace SHA-256: 8ef454d5aba6f5fd89a5bece461e9cbbcb1d7826003eac44f68bed81130d1a40
Milestone 4A baseline SHA-256: 8c7406ae013b9c53590841c65e01c5adb25902292a89cb34ee856d8eb3d956a6
Milestone 4B baseline SHA-256: fd2ebd7bb00de5e3c0929a91a70e2efdc3b3607a488792141af2b6f9854c0965
```

The measured pass took 2,607,367 ms and preserved exactly 200 process runs,
232 updates, 200 canonical results, 200 index events, zero workload captures,
and the separate two-frame key-evidence probe. Integrity failures were zero.
All Milestone 4A reader limits and applicable Milestone 3 writer, result,
index, and peak-RSS limits pass. Peak RSS was 448,905,216 bytes against the
862,846,976-byte inherited limit.

The expanded secondary-consumer scope establishes new single-sample candidate
limits: memory rebuild 4,198.72 ms, summary 1,605.83 ms, offline update load
1.662 ms, export 4,305.00 ms, peak RSS 561,131,520 bytes, and RSS growth
63,344,640 bytes. RSS growth is not compared with the narrower Milestone 4A
scope; it is preserved as a new bounded metric.

Qualification environment: Raspberry Pi 5 Model B Rev 1.0, aarch64 Linux
6.12.20+rpt-rpi-2712, NVMe/ext4, CPython 3.11.2, PySide/Qt 6.7.1, offscreen
Bubblewrap/private-device SIL. The fixture hash is
`0a2b57a0ea07bbe437ee3037c9ca2a9331a38dbdcae5fbb908e8390d8f592621`
and the workload hash is
`f99bdfc4150c98d0d2a37fd43d3cf4353ca1b20240152cfb264c89c9800ff341`.
No firmware or historical experiment file changed.

## Risks and rollback

Legacy whole-file rewrites remain and continue to dominate the long stress
workload. Canonical memory aggregation validates terminal bundles and is
therefore intentionally more expensive than compact history materialization.
Image-analysis execution and historical conversion remain deferred.
The Pi baseline is single-sample and its retained run overlapped a duplicate
collector; it is suitable for large-regression screening, not a statistical
stability claim. A future extended qualification may collect sequential
multi-run evidence when that confidence is specifically needed.

Operational rollback sets
`LABCRAFT_CALIBRATION_SECONDARY_READER=legacy` and restarts the application.
Canonical writes, the Milestone 4A primary reader, and legacy dual-writes
continue. The broader writer rollback remains
`LABCRAFT_CALIBRATION_STORE_AUTHORITATIVE=0`. Code rollback uses a revert
commit deployed through origin and Pi fast-forward-only synchronization; no
persisted artifacts are deleted or rewritten.
