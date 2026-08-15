# Calibration Recording Store Migration: Milestone 4B Completion Record

Status: Qualification pending

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

Host validation completed so far:

```text
Focused secondary-consumer, reader, memory, audit, export, manifest, baseline,
and Pi-lane tests: 221 passed
Secondary-reader lifecycle SIL: pass
Secondary-reader 8x25 stress SIL: pass (200 processes / 232 updates)
```

## Qualification evidence

The Raspberry Pi report set, tracked candidate baseline, final full-suite
counts, source commit, and local/origin/Pi synchronization hashes will be
filled after the clean-commit measured qualification.

## Risks and rollback

Legacy whole-file rewrites remain and continue to dominate the long stress
workload. Canonical memory aggregation validates terminal bundles and is
therefore intentionally more expensive than compact history materialization.
Image-analysis execution and historical conversion remain deferred.

Operational rollback sets
`LABCRAFT_CALIBRATION_SECONDARY_READER=legacy` and restarts the application.
Canonical writes, the Milestone 4A primary reader, and legacy dual-writes
continue. The broader writer rollback remains
`LABCRAFT_CALIBRATION_STORE_AUTHORITATIVE=0`. Code rollback uses a revert
commit deployed through origin and Pi fast-forward-only synchronization; no
persisted artifacts are deleted or rewritten.
