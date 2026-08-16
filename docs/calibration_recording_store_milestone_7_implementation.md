# Calibration recording store Milestone 7 implementation record

Date: 2026-08-15

Status: implementation complete; operational proving pending.

Milestone 7 removes the legacy calibration writer from the production path.
Canonical run creation, update append, terminal result, metadata, and compact
index commits remain mandatory and fail closed. Historical `calibration.json`
documents remain available through the typed legacy fallback and are never
rewritten by calibration lifecycle operations.

The retained `labcraft.calibration_storage.policy` v1 design field is an inert
compatibility field. The application always reports canonical authority. Unsafe
obsolete environment values (`LABCRAFT_CALIBRATION_LEGACY_WRITER=1`, authority
rollback, or legacy primary/secondary reader selections) block a new calibration
until removed and the application is restarted.

The read-only proving CLI provides three commands: `init`, `collect`, and
`evaluate`. Collection requires explicit experiment directories, validates only
indexed terminal bundles, records before/after source hashes, emits no raw head or
stock identities, refuses output overwrite, and prints flushed structured progress.
Evaluation requires 14 days, 20 completed calibration results, three printer
heads, two passing compact Pi report sets, unchanged sources, zero integrity or
storage errors, and no unresolved issue-ledger entries.

Automated qualification is intentionally bounded:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_calibration_storage_proving.py `
  tests\test_calibration_legacy_writer_policy.py `
  tests\test_calibration_recording_reader.py `
  tests\test_calibration_storage_scripted_process.py

.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_calibration_storage_new_store_only_contract_lifecycle.py

.\env\Scripts\python.exe -m pytest -q
```

The lifecycle is 16 processes and normally takes about 15 seconds on Windows.
The earlier 200-process/232-update stress workload is deliberately excluded. One
compact Pi pass uses 0 warmups and 1 measured run. Real calibration collection and
a second later Pi report set provide the remaining operational evidence.

Host validation completed on 2026-08-15:

- focused writer, reader, proving, memory, UI, and lifecycle coverage passed;
- compact composed lifecycle passed in 13.32 seconds;
- Pi orchestration contract passed;
- full Python suite passed: 4,809 passed, 147 skipped in 328.24 seconds.

No firmware, device protocol, camera, image-analysis, motion, pressure, dispense,
historical experiment, release-candidate, tag, or offline-bundle change is part of
this implementation.

Rollback requires deploying the last previously qualified commit/release that
still contains the writer. It must not delete or rewrite canonical or historical
artifacts. Operational proving is not complete until the evaluator returns
`status: pass` from real collected evidence.
